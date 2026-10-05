-- DDL da camada Gold (cinerocket.db), usado para montar o banco de teste.
CREATE TABLE dim_companies (
	sk_company_id VARCHAR(64) NOT NULL, nome_produtora VARCHAR(255) NOT NULL,
	CONSTRAINT pk_dim_companies PRIMARY KEY (sk_company_id),
	CONSTRAINT uq_dim_companies_nome_produtora UNIQUE (nome_produtora)
);
CREATE TABLE dim_genres (
	sk_genre_id VARCHAR(64) NOT NULL, nome_genero VARCHAR(50) NOT NULL,
	CONSTRAINT pk_dim_genres PRIMARY KEY (sk_genre_id),
	CONSTRAINT uq_dim_genres_nome_genero UNIQUE (nome_genero)
);
CREATE TABLE dim_movies (
	sk_movie_id VARCHAR(64) NOT NULL, id_filme VARCHAR(50) NOT NULL, titulo VARCHAR(500) NOT NULL,
	data_lancamento DATE, ano_lancamento INTEGER, duracao_minutos INTEGER, idioma_original VARCHAR(10),
	status_filme VARCHAR(50), sinopse VARCHAR(4000), url_poster VARCHAR(2048), url_backdrop VARCHAR(2048),
	CONSTRAINT pk_dim_movies PRIMARY KEY (sk_movie_id)
);
CREATE TABLE dim_people (
	sk_person_id VARCHAR(64) NOT NULL, nome_pessoa VARCHAR(255) NOT NULL, tipo_pessoa VARCHAR(20) NOT NULL,
	CONSTRAINT pk_dim_people PRIMARY KEY (sk_person_id),
	CONSTRAINT ck_dim_people_tipo_pessoa_valido CHECK (tipo_pessoa IN ('Ator', 'Diretor', 'Roteirista')),
	CONSTRAINT uq_dim_people_nome_pessoa_tipo_pessoa UNIQUE (nome_pessoa, tipo_pessoa)
);
CREATE TABLE bridge_movie_company (
	sk_movie_id VARCHAR(64) NOT NULL REFERENCES dim_movies (sk_movie_id),
	sk_company_id VARCHAR(64) NOT NULL REFERENCES dim_companies (sk_company_id),
	PRIMARY KEY (sk_movie_id, sk_company_id)
);
CREATE TABLE bridge_movie_genre (
	sk_movie_id VARCHAR(64) NOT NULL REFERENCES dim_movies (sk_movie_id),
	sk_genre_id VARCHAR(64) NOT NULL REFERENCES dim_genres (sk_genre_id),
	PRIMARY KEY (sk_movie_id, sk_genre_id)
);
CREATE TABLE bridge_movie_person (
	sk_movie_id VARCHAR(64) NOT NULL REFERENCES dim_movies (sk_movie_id),
	sk_person_id VARCHAR(64) NOT NULL REFERENCES dim_people (sk_person_id),
	PRIMARY KEY (sk_movie_id, sk_person_id)
);
CREATE TABLE dim_reviews (
	sk_review_id VARCHAR(64) NOT NULL, sk_movie_id VARCHAR(64) NOT NULL,
	qtd_avaliacoes_usuarios INTEGER NOT NULL, nota_media_usuarios DOUBLE,
	PRIMARY KEY (sk_review_id), UNIQUE (sk_movie_id)
);
CREATE TABLE fact_movies_performance (
	sk_movie_id VARCHAR(64) NOT NULL,
	orcamento_usd NUMERIC(18, 2), receita_usd NUMERIC(18, 2), lucro_usd NUMERIC(18, 2) NOT NULL,
	orcamento_brl NUMERIC(18, 2), receita_brl NUMERIC(18, 2), lucro_brl NUMERIC(18, 2) NOT NULL,
	popularidade DOUBLE, nota_tmdb DOUBLE, qtd_tmdb INTEGER, nota_imdb DOUBLE, qtd_imdb INTEGER,
	PRIMARY KEY (sk_movie_id)
);
CREATE TABLE movie_reviews (
	id INTEGER NOT NULL, sk_movie_review_id VARCHAR(64) NOT NULL, sk_movie_id VARCHAR(64) NOT NULL,
	name VARCHAR(120) NOT NULL, rating DOUBLE NOT NULL, text VARCHAR(4000) NOT NULL,
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
	PRIMARY KEY (id), CHECK (rating >= 0 AND rating <= 10)
);