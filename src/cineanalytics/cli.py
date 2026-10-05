"""Interface de linha de comando da CineAnalytics.

    cineanalytics ask "Quais os 5 filmes mais populares?"
    cineanalytics chat
    cineanalytics schema
    cineanalytics eval --id fin_01 --id pop_01
    cineanalytics report --abrir
    cineanalytics cache info | cache clear
"""

from __future__ import annotations

import json
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from . import render
from .agent import CineAgent, build_instructions, build_model
from .config import Settings
from .db import Database
from .evaluation import evaluate, load_questions
from .report import build_report, latest_eval
from .storage import ResponseCache, RunLog

app = typer.Typer(
    name="cineanalytics",
    help="Pergunte sobre o catálogo de filmes da CineAnalytics em linguagem natural.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)
cache_app = typer.Typer(help="Gerencia o cache de respostas.", no_args_is_help=True)
app.add_typer(cache_app, name="cache")

console = Console()
DEFAULT_EVAL_FILE = Path("evals/questions.yaml")


# --------------------------------------------------------------------- helpers
def _fail(message: str) -> NoReturn:
    console.print(Panel(message, title="Erro", title_align="left", border_style="red"))
    raise typer.Exit(1)


def _open_db(settings: Settings) -> Database:
    try:
        return Database(settings.db_path, max_rows=settings.max_rows, timeout_s=settings.query_timeout_s)
    except FileNotFoundError as e:
        _fail(str(e))


def _make_agent(settings: Settings, db: Database, *, use_cache: bool = True) -> CineAgent:
    try:
        api_key, models = settings.require_llm()
    except RuntimeError as e:
        _fail(str(e))
    cache = ResponseCache(settings.cache_dir) if settings.cache_enabled and use_cache else None
    return CineAgent(
        db,
        build_model(models, api_key),
        request_limit=settings.request_limit,
        history_turns=settings.history_turns,
        cache=cache,
    )


def _ask_with_spinner(agent: CineAgent, question: str, **kwargs):
    with console.status("[cyan]Consultando o catálogo…", spinner="dots"):
        return agent.ask(question, **kwargs)


# -------------------------------------------------------------------- comandos
@app.command()
def ask(
    pergunta: Annotated[str, typer.Argument(help="Pergunta em linguagem natural.")],
    sql: Annotated[bool, typer.Option("--sql/--sem-sql", help="Mostra o SQL executado.")] = True,
    dados: Annotated[bool, typer.Option("--dados", "-d", help="Mostra a tabela com o resultado bruto.")] = False,
    linhas: Annotated[int, typer.Option(help="Linhas exibidas na tabela de dados.")] = 10,
    sem_cache: Annotated[bool, typer.Option("--sem-cache", help="Ignora respostas em cache.")] = False,
) -> None:
    """Faz uma pergunta e mostra a resposta."""
    settings = Settings()
    with _open_db(settings) as db:
        agent = _make_agent(settings, db, use_cache=not sem_cache)
        run = _ask_with_spinner(agent, pergunta, remember=False)
        RunLog(settings.runs_path).append(run)
        render.render_run(console, run, show_sql=sql, show_data=dados, max_rows=linhas)
    if not run.ok:
        raise typer.Exit(1)


CHAT_HELP = """\
[bold]/sql[/]     mostra/oculta o SQL executado
[bold]/dados[/]   mostra/oculta a tabela com o resultado bruto
[bold]/limpar[/]  apaga a memória da conversa
[bold]/ajuda[/]   mostra esta ajuda
[bold]/sair[/]    encerra (Ctrl+C também funciona)"""


@app.command()
def chat(
    sem_cache: Annotated[bool, typer.Option("--sem-cache", help="Ignora respostas em cache.")] = False,
) -> None:
    """Conversa interativa com memória das perguntas anteriores."""
    settings = Settings()
    show_sql, show_data = True, False
    with _open_db(settings) as db:
        agent = _make_agent(settings, db, use_cache=not sem_cache)
        log = RunLog(settings.runs_path)
        console.print(Panel(
            "Pergunte sobre filmes, bilheteria, notas, elenco, gêneros e produtoras.\n"
            f"Ex.: [italic]Quais os 10 filmes com maior receita?[/]\n\n{CHAT_HELP}",
            title="CineAnalytics · chat", title_align="left", border_style="cyan",
        ))
        while True:
            try:
                question = Prompt.ask("\n[bold cyan]você[/]").strip()
            except (KeyboardInterrupt, EOFError):
                break
            if not question:
                continue
            command = question.lower()
            if command in ("/sair", "/exit", "/quit"):
                break
            if command == "/ajuda":
                console.print(CHAT_HELP)
                continue
            if command == "/limpar":
                agent.reset()
                console.print("[dim]Memória da conversa apagada.[/]")
                continue
            if command == "/sql":
                show_sql = not show_sql
                console.print(f"[dim]SQL {'visível' if show_sql else 'oculto'}.[/]")
                continue
            if command == "/dados":
                show_data = not show_data
                console.print(f"[dim]Tabela de dados {'visível' if show_data else 'oculta'}.[/]")
                continue
            if command.startswith("/"):
                console.print("[yellow]Comando desconhecido.[/] Digite /ajuda.")
                continue

            run = _ask_with_spinner(agent, question)
            log.append(run)
            render.render_run(console, run, show_sql=show_sql, show_data=show_data)
    console.print("[dim]Até logo![/]")


@app.command()
def schema(
    prompt: Annotated[bool, typer.Option("--prompt", help="Mostra o prompt completo enviado ao modelo.")] = False,
) -> None:
    """Mostra as views disponíveis para o agente (não usa o LLM)."""
    settings = Settings()
    with _open_db(settings) as db:
        if prompt:
            text = build_instructions(db)
            console.print(text, markup=False, highlight=False)
            console.print(f"\n[dim]{len(text)} caracteres ≈ {len(text) // 4} tokens[/]")
        else:
            render.render_schema(console, db)


@app.command("eval")
def eval_(
    ids: Annotated[list[str] | None, typer.Option("--id", help="Roda só estes IDs (repita a opção).")] = None,
    arquivo: Annotated[Path, typer.Option(help="Arquivo YAML com as perguntas.")] = DEFAULT_EVAL_FILE,
    sim: Annotated[bool, typer.Option("--sim", "-y", help="Não pede confirmação.")] = False,
    sem_cache: Annotated[bool, typer.Option("--sem-cache", help="Força novas chamadas ao LLM.")] = False,
) -> None:
    """Avalia o agente contra as perguntas de referência."""
    settings = Settings()
    try:
        questions = load_questions(arquivo, ids)
    except (OSError, ValueError) as e:
        _fail(f"Não foi possível carregar o eval: {e}")

    with _open_db(settings) as db:
        agent = _make_agent(settings, db, use_cache=not sem_cache)
        if agent.cache is not None:
            pending = [
                q for q in questions
                if agent.cache.get(agent.cache.key(q.question, model=agent.model_name, prompt=agent.instructions)) is None
            ]
        else:
            pending = list(questions)
        if pending and not sim:
            worst = len(pending) * settings.request_limit
            console.print(
                f"{len(questions)} perguntas, {len(pending)} sem cache. Estimativa: "
                f"~{len(pending) * 2}–{worst} requisições ao LLM (a conta gratuita tem 50/dia)."
            )
            if not Confirm.ask("Continuar?", default=False):
                raise typer.Exit(0)

        def progress(result) -> None:
            mark = "[green]✓[/]" if result.passed else "[red]✗[/]"
            console.print(f"{mark} {result.question.id} [dim]{result.question.question}[/]")

        with console.status("[cyan]Avaliando…", spinner="dots"):
            results = evaluate(agent, db, questions, use_cache=not sem_cache, on_result=progress)

    console.print()
    console.print(render.eval_table(results))
    console.print(render.eval_summary(results))

    settings.evals_dir.mkdir(parents=True, exist_ok=True)
    out = settings.evals_dir / f"eval-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps([
        {
            "id": r.question.id,
            "categoria": r.question.category,
            "passou": r.passed,
            "motivo": r.reason,
            "run": r.run.model_dump(mode="json"),
        }
        for r in results
    ], ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"[dim]Resultado salvo em {out}[/]")


@app.command()
def report(
    ultimas: Annotated[int | None, typer.Option(help="Inclui só as N perguntas mais recentes.")] = None,
    desde: Annotated[
        datetime | None, typer.Option(formats=["%Y-%m-%d"], help="Inclui só perguntas a partir desta data (AAAA-MM-DD).")
    ] = None,
    avaliacao: Annotated[
        bool, typer.Option("--avaliacao/--sem-avaliacao", help="Inclui o resultado do último eval.")
    ] = True,
    saida: Annotated[Path | None, typer.Option(help="Arquivo HTML de saída.")] = None,
    abrir: Annotated[bool, typer.Option("--abrir", help="Abre o relatório no navegador.")] = False,
) -> None:
    """Gera um relatório HTML com as perguntas feitas e o último eval (não usa o LLM)."""
    settings = Settings()
    runs = RunLog(settings.runs_path).load()
    if desde is not None:
        runs = [r for r in runs if r.criado_em >= desde]
    if ultimas is not None:
        runs = runs[-ultimas:]
    eval_file = latest_eval(settings.evals_dir) if avaliacao else None

    if not runs and eval_file is None:
        _fail(
            "Ainda não há perguntas registradas nem resultados de avaliação.\n"
            'Faça uma pergunta com: cineanalytics ask "Quais os 5 filmes mais populares?"'
        )

    out = saida or settings.reports_dir / f"relatorio-{datetime.now():%Y%m%d-%H%M%S}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_report(runs, eval_file=eval_file), encoding="utf-8")

    detalhe = f"{len(runs)} perguntas" + (f" e o eval {eval_file.name}" if eval_file else "")
    console.print(f"Relatório gerado com {detalhe}: [bold]{out}[/]")
    if abrir:
        webbrowser.open(out.resolve().as_uri())


@cache_app.command("info")
def cache_info() -> None:
    """Mostra quantas respostas estão em cache."""
    cache = ResponseCache(Settings().cache_dir)
    files = cache.entries()
    size_kb = sum(f.stat().st_size for f in files) / 1024
    console.print(f"{len(files)} respostas em cache ({size_kb:.0f} KB) em {cache.directory}")


@cache_app.command("clear")
def cache_clear() -> None:
    """Apaga todas as respostas em cache."""
    removed = ResponseCache(Settings().cache_dir).clear()
    console.print(f"{removed} respostas removidas do cache.")


if __name__ == "__main__":
    app()