from app.kube import VOLUME_ID_LABEL, build_service, build_statefulset
from app.models import Volume, VolumeState
from app.provisioner import KubernetesProvisioner


class FakeKube:
    def __init__(self) -> None:
        self.applied: list[str] = []
        self.deleted: list[str] = []
        self.ready = False
        self.gone = False

    def apply_volume_resources(self, volume) -> None:
        self.applied.append(volume.id)

    def delete_volume_resources(self, vol_id) -> None:
        self.deleted.append(vol_id)
        self.gone = True

    def pod_ready(self, vol_id) -> bool:
        return self.ready

    def resources_gone(self, vol_id) -> bool:
        return self.gone


def _provisioner(kube, timeout_s=0.05):
    return KubernetesProvisioner(kube=kube, timeout_s=timeout_s, poll_interval_s=0.01)


def _volume() -> Volume:
    return Volume(name="vol1", size_gib=5, service_level="standard")


def test_provision_applies_resources_and_stays_creating():
    kube, vol = FakeKube(), _volume()
    _provisioner(kube).provision(vol)
    assert kube.applied == [vol.id]
    assert vol.state == VolumeState.CREATING


def test_reconcile_reaches_available_with_export_path():
    kube, vol = FakeKube(), _volume()
    kube.ready = True
    _provisioner(kube).reconcile(vol)
    assert vol.state == VolumeState.AVAILABLE
    assert vol.export_path == f"{vol.id}.minifiles.svc.cluster.local:/data"


def test_reconcile_times_out_to_error():
    kube, vol = FakeKube(), _volume()  # ready stays False
    _provisioner(kube).reconcile(vol)
    assert vol.state == VolumeState.ERROR


def test_reconcile_aborts_if_volume_left_creating_state():
    kube, vol = FakeKube(), _volume()
    kube.ready = True
    vol.state = VolumeState.DELETING  # deleted mid-provision
    _provisioner(kube).reconcile(vol)
    assert vol.state == VolumeState.DELETING


def test_deprovision_and_finalize_delete():
    kube, vol = FakeKube(), _volume()
    prov = _provisioner(kube)
    prov.deprovision(vol)
    assert vol.state == VolumeState.DELETING
    assert kube.deleted == [vol.id]
    prov.finalize_delete(vol)  # kube.gone flipped by delete; returns promptly


def test_finalize_delete_times_out():
    import pytest

    kube, vol = FakeKube(), _volume()
    vol.state = VolumeState.DELETING
    with pytest.raises(TimeoutError):
        _provisioner(kube).finalize_delete(vol)


# -- manifest builders (pure functions, no cluster) -------------------------


def test_statefulset_manifest_shape():
    vol = _volume()
    sts = build_statefulset(vol)
    assert sts.metadata.name == vol.id
    assert sts.spec.replicas == 1
    assert sts.spec.selector.match_labels[VOLUME_ID_LABEL] == vol.id
    claim = sts.spec.volume_claim_templates[0]
    assert claim.spec.resources.requests["storage"] == "5Gi"
    container = sts.spec.template.spec.containers[0]
    assert container.security_context is None  # Ganesha is userspace: unprivileged
    assert container.ports[0].container_port == 2049
    assert container.readiness_probe.tcp_socket.port == 2049


def test_service_manifest_shape():
    vol = _volume()
    svc = build_service(vol)
    assert svc.metadata.name == vol.id
    assert svc.spec.selector[VOLUME_ID_LABEL] == vol.id
    assert svc.spec.ports[0].port == 2049
    # not headless: kubelet NFS mounts route via the clusterIP
    assert svc.spec.cluster_ip is None  # unset in the manifest, assigned by k8s
