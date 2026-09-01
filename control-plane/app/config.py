from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All knobs come from MINIFILES_* env vars so k8s ConfigMaps map 1:1."""

    max_total_gib: int = 100
    provisioner: str = "memory"  # "memory" | "kubernetes"
    namespace: str = "minifiles"
    nfs_image: str = "minifiles/nfs-godzilla:dev"
    storage_class: str = "standard"  # kind's default local-path provisioner
    provision_timeout_s: float = 120
    poll_interval_s: float = 2
    # Tiering: a per-volume CronJob (created with the volume when enabled)
    # and on-demand rehydrate Jobs, both mounting the volume's PVC and
    # reading Azure credentials from `azure_secret_name`.
    tiering_enabled: bool = False
    tiering_image: str = "minifiles/tiering-engine:dev"
    tiering_schedule: str = "0 * * * *"
    cold_after_days: float = 30
    azure_secret_name: str = "minifiles-azure"
    pushgateway_url: str = ""  # e.g. http://pushgateway.monitoring.svc:9091; empty = no push

    model_config = {"env_prefix": "MINIFILES_"}


settings = Settings()
