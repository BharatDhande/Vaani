"""
core/config.py
All environment variables and settings in one place.
Supports: OpenRouter API  +  Self-hosted model (vLLM / Ollama / LM Studio)
"""

from functools import lru_cache
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ─── App ───────────────────────────────────────────────
    APP_NAME: str = "AIRI Alex Assistant"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    ALLOWED_ORIGINS: list[str] = ["*"]   # tighten in production

    # ─── LLM Provider ──────────────────────────────────────
    # Options: "openrouter" | "self_hosted"
    LLM_PROVIDER: Literal["openrouter", "self_hosted"] = "openrouter"

    # ─── OpenRouter ────────────────────────────────────────
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    # Fast + cheap model for assistant tasks
    OPENROUTER_MODEL: str = "mistralai/mistral-7b-instruct:free"
    # e.g. other options:
    #   "openai/gpt-4o-mini"
    #   "anthropic/claude-3-haiku"
    #   "google/gemma-2-9b-it:free"

    # ─── Self-Hosted Model (vLLM / Ollama / LM Studio) ─────
    SELF_HOSTED_BASE_URL: str = "http://localhost:11434/v1"   # Ollama default
    SELF_HOSTED_API_KEY: str = "none"                         # vLLM may need key
    SELF_HOSTED_MODEL: str = "mistral:7b-instruct-q4_K_M"    # quantized

    # ─── LLM Generation Settings ───────────────────────────
    LLM_MAX_TOKENS: int = 512          # 256 was too small — JSON + sentence got cut off
    LLM_TEMPERATURE: float = 0.1      # low = deterministic JSON
    LLM_TIMEOUT: float = 8.0          # seconds

    # ─── Memory / Context ──────────────────────────────────
    MEMORY_MAX_TURNS: int = 10         # how many turns to keep in context
    REDIS_URL: str = "redis://localhost:6379/0"
    USE_REDIS: bool = False            # False = in-memory dict (dev mode)

    # ─── Intent Router ─────────────────────────────────────
    INTENT_CONFIDENCE_THRESHOLD: float = 0.85

    # ─── Rate Limiting ─────────────────────────────────────
    RATE_LIMIT_PER_MINUTE: int = 60

    # ─── Security ──────────────────────────────────────────
    API_KEY: str = ""                  # Optional: protect your API
    REQUIRE_API_KEY: bool = False

    # ─── TTS (optional) ────────────────────────────────────
    TTS_ENABLED: bool = False
    TTS_PROVIDER: Literal["google", "edge", "coqui"] = "edge"

    @property
    def llm_base_url(self) -> str:
        if self.LLM_PROVIDER == "openrouter":
            return self.OPENROUTER_BASE_URL
        return self.SELF_HOSTED_BASE_URL

    @property
    def llm_api_key(self) -> str:
        if self.LLM_PROVIDER == "openrouter":
            return self.OPENROUTER_API_KEY
        return self.SELF_HOSTED_API_KEY

    @property
    def llm_model(self) -> str:
        if self.LLM_PROVIDER == "openrouter":
            return self.OPENROUTER_MODEL
        return self.SELF_HOSTED_MODEL


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()