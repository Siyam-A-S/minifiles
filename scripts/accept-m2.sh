#!/usr/bin/env bash
# M2 acceptance: age a file artificially, run a tier scan
# against real Azure Blob, verify the blob exists in Azure, inspect the stub,
# rehydrate, and verify the restored bytes match (checksum). Requires:
# `az login` and a `terraform apply`'d deploy/terraform (for the conn string).
set -euo pipefail

cd "$(dirname "$0")/.."
PY=tiering-engine/.venv/bin/python

step() { printf '\n== %s\n' "$*"; }

step "credentials from terraform output"
export MINIFILES_AZURE_CONN_STRING=$(terraform -chdir=deploy/terraform output -raw connection_string)
export MINIFILES_AZURE_CONTAINER=$(terraform -chdir=deploy/terraform output -raw container_name)
ACCOUNT=$(terraform -chdir=deploy/terraform output -raw storage_account_name)
echo "storage account: $ACCOUNT, container: $MINIFILES_AZURE_CONTAINER"

step "prepare an artificially cold volume"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
VOL="$WORK/vol"
mkdir -p "$VOL/data"
echo "m2-acceptance-payload-$(date +%s)" > "$VOL/data/report.csv"
SUM_BEFORE=$(sha256sum "$VOL/data/report.csv" | cut -d' ' -f1)
touch -a -d '60 days ago' "$VOL/data/report.csv"

step "tier scan to Azure (cool tier)"
PREFIX="accept-m2-$(date +%s)/"
$PY -m app.main tier "$VOL" --target azure --key-prefix "$PREFIX" --cold-after-days 30
STUB="$VOL/data/report.csv.minifiles-tiered.json"
[ -f "$STUB" ] || { echo "FAIL: stub not written"; exit 1; }
[ ! -f "$VOL/data/report.csv" ] || { echo "FAIL: original still present"; exit 1; }
echo "stub contents:"; cat "$STUB"

step "verify blob exists in Azure"
az storage blob exists --connection-string "$MINIFILES_AZURE_CONN_STRING" \
  -c "$MINIFILES_AZURE_CONTAINER" -n "${PREFIX}data/report.csv" -o tsv | grep -qx True \
  || { echo "FAIL: blob not found in Azure"; exit 1; }
echo "blob present: ${PREFIX}data/report.csv"

step "rehydrate and verify checksum"
$PY -m app.main rehydrate "$VOL" --target azure --key-prefix "$PREFIX"
SUM_AFTER=$(sha256sum "$VOL/data/report.csv" | cut -d' ' -f1)
[ "$SUM_BEFORE" = "$SUM_AFTER" ] || { echo "FAIL: checksum mismatch"; exit 1; }
[ ! -f "$STUB" ] || { echo "FAIL: stub still present after rehydrate"; exit 1; }
echo "checksum match: $SUM_AFTER"

step "idempotency: re-scan tiers nothing new"
$PY -m app.main tier "$VOL" --target azure --key-prefix "$PREFIX" --cold-after-days 30

step "cleanup acceptance blobs"
az storage blob delete --connection-string "$MINIFILES_AZURE_CONN_STRING" \
  -c "$MINIFILES_AZURE_CONTAINER" -n "${PREFIX}data/report.csv" >/dev/null 2>&1 || true

printf '\nPASS: M2 acceptance criteria met (tier -> Azure cool -> rehydrate, checksums verified)\n'
