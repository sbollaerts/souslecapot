"""Orchestration d'un processus métier en 5 étapes — Labo 4.

Point clé du labo : le **contrôle des étapes est déterministe**, écrit dans ce
module (quelle étape suit quelle étape, quand s'arrêter, quand demander
confirmation, quand écrire). Le LLM ne décide jamais de passer à l'étape suivante
ni de déclencher l'écriture : il contribue uniquement à *comprendre* l'utilisateur
(détection d'intention, jugement des réponses) et à *formuler* les messages.

Les 5 étapes :

    1. Identification du trajet concerné
    2. Diagnostic (statut réel + procédure applicable)  → règle d'éligibilité
    3. Collecte des informations manquantes             → max 3 tentatives/info
    4. Confirmation (boutons explicites)
    5. Création de la demande (tool d'écriture)
"""

import json
import re
from dataclasses import dataclass
from typing import Callable

import ollama

# Informations à collecter à l'étape 3 (issues de la procédure documentaire
# 02-procedure-trajet-reste-ouvert.md, section « Informations à collecter »).
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

_TRIP_RE = re.compile(r"TRP-\d+", re.IGNORECASE)

_INTENT_SCHEMA = {
    "type": "object",
    "properties": {"wants_revision": {"type": "boolean"}},
    "required": ["wants_revision"],
}
_JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "answered": {"type": "boolean"},
        "wants_to_cancel": {"type": "boolean"},
    },
    "required": ["answered", "wants_to_cancel"],
}


@dataclass
class Deps:
    """Dépendances fournies par l'application (tools MCP, RAG, modèle)."""
    model: str
    get_trip_status: Callable[[str], dict]
    create_revision: Callable[[str, str, str, str], dict]
    rag_context: Callable[[str], str]


# --- Contributions du LLM : comprendre et formuler (jamais décider) ----------

def detect_revision_intent(model, text):
    """LLM : le membre veut-il contester/faire réviser un trajet ? (booléen)"""
    system = (
        "Tu analyses le message d'un membre Bikaroo. Renvoie wants_revision=true "
        "s'il veut CONTESTER des frais ou DEMANDER une révision/correction pour un "
        "trajet ; false pour une simple question d'information ou de procédure. "
        "Réponds uniquement en JSON."
    )
    try:
        response = ollama.chat(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
            format=_INTENT_SCHEMA,
            options={"temperature": 0},
        )
        return bool(json.loads(response["message"]["content"]).get("wants_revision", False))
    except Exception:  # noqa: BLE001
        return False


def _judge_answer(model, question, reply):
    """LLM : la réponse fournit-elle l'info ? le membre veut-il annuler ? (2 booléens)"""
    system = (
        f"Un membre Bikaroo répond à cette question : « {question} ». "
        "Renvoie answered=true si sa réponse fournit l'information demandée (même "
        "approximative), false si elle est absente, incompréhensible, hors sujet ou "
        "s'il dit ne pas savoir. Renvoie wants_to_cancel=true UNIQUEMENT s'il exprime "
        "clairement vouloir arrêter la démarche (pas une simple réponse hors sujet). "
        "Réponds uniquement en JSON."
    )
    try:
        response = ollama.chat(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": reply}],
            format=_JUDGE_SCHEMA,
            options={"temperature": 0},
        )
        data = json.loads(response["message"]["content"])
        return bool(data.get("answered")), bool(data.get("wants_to_cancel"))
    except Exception:  # noqa: BLE001
        return False, False


def _formulate(model, instruction, context="", fallback=""):
    """LLM : formule un court message en français à partir d'une consigne."""
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
    """Extraction déterministe d'un identifiant de trajet (format TRP-XXXXX)."""
    match = _TRIP_RE.search(text or "")
    return match.group(0).upper() if match else None


# --- Cycle de vie du processus -----------------------------------------------

def new_process(member_id):
    return {
        "active": True,
        "step": 1,
        "member_id": member_id,
        "trip_id": None,
        "trip": None,
        "collected": {},
        "field_index": 0,
        "attempts": 0,
        "finished": False,
        "outcome": None,          # created | cancelled | aborted | not_eligible
        "need_confirmation": False,
        "last_tool_call": None,   # appel à create_revision_request, pour l'UI
    }


def _finish(process, outcome, message):
    process["active"] = False
    process["finished"] = True
    process["outcome"] = outcome
    process["need_confirmation"] = False
    return message


# --- Étape 1 : identification -------------------------------------------------

def advance_after_start(process, deps):
    """Juste après détection de l'intention : diagnostiquer si le trajet est connu,
    sinon demander son identifiant."""
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


# --- Étape 2 : diagnostic (règles déterministes d'éligibilité) ----------------

def _diagnose(process, deps):
    process["step"] = 2
    trip = deps.get_trip_status(process["trip_id"])
    process["trip"] = trip

    # Trajet introuvable.
    if trip.get("found") is False or "status" not in trip:
        return _finish(process, "not_eligible",
            f"Je ne trouve aucun trajet {process['trip_id']} dans le système. "
            "Vérifiez l'identifiant ou contactez le service à la clientèle.")

    # Trajet d'un autre membre (pas d'ouverture de révision au nom de ce membre).
    if trip.get("member_id") and trip["member_id"] != process["member_id"]:
        return _finish(process, "not_eligible",
            f"Le trajet {process['trip_id']} n'est pas associé à votre compte "
            f"({process['member_id']}). Je ne peux pas ouvrir de révision à votre nom.")

    # Règle DÉTERMINISTE : un trajet déjà clôturé sans anomalie n'est pas éligible.
    if trip.get("status") == "closed":
        return _finish(process, "not_eligible",
            f"Le trajet {process['trip_id']} est déjà clôturé. Un trajet clôturé sans "
            "anomalie signalée n'est pas éligible à une demande de révision. Si vous "
            "constatez tout de même un problème, contactez le service à la clientèle.")

    # Éligible (trajet ouvert) : on s'appuie sur le RAG pour la procédure, puis on
    # passe à la collecte des informations.
    context = deps.rag_context(
        "procédure trajet resté ouvert après restitution, contestation et révision de frais")
    process["step"] = 3
    process["field_index"] = 0
    process["attempts"] = 0
    diagnostic = _formulate(
        deps.model,
        f"Le trajet {process['trip_id']} est toujours ouvert (statut « open »). "
        "En une ou deux phrases, explique au membre que tu vas ouvrir une demande de "
        "révision et que tu as besoin de quelques informations, en t'appuyant sur la "
        "procédure fournie.",
        context=("Procédure applicable :\n\n" + context) if context else "",
        fallback=(f"Le trajet {process['trip_id']} est effectivement toujours ouvert. "
                  "Je vais ouvrir une demande de révision ; j'ai besoin de quelques "
                  "informations."),
    )
    return diagnostic + "\n\n" + _ask_current_field(process, deps)


# --- Étape 3 : collecte -------------------------------------------------------

def _ask_current_field(process, deps):
    _, label = COLLECT_FIELDS[process["field_index"]]
    return _formulate(
        deps.model,
        f"Pose au membre une question courte et polie pour lui demander {label}. "
        "Écris UNIQUEMENT la question, ne réponds pas à sa place et n'ajoute pas d'explication.",
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

    # Réponse inexploitable : on retente, jusqu'à MAX_ATTEMPTS.
    process["attempts"] += 1
    if process["attempts"] >= MAX_ATTEMPTS:
        return _finish(process, "aborted",
            "Je n'ai pas réussi à recueillir cette information après plusieurs "
            "tentatives, je préfère m'arrêter là plutôt que de vous faire tourner en "
            "rond. Contactez directement le service à la clientèle, qui finalisera "
            "votre demande. Aucune demande n'a été créée.")
    return _formulate(
        deps.model,
        f"Le membre n'a pas fourni {label}. Repose la question autrement, en une "
        "phrase courte et polie. Écris UNIQUEMENT la question, ne réponds pas à sa place.",
        fallback=f"Je n'ai pas bien compris. Pouvez-vous préciser {label} ?",
    )


# --- Étape 4 : confirmation ---------------------------------------------------

def _to_confirmation(process):
    process["step"] = 4
    process["need_confirmation"] = True
    c = process["collected"]
    return (
        "Voici le récapitulatif de la demande de révision qui va être créée :\n\n"
        f"- **Membre** : {process['member_id']}\n"
        f"- **Trajet** : {process['trip_id']}\n"
        f"- **Heure de restitution** : {c.get('heure_restitution', '—')}\n"
        f"- **Emplacement** : {c.get('emplacement_restitution', '—')}\n"
        f"- **Problème** : {c.get('description_probleme', '—')}\n\n"
        "Confirmez-vous la création de cette demande ? Utilisez les boutons "
        "« Confirmer » ou « Annuler » ci-dessous."
    )


# --- Étape 5 : création (déclenchée UNIQUEMENT par le bouton « Confirmer ») ----

def confirm(process, deps):
    process["need_confirmation"] = False
    process["step"] = 5
    c = process["collected"]
    description = c.get("description_probleme", "")
    infos = (f"Heure de restitution : {c.get('heure_restitution', '—')}. "
             f"Emplacement : {c.get('emplacement_restitution', '—')}.")
    result = deps.create_revision(process["member_id"], process["trip_id"], description, infos)
    process["result"] = result
    process["last_tool_call"] = {
        "name": "create_revision_request",
        "arguments": {
            "member_id": process["member_id"],
            "trip_id": process["trip_id"],
            "description": description,
            "informations_complementaires": infos,
        },
        "result": json.dumps(result, ensure_ascii=False),
    }
    message = (
        f"Votre demande de révision a été créée : identifiant "
        f"**{result.get('request_id', '?')}**, statut « {result.get('status', '?')} ». "
        "Elle sera examinée par le service à la clientèle ; aucun remboursement n'est "
        "garanti avant analyse."
    )
    return _finish(process, "created", message)


def cancel(process):
    return _finish(process, "cancelled",
        "Démarche annulée. Aucune demande n'a été créée. N'hésitez pas à la reprendre "
        "quand vous le souhaitez.")


# --- Routage des messages utilisateur pendant le processus -------------------

def handle_message(process, user_text, deps):
    """Aiguille un message utilisateur selon l'étape courante (contrôle déterministe)."""
    step = process["step"]
    if step == 1:
        return _step1(process, user_text, deps)
    if step == 3:
        return _step3(process, user_text, deps)
    if step == 4:
        # L'utilisateur écrit au lieu de cliquer : on ne valide jamais une écriture
        # sur du texte libre. On propose d'annuler ou de cliquer.
        _, wants_cancel = _judge_answer(deps.model, "la confirmation de la demande", user_text)
        if wants_cancel:
            return cancel(process)
        return ("Pour créer la demande, utilisez le bouton « Confirmer » ci-dessous "
                "(ou « Annuler » pour abandonner).")
    return "Le processus est terminé."
