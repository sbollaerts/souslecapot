"""Serveur MCP Bikaroo — Labo 5.

Reprend le serveur du labo 4 et ajoute des FIXTURES DE SÉCURITÉ : certains
identifiants de trajet (TRP-990xx) renvoient des résultats volontairement piégés
(champ inattendu, statut hors liste blanche, champ manquant, format invalide)
pour démontrer la validation stricte côté client. Voir security_fixtures.py.

Reprend les deux tools de lecture du labo 3 et ajoute un tool d'ÉCRITURE :

    get_member(member_id)            → informations d'un membre (lecture)
    get_trip_status(trip_id)         → statut réel d'un trajet (lecture)
    create_revision_request(...)     → crée une demande de révision (ÉCRITURE)

Transport : Streamable HTTP (voir labo 3). Les données de référence (membres,
trajets) sont chargées en mémoire ; les demandes de révision créées sont
stockées dans une base SQLite dédiée (revision_requests.db, à côté du serveur).
"""

import json
import random
import sqlite3
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

import security_fixtures

# Données de référence : ressources du labo (deux niveaux au-dessus de ce fichier).
RESSOURCES_DIR = Path(__file__).resolve().parents[2] / "ressources"
MEMBERS = json.loads((RESSOURCES_DIR / "members.json").read_text(encoding="utf-8"))
TRIPS = json.loads((RESSOURCES_DIR / "trips.json").read_text(encoding="utf-8"))

# Base des demandes de révision, à côté du serveur. Réinitialisée à chaque
# démarrage (repartir d'une base vide) — voir le README. Exclue de Git (*.db).
DB_PATH = Path(__file__).resolve().parent / "revision_requests.db"


def _init_db():
    connection = sqlite3.connect(DB_PATH)
    connection.execute("DROP TABLE IF EXISTS revision_requests")
    connection.execute(
        "CREATE TABLE revision_requests ("
        "  id TEXT PRIMARY KEY,"
        "  member_id TEXT,"
        "  trip_id TEXT,"
        "  description TEXT,"
        "  informations_complementaires TEXT,"
        "  status TEXT,"
        "  created_at TEXT"
        ")"
    )
    connection.commit()
    connection.close()


mcp = FastMCP("bikaroo-operations", host="127.0.0.1", port=8000)


@mcp.tool()
def get_member(member_id: str) -> dict:
    """Donne les informations d'un membre Bikaroo à partir de son identifiant, par exemple MBR-1042."""
    for member in MEMBERS:
        if member["member_id"] == member_id:
            return member
    return {"found": False, "message": f"Aucun membre avec l'identifiant {member_id}."}


@mcp.tool()
def get_trip_status(trip_id: str) -> dict:
    """Donne le statut réel et actuel d'un trajet Bikaroo à partir de son identifiant, par exemple TRP-88231."""
    # Labo 5 : les identifiants de fixture (TRP-990xx) renvoient des résultats
    # volontairement piégés (champ inattendu, statut invalide…). Le comportement
    # des trajets nominaux est inchangé.
    fixture = security_fixtures.get_fixture_trip(trip_id)
    if fixture is not None:
        return fixture
    for trip in TRIPS:
        if trip["trip_id"] == trip_id:
            return trip
    return {"found": False, "message": f"Aucun trajet avec l'identifiant {trip_id}."}


@mcp.tool()
def create_revision_request(
    member_id: str,
    trip_id: str,
    description: str,
    informations_complementaires: str,
) -> dict:
    """Crée une demande de révision de frais pour un trajet et renvoie son identifiant et son statut."""
    # Tool d'ÉCRITURE : il n'est appelé qu'après confirmation explicite côté client.
    request_id = f"REV-{random.randint(10000, 99999)}"
    created_at = datetime.now().isoformat(timespec="seconds")
    connection = sqlite3.connect(DB_PATH)
    connection.execute(
        "INSERT INTO revision_requests VALUES (?, ?, ?, ?, ?, ?, ?)",
        (request_id, member_id, trip_id, description, informations_complementaires,
         "pending", created_at),
    )
    connection.commit()
    connection.close()
    return {"request_id": request_id, "status": "pending", "created_at": created_at}


if __name__ == "__main__":
    _init_db()
    print(f"Serveur MCP Bikaroo — {len(MEMBERS)} membres, {len(TRIPS)} trajets ; "
          "base des demandes réinitialisée.")
    print("Écoute sur http://127.0.0.1:8000/mcp (Streamable HTTP)")
    mcp.run(transport="streamable-http")
