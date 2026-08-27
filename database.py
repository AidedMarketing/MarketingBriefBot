import hashlib
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
                CREATE TABLE IF NOT EXISTS article_contents (
                    article_id BIGINT PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
                    source_type TEXT NOT NULL DEFAULT 'public_web',
                    content_status TEXT NOT NULL DEFAULT 'metadata_only',
                    plain_text TEXT NOT NULL DEFAULT '',
                    meta_description TEXT NOT NULL DEFAULT '',
                    word_count INTEGER NOT NULL DEFAULT 0,
                    content_hash TEXT,
                    fetched_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS reader_excerpts (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    article_id BIGINT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
                    excerpt_text TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(user_id, article_id, content_hash)
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_reader_excerpts_user_article
                ON reader_excerpts(user_id, article_id, created_at)
            """)

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

            cur.execute("""
                CREATE TABLE IF NOT EXISTS learning_memory (
                    user_id BIGINT NOT NULL,
                    article_id BIGINT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
                    topic TEXT,
                    publication TEXT,
                    delivered_count INTEGER NOT NULL DEFAULT 0,
                    discussed BOOLEAN NOT NULL DEFAULT FALSE,
                    liked BOOLEAN,
                    saved BOOLEAN NOT NULL DEFAULT FALSE,
                    reading_lens_used BOOLEAN NOT NULL DEFAULT FALSE,
                    key_ideas_used BOOLEAN NOT NULL DEFAULT FALSE,
                    apply_used BOOLEAN NOT NULL DEFAULT FALSE,
                    challenge_used BOOLEAN NOT NULL DEFAULT FALSE,
                    note_saved BOOLEAN NOT NULL DEFAULT FALSE,
                    discussion_turns INTEGER NOT NULL DEFAULT 0,
                    last_engaged_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (user_id, article_id)
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_learning_memory_user_engaged
                ON learning_memory(user_id, last_engaged_at DESC)
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS import_sessions (
                    user_id BIGINT PRIMARY KEY,
                    article_id BIGINT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
                    buffer_text TEXT NOT NULL DEFAULT '',
                    source_type TEXT NOT NULL DEFAULT 'user_paste',
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
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
                "Welcome to My Marketing Brief", "My Marketing Brief", "https://hbr.org/",
                "My Marketing Brief", "Strategy / Career",
                "A test recommendation for the cloud deployment.",
                "This confirms that Telegram, Railway, and Postgres are connected correctly.",
                5, -100
            ))


def upsert_article(article: dict) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE articles SET
                    title=%(title)s,
                    publication=%(publication)s,
                    author=COALESCE(%(author)s, author),
                    published_date=COALESCE(%(published_date)s, published_date),
                    topic=%(topic)s,
                    summary=%(summary)s,
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


def batch_upsert_articles(articles: list[dict]) -> int:
    if not articles:
        return 0

    urls = [article["url"] for article in articles]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT url FROM articles WHERE url = ANY(%s)",
                (urls,),
            )
            existing = {row["url"] for row in cur.fetchall()}

            cur.executemany(
                """
                INSERT INTO articles (
                    title, publication, url, author, published_date, topic,
                    summary, why_recommended, reading_time, recommendation_score
                )
                VALUES (
                    %(title)s,%(publication)s,%(url)s,%(author)s,%(published_date)s,%(topic)s,
                    %(summary)s,%(why_recommended)s,%(reading_time)s,%(recommendation_score)s
                )
                ON CONFLICT (url) DO UPDATE SET
                    title=EXCLUDED.title,
                    publication=EXCLUDED.publication,
                    author=COALESCE(EXCLUDED.author, articles.author),
                    published_date=COALESCE(EXCLUDED.published_date, articles.published_date),
                    topic=EXCLUDED.topic,
                    summary=CASE
                        WHEN EXCLUDED.summary <> '' THEN EXCLUDED.summary
                        ELSE articles.summary
                    END,
                    why_recommended=EXCLUDED.why_recommended,
                    reading_time=EXCLUDED.reading_time,
                    recommendation_score=EXCLUDED.recommendation_score
                """,
                articles,
            )

    return sum(1 for url in urls if url not in existing)


def find_article_by_url(url: str):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.*, c.content_status, c.source_type, c.word_count,
                       c.meta_description, c.plain_text
                FROM articles a
                LEFT JOIN article_contents c ON c.article_id=a.id
                WHERE a.url=%s
            """, (url,))
            return cur.fetchone()


def save_article_content(
    url: str,
    source_type: str,
    content_status: str,
    plain_text: str,
    meta_description: str = "",
    word_count: int = 0,
    content_hash: str | None = None,
) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM articles WHERE url=%s", (url,))
            row = cur.fetchone()
            if not row:
                return
            cur.execute("""
                INSERT INTO article_contents (
                    article_id, source_type, content_status, plain_text,
                    meta_description, word_count, content_hash, fetched_at
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (article_id) DO UPDATE SET
                    source_type=EXCLUDED.source_type,
                    content_status=EXCLUDED.content_status,
                    plain_text=EXCLUDED.plain_text,
                    meta_description=EXCLUDED.meta_description,
                    word_count=EXCLUDED.word_count,
                    content_hash=EXCLUDED.content_hash,
                    fetched_at=NOW()
            """, (
                row["id"], source_type, content_status, plain_text,
                meta_description, word_count, content_hash
            ))


def update_learning_memory(user_id: int, article_id: int, action: str) -> None:
    field_map = {
        "delivered": "delivered_count",
        "discussed": "discussed",
        "liked": "liked",
        "disliked": "liked",
        "saved": "saved",
        "reading_lens": "reading_lens_used",
        "learn_keyideas": "key_ideas_used",
        "learn_apply": "apply_used",
        "learn_challenge": "challenge_used",
        "note_saved": "note_saved",
        "discussion_turn": "discussion_turns",
    }
    field = field_map.get(action)
    if not field:
        return

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT topic, publication FROM articles WHERE id=%s", (article_id,))
            article = cur.fetchone()
            if not article:
                return

            cur.execute(
                """
                INSERT INTO learning_memory (user_id, article_id, topic, publication)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (user_id, article_id) DO UPDATE
                SET topic=EXCLUDED.topic,
                    publication=EXCLUDED.publication,
                    last_engaged_at=NOW()
                """,
                (user_id, article_id, article["topic"], article["publication"]),
            )

            if field in ("delivered_count", "discussion_turns"):
                cur.execute(
                    f"UPDATE learning_memory SET {field}={field}+1, last_engaged_at=NOW() WHERE user_id=%s AND article_id=%s",
                    (user_id, article_id),
                )
            elif action == "liked":
                cur.execute(
                    "UPDATE learning_memory SET liked=TRUE, last_engaged_at=NOW() WHERE user_id=%s AND article_id=%s",
                    (user_id, article_id),
                )
            elif action == "disliked":
                cur.execute(
                    "UPDATE learning_memory SET liked=FALSE, last_engaged_at=NOW() WHERE user_id=%s AND article_id=%s",
                    (user_id, article_id),
                )
            else:
                cur.execute(
                    f"UPDATE learning_memory SET {field}=TRUE, last_engaged_at=NOW() WHERE user_id=%s AND article_id=%s",
                    (user_id, article_id),
                )


def get_learning_profile(user_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) AS articles_seen,
                    COUNT(*) FILTER (WHERE discussed) AS articles_discussed,
                    COUNT(*) FILTER (WHERE note_saved) AS notes_saved,
                    COUNT(*) FILTER (WHERE challenge_used) AS challenges_used,
                    COALESCE(SUM(discussion_turns),0) AS discussion_turns
                FROM learning_memory
                WHERE user_id=%s
                """,
                (user_id,),
            )
            totals = cur.fetchone()

            cur.execute(
                """
                SELECT topic,
                    COUNT(*) AS exposure,
                    COUNT(*) FILTER (WHERE discussed OR note_saved OR challenge_used OR apply_used) AS engaged,
                    COUNT(*) FILTER (WHERE liked=TRUE) AS likes,
                    COUNT(*) FILTER (WHERE liked=FALSE) AS dislikes
                FROM learning_memory
                WHERE user_id=%s AND topic IS NOT NULL
                GROUP BY topic
                ORDER BY engaged DESC, exposure DESC, topic
                """,
                (user_id,),
            )
            topics = cur.fetchall()

            cur.execute(
                """
                SELECT publication, COUNT(*) AS exposure
                FROM learning_memory
                WHERE user_id=%s AND publication IS NOT NULL
                GROUP BY publication
                ORDER BY exposure DESC
                """,
                (user_id,),
            )
            publications = cur.fetchall()

    return {"totals": totals, "topics": topics, "publications": publications}


def learning_memory_context(user_id: int) -> str:
    profile = get_learning_profile(user_id)
    totals = profile["totals"] or {}
    topic_rows = profile["topics"][:10]
    pub_rows = profile["publications"][:6]

    topic_text = "; ".join(
        f"{r['topic']}: seen {r['exposure']}, engaged {r['engaged']}, likes {r['likes']}, dislikes {r['dislikes']}"
        for r in topic_rows
    ) or "No topic history yet"

    pub_text = "; ".join(
        f"{r['publication']}: {r['exposure']}"
        for r in pub_rows
    ) or "No publication history yet"

    return (
        f"Articles seen: {totals.get('articles_seen', 0)}; "
        f"discussed: {totals.get('articles_discussed', 0)}; "
        f"notes: {totals.get('notes_saved', 0)}; "
        f"challenges: {totals.get('challenges_used', 0)}; "
        f"discussion turns: {totals.get('discussion_turns', 0)}. "
        f"Topic history: {topic_text}. Publication history: {pub_text}."
    )


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
            cur.execute(
                "INSERT INTO activity (article_id, action, user_id) VALUES (%s,%s,%s)",
                (article_id, action, user_id)
            )

    update_learning_memory(user_id, article_id, action)


def get_article(article_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.*, c.content_status, c.source_type, c.word_count,
                       c.meta_description, c.plain_text
                FROM articles a
                LEFT JOIN article_contents c ON c.article_id=a.id
                WHERE a.id=%s
            """, (article_id,))
            return cur.fetchone()


def get_today_article(user_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                WITH topic_preferences AS (
                    SELECT a.topic,
                        COALESCE(SUM(
                            CASE
                                WHEN act.action='liked' THEN 12
                                WHEN act.action='disliked' THEN -12
                                ELSE 0
                            END
                        ),0) AS topic_boost
                    FROM articles a
                    JOIN activity act ON act.article_id=a.id
                    WHERE act.user_id=%s
                    GROUP BY a.topic
                ),
                recent_deliveries AS (
                    SELECT publication, COUNT(*) AS recent_count
                    FROM (
                        SELECT a.publication
                        FROM activity act
                        JOIN articles a ON a.id=act.article_id
                        WHERE act.user_id=%s AND act.action='delivered'
                        ORDER BY act.created_at DESC
                        LIMIT 6
                    ) recent
                    GROUP BY publication
                )
                SELECT a.*, c.content_status, c.source_type, c.word_count,
                       c.meta_description, c.plain_text,
                    (
                        a.recommendation_score
                        + COALESCE(tp.topic_boost,0)
                        - COALESCE(rd.recent_count,0)*14
                        + CASE
                            WHEN a.discovered_date > NOW()-INTERVAL '2 days' THEN 8
                            WHEN a.discovered_date > NOW()-INTERVAL '7 days' THEN 4
                            ELSE 0
                          END
                    ) AS personalized_score
                FROM articles a
                LEFT JOIN article_contents c ON c.article_id=a.id
                LEFT JOIN topic_preferences tp ON tp.topic=a.topic
                LEFT JOIN recent_deliveries rd ON rd.publication=a.publication
                WHERE NOT EXISTS (
                    SELECT 1 FROM activity seen
                    WHERE seen.article_id=a.id
                      AND seen.user_id=%s
                      AND seen.action='delivered'
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
                FROM articles a
                JOIN activity act ON act.article_id=a.id
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
                FROM articles a
                JOIN activity act ON act.article_id=a.id
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
                FROM activity act
                JOIN articles a ON a.id=act.article_id
                WHERE act.user_id=%s AND act.action IN ('liked','disliked')
                GROUP BY a.topic
                ORDER BY (
                    SUM(CASE WHEN act.action='liked' THEN 1 ELSE 0 END)
                    - SUM(CASE WHEN act.action='disliked' THEN 1 ELSE 0 END)
                ) DESC, a.topic
            """,(user_id,))
            return cur.fetchall()


def add_reader_excerpt(user_id: int, article_id: int, excerpt_text: str) -> bool:
    text = (excerpt_text or "").strip()
    if not text:
        return False

    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO reader_excerpts (
                    user_id, article_id, excerpt_text, content_hash
                )
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (user_id, article_id, content_hash) DO NOTHING
                RETURNING id
                """,
                (user_id, article_id, text, content_hash),
            )
            return cur.fetchone() is not None


def get_reader_excerpts(user_id: int, article_id: int, limit: int = 8):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT excerpt_text, created_at
                FROM reader_excerpts
                WHERE user_id=%s AND article_id=%s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (user_id, article_id, limit),
            )
            return list(reversed(cur.fetchall()))


def get_reader_excerpt_count(user_id: int, article_id: int) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS count
                FROM reader_excerpts
                WHERE user_id=%s AND article_id=%s
                """,
                (user_id, article_id),
            )
            row = cur.fetchone()
            return int(row["count"]) if row else 0


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
            cur.execute(
                "UPDATE discussion_sessions SET active=FALSE, updated_at=NOW() WHERE user_id=%s",
                (user_id,)
            )


def get_active_discussion(user_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.*, c.content_status, c.source_type, c.word_count,
                       c.meta_description, c.plain_text
                FROM discussion_sessions ds
                JOIN articles a ON a.id=ds.article_id
                LEFT JOIN article_contents c ON c.article_id=a.id
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
            cur.execute(
                "UPDATE discussion_sessions SET updated_at=NOW() WHERE user_id=%s",
                (user_id,)
            )


def get_discussion_history(user_id: int, article_id: int, limit: int = 12):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT role, content
                FROM discussion_messages
                WHERE user_id=%s AND article_id=%s
                ORDER BY created_at DESC
                LIMIT %s
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
                FROM learning_notes ln
                JOIN articles a ON a.id=ln.article_id
                WHERE ln.user_id=%s
                ORDER BY ln.created_at DESC
                LIMIT %s
            """,(user_id,limit))
            return cur.fetchall()


def start_import(user_id: int, article_id: int, source_type: str = "user_paste") -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO import_sessions (user_id, article_id, buffer_text, source_type, active, updated_at)
                VALUES (%s,%s,'',%s,TRUE,NOW())
                ON CONFLICT (user_id) DO UPDATE SET
                    article_id=EXCLUDED.article_id,
                    buffer_text='',
                    source_type=EXCLUDED.source_type,
                    active=TRUE,
                    updated_at=NOW()
            """,(user_id,article_id,source_type))


def get_import_session(user_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT s.*, a.title, a.url, a.publication
                FROM import_sessions s
                JOIN articles a ON a.id=s.article_id
                WHERE s.user_id=%s AND s.active=TRUE
            """,(user_id,))
            return cur.fetchone()


def append_import_text(user_id: int, text: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE import_sessions
                SET buffer_text = CASE
                        WHEN buffer_text='' THEN %s
                        ELSE buffer_text || E'\n\n' || %s
                    END,
                    updated_at=NOW()
                WHERE user_id=%s AND active=TRUE
            """,(text,text,user_id))


def finish_import(user_id: int, source_type: str | None = None):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT s.*, a.url
                FROM import_sessions s
                JOIN articles a ON a.id=s.article_id
                WHERE s.user_id=%s AND s.active=TRUE
            """,(user_id,))
            session=cur.fetchone()
            if not session:
                return None

            text=(session["buffer_text"] or "").strip()
            words=len(text.split())
            status="full" if words >= 350 else "partial" if words >= 40 else "metadata_only"
            actual_source=source_type or session["source_type"]

            cur.execute("""
                INSERT INTO article_contents (
                    article_id, source_type, content_status, plain_text,
                    meta_description, word_count, fetched_at
                )
                VALUES (%s,%s,%s,%s,'',%s,NOW())
                ON CONFLICT (article_id) DO UPDATE SET
                    source_type=EXCLUDED.source_type,
                    content_status=EXCLUDED.content_status,
                    plain_text=EXCLUDED.plain_text,
                    word_count=EXCLUDED.word_count,
                    fetched_at=NOW()
            """,(session["article_id"],actual_source,status,text,words))

            cur.execute(
                "UPDATE import_sessions SET active=FALSE, updated_at=NOW() WHERE user_id=%s",
                (user_id,)
            )

            cur.execute("""
                SELECT a.*, c.content_status, c.source_type, c.word_count,
                       c.meta_description, c.plain_text
                FROM articles a
                LEFT JOIN article_contents c ON c.article_id=a.id
                WHERE a.id=%s
            """,(session["article_id"],))
            return cur.fetchone()


def cancel_import(user_id: int) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE import_sessions SET active=FALSE, updated_at=NOW() WHERE user_id=%s",
                (user_id,)
            )
