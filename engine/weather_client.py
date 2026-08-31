"""
weather_client.py — Récupération météo historique (entraînement) et temps réel (prédiction)
API      : Open-Meteo (gratuite, sans clé)
Méthode  : BATCH — un seul appel par port pour toute la période → zéro rate limiting
Géocodage: Nominatim (geopy) — fallback automatique pour les ports inconnus
"""

import numpy as np
import pandas as pd
import requests
from functools import lru_cache
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from datetime import date as date_today

# ── Coordonnées GPS des ports connus ──────────────────────────────────────────
PORTS_GPS = {
    # Ports de chargement
    "Tanger Med":    (35.8840,  -5.5030),
    "Casablanca":    (33.5992,  -7.6150),
    "Nador":         (35.1740,  -2.9330),
    # Ports de déchargement
    "Civitavecchia": (42.0939,  11.7944),
    "Livorno":       (43.5484,  10.3083),
    "Barcelona":     (41.3500,   2.1833),
    "Valencia":      (39.4561,  -0.3274),
    "Sfax":          (34.7400,  10.7600),
    "Durban":        (-29.8579, 31.0292),
    "Dammam":        (26.4367,  50.1033),
    "Grimsby":       (53.5675,  -0.0800),
    "Naples":        (40.8518,  14.2681),
    "Alexandria":    (31.2001,  29.9187),
    "Istanbul":      (41.0082,  28.9784),
    "Rades":         (36.7700,  10.2800),
    "Hamburg":       (53.5500,   9.9700),
    "Bremerhaven":   (53.5500,   8.5800),
    "Rotterdam":     (51.9244,   4.4777),
    "Port Said":     (31.2565,  32.2841),
    "Mersin":        (36.7956,  34.6370),
    "Doha":          (25.2854,  51.5310),
    "Jeddah":        (21.4858,  39.1925),
    "Genoa":         (44.4056,   8.9463),
    "Vigo":          (42.2406,  -8.7207),
    "Amsterdam":     (52.3676,   4.9041),
    "Southampton":   (50.9097,  -1.4044),
    "Izmir":         (38.4192,  27.1287),
    "Tin Can Island":(6.4281,    3.3144),
    "Lagos":         (6.4550,    3.3841),
    "Cape Town":     (-33.9249, 18.4241),
    "Bilbao":        (43.2630,  -2.9350),
    "Bristol":       (51.4545,  -2.5879),
    "Sokhna":        (29.9500,  32.3500),
    "Apapa":         (6.4474,    3.3903),
    "Bizerte":       (37.2744,   9.8739),
}

# Cache en mémoire pour éviter de géocoder le même port deux fois
_geocode_cache: dict[str, tuple[float, float] | None] = {}

WEATHER_VARS = "precipitation_sum,wind_speed_10m_max,temperature_2m_max,weather_code"


# ═══════════════════════════════════════════════════════════════════════════
# GÉOCODAGE AUTOMATIQUE
# ═══════════════════════════════════════════════════════════════════════════

def get_coords(port: str) -> tuple[float, float] | None:
    """
    Retourne les coordonnées GPS d'un port.
    1. Cherche dans le dictionnaire statique PORTS_GPS (instantané)
    2. Si inconnu → géocode automatiquement via Nominatim (OpenStreetMap)
    3. Met en cache le résultat pour ne pas répéter l'appel
    """
    if not port:
        return None
    if port in PORTS_GPS:
        return PORTS_GPS[port]
    if port in _geocode_cache:
        return _geocode_cache[port]
    try:
        geolocator = Nominatim(user_agent="logistique_meteo_app", timeout=10)
        location   = geolocator.geocode(f"port {port}")
        if location:
            coords = (location.latitude, location.longitude)
            _geocode_cache[port] = coords
            print(f"[Géocodage] {port} → lat={coords[0]:.4f}, lon={coords[1]:.4f}")
            return coords
        else:
            print(f"[Géocodage] Port introuvable : '{port}' → météo sera NaN")
            _geocode_cache[port] = None
            return None
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        print(f"[Géocodage] Erreur pour '{port}' : {e} → météo sera NaN")
        _geocode_cache[port] = None
        return None


# ═══════════════════════════════════════════════════════════════════════════
# MÉTÉO HISTORIQUE BATCH (pour entraînement)
# ═══════════════════════════════════════════════════════════════════════════

def fetch_weather_batch(
    lat: float,
    lon: float,
    date_debut: str,
    date_fin: str,
) -> pd.DataFrame:
    """
    Récupère la météo pour toute une période en UN SEUL appel API.
    Retourne un DataFrame indexé par date (format 'YYYY-MM-DD').
    Zéro rate limiting car 1 appel par port au lieu de 1 appel par shipment.
    """
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude":   lat,
        "longitude":  lon,
        "start_date": date_debut,
        "end_date":   date_fin,
        "daily":      WEATHER_VARS,
        "timezone":   "auto",
    }
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()["daily"]
        return pd.DataFrame({
            "precipitation_mm": data["precipitation_sum"],
            "wind_speed_kmh":   data["wind_speed_10m_max"],
            "temperature_max":  data["temperature_2m_max"],
            "weather_code":     data["weather_code"],
        }, index=pd.to_datetime(data["time"]).strftime("%Y-%m-%d"))
    except Exception as e:
        print(f"  [Batch météo] Erreur : {e}")
        return pd.DataFrame()


def enrich_dataset_with_weather(df: pd.DataFrame) -> pd.DataFrame:
    """
    Enrichit le dataset avec la météo historique via appels BATCH.

    Stratégie :
      - 1 appel API par port unique (35 ports max) au lieu de 1 par shipment (1785)
      - Toute la période 2024-2025 récupérée en une fois par port
      - Jointure par (port, date) → zéro NaN lié au rate limiting

    ETD → météo au port de chargement
    ETA → météo au port de déchargement
    """
    df = df.copy()

    noms_originaux = list(df.columns)

    # ✅ FIX: mapper les colonnes brutes vers les noms attendus par la fonction
    # Supporte aussi bien la dataset brute (ETD, Port of Loading)
    # que la dataset après ETL (etd, port_chargement)
    COL_MAP = {
        "ETD":                    "etd",
        "ETA":                    "eta",
        "Port of Loading":        "port_chargement",
        "Port of Discharge":      "port_dechargement",
    }
    COL_MAP_INVERSE = {v: k for k, v in COL_MAP.items()}
    df = df.rename(columns=COL_MAP)

    # ── Plage de dates globale ─────────────────────────────────────────────
    toutes_dates = pd.to_datetime(
        pd.concat([
            pd.Series(df["etd"].dropna()),
            pd.Series(df["eta"].dropna()),
        ]),
        errors="coerce",
    ).dropna()

    date_debut = toutes_dates.min().strftime("%Y-%m-%d")
    date_fin_max = (pd.Timestamp(date_today.today()) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    date_fin     = min(toutes_dates.max().strftime("%Y-%m-%d"), date_fin_max)
    print(f"  Période météo : {date_debut} → {date_fin}")

    # ── Récupération batch par port unique ────────────────────────────────
    tous_ports = list(set(
        df["port_chargement"].dropna().tolist() +
        df["port_dechargement"].dropna().tolist()
    ))

    weather_cache: dict[str, pd.DataFrame] = {}
    for i, port in enumerate(tous_ports, 1):
        coords = get_coords(port)
        if coords:
            print(f"  [{i}/{len(tous_ports)}] Météo batch : {port}...")
            weather_cache[port] = fetch_weather_batch(*coords, date_debut, date_fin)
        else:
            weather_cache[port] = pd.DataFrame()

    print(f"  ✓ {len(weather_cache)} ports récupérés en batch")

    # ── Jointure par ligne ────────────────────────────────────────────────
    records = []
    for _, row in df.iterrows():
        r = {}

        # ETD — port de chargement
        port_load = row.get("port_chargement", "")
        etd_date  = pd.to_datetime(row.get("etd"), errors="coerce")
        etd_str   = etd_date.strftime("%Y-%m-%d") if pd.notna(etd_date) else None
        df_load   = weather_cache.get(port_load, pd.DataFrame())

        if etd_str and not df_load.empty and etd_str in df_load.index:
            row_w = df_load.loc[etd_str]
            r["etd_precipitation_mm"] = row_w["precipitation_mm"]
            r["etd_wind_speed_kmh"]   = row_w["wind_speed_kmh"]
            r["etd_temperature_max"]  = row_w["temperature_max"]
            r["etd_weather_code"]     = row_w["weather_code"]
        else:
            r.update({k: np.nan for k in [
                "etd_precipitation_mm", "etd_wind_speed_kmh",
                "etd_temperature_max",  "etd_weather_code",
            ]})

        # ETA — port de déchargement
        port_disch = row.get("port_dechargement", "")
        eta_date   = pd.to_datetime(row.get("eta"), errors="coerce")
        eta_str    = eta_date.strftime("%Y-%m-%d") if pd.notna(eta_date) else None
        df_disch   = weather_cache.get(port_disch, pd.DataFrame())

        if eta_str and not df_disch.empty and eta_str in df_disch.index:
            row_w = df_disch.loc[eta_str]
            r["eta_precipitation_mm"] = row_w["precipitation_mm"]
            r["eta_wind_speed_kmh"]   = row_w["wind_speed_kmh"]
            r["eta_temperature_max"]  = row_w["temperature_max"]
            r["eta_weather_code"]     = row_w["weather_code"]
        else:
            r.update({k: np.nan for k in [
                "eta_precipitation_mm", "eta_wind_speed_kmh",
                "eta_temperature_max",  "eta_weather_code",
            ]})

        records.append(r)

    weather_df = pd.DataFrame(records, index=df.index)
    nan_count  = weather_df["etd_precipitation_mm"].isna().sum()
    print(f"  ✓ Enrichissement météo terminé — NaN restants : {nan_count}/{len(df)}")
    result = pd.concat([df, weather_df], axis=1)
    result = result.rename(columns=COL_MAP_INVERSE)
    return result



# ═══════════════════════════════════════════════════════════════════════════
# MÉTÉO TEMPS RÉEL (pour prédiction)
# ═══════════════════════════════════════════════════════════════════════════

def fetch_weather_historical(lat: float, lon: float, date: str) -> dict:
    """Appel unitaire historique — utilisé en fallback pour les prédictions."""
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude":   lat,
        "longitude":  lon,
        "start_date": date,
        "end_date":   date,
        "daily":      WEATHER_VARS,
        "timezone":   "auto",
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()["daily"]
        return {
            "precipitation_mm": data["precipitation_sum"][0],
            "wind_speed_kmh":   data["wind_speed_10m_max"][0],
            "temperature_max":  data["temperature_2m_max"][0],
            "weather_code":     data["weather_code"][0],
        }
    except Exception:
        return {
            "precipitation_mm": np.nan,
            "wind_speed_kmh":   np.nan,
            "temperature_max":  np.nan,
            "weather_code":     np.nan,
        }


@lru_cache(maxsize=256)
def fetch_weather_forecast(lat: float, lon: float, date: str) -> dict:
    """
    Météo prévisionnelle pour une date future (16 jours max).
    Fallback sur historique année précédente si hors fenêtre.
    """
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude":   lat,
        "longitude":  lon,
        "start_date": date,
        "end_date":   date,
        "daily":      WEATHER_VARS,
        "timezone":   "auto",
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()["daily"]
        return {
            "precipitation_mm": data["precipitation_sum"][0],
            "wind_speed_kmh":   data["wind_speed_10m_max"][0],
            "temperature_max":  data["temperature_2m_max"][0],
            "weather_code":     data["weather_code"][0],
        }
    except Exception:
        fallback_date = (
            pd.to_datetime(date) - pd.DateOffset(years=1)
        ).strftime("%Y-%m-%d")
        return fetch_weather_historical(lat, lon, fallback_date)


def get_weather_for_prediction(
    port_chargement: str,
    port_dechargement: str,
    etd: str,
    eta: str,
) -> dict:
    """
    Retourne les 8 features météo pour une prédiction en temps réel.
    Gère automatiquement les nouveaux ports via géocodage Nominatim.
    Utilisé dans predire_retard() de predictor.py.
    """
    result = {}

    coords_load = get_coords(port_chargement)
    if coords_load and etd:
        w = fetch_weather_forecast(*coords_load, etd)
        result["etd_precipitation_mm"] = w["precipitation_mm"]
        result["etd_wind_speed_kmh"]   = w["wind_speed_kmh"]
        result["etd_temperature_max"]  = w["temperature_max"]
        result["etd_weather_code"]     = w["weather_code"]
    else:
        result.update({k: np.nan for k in [
            "etd_precipitation_mm", "etd_wind_speed_kmh",
            "etd_temperature_max",  "etd_weather_code",
        ]})

    coords_disch = get_coords(port_dechargement)
    if coords_disch and eta:
        w = fetch_weather_forecast(*coords_disch, eta)
        result["eta_precipitation_mm"] = w["precipitation_mm"]
        result["eta_wind_speed_kmh"]   = w["wind_speed_kmh"]
        result["eta_temperature_max"]  = w["temperature_max"]
        result["eta_weather_code"]     = w["weather_code"]
    else:
        result.update({k: np.nan for k in [
            "eta_precipitation_mm", "eta_wind_speed_kmh",
            "eta_temperature_max",  "eta_weather_code",
        ]})

    return result