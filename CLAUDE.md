# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

MiniFiles: a miniature multi-tenant file-storage service modeled on Azure NetApp
Files, built as a portfolio project targeting NetApp's ANF team. Architecture and
the milestone plan live in `docs/architecture.md` and `docs/roadmap.md` — read the
roadmap before adding features; work lands milestone by milestone (M1 next:
KubernetesProvisioner).

## Commands

- `make install` — venv + editable install for both services (`control-plane/`, `tiering-engine/`)
- `make test` — pytest for both; single service: `cd control-plane && .venv/bin/pytest -q`; single test: `.venv/bin/pytest tests/test_volumes.py::test_quota_enforced`
- `make lint` — ruff
- `make run` — control plane on :8471 (in-memory provisioner; host-facing port — in-cluster stays 8000)
- `make kind-up && make deploy-local` — build images, load into kind, apply `deploy/k8s/overlays/dev`
- `make accept-m1` — M1 acceptance end-to-end on kind (`scripts/accept-m1.sh`)
- `make destroy` — delete the kind cluster

## Architecture in one paragraph

Two independent Python packages (each with its own venv/pyproject, both named
`app` internally — never install them into one env). The control plane (FastAPI)
owns resource lifecycle and quota; all data-plane interaction goes through the
`Provisioner` protocol in `control-plane/app/provisioner.py` (in-memory impl for
tests/dev, Kubernetes impl is M1) — API code must never talk to Kubernetes
directly. The tiering engine is a stateless scan-and-tier pass (`scanner.py`
finds cold files by atime, `tierer.py` uploads and atomically replaces files
with `.minifiles-tiered.json` stubs); it must stay idempotent — re-running over
a half-tiered volume is a test-enforced invariant. Config is env-var driven
(`MINIFILES_*`) mapping 1:1 to the ConfigMap in `deploy/k8s/base/`.

## Constraints

- Control plane store is in-memory: keep `replicas: 1` until a real store lands.
- Azure spend rules are in `docs/azure-cost-guardrails.md` — nothing long-lived
  in Azure before M3; everything cloud-side must be reproducible via IaC.
- This project backs resume claims: a milestone's resume bullet is earned only
  when its acceptance criteria in `docs/roadmap.md` pass for real.
