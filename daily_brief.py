from html import escape

from database import get_connection


def get_today_article(user_id: int):
    """Select today's article using durable learning memory plus recency/balance signals.

    The scoring model is intentionally explainable: interest, engagement, coverage gaps,
    freshness, and recent topic/publication repetition each have a visible contribution.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
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
                    LEFT JOIN article_contents c ON c.article_id=a.id
                    LEFT JOIN topic_memory tm ON tm.topic=a.topic
                    LEFT JOIN recent_publications rp ON rp.publication=a.publication
                    LEFT JOIN recent_topics rt ON rt.topic=a.topic
                    CROSS JOIN memory_summary ms
                    WHERE NOT EXISTS (
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

    if not row:
        return None

    article = dict(row)
    article.update(_daily_brief_frame(article))
    return article


def _daily_brief_frame(article: dict) -> dict:
    exposure = int(article.get("topic_exposure") or 0)
    engaged = int(article.get("topic_engaged") or 0)
    likes = int(article.get("topic_likes") or 0)
    dislikes = int(article.get("topic_dislikes") or 0)
    max_exposure = int(article.get("max_topic_exposure") or 0)
    recent_topic = int(article.get("recent_topic_count") or 0)
    recent_pub = int(article.get("recent_pub_count") or 0)
    topic = article.get("topic") or "this topic"

    if max_exposure >= 2 and exposure == 0:
        reason = f"You've built momentum in other areas, so today's read broadens the mix with {topic}."
        mode = "Broaden"
    elif likes > dislikes and engaged > 0 and recent_topic < 2:
        reason = f"You've engaged positively with {topic}; this continues that thread without overloading it."
        mode = "Deepen"
    elif recent_pub >= 2:
        reason = "I'm rotating the source mix while keeping the recommendation aligned with your learning history."
        mode = "Balance"
    elif recent_topic >= 2:
        reason = f"You've seen {topic} recently, but this still earned today's spot on relevance and freshness."
        mode = "Revisit"
    else:
        reason = "This is the strongest current fit across relevance, freshness, and your developing reading pattern."
        mode = "Explore"

    objective = f"Read for one idea in {topic} that changes, sharpens, or challenges how you would approach real work."
    return {
        "daily_reason": reason,
        "learning_objective": objective,
        "reading_mode": mode,
    }


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
        f"{escape(mode)} · {escape(article['topic'])}\n"
        f"⏱ ~{article['reading_time']} min read\n"
        f"{escape(content_label_fn(article))}"
    )
