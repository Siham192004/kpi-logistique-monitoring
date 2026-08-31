from pydantic import BaseModel, field_validator, model_validator
from typing import Optional
from datetime import date
from enum import Enum
import re


# ── Enums ─────────────────────────────────────────────────────────────────────

class ShipmentStatusEnum(str, Enum):
    normal    = "Normal"
    cancelled = "Cancelled"


class TypeAnnulationEnum(str, Enum):
    non_annule   = "Non annulé"
    avant_depart = "Avant départ"
    apres_depart = "Après départ"


class IncotermEnum(str, Enum):
    cif = "CIF"
    fob = "FOB"
    cfr = "CFR"
    dap = "DAP"
    fca = "FCA"


# ════════════════════════════════════════════════════════════════════════════════
# SAISIE MANUELLE — Ce que React envoie à FastAPI
# ════════════════════════════════════════════════════════════════════════════════

class ShipmentCreateSchema(BaseModel):
    carrier:    str
    vessel_nom: str
    port_chargement:   str
    port_dechargement: str
    pays_destination:  str
    shipment_status: ShipmentStatusEnum = ShipmentStatusEnum.normal
    type_annulation: TypeAnnulationEnum = TypeAnnulationEnum.non_annule
    etd: Optional[date] = None
    eta: Optional[date] = None
    atd: Optional[date] = None
    ata: Optional[date] = None
    incoterm:         Optional[IncotermEnum] = None
    volume_booked:    Optional[float]        = None
    confirmed_volume: Optional[float]        = None
    charged_volume:   Optional[float]        = None
    transit_time:     Optional[int]          = None
    frequency:        Optional[str]          = None

    @field_validator("carrier", mode="before")
    @classmethod
    def normaliser_carrier(cls, v):
        if not v or not str(v).strip():
            raise ValueError("Ce champ ne peut pas être vide.")
        return str(v).strip().upper()

    @field_validator("vessel_nom", mode="before")
    @classmethod
    def normaliser_vessel(cls, v):
        if not v or not str(v).strip():
            raise ValueError("Ce champ ne peut pas être vide.")
        return str(v).strip().title()

    @field_validator("port_chargement", "port_dechargement", "pays_destination", mode="before")
    @classmethod
    def normaliser_ports(cls, v):
        if not v or not str(v).strip():
            raise ValueError("Ce champ ne peut pas être vide.")
        return str(v).strip().title()

    @field_validator("frequency")
    @classmethod
    def frequency_valide(cls, v):
        if v is not None:
            v = v.strip().lower()
            if not re.match(r"^\d+j$", v):
                raise ValueError("La fréquence doit être au format 'Xj' (ex: 7j, 10j, 18j).")
        return v

    @model_validator(mode="after")
    def verifier_regles_metier(self):
        if self.shipment_status == ShipmentStatusEnum.normal:
            if not self.etd:
                raise ValueError("ETD est obligatoire pour un shipment Normal.")
            if not self.eta:
                raise ValueError("ETA est obligatoire pour un shipment Normal.")
            if not self.transit_time or self.transit_time <= 0:
                raise ValueError("Transit time est obligatoire et doit être > 0 pour un shipment Normal.")
            if not self.incoterm:
                raise ValueError("Incoterm est obligatoire pour un shipment Normal.")
            if not self.volume_booked or self.volume_booked <= 0:
                raise ValueError("Volume Booked est obligatoire et doit être > 0 pour un shipment Normal.")
            if not self.confirmed_volume or self.confirmed_volume <= 0:
                raise ValueError("Confirmed Volume est obligatoire et doit être > 0 pour un shipment Normal.")
            if self.etd and self.eta and self.etd >= self.eta:
                raise ValueError("ETD doit être strictement antérieure à ETA.")
            if self.atd and self.ata and self.atd >= self.ata:
                raise ValueError("ATD doit être strictement antérieure à ATA.")
            if self.charged_volume is not None and self.charged_volume <= 0:
                raise ValueError("Charged Volume doit être supérieur à 0.")
            if self.type_annulation != TypeAnnulationEnum.non_annule:
                raise ValueError("Type annulation doit être 'Non annulé' pour un shipment Normal.")

        if self.shipment_status == ShipmentStatusEnum.cancelled:
            if self.type_annulation == TypeAnnulationEnum.non_annule:
                raise ValueError("Veuillez préciser le type d'annulation : 'Avant départ' ou 'Après départ'.")

        if (self.port_chargement and self.port_dechargement and
                self.port_chargement.strip().lower() == self.port_dechargement.strip().lower()):
            raise ValueError("Le port de chargement et le port de déchargement ne peuvent pas être identiques.")

        return self


# ════════════════════════════════════════════════════════════════════════════════
# MODIFICATION
# ════════════════════════════════════════════════════════════════════════════════

class ShipmentUpdateSchema(BaseModel):
    vessel_nom:        Optional[str]                = None
    carrier:           Optional[str]                = None
    port_chargement:   Optional[str]                = None
    port_dechargement: Optional[str]                = None
    pays_destination:  Optional[str]                = None
    etd:               Optional[date]               = None
    atd:               Optional[date]               = None
    eta:               Optional[date]               = None
    ata:               Optional[date]               = None
    incoterm:          Optional[IncotermEnum]       = None
    volume_booked:     Optional[float]              = None
    confirmed_volume:  Optional[float]              = None
    charged_volume:    Optional[float]              = None
    transit_time:      Optional[int]                = None
    frequency:         Optional[str]                = None
    shipment_status:   Optional[ShipmentStatusEnum] = None
    type_annulation:   Optional[TypeAnnulationEnum] = None

    @field_validator("carrier", mode="before")
    @classmethod
    def normaliser_carrier(cls, v):
        if v is not None:
            return str(v).strip().upper()
        return v

    @field_validator("vessel_nom", mode="before")
    @classmethod
    def normaliser_vessel(cls, v):
        if v is not None:
            return str(v).strip().title()
        return v

    @field_validator("port_chargement", "port_dechargement", "pays_destination", mode="before")
    @classmethod
    def normaliser_ports(cls, v):
        if v is not None:
            return str(v).strip().title()
        return v

    @field_validator("volume_booked", "confirmed_volume", "charged_volume")
    @classmethod
    def volumes_positifs(cls, v):
        if v is not None and v <= 0:
            raise ValueError("Les volumes doivent être supérieurs à 0.")
        return v

    @field_validator("transit_time")
    @classmethod
    def transit_time_positif(cls, v):
        if v is not None and v <= 0:
            raise ValueError("Le transit time doit être supérieur à 0.")
        return v

    @field_validator("frequency")
    @classmethod
    def frequency_valide(cls, v):
        if v is not None:
            v = v.strip().lower()
            if not re.match(r"^\d+j$", v):
                raise ValueError("La fréquence doit être au format 'Xj' (ex: 7j, 10j, 18j).")
        return v

    @model_validator(mode="after")
    def verifier_regles_metier(self):
        if (self.port_chargement and self.port_dechargement and
                self.port_chargement.strip().lower() == self.port_dechargement.strip().lower()):
            raise ValueError("Le port de chargement et le port de déchargement ne peuvent pas être identiques.")
        if self.etd and self.eta and self.etd >= self.eta:
            raise ValueError("ETD doit être strictement antérieure à ETA.")
        if self.atd and self.ata and self.atd >= self.ata:
            raise ValueError("ATD doit être strictement antérieure à ATA.")
        return self


# ════════════════════════════════════════════════════════════════════════════════
# RÉPONSE — Ce que FastAPI retourne à React
# ════════════════════════════════════════════════════════════════════════════════

class ShipmentResponseSchema(BaseModel):
    """Réponse complète avec colonnes dérivées + vessel + carrier + opérateur."""
    id:                            int
    port_chargement:               str
    port_dechargement:             str
    pays_destination:              str
    shipment_status:               str
    type_annulation:               str
    etd:                           Optional[date]  = None
    atd:                           Optional[date]  = None
    eta:                           Optional[date]  = None
    ata:                           Optional[date]  = None
    incoterm:                      Optional[str]   = None
    volume_booked:                 Optional[float] = None
    confirmed_volume:              Optional[float] = None
    charged_volume:                Optional[float] = None
    transit_time:                  Optional[int]   = None
    frequency:                     Optional[str]   = None
    month:                         Optional[str]   = None
    year:                          Optional[int]   = None
    # Colonnes dérivées ETL
    transit_time_reel:             Optional[float] = None
    eta_deviation:                 Optional[float] = None
    etd_deviation:                 Optional[float] = None
    is_delayed:                    Optional[float] = None
    volume_ratio_loaded:           Optional[float] = None
    volume_ratio_allocated_booked: Optional[float] = None
    niveau_retard:                 Optional[str]   = None
    # Vessel + carrier (JOIN table vessel)
    vessel_id:                     int
    vessel_nom:                    Optional[str]   = None
    carrier:                       Optional[str]   = None
    # Opérateur (JOIN table user via createur_id)
    createur_id:                   int
    operateur_prenom:              Optional[str]   = None
    operateur_nom:                 Optional[str]   = None

    class Config:
        from_attributes = True


# ════════════════════════════════════════════════════════════════════════════════
# SUPPRESSION
# ════════════════════════════════════════════════════════════════════════════════

class DeleteResponseSchema(BaseModel):
    success: bool
    message: str


# ════════════════════════════════════════════════════════════════════════════════
# VESSEL
# ════════════════════════════════════════════════════════════════════════════════

class VesselCreateSchema(BaseModel):
    nom:     str
    carrier: str

    @field_validator("nom", "carrier")
    @classmethod
    def texte_non_vide(cls, v):
        if not v or not v.strip():
            raise ValueError("Ce champ ne peut pas être vide.")
        return v.strip()


class VesselResponseSchema(BaseModel):
    id:      int
    nom:     str
    carrier: str

    class Config:
        from_attributes = True


# ════════════════════════════════════════════════════════════════════════════════
# CARRIER
# ════════════════════════════════════════════════════════════════════════════════

class CarrierResponseSchema(BaseModel):
    carrier: str