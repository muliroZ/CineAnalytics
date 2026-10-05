"""Configuração lida de variáveis de ambiente e de arquivos .env.

Ordem de prioridade, da maior para a menor:
1. variáveis de ambiente;
2. `.env` na pasta atual (configuração do projeto);
3. `.env` global do usuário (criado pelo instalador):
   - Linux e macOS: ~/.config/cineanalytics/.env (ou $XDG_CONFIG_HOME/cineanalytics/.env)
   - Windows: %APPDATA%\\cineanalytics\\.env
   A pasta pode ser trocada com a variável CINEANALYTICS_CONFIG_DIR.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="CINEANALYTICS_",
        extra="ignore",
        # `OPENROUTER_API_KEY=` vazio conta como ausente, e não como uma chave vazia.
        env_ignore_empty=True,
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
                f"Defina no .env global ({user_env_file()}) ou num .env na pasta atual. "
                "Use `cineanalytics config` para ver de onde vem cada configuração."
            )
        return self.openrouter_api_key.get_secret_value(), self.models


# ------------------------------------------------------------ configuração global
LOCAL_ENV_FILE = Path(".env")


def user_config_dir() -> Path:
    """Pasta da configuração global do usuário (mesma lógica dos instaladores)."""
    if custom := os.environ.get("CINEANALYTICS_CONFIG_DIR"):
        return Path(custom).expanduser()
    if os.name == "nt":
        base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "cineanalytics"


def user_env_file() -> Path:
    return user_config_dir() / ".env"


def load_settings() -> Settings:
    """Lê o .env global e o local; o local (pasta atual) tem prioridade."""
    return Settings(_env_file=(user_env_file(), LOCAL_ENV_FILE))