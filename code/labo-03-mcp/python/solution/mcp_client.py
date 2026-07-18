"""Client MCP de l'Assistant Bikaroo — Labo 3.

Ce module relie le modèle (via Ollama) au serveur MCP :

    1. il se connecte au serveur et récupère la liste des tools ;
    2. il transmet ces tools au modèle, qui décide seul s'il en appelle un ;
    3. il exécute l'appel demandé, réinjecte le résultat dans la conversation,
       et laisse le modèle formuler sa réponse finale.

Le SDK MCP est asynchrone ; Streamlit est synchrone. On expose donc des
fonctions synchrones qui encapsulent une boucle asyncio (asyncio.run), en
ouvrant une connexion au serveur le temps d'un échange.
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
                "parameters": tool.inputSchema,  # schéma JSON fourni par le serveur MCP
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


async def _answer_with_tools(url, model, messages, options):
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = _to_ollama_tools((await session.list_tools()).tools)

            conversation = list(messages)
            tool_log = []

            for _ in range(MAX_TOOL_ROUNDS):
                response = ollama.chat(
                    model=model, messages=conversation, tools=tools, options=options
                )
                message = response["message"]

                # Le modèle n'appelle plus de tool : c'est sa réponse finale.
                if not message.get("tool_calls"):
                    return message["content"], tool_log

                conversation.append(message)
                for call in message["tool_calls"]:
                    name = call["function"]["name"]
                    arguments = call["function"]["arguments"]
                    result = await session.call_tool(name, arguments)
                    text = result.content[0].text if result.content else ""
                    tool_log.append({"name": name, "arguments": arguments, "result": text})
                    # On réinjecte le résultat du tool dans la conversation.
                    conversation.append(
                        {"role": "tool", "tool_name": name, "content": text}
                    )

            # Garde-fou atteint : on demande une réponse finale sans nouveaux tools.
            final = ollama.chat(model=model, messages=conversation, options=options)
            return final["message"]["content"], tool_log


def list_tool_names(url):
    """Renvoie la liste des noms de tools exposés par le serveur MCP.

    Lève une exception si le serveur n'est pas joignable (utilisé au démarrage
    pour vérifier la connexion).
    """
    return asyncio.run(_list_tool_names(url))


def answer(url, model, messages, options):
    """Répond à la conversation en donnant au modèle l'accès aux tools MCP.

    Renvoie (réponse, journal_des_tools, mcp_disponible). Si le serveur MCP
    n'est pas joignable, on se replie sur une génération sans tools et on
    renvoie mcp_disponible=False (le RAG et le chat continuent de fonctionner).
    """
    try:
        text, tool_log = asyncio.run(_answer_with_tools(url, model, messages, options))
        return text, tool_log, True
    except Exception:  # noqa: BLE001 — serveur MCP injoignable : repli sans tools
        response = ollama.chat(model=model, messages=messages, options=options)
        return response["message"]["content"], [], False
