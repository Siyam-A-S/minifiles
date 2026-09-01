"""Kubernetes access for the provisioner.

Manifest builders are pure functions (unit-testable without a cluster);
KubeClient wraps the API calls and is faked in provisioner tests. Nothing
outside this module and the provisioner may import the kubernetes package.
"""

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from app.config import settings
from app.models import Volume

VOLUME_ID_LABEL = "minifiles.io/volume-id"


def _labels(vol_id: str) -> dict[str, str]:
    return {"app": vol_id, VOLUME_ID_LABEL: vol_id}


def build_service(volume: Volume) -> client.V1Service:
    # Plain ClusterIP (not headless): kubelet NFS mounts resolve the server
    # address through the node, not cluster DNS, so clients mount the
    # service's clusterIP and kube-proxy routes it to the pod.
    return client.V1Service(
        metadata=client.V1ObjectMeta(name=volume.id, labels=_labels(volume.id)),
        spec=client.V1ServiceSpec(
            selector=_labels(volume.id),
            ports=[client.V1ServicePort(name="nfs", port=2049, target_port=2049)],
        ),
    )


def build_statefulset(volume: Volume) -> client.V1StatefulSet:
    return client.V1StatefulSet(
        metadata=client.V1ObjectMeta(name=volume.id, labels=_labels(volume.id)),
        spec=client.V1StatefulSetSpec(
            service_name=volume.id,
            replicas=1,
            selector=client.V1LabelSelector(match_labels=_labels(volume.id)),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels=_labels(volume.id)),
                spec=client.V1PodSpec(
                    containers=[
                        client.V1Container(
                            name="nfs-server",
                            # NFS-godzilla, our userspace NFSv4 server:
                            # unprivileged, exports /exports per
                            # data-plane/godzilla.conf.
                            image=settings.nfs_image,
                            ports=[client.V1ContainerPort(container_port=2049, name="nfs")],
                            # The server's VFS FSAL opens files by handle
                            # (open_by_handle_at), which needs exactly this
                            # capability — everything else stays dropped.
                            security_context=client.V1SecurityContext(
                                capabilities=client.V1Capabilities(add=["DAC_READ_SEARCH"])
                            ),
                            # Gate pod Ready on actually serving NFS — without
                            # this, a crash-looping server briefly reports
                            # Ready and the volume goes AVAILABLE prematurely.
                            readiness_probe=client.V1Probe(
                                tcp_socket=client.V1TCPSocketAction(port=2049),
                                period_seconds=2,
                                failure_threshold=3,
                            ),
                            volume_mounts=[
                                client.V1VolumeMount(name="data", mount_path="/exports")
                            ],
                            resources=client.V1ResourceRequirements(
                                requests={"cpu": "50m", "memory": "64Mi"},
                                limits={"cpu": "500m", "memory": "256Mi"},
                            ),
                        )
                    ],
                ),
            ),
            volume_claim_templates=[
                client.V1PersistentVolumeClaim(
                    metadata=client.V1ObjectMeta(name="data", labels=_labels(volume.id)),
                    spec=client.V1PersistentVolumeClaimSpec(
                        access_modes=["ReadWriteOnce"],
                        storage_class_name=settings.storage_class,
                        resources=client.V1VolumeResourceRequirements(
                            requests={"storage": f"{volume.size_gib}Gi"}
                        ),
                    ),
                )
            ],
        ),
    )


def _pvc_name(vol_id: str) -> str:
    # volumeClaimTemplate "data" on StatefulSet <vol_id>, replica 0
    return f"data-{vol_id}-0"


def _tiering_pod_spec(volume: Volume, args: list[str]) -> client.V1PodSpec:
    """Pod template shared by the tiering CronJob and rehydrate Jobs: the
    tiering-engine image with the volume's PVC mounted at /mnt/vol and Azure
    credentials from the tiering Secret. Mounting the RWO PVC alongside the
    NFS server pod requires same-node scheduling — trivially true on the
    single-node dev/CI clusters; multi-node needs pod affinity (M3)."""
    return client.V1PodSpec(
        restart_policy="OnFailure",
        containers=[
            client.V1Container(
                name="tiering-engine",
                image=settings.tiering_image,
                args=args,
                env_from=[
                    client.V1EnvFromSource(
                        secret_ref=client.V1SecretEnvSource(name=settings.azure_secret_name)
                    )
                ],
                env=[
                    client.V1EnvVar(
                        name="MINIFILES_PUSHGATEWAY_URL", value=settings.pushgateway_url
                    )
                ],
                # The image defaults to `nobody`, but tiering replaces files
                # owned by arbitrary volume users in root-owned directories —
                # the agent must run as root (found the hard way on AKS,
                # where managed-disk dirs are root:755 unlike kind's 0777
                # local-path dirs).
                security_context=client.V1SecurityContext(run_as_user=0),
                volume_mounts=[client.V1VolumeMount(name="vol", mount_path="/mnt/vol")],
                resources=client.V1ResourceRequirements(
                    requests={"cpu": "50m", "memory": "64Mi"},
                    limits={"cpu": "500m", "memory": "256Mi"},
                ),
            )
        ],
        volumes=[
            client.V1Volume(
                name="vol",
                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                    claim_name=_pvc_name(volume.id)
                ),
            )
        ],
    )


def build_tiering_cronjob(volume: Volume) -> client.V1CronJob:
    args = [
        "tier",
        "/mnt/vol",
        "--target",
        "azure",
        "--key-prefix",
        f"{volume.id}/",
        "--cold-after-days",
        str(settings.cold_after_days),
    ]
    return client.V1CronJob(
        metadata=client.V1ObjectMeta(name=f"tier-{volume.id}", labels=_labels(volume.id)),
        spec=client.V1CronJobSpec(
            schedule=settings.tiering_schedule,
            concurrency_policy="Forbid",  # scans are idempotent but need not overlap
            job_template=client.V1JobTemplateSpec(
                metadata=client.V1ObjectMeta(labels=_labels(volume.id)),
                spec=client.V1JobSpec(
                    backoff_limit=2,
                    ttl_seconds_after_finished=3600,
                    template=client.V1PodTemplateSpec(
                        metadata=client.V1ObjectMeta(labels=_labels(volume.id)),
                        spec=_tiering_pod_spec(volume, args),
                    ),
                ),
            ),
        ),
    )


def build_rehydrate_job(volume: Volume) -> client.V1Job:
    args = ["rehydrate", "/mnt/vol", "--target", "azure", "--key-prefix", f"{volume.id}/"]
    return client.V1Job(
        metadata=client.V1ObjectMeta(
            generate_name=f"rehydrate-{volume.id}-", labels=_labels(volume.id)
        ),
        spec=client.V1JobSpec(
            backoff_limit=2,
            ttl_seconds_after_finished=600,
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels=_labels(volume.id)),
                spec=_tiering_pod_spec(volume, args),
            ),
        ),
    )


class KubeClient:
    def __init__(self, namespace: str | None = None) -> None:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        self.namespace = namespace or settings.namespace
        self.apps = client.AppsV1Api()
        self.core = client.CoreV1Api()
        self.batch = client.BatchV1Api()

    def apply_volume_resources(self, volume: Volume) -> None:
        creates = [
            (self.core.create_namespaced_service, build_service(volume)),
            (self.apps.create_namespaced_stateful_set, build_statefulset(volume)),
        ]
        if settings.tiering_enabled:
            creates.append((self.batch.create_namespaced_cron_job, build_tiering_cronjob(volume)))
        for create, manifest in creates:
            try:
                create(self.namespace, manifest)
            except ApiException as exc:
                if exc.status != 409:  # already exists: provision retry, fine
                    raise

    def create_rehydrate_job(self, volume: Volume) -> str:
        job = self.batch.create_namespaced_job(self.namespace, build_rehydrate_job(volume))
        return job.metadata.name

    def delete_volume_resources(self, vol_id: str) -> None:
        selector = f"{VOLUME_ID_LABEL}={vol_id}"
        for delete in (
            lambda: self.apps.delete_namespaced_stateful_set(vol_id, self.namespace),
            lambda: self.core.delete_namespaced_service(vol_id, self.namespace),
            lambda: self.batch.delete_namespaced_cron_job(f"tier-{vol_id}", self.namespace),
            # Background propagation so job pods are reaped with their jobs
            lambda: self.batch.delete_collection_namespaced_job(
                self.namespace, label_selector=selector, propagation_policy="Background"
            ),
            # volumeClaimTemplate PVCs survive StatefulSet deletion; reap by label
            lambda: self.core.delete_collection_namespaced_persistent_volume_claim(
                self.namespace, label_selector=selector
            ),
        ):
            try:
                delete()
            except ApiException as exc:
                if exc.status != 404:
                    raise

    def pod_ready(self, vol_id: str) -> bool:
        try:
            pod = self.core.read_namespaced_pod(f"{vol_id}-0", self.namespace)
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise
        conditions = (pod.status and pod.status.conditions) or []
        return any(c.type == "Ready" and c.status == "True" for c in conditions)

    def resources_gone(self, vol_id: str) -> bool:
        selector = f"{VOLUME_ID_LABEL}={vol_id}"
        try:
            self.apps.read_namespaced_stateful_set(vol_id, self.namespace)
            return False
        except ApiException as exc:
            if exc.status != 404:
                raise
        pvcs = self.core.list_namespaced_persistent_volume_claim(
            self.namespace, label_selector=selector
        )
        pods = self.core.list_namespaced_pod(self.namespace, label_selector=selector)
        return not pvcs.items and not pods.items
