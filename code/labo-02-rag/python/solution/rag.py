"""Chaîne RAG minimale pour l'Assistant Bikaroo — Labo 2.

Ce module contient toute la logique de Retrieval-Augmented Generation :

    documents Markdown → chunks → embeddings → index SQLite → recherche cosinus

Il est volontairement simple et lisible : la recherche de similarité est
calculée en Python, en mémoire, sur l'ensemble des chunks. Ce choix ne passe
pas à l'échelle au-delà de quelques centaines de chunks, mais suffit largement
au corpus de ce labo et évite toute dépendance à une base vectorielle dédiée.
"""

import json
import math
import sqlite3
from pathlib import Path

import ollama

# Modèle d'embeddings (multilingue, bonnes performances en français).
EMBEDDING_MODEL = "bge-m3"

# Le dossier du corpus et le chemin de la base ne sont pas définis ici : ce sont
# des décisions de l'application, qui les passe en paramètre (voir app.py).


# --- 1. Découpage du corpus en chunks ----------------------------------------

def _strip_frontmatter(text):
    """Retire l'éventuel bloc de métadonnées YAML en tête de fichier."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:]
    return text


def _split_sections(body):
    """Sépare un document en (titre, [(sous-titre, contenu), ...]).

    On découpe sur les titres de section « ## » : le corpus est déjà organisé
    en sections thématiques, ce qui donne des chunks cohérents sans découpage
    arbitraire par nombre de caractères.
    """
    title = ""
    sections = []
    current_heading = "Introduction"
    current_lines = []

    for line in body.splitlines():
        if line.startswith("## "):
            if any(l.strip() for l in current_lines):
                sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = line[3:].strip()
            current_lines = []
        elif line.startswith("# "):
            title = line[2:].strip()  # titre H1 du document
        else:
            current_lines.append(line)

    if any(l.strip() for l in current_lines):
        sections.append((current_heading, "\n".join(current_lines).strip()))

    return title, sections


def load_chunks(corpus_dir):
    """Charge les documents 01→06 du corpus et les découpe en chunks.

    corpus_dir : dossier contenant les documents Markdown du corpus.
    """
    chunks = []
    # Le motif « 0*.md » ne sélectionne que les documents du corpus
    # (README-corpus.md et questions-test.md sont ignorés).
    for path in sorted(Path(corpus_dir).glob("0*.md")):
        body = _strip_frontmatter(path.read_text(encoding="utf-8"))
        title, sections = _split_sections(body)
        for heading, content in sections:
            # On préfixe chaque chunk du titre du document et de la section :
            # cela ancre l'extrait dans son contexte et améliore le retrieval.
            chunk_text = f"{title} — {heading}\n\n{content}"
            chunks.append(
                {"document": path.name, "heading": heading, "content": chunk_text}
            )
    return chunks


# --- 2. Embeddings -----------------------------------------------------------

def embed_text(text):
    """Calcule l'embedding d'un texte via le modèle bge-m3 (Ollama)."""
    response = ollama.embed(model=EMBEDDING_MODEL, input=text)
    return response["embeddings"][0]


# --- 3. Indexation SQLite ----------------------------------------------------

def build_index(db_path, corpus_dir):
    """(Re)construit l'index SQLite à partir du corpus. Renvoie le nb de chunks."""
    chunks = load_chunks(corpus_dir)
    connection = sqlite3.connect(db_path)
    connection.execute("DROP TABLE IF EXISTS chunks")
    connection.execute(
        "CREATE TABLE chunks ("
        "  id INTEGER PRIMARY KEY,"
        "  document TEXT,"
        "  heading TEXT,"
        "  content TEXT,"
        "  embedding TEXT"  # embedding sérialisé en JSON, pour rester lisible
        ")"
    )
    for chunk in chunks:
        embedding = embed_text(chunk["content"])
        connection.execute(
            "INSERT INTO chunks (document, heading, content, embedding) "
            "VALUES (?, ?, ?, ?)",
            (chunk["document"], chunk["heading"], chunk["content"], json.dumps(embedding)),
        )
    connection.commit()
    connection.close()
    return len(chunks)


def ensure_index(db_path, corpus_dir):
    """Construit l'index seulement s'il est absent. Renvoie le nb de chunks.

    L'index est mis en cache sur disque (fichier SQLite) : il n'est calculé
    qu'au premier démarrage. Supprimer le fichier .db force une reconstruction.
    """
    connection = sqlite3.connect(db_path)
    table_exists = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='chunks'"
    ).fetchone()
    count = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] if table_exists else 0
    connection.close()

    return count if count > 0 else build_index(db_path, corpus_dir)


# --- 4. Recherche sémantique -------------------------------------------------

def _cosine_similarity(vector_a, vector_b):
    dot = sum(a * b for a, b in zip(vector_a, vector_b))
    norm_a = math.sqrt(sum(a * a for a in vector_a))
    norm_b = math.sqrt(sum(b * b for b in vector_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def search(db_path, question, top_k=4):
    """Renvoie les top_k chunks les plus proches de la question (score décroissant)."""
    question_embedding = embed_text(question)

    connection = sqlite3.connect(db_path)
    rows = connection.execute(
        "SELECT document, heading, content, embedding FROM chunks"
    ).fetchall()
    connection.close()

    scored = []
    for document, heading, content, embedding_json in rows:
        score = _cosine_similarity(question_embedding, json.loads(embedding_json))
        scored.append(
            {"document": document, "heading": heading, "content": content, "score": score}
        )

    scored.sort(key=lambda chunk: chunk["score"], reverse=True)
    return scored[:top_k]


# --- 5. Construction du contexte RAG -----------------------------------------

def build_context(chunks):
    """Assemble les chunks retrouvés en un bloc de contexte cité par source."""
    blocks = [
        f"[Source : {chunk['document']} — {chunk['heading']}]\n{chunk['content']}"
        for chunk in chunks
    ]
    return "\n\n".join(blocks)
