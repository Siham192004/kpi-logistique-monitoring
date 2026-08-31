"""
Regression_logistique.py — Modèle de prédiction de retard : RÉGRESSION LOGISTIQUE
Source de données : base SQLite Logistique.db (table shipment + vessel)

Méthode d'évaluation : split ALÉATOIRE STRATIFIÉ (80/20)
La stratification garantit que la proportion de retards (≈26%) est
identique dans le train et le test — identique au Random Forest pour
permettre une comparaison équitable des deux modèles.

Résultats obtenus :
    F1 test : ~44-50%  |  CV train : ~44-48%  (écart faible = pas de surapprentissage)

Spécificité de ce modèle par rapport au Random Forest :
    StandardScaler appliqué aux features numériques (la régression logistique
    est sensible à l'échelle des variables, contrairement aux arbres).
    Régularisation ElasticNet (mélange L1 + L2) pour gérer les features
    corrélées et effectuer une sélection automatique.

Features numériques (8) :
    transit_time, frequency_num, volume_ratio_allocated_booked,
    volume_booked, confirmed_volume,
    carrier_taux_retard, month_sin, month_cos
Features catégorielles (4) :
    carrier, port_chargement, port_dechargement, pays_destination
Variable cible : is_delayed (0 = à l'heure, 1 = en retard)

Exclusions (data leakage) :
    eta_deviation, etd_deviation, transit_time_reel, volume_ratio_loaded,
    ATD/ATA/ETA bruts, niveau_retard, incoterm (condition commerciale, non opérationnelle)
"""

import warnings
import logging
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import joblib

from sklearn.ensemble import StackingClassifier
from sklearn.linear_model import LogisticRegression
from lightgbm import LGBMClassifier
from xgboost import XGBClassifier
from engine.weather_client import get_weather_for_prediction
from engine.weather_client import enrich_dataset_with_weather
from scipy.stats import loguniform
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score, classification_report, confusion_matrix,
    f1_score, precision_recall_curve, precision_score, recall_score,
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

# ── Chemins ───────────────────────────────────────────────────────────────────
DB_PATH    = Path("data/Logistique.db")
MODEL_PATH = Path("models/regression_logistique.pkl")
MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)

# ── Features ──────────────────────────────────────────────────────────────────
# Alignées sur Random Forest (8 numériques + 4 catégorielles)
FEATURES_NUM = [
    "transit_time",
    "frequency_num",
    "volume_ratio_allocated_booked",
    "volume_booked",            # ajout vs version précédente
    "confirmed_volume",         # ajout vs version précédente
    "carrier_taux_retard",
    "month_sin",
    "month_cos",
    # ── NOUVELLES FEATURES MÉTÉO ──
    "etd_precipitation_mm",   # pluie au départ
    "etd_wind_speed_kmh",     # vent au départ
    "etd_temperature_max",    # température au départ
    "etd_weather_code",       # code météo WMO au départ
    "eta_precipitation_mm",   # pluie à l'arrivée
    "eta_wind_speed_kmh",     # vent à l'arrivée
    "eta_temperature_max",    # température à l'arrivée
    "eta_weather_code",       # code météo WMO à l'arrivée
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
    """
    Charge tous les shipments depuis Logistique.db en joignant la table
    vessel pour récupérer le carrier.
    """
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
    """'7j' → 7.0  |  valeur inconnue → NaN"""
    df = df.copy()
    df["frequency_num"] = (
        df["frequency"].astype(str).str.extract(r"(\d+)").astype(float)
    )
    return df


def extraire_month_cyclique(df: pd.DataFrame) -> pd.DataFrame:
    """
    'July 24' → month_sin / month_cos
    Encodage cyclique : décembre et janvier sont proches dans l'espace des features.
    """
    df = df.copy()
    mois_num = pd.to_datetime(df["month"], format="%B %y", errors="coerce").dt.month
    df["month_sin"] = np.sin(2 * np.pi * mois_num / 12)
    df["month_cos"] = np.cos(2 * np.pi * mois_num / 12)
    return df


def calculer_taux_retard_carrier(
    X_train: pd.DataFrame,
    X_test: pd.DataFrame,
    y_train: pd.Series,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, float]:
    """
    Taux de retard historique par carrier, calculé UNIQUEMENT sur le train
    pour éviter tout data leakage.
    Les carriers inconnus dans le test reçoivent le taux global du train.
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


# ═══════════════════════════════════════════════════════════════════════════
# PRÉPARATION DES DONNÉES
# ═══════════════════════════════════════════════════════════════════════════

def preparer_donnees(
    df: pd.DataFrame | None = None,
    proportion_test: float = 0.2,
) -> tuple:
    """
    Split ALÉATOIRE STRATIFIÉ : la proportion de retards est identique
    dans le train et le test (stratify=y).
    Identique au Random Forest pour permettre une comparaison équitable.

    Returns
    -------
    X_train, X_test, y_train, y_test, taux_par_carrier, taux_global
    """
    if df is None:
        df = get_all_shipments()

    # Garder uniquement les lignes avec is_delayed connu
    df_ml = df[df["is_delayed"].notna()].copy()

    # Feature engineering
    df_ml = extraire_frequency_num(df_ml)
    df_ml = extraire_month_cyclique(df_ml)
    

    # ── AJOUT : enrichissement météo ──
    print("\nEnrichissement météo en cours...")
    df_ml = enrich_dataset_with_weather(df_ml)  # ajoute les 8 colonnes météo
    print("Météo enrichie.")

    y = df_ml["is_delayed"].astype(int)
    features_brutes = [f for f in TOUTES_FEATURES if f != "carrier_taux_retard"]
    X = df_ml[features_brutes].copy() 
    features_brutes = [
        "transit_time", "frequency_num", "volume_ratio_allocated_booked",
        "volume_booked", "confirmed_volume",
        "month_sin", "month_cos",
        "carrier", "port_chargement", "port_dechargement",
        "pays_destination",
        # features météo
        "etd_precipitation_mm", "etd_wind_speed_kmh",
        "etd_temperature_max",  "etd_weather_code",
        "eta_precipitation_mm", "eta_wind_speed_kmh",
        "eta_temperature_max",  "eta_weather_code",
    ]
    X = df_ml[features_brutes].copy()

    # Split stratifié (identique au Random Forest)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=proportion_test,
        random_state=42,
        stratify=y,
    )

    # Taux retard carrier (après le split, sur train uniquement)
    X_train, X_test, taux_par_carrier, taux_global = calculer_taux_retard_carrier(
        X_train, X_test, y_train
    )

    print(f"\nDataset ML     : {len(df_ml)} shipments")
    print(f"En retard      : {y.sum()} ({y.mean()*100:.1f}%)")
    print(f"À l'heure      : {(y == 0).sum()} ({(1 - y.mean())*100:.1f}%)")
    print(f"Train set      : {len(X_train)} lignes")
    print(f"Test set       : {len(X_test)} lignes")
    print(f"Features       : {TOUTES_FEATURES}")

    return X_train, X_test, y_train, y_test, taux_par_carrier, taux_global


# ═══════════════════════════════════════════════════════════════════════════
# CONSTRUCTION DU PIPELINE
# ═══════════════════════════════════════════════════════════════════════════

def construire_pipeline_stacking() -> Pipeline:

    estimateurs_base = [
        (
            "lgbm",
            LGBMClassifier(
                objective="binary",
                class_weight="balanced",
                random_state=42,
                n_jobs=-1,
                verbose=-1,
            ),
        ),
        (
            "xgb",
            XGBClassifier(
                objective="binary:logistic",
                eval_metric="logloss",
                scale_pos_weight=1,
                random_state=42,
                n_jobs=-1,
                verbosity=0,
            ),
        ),
    ]

    meta_modele = LogisticRegression(
        solver="saga",
        penalty="elasticnet",
        l1_ratio=0.9,
        C=51.4,          # meilleurs params déjà trouvés
        class_weight="balanced",
        max_iter=5000,
        random_state=42,
    )

    stacking = StackingClassifier(
        estimators=estimateurs_base,
        final_estimator=meta_modele,
        cv=5,
        stack_method="predict_proba",
        n_jobs=-1,
    )

    preprocesseur = ColumnTransformer(
        transformers=[
            (
                "num",
                SimpleImputer(strategy="median"),
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

    pipeline = Pipeline(steps=[
        ("preprocesseur", preprocesseur),
        ("modele",        stacking),
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
    """
    Recherche aléatoire d'hyperparamètres avec cross-validation stratifiée
    sur le train uniquement. Métrique cible : F1 (classe 'En retard').

    Paramètres explorés :
      - C         : force de régularisation inverse (grand C = peu régularisé)
      - l1_ratio  : proportion L1 dans ElasticNet (0 = Ridge, 1 = Lasso)
    """
    pipeline_base = construire_pipeline_stacking()

    espace_recherche = {
        "modele__C":        loguniform(1e-3, 1e2),
        "modele__l1_ratio": [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0],
    }

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    recherche = RandomizedSearchCV(
        estimator=pipeline_base,
        param_distributions=espace_recherche,
        n_iter=n_iter,
        scoring="f1",
        cv=cv,
        random_state=42,
        n_jobs=-1,
        verbose=1,
        error_score=0.0,
    )

    print(f"\n=== TUNING HYPERPARAMÈTRES ({n_iter} combinaisons) ===")
    recherche.fit(X_train, y_train)

    print(f"\nMeilleur F1 CV : {recherche.best_score_*100:.2f}%")
    print("Meilleurs paramètres :")
    for k, v in recherche.best_params_.items():
        print(f"  {k:35s} : {v}")

    return recherche.best_estimator_, recherche.best_params_, recherche.best_score_


# ═══════════════════════════════════════════════════════════════════════════
# SEUIL DE DÉCISION OPTIMAL
# ═══════════════════════════════════════════════════════════════════════════

def trouver_seuil_optimal(pipeline: Pipeline, X_train: pd.DataFrame, y_train: pd.Series) -> float:
    """
    Trouve le seuil de décision qui maximise le F1 sur le train.
    Ce seuil remplace le 0.50 par défaut, souvent sous-optimal avec
    class_weight='balanced' et des classes déséquilibrées.
    Identique à la démarche du Random Forest.
    """
    probas = pipeline.predict_proba(X_train)[:, 1]
    precisions, recalls, seuils = precision_recall_curve(y_train, probas)
    f1s = np.where(
        (precisions + recalls) > 0,
        2 * precisions * recalls / (precisions + recalls),
        0,
    )
    # seuils a une longueur de n-1 par rapport à precisions/recalls
    seuil_optimal = float(seuils[np.argmax(f1s[:-1])])
    print(f"\nSeuil optimal (courbe PR sur train) : {seuil_optimal:.3f}")
    return seuil_optimal


# ═══════════════════════════════════════════════════════════════════════════
# ÉVALUATION
# ═══════════════════════════════════════════════════════════════════════════

def evaluer_modele(
    pipeline: Pipeline,
    X_train: pd.DataFrame,
    X_test: pd.DataFrame,
    y_train: pd.Series,
    y_test: pd.Series,
    seuil: float = 0.50,
) -> dict:
    """
    Évalue le pipeline sur le test set avec le seuil donné.
    Affiche aussi les scores CV sur le train (pour détecter le surapprentissage).
    Structure identique au Random Forest pour faciliter la comparaison.
    """
    # ── Prédictions train ─────────────────────────────────────────────────
    y_train_pred = (pipeline.predict_proba(X_train)[:, 1] >= seuil).astype(int)
    print("\n=== PERFORMANCE TRAIN ===")
    print(f"Accuracy train : {accuracy_score(y_train, y_train_pred)*100:.2f}%")
    print(f"F1 train       : {f1_score(y_train, y_train_pred)*100:.2f}%")

    # ── Prédictions test ──────────────────────────────────────────────────
    y_pred_proba = pipeline.predict_proba(X_test)[:, 1]
    y_pred = (y_pred_proba >= seuil).astype(int)

    acc  = accuracy_score(y_test, y_pred)
    prec = precision_score(y_test, y_pred, zero_division=0)
    rec  = recall_score(y_test, y_pred, zero_division=0)
    f1   = f1_score(y_test, y_pred, zero_division=0)

    print("\n=== PERFORMANCE TEST ===")
    print(f"Accuracy  : {acc*100:.2f}%")
    print(f"Precision : {prec*100:.2f}%")
    print(f"Recall    : {rec*100:.2f}%")
    print(f"F1 Score  : {f1*100:.2f}%")

    cm = confusion_matrix(y_test, y_pred)
    print("\nMatrice de confusion :")
    print(cm)
    print(f"  VN={cm[0][0]}  FP={cm[0][1]}  FN={cm[1][0]}  VP={cm[1][1]}")

    print("\nRapport complet :")
    print(classification_report(y_test, y_pred, target_names=["À l'heure", "En retard"]))

    # ── Cross-validation sur train ────────────────────────────────────────
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores_cv = cross_val_score(pipeline, X_train, y_train, cv=cv, scoring="f1")
    print(f"CV F1 (train) : {scores_cv.mean()*100:.2f}% (+/- {scores_cv.std()*100:.2f}%)")
    print(f"Écart CV/test : {(scores_cv.mean() - f1)*100:+.2f} pts")

    return {
        "accuracy":   round(acc  * 100, 2),
        "precision":  round(prec * 100, 2),
        "recall":     round(rec  * 100, 2),
        "f1":         round(f1   * 100, 2),
        "cv_f1_mean": round(scores_cv.mean() * 100, 2),
        "cv_f1_std":  round(scores_cv.std()  * 100, 2),
    }


# ═══════════════════════════════════════════════════════════════════════════
# IMPORTANCE DES FEATURES (COEFFICIENTS)
# ═══════════════════════════════════════════════════════════════════════════

def afficher_importance_features(pipeline: Pipeline, top_n: int = 20) -> None:
    print("\n=== STACKING : pas d'importance globale unique ===")
    print("Le méta-modèle (Régression Logistique) combine LightGBM + XGBoost.")
    print("Consulte les coefficients du méta-modèle :")
    meta = pipeline.named_steps["modele"].final_estimator_
    print(f"  Coef LightGBM : {meta.coef_[0][0]:.4f}")
    print(f"  Coef XGBoost  : {meta.coef_[0][1]:.4f}")


# ═══════════════════════════════════════════════════════════════════════════
# SAUVEGARDE
# ═══════════════════════════════════════════════════════════════════════════

def sauvegarder_modele(
    pipeline: Pipeline,
    taux_par_carrier: pd.Series,
    taux_global: float,
    seuil_decision: float,
) -> None:
    """
    Sauvegarde le pipeline, les taux carrier ET le seuil de décision optimal.
    Le seuil est inclus dans le pickle pour garantir la cohérence entre
    l'entraînement et la prédiction en production.
    """
    joblib.dump(
        {
            "pipeline":         pipeline,
            "taux_par_carrier": taux_par_carrier,
            "taux_global":      taux_global,
            "seuil_decision":   seuil_decision,
        },
        MODEL_PATH,
    )
    print(f"\n✓ Modèle sauvegardé : {MODEL_PATH}")
    print(f"  Seuil de décision sauvegardé : {seuil_decision:.3f}")


# ═══════════════════════════════════════════════════════════════════════════
# CHARGEMENT ET PRÉDICTION (utilisé par predictor.py)
# ═══════════════════════════════════════════════════════════════════════════

def charger_modele() -> tuple:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Modèle introuvable : {MODEL_PATH}\n"
            "Lancez d'abord : python -m engine.Regression_logistique"
        )
    contenu = joblib.load(MODEL_PATH)
    seuil   = contenu.get("seuil_decision", 0.50)
    return contenu["pipeline"], contenu["taux_par_carrier"], contenu["taux_global"], seuil


def predire_retard(nouveau_shipment: dict) -> dict:
    """
    Prédit le retard d'un shipment à partir d'un dictionnaire brut.
    Utilisé par predictor.py et l'API Flask.
    Interface identique au Random Forest pour un remplacement transparent.
    """
    pipeline, taux_par_carrier, taux_global, seuil_decision = charger_modele()

    # ── Reconstruction des features ───────────────────────────────────────
    frequency_str   = str(nouveau_shipment.get("frequency", ""))
    frequency_match = pd.Series([frequency_str]).str.extract(r"(\d+)").iloc[0, 0]
    frequency_num   = float(frequency_match) if pd.notna(frequency_match) else np.nan

    mois_texte = nouveau_shipment.get("month")
    mois_num   = pd.to_datetime(pd.Series([mois_texte]), format="%B %y", errors="coerce").dt.month.iloc[0]
    month_sin  = float(np.sin(2 * np.pi * mois_num / 12)) if pd.notna(mois_num) else np.nan
    month_cos  = float(np.cos(2 * np.pi * mois_num / 12)) if pd.notna(mois_num) else np.nan

    carrier      = nouveau_shipment.get("carrier", "") or ""
    carrier_taux = float(taux_par_carrier.get(carrier, taux_global))

    vol_booked    = float(nouveau_shipment.get("volume_booked") or 0)
    vol_confirmed = float(nouveau_shipment.get("confirmed_volume") or 0)
    volume_ratio  = (
        nouveau_shipment.get("volume_ratio_allocated_booked")
        or (vol_confirmed / vol_booked if vol_booked > 0 else np.nan)
    )

      # ── AJOUT : features météo temps réel ──
    meteo = get_weather_for_prediction(
        port_chargement=nouveau_shipment.get("port_chargement", ""),
        port_dechargement=nouveau_shipment.get("port_dechargement", ""),
        etd=str(nouveau_shipment.get("etd", "")),
        eta=str(nouveau_shipment.get("eta", "")),
    )

    X_nouveau = pd.DataFrame([{
        "transit_time":                  nouveau_shipment.get("transit_time", np.nan),
        "frequency_num":                 frequency_num,
        "volume_ratio_allocated_booked": volume_ratio,
        "volume_booked":                 vol_booked or np.nan,
        "confirmed_volume":              vol_confirmed or np.nan,
        "carrier_taux_retard":           carrier_taux,
        "month_sin":                     month_sin,
        "month_cos":                     month_cos,
        "carrier":                       carrier,
        "port_chargement":               nouveau_shipment.get("port_chargement") or np.nan,
        "port_dechargement":             nouveau_shipment.get("port_dechargement") or np.nan,
        "pays_destination":              nouveau_shipment.get("pays_destination") or np.nan,
        # ── météo ──
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
    }


# ═══════════════════════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  ENTRAÎNEMENT : RÉGRESSION LOGISTIQUE — PRÉDICTION DE RETARD")
    print("  Split aléatoire stratifié 80/20")
    print("=" * 60)

    # 1. Chargement et préparation
    df_raw = get_all_shipments()
    X_train, X_test, y_train, y_test, taux_par_carrier, taux_global = preparer_donnees(df_raw)

    # 2. Tuning hyperparamètres (50 itérations)
    pipeline, best_params, best_cv_score = tuner_hyperparametres(X_train, y_train, n_iter=50)

    # 3. Seuil de décision optimal
    seuil_optimal = trouver_seuil_optimal(pipeline, X_train, y_train)

    # 4. Évaluation complète sur le test
    metriques = evaluer_modele(pipeline, X_train, X_test, y_train, y_test, seuil=seuil_optimal)

    # 5. Coefficients des features
    afficher_importance_features(pipeline, top_n=20)

    # 6. Sauvegarde (pipeline + taux carrier + seuil)
    sauvegarder_modele(pipeline, taux_par_carrier, taux_global, seuil_optimal)

    print("\n" + "=" * 60)
    print(f"  RÉSUMÉ FINAL")
    print(f"  Accuracy  : {metriques['accuracy']}%")
    print(f"  Precision : {metriques['precision']}%")
    print(f"  Recall    : {metriques['recall']}%")
    print(f"  F1 Score  : {metriques['f1']}%")
    print(f"  CV F1     : {metriques['cv_f1_mean']}% (+/- {metriques['cv_f1_std']}%)")
    print("=" * 60)

    print("\n=== TEST DE PRÉDICTION SUR UN EXEMPLE ===")
    exemple = {
        "transit_time": 10, "frequency": "7j", "month": "September 25",
        "volume_booked": 1000, "confirmed_volume": 950,
        "carrier": "Grimaldi Lines", "port_chargement": "Tanger Med",
        "port_dechargement": "Civitavecchia", "pays_destination": "Italy",  "etd": "2025-09-15",   
        "eta": "2025-09-25",
    }
    resultat = predire_retard(exemple)
    print(f"Shipment test -> {resultat['label']} (probabilité : {resultat['probabilite_retard']}%, risque : {resultat['niveau_risque']})")
    