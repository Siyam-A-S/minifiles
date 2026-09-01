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


def test_metrics_reflect_store(client):
    client.post(
        "/v1/volumes",
        json={"name": "metricsvol", "size_gib": 7, "service_level": "standard"},
    )
    body = client.get("/metrics").text
    assert 'minifiles_volumes{state="available"} 1.0' in body
    assert "minifiles_provisioned_gib 7.0" in body


def test_request_latency_uses_route_template(client):
    vol_id = client.post(
        "/v1/volumes",
        json={"name": "latvol", "size_gib": 1, "service_level": "standard"},
    ).json()["id"]
    client.get(f"/v1/volumes/{vol_id}")
    body = client.get("/metrics").text
    # route template (prefix-less in this FastAPI version), never the raw
    # path — raw paths would make label cardinality unbounded
    assert 'route="/volumes/{volume_id}"' in body
    assert vol_id not in body
