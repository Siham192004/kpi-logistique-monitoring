"""
prediction_service.py — Logique métier : prédiction de retard ML

Responsabilités :
1. Récupérer le shipment depuis la DB
2. Vérifier qu'il est éligible à la prédiction
3. Appeler predire_retard() depuis Regression_logistique.py
4. Formater la réponse pour le schema Pydantic

Architecture :
prediction_router → prediction_service → shipment_repository → SessionLocal
                                       ↘ engine/Regression_logistique.py (ML)

Note :
get_shipment_by_id() retourne un dict (via _shipment_to_dict),
pas un objet ORM. Tous les accès sont donc en notation dict : shipment["champ"].
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.repositories.shipment_repository import (
    get_shipment_by_id,
    get_all_shipments,
)
from backend.schemas.prediction_schema import PredictionResponseSchema
from engine.Regression_logistique import predire_retard


# ═══════════════════════════════════════════════════════════════════════════════
# PRÉDICTION
# ═══════════════════════════════════════════════════════════════════════════════

def predire_retard_shipment(
    db: Session,
    shipment_id: int,
) -> PredictionResponseSchema:
    """
    Prédit le retard d'un shipment existant en base.

    Flux (diagramme de séquence seq_predire_retard) :
    1. Récupérer le shipment depuis la DB
    2. Vérifier l'éligibilité :
       - Shipment existe ?
       - Statut Normal (pas Cancelled) ?
       - Features ML suffisantes ?
    3. Construire le dict de features pour predire_retard()
    4. Appeler le modèle Régression Logistique
    5. Retourner PredictionResponseSchema

    Utilisé par : prediction_router (POST /predict/)
    """

    # 1. Shipment existe ?
    shipment = get_shipment_by_id(db, shipment_id)
    if not shipment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shipment {shipment_id} introuvable."
        )

    # 2. Shipment annulé → prédiction impossible
    if shipment["shipment_status"] == "Cancelled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Prédiction impossible : ce shipment est annulé."
        )

    # Après la vérification Cancelled, ajouter :
    if shipment.get("ata"):
        raise HTTPException(
           status_code=status.HTTP_400_BAD_REQUEST,
           detail="Prédiction impossible : ce shipment est déjà terminé (ATA renseignée)."
    )

    # 3. Features suffisantes ?
    features_requises = [
        "transit_time", "volume_booked", "confirmed_volume",
        "port_chargement", "port_dechargement",
        "pays_destination", "month", "frequency"
    ]
    manquantes = [
        f for f in features_requises
        if not shipment.get(f)
    ]
    if not shipment.get("carrier"):
        manquantes.append("carrier")

    if manquantes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Données insuffisantes : {', '.join(manquantes)} manquant(s)."
        )

    # 4. Construire le dict de features pour le modèle
    features_ml = {
        "transit_time":                  shipment["transit_time"],
        "frequency":                     shipment["frequency"],
        "month":                         shipment["month"],
        "volume_booked":                 shipment["volume_booked"],
        "confirmed_volume":              shipment["confirmed_volume"],
        "charged_volume":                shipment["charged_volume"],
        "volume_ratio_allocated_booked": shipment["volume_ratio_allocated_booked"],
        "carrier":                       shipment["carrier"],
        "port_chargement":               shipment["port_chargement"],
        "port_dechargement":             shipment["port_dechargement"],
        "pays_destination":              shipment["pays_destination"],
        "incoterm":                      shipment["incoterm"],
        "etd": str(shipment["etd"]) if shipment.get("etd") else None,
        "eta": str(shipment["eta"]) if shipment.get("eta") else None,
    }

    # 5. Appel du modèle ML
    resultat = predire_retard(features_ml)

    # 6. Retourner la réponse complète
    return PredictionResponseSchema(
        shipment_id=shipment_id,

        # Contexte shipment
        vessel_nom=shipment["vessel_nom"],
        carrier=shipment["carrier"],
        port_chargement=shipment["port_chargement"],
        port_dechargement=shipment["port_dechargement"],
        pays_destination=shipment["pays_destination"],
        etd=str(shipment["etd"]) if shipment.get("etd") else None,
        eta=str(shipment["eta"]) if shipment.get("eta") else None,
        transit_time=shipment["transit_time"],
        volume_booked=shipment["volume_booked"],
        confirmed_volume=shipment["confirmed_volume"],

        # Résultat ML
        prediction=resultat["prediction"],
        probabilite_retard=resultat["probabilite_retard"],
        niveau_risque=resultat["niveau_risque"],
        label=resultat["label"],
        meteo=None,
    )

import math

def _clean(val):
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val
# ═══════════════════════════════════════════════════════════════════════════════
# LISTE DES SHIPMENTS ÉLIGIBLES À LA PRÉDICTION
# ═══════════════════════════════════════════════════════════════════════════════

def lister_shipments_eligibles(db: Session) -> list:
    """
    Retourne la liste des shipments éligibles à la prédiction :
    - Statut Normal
    - Features ML complètes

    Utilisé par : prediction_router (GET /predict/eligibles)
    React affiche cette liste → l'utilisateur clique [Prédire].

    Note : get_all_shipments() retourne un DataFrame,
    on itère sur les dicts via itertuples ou to_dict.
    """
    df = get_all_shipments(db)

    if df.empty:
        return []

    features_requises = [
        "transit_time", "volume_booked", "confirmed_volume",
        "port_chargement", "port_dechargement",
        "pays_destination", "month", "frequency"
    ]

    df = df.where(df.notna(), other=None)

    eligibles = []
    for shipment in df.to_dict(orient="records"):
        # Exclure annulés
        if shipment.get("shipment_status") == "Cancelled":
            continue
        # ✅ FIX : exclure terminés — ata peut être NaT (truthy) sans ce check
        ata = shipment.get("ata")
        if ata is not None and str(ata) not in ("", "None", "NaT", "nan"):
            continue
        # Features complètes
        if any(not shipment.get(f) for f in features_requises):
            continue
        if not shipment.get("carrier"):
            continue

        eligibles.append({
            "id":                shipment["id"],
            "vessel_nom":        shipment.get("vessel_nom"),
            "carrier":           shipment.get("carrier"),
            "port_chargement":   shipment["port_chargement"],
            "port_dechargement": shipment["port_dechargement"],
            "pays_destination":  shipment["pays_destination"],
            "etd":               str(shipment["etd"]) if shipment.get("etd") else None,
            "eta":               str(shipment["eta"]) if shipment.get("eta") else None,
            "transit_time":      shipment["transit_time"],
            "volume_booked":     shipment["volume_booked"],
            "confirmed_volume":  shipment["confirmed_volume"],
            "shipment_status":   shipment["shipment_status"],
            "is_delayed":        _clean(shipment.get("is_delayed")),
        })

    return eligibles