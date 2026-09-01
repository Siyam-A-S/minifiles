#!/usr/bin/env bash
# M3 acceptance: a commit to main reaches AKS with no manual kubectl.
# Verifies: Argo CD Synced+Healthy, the deployed images come from ACR (tags
# stamped by the deploy workflow), the API answers via its LoadBalancer, and
# Prometheus is scraping MiniFiles metrics. Run after pushing to main and
# letting the deploy workflow finish.
set -euo pipefail
cd "$(dirname "$0")/.."
NS=minifiles
ACR=minifilesacrxw2sijbw.azurecr.io

step() { printf '\n== %s\n' "$*"; }

step "argo application Synced + Healthy"
SYNC=""; HEALTH=""
for _ in $(seq 1 60); do
  SYNC=$(kubectl -n argocd get application minifiles -o jsonpath='{.status.sync.status}')
  HEALTH=$(kubectl -n argocd get application minifiles -o jsonpath='{.status.health.status}')
  [ "$SYNC" = Synced ] && [ "$HEALTH" = Healthy ] && break
  sleep 10
done
[ "$SYNC" = Synced ] && [ "$HEALTH" = Healthy ] \
  || { echo "FAIL: application is $SYNC/$HEALTH"; exit 1; }
REV=$(kubectl -n argocd get application minifiles -o jsonpath='{.status.sync.revision}')
echo "Synced/Healthy at $REV"

step "deployed image is the CI-built ACR image"
IMAGE=$(kubectl -n "$NS" get deploy control-plane -o jsonpath='{.spec.template.spec.containers[0].image}')
case "$IMAGE" in
  "$ACR"/minifiles/control-plane:*) echo "image: $IMAGE" ;;
  *) echo "FAIL: unexpected image $IMAGE"; exit 1 ;;
esac

step "API healthy via LoadBalancer"
LB=$(kubectl -n "$NS" get svc control-plane -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
[ -n "$LB" ] || { echo "FAIL: no LoadBalancer IP yet"; exit 1; }
curl -sf --max-time 10 "http://$LB:8000/healthz" >/dev/null \
  || { echo "FAIL: healthz not answering on $LB:8000"; exit 1; }
echo "http://$LB:8000 ok"

step "prometheus scrapes minifiles metrics"
kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-prometheus 19090:9090 >/dev/null 2>&1 &
PF=$!
trap 'kill $PF 2>/dev/null' EXIT
sleep 4
SERIES=$(curl -sf 'http://localhost:19090/api/v1/query?query=minifiles_provisioned_gib' \
  | python3 -c 'import sys,json;print(len(json.load(sys.stdin)["data"]["result"]))')
[ "$SERIES" -ge 1 ] || { echo "FAIL: no minifiles series in prometheus"; exit 1; }
echo "prometheus sees minifiles metrics ($SERIES series)"

printf '\nPASS: M3 acceptance criteria met (GitOps rollout live, monitoring scraping)\n'
printf 'Grafana for the README screenshot: kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80\n'
printf '(admin password: kubectl -n monitoring get secret monitoring-grafana -o jsonpath="{.data.admin-password}" | base64 -d)\n'
