"""
Random_forest.py — Modèle de prédiction de retard : RANDOM FOREST
Source de données : base SQLite Logistique.db (table shipment + vessel)

Même démarche que la régression logistique :
  ✓ Split ALÉATOIRE STRATIFIÉ 80/20 (même proportion de retards dans train et test)
  ✓ SMOTE dans le pipeline (fold train uniquement)
  ✓ CV n°1 (RandomizedSearchCV)  → choisit les hyperparamètres
  ✓ CV n°2 (cross_val_predict)   → choisit le seuil de décision (F1 classe 'En retard')
  ✓ Test                         → mesure finale, jamais utilisé pour choisir
  ✓ Un seul F1 : celui de la classe 'En retard'

Features numériques (7) :
    transit_time, frequency_num, volume_ratio_allocated_booked,
    volume_booked, confirmed_volume, month_sin, month_cos
Features catégorielles (4) :
    carrier, port_chargement, port_dechargement, pays_destination
Variable cible : is_delayed (0 = à l'heure, 1 = en retard)

Exclusions (data leakage) :
    eta_deviation, etd_deviation, transit_time_reel, volume_ratio_loaded,
    ATD/ATA/ETA bruts, niveau_retard, incoterm,
    carrier_taux_retard (calculé hors pipeline → fuite pendant la CV)
"""

import warnings
import logging
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import joblib

from scipy.stats import randint
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score, confusion_matrix, f1_score, jaccard_score, log_loss,
    precision_recall_curve, precision_score, recall_score,
)
from sklearn.model_selection import (
    RandomizedSearchCV, StratifiedKFold, cross_val_predict, train_test_split,
)
from sklearn.preprocessing import OneHotEncoder
from imblearn.over_sampling import SMOTE
from imblearn.pipeline import Pipeline as ImbPipeline

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ── Chemins ───────────────────────────────────────────────────────────────────
DB_PATH    = Path("data/Logistique.db")
MODEL_PATH = Path("models/random_forest.pkl")
MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)

# ── Features ──────────────────────────────────────────────────────────────────
FEATURES_NUM = [
    "transit_time",
    "frequency_num",
    "volume_ratio_allocated_booked",
    "volume_booked",
    "confirmed_volume",
    "month_sin",
    "month_cos",
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
    """'7j' → 7.0  |  valeur inconnue → NaN"""
    df = df.copy()
    df["frequency_num"] = (
        df["frequency"].astype(str).str.extract(r"(\d+)").astype(float)
    )
    return df


def extraire_month_cyclique(df: pd.DataFrame) -> pd.DataFrame:
    """'July 24' → month_sin / month_cos (décembre et janvier restent proches)."""
    df = df.copy()
    mois_num = pd.to_datetime(df["month"], format="%B %y", errors="coerce").dt.month
    df["month_sin"] = np.sin(2 * np.pi * mois_num / 12)
    df["month_cos"] = np.cos(2 * np.pi * mois_num / 12)
    return df


# ═══════════════════════════════════════════════════════════════════════════
# PRÉPARATION DES DONNÉES — SPLIT ALÉATOIRE STRATIFIÉ
# ═══════════════════════════════════════════════════════════════════════════

def preparer_donnees(
    df: pd.DataFrame | None = None,
    proportion_test: float = 0.2,
) -> tuple:
    """Split aléatoire stratifié : même proportion de retards dans train et test."""
    if df is None:
        df = get_all_shipments()

    df_ml = df[df["is_delayed"].notna()].copy()
    df_ml = extraire_frequency_num(df_ml)
    df_ml = extraire_month_cyclique(df_ml)

    y = df_ml["is_delayed"].astype(int)
    X = df_ml[TOUTES_FEATURES].copy()

    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=proportion_test,
        random_state=42,
        stratify=y,
    )

    print(f"\nDataset ML    : {len(df_ml)} shipments")
    print(f"En retard     : {y.sum()} ({y.mean()*100:.1f}%)")
    print(f"À l'heure     : {(y == 0).sum()} ({(1 - y.mean())*100:.1f}%)")
    print(f"Train set     : {len(X_train)} lignes")
    print(f"Test set      : {len(X_test)} lignes")
    print(f"Features      : {TOUTES_FEATURES}")

    return X_train, X_test, y_train, y_test


# ═══════════════════════════════════════════════════════════════════════════
# CONSTRUCTION DU PIPELINE
# ═══════════════════════════════════════════════════════════════════════════

def construire_pipeline(
    n_estimators: int = 300,
    max_depth: int | None = 10,
    min_samples_leaf: int = 10,
    min_samples_split: int = 5,
    max_features: str | float = "sqrt",
    sampling_strategy: float = 0.5,
) -> ImbPipeline:
    """
    1. ColumnTransformer : imputation médiane (num) + OneHotEncoder (cat)
    2. SMOTE             : fold train uniquement
    3. RandomForest      : class_weight=None (SMOTE gère déjà le déséquilibre,
                           les deux ensemble compenseraient deux fois)
    """
    preprocesseur = ColumnTransformer(
        transformers=[
            ("num", SimpleImputer(strategy="median"), FEATURES_NUM),
            (
                "cat",
                OneHotEncoder(
                    handle_unknown="ignore",
                    sparse_output=False,
                    min_frequency=5,
                ),
                FEATURES_CAT,
            ),
        ],
        remainder="drop",
    )

    return ImbPipeline(steps=[
        ("preprocesseur", preprocesseur),
        ("smote", SMOTE(
            sampling_strategy=sampling_strategy,
            k_neighbors=5,
            random_state=42,
        )),
        ("modele", RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            min_samples_leaf=min_samples_leaf,
            min_samples_split=min_samples_split,
            max_features=max_features,
            class_weight=None,
            random_state=42,
            n_jobs=-1,
        )),
    ])


# ═══════════════════════════════════════════════════════════════════════════
# CV n°1 : CHOIX DES HYPERPARAMÈTRES
# ═══════════════════════════════════════════════════════════════════════════

def tuner_hyperparametres(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    n_iter: int = 60,
) -> tuple:
    pipeline_base = construire_pipeline()

    espace_recherche = {
        "modele__n_estimators":      randint(100, 500),
        "modele__max_depth":         [4, 6, 8, 10, 12, None],
        "modele__min_samples_leaf":  randint(5, 30),
        "modele__min_samples_split": randint(2, 20),
        "modele__max_features":      ["sqrt", "log2", 0.3],
        "smote__sampling_strategy":  [0.3, 0.4, 0.5, 0.6, 0.7],
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
# CV n°2 : CHOIX DU SEUIL (prédictions out-of-fold)
# ═══════════════════════════════════════════════════════════════════════════

def trouver_seuil_optimal(pipeline, X_train, y_train):
    """
    Probabilités out-of-fold : chaque ligne du train est prédite par un modèle
    qui ne l'a pas vue. Indispensable avec une Random Forest : sur le train
    directement, elle a mémorisé les données et ses probabilités sont trop
    parfaites, donc le seuil serait faussé.
    """
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    probas_oof = cross_val_predict(
        pipeline, X_train, y_train, cv=cv, method="predict_proba"
    )[:, 1]

    precisions, recalls, seuils = precision_recall_curve(y_train, probas_oof)
    f1s = np.where(
        (precisions + recalls) > 0,
        2 * precisions * recalls / (precisions + recalls),
        0,
    )
    idx = np.argmax(f1s[:-1])
    return float(seuils[idx]), float(f1s[idx]), probas_oof


# ═══════════════════════════════════════════════════════════════════════════
# ÉVALUATION
# ═══════════════════════════════════════════════════════════════════════════

def evaluer_modele(
    pipeline: ImbPipeline,
    X_train: pd.DataFrame,
    X_test: pd.DataFrame,
    y_train: pd.Series,
    y_test: pd.Series,
    probas_oof: np.ndarray,
    seuil: float,
) -> dict:
    print(f"\nSeuil de décision utilisé : {seuil:.3f}")

    # ── Train (données déjà vues → optimiste) ─────────────────────────────
    y_train_proba = pipeline.predict_proba(X_train)[:, 1]
    y_train_pred  = (y_train_proba >= seuil).astype(int)
    f1_train      = f1_score(y_train, y_train_pred, zero_division=0)

    print("\n=== PERFORMANCE TRAIN ===")
    print(f"Accuracy train  : {accuracy_score(y_train, y_train_pred)*100:.2f}%")
    print(f"F1 train        : {f1_train*100:.2f}%")
    print(f"Log Loss train  : {log_loss(y_train, y_train_proba):.4f}")

    # ── CV out-of-fold (au seuil choisi) ──────────────────────────────────
    y_oof = (probas_oof >= seuil).astype(int)
    cv_f1 = f1_score(y_train, y_oof, zero_division=0)

    # ── Test (jamais vu) ──────────────────────────────────────────────────
    y_pred_proba = pipeline.predict_proba(X_test)[:, 1]
    y_pred       = (y_pred_proba >= seuil).astype(int)

    acc  = accuracy_score(y_test, y_pred)
    f1   = f1_score(y_test, y_pred, zero_division=0)
    prec = precision_score(y_test, y_pred, zero_division=0)
    rec  = recall_score(y_test, y_pred, zero_division=0)
    ll   = log_loss(y_test, y_pred_proba)
    jacc = jaccard_score(y_test, y_pred, zero_division=0)

    print("\n=== PERFORMANCE TEST ===")
    print(f"Accuracy          : {acc*100:.2f}%")
    print(f"F1 score          : {f1*100:.2f}%")
    print(f"Precision         : {prec*100:.2f}%")
    print(f"Recall            : {rec*100:.2f}%")
    print(f"Log Loss          : {ll:.4f}")
    print(f"Jaccard Index     : {jacc:.4f}")

    cm = confusion_matrix(y_test, y_pred)
    print("\nMatrice de confusion :")
    print(cm)
    print(f"  VN={cm[0][0]}  FP={cm[0][1]}  FN={cm[1][0]}  VP={cm[1][1]}")
    print(f"  → {cm[1][1]} retards détectés sur {cm[1][0] + cm[1][1]} réels")

    print("\n=== CONTRÔLE SURAPPRENTISSAGE ===")
    print(f"F1 train                       : {f1_train*100:.2f}%")
    print(f"F1 CV (out-of-fold, au seuil)  : {cv_f1*100:.2f}%")
    print(f"F1 test                        : {f1*100:.2f}%")
    print(f"Écart train − CV : {(f1_train - cv_f1)*100:+.2f} pts (surapprentissage si grand)")
    print(f"Écart CV − test  : {(cv_f1 - f1)*100:+.2f} pts")

    return {
        "accuracy":      round(acc * 100, 2),
        "f1":            round(f1 * 100, 2),
        "precision":     round(prec * 100, 2),
        "recall":        round(rec * 100, 2),
        "log_loss":      round(ll, 4),
        "jaccard":       round(jacc, 4),
        "cv_f1":         round(cv_f1 * 100, 2),
        "ecart_cv_test": round((cv_f1 - f1) * 100, 2),
    }


# ═══════════════════════════════════════════════════════════════════════════
# IMPORTANCE DES FEATURES
# ═══════════════════════════════════════════════════════════════════════════

def afficher_importance_features(pipeline: ImbPipeline, top_n: int = 20) -> pd.DataFrame:
    # Noms réels produits par le préprocesseur → alignement garanti
    noms = [
        n.split("__", 1)[-1]
        for n in pipeline.named_steps["preprocesseur"].get_feature_names_out()
    ]
    importances = pipeline.named_steps["modele"].feature_importances_

    df_imp = (
        pd.DataFrame({"feature": noms, "importance": importances})
        .sort_values("importance", ascending=False)
        .reset_index(drop=True)
    )
    print(f"\n=== TOP {top_n} FEATURES ===")
    print(df_imp.head(top_n).to_string(index=False))
    return df_imp


# ═══════════════════════════════════════════════════════════════════════════
# SAUVEGARDE / CHARGEMENT
# ═══════════════════════════════════════════════════════════════════════════

def sauvegarder_modele(pipeline, taux_global: float, seuil_decision: float) -> None:
    joblib.dump(
        {
            "pipeline":       pipeline,
            "seuil_decision": seuil_decision,
            "taux_global":    taux_global,
        },
        MODEL_PATH,
    )
    print(f"\nModèle sauvegardé : {MODEL_PATH}")
    print(f"  Taux global     : {taux_global*100:.2f}%")
    print(f"  Seuil décision  : {seuil_decision:.3f} (optimisé F1)")


def charger_modele() -> tuple:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Modèle introuvable : {MODEL_PATH}\n"
            "Lancez d'abord : python -m engine.Random_forest"
        )
    contenu = joblib.load(MODEL_PATH)
    return contenu["pipeline"], contenu["seuil_decision"], contenu["taux_global"]


def predire_retard(nouveau_shipment: dict) -> dict:
    """
    Décision binaire : probabilité >= seuil optimal (maximisant le F1
    sur la classe 'En retard', calculé en validation croisée).
    """
    pipeline, seuil_decision, taux_global = charger_modele()

    frequency_str   = str(nouveau_shipment.get("frequency", ""))
    frequency_match = pd.Series([frequency_str]).str.extract(r"(\d+)").iloc[0, 0]
    frequency_num   = float(frequency_match) if pd.notna(frequency_match) else np.nan

    mois_texte = nouveau_shipment.get("month")
    mois_num   = pd.to_datetime(
        pd.Series([mois_texte]), format="%B %y", errors="coerce"
    ).dt.month.iloc[0]
    month_sin  = float(np.sin(2 * np.pi * mois_num / 12)) if pd.notna(mois_num) else np.nan
    month_cos  = float(np.cos(2 * np.pi * mois_num / 12)) if pd.notna(mois_num) else np.nan

    vol_booked    = float(nouveau_shipment.get("volume_booked") or 0) or np.nan
    vol_confirmed = float(nouveau_shipment.get("confirmed_volume") or 0) or np.nan
    volume_ratio  = (
        nouveau_shipment.get("volume_ratio_allocated_booked")
        or (vol_confirmed / vol_booked if (vol_booked and not np.isnan(vol_booked)) else np.nan)
    )

    X_nouveau = pd.DataFrame([{
        "transit_time":                  nouveau_shipment.get("transit_time", np.nan),
        "frequency_num":                 frequency_num,
        "volume_ratio_allocated_booked": volume_ratio,
        "volume_booked":                 vol_booked,
        "confirmed_volume":              vol_confirmed,
        "month_sin":                     month_sin,
        "month_cos":                     month_cos,
        "carrier":           nouveau_shipment.get("carrier")           or np.nan,
        "port_chargement":   nouveau_shipment.get("port_chargement")   or np.nan,
        "port_dechargement": nouveau_shipment.get("port_dechargement") or np.nan,
        "pays_destination":  nouveau_shipment.get("pays_destination")  or np.nan,
    }])

    probabilite = float(pipeline.predict_proba(X_nouveau)[0][1])
    en_retard   = probabilite >= seuil_decision

    return {
        "probabilite_retard": round(probabilite * 100, 1),
        "seuil_decision":     round(seuil_decision * 100, 1),
        "prediction":         int(en_retard),
        "label":              "Retard probable" if en_retard else "À l'heure",
        "taux_global":        round(taux_global * 100, 1),
    }


# ═══════════════════════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("  ENTRAÎNEMENT : RANDOM FOREST + SMOTE")
    print("  Split aléatoire stratifié 80/20 — seuil choisi en CV (out-of-fold)")
    print("=" * 70)

    # 1. Chargement et préparation
    df_raw = get_all_shipments()
    X_train, X_test, y_train, y_test = preparer_donnees(df_raw)
    taux_global = float(y_train.mean())

    # 2. CV n°1 : hyperparamètres
    pipeline, best_params, best_cv_score = tuner_hyperparametres(
        X_train, y_train, n_iter=60
    )

    # 3. CV n°2 : seuil de décision
    seuil_optimal, f1_cv, probas_oof = trouver_seuil_optimal(pipeline, X_train, y_train)
    print(f"\nSeuil optimal : {seuil_optimal:.3f}")

    # 4. Évaluation sur le test
    metriques = evaluer_modele(
        pipeline, X_train, X_test, y_train, y_test,
        probas_oof=probas_oof, seuil=seuil_optimal,
    )

    # 5. Importance des features
    afficher_importance_features(pipeline, top_n=20)

    # 6. Sauvegarde du pipeline et du seuil
    sauvegarder_modele(pipeline, taux_global, seuil_optimal)

    print("\n" + "=" * 70)
    print("  RÉSUMÉ FINAL")
    print(f"  Accuracy      : {metriques['accuracy']}%")
    print(f"  F1            : {metriques['f1']}%")
    print(f"  Precision     : {metriques['precision']}%")
    print(f"  Recall        : {metriques['recall']}%")
    print(f"  Log Loss      : {metriques['log_loss']}")
    print(f"  Jaccard Index : {metriques['jaccard']}")
    print("=" * 70)

    # 7. Test de prédiction (le carrier doit être écrit comme dans la base)
    print("\n=== TEST DE PRÉDICTION SUR UN EXEMPLE ===")
    exemple = {
        "transit_time": 10, "frequency": "7j", "month": "September 25",
        "volume_booked": 1000, "confirmed_volume": 950,
        "carrier": "GRIMALDI LINES",
        "port_chargement": "Tanger Med",
        "port_dechargement": "Civitavecchia",
        "pays_destination": "Italy",
    }
    r = predire_retard(exemple)
    print(f"Shipment test -> {r['label']} "
          f"(probabilité : {r['probabilite_retard']}%, "
          f"seuil : {r['seuil_decision']}%)")