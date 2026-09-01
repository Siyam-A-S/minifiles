from fastapi import FastAPI

from app.api import health, snapshots, volumes
from app.metrics import latency_middleware, metrics_endpoint

app = FastAPI(
    title="MiniFiles Control Plane",
    version="0.1.0",
    description="Volume/snapshot lifecycle API for the MiniFiles storage service.",
)
app.middleware("http")(latency_middleware)
app.add_api_route("/metrics", metrics_endpoint, methods=["GET"], include_in_schema=False)
app.include_router(health.router)
app.include_router(volumes.router, prefix="/v1")
app.include_router(snapshots.router, prefix="/v1")
