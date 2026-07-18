"""Assistant Bikaroo — Labo 2 : RAG documentaire (squelette de départ).

On part de la solution du labo 1 : la génération via Ollama fonctionne déjà.
À vous d'ajouter la chaîne RAG en complétant les « TODO » ici et dans rag.py :
indexation du corpus au démarrage, recherche des chunks pertinents et injection
du contexte dans le prompt lorsque le mode « Avec RAG » est activé.
"""

import time
from pathlib import Path

import ollama
import streamlit as st

import rag

# Modèle de génération (identique au labo 1).
MODEL = "qwen2.5:3b"

# Emplacements : c'est l'application qui décide où lire le corpus et où écrire
# l'index ; le module rag les reçoit en paramètre.
# app.py est dans .../python/depart/ ; le corpus dans .../ressources/.
CORPUS_DIR = Path(__file__).resolve().parents[2] / "ressources"

# Base SQLite de l'index vectoriel (mise en cache à côté de l'application).
DB_PATH = Path(__file__).resolve().parent / "bikaroo_rag.db"

# Prompt système par défaut : il invite le modèle à s'appuyer sur le contexte
# documentaire fourni et à reconnaître explicitement l'absence d'information.
DEFAULT_SYSTEM_PROMPT = (
    "Tu es l'Assistant Bikaroo, l'assistant virtuel de Bikaroo, une société de "
    "vélos partagés à Bruxelles. Tu réponds toujours en français, de manière "
    "claire, polie et concise.\n"
    "Lorsqu'un contexte documentaire t'est fourni, appuie-toi uniquement sur ce "
    "contexte pour répondre et cite les documents sources utilisés. Si "
    "l'information demandée ne figure pas dans le contexte, dis-le clairement "
    "au lieu d'inventer une réponse."
)

st.set_page_config(page_title="Assistant Bikaroo — Labo 2", page_icon="🚲")

# --- État de session ---------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []
if "last_call_info" not in st.session_state:
    st.session_state.last_call_info = None
if "last_sources" not in st.session_state:
    st.session_state.last_sources = None

# --- Indexation du corpus (une seule fois au démarrage) ----------------------
# Tant que rag.ensure_index() n'est pas implémenté, index_size vaudra 0.
if "index_size" not in st.session_state:
    with st.spinner("Indexation du corpus documentaire…"):
        st.session_state.index_size = rag.ensure_index(DB_PATH, CORPUS_DIR)


def call_ollama(system_prompt, context, history, temperature, max_tokens):
    """Appelle le modèle. Si un contexte RAG est fourni, il est ajouté aux messages."""
    messages = [{"role": "system", "content": system_prompt}]
    if context:
        messages.append(
            {
                "role": "system",
                "content": "Contexte documentaire (extraits de la base de "
                "connaissances Bikaroo) :\n\n" + context,
            }
        )
    messages.extend(history)

    start = time.time()
    response = ollama.chat(
        model=MODEL,
        messages=messages,
        options={"temperature": temperature, "num_predict": max_tokens},
    )
    return response["message"]["content"], time.time() - start


# --- Barre latérale : configuration ------------------------------------------
with st.sidebar:
    st.header("Configuration")

    use_rag = st.toggle("Avec RAG", value=True,
                        help="Activé : la réponse s'appuie sur le corpus Bikaroo. "
                             "Désactivé : le modèle répond seul, comme au labo 1.")

    system_prompt = st.text_area("Prompt système", value=DEFAULT_SYSTEM_PROMPT, height=200)

    st.subheader("Paramètres de génération")
    temperature = st.slider("Température", 0.0, 1.0, 0.7, 0.1)
    max_tokens = st.slider("Nombre maximum de tokens en sortie", 64, 2048, 512, 64)
    top_k = st.slider("Nombre de chunks récupérés (top-k)", 1, 6, 4, 1,
                     help="Nombre d'extraits documentaires fournis au modèle en mode RAG.")

    if st.button("Effacer la conversation"):
        st.session_state.messages = []
        st.session_state.last_call_info = None
        st.session_state.last_sources = None
        st.rerun()

# --- En-tête -----------------------------------------------------------------
st.title("🚲 Assistant Bikaroo")
st.caption(
    f"Labo 2 — RAG documentaire (Ollama · {MODEL} + {rag.EMBEDDING_MODEL} · "
    f"{st.session_state.index_size} chunks indexés)"
)

# --- Saisie utilisateur ------------------------------------------------------
user_input = st.chat_input("Posez votre question…")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    try:
        # En mode RAG : rechercher les chunks pertinents et construire le contexte.
        context = ""
        sources = None
        if use_rag:
            # TODO (étape 6) — Brancher le RAG :
            #   sources = rag.search(DB_PATH, user_input, top_k=top_k)
            #   context = rag.build_context(sources)
            pass

        answer, duration = call_ollama(
            system_prompt, context, st.session_state.messages, temperature, max_tokens
        )
        st.session_state.messages.append({"role": "assistant", "content": answer})
        st.session_state.last_sources = sources
        st.session_state.last_call_info = {
            "Mode": "Avec RAG" if use_rag else "Sans RAG",
            "Modèle": MODEL,
            "Modèle d'embeddings": rag.EMBEDDING_MODEL if use_rag else "—",
            "Température": temperature,
            "Max tokens": max_tokens,
            "Chunks récupérés (top-k)": top_k if use_rag else "—",
            "Durée de génération": f"{duration:.2f} s",
        }
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

        # TODO (étape 7) — Afficher les sources / chunks retrouvés (mode RAG) :
        # pour chaque élément de st.session_state.last_sources, afficher le score,
        # le document, la section et un court extrait.
