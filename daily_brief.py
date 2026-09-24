from html import escape
from datetime import datetime
from zoneinfo import ZoneInfo
from psycopg.types.json import Jsonb

from database import get_connection


def get_today_article(user_id: int, force_new: bool = False):
    """Select today's article using durable learning memory plus recency/balance signals.

    The scoring model is intentionally explainable: interest, engagement, coverage gaps,
    discovery recency, and recent topic/publication repetition each have a visible contribution.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            brief_date = datetime.now(ZoneInfo("America/New_York")).date()
            # Serialize selection for the same user, including concurrent requests.
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (user_id,))
            if not force_new:
                cur.execute("""
                    SELECT a.*, c.content_status, c.source_type, c.word_count,
                           c.meta_description, c.plain_text, d.frame
                    FROM daily_briefs d JOIN articles a ON a.id=d.article_id
                    LEFT JOIN article_contents c ON c.article_id=a.id AND c.source_type='public_web'
                    WHERE d.user_id=%s AND d.brief_date=%s
                """, (user_id, brief_date))
                existing = cur.fetchone()
                if existing:
                    article = dict(existing)
                    article.update(article.pop("frame") or {})
                    # Refresh the user-facing explanation for the cached daily pick.
                    # The article stays stable for the day, while improved copy applies immediately.
                    article.update(_daily_brief_copy(article))
                    return article
            cur.execute(
                """
                WITH topic_memory AS (
                    SELECT
                        topic,
                        COUNT(*) AS exposure,
                        COUNT(*) FILTER (
                            WHERE discussed OR note_saved OR challenge_used OR apply_used
                        ) AS engaged,
                        COUNT(*) FILTER (WHERE liked=TRUE) AS likes,
                        COUNT(*) FILTER (WHERE liked=FALSE) AS dislikes,
                        COALESCE(SUM(discussion_turns), 0) AS discussion_turns
                    FROM learning_memory
                    WHERE user_id=%s AND topic IS NOT NULL
                    GROUP BY topic
                ),
                memory_summary AS (
                    SELECT COALESCE(MAX(exposure), 0) AS max_topic_exposure
                    FROM topic_memory
                ),
                recent AS (
                    SELECT a.publication, a.topic
                    FROM activity act
                    JOIN articles a ON a.id=act.article_id
                    WHERE act.user_id=%s AND act.action='delivered'
                    ORDER BY act.created_at DESC
                    LIMIT 6
                ),
                recent_publications AS (
                    SELECT publication, COUNT(*) AS recent_pub_count
                    FROM recent
                    GROUP BY publication
                ),
                recent_topics AS (
                    SELECT topic, COUNT(*) AS recent_topic_count
                    FROM recent
                    GROUP BY topic
                ),
                candidates AS (
                    SELECT
                        a.*,
                        c.content_status,
                        c.source_type,
                        c.word_count,
                        c.meta_description,
                        c.plain_text,
                        COALESCE(tm.exposure, 0) AS topic_exposure,
                        COALESCE(tm.engaged, 0) AS topic_engaged,
                        COALESCE(tm.likes, 0) AS topic_likes,
                        COALESCE(tm.dislikes, 0) AS topic_dislikes,
                        COALESCE(tm.discussion_turns, 0) AS topic_discussion_turns,
                        COALESCE(rp.recent_pub_count, 0) AS recent_pub_count,
                        COALESCE(rt.recent_topic_count, 0) AS recent_topic_count,
                        ms.max_topic_exposure,
                        (
                            a.recommendation_score
                            + LEAST(COALESCE(tm.engaged, 0) * 4, 16)
                            + LEAST(COALESCE(tm.likes, 0) * 6, 18)
                            - LEAST(COALESCE(tm.dislikes, 0) * 8, 24)
                            + LEAST(COALESCE(tm.discussion_turns, 0), 8)
                            + CASE
                                WHEN ms.max_topic_exposure >= 2 AND COALESCE(tm.exposure, 0)=0 THEN 10
                                WHEN ms.max_topic_exposure >= 4 AND COALESCE(tm.exposure, 0) <= ms.max_topic_exposure-3 THEN 6
                                ELSE 0
                              END
                            - COALESCE(rp.recent_pub_count, 0) * 9
                            - COALESCE(rt.recent_topic_count, 0) * 7
                            + CASE
                                WHEN a.discovered_date > NOW()-INTERVAL '2 days' THEN 10
                                WHEN a.discovered_date > NOW()-INTERVAL '7 days' THEN 5
                                ELSE 0
                              END
                        ) AS personalized_score
                    FROM articles a
                    LEFT JOIN article_contents c ON c.article_id=a.id AND c.source_type='public_web'
                    LEFT JOIN topic_memory tm ON tm.topic=a.topic
                    LEFT JOIN recent_publications rp ON rp.publication=a.publication
                    LEFT JOIN recent_topics rt ON rt.topic=a.topic
                    CROSS JOIN memory_summary ms
                    WHERE a.publication <> 'My Marketing Brief'
                    AND NOT EXISTS (
                        SELECT 1 FROM activity seen
                        WHERE seen.article_id=a.id
                          AND seen.user_id=%s
                          AND seen.action='delivered'
                    )
                )
                SELECT * FROM candidates
                ORDER BY personalized_score DESC, discovered_date DESC, id DESC
                LIMIT 1
                """,
                (user_id, user_id, user_id),
            )
            row = cur.fetchone()
            if row:
                cur.execute("""
                    INSERT INTO daily_briefs (user_id, brief_date, article_id, frame)
                    VALUES (%s,%s,%s,%s)
                    ON CONFLICT (user_id, brief_date) DO UPDATE
                    SET article_id=EXCLUDED.article_id, frame=EXCLUDED.frame
                """, (user_id, brief_date, row["id"], Jsonb(_daily_brief_frame(dict(row)))))

    if not row:
        return None

    article = dict(row)
    article.update(_daily_brief_frame(article))
    return article


def _daily_brief_copy(article: dict) -> dict:
    """Explain the recommendation and give a practical, article-specific reading lens."""
    title = (article.get("title") or "").lower()
    topic = (article.get("topic") or "").strip()
    normalized_topic = topic.lower()

    if any(term in title for term in ("name", "naming", "brand", "position")) or "brand" in normalized_topic:
        reason = (
            "As the EV market shifts, a vehicle name is doing positioning work: "
            "helping buyers understand who the model is for and what sets it apart."
        )
        objective = (
            "Connect the buyer research behind a name to the promise it makes. "
            "Does that promise help the vehicle stand out while still telling buyers what to expect?"
        )
    elif "strateg" in title or "strateg" in normalized_topic:
        reason = (
            "This puts strategy in a real market context, so you can compare the "
            "reasoning with decisions in your own work."
        )
        objective = (
            "Identify the choice being made, what changed around it, and what "
            "evidence would support the same move in your work."
        )
    elif topic:
        reason = (
            f"This makes {topic} concrete through a business choice with practical "
            "consequences you can compare with your own work."
        )
        objective = (
            "Identify the decision being made and the evidence or assumptions behind it. "
            "What would you need to know before applying the same approach at work?"
        )
    else:
        reason = "This is a current business example with a decision worth examining."
        objective = (
            "Look for the main decision or trade-off, what evidence supports it, "
            "and one part you could adapt in your own work."
        )

    return {"daily_reason": reason, "learning_objective": objective}


def _daily_brief_frame(article: dict) -> dict:
    exposure = int(article.get("topic_exposure") or 0)
    engaged = int(article.get("topic_engaged") or 0)
    likes = int(article.get("topic_likes") or 0)
    dislikes = int(article.get("topic_dislikes") or 0)
    max_exposure = int(article.get("max_topic_exposure") or 0)
    recent_topic = int(article.get("recent_topic_count") or 0)

    if max_exposure >= 2 and exposure == 0:
        mode = "Broaden"
    elif likes > dislikes and engaged > 0 and recent_topic < 2:
        mode = "Deepen"
    elif recent_topic >= 2:
        mode = "Revisit"
    else:
        mode = "Explore"

    return {**_daily_brief_copy(article), "reading_mode": mode}



def format_article(article: dict, content_label_fn, heading: str = "Today's Brief") -> str:
    reason = article.get("daily_reason") or article.get("why_recommended") or "Selected for you today."
    objective = article.get("learning_objective") or "Look for one idea worth carrying into your work."
    mode = article.get("reading_mode") or "Explore"

    return (
        f"📖 <b>{escape(heading)}</b>\n\n"
        f"<b>{escape(article['title'])}</b>\n"
        f"{escape(article['publication'])}\n\n"
        f"🎯 <b>Why today:</b>\n{escape(reason)}\n\n"
        f"🧭 <b>Reading focus:</b>\n{escape(objective)}\n\n"
        f"{escape(mode)} · {escape(article.get('topic') or 'General')}\n"
        f"⏱ ~{article['reading_time']} min read\n"
        f"{escape(content_label_fn(article))}"
    )
