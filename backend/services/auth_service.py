"""
auth_service.py — Logique métier : authentification et JWT

Responsabilités :
1. Vérifier les credentials (login + password)
2. Gérer les tentatives échouées et le blocage
3. Générer et vérifier les tokens JWT
4. Gérer le changement de mot de passe

Rôles et accès :
- Administrateur            → gestion comptes uniquement
- Control Tower Team        → TOUT ce que voit le manager
                              + saisie/modification/suppression shipments
- Performance Managers Team → dashboard + KPIs + rapport carriers
                              + prédiction + messages

Routes partagées (Opérateur + Manager) → get_current_operateur_ou_manager()
Routes opérateur uniquement            → get_current_operateur()
Routes admin uniquement                → get_current_admin()

Architecture :
    Router → auth_service → user_repository → SessionLocal (SQLAlchemy)

Corrections vs version originale :
- db: Session ajouté en paramètre de toutes les fonctions métier
- db transmis à chaque appel du repository
- db.commit() après chaque écriture (incrementer_tentatives, update_statut,
  reset_tentatives, update_password, reset_password_admin)
- get_current_user / get_current_admin / get_current_operateur /
  get_current_operateur_ou_manager : db injecté via Depends(get_db)
  car ces fonctions sont appelées par FastAPI via Depends(), pas manuellement
- "bloque" → "bloqué" (avec accent, cohérent avec CheckConstraint du modèle)
"""

import bcrypt
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from backend.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from database.db import get_db          # dépendance FastAPI → Session SQLAlchemy
from backend.repositories.user_repository import (
    get_user_by_login,
    get_user_by_id,
    incrementer_tentatives,
    reset_tentatives,
    update_statut,
    update_password,
    reset_password_admin,
)
from backend.schemas.user_schema import TokenDataSchema

# ── OAuth2 : FastAPI lit le token depuis le header Authorization ──────────────
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/admin/login/oauth")

# ── Nombre max de tentatives avant blocage ────────────────────────────────────
MAX_TENTATIVES = 5


# ═══════════════════════════════════════════════════════════════════════════════
# VÉRIFICATION DU MOT DE PASSE
# ═══════════════════════════════════════════════════════════════════════════════

def verifier_password(password_clair: str, password_hash: str) -> bool:
    """
    Vérifie si le mot de passe saisi correspond au hash stocké en DB.
    Utilise bcrypt pour la comparaison sécurisée.
    Pas de db nécessaire — comparaison locale uniquement.
    """
    return bcrypt.checkpw(
        password_clair.encode("utf-8"),
        password_hash.encode("utf-8"),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# LOGIN — VÉRIFICATION DES CREDENTIALS
# ═══════════════════════════════════════════════════════════════════════════════

def authentifier_user(db: Session, login: str, password: str) -> dict:
    """
    Vérifie les credentials selon le diagramme de séquence login :

    1. Vérifier que l'user existe
    2. Vérifier que le statut n'est pas 'bloqué' ou 'inactif'
    3. Vérifier le mot de passe
    4. Si échec → incrémenter tentatives → bloquer si >= MAX_TENTATIVES
    5. Si succès → reset tentatives → retourner l'user

    Retourne le dict user si authentification réussie.
    Lève HTTPException sinon.
    """
    # 1. User existe ?
    user = get_user_by_login(db, login)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Login ou mot de passe incorrect.",
        )

    # 2. Compte bloqué ? ("bloqué" avec accent — cohérent avec le modèle)
    if user["statut"] == "bloqué":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte bloqué après trop de tentatives. "
                   "Contactez l'administrateur.",
        )

    # 3. Compte inactif ?
    if user["statut"] == "inactif":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte désactivé. Contactez l'administrateur.",
        )

    # 4. Mot de passe incorrect ?
    if not verifier_password(password, user["password_hash"]):
        incrementer_tentatives(db, login)
        db.commit()

        # Recharger pour avoir le nb de tentatives à jour
        user_maj = get_user_by_login(db, login)
        tentatives = user_maj["tentatives_echouees"]

        if tentatives >= MAX_TENTATIVES:
            update_statut(db, user["id"], "bloqué")
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Compte bloqué après {MAX_TENTATIVES} tentatives échouées. "
                       "Contactez l'administrateur.",
            )

        restantes = MAX_TENTATIVES - tentatives
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Login ou mot de passe incorrect. "
                   f"{restantes} tentative(s) restante(s) avant blocage.",
        )

    # 5. Succès → reset tentatives
    reset_tentatives(db, login)
    db.commit()
    return user


# ═══════════════════════════════════════════════════════════════════════════════
# TOKEN JWT — GÉNÉRATION ET VÉRIFICATION
# ═══════════════════════════════════════════════════════════════════════════════

def creer_token(user: dict) -> str:
    """
    Génère un token JWT contenant :
    - sub  : login de l'utilisateur
    - role : nom du rôle
    - id   : id de l'utilisateur
    - exp  : date d'expiration

    Le token est signé avec SECRET_KEY → impossible à falsifier.
    Pas de db nécessaire — opération locale uniquement.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub":  user["login"],
        "role": user["nom_role"],
        "id":   user["id"],
        "exp":  expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verifier_token(token: str = Depends(oauth2_scheme)) -> TokenDataSchema:
    """
    Vérifie et décode le token JWT.
    Appelé automatiquement par FastAPI via Depends() dans chaque route protégée.
    Pas de db nécessaire — vérification cryptographique locale uniquement.
    Lève HTTPException 401 si token invalide ou expiré.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalide ou expiré. Veuillez vous reconnecter.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload  = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        login:   str = payload.get("sub")
        role:    str = payload.get("role")
        user_id: int = payload.get("id")

        if login is None:
            raise credentials_exception

        return TokenDataSchema(login=login, role=role, user_id=user_id)

    except JWTError:
        raise credentials_exception


def get_current_user(
    token_data: TokenDataSchema = Depends(verifier_token),
    db: Session = Depends(get_db),          # ← db injecté ici par FastAPI
) -> dict:
    """
    Retourne l'utilisateur courant depuis le token JWT.
    Vérifie que l'user existe toujours en DB et est actif.

    db est injecté via Depends(get_db) car cette fonction est appelée
    par FastAPI via Depends(), pas manuellement depuis le code.
    Utilisé par toutes les routes protégées via Depends().
    """
    user = get_user_by_id(db, token_data.user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utilisateur introuvable.",
        )
    if user["statut"] != "actif":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte désactivé ou bloqué.",
        )
    return user


# ═══════════════════════════════════════════════════════════════════════════════
# DÉPENDANCES DE RÔLE — Pour protéger les routes par rôle
# ═══════════════════════════════════════════════════════════════════════════════

def get_current_admin(
    user: dict = Depends(get_current_user),
) -> dict:
    """
    Vérifie que l'utilisateur est Administrateur.
    Accès : gestion des comptes uniquement.
    Utilisé via Depends() dans les routes /admin/
    """
    if user["nom_role"] != "Administrateur":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès réservé à l'Administrateur.",
        )
    return user


def get_current_operateur(
    user: dict = Depends(get_current_user),
) -> dict:
    """
    Vérifie que l'utilisateur est Control Tower Team.
    Accès : saisie + modification + suppression shipments uniquement.
    Utilisé via Depends() dans POST/PUT/DELETE /shipments/
    """
    if user["nom_role"] != "Control Tower Team":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès réservé à l'équipe Control Tower.",
        )
    return user


def get_current_operateur_ou_manager(
    user: dict = Depends(get_current_user),
) -> dict:
    """
    Vérifie que l'utilisateur est Control Tower Team OU Performance Managers Team.

    Routes partagées accessibles aux deux rôles :
    - Dashboard KPIs
    - Rapport carriers
    - Prédiction retard (ML)
    - Messagerie
    - Consultation shipments (GET uniquement)

    Utilisé via Depends() dans GET /shipments/, /kpis/, /predict/, /messages/
    """
    if user["nom_role"] not in ["Control Tower Team", "Performance Managers Team"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès réservé aux équipes Control Tower et Performance Managers.",
        )
    return user


# ═══════════════════════════════════════════════════════════════════════════════
# CHANGEMENT DE MOT DE PASSE
# ═══════════════════════════════════════════════════════════════════════════════

def changer_password(
    db: Session,
    user_id: int,
    ancien_password: str,
    nouveau_password: str,
) -> bool:
    """
    Changement de mot de passe par l'utilisateur lui-même.

    Utilisé dans 2 cas :
    1. Première connexion (doit_changer_mdp = 1)
       → doit_changer_mdp → 0 après changement
    2. Changement volontaire depuis les paramètres

    Dans les deux cas : vérification de l'ancien mdp obligatoire.
    Lève HTTPException si l'ancien mot de passe est incorrect.
    """
    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur introuvable.",
        )

    if not verifier_password(ancien_password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ancien mot de passe incorrect.",
        )

    result = update_password(db, user_id, nouveau_password)
    db.commit()
    return result


def reinitialiser_password_admin(
    db: Session,
    user_id: int,
    nouveau_password: str,
    admin: dict,
) -> bool:
    """
    Réinitialisation du mot de passe par l'admin.
    → doit_changer_mdp = 1 → l'user devra changer à la prochaine connexion.
    Protège contre l'auto-réinitialisation.
    """
    if user_id == admin["id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vous ne pouvez pas réinitialiser votre propre mot de passe.",
        )

    result = reset_password_admin(db, user_id, nouveau_password)
    db.commit()
    return result

def verifier_token_ws(token: str) -> dict:
    """
    Version WebSocket de verifier_token — accepte un string directement.
    Utilisée pour les connexions WebSocket qui passent le token en query param.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        login:   str = payload.get("sub")
        role:    str = payload.get("role")
        user_id: int = payload.get("id")
        if login is None:
            return None
        return {"login": login, "role": role, "id": user_id}
    except JWTError:
        return None