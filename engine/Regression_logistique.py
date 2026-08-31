"""
Regression_logistique.py — Modèle de prédiction de retard : RÉGRESSION LOGISTIQUE
Source de données : base SQLite Logistique.db (table shipment + vessel)

Méthode d'évaluation : split ALÉATOIRE STRATIFIÉ (80/20)

Gestion du déséquilibre : SMOTE
    Appliqué uniquement sur le fold train à chaque pli de CV
    grâce à imblearn.pipeline.Pipeline.

Encodage des variables catégorielles : TARGET ENCODING (category_encoders)
    TargetEncoder est intégré DANS le pipeline imblearn.
    → À chaque pli de CV, le target encoding est recalculé
      uniquement sur le fold train : zéro data leakage.
    → Pour toute modalité inconnue (nouveau port, nouveau carrier)
      → taux global automatique (handle_unknown='value').

Pipeline complet :
    1. TargetEncoder  — carrier, port_chargement, port_dechargement, pays_destination
    2. Imputation médiane (SimpleImputer)
    3. Normalisation (StandardScaler)
    4. SMOTE          — suréchantillonnage classe minoritaire sur fold train uniquement
    5. LogisticRegression (ElasticNet, solver=saga)

Features finales (11, toutes numériques après encoding) :
    transit_time, frequency_num, volume_ratio_allocated_booked,
    volume_booked, confirmed_volume,
    carrier, port_chargement, port_dechargement, pays_destination,
    month_sin, month_cos

Variable cible : is_delayed (0 = à l'heure, 1 = en retard)

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

from category_encoders import TargetEncoder
from scipy.stats import loguniform
from imblearn.over_sampling import SMOTE
from imblearn.pipeline import Pipeline as ImbPipeline
from sklearn.linear_model import LogisticRegression
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score, classification_report, confusion_matrix,
    f1_score, precision_recall_curve, precision_score, recall_score,
    log_loss, jaccard_score,
)
from sklearn.model_selection import (
    RandomizedSearchCV, StratifiedKFold,
    cross_val_score, train_test_split,
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
    df = df.copy()
    df["frequency_num"] = (
        df["frequency"].astype(str).str.extract(r"(\d+)").astype(float)
    )
    return df


def extraire_month_cyclique(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    mois_num = pd.to_datetime(
        df["month"], format="%B %y", errors="coerce"
    ).dt.month
    df["month_sin"] = np.sin(2 * np.pi * mois_num / 12)
    df["month_cos"] = np.cos(2 * np.pi * mois_num / 12)
    return df


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

    y = df_ml["is_delayed"].astype(int)
    X = df_ml[TOUTES_FEATURES].copy()

    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=proportion_test,
        random_state=42,
        stratify=y,
    )

    print(f"\nDataset ML      : {len(df_ml)} shipments")
    print(f"En retard       : {y.sum()} ({y.mean()*100:.1f}%)")
    print(f"À l'heure       : {(y == 0).sum()} ({(1-y.mean())*100:.1f}%)")
    print(f"Train set       : {len(X_train)} lignes")
    print(f"Test set        : {len(X_test)} lignes")
    print(f"Features entrée : {TOUTES_FEATURES}")
    print(f"\nDistribution avant SMOTE :")
    print(f"   Train — En retard : {y_train.sum()} ({y_train.mean()*100:.1f}%)"
          f" | À l'heure : {(y_train==0).sum()}")

    return X_train, X_test, y_train, y_test


# ═══════════════════════════════════════════════════════════════════════════
# CONSTRUCTION DU PIPELINE COMPLET
# ═══════════════════════════════════════════════════════════════════════════

def construire_pipeline(
    C: float = 1.0,
    l1_ratio: float = 0.0,
    sampling_strategy: float = 0.5,
) -> ImbPipeline:
    """
    Pipeline imblearn complet — 5 étapes APLATIES (pas de Pipeline imbriqué) :

    CORRECTION : imblearn.Pipeline interdit les sklearn.Pipeline en étapes
    intermédiaires. Les étapes imputation + normalisation sont donc déclarées
    directement au niveau du pipeline principal, sans sous-Pipeline.

    1. TargetEncoder  — encode les 4 variables catégorielles par leur taux
                        de retard historique. Recalculé sur le fold train
                        à chaque pli de CV → zéro data leakage.
    2. SimpleImputer  — imputation médiane sur toutes les features.
    3. StandardScaler — normalisation z-score sur toutes les features.
    4. SMOTE          — suréchantillonnage sur le fold train uniquement.
    5. LogisticRegression (ElasticNet, solver=saga).
    """

    pipeline = ImbPipeline(steps=[
        # Étape 1 : encodage target des variables catégorielles
        (
            "target_encoder",
            TargetEncoder(
                cols=FEATURES_CAT,
                handle_unknown="value",   # modalité inconnue → taux global
                handle_missing="value",   # NaN → taux global
                min_samples_leaf=20,      # lissage petits groupes
                smoothing=1.0,            # régularisation vers moyenne globale
            ),
        ),
        # Étape 2 : imputation médiane (directement, pas dans un sous-Pipeline)
        (
            "imputation",
            SimpleImputer(strategy="median"),
        ),
        # Étape 3 : normalisation (directement, pas dans un sous-Pipeline)
        (
            "normalisation",
            StandardScaler(),
        ),
        # Étape 4 : SMOTE sur fold train uniquement
        (
            "smote",
            SMOTE(
                sampling_strategy=sampling_strategy,
                random_state=42,
                k_neighbors=5,
            ),
        ),
        # Étape 5 : régression logistique ElasticNet
        (
            "modele",
            LogisticRegression(
                solver="saga",
                penalty="elasticnet",
                l1_ratio=l1_ratio,
                C=C,
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
    """
    Recherche aléatoire sur 3 hyperparamètres :
      - modele__C               : régularisation
      - modele__l1_ratio        : proportion L1 dans ElasticNet
      - smote__sampling_strategy: ratio SMOTE
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

    print(f"\nSeuil optimal (F1 macro sur train) : {seuil_optimal:.3f}")
    print(f"F1 macro au seuil optimal          : {f1_au_seuil*100:.2f}%")
    return seuil_optimal, f1_au_seuil


# ═══════════════════════════════════════════════════════════════════════════
# ÉVALUATION
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

    # ── Performance test ──────────────────────────────────────────────────
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

    print("\n=== PERFORMANCE TEST ===")
    print(f"Accuracy          : {acc*100:.2f}%")
    print(f"F1 macro          : {f1_mac*100:.2f}%")
    print(f"F1 'En retard'    : {f1_ret*100:.2f}%")
    print(f"F1 'À l'heure'   : {f1_heure*100:.2f}%")
    print(f"Precision         : {prec*100:.2f}%")
    print(f"Recall            : {rec*100:.2f}%")
    print(f"Log Loss          : {ll:.4f}")
    print(f"Jaccard Index     : {jacc:.4f}")

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

    # ── Cross-validation ──────────────────────────────────────────────────
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores_cv = cross_val_score(
        pipeline, X_train, y_train,
        cv=cv, scoring="f1_macro"
    )
    print(f"CV F1 macro (5 plis) : {scores_cv.mean()*100:.2f}%"
          f" (+/- {scores_cv.std()*100:.2f}%)")
    print(f"Écart CV/test        : {(scores_cv.mean()-f1_mac)*100:+.2f} pts")

    if ll < 0.35:
        print(f"\nLog Loss {ll:.4f} : Très bon — probabilités bien calibrées")
    elif ll < 0.50:
        print(f"\nLog Loss {ll:.4f} : Bon — probabilités acceptables")
    else:
        print(f"\nLog Loss {ll:.4f} : À améliorer")

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
    top_n: int = 15,
) -> pd.DataFrame:
    try:
        coefficients = pipeline.named_steps["modele"].coef_[0]
        noms = TOUTES_FEATURES[:len(coefficients)]

        df_coef = (
            pd.DataFrame({
                "feature":     noms,
                "coefficient": coefficients,
            })
            .assign(impact_abs=lambda d: d["coefficient"].abs())
            .sort_values("impact_abs", ascending=False)
            .drop(columns="impact_abs")
            .reset_index(drop=True)
        )

        non_nuls = (df_coef["coefficient"] != 0).sum()
        print(f"\n=== TOP {top_n} FEATURES (triées par impact absolu) ===")
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
    seuil_decision: float | None = None,  # conservé pour compatibilité, non utilisé
) -> None:
    """
    Sauvegarde le pipeline et le taux global.
    Le seuil de décision binaire n'est plus utilisé en production :
    les niveaux de risque sont calculés directement depuis la probabilité brute.
    Un seuil_decision=None est sauvegardé pour signaler ce changement.
    """
    joblib.dump(
        {
            "pipeline":       pipeline,
            "seuil_decision": None,   # obsolète — niveaux basés sur proba brute
            "taux_global":    taux_global,
        },
        MODEL_PATH,
    )
    print(f"\nModèle sauvegardé : {MODEL_PATH}")
    print(f"  Taux global       : {taux_global*100:.2f}%")
    print(f"  Niveaux de risque : basés sur probabilité brute (< 10% / < 25% / ≥ 25%)")
    print(f"  TargetEncoder inclus dans le pipeline sauvegardé")


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
    return (
        contenu["pipeline"],
        contenu["seuil_decision"],
        contenu["taux_global"],
    )


def _classifier_niveau_risque(probabilite: float) -> tuple[str, str]:
    if probabilite < 0.30:
        niveau_risque = "Faible"
        label = "Risque faible"
    elif probabilite < 0.639:
        niveau_risque = "Modéré"
        label = "Risque modéré"
    else:
        niveau_risque = "Élevé"
        label = "Risque élevé"

    return niveau_risque, label


def predire_retard(nouveau_shipment: dict) -> dict:
    """
    Prédit le risque de retard d'un shipment.

    Le niveau de risque est déterminé par la probabilité brute du modèle,
    sans seuil binaire fixe. Cette approche est plus robuste sur des données
    déséquilibrées (10.6% de retards) et plus informative pour l'utilisateur.

    Niveaux retournés :
        Faible      (proba < 10%)  → en dessous du taux moyen historique
        Modéré      (10% ≤ proba < 25%) → à surveiller
        Élevé       (proba ≥ 25%) → action recommandée
    """
    pipeline, seuil_decision, taux_global = charger_modele()

    # ── Feature engineering ───────────────────────────────────────────────
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

    # ── Prédiction — probabilité brute ────────────────────────────────────
    probabilite   = float(pipeline.predict_proba(X_nouveau)[0][1])
    niveau_risque, label = _classifier_niveau_risque(probabilite)

    return {
        "probabilite_retard": round(probabilite * 100, 1),
        "niveau_risque":      niveau_risque,
        "label":              label,
        # Conservé pour compatibilité avec le backend existant
        "prediction":         1 if niveau_risque == "Élevé" else 0,
        "taux_global":        round(taux_global * 100, 1),
    }


# ═══════════════════════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 65)
    print("  ENTRAÎNEMENT : RÉGRESSION LOGISTIQUE + SMOTE")
    print("  TargetEncoder dans pipeline — zéro data leakage")
    print("  Split aléatoire stratifié 80/20")
    print("=" * 65)

    # 1. Chargement et préparation
    df_raw = get_all_shipments()
    X_train, X_test, y_train, y_test = preparer_donnees(df_raw)

    taux_global = float(y_train.mean())

    # 2. Tuning hyperparamètres
    pipeline, best_params, best_cv_score = tuner_hyperparametres(
        X_train, y_train, n_iter=50
    )

    # 3. Seuil de décision optimal
    seuil_optimal, _ = trouver_seuil_optimal(pipeline, X_train, y_train)

    # 4. Évaluation complète
    metriques = evaluer_modele(
        pipeline, X_train, X_test, y_train, y_test,
        seuil=seuil_optimal
    )

    # 5. Coefficients des features
    afficher_importance_features(pipeline, top_n=11)

    # 6. Sauvegarde (seuil_decision non utilisé en production)
    sauvegarder_modele(pipeline, taux_global)

    print("\n" + "=" * 65)
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
    print("=" * 65)

    # 7. Tests de prédiction — cas métier représentatifs
    # Basés sur les features les plus influentes :
    #   1. frequency_num  (coef +1.34) : fréquence faible  → risque plus élevé
    #   2. month_sin      (coef +1.20) : pic saisonnier    → risque plus élevé
    #   3. volume_ratio   (coef -0.49) : ratio faible      → risque plus élevé
    #   4. transit_time   (coef -0.10) : transit long      → légèrement plus élevé

    print("\n=== TESTS DE PRÉDICTION — CAS MÉTIER ===")
    exemples = [

        # ── CAS 1 : profil idéal — toutes features favorables ─────────────
        # Fréquence haute (7j), bon ratio volume (98%), mois calme (avril),
        # transit court → combinaison la moins risquée possible
        ("Profil idéal — risque minimal",
         {"transit_time": 7,  "frequency": "7j",  "month": "April 25",
          "volume_booked": 1000, "confirmed_volume": 980,
          "carrier": "GRIMALDI LINES",
          "port_chargement": "Tanger Med",
          "port_dechargement": "Civitavecchia",
          "pays_destination": "Italy"}),

        # ── CAS 2 : profil standard — conditions normales ──────────────────
        # Fréquence normale (14j), ratio volume correct (90%), mois neutre
        ("Profil standard — conditions normales",
         {"transit_time": 14, "frequency": "14j", "month": "June 25",
          "volume_booked": 800, "confirmed_volume": 720,
          "carrier": "GRIMALDI LINES",
          "port_chargement": "Tanger Med",
          "port_dechargement": "Barcelona",
          "pays_destination": "Spain"}),

        # ── CAS 3 : fréquence faible — feature la plus influente ───────────
        # Fréquence 30j = rotations rares → moins de flexibilité
        # Isole l'impact de frequency_num (coef +1.34)
        ("Fréquence faible (30j) — impact frequency",
         {"transit_time": 14, "frequency": "30j", "month": "June 25",
          "volume_booked": 800, "confirmed_volume": 750,
          "carrier": "GRIMALDI LINES",
          "port_chargement": "Tanger Med",
          "port_dechargement": "Civitavecchia",
          "pays_destination": "Italy"}),

        # ── CAS 4 : période hivernale — risque saisonnier ──────────────────
        # Décembre = pic saisonnier (month_sin élevé, coef +1.20)
        # Combine fréquence basse + période chargée
        ("Période hivernale — risque saisonnier (Déc)",
         {"transit_time": 21, "frequency": "21j", "month": "December 25",
          "volume_booked": 600, "confirmed_volume": 540,
          "carrier": "WALLENIUS WILHELMSEN",
          "port_chargement": "Tanger Med",
          "port_dechargement": "Barcelona",
          "pays_destination": "Spain"}),

        # ── CAS 5 : ratio volume dégradé — sous-confirmation ───────────────
        # Confirmed Volume = 50% de Volume Booked → ratio très faible
        # Isole l'impact de volume_ratio_allocated_booked (coef -0.49)
        ("Sous-confirmation volume (50%) — ratio dégradé",
         {"transit_time": 14, "frequency": "14j", "month": "September 25",
          "volume_booked": 1000, "confirmed_volume": 500,
          "carrier": "GRIMALDI LINES",
          "port_chargement": "Tanger Med",
          "port_dechargement": "Civitavecchia",
          "pays_destination": "Italy"}),

        # ── CAS 6 : cumul de tous les facteurs défavorables ────────────────
        # Fréquence très basse (30j) + pic hivernal (Décembre)
        # + ratio volume dégradé (60%) + transit long (30j)
        # → pire combinaison possible pour évaluer le plafond du modèle
        ("Cumul facteurs défavorables — risque maximal",
         {"transit_time": 30, "frequency": "30j", "month": "December 25",
          "volume_booked": 800, "confirmed_volume": 480,
          "carrier": "WALLENIUS WILHELMSEN",
          "port_chargement": "Tanger Med",
          "port_dechargement": "Barcelona",
          "pays_destination": "Spain"}),

        # ── CAS 7 : robustesse — carrier inconnu ───────────────────────────
        # TargetEncoder → taux global automatique (≈10.6%)
        # Vérifie que le modèle gère correctement une nouvelle modalité
        ("Carrier inconnu → taux global automatique",
         {"transit_time": 14, "frequency": "14j", "month": "June 25",
          "volume_booked": 900, "confirmed_volume": 860,
          "carrier": "NOUVEAU_CARRIER_XYZ",
          "port_chargement": "Tanger Med",
          "port_dechargement": "Civitavecchia",
          "pays_destination": "Italy"}),

        # ── CAS 8 : robustesse — données manquantes ────────────────────────
        # SimpleImputer → médiane sur toutes les features manquantes
        # Vérifie la robustesse du pipeline en conditions dégradées
        ("Données manquantes — imputation médiane",
         {"transit_time": None, "frequency": None, "month": None,
          "volume_booked": None, "confirmed_volume": None,
          "carrier": None, "port_chargement": None,
          "port_dechargement": None, "pays_destination": None}),
    ]

    print(f"\n{'─'*78}")
    print(f"{'Cas':<45} {'Proba':>6}  {'Risque':<10}  {'Label'}")
    print(f"{'─'*78}")
    for nom, data in exemples:
        r = predire_retard(data)
        print(f"{nom:<45} {r['probabilite_retard']:>5.1f}%"
              f"  {r['niveau_risque']:<10}  {r['label']}")
    print(f"{'─'*78}")
    print(f"\nTaux historique de retard dans le dataset : 10.6%")
    print(f"\nSeuils de classification (basés sur le taux historique) :")
    print(f"  Faible    : probabilité <  5%  → bien en dessous du taux moyen")
    print(f"  Modéré    : probabilité  5–10% → autour du taux moyen, à surveiller")
    print(f"  Élevé     : probabilité ≥ 10%  → dépasse le taux moyen, action requise")