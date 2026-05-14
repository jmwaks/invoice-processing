from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    xai_api_key: str = ""
    xai_model: str = "grok-4"
    xai_base_url: str = "https://api.x.ai/v1"
    xai_fallback_model: str = "grok-3"

    invoice_processing_log_dir: Path = Path("./logs")
    invoice_processing_invoices_dir: Path = Path("./data/invoices")
    invoice_processing_db_path: Path = Path("./data/inventory.db")

    run_live_tests: bool = False

    manual_cost_per_invoice_usd: float = 12.0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
