"""
kpi_router.py — Routes HTTP : KPIs et rapport carriers

Routes accessibles Opérateur ET Manager :
    GET /kpis/dashboard              → 5 KPIs résumé (page principale)
    GET /kpis/filtres                → valeurs disponibles pour les filtres
    GET /kpis/{kpi_id}/groupe/{groupby} → KPI groupé (graphiques)
    GET /kpis/kpi3/detail            → détail KPI3 (shipments critiques)
    GET /kpis/kpi4/detail            → détail KPI4 (annulés/modifiés)
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
def get_filtres(db: Session = Depends(get_db),user: dict = Depends(get_current_operateur_ou_manager),):
    """
    Retourne les valeurs disponibles pour les filtres du dashboard :
    - Liste des mois disponibles (triés chronologiquement)
    - Liste des carriers distincts
    - Liste des ports distincts (chargement + déchargement)

    Appelé au chargement du dashboard pour alimenter les listes déroulantes.
    """
    return get_filtres_disponibles(db)


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD — 5 KPIs en un seul appel
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/dashboard", response_model=DashboardSchema, tags=["KPIs"])
def get_dashboard_kpis(
    db: Session = Depends(get_db),
    mois:    Optional[str] = Query(None, description="Filtrer par mois (ex: July 24)"),
    carrier: Optional[str] = Query(None, description="Filtrer par carrier"),
    annee: Optional[str] = Query(None, description="Filtrer par année (ex: 2024)"),
    user:    dict = Depends(get_current_operateur_ou_manager),
):
    """
    Retourne les 5 KPIs pour la page dashboard.
    Un seul appel API → React affiche les 5 cartes KPI.

    Filtres optionnels combinables :
    - mois    → ex: "July 24"
    - carrier → ex: "GRIMALDI LINES"
    - port    → ex: "Tanger Med" (chargement ou déchargement)

    Correspond à la boucle 1→5 du diagramme de séquence
    "Consulter le Dashboard KPI".
    """
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
    annee: Optional[str] = Query(None, description="Filtrer par année (ex: 2024)"),
    user:    dict = Depends(get_current_operateur_ou_manager),
):
    """
    Retourne un KPI groupé par carrier, mois ou port.
    Utilisé pour les graphiques barres/lignes de la page détail KPIs.

    kpi_id  : KPI1, KPI2, KPI4, KPI5
    groupby : carrier | month | port_chargement | port_dechargement

    Exemple : GET /kpis/KPI1/groupe/carrier
    → retourne le % volume chargé/alloué par carrier
    """
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
    annee: Optional[str] = Query(None, description="Filtrer par année (ex: 2024)"),
    user:    dict = Depends(get_current_operateur_ou_manager),
):
    """
    Détail KPI3 — Retards dans les ports de transbordement.
    - Répartition On target / To monitor / Critical
    - Liste des shipments critiques (ETD deviation ou ETA deviation)
    Affiché dans l'onglet KPI3 de la page détail.
    """
    filtres = FiltresDashboardSchema(mois=mois, carrier=carrier, annee=annee)
    return get_kpi3_detail(db, filtres)


@router.get("/kpi4/detail", response_model=Kpi4DetailSchema, tags=["KPIs"])
def get_detail_kpi4(
    db: Session = Depends(get_db),
    mois:    Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    annee: Optional[str] = Query(None, description="Filtrer par année (ex: 2024)"),
    user:    dict = Depends(get_current_operateur_ou_manager),
):
    """
    Détail KPI4 — Taux de modifications et annulations.
    - Valeur globale + niveau (On target / To monitor / Critical)
    - Répartition Normal / Modifié / Annulé
    - Répartition Avant départ / Après départ
    Affiché dans l'onglet KPI4 de la page détail.
    """
    filtres = FiltresDashboardSchema(mois=mois, carrier=carrier, annee=annee)
    return get_kpi4_detail(db, filtres)


@router.get("/kpi5/detail", response_model=Kpi5DetailSchema, tags=["KPIs"])
def get_detail_kpi5(
    db: Session = Depends(get_db),
    mois:    Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    annee: Optional[str] = Query(None, description="Filtrer par année (ex: 2024)"),
    user:    dict = Depends(get_current_operateur_ou_manager),
):
    """
    Détail KPI5 — Déviation ETA vs ATA.
    - Valeur globale + niveau
    - Répartition Normal / En retard
    Affiché dans l'onglet KPI5 de la page détail.
    """
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
    annee: Optional[str] = Query(None, description="Filtrer par année (ex: 2024)"),
    user:    dict = Depends(get_current_operateur_ou_manager),
):
    """
    Retourne les valeurs individuelles d'un KPI pour histogramme.
    Disponible pour : KPI1, KPI2, KPI5.
    Utilisé pour les graphiques de distribution dans la page détail.
    """
    filtres = FiltresDashboardSchema(mois=mois, carrier=carrier, annee=annee)
    return get_distribution(db, kpi_id, filtres)


# ═══════════════════════════════════════════════════════════════════════════════
# RAPPORT CARRIERS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/rapport-carriers", response_model=list[CarrierRapportSchema], tags=["KPIs"])
def get_rapport(db: Session = Depends(get_db),user: dict = Depends(get_current_operateur_ou_manager),):
    """
    Retourne les performances de chaque carrier sur tous les KPIs.
    Utilisé pour la page rapport carriers (Opérateur + Manager).

    Pour chaque carrier :
    - KPI1 : % volume chargé / alloué
    - KPI2 : % volume alloué / réservé
    - KPI4 : % modifiés ou annulés
    - KPI5 : % en retard
    - Niveau global : le pire des niveaux (Critical > To monitor > On target)
    """
    return get_rapport_carriers(db)


@router.get("/rapport-carriers-mensuel", tags=["KPIs"])
def get_rapport_mensuel(
    db: Session = Depends(get_db),
    annee:   Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    user: dict = Depends(get_current_operateur_ou_manager),
):
    return get_rapport_carriers_mensuel(db, annee, carrier)