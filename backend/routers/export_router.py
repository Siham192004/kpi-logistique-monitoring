from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional
import pandas as pd
import io

from database.db import get_db
from backend.services.auth_service import get_current_operateur_ou_manager
from backend.repositories.shipment_repository import get_all_shipments_avec_annules
from backend.services.kpi_service import get_rapport_carriers

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════════════
# EXPORT SHIPMENTS → EXCEL
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/excel/shipments", tags=["Export"])
def export_shipments_excel(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_operateur_ou_manager),
):
    # ─────────────────────────────────────────────
    # 1. Récupérer TOUS les shipments
    #    (y compris les annulés)
    # ─────────────────────────────────────────────

    df = get_all_shipments_avec_annules(db)

    # ─────────────────────────────────────────────
    # 2. Normaliser shipment_status
    # ─────────────────────────────────────────────

    status = (
        df["shipment_status"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    # ─────────────────────────────────────────────
    # 3. SHIPMENTS ANNULÉS
    #
    # shipment_status = Cancelled
    # ─────────────────────────────────────────────

    df_annules = df[
        status == "cancelled"
    ].copy()

    # ─────────────────────────────────────────────
    # 4. SHIPMENTS NON ANNULÉS
    # ─────────────────────────────────────────────

    df_non_annules = df[
        status != "cancelled"
    ].copy()

    # ─────────────────────────────────────────────
    # 5. SHIPMENTS EN COURS
    #
    # ATD absent
    # ET
    # ATA absent
    #
    # Exemple :
    # ATD = None
    # ATA = None
    # → En cours
    # ─────────────────────────────────────────────

    df_en_cours = df_non_annules[
        df_non_annules["atd"].isna()
        &
        df_non_annules["ata"].isna()
    ].copy()

    # ─────────────────────────────────────────────
    # 6. SHIPMENTS NORMAUX
    #
    # ATD présent
    # ET
    # ATA présent
    #
    # Exemple :
    # ATD = 2026-01-10
    # ATA = 2026-01-25
    # → Normal
    # ─────────────────────────────────────────────

    df_normal = df_non_annules[
        df_non_annules["atd"].notna()
        &
        df_non_annules["ata"].notna()
    ].copy()

    # ─────────────────────────────────────────────
    # 7. Créer le fichier Excel en mémoire
    # ─────────────────────────────────────────────

    buffer = io.BytesIO()

    with pd.ExcelWriter(
        buffer,
        engine="openpyxl"
    ) as writer:

        # Feuille 1 : En cours
        df_en_cours.to_excel(
            writer,
            sheet_name="En cours",
            index=False
        )

        # Feuille 2 : Normal
        df_normal.to_excel(
            writer,
            sheet_name="Normal",
            index=False
        )

        # Feuille 3 : Annulée
        df_annules.to_excel(
            writer,
            sheet_name="Annulée",
            index=False
        )

    # Revenir au début du fichier
    buffer.seek(0)

    # ─────────────────────────────────────────────
    # 8. Retourner le fichier au frontend
    # ─────────────────────────────────────────────

    return StreamingResponse(
        buffer,
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": (
                "attachment; filename=shipments.xlsx"
            )
        }
    )

# export_router.py — endpoint carriers
@router.get("/excel/carriers", tags=["Export"])
def export_carriers_excel(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_operateur_ou_manager),
):
    data = get_rapport_carriers(db)

    # ✅ Gérer les deux cas : objets Pydantic ou dicts bruts
    if data and hasattr(data[0], 'dict'):
        records = [r.dict() for r in data]
    elif data and hasattr(data[0], '__dict__'):
        records = [
            {k: v for k, v in r.__dict__.items() if not k.startswith('_')}
            for r in data
        ]
    else:
        records = list(data)  # déjà des dicts

    df = pd.DataFrame(records)
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=carriers.xlsx"}
    )