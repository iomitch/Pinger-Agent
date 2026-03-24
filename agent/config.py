from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    pinger_server_url: str = "http://localhost:8000"
    pinger_api_key: str = ""
    ping_interval_override: int | None = None
    batch_size: int = 10
    batch_flush_seconds: int = 5
    traceroute_interval_seconds: int = 120
    traceroute_max_hops: int = 30
    log_level: str = "INFO"

    model_config = {"env_prefix": ""}


settings = Settings()
