"""Orchestration du processus métier, instrumentée — Labo 6.

Reprend le processus en 5 étapes (labo 4) sous contrôle de sécurité (labo 5), et
l'instrumente : chaque opération significative ouvre un SPAN, chaque changement
d'étape enregistre une TRANSITION, et tout est corrélé par le trace_id courant.

Le contrôle des étapes reste déterministe ; le LLM ne fait que comprendre et
formuler. L'observabilité n'change rien au comportement métier : elle le rend
seulement reconstructible.
"""

import json
import re
from dataclasses import dataclass
from typing import Callable

import ollama

import observability as obs_mod
import security

COLLECT_FIELDS = [
    ("heure_restitution", "l'heure approximative à laquelle le vélo a été restitué"),
    ("emplacement_restitution", "l'emplacement (station ou zone) où le vélo a été laissé"),
    ("description_probleme", "une description du problème et du message affiché dans l'application"),
]
MAX_ATTEMPTS = 3

STEP_LABELS = {
    1: "Identification du trajet",
    2: "Diagnostic",
    3: "Collecte des informations",
    4: "Confirmation",
    5: "Création de la demande",
}
# Noms d'étapes utilisés dans les transitions (lisibles dans la trace).
STEP_NAMES = {0: "START", 1: "IDENTIFICATION", 2: "DIAGNOSTIC", 3: "COLLECTE",
              4: "CONFIRMATION", 5: "CREATION"}
TERMINATED = "TERMINATED"

_TRIP_RE = re.compile(r"TR[PI]P?-[A-Z0-9]+", re.IGNORECASE)
_MEMBER_RE = re.compile(r"MBR-\d+", re.IGNORECASE)
_TEXT_CONFIRMATION_RE = re.compile(
    r"(je\s+confirme|c'?est\s+confirm[ée]|confirme\s+d[ée]j[àa]|"
    r"cr[ée]e[sz]?\s+(imm[ée]diatement\s+)?(la\s+)?demande|valide\s+la\s+demande)",
    re.IGNORECASE)

_INTENT_SCHEMA = {"type": "object",
                  "properties": {"wants_revision": {"type": "boolean"}},
                  "required": ["wants_revision"]}
_JUDGE_SCHEMA = {"type": "object",
                 "properties": {"answered": {"type": "boolean"},
                                "wants_to_cancel": {"type": "boolean"}},
                 "required": ["answered", "wants_to_cancel"]}


@dataclass
class Deps:
    model: str
    get_trip_raw: Callable[[str], str]
    create_revision: Callable[[dict], dict]
    rag_search: Callable[[str], list]      # renvoie les chunks (pour les tracer)
    rag_build_context: Callable[[list], str]
    policy: security.SecurityPolicy
    context: object
    obs: obs_mod.ObservabilityService


# --- Appels LLM instrumentés --------------------------------------------------

def _chat(obs, model, messages, options, call_type, span_name, fmt=None):
    """Appelle Ollama en enregistrant un span et les métriques de l'appel.

    On n'enregistre PAS les prompts : seulement leur taille et une estimation de
    tokens (≈ caractères / 4, documentée comme approximative).
    """
    input_chars = sum(len(m.get("content", "")) for m in messages)
    with obs.span(span_name, obs_mod.CAT_LLM,
                  model=model, call_type=call_type,
                  temperature=options.get("temperature"),
                  num_predict=options.get("num_predict"),
                  input_chars=input_chars,
                  estimated_input_tokens=obs_mod.estimate_tokens("x" * input_chars)) as span:
        try:
            kwargs = {"model": model, "messages": messages, "options": options}
            if fmt is not None:
                kwargs["format"] = fmt
            response = ollama.chat(**kwargs)
            content = response["message"]["content"]
            span.set(output_chars=len(content),
                     estimated_output_tokens=obs_mod.estimate_tokens(content))
            return content
        except Exception as error:  # noqa: BLE001
            obs.record_event(obs_mod.LLM_ERROR, "llm", "critical",
                             f"Appel LLM « {call_type} » en échec : {error}")
            raise


def detect_revision_intent(model, text, obs):
    system = ("Tu analyses le message d'un membre Bikaroo. Renvoie wants_revision=true "
              "s'il veut CONTESTER des frais ou DEMANDER une révision/correction pour un "
              "trajet ; false pour une simple question d'information ou de procédure. "
              "Réponds uniquement en JSON.")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": text}]
    try:
        content = _chat(obs, model, messages, {"temperature": 0},
                        "intent_detection", "intent_detection", fmt=_INTENT_SCHEMA)
        return bool(json.loads(content).get("wants_revision", False))
    except Exception:  # noqa: BLE001
        return False


def _judge_answer(model, question, reply, obs):
    system = (f"Un membre Bikaroo répond à cette question : « {question} ». "
              "Renvoie answered=true si sa réponse fournit l'information demandée (même "
              "approximative), false si elle est absente, incompréhensible, hors sujet ou "
              "s'il dit ne pas savoir. Renvoie wants_to_cancel=true UNIQUEMENT s'il exprime "
              "clairement vouloir arrêter la démarche. Réponds uniquement en JSON.")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": reply}]
    try:
        content = _chat(obs, model, messages, {"temperature": 0},
                        "answer_judgement", "answer_judgement", fmt=_JUDGE_SCHEMA)
        data = json.loads(content)
        return bool(data.get("answered")), bool(data.get("wants_to_cancel"))
    except Exception:  # noqa: BLE001
        return False, False


def _formulate(model, instruction, obs, context="", fallback=""):
    messages = [{"role": "system", "content":
                 "Tu es l'Assistant Bikaroo. Réponds en français, brièvement et poliment."}]
    if context:
        messages.append({"role": "system", "content": context})
    messages.append({"role": "user", "content": instruction})
    try:
        return _chat(obs, model, messages, {"temperature": 0.3, "num_predict": 220},
                     "formulation", "llm_formulation").strip() or fallback
    except Exception:  # noqa: BLE001
        return fallback


def find_trip_id(text):
    match = _TRIP_RE.search(text or "")
    return match.group(0).upper() if match else None


def find_member_id(text):
    match = _MEMBER_RE.search(text or "")
    return match.group(0).upper() if match else None


# --- Cycle de vie du processus -----------------------------------------------

def new_process(context):
    return {
        # step 0 = processus créé mais pas encore démarré (transition START → …).
        "active": True, "step": 0,
        "member_id": context.authenticated_member_id,
        "trip_id": None, "validated_trip_id": None,
        "collected": {}, "field_index": 0, "attempts": 0,
        "outcome": None, "need_confirmation": False, "last_tool_call": None,
    }


def _transition(deps, process, step_after_name, reason, status="ok"):
    """Enregistre une transition AU MOMENT où elle se produit (jamais déduite)."""
    before = STEP_NAMES.get(process.get("step", 0), "START")
    deps.obs.record_transition(before, step_after_name, reason, status)
    with deps.obs.span("workflow_transition", obs_mod.CAT_WORKFLOW,
                       step_before=before, step_after=step_after_name, reason=reason):
        pass


def _finish(deps, process, outcome, message, reason):
    _transition(deps, process, TERMINATED, reason,
                status="ok" if outcome == obs_mod.OUTCOME_CREATED else "stopped")
    process["active"] = False
    process["outcome"] = outcome
    process["need_confirmation"] = False
    if outcome in (obs_mod.OUTCOME_ABORTED, obs_mod.OUTCOME_REFUSED):
        deps.obs.record_event(obs_mod.WORKFLOW_ABORTED, "workflow", "warning",
                              f"Processus arrêté : {reason}")
    return message


# --- Démarrage / étape 1 : identification ------------------------------------

def advance_after_start(process, user_text, deps):
    claimed = find_member_id(user_text)
    deps.policy.note_member_override(claimed, deps.context)
    if claimed and not deps.policy.protected:
        process["member_id"] = claimed

    _transition(deps, process, STEP_NAMES[1], "intention de révision détectée")
    process["step"] = 1
    if process["trip_id"]:
        return _diagnose(process, deps)
    return ("Je peux vous aider à contester un trajet. Quel est l'identifiant du "
            "trajet concerné (format TRP-XXXXX) ?")


def _step1(process, user_text, deps):
    with deps.obs.span("trip_id_extraction", obs_mod.CAT_APPLICATION) as span:
        trip_id = find_trip_id(user_text)
        span.set(found=trip_id is not None, trip_id=trip_id or "")
    if not trip_id:
        _, wants_cancel = _judge_answer(deps.model, "l'identifiant du trajet à contester",
                                        user_text, deps.obs)
        if wants_cancel:
            return cancel(process, deps)
        return ("Je n'ai pas repéré d'identifiant de trajet (format TRP-XXXXX). "
                "Pouvez-vous me le communiquer ?")
    process["trip_id"] = trip_id
    return _diagnose(process, deps)


# --- Étape 2 : diagnostic -----------------------------------------------------

def _diagnose(process, deps):
    _transition(deps, process, STEP_NAMES[2], "identifiant de trajet connu")
    process["step"] = 2

    # (1) Appel MCP — succès TECHNIQUE de l'appel.
    try:
        with deps.obs.span("mcp_get_trip_status", obs_mod.CAT_MCP,
                           tool_name="get_trip_status",
                           validated_arguments={"trip_id": process["trip_id"]}) as span:
            raw = deps.get_trip_raw(process["trip_id"])
            span.set(result_summary=(raw or "")[:120].replace("\n", " "))
    except Exception as error:  # noqa: BLE001
        deps.obs.record_error(obs_mod.MCP_UNAVAILABLE, "mcp",
                              f"Serveur MCP injoignable : {error}")
        return _finish(deps, process, obs_mod.OUTCOME_FAILED,
            "Je ne parviens pas à joindre le système opérationnel pour vérifier ce "
            "trajet. Réessayez plus tard ou contactez le service à la clientèle.",
            "mcp_unavailable")

    # (2) Validation MÉTIER du résultat — distincte du succès technique.
    with deps.obs.span("tool_result_validation", obs_mod.CAT_SECURITY,
                       tool_name="get_trip_status") as span:
        trip = deps.policy.validate_trip_result(raw)
        span.set(valid=trip is not None)
        if trip is None:
            span.status = obs_mod.STATUS_FAILED
    if trip is None:
        return _finish(deps, process, obs_mod.OUTCOME_REFUSED,
            f"Je ne peux pas exploiter les informations du trajet {process['trip_id']} : "
            "le résultat reçu est incomplet ou invalide. Par précaution, je m'arrête ici.",
            "invalid_tool_result")

    # (3) Contrôle d'identité.
    with deps.obs.span("identity_validation", obs_mod.CAT_SECURITY,
                       trip_member=trip.member_id,
                       authenticated_member=deps.context.authenticated_member_id) as span:
        identity_ok = deps.policy.check_identity(trip, deps.context)
        span.set(identity_ok=identity_ok)
        if not identity_ok:
            span.status = obs_mod.STATUS_FAILED
    if not identity_ok:
        return _finish(deps, process, obs_mod.OUTCOME_REFUSED,
            f"Je ne peux pas ouvrir de demande de révision pour le trajet {trip.trip_id} "
            "avec le compte actuellement authentifié.", "identity_mismatch")

    # (4) Règle métier d'éligibilité.
    if trip.status == "closed":
        return _finish(deps, process, obs_mod.OUTCOME_NOT_ELIGIBLE,
            f"Le trajet {trip.trip_id} est déjà clôturé. Un trajet clôturé sans anomalie "
            "signalée n'est pas éligible à une demande de révision.", "trajet clôturé")

    process["validated_trip_id"] = trip.trip_id
    _transition(deps, process, STEP_NAMES[3], "trajet open et identité valide")
    process["step"] = 3
    process["field_index"] = 0
    process["attempts"] = 0

    # (5) Recherche RAG instrumentée.
    query = "procédure trajet resté ouvert après restitution, contestation et révision de frais"
    with deps.obs.span("rag_search", obs_mod.CAT_RAG, query=query, top_k=4) as span:
        chunks = deps.rag_search(query)
        raw_context = deps.rag_build_context(chunks)
        span.set(result_count=len(chunks),
                 documents=[c["document"] for c in chunks],
                 headings=[c["heading"] for c in chunks],
                 scores=[round(c["score"], 3) for c in chunks],
                 context_chars=len(raw_context))
        if not chunks:
            deps.obs.record_event(obs_mod.RAG_NO_RESULT, "rag", "warning",
                                  "Aucun extrait documentaire retrouvé.")

    deps.policy.scan_for_injection(raw_context, "rag_document")
    wrapped = deps.policy.wrap_untrusted(raw_context, security.UNTRUSTED_DOCUMENTS_TAG)

    diagnostic = _formulate(
        deps.model,
        f"Le trajet {trip.trip_id} est toujours ouvert (statut « open »). En une ou deux "
        "phrases, explique au membre que tu vas ouvrir une demande de révision et que tu as "
        "besoin de quelques informations, en t'appuyant sur la procédure fournie.",
        deps.obs,
        context=("Procédure applicable :\n\n" + wrapped) if wrapped else "",
        fallback=(f"Le trajet {trip.trip_id} est effectivement toujours ouvert. Je vais "
                  "ouvrir une demande de révision ; j'ai besoin de quelques informations."))
    return diagnostic + "\n\n" + _ask_current_field(process, deps)


# --- Étape 3 : collecte -------------------------------------------------------

def _ask_current_field(process, deps):
    _, label = COLLECT_FIELDS[process["field_index"]]
    return _formulate(
        deps.model,
        f"Pose au membre une question courte et polie pour lui demander {label}. Écris "
        "UNIQUEMENT la question, ne réponds pas à sa place et n'ajoute pas d'explication.",
        deps.obs, fallback=f"Pouvez-vous m'indiquer {label} ?")


def _step3(process, user_text, deps):
    name, label = COLLECT_FIELDS[process["field_index"]]
    answered, wants_cancel = _judge_answer(deps.model, label, user_text, deps.obs)

    if wants_cancel:
        return cancel(process, deps)
    if answered:
        process["collected"][name] = user_text.strip()
        process["field_index"] += 1
        process["attempts"] = 0
        deps.obs.record_event("collect_field_accepted", "workflow", "info",
                              f"Information « {name} » collectée.",
                              field_index=process["field_index"])
        if process["field_index"] >= len(COLLECT_FIELDS):
            return _to_confirmation(process, deps)
        return _ask_current_field(process, deps)

    process["attempts"] += 1
    deps.obs.record_event("collect_field_rejected", "workflow", "warning",
                          f"Réponse inexploitable pour « {name} ».",
                          attempts=process["attempts"])
    if process["attempts"] >= MAX_ATTEMPTS:
        return _finish(deps, process, obs_mod.OUTCOME_ABORTED,
            "Je n'ai pas réussi à recueillir cette information après plusieurs tentatives. "
            "Contactez directement le service à la clientèle. Aucune demande n'a été créée.",
            f"{MAX_ATTEMPTS} tentatives infructueuses")
    return _formulate(
        deps.model,
        f"Le membre n'a pas fourni {label}. Repose la question autrement, en une phrase "
        "courte et polie. Écris UNIQUEMENT la question, ne réponds pas à sa place.",
        deps.obs, fallback=f"Je n'ai pas bien compris. Pouvez-vous préciser {label} ?")


# --- Étape 4 : confirmation ---------------------------------------------------

def _to_confirmation(process, deps):
    _transition(deps, process, STEP_NAMES[4], "toutes les informations sont collectées")
    process["step"] = 4
    process["need_confirmation"] = True
    c = process["collected"]
    return ("Voici le récapitulatif de la demande de révision qui va être créée :\n\n"
            f"- **Membre** : {process['member_id']}\n"
            f"- **Trajet** : {process['validated_trip_id'] or process['trip_id']}\n"
            f"- **Heure de restitution** : {c.get('heure_restitution', '—')}\n"
            f"- **Emplacement** : {c.get('emplacement_restitution', '—')}\n"
            f"- **Problème** : {c.get('description_probleme', '—')}\n\n"
            "Confirmez-vous la création de cette demande ? Utilisez les boutons "
            "« Confirmer » ou « Annuler » ci-dessous.")


# --- Étape 5 : création -------------------------------------------------------

def _create(process, deps, confirmation_event):
    with deps.obs.span("write_authorization", obs_mod.CAT_SECURITY,
                       confirmation_event=confirmation_event,
                       step=process.get("step"),
                       need_confirmation=process.get("need_confirmation")) as span:
        authorized = deps.policy.authorize_write(process, confirmation_event, deps.context)
        span.set(authorized=authorized)
        if not authorized:
            span.status = obs_mod.STATUS_FAILED
    if not authorized:
        return ("Je ne peux pas créer la demande : une confirmation explicite est "
                "nécessaire. Utilisez le bouton « Confirmer » à l'étape de confirmation. "
                "Aucune écriture n'a été effectuée.")

    parameters = deps.policy.build_write_parameters(process, deps.context)
    if parameters is None:
        return _finish(deps, process, obs_mod.OUTCOME_REFUSED,
            "Les paramètres de la demande n'ont pas pu être validés. Aucune écriture "
            "n'a été effectuée.", "invalid_write_parameters")

    _transition(deps, process, STEP_NAMES[5], "clic utilisateur sur Confirmer")
    process["need_confirmation"] = False
    process["step"] = 5
    try:
        with deps.obs.span("mcp_create_revision_request", obs_mod.CAT_MCP,
                           tool_name="create_revision_request",
                           validated_arguments={k: v for k, v in parameters.items()
                                                if k in ("member_id", "trip_id")}) as span:
            result = deps.create_revision(parameters)
            span.set(result_summary=json.dumps(result, ensure_ascii=False)[:120])
    except Exception as error:  # noqa: BLE001
        deps.obs.record_error(obs_mod.MCP_UNAVAILABLE, "mcp",
                              f"Écriture impossible (serveur MCP) : {error}")
        return _finish(deps, process, obs_mod.OUTCOME_FAILED,
            "La demande n'a pas pu être enregistrée : le système est indisponible. "
            "Aucune écriture n'a été effectuée.", "mcp_unavailable")

    process["last_tool_call"] = {"name": "create_revision_request",
                                 "arguments": parameters,
                                 "result": json.dumps(result, ensure_ascii=False)}
    return _finish(deps, process, obs_mod.OUTCOME_CREATED,
        f"Votre demande de révision a été créée : identifiant "
        f"**{result.get('request_id', '?')}**, statut « {result.get('status', '?')} ». "
        "Elle sera examinée par le service à la clientèle.",
        "demande créée")


def confirm(process, deps):
    return _create(process, deps, confirmation_event="button_click")


def cancel(process, deps):
    return _finish(deps, process, obs_mod.OUTCOME_CANCELLED,
        "Démarche annulée. Aucune demande n'a été créée.", "annulation par l'utilisateur")


# --- Routage des messages utilisateur ----------------------------------------

def handle_message(process, user_text, deps):
    deps.policy.scan_for_injection(user_text, "user_message")

    if _TEXT_CONFIRMATION_RE.search(user_text or ""):
        return _create(process, deps, confirmation_event="text_confirmation")

    step = process["step"]
    if step == 1:
        return _step1(process, user_text, deps)
    if step == 3:
        return _step3(process, user_text, deps)
    if step == 4:
        _, wants_cancel = _judge_answer(deps.model, "la confirmation de la demande",
                                        user_text, deps.obs)
        if wants_cancel:
            return cancel(process, deps)
        return ("Pour créer la demande, utilisez le bouton « Confirmer » ci-dessous "
                "(ou « Annuler » pour abandonner).")
    return "Le processus est terminé."
