"""Orchestration du processus métier, sous contrôle de sécurité — Labo 5.

Reprend le processus en 5 étapes du labo 4 (contrôle déterministe des étapes ; le
LLM ne fait que comprendre et formuler) et le place derrière une couche de
sécurité explicite (module security) :

  - l'identité vient du TrustedContext, jamais d'un message ;
  - les résultats de tools sont validés strictement avant usage ;
  - les contenus non fiables (RAG, tools) sont délimités et signalés ;
  - l'écriture n'est autorisée que par un clic sur « Confirmer » ;
  - les paramètres d'écriture sont reconstruits depuis l'état validé.

Deux modes permettent la comparaison : « vulnérable » (contrôles contournés,
défauts de conception plausibles) et « protégé » (tous les contrôles actifs).
"""

import json
import re
from dataclasses import dataclass
from typing import Callable

import ollama

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

# On repère largement les identifiants cités (y compris mal formés) : c'est la
# validation stricte, plus loin, qui décide de ce qui est acceptable.
_TRIP_RE = re.compile(r"TR[PI]P?-[A-Z0-9]+", re.IGNORECASE)
_MEMBER_RE = re.compile(r"MBR-\d+", re.IGNORECASE)

# Formulations par lesquelles un utilisateur « affirme » une confirmation.
# En mode protégé, elles ne déclenchent JAMAIS d'écriture.
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
    """Dépendances fournies par l'application."""
    model: str
    get_trip_raw: Callable[[str], str]       # renvoie le JSON BRUT du tool
    create_revision: Callable[[dict], dict]  # reçoit les paramètres reconstruits
    rag_context: Callable[[str], str]
    policy: security.SecurityPolicy
    context: object                          # TrustedContext


# --- Contributions du LLM : comprendre et formuler (jamais décider) ----------

def detect_revision_intent(model, text):
    system = ("Tu analyses le message d'un membre Bikaroo. Renvoie wants_revision=true "
              "s'il veut CONTESTER des frais ou DEMANDER une révision/correction pour un "
              "trajet ; false pour une simple question d'information ou de procédure. "
              "Réponds uniquement en JSON.")
    try:
        response = ollama.chat(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
            format=_INTENT_SCHEMA, options={"temperature": 0})
        return bool(json.loads(response["message"]["content"]).get("wants_revision", False))
    except Exception:  # noqa: BLE001
        return False


def _judge_answer(model, question, reply):
    system = (f"Un membre Bikaroo répond à cette question : « {question} ». "
              "Renvoie answered=true si sa réponse fournit l'information demandée (même "
              "approximative), false si elle est absente, incompréhensible, hors sujet ou "
              "s'il dit ne pas savoir. Renvoie wants_to_cancel=true UNIQUEMENT s'il exprime "
              "clairement vouloir arrêter la démarche. Réponds uniquement en JSON.")
    try:
        response = ollama.chat(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": reply}],
            format=_JUDGE_SCHEMA, options={"temperature": 0})
        data = json.loads(response["message"]["content"])
        return bool(data.get("answered")), bool(data.get("wants_to_cancel"))
    except Exception:  # noqa: BLE001
        return False, False


def _formulate(model, instruction, context="", fallback=""):
    messages = [{"role": "system", "content":
                 "Tu es l'Assistant Bikaroo. Réponds en français, brièvement et poliment."}]
    if context:
        messages.append({"role": "system", "content": context})
    messages.append({"role": "user", "content": instruction})
    try:
        response = ollama.chat(model=model, messages=messages,
                               options={"temperature": 0.3, "num_predict": 220})
        return response["message"]["content"].strip() or fallback
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
        "active": True,
        "step": 1,
        # Identité de travail : par défaut celle du contexte de confiance.
        "member_id": context.authenticated_member_id,
        "trip_id": None,
        "validated_trip_id": None,   # rempli seulement après validation du tool
        "collected": {},
        "field_index": 0,
        "attempts": 0,
        "outcome": None,
        "need_confirmation": False,
        "last_tool_call": None,
    }


def _finish(process, outcome, message):
    process["active"] = False
    process["outcome"] = outcome
    process["need_confirmation"] = False
    return message


# --- Démarrage / étape 1 : identification ------------------------------------

def advance_after_start(process, user_text, deps):
    # Une identité affirmée dans un message est une donnée non fiable.
    claimed = find_member_id(user_text)
    deps.policy.note_member_override(claimed, deps.context)
    if claimed and not deps.policy.protected:
        # Défaut de conception (mode vulnérable) : on fait confiance au message.
        process["member_id"] = claimed

    if process["trip_id"]:
        return _diagnose(process, deps)
    process["step"] = 1
    return ("Je peux vous aider à contester un trajet. Quel est l'identifiant du "
            "trajet concerné (format TRP-XXXXX) ?")


def _step1(process, user_text, deps):
    trip_id = find_trip_id(user_text)
    if not trip_id:
        _, wants_cancel = _judge_answer(deps.model, "l'identifiant du trajet à contester", user_text)
        if wants_cancel:
            return cancel(process)
        return ("Je n'ai pas repéré d'identifiant de trajet (format TRP-XXXXX). "
                "Pouvez-vous me le communiquer ?")
    process["trip_id"] = trip_id
    return _diagnose(process, deps)


# --- Étape 2 : diagnostic (validation stricte + identité + éligibilité) ------

def _diagnose(process, deps):
    process["step"] = 2
    raw = deps.get_trip_raw(process["trip_id"])

    # (a) Validation stricte du résultat de tool : liste blanche de champs,
    #     formats, statut ; les champs inconnus sont ignorés et signalés.
    trip = deps.policy.validate_trip_result(raw)
    if trip is None:
        return _finish(process, "invalid_tool_result",
            f"Je ne peux pas exploiter les informations du trajet {process['trip_id']} : "
            "le résultat reçu est incomplet ou invalide. Par précaution, je m'arrête ici. "
            "Contactez le service à la clientèle.")

    # (b) Contrôle d'identité AVANT toute autre règle : le trajet doit appartenir
    #     au membre authentifié (source de vérité = TrustedContext).
    if not deps.policy.check_identity(trip, deps.context):
        return _finish(process, "identity_mismatch",
            f"Je ne peux pas ouvrir de demande de révision pour le trajet {trip.trip_id} "
            "avec le compte actuellement authentifié.")

    # (c) Règle métier déterministe d'éligibilité (héritée du labo 4).
    if trip.status == "closed":
        return _finish(process, "not_eligible",
            f"Le trajet {trip.trip_id} est déjà clôturé. Un trajet clôturé sans anomalie "
            "signalée n'est pas éligible à une demande de révision.")

    # Trajet validé : c'est CETTE valeur qui servira à l'écriture.
    process["validated_trip_id"] = trip.trip_id
    process["step"] = 3
    process["field_index"] = 0
    process["attempts"] = 0

    raw_context = deps.rag_context(
        "procédure trajet resté ouvert après restitution, contestation et révision de frais")
    deps.policy.scan_for_injection(raw_context, "rag_document")
    wrapped = deps.policy.wrap_untrusted(raw_context, security.UNTRUSTED_DOCUMENTS_TAG)

    diagnostic = _formulate(
        deps.model,
        f"Le trajet {trip.trip_id} est toujours ouvert (statut « open »). En une ou deux "
        "phrases, explique au membre que tu vas ouvrir une demande de révision et que tu as "
        "besoin de quelques informations, en t'appuyant sur la procédure fournie.",
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
        fallback=f"Pouvez-vous m'indiquer {label} ?")


def _step3(process, user_text, deps):
    _, label = COLLECT_FIELDS[process["field_index"]]
    answered, wants_cancel = _judge_answer(deps.model, label, user_text)

    if wants_cancel:
        return cancel(process)
    if answered:
        name = COLLECT_FIELDS[process["field_index"]][0]
        process["collected"][name] = user_text.strip()
        process["field_index"] += 1
        process["attempts"] = 0
        if process["field_index"] >= len(COLLECT_FIELDS):
            return _to_confirmation(process)
        return _ask_current_field(process, deps)

    process["attempts"] += 1
    if process["attempts"] >= MAX_ATTEMPTS:
        return _finish(process, "aborted",
            "Je n'ai pas réussi à recueillir cette information après plusieurs tentatives. "
            "Contactez directement le service à la clientèle. Aucune demande n'a été créée.")
    return _formulate(
        deps.model,
        f"Le membre n'a pas fourni {label}. Repose la question autrement, en une phrase "
        "courte et polie. Écris UNIQUEMENT la question, ne réponds pas à sa place.",
        fallback=f"Je n'ai pas bien compris. Pouvez-vous préciser {label} ?")


# --- Étape 4 : confirmation ---------------------------------------------------

def _to_confirmation(process):
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
    """Crée la demande si et seulement si l'écriture est autorisée."""
    if not deps.policy.authorize_write(process, confirmation_event, deps.context):
        return ("Je ne peux pas créer la demande : une confirmation explicite est "
                "nécessaire. Utilisez le bouton « Confirmer » à l'étape de confirmation. "
                "Aucune écriture n'a été effectuée.")

    # Les paramètres finaux sont RECONSTRUITS depuis l'état validé et le contexte
    # de confiance — jamais depuis le dernier message ou un JSON du modèle.
    parameters = deps.policy.build_write_parameters(process, deps.context)
    if parameters is None:
        return _finish(process, "refused",
            "Les paramètres de la demande n'ont pas pu être validés. Aucune écriture "
            "n'a été effectuée.")

    process["need_confirmation"] = False
    process["step"] = 5
    result = deps.create_revision(parameters)
    process["last_tool_call"] = {
        "name": "create_revision_request",
        "arguments": parameters,
        "result": json.dumps(result, ensure_ascii=False),
    }
    return _finish(process, "created",
        f"Votre demande de révision a été créée : identifiant "
        f"**{result.get('request_id', '?')}**, statut « {result.get('status', '?')} ». "
        "Elle sera examinée par le service à la clientèle.")


def confirm(process, deps):
    """Bouton « Confirmer » : le SEUL signal autorisant une écriture en mode protégé."""
    return _create(process, deps, confirmation_event="button_click")


def cancel(process):
    return _finish(process, "cancelled",
        "Démarche annulée. Aucune demande n'a été créée.")


# --- Routage des messages utilisateur ----------------------------------------

def handle_message(process, user_text, deps):
    # Toute entrée utilisateur est une donnée non fiable : on la scanne.
    deps.policy.scan_for_injection(user_text, "user_message")

    # Une « confirmation » exprimée en texte libre n'est pas une confirmation.
    if _TEXT_CONFIRMATION_RE.search(user_text or ""):
        return _create(process, deps, confirmation_event="text_confirmation")

    step = process["step"]
    if step == 1:
        return _step1(process, user_text, deps)
    if step == 3:
        return _step3(process, user_text, deps)
    if step == 4:
        _, wants_cancel = _judge_answer(deps.model, "la confirmation de la demande", user_text)
        if wants_cancel:
            return cancel(process)
        return ("Pour créer la demande, utilisez le bouton « Confirmer » ci-dessous "
                "(ou « Annuler » pour abandonner).")
    return "Le processus est terminé."
