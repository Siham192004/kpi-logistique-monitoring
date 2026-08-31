"""
backend/models/__init__.py
Expose la Base et tous les modèles pour que SQLAlchemy
puisse générer le schéma en un seul import.

Usage :
    from backend.models import Base, Role, User, Vessel, Shipment, Message
"""

from .base import Base
from .user import Role, User
from .shipment import Vessel, Shipment
from .message import Message

__all__ = [
    "Base",
    "Role",
    "User",
    "Vessel",
    "Shipment",
    "Message",
]