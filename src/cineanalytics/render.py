"""Renderização no terminal com Rich. Nenhuma função aqui chama o LLM."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

import sqlglot
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from .db import Database
from .evaluation import EvalResult, category_label
from .models import AgentRun, QueryLog


# ------------------------------------------------------------------ formatação
def _br(value: float, decimals: int) -> str:
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "§").replace(".", ",").replace("§", ".")


def format_value(column: str, value: Any) -> str:
    """Formata um valor no padrão brasileiro, guiado pelo nome da coluna."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "sim" if value else "não"
    name = column.lower()
    if isinstance(value, (int, float)):
        if "ano" in name.split("_"):
            return str(int(value))
        if name.endswith("_brl"):
            return f"R$ {_br(value, 2)}"
        if name.endswith("_usd"):
            return f"US$ {_br(value, 2)}"
        if name.endswith("_pct"):
            return f"{_br(value, 2)}%"
        if isinstance(value, int) or float(value).is_integer():
            return _br(value, 0)
        return _br(value, 2)
    return str(value)


def _is_numeric_column(rows: Sequence[Sequence[Any]], idx: int) -> bool:
    values = [r[idx] for r in rows if r[idx] is not None]
    return bool(values) and all(isinstance(v, (int, float)) for v in values)


def result_table(query: QueryLog, max_rows: int = 10) -> Table:
    table = Table(show_lines=False, header_style="bold", expand=False)
    for i, col in enumerate(query.columns):
        table.add_column(col, justify="right" if _is_numeric_column(query.rows, i) else "left", overflow="fold")
    for row in query.rows[:max_rows]:
        table.add_row(*(format_value(c, v) for c, v in zip(query.columns, row)))
    hidden = len(query.rows) - max_rows
    if hidden > 0 or query.truncated:
        extra = f"+{hidden} linhas" if hidden > 0 else ""
        more = " (resultado truncado no banco)" if query.truncated else ""
        table.caption = f"{extra}{more}".strip()
    return table


def pretty_sql(sql: str) -> str:
    """Indenta o SQL só para exibição; se o sqlglot não entender, mostra como veio."""
    try:
        return sqlglot.transpile(sql, read="sqlite", write="sqlite", pretty=True)[0]
    except Exception:
        return sql


# --------------------------------------------------------------------- resposta
def run_footer(run: AgentRun) -> Text:
    if run.cache_hit:
        return Text(f"⚡ do cache · {run.modelo or 'modelo desconhecido'} · 0 requisições", style="dim")
    parts = [
        run.modelo or "modelo desconhecido",
        f"{run.requisicoes} requisiç{'ão' if run.requisicoes == 1 else 'ões'}",
        f"{_br(run.tokens_entrada + run.tokens_saida, 0)} tokens",
        f"{_br(run.duracao_s, 1)} s",
    ]
    return Text(" · ".join(parts), style="dim")


def render_run(console: Console, run: AgentRun, *, show_sql: bool = True, show_data: bool = False,
               max_rows: int = 10) -> None:
    if run.ok:
        console.print(Panel(Markdown(run.resposta or ""), title="Resposta", title_align="left",
                            border_style="cyan", padding=(1, 2)))
    else:
        console.print(Panel(run.erro or "Erro desconhecido.", title="Não foi possível responder",
                            title_align="left", border_style="red"))

    if show_sql and run.consultas:
        console.print(sql_panel(run))
    final = run.consulta_final
    if show_data and final is not None and final.columns:
        console.print(result_table(final, max_rows=max_rows))
    console.print(run_footer(run))


def sql_panel(run: AgentRun) -> Panel:
    items: list[Any] = []
    failed = [q for q in run.consultas if not q.ok]
    for q in failed:
        items.append(Text(f"✗ tentativa corrigida: {q.error}", style="yellow"))
    final = run.consulta_final
    if final is not None:
        items.append(Syntax(pretty_sql(final.sql), "sql", theme="ansi_dark", word_wrap=True, background_color="default"))
        rows = f"{len(final.rows)}{'+' if final.truncated else ''} linhas"
        items.append(Text(f"{rows} · {_br(final.elapsed_ms, 0)} ms", style="dim"))
    title = "SQL executado" + (f" ({len(run.consultas)} consultas)" if len(run.consultas) > 1 else "")
    return Panel(Group(*items), title=title, title_align="left", border_style="bright_black")


# ----------------------------------------------------------------------- schema
def render_schema(console: Console, db: Database) -> None:
    for view in db.views:
        table = Table(title=f"[bold]{view.name}[/]", caption=view.description, caption_justify="left",
                      title_justify="left", header_style="bold", expand=True)
        table.add_column("coluna", style="cyan", no_wrap=True)
        table.add_column("tipo", style="magenta", no_wrap=True)
        table.add_column("descrição")
        for col in view.columns:
            table.add_row(col.name, col.type, col.description)
        console.print(table)
        console.print()
    console.print(f"[bold]Gêneros:[/] {', '.join(db.genres)}")
    console.print(f"[bold]Ano de referência (último com filmes lançados):[/] {db.reference_year}")


# ------------------------------------------------------------------- avaliação
def eval_table(results: Sequence[EvalResult]) -> Table:
    table = Table(header_style="bold", expand=True)
    table.add_column("id", no_wrap=True)
    table.add_column("pergunta", ratio=3)
    table.add_column("", justify="center", no_wrap=True)
    table.add_column("detalhe", ratio=2, style="dim")
    table.add_column("req.", justify="right", no_wrap=True)
    for r in results:
        mark = "[green]✓[/]" if r.passed else "[red]✗[/]"
        req = "cache" if r.run.cache_hit else str(r.run.requisicoes)
        table.add_row(r.question.id, r.question.question, mark, "" if r.passed else r.reason, req)
    return table


def eval_summary(results: Sequence[EvalResult]) -> Table:
    by_cat: dict[str, list[bool]] = defaultdict(list)
    for r in results:
        by_cat[r.question.category].append(r.passed)
    table = Table(title="Acurácia", title_justify="left", header_style="bold")
    table.add_column("categoria")
    table.add_column("acertos", justify="right")
    table.add_column("%", justify="right")
    for cat, flags in by_cat.items():
        table.add_row(category_label(cat), f"{sum(flags)}/{len(flags)}", f"{100 * sum(flags) / len(flags):.0f}%")
    total = [r.passed for r in results]
    table.add_section()
    table.add_row("[bold]total[/]", f"[bold]{sum(total)}/{len(total)}[/]",
                  f"[bold]{100 * sum(total) / max(len(total), 1):.0f}%[/]")
    requests = sum(r.run.requisicoes for r in results)
    table.caption = f"{requests} requisições ao LLM nesta execução"
    return table