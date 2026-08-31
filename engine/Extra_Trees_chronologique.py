"""
Extra_trees.py — Modèle de prédiction de retard : EXTRA TREES
Fichier autonome, indépendant des autres modèles.

Particularité par rapport à Random Forest : Extra Trees (Extremely
Randomized Trees) choisit les seuils de découpage de chaque arbre de
manière ALÉATOIRE plutôt que d'optimiser le meilleur seuil possible à
chaque nœud. Cela introduit plus de variance individuelle par arbre,
mais réduit généralement le risque de surapprentissage global de
l'ensemble — un atout potentiellement intéressant ici, puisque Random
Forest a montré un fort surapprentissage temporel (écart CV/test de
+13.13 points).

Même preprocessing que Random Forest (pas de normalisation nécessaire,
insensible à l'échelle des variables).

Méthode d'évaluation : split CHRONOLOGIQUE (train = période ancienne,
test = période la plus récente, jamais vue).

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
import pandas as pd
import numpy as np
import joblib
from pathlib import Path

from sklearn.ensemble import ExtraTreesClassifier
from sklearn.model_selection import (
    cross_val_score, StratifiedKFold, RandomizedSearchCV, train_test_split
)
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score,
    f1_score, confusion_matrix, classification_report,
    precision_recall_curve,
)
from scipy.stats import randint

from database.db import get_all_shipments

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ── Chemin du modèle sauvegardé ───────────────────────────────────────────────
MODEL_PATH = Path("models/extra_trees.pkl")
MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)

# ── Définition des features ───────────────────────────────────────────────────
FEATURES_NUM = [
    "transit_time",
    "frequency_num",
    "volume_ratio_allocated_booked",
    "volume_booked",        # ajout aligné sur Random Forest
    "confirmed_volume",     # ajout aligné sur Random Forest
    "carrier_taux_retard",
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
# FEATURE ENGINEERING
# ═══════════════════════════════════════════════════════════════════════════

def extraire_frequency_num(df: pd.DataFrame) -> pd.DataFrame:
    """Convertit 'frequency' de texte ("7j") en nombre entier (7)."""
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
# PRÉPARATION DES DONNÉES — SPLIT ALEATOIRE
# ═══════════════════════════════════════════════════════════════════════════

def preparer_donnees(df: pd.DataFrame | None = None, proportion_test: float = 0.2) -> tuple:
    """
     Split ALÉATOIRE STRATIFIÉ : la proportion de retards est identique
    dans le train et le test (stratify=y).

    Returns
    -------
    X_train, X_test, y_train, y_test, taux_par_carrier, taux_global
    """
    if df is None:
        df = get_all_shipments()

    df_ml = df[df["is_delayed"].notna()].copy()

    df_ml = extraire_frequency_num(df_ml)
    df_ml = extraire_month_cyclique(df_ml)

    df_ml["etd"] = pd.to_datetime(df_ml["etd"], errors="coerce")
    df_ml = df_ml.sort_values("etd").reset_index(drop=True)

    y = df_ml["is_delayed"].astype(int)

    # volume_booked et confirmed_volume ajoutés (alignement RF)
    features_brutes = [
        "transit_time", "frequency_num", "volume_ratio_allocated_booked",
        "volume_booked", "confirmed_volume",
        "month_sin", "month_cos",
        "carrier", "port_chargement", "port_dechargement", "pays_destination",
    ]
    X = df_ml[features_brutes].copy()

    n_total = len(df_ml)
    n_test = int(n_total * proportion_test)
    n_train = n_total - n_test

    X_train = X.iloc[:n_train].copy()
    X_test = X.iloc[n_train:].copy()

    y_train = y.iloc[:n_train].copy()
    y_test = y.iloc[n_train:].copy()

    print(f"Période train : {df_ml.iloc[:n_train]['etd'].min().date()} → {df_ml.iloc[:n_train]['etd'].max().date()}")
    print(f"Période test  : {df_ml.iloc[n_train:]['etd'].min().date()} → {df_ml.iloc[n_train:]['etd'].max().date()}")

    # Taux retard carrier (calculé après le split, sur train uniquement)
    X_train, X_test, taux_par_carrier, taux_global = calculer_taux_retard_carrier(
        X_train, X_test, y_train
    )

    print(f"\nDataset ML     : {len(df_ml)} shipments")
    print(f"En retard      : {y.sum()} ({y.mean()*100:.1f}%)")
    print(f"À l'heure      : {(y == 0).sum()} ({(1 - y.mean())*100:.1f}%)")
    print(f"Train set      : {len(X_train)} lignes (plus anciens)")
    print(f"Test set       : {len(X_test)} lignes (plus recents, jamais vus)")
    print(f"Features       : {TOUTES_FEATURES}")

    return X_train, X_test, y_train, y_test, taux_par_carrier, taux_global


# ═══════════════════════════════════════════════════════════════════════════
# CONSTRUCTION DU PIPELINE — EXTRA TREES
# ═══════════════════════════════════════════════════════════════════════════

def construire_pipeline(
    n_estimators: int = 300,
    max_depth: int | None = 10,
    min_samples_leaf: int = 5,
    min_samples_split: int = 2,
    max_features: str | float = "sqrt",
) -> Pipeline:
    """
    Preprocessing :
      - Imputation médiane pour les numériques (robuste aux outliers)
      - OneHotEncoder avec min_frequency=5 pour grouper les catégories rares
        en 'infrequent_sklearn' et réduire la dimensionnalité
    Extra Trees avec class_weight='balanced' pour compenser le déséquilibre
    des classes (≈26% de retards).
    """
    preprocesseur = ColumnTransformer(
        transformers=[
            (
                "num",
                SimpleImputer(strategy="median"),
                FEATURES_NUM,
            ),
            (
                "cat",
                OneHotEncoder(
                    handle_unknown="ignore",
                    sparse_output=False,
                    min_frequency=5,        # catégories rares → 'infrequent_sklearn'
                ),
                FEATURES_CAT,
            ),
        ],
        remainder="drop",
    )
    pipeline = Pipeline(steps=[
        ("preprocesseur", preprocesseur),
        (
            "modele",
            ExtraTreesClassifier(
                n_estimators=n_estimators,
                max_depth=max_depth,
                min_samples_leaf=min_samples_leaf,
                min_samples_split=min_samples_split,
                max_features=max_features,
                class_weight="balanced",
                random_state=42,
                n_jobs=-1,
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
    n_iter: int = 60,
) -> tuple:
    """
    Recherche aléatoire d'hyperparamètres avec cross-validation stratifiée
    sur le train uniquement. Métrique cible : F1 (classe 'En retard').
    """
    pipeline_base = construire_pipeline()

    espace_recherche = {
        "modele__n_estimators":      randint(100, 600),
        "modele__max_depth":         [5, 8, 10, 12, 15, 20, None],
        "modele__min_samples_leaf":  randint(2, 25),
        "modele__min_samples_split": randint(2, 30),
        "modele__max_features":      ["sqrt", "log2", 0.3, 0.5, None],
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

    print("\n=== PERFORMANCE TEST (split chronologique) ===")
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
# IMPORTANCE DES FEATURES
# ═══════════════════════════════════════════════════════════════════════════

def afficher_importance_features(pipeline: Pipeline, top_n: int = 20) -> pd.DataFrame:
    """Affiche les features les plus importantes selon Extra Trees."""
    cat_names = (
        pipeline.named_steps["preprocesseur"]
        .named_transformers_["cat"]
        .get_feature_names_out(FEATURES_CAT)
        .tolist()
    )
    all_names   = FEATURES_NUM + cat_names
    importances = pipeline.named_steps["modele"].feature_importances_

    df_imp = (
        pd.DataFrame({"feature": all_names, "importance": importances})
        .sort_values("importance", ascending=False)
        .reset_index(drop=True)
    )

    print(f"\n=== TOP {top_n} FEATURES ===")
    print(df_imp.head(top_n).to_string(index=False))
    return df_imp


# ═══════════════════════════════════════════════════════════════════════════
# SAUVEGARDE
# ═══════════════════════════════════════════════════════════════════════════

def sauvegarder_modele(
    pipeline: Pipeline,
    taux_par_carrier: pd.Series,
    taux_global: float,
    seuil_decision: float,
) -> None:
    joblib.dump(
        {
            "pipeline":         pipeline,
            "taux_par_carrier": taux_par_carrier,
            "taux_global":      taux_global,
            "seuil_decision":   seuil_decision,   # sauvegardé comme dans RF
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
            "Lancez d'abord : python -m engine.Extra_trees"
        )
    contenu = joblib.load(MODEL_PATH)
    seuil   = contenu.get("seuil_decision", 0.50)   # rétrocompat si ancien pkl sans seuil
    return contenu["pipeline"], contenu["taux_par_carrier"], contenu["taux_global"], seuil


def predire_retard(nouveau_shipment: dict) -> dict:
    """
    Prédit le retard d'un shipment à partir d'un dictionnaire brut.
    Utilisé par predictor.py et l'API Flask.
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

    # volume_ratio : utilise la valeur directe si fournie, sinon calcule
    vol_booked    = float(nouveau_shipment.get("volume_booked") or 0)
    vol_confirmed = float(nouveau_shipment.get("confirmed_volume") or 0)
    volume_ratio  = (
        nouveau_shipment.get("volume_ratio_allocated_booked")
        or (vol_confirmed / vol_booked if vol_booked > 0 else np.nan)
    )

    X_nouveau = pd.DataFrame([{
        "transit_time":                  nouveau_shipment.get("transit_time", np.nan),
        "frequency_num":                 frequency_num,
        "volume_ratio_allocated_booked": volume_ratio,
        "volume_booked":                 vol_booked or np.nan,      # ajout aligné RF
        "confirmed_volume":              vol_confirmed or np.nan,   # ajout aligné RF
        "carrier_taux_retard":           carrier_taux,
        "month_sin":                     month_sin,
        "month_cos":                     month_cos,
        "carrier":                       carrier,
        "port_chargement":               nouveau_shipment.get("port_chargement") or np.nan,
        "port_dechargement":             nouveau_shipment.get("port_dechargement") or np.nan,
        "pays_destination":              nouveau_shipment.get("pays_destination") or np.nan,
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
        "seuil_utilise":      round(seuil_decision, 3),   # ajout pour traçabilité
    }


# ═══════════════════════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  ENTRAÎNEMENT : EXTRA TREES — PRÉDICTION DE RETARD")
    print("  === (evaluation chronologique : train = passe, test = futur) ===")
    print("=" * 60)

    # 1. Chargement et préparation
    df_raw = get_all_shipments()
    X_train, X_test, y_train, y_test, taux_par_carrier, taux_global = preparer_donnees(df_raw)

    # 2. Tuning hyperparamètres (60 itérations, comme RF)
    pipeline, best_params, best_cv_score = tuner_hyperparametres(X_train, y_train, n_iter=60)

    # 3. Seuil de décision optimal (sur train uniquement)
    seuil_optimal = trouver_seuil_optimal(pipeline, X_train, y_train)

    # 4. Évaluation complète sur le test
    metriques = evaluer_modele(pipeline, X_train, X_test, y_train, y_test, seuil=seuil_optimal)

    # 5. Importance des features
    afficher_importance_features(pipeline, top_n=20)

    # 6. Sauvegarde (avec seuil)
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
        "port_dechargement": "Civitavecchia", "pays_destination": "Italy",
    }
    resultat = predire_retard(exemple)
    print(
        f"Shipment test → {resultat['label']} "
        f"(probabilité : {resultat['probabilite_retard']}%, "
        f"risque : {resultat['niveau_risque']}, "
        f"seuil : {resultat['seuil_utilise']})"
    )