import pytest

from cineanalytics.guardrails import SQLValidationError, validate_select

ALLOWED = ["vw_filmes", "vw_generos_filme", "vw_pessoas_filme"]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT titulo FROM vw_filmes",
        "select titulo from VW_FILMES;",
        "SELECT titulo FROM temp.vw_filmes",
        "WITH top AS (SELECT * FROM vw_filmes LIMIT 5) SELECT titulo FROM top",
        "SELECT titulo FROM vw_filmes UNION SELECT nome_genero FROM vw_generos_filme",
        "SELECT nome_pessoa FROM vw_pessoas_filme WHERE nome_pessoa GLOB '*a*'",
        "SELECT x FROM (SELECT titulo AS x FROM vw_filmes) sub",
        "SELECT COUNT(*) FROM vw_filmes f JOIN vw_generos_filme g USING (sk_movie_id)",
    ],
)
def test_aceita_consultas_de_leitura(sql):
    assert validate_select(sql, ALLOWED)


def test_remove_ponto_e_virgula_final():
    assert validate_select("  SELECT 1 FROM vw_filmes ;  ", ALLOWED) == "SELECT 1 FROM vw_filmes"


@pytest.mark.parametrize(
    ("sql", "trecho_da_mensagem"),
    [
        ("", "vazia"),
        ("DELETE FROM vw_filmes", "leitura"),
        ("DROP TABLE dim_movies", "leitura"),
        ("UPDATE vw_filmes SET titulo = 'x'", "leitura"),
        ("INSERT INTO vw_filmes (titulo) SELECT 'x'", "leitura"),
        ("PRAGMA table_info(dim_movies)", "leitura"),
        ("ATTACH DATABASE 'x.db' AS x", "leitura"),
        ("SELECT 1 FROM vw_filmes; DROP TABLE dim_movies", "uma consulta"),
        ("SELECT 1 FROM vw_filmes; SELECT 2 FROM vw_filmes", "uma consulta"),
        ("SELECT * FROM dim_movies", "não disponível"),
        ("SELECT * FROM sqlite_master", "não disponível"),
        ("SELECT * FROM main.vw_filmes", "prefixo"),
        ("SELECT * FROM pragma_table_info('dim_movies')", "Funções de tabela"),
        ("WITH x AS (SELECT * FROM dim_people) SELECT * FROM x", "não disponível"),
        ("SELEC titulo FROM vw_filmes", "sintaxe"),
    ],
)
def test_rejeita_consultas_perigosas_ou_invalidas(sql, trecho_da_mensagem):
    with pytest.raises(SQLValidationError, match=trecho_da_mensagem):
        validate_select(sql, ALLOWED)