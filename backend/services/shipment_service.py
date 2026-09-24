"""
shipment_service.py — Logique métier : gestion des shipments

Responsabilités :
1. Créer un shipment (saisie manuelle)
2. Modifier un shipment existant
3. Supprimer un shipment
4. Consulter les shipments
5. Orchestrer l'ETL après insertion/modification

Règles métier :
- Seul l'opérateur (Control Tower Team) peut créer/modifier/supprimer
- Opérateur ET Manager peuvent consulter
- Suppression bloquée si messages associés
- ETL recalcule les colonnes dérivées après chaque insertion/modification
- Vessel : saisie manuelle (pas de liste déroulante — trop de vessels)
- Carrier : liste déroulante + possibilité de saisir un nouveau carrier
            qui s'ajoute automatiquement à la liste

Architecture :
shipment_router → shipment_service → shipment_repository → db.py
                                   ↘ etl/ (calcul colonnes dérivées)
"""

import pandas as pd
from datetime import date
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.repositories.shipment_repository import (
    get_all_shipments_avec_annules,
    get_all_shipments,
    get_shipment_by_id,
    get_shipments_by_createur,
    get_ou_creer_vessel,
    get_carriers_distincts,
    insert_shipment,
    update_shipment,
    delete_shipment,
    has_messages,
)
from backend.schemas.shipment_schema import (
    ShipmentCreateSchema,
    ShipmentUpdateSchema,
    DeleteResponseSchema,
)


# ═══════════════════════════════════════════════════════════════════════════════
# COLONNES VALIDES — Table shipment (sans vessel_nom, carrier, id)
# ═══════════════════════════════════════════════════════════════════════════════

# ✅ FIX : liste exacte des colonnes de la table shipment en base.
# Tout champ absent de cet ensemble provoque une erreur 500 si passé
# à SQLAlchemy .update() ou Shipment(**data).
COLONNES_SHIPMENT = {
    "port_chargement", "port_dechargement", "pays_destination",
    "etd", "atd", "eta", "ata",
    "incoterm", "volume_booked", "confirmed_volume", "charged_volume",
    "transit_time", "frequency", "month", "year",
    "shipment_status",
    "transit_time_reel", "eta_deviation", "etd_deviation",
    "is_delayed", "volume_ratio_loaded", "volume_ratio_allocated_booked",
    "niveau_retard", "vessel_id", "createur_id",
    "created_at", "updated_at", "updated_by_id",
}


def _filtrer_colonnes_shipment(data: dict) -> dict:
    """
    Garde uniquement les colonnes valides de la table shipment.
    Élimine vessel_nom, carrier, id et tout autre champ inconnu
    qui causerait une erreur 500 lors du UPDATE ou INSERT SQLAlchemy.
    """
    return {k: v for k, v in data.items() if k in COLONNES_SHIPMENT}


# ═══════════════════════════════════════════════════════════════════════════════
# CALCUL ETL — Colonnes dérivées pour un shipment individuel
# ═══════════════════════════════════════════════════════════════════════════════

def _calculer_colonnes_derivees(data: dict) -> dict:
    """
    Calcule les colonnes dérivées pour un shipment individuel.
    - month                         depuis etd
    - transit_time_reel             ATA - ATD
    - eta_deviation                 ATA - ETA
    - etd_deviation                 ATD - ETD
    - is_delayed                    1 si eta_deviation > 0
    - volume_ratio_loaded           charged_volume / confirmed_volume
    - volume_ratio_allocated_booked confirmed_volume / volume_booked
    - niveau_retard                 selon transit_time_reel vs transit_time
    """
    derivees = {}

    # ── month depuis etd ──────────────────────────────────────────────────────
    # ── Month et Year depuis ETD ──────────────────────────────────────────────
    etd = data.get("etd")

    if etd:
       if isinstance(etd, str):
        etd = pd.to_datetime(etd, errors="coerce")
       elif isinstance(etd, date):
        etd = pd.Timestamp(etd)

       if pd.notna(etd):
        mois_fr = {
            1: "Janvier",
            2: "Février",
            3: "Mars",
            4: "Avril",
            5: "Mai",
            6: "Juin",
            7: "Juillet",
            8: "Août",
            9: "Septembre",
            10: "Octobre",
            11: "Novembre",
            12: "Décembre",
        }

        derivees["month"] = mois_fr[etd.month]
        derivees["year"] = etd.year
       else:
        derivees["month"] = None
        derivees["year"] = None
    else:
      derivees["month"] = None
      derivees["year"] = None

    # ── Conversion dates ──────────────────────────────────────────────────────
    def to_timestamp(d):
        if d is None:
            return None
        if isinstance(d, date) and not isinstance(d, pd.Timestamp):
            return pd.Timestamp(d)
        return pd.to_datetime(d, errors="coerce") if isinstance(d, str) else d

    atd     = to_timestamp(data.get("atd"))
    ata     = to_timestamp(data.get("ata"))
    eta     = to_timestamp(data.get("eta"))
    etd_ts  = to_timestamp(data.get("etd"))   # ✅ variable séparée (pas écraser etd ci-dessus)

    # ── transit_time_reel : ATA - ATD ─────────────────────────────────────────
    derivees["transit_time_reel"] = (ata - atd).days if ata and atd else None

    # ── eta_deviation : ATA - ETA ─────────────────────────────────────────────
    derivees["eta_deviation"] = (ata - eta).days if ata and eta else None

    # ── etd_deviation : ATD - ETD ─────────────────────────────────────────────
    derivees["etd_deviation"] = (atd - etd_ts).days if atd and etd_ts else None

    # ── is_delayed ────────────────────────────────────────────────────────────
    SEUIL_RETARD_ML = 4

    if derivees["eta_deviation"] is not None:
        derivees["is_delayed"] = (
        1 if derivees["eta_deviation"] >= SEUIL_RETARD_ML else 0
    )
    else:
       derivees["is_delayed"] = None

    # ── volume_ratio_loaded : charged / confirmed ─────────────────────────────
    charged   = data.get("charged_volume")
    confirmed = data.get("confirmed_volume")
    derivees["volume_ratio_loaded"] = (
        round(charged / confirmed, 4)
        if charged and confirmed and confirmed > 0
        else None
    )

    # ── volume_ratio_allocated_booked : confirmed / booked ────────────────────
    booked = data.get("volume_booked")
    derivees["volume_ratio_allocated_booked"] = (
        round(confirmed / booked, 4)
        if confirmed and booked and booked > 0
        else None
    )

    # ── niveau_retard ─────────────────────────────────────────────────────────
    transit_reel        = derivees["transit_time_reel"]
    transit_contractuel = data.get("transit_time")
    if transit_reel is not None and transit_contractuel is not None:
        if transit_reel > transit_contractuel + 60:
            derivees["niveau_retard"] = "Retard critique"
        elif transit_reel > transit_contractuel + 30:
            derivees["niveau_retard"] = "Retard important"
        elif transit_reel > transit_contractuel + 5:
            derivees["niveau_retard"] = "Retard leger"
        else:
            derivees["niveau_retard"] = "A temps"
    else:
        derivees["niveau_retard"] = None

    return derivees


def _colonnes_derivees_vides(data: dict = None) -> dict:
    """Retourne les colonnes dérivées à NULL SAUF month et year calculés depuis ETD."""
    month = None
    year = None

    if data:
        etd = data.get("etd")
        if etd:
            if isinstance(etd, str):
                etd = pd.to_datetime(etd, errors="coerce")
            elif isinstance(etd, date):
                etd = pd.Timestamp(etd)
            if pd.notna(etd):
                mois_fr = {
                    1: "Janvier", 2: "Février", 3: "Mars",
                    4: "Avril", 5: "Mai", 6: "Juin",
                    7: "Juillet", 8: "Août", 9: "Septembre",
                    10: "Octobre", 11: "Novembre", 12: "Décembre",
                }
                month = mois_fr[etd.month]
                year = etd.year

    return {
        "month":                         month,  # ✅ calculé depuis ETD
        "year":                          year,   # ✅ calculé depuis ETD
        "transit_time_reel":             None,
        "eta_deviation":                 None,
        "etd_deviation":                 None,
        "is_delayed":                    None,
        "volume_ratio_loaded":           None,
        "volume_ratio_allocated_booked": None,
        "niveau_retard":                 None,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# CONSULTATION
# ═══════════════════════════════════════════════════════════════════════════════
import math

def _sanitize(obj):
    """Remplace NaN/inf par None pour la sérialisation JSON."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(i) for i in obj]
    return obj

def lister_shipments(
    db: Session,
    createur_id: int = None,
    carrier: str = None,
) -> list:
    if createur_id:
        df = get_shipments_by_createur(db, createur_id)
    else:
        df = get_all_shipments_avec_annules(db)

    if carrier and not df.empty:
        df = df[df["carrier"] == carrier]

    records = df.where(df.notna(), other=None).to_dict(orient="records")
    return _sanitize(records)


def obtenir_shipment(db: Session, shipment_id: int) -> dict:
    shipment = get_shipment_by_id(db, shipment_id)
    if not shipment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shipment {shipment_id} introuvable."
        )
    return _sanitize(shipment)  # ← seul changement


def lister_carriers(db: Session) -> list:
    return get_carriers_distincts(db)


# ═══════════════════════════════════════════════════════════════════════════════
# CRÉATION
# ═══════════════════════════════════════════════════════════════════════════════

def creer_shipment(db: Session, data: ShipmentCreateSchema, createur_id: int) -> dict:
    """
    Crée un nouveau shipment.

    ✅ FIX création : _filtrer_colonnes_shipment() appliqué avant insert_shipment()
    pour éviter que vessel_nom, carrier ou tout champ inconnu fasse planter
    Shipment(**data_dict) dans le repository.
    """
    # 1. Vessel → vessel_id
    vessel_id = get_ou_creer_vessel(db, data.vessel_nom, data.carrier)

    # 2. Préparer les données
    data_dict = data.model_dump()
    data_dict["vessel_id"]   = vessel_id
    data_dict["createur_id"] = createur_id
    data_dict.pop("vessel_nom", None)  # pas une colonne en DB
    data_dict.pop("carrier", None)     # porté par vessel, pas par shipment

    # Convertir enums en valeur string
    # ✅ Après
    if data.incoterm:
       data_dict["incoterm"] = data.incoterm.value
# type_annulation n'est plus dans le schema, on le calcule directement

# 3. Colonnes dérivées
    if data.shipment_status.value == "Normal":
       data_dict.update(_calculer_colonnes_derivees(data_dict))                         # ✅
    else:
       data_dict.update(_colonnes_derivees_vides(data_dict))

    # 4. ✅ Filtrer : ne garder que les colonnes de la table shipment
    shipment_id = insert_shipment(db, _filtrer_colonnes_shipment(data_dict))
    db.commit()

    # 5. Retourner le shipment complet
    return get_shipment_by_id(db, shipment_id)


# ═══════════════════════════════════════════════════════════════════════════════
# MODIFICATION
# ═══════════════════════════════════════════════════════════════════════════════

def modifier_shipment(db: Session, shipment_id: int, data: ShipmentUpdateSchema, modificateur_id: int) -> dict:
    """
    Modifie un shipment existant.

    ✅ FIX erreur 500 : la cause était que donnees_finales contenait
    vessel_nom, carrier et id (venant de {**existant}) qui ne sont
    pas des colonnes de la table shipment.
    SQLAlchemy .update(donnees_finales) levait alors une erreur 500.
    Solution : _filtrer_colonnes_shipment() avant update_shipment().
    """
    # 1. Shipment existe ?
    existant = get_shipment_by_id(db, shipment_id)
    if not existant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shipment {shipment_id} introuvable."
        )

    # 2. Champs modifiés par l'utilisateur
    data_dict = data.model_dump(exclude_none=True)

    # ← Traçabilité : qui a modifié et quand
    from datetime import datetime, timezone
    data_dict["updated_by_id"] = modificateur_id
    data_dict["updated_at"]    = datetime.now(timezone.utc)

    # 3. Vessel mis à jour si vessel_nom ou carrier changé
    vessel_nom = data_dict.pop("vessel_nom", None)
    carrier    = data_dict.pop("carrier", None)
    if vessel_nom or carrier:
        nouveau_nom     = (vessel_nom or existant["vessel_nom"]).strip().title()
        nouveau_carrier = (carrier    or existant["carrier"]).strip().upper()
        data_dict["vessel_id"] = get_ou_creer_vessel(db, nouveau_nom, nouveau_carrier)

    # 4. Fusionner avec les données existantes (nécessaire pour recalcul ETL)
    donnees_finales = {**existant, **data_dict}

    # Convertir enums en string
    for champ in ["shipment_status", "type_annulation", "incoterm"]:
        val = donnees_finales.get(champ)
        if val and hasattr(val, "value"):
            donnees_finales[champ] = val.value

    # 5. Recalculer colonnes dérivées
    statut = donnees_finales.get("shipment_status", "Normal")
    if statut == "Normal":
       donnees_finales.update(_calculer_colonnes_derivees(donnees_finales))                           # ✅ reset si repassé Normal
    else:
       donnees_finales.update(_colonnes_derivees_vides(donnees_finales))

    # 6. ✅ Filtrer : éliminer vessel_nom, carrier, id et tout champ inconnu
    #    avant d'appeler SQLAlchemy .update() — c'était la cause de l'erreur 500
    update_shipment(db, shipment_id, _filtrer_colonnes_shipment(donnees_finales))
    db.commit()

    # 7. Retourner le shipment mis à jour
    return get_shipment_by_id(db, shipment_id)


def recalculer_cancelled(db: Session) -> dict:
    df = get_all_shipments_avec_annules(db)
    cancelled = df[df["shipment_status"] == "Cancelled"]
    updated = 0
    for _, row in cancelled.iterrows():
        data = row.to_dict()
        vides = _colonnes_derivees_vides(data)
        update_shipment(db, int(row["id"]), {
            "month":                         vides["month"],
            "year":                          vides["year"],
            "transit_time_reel":             None,
            "eta_deviation":                 None,
            "etd_deviation":                 None,
            "is_delayed":                    None,
            "volume_ratio_loaded":           None,
            "volume_ratio_allocated_booked": None,
            "niveau_retard":                 None,
        })
        updated += 1
    db.commit()
    return {"updated": updated, "message": f"{updated} Cancelled recalculés."}


# ═══════════════════════════════════════════════════════════════════════════════
# SUPPRESSION
# ═══════════════════════════════════════════════════════════════════════════════

def supprimer_shipment(db: Session, shipment_id: int, suppresseur_id: int) -> DeleteResponseSchema:
    
    shipment = get_shipment_by_id(db, shipment_id)          # ✅ 2 args (pas 3)
    if not shipment:
        return DeleteResponseSchema(
            success=False,
            message=f"Shipment {shipment_id} introuvable."
        )

    nb_messages = has_messages(db, shipment_id)
    if nb_messages > 0:
        return DeleteResponseSchema(
            success=False,
            message=f"Suppression impossible : {nb_messages} message(s) "
                    f"associé(s) à ce shipment."
        )

    if delete_shipment(db, shipment_id, suppresseur_id):    # ✅ 3 args
        db.commit()
        return DeleteResponseSchema(
            success=True,
            message="Shipment supprimé avec succès."
        )

    return DeleteResponseSchema(
        success=False,
        message="Erreur lors de la suppression."
    )

def lister_shipments_supprimes(db: Session) -> list:
    from backend.repositories.shipment_repository import get_shipments_supprimes
    df = get_shipments_supprimes(db)
    if df.empty:
        return []
    records = df.where(df.notna(), other=None).to_dict(orient="records")
    return _sanitize(records)

# ═══════════════════════════════════════════════════════════════════════════════
# RECALCUL BATCH — Colonnes dérivées pour données historiques (Fix 7)
# ═══════════════════════════════════════════════════════════════════════════════

def recalculer_toutes_colonnes_derivees(db: Session) -> dict:
    """
    Recalcule les colonnes dérivées pour TOUS les shipments Normal.
    Corrige volume_ratio_allocated_booked = NULL dans les données
    historiques importées sans volume_booked / confirmed_volume renseignés.
    Accessible via POST /shipments/recalcul-derivees (opérateur uniquement).
    """
    df = get_all_shipments(db)
    if df.empty:
        return {"updated": 0, "message": "Aucun shipment à recalculer."}

    updated = 0
    for _, row in df.iterrows():
        data = row.to_dict()
        derivees = _calculer_colonnes_derivees(data)
        update_shipment(db, int(row["id"]), _filtrer_colonnes_shipment(derivees))
        updated += 1

    db.commit()
    return {
        "updated": updated,
        "message": f"{updated} shipment(s) recalculés avec succès.",
    }