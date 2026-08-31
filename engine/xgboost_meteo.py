"""
xgboost_meteo.py — Modèle XGBoost avec features météo

Objectif :
    Prédiction du retard des shipments à partir des caractéristiques
    opérationnelles, commerciales et météorologiques.

Méthode d'évaluation :
    Split aléatoire stratifié 80/20.

Particularités :
    - XGBoost
    - Features météo sur les ports de départ et d'arrivée
    - Encodage One-Hot des variables catégorielles
    - Imputation médiane des variables numériques
    - Taux historique de retard par carrier
    - Recherche aléatoire des hyperparamètres
    - Optimisation du seuil de décision selon le F1
"""

import warnings
import logging
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import joblib

from xgboost import XGBClassifier

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer

from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    precision_recall_curve,
)

from sklearn.model_selection import (
    RandomizedSearchCV,
    StratifiedKFold,
    cross_val_score,
    train_test_split,
)

from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from engine.weather_client import enrich_dataset_with_weather


# =============================================================================
# CONFIGURATION
# =============================================================================

warnings.filterwarnings("ignore")

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)


DB_PATH = Path("data/Logistique.db")
MODEL_PATH = Path("models/xgboost_meteo.pkl")

MODEL_PATH.parent.mkdir(
    parents=True,
    exist_ok=True
)


# =============================================================================
# FEATURES
# =============================================================================

FEATURES_NUM = [
    "transit_time",
    "frequency_num",
    "volume_ratio_allocated_booked",
    "volume_booked",
    "confirmed_volume",
    "carrier_taux_retard",
    "month_sin",
    "month_cos",

    # Météo au départ
    "etd_precipitation_mm",
    "etd_wind_speed_kmh",
    "etd_temperature_max",
    "etd_weather_code",

    # Météo à l'arrivée
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


# =============================================================================
# CHARGEMENT DE LA BASE
# =============================================================================

def get_all_shipments(db_path: Path = DB_PATH) -> pd.DataFrame:
    """
    Charge tous les shipments depuis la base SQLite.

    La table shipment est jointe à la table vessel afin de récupérer
    le carrier.
    """

    if not db_path.exists():
        raise FileNotFoundError(
            f"Base introuvable : {db_path}\n"
            "Vérifiez que Logistique.db est bien présent dans data/."
        )

    conn = sqlite3.connect(db_path)

    try:
        df = pd.read_sql(
            """
            SELECT
                s.*,
                v.carrier
            FROM shipment s
            JOIN vessel v
                ON s.vessel_id = v.id
            """,
            conn,
        )
    finally:
        conn.close()

    logger.info(
        "Base chargée : %d lignes, %d colonnes",
        *df.shape
    )

    return df


# =============================================================================
# NORMALISATION DES COLONNES DE PORTS
# =============================================================================

def normaliser_colonnes_ports(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalise les noms des colonnes correspondant aux ports.

    Le dataset peut utiliser différents noms selon la version de la base.
    Le modèle utilise ensuite systématiquement :

        port_chargement
        port_dechargement

    Si les colonnes ne sont pas trouvées, une erreur explicite est générée
    avec la liste des colonnes disponibles.
    """

    df = df.copy()

    # -------------------------------------------------------------------------
    # Colonne port de chargement
    # -------------------------------------------------------------------------

    candidats_chargement = [
        "port_chargement",
        "port_loading",
        "port_load",
        "loading_port",
        "port_of_loading",
        "pol",
        "POL",
    ]

    # -------------------------------------------------------------------------
    # Colonne port de déchargement
    # -------------------------------------------------------------------------

    candidats_dechargement = [
        "port_dechargement",
        "port_discharge",
        "port_discharge",
        "discharge_port",
        "port_of_discharge",
        "pod",
        "POD",
    ]

    # Recherche du port de chargement
    colonne_chargement = next(
        (
            col
            for col in candidats_chargement
            if col in df.columns
        ),
        None,
    )

    # Recherche du port de déchargement
    colonne_dechargement = next(
        (
            col
            for col in candidats_dechargement
            if col in df.columns
        ),
        None,
    )

    # -------------------------------------------------------------------------
    # Création des noms standards
    # -------------------------------------------------------------------------

    if "port_chargement" not in df.columns:

        if colonne_chargement is None:
            raise KeyError(
                "\nColonne du port de chargement introuvable.\n"
                f"Colonnes disponibles : {df.columns.tolist()}\n"
                f"Noms recherchés : {candidats_chargement}"
            )

        df["port_chargement"] = df[colonne_chargement]

        logger.info(
            "Colonne port de chargement normalisée : %s -> port_chargement",
            colonne_chargement,
        )

    if "port_dechargement" not in df.columns:

        if colonne_dechargement is None:
            raise KeyError(
                "\nColonne du port de déchargement introuvable.\n"
                f"Colonnes disponibles : {df.columns.tolist()}\n"
                f"Noms recherchés : {candidats_dechargement}"
            )

        df["port_dechargement"] = df[colonne_dechargement]

        logger.info(
            "Colonne port de déchargement normalisée : "
            "%s -> port_dechargement",
            colonne_dechargement,
        )

    return df


# =============================================================================
# FEATURE ENGINEERING
# =============================================================================

def extraire_frequency_num(df: pd.DataFrame) -> pd.DataFrame:
    """
    Transforme une fréquence textuelle en variable numérique.

    Exemple :
        '7j' -> 7.0
        '14j' -> 14.0
        valeur inconnue -> NaN
    """

    df = df.copy()

    df["frequency_num"] = (
        df["frequency"]
        .astype(str)
        .str.extract(r"(\d+)", expand=False)
        .astype(float)
    )

    return df


def extraire_month_cyclique(df: pd.DataFrame) -> pd.DataFrame:
    """
    Transforme le mois en deux variables cycliques :

        month_sin
        month_cos

    Cela permet de conserver la proximité entre décembre et janvier.
    """

    df = df.copy()

    mois_num = pd.to_datetime(
        df["month"],
        format="%B %y",
        errors="coerce"
    ).dt.month

    df["month_sin"] = np.sin(
        2 * np.pi * mois_num / 12
    )

    df["month_cos"] = np.cos(
        2 * np.pi * mois_num / 12
    )

    return df


# =============================================================================
# TAUX HISTORIQUE DE RETARD PAR CARRIER
# =============================================================================

def calculer_taux_retard_carrier(
    X_train: pd.DataFrame,
    X_test: pd.DataFrame,
    y_train: pd.Series,
):
    """
    Calcule le taux historique de retard par carrier.

    IMPORTANT :
        Le taux est calculé uniquement à partir du train afin d'éviter
        d'utiliser directement les labels du test.

    Les carriers inconnus reçoivent le taux global du train.
    """

    taux_global = float(y_train.mean())

    taux_par_carrier = (
        X_train
        .assign(is_delayed=y_train.values)
        .groupby("carrier")["is_delayed"]
        .mean()
    )

    X_train = X_train.copy()
    X_test = X_test.copy()

    X_train["carrier_taux_retard"] = (
        X_train["carrier"]
        .map(taux_par_carrier)
        .fillna(taux_global)
    )

    X_test["carrier_taux_retard"] = (
        X_test["carrier"]
        .map(taux_par_carrier)
        .fillna(taux_global)
    )

    return (
        X_train,
        X_test,
        taux_par_carrier,
        taux_global,
    )


# =============================================================================
# PREPARATION DES DONNEES
# =============================================================================

def preparer_donnees(
    df: pd.DataFrame | None = None,
    proportion_test: float = 0.2,
):
    """
    Prépare les données pour XGBoost.

    Étapes :

        1. Sélection des observations avec is_delayed connu
        2. Normalisation des noms des ports
        3. Feature engineering fréquence
        4. Feature engineering temporel
        5. Enrichissement météo
        6. Séparation X / y
        7. Split stratifié 80/20
        8. Calcul du taux de retard par carrier
    """

    if df is None:
        df = get_all_shipments()

    # -------------------------------------------------------------------------
    # Normalisation des colonnes
    # -------------------------------------------------------------------------

    df = normaliser_colonnes_ports(df)

    # -------------------------------------------------------------------------
    # Conservation des lignes avec cible connue
    # -------------------------------------------------------------------------

    if "is_delayed" not in df.columns:
        raise KeyError(
            "La colonne 'is_delayed' est absente de la base."
        )

    df_ml = df[
        df["is_delayed"].notna()
    ].copy()

    # -------------------------------------------------------------------------
    # Feature engineering
    # -------------------------------------------------------------------------

    df_ml = extraire_frequency_num(df_ml)

    df_ml = extraire_month_cyclique(df_ml)

    # -------------------------------------------------------------------------
    # Enrichissement météo
    # -------------------------------------------------------------------------

    print("\nEnrichissement météo...")

    df_ml = enrich_dataset_with_weather(
        df_ml
    )

    print("Météo enrichie.")

    # -------------------------------------------------------------------------
    # Vérification des features météo
    # -------------------------------------------------------------------------

    features_meteo = [
        "etd_precipitation_mm",
        "etd_wind_speed_kmh",
        "etd_temperature_max",
        "etd_weather_code",
        "eta_precipitation_mm",
        "eta_wind_speed_kmh",
        "eta_temperature_max",
        "eta_weather_code",
    ]

    colonnes_meteo_absentes = [
        col
        for col in features_meteo
        if col not in df_ml.columns
    ]

    if colonnes_meteo_absentes:
        raise KeyError(
            "\nCertaines variables météo sont absentes après "
            "l'enrichissement :\n"
            f"{colonnes_meteo_absentes}\n\n"
            f"Colonnes disponibles :\n{df_ml.columns.tolist()}"
        )

    # -------------------------------------------------------------------------
    # Variable cible
    # -------------------------------------------------------------------------

    y = df_ml[
        "is_delayed"
    ].astype(int)

    # -------------------------------------------------------------------------
    # Features brutes
    #
    # carrier_taux_retard est ajouté après le split.
    # -------------------------------------------------------------------------

    features_brutes = [
        feature
        for feature in TOUTES_FEATURES
        if feature != "carrier_taux_retard"
    ]

    colonnes_absentes = [
        feature
        for feature in features_brutes
        if feature not in df_ml.columns
    ]

    if colonnes_absentes:
        raise KeyError(
            "\nFeatures absentes du dataset :\n"
            f"{colonnes_absentes}\n\n"
            "Colonnes disponibles :\n"
            f"{df_ml.columns.tolist()}"
        )

    X = df_ml[
        features_brutes
    ].copy()

    # -------------------------------------------------------------------------
    # Split stratifié
    # -------------------------------------------------------------------------

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=proportion_test,
        random_state=42,
        stratify=y,
    )

    # -------------------------------------------------------------------------
    # Taux historique de retard par carrier
    # -------------------------------------------------------------------------

    (
        X_train,
        X_test,
        taux_par_carrier,
        taux_global,
    ) = calculer_taux_retard_carrier(
        X_train,
        X_test,
        y_train,
    )

    # -------------------------------------------------------------------------
    # Résumé
    # -------------------------------------------------------------------------

    print(
        f"\nDataset       : {len(df_ml)} shipments"
    )

    print(
        f"Retards       : {y.sum()} "
        f"({y.mean() * 100:.1f}%)"
    )

    print(
        f"À l'heure     : {(y == 0).sum()} "
        f"({(1 - y.mean()) * 100:.1f}%)"
    )

    print(
        f"Train         : {len(X_train)}"
    )

    print(
        f"Test          : {len(X_test)}"
    )

    print(
        f"Features      : {TOUTES_FEATURES}"
    )

    return (
        X_train,
        X_test,
        y_train,
        y_test,
        taux_par_carrier,
        taux_global,
    )


# =============================================================================
# CONSTRUCTION DU PIPELINE XGBOOST
# =============================================================================

def construire_pipeline(
    n_estimators=300,
    max_depth=6,
    learning_rate=0.1,
    subsample=0.8,
    colsample_bytree=0.8,
    scale_pos_weight=1,
    min_child_weight=1,
    gamma=0,
):
    """
    Construit le pipeline complet :

        Variables numériques
            -> imputation médiane

        Variables catégorielles
            -> One-Hot Encoding

        Puis
            -> XGBoost
    """

    preprocesseur = ColumnTransformer(
        transformers=[
            (
                "num",
                SimpleImputer(
                    strategy="median"
                ),
                FEATURES_NUM,
            ),

            (
                "cat",
                OneHotEncoder(
                    handle_unknown="ignore",
                    sparse_output=False,
                ),
                FEATURES_CAT,
            ),
        ],
        remainder="drop",
    )

    modele = XGBClassifier(
        objective="binary:logistic",

        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=learning_rate,

        subsample=subsample,
        colsample_bytree=colsample_bytree,

        scale_pos_weight=scale_pos_weight,

        min_child_weight=min_child_weight,
        gamma=gamma,

        eval_metric="logloss",

        random_state=42,
        n_jobs=-1,
    )

    pipeline = Pipeline(
        steps=[
            (
                "preprocesseur",
                preprocesseur,
            ),

            (
                "modele",
                modele,
            ),
        ]
    )

    return pipeline


# =============================================================================
# TUNING DES HYPERPARAMETRES
# =============================================================================

def tuner_hyperparametres(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    n_iter=40,
):
    """
    Recherche aléatoire des meilleurs hyperparamètres XGBoost.

    La métrique optimisée est le F1 de la classe positive :
        1 = En retard
    """

    pipeline_base = construire_pipeline()

    espace = {
        "modele__n_estimators": [
            200,
            300,
            500,
            700,
        ],

        "modele__max_depth": [
            4,
            5,
            6,
            7,
            8,
        ],

        "modele__learning_rate": [
            0.01,
            0.05,
            0.1,
            0.15,
            0.2,
        ],

        "modele__subsample": [
            0.7,
            0.8,
            0.9,
            1.0,
        ],

        "modele__colsample_bytree": [
            0.6,
            0.7,
            0.8,
            0.9,
            1.0,
        ],

        "modele__min_child_weight": [
            1,
            3,
            5,
            7,
        ],

        "modele__gamma": [
            0,
            0.1,
            0.2,
            0.5,
        ],
    }

    cv = StratifiedKFold(
        n_splits=5,
        shuffle=True,
        random_state=42,
    )

    recherche = RandomizedSearchCV(
        estimator=pipeline_base,
        param_distributions=espace,
        n_iter=n_iter,
        scoring="f1",
        cv=cv,
        random_state=42,
        n_jobs=-1,
        verbose=1,
        error_score="raise",
    )

    print(
        f"\n=== TUNING XGBOOST "
        f"({n_iter} combinaisons) ==="
    )

    recherche.fit(
        X_train,
        y_train,
    )

    print(
        f"\nMeilleur F1 CV : "
        f"{recherche.best_score_ * 100:.2f}%"
    )

    print(
        "\nMeilleurs paramètres :"
    )

    for key, value in recherche.best_params_.items():
        print(
            f"  {key:40s} : {value}"
        )

    return (
        recherche.best_estimator_,
        recherche.best_params_,
        recherche.best_score_,
    )


# =============================================================================
# SEUIL DE DECISION OPTIMAL
# =============================================================================

def trouver_seuil_optimal(
    pipeline,
    X_train,
    y_train,
):
    """
    Recherche le seuil de décision maximisant le F1 sur le train.

    Le seuil 0.50 n'est donc pas imposé.
    """

    probas = pipeline.predict_proba(
        X_train
    )[:, 1]

    precisions, recalls, seuils = (
        precision_recall_curve(
            y_train,
            probas,
        )
    )

    f1s = np.where(
        (precisions + recalls) > 0,
        (
            2
            * precisions
            * recalls
            / (precisions + recalls)
        ),
        0,
    )

    if len(seuils) == 0:
        print(
            "\nImpossible de déterminer un seuil optimal."
        )
        return 0.50

    indice_optimal = np.argmax(
        f1s[:-1]
    )

    seuil_optimal = float(
        seuils[indice_optimal]
    )

    print(
        f"\nSeuil optimal : "
        f"{seuil_optimal:.3f}"
    )

    return seuil_optimal


# =============================================================================
# EVALUATION
# =============================================================================

def evaluer_modele(
    pipeline,
    X_train,
    X_test,
    y_train,
    y_test,
    seuil=0.50,
):
    """
    Évalue le modèle sur train et test.

    Métriques :
        Accuracy
        Precision
        Recall
        F1
        Matrice de confusion
        Cross-validation F1
    """

    # -------------------------------------------------------------------------
    # TRAIN
    # -------------------------------------------------------------------------

    y_train_proba = (
        pipeline
        .predict_proba(X_train)[:, 1]
    )

    y_train_pred = (
        y_train_proba >= seuil
    ).astype(int)

    print(
        "\n=== PERFORMANCE TRAIN ==="
    )

    print(
        f"Accuracy : "
        f"{accuracy_score(y_train, y_train_pred) * 100:.2f}%"
    )

    print(
        f"F1       : "
        f"{f1_score(y_train, y_train_pred, zero_division=0) * 100:.2f}%"
    )

    # -------------------------------------------------------------------------
    # TEST
    # -------------------------------------------------------------------------

    y_pred_proba = (
        pipeline
        .predict_proba(X_test)[:, 1]
    )

    y_pred = (
        y_pred_proba >= seuil
    ).astype(int)

    acc = accuracy_score(
        y_test,
        y_pred,
    )

    prec = precision_score(
        y_test,
        y_pred,
        zero_division=0,
    )

    rec = recall_score(
        y_test,
        y_pred,
        zero_division=0,
    )

    f1 = f1_score(
        y_test,
        y_pred,
        zero_division=0,
    )

    print(
        "\n=== PERFORMANCE TEST ==="
    )

    print(
        f"Accuracy  : {acc * 100:.2f}%"
    )

    print(
        f"Precision : {prec * 100:.2f}%"
    )

    print(
        f"Recall    : {rec * 100:.2f}%"
    )

    print(
        f"F1 Score  : {f1 * 100:.2f}%"
    )

    # -------------------------------------------------------------------------
    # MATRICE DE CONFUSION
    # -------------------------------------------------------------------------

    cm = confusion_matrix(
        y_test,
        y_pred,
    )

    print(
        "\nMatrice de confusion :"
    )

    print(cm)

    print(
        f"  VN={cm[0][0]} "
        f"FP={cm[0][1]} "
        f"FN={cm[1][0]} "
        f"VP={cm[1][1]}"
    )

    # -------------------------------------------------------------------------
    # RAPPORT
    # -------------------------------------------------------------------------

    print(
        "\nRapport de classification :"
    )

    print(
        classification_report(
            y_test,
            y_pred,
            target_names=[
                "À l'heure",
                "En retard",
            ],
            zero_division=0,
        )
    )

    # -------------------------------------------------------------------------
    # CROSS-VALIDATION
    # -------------------------------------------------------------------------

    cv = StratifiedKFold(
        n_splits=5,
        shuffle=True,
        random_state=42,
    )

    scores_cv = cross_val_score(
        pipeline,
        X_train,
        y_train,
        cv=cv,
        scoring="f1",
        n_jobs=-1,
    )

    cv_mean = scores_cv.mean()
    cv_std = scores_cv.std()

    print(
        f"CV F1 (train) : "
        f"{cv_mean * 100:.2f}% "
        f"(+/- {cv_std * 100:.2f}%)"
    )

    print(
        f"Écart CV/test : "
        f"{(cv_mean - f1) * 100:+.2f} pts"
    )

    return {
        "accuracy": round(
            acc * 100,
            2
        ),

        "precision": round(
            prec * 100,
            2
        ),

        "recall": round(
            rec * 100,
            2
        ),

        "f1": round(
            f1 * 100,
            2
        ),

        "cv_f1_mean": round(
            cv_mean * 100,
            2
        ),

        "cv_f1_std": round(
            cv_std * 100,
            2
        ),
    }


# =============================================================================
# IMPORTANCE DES FEATURES
# =============================================================================

def afficher_importance_features(
    pipeline,
    top_n=20,
):
    """
    Affiche l'importance des variables selon XGBoost.

    Contrairement à une régression logistique, XGBoost ne possède pas
    de coefficients 'coef_'.
    """

    preprocesseur = (
        pipeline
        .named_steps["preprocesseur"]
    )

    modele = (
        pipeline
        .named_steps["modele"]
    )

    # -------------------------------------------------------------------------
    # Noms des variables numériques
    # -------------------------------------------------------------------------

    noms_num = FEATURES_NUM.copy()

    # -------------------------------------------------------------------------
    # Noms après One-Hot Encoding
    # -------------------------------------------------------------------------

    encoder = (
        preprocesseur
        .named_transformers_["cat"]
    )

    noms_cat = (
        encoder
        .get_feature_names_out(
            FEATURES_CAT
        )
        .tolist()
    )

    noms_features = (
        noms_num
        + noms_cat
    )

    importances = (
        modele.feature_importances_
    )

    if len(noms_features) != len(importances):
        raise ValueError(
            "Nombre de features différent du nombre "
            "d'importances XGBoost."
        )

    df_importance = pd.DataFrame(
        {
            "feature": noms_features,
            "importance": importances,
        }
    )

    df_importance = (
        df_importance
        .sort_values(
            "importance",
            ascending=False,
        )
        .reset_index(drop=True)
    )

    print(
        f"\n=== TOP {top_n} FEATURES "
        f"XGBOOST ==="
    )

    print(
        df_importance
        .head(top_n)
        .to_string(index=False)
    )

    return df_importance


# =============================================================================
# SAUVEGARDE
# =============================================================================

def sauvegarder_modele(
    pipeline,
    taux_par_carrier,
    taux_global,
    seuil_decision,
):
    """
    Sauvegarde :

        - pipeline XGBoost
        - taux de retard par carrier
        - taux global de retard
        - seuil de décision
    """

    contenu = {
        "pipeline": pipeline,
        "taux_par_carrier": taux_par_carrier,
        "taux_global": taux_global,
        "seuil_decision": seuil_decision,
    }

    joblib.dump(
        contenu,
        MODEL_PATH,
    )

    print(
        f"\n✓ Modèle XGBoost sauvegardé : "
        f"{MODEL_PATH}"
    )

    print(
        f"  Seuil sauvegardé : "
        f"{seuil_decision:.3f}"
    )


# =============================================================================
# CHARGEMENT DU MODELE
# =============================================================================

def charger_modele():
    """
    Recharge le modèle sauvegardé.
    """

    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Modèle introuvable : {MODEL_PATH}\n"
            "Lancez d'abord l'entraînement."
        )

    contenu = joblib.load(
        MODEL_PATH
    )

    pipeline = contenu["pipeline"]

    taux_par_carrier = (
        contenu["taux_par_carrier"]
    )

    taux_global = (
        contenu["taux_global"]
    )

    seuil_decision = (
        contenu.get(
            "seuil_decision",
            0.50,
        )
    )

    return (
        pipeline,
        taux_par_carrier,
        taux_global,
        seuil_decision,
    )


# =============================================================================
# IMPORTANCE DES FEATURES + PREDICTION
# =============================================================================

def predire_retard(
    nouveau_shipment: dict,
):
    """
    Prédit le retard d'un nouveau shipment.

    Les variables dérivées frequency_num, month_sin et month_cos
    sont reconstruites automatiquement.
    """

    (
        pipeline,
        taux_par_carrier,
        taux_global,
        seuil_decision,
    ) = charger_modele()

    # -------------------------------------------------------------------------
    # Frequency
    # -------------------------------------------------------------------------

    frequency_str = str(
        nouveau_shipment.get(
            "frequency",
            "",
        )
    )

    frequency_match = (
        pd.Series([frequency_str])
        .str.extract(
            r"(\d+)",
            expand=False,
        )
        .iloc[0]
    )

    if pd.notna(frequency_match):
        frequency_num = float(
            frequency_match
        )
    else:
        frequency_num = np.nan

    # -------------------------------------------------------------------------
    # Month
    # -------------------------------------------------------------------------

    mois_texte = (
        nouveau_shipment.get(
            "month"
        )
    )

    mois_num = (
        pd.to_datetime(
            pd.Series([mois_texte]),
            format="%B %y",
            errors="coerce",
        )
        .dt.month
        .iloc[0]
    )

    if pd.notna(mois_num):

        month_sin = float(
            np.sin(
                2
                * np.pi
                * mois_num
                / 12
            )
        )

        month_cos = float(
            np.cos(
                2
                * np.pi
                * mois_num
                / 12
            )
        )

    else:

        month_sin = np.nan
        month_cos = np.nan

    # -------------------------------------------------------------------------
    # Carrier
    # -------------------------------------------------------------------------

    carrier = (
        nouveau_shipment.get(
            "carrier",
            "",
        )
        or ""
    )

    carrier_taux = float(
        taux_par_carrier.get(
            carrier,
            taux_global,
        )
    )

    # -------------------------------------------------------------------------
    # Volumes
    # -------------------------------------------------------------------------

    volume_booked = (
        nouveau_shipment.get(
            "volume_booked"
        )
    )

    confirmed_volume = (
        nouveau_shipment.get(
            "confirmed_volume"
        )
    )

    try:
        volume_booked = float(
            volume_booked
        )
    except (
        TypeError,
        ValueError,
    ):
        volume_booked = np.nan

    try:
        confirmed_volume = float(
            confirmed_volume
        )
    except (
        TypeError,
        ValueError,
    ):
        confirmed_volume = np.nan

    volume_ratio = (
        nouveau_shipment.get(
            "volume_ratio_allocated_booked"
        )
    )

    if pd.isna(volume_ratio):

        if (
            pd.notna(volume_booked)
            and volume_booked > 0
            and pd.notna(confirmed_volume)
        ):
            volume_ratio = (
                confirmed_volume
                / volume_booked
            )

        else:
            volume_ratio = np.nan

    # -------------------------------------------------------------------------
    # Construction des données
    # -------------------------------------------------------------------------

    X_nouveau = pd.DataFrame(
        [
            {
                "transit_time":
                    nouveau_shipment.get(
                        "transit_time",
                        np.nan,
                    ),

                "frequency_num":
                    frequency_num,

                "volume_ratio_allocated_booked":
                    volume_ratio,

                "volume_booked":
                    volume_booked,

                "confirmed_volume":
                    confirmed_volume,

                "carrier_taux_retard":
                    carrier_taux,

                "month_sin":
                    month_sin,

                "month_cos":
                    month_cos,

                "etd_precipitation_mm":
                    nouveau_shipment.get(
                        "etd_precipitation_mm",
                        np.nan,
                    ),

                "etd_wind_speed_kmh":
                    nouveau_shipment.get(
                        "etd_wind_speed_kmh",
                        np.nan,
                    ),

                "etd_temperature_max":
                    nouveau_shipment.get(
                        "etd_temperature_max",
                        np.nan,
                    ),

                "etd_weather_code":
                    nouveau_shipment.get(
                        "etd_weather_code",
                        np.nan,
                    ),

                "eta_precipitation_mm":
                    nouveau_shipment.get(
                        "eta_precipitation_mm",
                        np.nan,
                    ),

                "eta_wind_speed_kmh":
                    nouveau_shipment.get(
                        "eta_wind_speed_kmh",
                        np.nan,
                    ),

                "eta_temperature_max":
                    nouveau_shipment.get(
                        "eta_temperature_max",
                        np.nan,
                    ),

                "eta_weather_code":
                    nouveau_shipment.get(
                        "eta_weather_code",
                        np.nan,
                    ),

                "carrier":
                    carrier,

                "port_chargement":
                    nouveau_shipment.get(
                        "port_chargement",
                        np.nan,
                    ),

                "port_dechargement":
                    nouveau_shipment.get(
                        "port_dechargement",
                        np.nan,
                    ),

                "pays_destination":
                    nouveau_shipment.get(
                        "pays_destination",
                        np.nan,
                    ),
            }
        ]
    )

    # -------------------------------------------------------------------------
    # Prediction
    # -------------------------------------------------------------------------

    probabilite = float(
        pipeline
        .predict_proba(
            X_nouveau
        )[0][1]
    )

    prediction = int(
        probabilite
        >= seuil_decision
    )

    # -------------------------------------------------------------------------
    # Niveau de risque
    # -------------------------------------------------------------------------

    if probabilite < 0.35:

        niveau_risque = "Faible"

    elif probabilite < 0.65:

        niveau_risque = "Moyen"

    else:

        niveau_risque = "Élevé"

    return {
        "prediction": prediction,

        "probabilite_retard":
            round(
                probabilite * 100,
                1,
            ),

        "niveau_risque":
            niveau_risque,

        "label":
            (
                "En retard"
                if prediction == 1
                else "À l'heure"
            ),

        "seuil_utilise":
            round(
                seuil_decision,
                3,
            ),
    }


# =============================================================================
# POINT D'ENTREE
# =============================================================================

if __name__ == "__main__":

    print("=" * 60)

    print(
        "  ENTRAÎNEMENT : XGBOOST + MÉTÉO"
    )

    print(
        "  Split aléatoire stratifié 80/20"
    )

    print("=" * 60)

    # -------------------------------------------------------------------------
    # 1. Chargement
    # -------------------------------------------------------------------------

    df_raw = get_all_shipments()

    # -------------------------------------------------------------------------
    # 2. Préparation
    # -------------------------------------------------------------------------

    (
        X_train,
        X_test,
        y_train,
        y_test,
        taux_par_carrier,
        taux_global,
    ) = preparer_donnees(
        df_raw
    )

    # -------------------------------------------------------------------------
    # 3. Tuning
    # -------------------------------------------------------------------------

    (
        pipeline,
        best_params,
        best_cv,
    ) = tuner_hyperparametres(
        X_train,
        y_train,
        n_iter=40,
    )

    # -------------------------------------------------------------------------
    # 4. Seuil optimal
    # -------------------------------------------------------------------------

    seuil = trouver_seuil_optimal(
        pipeline,
        X_train,
        y_train,
    )

    # -------------------------------------------------------------------------
    # 5. Evaluation
    # -------------------------------------------------------------------------

    metriques = evaluer_modele(
        pipeline,
        X_train,
        X_test,
        y_train,
        y_test,
        seuil=seuil,
    )

    # -------------------------------------------------------------------------
    # 6. Importance des variables
    # -------------------------------------------------------------------------

    afficher_importance_features(
        pipeline,
        top_n=20,
    )

    # -------------------------------------------------------------------------
    # 7. Sauvegarde
    # -------------------------------------------------------------------------

    sauvegarder_modele(
        pipeline,
        taux_par_carrier,
        taux_global,
        seuil,
    )

    # -------------------------------------------------------------------------
    # 8. Résumé final
    # -------------------------------------------------------------------------

    print(
        "\n" + "=" * 60
    )

    print(
        "  RÉSUMÉ FINAL XGBOOST"
    )

    print(
        f"  Accuracy  : "
        f"{metriques['accuracy']}%"
    )

    print(
        f"  Precision : "
        f"{metriques['precision']}%"
    )

    print(
        f"  Recall    : "
        f"{metriques['recall']}%"
    )

    print(
        f"  F1 Score  : "
        f"{metriques['f1']}%"
    )

    print(
        f"  CV F1     : "
        f"{metriques['cv_f1_mean']}% "
        f"(+/- {metriques['cv_f1_std']}%)"
    )

    print(
        f"  Seuil     : "
        f"{seuil:.3f}"
    )

    print(
        "=" * 60
    )