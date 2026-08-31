"""In-memory resource store.

Deliberately a plain dict behind a small interface: swapping in SQLite or
Postgres later only touches this module. Not safe across multiple replicas —
the control plane runs single-replica until a real store lands.
"""

from app.models import Snapshot, Volume


class Store:
    def __init__(self) -> None:
        self.volumes: dict[str, Volume] = {}
        self.snapshots: dict[str, Snapshot] = {}

    # -- volumes -----------------------------------------------------------
    def add_volume(self, vol: Volume) -> Volume:
        self.volumes[vol.id] = vol
        return vol

    def get_volume(self, vol_id: str) -> Volume | None:
        return self.volumes.get(vol_id)

    def list_volumes(self) -> list[Volume]:
        return list(self.volumes.values())

    def remove_volume(self, vol_id: str) -> None:
        self.volumes.pop(vol_id, None)
        self.snapshots = {
            sid: s for sid, s in self.snapshots.items() if s.volume_id != vol_id
        }

    def total_provisioned_gib(self) -> int:
        return sum(v.size_gib for v in self.volumes.values())

    def volume_name_taken(self, name: str) -> bool:
        return any(v.name == name for v in self.volumes.values())

    # -- snapshots ---------------------------------------------------------
    def add_snapshot(self, snap: Snapshot) -> Snapshot:
        self.snapshots[snap.id] = snap
        return snap

    def list_snapshots(self, volume_id: str) -> list[Snapshot]:
        return [s for s in self.snapshots.values() if s.volume_id == volume_id]


store = Store()
