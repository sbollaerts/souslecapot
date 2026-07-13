"""Assistant Bikaroo — Labo 1 : chatbot local minimal (squelette de départ).

La plomberie technique (interface Streamlit, import du client Ollama, gestion
de l'état de session) est déjà en place. À vous d'implémenter le cœur du labo :
le prompt système, l'historique de conversation, l'appel au modèle et les
paramètres de génération. Suivez les commentaires « TODO » ci-dessous.
"""

import time

import ollama  # client Ollama officiel — déjà installé via requirements.txt
import streamlit as st

# Modèle fixé pour ce labo (bonnes performances en français).
MODEL = "mistral"

# TODO (étape 1) — Prompt système par défaut.
# Rédigez un prompt qui positionne l'assistant comme « Assistant Bikaroo »
# (société de vélos partagés à Bruxelles), répondant en français.
# N'y mettez AUCUNE connaissance des documents internes de Bikaroo : ce sera
# l'objet du labo 2 (RAG).
DEFAULT_SYSTEM_PROMPT = ""

st.set_page_config(page_title="Assistant Bikaroo — Labo 1", page_icon="🚲")

# --- État de session ---------------------------------------------------------
# Streamlit ré-exécute tout le script à chaque interaction : on conserve donc
# l'historique et les infos du dernier appel dans st.session_state.
if "messages" not in st.session_state:
    st.session_state.messages = []  # liste de {"role": "user"|"assistant", "content": ...}
if "last_call_info" not in st.session_state:
    st.session_state.last_call_info = None

# --- Barre latérale : prompt système et paramètres de génération -------------
with st.sidebar:
    st.header("Configuration")

    # TODO (étape 2) — Remplacez ces valeurs figées par de vrais contrôles :
    #   * une zone de texte éditable (st.text_area) pour le prompt système,
    #     initialisée avec DEFAULT_SYSTEM_PROMPT ;
    #   * un curseur (st.slider) pour la température (0.0 à 1.0) ;
    #   * un curseur pour le nombre maximum de tokens en sortie.
    system_prompt = DEFAULT_SYSTEM_PROMPT
    temperature = 0.7
    max_tokens = 512

    # TODO (étape 5) — Ajoutez un bouton « Effacer la conversation » qui vide
    # l'historique (st.session_state.messages) et last_call_info, mais conserve
    # le prompt système. Pensez à st.rerun() pour rafraîchir l'affichage.

# --- En-tête -----------------------------------------------------------------
st.title("🚲 Assistant Bikaroo")
st.caption(f"Labo 1 — Chatbot local (Ollama · modèle « {MODEL} »)")

# --- Saisie utilisateur ------------------------------------------------------
user_input = st.chat_input("Posez votre question…")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})

    # TODO (étape 3) — Appel au modèle.
    #   a) Construisez la liste des messages à envoyer : le prompt système en
    #      premier ({"role": "system", ...}), puis tout st.session_state.messages.
    #   b) Appelez ollama.chat(model=MODEL, messages=..., options={...}) en
    #      passant "temperature" et "num_predict" (= max_tokens) dans options.
    #   c) Mesurez la durée de l'appel (time.time() avant/après).
    #   d) Ajoutez la réponse à l'historique
    #      ({"role": "assistant", "content": ...}) et renseignez
    #      st.session_state.last_call_info (modèle, paramètres, durée).
    #   e) Entourez l'appel d'un try/except pour afficher un message clair
    #      (st.error) si Ollama n'est pas lancé ou si le modèle est absent.
    pass

# --- Fil de conversation -----------------------------------------------------
# Affichage simple, dans l'ordre chronologique : la clarté prime sur l'esthétique.
for message in st.session_state.messages:
    role = "Vous" if message["role"] == "user" else "Assistant"
    st.markdown(f"**{role} :** {message['content']}")

# TODO (étape 4) — Zone d'informations techniques.
# Si st.session_state.last_call_info existe, affichez-le (par ex. dans un
# st.expander) : modèle, température, max tokens, durée de génération.
