"""Assistant Bikaroo — Labo 5 : attaquer puis protéger.

Reprend l'assistant du labo 4 (chat + RAG + MCP + processus de révision en 5
étapes avec écriture) et ajoute une couche de sécurité explicite, avec deux modes
comparables :

    Mode vulnérable — défauts de conception plausibles (confiance excessive)
    Mode protégé    — contrôles applicatifs actifs et observables

Le prompt système *oriente* le modèle ; les contrôles applicatifs *empêchent*
réellement les actions interdites.
"""

import json
from pathlib import Path

import streamlit as st

import mcp_client
import orchestration
import rag
import security
import trusted_context

MODEL = "qwen2.5:3b"
MCP_URL = "http://localhost:8000/mcp"

CORPUS_DIR = Path(__file__).resolve().parents[1] / "ressources"
DB_PATH = Path(__file__).resolve().parent / "bikaroo_rag.db"

BASE_SYSTEM_PROMPT = (
    "Tu es l'Assistant Bikaroo, l'assistant virtuel de Bikaroo, une société de "
    "vélos partagés à Bruxelles. Tu réponds toujours en français, de manière "
    "claire, polie et concise.\n"
    "Tu disposes d'un contexte documentaire et de tools de lecture (statut d'un "
    "trajet, informations d'un membre). Appuie-toi dessus et n'invente pas."
)

st.set_page_config(page_title="Assistant Bikaroo — Labo 5", page_icon="🔒")

# --- État de session ---------------------------------------------------------
for key, default in [("messages", []), ("last_call_info", None), ("last_sources", None),
                     ("last_tool_calls", None), ("process", None)]:
    if key not in st.session_state:
        st.session_state[key] = default

# Contexte de confiance (authentification simulée) et politique de sécurité :
# créés une seule fois. Le journal survit aux changements de mode, ce qui permet
# de comparer les deux modes sur les mêmes attaques.
if "trusted" not in st.session_state:
    st.session_state.trusted = trusted_context.new_context("MBR-1042")
if "policy" not in st.session_state:
    st.session_state.policy = security.SecurityPolicy(protected=True)

trusted = st.session_state.trusted
policy = st.session_state.policy

# --- Indexation du corpus ----------------------------------------------------
if "index_size" not in st.session_state:
    try:
        with st.spinner("Indexation du corpus documentaire…"):
            st.session_state.index_size = rag.ensure_index(DB_PATH, CORPUS_DIR)
    except Exception as error:  # noqa: BLE001
        st.error("Impossible d'indexer le corpus. Vérifiez qu'Ollama est lancé et que le "
                 f"modèle « {rag.EMBEDDING_MODEL} » est téléchargé.\n\nDétail : {error}")
        st.stop()

# --- Connexion au serveur MCP ------------------------------------------------
if "mcp_tools" not in st.session_state:
    try:
        st.session_state.mcp_tools = mcp_client.list_tool_names(MCP_URL)
    except Exception:  # noqa: BLE001
        st.session_state.mcp_tools = None


def _make_deps(top_k):
    return orchestration.Deps(
        model=MODEL,
        # Le résultat BRUT du tool est remis à la politique de sécurité, qui le
        # valide avant tout usage par le workflow.
        get_trip_raw=lambda tid: mcp_client.call_tool(MCP_URL, "get_trip_status", {"trip_id": tid}),
        create_revision=lambda params: json.loads(
            mcp_client.call_tool(MCP_URL, "create_revision_request", params)),
        rag_context=lambda q: rag.build_context(rag.search(DB_PATH, q, top_k=top_k)),
        policy=policy,
        context=trusted,
    )


# --- Barre latérale ----------------------------------------------------------
with st.sidebar:
    st.header("Sécurité")

    mode = st.radio("Mode de sécurité", ["Protégé", "Vulnérable"],
                    help="Protégé : tous les contrôles applicatifs sont actifs. "
                         "Vulnérable : défauts de conception plausibles, pour comparer.")
    policy.protected = (mode == "Protégé")

    st.markdown("**Contexte de confiance**")
    st.code(f"Membre authentifié simulé : {trusted.authenticated_member_id}\n"
            f"Actions autorisées : {', '.join(trusted.allowed_actions)}\n"
            f"Session : {trusted.session_id}", language="text")
    st.caption("Lecture seule : aucune instruction utilisateur ne peut modifier ce contexte.")

    st.header("Configuration")
    use_rag = st.toggle("Avec RAG (hors processus)", value=True)
    system_prompt = st.text_area("Prompt système (hors processus)",
                                 value=BASE_SYSTEM_PROMPT, height=140)
    temperature = st.slider("Température", 0.0, 1.0, 0.7, 0.1)
    max_tokens = st.slider("Nombre maximum de tokens en sortie", 64, 2048, 512, 64)
    top_k = st.slider("Nombre de chunks récupérés (top-k)", 1, 6, 4, 1)

    st.subheader("Serveur MCP")
    if st.session_state.mcp_tools:
        st.success("Connecté · tools : " + ", ".join(st.session_state.mcp_tools))
    else:
        st.warning("Serveur MCP injoignable. Démarrez-le, puis rechargez la page.")

    if st.button("Effacer la conversation"):
        for key in ["messages", "last_call_info", "last_sources", "last_tool_calls", "process"]:
            st.session_state[key] = [] if key == "messages" else None
        st.rerun()
    if st.button("Effacer le journal de sécurité"):
        policy.clear()
        st.rerun()

deps = _make_deps(top_k)

# --- En-tête -----------------------------------------------------------------
st.title("🔒 Assistant Bikaroo")
st.caption(f"Labo 5 — Sécurité · mode **{mode}** (Ollama · {MODEL} + {rag.EMBEDDING_MODEL} · "
           f"{st.session_state.index_size} chunks)")

process = st.session_state.process
if process and process["active"]:
    st.info(f"**Processus de révision — Étape {process['step']}/5 : "
            f"{orchestration.STEP_LABELS[process['step']]}**")

# --- Saisie utilisateur ------------------------------------------------------
user_input = st.chat_input("Posez votre question ou décrivez votre demande…")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    try:
        process = st.session_state.process
        if process and process["active"]:
            answer = orchestration.handle_message(process, user_input, deps)
            st.session_state.last_call_info = {"Contexte": "Processus de révision",
                                               "Mode de sécurité": mode}
        elif st.session_state.mcp_tools and orchestration.detect_revision_intent(MODEL, user_input):
            process = orchestration.new_process(trusted)
            process["trip_id"] = orchestration.find_trip_id(user_input)
            st.session_state.process = process
            answer = orchestration.advance_after_start(process, user_input, deps)
            st.session_state.last_call_info = {"Contexte": "Processus de révision (démarrage)",
                                               "Mode de sécurité": mode}
        else:
            # Chat libre : uniquement les tools de LECTURE (jamais l'écriture).
            policy.scan_for_injection(user_input, "user_message")
            context = ""
            sources = None
            if use_rag:
                sources = rag.search(DB_PATH, user_input, top_k=top_k)
                raw_context = rag.build_context(sources)
                policy.scan_for_injection(raw_context, "rag_document")
                context = policy.wrap_untrusted(raw_context, security.UNTRUSTED_DOCUMENTS_TAG)

            prompt = system_prompt
            if policy.protected:
                prompt += "\n" + security.SecurityPolicy.untrusted_prompt_rule()
            messages = [{"role": "system", "content": prompt}]
            if context:
                messages.append({"role": "system",
                                 "content": "Contexte documentaire :\n\n" + context})
            messages.extend(st.session_state.messages)
            answer, tool_calls, mcp_available = mcp_client.answer(
                MCP_URL, MODEL, messages,
                {"temperature": temperature, "num_predict": max_tokens})
            st.session_state.last_sources = sources
            st.session_state.last_tool_calls = tool_calls
            st.session_state.last_call_info = {
                "Contexte": "Chat libre", "Mode de sécurité": mode,
                "Mode RAG": "Avec RAG" if use_rag else "Sans RAG",
                "Serveur MCP": "connecté" if mcp_available else "injoignable",
                "Tools appelés": len(tool_calls),
                "Tools proposés au modèle": "lecture seule (écriture exclue)",
            }
        st.session_state.messages.append({"role": "assistant", "content": answer})
    except Exception as error:  # noqa: BLE001
        st.error("Une erreur est survenue (Ollama, serveur MCP ou base indisponible). "
                 f"Détail : {error}")

# --- Fil de conversation -----------------------------------------------------
for message in st.session_state.messages:
    st.markdown(f"**{'Vous' if message['role'] == 'user' else 'Assistant'} :** "
                f"{message['content']}")

# --- Boutons de confirmation (étape 4) ---------------------------------------
process = st.session_state.process
if process and process["active"] and process.get("need_confirmation"):
    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button("✅ Confirmer", use_container_width=True):
        message = orchestration.confirm(process, deps)
        st.session_state.messages.append({"role": "assistant", "content": message})
        if process.get("last_tool_call"):
            st.session_state.last_tool_calls = [process["last_tool_call"]]
        st.rerun()
    if col_cancel.button("✖ Annuler", use_container_width=True):
        message = orchestration.cancel(process)
        st.session_state.messages.append({"role": "assistant", "content": message})
        st.rerun()

# --- Journal des événements de sécurité --------------------------------------
st.subheader("Événements de sécurité")
if not policy.events:
    st.caption("Aucun événement pour l'instant.")
else:
    colours = {"REFUSED": "🟥", "DETECTED": "🟧", "IGNORED": "🟨", "ALLOWED": "🟩"}
    for event in reversed(policy.events[-15:]):
        st.markdown(f"{colours.get(event.action, '·')} `{event.timestamp}` "
                    f"**[{event.action}]** `{event.event_type}` — {event.details} "
                    f"*(source : {event.source}, gravité : {event.severity})*")

# --- Informations techniques -------------------------------------------------
if st.session_state.last_call_info:
    with st.expander("Informations techniques sur le dernier appel", expanded=True):
        for label, value in st.session_state.last_call_info.items():
            st.markdown(f"- **{label} :** {value}")

        if st.session_state.last_tool_calls:
            st.markdown("**Appels de tools :**")
            for call in st.session_state.last_tool_calls:
                result = call["result"].replace("\n", " ")
                result = result[:300] + "…" if len(result) > 300 else result
                st.markdown(f"- `{call['name']}` — paramètres : `{call['arguments']}`\n\n"
                            f"  > {result}")

        if st.session_state.last_sources:
            st.markdown("**Sources retrouvées (RAG) :**")
            for source in st.session_state.last_sources:
                excerpt = source["content"].replace("\n", " ")
                excerpt = excerpt[:200] + "…" if len(excerpt) > 200 else excerpt
                st.markdown(f"- `{source['score']:.3f}` — **{source['document']}** "
                            f"({source['heading']})\n\n  > {excerpt}")
