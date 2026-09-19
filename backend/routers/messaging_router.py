"""
messaging_router.py — Routes HTTP + WebSocket : messagerie interne
"""

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, Query
from typing import Optional
from sqlalchemy.orm import Session

from backend.services.auth_service import (
    get_current_operateur_ou_manager,
    get_current_user,   # ← ajouter cet import
    verifier_token,
    verifier_token_ws,
)
from backend.services.messaging_service import (
    ws_manager,
    envoyer_message,
    lister_messages,
    lister_conversation,
    lister_destinataires,
    marquer_lu,
    marquer_conversation_lue_service,
    get_badge,
    websocket_endpoint,
    supprimer_message_service,
)
from backend.schemas.message_schema import (
    MessageCreateSchema,
    ConversationSchema,
    BadgeSchema,
    MarquerLuSchema,
)
from database.db import get_db

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════════════
# WEBSOCKET
# ═══════════════════════════════════════════════════════════════════════════════
@router.websocket("/ws/{user_id}")
async def websocket_badge(
    websocket: WebSocket,
    user_id: int,
    token: str = Query(...)
):
    payload = verifier_token_ws(token)
    if not payload or payload.get("id") != user_id:
        await websocket.close(code=4001)
        return
    await websocket_endpoint(websocket, user_id)


# ═══════════════════════════════════════════════════════════════════════════════
# BADGE
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/badge", response_model=BadgeSchema, tags=["Messagerie"])
def get_badge_count(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),   # ← modifié
):
    return get_badge(db, user["id"])


# ═══════════════════════════════════════════════════════════════════════════════
# DESTINATAIRES
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/destinataires", tags=["Messagerie"])
def get_destinataires(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),   # ← modifié
):
    return lister_destinataires(db, user["id"])


# ═══════════════════════════════════════════════════════════════════════════════
# CONVERSATIONS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/", response_model=ConversationSchema, tags=["Messagerie"])
def get_messages(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),   # ← modifié
):
    return lister_messages(db, user["id"])


@router.get("/conversation/{autre_user_id}", response_model=ConversationSchema, tags=["Messagerie"])
def get_conversation(
    autre_user_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),   # ← modifié
):
    return lister_conversation(db, user["id"], autre_user_id)


# ═══════════════════════════════════════════════════════════════════════════════
# ENVOI DE MESSAGE
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/", status_code=201, tags=["Messagerie"])
async def send_message(
    data: MessageCreateSchema,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),   # ← modifié
):
    return await envoyer_message(db, data, expediteur_id=user["id"])


# ═══════════════════════════════════════════════════════════════════════════════
# MARQUER COMME LU
# ═══════════════════════════════════════════════════════════════════════════════

@router.put("/{message_id}/lu", response_model=MarquerLuSchema, tags=["Messagerie"])
async def mark_as_read(
    message_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),   # ← modifié
):
    return await marquer_lu(db, message_id, user["id"])


@router.put("/conversation/{autre_user_id}/lu", tags=["Messagerie"])
async def mark_conversation_as_read(
    autre_user_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),   # ← modifié
):
    return await marquer_conversation_lue_service(db, user["id"], autre_user_id)

@router.delete("/{message_id}", tags=["Messagerie"])
async def delete_message(
    message_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    return await supprimer_message_service(db, message_id, user["id"])