"""
message.py — Modèle Message (SQLAlchemy ORM)

Correspond à la table :
    message : id, contenu, date_envoi, lu,
              expediteur_id (FK → user),
              destinataire_id (FK → user),
              shipment_id (FK → shipment, nullable)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

# Imports uniquement pour Pylance / mypy — jamais exécutés à runtime
if TYPE_CHECKING:
    from .shipment import Shipment
    from .user import User


class Message(Base):
    __tablename__ = "message"

    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    contenu:    Mapped[str]      = mapped_column(Text, nullable=False)
    date_envoi: Mapped[datetime] = mapped_column(
    DateTime,
    nullable=False,
    default=lambda: datetime.now(timezone.utc),
    server_default=func.now(),
)
    lu:         Mapped[int]      = mapped_column(Integer, nullable=False, default=0)

    # ── Clés étrangères ───────────────────────────────────────────────────────
    expediteur_id:   Mapped[int]           = mapped_column(Integer, ForeignKey("user.id"),     nullable=False)
    destinataire_id: Mapped[int]           = mapped_column(Integer, ForeignKey("user.id"),     nullable=False)
    shipment_id:     Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("shipment.id"), nullable=True)

    # ── Relations ─────────────────────────────────────────────────────────────
    expediteur:   Mapped[User]             = relationship(
        "User",
        foreign_keys=[expediteur_id],
        back_populates="messages_envoyes",
    )
    destinataire: Mapped[User]             = relationship(
        "User",
        foreign_keys=[destinataire_id],
        back_populates="messages_recus",
    )
    shipment:     Mapped[Optional[Shipment]] = relationship(
        "Shipment",
        back_populates="messages",
    )

    def __repr__(self) -> str:
        return (
            f"<Message id={self.id} "
            f"de={self.expediteur_id} "
            f"à={self.destinataire_id} "
            f"lu={bool(self.lu)}>"
        )