"""Configuração global (instalação com `uv tool`) e prioridade entre arquivos .env."""

import os

import pytest
from typer.testing import CliRunner

from cineanalytics import cli
from cineanalytics.config import load_settings, user_config_dir, user_env_file
from cineanalytics.evaluation import default_questions_file

runner = CliRunner()


@pytest.fixture()
def dirs(monkeypatch, tmp_path):
    """Pasta de configuração global e pasta de trabalho separadas, sem variáveis herdadas."""
    for var in ("OPENROUTER_API_KEY", "CINEANALYTICS_MODELS", "CINEANALYTICS_DB_PATH"):
        monkeypatch.delenv(var, raising=False)
    global_dir, work = tmp_path / "global", tmp_path / "trabalho"
    global_dir.mkdir()
    work.mkdir()
    monkeypatch.setenv("CINEANALYTICS_CONFIG_DIR", str(global_dir))
    monkeypatch.chdir(work)
    return global_dir, work


def test_pasta_global_por_sistema(monkeypatch, tmp_path):
    monkeypatch.delenv("CINEANALYTICS_CONFIG_DIR")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    if os.name == "nt":
        monkeypatch.setenv("APPDATA", str(tmp_path))
    assert user_config_dir() == tmp_path / "cineanalytics"
    assert user_env_file() == tmp_path / "cineanalytics" / ".env"


def test_variavel_troca_a_pasta_global(monkeypatch, tmp_path):
    monkeypatch.setenv("CINEANALYTICS_CONFIG_DIR", str(tmp_path / "x"))
    assert user_config_dir() == tmp_path / "x"


def test_le_o_env_global_em_qualquer_pasta(dirs):
    global_dir, _ = dirs
    (global_dir / ".env").write_text(
        "OPENROUTER_API_KEY=sk-global\nCINEANALYTICS_MODELS=a/x:free\nCINEANALYTICS_DB_PATH=/dados/cinerocket.db\n"
    )
    s = load_settings()
    assert s.require_llm() == ("sk-global", ["a/x:free"])
    assert str(s.db_path) == "/dados/cinerocket.db"


def test_env_local_tem_prioridade_sobre_o_global(dirs):
    global_dir, work = dirs
    (global_dir / ".env").write_text("OPENROUTER_API_KEY=sk-global\nCINEANALYTICS_MODELS=a/x:free\n")
    (work / ".env").write_text("CINEANALYTICS_MODELS=b/y:free\n")
    s = load_settings()
    assert s.models == ["b/y:free"]                                   # do local
    assert s.openrouter_api_key.get_secret_value() == "sk-global"    # herdado do global


def test_variavel_de_ambiente_tem_prioridade_sobre_arquivos(dirs, monkeypatch):
    global_dir, work = dirs
    (global_dir / ".env").write_text("CINEANALYTICS_MODELS=a/x:free\n")
    (work / ".env").write_text("CINEANALYTICS_MODELS=b/y:free\n")
    monkeypatch.setenv("CINEANALYTICS_MODELS", "c/z:free")
    assert load_settings().models == ["c/z:free"]


def test_valor_vazio_conta_como_ausente(dirs):
    _, work = dirs
    (work / ".env").write_text("OPENROUTER_API_KEY=\nCINEANALYTICS_MODELS=\n")
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY, CINEANALYTICS_MODELS"):
        load_settings().require_llm()


def test_mensagem_de_configuracao_ausente_indica_o_env_global(dirs):
    global_dir, _ = dirs
    with pytest.raises(RuntimeError, match="cineanalytics config") as err:
        load_settings().require_llm()
    assert str(global_dir) in str(err.value)


def test_perguntas_do_eval_encontradas_fora_do_repositorio(dirs):
    path = default_questions_file()
    assert path is not None and path.is_file()


def test_comando_config_mostra_origem_e_mascara_a_chave(dirs, db_path):
    global_dir, _ = dirs
    (global_dir / ".env").write_text(
        f"OPENROUTER_API_KEY=sk-or-v1-abcdefghijklmnop1234\nCINEANALYTICS_MODELS=a/x:free\n"
        f"CINEANALYTICS_DB_PATH={db_path}\n"
    )
    result = runner.invoke(cli.app, ["config"])
    assert result.exit_code == 0, result.output
    assert "sk-or-v1…1234" in result.output
    assert "abcdefghijklmnop" not in result.output
    assert "a/x:free" in result.output
    assert "(encontrado)" in result.output


def test_comando_config_caminho(dirs):
    global_dir, _ = dirs
    result = runner.invoke(cli.app, ["config", "--caminho"])
    assert result.output.strip() == str(global_dir / ".env")


def test_schema_funciona_so_com_o_env_global(dirs, db_path):
    global_dir, _ = dirs
    (global_dir / ".env").write_text(f"CINEANALYTICS_DB_PATH={db_path}\n")
    result = runner.invoke(cli.app, ["schema"])
    assert result.exit_code == 0 and "vw_filmes" in result.output


def test_banco_nao_encontrado_aponta_o_env_global(dirs):
    result = runner.invoke(cli.app, ["schema"])
    assert result.exit_code == 1
    assert "CINEANALYTICS_DB_PATH" in result.output