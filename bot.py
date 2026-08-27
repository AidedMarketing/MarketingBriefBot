import asyncio
import os
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from database import (
    get_article,
    get_history,
    get_preference_summary,
    get_saved_articles,
    get_today_article,
    init_db,
    record_activity,
    seed_test_article,
)
from sources import refresh_sources

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


def article_keyboard(article: dict) -> InlineKeyboardMarkup:
    article_id = article["id"]
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📖 Read Article", url=article["url"])],
            [
                InlineKeyboardButton("🔖 Save", callback_data=f"save:{article_id}"),
                InlineKeyboardButton("👍 More Like This", callback_data=f"like:{article_id}"),
            ],
            [
                InlineKeyboardButton("👎 Less Like This", callback_data=f"dislike:{article_id}"),
                InlineKeyboardButton("💬 Discuss", callback_data=f"discuss:{article_id}"),
            ],
        ]
    )


def format_article(article: dict, heading: str = "Today's Recommended Read") -> str:
    return (
        f"📖 <b>{escape(heading)}</b>\n\n"
        f"<b>{escape(article['title'])}</b>\n"
        f"{escape(article['publication'])}\n\n"
        "🎯 <b>Why I picked this:</b>\n"
        f"{escape(article['why_recommended'])}\n\n"
        f"🏷 {escape(article['topic'])}\n"
        f"⏱ ~{article['reading_time']} min read"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📚 Welcome to My Marketing Brief.\n\n"
        "Your curated professional reading assistant for:\n"
        "• Harvard Business Review\n"
        "• Marketing Brew\n"
        "• MIT Sloan Management Review\n\n"
        "Commands:\n"
        "/today — Get your next recommended read\n"
        "/saved — View saved articles\n"
        "/history — View recent recommendations\n"
        "/topics — See what The Brief is learning\n"
        "/refresh — Check sources for new articles\n"
        "/help — View commands"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📖 My Marketing Brief Commands\n\n"
        "/today — Your next recommendation\n"
        "/saved — Saved reading list\n"
        "/history — Recent recommendation history\n"
        "/topics — Your emerging topic preferences\n"
        "/refresh — Discover new articles now\n"
        "/help — Show this menu\n\n"
        "The Brief now balances publications, favors fresher discoveries, and uses your 👍/👎 feedback to personalize the queue."
    )


async def refresh_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = await update.message.reply_text("🔎 Checking the publications now…")
    result = await asyncio.to_thread(refresh_sources)
    await message.edit_text(
        "✅ Refresh complete.\n\n"
        f"Found {result['found']} article candidates.\n"
        f"Added {result['added']} new articles.\n"
        "Updated the recommendation metadata for existing articles too.\n\n"
        "Send /today for your next recommendation."
    )


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    await asyncio.to_thread(refresh_sources, False)
    article = get_today_article(user_id)

    if not article:
        await update.message.reply_text(
            "You've reached the end of the current recommendation queue. "
            "Try /refresh and then /today again."
        )
        return

    record_activity(article["id"], "delivered", user_id)

    await update.message.reply_text(
        format_article(article),
        parse_mode="HTML",
        reply_markup=article_keyboard(article),
    )


async def saved(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    articles = get_saved_articles(update.effective_user.id, limit=10)
    if not articles:
        await update.message.reply_text("🔖 You haven't saved any articles yet.")
        return

    lines = ["🔖 <b>Your Saved Reading</b>\n"]
    for index, article in enumerate(articles, start=1):
        lines.append(
            f'{index}. <a href="{escape(article["url"], quote=True)}">'
            f'{escape(article["title"])}</a>\n'
            f'   {escape(article["publication"])} · {escape(article["topic"])}'
        )

    await update.message.reply_text(
        "\n\n".join(lines),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    articles = get_history(update.effective_user.id, limit=10)
    if not articles:
        await update.message.reply_text("📚 No recommendation history yet.")
        return

    lines = ["📚 <b>Recent Recommendations</b>\n"]
    for index, article in enumerate(articles, start=1):
        lines.append(
            f'{index}. <a href="{escape(article["url"], quote=True)}">'
            f'{escape(article["title"])}</a>\n'
            f'   {escape(article["publication"])} · {escape(article["topic"])}'
        )

    await update.message.reply_text(
        "\n\n".join(lines),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def topics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rows = get_preference_summary(update.effective_user.id)
    if not rows:
        await update.message.reply_text(
            "🧭 I don't have enough preference data yet.\n\n"
            "Use 👍 More Like This and 👎 Less Like This on a few recommendations, "
            "then come back to /topics."
        )
        return

    lines = ["🧭 <b>What The Brief Is Learning</b>\n"]
    for row in rows:
        net = row["likes"] - row["dislikes"]
        signal = "↑" if net > 0 else "↓" if net < 0 else "→"
        lines.append(
            f'{signal} <b>{escape(row["topic"])}</b> — '
            f'{row["likes"]} 👍 · {row["dislikes"]} 👎'
        )

    lines.append(
        "\nThese signals influence future recommendations, but publication diversity "
        "is still protected so your feed does not become an echo chamber."
    )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def article_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    action, article_id_text = query.data.split(":", 1)
    article_id = int(article_id_text)
    user_id = update.effective_user.id
    article = get_article(article_id)

    if not article:
        await query.answer("Article not found.", show_alert=True)
        return

    if action == "save":
        record_activity(article_id, "saved", user_id, dedupe=True)
        await query.answer("Saved to your reading list 🔖")
        return

    if action == "like":
        record_activity(article_id, "liked", user_id, dedupe=True)
        await query.answer("Got it — more like this 👍")
        return

    if action == "dislike":
        record_activity(article_id, "disliked", user_id, dedupe=True)
        await query.answer("Got it — I'll weight this down 👎")
        return

    if action == "discuss":
        record_activity(article_id, "discussed", user_id, dedupe=True)
        await query.answer()
        await query.message.reply_text(
            "💬 <b>Discussion Room</b>\n\n"
            f"<b>{escape(article['title'])}</b>\n\n"
            "After you read it, send me what stood out — even a single sentence.\n\n"
            "1️⃣ What's the main argument in your own words?\n"
            "2️⃣ What do you agree or disagree with?\n"
            "3️⃣ Where could this apply to marketing, business, or your work?\n\n"
            "AI-guided discussion is the next dedicated release.",
            parse_mode="HTML",
        )


def main() -> None:
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured.")

    init_db()
    seed_test_article()

    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("today", today))
    application.add_handler(CommandHandler("saved", saved))
    application.add_handler(CommandHandler("history", history))
    application.add_handler(CommandHandler("topics", topics))
    application.add_handler(CommandHandler("refresh", refresh_command))
    application.add_handler(CallbackQueryHandler(article_action))

    print("My Marketing Brief v0.4 is running...", flush=True)
    application.run_polling()


if __name__ == "__main__":
    main()
