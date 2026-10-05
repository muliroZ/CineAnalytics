"""Relatório HTML autocontido das perguntas feitas ao agente.

Sem CDN e sem fontes externas: o arquivo abre offline em qualquer navegador e
pode ser salvo como PDF pela impressão do próprio navegador. Os gráficos são
SVG gerados aqui mesmo.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader
from markdown_it import MarkdownIt
from markupsafe import Markup

from .evaluation import category_label
from .models import AgentRun, QueryLog
from .render import _br, format_value, pretty_sql

TABLE_ROWS = 20
MAX_BARS = 15

# html=False: a resposta vem de um LLM, então HTML embutido é exibido como texto.
_markdown = MarkdownIt("commonmark", {"html": False}).enable("table")
_env = Environment(loader=PackageLoader("cineanalytics", "templates"), autoescape=True)


# ---------------------------------------------------------------------- gráfico
def _is_numeric(rows: Sequence[Sequence[Any]], i: int) -> bool:
    values = [r[i] for r in rows if r[i] is not None]
    return bool(values) and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values)


def _is_year(column: str) -> bool:
    return "ano" in column.lower().split("_")


def compact_value(column: str, value: float) -> str:
    """Formato curto para rótulos de gráfico: R$ 11,7 bi, 812,3 mi, 45,2 mil."""
    name = column.lower()
    if name.endswith("_pct") or "ano" in name.split("_"):
        return format_value(column, value)
    magnitude = abs(value)
    for limit, suffix in ((1e9, " bi"), (1e6, " mi"), (1e3, " mil")):
        if magnitude >= limit:
            number = f"{_br(magnitude / limit, 1)}{suffix}"
            break
    else:
        return format_value(column, value)
    prefix = "R$ " if name.endswith("_brl") else "US$ " if name.endswith("_usd") else ""
    return f"{'−' if value < 0 else ''}{prefix}{number}"


def pick_chart_columns(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> tuple[int, int] | None:
    """Escolhe (rótulo, valor): a 1ª coluna de texto (ou de ano) e a 1ª numérica."""
    if len(rows) < 2 or len(columns) < 2:
        return None
    label = next((i for i in range(len(columns)) if not _is_numeric(rows, i)), None)
    if label is None:
        label = next((i for i, c in enumerate(columns) if _is_year(c)), None)
    if label is None:
        return None
    value = next(
        (i for i, c in enumerate(columns) if i != label and _is_numeric(rows, i) and not _is_year(c)),
        None,
    )
    return None if value is None else (label, value)


def chart_svg(columns: Sequence[str], rows: Sequence[Sequence[Any]], *, max_bars: int = MAX_BARS) -> str | None:
    """Gráfico de barras horizontais em SVG, ou None se os dados não forem plotáveis."""
    picked = pick_chart_columns(columns, rows)
    if picked is None:
        return None
    label_i, value_i = picked
    data = [(r[label_i], float(r[value_i])) for r in rows if r[value_i] is not None][:max_bars]
    if len(data) < 2:
        return None

    lo, hi = min(0.0, *(v for _, v in data)), max(0.0, *(v for _, v in data))
    span = (hi - lo) or 1.0
    width, label_w, value_w, row_h, bar_h = 680, 200, 130, 30, 18
    bar_area = width - label_w - value_w
    height = row_h * len(data) + 6
    x_of = lambda v: label_w + (v - lo) / span * bar_area  # noqa: E731

    parts = []
    for n, (label, value) in enumerate(data):
        y = n * row_h + 6
        x0, x1 = sorted((x_of(0.0), x_of(value)))
        text = format_value(columns[label_i], label)
        short = text if len(text) <= 28 else text[:27] + "…"
        parts.append(
            f'<text class="lbl" x="{label_w - 10}" y="{y + bar_h - 4}" text-anchor="end">'
            f"<title>{escape(text)}</title>{escape(short)}</text>"
            f'<rect class="bar{" neg" if value < 0 else ""}" x="{x0:.1f}" y="{y}" '
            f'width="{max(x1 - x0, 1):.1f}" height="{bar_h}" rx="2"/>'
            f'<text class="val" x="{label_w + bar_area + 8}" y="{y + bar_h - 4}">'
            f"{escape(compact_value(columns[value_i], value))}</text>"
        )
    if lo < 0:
        zx = x_of(0.0)
        parts.append(f'<line class="zero" x1="{zx:.1f}" x2="{zx:.1f}" y1="0" y2="{height}"/>')

    title = f"{columns[value_i]} por {columns[label_i]}"
    return (
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{escape(title)}" preserveAspectRatio="xMinYMin meet">{"".join(parts)}</svg>'
    )


# ------------------------------------------------------------------------ dados
@dataclass
class Entry:
    number: int
    run: AgentRun
    answer_html: Markup | None
    sql: str | None
    failed: list[QueryLog]
    columns: list[str]
    rows: list[list[str]]
    numeric_cols: set[int]
    hidden_rows: int
    chart: Markup | None


def _entry(number: int, run: AgentRun) -> Entry:
    final = run.consulta_final
    columns, rows, numeric, hidden, chart, sql = [], [], set(), 0, None, None
    if final is not None:
        sql = pretty_sql(final.sql)
        columns = final.columns
        rows = [[format_value(c, v) for c, v in zip(columns, r)] for r in final.rows[:TABLE_ROWS]]
        numeric = {i for i in range(len(columns)) if _is_numeric(final.rows, i)}
        hidden = max(len(final.rows) - TABLE_ROWS, 0)
        svg = chart_svg(final.columns, final.rows)
        chart = Markup(svg) if svg else None
    return Entry(
        number=number,
        run=run,
        answer_html=Markup(_markdown.render(run.resposta)) if run.resposta else None,
        sql=sql,
        failed=[q for q in run.consultas if not q.ok],
        columns=columns,
        rows=rows,
        numeric_cols=numeric,
        hidden_rows=hidden,
        chart=chart,
    )


def _stats(runs: Sequence[AgentRun]) -> dict[str, Any]:
    answered = [r for r in runs if r.ok]
    live = [r for r in answered if not r.cache_hit]
    return {
        "perguntas": len(runs),
        "respondidas": len(answered),
        "falhas": len(runs) - len(answered),
        "cache": sum(r.cache_hit for r in runs),
        "requisicoes": sum(r.requisicoes for r in runs),
        "tokens": sum(r.tokens_entrada + r.tokens_saida for r in runs),
        "tempo_medio": (sum(r.duracao_s for r in live) / len(live)) if live else None,
        "modelos": Counter(r.modelo for r in runs if r.modelo and not r.cache_hit).most_common(),
    }


def _evaluation(items: list[dict[str, Any]], source: Path) -> dict[str, Any]:
    by_cat: dict[str, list[bool]] = defaultdict(list)
    for item in items:
        by_cat[item["categoria"]].append(item["passou"])
    categories = [
        {"nome": category_label(cat), "acertos": sum(f), "total": len(f), "pct": 100 * sum(f) / len(f)}
        for cat, f in by_cat.items()
    ]
    svg = chart_svg(["categoria", "acerto_pct"], [[c["nome"], c["pct"]] for c in categories])
    passed = sum(i["passou"] for i in items)
    return {
        "arquivo": source.name,
        "total": len(items),
        "acertos": passed,
        "pct": 100 * passed / max(len(items), 1),
        "categorias": categories,
        "grafico": Markup(svg) if svg else None,
        "itens": [
            {
                "id": i["id"],
                "pergunta": i["run"]["pergunta"],
                "passou": i["passou"],
                "motivo": i["motivo"],
                "requisicoes": "cache" if i["run"].get("cache_hit") else i["run"].get("requisicoes", 0),
            }
            for i in items
        ],
    }


# ------------------------------------------------------------------- interface
def latest_eval(evals_dir: Path) -> Path | None:
    files = sorted(Path(evals_dir).glob("eval-*.json")) if Path(evals_dir).is_dir() else []
    return files[-1] if files else None


def build_report(
    runs: Sequence[AgentRun],
    *,
    eval_file: Path | None = None,
    generated_at: datetime | None = None,
) -> str:
    evaluation = None
    if eval_file is not None:
        evaluation = _evaluation(json.loads(Path(eval_file).read_text(encoding="utf-8")), Path(eval_file))
    dates = [r.criado_em for r in runs]
    return _env.get_template("report.html.j2").render(
        gerado_em=generated_at or datetime.now(),
        inicio=min(dates) if dates else None,
        fim=max(dates) if dates else None,
        stats=_stats(runs),
        entries=[_entry(n, r) for n, r in enumerate(runs, start=1)],
        evaluation=evaluation,
        fmt_int=lambda v: format_value("n", int(v)),
    )