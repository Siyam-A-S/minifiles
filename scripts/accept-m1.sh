#!/usr/bin/env bash
# M1 acceptance (docs/roadmap.md): create a volume via the API, mount its NFS
# export from a client pod, write+read a file, delete the volume, verify the
# PVC is gone. Prints PASS or fails loudly.
set -euo pipefail

API=localhost:8471
NS=minifiles

jsonval() { python3 -c "import sys,json;print(json.load(sys.stdin)[\"$1\"])"; }

step() { printf '\n== %s\n' "$*"; }

step "cluster + deploy"
kind get clusters 2>/dev/null | grep -qx minifiles || make kind-up
make deploy-local
kubectl -n "$NS" rollout status deploy/control-plane --timeout=180s
curl -sf --retry 30 --retry-connrefused --retry-delay 2 "$API/healthz" >/dev/null

step "create volume"
VOL_ID=$(curl -sf -X POST "$API/v1/volumes" -H 'content-type: application/json' \
  -d '{"name":"m1-accept","size_gib":1,"service_level":"standard"}' | jsonval id)
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
        path: /
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
