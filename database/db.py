"""
db.py — Couche d'accès aux données avec SQLAlchemy
"""

import os
import bcrypt
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime

from sqlalchemy import (
    create_engine, Column, Integer, String, Float,
    Date, DateTime, ForeignKey, Text, UniqueConstraint
)
from sqlalchemy.orm import (
    sessionmaker, DeclarativeBase, relationship, Session
)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/logistique.db")

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=False,
    )
else:
    engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class Role(Base):
    __tablename__ = "role"
    id       = Column(Integer, primary_key=True, autoincrement=True)
    nom_role = Column(String, nullable=False, unique=True)


class User(Base):
    __tablename__ = "user"
    id                  = Column(Integer, primary_key=True, autoincrement=True)
    nom                 = Column(String,  nullable=False)
    prenom              = Column(String,  nullable=False)
    login               = Column(String,  nullable=False, unique=True)
    password_hash       = Column(String,  nullable=False)
    statut              = Column(String,  nullable=False, default="actif")
    tentatives_echouees = Column(Integer, nullable=False, default=0)
    doit_changer_mdp    = Column(Integer, nullable=False, default=1)
    role_id             = Column(Integer, ForeignKey("role.id"), nullable=False)


class Vessel(Base):
    __tablename__ = "vessel"
    id      = Column(Integer, primary_key=True, autoincrement=True)
    nom     = Column(String,  nullable=False)
    carrier = Column(String,  nullable=False)
    __table_args__ = (UniqueConstraint("nom", "carrier", name="uq_vessel_nom_carrier"),)

class Shipment(Base):
    __tablename__ = "shipment"
    id                            = Column(Integer, primary_key=True, autoincrement=True)
    port_chargement               = Column(String, nullable=False)
    port_dechargement             = Column(String, nullable=False)
    pays_destination              = Column(String, nullable=False)
    etd                           = Column(Date)
    atd                           = Column(Date)
    eta                           = Column(Date)
    ata                           = Column(Date)
    incoterm                      = Column(String)
    volume_booked                 = Column(Float)
    confirmed_volume              = Column(Float)
    charged_volume                = Column(Float)
    transit_time                  = Column(Integer)
    frequency                     = Column(String)
    month                         = Column(String)
    year                          = Column(Integer)
    shipment_status               = Column(String, nullable=False, default="Normal")
    type_annulation               = Column(String, nullable=False, default="Non annulé")
    transit_time_reel             = Column(Float)
    eta_deviation                 = Column(Float)
    etd_deviation                 = Column(Float)
    is_delayed                    = Column(Float)
    volume_ratio_loaded           = Column(Float)
    volume_ratio_allocated_booked = Column(Float)
    niveau_retard                 = Column(String)
    vessel_id                     = Column(Integer, ForeignKey("vessel.id"), nullable=False)
    createur_id                   = Column(Integer, ForeignKey("user.id"),   nullable=False)
    created_at                    = Column(DateTime, nullable=True)
    updated_at                    = Column(DateTime, nullable=True, onupdate=datetime.now)
    updated_by_id                 = Column(Integer, ForeignKey("user.id"), nullable=True)
    deleted_at    = Column(DateTime, nullable=True)
    deleted_by_id = Column(Integer, ForeignKey("user.id"), nullable=True)

class Message(Base):
    __tablename__ = "message"
    id              = Column(Integer,  primary_key=True, autoincrement=True)
    contenu         = Column(Text,     nullable=False)
    date_envoi      = Column(DateTime, nullable=False, default=datetime.now)
    lu              = Column(Integer,  nullable=False, default=0)
    expediteur_id   = Column(Integer,  ForeignKey("user.id"),     nullable=False)
    destinataire_id = Column(Integer,  ForeignKey("user.id"),     nullable=False)
    shipment_id     = Column(Integer,  ForeignKey("shipment.id"), nullable=True)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    if DATABASE_URL.startswith("sqlite"):
        Path("data").mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    print("✅ Base de données initialisée avec succès.")


# ─────────────────────────────────────────────────────────────────────────────
# OPÉRATEURS PAR DÉFAUT (Control Tower Team)
# ─────────────────────────────────────────────────────────────────────────────

OPERATEURS = [
    {"nom": "Benali",    "prenom": "Karim",   "login": "benalikarim@gmail.com"},
    {"nom": "Idrissi",   "prenom": "Sara",    "login": "idrissisara@gmail.com"},
    {"nom": "Tahiri",    "prenom": "Youssef", "login": "tahiriyoussef@gmail.com"},
    {"nom": "Cherkaoui", "prenom": "Nadia",   "login": "cherkaouinadia@gmail.com"},
    {"nom": "Ouali",     "prenom": "Mehdi",   "login": "oualimehdi@gmail.com"},
    {"nom": "Zouaki",    "prenom": "Fatima",  "login": "zouakifatima@gmail.com"},
]


def inserer_donnees_initiales():
    db: Session = SessionLocal()
    try:
        # ── Rôles ─────────────────────────────────────────────────────────────
        if db.query(Role).count() == 0:
            db.add_all([
                Role(nom_role="Administrateur"),
                Role(nom_role="Control Tower Team"),
                Role(nom_role="Performance Managers Team"),
            ])
            db.commit()
            print("✅ Rôles insérés.")

        # ── Admin ─────────────────────────────────────────────────────────────
        if not db.query(User).filter(User.login == "admin").first():
            mdp = os.getenv("ADMIN_PASSWORD")
            if not mdp:
                raise ValueError("ADMIN_PASSWORD manquant dans .env")
            password_hash = bcrypt.hashpw(mdp.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            role_admin = db.query(Role).filter(Role.nom_role == "Administrateur").first()
            db.add(User(
                nom="Admin", prenom="Système", login="admin",
                password_hash=password_hash, statut="actif",
                role_id=role_admin.id, doit_changer_mdp=1,
            ))
            db.commit()
            print("✅ Administrateur par défaut créé.")

        # ── Opérateurs (Control Tower Team) ───────────────────────────────────
        role_op = db.query(Role).filter(Role.nom_role == "Control Tower Team").first()
        mdp_defaut_str = os.getenv("OPERATEUR_DEFAULT_PASSWORD")
        if not mdp_defaut_str:
            raise ValueError("OPERATEUR_DEFAULT_PASSWORD manquant dans .env")
        mdp_defaut = bcrypt.hashpw(
            mdp_defaut_str.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        nb_op_crees = 0
        for op in OPERATEURS:
            if not db.query(User).filter(User.login == op["login"]).first():
                db.add(User(
                    nom=op["nom"], prenom=op["prenom"],
                    login=op["login"], password_hash=mdp_defaut,
                    statut="actif", role_id=role_op.id, doit_changer_mdp=1,
                ))
                nb_op_crees += 1
        if nb_op_crees:
            db.commit()
            print(f"✅ {nb_op_crees} opérateur(s) créé(s).")

    finally:
        db.close()


def _convertir_dates(df: pd.DataFrame) -> pd.DataFrame:
    for col in ["ETD", "ATD", "ETA", "ATA"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
    return df


def _get_ou_creer_vessel(db: Session, nom: str, carrier: str) -> int:
    vessel = db.query(Vessel).filter(Vessel.nom == nom, Vessel.carrier == carrier).first()
    if vessel:
        return vessel.id
    nouveau = Vessel(nom=nom, carrier=carrier)
    db.add(nouveau)
    db.flush()
    return nouveau.id


def _calculer_month_year(etd) -> tuple[str | None, int | None]:
    """Calcule month ('July 24') et year (2024) depuis une date ETD."""
    if etd is None:
        return None, None
    try:
        ts = pd.Timestamp(etd)
        if pd.isna(ts):
            return None, None
        return ts.strftime("%B %y"), int(ts.year)
    except Exception:
        return None, None


def charger_donnees_historiques(filepath: str = "data/maritime_dataset_nettoye.xlsx"):
    db: Session = SessionLocal()
    try:
        if db.query(Shipment).count() > 0:
            print("⚠️  Des données historiques existent déjà. Chargement ignoré.")
            return

        df = pd.read_excel(filepath)
        print("Colonnes réelles du fichier:", list(df.columns))
        print(f"📂 Fichier chargé : {len(df)} lignes")
        print(f"    Colonnes : {list(df.columns)}")
        df = _convertir_dates(df)

        # ── Mapping opérateurs : "Prénom Nom" → user.id ─────────────────────
        # La colonne "Operateur" du dataset contient "Karim Benali", "Sara Idrissi", etc.
        # On construit un dict { "Karim Benali": user.id, ... } depuis la table user
        operateurs = (
            db.query(User)
            .join(Role)
            .filter(Role.nom_role == "Control Tower Team")
            .all()
        )
        # Clé : "Prénom Nom" (même format que la colonne Operateur du fichier Excel)
        operateur_map = {
            f"{op.prenom} {op.nom}": op.id
            for op in operateurs
        }
        # Fallback : admin si aucun opérateur ou valeur inconnue dans le fichier
        fallback_id = db.query(User).filter(User.login == "admin").first().id
        print(f"    {len(operateur_map)} opérateur(s) mappés : {list(operateur_map.keys())}")

        colonnes_map = {
    "Port of Loading":              "port_chargement",
    "Port of Discharge":            "port_dechargement",
    "Port of Discharge country":    "pays_destination",
    "ETD":                          "etd",
    "ATD":                          "atd",
    "ETA":                          "eta",
    "ATA":                          "ata",
    "Incoterm":                     "incoterm",
    "Volume Booked":                "volume_booked",
    "Confirmed Volume":             "confirmed_volume",
    "Charged Volume":               "charged_volume",
    "Transit_Time":                 "transit_time",
    "Frequency":                    "frequency",
    "Month":                        "month",
    "Year":                         "year",
    "shipment_status":              "shipment_status",
    "type_annulation":              "type_annulation",
    "Transit_Time_Reel":            "transit_time_reel",
    "eta_deviation":                "eta_deviation",
    "etd_deviation":                "etd_deviation",
    "is_delayed":                   "is_delayed",
    "volume_ratio_loaded":          "volume_ratio_loaded",
    # ✅ FIX: nom exact de la colonne dans le fichier ETL
    "volume_ratio_allocated": "volume_ratio_allocated_booked",
    "niveau_retard":                "niveau_retard",
}

        lignes_inserees = 0
        lignes_ignorees = 0

        for _, row in df.iterrows():
            try:
                nom_vessel  = str(row.get("Vessel", "")).strip()
                nom_carrier = str(row.get("Carrier", "")).strip()

                if not nom_vessel or nom_vessel == "nan":
                    lignes_ignorees += 1
                    continue

                vessel_id = _get_ou_creer_vessel(db, nom_vessel, nom_carrier)

                valeurs = {}
                for col_excel, col_db in colonnes_map.items():
                    val = row.get(col_excel, None)
                    if val is not None and not isinstance(val, str):
                        try:
                            if pd.isna(val):
                                val = None
                        except (TypeError, ValueError):
                            pass
                    valeurs[col_db] = val

                # ✅ Calculer year depuis ETD (month peut déjà être dans le fichier ETL)
                # ✅ Calcul de Month/Year :
# - si Month/Year sont déjà présents dans le fichier Excel, on les conserve
# - sinon, on les calcule depuis ETD (utile pour les nouveaux shipments)

                month_calc, year_calc = _calculer_month_year(valeurs.get("etd"))

                if not valeurs.get("month"):
                   valeurs["month"] = month_calc

                if valeurs.get("year") is None:
                   valeurs["year"] = year_calc

                # ✅ Mapping exact depuis la colonne "Operateur" du fichier Excel
                # Format: "Karim Benali" → cherche dans operateur_map → user.id
                nom_operateur = str(row.get("Operateur", "")).strip()
                createur_id = operateur_map.get(nom_operateur, fallback_id)
                if nom_operateur and nom_operateur not in operateur_map:
                    print(f"⚠️  Opérateur inconnu : {nom_operateur!r} → fallback admin")

                shipment = Shipment(**valeurs, vessel_id=vessel_id, createur_id=createur_id)
                db.add(shipment)
                db.flush()
                lignes_inserees += 1

            except Exception as e:
                db.rollback()
                lignes_ignorees += 1
                print(f"⚠️  Ligne ignorée : {e}")
                continue

        db.commit()
        print(f"✅ {lignes_inserees} insérées, {lignes_ignorees} ignorées.")

    except Exception as e:
        db.rollback()
        print(f"❌ Erreur : {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("🚀 Initialisation de la base de données...")
    init_db()
    inserer_donnees_initiales()
    charger_donnees_historiques()
    print(f"\n✅ Initialisation complète ! Base : {DATABASE_URL}")

    db: Session = SessionLocal()
    try:
        for model, nom in [(Role,"role"),(User,"user"),(Vessel,"vessel"),(Shipment,"shipment"),(Message,"message")]:
            print(f"   {nom:12} → {db.query(model).count():5} lignes")
    finally:
        db.close()