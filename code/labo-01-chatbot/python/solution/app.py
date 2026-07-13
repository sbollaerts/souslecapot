"""Assistant Bikaroo — Labo 1 : chatbot local minimal.

Ce script montre le mécanisme de base d'un appel à un LLM local via Ollama :
un prompt système + l'historique de la conversation sont envoyés au modèle,
qui génère une réponse. Les principaux paramètres de génération (température,
nombre maximum de tokens) sont exposés au lecteur pour qu'il en observe l'effet.
"""

import time

import ollama
import streamlit as st

# Modèle fixé pour ce labo (bonnes performances en français).
MODEL = "mistral"

# Prompt système par défaut : il positionne l'assistant, mais ne lui donne
# volontairement aucune connaissance des documents internes de Bikaroo.
# (Cette connaissance documentaire sera introduite au labo 2, avec le RAG.)
DEFAULT_SYSTEM_PROMPT = (
    "Tu es l'Assistant Bikaroo, l'assistant virtuel de Bikaroo, une société "
    "de vélos partagés à Bruxelles. Tu réponds toujours en français, de "
    "manière claire, polie et concise."
)

st.set_page_config(page_title="Assistant Bikaroo — Labo 1", page_icon="🚲")

# --- État de session ---------------------------------------------------------
# Streamlit ré-exécute tout le script à chaque interaction : on conserve donc
# l'historique et les infos du dernier appel dans st.session_state.
if "messages" not in st.session_state:
    st.session_state.messages = []  # liste de {"role": "user"|"assistant", "content": ...}
if "last_call_info" not in st.session_state:
    st.session_state.last_call_info = None


def call_ollama(system_prompt, history, temperature, max_tokens):
    """Appelle le modèle local et renvoie (réponse, durée en secondes)."""
    # On reconstruit à chaque appel la liste complète des messages :
    # le prompt système d'abord, puis tout l'historique de la conversation.
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)

    start = time.time()
    response = ollama.chat(
        model=MODEL,
        messages=messages,
        options={
            "temperature": temperature,
            # num_predict = nombre maximum de tokens générés en sortie.
            "num_predict": max_tokens,
        },
    )
    duration = time.time() - start
    return response["message"]["content"], duration


# --- Barre latérale : prompt système et paramètres de génération -------------
with st.sidebar:
    st.header("Configuration")

    system_prompt = st.text_area(
        "Prompt système",
        value=DEFAULT_SYSTEM_PROMPT,
        height=180,
        help="Définit le rôle et le ton de l'assistant. Modifiable librement.",
    )

    st.subheader("Paramètres de génération")
    temperature = st.slider(
        "Température",
        min_value=0.0,
        max_value=1.0,
        value=0.7,
        step=0.1,
        help="Plus la valeur est élevée, plus les réponses sont créatives "
        "et variées ; plus elle est basse, plus elles sont répétables.",
    )
    max_tokens = st.slider(
        "Nombre maximum de tokens en sortie",
        min_value=64,
        max_value=2048,
        value=512,
        step=64,
    )

    # Le bouton « Effacer » vide la conversation mais conserve le prompt système
    # tel qu'il est configuré ci-dessus.
    if st.button("Effacer la conversation"):
        st.session_state.messages = []
        st.session_state.last_call_info = None
        st.rerun()

# --- En-tête -----------------------------------------------------------------
st.title("🚲 Assistant Bikaroo")
st.caption(f"Labo 1 — Chatbot local (Ollama · modèle « {MODEL} »)")

# --- Saisie utilisateur ------------------------------------------------------
user_input = st.chat_input("Posez votre question…")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    try:
        answer, duration = call_ollama(
            system_prompt, st.session_state.messages, temperature, max_tokens
        )
        st.session_state.messages.append({"role": "assistant", "content": answer})
        st.session_state.last_call_info = {
            "Modèle": MODEL,
            "Température": temperature,
            "Max tokens": max_tokens,
            "Durée de génération": f"{duration:.2f} s",
        }
    except Exception as error:  # noqa: BLE001 — message volontairement simple pour le lecteur
        st.error(
            f"Impossible de contacter Ollama. Vérifiez qu'Ollama est bien lancé "
            f"et que le modèle « {MODEL} » est téléchargé "
            f"(commande : `ollama pull {MODEL}`).\n\nDétail technique : {error}"
        )

# --- Fil de conversation -----------------------------------------------------
# Affichage simple, dans l'ordre chronologique : la clarté prime sur l'esthétique.
for message in st.session_state.messages:
    role = "Vous" if message["role"] == "user" else "Assistant"
    st.markdown(f"**{role} :** {message['content']}")

# --- Informations techniques sur le dernier appel ----------------------------
# Zone volontairement simple : elle sera enrichie dans les labos suivants
# (chunks retrouvés, appels de tools, traces…). D'où l'affichage générique
# à partir d'un simple dictionnaire clé/valeur, facile à étendre.
if st.session_state.last_call_info:
    with st.expander("Informations techniques sur le dernier appel", expanded=True):
        for label, value in st.session_state.last_call_info.items():
            st.markdown(f"- **{label} :** {value}")
