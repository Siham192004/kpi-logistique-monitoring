"""
Regression_logistique.py — Modèle de prédiction de retard : RÉGRESSION LOGISTIQUE
Source de données : base SQLite Logistique.db (table shipment + vessel)

Méthode d'évaluation : split ALÉATOIRE STRATIFIÉ (80/20)
Rééquilibrage       : SMOTE sur le train uniquement (pas de leakage)

Features numériques (17) :
    transit_time, frequency_num, volume_ratio_allocated_booked,
    volume_booked, confirmed_volume,
    carrier_taux_retard, route_taux_retard,
    month_sin, month_cos,
    etd_precipitation_mm, etd_wind_speed_kmh, etd_temperature_max, etd_weather_code,
    eta_precipitation_mm, eta_wind_speed_kmh, eta_temperature_max, eta_weather_code
Features catégorielles (4) :
    carrier, port_chargement, port_dechargement, pays_destination
Variable cible : is_delayed (0 = à l'heure, 1 = en retard)

Métriques d'évaluation :
    accuracy, precision, recall, f1, log_loss, jaccard_index, cv_f1

Exclusions (data leakage) :
    eta_deviation, etd_deviation, transit_time_reel, volume_ratio_loaded,
    ATD/ATA/ETA bruts, niveau_retard, incoterm
"""

import warnings
import logging
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import joblib

from engine.weather_client import get_weather_for_prediction, enrich_dataset_with_weather
from imblearn.over_sampling import SMOTE
from imblearn.pipeline import Pipeline as ImbPipeline
from scipy.stats import loguniform
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score, classification_report, confusion_matrix,
    f1_score, jaccard_score, log_loss,
    precision_recall_curve, precision_score, recall_score,
)
from sklearn.model_selection import (
    RandomizedSearchCV, StratifiedKFold,
    cross_val_score, train_test_split,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

MOIS_FR = {
    "Janvier": 1,  "Février": 2,  "Mars": 3,    "Avril": 4,
    "Mai": 5,      "Juin": 6,     "Juillet": 7,  "Août": 8,
    "Septembre": 9,"Octobre": 10, "Novembre": 11,"Décembre": 12,
}

# ── Chemins ───────────────────────────────────────────────────────────────────
DB_PATH    = Path("data/Logistique.db")
MODEL_PATH = Path("models/regression_logistique.pkl")
MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)

# ── Features ──────────────────────────────────────────────────────────────────
FEATURES_NUM = [
    "transit_time",
    "frequency_num",
    "volume_ratio_allocated_booked",
    "volume_booked",
    "confirmed_volume",
    "carrier_taux_retard",
    "route_taux_retard",
    "month_sin",
    "month_cos",
    # Features météo
    "etd_precipitation_mm",
    "etd_wind_speed_kmh",
    "etd_temperature_max",
    "etd_weather_code",
    "eta_precipitation_mm",
    "eta_wind_speed_kmh",
    "eta_temperature_max",
    "eta_weather_code",
]

FEATURES_CAT = [
    "carrier",
    "port_chargement",
    "port_dechargement",
    "pays_destination",
]

TOUTES_FEATURES = FEATURES_NUM + FEATURES_CAT


# ═══════════════════════════════════════════════════════════════════════════
# CHARGEMENT DEPUIS LA BASE DE DONNÉES
# ═══════════════════════════════════════════════════════════════════════════

def get_all_shipments(db_path: Path = DB_PATH) -> pd.DataFrame:
    if not db_path.exists():
        raise FileNotFoundError(
            f"Base introuvable : {db_path}\n"
            "Vérifiez que Logistique.db est dans le répertoire courant."
        )
    conn = sqlite3.connect(db_path)
    df = pd.read_sql(
        """
        SELECT s.*, v.carrier
        FROM shipment s
        JOIN vessel v ON s.vessel_id = v.id
        """,
        conn,
    )
    conn.close()
    logger.info("Base chargée : %d lignes, %d colonnes", *df.shape)
    return df


# ═══════════════════════════════════════════════════════════════════════════
# FEATURE ENGINEERING
# ═══════════════════════════════════════════════════════════════════════════

def extraire_frequency_num(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["frequency_num"] = (
        df["frequency"].astype(str).str.extract(r"(\d+)").astype(float)
    )
    return df



def extraire_month_cyclique(df: pd.DataFrame) -> pd.DataFrame:
    """
    Accepte les deux formats :
      - Français sans année : 'Septembre', 'Janvier' (format après ETL en base)
      - Anglais avec année  : 'September 24' (format brut avant ETL)
    """
    df = df.copy()

    # Priorité : mapping français direct (format base de données)
    mois_num = df["month"].astype(str).str.strip().map(MOIS_FR)

    # Fallback : format anglais avec année (format brut)
    mask_nan = mois_num.isna()
    if mask_nan.any():
        mois_num[mask_nan] = pd.to_datetime(
            df.loc[mask_nan, "month"], format="%B %y", errors="coerce"
        ).dt.month

    df["month_sin"] = np.sin(2 * np.pi * mois_num / 12)
    df["month_cos"] = np.cos(2 * np.pi * mois_num / 12)
    return df


def calculer_taux_retard_carrier(
    X_train: pd.DataFrame,
    X_test: pd.DataFrame,
    y_train: pd.Series,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, float]:
    """
    Taux de retard par carrier — calculé sur train uniquement (pas de leakage).
    """
    taux_global = float(y_train.mean())
    taux_par_carrier = (
        X_train.assign(is_delayed=y_train.values)
        .groupby("carrier")["is_delayed"]
        .mean()
    )
    X_train = X_train.copy()
    X_test  = X_test.copy()
    X_train["carrier_taux_retard"] = X_train["carrier"].map(taux_par_carrier).fillna(taux_global)
    X_test["carrier_taux_retard"]  = X_test["carrier"].map(taux_par_carrier).fillna(taux_global)
    return X_train, X_test, taux_par_carrier, taux_global


def calculer_taux_retard_route(
    X_train: pd.DataFrame,
    X_test: pd.DataFrame,
    y_train: pd.Series,
    taux_global: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """
    Taux de retard par route (port_chargement + port_dechargement).
    Calculé sur train uniquement pour éviter tout data leakage.
    """
    taux_par_route = (
        X_train.assign(is_delayed=y_train.values)
        .groupby(["port_chargement", "port_dechargement"])["is_delayed"]
        .mean()
    )
    X_train = X_train.copy()
    X_test  = X_test.copy()

    X_train["route_taux_retard"] = (
        X_train.set_index(["port_chargement", "port_dechargement"])
        .index.map(taux_par_route)
        .fillna(taux_global)
        .values
    )
    X_test["route_taux_retard"] = (
        X_test.set_index(["port_chargement", "port_dechargement"])
        .index.map(taux_par_route)
        .fillna(taux_global)
        .values
    )
    return X_train, X_test, taux_par_route


# ═══════════════════════════════════════════════════════════════════════════
# PRÉPARATION DES DONNÉES
# ═══════════════════════════════════════════════════════════════════════════

def preparer_donnees(
    df: pd.DataFrame | None = None,
    proportion_test: float = 0.2,
) -> tuple:
    if df is None:
        df = get_all_shipments()

    df_ml = df[df["is_delayed"].notna()].copy()

    df_ml = extraire_frequency_num(df_ml)
    df_ml = extraire_month_cyclique(df_ml)
    
    print("✅ Météo chargée depuis la base de données.")

    y = df_ml["is_delayed"].astype(int)

    features_brutes = [
        "transit_time", "frequency_num", "volume_ratio_allocated_booked",
        "volume_booked", "confirmed_volume",
        "month_sin", "month_cos",
        "carrier", "port_chargement", "port_dechargement", "pays_destination",
        # météo
        "etd_precipitation_mm", "etd_wind_speed_kmh",
        "etd_temperature_max",  "etd_weather_code",
        "eta_precipitation_mm", "eta_wind_speed_kmh",
        "eta_temperature_max",  "eta_weather_code",
    ]
    X = df_ml[features_brutes].copy()

    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=proportion_test,
        random_state=42,
        stratify=y,
    )

    # Taux retard carrier (sur train uniquement)
    X_train, X_test, taux_par_carrier, taux_global = calculer_taux_retard_carrier(
        X_train, X_test, y_train
    )

    # Taux retard route (sur train uniquement)
    X_train, X_test, taux_par_route = calculer_taux_retard_route(
        X_train, X_test, y_train, taux_global
    )

    print(f"\nDataset ML     : {len(df_ml)} shipments")
    print(f"En retard      : {y.sum()} ({y.mean()*100:.1f}%)")
    print(f"À l'heure      : {(y == 0).sum()} ({(1 - y.mean())*100:.1f}%)")
    print(f"Train set      : {len(X_train)} lignes")
    print(f"Test set       : {len(X_test)} lignes")
    print(f"Features       : {TOUTES_FEATURES}")

    return X_train, X_test, y_train, y_test, taux_par_carrier, taux_par_route, taux_global


# ═══════════════════════════════════════════════════════════════════════════
# CONSTRUCTION DU PIPELINE — avec SMOTE intégré (imblearn Pipeline)
#
# POURQUOI SMOTE ICI :
#   - SMOTE génère des exemples synthétiques de la classe minoritaire
#     (is_delayed=1) uniquement sur le train — jamais sur le test.
#   - Cela corrige le déséquilibre des classes sans biaiser l'évaluation.
#   - On utilise imblearn.Pipeline (pas sklearn.Pipeline) pour que SMOTE
#     s'applique uniquement pendant le fit(), pas pendant predict().
#   - class_weight='balanced' est retiré car SMOTE remplace ce mécanisme
#     et les deux ensemble surcompensent le déséquilibre.
# ═══════════════════════════════════════════════════════════════════════════

def construire_pipeline(C: float = 1.0, l1_ratio: float = 0.5) -> ImbPipeline:
    preprocesseur = ColumnTransformer(
        transformers=[
            (
                "num",
                Pipeline(steps=[
                    ("imputation",    SimpleImputer(strategy="median")),
                    ("normalisation", StandardScaler()),
                ]),
                FEATURES_NUM,
            ),
            (
                "cat",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                FEATURES_CAT,
            ),
        ],
        remainder="drop",
    )

    # ImbPipeline : SMOTE s'applique après le preprocessing, avant le modèle
    pipeline = ImbPipeline(steps=[
        ("preprocesseur", preprocesseur),
        (
            # SMOTE uniquement sur train (géré automatiquement par ImbPipeline)
            # k_neighbors=5 : valeur standard, réduit à 3 si dataset petit
            "smote", SMOTE(random_state=42, k_neighbors=5),
        ),
        (
            "modele",
            LogisticRegression(
                solver="saga",
                penalty="elasticnet",
                l1_ratio=l1_ratio,
                C=C,
                # class_weight retiré — SMOTE remplace ce mécanisme
                class_weight=None,
                max_iter=5000,
                random_state=42,
            ),
        ),
    ])
    return pipeline


# ═══════════════════════════════════════════════════════════════════════════
# TUNING DES HYPERPARAMÈTRES
# ═══════════════════════════════════════════════════════════════════════════

def tuner_hyperparametres(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    n_iter: int = 50,
) -> tuple:
    pipeline_base = construire_pipeline()
    espace_recherche = {
        "modele__C":                loguniform(1e-2, 1e2),
        "modele__l1_ratio":         [0.0, 0.1, 0.2, 0.3, 0.4, 0.5],
        "smote__sampling_strategy": [0.5, 0.7, 1.0],
    }
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    recherche = RandomizedSearchCV(
        estimator=pipeline_base,
        param_distributions=espace_recherche,
        n_iter=n_iter,
        scoring="f1_macro",          # ← CORRECTION : était "f1"
        cv=cv,
        random_state=42,
        n_jobs=-1,
        verbose=1,
        error_score=0.0,
    )
    print(f"\n=== TUNING HYPERPARAMÈTRES ({n_iter} combinaisons) ===")
    recherche.fit(X_train, y_train)
    print(f"\nMeilleur F1 macro CV : {recherche.best_score_*100:.2f}%")
    print("Meilleurs paramètres :")
    for k, v in recherche.best_params_.items():
        print(f"  {k:40s} : {v}")
    return recherche.best_estimator_, recherche.best_params_, recherche.best_score_


# ═══════════════════════════════════════════════════════════════════════════
# SEUIL DE DÉCISION OPTIMAL
# ═══════════════════════════════════════════════════════════════════════════


def trouver_seuil_optimal(
    pipeline: ImbPipeline,
    X_train: pd.DataFrame,
    y_train: pd.Series,
) -> float:
    """
    Optimise le seuil sur f1_macro via grille linéaire 0.1→0.9.
    La courbe PR favorisait la classe majoritaire — f1_macro équilibre les deux.
    """
    probas = pipeline.predict_proba(X_train)[:, 1]
    seuils_candidats = np.linspace(0.1, 0.9, 81)

    meilleur_f1    = 0.0
    meilleur_seuil = 0.5

    for seuil in seuils_candidats:
        y_pred = (probas >= seuil).astype(int)
        score  = f1_score(y_train, y_pred, average="macro", zero_division=0)
        if score > meilleur_f1:
            meilleur_f1    = score
            meilleur_seuil = seuil

    print(f"\nSeuil optimal (F1 macro sur train) : {meilleur_seuil:.3f}")
    print(f"F1 macro au seuil optimal          : {meilleur_f1*100:.2f}%")
    return meilleur_seuil


# ═══════════════════════════════════════════════════════════════════════════
# ÉVALUATION — avec log_loss et jaccard_index
#
# LOG_LOSS (entropie croisée) :
#   - Mesure la qualité des probabilités prédites (pas juste la classe).
#   - Plus il est bas, mieux c'est. 0 = parfait.
#   - Objectif : < 0.5 (bon modèle), < 0.35 (très bon modèle).
#   - Utile car notre modèle sort des probabilités de retard.
#
# JACCARD INDEX (Intersection over Union) :
#   - Jaccard = VP / (VP + FP + FN)
#   - Mesure le chevauchement entre prédictions et vérité.
#   - Entre 0 et 1, plus c'est élevé mieux c'est.
#   - Complément du F1 : plus strict car ignore les VN.
#   - Objectif : > 0.35 (acceptable), > 0.50 (bon).
# ═══════════════════════════════════════════════════════════════════════════


def evaluer_modele(
    pipeline: ImbPipeline,
    X_train: pd.DataFrame,
    X_test: pd.DataFrame,
    y_train: pd.Series,
    y_test: pd.Series,
    seuil: float = 0.50,
) -> dict:
    # Performance Train
    y_train_proba = pipeline.predict_proba(X_train)[:, 1]
    y_train_pred  = (y_train_proba >= seuil).astype(int)
    print("\n=== PERFORMANCE TRAIN ===")
    print(f"Accuracy train  : {accuracy_score(y_train, y_train_pred)*100:.2f}%")
    print(f"F1 macro train  : {f1_score(y_train, y_train_pred, average='macro')*100:.2f}%")
    print(f"Log Loss train  : {log_loss(y_train, y_train_proba):.4f}")

    # Performance Test
    y_pred_proba = pipeline.predict_proba(X_test)[:, 1]
    y_pred       = (y_pred_proba >= seuil).astype(int)

    acc      = accuracy_score(y_test, y_pred)
    prec     = precision_score(y_test, y_pred, zero_division=0)
    rec      = recall_score(y_test, y_pred, zero_division=0)
    f1_macro = f1_score(y_test, y_pred, average="macro",  zero_division=0)
    f1_ret   = f1_score(y_test, y_pred, pos_label=1,      zero_division=0)
    f1_heure = f1_score(y_test, y_pred, pos_label=0,      zero_division=0)
    logloss  = log_loss(y_test, y_pred_proba)
    jaccard  = jaccard_score(y_test, y_pred, zero_division=0)

    print("\n=== PERFORMANCE TEST ===")
    print(f"Accuracy          : {acc*100:.2f}%")
    print(f"F1 macro          : {f1_macro*100:.2f}%")
    print(f"F1 'En retard'    : {f1_ret*100:.2f}%")
    print(f"F1 'À l'heure'   : {f1_heure*100:.2f}%")
    print(f"Precision         : {prec*100:.2f}%")
    print(f"Recall            : {rec*100:.2f}%")
    print(f"Log Loss          : {logloss:.4f}  (objectif < 0.50 | très bon < 0.35)")
    print(f"Jaccard Index     : {jaccard:.4f}  (objectif > 0.35 | bon > 0.50)")

    cm = confusion_matrix(y_test, y_pred)
    print("\nMatrice de confusion :")
    print(cm)
    print(f"  VN={cm[0][0]}  FP={cm[0][1]}  FN={cm[1][0]}  VP={cm[1][1]}")
    print(f"  → {cm[0][0]} shipments 'À l'heure' correctement identifiés")
    print(f"  → {cm[1][1]} shipments 'En retard' correctement identifiés")

    print("\nRapport complet :")
    print(classification_report(
        y_test, y_pred,
        target_names=["À l'heure", "En retard"],
        zero_division=0,
    ))

    # CORRECTION 3 : f1_macro dans cross_val_score
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores_cv = cross_val_score(
        pipeline, X_train, y_train,
        cv=cv,
        scoring="f1_macro",          # ← CORRECTION : était "f1"
    )
    print(f"CV F1 macro (train) : {scores_cv.mean()*100:.2f}% (+/- {scores_cv.std()*100:.2f}%)")
    print(f"Écart CV/test       : {(scores_cv.mean() - f1_macro)*100:+.2f} pts")

    # Interprétations
    print(f"\n📊 Interprétation Log Loss ({logloss:.4f}) :")
    if logloss < 0.35:    print("   ✅ Très bon — probabilités bien calibrées")
    elif logloss < 0.50:  print("   ✅ Bon — modèle fiable")
    elif logloss < 0.70:  print("   ⚠️  Acceptable — probabilités à améliorer")
    else:                 print("   🔴 Mauvais — modèle peu fiable")

    print(f"\n📊 Interprétation Jaccard ({jaccard:.4f}) :")
    if jaccard > 0.50:    print("   ✅ Bon — fort chevauchement prédictions/réalité")
    elif jaccard > 0.35:  print("   ✅ Acceptable — chevauchement modéré")
    else:                 print("   ⚠️  Faible — beaucoup de FP ou FN")

    return {
        "accuracy":      round(acc      * 100, 2),
        "f1_macro":      round(f1_macro * 100, 2),
        "f1_retard":     round(f1_ret   * 100, 2),
        "f1_a_lheure":   round(f1_heure * 100, 2),
        "precision":     round(prec     * 100, 2),
        "recall":        round(rec      * 100, 2),
        "log_loss":      round(logloss,         4),
        "jaccard_index": round(jaccard,         4),
        "cv_f1_mean":    round(scores_cv.mean() * 100, 2),
        "cv_f1_std":     round(scores_cv.std()  * 100, 2),
    }


# ═══════════════════════════════════════════════════════════════════════════
# IMPORTANCE DES FEATURES (COEFFICIENTS)
# ═══════════════════════════════════════════════════════════════════════════

def afficher_importance_features(pipeline: ImbPipeline, top_n: int = 20) -> pd.DataFrame:
    preprocesseur = pipeline.named_steps["preprocesseur"]

    # get_feature_names_out() retourne les noms RÉELS après fit
    # (plus fiable que num_transformer[2] qui peut avoir un décalage avec SMOTE)
    try:
        all_names = preprocesseur.get_feature_names_out().tolist()
        # Nettoyer les préfixes sklearn : "num__transit_time" → "transit_time"
        all_names = [
            n.replace("num__", "").replace("cat__", "")
            for n in all_names
        ]
    except Exception:
        # Fallback si get_feature_names_out échoue
        cat_names = (
            preprocesseur.named_transformers_["cat"]
            .get_feature_names_out(FEATURES_CAT)
            .tolist()
        )
        all_names = FEATURES_NUM + cat_names

    coefficients = pipeline.named_steps["modele"].coef_[0]

    print(f"  Num features : {len(FEATURES_NUM)}")
    print(f"  Cat features : {len(all_names) - len(FEATURES_NUM)}")
    print(f"  Total noms   : {len(all_names)}")
    print(f"  Coefficients : {len(coefficients)}")

    # Ajustement si mismatch résiduel
    min_len = min(len(all_names), len(coefficients))
    if len(all_names) != len(coefficients):
        print(f"  ⚠️  Ajustement à {min_len} features")

    df_coef = (
        pd.DataFrame({
            "feature":     all_names[:min_len],
            "coefficient": coefficients[:min_len],
        })
        .assign(impact_abs=lambda d: d["coefficient"].abs())
        .sort_values("impact_abs", ascending=False)
        .drop(columns="impact_abs")
        .reset_index(drop=True)
    )
    print(f"\n=== TOP {top_n} FEATURES (triées par impact absolu) ===")
    print("(positif = augmente le risque de retard, négatif = le diminue)")
    print(df_coef.head(top_n).to_string(index=False))

    non_nuls = (df_coef["coefficient"].abs() > 1e-6).sum()
    print(f"\n→ {non_nuls}/{len(df_coef)} features avec coefficient non nul")

    return df_coef


# ═══════════════════════════════════════════════════════════════════════════
# SAUVEGARDE
# ═══════════════════════════════════════════════════════════════════════════

def sauvegarder_modele(
    pipeline: ImbPipeline,
    taux_par_carrier: pd.Series,
    taux_par_route: pd.Series,
    taux_global: float,
    seuil_decision: float,
) -> None:
    joblib.dump(
        {
            "pipeline":         pipeline,
            "taux_par_carrier": taux_par_carrier,
            "taux_par_route":   taux_par_route,
            "taux_global":      taux_global,
            "seuil_decision":   seuil_decision,
        },
        MODEL_PATH,
    )
    print(f"\n✓ Modèle sauvegardé : {MODEL_PATH}")
    print(f"  Seuil de décision sauvegardé : {seuil_decision:.3f}")


# ═══════════════════════════════════════════════════════════════════════════
# CHARGEMENT ET PRÉDICTION
# ═══════════════════════════════════════════════════════════════════════════

def charger_modele() -> tuple:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Modèle introuvable : {MODEL_PATH}\n"
            "Lancez d'abord : python -m engine.Regression_logistique"
        )
    contenu = joblib.load(MODEL_PATH)
    seuil   = contenu.get("seuil_decision", 0.50)
    return (
        contenu["pipeline"],
        contenu["taux_par_carrier"],
        contenu.get("taux_par_route", pd.Series(dtype=float)),
        contenu["taux_global"],
        seuil,
    )


def predire_retard(nouveau_shipment: dict) -> dict:
    
    pipeline, taux_par_carrier, taux_par_route, taux_global, seuil_decision = charger_modele()

    # Features de base
    frequency_str   = str(nouveau_shipment.get("frequency", ""))
    frequency_match = pd.Series([frequency_str]).str.extract(r"(\d+)").iloc[0, 0]
    frequency_num   = float(frequency_match) if pd.notna(frequency_match) else np.nan

    # ── CORRECTION : parsing mois français ET anglais ─────────────────────
    mois_texte  = str(nouveau_shipment.get("month", "")).strip()
    mois_num_val = MOIS_FR.get(mois_texte.split()[0])   # "Septembre" → 9
    if mois_num_val is None:
        # Fallback anglais : "September 24" → 9
        mois_num_val = pd.to_datetime(
            pd.Series([mois_texte]), format="%B %y", errors="coerce"
        ).dt.month.iloc[0]

    if pd.notna(mois_num_val):
        month_sin = float(np.sin(2 * np.pi * mois_num_val / 12))
        month_cos = float(np.cos(2 * np.pi * mois_num_val / 12))
    else:
        month_sin = np.nan
        month_cos = np.nan

    carrier      = nouveau_shipment.get("carrier", "") or ""
    carrier_taux = float(taux_par_carrier.get(carrier, taux_global))

    pol = nouveau_shipment.get("port_chargement", "")
    pod = nouveau_shipment.get("port_dechargement", "")
    route_taux = float(
        taux_par_route.get((pol, pod), taux_global)
        if (pol, pod) in taux_par_route.index else taux_global
    )

    vol_booked    = float(nouveau_shipment.get("volume_booked") or 0)
    vol_confirmed = float(nouveau_shipment.get("confirmed_volume") or 0)
    volume_ratio  = (
        nouveau_shipment.get("volume_ratio_allocated_booked")
        or (vol_confirmed / vol_booked if vol_booked > 0 else np.nan)
    )

    # Météo temps réel
    meteo = get_weather_for_prediction(
        port_chargement=pol,
        port_dechargement=pod,
        etd=str(nouveau_shipment.get("etd", "")),
        eta=str(nouveau_shipment.get("eta", "")),
    )
    print("Météo reçue:", meteo)
    print("route_taux:", route_taux)
    X_nouveau = pd.DataFrame([{
        "transit_time":                  nouveau_shipment.get("transit_time", np.nan),
        "frequency_num":                 frequency_num,
        "volume_ratio_allocated_booked": volume_ratio,
        "volume_booked":                 vol_booked or np.nan,
        "confirmed_volume":              vol_confirmed or np.nan,
        "carrier_taux_retard":           carrier_taux,
        "route_taux_retard":             route_taux,
        "month_sin":                     month_sin,
        "month_cos":                     month_cos,
        "carrier":                       carrier,
        "port_chargement":               pol or np.nan,
        "port_dechargement":             pod or np.nan,
        "pays_destination":              nouveau_shipment.get("pays_destination") or np.nan,
        # météo
        "etd_precipitation_mm": meteo.get("etd_precipitation_mm", np.nan),
        "etd_wind_speed_kmh":   meteo.get("etd_wind_speed_kmh",   np.nan),
        "etd_temperature_max":  meteo.get("etd_temperature_max",  np.nan),
        "etd_weather_code":     meteo.get("etd_weather_code",     np.nan),
        "eta_precipitation_mm": meteo.get("eta_precipitation_mm", np.nan),
        "eta_wind_speed_kmh":   meteo.get("eta_wind_speed_kmh",   np.nan),
        "eta_temperature_max":  meteo.get("eta_temperature_max",  np.nan),
        "eta_weather_code":     meteo.get("eta_weather_code",     np.nan),
    }])

    probabilite = float(pipeline.predict_proba(X_nouveau)[0][1])
    prediction  = int(probabilite >= seuil_decision)

    if probabilite < 0.35:
        niveau_risque = "Faible"
    elif probabilite < 0.65:
        niveau_risque = "Moyen"
    else:
        niveau_risque = "Élevé"

    return {
        "prediction":         prediction,
        "probabilite_retard": round(probabilite * 100, 1),
        "niveau_risque":      niveau_risque,
        "label":              "En retard" if prediction == 1 else "À l'heure",
        "seuil_utilise":      round(seuil_decision, 3),
        "meteo":              meteo,   # ✅ AJOUTER
    }


# ═══════════════════════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  ENTRAÎNEMENT : RÉGRESSION LOGISTIQUE + SMOTE + MÉTÉO + ROUTE")
    print("  Split aléatoire stratifié 80/20")
    print("=" * 60)

    # 1. Chargement et préparation
    df_raw = get_all_shipments()
    X_train, X_test, y_train, y_test, taux_par_carrier, taux_par_route, taux_global = preparer_donnees(df_raw)

    print(f"\n📊 Distribution avant SMOTE :")
    print(f"   Train — En retard: {y_train.sum()} ({y_train.mean()*100:.1f}%) | À l'heure: {(y_train==0).sum()}")

    # 2. Tuning hyperparamètres (SMOTE intégré dans le pipeline)
    pipeline, best_params, best_cv_score = tuner_hyperparametres(X_train, y_train, n_iter=50)

    # 3. Seuil de décision optimal
    seuil_optimal = trouver_seuil_optimal(pipeline, X_train, y_train)

    # 4. Évaluation complète (accuracy + f1 + log_loss + jaccard)
    metriques = evaluer_modele(pipeline, X_train, X_test, y_train, y_test, seuil=seuil_optimal)

    # 5. Importance des features
    afficher_importance_features(pipeline, top_n=20)

    # 6. Sauvegarde
    sauvegarder_modele(pipeline, taux_par_carrier, taux_par_route, taux_global, seuil_optimal)

    print("\n" + "=" * 60)
    print("  RÉSUMÉ FINAL")
    print(f"  Accuracy      : {metriques['accuracy']}%")
    print(f"  F1 macro      : {metriques['f1_macro']}%")
    print(f"  F1 En retard  : {metriques['f1_retard']}%")
    print(f"  F1 À l'heure  : {metriques['f1_a_lheure']}%")
    print(f"  Precision     : {metriques['precision']}%")
    print(f"  Recall        : {metriques['recall']}%")
    print(f"  Log Loss      : {metriques['log_loss']}")
    print(f"  Jaccard Index : {metriques['jaccard_index']}")
    print(f"  CV F1 macro   : {metriques['cv_f1_mean']}% (+/- {metriques['cv_f1_std']}%)")
    print("=" * 60)

    print("\n=== TEST DE PRÉDICTION SUR UN EXEMPLE ===")
    exemple = {
        "transit_time": 10, "frequency": "7j", "month": "September 25",
        "volume_booked": 1000, "confirmed_volume": 950,
        "carrier": "Grimaldi Lines", "port_chargement": "Tanger Med",
        "port_dechargement": "Civitavecchia", "pays_destination": "Italy",
        "etd": "2025-09-15", "eta": "2025-09-25",
    }
    resultat = predire_retard(exemple)
    print(f"Shipment test -> {resultat['label']} "
          f"(probabilité : {resultat['probabilite_retard']}%, "
          f"risque : {resultat['niveau_risque']})")