from pydantic import BaseModel
from typing import Optional


# ════════════════════════════════════════════════════════════════════════════════
# FILTRES — Ce que React envoie pour filtrer le dashboard
# ════════════════════════════════════════════════════════════════════════════════

class FiltresDashboardSchema(BaseModel):
    """
    Filtres appliqués par l'utilisateur sur le dashboard.
    Tous optionnels : si aucun filtre → données globales.
    Correspond à la fonction filtrer() dans kpi_engine.py.
    """
    mois:    Optional[str] = None   # ex: "July 24"
    carrier: Optional[str] = None   # ex: "GRIMALDI LINES"
    annee:   Optional[str] = None 


# ════════════════════════════════════════════════════════════════════════════════
# VALEUR D'UN KPI — Résultat global d'un seul KPI
# ════════════════════════════════════════════════════════════════════════════════

class KpiValeurSchema(BaseModel):
    """
    Résultat global d'un KPI (valeur + contexte).
    Utilisé pour afficher chaque carte KPI sur le dashboard.

    Exemples :
    - KPI1 : valeur=94.5, effectif=1200, niveau="To monitor", objectif=95.0
    - KPI4 : valeur=12.3, effectif=1500, niveau="To monitor", objectif=10.0
    """
    kpi_id:    str            # "KPI1", "KPI2", ..., "KPI5"
    label:     str            # "% Volume chargé / Volume alloué"
    valeur:    Optional[float] = None   # None si pas assez de données
    valeur_affichee: str                # "95.2%" ou "42 shipments" — affichage carte
    effectif:  int            # nb shipments utilisés dans le calcul
    niveau:    Optional[str]  = None   # "On target" / "To monitor" / "Critical"
    objectif_texte:  str               # ">= 95%" ou "< 10% On target | ..." 
    unite:     str = "%"               # unité d'affichage 


# ════════════════════════════════════════════════════════════════════════════════
# VALEUR PAR GROUPE — Pour les graphiques par carrier / mois / port
# ════════════════════════════════════════════════════════════════════════════════

class KpiParGroupeItemSchema(BaseModel):
    """Un item dans un groupby (ex: carrier=GRIMALDI LINES, valeur=94.5)."""
    groupe:  str            # valeur du groupe (ex: "GRIMALDI LINES", "July 24")
    valeur:  Optional[float] = None
    effectif: Optional[int] = None
    niveau:  Optional[str]  = None   # "On target" / "To monitor" / "Critical"


class KpiParGroupeSchema(BaseModel):
    """
    Résultats d'un KPI groupé par carrier, mois ou port.
    Utilisé pour les graphiques barres/lignes du dashboard.

    Exemple groupby='carrier' pour KPI1 :
    [
      { groupe: "GRIMALDI LINES", valeur: 96.2, niveau: "On target" },
      { groupe: "MSC",            valeur: 88.1, niveau: "To monitor" },
      ...
    ]
    """
    kpi_id:    str
    groupby:   str                        # "carrier", "month", "port_chargement"
    items:     list[KpiParGroupeItemSchema]


# ════════════════════════════════════════════════════════════════════════════════
# DASHBOARD — Résumé des 5 KPIs (page principale)
# ════════════════════════════════════════════════════════════════════════════════

class DashboardSchema(BaseModel):
    """
    Résumé complet des 5 KPIs retourné à React pour la page dashboard.
    Un seul appel API → React reçoit tout et affiche les 5 cartes KPI.

    Correspond à la boucle 1→5 du diagramme de séquence
    "Consulter le Dashboard KPI".   
    """
    filtres_appliques: FiltresDashboardSchema
    kpi1: KpiValeurSchema 
    kpi2: KpiValeurSchema 
    kpi3: KpiValeurSchema
    kpi4: KpiValeurSchema
    kpi5: KpiValeurSchema


# ════════════════════════════════════════════════════════════════════════════════
# DETAIL KPI3 — Retards dans les ports de transbordement
# ════════════════════════════════════════════════════════════════════════════════

class Kpi3CategorieItemSchema(BaseModel):
    """Une catégorie métier KPI3 avec son nombre de shipments."""
    categorie:    str   # ex: 'Retard arrivée - Critical'
    niveau:       str   # 'On target' / 'To monitor' / 'Critical'
    nombre:       int

    # Rétrocompatibilité — gardés pour ne pas casser d'autres usages
    niveau_etd_deviation: Optional[str] = None
    niveau_delay_days:    Optional[str] = None


class Kpi3ShipmentCritiqueSchema(BaseModel):
    """Un shipment critique pour KPI3."""
    shipment_id:      int
    carrier:          Optional[str]   = None
    vessel_nom:       Optional[str]   = None
    month:            Optional[str]   = None
    port_chargement:  Optional[str]   = None
    port_dechargement:Optional[str]   = None
    etd_deviation:    Optional[float] = None
    eta_deviation:    Optional[float] = None
    categorie_metier: Optional[str]   = None   # ← nouvelle
    niveau_global:    Optional[str]   = None   # ← nouvelle
    # Rétrocompatibilité
    niveau_etd_deviation: Optional[str] = None
    niveau_delay_days:    Optional[str] = None


class Kpi3DetailSchema(BaseModel):
    """Détail complet de KPI3 — 7 catégories métier + tous les shipments."""
    repartition:         list[Kpi3CategorieItemSchema]
    shipments_critiques: list[Kpi3ShipmentCritiqueSchema]  # tous les shipments
    total_critiques:     int

# ════════════════════════════════════════════════════════════════════════════════
# DETAIL KPI4 — Taux de modifications et annulations
# ════════════════════════════════════════════════════════════════════════════════

class Kpi4DetailSchema(BaseModel):
    """
    Détail complet de KPI4.
    - repartition_statut   : Normal / Modifié / Annulé
    - repartition_annulation : Avant départ / Après départ
    Correspond à kpi4_detail() + kpi4_type_annulation() dans kpi_engine.py.
    """
    valeur:                  Optional[float] = None
    niveau:                  Optional[str]   = None
    effectif:                int
    nb_annules:              int
    nb_modifies:             int
    nb_normaux:              int
    nb_avant_depart:         int
    nb_apres_depart:         int
    pct_annules:      float = 0.0
    pct_modifies:     float = 0.0
    pct_normaux:      float = 0.0
    pct_avant_depart: float = 0.0
    pct_apres_depart: float = 0.0


# ════════════════════════════════════════════════════════════════════════════════
# DETAIL KPI5 — Déviation ETA vs ATA
# ════════════════════════════════════════════════════════════════════════════════

class Kpi5DetailSchema(BaseModel):
    """
    Détail complet de KPI5.
    - nb_en_retard / nb_a_lheure pour vérifier la composition du ratio
    Correspond à kpi5_detail() dans kpi_engine.py.
    """
    valeur:        Optional[float] = None
    niveau:        Optional[str]   = None
    effectif:      int
    nb_en_retard:  int
    nb_a_lheure:   int
    pct_en_retard: float  
    pct_a_lheure:  float  


# ════════════════════════════════════════════════════════════════════════════════
# DISTRIBUTION — Données pour graphiques/histogrammes
# ════════════════════════════════════════════════════════════════════════════════

class KpiDistributionSchema(BaseModel):
    """
    Valeurs individuelles d'un KPI pour affichage histogramme/courbe.
    Correspond à kpi1_distribution(), kpi2_distribution(), kpi5_distribution().

    valeurs : liste des ratios ou déviations individuels par shipment
    """
    kpi_id: str
    valeurs: list[Optional[float]]


# ════════════════════════════════════════════════════════════════════════════════
# RAPPORT CARRIERS — Page rapport carriers (Manager/Consultant)
# ════════════════════════════════════════════════════════════════════════════════

class CarrierRapportSchema(BaseModel):
    """
    Résumé des performances d'un carrier sur tous les KPIs.
    Utilisé pour la page "Rapport carriers" (Manager/Consultant).
    Un item par carrier.
    """
    carrier:       str
    kpi1:          Optional[float] = None   # % volume chargé/alloué
    kpi2:          Optional[float] = None   # % volume alloué/réservé
    kpi4:          Optional[float] = None   # % modifiés ou annulés
    kpi5:          Optional[float] = None   # % en retard
    niveau_global: Optional[str]   = None   # "On target" / "To monitor" / "Critical"
    effectif:      int                      # nb shipments du carrier

    
