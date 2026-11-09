"""Request models with validation."""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .config import CAMERAS, VILLAGES


class SimulationRequest(BaseModel):
    animal: Literal["Elephant", "Leopard"] = "Elephant"
    source: Literal["Camera Trap", "GPS Collar", "Acoustic Sensor", "PIR Sensor"] = "Camera Trap"
    camera_id: str = "CAM-01"
    movement: Literal["Toward Village", "Away From Village", "Parallel To Boundary"] = "Toward Village"

    @field_validator("camera_id")
    @classmethod
    def known_camera(cls, value):
        if value not in CAMERAS:
            raise ValueError(f"unknown camera_id; choose one of {sorted(CAMERAS)}")
        return value


class SubscriberCreate(BaseModel):
    name: str
    phone: str
    village: str
    language: Literal["en", "ta"] = "en"
    voice: bool = False  # also receive an automated voice call for Warning and Imminent alerts

    @field_validator("phone")
    @classmethod
    def indian_mobile(cls, value):
        if not re.fullmatch(r"[6-9]\d{9}", value):
            raise ValueError("phone must be a 10-digit Indian mobile number")
        return value

    @field_validator("village")
    @classmethod
    def known_village(cls, value):
        if value not in VILLAGES:
            raise ValueError(f"unknown village; choose one of {sorted(VILLAGES)}")
        return value


class VerifyRequest(BaseModel):
    action: Literal["confirm", "reject"]


# ---------------------------------------------------------------- ingestion


class DetectionIn(BaseModel):
    species: Literal["Elephant", "Leopard"]
    confidence: float = Field(ge=0, le=1)
    timestamp: str | None = None
    lat: float | None = None
    lon: float | None = None
    count: int = Field(default=1, ge=1, le=200)


class GpsFix(BaseModel):
    animal_id: str = Field(min_length=1, max_length=40)
    species: Literal["Elephant", "Leopard"]
    timestamp: str | None = None
    lat: float
    lon: float


class GpsBatch(BaseModel):
    fixes: list[GpsFix] = Field(min_length=1, max_length=500)


class SensorReading(BaseModel):
    kind: str
    value: float
    timestamp: str | None = None
    lat: float | None = None
    lon: float | None = None


class SensorBatch(BaseModel):
    readings: list[SensorReading] = Field(min_length=1, max_length=500)


class DeviceCreate(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{2,32}$")
    type: str = Field(min_length=2, max_length=40)
    kind: Literal["camera", "collar", "ground"]
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    lora_id: int | None = Field(default=None, ge=1, le=65535)  # short id used in LoRa frames
    rotate: bool = False


class IncidentCreate(BaseModel):
    village: str
    animal: Literal["Elephant", "Leopard"] | None = None
    timestamp: str | None = None
    notes: str | None = Field(default=None, max_length=300)

    @field_validator("village")
    @classmethod
    def known_village(cls, value):
        if value not in VILLAGES:
            raise ValueError(f"unknown village; choose one of {sorted(VILLAGES)}")
        return value


class ScenarioRequest(BaseModel):
    mode: Literal["mixed", "approach", "veer", "loiter"] = "mixed"
    species: Literal["Elephant", "Leopard"] = "Elephant"
    village: str = "Village A"
    speed: float = Field(default=10.0, ge=1, le=60)

    @field_validator("village")
    @classmethod
    def known_village(cls, value):
        if value not in VILLAGES:
            raise ValueError(f"unknown village; choose one of {sorted(VILLAGES)}")
        return value


class LoraUplink(BaseModel):
    frames: list[str] = Field(min_length=1, max_length=200)  # hex strings
