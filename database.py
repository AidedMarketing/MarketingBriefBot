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
                    user_id BIGINT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                ALTER TABLE activity
                ADD COLUMN IF NOT EXISTS user_id BIGINT
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_activity_user_action
                ON activity(user_id, action)
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


def record_activity(article_id: int, action: str, user_id: int, dedupe: bool = False) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            if dedupe:
                cur.execute(
                    """
                    SELECT 1
                    FROM activity
                    WHERE article_id = %s
                      AND action = %s
                      AND user_id = %s
                    LIMIT 1
                    """,
                    (article_id, action, user_id),
                )
                if cur.fetchone():
                    return

            cur.execute(
                """
                INSERT INTO activity (article_id, action, user_id)
                VALUES (%s, %s, %s)
                """,
                (article_id, action, user_id),
            )


def get_article(article_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM articles WHERE id = %s", (article_id,))
            return cur.fetchone()


def get_today_article(user_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH preferences AS (
                    SELECT
                        a.topic,
                        COALESCE(SUM(
                            CASE
                                WHEN act.action = 'liked' THEN 12
                                WHEN act.action = 'disliked' THEN -12
                                ELSE 0
                            END
                        ), 0) AS topic_boost
                    FROM articles a
                    JOIN activity act ON act.article_id = a.id
                    WHERE act.user_id = %s
                    GROUP BY a.topic
                )
                SELECT
                    a.*,
                    a.recommendation_score + COALESCE(p.topic_boost, 0)
                        AS personalized_score
                FROM articles a
                LEFT JOIN preferences p ON p.topic = a.topic
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM activity seen
                    WHERE seen.article_id = a.id
                      AND seen.user_id = %s
                      AND seen.action = 'delivered'
                )
                ORDER BY
                    personalized_score DESC,
                    a.discovered_date DESC,
                    a.id DESC
                LIMIT 1
                """,
                (user_id, user_id),
            )
            return cur.fetchone()


def get_saved_articles(user_id: int, limit: int = 10):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (a.id)
                    a.*
                FROM articles a
                JOIN activity act ON act.article_id = a.id
                WHERE act.user_id = %s
                  AND act.action = 'saved'
                ORDER BY a.id, act.created_at DESC
                """,
                (user_id,),
            )
            rows = cur.fetchall()
            return list(reversed(rows[-limit:]))


def get_history(user_id: int, limit: int = 10):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (a.id)
                    a.*, act.created_at AS delivered_at
                FROM articles a
                JOIN activity act ON act.article_id = a.id
                WHERE act.user_id = %s
                  AND act.action = 'delivered'
                ORDER BY a.id, act.created_at DESC
                """,
                (user_id,),
            )
            rows = cur.fetchall()
            rows.sort(key=lambda row: row["delivered_at"], reverse=True)
            return rows[:limit]
