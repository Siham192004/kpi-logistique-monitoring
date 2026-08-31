"""
admin_router.py — Routes HTTP : authentification + administration des comptes

Routes publiques (sans token) :
    POST /admin/login              → authentification
    POST /admin/change-password    → changement mdp (1ère connexion ou volontaire)

Routes protégées Administrateur uniquement :
    GET  /admin/users              → liste des utilisateurs
    GET  /admin/roles              → liste des rôles
    POST /admin/users              → créer un compte
    PUT  /admin/users/{id}/toggle  → désactiver / réactiver
    PUT  /admin/users/{id}/unlock  → déverrouiller un compte bloqué
    PUT  /admin/users/{id}/role    → modifier le rôle
    POST /admin/users/{id}/reset-password → réinitialiser le mot de passe

Architecture :
admin_router → auth_service / admin_service → repositories → db.py
"""

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from backend.services.auth_service import (
    authentifier_user,
    creer_token,
    get_current_user,
    get_current_admin,
    changer_password,
    reinitialiser_password_admin,
)
from backend.services.admin_service import (
    lister_utilisateurs,
    lister_roles,
    creer_utilisateur,
    desactiver_reactiver_utilisateur,
    deverrouiller_utilisateur,
    modifier_role_utilisateur,
)
from backend.schemas.user_schema import (
    LoginSchema,
    TokenSchema,
    UserCreateSchema,
    UserUpdateRoleSchema,
    PasswordChangeSchema,
    PasswordResetSchema,
)
from database.db import get_db

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════════════
# AUTHENTIFICATION — Routes publiques (pas de token requis)
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/login", response_model=TokenSchema, tags=["Auth"])
def login(data: LoginSchema, db: Session = Depends(get_db)):
    user  = authentifier_user(db, data.login, data.password)  # ✅
    token = creer_token(user)
    return TokenSchema(
        access_token=token,
        token_type="bearer",
        role=user["nom_role"],
        nom=user["nom"],
        prenom=user["prenom"],
        id=user["id"], 
        doit_changer_mdp=bool(user["doit_changer_mdp"]),
    )


@router.post("/change-password", tags=["Auth"])
def change_password(
    data: PasswordChangeSchema,
    db:   Session = Depends(get_db),
    user: dict    = Depends(get_current_user),
):
    changer_password(db, user["id"], data.ancien_password, data.nouveau_password)  # ✅
    return {"success": True, "message": "Mot de passe changé avec succès."}


# admin_router.py — ajoutez cette route après /change-password

@router.get("/me", tags=["Auth"])
def get_me(
    user: dict = Depends(get_current_user),
):
    return {
        "id":               user["id"], 
        "nom":              user["nom"],
        "prenom":           user["prenom"],
        "nom_role":         user["nom_role"],
        "doit_changer_mdp": bool(user["doit_changer_mdp"]),
    }

# ═══════════════════════════════════════════════════════════════════════════════
# ADMINISTRATION — Routes protégées (Administrateur uniquement)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/users", tags=["Admin"])
def get_users(
    db:    Session = Depends(get_db),
    admin: dict    = Depends(get_current_admin),
):
    return lister_utilisateurs(db)  # ✅


@router.get("/roles", tags=["Admin"])
def get_roles(
    db:    Session = Depends(get_db),
    admin: dict    = Depends(get_current_admin),
):
    return lister_roles(db)  # ✅


@router.post("/users", status_code=status.HTTP_201_CREATED, tags=["Admin"])
def create_user(
    data:  UserCreateSchema,
    db:    Session = Depends(get_db),
    admin: dict    = Depends(get_current_admin),
):
    user = creer_utilisateur(db, data)  # ✅
    return {
        "success": True,
        "message": f"Compte '{data.login}' créé avec succès.",
        "user_id": user["id"],
    }


@router.put("/users/{user_id}/toggle", tags=["Admin"])
def toggle_user(
    user_id: int,
    db:      Session = Depends(get_db),
    admin:   dict    = Depends(get_current_admin),
):
    return desactiver_reactiver_utilisateur(db, user_id, admin["id"])  # ✅


@router.put("/users/{user_id}/unlock", tags=["Admin"])
def unlock_user(
    user_id: int,
    db:      Session = Depends(get_db),
    admin:   dict    = Depends(get_current_admin),
):
    return deverrouiller_utilisateur(db, user_id, admin["id"])  # ✅


@router.put("/users/{user_id}/role", tags=["Admin"])
def update_role(
    user_id: int,
    data:    UserUpdateRoleSchema,
    db:      Session = Depends(get_db),
    admin:   dict    = Depends(get_current_admin),
):
    return modifier_role_utilisateur(db, user_id, data, admin["id"])  # ✅


@router.post("/users/{user_id}/reset-password", tags=["Admin"])
def reset_password(
    user_id: int,
    data:    PasswordResetSchema,
    db:      Session = Depends(get_db),
    admin:   dict    = Depends(get_current_admin),
):
    reinitialiser_password_admin(db, user_id, data.nouveau_password, admin)  # ✅
    return {
        "success": True,
        "message": "Mot de passe réinitialisé. "
                   "L'utilisateur devra le changer à sa prochaine connexion.",
    }


@router.post("/login/oauth", include_in_schema=False)
def login_oauth(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db:        Session                   = Depends(get_db),
):
    user  = authentifier_user(db, form_data.username, form_data.password)  # ✅
    token = creer_token(user)
    return {"access_token": token, "token_type": "bearer"}