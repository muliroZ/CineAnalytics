import pytest
from helpers import scripted
from typer.testing import CliRunner

from cineanalytics import cli

runner = CliRunner()
SQL = "SELECT titulo, receita_brl FROM vw_filmes WHERE receita_brl IS NOT NULL ORDER BY receita_brl DESC LIMIT 3"


@pytest.fixture()
def env(monkeypatch, tmp_path, db_path):
    monkeypatch.chdir(tmp_path)  # .cineanalytics/ e .env relativos ficam no tmp
    monkeypatch.setenv("CINEANALYTICS_DB_PATH", str(db_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-teste")
    monkeypatch.setenv("CINEANALYTICS_MODELS", "teste/modelo:free")
    model, calls = scripted(SQL, "FINAL: **Delta** lidera com R$ 5 milhões.")
    monkeypatch.setattr(cli, "build_model", lambda models, key: model)
    return calls


def test_schema_nao_precisa_de_llm(env, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    result = runner.invoke(cli.app, ["schema"])
    assert result.exit_code == 0
    assert "vw_filmes" in result.output and "Drama" in result.output


def test_schema_prompt_mostra_estimativa_de_tokens(env):
    result = runner.invoke(cli.app, ["schema", "--prompt"])
    assert result.exit_code == 0 and "tokens" in result.output


def test_ask_mostra_resposta_sql_e_dados(env, tmp_path):
    result = runner.invoke(cli.app, ["ask", "Top 3 receitas?", "--dados"])
    assert result.exit_code == 0, result.output
    assert "Delta" in result.output
    assert "SELECT" in result.output
    assert "R$ 5.000.000,00" in result.output  # tabela formatada no padrão brasileiro
    assert (tmp_path / ".cineanalytics" / "runs.jsonl").is_file()


def test_ask_repetido_vem_do_cache(env):
    runner.invoke(cli.app, ["ask", "Top 3 receitas?"])
    n = len(env)
    result = runner.invoke(cli.app, ["ask", "top 3 receitas"])
    assert "do cache" in result.output
    assert len(env) == n


def test_ask_sem_configuracao_explica_o_que_falta(env, monkeypatch):
    monkeypatch.delenv("CINEANALYTICS_MODELS")
    result = runner.invoke(cli.app, ["ask", "oi"])
    assert result.exit_code == 1
    assert "CINEANALYTICS_MODELS" in result.output


def test_banco_inexistente_gera_erro_amigavel(env, monkeypatch):
    monkeypatch.setenv("CINEANALYTICS_DB_PATH", "nao/existe.db")
    result = runner.invoke(cli.app, ["schema"])
    assert result.exit_code == 1 and "README" in result.output


def test_chat_comandos_e_pergunta(env):
    entrada = "/ajuda\n/sql\nTop 3 receitas?\n/limpar\n/xyz\n/sair\n"
    result = runner.invoke(cli.app, ["chat"], input=entrada)
    assert result.exit_code == 0, result.output
    assert "Delta" in result.output
    assert "SQL oculto" in result.output
    assert "Memória da conversa apagada" in result.output
    assert "Comando desconhecido" in result.output
    assert "Até logo" in result.output


def test_eval_roda_e_salva_resultado(env, tmp_path, monkeypatch):
    monkeypatch.chdir(cli.Path(__file__).parents[1])  # precisa achar evals/questions.yaml
    monkeypatch.setenv("CINEANALYTICS_STATE_DIR", str(tmp_path / "state"))
    result = runner.invoke(cli.app, ["eval", "--id", "fin_01", "--sim", "--sem-cache"])
    assert result.exit_code == 0, result.output
    assert "fin_01" in result.output and "Acurácia" in result.output
    assert list((tmp_path / "state" / "evals").glob("eval-*.json"))


def test_cache_info_e_clear(env):
    runner.invoke(cli.app, ["ask", "Top 3 receitas?"])
    assert "1 respostas em cache" in runner.invoke(cli.app, ["cache", "info"]).output
    assert "1 respostas removidas" in runner.invoke(cli.app, ["cache", "clear"]).output