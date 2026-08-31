from fastapi import APIRouter, HTTPException

from app.models import Snapshot, SnapshotCreate, VolumeState
from app.store import store

router = APIRouter(prefix="/volumes/{volume_id}/snapshots", tags=["snapshots"])


def _get_available_volume(volume_id: str):
    vol = store.get_volume(volume_id)
    if vol is None:
        raise HTTPException(404, "volume not found")
    return vol


@router.post("", status_code=201)
def create_snapshot(volume_id: str, body: SnapshotCreate) -> Snapshot:
    vol = _get_available_volume(volume_id)
    if vol.state != VolumeState.AVAILABLE:
        raise HTTPException(409, f"volume is {vol.state}, not available")
    if any(s.name == body.name for s in store.list_snapshots(volume_id)):
        raise HTTPException(409, f"snapshot name {body.name!r} already exists on this volume")
    # M1+: actually snapshot the PVC (CSI VolumeSnapshot). Metadata-only for now.
    return store.add_snapshot(Snapshot(volume_id=volume_id, name=body.name))


@router.get("")
def list_snapshots(volume_id: str) -> list[Snapshot]:
    _get_available_volume(volume_id)
    return store.list_snapshots(volume_id)
