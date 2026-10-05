from datetime import datetime, timedelta

from typer.testing import CliRunner

from cineanalytics import cli
from cineanalytics.models import AgentRun, QueryLog
from cineanalytics.report import (
    build_report,
    chart_svg,
    compact_value,
    pick_chart_columns,
)

T0 = datetime(2026, 10, 4, 14, 0)


def _run(pergunta, **kw):
    return AgentRun(pergunta=pergunta, criado_em=kw.pop("criado_em", T0), **kw)


RUNS = [
    _run(
        "Top filmes por receita?",
        resposta="**Delta** lidera.\n\n| Filme | Receita |\n|---|---|\n| Delta | R$ 5 mi |",
        modelo="fornecedor/modelo:free", requisicoes=3, duracao_s=4.2,
        consultas=[
            QueryLog(sql="SELECT * FROM dim_movies", error="Tabela 'dim_movies' não disponível."),
            QueryLog(sql="SELECT titulo, receita_brl FROM vw_filmes", columns=["titulo", "receita_brl"],
                     rows=[["Delta", 5_000_000.0], ["Alpha", 1_500_000.0], ["Gamma", 200_000.0]]),
        ],
    ),
    _run("Pergunta que falhou", erro="Limite de requisições do OpenRouter atingido.",
         criado_em=T0 + timedelta(minutes=5)),
    _run("Pergunta do cache", resposta="ok", cache_hit=True, criado_em=T0 + timedelta(minutes=9)),
]


def test_relatorio_tem_respostas_erros_e_estatisticas():
    html = build_report(RUNS, generated_at=T0)
    assert "Relatório de consultas" in html
    assert "<strong>Delta</strong>" in html and "<table>" in html   # markdown renderizado
    assert "Limite de requisições do OpenRouter" in html
    assert "resposta do cache" in html
    assert "após 1 correção" in html                                  # tentativa recusada
    assert "R$ 5.000.000,00" in html                                  # tabela formatada
    assert "<svg" in html                                              # gráfico gerado
    assert "04/10/2026 14:00" in html and "04/10/2026 14:09" in html


def test_html_da_resposta_do_llm_e_escapado():
    html = build_report([_run("x", resposta="<script>alert(1)</script>", consultas=[
        QueryLog(sql="SELECT 1", columns=["a"], rows=[["<b>"]])])])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html and "&lt;b&gt;" in html


def test_relatorio_vazio_orienta_o_usuario():
    assert "Nenhuma pergunta registrada" in build_report([])


def test_escolha_de_colunas_do_grafico():
    assert pick_chart_columns(["titulo", "receita"], [["A", 1], ["B", 2]]) == (0, 1)
    assert pick_chart_columns(["ano_lancamento", "nota"], [[2020, 6.1], [2021, 6.3]]) == (0, 1)
    assert pick_chart_columns(["receita", "titulo"], [[1, "A"], [2, "B"]]) == (1, 0)
    assert pick_chart_columns(["titulo"], [["A"], ["B"]]) is None          # nada numérico
    assert pick_chart_columns(["titulo", "n"], [["A", 1]]) is None          # uma linha só


def test_grafico_lida_com_valores_negativos_e_rotulos_perigosos():
    svg = chart_svg(["produtora", "lucro_brl"], [["<X>", 100.0], ["Y", -50.0]])
    assert 'class="bar neg"' in svg and 'class="zero"' in svg
    assert "&lt;X&gt;" in svg and "<X>" not in svg


def test_cli_report_gera_arquivo_filtrado(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CINEANALYTICS_STATE_DIR", str(tmp_path / "state"))
    from cineanalytics.storage import RunLog

    log = RunLog(tmp_path / "state" / "runs.jsonl")
    for r in RUNS:
        log.append(r)
    out = tmp_path / "rel.html"
    result = CliRunner().invoke(cli.app, ["report", "--ultimas", "1", "--saida", str(out)])
    assert result.exit_code == 0, result.output
    html = out.read_text(encoding="utf-8")
    assert "Pergunta do cache" in html and "Top filmes por receita?" not in html


def test_cli_report_sem_dados_explica_o_que_fazer(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CINEANALYTICS_STATE_DIR", str(tmp_path / "vazio"))
    result = CliRunner().invoke(cli.app, ["report"])
    assert result.exit_code == 1 and "cineanalytics ask" in result.output


def test_valores_compactos_no_grafico():
    assert compact_value("receita_brl", 11_712_345_678.9) == "R$ 11,7 bi"
    assert compact_value("lucro_brl", -3_456_789.0) == "−R$ 3,5 mi"
    assert compact_value("qtd_filmes", 45_200) == "45,2 mil"
    assert compact_value("nota_media", 6.31) == "6,31"
    assert compact_value("margem_lucro_pct", 66.67) == "66,67%"


def test_falha_sem_uso_registrado_nao_mostra_zero_requisicoes():
    html = build_report([_run("falhou", erro="429")])
    assert "0 requisições" not in html