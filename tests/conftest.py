import sqlite3
from pathlib import Path

import pytest

from cineanalytics.db import Database

FIXTURES = Path(__file__).parent / "fixtures"

# (sk, titulo, ano, status)
MOVIES = [
    ("m1", "Alpha", 2023, "Lançado"),
    ("m2", "Beta", 2026, "Lançado"),
    ("m3", "Gamma", 2024, "Lançado"),     # orçamento de US$ 1 (inválido)
    ("m4", "Futuro", 2029, "Planejado"),  # não lançado, ano no futuro
    ("m5", "Antigo", 2018, "Lançado"),    # fora da janela de 5 anos
    ("m6", "Delta", 2025, "Lançado"),
]
# (sk, orc_usd, rec_usd, lucro_usd, orc_brl, rec_brl, lucro_brl, pop, tmdb, qtd_tmdb, imdb, qtd_imdb)
FACTS = [
    ("m1", 100_000, 300_000, 200_000, 500_000, 1_500_000, 1_000_000, 50.0, 7.0, 100, 7.5, 200),
    ("m2", None, None, 0, None, None, 0, 30.0, 0.0, 0, 8.0, 20),           # TMDB 0 sem votos
    ("m3", 1, 40_000, 39_999, 5, 200_000, 199_995, 20.0, 5.0, 5, 4.0, 5),
    ("m4", None, None, 0, None, None, 0, 1.0, 0.0, 0, None, None),
    ("m5", 50_000, 60_000, 10_000, 250_000, 300_000, 50_000, 10.0, 6.0, 10, None, None),
    ("m6", 200_000, 1_000_000, 800_000, 1_000_000, 5_000_000, 4_000_000, 40.0, 8.0, 50, 6.0, 80),
]
GENRES = {"g1": "Drama", "g2": "Ação"}
MOVIE_GENRES = [("m1", "g1"), ("m3", "g1"), ("m6", "g1"), ("m1", "g2"), ("m5", "g2")]
PEOPLE = [
    ("p1", "Ana", "Ator"), ("p2", "Bia", "Diretor"),
    ("p3", "0.6", "Ator"), ("p4", "1950s", "Diretor"),         # nomes inválidos
    ("p5", "Carlos", "Ator"), ("p6", "Carlos", "Diretor"),     # atua e dirige o próprio filme
    ("p7", "50 Cent", "Ator"),                                 # nome legítimo com dígitos
]
MOVIE_PEOPLE = (
    [(m, "p1") for m in ("m1", "m3", "m6", "m4", "m5")]
    + [(m, "p2") for m in ("m1", "m3", "m6")]
    + [(m, "p3") for m in ("m1", "m2", "m3", "m4", "m5", "m6")]
    + [(m, "p4") for m in ("m1", "m2", "m3", "m4", "m5", "m6")]
    + [("m6", "p5"), ("m6", "p6"), ("m2", "p7")]
)
COMPANIES = {"c1": "X Films", "c2": "Y Studio"}
MOVIE_COMPANIES = [("m1", "c1"), ("m6", "c1"), ("m1", "c2"), ("m5", "c2")]
REVIEWS = [  # movie_reviews: (id, sk_review, sk_movie, autor, nota, texto)
    (1, "rv1", "m1", "joao", 5.0, "bom"),
    (2, "rv2", "m1", "maria", 7.0, "ótimo"),
    (3, "rv3", "m3", "ana", 9.0, "excelente"),
]


@pytest.fixture(autouse=True)
def _isola_configuracao_global(monkeypatch, tmp_path_factory):
    """Impede que o .env global da máquina de quem roda os testes interfira neles."""
    monkeypatch.setenv("CINEANALYTICS_CONFIG_DIR", str(tmp_path_factory.mktemp("config_global")))


@pytest.fixture(scope="session")
def db_path(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("data") / "cinerocket_test.db"
    conn = sqlite3.connect(path)
    conn.executescript((FIXTURES / "schema.sql").read_text(encoding="utf-8"))
    conn.executemany(
        "INSERT INTO dim_movies (sk_movie_id, id_filme, titulo, ano_lancamento, status_filme) "
        "VALUES (?, ?, ?, ?, ?)",
        [(sk, sk, t, a, s) for sk, t, a, s in MOVIES],
    )
    conn.executemany(f"INSERT INTO fact_movies_performance VALUES ({','.join('?' * 12)})", FACTS)
    conn.executemany("INSERT INTO dim_genres VALUES (?, ?)", GENRES.items())
    conn.executemany("INSERT INTO bridge_movie_genre VALUES (?, ?)", MOVIE_GENRES)
    conn.executemany("INSERT INTO dim_people VALUES (?, ?, ?)", PEOPLE)
    conn.executemany("INSERT INTO bridge_movie_person VALUES (?, ?)", MOVIE_PEOPLE)
    conn.executemany("INSERT INTO dim_companies VALUES (?, ?)", COMPANIES.items())
    conn.executemany("INSERT INTO bridge_movie_company VALUES (?, ?)", MOVIE_COMPANIES)
    conn.executemany(
        "INSERT INTO movie_reviews (id, sk_movie_review_id, sk_movie_id, name, rating, text) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        REVIEWS,
    )
    conn.execute(
        "INSERT INTO dim_reviews "
        "SELECT 'dr_' || sk_movie_id, sk_movie_id, COUNT(*), AVG(rating) "
        "FROM movie_reviews GROUP BY sk_movie_id"
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture()
def db(db_path):
    with Database(db_path, max_rows=50, timeout_s=5) as database:
        yield database