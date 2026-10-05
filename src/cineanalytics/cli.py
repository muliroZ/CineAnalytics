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
from rich.table import Table

from . import render
from .agent import CineAgent, build_instructions, build_model
from .config import LOCAL_ENV_FILE, Settings, load_settings, user_env_file
from .db import Database
from .evaluation import default_questions_file, evaluate, load_questions
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


# --------------------------------------------------------------------- helpers
def _fail(message: str) -> NoReturn:
    console.print(Panel(message, title="Erro", title_align="left", border_style="red"))
    raise typer.Exit(1)


def _open_db(settings: Settings) -> Database:
    try:
        return Database(settings.db_path, max_rows=settings.max_rows, timeout_s=settings.query_timeout_s)
    except FileNotFoundError as e:
        _fail(
            f"{e}\n\nO caminho vem de CINEANALYTICS_DB_PATH. Ajuste-o no .env global "
            f"({user_env_file()}) ou rode `cineanalytics config` para ver a configuração atual."
        )


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
    settings = load_settings()
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
    settings = load_settings()
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
    settings = load_settings()
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
    arquivo: Annotated[
        Path | None,
        typer.Option(help="Arquivo YAML com as perguntas. Padrão: evals/questions.yaml (ou a cópia instalada)."),
    ] = None,
    sim: Annotated[bool, typer.Option("--sim", "-y", help="Não pede confirmação.")] = False,
    sem_cache: Annotated[bool, typer.Option("--sem-cache", help="Força novas chamadas ao LLM.")] = False,
) -> None:
    """Avalia o agente contra as perguntas de referência."""
    settings = load_settings()
    arquivo = arquivo or default_questions_file()
    if arquivo is None:
        _fail("Arquivo de perguntas não encontrado. Informe um com --arquivo.")
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
    settings = load_settings()
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


def _mask(secret: str) -> str:
    return secret[:8] + "…" + secret[-4:] if len(secret) > 16 else "…" * 3


def _path_status(path: Path, *, must_exist: bool = True) -> str:
    resolved = path.expanduser().resolve()
    if path.exists():
        return f"{resolved} [green](encontrado)[/]"
    return f"{resolved} [{'red' if must_exist else 'dim'}](não existe{'' if must_exist else ' ainda'})[/]"


@app.command()
def config(
    caminho: Annotated[
        bool, typer.Option("--caminho", help="Só imprime o caminho do .env global (útil em scripts).")
    ] = False,
) -> None:
    """Mostra a configuração em uso e de onde ela vem (não usa o LLM)."""
    global_env = user_env_file()
    if caminho:
        print(global_env)
        return

    settings = load_settings()
    files = Table(title="Arquivos de configuração", title_justify="left", show_header=False, box=None)
    files.add_column(style="bold")
    files.add_column()
    files.add_row("Global", _path_status(global_env))
    files.add_row("Local (pasta atual)", _path_status(LOCAL_ENV_FILE, must_exist=False))
    console.print(files)
    console.print("[dim]Variáveis de ambiente têm prioridade sobre o .env local, que tem prioridade sobre o global.[/]\n")

    key = settings.openrouter_api_key.get_secret_value() if settings.openrouter_api_key else None
    values = Table(title="Valores em uso", title_justify="left", show_header=False, box=None)
    values.add_column(style="bold")
    values.add_column()
    values.add_row("Chave do OpenRouter", _mask(key) if key else "[red]não definida[/]")
    values.add_row("Modelos", ", ".join(settings.models) if settings.models else "[red]não definidos[/]")
    values.add_row("Banco", _path_status(settings.db_path))
    values.add_row("Estado (cache e histórico)", _path_status(settings.state_dir, must_exist=False))
    values.add_row("Relatórios", _path_status(settings.reports_dir, must_exist=False))
    values.add_row("Cache", "ligado" if settings.cache_enabled else "desligado")
    values.add_row("Limites", f"{settings.request_limit} requisições por pergunta, "
                   f"{settings.max_rows} linhas, {settings.query_timeout_s:g} s por consulta")
    values.add_row("Memória do chat", f"{settings.history_turns} perguntas")
    questions = default_questions_file()
    values.add_row("Perguntas do eval", str(questions.resolve()) if questions else "[red]não encontrado[/]")
    console.print(values)


@cache_app.command("info")
def cache_info() -> None:
    """Mostra quantas respostas estão em cache."""
    cache = ResponseCache(load_settings().cache_dir)
    files = cache.entries()
    size_kb = sum(f.stat().st_size for f in files) / 1024
    console.print(f"{len(files)} respostas em cache ({size_kb:.0f} KB) em {cache.directory}")


@cache_app.command("clear")
def cache_clear() -> None:
    """Apaga todas as respostas em cache."""
    removed = ResponseCache(load_settings().cache_dir).clear()
    console.print(f"{removed} respostas removidas do cache.")


if __name__ == "__main__":
    app()