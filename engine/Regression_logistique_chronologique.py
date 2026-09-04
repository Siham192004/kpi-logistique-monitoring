"""
Regression_logistique_chrono_smote.py
======================================
Modèle de prédiction de retard : RÉGRESSION LOGISTIQUE
Meilleur des deux mondes :
  ✓ Split CHRONOLOGIQUE  → évaluation temporellement honnête (train=passé, test=futur)
  ✓ SMOTE               → rééquilibrage classe minoritaire sur fold train uniquement
  ✓ TargetEncoder       → encodage catégoriel sans data leakage (recalculé à chaque pli CV)

Architecture pipeline (imblearn.Pipeline, 5 étapes plates) :
  1. TargetEncoder  — encode carrier, ports, pays par taux de retard historique
  2. SimpleImputer  — imputation médiane
  3. StandardScaler — normalisation z-score
  4. SMOTE          — suréchantillonnage sur fold train UNIQUEMENT
  5. LogisticRegression (ElasticNet, solver=saga)

Features (11) :
  transit_time, frequency_num, volume_ratio_allocated_booked,
  volume_booked, confirmed_volume, month_sin, month_cos,
  carrier, port_chargement, port_dechargement, pays_destination

Variable cible : is_delayed (0 = à l'heure, 1 = en retard)

Exclusions (data leakage) :
  eta_deviation, etd_deviation, transit_time_reel, volume_ratio_loaded,
  ATD/ATA/ETA bruts, niveau_retard, incoterm, carrier_taux_retard
  (ce dernier était calculé hors pipeline → risque de leakage chronologique)
"""

import warnings
import logging
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import joblib

from category_encoders import TargetEncoder
from scipy.stats import loguniform
from imblearn.over_sampling import SMOTE
from imblearn.pipeline import Pipeline as ImbPipeline
from sklearn.linear_model import LogisticRegression
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score, classification_report, confusion_matrix,
    f1_score, log_loss, jaccard_score,
    precision_recall_curve, precision_score, recall_score,
)
from sklearn.model_selection import (
    RandomizedSearchCV, StratifiedKFold, cross_val_score,
)
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ── Chemins ───────────────────────────────────────────────────────────────────
DB_PATH    = Path("data/Logistique.db")
MODEL_PATH = Path("models/regression_logistique.pkl")
MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)

# ── Features ──────────────────────────────────────────────────────────────────
FEATURES_CAT = [
    "carrier",
    "port_chargement",
    "port_dechargement",
    "pays_destination",
]

FEATURES_NUM = [
    "transit_time",
    "frequency_num",
    "volume_ratio_allocated_booked",
    "volume_booked",
    "confirmed_volume",
    "month_sin",
    "month_cos",
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
    """
    'July 24' → month_sin / month_cos
    Encodage cyclique : décembre et janvier restent proches.
    """
    df = df.copy()
    mois_num = pd.to_datetime(
        df["month"], format="%B %y", errors="coerce"
    ).dt.month
    df["month_sin"] = np.sin(2 * np.pi * mois_num / 12)
    df["month_cos"] = np.cos(2 * np.pi * mois_num / 12)
    return df


# ═══════════════════════════════════════════════════════════════════════════
# PRÉPARATION DES DONNÉES — SPLIT CHRONOLOGIQUE
# ═══════════════════════════════════════════════════════════════════════════

def preparer_donnees(
    df: pd.DataFrame | None = None,
    proportion_test: float = 0.2,
) -> tuple:
    """
    Split CHRONOLOGIQUE (80% passé → train, 20% futur → test).

    Pourquoi chronologique ?
      En production, le modèle prédit toujours le futur depuis le passé.
      Un split aléatoire laisse "fuiter" des données futures dans le train,
      ce qui surestime les métriques sans que ce soit visible.

    Le TargetEncoder et SMOTE restent dans le pipeline imblearn :
      → zéro data leakage même avec le split chronologique.
    """
    if df is None:
        df = get_all_shipments()

    df_ml = df[df["is_delayed"].notna()].copy()
    df_ml = extraire_frequency_num(df_ml)
    df_ml = extraire_month_cyclique(df_ml)

    # ── Tri chronologique ─────────────────────────────────────────────────
    df_ml["etd"] = pd.to_datetime(df_ml["etd"], errors="coerce")
    df_ml = df_ml.sort_values("etd").reset_index(drop=True)

    y = df_ml["is_delayed"].astype(int)
    X = df_ml[TOUTES_FEATURES].copy()

    # ── Coupure temporelle ────────────────────────────────────────────────
    n_total = len(df_ml)
    n_train = int(n_total * (1 - proportion_test))

    X_train = X.iloc[:n_train].copy()
    X_test  = X.iloc[n_train:].copy()
    y_train = y.iloc[:n_train].copy()
    y_test  = y.iloc[n_train:].copy()

    date_train_min = df_ml.iloc[:n_train]["etd"].min().date()
    date_train_max = df_ml.iloc[:n_train]["etd"].max().date()
    date_test_min  = df_ml.iloc[n_train:]["etd"].min().date()
    date_test_max  = df_ml.iloc[n_train:]["etd"].max().date()

    print(f"\nDataset ML  : {len(df_ml)} shipments")
    print(f"En retard   : {y.sum()} ({y.mean()*100:.1f}%)")
    print(f"À l'heure   : {(y == 0).sum()} ({(1-y.mean())*100:.1f}%)")
    print(f"Période train : {date_train_min} → {date_train_max}")
    print(f"Période test  : {date_test_min}  → {date_test_max}")
    print(f"Train set   : {len(X_train)} lignes (plus anciens)")
    print(f"Test set    : {len(X_test)} lignes (plus récents, jamais vus)")
    print(f"Features    : {TOUTES_FEATURES}")

    return X_train, X_test, y_train, y_test


# ═══════════════════════════════════════════════════════════════════════════
# CONSTRUCTION DU PIPELINE
# ═══════════════════════════════════════════════════════════════════════════

def construire_pipeline(
    C: float = 1.0,
    l1_ratio: float = 0.0,
    sampling_strategy: float = 0.5,
) -> ImbPipeline:
    """
    Pipeline imblearn complet — 5 étapes plates (pas de sklearn.Pipeline imbriqué
    car imblearn.Pipeline ne les accepte pas en étape intermédiaire).

    Étape 1 — TargetEncoder :
      Encode les 4 variables catégorielles par leur taux de retard historique.
      Recalculé sur le fold train à chaque pli de CV → zéro data leakage.
      Modalités inconnues → taux global (handle_unknown='value').

    Étape 2 — SimpleImputer (médiane) :
      Gère les NaN résiduels après encoding.

    Étape 3 — StandardScaler :
      Indispensable pour la régression logistique (sensible à l'échelle).

    Étape 4 — SMOTE :
      Suréchantillonnage de la classe minoritaire (retards) sur le fold train.
      sampling_strategy=0.5 → ratio minoritaire/majoritaire = 1:2 après SMOTE.

    Étape 5 — LogisticRegression (ElasticNet) :
      solver=saga → seul solver compatible ElasticNet.
      class_weight=None → SMOTE gère déjà le déséquilibre.
    """
    return ImbPipeline(steps=[
        (
            "target_encoder",
            TargetEncoder(
                cols=FEATURES_CAT,
                handle_unknown="value",
                handle_missing="value",
                min_samples_leaf=20,
                smoothing=1.0,
            ),
        ),
        (
            "imputation",
            SimpleImputer(strategy="median"),
        ),
        (
            "normalisation",
            StandardScaler(),
        ),
        (
            "smote",
            SMOTE(
                sampling_strategy=sampling_strategy,
                random_state=42,
                k_neighbors=5,
            ),
        ),
        (
            "modele",
            LogisticRegression(
                solver="saga",
                penalty="elasticnet",
                l1_ratio=l1_ratio,
                C=C,
                class_weight=None,   # SMOTE gère le déséquilibre
                max_iter=5000,
                random_state=42,
            ),
        ),
    ])


# ═══════════════════════════════════════════════════════════════════════════
# TUNING DES HYPERPARAMÈTRES
# ═══════════════════════════════════════════════════════════════════════════

def tuner_hyperparametres(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    n_iter: int = 50,
) -> tuple:
    """
    Recherche aléatoire sur 3 hyperparamètres.
    La CV stratifiée est appliquée sur le train uniquement (split chronologique
    déjà réalisé en amont — le test n'est jamais vu ici).

    Paramètres explorés :
      modele__C               : force de régularisation inverse
      modele__l1_ratio        : proportion L1 dans ElasticNet (0=Ridge, 1=Lasso)
      smote__sampling_strategy: ratio après SMOTE (0.3→0.7)
    """
    pipeline_base = construire_pipeline()

    espace_recherche = {
        "modele__C":                loguniform(0.5, 1e3),
        "modele__l1_ratio":         [0.0, 0.1, 0.2, 0.3, 0.5],
        "smote__sampling_strategy": [0.3, 0.4, 0.5, 0.6, 0.7],
    }

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    recherche = RandomizedSearchCV(
        estimator=pipeline_base,
        param_distributions=espace_recherche,
        n_iter=n_iter,
        scoring="f1_macro",
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
) -> tuple:
    """
    Trouve le seuil qui maximise le F1 macro sur les données train.
    Ce seuil remplace le 0.50 par défaut, souvent sous-optimal avec SMOTE.
    """
    probas = pipeline.predict_proba(X_train)[:, 1]
    precisions, recalls, seuils = precision_recall_curve(y_train, probas)

    f1s = np.where(
        (precisions + recalls) > 0,
        2 * precisions * recalls / (precisions + recalls),
        0,
    )
    idx_optimal   = np.argmax(f1s[:-1])
    seuil_optimal = float(seuils[idx_optimal])
    f1_au_seuil   = float(f1s[idx_optimal])

    print(f"\nSeuil optimal (courbe PR sur train) : {seuil_optimal:.3f}")
    print(f"F1 au seuil optimal                 : {f1_au_seuil*100:.2f}%")
    return seuil_optimal, f1_au_seuil


# ═══════════════════════════════════════════════════════════════════════════
# ÉVALUATION COMPLÈTE
# ═══════════════════════════════════════════════════════════════════════════

def evaluer_modele(
    pipeline: ImbPipeline,
    X_train: pd.DataFrame,
    X_test: pd.DataFrame,
    y_train: pd.Series,
    y_test: pd.Series,
    seuil: float = 0.50,
) -> dict:
    # ── Performance train ─────────────────────────────────────────────────
    y_train_proba = pipeline.predict_proba(X_train)[:, 1]
    y_train_pred  = (y_train_proba >= seuil).astype(int)

    print("\n=== PERFORMANCE TRAIN ===")
    print(f"Accuracy train  : {accuracy_score(y_train, y_train_pred)*100:.2f}%")
    print(f"F1 macro train  : {f1_score(y_train, y_train_pred, average='macro')*100:.2f}%")
    print(f"Log Loss train  : {log_loss(y_train, y_train_proba):.4f}")

    # ── Performance test (données FUTURES jamais vues) ────────────────────
    y_pred_proba = pipeline.predict_proba(X_test)[:, 1]
    y_pred       = (y_pred_proba >= seuil).astype(int)

    acc      = accuracy_score(y_test, y_pred)
    f1_mac   = f1_score(y_test, y_pred, average="macro")
    f1_ret   = f1_score(y_test, y_pred, pos_label=1, zero_division=0)
    f1_heure = f1_score(y_test, y_pred, pos_label=0, zero_division=0)
    prec     = precision_score(y_test, y_pred, zero_division=0)
    rec      = recall_score(y_test, y_pred, zero_division=0)
    ll       = log_loss(y_test, y_pred_proba)
    jacc     = jaccard_score(y_test, y_pred, pos_label=1, zero_division=0)

    print("\n=== PERFORMANCE TEST (données futures) ===")
    print(f"Accuracy        : {acc*100:.2f}%")
    print(f"F1 macro        : {f1_mac*100:.2f}%")
    print(f"F1 'En retard'  : {f1_ret*100:.2f}%")
    print(f"F1 'À l'heure' : {f1_heure*100:.2f}%")
    print(f"Precision       : {prec*100:.2f}%")
    print(f"Recall          : {rec*100:.2f}%")
    print(f"Log Loss        : {ll:.4f}")
    print(f"Jaccard Index   : {jacc:.4f}")

    cm = confusion_matrix(y_test, y_pred)
    print("\nMatrice de confusion :")
    print(cm)
    print(f"  VN={cm[0][0]}  FP={cm[0][1]}  FN={cm[1][0]}  VP={cm[1][1]}")
    print(f"  → {cm[1][1]} retards détectés sur {cm[1][0]+cm[1][1]} réels")

    print("\nRapport complet :")
    print(classification_report(
        y_test, y_pred,
        target_names=["À l'heure", "En retard"]
    ))

    # ── Cross-validation sur train ────────────────────────────────────────
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores_cv = cross_val_score(
        pipeline, X_train, y_train,
        cv=cv, scoring="f1_macro"
    )
    print(f"CV F1 macro (5 plis) : {scores_cv.mean()*100:.2f}%"
          f" (+/- {scores_cv.std()*100:.2f}%)")
    print(f"Écart CV/test        : {(scores_cv.mean()-f1_mac)*100:+.2f} pts")

    # Interprétation Log Loss
    if ll < 0.35:
        print(f"\nLog Loss {ll:.4f} : Très bon — probabilités bien calibrées")
    elif ll < 0.50:
        print(f"\nLog Loss {ll:.4f} : Bon — probabilités acceptables")
    else:
        print(f"\nLog Loss {ll:.4f} : À améliorer")

    # Interprétation Jaccard
    if jacc > 0.50:
        print(f"Jaccard {jacc:.4f}  : Bon — fort chevauchement prédictions/réalité")
    elif jacc > 0.35:
        print(f"Jaccard {jacc:.4f}  : Acceptable")
    else:
        print(f"Jaccard {jacc:.4f}  : Faible chevauchement")

    return {
        "accuracy":      round(acc    * 100, 2),
        "f1_macro":      round(f1_mac * 100, 2),
        "f1_retard":     round(f1_ret * 100, 2),
        "f1_heure":      round(f1_heure * 100, 2),
        "precision":     round(prec   * 100, 2),
        "recall":        round(rec    * 100, 2),
        "log_loss":      round(ll,    4),
        "jaccard":       round(jacc,  4),
        "cv_f1_mean":    round(scores_cv.mean() * 100, 2),
        "cv_f1_std":     round(scores_cv.std()  * 100, 2),
        "ecart_cv_test": round((scores_cv.mean() - f1_mac) * 100, 2),
    }


# ═══════════════════════════════════════════════════════════════════════════
# IMPORTANCE DES FEATURES (COEFFICIENTS)
# ═══════════════════════════════════════════════════════════════════════════

def afficher_importance_features(
    pipeline: ImbPipeline,
    top_n: int = 11,
) -> pd.DataFrame:
    """
    Après TargetEncoder, toutes les features sont numériques → coefficients
    directement accessibles. Pas de OneHotEncoder ici, donc noms = TOUTES_FEATURES.
    """
    try:
        coefficients = pipeline.named_steps["modele"].coef_[0]
        noms = TOUTES_FEATURES[:len(coefficients)]

        df_coef = (
            pd.DataFrame({"feature": noms, "coefficient": coefficients})
            .assign(impact_abs=lambda d: d["coefficient"].abs())
            .sort_values("impact_abs", ascending=False)
            .drop(columns="impact_abs")
            .reset_index(drop=True)
        )

        non_nuls = (df_coef["coefficient"] != 0).sum()
        print(f"\n=== TOP {top_n} FEATURES (coefficients, triés par impact absolu) ===")
        print("(positif = augmente le risque de retard, négatif = le diminue)")
        print(df_coef.head(top_n).to_string(index=False))
        print(f"\n→ {non_nuls}/{len(df_coef)} features avec coefficient non nul")
        return df_coef
    except Exception as e:
        print(f"Importance features non disponible : {e}")
        return pd.DataFrame()


# ═══════════════════════════════════════════════════════════════════════════
# SAUVEGARDE
# ═══════════════════════════════════════════════════════════════════════════

def sauvegarder_modele(
    pipeline: ImbPipeline,
    taux_global: float,
) -> None:
    """
    Sauvegarde le pipeline complet.
    Le TargetEncoder est inclus dans le pipeline → pas besoin de sauvegarder
    taux_par_carrier séparément (contrairement à la version chronologique v1).
    Le seuil est None en production : les niveaux de risque sont calculés
    directement depuis la probabilité brute.
    """
    joblib.dump(
        {
            "pipeline":       pipeline,
            "seuil_decision": None,
            "taux_global":    taux_global,
        },
        MODEL_PATH,
    )
    print(f"\nModèle sauvegardé : {MODEL_PATH}")
    print(f"  Taux global       : {taux_global*100:.2f}%")
    print(f"  TargetEncoder     : inclus dans le pipeline sauvegardé")
    print(f"  Niveaux de risque : basés sur probabilité brute (< 30% / 30–63% / ≥ 63%)")


# ═══════════════════════════════════════════════════════════════════════════
# CHARGEMENT ET PRÉDICTION
# ═══════════════════════════════════════════════════════════════════════════

def charger_modele() -> tuple:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Modèle introuvable : {MODEL_PATH}\n"
            "Lancez d'abord : python -m engine.Regression_logistique_chrono_smote"
        )
    contenu = joblib.load(MODEL_PATH)
    return (
        contenu["pipeline"],
        contenu["seuil_decision"],
        contenu["taux_global"],
    )


def _classifier_niveau_risque(probabilite: float) -> tuple[str, str]:
    if probabilite < 0.30:
        return "Faible", "Risque faible"
    elif probabilite < 0.639:
        return "Modéré", "Risque modéré"
    else:
        return "Élevé", "Risque élevé"


def predire_retard(nouveau_shipment: dict) -> dict:
    """
    Prédit le risque de retard d'un shipment.
    Le TargetEncoder dans le pipeline gère automatiquement les carriers
    et ports inconnus (→ taux global).
    """
    pipeline, _, taux_global = charger_modele()

    # ── Feature engineering identique à l'entraînement ───────────────────
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

    probabilite   = float(pipeline.predict_proba(X_nouveau)[0][1])
    niveau_risque, label = _classifier_niveau_risque(probabilite)

    return {
        "probabilite_retard": round(probabilite * 100, 1),
        "niveau_risque":      niveau_risque,
        "label":              label,
        "prediction":         1 if niveau_risque == "Élevé" else 0,
        "taux_global":        round(taux_global * 100, 1),
    }


# ═══════════════════════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("  ENTRAÎNEMENT : RÉGRESSION LOGISTIQUE")
    print("  Split CHRONOLOGIQUE + SMOTE + TargetEncoder")
    print("  → Évaluation temporellement honnête + bonnes métriques")
    print("=" * 70)

    # 1. Chargement et préparation (split chronologique)
    df_raw = get_all_shipments()
    X_train, X_test, y_train, y_test = preparer_donnees(df_raw)

    taux_global = float(y_train.mean())

    # 2. Tuning hyperparamètres (CV sur train uniquement)
    pipeline, best_params, best_cv_score = tuner_hyperparametres(
        X_train, y_train, n_iter=50
    )

    # 3. Seuil de décision optimal (sur train)
    seuil_optimal, _ = trouver_seuil_optimal(pipeline, X_train, y_train)

    # 4. Évaluation complète (test = données futures)
    metriques = evaluer_modele(
        pipeline, X_train, X_test, y_train, y_test,
        seuil=seuil_optimal
    )

    # 5. Importance des features
    afficher_importance_features(pipeline, top_n=11)

    # 6. Sauvegarde
    sauvegarder_modele(pipeline, taux_global)

    print("\n" + "=" * 70)
    print("  RÉSUMÉ FINAL")
    print(f"  Accuracy      : {metriques['accuracy']}%")
    print(f"  F1 macro      : {metriques['f1_macro']}%")
    print(f"  F1 En retard  : {metriques['f1_retard']}%")
    print(f"  F1 À l'heure  : {metriques['f1_heure']}%")
    print(f"  Precision     : {metriques['precision']}%")
    print(f"  Recall        : {metriques['recall']}%")
    print(f"  Log Loss      : {metriques['log_loss']}")
    print(f"  Jaccard Index : {metriques['jaccard']}")
    print(f"  CV F1 macro   : {metriques['cv_f1_mean']}%"
          f" (+/- {metriques['cv_f1_std']}%)")
    print(f"  Écart CV/test : {metriques['ecart_cv_test']} pts")
    print("=" * 70)

    # 7. Test de prédiction
    print("\n=== TEST DE PRÉDICTION SUR UN EXEMPLE ===")
    exemple = {
        "transit_time": 10, "frequency": "7j", "month": "September 25",
        "volume_booked": 1000, "confirmed_volume": 950,
        "carrier": "GRIMALDI LINES",
        "port_chargement": "Tanger Med",
        "port_dechargement": "Civitavecchia",
        "pays_destination": "Italy",
    }
    resultat = predire_retard(exemple)
    print(f"Shipment test -> {resultat['label']}"
          f" (probabilité : {resultat['probabilite_retard']}%,"
          f" risque : {resultat['niveau_risque']})")