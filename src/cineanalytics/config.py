"""Configuração lida de variáveis de ambiente e do arquivo .env."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", env_prefix="CINEANALYTICS_", extra="ignore"
    )

    openrouter_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENROUTER_API_KEY", "CINEANALYTICS_OPENROUTER_API_KEY"),
    )
    # Ordem de preferência: o primeiro é o principal, os demais são fallback.
    # No .env: CINEANALYTICS_MODELS=fornecedor/modelo-a:free,fornecedor/modelo-b:free
    models: Annotated[list[str], NoDecode] = Field(default_factory=list)

    db_path: Path = Path("data/cinerocket.db")
    max_rows: int = Field(default=50, ge=1, le=500)
    query_timeout_s: float = Field(default=10.0, gt=0)
    # Teto de chamadas ao LLM por pergunta. Protege a cota diária do OpenRouter.
    request_limit: int = Field(default=6, ge=2)
    # Quantas perguntas anteriores o modo chat mantém como memória.
    history_turns: int = Field(default=5, ge=0)

    # Cache de respostas, log de perguntas e resultados de avaliação ficam aqui.
    state_dir: Path = Path(".cineanalytics")
    cache_enabled: bool = True
    reports_dir: Path = Path("reports")

    @property
    def cache_dir(self) -> Path:
        return self.state_dir / "cache"

    @property
    def runs_path(self) -> Path:
        return self.state_dir / "runs.jsonl"

    @property
    def evals_dir(self) -> Path:
        return self.state_dir / "evals"

    @field_validator("models", mode="before")
    @classmethod
    def _split_models(cls, value: object) -> object:
        if isinstance(value, str):
            return [m.strip() for m in value.split(",") if m.strip()]
        return value

    def require_llm(self) -> tuple[str, list[str]]:
        """Retorna (api_key, modelos) ou explica o que falta configurar."""
        missing = []
        if self.openrouter_api_key is None:
            missing.append("OPENROUTER_API_KEY")
        if not self.models:
            missing.append("CINEANALYTICS_MODELS")
        if missing:
            raise RuntimeError(
                f"Configuração ausente: {', '.join(missing)}. "
                "Copie .env.example para .env e preencha os valores (veja o README)."
            )
        return self.openrouter_api_key.get_secret_value(), self.models