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
                            # Userspace NFSv4 server (Ganesha): unprivileged,
                            # exports /exports per data-plane/ganesha.conf.
                            image=settings.nfs_image,
                            ports=[client.V1ContainerPort(container_port=2049, name="nfs")],
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


class KubeClient:
    def __init__(self, namespace: str | None = None) -> None:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        self.namespace = namespace or settings.namespace
        self.apps = client.AppsV1Api()
        self.core = client.CoreV1Api()

    def apply_volume_resources(self, volume: Volume) -> None:
        for create, manifest in (
            (self.core.create_namespaced_service, build_service(volume)),
            (self.apps.create_namespaced_stateful_set, build_statefulset(volume)),
        ):
            try:
                create(self.namespace, manifest)
            except ApiException as exc:
                if exc.status != 409:  # already exists: provision retry, fine
                    raise

    def delete_volume_resources(self, vol_id: str) -> None:
        selector = f"{VOLUME_ID_LABEL}={vol_id}"
        for delete in (
            lambda: self.apps.delete_namespaced_stateful_set(vol_id, self.namespace),
            lambda: self.core.delete_namespaced_service(vol_id, self.namespace),
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
