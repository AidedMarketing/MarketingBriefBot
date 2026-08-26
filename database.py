import os
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL")

def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured. Add Railway Postgres to the project.")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

def init_db():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
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
                    discovered_date TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS activity (
                    id BIGSERIAL PRIMARY KEY,
                    article_id BIGINT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
                    action TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

def seed_test_article():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO articles (
                    title, publication, url, author, topic, summary,
                    why_recommended, reading_time
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (url) DO NOTHING
            """, (
                "Welcome to My Marketing Brief",
                "My Marketing Brief",
                "https://hbr.org/",
                "My Marketing Brief",
                "Strategy / Career",
                "A test recommendation for the cloud deployment.",
                "This confirms that Telegram, Railway, and Postgres are connected correctly.",
                5
            ))

def get_today_article():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM articles ORDER BY id DESC LIMIT 1")
            return cur.fetchone()
