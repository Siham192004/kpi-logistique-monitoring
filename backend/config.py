from pathlib import Path
from dotenv import load_dotenv
import os

# ── Charge les variables depuis .env ─────────────────────────────────────────
load_dotenv()

# ── Racine du projet ──────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent

# ── Base de données ───────────────────────────────────────────────────────────
DB_PATH = BASE_DIR / "data" / "logistique.db"

# ── Modèle ML ─────────────────────────────────────────────────────────────────
MODEL_PATH = BASE_DIR / "models" / "random_forest.pkl"

# ── Sécurité JWT ──────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "changeme")
ALGORITHM  = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60))

# ── CORS ──────────────────────────────────────────────────────────────────────
ALLOWED_ORIGINS = ["http://localhost:5173"]