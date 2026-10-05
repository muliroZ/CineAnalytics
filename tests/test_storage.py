from helpers import scripted
from pydantic_ai.messages import ModelRequest, ModelResponse

from cineanalytics.agent import CineAgent
from cineanalytics.models import AgentRun
from cineanalytics.storage import ResponseCache, RunLog

SQL = "SELECT titulo FROM vw_filmes ORDER BY popularidade DESC LIMIT 2"


def test_normalizacao_da_pergunta():
    n = ResponseCache.normalize
    assert n("  Top 10   FILMES?? ") == n("top 10 filmes") == "top 10 filmes"
    assert n("Filmes de ação") != n("Filmes de acao")  # acentos mudam o sentido às vezes


def test_chave_muda_com_modelo_e_prompt(tmp_path):
    c = ResponseCache(tmp_path)
    base = c.key("pergunta", model="a", prompt="p1")
    assert base == c.key("Pergunta?", model="a", prompt="p1")
    assert base != c.key("pergunta", model="b", prompt="p1")
    assert base != c.key("pergunta", model="a", prompt="p2")


def test_so_respostas_bem_sucedidas_vao_para_o_cache(tmp_path):
    c = ResponseCache(tmp_path)
    c.set("k1", AgentRun(pergunta="x", erro="falhou"))
    c.set("k2", AgentRun(pergunta="x", resposta="ok"))
    assert c.get("k1") is None
    assert c.get("k2").resposta == "ok"
    assert c.clear() == 1


def test_arquivo_corrompido_e_ignorado(tmp_path):
    (tmp_path / "ruim.json").write_text("{nao é json")
    assert ResponseCache(tmp_path).get("ruim") is None


def test_segunda_pergunta_igual_nao_chama_o_modelo(db, tmp_path):
    model, calls = scripted(SQL, "FINAL: Alpha e Delta.")
    agent = CineAgent(db, model, cache=ResponseCache(tmp_path))

    first = agent.ask("Filmes mais populares?", remember=False)
    n_calls = len(calls)
    second = agent.ask("filmes mais populares", remember=False)

    assert not first.cache_hit and second.cache_hit
    assert len(calls) == n_calls
    assert second.resposta == first.resposta
    assert second.requisicoes == 0
    assert second.consulta_final.rows == first.consulta_final.rows


def test_resposta_do_cache_entra_na_memoria(db, tmp_path):
    model, _ = scripted("FINAL: resposta")
    cache = ResponseCache(tmp_path)
    CineAgent(db, model, cache=cache).ask("pergunta 1", remember=False)

    agent = CineAgent(db, model, cache=cache)
    assert agent.ask("pergunta 1").cache_hit
    assert isinstance(agent.history[0], ModelRequest) and isinstance(agent.history[1], ModelResponse)


def test_cache_nao_e_usado_quando_ha_contexto(db, tmp_path):
    model, calls = scripted("FINAL: resposta")
    cache = ResponseCache(tmp_path)
    CineAgent(db, model, cache=cache).ask("e no ano anterior?", remember=False)

    agent = CineAgent(db, model, cache=cache)
    agent.ask("filmes de 2024")              # cria contexto
    run = agent.ask("e no ano anterior?")    # depende do contexto: não pode vir do cache
    assert not run.cache_hit


def test_run_log_append_e_load(tmp_path):
    log = RunLog(tmp_path / "sub" / "runs.jsonl")
    log.append(AgentRun(pergunta="a", resposta="1"))
    log.append(AgentRun(pergunta="b", erro="x"))
    with log.path.open("a") as f:
        f.write("linha quebrada\n")
    assert [r.pergunta for r in log.load()] == ["a", "b"]