"""
Maritime Logistics ETL Pipeline — v3
======================================
Compatible avec : maritime_ml_dataset_merged.xlsx

DIFFÉRENCES vs ETL d'origine
------------------------------
1. Corrections manuelles par index : abandonnées — le dataset "_merged" a des index
   différents. Remplacé par correction AUTOMATIQUE étendue (heuristiques + règles).
2. Les onglets Excel de corrections manuelles ne sont plus nécessaires.
3. Détection d'inversion jour/mois : algo basé sur la cohérence inter-colonnes.
4. Compatible dataset de N lignes (pas de hardcodage d'index).
5. Toutes les colonnes dérivées ML sont calculées.

COLONNES SOURCE ATTENDUES
--------------------------
Carrier, Vessel, Port of Loading, Port of Discharge, Incoterm,
Transit_Time, Frequency, Port of Discharge country,
ETD, ATD, ETA, ATA, Volume Booked, Confirmed Volume, Charged Volume, Month

COLONNES DÉRIVÉES PRODUITES
-----------------------------
shipment_status, type_annulation, Transit_Time_Reel,
eta_deviation, etd_deviation, is_delayed, niveau_retard,
volume_ratio_loaded, volume_ratio_allocated, charge_sans_allocation,
alerte_outlier, Month (resynchronisé)
"""

import re
import warnings
import numpy as np
import pandas as pd
from dateutil import parser as dateutil_parser
from engine.weather_client import enrich_dataset_with_weather


warnings.filterwarnings("ignore")
np.random.seed(42)


# ──────────────────────────────────────────────────────────────────────────────
# 1. CHARGEMENT
# ──────────────────────────────────────────────────────────────────────────────

def charger_fichier(filepath: str) -> pd.DataFrame:
    if filepath.endswith(".csv"):
        return pd.read_csv(filepath, sep=";", encoding="utf-8")
    return pd.read_excel(filepath)


# ──────────────────────────────────────────────────────────────────────────────
# 2. NORMALISATION DES TEXTES
# ──────────────────────────────────────────────────────────────────────────────

def _nettoyer_serie(serie: pd.Series, casse: str = "title") -> pd.Series:
    s = serie.astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
    if casse == "upper":  return s.str.upper()
    if casse == "lower":  return s.str.lower()
    return s.str.title()


def _normaliser_frequency(serie: pd.Series) -> pd.Series:
    def convertir(val):
        v = str(val).strip().lower()
        m = re.search(r"(\d+)", v)
        if not m:
            return val
        n = int(m.group(1))
        if "semaine" in v or "week" in v:
            n *= 7
        return f"{n}j"
    return serie.apply(convertir)


def normaliser_textes(df: pd.DataFrame) -> pd.DataFrame:
    mapping = {
        "Carrier":                   "upper",
        "Vessel":                    "title",
        "Port of Loading":           "title",
        "Port of Discharge":         "title",
        "Port of Discharge country": "title",
        "Incoterm":                  "upper",
        "Frequency":                 "lower",
        "Operateur":                 "title",  
    }
    for col, casse in mapping.items():
        if col in df.columns:
            df[col] = _nettoyer_serie(df[col], casse)
    if "Frequency" in df.columns:
        df["Frequency"] = _normaliser_frequency(df["Frequency"])
    return df


# ──────────────────────────────────────────────────────────────────────────────
# 3. DÉTECTION DES ANNULATIONS
# ──────────────────────────────────────────────────────────────────────────────

def detecter_annulations(df: pd.DataFrame) -> pd.DataFrame:
    date_cols = [c for c in ["ETD", "ATD", "ETA", "ATA"] if c in df.columns]
    df["shipment_status"] = "Normal"
    mask = df[date_cols].apply(
        lambda c: c.astype(str).str.strip().str.upper() == "CANCELLED"
    ).any(axis=1)
    df.loc[mask, "shipment_status"] = "Cancelled"
    return df


def determiner_type_annulation(df: pd.DataFrame) -> pd.DataFrame:
    df["type_annulation"] = "Non annulé"
    is_cancelled = df["shipment_status"] == "Cancelled"

    def is_cancel_str(col):
        return df[col].astype(str).str.upper().str.strip() == "CANCELLED"

    mask_avant = is_cancelled & (is_cancel_str("ETD") | is_cancel_str("ATD"))
    df.loc[mask_avant, "type_annulation"] = "Avant départ"
    # ✅ Avant départ → ATD, ETA, ATA doivent être NULL
    df.loc[mask_avant, ["ATD", "ETA", "ATA"]] = np.nan

    mask_apres = (
        is_cancelled & ~mask_avant &
        ~is_cancel_str("ATD") &
        (is_cancel_str("ETA") | is_cancel_str("ATA"))
    )
    df.loc[mask_apres, "type_annulation"] = "Après départ"
    # ✅ Après départ → ETA, ATA doivent être NULL (ATD conservé)
    df.loc[mask_apres, ["ETA", "ATA"]] = np.nan

    return df


# ──────────────────────────────────────────────────────────────────────────────
# 4. PARSING DES DATES — parseur robuste multi-format
# ──────────────────────────────────────────────────────────────────────────────

_PLACEHOLDERS = {"pending", "tbd", "tbc", "cancelled", "end sep", "nan", "", "none", "n/a", "-"}


def _parse_date_robuste(val) -> pd.Timestamp:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return pd.NaT
    if isinstance(val, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(val)
    s = str(val).strip()
    if s.lower() in _PLACEHOLDERS:
        return pd.NaT
    # Format ISO
    try:
        return pd.Timestamp(s)
    except Exception:
        pass
    # YYYY/MM/DD ou YYYY-MM-DD
    if re.match(r"\d{4}[/\-]\d{2}[/\-]\d{2}", s):
        return pd.to_datetime(s, errors="coerce")
    # DD/MM/YYYY, MM/DD/YYYY, DD-MM-YYYY...
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y",
                "%d/%m/%y", "%m/%d/%y"):
        try:
            return pd.Timestamp(pd.to_datetime(s, format=fmt))
        except Exception:
            pass
    # Textuels : '10 October 2023', '16 Dec 2024'
    try:
        return pd.Timestamp(dateutil_parser.parse(s, dayfirst=True))
    except Exception:
        pass
    return pd.NaT


def nettoyer_colonnes_dates(df: pd.DataFrame) -> pd.DataFrame:
    for col in ["ETD", "ATD", "ETA", "ATA"]:
        if col not in df.columns:
            continue
        df[col] = df[col].apply(_parse_date_robuste)
    return df


# ──────────────────────────────────────────────────────────────────────────────
# 5. IMPUTATION TRANSIT_TIME PAR ROUTE
# ──────────────────────────────────────────────────────────────────────────────

def imputer_transit_time(df: pd.DataFrame) -> pd.DataFrame:
    if "Transit_Time" not in df.columns:
        return df
    route_med = (
        df.dropna(subset=["Transit_Time"])
        .groupby(["Port of Loading", "Port of Discharge"])["Transit_Time"]
        .median()
    )
    global_med = df["Transit_Time"].median()

    def imputer(row):
        if pd.notna(row["Transit_Time"]):
            return row["Transit_Time"]
        key = (row["Port of Loading"], row["Port of Discharge"])
        return route_med.get(key, global_med)

    df["Transit_Time"] = df.apply(imputer, axis=1)
    return df


# ──────────────────────────────────────────────────────────────────────────────
# 6. IMPUTATION PORT OF DISCHARGE COUNTRY
# ──────────────────────────────────────────────────────────────────────────────

def imputer_pays_destination(df: pd.DataFrame) -> pd.DataFrame:
    if "Port of Discharge country" not in df.columns:
        return df
    lookup = (
        df.dropna(subset=["Port of Discharge country"])
        .groupby("Port of Discharge")["Port of Discharge country"]
        .agg(lambda x: x.mode().iloc[0] if not x.mode().empty else np.nan)
    )
    mask = df["Port of Discharge country"].isna()
    df.loc[mask, "Port of Discharge country"] = df.loc[mask, "Port of Discharge"].map(lookup)
    return df


# ──────────────────────────────────────────────────────────────────────────────
# 7. CORRECTION AUTOMATIQUE ÉTENDUE DES DATES
#    Remplace les corrections manuelles par index (incompatibles avec _merged)
# ──────────────────────────────────────────────────────────────────────────────

def _swap_day_month(ts: pd.Timestamp) -> pd.Timestamp:
    """Inverse jour et mois si valide."""
    try:
        return ts.replace(month=ts.day, day=ts.month)
    except ValueError:
        return ts


def corriger_annee_erronnee(df: pd.DataFrame) -> tuple:
    """Correction automatique des années via règles inter-colonnes."""
    log = []

    def corriger(mask, col, new_year):
        for idx in df[mask].index:
            old = df.at[idx, col]
            try:
                new = old.replace(year=new_year)
                df.at[idx, col] = new
                log.append({"idx": idx, "colonne": col, "avant": old, "après": new, "type": "année"})
            except Exception:
                pass

    # ATD un an en avance sur ETD même mois
    corriger(
        df["ATD"].notna() & df["ETD"].notna() &
        (df["ATD"].dt.year == df["ETD"].dt.year + 1) &
        (df["ATD"].dt.month == df["ETD"].dt.month),
        "ATD", None  # géré ci-dessous
    )

    # Règles classiques
    for year_target, conditions in [
        (2024, (df["ATD"].dt.year == 2025) & df["ETD"].notna() & (df["ETD"].dt.year == 2024) &
               (df["ATD"].dt.month == df["ETD"].dt.month)),
        (2024, (df["ATA"].dt.year == 2025) & df["ETA"].notna() & (df["ETA"].dt.year == 2024) &
               ((df["ATA"] - df["ETA"]).dt.days.abs() > 100)),
        (2025, (df["ATA"].dt.year == 2024) & df["ATD"].notna() &
               (df["ATA"] < df["ATD"]) & ((df["ATD"] - df["ATA"]).dt.days > 100)),
        (2025, (df["ETA"].dt.year == 2024) & df["ETD"].notna() &
               (df["ETA"] < df["ETD"]) & ((df["ETD"] - df["ETA"]).dt.days > 100)),
        (2025, (df["ETD"].dt.year == 2026) & df["ATD"].notna() & (df["ATD"].dt.year == 2025)),
        (2024, (df["ETA"].dt.year == 2025) & df["ETD"].notna() & (df["ETD"].dt.year == 2024) &
               (df["ETA"].dt.month == df["ETD"].dt.month)),
        (2024, (df["ATA"].dt.year == 2025) & df["ATD"].notna() & (df["ATD"].dt.year == 2024) &
               (df["ATA"].dt.month == df["ATD"].dt.month)),
    ]:
        col = None
        if "ATD" in str(conditions) and year_target in [2024]:
            col = "ATD"
        corriger(conditions, "ATD" if "ATD.dt.year ==" in str(conditions) else
                             "ATA" if "ATA.dt.year ==" in str(conditions) else
                             "ETD" if "ETD.dt.year ==" in str(conditions) else "ETA", year_target)

    return df, pd.DataFrame(log)


def corriger_inversion_jour_mois(df: pd.DataFrame) -> pd.DataFrame:
    """
    Détecte et corrige les inversions jour/mois sur ATD et ETD.
    Heuristique : si ATD > ATA ou ATD < ETD - 5j, on tente le swap.
    Score de cohérence : Transit_Time_Reel proche de Transit_Time contractuel.
    """
    corrections = 0

    for idx in df.index:
        atd = df.at[idx, "ATD"]
        ata = df.at[idx, "ATA"]
        etd = df.at[idx, "ETD"]
        eta = df.at[idx, "ETA"]
        tt  = df.at[idx, "Transit_Time"]

        if pd.isna(atd) or pd.isna(ata) or pd.isna(tt):
            continue
        if atd.month == atd.day:  # indiscernable
            continue

        ttr_actuel = (ata - atd).days

        # Symptôme 1 : ATD >= ATA (physiquement impossible)
        # Symptôme 2 : Transit réel très loin du contractuel
        besoin_swap = (
            atd >= ata or
            ttr_actuel < 0 or
            (pd.notna(tt) and abs(ttr_actuel - tt) > 60 and ttr_actuel > tt + 30)
        )
        if not besoin_swap:
            continue

        atd_swap = _swap_day_month(atd)
        if atd_swap == atd:
            continue

        ttr_swap = (ata - atd_swap).days

        # Le swap est retenu si :
        # - il produit un ATD < ATA
        # - le Transit_Time_Reel résultant est plus proche du contractuel
        if (atd_swap < ata and ttr_swap > 0 and
                abs(ttr_swap - tt) < abs(ttr_actuel - tt)):
            df.at[idx, "ATD"] = atd_swap
            corrections += 1

    # Même logique sur ETD si ETD > ATD
    for idx in df.index:
        etd = df.at[idx, "ETD"]
        atd = df.at[idx, "ATD"]
        if pd.isna(etd) or pd.isna(atd):
            continue
        if etd.month == etd.day:
            continue
        if etd <= atd:
            continue  # déjà cohérent
        etd_swap = _swap_day_month(etd)
        if etd_swap != etd and etd_swap <= atd:
            df.at[idx, "ETD"] = etd_swap
            corrections += 1

    print(f"  → Inversions jour/mois corrigées : {corrections}")
    return df


# ──────────────────────────────────────────────────────────────────────────────
# 8. RECALCUL DES DATES MANQUANTES
# ──────────────────────────────────────────────────────────────────────────────

def _rand(choices, probs):
    return int(np.random.choice(choices, p=probs))


def recalculer_eta_manquante(df: pd.DataFrame) -> pd.DataFrame:
    for idx in df.index:
        if pd.notna(df.at[idx, "ETA"]):
            continue
        tt = df.at[idx, "Transit_Time"]
        if pd.isna(tt):
            continue
        if pd.notna(df.at[idx, "ETD"]):
            eta = df.at[idx, "ETD"] + pd.Timedelta(days=int(tt))
            if pd.notna(df.at[idx, "ATD"]) and eta <= df.at[idx, "ATD"]:
                eta = df.at[idx, "ATD"] + pd.Timedelta(days=1)
            df.at[idx, "ETA"] = eta
        elif pd.notna(df.at[idx, "ATD"]):
            dev = _rand([0, 1, 2, 3, 4], [0.35, 0.25, 0.18, 0.14, 0.08])
            eta = df.at[idx, "ATD"] - pd.Timedelta(days=dev) + pd.Timedelta(days=int(tt))
            if eta <= df.at[idx, "ATD"]:
                eta = df.at[idx, "ATD"] + pd.Timedelta(days=1)
            df.at[idx, "ETA"] = eta
    return df


def recalculer_etd_manquante(df: pd.DataFrame) -> pd.DataFrame:
    devs  = [-2, -1, 0, 1, 2, 3, 4]
    probs = [0.05, 0.10, 0.35, 0.20, 0.15, 0.10, 0.05]
    for idx in df.index:
        if pd.notna(df.at[idx, "ETD"]):
            continue
        tt = df.at[idx, "Transit_Time"]
        if pd.isna(tt):
            continue
        if pd.notna(df.at[idx, "ATD"]):
            df.at[idx, "ETD"] = df.at[idx, "ATD"] + pd.Timedelta(days=_rand(devs, probs))
        elif pd.notna(df.at[idx, "ETA"]):
            df.at[idx, "ETD"] = df.at[idx, "ETA"] - pd.Timedelta(days=int(tt))
        elif pd.notna(df.at[idx, "ATA"]):
            df.at[idx, "ETD"] = df.at[idx, "ATA"] - pd.Timedelta(days=int(tt) + _rand(devs, probs))
    return df


def recalculer_atd_manquante(df: pd.DataFrame) -> pd.DataFrame:
    devs  = [-2, -1, 0, 1, 2, 3, 4]
    probs = [0.05, 0.10, 0.35, 0.20, 0.15, 0.10, 0.05]
    for idx in df.index:
        if pd.notna(df.at[idx, "ATD"]):
            continue
        tt = df.at[idx, "Transit_Time"]
        if pd.notna(df.at[idx, "ETD"]):
            atd = df.at[idx, "ETD"] + pd.Timedelta(days=_rand(devs, probs))
            if pd.notna(df.at[idx, "ATA"]) and atd >= df.at[idx, "ATA"]:
                atd = df.at[idx, "ATA"] - pd.Timedelta(days=1)
            df.at[idx, "ATD"] = atd
        elif pd.notna(df.at[idx, "ATA"]) and pd.notna(tt):
            atd = df.at[idx, "ATA"] - pd.Timedelta(days=int(tt))
            if atd >= df.at[idx, "ATA"]:
                atd = df.at[idx, "ATA"] - pd.Timedelta(days=1)
            df.at[idx, "ATD"] = atd
    return df


def recalculer_ata_manquante(df: pd.DataFrame) -> pd.DataFrame:
    ecarts = [-3, -2, -1, 0, 1, 2, 3, 4, 5]
    probs  = [0.03, 0.05, 0.07, 0.40, 0.18, 0.12, 0.08, 0.05, 0.02]
    for idx in df[df["ATA"].isna() & df["ATD"].notna() & df["Transit_Time"].notna()].index:
        e   = _rand(ecarts, probs)
        ata = df.at[idx, "ATD"] + pd.Timedelta(days=int(df.at[idx, "Transit_Time"]) + e)
        if ata <= df.at[idx, "ATD"]:
            ata = df.at[idx, "ATD"] + pd.Timedelta(days=1)
        df.at[idx, "ATA"] = ata
    for idx in df[df["ATA"].isna() & df["ETA"].notna()].index:
        e   = _rand(ecarts, probs)
        ata = df.at[idx, "ETA"] + pd.Timedelta(days=e)
        if pd.notna(df.at[idx, "ATD"]) and ata <= df.at[idx, "ATD"]:
            ata = df.at[idx, "ATD"] + pd.Timedelta(days=1)
        df.at[idx, "ATA"] = ata
    return df


# ──────────────────────────────────────────────────────────────────────────────
# 9. TRANSIT TIME RÉEL
# ──────────────────────────────────────────────────────────────────────────────

def calculer_transit_time_reel(df: pd.DataFrame) -> pd.DataFrame:
    df["Transit_Time_Reel"] = (df["ATA"] - df["ATD"]).dt.days
    return df


def auditer_volumes(df: pd.DataFrame) -> pd.DataFrame:
    ratio = df["Charged Volume"] / df["Confirmed Volume"].replace(0, np.nan)
    df["erreur_charged_trop_superieur"] = (
        df["Charged Volume"].notna() & df["Confirmed Volume"].notna() & (ratio > 1.5)
    )
    return df


# ──────────────────────────────────────────────────────────────────────────────
# 11. NETTOYAGE & IMPUTATION DES VOLUMES
# ──────────────────────────────────────────────────────────────────────────────

def nettoyer_volumes(df: pd.DataFrame) -> pd.DataFrame:
    def convertir(val):
        if pd.isna(val):
            return np.nan
        s = str(val).strip()
        if s in ("*", "-", ""):
            return np.nan
        if "->" in s:
            parts = s.split("->")
            return sum(float(p.strip()) for p in parts) / len(parts)
        try:
            return float(s)
        except ValueError:
            return np.nan

    for col in ["Volume Booked", "Confirmed Volume", "Charged Volume"]:
        if col in df.columns:
            df[col] = df[col].apply(convertir).astype(float)
    return df


def imputer_volumes(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["Volume Booked", "Confirmed Volume", "Charged Volume"]
    cols = [c for c in cols if c in df.columns]
    df[cols] = df[cols].replace(0, np.nan)
    if "Charged Volume" in df.columns:
        df["Charged Volume"] = (
            df["Charged Volume"]
            .fillna(df.get("Confirmed Volume"))
            .fillna(df.get("Volume Booked"))
        )
    if "Confirmed Volume" in df.columns:
        df["Confirmed Volume"] = (
            df["Confirmed Volume"]
            .fillna(df.get("Charged Volume"))
            .fillna(df.get("Volume Booked"))
        )
    if "Volume Booked" in df.columns:
        df["Volume Booked"] = (
            df["Volume Booked"]
            .fillna(df.get("Confirmed Volume"))
            .fillna(df.get("Charged Volume"))
        )
    return df


def imputer_volumes_par_mediane(df: pd.DataFrame) -> pd.DataFrame:
    for col in ["Confirmed Volume", "Charged Volume", "Volume Booked"]:
        if col not in df.columns:
            continue
        if "Carrier" in df.columns:
            med = df.groupby("Carrier")[col].transform(lambda x: x.fillna(x.median()))
        else:
            med = df[col].median()
        df[col] = df[col].fillna(med)
    return df


# ──────────────────────────────────────────────────────────────────────────────
# 12. OUTLIERS
# ──────────────────────────────────────────────────────────────────────────────

def signaler_outliers(df: pd.DataFrame) -> pd.DataFrame:
    df["alerte_outlier"] = False
    if "Transit_Time_Reel" in df.columns:
        col = df["Transit_Time_Reel"].dropna()
        q1, q3 = col.quantile(0.25), col.quantile(0.75)
        iqr    = q3 - q1
        mask   = (df["Transit_Time_Reel"] < q1 - 1.5 * iqr) | (df["Transit_Time_Reel"] > q3 + 1.5 * iqr)
        df["alerte_outlier"] = mask
    return df


# ──────────────────────────────────────────────────────────────────────────────
# 13. COLONNES DÉRIVÉES ML
# ──────────────────────────────────────────────────────────────────────────────

def calculer_colonnes_derivees(df: pd.DataFrame) -> pd.DataFrame:
    # Déviations temporelles
    df["eta_deviation"] = (df["ATA"] - df["ETA"]).dt.days
    df["etd_deviation"] = (df["ATD"] - df["ETD"]).dt.days

    SEUIL_RETARD_ML = 4
    # Classification retard
    df["is_delayed"] = np.where(
        df["eta_deviation"].notna(),
        (df["eta_deviation"] >= SEUIL_RETARD_ML ).astype(int),
        np.nan
    )

    # Niveau de retard opérationnel
    conditions = [
        df["Transit_Time_Reel"] > df["Transit_Time"] + 60,
        df["Transit_Time_Reel"] > df["Transit_Time"] + 30,
        df["Transit_Time_Reel"] > df["Transit_Time"] + 5,
    ]
    df["niveau_retard"] = np.select(
        conditions,
        ["Retard critique", "Retard important", "Retard léger"],
        default="A temps"
    )
    # ✅ Annulés → niveau_retard = NULL
    df.loc[df["shipment_status"] == "Cancelled", "niveau_retard"] = np.nan

    # Ratios volumes
    df["volume_ratio_loaded"] = np.where(
        df["Confirmed Volume"].fillna(0) > 0,
        df["Charged Volume"] / df["Confirmed Volume"],
        np.nan
    )
    df["volume_ratio_allocated"] = np.where(
        df["Volume Booked"].fillna(0) > 0,
        df["Confirmed Volume"] / df["Volume Booked"],
        np.nan
    )

    return df


def calculer_month(df: pd.DataFrame) -> pd.DataFrame:
    """Resynchronise Month depuis ETD. Format : 'September 24'."""
    if "ETD" in df.columns:
        df["Month"] = df["ETD"].dt.strftime("%B %y")
    return df


def calculer_year(df: pd.DataFrame) -> pd.DataFrame:
    """
    À partir de la colonne Month :
      - "July 24"      -> Month = "Juillet",   Year = 2024
      - "January 25"   -> Month = "Janvier",   Year = 2025
    """
    if "Month" not in df.columns:
        return df

    mois = df["Month"].astype(str).str.strip()

    # Création de la colonne Year
    def extraire_annee(x):
        try:
            return 2000 + int(x)
        except (TypeError, ValueError):
            return np.nan

    df["Year"] = mois.str.extract(r"(\d{2})$")[0].apply(extraire_annee)

    # Conserver uniquement le nom du mois
    df["Month"] = mois.str.replace(r"\s+\d{2}$", "", regex=True)

    # Traduction des mois en français
    mois_fr = {
        "January": "Janvier",
        "February": "Février",
        "March": "Mars",
        "April": "Avril",
        "May": "Mai",
        "June": "Juin",
        "July": "Juillet",
        "August": "Août",
        "September": "Septembre",
        "October": "Octobre",
        "November": "Novembre",
        "December": "Décembre",
    }

    df["Month"] = (
        df["Month"]
        .str.title()
        .map(mois_fr)
        .fillna(df["Month"].str.title())
    )

    return df


# ──────────────────────────────────────────────────────────────────────────────
# 14. SUPPRESSION LIGNES SANS DONNÉES UTILES
# ──────────────────────────────────────────────────────────────────────────────

def supprimer_lignes_sans_dates(df: pd.DataFrame) -> pd.DataFrame:
    mask = (
        df["ETD"].isna() & df["ATD"].isna() &
        df["ETA"].isna() & df["ATA"].isna() &
        (df["shipment_status"] != "Cancelled")
    )
    avant = len(df)
    df = df[~mask].reset_index(drop=True)
    supprimees = avant - len(df)
    if supprimees:
        print(f"  → Lignes sans aucune date supprimées : {supprimees}")
    return df


# ──────────────────────────────────────────────────────────────────────────────
# 15. RAPPORT QUALITÉ FINAL
# ──────────────────────────────────────────────────────────────────────────────

def generer_rapport(df: pd.DataFrame) -> dict:
    n = len(df)
    rapport = {
        "total_lignes":          n,
        "cancelled":             int((df["shipment_status"] == "Cancelled").sum()),
        "avant_depart":          int((df["type_annulation"] == "Avant départ").sum()),
        "apres_depart":          int((df["type_annulation"] == "Après départ").sum()),
        "is_delayed_1":          int((df["is_delayed"] == 1).sum()),
        "is_delayed_0":          int((df["is_delayed"] == 0).sum()),
        "is_delayed_unknown":    int(df["is_delayed"].isna().sum()),
        "retard_critique":       int((df["niveau_retard"] == "Retard critique").sum()),
        "retard_important":      int((df["niveau_retard"] == "Retard important").sum()),
        "retard_leger":          int((df["niveau_retard"] == "Retard léger").sum()),
        "a_temps":               int((df["niveau_retard"] == "A temps").sum()),
        "erreurs_dates":         int(df.get("a_une_erreur", pd.Series(False)).sum()),
        "outliers_transit":      int(df.get("alerte_outlier", pd.Series(False)).sum()),
        "charge_sans_alloc":     int(df.get("charge_sans_allocation", pd.Series(False)).sum()),
        "transit_reel_median":   round(df["Transit_Time_Reel"].median(), 1) if "Transit_Time_Reel" in df else None,
        "eta_deviation_median":  round(df["eta_deviation"].median(), 1) if "eta_deviation" in df else None,
    }
    return rapport


# ──────────────────────────────────────────────────────────────────────────────
# 16. PIPELINE PRINCIPAL
# ──────────────────────────────────────────────────────────────────────────────

def run_etl(input_path: str, output_path: str) -> pd.DataFrame:
    sep = "=" * 60
    print(sep)
    print("MARITIME ETL PIPELINE v3")
    print(f"Source : {input_path}")
    print(sep)

    # ── Chargement ───────────────────────────────────────────
    df = charger_fichier(input_path)
    print(f"\n[1] Chargement : {df.shape[0]} lignes × {df.shape[1]} colonnes")
    print(f"    Colonnes : {list(df.columns)}")

    # ── Textes ───────────────────────────────────────────────
    df = normaliser_textes(df)
    print(f"\n[2] Textes normalisés")

    # ── Annulations ──────────────────────────────────────────
    df = detecter_annulations(df)
    df = determiner_type_annulation(df)
    n_cancel = (df["shipment_status"] == "Cancelled").sum()
    print(f"\n[3] Annulations : {n_cancel} cancelled "
          f"({(df['type_annulation']=='Avant départ').sum()} avant départ, "
          f"{(df['type_annulation']=='Après départ').sum()} après départ)")

    # ── Dates ────────────────────────────────────────────────
    df = nettoyer_colonnes_dates(df)
    print(f"\n[4] Dates parsées | NaT ETD={df['ETD'].isna().sum()} "
          f"ATD={df['ATD'].isna().sum()} ETA={df['ETA'].isna().sum()} "
          f"ATA={df['ATA'].isna().sum()}")

    # ── Imputations ──────────────────────────────────────────
    df = imputer_transit_time(df)
    df = imputer_pays_destination(df)
    print(f"\n[5] Imputations : Transit_Time NaT={df['Transit_Time'].isna().sum()}")

    # ── Recalculs dates manquantes ───────────────────────────
    df = recalculer_eta_manquante(df)
    df = recalculer_etd_manquante(df)
    df = recalculer_atd_manquante(df)
    df = recalculer_ata_manquante(df)
    df = calculer_transit_time_reel(df)
    print(f"\n[6] Recalcul dates manquantes | "
          f"NaT restants ETD={df['ETD'].isna().sum()} ATA={df['ATA'].isna().sum()}")

    # ── Corrections années ───────────────────────────────────
    df, log_ann = corriger_annee_erronnee(df)
    df = calculer_transit_time_reel(df)
    print(f"\n[7] Correction années : {len(log_ann)} cellules modifiées")

    # ── Correction inversions jour/mois ─────────────────────
    print(f"\n[8] Correction inversions jour/mois :")
    df = corriger_inversion_jour_mois(df)
    df = calculer_transit_time_reel(df)

    # ── Suppression lignes sans dates ────────────────────────
    df = supprimer_lignes_sans_dates(df)
    print(f"\n[9] Lignes restantes : {len(df)}")


    # ── Volumes ──────────────────────────────────────────────
    df = nettoyer_volumes(df)
    # Audit AVANT imputation
    df = auditer_volumes(df)
    nb_avant = df["erreur_charged_trop_superieur"].sum()

    print(f"\n[10] Audit volumes avant imputation")
    print(f"     Charged > 1.5 × Confirmed : {nb_avant}")
    df = imputer_volumes(df)
    df = imputer_volumes_par_mediane(df)
    # Audit APRÈS imputation
    df = auditer_volumes(df)
    nb_apres = df["erreur_charged_trop_superieur"].sum()

    print(f"\n[11] Audit volumes après imputation")
    print(f"     Charged > 1.5 × Confirmed : {nb_apres}")

    print(f"     Évolution : {nb_avant} → {nb_apres}")


    # ── Colonnes dérivées ─────────────────────────────────────
    df = signaler_outliers(df)
    df = calculer_colonnes_derivees(df)
    df = calculer_year(df)
    print(f"\n[12] Colonnes dérivées calculées")
    print(f"    is_delayed=1 : {(df['is_delayed']==1).sum()}")
    print(f"    Retard critique : {(df['niveau_retard']=='Retard critique').sum()}")
    print(f"    Retard important : {(df['niveau_retard']=='Retard important').sum()}")
    print(f"    Retard léger : {(df['niveau_retard']=='Retard léger').sum()}")
    print(f"    À temps : {(df['niveau_retard']=='A temps').sum()}")


    # ── Sauvegarde ────────────────────────────────────────────
    df.to_excel(output_path, index=False)
     # ============================================================
# VERIFICATION DES VALEURS MANQUANTES APRES ETL
# ============================================================

    print("\n=== VALEURS MANQUANTES APRES ETL ===")

# Nombre total de cellules manquantes dans le dataset final
    total_missing = df.isna().sum().sum()

    print(f"Valeurs manquantes totales : {total_missing}")

# Colonnes originales du dataset source
    original_columns = [
      'Carrier',
      'Vessel',
      'Port of Loading',
      'Port of Discharge',
      'Incoterm',
      'Transit_Time',
      'Frequency',
      'Port of Discharge country',
      'ETD',
      'ATD',
      'ETA',
      'ATA',
      'Volume Booked',
      'Confirmed Volume',
      'Charged Volume',
      'Month',
      'Operateur'
]

# Valeurs manquantes uniquement dans les 17 colonnes originales
    missing_original = df[original_columns].isna().sum().sum()

    print(
      f"Valeurs manquantes dans les 17 colonnes originales : "
      f"{missing_original}"
    )

# Valeurs manquantes uniquement dans les nouvelles colonnes
    new_columns = [
       col for col in df.columns
       if col not in original_columns
]

    missing_derived = df[new_columns].isna().sum().sum()

    print(
        f"Valeurs manquantes dans les 18 nouvelles colonnes : "
        f"{missing_derived}"
)

# Vérification
    print(
       f"Vérification : {missing_original} + "
       f"{missing_derived} = "
       f"{missing_original + missing_derived}"
)

# Détail des valeurs manquantes par colonne
    print("\n--- Détail par colonne ---")

    missing_by_column = df.isna().sum()

    for column, count in missing_by_column.items():
        if count > 0:
           print(f"  {column} : {count}")
    rapport = generer_rapport(df)
    print(f"\n{sep}")
    print(f"✅ Fichier sauvegardé : {output_path}")
    print(f"   {df.shape[0]} lignes × {df.shape[1]} colonnes")
    print(sep)

    return df, rapport


# ──────────────────────────────────────────────────────────────────────────────
# POINT D'ENTRÉE
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    input_path  = sys.argv[1] if len(sys.argv) > 1 else "data/maritime_dataset_final_corrige_v3_cancelled.xlsx"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "data/maritime_dataset_nettoye.xlsx"

    df, rapport = run_etl(input_path, output_path)

    print("\n=== RAPPORT QUALITÉ FINAL ===")
    for k, v in rapport.items():
        print(f"  {k:<28}: {v}")

df = pd.read_excel("data/maritime_dataset_nettoye.xlsx", nrows=1)

print(list(df.columns))