from pathlib import Path

import pytest
import yaml

QUESTIONS = {
    q["id"]: q
    for q in yaml.safe_load(
        (Path(__file__).parents[1] / "evals" / "questions.yaml").read_text(encoding="utf-8")
    )["questions"]
}

VIEW_SQL = {
    "fin_01": "SELECT titulo FROM vw_filmes WHERE receita_brl IS NOT NULL ORDER BY receita_brl DESC LIMIT 10",
    "fin_02": """SELECT g.nome_genero, ROUND(AVG(f.lucro_brl), 2) FROM vw_filmes f
                 JOIN vw_generos_filme g USING (sk_movie_id) WHERE f.lucro_brl IS NOT NULL
                 GROUP BY g.nome_genero ORDER BY 2 DESC""",
    "fin_03": """SELECT titulo FROM vw_filmes WHERE margem_lucro_pct IS NOT NULL
                 ORDER BY margem_lucro_pct DESC LIMIT 10""",
    "pop_02": """SELECT titulo FROM vw_filmes WHERE nota_tmdb IS NOT NULL AND nota_imdb IS NOT NULL
                 ORDER BY ABS(nota_tmdb - nota_imdb) DESC LIMIT 10""",
    "cast_01": """SELECT p.nome_pessoa, COUNT(DISTINCT p.sk_movie_id) AS n
                  FROM vw_pessoas_filme p JOIN vw_filmes f USING (sk_movie_id)
                  WHERE p.tipo_pessoa = 'Ator' AND f.status_filme = 'Lançado'
                    AND f.ano_lancamento > {ano_referencia} - 5
                  GROUP BY p.sk_person_id, p.nome_pessoa ORDER BY n DESC LIMIT 10""",
    "cast_03": """SELECT a.nome_pessoa, d.nome_pessoa, COUNT(DISTINCT a.sk_movie_id) AS n
                  FROM vw_pessoas_filme a JOIN vw_pessoas_filme d USING (sk_movie_id)
                  WHERE a.tipo_pessoa = 'Ator' AND d.tipo_pessoa = 'Diretor'
                    AND a.nome_pessoa <> d.nome_pessoa
                  GROUP BY a.sk_person_id, d.sk_person_id ORDER BY n DESC LIMIT 10""",
    "gen_02": """SELECT p.nome_produtora, SUM(f.lucro_brl) AS total FROM vw_filmes f
                 JOIN vw_produtoras_filme p USING (sk_movie_id) WHERE f.lucro_brl IS NOT NULL
                 GROUP BY p.sk_company_id, p.nome_produtora ORDER BY total DESC LIMIT 10""",
    "gen_03": """SELECT g.nome_genero, AVG(f.margem_lucro_pct) AS m FROM vw_filmes f
                 JOIN vw_generos_filme g USING (sk_movie_id) WHERE f.margem_lucro_pct IS NOT NULL
                 GROUP BY g.nome_genero ORDER BY m DESC""",
    "usr_01": """SELECT titulo FROM vw_filmes WHERE qtd_avaliacoes_usuarios > 0
                 ORDER BY qtd_avaliacoes_usuarios DESC LIMIT 10""",
    "usr_02": """SELECT titulo FROM vw_filmes
                 WHERE nota_media_usuarios IS NOT NULL AND nota_imdb IS NOT NULL
                 ORDER BY ABS(nota_media_usuarios - nota_imdb) DESC LIMIT 10""",
}

def _project(rows, cols):
    return [tuple(r[i] for i in cols) for r in rows]


@pytest.mark.parametrize("qid", sorted(QUESTIONS))
def test_referencia_executa(db, qid):
    db.execute(QUESTIONS[qid]["sql"])


@pytest.mark.parametrize("qid", sorted(VIEW_SQL))
def test_views_concordam_com_referencia(db, qid):
    q = QUESTIONS[qid]
    cols = q["compare_cols"]
    ref = _project(db.execute(q["sql"]).rows, cols)
    got = _project(db.execute(VIEW_SQL[qid].format(ano_referencia=db.reference_year)).rows, range(len(cols)))
    assert ref, f"{qid}: a referência voltou vazia; o fixture não cobre esse caso"
    if q["check"] == "set":
        assert sorted(ref) == sorted(got)
    elif q["check"] == "top1":
        assert ref[0] == got[0]
    else:
        assert ref == got
