---
name: deploy-local
description: Build, load, and deploy MiniFiles to the local kind cluster, then verify it end to end. Use when deploying to or debugging the local cluster, or when a change needs to be confirmed running in Kubernetes (not just unit tests).
---

# Deploy MiniFiles locally (kind)

## Steps

1. **Cluster**: `kind get clusters | grep -qx minifiles || make kind-up`
2. **Build + load + apply**: `make deploy-local` (builds both images, `kind load`s them, applies `deploy/k8s/overlays/dev`).
3. **Wait for rollout**: `kubectl -n minifiles rollout status deploy/control-plane --timeout=120s`
4. **Smoke test from the host**: `curl -sf localhost:8471/healthz` (kind maps nodePort 30080 → host 8471 via `deploy/kind/cluster.yaml`).
5. Optional API check: create a volume per the README curl example (against `localhost:8471`), then `kubectl -n minifiles get statefulsets,pvc,svc -l minifiles.io/volume-id`.

## Failure diagnosis (in order of likelihood)

- **ImagePullBackOff / ErrImageNeverPull**: the image wasn't loaded into kind — rerun `make deploy-local`; confirm the tag in the Deployment matches `minifiles/control-plane:dev`.
- **Probe failures / CrashLoopBackOff**: `kubectl -n minifiles logs deploy/control-plane`; usually a bad `MINIFILES_*` value in the ConfigMap — check `kubectl -n minifiles get cm control-plane-config -o yaml`.
- **curl to 8471 refused**: the NodePort patch didn't apply (`kubectl -n minifiles get svc control-plane -o yaml` should show nodePort 30080), or the cluster was created without `deploy/kind/cluster.yaml` — delete and recreate with `make destroy && make kind-up`.
- **Volumes stuck in `creating`**: provisioner is `kubernetes` — check RBAC events (`kubectl -n minifiles get events --sort-by=.lastTimestamp | tail`) and the volume's StatefulSet pod.

## Rules

- Never `kubectl apply` raw files from `deploy/k8s/base` directly — always go through an overlay.
- `make destroy` when done if the cluster isn't needed — it must always be safe to delete (nothing stateful lives only in the cluster).
