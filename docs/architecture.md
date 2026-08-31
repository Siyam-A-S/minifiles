# Architecture

## Control plane vs. data plane

The split mirrors real cloud file services (and is the vocabulary the ANF team
uses): the control plane is a stateless REST API that owns *resource lifecycle*,
while the data plane is the set of pods that actually serve NFS traffic. The
control plane never touches file data; the tiering engine never creates or
deletes volumes.

### Control plane (`control-plane/`)

FastAPI service exposing resources:

| Resource | Endpoints | Notes |
|---|---|---|
| Volume | `POST/GET /v1/volumes`, `GET/DELETE /v1/volumes/{id}` | `size_gib`, `service_level` (standard/premium), lifecycle state machine |
| Snapshot | `POST/GET /v1/volumes/{id}/snapshots` | point-in-time, name-scoped to volume |
| Health | `GET /healthz`, `GET /readyz` | wired to k8s probes |

Volume lifecycle: `creating → available → deleting → (gone)`, with `error` as a
terminal failure state. State transitions are owned by the **provisioner**, an
interface with two implementations:

- `InMemoryProvisioner` — instant transitions, used in tests and day-one dev.
- `KubernetesProvisioner` (M1) — creates a StatefulSet + PVC + Service per
  volume (NFS server pod), watches readiness, and reflects pod status back into
  volume state.

Quota is enforced at the API layer: total provisioned GiB across volumes must
stay under `MINIFILES_MAX_TOTAL_GIB` (a stand-in for ANF's capacity-pool model —
if a pool abstraction is added later, quota moves there).

### Data plane (`data-plane/`, provisioned dynamically)

One NFS server pod per volume, backed by a PVC — `local-path` on kind, Azure
Disk on AKS. The server is **NFS-Ganesha (userspace, NFSv4-only)** built in
`data-plane/Dockerfile`: kernel knfsd inside kind/CI containers is unreliable
(module availability, overlayfs export limits) and needs privileged pods,
while Ganesha runs unprivileged with no added capabilities. Pod `Ready` is
gated on a TCP:2049 readiness probe — the control plane marks a volume
`available` only when the server actually accepts connections. The pod
template lives in the provisioner (`control-plane/app/kube.py`), not in static
manifests, because volumes are dynamic. Static manifests cover the control
plane, tiering engine, namespace, and RBAC.

### Tiering engine (`tiering-engine/`)

A background scanner in the tradition of storage-tiering/GC scanners:

1. **Scan**: walk each volume mount, classify files as cold when
   `now - atime > cold_after` (configurable per service level).
2. **Tier**: upload cold files to the tier target (Azure Blob cool tier; a
   local archive directory in dev), replace the original with a small stub
   metadata file (JSON: blob URL, size, checksum, tiered-at).
3. **Rehydrate** (M2): a read against a stub triggers download-and-restore.
   First implementation: an explicit `POST /v1/volumes/{id}/rehydrate` control
   plane call; transparent interception is a stretch goal.

Design constraints carried over from real scanners: the scan must be
resumable, must never race a rehydration (stub files are written atomically via
rename), and must be idempotent — re-running over a half-tiered volume is safe.

## Observability (M3)

- Control plane and tiering engine expose Prometheus metrics (`/metrics`):
  volume counts by state, bytes tiered, scan duration, API latency histograms.
- kube-prometheus-stack on the cluster; one Grafana dashboard checked into
  `deploy/k8s/` as a ConfigMap.

## Deployment path

kind (local) → AKS single node pool (spot). Same kustomize base, different
overlays. GitOps via Argo CD in M3: CI builds images to ACR, bumps the tag in
the `azure` overlay, Argo syncs.
