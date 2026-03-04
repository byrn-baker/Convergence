from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Threat intelligence API keys
    abuseipdb_api_key: str = ""
    greynoise_api_key: str = ""
    otx_api_key: str = ""
    ipinfo_token: str = ""
    anthropic_api_key: str = ""

    # LLM provider: "anthropic" (default) or "ollama"
    llm_provider: str = "anthropic"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"

    # Infrastructure
    redis_url: str = "redis://redis:6379/0"
    victoriametrics_url: str = "http://victoriametrics:8428"
    loki_url: str = "http://loki:3100"

    # Service behaviour
    enrichment_interval_seconds: int = 3600  # 1 hour
    top_blocked_ips: int = 50
    top_outbound_ips: int = 20
    cache_ttl_seconds: int = 86400  # 24 hours
    abuseipdb_daily_budget: int = 900  # free tier is 1000/day; keep 10% reserve
    lookback_hours: int = 1

    # Data directory (port_services.json lives here)
    data_dir: str = "/app/data"


settings = Settings()
