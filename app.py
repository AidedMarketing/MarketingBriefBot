import bot
from daily_brief import format_article as format_daily_article
from daily_brief import get_today_article as get_daily_article


# Keep the Telegram surface compact while replacing the recommendation backend.
bot.get_today_article = get_daily_article


def _format_article(article: dict, heading: str = "Today's Brief") -> str:
    return format_daily_article(article, bot.content_label, heading)


bot.format_article = _format_article


if __name__ == "__main__":
    print("My Marketing Brief v1.0 Daily Brief is starting...", flush=True)
    bot.main()
