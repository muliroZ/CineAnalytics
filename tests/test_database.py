from concurrent.futures import ThreadPoolExecutor

import pytest

from cineanalytics.db import Database, QueryExecutionError, QueryTimeoutError


def test_arquivo_inexistente_gera_erro_claro(tmp_path):
    with pytest.raises(FileNotFoundError, match="README"):
        Database(tmp_path / "nao_existe.db")


def test_colunas_documentadas_batem_com_as_views(db):
    for view in db.views:
        result = db.execute(f"SELECT * FROM {view.name}", max_rows=0)
        assert result.columns == view.column_names, view.name


def test_ano_de_referencia_ignora_filmes_nao_lancados(db):
    assert db.reference_year == 2026


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO dim_genres VALUES ('g9', 'Terror')",
        "DELETE FROM dim_movies",
        "CREATE TEMP TABLE x (a)",
        "DROP VIEW vw_filmes",
        "ATTACH DATABASE ':memory:' AS outro",
        "PRAGMA writable_schema = ON",
    ],
)
def test_escrita_e_bloqueada_mesmo_sem_guardrail(db, sql):
    with pytest.raises(QueryExecutionError):
        db.execute(sql)


def test_trunca_resultados_grandes(db):
    result = db.execute("SELECT * FROM vw_pessoas_filme", max_rows=3)
    assert len(result.rows) == 3
    assert result.truncated


def test_resultado_pequeno_nao_e_truncado(db):
    result = db.execute("SELECT titulo FROM vw_filmes")
    assert len(result.rows) == 6
    assert not result.truncated


def test_timeout_interrompe_consulta_infinita(db_path):
    infinita = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT MAX(x) FROM c"
    with Database(db_path, timeout_s=0.2) as db, pytest.raises(QueryTimeoutError):
        db.execute(infinita)


def test_erro_de_coluna_vira_query_execution_error(db):
    with pytest.raises(QueryExecutionError, match="no such column"):
        db.execute("SELECT coluna_inexistente FROM vw_filmes")


def test_funciona_a_partir_de_outras_threads(db):
    # Pydantic-AI roda tools síncronas em threads separadas.
    with ThreadPoolExecutor(max_workers=4) as pool:
        counts = list(pool.map(lambda _: db.execute("SELECT COUNT(*) FROM vw_filmes").rows[0][0], range(8)))
    assert counts == [6] * 8


class TestRegrasDasViews:
    def test_orcamento_irreal_vira_null_e_zera_lucro(self, db):
        row = db.execute(
            "SELECT orcamento_usd, receita_usd, lucro_brl, margem_lucro_pct FROM vw_filmes WHERE titulo = 'Gamma'"
        ).rows[0]
        assert row == (None, 40000.0, None, None)

    def test_margem_nao_sofre_divisao_inteira(self, db):
        margem = db.execute("SELECT margem_lucro_pct FROM vw_filmes WHERE titulo = 'Alpha'").rows[0][0]
        assert margem == pytest.approx(66.67)

    def test_nota_tmdb_sem_votos_vira_null(self, db):
        assert db.execute("SELECT nota_tmdb FROM vw_filmes WHERE titulo = 'Beta'").rows[0][0] is None

    def test_nomes_invalidos_sao_removidos(self, db):
        nomes = {r[0] for r in db.execute("SELECT DISTINCT nome_pessoa FROM vw_pessoas_filme").rows}
        assert nomes == {"Ana", "Bia", "Carlos", "50 Cent"}

    def test_filme_sem_review_tem_contagem_zero(self, db):
        row = db.execute(
            "SELECT qtd_avaliacoes_usuarios, nota_media_usuarios FROM vw_filmes WHERE titulo = 'Delta'"
        ).rows[0]
        assert row == (0, None)


def test_schema_prompt_descreve_todas_as_views(db):
    prompt = db.schema_prompt()
    for view in db.views:
        assert f"### {view.name}" in prompt
    assert "dim_movies" not in prompt  # o agente não deve ver as tabelas brutas