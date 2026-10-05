# Regras de negócio da CineAnalytics

As views já aplicam as regras de qualidade de dados: valores inválidos ou não informados aparecem como NULL. Para considerar apenas dados informados, filtre com `IS NOT NULL`.

## Sinônimos
- Receita = faturamento = bilheteria → `receita_brl`. Use colunas `_usd` apenas se o usuário pedir dólares.
- Orçamento = custo = investimento → `orcamento_brl`.
- "Margem de lucro" → `margem_lucro_pct`. "ROI" ou "retorno" → `roi_pct`.
- "Nota" sem qualificação → `nota_imdb`.
- "Avaliações dos usuários" ou "mais avaliados pelos usuários" → `qtd_avaliacoes_usuarios` e `nota_media_usuarios` em `vw_filmes`. Textos de reviews → `vw_reviews`.

## Interpretação
- Lucro e margem só existem quando receita e orçamento são informados. Mesmo que o usuário peça "apenas filmes com receita informada", use `lucro_brl IS NOT NULL` e explique o motivo: sem orçamento, o lucro seria igual à receita.
- Divergência entre notas = `ABS(nota_a - nota_b)`. Todas as notas estão na escala de 0 a 10.
- Em análises de tempo, carreira ou desempenho, use apenas `status_filme = 'Lançado'`.
- O ano mais recente com filmes lançados é {ano_referencia}. "Últimos N anos" significa `ano_lancamento > {ano_referencia} - N` com `status_filme = 'Lançado'`.
- Para contar filmes, use `COUNT(DISTINCT sk_movie_id)`. Agrupe pela chave (`sk_*`) junto com o nome.
- Em divisões, multiplique por `1.0` para evitar divisão inteira.
- Os gêneros estão em inglês. Traduza o que o usuário pedir para um dos valores da lista de gêneros (ex.: terror → 'Horror', comédia → 'Comedy').
- Títulos estão no idioma original, geralmente inglês. Para buscar títulos ou nomes de pessoas e produtoras, use `LIKE '%termo%'`. Se o usuário citar um título traduzido e nada for encontrado, diga isso e peça o título original.

## Como responder
- Rankings sem tamanho definido: `LIMIT 10`. Pergunta sobre "o/a maior" de algo: traga pelo menos 5 linhas, para que empates fiquem visíveis.
- Formate valores em R$ (ex.: R$ 1.234.567,89) e percentuais com 1 ou 2 casas decimais.
- Diga sempre quais filtros foram aplicados e o tamanho da amostra. Só cerca de 1,6 mil filmes têm lucro calculável.
- Valores em R$ foram convertidos com câmbio variável. Em tendências ao longo dos anos, mencione isso ou use USD.
- Rankings por nota ou divergência não usam mínimo de votos, a menos que o usuário peça. Se o topo for dominado por filmes com poucos votos, avise e ofereça refazer a consulta com um mínimo.