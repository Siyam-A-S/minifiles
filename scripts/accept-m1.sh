#!/usr/bin/env bash
# M1 acceptance: create a volume via the API, mount its NFS
# export from a client pod, write+read a file, delete the volume, verify the
# PVC is gone. Prints PASS or fails loudly.
set -euo pipefail

API=localhost:8471
NS=minifiles

jsonval() { python3 -c "import sys,json;print(json.load(sys.stdin)[\"$1\"])"; }

step() { printf '\n== %s\n' "$*"; }

wait_healthz() {
  # plain poll: curl --retry doesn't cover connection-reset, which the
  # Recreate strategy produces while no pod is serving
  for _ in $(seq 1 60); do
    curl -sf "$API/healthz" >/dev/null 2>&1 && return 0
    sleep 2
  done
  echo "FAIL: control plane not responding on $API"
  return 1
}

step "cluster + deploy"
kind get clusters 2>/dev/null | grep -qx minifiles || make kind-up
make deploy-local
kubectl -n "$NS" rollout status deploy/control-plane --timeout=180s
wait_healthz

step "clean leftovers from previous runs"
# The dev cluster is disposable: reap the client pod and any orphaned
# data-plane resources (the in-memory store forgets volumes on redeploy).
kubectl -n "$NS" delete pod m1-client --ignore-not-found --now
kubectl -n "$NS" delete sts,svc,pvc -l "minifiles.io/volume-id" --ignore-not-found
# The store is in-memory: restart the control plane so its state matches the
# cleaned cluster (and so ConfigMap changes are picked up).
kubectl -n "$NS" rollout restart deploy/control-plane
kubectl -n "$NS" rollout status deploy/control-plane --timeout=120s
wait_healthz

step "create volume"
# Retry: right after a rollout restart the NodePort can briefly route to the
# terminating pod. Unique name so a half-landed earlier attempt can't 409 us.
VOL_NAME="m1-accept-$(date +%s)"
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

step "mount from client pod and write+read"
CLUSTER_IP=$(kubectl -n "$NS" get svc "$VOL_ID" -o jsonpath='{.spec.clusterIP}')
kubectl -n "$NS" apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: m1-client
spec:
  restartPolicy: Never
  containers:
    - name: client
      image: busybox:1.36
      command: ["sh", "-c", "sleep 600"]
      volumeMounts:
        - name: vol
          mountPath: /mnt/vol
  volumes:
    - name: vol
      nfs:
        server: $CLUSTER_IP
        path: /data
EOF
kubectl -n "$NS" wait --for=condition=Ready pod/m1-client --timeout=120s
kubectl -n "$NS" exec m1-client -- sh -c 'echo hello-m1 > /mnt/vol/accept.txt && cat /mnt/vol/accept.txt' \
  | grep -qx hello-m1 || { echo "FAIL: write/read through NFS mount failed"; exit 1; }
echo "write+read through NFS: ok"
kubectl -n "$NS" delete pod m1-client --now

step "delete volume and verify teardown"
HTTP=$(curl -s -o /dev/null -w '%{http_code}' -X DELETE "$API/v1/volumes/$VOL_ID")
[ "$HTTP" = 204 ] || { echo "FAIL: DELETE returned $HTTP"; exit 1; }
for _ in $(seq 1 60); do
  LEFT=$(kubectl -n "$NS" get pvc,pod,svc -l "minifiles.io/volume-id=$VOL_ID" --no-headers 2>/dev/null | wc -l)
  [ "$LEFT" = 0 ] && break
  sleep 2
done
[ "$LEFT" = 0 ] || { echo "FAIL: data-plane resources still present"; kubectl -n "$NS" get pvc,pod,svc -l "minifiles.io/volume-id=$VOL_ID"; exit 1; }

printf '\nPASS: M1 acceptance criteria met\n'
