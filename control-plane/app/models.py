import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ServiceLevel(StrEnum):
    STANDARD = "standard"
    PREMIUM = "premium"


class VolumeState(StrEnum):
    CREATING = "creating"
    AVAILABLE = "available"
    DELETING = "deleting"
    ERROR = "error"


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _now() -> datetime:
    return datetime.now(UTC)


class VolumeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=63, pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
    size_gib: int = Field(gt=0, le=1024)
    service_level: ServiceLevel = ServiceLevel.STANDARD


class Volume(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("vol"))
    name: str
    size_gib: int
    service_level: ServiceLevel
    state: VolumeState = VolumeState.CREATING
    # Set by the provisioner once the data-plane pod is ready (M1).
    export_path: str | None = None
    created_at: datetime = Field(default_factory=_now)


class SnapshotCreate(BaseModel):
    name: str = Field(min_length=1, max_length=63, pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


class Snapshot(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("snap"))
    volume_id: str
    name: str
    created_at: datetime = Field(default_factory=_now)
