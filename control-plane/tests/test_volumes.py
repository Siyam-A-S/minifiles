import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.store import store


@pytest.fixture(autouse=True)
def clean_store():
    store.volumes.clear()
    store.snapshots.clear()
    yield


@pytest.fixture
def client():
    return TestClient(app)


def _create(client, name="vol1", size_gib=10, service_level="standard"):
    return client.post(
        "/v1/volumes",
        json={"name": name, "size_gib": size_gib, "service_level": service_level},
    )


def test_create_volume_becomes_available(client):
    resp = _create(client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["state"] == "available"
    assert body["export_path"] == "/exports/vol1"


def test_duplicate_name_rejected(client):
    assert _create(client).status_code == 201
    assert _create(client).status_code == 409


def test_quota_enforced(client):
    assert _create(client, name="big", size_gib=90).status_code == 201
    resp = _create(client, name="overflow", size_gib=20)
    assert resp.status_code == 409
    assert "quota exceeded" in resp.json()["detail"]


def test_invalid_name_rejected(client):
    assert _create(client, name="Bad_Name!").status_code == 422


def test_get_list_delete_roundtrip(client):
    vol_id = _create(client).json()["id"]
    assert client.get(f"/v1/volumes/{vol_id}").status_code == 200
    assert len(client.get("/v1/volumes").json()) == 1
    assert client.delete(f"/v1/volumes/{vol_id}").status_code == 204
    assert client.get(f"/v1/volumes/{vol_id}").status_code == 404


def test_rehydrate_endpoint(client):
    vol_id = _create(client).json()["id"]
    resp = client.post(f"/v1/volumes/{vol_id}/rehydrate")
    assert resp.status_code == 202
    assert resp.json() == {"volume_id": vol_id, "job": "rehydrate-inline"}
    assert client.post("/v1/volumes/vol-missing/rehydrate").status_code == 404


def test_snapshot_lifecycle(client):
    vol_id = _create(client).json()["id"]
    resp = client.post(f"/v1/volumes/{vol_id}/snapshots", json={"name": "snap1"})
    assert resp.status_code == 201
    assert resp.json()["volume_id"] == vol_id
    # duplicate snapshot name on same volume
    assert client.post(f"/v1/volumes/{vol_id}/snapshots", json={"name": "snap1"}).status_code == 409
    assert len(client.get(f"/v1/volumes/{vol_id}/snapshots").json()) == 1
    # snapshots are removed with their volume
    client.delete(f"/v1/volumes/{vol_id}")
    assert client.get(f"/v1/volumes/{vol_id}/snapshots").status_code == 404
