"""Agente Text-to-SQL da CineAnalytics.

Fluxo típico de uma pergunta (2 requisições ao LLM):
  1. o modelo lê o schema no prompt e chama `run_sql` com uma consulta;
  2. o modelo recebe o resultado e escreve a resposta final.
Se o SQL falhar (guardrail ou erro do SQLite), o erro volta para o modelo via
ModelRetry e ele corrige a consulta, ao custo de uma requisição extra.

A saída do agente é texto livre, e não um objeto estruturado: vários modelos
gratuitos falham ao preencher schemas de saída. Os dados estruturados (SQL,
linhas, tokens) são coletados pelas deps e montados em `AgentRun`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from importlib import resources
from typing import Any

from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.exceptions import (
    FallbackExceptionGroup,
    ModelAPIError,
    ModelHTTPError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.usage import UsageLimits

from .db import Database, QueryExecutionError, QueryResult
from .guardrails import SQLValidationError, validate_select
from .models import AgentRun, QueryLog
from .storage import ResponseCache

MAX_CELL_CHARS = 300


@dataclass
class Deps:
    db: Database
    queries: list[QueryLog] = field(default_factory=list)


# ----------------------------------------------------------------------- prompt
_ROLE = """\
Você é o analista de dados da CineAnalytics. Você responde perguntas de \
usuários não técnicos sobre um catálogo de filmes, consultando um banco SQLite.

## Como trabalhar
1. Use a ferramenta `run_sql` para consultar o banco. Nunca invente números: \
toda informação da resposta deve vir de uma consulta.
2. Cada chamada recebe uma única consulta SELECT e só pode usar as views descritas abaixo.
3. Tente resolver a pergunta com uma única consulta bem construída. Se ela falhar, \
leia o erro, corrija e tente de novo.
4. Se a pergunta não tiver relação com o catálogo de filmes ou não puder ser \
respondida com estes dados, explique isso com educação, sem consultar o banco.

## Resposta final
- Em português, direta, começando pela resposta à pergunta.
- Use uma tabela Markdown quando listar vários itens.
- Mencione os filtros aplicados e o tamanho da amostra quando forem relevantes.
- Não mostre o SQL: a interface já exibe as consultas executadas.
"""


def build_instructions(db: Database) -> str:
    glossary = (
        resources.files("cineanalytics.prompts").joinpath("regras_negocio.md").read_text(encoding="utf-8")
    )
    glossary = glossary.replace("{ano_referencia}", str(db.reference_year))
    genres = ", ".join(f"'{g}'" for g in db.genres)
    return (
        f"{_ROLE}\n"
        f"## Views disponíveis\n\n{db.schema_prompt()}\n\n"
        f"Gêneros existentes (use exatamente estes valores): {genres}\n\n"
        f"{glossary}"
    )


# ------------------------------------------------------------------- ferramenta
def format_result(result: QueryResult) -> str:
    """Resultado compacto para o modelo: menos tokens que JSON."""
    if not result.rows:
        return (
            "A consulta não retornou linhas. Confira os valores usados nos filtros "
            "(gêneros estão em inglês; para títulos e nomes, use LIKE)."
        )

    def cell(value: Any) -> str:
        text = "NULL" if value is None else str(value)
        return text if len(text) <= MAX_CELL_CHARS else text[: MAX_CELL_CHARS - 1] + "…"

    lines = [" | ".join(result.columns)]
    lines += [" | ".join(cell(v) for v in row) for row in result.rows]
    footer = f"({len(result.rows)} linhas)"
    if result.truncated:
        footer = (
            f"(resultado truncado nas primeiras {len(result.rows)} linhas; "
            "se precisar do total, use agregação ou LIMIT)"
        )
    return "\n".join([*lines, footer])


def build_agent(db: Database, model: Model | str, instructions: str | None = None) -> Agent[Deps, str]:
    agent = Agent(
        model,
        deps_type=Deps,
        output_type=str,
        instructions=instructions or build_instructions(db),
        retries=3,
        model_settings={"temperature": 0.0},
    )

    @agent.tool
    def run_sql(ctx: RunContext[Deps], sql: str) -> str:
        """Executa uma consulta SELECT no banco de filmes e retorna as linhas.

        Args:
            sql: Uma única consulta SQLite (SELECT ou WITH ... SELECT) usando apenas as views disponíveis.
        """
        try:
            safe_sql = validate_select(sql, ctx.deps.db.allowed_tables)
            result = ctx.deps.db.execute(safe_sql)
        except (SQLValidationError, QueryExecutionError) as e:
            ctx.deps.queries.append(QueryLog(sql=sql, error=str(e)))
            raise ModelRetry(f"A consulta falhou: {e}\nCorrija o SQL e tente novamente.") from e

        ctx.deps.queries.append(
            QueryLog(
                sql=safe_sql,
                columns=result.columns,
                rows=[list(r) for r in result.rows],
                truncated=result.truncated,
                elapsed_ms=result.elapsed_ms,
            )
        )
        return format_result(result)

    return agent


def build_model(model_names: list[str], api_key: str) -> Model:
    """Um modelo do OpenRouter ou, se houver mais de um, uma cadeia de fallback."""
    provider = OpenRouterProvider(api_key=api_key)
    models = [OpenRouterModel(name, provider=provider) for name in model_names]
    return models[0] if len(models) == 1 else FallbackModel(*models)


# ------------------------------------------------------------------- orquestração
class CineAgent:
    """Fachada usada pela CLI: mantém a memória da conversa e trata erros."""

    def __init__(
        self,
        db: Database,
        model: Model | str,
        *,
        request_limit: int = 6,
        history_turns: int = 5,
        cache: ResponseCache | None = None,
    ):
        self.db = db
        self.instructions = build_instructions(db)
        self.agent = build_agent(db, model, self.instructions)
        self.model_name = model if isinstance(model, str) else model.model_name
        self.request_limit = request_limit
        self.history_turns = history_turns
        self.cache = cache
        self.history: list[ModelMessage] = []

    def reset(self) -> None:
        self.history = []

    def ask(self, question: str, *, remember: bool = True, use_cache: bool = True) -> AgentRun:
        """Responde uma pergunta.

        O cache só é usado quando não há histórico: com memória, "e no ano anterior?"
        depende do contexto e a mesma frase pode ter respostas diferentes.
        """
        cacheable = use_cache and self.cache is not None and not self.history
        key = self.cache.key(question, model=self.model_name, prompt=self.instructions) if cacheable else None

        if key and (cached := self.cache.get(key)):
            run = cached.model_copy(
                update={
                    "pergunta": question,
                    "cache_hit": True,
                    "requisicoes": 0,
                    "tokens_entrada": 0,
                    "tokens_saida": 0,
                    "duracao_s": 0.0,
                    "criado_em": datetime.now(),
                }
            )
            if remember and self.history_turns:
                # Mantém a pergunta respondida pelo cache na memória da conversa.
                self.history = [
                    ModelRequest(parts=[UserPromptPart(question)]),
                    ModelResponse(parts=[TextPart(run.resposta or "")]),
                ]
            return run

        run = self._run(question, remember=remember)
        if key:
            self.cache.set(key, run)
        return run

    def _run(self, question: str, *, remember: bool) -> AgentRun:
        deps = Deps(db=self.db)
        run = AgentRun(pergunta=question)
        start = time.perf_counter()
        try:
            result = self.agent.run_sync(
                question,
                deps=deps,
                message_history=self.history or None,
                usage_limits=UsageLimits(request_limit=self.request_limit),
            )
        except UsageLimitExceeded:
            run.erro = (
                f"O agente usou o limite de {self.request_limit} chamadas ao modelo sem chegar "
                "a uma resposta. Tente reformular a pergunta de forma mais específica."
            )
        except (ModelHTTPError, ModelAPIError, FallbackExceptionGroup) as e:
            run.erro = _describe_api_error(e)
        except UnexpectedModelBehavior as e:
            run.erro = f"O modelo não conseguiu concluir a resposta ({e.message})."
        else:
            run.resposta = result.output
            run.modelo = _last_model_name(result.new_messages())
            # `usage` é método no Pydantic-AI 1.x e propriedade no 2.x.
            usage = result.usage() if callable(result.usage) else result.usage
            run.requisicoes = usage.requests
            run.tokens_entrada = usage.input_tokens
            run.tokens_saida = usage.output_tokens
            if remember and self.history_turns:
                self.history = trim_history(result.all_messages(), self.history_turns)

        run.consultas = deps.queries
        run.duracao_s = round(time.perf_counter() - start, 2)
        return run


# ---------------------------------------------------------------------- helpers
def trim_history(messages: list[ModelMessage], max_turns: int) -> list[ModelMessage]:
    """Mantém só as últimas `max_turns` perguntas, sem cortar no meio de um turno."""
    starts = [
        i
        for i, m in enumerate(messages)
        if isinstance(m, ModelRequest) and any(isinstance(p, UserPromptPart) for p in m.parts)
    ]
    if len(starts) <= max_turns:
        return messages
    return messages[starts[-max_turns]:]


def _last_model_name(messages: list[ModelMessage]) -> str | None:
    for m in reversed(messages):
        if isinstance(m, ModelResponse) and m.model_name:
            return m.model_name
    return None


def _describe_api_error(error: Exception) -> str:
    errors = list(error.exceptions) if isinstance(error, FallbackExceptionGroup) else [error]
    if any(isinstance(e, ModelHTTPError) and e.status_code == 429 for e in errors):
        return (
            "Limite de requisições do OpenRouter atingido (modelos gratuitos: 50 por dia "
            "na conta gratuita, além de limites por minuto). Aguarde e tente novamente, "
            "ou configure outro modelo em CINEANALYTICS_MODELS."
        )
    if any(isinstance(e, ModelHTTPError) and e.status_code in (401, 403) for e in errors):
        return "A chave do OpenRouter foi recusada. Confira OPENROUTER_API_KEY no .env."
    detail = "; ".join(str(e) for e in errors)
    return f"Falha ao chamar o modelo: {detail}"