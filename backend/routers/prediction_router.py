

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.services.auth_service import get_current_operateur_ou_manager
from backend.services.prediction_service import (
    predire_retard_shipment,
    lister_shipments_eligibles,
)
from backend.schemas.prediction_schema import (
    PredictionRequestSchema,
    PredictionResponseSchema,
)
from database.db import get_db

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════════════
# SHIPMENTS ÉLIGIBLES
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/eligibles", tags=["Prédiction"])
def get_eligibles(db: Session = Depends(get_db), user: dict = Depends(get_current_operateur_ou_manager)):
    """
    Retourne la liste des shipments éligibles à la prédiction ML.

    Critères d'éligibilité :
    - Statut Normal (pas Cancelled)
    - Features ML complètes : transit_time, volumes, carrier,
      ports, pays_destination, month, frequency

    React affiche cette liste dans le tableau de la page prédiction.
    L'utilisateur sélectionne un shipment → clic [Prédire].
    """
    return lister_shipments_eligibles(db)


# ═══════════════════════════════════════════════════════════════════════════════
# PRÉDICTION
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/", response_model=PredictionResponseSchema, tags=["Prédiction"])
def predict(
    data: PredictionRequestSchema,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_operateur_ou_manager),
):
    """
    Prédit le retard d'un shipment via le modèle ML (Régression Logistique).

    Flux (diagramme seq_predire_retard) :
    1. React envoie { shipment_id: 142 }
    2. FastAPI récupère le shipment complet depuis la DB
    3. Vérifie l'éligibilité (Normal + features complètes)
    4. Appelle predire_retard() depuis engine/Regression_logistique.py
    5. Retourne le résultat avec le contexte du shipment

    Retourne :
    - Contexte shipment (vessel, carrier, ports, dates, volumes)
    - prediction    : 0 = À l'heure, 1 = En retard
    - probabilite_retard : ex: 73.5 (en %)
    - niveau_risque : Faible / Moyen / Élevé
    - label         : "À l'heure" / "En retard"
    """
    return predire_retard_shipment(db, data.shipment_id)