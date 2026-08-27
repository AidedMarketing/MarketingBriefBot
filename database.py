import os

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL")


def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured.")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db() -> None:
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
                    discovered_date TIMESTAMPTZ DEFAULT NOW(),
                    recommendation_score INTEGER DEFAULT 0
                )
            """)
            cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS recommendation_score INTEGER DEFAULT 0")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS activity (
                    id BIGSERIAL PRIMARY KEY,
                    article_id BIGINT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
                    action TEXT NOT NULL,
                    user_id BIGINT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("ALTER TABLE activity ADD COLUMN IF NOT EXISTS user_id BIGINT")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_activity_user_action ON activity(user_id, action)")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS discussion_sessions (
                    user_id BIGINT PRIMARY KEY,
                    article_id BIGINT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS discussion_messages (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    article_id BIGINT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK (role IN ('user','assistant')),
                    content TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS learning_notes (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    article_id BIGINT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
                    note TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)


def seed_test_article() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO articles (
                    title, publication, url, author, topic, summary,
                    why_recommended, reading_time, recommendation_score
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (url) DO NOTHING
            """, (
                "Welcome to My Marketing Brief","My Marketing Brief","https://hbr.org/",
                "My Marketing Brief","Strategy / Career",
                "A test recommendation for the cloud deployment.",
                "This confirms that Telegram, Railway, and Postgres are connected correctly.",5,-100
            ))


def upsert_article(article: dict) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE articles SET
                    title=%(title)s, publication=%(publication)s,
                    author=COALESCE(%(author)s, author),
                    published_date=COALESCE(%(published_date)s, published_date),
                    topic=%(topic)s, summary=%(summary)s,
                    why_recommended=%(why_recommended)s,
                    reading_time=%(reading_time)s,
                    recommendation_score=%(recommendation_score)s
                WHERE url=%(url)s
                RETURNING id
            """, article)
            if cur.fetchone():
                return False
            cur.execute("""
                INSERT INTO articles (
                    title, publication, url, author, published_date, topic,
                    summary, why_recommended, reading_time, recommendation_score
                )
                VALUES (
                    %(title)s,%(publication)s,%(url)s,%(author)s,%(published_date)s,%(topic)s,
                    %(summary)s,%(why_recommended)s,%(reading_time)s,%(recommendation_score)s
                )
                RETURNING id
            """, article)
            return cur.fetchone() is not None


def record_activity(article_id: int, action: str, user_id: int, dedupe: bool = False) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            if dedupe:
                cur.execute("""
                    SELECT 1 FROM activity
                    WHERE article_id=%s AND action=%s AND user_id=%s LIMIT 1
                """, (article_id, action, user_id))
                if cur.fetchone():
                    return
            cur.execute("INSERT INTO activity (article_id, action, user_id) VALUES (%s,%s,%s)",
                        (article_id, action, user_id))


def get_article(article_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM articles WHERE id=%s", (article_id,))
            return cur.fetchone()


def get_today_article(user_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                WITH topic_preferences AS (
                    SELECT a.topic,
                        COALESCE(SUM(CASE WHEN act.action='liked' THEN 12
                                          WHEN act.action='disliked' THEN -12 ELSE 0 END),0) AS topic_boost
                    FROM articles a JOIN activity act ON act.article_id=a.id
                    WHERE act.user_id=%s GROUP BY a.topic
                ),
                recent_deliveries AS (
                    SELECT publication, COUNT(*) AS recent_count FROM (
                        SELECT a.publication
                        FROM activity act JOIN articles a ON a.id=act.article_id
                        WHERE act.user_id=%s AND act.action='delivered'
                        ORDER BY act.created_at DESC LIMIT 6
                    ) recent GROUP BY publication
                )
                SELECT a.*,
                    (a.recommendation_score + COALESCE(tp.topic_boost,0)
                     - COALESCE(rd.recent_count,0)*14
                     + CASE WHEN a.discovered_date > NOW()-INTERVAL '2 days' THEN 8
                            WHEN a.discovered_date > NOW()-INTERVAL '7 days' THEN 4 ELSE 0 END
                    ) AS personalized_score
                FROM articles a
                LEFT JOIN topic_preferences tp ON tp.topic=a.topic
                LEFT JOIN recent_deliveries rd ON rd.publication=a.publication
                WHERE NOT EXISTS (
                    SELECT 1 FROM activity seen
                    WHERE seen.article_id=a.id AND seen.user_id=%s AND seen.action='delivered'
                )
                ORDER BY personalized_score DESC, a.discovered_date DESC, a.id DESC
                LIMIT 1
            """, (user_id, user_id, user_id))
            return cur.fetchone()


def get_saved_articles(user_id: int, limit: int = 10):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT ON (a.id) a.*
                FROM articles a JOIN activity act ON act.article_id=a.id
                WHERE act.user_id=%s AND act.action='saved'
                ORDER BY a.id, act.created_at DESC
            """, (user_id,))
            rows=cur.fetchall()
            return list(reversed(rows[-limit:]))


def get_history(user_id: int, limit: int = 10):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT ON (a.id) a.*, act.created_at AS delivered_at
                FROM articles a JOIN activity act ON act.article_id=a.id
                WHERE act.user_id=%s AND act.action='delivered'
                ORDER BY a.id, act.created_at DESC
            """, (user_id,))
            rows=cur.fetchall()
            rows.sort(key=lambda r:r["delivered_at"], reverse=True)
            return rows[:limit]


def get_preference_summary(user_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.topic,
                    SUM(CASE WHEN act.action='liked' THEN 1 ELSE 0 END) AS likes,
                    SUM(CASE WHEN act.action='disliked' THEN 1 ELSE 0 END) AS dislikes
                FROM activity act JOIN articles a ON a.id=act.article_id
                WHERE act.user_id=%s AND act.action IN ('liked','disliked')
                GROUP BY a.topic
                ORDER BY (SUM(CASE WHEN act.action='liked' THEN 1 ELSE 0 END)
                         - SUM(CASE WHEN act.action='disliked' THEN 1 ELSE 0 END)) DESC, a.topic
            """,(user_id,))
            return cur.fetchall()


def start_discussion(user_id: int, article_id: int) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO discussion_sessions (user_id, article_id, active, updated_at)
                VALUES (%s,%s,TRUE,NOW())
                ON CONFLICT (user_id) DO UPDATE
                SET article_id=EXCLUDED.article_id, active=TRUE, updated_at=NOW()
            """,(user_id,article_id))


def end_discussion(user_id: int) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE discussion_sessions SET active=FALSE, updated_at=NOW() WHERE user_id=%s",(user_id,))


def get_active_discussion(user_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ds.*, a.* FROM discussion_sessions ds
                JOIN articles a ON a.id=ds.article_id
                WHERE ds.user_id=%s AND ds.active=TRUE
            """,(user_id,))
            return cur.fetchone()


def add_discussion_message(user_id: int, article_id: int, role: str, content: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO discussion_messages (user_id, article_id, role, content)
                VALUES (%s,%s,%s,%s)
            """,(user_id,article_id,role,content))
            cur.execute("UPDATE discussion_sessions SET updated_at=NOW() WHERE user_id=%s",(user_id,))


def get_discussion_history(user_id: int, article_id: int, limit: int = 12):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT role, content FROM discussion_messages
                WHERE user_id=%s AND article_id=%s
                ORDER BY created_at DESC LIMIT %s
            """,(user_id,article_id,limit))
            return list(reversed(cur.fetchall()))


def save_learning_note(user_id: int, article_id: int, note: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO learning_notes (user_id, article_id, note)
                VALUES (%s,%s,%s)
            """,(user_id,article_id,note))


def get_learning_notes(user_id: int, limit: int = 10):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ln.note, ln.created_at, a.title, a.publication
                FROM learning_notes ln JOIN articles a ON a.id=ln.article_id
                WHERE ln.user_id=%s
                ORDER BY ln.created_at DESC LIMIT %s
            """,(user_id,limit))
            return cur.fetchall()
