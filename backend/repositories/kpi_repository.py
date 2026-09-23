"""
kpi_repository.py — Accès aux données pour les KPIs (SQLAlchemy)

Fournit les données brutes nécessaires aux calculs des KPIs.
Le calcul lui-même reste dans kpi_engine.py.

Architecture :
    Router → kpi_service → kpi_repository → SessionLocal (SQLAlchemy)
                        ↘ kpi_engine.py (calculs)

Différences vs version sqlite3 :
- get_connection() / cursor  →  Session SQLAlchemy injectée en paramètre
- Délègue à shipment_repository pour les DataFrames (DRY)
- Les 3 fonctions de filtres disponibles utilisent des requêtes ORM ciblées
"""

import pandas as pd
from sqlalchemy import distinct, union_all
from sqlalchemy.orm import Session

from backend.models.shipment import Shipment, Vessel
from backend.repositories.shipment_repository import (
    get_all_shipments,
    get_all_shipments_avec_annules,
)


# ═══════════════════════════════════════════════════════════════════════════════
# DONNÉES POUR LES KPIs
# ═══════════════════════════════════════════════════════════════════════════════

def get_data_kpis(db: Session) -> pd.DataFrame:
    """
    Retourne tous les shipments avec annulés pour les calculs KPI.
    Point d'entrée unique pour kpi_service → kpi_engine.
    Utilisé par : kpi_service (dashboard)
    """
    return get_all_shipments_avec_annules(db)


def get_data_kpis_filtres(
    db: Session,
    mois: str | None = None,
    carrier: str | None = None,
    annee: str | None = None,
) -> pd.DataFrame:
    df = get_all_shipments_avec_annules(db)

    if annee and not df.empty:
       df = df[df["year"] == int(annee)]
    if mois and not df.empty:
        df_normaux = df[df["month"] == mois]
        df_annules = df[
            (df["shipment_status"] == "Cancelled") &
            (pd.to_datetime(df["etd"], errors="coerce")
               .dt.strftime("%B %y") == mois)
        ]
        df = pd.concat([df_normaux, df_annules]).drop_duplicates(subset=["id"])

    if carrier and not df.empty:
        df = df[df["carrier"] == carrier]

    return df

# ═══════════════════════════════════════════════════════════════════════════════
# FILTRES DISPONIBLES — Pour les listes déroulantes du dashboard
# ═══════════════════════════════════════════════════════════════════════════════

def get_mois_disponibles(db: Session) -> list:
    """
    Retourne la liste des mois disponibles, triés chronologiquement par ETD.
    Utilisé par : kpi_service (filtre mois)
    """
    rows = (
        db.query(Shipment.month)
        .filter(Shipment.month.isnot(None))
        .distinct()
        .order_by(Shipment.month.asc())
        .all()
    )
    return [r[0] for r in rows]


def get_carriers_disponibles(db: Session) -> list:
    """
    Retourne la liste des carriers distincts depuis la table vessel.
    Utilisé par : kpi_service (filtre carrier dashboard)
    """
    rows = (
        db.query(Vessel.carrier)
        .distinct()
        .order_by(Vessel.carrier)
        .all()
    )
    return [r[0] for r in rows]


def get_ports_disponibles(db: Session) -> list:
    """
    Retourne la liste de tous les ports distincts
    (chargement + déchargement combinés).
    Utilisé par : kpi_service (filtre port dashboard)
    """
    ports_chargement   = db.query(Shipment.port_chargement.label("port")).distinct()
    ports_dechargement = db.query(Shipment.port_dechargement.label("port")).distinct()

    tous_ports = ports_chargement.union(ports_dechargement).all()
    return sorted([r[0] for r in tous_ports if r[0]])


# ═══════════════════════════════════════════════════════════════════════════════
# RAPPORT CARRIERS — Pour la page rapport carriers
# ═══════════════════════════════════════════════════════════════════════════════

def get_data_rapport_carriers(db: Session) -> pd.DataFrame:
    """
    Retourne les shipments non annulés pour le rapport carriers.
    Les annulés sont comptés séparément via get_data_kpis() pour KPI4.
    Utilisé par : kpi_service (rapport carriers)
    """
    return get_all_shipments(db)