"""Prometheus metrics: request latency middleware plus gauges computed from
the store at scrape time (no counters to keep in sync with CRUD paths)."""

import time

from fastapi import Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Histogram, generate_latest
from prometheus_client.core import GaugeMetricFamily

from app.store import store

REQUEST_LATENCY = Histogram(
    "minifiles_http_request_duration_seconds",
    "API request latency",
    ["method", "route", "status"],
)


class StoreCollector:
    """Computes resource gauges from the store on every scrape."""

    def collect(self):
        volumes = GaugeMetricFamily(
            "minifiles_volumes", "Volumes by lifecycle state", labels=["state"]
        )
        by_state: dict[str, int] = {}
        for vol in store.list_volumes():
            by_state[vol.state.value] = by_state.get(vol.state.value, 0) + 1
        for state, count in by_state.items():
            volumes.add_metric([state], count)
        yield volumes
        yield GaugeMetricFamily(
            "minifiles_provisioned_gib",
            "Total provisioned capacity in GiB",
            value=store.total_provisioned_gib(),
        )
        yield GaugeMetricFamily(
            "minifiles_snapshots", "Snapshot count", value=len(store.snapshots)
        )


REGISTRY.register(StoreCollector())


async def latency_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    # label with the route template (/v1/volumes/{volume_id}), never the raw
    # path — raw paths make label cardinality unbounded
    if route is not None and route.path != "/metrics":
        REQUEST_LATENCY.labels(request.method, route.path, str(response.status_code)).observe(
            time.perf_counter() - start
        )
    return response


def metrics_endpoint() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
