"""
message_repository.py — Accès aux données : table message (SQLAlchemy)

Contient UNIQUEMENT les requêtes sur la table message.
Toute la logique métier est dans messaging_service.py.

Architecture :
    Router → Service → Repository → SessionLocal (SQLAlchemy)

Différences vs version sqlite3 :
- get_connection() / cursor  →  Session SQLAlchemy injectée en paramètre
- pd.read_sql_query()        →  query ORM + pd.DataFrame([...])
- INSERT/UPDATE SQL          →  méthodes ORM (add, update)
- Chaque fonction reçoit `db: Session` — pas de connexion ouverte/fermée ici
"""

import pandas as pd
from sqlalchemy import or_, and_
from sqlalchemy.orm import Session

from backend.models.message import Message
from backend.models.shipment import Shipment
from backend.models.user import User


# ─────────────────────────────────────────────
# HELPER DE SÉRIALISATION
# ─────────────────────────────────────────────

def _message_to_dict(m: Message) -> dict:
    """Convertit un objet Message ORM en dict plat avec les jointures dénormalisées."""
    return {
        "id":                        m.id,
        "contenu":                   m.contenu,
        "date_envoi":                m.date_envoi,
        "lu":                        m.lu,
        "expediteur_id":             m.expediteur_id,
        "destinataire_id":           m.destinataire_id,
        "shipment_id":               m.shipment_id,
        # Expéditeur dénormalisé
        "expediteur_login":          m.expediteur.login   if m.expediteur   else None,
        "expediteur_nom":            m.expediteur.nom     if m.expediteur   else None,
        "expediteur_prenom":         m.expediteur.prenom  if m.expediteur   else None,
        # Destinataire dénormalisé
        "destinataire_login":        m.destinataire.login  if m.destinataire else None,
        "destinataire_nom":          m.destinataire.nom    if m.destinataire else None,
        "destinataire_prenom":       m.destinataire.prenom if m.destinataire else None,
        # Shipment dénormalisé (nullable)
        "shipment_port_chargement":  m.shipment.port_chargement  if m.shipment else None,
        "shipment_port_dechargement":m.shipment.port_dechargement if m.shipment else None,
        "shipment_etd":              m.shipment.etd               if m.shipment else None,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# LECTURE — MESSAGE
# ═══════════════════════════════════════════════════════════════════════════════

def get_messages_user(db: Session, user_id: int) -> pd.DataFrame:
    """
    Retourne toutes les conversations d'un utilisateur
    (messages envoyés ET reçus), triés par date décroissante.
    Inclut nom + prenom de l'expéditeur, du destinataire et contexte shipment.
    Utilisé par : messaging_service (liste des messages)
    """
    # Alias pour joindre user deux fois (expéditeur et destinataire)
    Expediteur   = User.__table__.alias("u_exp")
    Destinataire = User.__table__.alias("u_dest")

    messages = (
        db.query(Message)
        .filter(
            or_(
                Message.expediteur_id   == user_id,
                Message.destinataire_id == user_id,
            )
        )
        .order_by(Message.date_envoi.desc())
        .all()
    )
    return pd.DataFrame([_message_to_dict(m) for m in messages])


def get_conversation(
    db: Session,
    user_id: int,
    autre_user_id: int,
) -> pd.DataFrame:
    """
    Retourne les messages entre deux utilisateurs spécifiques.
    Triés par date croissante (ordre chronologique de conversation).
    Utilisé par : messaging_service (affichage d'une conversation)
    """
    messages = (
        db.query(Message)
        .filter(
            or_(
                and_(
                    Message.expediteur_id   == user_id,
                    Message.destinataire_id == autre_user_id,
                ),
                and_(
                    Message.expediteur_id   == autre_user_id,
                    Message.destinataire_id == user_id,
                ),
            )
        )
        .order_by(Message.date_envoi.asc())
        .all()
    )
    return pd.DataFrame([_message_to_dict(m) for m in messages])


def get_unread_count(db: Session, user_id: int) -> int:
    """
    Retourne le nombre de messages non lus pour un utilisateur.
    Utilisé par : messaging_service (badge 🔔 WebSocket)
    """
    return (
        db.query(Message)
        .filter(
            Message.destinataire_id == user_id,
            Message.lu == 0,
        )
        .count()
    )


def get_destinataires_disponibles(db: Session, user_id: int) -> pd.DataFrame:
    """
    Retourne tous les utilisateurs actifs sauf l'expéditeur lui-même.
    Utilisé par : messaging_service (liste déroulante destinataires)
    """
    from backend.models.user import Role

    users = (
        db.query(User)
        .join(Role)
        .filter(User.id != user_id, User.statut == "actif")
        .order_by(Role.nom_role, User.nom)
        .all()
    )

    return pd.DataFrame([
        {
            "id":       u.id,
            "login":    u.login,
            "nom":      u.nom,
            "prenom":   u.prenom,
            "nom_role": u.role.nom_role if u.role else None,
        }
        for u in users
    ])


# ═══════════════════════════════════════════════════════════════════════════════
# CRÉATION — MESSAGE
# ═══════════════════════════════════════════════════════════════════════════════

def insert_message(
    db: Session,
    contenu: str,
    expediteur_id: int,
    destinataire_id: int,
    shipment_id: int | None = None,
) -> int:
    """
    Insère un nouveau message.
    shipment_id est optionnel (contexte logistique).
    Retourne l'id du message inséré.
    Le commit reste dans le service appelant.
    Utilisé par : messaging_service (envoi message)
    """
    message = Message(
        contenu=contenu,
        expediteur_id=expediteur_id,
        destinataire_id=destinataire_id,
        shipment_id=shipment_id,
        lu=0,
    )
    db.add(message)
    db.flush()   # obtenir l'id sans commit
    return message.id

def supprimer_message(db: Session, message_id: int, expediteur_id: int) -> bool:
    """
    Supprime un message uniquement si l'expéditeur en est l'auteur.
    Retourne True si supprimé, False si introuvable ou non autorisé.
    """
    rows = (
        db.query(Message)
        .filter(
            Message.id == message_id,
            Message.expediteur_id == expediteur_id,  # sécurité : uniquement ses propres messages
        )
        .delete()
    )
    return rows > 0

# ═══════════════════════════════════════════════════════════════════════════════
# MISE À JOUR — MESSAGE
# ═══════════════════════════════════════════════════════════════════════════════

def marquer_message_lu(db: Session, message_id: int) -> bool:
    """
    Marque un message comme lu (lu = 1).
    Retourne True si mis à jour, False si message introuvable.
    Utilisé par : messaging_service (ouverture d'un message)
    """
    rows = (
        db.query(Message)
        .filter(Message.id == message_id)
        .update({"lu": 1})
    )
    return rows > 0


def marquer_conversation_lue(
    db: Session,
    user_id: int,
    autre_user_id: int,
) -> None:
    """
    Marque tous les messages non lus d'une conversation comme lus.
    Appelé quand l'utilisateur ouvre une conversation.
    Utilisé par : messaging_service (ouverture conversation)
    """
    db.query(Message).filter(
        Message.destinataire_id == user_id,
        Message.expediteur_id   == autre_user_id,
        Message.lu == 0,
    ).update({"lu": 1})