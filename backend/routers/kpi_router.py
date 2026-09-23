"""
kpi_router.py — Routes HTTP : KPIs et rapport carriers

Routes accessibles Opérateur ET Manager :
    GET /kpis/dashboard              → 5 KPIs résumé (page principale)
    GET /kpis/filtres                → valeurs disponibles pour les filtres
    GET /kpis/{kpi_id}/groupe/{groupby} → KPI groupé (graphiques)
    GET /kpis/kpi3/detail            → détail KPI3 (shipments critiques)
    GET /kpis/kpi4/detail            → détail KPI4 (annulés/modifiés)
    GET /kpis/kpi4/par_mois          → évolution mensuelle KPI4 (graphe linéaire)
    GET /kpis/kpi5/detail            → détail KPI5 (retards)
    GET /kpis/{kpi_id}/distribution  → valeurs individuelles (histogrammes)
    GET /kpis/rapport-carriers       → rapport performance par carrier

Architecture :
kpi_router → kpi_service → kpi_repository + kpi_engine → db.py
"""

from fastapi import APIRouter, Depends, Query
from typing import Optional
from sqlalchemy.orm import Session

from backend.services.auth_service import get_current_operateur_ou_manager
from backend.services.kpi_service import (
    get_dashboard,
    get_filtres_disponibles,
    get_kpi_par_groupe,
    get_kpi3_detail,
    get_kpi4_detail,
    get_kpi4_par_mois,
    get_kpi5_detail,
    get_distribution,
    get_rapport_carriers,
    get_rapport_carriers_mensuel,
)
from backend.schemas.kpi_schema import (
    FiltresDashboardSchema,
    DashboardSchema,
    KpiParGroupeSchema,
    Kpi3DetailSchema,
    Kpi4DetailSchema,
    Kpi5DetailSchema,
    KpiDistributionSchema,
    CarrierRapportSchema,
)
from database.db import get_db

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════════════
# FILTRES DISPONIBLES
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/filtres", tags=["KPIs"])
def get_filtres(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_operateur_ou_manager),
):
    return get_filtres_disponibles(db)


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD — 5 KPIs en un seul appel
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/dashboard", response_model=DashboardSchema, tags=["KPIs"])
def get_dashboard_kpis(
    db: Session = Depends(get_db),
    mois:    Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    annee:   Optional[str] = Query(None),
    user:    dict = Depends(get_current_operateur_ou_manager),
):
    filtres = FiltresDashboardSchema(mois=mois, carrier=carrier, annee=annee)
    return get_dashboard(db, filtres)


# ═══════════════════════════════════════════════════════════════════════════════
# KPI PAR GROUPE — Pour les graphiques
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/{kpi_id}/groupe/{groupby}", response_model=KpiParGroupeSchema, tags=["KPIs"])
def get_kpi_groupe(
    kpi_id:  str,
    groupby: str,
    db: Session = Depends(get_db),
    mois:    Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    annee:   Optional[str] = Query(None),
    user:    dict = Depends(get_current_operateur_ou_manager),
):
    filtres = FiltresDashboardSchema(mois=mois, carrier=carrier, annee=annee)
    return get_kpi_par_groupe(db, kpi_id, groupby, filtres)


# ═══════════════════════════════════════════════════════════════════════════════
# DÉTAILS PAR KPI
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/kpi3/detail", response_model=Kpi3DetailSchema, tags=["KPIs"])
def get_detail_kpi3(
    db: Session = Depends(get_db),
    mois:    Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    annee:   Optional[str] = Query(None),
    user:    dict = Depends(get_current_operateur_ou_manager),
):
    filtres = FiltresDashboardSchema(mois=mois, carrier=carrier, annee=annee)
    return get_kpi3_detail(db, filtres)


@router.get("/kpi4/detail", response_model=Kpi4DetailSchema, tags=["KPIs"])
def get_detail_kpi4(
    db: Session = Depends(get_db),
    mois:    Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    annee:   Optional[str] = Query(None),
    user:    dict = Depends(get_current_operateur_ou_manager),
):
    filtres = FiltresDashboardSchema(mois=mois, carrier=carrier, annee=annee)
    return get_kpi4_detail(db, filtres)


# ═══════════════════════════════════════════════════════════════════════════════
# KPI4 — ÉVOLUTION MENSUELLE (graphe linéaire, filtre carrier indépendant)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/kpi4/par_mois", tags=["KPIs"])
def get_kpi4_mois(
    db: Session = Depends(get_db),
    annee:   Optional[str] = Query(None, description="Filtrer par année (ex: 2024)"),
    carrier: Optional[str] = Query(None, description="Filtrer par carrier"),
    user:    dict = Depends(get_current_operateur_ou_manager),
):
    """
    Évolution mensuelle des statuts KPI4 (Normal / Modifié / Annulé).
    Filtre carrier indépendant du reste de la page — ne recharge que le graphe linéaire.

    Retourne :
    {
        "par_mois": [
            { "month": "January", "normal": 12, "modifie": 3, "annule": 1 },
            ...
        ]
    }
    """
    return get_kpi4_par_mois(db, annee=annee, carrier=carrier)


@router.get("/kpi5/detail", response_model=Kpi5DetailSchema, tags=["KPIs"])
def get_detail_kpi5(
    db: Session = Depends(get_db),
    mois:    Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    annee:   Optional[str] = Query(None),
    user:    dict = Depends(get_current_operateur_ou_manager),
):
    filtres = FiltresDashboardSchema(mois=mois, carrier=carrier, annee=annee)
    return get_kpi5_detail(db, filtres)


# ═══════════════════════════════════════════════════════════════════════════════
# DISTRIBUTIONS — Pour les histogrammes
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/{kpi_id}/distribution", response_model=KpiDistributionSchema, tags=["KPIs"])
def get_kpi_distribution(
    kpi_id:  str,
    db: Session = Depends(get_db),
    mois:    Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    annee:   Optional[str] = Query(None),
    user:    dict = Depends(get_current_operateur_ou_manager),
):
    filtres = FiltresDashboardSchema(mois=mois, carrier=carrier, annee=annee)
    return get_distribution(db, kpi_id, filtres)


# ═══════════════════════════════════════════════════════════════════════════════
# RAPPORT CARRIERS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/rapport-carriers", response_model=list[CarrierRapportSchema], tags=["KPIs"])
def get_rapport(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_operateur_ou_manager),
):
    return get_rapport_carriers(db)


@router.get("/rapport-carriers-mensuel", tags=["KPIs"])
def get_rapport_mensuel(
    db: Session = Depends(get_db),
    annee:   Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    user:    dict = Depends(get_current_operateur_ou_manager),
):
    return get_rapport_carriers_mensuel(db, annee, carrier)