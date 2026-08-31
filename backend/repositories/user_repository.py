"""
user_repository.py — Accès aux données : tables user et role (SQLAlchemy)

Contient UNIQUEMENT les requêtes sur les tables user et role.
Toute la logique métier est dans auth_service.py / admin_service.py.

Architecture :
    Router → Service → Repository → SessionLocal (SQLAlchemy)

Différences vs version sqlite3 :
- get_connection() / cursor  →  Session SQLAlchemy injectée en paramètre
- dict(row)                  →  objet ORM sérialisé manuellement via _user_to_dict()
- pd.read_sql_query()        →  query ORM + pd.DataFrame([_user_to_dict(...)])
- Chaque fonction reçoit `db: Session` — pas de connexion ouverte/fermée ici
"""

import bcrypt
import pandas as pd
from sqlalchemy.orm import Session

from backend.models.user import Role, User


# ─────────────────────────────────────────────
# HELPERS DE SÉRIALISATION
# ─────────────────────────────────────────────

def _user_to_dict(u: User) -> dict:
    """Convertit un objet User ORM en dict plat (avec nom_role dénormalisé)."""
    return {
        "id":                  u.id,
        "nom":                 u.nom,
        "prenom":              u.prenom,
        "login":               u.login,
        "password_hash":       u.password_hash,
        "statut":              u.statut,
        "tentatives_echouees": u.tentatives_echouees,
        "doit_changer_mdp":    u.doit_changer_mdp,
        "role_id":             u.role_id,
        "nom_role":            u.role.nom_role if u.role else None,
    }


def _role_to_dict(r: Role) -> dict:
    return {"id": r.id, "nom_role": r.nom_role}


# ═══════════════════════════════════════════════════════════════════════════════
# LECTURE — USER
# ═══════════════════════════════════════════════════════════════════════════════

def get_user_by_login(db: Session, login: str) -> dict | None:
    """
    Retourne un utilisateur par son login avec son rôle.
    Retourne None si introuvable.
    Utilisé par : auth_service (login, vérification token)
    """
    user = (
        db.query(User)
        .join(Role)
        .filter(User.login == login)
        .first()
    )
    return _user_to_dict(user) if user else None


def get_user_by_id(db: Session, user_id: int) -> dict | None:
    """
    Retourne un utilisateur par son id avec son rôle.
    Retourne None si introuvable.
    Utilisé par : auth_service (vérification token JWT)
    """
    user = (
        db.query(User)
        .join(Role)
        .filter(User.id == user_id)
        .first()
    )
    return _user_to_dict(user) if user else None


def get_all_users(db: Session) -> pd.DataFrame:
    """
    Retourne tous les utilisateurs avec leur rôle.
    Utilisé par : admin_service (liste des comptes)
    """
    users = db.query(User).join(Role).order_by(User.id).all()
    return pd.DataFrame([_user_to_dict(u) for u in users])


def login_exists(db: Session, login: str) -> bool:
    """
    Vérifie si un login est déjà utilisé.
    Utilisé par : admin_service (création de compte)
    """
    return db.query(User).filter(User.login == login).count() > 0


# ═══════════════════════════════════════════════════════════════════════════════
# CRÉATION — USER
# ═══════════════════════════════════════════════════════════════════════════════

def insert_user(
    db: Session,
    nom: str,
    prenom: str,
    login: str,
    password: str,
    role_id: int,
) -> int:
    """
    Crée un nouveau compte utilisateur avec mot de passe hashé.
    doit_changer_mdp = 1 par défaut.
    Retourne l'id du nouvel utilisateur.
    Utilisé par : admin_service (création de compte)
    """
    password_hash = bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")

    user = User(
        nom=nom,
        prenom=prenom,
        login=login,
        password_hash=password_hash,
        statut="actif",
        role_id=role_id,
        doit_changer_mdp=1,
    )
    db.add(user)
    db.flush()   # obtenir l'id sans commit (le commit reste dans le service)
    return user.id


# ═══════════════════════════════════════════════════════════════════════════════
# MISE À JOUR — STATUT / TENTATIVES / MOT DE PASSE / RÔLE
# ═══════════════════════════════════════════════════════════════════════════════

def update_statut(db: Session, user_id: int, nouveau_statut: str) -> bool:
    """
    Met à jour le statut d'un utilisateur (actif / inactif / bloqué).
    Retourne True si mis à jour, False si introuvable.
    Utilisé par : admin_service (désactiver / réactiver / bloquer)
    """
    rows = (
        db.query(User)
        .filter(User.id == user_id)
        .update({"statut": nouveau_statut})
    )
    return rows > 0


def incrementer_tentatives(db: Session, login: str) -> None:
    """
    Incrémente le compteur de tentatives échouées de +1.
    Appelé après chaque échec de connexion.
    Utilisé par : auth_service (login)
    """
    db.query(User).filter(User.login == login).update(
        {"tentatives_echouees": User.tentatives_echouees + 1}
    )


def reset_tentatives(db: Session, login: str) -> None:
    """
    Remet le compteur de tentatives échouées à 0.
    Appelé après une connexion réussie ou un déverrouillage.
    Utilisé par : auth_service (login réussi), admin_service (déverrouillage)
    """
    db.query(User).filter(User.login == login).update(
        {"tentatives_echouees": 0}
    )


def debloquer_user(db: Session, user_id: int) -> bool:
    """
    Déverrouille un compte bloqué : statut → actif, tentatives → 0.
    Retourne True si déverrouillé, False si introuvable.
    Utilisé par : admin_service (déverrouillage)
    """
    rows = (
        db.query(User)
        .filter(User.id == user_id)
        .update({"statut": "actif", "tentatives_echouees": 0})
    )
    return rows > 0


def update_password(db: Session, user_id: int, nouveau_mdp: str) -> bool:
    """
    Met à jour le mot de passe hashé. doit_changer_mdp → 0.
    Retourne True si mis à jour, False si introuvable.
    Utilisé par : auth_service (changement mdp volontaire ou 1ère connexion)
    """
    password_hash = bcrypt.hashpw(
        nouveau_mdp.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")

    rows = (
        db.query(User)
        .filter(User.id == user_id)
        .update({"password_hash": password_hash, "doit_changer_mdp": 0})
    )
    return rows > 0


def reset_password_admin(db: Session, user_id: int, nouveau_mdp: str) -> bool:
    """
    Réinitialise le mot de passe par l'admin. doit_changer_mdp → 1.
    Retourne True si mis à jour, False si introuvable.
    Utilisé par : admin_service (réinitialisation mdp)
    """
    password_hash = bcrypt.hashpw(
        nouveau_mdp.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")

    rows = (
        db.query(User)
        .filter(User.id == user_id)
        .update({"password_hash": password_hash, "doit_changer_mdp": 1})
    )
    return rows > 0


def update_role(db: Session, user_id: int, nouveau_role_id: int) -> bool:
    """
    Modifie le rôle d'un utilisateur.
    Retourne True si mis à jour, False si introuvable.
    Utilisé par : admin_service (modification rôle)
    """
    rows = (
        db.query(User)
        .filter(User.id == user_id)
        .update({"role_id": nouveau_role_id})
    )
    return rows > 0


# ═══════════════════════════════════════════════════════════════════════════════
# LECTURE — ROLE
# ═══════════════════════════════════════════════════════════════════════════════

def get_all_roles(db: Session) -> pd.DataFrame:
    """
    Retourne tous les rôles disponibles.
    Utilisé par : admin_service (liste déroulante rôles)
    """
    roles = db.query(Role).order_by(Role.id).all()
    return pd.DataFrame([_role_to_dict(r) for r in roles])


def get_role_by_id(db: Session, role_id: int) -> dict | None:
    """
    Retourne un rôle par son id.
    Utilisé par : admin_service (vérification rôle)
    """
    role = db.query(Role).filter(Role.id == role_id).first()
    return _role_to_dict(role) if role else None