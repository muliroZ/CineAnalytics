-- =====================================================================
-- Diagnóstico do cinerocket.db
-- Ex.: sqlite3 data/cinerocket.db < sql/diagnostico.sql
-- =====================================================================
.headers on
.mode column

-- D1. Tamanho da base e faixa de anos (define "últimos 5 anos")
SELECT COUNT(*) AS total_filmes,
       MIN(ano_lancamento) AS ano_min,
       MAX(ano_lancamento) AS ano_max,
       SUM(ano_lancamento IS NULL) AS sem_ano
FROM dim_movies;

-- D2. Status dos filmes (existem filmes não lançados / com ano futuro?)
SELECT status_filme, COUNT(*) AS qtd, MAX(ano_lancamento) AS ano_max
FROM dim_movies
GROUP BY status_filme
ORDER BY qtd DESC;

-- D3. Receita/orçamento ausentes: aparecem como NULL, como 0, ou ambos?
SELECT COUNT(*)                   AS total,
       SUM(receita_brl IS NULL)   AS receita_null,
       SUM(receita_brl = 0)       AS receita_zero,
       SUM(receita_brl > 0)       AS receita_ok,
       SUM(orcamento_brl IS NULL) AS orcamento_null,
       SUM(orcamento_brl = 0)     AS orcamento_zero,
       SUM(orcamento_brl > 0)     AS orcamento_ok,
       SUM(receita_brl > 0 AND orcamento_brl > 0) AS ambos_ok
FROM fact_movies_performance;

-- D4. Como lucro_brl (NOT NULL) é preenchido quando falta receita ou orçamento?
--     Se aparecer lucro = -orçamento ou lucro = receita, o lucro só é confiável
--     quando os dois estão informados.
SELECT receita_brl, orcamento_brl, lucro_brl
FROM fact_movies_performance
WHERE NOT (receita_brl > 0 AND orcamento_brl > 0)
LIMIT 10;

-- D5. lucro_brl bate com receita - orçamento?
SELECT COUNT(*) AS divergentes
FROM fact_movies_performance
WHERE receita_brl > 0 AND orcamento_brl > 0
  AND ABS(lucro_brl - (receita_brl - orcamento_brl)) > 0.01;

-- D6. Tipo real armazenado (NUMERIC pode virar INTEGER -> divisão inteira!)
SELECT typeof(receita_brl) AS tipo, COUNT(*) AS qtd
FROM fact_movies_performance
GROUP BY 1;

-- D7. Taxa de câmbio implícita (é constante? vale citar na resposta)
SELECT ROUND(MIN(receita_brl * 1.0 / receita_usd), 4) AS cambio_min,
       ROUND(MAX(receita_brl * 1.0 / receita_usd), 4) AS cambio_max
FROM fact_movies_performance
WHERE receita_usd > 0;

-- D8. Orçamentos/receitas suspeitos (outliers que distorcem margem/ROI)
SELECT m.titulo, f.orcamento_usd, f.receita_usd
FROM fact_movies_performance f
JOIN dim_movies m ON m.sk_movie_id = f.sk_movie_id
WHERE (f.orcamento_usd > 0 AND f.orcamento_usd < 1000)
   OR (f.receita_usd   > 0 AND f.receita_usd   < 1000)
LIMIT 20;

-- D9. Escalas das notas (todas 0-10? usuários em 0-5?)
SELECT 'nota_tmdb' AS coluna, MIN(nota_tmdb), MAX(nota_tmdb), ROUND(AVG(nota_tmdb), 2) FROM fact_movies_performance
UNION ALL
SELECT 'nota_imdb', MIN(nota_imdb), MAX(nota_imdb), ROUND(AVG(nota_imdb), 2) FROM fact_movies_performance
UNION ALL
SELECT 'nota_media_usuarios', MIN(nota_media_usuarios), MAX(nota_media_usuarios), ROUND(AVG(nota_media_usuarios), 2) FROM dim_reviews
UNION ALL
SELECT 'movie_reviews.rating', MIN(rating), MAX(rating), ROUND(AVG(rating), 2) FROM movie_reviews;

-- D10. Nota 0 significa "sem votos"?
SELECT SUM(nota_tmdb = 0)                  AS tmdb_zero,
       SUM(nota_tmdb = 0 AND qtd_tmdb = 0) AS tmdb_zero_sem_votos,
       SUM(nota_imdb IS NULL)              AS imdb_null,
       SUM(nota_imdb = 0)                  AS imdb_zero
FROM fact_movies_performance;

-- D11. dim_reviews x movie_reviews: são a mesma fonte?
SELECT (SELECT COUNT(*) FROM dim_reviews)                     AS filmes_dim_reviews,
       (SELECT SUM(qtd_avaliacoes_usuarios) FROM dim_reviews) AS soma_qtd_avaliacoes,
       (SELECT COUNT(DISTINCT sk_movie_id) FROM movie_reviews) AS filmes_movie_reviews,
       (SELECT COUNT(*) FROM movie_reviews)                   AS total_movie_reviews;

-- D12. Pessoas por papel e pessoas com mais de um papel
SELECT tipo_pessoa, COUNT(*) AS qtd FROM dim_people GROUP BY 1;

SELECT nome_pessoa, GROUP_CONCAT(tipo_pessoa) AS papeis
FROM dim_people
GROUP BY nome_pessoa
HAVING COUNT(DISTINCT tipo_pessoa) > 1
LIMIT 10;

-- D13. Filmes sem gênero / sem fato (afeta JOIN vs LEFT JOIN)
SELECT (SELECT COUNT(*) FROM dim_movies m
        WHERE NOT EXISTS (SELECT 1 FROM bridge_movie_genre b WHERE b.sk_movie_id = m.sk_movie_id)) AS sem_genero,
       (SELECT COUNT(*) FROM dim_movies m
        WHERE NOT EXISTS (SELECT 1 FROM fact_movies_performance f WHERE f.sk_movie_id = m.sk_movie_id)) AS sem_fato;

-- =====================================================================
-- Parte 2: pendências depois da primeira rodada
-- =====================================================================

-- D4 (não veio na primeira rodada). Como lucro_brl é preenchido quando falta dado?
SELECT receita_brl, orcamento_brl, lucro_brl
FROM fact_movies_performance
WHERE receita_brl IS NULL OR orcamento_brl IS NULL
LIMIT 10;

-- D14. Tamanho das 24 divergências de lucro (arredondamento ou erro?)
SELECT m.titulo, f.receita_brl, f.orcamento_brl, f.lucro_brl,
       ROUND(f.lucro_brl - (f.receita_brl - f.orcamento_brl), 2) AS diferenca
FROM fact_movies_performance f
JOIN dim_movies m ON m.sk_movie_id = f.sk_movie_id
WHERE f.receita_brl > 0 AND f.orcamento_brl > 0
  AND ABS(f.lucro_brl - (f.receita_brl - f.orcamento_brl)) > 0.01
ORDER BY ABS(diferenca) DESC
LIMIT 10;

-- D15. Quantos filmes o corte de US$ 1.000 remove?
SELECT SUM(receita_usd > 0)                             AS com_receita,
       SUM(receita_usd >= 1000)                         AS receita_valida,
       SUM(receita_usd > 0 AND orcamento_usd > 0)       AS com_ambos,
       SUM(receita_usd >= 1000 AND orcamento_usd >= 1000) AS ambos_validos
FROM fact_movies_performance;

-- D16. Impacto dos nomes inválidos em dim_people
SELECT p.tipo_pessoa,
       COUNT(DISTINCT p.sk_person_id) AS pessoas_invalidas,
       COUNT(bp.sk_movie_id)          AS vinculos_com_filmes
FROM dim_people p
LEFT JOIN bridge_movie_person bp ON bp.sk_person_id = p.sk_person_id
WHERE NOT (p.nome_pessoa GLOB '*[^0-9.]*')
   OR p.nome_pessoa GLOB '[12][0-9][0-9]0s'
GROUP BY p.tipo_pessoa;
