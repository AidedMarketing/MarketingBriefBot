import os

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL")


def get_connection():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not configured. Add Railway Postgres to the project."
        )
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS articles (
                    id BIGSERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    publication TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    author TEXT,
                    published_date DATE,
                    topic TEXT,
                    summary TEXT,
                    why_recommended TEXT,
                    reading_time INTEGER,
                    discovered_date TIMESTAMPTZ DEFAULT NOW(),
                    recommendation_score INTEGER DEFAULT 0
                )
                """
            )
            cur.execute(
                """
                ALTER TABLE articles
                ADD COLUMN IF NOT EXISTS recommendation_score INTEGER DEFAULT 0
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS activity (
                    id BIGSERIAL PRIMARY KEY,
                    article_id BIGINT NOT NULL
                        REFERENCES articles(id)
                        ON DELETE CASCADE,
                    action TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )


def seed_test_article() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO articles (
                    title, publication, url, author, topic, summary,
                    why_recommended, reading_time, recommendation_score
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (url) DO NOTHING
                """,
                (
                    "Welcome to My Marketing Brief",
                    "My Marketing Brief",
                    "https://hbr.org/",
                    "My Marketing Brief",
                    "Strategy / Career",
                    "A test recommendation for the cloud deployment.",
                    "This confirms that Telegram, Railway, and Postgres are connected correctly.",
                    5,
                    -100,
                ),
            )


def upsert_article(article: dict) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO articles (
                    title, publication, url, author, published_date,
                    topic, summary, why_recommended, reading_time,
                    recommendation_score
                )
                VALUES (
                    %(title)s, %(publication)s, %(url)s, %(author)s,
                    %(published_date)s, %(topic)s, %(summary)s,
                    %(why_recommended)s, %(reading_time)s,
                    %(recommendation_score)s
                )
                ON CONFLICT (url) DO NOTHING
                RETURNING id
                """,
                article,
            )
            return cur.fetchone() is not None


def get_today_article():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM articles
                ORDER BY
                    recommendation_score DESC,
                    discovered_date DESC,
                    id DESC
                LIMIT 1
                """
            )
            return cur.fetchone()
