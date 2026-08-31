# Roadmap

Each milestone has acceptance criteria — the resume bullet it unlocks goes on
only when the criteria pass. Estimated effort assumes weekend work.

## M0 — Scaffold (done)

- [x] Control plane runs locally with in-memory provisioner; volume + snapshot
      CRUD; quota enforcement; tests pass.
- [x] Tiering scanner finds cold files and tiers to a local archive target;
      tests pass.
- [x] Kustomize base + kind overlay, CI (lint + tests + image builds), Makefile.

## M1 — Real data plane on kind (done 2026-08-31)

- [x] `KubernetesProvisioner`: `POST /v1/volumes` creates an NFS server pod
      (StatefulSet + PVC + Service) in the cluster; `DELETE` tears it down.
- [x] Volume state reflects pod readiness (creating → available), gated on a
      TCP:2049 readiness probe.
- [x] An in-cluster client pod can mount the NFS export and write files.
- [x] Liveness/readiness probes, resource requests/limits on everything.
- **Acceptance**: `make accept-m1` — create a volume via curl, mount it from a
  busybox pod, write a file, delete the volume, PVC is gone.
  **Passed** in the `acceptance` GitHub Actions workflow (run 33447141049);
  local dev hosts without kernel NFS client support can't run the mount step —
  CI is the reference environment.

## M2 — Tiering to Azure Blob + rehydration (1–2 weekends)

- [ ] `AzureBlobTarget` using `azure-storage-blob`; cool tier by default.
- [ ] Stub-file format finalized; scanner idempotent over half-tiered volumes.
- [ ] `POST /v1/volumes/{id}/rehydrate` restores tiered files.
- [ ] Tiering engine runs as a CronJob (or long-running Deployment) in-cluster.
- **Acceptance**: age a file artificially (touch -a), run a scan, see the blob
  in Azure, cat the stub, rehydrate, get the original bytes back (checksum).

## M3 — AKS, GitOps, observability (2 weekends)

- [ ] Terraform (or Bicep) for: resource group, ACR, single-node AKS (spot),
      storage account. One `terraform destroy` tears it all down.
- [ ] CI pushes images to ACR; Argo CD syncs the `azure` overlay.
- [ ] kube-prometheus-stack; metrics from both services; one dashboard
      (volumes by state, bytes tiered, API p95) checked in.
- **Acceptance**: a commit to main rolls out to AKS with no manual kubectl;
  dashboard screenshot in the README.

## M4 — Reliability story (1 weekend)

- [ ] Chaos test: kill the NFS pod mid-write, measure recovery time from
      Prometheus data.
- [ ] k6 (or fio in-cluster) load test against a volume; tune requests/limits;
      write up findings in `docs/perf-notes.md`.
- **Acceptance**: a short writeup with numbers — this is the interview
  war-story milestone.

## Stretch

- MCP diagnostics agent over Prometheus + scan history ("why is vol X slow?").
- Capacity pools as a first-class resource (quota moves off the global cap).
- SMB via Samba pod; per-service-level `cold_after` policies.
