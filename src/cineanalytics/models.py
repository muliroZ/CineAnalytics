"""Modelos de dados compartilhados entre agente, cache, CLI e relatórios."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class QueryLog(BaseModel):
    sql: str
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    truncated: bool = False
    elapsed_ms: float = 0.0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class AgentRun(BaseModel):
    """Registro completo de uma pergunta: alimenta a CLI, o cache e o relatório."""

    pergunta: str
    resposta: str | None = None
    erro: str | None = None
    modelo: str | None = None
    consultas: list[QueryLog] = Field(default_factory=list)
    requisicoes: int = 0
    tokens_entrada: int = 0
    tokens_saida: int = 0
    duracao_s: float = 0.0
    cache_hit: bool = False
    criado_em: datetime = Field(default_factory=datetime.now)

    @property
    def ok(self) -> bool:
        return self.erro is None and self.resposta is not None

    @property
    def consulta_final(self) -> QueryLog | None:
        """A última consulta bem-sucedida, que normalmente embasa a resposta."""
        return next((q for q in reversed(self.consultas) if q.ok), None)