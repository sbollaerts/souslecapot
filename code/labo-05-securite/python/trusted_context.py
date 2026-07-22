"""Contexte de confiance — Labo 5.

Le TrustedContext porte la **source de vérité** de la session : qui est
l'utilisateur authentifié, et ce qu'il a le droit de faire.

Règle fondamentale du labo : ce contexte est établi par l'application (ici, une
authentification simulée) et **ne peut jamais être modifié par une donnée non
fiable** — ni par un message utilisateur, ni par un document du RAG, ni par le
résultat d'un tool.
"""

import uuid
from dataclasses import dataclass, field

# Actions que la session a le droit de déclencher.
READ_TRIP = "read_trip"
CREATE_REVISION = "create_revision"


@dataclass(frozen=True)
class TrustedContext:
    """Identité et autorisations de confiance (immuable)."""

    authenticated_member_id: str
    allowed_actions: tuple = (READ_TRIP, CREATE_REVISION)
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def is_allowed(self, action):
        return action in self.allowed_actions


def new_context(authenticated_member_id="MBR-1042"):
    """Crée le contexte de confiance de la session (authentification simulée).

    Dans une vraie application, cet identifiant viendrait d'une authentification
    réelle (session, jeton signé…). Ici il est simulé, mais il est traité comme
    la seule source de vérité : l'interface l'affiche en lecture seule.
    """
    return TrustedContext(authenticated_member_id=authenticated_member_id)
