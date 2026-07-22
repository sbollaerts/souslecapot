"""Assistant Bikaroo — Labo 4 : orchestrer un processus métier.

Ce labo fait passer l'assistant d'appels ponctuels (labos 1-3) à un PROCESSUS
explicite en 5 étapes, avec un état visible et une action d'écriture (créer une
demande de révision) déclenchée uniquement après confirmation explicite.

Le contrôle des étapes est déterministe (module orchestration) ; le LLM ne fait
que comprendre l'utilisateur et formuler les messages. En dehors du processus,
l'assistant garde le comportement du labo 3 (chat + RAG + tools de lecture).
"""

import json
from pathlib import Path

import streamlit as st

import mcp_client
import orchestration
import rag

MODEL = "qwen2.5:3b"
MCP_URL = "http://localhost:8000/mcp"

# app.py est dans .../python/ ; le corpus dans .../ressources/.
CORPUS_DIR = Path(__file__).resolve().parents[1] / "ressources"
DB_PATH = Path(__file__).resolve().parent / "bikaroo_rag.db"

DEFAULT_SYSTEM_PROMPT = (
    "Tu es l'Assistant Bikaroo, l'assistant virtuel de Bikaroo, une société de "
    "vélos partagés à Bruxelles. Tu réponds toujours en français, de manière "
    "claire, polie et concise.\n"
    "Tu disposes d'un contexte documentaire (procédures, tarifs, règles) et de "
    "tools de lecture (statut d'un trajet, informations d'un membre). Appuie-toi "
    "dessus et n'invente pas : si l'information manque, dis-le."
)

st.set_page_config(page_title="Assistant Bikaroo — Labo 4", page_icon="🚲")

# --- État de session ---------------------------------------------------------
for key, default in [
    ("messages", []), ("last_call_info", None), ("last_sources", None),
    ("last_tool_calls", None), ("process", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# --- Indexation du corpus (une fois au démarrage) ----------------------------
if "index_size" not in st.session_state:
    try:
        with st.spinner("Indexation du corpus documentaire…"):
            st.session_state.index_size = rag.ensure_index(DB_PATH, CORPUS_DIR)
    except Exception as error:  # noqa: BLE001
        st.error(
            "Impossible d'indexer le corpus. Vérifiez qu'Ollama est lancé et que le "
            f"modèle « {rag.EMBEDDING_MODEL} » est téléchargé.\n\nDétail : {error}"
        )
        st.stop()

# --- Connexion au serveur MCP ------------------------------------------------
if "mcp_tools" not in st.session_state:
    try:
        st.session_state.mcp_tools = mcp_client.list_tool_names(MCP_URL)
    except Exception:  # noqa: BLE001
        st.session_state.mcp_tools = None


# --- Dépendances passées à l'orchestration (tools MCP + RAG) -----------------
def _make_deps(top_k):
    return orchestration.Deps(
        model=MODEL,
        get_trip_status=lambda tid: json.loads(
            mcp_client.call_tool(MCP_URL, "get_trip_status", {"trip_id": tid})),
        create_revision=lambda m, t, d, i: json.loads(
            mcp_client.call_tool(MCP_URL, "create_revision_request", {
                "member_id": m, "trip_id": t,
                "description": d, "informations_complementaires": i})),
        rag_context=lambda q: rag.build_context(rag.search(DB_PATH, q, top_k=top_k)),
    )


# --- Barre latérale ----------------------------------------------------------
with st.sidebar:
    st.header("Configuration")

    member_id = st.text_input("Membre connecté (identifiant)", value="MBR-1042",
                              help="Pas d'authentification réelle dans ce labo : "
                                   "le membre est simplement pré-configuré ici.")

    use_rag = st.toggle("Avec RAG (hors processus)", value=True)
    system_prompt = st.text_area("Prompt système (hors processus)",
                                 value=DEFAULT_SYSTEM_PROMPT, height=160)

    st.subheader("Paramètres de génération")
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

deps = _make_deps(top_k)

# --- En-tête + indicateur d'étape --------------------------------------------
st.title("🚲 Assistant Bikaroo")
st.caption(f"Labo 4 — Orchestration (Ollama · {MODEL} + {rag.EMBEDDING_MODEL} · "
           f"{st.session_state.index_size} chunks · serveur MCP)")

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
            # Un processus est en cours : l'orchestration pilote (déterministe).
            answer = orchestration.handle_message(process, user_input, deps)
            st.session_state.last_call_info = {"Contexte": "Processus de révision"}
        elif st.session_state.mcp_tools and orchestration.detect_revision_intent(MODEL, user_input):
            # Intention de contestation détectée : on démarre le processus.
            process = orchestration.new_process(member_id)
            process["trip_id"] = orchestration.find_trip_id(user_input)
            st.session_state.process = process
            answer = orchestration.advance_after_start(process, deps)
            st.session_state.last_call_info = {"Contexte": "Processus de révision (démarrage)"}
        else:
            # Hors processus : comportement du labo 3 (chat + RAG + tools de lecture).
            context = ""
            sources = None
            if use_rag:
                sources = rag.search(DB_PATH, user_input, top_k=top_k)
                context = rag.build_context(sources)
            messages = [{"role": "system", "content": system_prompt}]
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
                "Contexte": "Chat libre", "Mode": "Avec RAG" if use_rag else "Sans RAG",
                "Serveur MCP": "connecté" if mcp_available else "injoignable",
                "Tools appelés": len(tool_calls),
            }
        st.session_state.messages.append({"role": "assistant", "content": answer})
    except Exception as error:  # noqa: BLE001
        st.error("Une erreur est survenue (Ollama, serveur MCP ou base indisponible). "
                 f"Détail : {error}")

# --- Fil de conversation -----------------------------------------------------
for message in st.session_state.messages:
    st.markdown(f"**{'Vous' if message['role'] == 'user' else 'Assistant'} :** "
                f"{message['content']}")

# --- Boutons de confirmation (étape 4 uniquement) ----------------------------
process = st.session_state.process
if process and process["active"] and process.get("need_confirmation"):
    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button("✅ Confirmer", use_container_width=True):
        message = orchestration.confirm(process, deps)
        st.session_state.messages.append({"role": "assistant", "content": message})
        st.session_state.last_tool_calls = [process["last_tool_call"]]
        st.rerun()
    if col_cancel.button("✖ Annuler", use_container_width=True):
        message = orchestration.cancel(process)
        st.session_state.messages.append({"role": "assistant", "content": message})
        st.rerun()

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
