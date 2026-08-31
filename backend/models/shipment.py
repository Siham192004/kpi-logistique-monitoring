"""
shipment.py — Modèles Vessel et Shipment (SQLAlchemy ORM)

Correspond aux tables :
    vessel   : id, nom, carrier
    shipment : toutes les colonnes brutes + colonnes dérivées ETL
               + vessel_id (FK) + createur_id (FK → user)

Note : l'opérateur n'est PAS une colonne — il passe par la relation
       createur → User (JOIN). Accessible via shipment.createur.prenom/nom
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

# Imports uniquement pour Pylance / mypy — jamais exécutés à runtime
if TYPE_CHECKING:
    from .message import Message
    from .user import User


# ─────────────────────────────────────────────
# VESSEL
# ─────────────────────────────────────────────

class Vessel(Base):
    __tablename__ = "vessel"

    __table_args__ = (
        UniqueConstraint("nom", "carrier", name="uq_vessel_nom_carrier"),
    )

    id:      Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nom:     Mapped[str] = mapped_column(String, nullable=False)
    carrier: Mapped[str] = mapped_column(String, nullable=False)

    shipments: Mapped[list[Shipment]] = relationship("Shipment", back_populates="vessel")

    def __repr__(self) -> str:
        return f"<Vessel id={self.id} nom={self.nom!r} carrier={self.carrier!r}>"


# ─────────────────────────────────────────────
# SHIPMENT
# ─────────────────────────────────────────────

class Shipment(Base):
    __tablename__ = "shipment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── Données brutes ────────────────────────────────────────────────────────
    port_chargement:   Mapped[str] = mapped_column(String, nullable=False)
    port_dechargement: Mapped[str] = mapped_column(String, nullable=False)
    pays_destination:  Mapped[str] = mapped_column(String, nullable=False)

    etd: Mapped[Optional[date]] = mapped_column(Date)
    atd: Mapped[Optional[date]] = mapped_column(Date)
    eta: Mapped[Optional[date]] = mapped_column(Date)
    ata: Mapped[Optional[date]] = mapped_column(Date)

    incoterm:         Mapped[Optional[str]]   = mapped_column(String)
    volume_booked:    Mapped[Optional[float]] = mapped_column(Float)
    confirmed_volume: Mapped[Optional[float]] = mapped_column(Float)
    charged_volume:   Mapped[Optional[float]] = mapped_column(Float)
    transit_time:     Mapped[Optional[int]]   = mapped_column(Integer)
    frequency:        Mapped[Optional[str]]   = mapped_column(String)

    # ── Colonnes dérivées (calculées par l'ETL) ───────────────────────────────
    month:                         Mapped[Optional[str]]   = mapped_column(String)
    year:                          Mapped[Optional[int]]   = mapped_column(Integer)
    shipment_status:               Mapped[str]             = mapped_column(String, nullable=False, default="Normal")
    type_annulation:               Mapped[str]             = mapped_column(String, nullable=False, default="Non annulé")
    transit_time_reel:             Mapped[Optional[float]] = mapped_column(Float)
    eta_deviation:                 Mapped[Optional[float]] = mapped_column(Float)
    etd_deviation:                 Mapped[Optional[float]] = mapped_column(Float)
    is_delayed:                    Mapped[Optional[float]] = mapped_column(Float)
    volume_ratio_loaded:           Mapped[Optional[float]] = mapped_column(Float)
    volume_ratio_allocated_booked: Mapped[Optional[float]] = mapped_column(Float)
    niveau_retard:                 Mapped[Optional[str]]   = mapped_column(String)

    # ── Clés étrangères ───────────────────────────────────────────────────────
    vessel_id:   Mapped[int] = mapped_column(Integer, ForeignKey("vessel.id"), nullable=False)
    createur_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"),   nullable=False)

    # ── Relations ─────────────────────────────────────────────────────────────
    # L'opérateur est accessible via : shipment.createur.prenom + " " + shipment.createur.nom
    vessel:   Mapped[Vessel] = relationship("Vessel", back_populates="shipments")
    createur: Mapped[User]   = relationship("User",   back_populates="shipments_crees")

    messages: Mapped[list[Message]] = relationship(
        "Message",
        back_populates="shipment",
    )

    def __repr__(self) -> str:
        return (
            f"<Shipment id={self.id} "
            f"{self.port_chargement}→{self.port_dechargement} "
            f"etd={self.etd}>"
        )