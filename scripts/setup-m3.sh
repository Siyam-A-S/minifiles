#!/usr/bin/env bash
# One-time AKS bootstrap for M3 (idempotent): kubeconfig, Argo CD + private
# repo access (deploy key), the minifiles Application, kube-prometheus-stack
# + pushgateway, and the Azure tiering secret. Everything applied here is
# either cluster plumbing or credentials — the app itself arrives via GitOps.
set -euo pipefail
cd "$(dirname "$0")/.."

RG=$(terraform -chdir=deploy/terraform output -raw resource_group)
AKS=$(terraform -chdir=deploy/terraform output -raw aks_name)
CONN=$(terraform -chdir=deploy/terraform output -raw connection_string)
CONTAINER=$(terraform -chdir=deploy/terraform output -raw container_name)

step() { printf '\n== %s\n' "$*"; }

step "kubeconfig for $AKS"
az aks get-credentials -g "$RG" -n "$AKS" --overwrite-existing

step "argo cd"
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
# server-side: the applicationsets CRD exceeds the client-side annotation limit
kubectl apply --server-side --force-conflicts -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml >/dev/null
kubectl -n argocd rollout status deploy/argocd-repo-server --timeout=300s

step "repo deploy key for argo (read-only)"
KEY=~/.ssh/minifiles_argocd
if [ ! -f "$KEY" ]; then
  ssh-keygen -t ed25519 -N "" -f "$KEY" -C "argocd@minifiles" >/dev/null
  gh repo deploy-key add "$KEY.pub" --title "argocd-readonly"
fi
kubectl -n argocd create secret generic minifiles-repo \
  --from-literal=type=git \
  --from-literal=url=git@github.com:Siyam-A-S/minifiles.git \
  --from-file=sshPrivateKey="$KEY" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n argocd label secret minifiles-repo argocd.argoproj.io/secret-type=repository --overwrite

step "minifiles application"
kubectl apply -f deploy/argocd/application.yaml

step "monitoring stack"
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
helm repo update >/dev/null
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace --wait --timeout 10m \
  --set alertmanager.enabled=false \
  --set prometheus.prometheusSpec.retention=24h \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
  --set grafana.sidecar.dashboards.searchNamespace=ALL
helm upgrade --install pushgateway prometheus-community/prometheus-pushgateway \
  --namespace monitoring --wait --timeout 5m \
  --set serviceMonitor.enabled=true

step "azure tiering secret"
kubectl create namespace minifiles --dry-run=client -o yaml | kubectl apply -f -
kubectl -n minifiles create secret generic minifiles-azure \
  --from-literal=MINIFILES_AZURE_CONN_STRING="$CONN" \
  --from-literal=MINIFILES_AZURE_CONTAINER="$CONTAINER" \
  --dry-run=client -o yaml | kubectl apply -f -

printf '\nBootstrap complete. Grafana: kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80\n'
printf 'Argo UI:  kubectl -n argocd port-forward svc/argocd-server 8080:443\n'
