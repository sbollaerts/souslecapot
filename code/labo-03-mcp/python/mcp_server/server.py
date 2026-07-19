"""Serveur MCP Bikaroo — Labo 3.

Expose deux tools qui donnent accès à des données opérationnelles de Bikaroo
(membres et trajets), que le RAG documentaire ne peut pas fournir :

    get_member(member_id)     → informations d'un membre
    get_trip_status(trip_id)  → statut réel et actuel d'un trajet

Transport : Streamable HTTP (et non stdio). Ce choix évite le conflit classique
entre le flux stdio, réservé au protocole MCP, et les logs de débogage
(print/console), et permet d'inspecter le serveur directement (curl) avant de le
relier au modèle.

Les données sont chargées en mémoire au démarrage depuis members.json et
trips.json (pas de base de données pour ce labo).
"""

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Données synthétiques : ressources du labo.
# server.py est dans .../python/mcp_server/ ; les données dans
# .../labo-03-mcp/ressources/.
RESSOURCES_DIR = Path(__file__).resolve().parents[2] / "ressources"

MEMBERS = json.loads((RESSOURCES_DIR / "members.json").read_text(encoding="utf-8"))
TRIPS = json.loads((RESSOURCES_DIR / "trips.json").read_text(encoding="utf-8"))

mcp = FastMCP("bikaroo-operations", host="127.0.0.1", port=8000)


# Note : les descriptions des tools (docstrings) sont volontairement courtes et
# directes. Un modèle local choisit d'appeler un tool bien plus fiablement avec
# une description brève et orientée action qu'avec un long paragraphe. Les
# détails (champs renvoyés, cas d'absence) restent en commentaire.


@mcp.tool()
def get_member(member_id: str) -> dict:
    """Donne les informations d'un membre Bikaroo à partir de son identifiant, par exemple MBR-1042."""
    # Renvoie le membre, ou une absence de résultat si l'identifiant est inconnu.
    for member in MEMBERS:
        if member["member_id"] == member_id:
            return member
    return {"found": False, "message": f"Aucun membre avec l'identifiant {member_id}."}


@mcp.tool()
def get_trip_status(trip_id: str) -> dict:
    """Donne le statut réel et actuel d'un trajet Bikaroo à partir de son identifiant, par exemple TRP-88231."""
    # Renvoie le trajet (statut open/closed, membre, vélo, heures, lieux), ou une
    # absence de résultat si l'identifiant est inconnu.
    for trip in TRIPS:
        if trip["trip_id"] == trip_id:
            return trip
    return {"found": False, "message": f"Aucun trajet avec l'identifiant {trip_id}."}


if __name__ == "__main__":
    print(f"Serveur MCP Bikaroo — {len(MEMBERS)} membres, {len(TRIPS)} trajets chargés.")
    print("Écoute sur http://127.0.0.1:8000/mcp (Streamable HTTP)")
    mcp.run(transport="streamable-http")
