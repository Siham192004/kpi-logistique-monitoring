"""
kpi_engine.py — Calcul des KPIs logistiques (cahier des charges, section 5.1)

Principe general :
- Une SEULE source de donnees (get_all_shipments_avec_annules) alimente TOUS
  les KPIs. Chaque fonction gere elle-meme, en interne, si elle doit exclure
  les shipments annules ou non.
- Toutes les fonctions acceptent df en parametre (obligatoire).
  La session db est geree par l'appelant (service/router), jamais ici.
- groupby accepte une seule colonne ou une liste de colonnes.
- Si aucune donnee ne correspond, retourne None (global) ou Serie vide (groupby).
"""

import pandas as pd


# ═══════════════════════════════════════════════════════════════════════════
# REGISTRE OFFICIEL DES KPIs (cahier des charges, section 5.1)
# ═══════════════════════════════════════════════════════════════════════════

KPI_LABELS = {
    'KPI1': "% Volume charge / Volume alloue",
    'KPI2': "% Volume alloue / Volume reserve",
    'KPI3': "Retards dans les ports de transbordement",
    'KPI4': "Taux de modifications et annulations vessels",
    'KPI5': "Ratio de deviation ETA vs ATA",
}

KPI_OBJECTIFS = {
    'KPI1': 95,
    'KPI2': 90,
    'KPI3': {'on_target': 8,  'to_monitor': 15},
    'KPI4': {'on_target': 10, 'to_monitor': 25},
    'KPI5': {'on_target': 15, 'to_monitor': 30},
}


# ═══════════════════════════════════════════════════════════════════════════
# OUTILS COMMUNS
# ═══════════════════════════════════════════════════════════════════════════

def filtrer(df, mois=None, annee=None, carrier=None, port=None):
    """
    Applique les filtres du dashboard au DataFrame complet.
    ✅ FIX : ajout du filtre annee (Integer) en plus de mois.
    """
    if annee:
        try:
            df = df[df['year'] == int(annee)]
        except (ValueError, TypeError):
            pass
    if mois:
        # Filtre insensible à la casse
        mois_lower = str(mois).strip().lower()
        df = df[df['month'].apply(
            lambda m: str(m).strip().lower() == mois_lower if pd.notna(m) else False
        )]
    if carrier:
        df = df[df['carrier'] == carrier]
    if port:
        df = df[(df['port_chargement'] == port) | (df['port_dechargement'] == port)]
    return df


def _exclure_annules(df):
    """
    Retire les shipments annules. Utilisee par TOUS les KPIs sauf KPI4.
    """
    return df[df['shipment_status'] != 'Cancelled']

def _exclure_incomplets_kpi3(df):
    """Exclut les shipments sans etd_deviation ET eta_deviation (en cours, pas encore de données)."""
    return df[df['etd_deviation'].notna() & df['eta_deviation'].notna()]


def _ratio_sommes(df, colonne_numerateur, colonne_denominateur, groupby=None):
    """
    Calcule (somme(numerateur) / somme(denominateur)) x 100.
    ✅ FIX : dropna=True pour exclure les groupes NaN (month=None des anciens Cancelled).
    """
    sub = df[
        df[colonne_numerateur].notna() &
        df[colonne_denominateur].notna() &
        (df[colonne_denominateur] > 0)
    ]

    if groupby:
        if sub.empty:
            return pd.Series(dtype=float)
        return sub.groupby(groupby, dropna=True).apply(
            lambda g: round((g[colonne_numerateur].sum() / g[colonne_denominateur].sum()) * 100, 2)
        )

    if sub.empty:
        return None
    return round((sub[colonne_numerateur].sum() / sub[colonne_denominateur].sum()) * 100, 2)


def _effectif_ratio(df, colonne_numerateur, colonne_denominateur, groupby=None):
    """
    Compte le nombre de shipments utilises dans un _ratio_sommes.
    ✅ FIX : dropna=True cohérent avec _ratio_sommes.
    """
    sub = df[
        df[colonne_numerateur].notna() &
        df[colonne_denominateur].notna() &
        (df[colonne_denominateur] > 0)
    ]
    if groupby:
        return sub.groupby(groupby, dropna=True).size()
    return len(sub)


# ═══════════════════════════════════════════════════════════════════════════
# KPI1 — % Volume charge / Volume alloue (objectif >= 95%)
# ═══════════════════════════════════════════════════════════════════════════

def kpi1(df, groupby=None):
    """KPI1 = (Charged Volume / Confirmed Volume) x 100."""
    df = _exclure_annules(df)
    return _ratio_sommes(df, 'charged_volume', 'confirmed_volume', groupby)


def kpi1_effectif(df, groupby=None):
    """Nombre de shipments utilises dans le calcul de KPI1."""
    df = _exclure_annules(df)
    return _effectif_ratio(df, 'charged_volume', 'confirmed_volume', groupby)


def kpi1_distribution(df):
    """Ratios individuels par shipment, pour histogramme."""
    df = _exclure_annules(df)
    return df['volume_ratio_loaded'].dropna()


# ═══════════════════════════════════════════════════════════════════════════
# KPI2 — % Volume alloue / Volume reserve (objectif >= 90%)
# ═══════════════════════════════════════════════════════════════════════════

def kpi2(df, groupby=None):
    """KPI2 = (Confirmed Volume / Volume Booked) x 100."""
    df = _exclure_annules(df)
    return _ratio_sommes(df, 'confirmed_volume', 'volume_booked', groupby)


def kpi2_effectif(df, groupby=None):
    """Nombre de shipments utilises dans le calcul de KPI2."""
    df = _exclure_annules(df)
    return _effectif_ratio(df, 'confirmed_volume', 'volume_booked', groupby)


def kpi2_distribution(df):
    """Ratios individuels par shipment, pour histogramme."""
    df = _exclure_annules(df)
    return df['volume_ratio_allocated_booked'].dropna()


# ═══════════════════════════════════════════════════════════════════════════
# KPI3 — Retards dans les ports de transbordement
# Seuils : <= 8j On target | 8-15j To monitor | > 15j Critical
# ═══════════════════════════════════════════════════════════════════════════

KPI3_OBJECTIF = {'on_target': 8, 'to_monitor': 15}

CATEGORIES_KPI3 = {
    'Normal':                               'On target',
    'Retard départ - To Monitor':           'To monitor',
    'Retard départ - Critical':             'Critical',
    'Retard arrivée - To Monitor':          'To monitor',
    'Retard arrivée - Critical':            'Critical',
    'Retard départ + arrivée - To Monitor': 'To monitor',
    'Retard départ + arrivée - Critical':   'Critical',
}


def evaluer_kpi3(valeur):
    if pd.isna(valeur):
        return None
    if valeur <= 8:
        return 'On target'
    elif valeur <= 15:
        return 'To monitor'
    else:
        return 'Critical'


def classifier_kpi3(etd_dev, eta_dev):
    """Classe un shipment dans l'une des 7 categories metier KPI3."""
    etd = etd_dev if (etd_dev is not None and not pd.isna(etd_dev)) else 0
    eta = eta_dev if (eta_dev is not None and not pd.isna(eta_dev)) else 0

    dep_normal   = etd <= 8
    dep_monitor  = 8 < etd <= 15
    dep_critical = etd > 15
    arr_normal   = eta <= 8
    arr_monitor  = 8 < eta <= 15
    arr_critical = eta > 15

    if dep_normal and arr_normal:
        cat = 'Normal'
    elif dep_monitor and arr_normal:
        cat = 'Retard départ - To Monitor'
    elif dep_critical and arr_normal:
        cat = 'Retard départ - Critical'
    elif dep_normal and arr_monitor:
        cat = 'Retard arrivée - To Monitor'
    elif dep_normal and arr_critical:
        cat = 'Retard arrivée - Critical'
    elif (dep_monitor or dep_critical) and (arr_monitor or arr_critical):
        if dep_critical or arr_critical:
            cat = 'Retard départ + arrivée - Critical'
        else:
            cat = 'Retard départ + arrivée - To Monitor'
    else:
        cat = 'Normal'

    return cat, CATEGORIES_KPI3[cat]


def kpi3_par_shipment(df):
    df = _exclure_annules(df)
    df = _exclure_incomplets_kpi3(df)  # ← ajoute cette ligne
    df = df.copy()
    df['niveau_etd_deviation'] = df['etd_deviation'].apply(evaluer_kpi3)
    df['niveau_delay_days']    = df['eta_deviation'].apply(evaluer_kpi3)
    classification = df.apply(
        lambda row: classifier_kpi3(row.get('etd_deviation'), row.get('eta_deviation')),
        axis=1
    )
    df['categorie_metier'] = classification.apply(lambda x: x[0])
    df['niveau_global']    = classification.apply(lambda x: x[1])
    return df


def kpi3(df, groupby=None):
    df = _exclure_annules(df)
    df = _exclure_incomplets_kpi3(df)  # ← ajoute cette ligne
    df = df.copy()
    df['niveau_etd_deviation'] = df['etd_deviation'].apply(evaluer_kpi3)
    df['niveau_delay_days']    = df['eta_deviation'].apply(evaluer_kpi3)
    if groupby:
        return df.groupby(groupby, dropna=True)[['niveau_etd_deviation', 'niveau_delay_days']].value_counts()
    return df[['niveau_etd_deviation', 'niveau_delay_days']].value_counts()


def kpi3_effectif(df, groupby=None):
    df = _exclure_annules(df)
    df = _exclure_incomplets_kpi3(df)  # ← ajoute cette ligne
    if groupby:
        return df.groupby(groupby, dropna=True).size()
    return len(df)


def kpi3_detail(df):
    df = _exclure_annules(df)
    df = _exclure_incomplets_kpi3(df)  # ← ajoute cette ligne
    df = df.copy()
    classification = df.apply(
        lambda row: classifier_kpi3(row.get('etd_deviation'), row.get('eta_deviation')),
        axis=1
    )
    df['categorie_metier'] = classification.apply(lambda x: x[0])
    counts = df['categorie_metier'].value_counts()
    result = {}
    for cat in CATEGORIES_KPI3:
        result[cat] = int(counts.get(cat, 0))
    return result


def kpi3_shipments_critiques(df, seuil_niveau='To monitor'):
    df = _exclure_annules(df)
    df = _exclure_incomplets_kpi3(df)  # ← ajoute cette ligne
    df = df.copy()
    df['niveau_etd_deviation'] = df['etd_deviation'].apply(evaluer_kpi3)
    df['niveau_delay_days']    = df['eta_deviation'].apply(evaluer_kpi3)
    classification = df.apply(
        lambda row: classifier_kpi3(row.get('etd_deviation'), row.get('eta_deviation')),
        axis=1
    )
    df['categorie_metier'] = classification.apply(lambda x: x[0])
    df['niveau_global']    = classification.apply(lambda x: x[1])
    niveaux_a_signaler = {'To monitor', 'Critical'} if seuil_niveau == 'To monitor' else {'Critical'}
    return df[df['niveau_global'].isin(niveaux_a_signaler)]


# ═══════════════════════════════════════════════════════════════════════════
# KPI4 — Taux de modifications et annulations vessels
# Objectif : <10% On target | 10-25% To monitor | >25% Critical
# ═══════════════════════════════════════════════════════════════════════════

SEUIL_MODIFICATION_KPI4 = 4
KPI4_OBJECTIF = {'on_target': 10, 'to_monitor': 25}


def kpi4(df, groupby=None, seuil_modification=SEUIL_MODIFICATION_KPI4):
    """KPI4 = (Nb shipments modifies OU annules / Nb total) x 100."""
    df = df.copy()
    df['est_annule']  = (df['shipment_status'] == 'Cancelled')
    df['est_modifie'] = (df['etd_deviation'].fillna(0) >= seuil_modification) & (~df['est_annule'])
    df['est_modifie_ou_annule'] = (df['est_annule'] | df['est_modifie']).astype(int)

    if groupby:
        if df.empty:
            return pd.Series(dtype=float)
        return (df.groupby(groupby, dropna=True)['est_modifie_ou_annule'].mean() * 100).round(2)

    if df.empty:
        return None
    return round(df['est_modifie_ou_annule'].mean() * 100, 2)


def kpi4_detail(df, groupby=None, seuil_modification=SEUIL_MODIFICATION_KPI4):
    df = df.copy()
    df['est_annule']  = df['shipment_status'] == 'Cancelled'
    df['est_modifie'] = (df['etd_deviation'].fillna(0) >= seuil_modification) & (~df['est_annule'])
    df['statut_kpi4'] = 'Normal'
    df.loc[df['est_modifie'], 'statut_kpi4'] = 'Modifié'
    df.loc[df['est_annule'],  'statut_kpi4'] = 'Annulé'
    if groupby:
        return df.groupby(groupby, dropna=True)['statut_kpi4'].value_counts()
    return df['statut_kpi4'].value_counts()



def kpi4_effectif(df, groupby=None):
    if groupby:
        return df.groupby(groupby, dropna=True).size()
    return len(df)


def evaluer_kpi4(valeur):
    if valeur is None:
        return None
    if valeur <= 10:
        return 'On target'
    elif valeur <= 25:
        return 'To monitor'
    else:
        return 'Critical'


# ═══════════════════════════════════════════════════════════════════════════
# KPI5 — Deviation Ratio: ETA planifie vs ETA reel (ATA)
# Objectif : <15% On target | 15-30% To monitor | >30% Critical
# ═══════════════════════════════════════════════════════════════════════════

SEUIL_RETARD_KPI5 = 4
KPI5_OBJECTIF = {'on_target': 15, 'to_monitor':30}


def kpi5(df, groupby=None, seuil=SEUIL_RETARD_KPI5):
    """KPI5 = (Nb shipments avec ATA en retard sur ETA >= seuil / Nb total) x 100."""
    df = _exclure_annules(df)
    sub = df[df['eta_deviation'].notna()].copy()
    if sub.empty:
        return pd.Series(dtype=float) if groupby else None
    sub['est_en_retard'] = (sub['eta_deviation'] >= seuil).astype(int)
    if groupby:
        return (sub.groupby(groupby, dropna=True)['est_en_retard'].mean() * 100).round(2)
    return round(sub['est_en_retard'].mean() * 100, 2)


def kpi5_detail(df, groupby=None, seuil=SEUIL_RETARD_KPI5):
    df = _exclure_annules(df)
    sub = df[df['eta_deviation'].notna()].copy()
    if sub.empty:
        return pd.Series(dtype=int)
    sub['statut_kpi5'] = 'Normal'
    sub.loc[sub['eta_deviation'] >= seuil, 'statut_kpi5'] = 'En retard'
    if groupby:
        return sub.groupby(groupby, dropna=True)['statut_kpi5'].value_counts()
    return sub['statut_kpi5'].value_counts()


def kpi5_effectif(df, groupby=None):
    df = _exclure_annules(df)
    sub = df[df['eta_deviation'].notna()]
    if groupby:
        return sub.groupby(groupby, dropna=True).size()
    return len(sub)


def kpi5_distribution(df):
    df = _exclure_annules(df)
    return df['eta_deviation'].dropna()


def evaluer_kpi5(valeur):
    if valeur is None or pd.isna(valeur):
        return None
    if valeur <= KPI_OBJECTIFS['KPI5']['on_target']:
        return 'On target'
    elif valeur <= KPI_OBJECTIFS['KPI5']['to_monitor']:
        return 'To monitor'
    else:
        return 'Critical'


# ═══════════════════════════════════════════════════════════════════════════
# REGISTRE DES FONCTIONS
# ═══════════════════════════════════════════════════════════════════════════

KPI_FUNCTIONS = {
    'KPI1': kpi1,
    'KPI2': kpi2,
    'KPI3': kpi3,
    'KPI4': kpi4,
    'KPI5': kpi5,
}

KPI_EFFECTIFS = {
    'KPI1': kpi1_effectif,
    'KPI2': kpi2_effectif,
    'KPI3': kpi3_effectif,
    'KPI4': kpi4_effectif,
    'KPI5': kpi5_effectif,
}


# ═══════════════════════════════════════════════════════════════════════════
# BLOC DE TEST
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    from database.db import SessionLocal
    from backend.repositories.shipment_repository import get_all_shipments_avec_annules

    db = SessionLocal()
    df = get_all_shipments_avec_annules(db)
    db.close()

    print(f"Total shipments en base (annules inclus) : {len(df)}\n")

    for nom_kpi, fonction in KPI_FUNCTIONS.items():
        effectif_fn = KPI_EFFECTIFS[nom_kpi]
        print(f"=== {nom_kpi} — {KPI_LABELS[nom_kpi]} (objectif: {KPI_OBJECTIFS[nom_kpi]}) ===")
        print("Global :", fonction(df), "| base sur", effectif_fn(df), "shipments")
        print("Par carrier :\n", fonction(df, groupby='carrier'))
        print("Par mois :\n",    fonction(df, groupby='month'))

        if nom_kpi == 'KPI3':
            print("Repartition des niveaux (global) :\n", kpi3(df))

            print("\n=== Shipments a surveiller (To monitor ou Critical) ===")
            critiques = kpi3_shipments_critiques(df)
            print(f"Nombre de shipments concernes : {len(critiques)}")
            print(critiques[['carrier', 'month', 'etd_deviation', 'eta_deviation']].head(20))

            print("\n=== DETAIL PAR SHIPMENT (kpi3_par_shipment) ===")
            df_detail = kpi3_par_shipment(df)
            print(f"Total shipments (hors annules) : {len(df_detail)}")
            print("\nNombre de NaN par colonne :")
            print(df_detail[['niveau_etd_deviation', 'niveau_delay_days']].isna().sum())
            print("\nRepartition complete :")
            print(df_detail[['niveau_etd_deviation', 'niveau_delay_days']].value_counts(dropna=False))

            critique_depart = df_detail[df_detail['niveau_etd_deviation'].isin(['To monitor', 'Critical'])]
            print(f"\nShipments critiques sur ETD deviation : {len(critique_depart)}")
            print(critique_depart[['carrier', 'month', 'etd_deviation', 'niveau_etd_deviation']])

            critique_arrivee = df_detail[df_detail['niveau_delay_days'].isin(['To monitor', 'Critical'])]
            print(f"\nShipments critiques sur delay days : {len(critique_arrivee)}")
            print(critique_arrivee[['carrier', 'month', 'eta_deviation', 'niveau_delay_days']].head(10))


        if nom_kpi == 'KPI5':
            valeur_globale = fonction(df)
            print(f"\nNiveau global : {evaluer_kpi5(valeur_globale)}")
            par_carrier = fonction(df, groupby='carrier')
            print("\nNiveau par carrier :\n", par_carrier.apply(evaluer_kpi5))
            print("\n=== Repartition statut KPI5 ===")
            print(kpi5_detail(df))
            print("\nPar carrier :\n", kpi5_detail(df, groupby='carrier'))

        # ✅ FIX : ce bloc de debug eta_deviation est hors de la boucle for
        print()

    # ✅ Bloc debug eta_deviation affiché UNE SEULE FOIS après la boucle
    print("\n=== DEBUG eta_deviation ===")
    print("eta_deviation >= 4 :", (df['eta_deviation'] >= 4).sum())
    print("eta_deviation > 8  :", (df['eta_deviation'] > 8).sum())