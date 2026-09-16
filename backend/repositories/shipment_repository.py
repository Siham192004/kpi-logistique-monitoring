"""
shipment_repository.py — Accès aux données : tables shipment et vessel (SQLAlchemy)
"""

import pandas as pd
from sqlalchemy.orm import Session

from backend.models.shipment import Shipment, Vessel
from backend.models.message import Message


# ─────────────────────────────────────────────
# HELPERS DE SÉRIALISATION
# ─────────────────────────────────────────────

def _shipment_to_dict(s: Shipment) -> dict:
    """Convertit un objet Shipment ORM en dict plat (avec vessel_nom, carrier et opérateur)."""
    return {
        "id":                           s.id,
        "port_chargement":              s.port_chargement,
        "port_dechargement":            s.port_dechargement,
        "pays_destination":             s.pays_destination,
        "etd":                          s.etd,
        "atd":                          s.atd,
        "eta":                          s.eta,
        "ata":                          s.ata,
        "incoterm":                     s.incoterm,
        "volume_booked":                s.volume_booked,
        "confirmed_volume":             s.confirmed_volume,
        "charged_volume":               s.charged_volume,
        "transit_time":                 s.transit_time,
        "frequency":                    s.frequency,
        "month":                        s.month,
        "year":                         s.year,
        "shipment_status":              s.shipment_status,
        "type_annulation":              s.type_annulation,
        "transit_time_reel":            s.transit_time_reel,
        "eta_deviation":                s.eta_deviation,
        "etd_deviation":                s.etd_deviation,
        "is_delayed":                   s.is_delayed,
        "volume_ratio_loaded":          s.volume_ratio_loaded,
        "volume_ratio_allocated_booked":s.volume_ratio_allocated_booked,
        "niveau_retard":                s.niveau_retard,
        "vessel_id":                    s.vessel_id,
        "createur_id":                  s.createur_id,
        # Traçabilité
        "created_at":                   s.created_at,
        "updated_at":                   s.updated_at,
        "updated_by_id":                s.updated_by_id,
        # JOIN vessel
        "vessel_nom":                   s.vessel.nom     if s.vessel else None,
        "carrier":                      s.vessel.carrier if s.vessel else None,
        # JOIN user → opérateur (prenom + nom séparés pour le frontend)
        "operateur_prenom":             s.createur.prenom if s.createur else None,
        "operateur_nom":                s.createur.nom    if s.createur else None,
        # JOIN user → modificateur (qui a modifié)
        "modificateur_prenom": s.modificateur.prenom if s.modificateur else None,
        "modificateur_nom":    s.modificateur.nom    if s.modificateur else None,
        # Traçabilité suppression
        "deleted_at":       s.deleted_at,
        "deleted_by_id":    s.deleted_by_id,
        "suppresseur_prenom": s.suppresseur.prenom if s.suppresseur else None,
        "suppresseur_nom":    s.suppresseur.nom    if s.suppresseur else None,
    }


def _vessel_to_dict(v: Vessel) -> dict:
    return {"id": v.id, "nom": v.nom, "carrier": v.carrier}


# ═══════════════════════════════════════════════════════════════════════════════
# LECTURE — SHIPMENT
# ═══════════════════════════════════════════════════════════════════════════════

def get_all_shipments(db: Session) -> pd.DataFrame:
    shipments = (
        db.query(Shipment)
        .join(Vessel)
        .filter(
            Shipment.shipment_status != "Cancelled",
            Shipment.deleted_at == None  # ← exclure les supprimés
        )
        .all()
    )
    return pd.DataFrame([_shipment_to_dict(s) for s in shipments])


def get_all_shipments_avec_annules(db: Session) -> pd.DataFrame:
    shipments = (
        db.query(Shipment)
        .join(Vessel)
        .filter(Shipment.deleted_at == None)  # ← exclure les supprimés
        .all()
    )
    return pd.DataFrame([_shipment_to_dict(s) for s in shipments])

def get_shipments_supprimes(db: Session) -> pd.DataFrame:
    shipments = (
        db.query(Shipment)
        .join(Vessel)
        .filter(Shipment.deleted_at != None)
        .all()
    )
    return pd.DataFrame([_shipment_to_dict(s) for s in shipments])


def get_shipment_by_id(db: Session, shipment_id: int) -> dict | None:
    s = (
        db.query(Shipment)
        .join(Vessel)
        .filter(Shipment.id == shipment_id)
        .first()
    )
    return _shipment_to_dict(s) if s else None


def get_shipments_by_createur(db: Session, createur_id: int) -> pd.DataFrame:
    shipments = (
        db.query(Shipment)
        .join(Vessel)
        .filter(Shipment.createur_id == createur_id)
        .order_by(Shipment.etd.desc())
        .all()
    )
    return pd.DataFrame([_shipment_to_dict(s) for s in shipments])


def has_messages(db: Session, shipment_id: int) -> int:
    return (
        db.query(Message)
        .filter(Message.shipment_id == shipment_id)
        .count()
    )


# ═══════════════════════════════════════════════════════════════════════════════
# CRÉATION — SHIPMENT
# ═══════════════════════════════════════════════════════════════════════════════

def insert_shipment(db: Session, data: dict) -> int:
    shipment = Shipment(**data)
    db.add(shipment)
    db.flush()
    return shipment.id


# ═══════════════════════════════════════════════════════════════════════════════
# MISE À JOUR — SHIPMENT
# ═══════════════════════════════════════════════════════════════════════════════

def update_shipment(db: Session, shipment_id: int, data: dict) -> bool:
    rows = (
        db.query(Shipment)
        .filter(Shipment.id == shipment_id)
        .update(data)
    )
    return rows > 0


def update_colonnes_derivees(db: Session, shipment_id: int, data: dict) -> bool:
    champs = {
        "month":                         data.get("month"),
        "year":                          data.get("year"),
        "transit_time_reel":             data.get("transit_time_reel"),
        "eta_deviation":                 data.get("eta_deviation"),
        "etd_deviation":                 data.get("etd_deviation"),
        "is_delayed":                    data.get("is_delayed"),
        "volume_ratio_loaded":           data.get("volume_ratio_loaded"),
        "volume_ratio_allocated_booked": data.get("volume_ratio_allocated_booked"),
        "niveau_retard":                 data.get("niveau_retard"),
    }
    rows = (
        db.query(Shipment)
        .filter(Shipment.id == shipment_id)
        .update(champs)
    )
    return rows > 0


# ═══════════════════════════════════════════════════════════════════════════════
# SUPPRESSION — SHIPMENT
# ═══════════════════════════════════════════════════════════════════════════════

def delete_shipment(db: Session, shipment_id: int, deleted_by_id: int) -> bool:
    from datetime import datetime, timezone
    rows = (
        db.query(Shipment)
        .filter(Shipment.id == shipment_id)
        .update({
            "deleted_at":    datetime.now(timezone.utc),
            "deleted_by_id": deleted_by_id,
            "updated_at":    None,   # ✅ annule le onupdate automatique
            "updated_by_id": None,   # ✅ s'assure qu'il n'y a pas de modificateur
        })
    )
    return rows > 0


# ═══════════════════════════════════════════════════════════════════════════════
# VESSEL
# ═══════════════════════════════════════════════════════════════════════════════

def get_all_vessels(db: Session) -> pd.DataFrame:
    vessels = (
        db.query(Vessel)
        .order_by(Vessel.carrier, Vessel.nom)
        .all()
    )
    return pd.DataFrame([_vessel_to_dict(v) for v in vessels])


def get_carriers_distincts(db: Session) -> list:
    rows = (
        db.query(Vessel.carrier)
        .distinct()
        .order_by(Vessel.carrier)
        .all()
    )
    return [r[0] for r in rows]


def get_ou_creer_vessel(db: Session, nom: str, carrier: str) -> int:
    vessel = (
        db.query(Vessel)
        .filter(Vessel.nom == nom, Vessel.carrier == carrier)
        .first()
    )
    if vessel:
        return vessel.id

    nouveau = Vessel(nom=nom, carrier=carrier)
    db.add(nouveau)
    db.flush()
    return nouveau.id