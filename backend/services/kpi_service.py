"""
kpi_service.py — Logique métier : calcul et orchestration des KPIs
"""

import pandas as pd
from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.repositories.kpi_repository import (
    get_data_kpis_filtres,
    get_data_rapport_carriers,
    get_mois_disponibles,
    get_carriers_disponibles,
)
from engine.kpi_engine import (
    kpi1, kpi1_effectif, kpi1_distribution,
    kpi2, kpi2_effectif, kpi2_distribution,
    kpi3, kpi3_effectif, kpi3_par_shipment, kpi3_shipments_critiques,
    kpi4, kpi4_effectif, kpi4_detail,
    kpi5, kpi5_effectif, kpi5_detail, kpi5_distribution,
    evaluer_kpi4, evaluer_kpi5,
    KPI_LABELS, KPI_OBJECTIFS, kpi3_detail,
    CATEGORIES_KPI3,
)
from backend.schemas.kpi_schema import (
    FiltresDashboardSchema,
    KpiValeurSchema,
    KpiParGroupeSchema,
    KpiParGroupeItemSchema,
    DashboardSchema,
    Kpi3DetailSchema,
    Kpi3CategorieItemSchema,
    Kpi3ShipmentCritiqueSchema,
    Kpi4DetailSchema,
    Kpi5DetailSchema,
    KpiDistributionSchema,
    CarrierRapportSchema,
)

MONTH_ORDER = [
    'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
    'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre'
]


# ═══════════════════════════════════════════════════════════════════════════════
# UTILITAIRES
# ═══════════════════════════════════════════════════════════════════════════════

def _evaluer_kpi1_2(valeur: float, objectif: float) -> str:
    if valeur is None:
        return None
    if round(valeur, 1) >= objectif:   # ← arrondi à 1 décimale
        return "On target"
    elif valeur >= objectif - 5:
        return "To monitor"
    else:
        return "Critical"
    

def _evaluer_kpi3_global(v3: float) -> str:
    """Niveau global KPI3 basé sur % shipments normaux — objectifs métier."""
    if v3 is None:
        return None
    if v3 >= 85:
        return "On target"
    elif v3 >= 60:
        return "To monitor"
    else:
        return "Critical"


def _series_to_groupe_items(
    serie: pd.Series,
    effectif_serie: pd.Series = None,
    evaluateur=None,
) -> list:
    items = []
    for groupe, valeur in serie.items():
        effectif = (
            int(effectif_serie[groupe])
            if effectif_serie is not None and groupe in effectif_serie
            else None
        )
        niveau = evaluateur(valeur) if evaluateur else None
        items.append(KpiParGroupeItemSchema(
            groupe=str(groupe),
            valeur=round(float(valeur), 2) if pd.notna(valeur) else None,
            effectif=effectif,
            niveau=niveau,
        ))
    return items


def _build_statut_kpi4(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute la colonne statut_kpi4 à un DataFrame — logique centralisée."""
    df = df.copy()
    df['est_annule']  = df['shipment_status'] == 'Cancelled'
    df['est_modifie'] = (
        (df['etd_deviation'].fillna(0) >= 4) & (~df['est_annule'])
    )
    df['statut_kpi4'] = 'Normal'
    df.loc[df['est_modifie'], 'statut_kpi4'] = 'Modifié'
    df.loc[df['est_annule'],  'statut_kpi4'] = 'Annulé'
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# FILTRES DISPONIBLES
# ═══════════════════════════════════════════════════════════════════════════════

def get_filtres_disponibles(db: Session) -> dict:
    return {
        "mois":     get_mois_disponibles(db),
        "carriers": get_carriers_disponibles(db),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

def get_dashboard(db: Session, filtres: FiltresDashboardSchema) -> DashboardSchema:
    df = get_data_kpis_filtres(
        db,
        mois=filtres.mois,
        carrier=filtres.carrier,
        annee=filtres.annee,
    )

    v1 = kpi1(df)
    kpi1_schema = KpiValeurSchema(
        kpi_id="KPI1", label=KPI_LABELS["KPI1"], valeur=v1,
        valeur_affichee=f"{round(v1, 1)}%" if v1 is not None else "—",
        effectif=kpi1_effectif(df),
        niveau=_evaluer_kpi1_2(v1, KPI_OBJECTIFS["KPI1"]),
        objectif=float(KPI_OBJECTIFS["KPI1"]),
        objectif_texte=f"≥ {KPI_OBJECTIFS['KPI1']}%",
    )

    v2 = kpi2(df)
    kpi2_schema = KpiValeurSchema(
        kpi_id="KPI2", label=KPI_LABELS["KPI2"], valeur=v2,
        valeur_affichee=f"{round(v2, 1)}%" if v2 is not None else "—",
        effectif=kpi2_effectif(df),
        niveau=_evaluer_kpi1_2(v2, KPI_OBJECTIFS["KPI2"]),
        objectif=float(KPI_OBJECTIFS["KPI2"]),
        objectif_texte=f"≥ {KPI_OBJECTIFS['KPI2']}%",
    )

    df_kpi3    = kpi3_par_shipment(df)
    total_kpi3 = len(df_kpi3)
    on_target_kpi3 = (
        (df_kpi3["niveau_etd_deviation"] == "On target") &
        (df_kpi3["niveau_delay_days"]    == "On target")
    ).sum() if total_kpi3 > 0 else 0
    v3 = round(on_target_kpi3 / total_kpi3 * 100, 2) if total_kpi3 > 0 else None
    kpi3_schema = KpiValeurSchema(
        kpi_id="KPI3", label=KPI_LABELS["KPI3"], valeur=v3,
        valeur_affichee=f"{int(kpi3_effectif(df) - on_target_kpi3)} critiques" if total_kpi3 > 0 else "—",
        effectif=kpi3_effectif(df),
        niveau=_evaluer_kpi3_global(v3),
        objectif=float(100 - KPI_OBJECTIFS["KPI3"]["on_target"]),
        objectif_texte="≥ 85% shipments On target (déviation ≤ 4j)"
    )

    v4 = kpi4(df)
    kpi4_schema = KpiValeurSchema(
        kpi_id="KPI4", label=KPI_LABELS["KPI4"], valeur=v4,
        valeur_affichee=f"{round(v4, 1)}%" if v4 is not None else "—",
        effectif=kpi4_effectif(df),
        niveau=evaluer_kpi4(v4),
        objectif=float(KPI_OBJECTIFS["KPI4"]["on_target"]),
        objectif_texte=f"≤ {KPI_OBJECTIFS['KPI4']['on_target']}%",
    )

    v5 = kpi5(df)
    kpi5_schema = KpiValeurSchema(
        kpi_id="KPI5", label=KPI_LABELS["KPI5"], valeur=v5,
        valeur_affichee=f"{round(v5, 1)}%" if v5 is not None else "—",
        effectif=kpi5_effectif(df),
        niveau=evaluer_kpi5(v5),
        objectif=float(KPI_OBJECTIFS["KPI5"]["on_target"]),
        objectif_texte=f"≤ {KPI_OBJECTIFS['KPI5']['on_target']}%",
    )

    return DashboardSchema(
        filtres_appliques=filtres,
        kpi1=kpi1_schema, kpi2=kpi2_schema, kpi3=kpi3_schema,
        kpi4=kpi4_schema, kpi5=kpi5_schema,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# KPIs PAR GROUPE
# ═══════════════════════════════════════════════════════════════════════════════

def get_kpi_par_groupe(
    db: Session,
    kpi_id: str,
    groupby: str,
    filtres: FiltresDashboardSchema,
) -> KpiParGroupeSchema:
    groupby_valides = ["carrier", "month", "port_chargement", "port_dechargement"]
    if groupby not in groupby_valides:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"groupby invalide. Valeurs acceptées : {groupby_valides}",
        )

    df = get_data_kpis_filtres(
        db,
        mois=filtres.mois,
        carrier=filtres.carrier,
        annee=filtres.annee,
    )

    kpi_map = {
        "KPI1": (kpi1, kpi1_effectif, lambda v: _evaluer_kpi1_2(v, KPI_OBJECTIFS["KPI1"])),
        "KPI2": (kpi2, kpi2_effectif, lambda v: _evaluer_kpi1_2(v, KPI_OBJECTIFS["KPI2"])),
        "KPI4": (kpi4, kpi4_effectif, evaluer_kpi4),
        "KPI5": (kpi5, kpi5_effectif, evaluer_kpi5),
    }

    if kpi_id not in kpi_map:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"KPI invalide pour groupby. KPIs supportés : {list(kpi_map.keys())}",
        )

    fn_kpi, fn_effectif, evaluateur = kpi_map[kpi_id]
    serie     = fn_kpi(df, groupby=groupby)
    effectifs = fn_effectif(df, groupby=groupby)

    items = (
        []
        if isinstance(serie, pd.Series) and serie.empty
        else _series_to_groupe_items(serie, effectifs, evaluateur)
    )

    return KpiParGroupeSchema(kpi_id=kpi_id, groupby=groupby, items=items)


# ═══════════════════════════════════════════════════════════════════════════════
# DÉTAIL KPI3
# ═══════════════════════════════════════════════════════════════════════════════

def get_kpi3_detail(db: Session, filtres: FiltresDashboardSchema) -> Kpi3DetailSchema:
    df = get_data_kpis_filtres(
        db,
        mois=filtres.mois,
        carrier=filtres.carrier,
        annee=filtres.annee,
    )

    detail_dict = kpi3_detail(df)
    repartition = [
        Kpi3CategorieItemSchema(
            categorie=cat,
            niveau=CATEGORIES_KPI3[cat],
            nombre=detail_dict[cat],
        )
        for cat in CATEGORIES_KPI3
    ]

    critiques_df = kpi3_par_shipment(df)
    shipments_critiques = [
        Kpi3ShipmentCritiqueSchema(
            shipment_id=         int(row['id']),
            carrier=             row.get('carrier'),
            vessel_nom=          row.get('vessel_nom'),
            month=               row.get('month'),
            port_chargement=     row.get('port_chargement'),
            port_dechargement=   row.get('port_dechargement'),
            etd_deviation=       row.get('etd_deviation'),
            eta_deviation=       row.get('eta_deviation'),
            categorie_metier=    row.get('categorie_metier'),
            niveau_global=       row.get('niveau_global'),
            niveau_etd_deviation=row.get('niveau_etd_deviation'),
            niveau_delay_days=   row.get('niveau_delay_days'),
        )
        for _, row in critiques_df.iterrows()
    ]

    return Kpi3DetailSchema(
        repartition=repartition,
        shipments_critiques=shipments_critiques,
        total_critiques=len(shipments_critiques),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# DÉTAIL KPI4
# ═══════════════════════════════════════════════════════════════════════════════

def get_kpi4_detail(db: Session, filtres: FiltresDashboardSchema) -> Kpi4DetailSchema:
    df = get_data_kpis_filtres(
        db, mois=filtres.mois, carrier=filtres.carrier, annee=filtres.annee,
    )

    valeur      = kpi4(df)
    detail      = kpi4_detail(df)
    detail_dict = detail.to_dict() if not detail.empty else {}

    total       = len(df)
    nb_annules  = int(detail_dict.get("Annulé",  0))
    nb_modifies = int(detail_dict.get("Modifié", 0))
    nb_normaux  = int(detail_dict.get("Normal",  0))

    pct_annules  = round(nb_annules  / total * 100, 1) if total > 0 else 0
    pct_modifies = round(nb_modifies / total * 100, 1) if total > 0 else 0
    pct_normaux  = round(nb_normaux  / total * 100, 1) if total > 0 else 0

    return Kpi4DetailSchema(
        valeur=valeur,
        niveau=evaluer_kpi4(valeur),
        effectif=kpi4_effectif(df),
        nb_annules=nb_annules,
        nb_modifies=nb_modifies,
        nb_normaux=nb_normaux,
        pct_annules=pct_annules,
        pct_modifies=pct_modifies,
        pct_normaux=pct_normaux,
        par_mois=[],  # ← plus utilisé, le frontend appelle /kpi4/par_mois séparément
    )


# ═══════════════════════════════════════════════════════════════════════════════
# KPI4 — ÉVOLUTION MENSUELLE (endpoint dédié, filtre carrier indépendant)
# ═══════════════════════════════════════════════════════════════════════════════

def get_kpi4_par_mois(db: Session, annee: Optional[str], carrier: Optional[str]) -> dict:
    """
    Calcule l'évolution mensuelle Normal/Modifié/Annulé pour KPI4.
    Utilise le même DataFrame pandas que le reste du service.
    Filtre carrier indépendant → ne recharge pas les autres widgets.
    """
    df = get_data_kpis_filtres(db, mois=None, carrier=carrier, annee=annee)

    if df.empty:
        return {"par_mois": []}

    df = _build_statut_kpi4(df)

    grouped = (
        df.groupby(['month', 'statut_kpi4'], dropna=True)
        .size()
        .reset_index(name='count')
    )

    if grouped.empty:
        return {"par_mois": []}

    pivot = grouped.pivot(index='month', columns='statut_kpi4', values='count').fillna(0)

    # Trier les mois dans l'ordre calendaire
    pivot = pivot.reindex([m for m in MONTH_ORDER if m in pivot.index])

    par_mois = []
    for month, row in pivot.iterrows():
        par_mois.append({
            "month":   month[:3],
            "normal":  int(row.get("Normal",  0)),
            "modifie": int(row.get("Modifié", 0)),
            "annule":  int(row.get("Annulé",  0)),
        })

    return {"par_mois": par_mois}


# ═══════════════════════════════════════════════════════════════════════════════
# DÉTAIL KPI5
# ═══════════════════════════════════════════════════════════════════════════════

def get_kpi5_detail(db: Session, filtres: FiltresDashboardSchema) -> Kpi5DetailSchema:
    df = get_data_kpis_filtres(
        db,
        mois=filtres.mois,
        carrier=filtres.carrier,
        annee=filtres.annee,
    )

    valeur = kpi5(df)
    detail = kpi5_detail(df)

    nb_en_retard = int(detail.get("En retard", 0))
    nb_a_lheure  = int(detail.get("Normal",    0))
    total        = nb_en_retard + nb_a_lheure

    pct_en_retard = round(nb_en_retard / total * 100, 1) if total > 0 else 0
    pct_a_lheure  = round(nb_a_lheure  / total * 100, 1) if total > 0 else 0

    return Kpi5DetailSchema(
        valeur=valeur,
        niveau=evaluer_kpi5(valeur),
        effectif=kpi5_effectif(df),
        nb_en_retard=nb_en_retard,
        nb_a_lheure=nb_a_lheure,
        pct_en_retard=pct_en_retard,
        pct_a_lheure=pct_a_lheure,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# DISTRIBUTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def get_distribution(
    db: Session,
    kpi_id: str,
    filtres: FiltresDashboardSchema,
) -> KpiDistributionSchema:
    df = get_data_kpis_filtres(
        db,
        mois=filtres.mois,
        carrier=filtres.carrier,
        annee=filtres.annee,
    )

    dist_map = {
        "KPI1": kpi1_distribution,
        "KPI2": kpi2_distribution,
        "KPI5": kpi5_distribution,
    }

    if kpi_id not in dist_map:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Distribution non disponible pour {kpi_id}.",
        )

    serie = dist_map[kpi_id](df)
    return KpiDistributionSchema(
        kpi_id=kpi_id,
        valeurs=[round(float(v), 4) if pd.notna(v) else None for v in serie],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# RAPPORT CARRIERS
# ═══════════════════════════════════════════════════════════════════════════════

def get_rapport_carriers(db: Session) -> list[CarrierRapportSchema]:
    df       = get_data_rapport_carriers(db)
    carriers = get_carriers_disponibles(db)
    rapport  = []

    for carrier in carriers:
        df_carrier = df[df["carrier"] == carrier]
        if df_carrier.empty:
            continue

        v1 = kpi1(df_carrier)
        v2 = kpi2(df_carrier)
        v4 = kpi4(df_carrier)
        v5 = kpi5(df_carrier)

        niveaux = [
            _evaluer_kpi1_2(v1, KPI_OBJECTIFS["KPI1"]),
            _evaluer_kpi1_2(v2, KPI_OBJECTIFS["KPI2"]),
            evaluer_kpi4(v4),
            evaluer_kpi5(v5),
        ]
        niveaux_valides = [n for n in niveaux if n]

        if "Critical" in niveaux_valides:
            niveau_global = "Critical"
        elif "To monitor" in niveaux_valides:
            niveau_global = "To monitor"
        elif "On target" in niveaux_valides:
            niveau_global = "On target"
        else:
            niveau_global = None

        rapport.append(CarrierRapportSchema(
            carrier=carrier,
            kpi1=v1, kpi2=v2, kpi4=v4, kpi5=v5,
            niveau_global=niveau_global,
            effectif=kpi1_effectif(df_carrier),
        ))

    return rapport


def get_rapport_carriers_mensuel(
    db: Session,
    annee: Optional[str] = None,
    carrier: Optional[str] = None,
) -> list:
    from backend.repositories.kpi_repository import get_all_shipments_avec_annules
    df = get_all_shipments_avec_annules(db)
    if df.empty:
        return []

    if annee:
        df = df[df["year"] == int(annee)]
    if carrier:
        df = df[df["carrier"] == carrier]
    if df.empty:
        return []

    df["month_short"] = pd.to_datetime(df["etd"], errors="coerce").dt.strftime("%b")
    df["month_num"]   = pd.to_datetime(df["etd"], errors="coerce").dt.month

    result = []
    for (month_short, month_num), grp in df.groupby(["month_short", "month_num"]):
        v1 = kpi1(grp)
        v2 = kpi2(grp)
        v4 = kpi4(grp)
        v5 = kpi5(grp)

        if any(v is None for v in [v1, v2, v4, v5]):
            continue

        score = round((v1 * 0.30) + (v2 * 0.15) + ((100 - v4) * 0.20) + ((100 - v5) * 0.35), 1)

        if score >= 80:
            niveau = "On target"
            color  = "#10b981"
        elif score >= 65:
            niveau = "To monitor"
            color  = "#f59e0b"
        else:
            niveau = "Critical"
            color  = "#ef4444"

        result.append({
            "mois":      month_short,
            "month_num": int(month_num),
            "score":     score,
            "niveau":    niveau,
            "color":     color,
            "kpi1":      round(v1, 1),
            "kpi2":      round(v2, 1),
            "kpi4":      round(v4, 1),
            "kpi5":      round(v5, 1),
        })

    result.sort(key=lambda x: x["month_num"])
    return result