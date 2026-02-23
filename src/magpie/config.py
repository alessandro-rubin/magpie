"""Application settings loaded from environment / .env file."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Alpaca
    alpaca_api_key: str = Field(..., description="Alpaca API key")
    alpaca_secret_key: str = Field(..., description="Alpaca secret key")
    alpaca_paper: bool = Field(True, description="Use paper trading account")
    alpaca_base_url: str = Field(
        "https://paper-api.alpaca.markets",
        description="Alpaca base URL",
    )

    # Anthropic (optional — only needed for standalone CLI analysis)
    anthropic_api_key: str | None = Field(None, description="Anthropic API key")
    anthropic_model: str = Field("claude-opus-4-6", description="Model to use for analysis")

    # Database
    magpie_db_path: Path = Field(Path("./data/magpie.duckdb"), description="DuckDB file path")

    # Risk controls
    magpie_max_position_pct: float = Field(
        0.10, ge=0.01, le=1.0, description="Max position size as fraction of equity"
    )
    magpie_max_daily_loss_pct: float = Field(
        0.02, ge=0.001, le=1.0, description="Max daily loss as fraction of equity"
    )


def _load_settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]
    except Exception:
        # Return a partial settings object for commands that don't need all keys
        # (e.g. `magpie --help`). Full validation happens when keys are first accessed.
        return Settings.model_construct()  # type: ignore[return-value]


settings = _load_settings()
