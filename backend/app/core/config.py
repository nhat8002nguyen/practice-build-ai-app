from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_JWT_SECRET = "dev-only-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "smb-support-copilot"
    app_env: str = "development"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/copilot"
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    jwt_secret: str = DEFAULT_JWT_SECRET
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    chunk_strategy: str = "parent_child"
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    qdrant_collection: str = "knowledge_chunks"
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    anthropic_model: str = "claude-haiku-4-5"
    # Gate applies to merge_hybrid scores. Default 0.3 pairs with dense_weight 0.7 so
    # single-channel strong hits and mid-strength both-present scores (e.g. 0.4/0.2) clear.
    retrieval_min_score: float = 0.3
    retrieval_dense_weight: float = 0.7
    chat_history_turns: int = 6
    cors_origins: str = "http://localhost:5173,http://localhost:8081"
    n8n_draft_secret: str = ""
    draft_user_email: str = ""
    llm_timeout_seconds: float = Field(default=60, gt=0)
    rate_limit_enabled: bool = True
    rate_limit_chat_burst: int = Field(default=10, ge=1)
    rate_limit_chat_per_minute: int = Field(default=30, ge=1)
    rate_limit_drafts_burst: int = Field(default=10, ge=1)
    rate_limit_drafts_per_minute: int = Field(default=30, ge=1)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


def validate_production_settings(current: Settings) -> None:
    if current.is_production and current.jwt_secret == DEFAULT_JWT_SECRET:
        raise RuntimeError("JWT_SECRET must be changed when APP_ENV=production")


settings = Settings()
