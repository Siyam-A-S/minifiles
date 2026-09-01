from app.kube import (
    VOLUME_ID_LABEL,
    build_rehydrate_job,
    build_service,
    build_statefulset,
    build_tiering_cronjob,
)
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

    def create_rehydrate_job(self, volume) -> str:
        self.rehydrate_jobs = getattr(self, "rehydrate_jobs", [])
        self.rehydrate_jobs.append(volume.id)
        return f"rehydrate-{volume.id}-x1y2z"


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


def test_rehydrate_creates_job():
    kube, vol = FakeKube(), _volume()
    name = _provisioner(kube).rehydrate(vol)
    assert name == f"rehydrate-{vol.id}-x1y2z"
    assert kube.rehydrate_jobs == [vol.id]


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
    # userspace NFS: no privileged mode, only the handle-open capability
    assert container.security_context.privileged is None
    assert container.security_context.capabilities.add == ["DAC_READ_SEARCH"]
    assert container.ports[0].container_port == 2049
    assert container.readiness_probe.tcp_socket.port == 2049


def test_tiering_cronjob_manifest_shape():
    vol = _volume()
    cj = build_tiering_cronjob(vol)
    assert cj.metadata.name == f"tier-{vol.id}"
    assert cj.spec.schedule == "0 * * * *"
    assert cj.spec.concurrency_policy == "Forbid"
    pod = cj.spec.job_template.spec.template.spec
    assert pod.volumes[0].persistent_volume_claim.claim_name == f"data-{vol.id}-0"
    container = pod.containers[0]
    assert container.args[0] == "tier"
    assert f"{vol.id}/" in container.args  # per-volume blob key prefix
    assert container.env_from[0].secret_ref.name == "minifiles-azure"


def test_rehydrate_job_manifest_shape():
    vol = _volume()
    job = build_rehydrate_job(vol)
    assert job.metadata.generate_name == f"rehydrate-{vol.id}-"
    pod = job.spec.template.spec
    assert pod.volumes[0].persistent_volume_claim.claim_name == f"data-{vol.id}-0"
    assert pod.containers[0].args[0] == "rehydrate"
    assert job.spec.ttl_seconds_after_finished == 600


def test_service_manifest_shape():
    vol = _volume()
    svc = build_service(vol)
    assert svc.metadata.name == vol.id
    assert svc.spec.selector[VOLUME_ID_LABEL] == vol.id
    assert svc.spec.ports[0].port == 2049
    # not headless: kubelet NFS mounts route via the clusterIP
    assert svc.spec.cluster_ip is None  # unset in the manifest, assigned by k8s
