"""Client MCP de l'Assistant Bikaroo — Labo 4.

Reprend le client du labo 3 (connexion au serveur, boucle d'appel de tools par
le modèle) et ajoute :

- un garde-fou : les tools d'ÉCRITURE (create_revision_request) ne sont PAS
  exposés au modèle dans le chat normal — il ne peut donc pas les déclencher
  seul. Ils sont appelés directement par l'orchestration, après confirmation
  explicite de l'utilisateur ;
- un appel de tool direct (call_tool) utilisé par l'orchestration pour piloter le
  processus de façon déterministe.
"""

import asyncio

import ollama
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# Garde-fou contre les boucles d'appels de tools.
MAX_TOOL_ROUNDS = 5

# Tools d'écriture : jamais proposés au modèle dans le chat libre. Ils modifient
# des données et ne doivent être appelés qu'après une confirmation explicite.
WRITE_TOOLS = {"create_revision_request"}


def _to_ollama_tools(mcp_tools):
    """Convertit les tools MCP (en excluant les tools d'écriture) pour ollama.chat."""
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
        if tool.name not in WRITE_TOOLS
    ]


async def _list_tool_names(url):
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return [tool.name for tool in (await session.list_tools()).tools]


async def _call_tool(url, name, arguments):
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)
            return result.content[0].text if result.content else ""


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
                if not message.get("tool_calls"):
                    return message["content"], tool_log

                conversation.append(message)
                for call in message["tool_calls"]:
                    name = call["function"]["name"]
                    arguments = call["function"]["arguments"]
                    result = await session.call_tool(name, arguments)
                    text = result.content[0].text if result.content else ""
                    tool_log.append({"name": name, "arguments": arguments, "result": text})
                    conversation.append(
                        {"role": "tool", "tool_name": name, "content": text}
                    )

            final = ollama.chat(model=model, messages=conversation, options=options)
            return final["message"]["content"], tool_log


def list_tool_names(url):
    """Noms de tous les tools exposés par le serveur (vérification au démarrage)."""
    return asyncio.run(_list_tool_names(url))


def call_tool(url, name, arguments):
    """Appelle directement un tool MCP et renvoie son résultat (texte JSON).

    Utilisé par l'orchestration pour piloter le processus de façon déterministe,
    y compris le tool d'écriture create_revision_request après confirmation.
    """
    return asyncio.run(_call_tool(url, name, arguments))


def answer(url, model, messages, options):
    """Chat libre avec accès aux tools de LECTURE (pas d'écriture — voir WRITE_TOOLS).

    Renvoie (réponse, journal_des_tools, mcp_disponible).
    """
    try:
        text, tool_log = asyncio.run(_answer_with_tools(url, model, messages, options))
        return text, tool_log, True
    except Exception:  # noqa: BLE001 — serveur MCP injoignable : repli sans tools
        response = ollama.chat(model=model, messages=messages, options=options)
        return response["message"]["content"], [], False
