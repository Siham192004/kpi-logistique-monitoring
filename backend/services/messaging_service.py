"""
messaging_service.py — Logique métier : messagerie interne + WebSocket

Responsabilités :
1. Envoyer un message
2. Récupérer les conversations d'un utilisateur
3. Marquer les messages comme lus
4. Gérer le badge 🔔 (messages non lus) via WebSocket
5. Fournir la liste des destinataires disponibles

Règles métier :
- Un utilisateur ne peut envoyer qu'à un utilisateur actif
- Un utilisateur ne voit QUE ses propres conversations
- Le badge 🔔 est mis à jour en temps réel via WebSocket
- shipment_id est optionnel (contexte logistique)

Architecture :
messaging_router → messaging_service → message_repository → SessionLocal
                 ↘ WebSocket (badge temps réel)
"""

from fastapi import HTTPException, WebSocket, WebSocketDisconnect, status
from typing import Dict, Set
import json

from sqlalchemy.orm import Session

from backend.repositories.message_repository import (
    insert_message,
    get_messages_user,
    get_conversation,
    get_unread_count,
    get_destinataires_disponibles,
    marquer_message_lu,
    marquer_conversation_lue,
    supprimer_message,
)
from backend.repositories.user_repository import get_user_by_id
from backend.schemas.message_schema import (
    MessageCreateSchema,
    BadgeSchema,
    ConversationSchema,
    MarquerLuSchema,
)
from database.db import SessionLocal


# ═══════════════════════════════════════════════════════════════════════════════
# GESTIONNAIRE DE CONNEXIONS WEBSOCKET
# ═══════════════════════════════════════════════════════════════════════════════

class WebSocketManager:
    """
    connexions = { user_id: {websocket1, websocket2, ...} }
    """

    def __init__(self):
        self.connexions: Dict[int, Set[WebSocket]] = {}

    async def connecter(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        if user_id not in self.connexions:
            self.connexions[user_id] = set()
        self.connexions[user_id].add(websocket)

    def deconnecter(self, user_id: int, websocket: WebSocket):
        if user_id in self.connexions:
            self.connexions[user_id].discard(websocket)
            if not self.connexions[user_id]:
                del self.connexions[user_id]

    async def envoyer_evenement(self, user_id: int, evenement: dict):
        payload = json.dumps(evenement)
        connexions_mortes = set()
        for ws in list(self.connexions.get(user_id, set())):
            try:
                await ws.send_text(payload)
            except Exception:
                connexions_mortes.add(ws)
        for ws in connexions_mortes:
            self.deconnecter(user_id, ws)

    async def notifier_actualisation_kpi(self):
        for user_id in list(self.connexions):
            await self.envoyer_evenement(user_id, {"type": "kpi_data_updated"})

    async def envoyer_badge(self, user_id: int, db: Session):
        if user_id not in self.connexions:
            return
        non_lus = get_unread_count(db, user_id)
        payload = json.dumps({"type": "badge", "non_lus": non_lus})
        connexions_mortes = set()
        for ws in self.connexions[user_id]:
            try:
                await ws.send_text(payload)
            except Exception:
                connexions_mortes.add(ws)
        for ws in connexions_mortes:
            self.connexions[user_id].discard(ws)

    async def notifier_nouveau_message(self, destinataire_id: int, db: Session):
        await self.envoyer_badge(destinataire_id, db)
        await self.envoyer_evenement(destinataire_id, {"type": "nouveau_message"})


# Instance globale
ws_manager = WebSocketManager()


# ═══════════════════════════════════════════════════════════════════════════════
# WEBSOCKET — CONNEXION TEMPS RÉEL
# ═══════════════════════════════════════════════════════════════════════════════

async def websocket_endpoint(websocket: WebSocket, user_id: int):
    """
    Flux :
    1. Connexion → badge initial + broadcast présence "en ligne" à tous
    2. Envoi immédiat de la liste des users déjà connectés (snapshot)
    3. Ping/pong pour maintenir la connexion
    4. Déconnexion → broadcast présence "hors ligne" à tous
    """
    await ws_manager.connecter(user_id, websocket)
    db = SessionLocal()

    try:
        # Badge initial
        await ws_manager.envoyer_badge(user_id, db)

        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

    except WebSocketDisconnect:
        pass

    finally:
        ws_manager.deconnecter(user_id, websocket)
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# ENVOI DE MESSAGE
# ═══════════════════════════════════════════════════════════════════════════════

async def envoyer_message(
    db: Session,
    data: MessageCreateSchema,
    expediteur_id: int,
) -> dict:
    """
    Envoie un nouveau message.

    Règles métier :
    - L'expéditeur ne peut pas s'envoyer un message à lui-même
    - Le destinataire doit exister et être actif
    - shipment_id optionnel (contexte logistique)
    - Après envoi → notifie le destinataire via WebSocket (badge 🔔)
    """
    # Pas d'auto-message
    if data.destinataire_id == expediteur_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vous ne pouvez pas vous envoyer un message à vous-même."
        )

    # Destinataire existe et est actif ?
    destinataire = get_user_by_id(db, data.destinataire_id)
    if not destinataire:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Destinataire introuvable."
        )
    if destinataire["statut"] != "actif":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Impossible d'envoyer un message à un compte inactif ou bloqué."
        )

    # Insérer le message
    message_id = insert_message(
        db=db,
        contenu=data.contenu,
        expediteur_id=expediteur_id,
        destinataire_id=data.destinataire_id,
        shipment_id=data.shipment_id,
    )
    db.commit()

    # Notifier le destinataire via WebSocket (badge 🔔)
    await ws_manager.notifier_nouveau_message(data.destinataire_id, db)

    return {"success": True, "message_id": message_id}


# ═══════════════════════════════════════════════════════════════════════════════
# CONSULTATION DES MESSAGES
# ═══════════════════════════════════════════════════════════════════════════════

def lister_messages(db: Session, user_id: int) -> ConversationSchema:
    """
    Retourne toutes les conversations de l'utilisateur
    (messages envoyés ET reçus), triés par date décroissante.
    """
    df = get_messages_user(db, user_id)
    messages = df.to_dict(orient="records") if not df.empty else []
    return ConversationSchema(messages=messages, total=len(messages))


def lister_conversation(
    db: Session,
    user_id: int,
    autre_user_id: int,
) -> ConversationSchema:
    """
    Retourne les messages entre deux utilisateurs spécifiques.
    Triés chronologiquement.
    """
    autre_user = get_user_by_id(db, autre_user_id)
    if not autre_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur introuvable."
        )

    df = get_conversation(db, user_id, autre_user_id)
    messages = df.to_dict(orient="records") if not df.empty else []
    return ConversationSchema(messages=messages, total=len(messages))


def lister_destinataires(db: Session, user_id: int) -> list:
    """
    Retourne la liste des utilisateurs disponibles comme destinataires.
    Exclut l'expéditeur et les comptes inactifs/bloqués.
    """
    df = get_destinataires_disponibles(db, user_id)
    return df.to_dict(orient="records") if not df.empty else []


# ═══════════════════════════════════════════════════════════════════════════════
# MARQUER COMME LU
# ═══════════════════════════════════════════════════════════════════════════════

async def marquer_lu(
    db: Session,
    message_id: int,
    user_id: int,
) -> MarquerLuSchema:
    """
    Marque un message comme lu.
    Met à jour le badge 🔔 via WebSocket après la lecture.
    """
    success = marquer_message_lu(db, message_id)
    if success:
        db.commit()
        await ws_manager.envoyer_badge(user_id, db)

    return MarquerLuSchema(success=success, message_id=message_id)


async def marquer_conversation_lue_service(
    db: Session,
    user_id: int,
    autre_user_id: int,
) -> dict:
    """
    Marque tous les messages non lus d'une conversation comme lus.
    Met à jour le badge 🔔 via WebSocket.
    """
    marquer_conversation_lue(db, user_id, autre_user_id)
    db.commit()
    await ws_manager.envoyer_badge(user_id, db)
    return {"success": True, "message": "Conversation marquée comme lue."}

async def supprimer_message_service(
    db: Session,
    message_id: int,
    expediteur_id: int,
) -> dict:
    """Supprime un message si l'utilisateur en est l'auteur."""
    success = supprimer_message(db, message_id, expediteur_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message introuvable ou non autorisé."
        )
    db.commit()
    return {"success": True, "message_id": message_id}
# ═══════════════════════════════════════════════════════════════════════════════
# BADGE
# ═══════════════════════════════════════════════════════════════════════════════

def get_badge(db: Session, user_id: int) -> BadgeSchema:
    """
    Retourne le nombre de messages non lus.
    Appelé au chargement de l'app pour initialiser le badge.
    """
    non_lus = get_unread_count(db, user_id)
    return BadgeSchema(non_lus=non_lus)
