from pydantic import BaseModel
from typing import Optional


# ══════════════════════════════════════════════════════════════════════════════
# REQUÊTE — Ce que React envoie à FastAPI (POST /predictions)
# ══════════════════════════════════════════════════════════════════════════════

class PredictionRequestSchema(BaseModel):
    """
    L'utilisateur choisit un shipment depuis le tableau de la page prédiction.
    React envoie uniquement l'id du shipment sélectionné.

    FastAPI s'occupe ensuite de :
    1. Récupérer le shipment complet depuis db.py (get_shipment_by_id)
    2. Extraire les 9 champs nécessaires au modèle ML invisiblement :
         transit_time, frequency, month,
         volume_booked, confirmed_volume,
         carrier, port_chargement,
         port_dechargement, pays_destination
    3. Appeler predire_retard(dict) depuis Random_forest.py
    4. Retourner PredictionResponseSchema à React

    L'utilisateur ne voit jamais les extractions intermédiaires.
    """
    shipment_id: int


# ══════════════════════════════════════════════════════════════════════════════
# RÉPONSE — Ce que FastAPI retourne à React
# ══════════════════════════════════════════════════════════════════════════════

class PredictionResponseSchema(BaseModel):
    """
    Résultat de la prédiction retourné à React.

    Affiché dans le panneau qui s'ouvre après clic sur [Prédire] :

    ┌──────────────────────────────────────────┐
    │  Vessel        : Grande Milano           │
    │  Carrier       : GRIMALDI LINES          │
    │  De            : Tanger Med              │
    │  Vers          : Civitavecchia           │
    │  Destination   : Italy                   │
    │  ETD           : 10/01/2025              │
    │  ETA           : 20/01/2025              │
    │  Transit Time  : 10 jours                │
    │  Volume Booked : 1000                    │
    │  Confirmed Vol : 950                     │
    │  ──────────────────────────────────────  │
    │  🔴 En retard                            │
    │  Probabilité de retard : 73.5%           │
    │  Niveau de risque      : Élevé           │
    │  Seuil utilisé         : 0.423           │
    └──────────────────────────────────────────┘

    Séparation claire :
    - Contexte shipment  → informations pour identifier le shipment
                           et contextualiser le résultat ML
    - Résultat ML        → ce que retourne predire_retard()
                           depuis Random_forest.py
    """

    # ── Contexte shipment (pour affichage React) ──────────────────────────────
    # Identification du shipment
    shipment_id:       int
    vessel_nom:        Optional[str]   = None
    carrier:           Optional[str]   = None
    port_chargement:   Optional[str]   = None
    port_dechargement: Optional[str]   = None
    pays_destination:  Optional[str]   = None
    etd:               Optional[str]   = None  # str pour affichage simple
    eta:               Optional[str]   = None  # str pour affichage simple
    transit_time:      Optional[int]   = None
    volume_booked:     Optional[float] = None
    confirmed_volume:  Optional[float] = None

    # ── Résultat ML retourné par predire_retard() ─────────────────────────────
    prediction:         int    # 0 = à l'heure, 1 = en retard
    probabilite_retard: float  # ex: 73.5 (en %)
    niveau_risque:str  # "Faible" / "Modéré" / "Élevé"  ← "Moyen" → "Modéré"
    label: str         # "À l'heure" / "À surveiller" / "En retard"  ← 3 valeurs


# ══════════════════════════════════════════════════════════════════════════════
# ERREUR — Si la prédiction est impossible
# ══════════════════════════════════════════════════════════════════════════════

class PredictionErrorSchema(BaseModel):
    """
    Retourné par FastAPI si la prédiction est impossible.

    Cas possibles :
    - Shipment annulé (Cancelled) → pas de données réelles disponibles
    - Shipment introuvable        → id inexistant en base
    - Données insuffisantes       → transit_time ou volume manquant

    React affiche ce message à l'utilisateur à la place du résultat ML.

    Exemples de messages :
    - "Prédiction impossible : ce shipment est annulé."
    - "Shipment introuvable en base de données."
    - "Données insuffisantes : transit_time manquant."
    """
    shipment_id: int
    erreur:      str