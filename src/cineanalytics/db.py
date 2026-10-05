"""Acesso ao cinerocket.db.

Três camadas de proteção (a quarta, a validação com sqlglot, fica em guardrails.py):
1. Conexão aberta com `mode=ro`: o arquivo não pode ser alterado.
2. Authorizer do SQLite: depois de criadas as views, só leitura é permitida.
3. Timeout por consulta e limite de linhas retornadas.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .views import VIEWS, View


class QueryExecutionError(RuntimeError):
    """Erro do SQLite ao executar a consulta (coluna inexistente, etc.)."""


class QueryTimeoutError(QueryExecutionError):
    """A consulta passou do tempo limite."""


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]
    truncated: bool
    elapsed_ms: float


_ALLOWED_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    getattr(sqlite3, "SQLITE_RECURSIVE", 33),
}


def _read_only_authorizer(action: int, *_: Any) -> int:
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


class Database:
    def __init__(self, path: str | Path, *, max_rows: int = 50, timeout_s: float = 10.0):
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(
                f"Banco não encontrado em '{self.path}'. "
                "Baixe o cinerocket.db e coloque-o na pasta data/ (veja o README)."
            )
        self.max_rows = max_rows
        self.timeout_s = timeout_s
        self.views: tuple[View, ...] = VIEWS
        # Pydantic-AI executa tools síncronas em threads; o lock serializa o acesso.
        self._lock = threading.Lock()

        uri = self.path.resolve().as_uri() + "?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True, check_same_thread=False)

        for view in self.views:
            self._conn.execute(f"CREATE TEMP VIEW {view.name} AS {view.sql}")
        self.reference_year: int | None = self._conn.execute(
            "SELECT MAX(ano_lancamento) FROM dim_movies WHERE status_filme = 'Lançado'"
        ).fetchone()[0]
        self.genres: list[str] = [
            r[0] for r in self._conn.execute("SELECT DISTINCT nome_genero FROM vw_generos_filme ORDER BY 1")
        ]

        self._conn.set_authorizer(_read_only_authorizer)

    # ------------------------------------------------------------------ execução
    @property
    def allowed_tables(self) -> list[str]:
        return [v.name for v in self.views]

    def execute(self, sql: str, *, max_rows: int | None = None) -> QueryResult:
        limit = self.max_rows if max_rows is None else max_rows
        with self._lock:
            deadline = time.monotonic() + self.timeout_s
            self._conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
            start = time.perf_counter()
            try:
                cursor = self._conn.execute(sql)
                rows = cursor.fetchmany(limit + 1)
                columns = [d[0] for d in cursor.description or []]
                cursor.close()
            except sqlite3.OperationalError as e:
                if "interrupted" in str(e).lower():
                    raise QueryTimeoutError(
                        f"A consulta excedeu {self.timeout_s:.0f}s. Simplifique-a ou filtre mais os dados."
                    ) from e
                raise QueryExecutionError(str(e)) from e
            except sqlite3.Error as e:
                raise QueryExecutionError(str(e)) from e
            finally:
                self._conn.set_progress_handler(None, 0)

        elapsed_ms = (time.perf_counter() - start) * 1000
        return QueryResult(
            columns=columns,
            rows=[tuple(r) for r in rows[:limit]],
            truncated=len(rows) > limit,
            elapsed_ms=round(elapsed_ms, 1),
        )

    # ------------------------------------------------------------- introspecção
    def schema_prompt(self, sample_rows: int = 2, max_chars: int = 40) -> str:
        """Descrição das views em Markdown, para o system prompt do agente."""
        parts: list[str] = []
        for view in self.views:
            lines = [f"### {view.name}", view.description, ""]
            lines += [f"- `{c.name}` ({c.type}): {c.description}" for c in view.columns]
            if sample_rows:
                # Hashes e textos longos gastam tokens sem ensinar nada ao modelo.
                cols = [
                    c.name for c in view.columns
                    if not c.name.startswith(("sk_", "id_")) and c.name not in ("sinopse", "texto")
                ]
                sample = self.execute(f"SELECT {', '.join(cols)} FROM {view.name}", max_rows=sample_rows)
                if sample.rows:
                    lines += ["", "Exemplo de linhas:", f"`{' | '.join(cols)}`"]
                    lines += [f"`{' | '.join(_short(v, max_chars) for v in row)}`" for row in sample.rows]
            parts.append("\n".join(lines))
        return "\n\n".join(parts)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


def _short(value: Any, max_chars: int) -> str:
    text = "NULL" if value is None else str(value)
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"