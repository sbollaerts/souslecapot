"""Assistant Bikaroo — Labo 3 : tools et MCP.

Ce labo reprend le chatbot + RAG du labo 2 et ajoute l'accès à des données
opérationnelles (membres, trajets) via un serveur MCP exposant des tools. Le
modèle décide seul d'appeler un tool ; le résultat est réinjecté dans la
conversation. RAG (connaissance documentaire) et tools (donnée opérationnelle)
se combinent : les tools s'ajoutent, ils ne remplacent pas le RAG.
"""

import time
from pathlib import Path

import streamlit as st

import mcp_client
import rag

# Modèle de génération. Ce labo demande un appel de tools fiable : on utilise
# qwen2.5:3b, léger (~2 Go) et le plus régulier de notre comparatif pour décider
# d'appeler un tool, même en présence d'un contexte RAG. Sur une machine plus
# confortable, « qwen2.5:7b » est encore plus stable. Voir la section « Choix
# techniques » du README. Les embeddings restent bge-m3.
MODEL = "qwen2.5:3b"

# URL du serveur MCP (à démarrer AVANT le client — voir le README).
MCP_URL = "http://localhost:8000/mcp"

# Emplacements : c'est l'application qui décide où lire le corpus et où écrire
# l'index ; le module rag les reçoit en paramètre.
# app.py est dans .../python/solution/ ; le corpus dans .../ressources/.
CORPUS_DIR = Path(__file__).resolve().parents[2] / "ressources"
DB_PATH = Path(__file__).resolve().parent / "bikaroo_rag.db"

# Prompt système : il distingue les deux sources d'information à disposition de
# l'assistant — la connaissance documentaire (contexte RAG) et les données
# opérationnelles (tools). Il invite à ne pas inventer.
DEFAULT_SYSTEM_PROMPT = (
    "Tu es l'Assistant Bikaroo, l'assistant virtuel de Bikaroo, une société de "
    "vélos partagés à Bruxelles. Tu réponds toujours en français, de manière "
    "claire, polie et concise.\n"
    "Tu disposes de deux sources d'information :\n"
    "- un contexte documentaire (procédures, tarifs, règles) : appuie-toi dessus "
    "pour les questions générales et cite les documents sources ;\n"
    "- des tools qui donnent accès aux données opérationnelles réelles (statut "
    "d'un trajet, informations d'un membre) : appelle-les lorsqu'on te demande "
    "une donnée précise et actuelle (par exemple le statut d'un trajet).\n"
    "Si l'information ne figure ni dans le contexte ni dans le résultat d'un "
    "tool, dis-le clairement au lieu d'inventer."
)

st.set_page_config(page_title="Assistant Bikaroo — Labo 3", page_icon="🚲")

# --- État de session ---------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []
if "last_call_info" not in st.session_state:
    st.session_state.last_call_info = None
if "last_sources" not in st.session_state:
    st.session_state.last_sources = None
if "last_tool_calls" not in st.session_state:
    st.session_state.last_tool_calls = None

# --- Indexation du corpus (une seule fois au démarrage) ----------------------
if "index_size" not in st.session_state:
    try:
        with st.spinner("Indexation du corpus documentaire…"):
            st.session_state.index_size = rag.ensure_index(DB_PATH, CORPUS_DIR)
    except Exception as error:  # noqa: BLE001
        st.error(
            "Impossible d'indexer le corpus. Vérifiez qu'Ollama est lancé et que "
            f"le modèle d'embeddings « {rag.EMBEDDING_MODEL} » est téléchargé "
            f"(commande : `ollama pull {rag.EMBEDDING_MODEL}`), et que le dossier "
            f"« {CORPUS_DIR} » existe.\n\nDétail technique : {error}"
        )
        st.stop()

# --- Connexion au serveur MCP (vérifiée au démarrage) ------------------------
# On récupère la liste des tools ; si le serveur n'est pas joignable, l'app
# fonctionne quand même (chat + RAG), mais sans accès aux tools.
if "mcp_tools" not in st.session_state:
    try:
        st.session_state.mcp_tools = mcp_client.list_tool_names(MCP_URL)
    except Exception:  # noqa: BLE001 — serveur MCP non démarré
        st.session_state.mcp_tools = None


# --- Barre latérale : configuration ------------------------------------------
with st.sidebar:
    st.header("Configuration")

    use_rag = st.toggle("Avec RAG", value=True,
                        help="Activé : la réponse s'appuie sur le corpus Bikaroo. "
                             "Désactivé : le modèle répond seul, comme au labo 1.")

    system_prompt = st.text_area("Prompt système", value=DEFAULT_SYSTEM_PROMPT, height=240)

    st.subheader("Paramètres de génération")
    temperature = st.slider("Température", 0.0, 1.0, 0.7, 0.1)
    max_tokens = st.slider("Nombre maximum de tokens en sortie", 64, 2048, 512, 64)
    top_k = st.slider("Nombre de chunks récupérés (top-k)", 1, 6, 4, 1,
                     help="Nombre d'extraits documentaires fournis au modèle en mode RAG.")

    st.subheader("Serveur MCP")
    if st.session_state.mcp_tools:
        st.success("Connecté · tools : " + ", ".join(st.session_state.mcp_tools))
    else:
        st.warning("Serveur MCP injoignable. Démarrez-le, puis rechargez la page.")

    if st.button("Effacer la conversation"):
        st.session_state.messages = []
        st.session_state.last_call_info = None
        st.session_state.last_sources = None
        st.session_state.last_tool_calls = None
        st.rerun()

# --- En-tête -----------------------------------------------------------------
st.title("🚲 Assistant Bikaroo")
st.caption(
    f"Labo 3 — Tools et MCP (Ollama · {MODEL} + {rag.EMBEDDING_MODEL} · "
    f"{st.session_state.index_size} chunks · serveur MCP)"
)

# --- Saisie utilisateur ------------------------------------------------------
user_input = st.chat_input("Posez votre question…")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    try:
        # 1. En mode RAG : rechercher les chunks pertinents et construire le contexte.
        context = ""
        sources = None
        if use_rag:
            sources = rag.search(DB_PATH, user_input, top_k=top_k)
            context = rag.build_context(sources)

        # 2. Construire les messages : prompt système, puis (en RAG) le contexte
        #    documentaire, puis l'historique de la conversation.
        messages = [{"role": "system", "content": system_prompt}]
        if context:
            messages.append(
                {
                    "role": "system",
                    "content": "Contexte documentaire (extraits de la base de "
                    "connaissances Bikaroo) :\n\n" + context,
                }
            )
        messages.extend(st.session_state.messages)

        # 3. Laisser le modèle répondre, avec accès aux tools MCP.
        start = time.time()
        answer, tool_calls, mcp_available = mcp_client.answer(
            MCP_URL, MODEL, messages,
            {"temperature": temperature, "num_predict": max_tokens},
        )
        duration = time.time() - start

        st.session_state.messages.append({"role": "assistant", "content": answer})
        st.session_state.last_sources = sources
        st.session_state.last_tool_calls = tool_calls
        st.session_state.last_call_info = {
            "Mode": "Avec RAG" if use_rag else "Sans RAG",
            "Modèle": MODEL,
            "Modèle d'embeddings": rag.EMBEDDING_MODEL if use_rag else "—",
            "Serveur MCP": "connecté" if mcp_available else "injoignable",
            "Tools appelés": len(tool_calls),
            "Température": temperature,
            "Max tokens": max_tokens,
            "Chunks récupérés (top-k)": top_k if use_rag else "—",
            "Durée": f"{duration:.2f} s",
        }
        if not mcp_available:
            st.warning(
                "Le serveur MCP n'a pas pu être joint : réponse générée sans "
                "accès aux tools. Démarrez le serveur MCP (voir le README) pour "
                "les données opérationnelles."
            )
    except Exception as error:  # noqa: BLE001 — message volontairement simple
        st.error(
            f"Impossible de contacter Ollama. Vérifiez qu'Ollama est bien lancé et "
            f"que les modèles « {MODEL} » et « {rag.EMBEDDING_MODEL} » sont "
            f"téléchargés.\n\nDétail technique : {error}"
        )

# --- Fil de conversation -----------------------------------------------------
for message in st.session_state.messages:
    role = "Vous" if message["role"] == "user" else "Assistant"
    st.markdown(f"**{role} :** {message['content']}")

# --- Informations techniques sur le dernier appel ----------------------------
if st.session_state.last_call_info:
    with st.expander("Informations techniques sur le dernier appel", expanded=True):
        for label, value in st.session_state.last_call_info.items():
            st.markdown(f"- **{label} :** {value}")

        # Appels de tools (MCP) effectués pour cette réponse.
        if st.session_state.last_tool_calls:
            st.markdown("**Appels de tools :**")
            for call in st.session_state.last_tool_calls:
                result = call["result"].replace("\n", " ")
                if len(result) > 300:
                    result = result[:300] + "…"
                st.markdown(
                    f"- `{call['name']}` — paramètres : `{call['arguments']}`\n\n"
                    f"  > {result}"
                )

        # Sources / chunks retrouvés (uniquement en mode RAG).
        if st.session_state.last_sources:
            st.markdown("**Sources retrouvées (RAG) :**")
            for source in st.session_state.last_sources:
                excerpt = source["content"].replace("\n", " ")
                if len(excerpt) > 200:
                    excerpt = excerpt[:200] + "…"
                st.markdown(
                    f"- `{source['score']:.3f}` — **{source['document']}** "
                    f"({source['heading']})\n\n  > {excerpt}"
                )
