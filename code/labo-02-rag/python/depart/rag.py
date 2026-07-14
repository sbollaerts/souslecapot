"""Chaîne RAG de l'Assistant Bikaroo — Labo 2 (squelette de départ).

La plomberie est en place : accès au corpus (CORPUS_DIR), modèle d'embeddings
et fonction embed_text() déjà câblée sur Ollama. À vous d'implémenter le cœur du
RAG en suivant les « TODO » :

    documents Markdown → chunks → embeddings → index SQLite → recherche cosinus
"""

import sqlite3
from pathlib import Path

import ollama

# Modèle d'embeddings (multilingue, bonnes performances en français).
EMBEDDING_MODEL = "bge-m3"

# Dossier du corpus documentaire, partagé par les deux implémentations.
# rag.py est dans .../python/depart/ ; le corpus dans .../ressources/.
CORPUS_DIR = Path(__file__).resolve().parents[2] / "ressources"


# --- 1. Découpage du corpus en chunks ----------------------------------------

def load_chunks():
    """Charge les documents 01→06 du corpus et les découpe en chunks.

    TODO (étape 1) :
      * parcourir CORPUS_DIR.glob("0*.md") (ne sélectionne que 01→06) ;
      * pour chaque fichier, retirer l'éventuel bloc de métadonnées YAML en tête
        (délimité par des lignes « --- ») ;
      * découper le corps sur les titres de section « ## » (le corpus est déjà
        organisé en sections thématiques) ;
      * renvoyer une liste de dictionnaires
        {"document": nom_fichier, "heading": sous-titre, "content": texte}.
        Astuce : préfixer le texte du titre du document et de la section améliore
        le retrieval.
    """
    # TODO : à implémenter
    return []


# --- 2. Embeddings (déjà câblé) ----------------------------------------------

def embed_text(text):
    """Calcule l'embedding d'un texte via le modèle bge-m3 (Ollama)."""
    response = ollama.embed(model=EMBEDDING_MODEL, input=text)
    return response["embeddings"][0]


# --- 3. Indexation SQLite ----------------------------------------------------

def build_index(db_path):
    """(Re)construit l'index SQLite à partir du corpus. Renvoie le nb de chunks.

    TODO (étape 3) :
      * appeler load_chunks() ;
      * créer une table SQLite « chunks » (document, heading, content, embedding) ;
      * pour chaque chunk, calculer embed_text(chunk["content"]) et l'insérer
        (par ex. l'embedding sérialisé en JSON) ;
      * renvoyer le nombre de chunks indexés.
    """
    # TODO : à implémenter
    return 0


def ensure_index(db_path):
    """Construit l'index seulement s'il est absent. Renvoie le nb de chunks.

    TODO (étape 3) : vérifier si la table « chunks » existe et contient des
    lignes ; si oui renvoyer le nombre de lignes, sinon appeler build_index().
    """
    # TODO : à implémenter (pour l'instant : aucun index construit)
    return 0


# --- 4. Recherche sémantique -------------------------------------------------

def search(db_path, question, top_k=4):
    """Renvoie les top_k chunks les plus proches de la question.

    TODO (étape 4) :
      * calculer l'embedding de la question (embed_text) ;
      * charger tous les chunks + embeddings depuis SQLite ;
      * calculer la similarité cosinus entre la question et chaque chunk ;
      * trier par score décroissant et renvoyer les top_k, sous la forme
        [{"document", "heading", "content", "score"}, ...].
    """
    # TODO : à implémenter
    return []


# --- 5. Construction du contexte RAG -----------------------------------------

def build_context(chunks):
    """Assemble les chunks retrouvés en un bloc de contexte cité par source.

    TODO (étape 5) : concaténer les chunks en un texte lisible, en indiquant la
    source de chaque extrait (document + section) pour que le modèle puisse citer.
    """
    # TODO : à implémenter
    return ""
