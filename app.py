import asyncio

import bot
from daily_brief import format_article as format_daily_article
from daily_brief import get_today_article as get_daily_article


def _format_article(article: dict, heading: str = "Today's Brief") -> str:
    return format_daily_article(article, bot.content_label, heading)


async def daily_today(update, context):
    uid = update.effective_user.id

    # Keep discovery lightweight; only deep-fetch the selected article.
    try:
        await asyncio.wait_for(asyncio.to_thread(bot.refresh_sources, False), timeout=20)
    except asyncio.TimeoutError:
        pass

    article = get_daily_article(uid)
    if not article:
        await update.message.reply_text("You've reached the end of the current queue. Try /refresh.")
        return

    if (article.get("content_status") or "metadata_only") != "full":
        try:
            await asyncio.wait_for(asyncio.to_thread(bot.enrich_article, article), timeout=12)
            fresh = bot.get_article(article["id"])
            if fresh:
                # Refresh content fields without discarding the recommendation explanation.
                article.update(dict(fresh))
        except asyncio.TimeoutError:
            pass

    article = bot.attach_reader_context(article, uid)
    bot.record_activity(article["id"], "delivered", uid)
    await update.message.reply_text(
        _format_article(article),
        parse_mode="HTML",
        reply_markup=bot.article_keyboard(article),
    )


# Replace only the recommendation surface. Article handling, discussion, memory,
# imports, and the rest of Telegram remain untouched.
bot.today = daily_today
bot.format_article = _format_article


if __name__ == "__main__":
    print("My Marketing Brief v1.0 Daily Brief is starting...", flush=True)
    bot.main()
