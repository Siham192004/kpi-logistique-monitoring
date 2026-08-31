"""
admin_service.py — Logique métier : gestion des comptes utilisateurs

Responsabilités (réservées à l'Administrateur uniquement) :
1. Créer un compte utilisateur
2. Désactiver / Réactiver un compte
3. Déverrouiller un compte bloqué
4. Modifier le rôle d'un utilisateur
5. Lister les utilisateurs et les rôles

Toutes les règles métier sont ici.
Les requêtes sont dans user_repository.py.

Architecture :
    admin_router → admin_service → user_repository → SessionLocal (SQLAlchemy)

Corrections vs version originale :
- db: Session ajouté en paramètre de chaque fonction publique
- db transmis à chaque appel du repository
- db.commit() après chaque écriture (insert_user, update_statut, debloquer_user, update_role)
- creer_utilisateur : suppression du doublon get_role_by_id / get_all_roles
  → on cherche directement le rôle par nom dans get_all_roles()
- deverrouiller_utilisateur : "bloque" → "bloqué" (avec accent, cohérent avec la DB)
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.repositories.user_repository import (
    get_all_users,
    get_all_roles,
    get_user_by_id,
    login_exists,
    insert_user,
    update_statut,
    debloquer_user,
    update_role,
)
from backend.schemas.user_schema import (
    UserCreateSchema,
    UserUpdateRoleSchema,
)


# ═══════════════════════════════════════════════════════════════════════════════
# LISTE DES UTILISATEURS ET RÔLES
# ═══════════════════════════════════════════════════════════════════════════════

def lister_utilisateurs(db: Session) -> list:
    """
    Retourne la liste de tous les utilisateurs avec leur rôle.
    Utilisé par : admin_router (GET /admin/users)
    """
    df = get_all_users(db)
    return df.to_dict(orient="records")


def lister_roles(db: Session) -> list:
    """
    Retourne la liste de tous les rôles disponibles.
    Utilisé par : admin_router (GET /admin/roles)
    """
    df = get_all_roles(db)
    return df.to_dict(orient="records")


# ═══════════════════════════════════════════════════════════════════════════════
# CRÉATION D'UN COMPTE
# ═══════════════════════════════════════════════════════════════════════════════

def creer_utilisateur(db: Session, data: UserCreateSchema) -> dict:
    """
    Crée un nouveau compte utilisateur.

    Règles métier :
    1. Vérifier que le login n'est pas déjà utilisé
    2. Vérifier que le rôle existe en DB (par nom)
    3. Insérer avec doit_changer_mdp = 1
       → l'user devra changer son mdp dès la 1ère connexion

    Retourne l'utilisateur créé.
    Lève HTTPException si login déjà utilisé ou rôle invalide.
    """
    # 1. Login unique ?
    if login_exists(db, data.login):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Le login '{data.login}' est déjà utilisé. Choisissez un autre.",
        )

    # 2. Rôle valide ? → résoudre le nom → id en une seule requête
    roles_df = get_all_roles(db)
    role_row = roles_df[roles_df["nom_role"] == data.role]
    if role_row.empty:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Rôle '{data.role}' invalide.",
        )
    role_id = int(role_row.iloc[0]["id"])

    # 3. Créer l'utilisateur
    user_id = insert_user(
        db,
        nom=data.nom,
        prenom=data.prenom,
        login=data.login,
        password=data.password,
        role_id=role_id,
    )
    db.commit()

    return get_user_by_id(db, user_id)


# ═══════════════════════════════════════════════════════════════════════════════
# DÉSACTIVER / RÉACTIVER UN COMPTE
# ═══════════════════════════════════════════════════════════════════════════════

def desactiver_reactiver_utilisateur(
    db: Session,
    user_id: int,
    admin_id: int,
) -> dict:
    """
    Désactive ou réactive un compte (statut inactif ↔ actif).

    Règles métier :
    - Ne supprime jamais physiquement → préserve l'historique
    - Protège contre l'auto-désactivation
    - Bascule automatiquement : actif → inactif, inactif → actif

    Lève HTTPException si règle métier violée.
    """
    if user_id == admin_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vous ne pouvez pas modifier votre propre compte.",
        )

    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur introuvable.",
        )

    nouveau_statut = "inactif" if user["statut"] == "actif" else "actif"
    update_statut(db, user_id, nouveau_statut)
    db.commit()

    action = "désactivé" if nouveau_statut == "inactif" else "réactivé"
    return {
        "success": True,
        "message": f"Compte de {user['nom']} {user['prenom']} {action} avec succès.",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# DÉVERROUILLER UN COMPTE BLOQUÉ
# ═══════════════════════════════════════════════════════════════════════════════

def deverrouiller_utilisateur(
    db: Session,
    user_id: int,
    admin_id: int,
) -> dict:
    """
    Déverrouille un compte bloqué après trop de tentatives.

    Règles métier :
    - Vérifie que le compte est bien bloqué avant de déverrouiller
    - statut → 'actif' + tentatives_echouees → 0
    - Protège contre l'auto-déverrouillage

    Lève HTTPException si compte non bloqué ou introuvable.
    """
    if user_id == admin_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action non autorisée sur votre propre compte.",
        )

    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur introuvable.",
        )

    # "bloqué" avec accent — cohérent avec CheckConstraint dans models/user.py
    if user["statut"] != "bloqué":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Le compte de {user['nom']} {user['prenom']} "
                f"n'est pas bloqué (statut actuel : {user['statut']})."
            ),
        )

    debloquer_user(db, user_id)
    db.commit()

    return {
        "success": True,
        "message": f"Compte de {user['nom']} {user['prenom']} déverrouillé avec succès.",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MODIFIER LE RÔLE D'UN UTILISATEUR
# ═══════════════════════════════════════════════════════════════════════════════

def modifier_role_utilisateur(
    db: Session,
    user_id: int,
    data: UserUpdateRoleSchema,
    admin_id: int,
) -> dict:
    """
    Modifie le rôle d'un utilisateur.

    Règles métier :
    - Protège contre l'auto-modification de rôle
    - Vérifie que le nouveau rôle existe en DB
    - Ne peut pas modifier le rôle d'un compte inactif ou bloqué

    Lève HTTPException si règle métier violée.
    """
    if user_id == admin_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vous ne pouvez pas modifier votre propre rôle.",
        )

    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur introuvable.",
        )

    if user["statut"] != "actif":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Impossible de modifier le rôle d'un compte {user['statut']}.",
        )

    # Résoudre le nom du rôle → id
    roles_df = get_all_roles(db)
    role_row = roles_df[roles_df["nom_role"] == data.role_id]
    if role_row.empty:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Rôle '{data.role_id}' invalide.",
        )
    nouveau_role_id = int(role_row.iloc[0]["id"])

    update_role(db, user_id, nouveau_role_id)
    db.commit()

    return {
        "success": True,
        "message": f"Rôle de {user['nom']} {user['prenom']} modifié avec succès.",
    }