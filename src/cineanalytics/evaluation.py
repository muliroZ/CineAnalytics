"""Avaliação do agente contra o conjunto evals/questions.yaml.

A comparação é feita sobre os DADOS, não sobre o SQL: o agente pode escrever a
consulta de outro jeito, nomear e ordenar as colunas como quiser, e ainda assim
passar, desde que os valores batam com os da consulta de referência.
"""

from __future__ import annotations

import itertools
import math
from importlib import resources
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from .agent import CineAgent
from .db import Database
from .models import AgentRun, QueryLog

Check = Literal["ordered", "set", "top1"]

CATEGORY_LABELS = {
    "bilheteria_financas": "Bilheteria e finanças",
    "popularidade_engajamento": "Popularidade e engajamento",
    "elenco_equipe": "Elenco e equipe",
    "generos_produtoras": "Gêneros e produtoras",
    "avaliacoes_usuarios": "Avaliações dos usuários",
}


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category.replace("_", " ").capitalize())
MIN_ORDERED_ROWS = 5


@dataclass(frozen=True)
class EvalQuestion:
    id: str
    category: str
    question: str
    sql: str
    check: Check
    compare_cols: tuple[int, ...]
    notes: str = ""


@dataclass
class EvalResult:
    question: EvalQuestion
    run: AgentRun
    passed: bool
    reason: str
    reference_rows: list[list[Any]] = field(default_factory=list)


def default_questions_file() -> Path | None:
    """Encontra o questions.yaml: na pasta atual, no pacote instalado ou no repositório."""
    candidates = [
        Path("evals/questions.yaml"),
        Path(str(resources.files("cineanalytics").joinpath("evals", "questions.yaml"))),
        Path(__file__).resolve().parents[2] / "evals" / "questions.yaml",
    ]
    return next((c for c in candidates if c.is_file()), None)


def load_questions(path: Path, ids: Sequence[str] | None = None) -> list[EvalQuestion]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    questions = [
        EvalQuestion(
            id=q["id"],
            category=q["category"],
            question=q["question"],
            sql=q["sql"],
            check=q["check"],
            compare_cols=tuple(q["compare_cols"]),
            notes=q.get("notes", ""),
        )
        for q in data["questions"]
    ]
    if ids:
        unknown = set(ids) - {q.id for q in questions}
        if unknown:
            raise ValueError(f"IDs inexistentes no eval: {', '.join(sorted(unknown))}")
        questions = [q for q in questions if q.id in set(ids)]
    return questions


# ------------------------------------------------------------------ comparação
def _norm(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return " ".join(value.casefold().split())
    return value


def values_equal(a: Any, b: Any) -> bool:
    a, b = _norm(a), _norm(b)
    if isinstance(a, float) and isinstance(b, float):
        # Tolera arredondamentos diferentes (ex.: 66.67 vs 66.6667 vs 66.7).
        return math.isclose(a, b, rel_tol=1e-3, abs_tol=0.051)
    return a == b


def _multiset_equal(a: Sequence[Any], b: Sequence[Any], eq: Callable[[Any, Any], bool]) -> bool:
    if len(a) != len(b):
        return False
    remaining = list(b)
    for item in a:
        idx = next((i for i, other in enumerate(remaining) if eq(item, other)), None)
        if idx is None:
            return False
        remaining.pop(idx)
    return True


def _column_matches(ref: list[Any], got: list[Any], check: Check) -> bool:
    if not ref or not got:
        return False
    if check == "top1":
        return values_equal(ref[0], got[0])
    if check == "ordered":
        n = min(len(ref), len(got))
        return all(values_equal(a, b) for a, b in zip(ref[:n], got[:n]))
    return _multiset_equal(ref, got, values_equal)


def compare(
    ref_rows: list[Sequence[Any]], got: QueryLog, check: Check, compare_cols: Sequence[int]
) -> tuple[bool, str]:
    """Compara o resultado do agente com a referência.

    Para cada coluna da referência, procura uma coluna do agente com os mesmos
    valores, independentemente de nome ou posição.
    """
    if not ref_rows:
        return False, "a consulta de referência não retornou linhas"
    if not got.rows:
        return False, "a consulta do agente não retornou linhas"
    if check == "ordered" and len(got.rows) < min(len(ref_rows), MIN_ORDERED_ROWS):
        return False, f"retornou só {len(got.rows)} linha(s)"

    got_cols = [list(col) for col in zip(*got.rows)]
    candidates: list[list[int]] = []
    for c in compare_cols:
        ref_col = [r[c] for r in ref_rows]
        matches = [k for k, col in enumerate(got_cols) if _column_matches(ref_col, col, check)]
        if not matches:
            sample = ref_rows[0][c]
            return False, f"nenhuma coluna do agente corresponde à esperada (1º valor: {sample!r})"
        candidates.append(matches)

    if check != "set" or len(compare_cols) == 1:
        return True, "ok"

    # Em 'set' com várias colunas, os valores também precisam estar na mesma LINHA.
    ref_tuples = [tuple(r[c] for c in compare_cols) for r in ref_rows]
    for mapping in itertools.islice(itertools.product(*candidates), 50):
        got_tuples = [tuple(row[k] for k in mapping) for row in got.rows]
        if _multiset_equal(ref_tuples, got_tuples, lambda a, b: all(map(values_equal, a, b))):
            return True, "ok"
    return False, "os valores existem, mas não estão associados corretamente nas linhas"


def judge(question: EvalQuestion, run: AgentRun, ref_rows: list[Sequence[Any]]) -> tuple[bool, str]:
    if not run.ok:
        return False, run.erro or "sem resposta"
    successful = [q for q in reversed(run.consultas) if q.ok]
    if not successful:
        return False, "o agente não executou nenhuma consulta válida"
    # O agente pode ter feito consultas auxiliares (ex.: contar a amostra) depois
    # da principal, então qualquer consulta bem-sucedida que bata conta como acerto.
    first_reason = None
    for query in successful:
        passed, reason = compare(ref_rows, query, question.check, question.compare_cols)
        if passed:
            return True, reason
        first_reason = first_reason or reason
    return False, first_reason or "sem correspondência"


def evaluate(
    agent: CineAgent,
    db: Database,
    questions: Sequence[EvalQuestion],
    *,
    use_cache: bool = True,
    on_result: Callable[[EvalResult], None] | None = None,
) -> list[EvalResult]:
    results = []
    for q in questions:
        agent.reset()
        run = agent.ask(q.question, remember=False, use_cache=use_cache)
        ref_rows = [list(r) for r in db.execute(q.sql, max_rows=1000).rows]
        passed, reason = judge(q, run, ref_rows)
        result = EvalResult(question=q, run=run, passed=passed, reason=reason, reference_rows=ref_rows)
        results.append(result)
        if on_result:
            on_result(result)
    return results