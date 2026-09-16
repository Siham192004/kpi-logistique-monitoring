"""
user.py — Modèles Role et User (SQLAlchemy ORM)

Correspond aux tables :
    role  : id, nom_role
    user  : id, nom, prenom, login, password_hash, statut,
            tentatives_echouees, doit_changer_mdp, role_id (FK)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

# Imports uniquement pour Pylance / mypy — jamais exécutés à runtime
# Évite les imports circulaires tout en satisfaisant le type checker
if TYPE_CHECKING:
    from .message import Message
    from .shipment import Shipment


# ─────────────────────────────────────────────
# ROLE
# ─────────────────────────────────────────────

class Role(Base):
    __tablename__ = "role"

    id:       Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nom_role: Mapped[str] = mapped_column(String, nullable=False, unique=True)

    # Relation inverse : tous les utilisateurs ayant ce rôle
    users: Mapped[list[User]] = relationship("User", back_populates="role")

    def __repr__(self) -> str:
        return f"<Role id={self.id} nom_role={self.nom_role!r}>"


# ─────────────────────────────────────────────
# USER
# ─────────────────────────────────────────────

class User(Base):
    __tablename__ = "user"

    __table_args__ = (
        CheckConstraint("statut IN ('actif', 'inactif', 'bloqué')", name="ck_user_statut"),
    )

    id:                  Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nom:                 Mapped[str] = mapped_column(String, nullable=False)
    prenom:              Mapped[str] = mapped_column(String, nullable=False)
    login:               Mapped[str] = mapped_column(String, nullable=False, unique=True)
    password_hash:       Mapped[str] = mapped_column(String, nullable=False)
    statut:              Mapped[str] = mapped_column(String, nullable=False, default="actif")
    tentatives_echouees: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    doit_changer_mdp:    Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Clé étrangère
    role_id: Mapped[int] = mapped_column(Integer, ForeignKey("role.id"), nullable=False)

    # Relations
    role: Mapped[Role] = relationship("Role", back_populates="users")

    messages_envoyes: Mapped[list[Message]] = relationship(
        "Message",
        foreign_keys="Message.expediteur_id",
        back_populates="expediteur",
    )
    messages_recus: Mapped[list[Message]] = relationship(
        "Message",
        foreign_keys="Message.destinataire_id",
        back_populates="destinataire",
    )
    shipments_crees: Mapped[list[Shipment]] = relationship(
        "Shipment",
        back_populates="createur",
        foreign_keys="[Shipment.createur_id]",
        overlaps="modificateur",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} login={self.login!r} role_id={self.role_id}>"