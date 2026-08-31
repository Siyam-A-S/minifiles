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

    model_config = {"env_prefix": "MINIFILES_"}


settings = Settings()
