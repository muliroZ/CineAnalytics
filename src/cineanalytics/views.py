"""Views de negócio criadas como TEMP VIEWs a cada conexão.

As regras de qualidade de dados descobertas no diagnóstico (sql/diagnostico.sql)
ficam codificadas aqui, e não no prompt. O agente só enxerga estas views, então
"dado informado" passa a significar simplesmente "coluna IS NOT NULL".

As views vivem no schema `temp` da conexão: o cinerocket.db continua intacto
e pode ser aberto em modo somente leitura.
"""

from __future__ import annotations

from dataclasses import dataclass

# Valores financeiros abaixo deste corte (em USD) são erros de cadastro
# (ex.: orçamento de US$ 1). O corte é em USD porque o câmbio para BRL varia.
MIN_VALOR_USD = 1000

# Nomes inválidos em dim_people vindos de erro de parsing: '0.6', '100', '1950s'.
# Mantém nomes legítimos com dígitos, como '50 Cent' e '2Pac'.
NOME_VALIDO = (
    "nome_pessoa GLOB '*[^0-9.]*' "
    "AND nome_pessoa NOT GLOB '[12][0-9][0-9]0s'"
)


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    description: str


@dataclass(frozen=True)
class View:
    name: str
    description: str
    columns: tuple[Column, ...]
    sql: str

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]


def _valido(col: str) -> str:
    return f"f.{col}_usd >= {MIN_VALOR_USD}"


_FINANCEIRO_OK = f"{_valido('receita')} AND {_valido('orcamento')}"

VW_FILMES = View(
    name="vw_filmes",
    description=(
        "Uma linha por filme, com métricas de desempenho, notas e avaliações dos usuários. "
        "Valores ausentes ou inválidos são NULL: filtre com IS NOT NULL."
    ),
    columns=(
        Column("sk_movie_id", "TEXT", "Chave do filme; use para juntar com as outras views"),
        Column("titulo", "TEXT", "Título do filme"),
        Column("ano_lancamento", "INTEGER", "Ano de lançamento (2016 a 2029)"),
        Column("data_lancamento", "TEXT", "Data de lançamento (AAAA-MM-DD)"),
        Column("status_filme", "TEXT", "'Lançado', 'Pós-Produção', 'Em Produção' ou 'Planejado'"),
        Column("duracao_minutos", "INTEGER", "Duração em minutos"),
        Column("idioma_original", "TEXT", "Código do idioma original (ex.: 'en', 'pt')"),
        Column("sinopse", "TEXT", "Sinopse do filme (texto longo; evite selecionar sem necessidade)"),
        Column("popularidade", "REAL", "Índice de popularidade do TMDB (maior = mais popular)"),
        Column("nota_tmdb", "REAL", "Nota TMDB de 0 a 10; NULL se não há votos"),
        Column("qtd_votos_tmdb", "INTEGER", "Quantidade de votos no TMDB"),
        Column("nota_imdb", "REAL", "Nota IMDb de 0 a 10; NULL se não há votos"),
        Column("qtd_votos_imdb", "INTEGER", "Quantidade de votos no IMDb"),
        Column("nota_media_usuarios", "REAL", "Nota média dos usuários da plataforma, 0 a 10; NULL se não há avaliações"),
        Column("qtd_avaliacoes_usuarios", "INTEGER", "Quantidade de avaliações dos usuários da plataforma"),
        Column("receita_brl", "REAL", "Receita/faturamento/bilheteria em R$; NULL se não informada"),
        Column("orcamento_brl", "REAL", "Orçamento em R$; NULL se não informado"),
        Column("lucro_brl", "REAL", "Lucro em R$; preenchido só quando receita E orçamento são informados"),
        Column("margem_lucro_pct", "REAL", "Margem de lucro (%) = lucro / receita * 100"),
        Column("roi_pct", "REAL", "Retorno sobre investimento (%) = lucro / orçamento * 100"),
        Column("receita_usd", "REAL", "Receita em US$; NULL se não informada"),
        Column("orcamento_usd", "REAL", "Orçamento em US$; NULL se não informado"),
        Column("lucro_usd", "REAL", "Lucro em US$; mesma regra de lucro_brl"),
    ),
    sql=f"""
SELECT
    m.sk_movie_id,
    m.titulo,
    m.ano_lancamento,
    m.data_lancamento,
    m.status_filme,
    m.duracao_minutos,
    m.idioma_original,
    m.sinopse,
    CAST(f.popularidade AS REAL)                                       AS popularidade,
    CASE WHEN f.qtd_tmdb > 0 THEN CAST(f.nota_tmdb AS REAL) END        AS nota_tmdb,
    COALESCE(f.qtd_tmdb, 0)                                            AS qtd_votos_tmdb,
    CASE WHEN f.qtd_imdb > 0 THEN CAST(f.nota_imdb AS REAL) END        AS nota_imdb,
    COALESCE(f.qtd_imdb, 0)                                            AS qtd_votos_imdb,
    CASE WHEN r.qtd_avaliacoes_usuarios > 0
         THEN CAST(r.nota_media_usuarios AS REAL) END                  AS nota_media_usuarios,
    COALESCE(r.qtd_avaliacoes_usuarios, 0)                             AS qtd_avaliacoes_usuarios,
    CASE WHEN {_valido('receita')}   THEN CAST(f.receita_brl AS REAL)   END AS receita_brl,
    CASE WHEN {_valido('orcamento')} THEN CAST(f.orcamento_brl AS REAL) END AS orcamento_brl,
    CASE WHEN {_FINANCEIRO_OK} THEN CAST(f.lucro_brl AS REAL) END      AS lucro_brl,
    CASE WHEN {_FINANCEIRO_OK}
         THEN ROUND(f.lucro_brl * 100.0 / f.receita_brl, 2) END        AS margem_lucro_pct,
    CASE WHEN {_FINANCEIRO_OK}
         THEN ROUND(f.lucro_brl * 100.0 / f.orcamento_brl, 2) END      AS roi_pct,
    CASE WHEN {_valido('receita')}   THEN CAST(f.receita_usd AS REAL)   END AS receita_usd,
    CASE WHEN {_valido('orcamento')} THEN CAST(f.orcamento_usd AS REAL) END AS orcamento_usd,
    CASE WHEN {_FINANCEIRO_OK} THEN CAST(f.lucro_usd AS REAL) END      AS lucro_usd
FROM dim_movies m
JOIN fact_movies_performance f ON f.sk_movie_id = m.sk_movie_id
LEFT JOIN dim_reviews r        ON r.sk_movie_id = m.sk_movie_id
""",
)

VW_GENEROS_FILME = View(
    name="vw_generos_filme",
    description=(
        "Relação filme ↔ gênero (N:N). Um filme com 3 gêneros aparece 3 vezes. "
        "Cerca de 21% dos filmes não têm gênero e não aparecem aqui."
    ),
    columns=(
        Column("sk_movie_id", "TEXT", "Chave do filme (junta com vw_filmes)"),
        Column("nome_genero", "TEXT", "Nome do gênero"),
    ),
    sql="""
SELECT b.sk_movie_id, g.nome_genero
FROM bridge_movie_genre b
JOIN dim_genres g ON g.sk_genre_id = b.sk_genre_id
""",
)

VW_PESSOAS_FILME = View(
    name="vw_pessoas_filme",
    description=(
        "Relação filme ↔ pessoa (N:N), com o papel da pessoa no filme. "
        "Nomes inválidos da base já foram removidos. A mesma pessoa real tem um "
        "sk_person_id diferente para cada papel."
    ),
    columns=(
        Column("sk_movie_id", "TEXT", "Chave do filme (junta com vw_filmes)"),
        Column("sk_person_id", "TEXT", "Chave da pessoa naquele papel"),
        Column("nome_pessoa", "TEXT", "Nome da pessoa"),
        Column("tipo_pessoa", "TEXT", "'Ator', 'Diretor' ou 'Roteirista'"),
    ),
    sql=f"""
SELECT b.sk_movie_id, p.sk_person_id, p.nome_pessoa, p.tipo_pessoa
FROM bridge_movie_person b
JOIN dim_people p ON p.sk_person_id = b.sk_person_id
WHERE {NOME_VALIDO.replace('nome_pessoa', 'p.nome_pessoa')}
""",
)

VW_PRODUTORAS_FILME = View(
    name="vw_produtoras_filme",
    description=(
        "Relação filme ↔ produtora (N:N). Um filme coproduzido aparece uma vez "
        "para cada produtora."
    ),
    columns=(
        Column("sk_movie_id", "TEXT", "Chave do filme (junta com vw_filmes)"),
        Column("sk_company_id", "TEXT", "Chave da produtora"),
        Column("nome_produtora", "TEXT", "Nome da produtora"),
    ),
    sql="""
SELECT b.sk_movie_id, c.sk_company_id, c.nome_produtora
FROM bridge_movie_company b
JOIN dim_companies c ON c.sk_company_id = b.sk_company_id
""",
)

VW_REVIEWS = View(
    name="vw_reviews",
    description=(
        "Reviews individuais escritas pelos usuários (uma linha por review). "
        "Para contagem e nota média por filme, prefira as colunas de vw_filmes."
    ),
    columns=(
        Column("id_review", "TEXT", "Chave da review"),
        Column("sk_movie_id", "TEXT", "Chave do filme (junta com vw_filmes)"),
        Column("autor", "TEXT", "Nome de quem escreveu"),
        Column("nota", "REAL", "Nota dada na review, de 0 a 10"),
        Column("texto", "TEXT", "Texto da review"),
        Column("criado_em", "TEXT", "Data e hora da review"),
    ),
    sql="""
SELECT sk_movie_review_id AS id_review, sk_movie_id, name AS autor,
       CAST(rating AS REAL) AS nota, text AS texto, created_at AS criado_em
FROM movie_reviews
""",
)

VIEWS: tuple[View, ...] = (
    VW_FILMES,
    VW_GENEROS_FILME,
    VW_PESSOAS_FILME,
    VW_PRODUTORAS_FILME,
    VW_REVIEWS,
)