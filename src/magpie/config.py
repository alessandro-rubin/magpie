"""Application settings loaded from environment / .env file."""

import logging
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


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

    # LLM provider (anthropic or groq)
    llm_provider: str = Field("anthropic", description="LLM provider: 'anthropic' or 'groq'")

    # Anthropic (optional — only needed for standalone CLI analysis)
    anthropic_api_key: str | None = Field(None, description="Anthropic API key")
    anthropic_model: str = Field("claude-opus-4-6", description="Anthropic model to use for analysis")

    # Groq (optional — alternative LLM provider)
    groq_api_key: str | None = Field(None, description="Groq API key")
    groq_model: str = Field("llama-3.3-70b-versatile", description="Groq model to use for analysis")

    # Database
    magpie_db_path: Path = Field(Path("./data/magpie.sqlite"), description="SQLite file path")

    # Risk controls
    magpie_max_position_pct: float = Field(
        0.10, ge=0.01, le=1.0, description="Max position size as fraction of equity"
    )
    magpie_max_daily_loss_pct: float = Field(
        0.02, ge=0.001, le=1.0, description="Max daily loss as fraction of equity"
    )

    # Position management thresholds
    magpie_profit_target_pct: float = Field(
        0.50, ge=0.1, le=1.0, description="Close at this fraction of max profit (default 50%)"
    )
    magpie_stop_loss_pct: float = Field(
        1.0, ge=0.1, le=2.0, description="Close at this fraction of max loss (default 100%)"
    )
    magpie_min_dte_close: int = Field(
        3, ge=0, le=30, description="Close positions with DTE at or below this (gamma risk)"
    )

    # Autonomous agent loop
    magpie_auto_trade_max_cost: float = Field(
        0.0, ge=0.0, description="Max trade cost ($) for auto-execution (0 = always require human approval)"
    )
    magpie_agent_interval: int = Field(
        1800, ge=60, description="Agent scan interval in seconds (default 30 min)"
    )

    # HTTP API server (for OpenClaw skill integration)
    magpie_api_port: int = Field(8080, description="HTTP API server port")
    magpie_api_key: str | None = Field(None, description="Local API auth key (None = no auth required)")


def _load_settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]
    except Exception as exc:
        logger.warning("Failed to load settings: %s. Some commands may not work.", exc)
        return Settings.model_construct()  # type: ignore[return-value]


settings = _load_settings()
