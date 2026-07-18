"""Client MCP de l'Assistant Bikaroo — Labo 3 (squelette de départ).

La connexion au serveur MCP est déjà câblée (list_tool_names fonctionne). À vous
d'écrire la logique qui relie le modèle aux tools :

    1. récupérer la liste des tools et les transmettre au modèle ;
    2. exécuter l'appel de tool demandé par le modèle ;
    3. réinjecter le résultat dans la conversation, puis laisser le modèle
       formuler sa réponse finale.

Le SDK MCP est asynchrone ; Streamlit est synchrone. On expose donc des
fonctions synchrones qui encapsulent une boucle asyncio (asyncio.run).
"""

import asyncio

import ollama
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# Nombre maximal d'allers-retours modèle → tool (garde-fou contre les boucles).
MAX_TOOL_ROUNDS = 5


def _to_ollama_tools(mcp_tools):
    """Convertit les tools MCP au format attendu par ollama.chat(tools=...)."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.inputSchema,
            },
        }
        for tool in mcp_tools
    ]


async def _list_tool_names(url):
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            return [tool.name for tool in tools]


def list_tool_names(url):
    """Renvoie la liste des noms de tools exposés par le serveur MCP.

    (Connexion déjà câblée — sert à vérifier la disponibilité au démarrage.)
    """
    return asyncio.run(_list_tool_names(url))


def answer(url, model, messages, options):
    """Répond à la conversation en donnant au modèle l'accès aux tools MCP.

    Renvoie (réponse, journal_des_tools, mcp_disponible).

    TODO (étape 4) — Implémenter la boucle d'appel de tools :
      * ouvrir une connexion MCP (streamablehttp_client + ClientSession, comme
        dans _list_tool_names) et récupérer les tools ;
      * les convertir avec _to_ollama_tools et les passer à ollama.chat(tools=...) ;
      * tant que le modèle renvoie des "tool_calls" (dans la limite de
        MAX_TOOL_ROUNDS) : exécuter chaque appel via session.call_tool(name, args),
        journaliser {"name", "arguments", "result"}, et réinjecter le résultat
        dans la conversation avec le rôle "tool" ({"role": "tool",
        "tool_name": name, "content": texte}) ;
      * dès que le modèle ne demande plus de tool, renvoyer sa réponse et le
        journal ;
      * en cas d'échec de connexion au serveur MCP, se replier sur une génération
        sans tools et renvoyer mcp_disponible=False.

    En attendant, on répond SANS tools (le chat et le RAG fonctionnent déjà).
    """
    response = ollama.chat(model=model, messages=messages, options=options)
    return response["message"]["content"], [], False
