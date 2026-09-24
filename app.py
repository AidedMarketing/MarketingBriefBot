import asyncio
import logging
import time

import bot
from daily_brief import format_article as format_daily_article
from daily_brief import get_today_article as get_daily_article

logger = logging.getLogger(__name__)

_REFRESH_COOLDOWN_SECONDS = 300
_last_refresh_started = 0.0
_refresh_task = None
_enriching_article_ids = set()


def _schedule_source_refresh():
    """Refresh publication discovery in the background, coalescing /today calls."""
    global _last_refresh_started, _refresh_task
    now = time.monotonic()
    if _refresh_task is not None and not _refresh_task.done():
        return
    if now - _last_refresh_started < _REFRESH_COOLDOWN_SECONDS:
        return

    _last_refresh_started = now

    async def refresh():
        started = time.monotonic()
        try:
            result = await asyncio.to_thread(bot.refresh_sources, False)
            logger.info(
                "Background source refresh completed",
                extra={
                    "duration_ms": round((time.monotonic() - started) * 1000),
                    "found_count": result.get("found") if isinstance(result, dict) else None,
                    "added_count": result.get("added") if isinstance(result, dict) else None,
                },
            )
        except Exception:
            logger.exception("Background source refresh failed")

    _refresh_task = asyncio.create_task(refresh())


def _schedule_article_enrichment(article: dict):
    """Enrich a selected article without holding up its recommendation card."""
    article_id = article.get("id")
    if article_id is None or article_id in _enriching_article_ids:
        return

    _enriching_article_ids.add(article_id)

    async def enrich():
        started = time.monotonic()
        try:
            await asyncio.to_thread(bot.enrich_article, article)
            logger.info(
                "Background article enrichment completed",
                extra={
                    "article_id": article_id,
                    "duration_ms": round((time.monotonic() - started) * 1000),
                },
            )
        except Exception:
            logger.exception("Background enrichment failed for article %s", article_id)
        finally:
            _enriching_article_ids.discard(article_id)

    asyncio.create_task(enrich())


def _format_article(article: dict, heading: str = "Today's Brief") -> str:
    return format_daily_article(article, bot.content_label, heading)


async def daily_today(update, context, force_new=False):
    uid = update.effective_user.id
    started = time.monotonic()

    # Return the persisted daily card promptly; source discovery is opportunistic.
    _schedule_source_refresh()
    article = await asyncio.to_thread(get_daily_article, uid, force_new)
    if not article:
        await update.message.reply_text("You've reached the end of the current queue. Try /refresh.")
        return

    if (article.get("content_status") or "metadata_only") != "full":
        _schedule_article_enrichment(article)

    article = await asyncio.to_thread(bot.attach_reader_context, article, uid)
    await update.message.reply_text(
        _format_article(article),
        parse_mode="HTML",
        reply_markup=bot.article_keyboard(article),
    )
    logger.info(
        "Daily recommendation card sent",
        extra={
            "article_id": article["id"],
            "force_new": force_new,
            "duration_ms": round((time.monotonic() - started) * 1000),
        },
    )
    # A delivered /today card becomes the active discussion so a direct reply
    # naturally stays grounded in the article the user just received.
    try:
        await asyncio.to_thread(bot.start_discussion, uid, article["id"])
    except Exception:
        logger.exception("Could not activate discussion for article %s", article["id"])
    await asyncio.to_thread(bot.record_activity, article["id"], "delivered", uid, True)


async def daily_next(update, context):
    await daily_today(update, context, force_new=True)


# Replace only the recommendation surface. Article handling, discussion, memory,
# imports, and the rest of Telegram remain untouched.
bot.today = daily_today
bot.next_today = daily_next
bot.format_article = _format_article


if __name__ == "__main__":
    print("My Marketing Brief v1.0 Daily Brief is starting...", flush=True)
    bot.main()
