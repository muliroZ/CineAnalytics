from pathlib import Path

import pytest
from helpers import scripted
from test_eval_references import VIEW_SQL

from cineanalytics.agent import CineAgent
from cineanalytics.evaluation import (
    compare,
    evaluate,
    judge,
    load_questions,
    values_equal,
)
from cineanalytics.models import AgentRun, QueryLog

REF = [["Delta", 2025, 5_000_000.0], ["Alpha", 2023, 1_500_000.0], ["Gamma", 2024, 200_000.0]]


def q(columns, rows):
    return QueryLog(sql="-", columns=columns, rows=rows)


@pytest.mark.parametrize(("a", "b", "eq"), [
    (66.67, 66.6667, True), (66.67, 66.7, True), (1_500_000, 1_500_000.4, True),
    (7.5, 7.8, False), ("Delta ", "delta", True), (None, None, True), (None, 0, False),
])
def test_values_equal(a, b, eq):
    assert values_equal(a, b) is eq


def test_ordered_ignora_nome_e_posicao_das_colunas():
    got = q(["receita", "filme"], [[r[2], r[0]] for r in REF])
    assert compare(REF, got, "ordered", [0]) == (True, "ok")


def test_ordered_aceita_prefixo_mas_exige_minimo_de_linhas():
    ref10 = [[f"f{i}"] for i in range(10)]
    assert compare(ref10, q(["t"], ref10[:5]), "ordered", [0])[0]
    passed, reason = compare(ref10, q(["t"], ref10[:2]), "ordered", [0])
    assert not passed and "2 linha" in reason


def test_ordered_falha_com_ordem_errada():
    got = q(["t"], [[r[0]] for r in reversed(REF)])
    assert not compare(REF, got, "ordered", [0])[0]


def test_top1_so_olha_a_primeira_linha():
    got = q(["t"], [["Delta"], ["outro"]])
    assert compare(REF, got, "top1", [0])[0]


def test_set_exige_mesma_associacao_entre_colunas():
    ref = [["Drama", 10.0], ["Ação", 20.0]]
    assert compare(ref, q(["g", "v"], [["Ação", 20.0], ["Drama", 10.0]]), "set", [0, 1])[0]
    passed, reason = compare(ref, q(["g", "v"], [["Drama", 20.0], ["Ação", 10.0]]), "set", [0, 1])
    assert not passed and "associados" in reason


def test_judge_aceita_consulta_auxiliar_depois_da_principal():
    run = AgentRun(pergunta="?", resposta="ok", consultas=[
        q(["t"], [[r[0]] for r in REF]),
        q(["n"], [[3]]),  # ex.: o agente contou a amostra depois
    ])
    question = load_questions(Path("evals/questions.yaml"), ["fin_01"])[0]
    assert judge(question, run, REF)[0]


def test_judge_reprova_run_com_erro():
    question = load_questions(Path("evals/questions.yaml"), ["fin_01"])[0]
    assert judge(question, AgentRun(pergunta="?", erro="429"), REF) == (False, "429")


def test_ids_inexistentes_geram_erro():
    with pytest.raises(ValueError, match="xyz"):
        load_questions(Path("evals/questions.yaml"), ["fin_01", "xyz"])


@pytest.mark.parametrize("qid", sorted(VIEW_SQL))
def test_evaluate_ponta_a_ponta(db, qid):
    """Um 'agente' que escreve o SQL ideal sobre as views deve passar no eval."""
    sql = VIEW_SQL[qid].format(ano_referencia=db.reference_year)
    model, _ = scripted(sql, "FINAL: resposta")
    questions = load_questions(Path("evals/questions.yaml"), [qid])
    [result] = evaluate(CineAgent(db, model), db, questions, use_cache=False)
    assert result.passed, result.reason