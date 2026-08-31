from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime


# ════════════════════════════════════════════════════════════════════════════════
# ENVOI — Ce que React envoie à FastAPI (POST /messages)
# ════════════════════════════════════════════════════════════════════════════════

class MessageCreateSchema(BaseModel):
    """
    Envoi d'un nouveau message.

    Règles métier (diagramme de séquence messagerie) :
    - contenu      : obligatoire et non vide
    - destinataire : obligatoire et doit exister en DB
    - shipment_id  : optionnel — associe le message à un shipment
                     pour afficher le contexte logistique

    expediteur_id : jamais envoyé par React — extrait du token JWT
                    par FastAPI (sécurité : un user ne peut pas
                    envoyer un message au nom d'un autre)
    """
    contenu:         str
    destinataire_id: int
    shipment_id:     Optional[int] = None   # contexte logistique optionnel

    @field_validator("contenu")
    @classmethod
    def contenu_non_vide(cls, v):
        if not v or not v.strip():
            raise ValueError("Le message ne peut pas être vide.")
        return v.strip()


# ════════════════════════════════════════════════════════════════════════════════
# RÉPONSE — Ce que FastAPI retourne à React
# ════════════════════════════════════════════════════════════════════════════════

class MessageResponseSchema(BaseModel):
    """
    Un message complet retourné à React.
    Inclut les infos de l'expéditeur et du destinataire pour affichage.
    Inclut le contexte shipment si shipment_id est renseigné.

    Correspond à :
    SELECT * FROM message
    JOIN user expediteur  ON message.expediteur_id   = expediteur.id
    JOIN user destinataire ON message.destinataire_id = destinataire.id
    WHERE expediteur_id = ? OR destinataire_id = ?
    ORDER BY date_envoi DESC
    (get_messages_user() dans db.py)
    """
    id:               int
    contenu:          str
    date_envoi:       datetime
    lu:               bool

    # Expéditeur
    expediteur_id:    int
    expediteur_login: str
    expediteur_nom:   Optional[str] = None
    expediteur_prenom:Optional[str] = None

    # Destinataire
    destinataire_id:    int
    destinataire_login: str
    destinataire_nom:   Optional[str] = None
    destinataire_prenom:Optional[str] = None

    # Contexte shipment (optionnel)
    shipment_id:          Optional[int] = None
    shipment_port_chargement:   Optional[str] = None   # pour afficher le contexte
    shipment_port_dechargement: Optional[str] = None
    shipment_etd:               Optional[str] = None

    class Config:
        from_attributes = True


# ════════════════════════════════════════════════════════════════════════════════
# BADGE — Nombre de messages non lus (WebSocket)
# ════════════════════════════════════════════════════════════════════════════════

class BadgeSchema(BaseModel):
    """
    Nombre de messages non lus retourné via WebSocket.

    Correspond à get_unread_count(user_id) dans db.py :
    SELECT COUNT(*) FROM message WHERE destinataire_id = ? AND lu = 0

    Envoyé automatiquement par WebSocket toutes les 30s
    (remplace le rafraîchissement st.empty() de Streamlit).
    React affiche 🔔 N à côté de ✉️ Messagerie si non_lus > 0.
    """
    non_lus: int   # 0 = pas de badge, >0 = badge 🔔 affiché


# ════════════════════════════════════════════════════════════════════════════════
# MARQUER LU — Quand l'utilisateur ouvre un message non lu
# ════════════════════════════════════════════════════════════════════════════════

class MarquerLuSchema(BaseModel):
    """
    Retourné après UPDATE messages SET lu=1 WHERE id=?
    (marquer_message_lu() dans db.py).
    React retire le badge 🔔 et affiche le contenu complet.
    """
    success:    bool
    message_id: int


# ════════════════════════════════════════════════════════════════════════════════
# CONVERSATION — Liste des messages d'une conversation
# ════════════════════════════════════════════════════════════════════════════════

class ConversationSchema(BaseModel):
    """
    Liste des messages entre 2 utilisateurs, triés par date.
    Chaque utilisateur ne voit QUE ses propres conversations
    (messages envoyés ET reçus) — règle métier du diagramme de séquence.
    """
    messages:   list[MessageResponseSchema]
    total:      int   # nombre total de messages dans la conversation


# ════════════════════════════════════════════════════════════════════════════════
# LISTE DESTINATAIRES — Pour la liste déroulante "À :"
# ════════════════════════════════════════════════════════════════════════════════

class DestinataireSchema(BaseModel):
    """
    Liste des utilisateurs disponibles comme destinataires.
    Exclut l'expéditeur lui-même et les comptes inactifs/bloqués.
    Utilisé pour alimenter la liste déroulante "À :" dans le formulaire.
    """
    id:     int
    login:  str
    nom:    Optional[str] = None
    prenom: Optional[str] = None
    role:   str   # pour afficher le rôle à côté du nom