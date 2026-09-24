"""
shipment_router.py — Routes HTTP : gestion des shipments

Routes accessibles Opérateur ET Manager (GET) :
    GET  /shipments/              → liste des shipments (filtres optionnels)
    GET  /shipments/carriers      → liste des carriers (liste déroulante)
    GET  /shipments/{id}          → détail d'un shipment

Routes Opérateur uniquement (POST, PUT, DELETE) :
    POST   /shipments/            → créer un shipment
    PUT    /shipments/{id}        → modifier un shipment
    DELETE /shipments/{id}        → supprimer un shipment

Architecture :
shipment_router → shipment_service → shipment_repository → db.py
"""

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from typing import Optional
from sqlalchemy.orm import Session

from backend.services.auth_service import (
    get_current_operateur,
    get_current_operateur_ou_manager,
)
from backend.services.shipment_service import (
    lister_shipments,
    obtenir_shipment,
    lister_carriers,
    creer_shipment,
    modifier_shipment,
    supprimer_shipment,
    recalculer_toutes_colonnes_derivees,
)
from backend.services.messaging_service import ws_manager
from backend.schemas.shipment_schema import (
    ShipmentCreateSchema,
    ShipmentUpdateSchema,
    ShipmentResponseSchema,
    DeleteResponseSchema,
    CarrierResponseSchema,
)
from database.db import get_db

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════════════
# LECTURE — Opérateur ET Manager
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/", tags=["Shipments"])
def get_shipments(
    carrier: Optional[str] = Query(None, description="Filtrer par carrier"),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_operateur_ou_manager),
):
    """
    Retourne la liste des shipments non annulés.

    Filtres optionnels :
    - carrier → filtre par carrier (Manager + Opérateur)

    L'opérateur voit tous les shipments (pas de filtre par créateur)
    car il peut modifier/supprimer tous les shipments de son équipe.
    """
    return lister_shipments(db, carrier=carrier)


@router.get("/carriers", tags=["Shipments"])
def get_carriers(db: Session = Depends(get_db), user: dict = Depends(get_current_operateur_ou_manager)):
    """
    Retourne la liste des carriers distincts depuis la table vessel.
    Utilisé pour la liste déroulante carrier dans le formulaire.
    Un nouveau carrier saisi sera automatiquement ajouté à cette liste
    lors de la création du shipment.
    """
    return lister_carriers(db)


@router.get("/supprimes/liste", tags=["Shipments"])
def get_shipments_supprimes(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_operateur_ou_manager),
):
    from backend.repositories.shipment_repository import get_shipments_supprimes
    result = get_shipments_supprimes(db)
    if result.empty:
        return []
    # Convertir NaN/NaT Pandas en null JSON (sin quoi Starlette renvoie une 500).
    result_json = result.astype(object).where(result.notna(), None)
    return result_json.to_dict(orient="records")

@router.get("/{shipment_id}", tags=["Shipments"])
def get_shipment(
    shipment_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_operateur_ou_manager),
):
    """
    Retourne le détail complet d'un shipment par son id.
    Retourne 404 si introuvable.
    """
    return obtenir_shipment(db, shipment_id)

# ═══════════════════════════════════════════════════════════════════════════════
# CRÉATION — Opérateur uniquement
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/", status_code=201, tags=["Shipments"])
def create_shipment(
    data: ShipmentCreateSchema,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_operateur),
):
    """
    Crée un nouveau shipment (saisie manuelle).

    Flux :
    1. Validation Pydantic (obligatoires, volumes > 0, dates cohérentes...)
    2. vessel_nom + carrier → get_ou_creer_vessel() → vessel_id
    3. Calcul colonnes dérivées par ETL si Normal, NULL si Cancelled
    4. Insertion en DB
    5. Retour du shipment complet

    createur_id = id de l'opérateur connecté (extrait du token JWT).
    """
    shipment = creer_shipment(db, data, createur_id=user["id"])
    background_tasks.add_task(ws_manager.notifier_actualisation_kpi)
    return shipment


# ═══════════════════════════════════════════════════════════════════════════════
# MODIFICATION — Opérateur uniquement
# ═══════════════════════════════════════════════════════════════════════════════

@router.put("/{shipment_id}", tags=["Shipments"])
def update_shipment(
    shipment_id: int,
    data: ShipmentUpdateSchema,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_operateur),
):
    """
    Modifie un shipment existant.

    Seuls les champs envoyés sont mis à jour (PATCH-like).
    Les colonnes dérivées sont recalculées automatiquement par l'ETL.
    Retourne 404 si le shipment est introuvable.
    """
    shipment = modifier_shipment(db, shipment_id, data, modificateur_id=user["id"])
    background_tasks.add_task(ws_manager.notifier_actualisation_kpi)
    return shipment

# ═══════════════════════════════════════════════════════════════════════════════
# SUPPRESSION — Opérateur uniquement
# ═══════════════════════════════════════════════════════════════════════════════

@router.delete("/{shipment_id}", response_model=DeleteResponseSchema, tags=["Shipments"])
def delete_shipment(
    shipment_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_operateur),
):
    """
    Supprime un shipment.

    Le popup de confirmation est géré côté React AVANT cet appel.
    Bloque la suppression si des messages sont associés au shipment.

    Retourne :
    - success=True  → "Shipment supprimé avec succès."
    - success=False → "Suppression impossible : N message(s) associé(s)."
    """
    result = supprimer_shipment(db, shipment_id, suppresseur_id=user["id"])
    if result.success:
        background_tasks.add_task(ws_manager.notifier_actualisation_kpi)
    return result


@router.post("/recalcul-derivees", tags=["Shipments"])
def recalculate_derived_columns(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_operateur),
):
    """Recalcule les colonnes dérivées et notifie les dashboards connectés."""
    result = recalculer_toutes_colonnes_derivees(db)
    if result.get("updated", 0) > 0:
        background_tasks.add_task(ws_manager.notifier_actualisation_kpi)
    return result


@router.post("/recalcul-cancelled", tags=["Shipments"])
def recalculate_cancelled(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_operateur),
):
    from backend.services.shipment_service import recalculer_cancelled
    return recalculer_cancelled(db)
