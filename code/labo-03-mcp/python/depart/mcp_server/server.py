"""Serveur MCP Bikaroo — Labo 3 (squelette de départ).

La plomberie est en place : chargement des données, création du serveur FastMCP
en Streamable HTTP, et déclaration des deux tools. À vous d'implémenter le corps
des tools (voir les « TODO ») :

    get_member(member_id)     → informations d'un membre
    get_trip_status(trip_id)  → statut réel et actuel d'un trajet

Transport : Streamable HTTP (et non stdio), pour éviter le conflit entre le flux
stdio réservé au protocole et les logs de débogage, et pouvoir inspecter le
serveur avec curl.
"""

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Données synthétiques : ressources du labo, deux niveaux au-dessus de ce fichier.
RESSOURCES_DIR = Path(__file__).resolve().parents[3] / "ressources"

MEMBERS = json.loads((RESSOURCES_DIR / "members.json").read_text(encoding="utf-8"))
TRIPS = json.loads((RESSOURCES_DIR / "trips.json").read_text(encoding="utf-8"))

mcp = FastMCP("bikaroo-operations", host="127.0.0.1", port=8000)

# Astuce : gardez les descriptions (docstrings) COURTES et directes. Un modèle
# local décide d'appeler un tool bien plus fiablement avec une phrase brève et
# orientée action qu'avec un long paragraphe.


@mcp.tool()
def get_member(member_id: str) -> dict:
    """Donne les informations d'un membre Bikaroo à partir de son identifiant, par exemple MBR-1042."""
    # TODO (étape 2) — Parcourir MEMBERS et renvoyer le membre dont "member_id"
    # correspond. Si aucun ne correspond, renvoyer une absence de résultat
    # exploitable, par ex. {"found": False, "message": "..."}.
    return {"found": False, "message": "get_member n'est pas encore implémenté."}


@mcp.tool()
def get_trip_status(trip_id: str) -> dict:
    """Donne le statut réel et actuel d'un trajet Bikaroo à partir de son identifiant, par exemple TRP-88231."""
    # TODO (étape 2) — Parcourir TRIPS et renvoyer le trajet dont "trip_id"
    # correspond (statut open/closed, membre, vélo, heures, lieux). Sinon,
    # renvoyer une absence de résultat exploitable.
    return {"found": False, "message": "get_trip_status n'est pas encore implémenté."}


if __name__ == "__main__":
    print(f"Serveur MCP Bikaroo — {len(MEMBERS)} membres, {len(TRIPS)} trajets chargés.")
    print("Écoute sur http://127.0.0.1:8000/mcp (Streamable HTTP)")
    mcp.run(transport="streamable-http")
