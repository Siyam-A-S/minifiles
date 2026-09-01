from fastapi import APIRouter, BackgroundTasks, HTTPException, Response

from app.config import settings
from app.models import Volume, VolumeCreate, VolumeState
from app.provisioner import Provisioner, get_provisioner
from app.store import store

router = APIRouter(prefix="/volumes", tags=["volumes"])


@router.post("", status_code=201)
def create_volume(body: VolumeCreate, background_tasks: BackgroundTasks) -> Volume:
    if store.volume_name_taken(body.name):
        raise HTTPException(409, f"volume name {body.name!r} already exists")
    if store.total_provisioned_gib() + body.size_gib > settings.max_total_gib:
        raise HTTPException(
            409,
            f"quota exceeded: {store.total_provisioned_gib()} GiB provisioned, "
            f"limit {settings.max_total_gib} GiB",
        )
    vol = Volume(name=body.name, size_gib=body.size_gib, service_level=body.service_level)
    store.add_volume(vol)
    provisioner = get_provisioner()
    provisioner.provision(vol)
    if vol.state == VolumeState.CREATING:
        # async provisioner (kubernetes): poll to AVAILABLE/ERROR off-request
        background_tasks.add_task(provisioner.reconcile, vol)
    return vol


@router.get("")
def list_volumes() -> list[Volume]:
    return store.list_volumes()


@router.get("/{volume_id}")
def get_volume(volume_id: str) -> Volume:
    vol = store.get_volume(volume_id)
    if vol is None:
        raise HTTPException(404, "volume not found")
    return vol


@router.delete("/{volume_id}", status_code=204)
def delete_volume(volume_id: str, background_tasks: BackgroundTasks) -> Response:
    vol = store.get_volume(volume_id)
    if vol is None:
        raise HTTPException(404, "volume not found")
    # Idempotent: re-deleting a DELETING volume retries teardown.
    provisioner = get_provisioner()
    provisioner.deprovision(vol)
    background_tasks.add_task(_finish_delete, provisioner, vol)
    return Response(status_code=204)


@router.post("/{volume_id}/rehydrate", status_code=202)
def rehydrate_volume(volume_id: str) -> dict[str, str]:
    vol = store.get_volume(volume_id)
    if vol is None:
        raise HTTPException(404, "volume not found")
    if vol.state != VolumeState.AVAILABLE:
        raise HTTPException(409, f"volume is {vol.state}, not available")
    job = get_provisioner().rehydrate(vol)
    return {"volume_id": vol.id, "job": job}


def _finish_delete(provisioner: Provisioner, vol: Volume) -> None:
    # On TimeoutError the volume stays in the store as DELETING so the client
    # can observe the stuck state and retry the DELETE.
    provisioner.finalize_delete(vol)
    store.remove_volume(vol.id)
