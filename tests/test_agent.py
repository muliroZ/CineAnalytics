"""Testes do agente com FunctionModel: nenhum teste chama o OpenRouter."""

from helpers import scripted
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    RetryPromptPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import FunctionModel

from cineanalytics.agent import (
    CineAgent,
    build_instructions,
    format_result,
    trim_history,
)
from cineanalytics.db import QueryResult

SQL_OK = "SELECT titulo, receita_brl FROM vw_filmes WHERE receita_brl IS NOT NULL ORDER BY receita_brl DESC LIMIT 3"


def _last_parts(messages: list[ModelMessage]):
    return messages[-1].parts if isinstance(messages[-1], ModelRequest) else []


def test_instrucoes_tem_schema_generos_e_ano(db):
    text = build_instructions(db)
    assert "### vw_filmes" in text
    assert "'Drama'" in text and "'Ação'" in text
    assert "ano_lancamento > 2026 - N" in text
    assert "{ano_referencia}" not in text


def test_fluxo_feliz_uma_consulta(db):
    model, calls = scripted(SQL_OK, "FINAL: O filme com maior receita é Delta.")
    run = CineAgent(db, model).ask("Top 3 receitas?")

    assert run.erro is None
    assert run.resposta == "O filme com maior receita é Delta."
    assert run.requisicoes == 2
    assert len(run.consultas) == 1
    assert run.consulta_final.rows[0] == ["Delta", 5_000_000.0]
    # O modelo recebeu o resultado formatado como tabela compacta.
    tool_return = next(p for p in _last_parts(calls[1]) if isinstance(p, ToolReturnPart))
    assert tool_return.content.startswith("titulo | receita_brl\nDelta | 5000000.0")


def test_sql_invalido_volta_para_o_modelo_corrigir(db):
    model, calls = scripted("SELECT * FROM dim_movies", SQL_OK, "FINAL: ok")
    run = CineAgent(db, model).ask("Top 3 receitas?")

    assert run.resposta == "ok"
    assert [q.ok for q in run.consultas] == [False, True]
    assert "não disponível" in run.consultas[0].error
    retry = next(p for p in _last_parts(calls[1]) if isinstance(p, RetryPromptPart))
    assert "vw_filmes" in str(retry.content)


def test_erro_do_sqlite_tambem_volta_para_o_modelo(db):
    model, _ = scripted("SELECT coluna_que_nao_existe FROM vw_filmes", SQL_OK, "FINAL: ok")
    run = CineAgent(db, model).ask("?")
    assert "no such column" in run.consultas[0].error
    assert run.resposta == "ok"


def test_limite_de_requisicoes_vira_erro_amigavel(db):
    model, _ = scripted(SQL_OK)  # nunca responde, só consulta
    run = CineAgent(db, model, request_limit=3).ask("?")
    assert run.resposta is None
    assert "limite de 3 chamadas" in run.erro
    assert len(run.consultas) >= 2


def test_rate_limit_do_openrouter_vira_erro_amigavel(db):
    def fn(messages, info):
        raise ModelHTTPError(status_code=429, model_name="modelo:free", body="rate limited")

    run = CineAgent(db, FunctionModel(fn)).ask("?")
    assert "Limite de requisições do OpenRouter" in run.erro


def test_memoria_da_conversa(db):
    model, calls = scripted("FINAL: resposta")
    agent = CineAgent(db, model)
    agent.ask("primeira pergunta")
    agent.ask("e a segunda?")
    prompts = [p.content for m in calls[-1] if isinstance(m, ModelRequest) for p in m.parts if hasattr(p, "content")]
    assert "primeira pergunta" in prompts and "e a segunda?" in prompts


def test_remember_false_nao_altera_memoria(db):
    model, _ = scripted("FINAL: resposta")
    agent = CineAgent(db, model)
    agent.ask("pergunta avulsa", remember=False)
    assert agent.history == []


def test_trim_history_mantem_turnos_inteiros(db):
    model, _ = scripted(SQL_OK, "FINAL: ok")
    agent = CineAgent(db, model, history_turns=2)
    for i in range(4):
        agent.ask(f"pergunta {i}")
    first = agent.history[0]
    assert isinstance(first, ModelRequest)
    assert first.parts[0].content == "pergunta 2"
    assert trim_history(agent.history, 10) == agent.history


def test_format_result_avisa_truncamento_e_vazio():
    truncated = QueryResult(columns=["a"], rows=[(1,), (2,)], truncated=True, elapsed_ms=1)
    assert "truncado" in format_result(truncated)
    empty = QueryResult(columns=["a"], rows=[], truncated=False, elapsed_ms=1)
    assert "LIKE" in format_result(empty)


def test_format_result_corta_textos_longos():
    result = QueryResult(columns=["sinopse"], rows=[("x" * 1000,)], truncated=False, elapsed_ms=1)
    assert len(format_result(result).splitlines()[1]) == 300