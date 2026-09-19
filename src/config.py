from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Discord
    discord_bot_token: str
    discord_home_channel: int = 0
    allow_all_users: bool = True

    # vLLM inference (OpenAI-compatible endpoint used via LangChain)
    vllm_base_url: str = "http://127.0.0.1:8000/v1"
    vllm_model: str = "neuralmagic/Meta-Llama-3.1-8B-Instruct-FP8"
    vllm_api_key: str = "EMPTY"
    vllm_timeout: float = 30.0
    vllm_max_retries: int = 3

    # Generation hyperparameters
    model_temperature: float = 0.1
    model_max_tokens: int = 1500
    context_history_limit: int = 8
    rate_limit_per_minute: int = 15

    # POC Discord IDs for escalation routing
    poc_discord_sanskruti: str = ""
    poc_discord_sreesanth: str = ""
    poc_discord_nitish: str = ""

    # Escalation router
    enable_dm_routing: bool = True
    escalation_cooldown_hours: int = 2
    enable_p0_override: bool = True

    # Discord message limits
    max_message_length: int = Field(default=2000, ge=500)

    # Database
    database_url: str = ""

    # Production operations
    log_level: str = "INFO"
    health_check_interval: int = 60
    knowledge_reload_interval: int = 300
    max_conversation_turns: int = 8
    db_path: str = "data/hrcc.db"


settings = Settings()  # type: ignore[call-arg]
