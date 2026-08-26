import os
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from database import init_db, get_today_article, seed_test_article

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📚 Welcome to My Marketing Brief.\n\n"
        "Your curated professional reading assistant for HBR, Marketing Brew, "
        "and MIT Sloan Management Review.\n\n"
        "/today — Get a recommended read\n"
        "/help — View commands"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📖 My Marketing Brief Commands\n\n"
        "/start — Welcome screen\n"
        "/today — Today's recommended article\n"
        "/help — Show this menu"
    )

async def today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    article = get_today_article()
    if not article:
        await update.message.reply_text("I don't have a recommendation loaded yet.")
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
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 Read Article", url=article["url"])]
    ])
    await update.message.reply_text(message, parse_mode="HTML", reply_markup=keyboard)

def main() -> None:
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured.")
    init_db()
    seed_test_article()
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("today", today))
    print("My Marketing Brief is running...", flush=True)
    application.run_polling()

if __name__ == "__main__":
    main()
