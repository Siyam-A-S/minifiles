#!/usr/bin/env bash
# In-cluster M2 acceptance: the per-volume tiering CronJob moves cold data
# from a live volume's PVC to Azure Blob, and POST /v1/volumes/{id}/rehydrate
# restores it via a k8s Job. Requires: az login, terraform apply'd
# deploy/terraform, docker/kind. Runs on single-node kind (the tiering Jobs
# mount the PVC directly — no NFS client mount involved).
set -euo pipefail

cd "$(dirname "$0")/.."
API=localhost:8471
NS=minifiles

jsonval() { python3 -c "import sys,json;print(json.load(sys.stdin)[\"$1\"])"; }

step() { printf '\n== %s\n' "$*"; }

wait_healthz() {
  for _ in $(seq 1 60); do
    curl -sf "$API/healthz" >/dev/null 2>&1 && return 0
    sleep 2
  done
  echo "FAIL: control plane not responding on $API"
  return 1
}

step "azure credentials from terraform output"
CONN=$(terraform -chdir=deploy/terraform output -raw connection_string)
CONTAINER=$(terraform -chdir=deploy/terraform output -raw container_name)

step "cluster + deploy"
kind get clusters 2>/dev/null | grep -qx minifiles || make kind-up
make deploy-local
kubectl -n "$NS" rollout status deploy/control-plane --timeout=180s
wait_healthz

step "azure tiering secret"
kubectl -n "$NS" delete secret minifiles-azure --ignore-not-found
kubectl -n "$NS" create secret generic minifiles-azure \
  --from-literal=MINIFILES_AZURE_CONN_STRING="$CONN" \
  --from-literal=MINIFILES_AZURE_CONTAINER="$CONTAINER"

step "clean leftovers and restart control plane"
kubectl -n "$NS" delete pod m1-client --ignore-not-found --now
kubectl -n "$NS" delete sts,svc,pvc,cronjob,job -l "minifiles.io/volume-id" --ignore-not-found
kubectl -n "$NS" rollout restart deploy/control-plane
kubectl -n "$NS" rollout status deploy/control-plane --timeout=120s
wait_healthz

step "create volume"
VOL_NAME="m2-accept-$(date +%s)"
VOL_ID=""
for _ in $(seq 1 10); do
  if VOL_ID=$(curl -sf -X POST "$API/v1/volumes" -H 'content-type: application/json' \
      -d "{\"name\":\"$VOL_NAME\",\"size_gib\":1,\"service_level\":\"standard\"}" | jsonval id) \
      && [ -n "$VOL_ID" ]; then
    break
  fi
  sleep 2
done
[ -n "$VOL_ID" ] || { echo "FAIL: could not create volume"; exit 1; }
echo "volume: $VOL_ID"

step "wait for AVAILABLE"
for _ in $(seq 1 60); do
  STATE=$(curl -sf "$API/v1/volumes/$VOL_ID" | jsonval state)
  [ "$STATE" = available ] && break
  [ "$STATE" = error ] && { echo "FAIL: volume entered error state"; exit 1; }
  sleep 2
done
[ "$STATE" = available ] || { echo "FAIL: volume never became available (state=$STATE)"; exit 1; }

step "seed cold data through the data-plane pod"
# checksum BEFORE aging: reading the file (sha256sum) resets atime under
# relatime, which would make it warm again and invisible to the scanner
kubectl -n "$NS" exec "$VOL_ID-0" -- bash -c \
  'echo "m2-incluster-payload-$(date +%s)" > /exports/report.csv'
SUM_BEFORE=$(kubectl -n "$NS" exec "$VOL_ID-0" -- sha256sum /exports/report.csv | cut -d' ' -f1)
kubectl -n "$NS" exec "$VOL_ID-0" -- touch -a -d "60 days ago" /exports/report.csv
echo "seeded, sha256=$SUM_BEFORE"

step "trigger the tiering CronJob"
kubectl -n "$NS" get cronjob "tier-$VOL_ID" >/dev/null || { echo "FAIL: tiering CronJob missing"; exit 1; }
kubectl -n "$NS" create job m2-tier-run --from="cronjob/tier-$VOL_ID"
kubectl -n "$NS" wait --for=condition=complete job/m2-tier-run --timeout=180s \
  || { echo "FAIL: tiering job did not complete"; kubectl -n "$NS" logs job/m2-tier-run --tail=30; exit 1; }
kubectl -n "$NS" logs job/m2-tier-run --tail=3
kubectl -n "$NS" exec "$VOL_ID-0" -- test -f /exports/report.csv.minifiles-tiered.json \
  || { echo "FAIL: stub not written"; exit 1; }
kubectl -n "$NS" exec "$VOL_ID-0" -- test ! -f /exports/report.csv \
  || { echo "FAIL: original still present"; exit 1; }

step "verify blob in Azure"
az storage blob exists --connection-string "$CONN" -c "$CONTAINER" \
  -n "$VOL_ID/report.csv" -o tsv --only-show-errors | grep -qx True \
  || { echo "FAIL: blob not found in Azure"; exit 1; }
echo "blob present: $VOL_ID/report.csv"

step "rehydrate via the control-plane endpoint"
JOB=$(curl -sf -X POST "$API/v1/volumes/$VOL_ID/rehydrate" | jsonval job)
echo "rehydrate job: $JOB"
kubectl -n "$NS" wait --for=condition=complete "job/$JOB" --timeout=180s \
  || { echo "FAIL: rehydrate job did not complete"; kubectl -n "$NS" logs "job/$JOB" --tail=30; exit 1; }
SUM_AFTER=$(kubectl -n "$NS" exec "$VOL_ID-0" -- sha256sum /exports/report.csv | cut -d' ' -f1)
[ "$SUM_BEFORE" = "$SUM_AFTER" ] || { echo "FAIL: checksum mismatch ($SUM_BEFORE vs $SUM_AFTER)"; exit 1; }
kubectl -n "$NS" exec "$VOL_ID-0" -- test ! -f /exports/report.csv.minifiles-tiered.json \
  || { echo "FAIL: stub still present after rehydrate"; exit 1; }
echo "checksum match: $SUM_AFTER"

step "cleanup: delete volume, verify CronJob and PVC teardown"
az storage blob delete --connection-string "$CONN" -c "$CONTAINER" \
  -n "$VOL_ID/report.csv" --only-show-errors >/dev/null 2>&1 || true
HTTP=$(curl -s -o /dev/null -w '%{http_code}' -X DELETE "$API/v1/volumes/$VOL_ID")
[ "$HTTP" = 204 ] || { echo "FAIL: DELETE returned $HTTP"; exit 1; }
for _ in $(seq 1 60); do
  LEFT=$(kubectl -n "$NS" get pvc,pod,svc,cronjob,job -l "minifiles.io/volume-id=$VOL_ID" --no-headers 2>/dev/null | wc -l)
  [ "$LEFT" = 0 ] && break
  sleep 2
done
[ "$LEFT" = 0 ] || { echo "FAIL: resources still present"; kubectl -n "$NS" get pvc,pod,svc,cronjob,job -l "minifiles.io/volume-id=$VOL_ID"; exit 1; }

printf '\nPASS: M2 in-cluster acceptance met (CronJob tier -> Azure -> rehydrate endpoint, checksums verified)\n'
