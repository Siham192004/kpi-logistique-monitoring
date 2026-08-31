from pydantic import BaseModel
from enum import Enum
from typing import Optional


# ── Rôles (correspondent exactement à la table role en DB) ───────────────────
class RoleEnum(str, Enum):
    administrateur          = "Administrateur"
    control_tower_team      = "Control Tower Team"
    performance_managers    = "Performance Managers Team"


# ── Statuts possibles d'un compte ────────────────────────────────────────────
class StatutEnum(str, Enum):
    actif   = "actif"
    inactif = "inactif"
    bloque  = "bloque"


# ════════════════════════════════════════════════════════════════════════════════
# AUTHENTIFICATION
# ════════════════════════════════════════════════════════════════════════════════

class LoginSchema(BaseModel):
    """Ce que React envoie lors du login."""
    login:    str
    password: str


class TokenSchema(BaseModel):
    """Ce que FastAPI retourne après un login réussi."""
    access_token:     str
    token_type:       str  = "bearer"
    role:             str                   # pour que React sache quelle interface afficher
    nom:              str                   # pour afficher "Bonjour Ahmed"
    prenom:           str
    id: int 
    doit_changer_mdp: bool = False          # True → React redirige vers page changement mdp


class TokenDataSchema(BaseModel):
    """Données encodées dans le token JWT."""
    login:    Optional[str]      = None
    role:     Optional[RoleEnum] = None
    user_id:  Optional[int]      = None


# ════════════════════════════════════════════════════════════════════════════════
# CHANGEMENT DE MOT DE PASSE
# ════════════════════════════════════════════════════════════════════════════════

class PasswordChangeSchema(BaseModel):
    """
    Utilisé dans 2 cas :
    - 1ère connexion : l'utilisateur doit changer son mdp temporaire
    - Changement volontaire par l'utilisateur
    """
    ancien_password:  str
    nouveau_password: str


# ════════════════════════════════════════════════════════════════════════════════
# ADMINISTRATION (actions réservées à l'Administrateur Système)
# ════════════════════════════════════════════════════════════════════════════════

class UserCreateSchema(BaseModel):
    """
    Création d'un compte par l'admin.
    doit_changer_mdp = 1 automatiquement en DB → mdp temporaire à usage unique.
    """
    nom:      str
    prenom:   str
    login:    str
    password: str       # mot de passe temporaire, l'user devra le changer
    role:     RoleEnum


class UserResponseSchema(BaseModel):
    """
    Ce qu'on retourne à React pour afficher la liste des utilisateurs.
    Ne contient jamais le mot de passe.
    """
    id:                  int
    nom:                 str
    prenom:              str
    login:               str
    statut:              StatutEnum
    tentatives_echouees: int
    doit_changer_mdp:    bool
    nom_role:            str            # nom lisible du rôle (ex: "Control Tower Team")

    class Config:
        from_attributes = True


class UserUpdateRoleSchema(BaseModel):
    """Modification du rôle d'un utilisateur par l'admin."""
    role_id: int        # id depuis la table role (1=Admin, 2=CTT, 3=PMT)


class PasswordResetSchema(BaseModel):
    """
    Réinitialisation du mdp par l'admin.
    Génère un mdp temporaire → doit_changer_mdp = 1 automatiquement.
    """
    nouveau_password: str