"""Provisioner: the boundary between the control plane and the data plane.

The API layer owns validation and quota; the provisioner owns state
transitions. Anything that talks to Kubernetes lives behind this interface so
the API and its tests never need a cluster.

Lifecycle contract:
- provision() starts provisioning; it may complete instantly (in-memory) or
  leave the volume in CREATING (kubernetes).
- reconcile() blocks until the volume reaches AVAILABLE or ERROR; the API
  schedules it as a background task when provision() returns with CREATING.
- deprovision() moves the volume to DELETING and starts teardown.
- finalize_delete() blocks until data-plane resources are gone; the API
  removes the volume from the store afterwards.
"""

import time
from typing import Protocol

from app.config import settings
from app.models import Volume, VolumeState


class Provisioner(Protocol):
    def provision(self, volume: Volume) -> None: ...

    def reconcile(self, volume: Volume) -> None: ...

    def deprovision(self, volume: Volume) -> None: ...

    def finalize_delete(self, volume: Volume) -> None: ...


class InMemoryProvisioner:
    """Instant transitions; used in tests and day-one local dev."""

    def provision(self, volume: Volume) -> None:
        volume.export_path = f"/exports/{volume.name}"
        volume.state = VolumeState.AVAILABLE

    def reconcile(self, volume: Volume) -> None:
        pass

    def deprovision(self, volume: Volume) -> None:
        volume.state = VolumeState.DELETING

    def finalize_delete(self, volume: Volume) -> None:
        pass


class KubernetesProvisioner:
    """One NFS server pod per volume: StatefulSet + PVC + ClusterIP Service,
    all named after the volume id (see app/kube.py for the manifests)."""

    def __init__(
        self,
        kube=None,
        timeout_s: float | None = None,
        poll_interval_s: float | None = None,
    ) -> None:
        if kube is None:
            from app.kube import KubeClient  # deferred: needs cluster config

            kube = KubeClient()
        self.kube = kube
        self.timeout_s = settings.provision_timeout_s if timeout_s is None else timeout_s
        self.poll_interval_s = (
            settings.poll_interval_s if poll_interval_s is None else poll_interval_s
        )

    def provision(self, volume: Volume) -> None:
        self.kube.apply_volume_resources(volume)
        # stays CREATING; reconcile() drives it to AVAILABLE/ERROR

    def reconcile(self, volume: Volume) -> None:
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            if volume.state != VolumeState.CREATING:
                return  # deleted (or errored) while we were waiting
            if self.kube.pod_ready(volume.id):
                # /data = the export's Pseudo path in data-plane/ganesha.conf
                volume.export_path = f"{volume.id}.{settings.namespace}.svc.cluster.local:/data"
                volume.state = VolumeState.AVAILABLE
                return
            time.sleep(self.poll_interval_s)
        volume.state = VolumeState.ERROR

    def deprovision(self, volume: Volume) -> None:
        volume.state = VolumeState.DELETING
        self.kube.delete_volume_resources(volume.id)

    def finalize_delete(self, volume: Volume) -> None:
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            if self.kube.resources_gone(volume.id):
                return
            time.sleep(self.poll_interval_s)
        # Timed out: leave the volume in DELETING rather than lie about it;
        # the API keeps it in the store so a retry DELETE is possible.
        raise TimeoutError(f"data-plane resources for {volume.id} not gone after {self.timeout_s}s")


_provisioner: Provisioner | None = None


def get_provisioner() -> Provisioner:
    global _provisioner
    if _provisioner is None:
        if settings.provisioner == "kubernetes":
            _provisioner = KubernetesProvisioner()
        else:
            _provisioner = InMemoryProvisioner()
    return _provisioner
