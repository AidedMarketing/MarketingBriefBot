import asyncio
import os
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from database import get_today_article, init_db, seed_test_article
from sources import refresh_sources

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📚 Welcome to My Marketing Brief.\n\n"
        "Your curated professional reading assistant for:\n"
        "• Harvard Business Review\n"
        "• Marketing Brew\n"
        "• MIT Sloan Management Review\n\n"
        "Commands:\n"
        "/today — Get a recommended read\n"
        "/refresh — Check sources for new articles\n"
        "/help — View commands"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📖 My Marketing Brief Commands\n\n"
        "/start — Welcome screen\n"
        "/today — Today's recommended article\n"
        "/refresh — Discover new articles now\n"
        "/help — Show this menu"
    )


async def refresh_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = await update.message.reply_text("🔎 Checking the publications now…")
    result = await asyncio.to_thread(refresh_sources)
    await message.edit_text(
        "✅ Refresh complete.\n\n"
        f"Found {result['found']} article candidates.\n"
        f"Added {result['added']} new articles.\n\n"
        "Send /today for the current recommendation."
    )


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Keep discovery fresh without making every request depend on external sites.
    await asyncio.to_thread(refresh_sources, False)
    article = get_today_article()

    if not article:
        await update.message.reply_text(
            "I don't have a recommendation yet. Try /refresh in a moment."
        )
        return

    message = (
        "📖 <b>Today's Recommended Read</b>\n\n"
        f"<b>{escape(article['title'])}</b>\n"
        f"{escape(article['publication'])}\n\n"
        "🎯 <b>Why I picked this:</b>\n"
        f"{escape(article['why_recommended'])}\n\n"
        f"🏷 {escape(article['topic'])}\n"
        f"⏱ ~{article['reading_time']} min read"
    )

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("📖 Read Article", url=article["url"])]]
    )

    await update.message.reply_text(
        message,
        parse_mode="HTML",
        reply_markup=keyboard,
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
    application.add_handler(CommandHandler("refresh", refresh_command))

    print("My Marketing Brief is running...", flush=True)
    application.run_polling()


if __name__ == "__main__":
    main()
