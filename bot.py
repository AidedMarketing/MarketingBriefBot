import asyncio
import os
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler,
    ContextTypes, MessageHandler, filters,
)

from ai_provider import AIUnavailable, create_learning_note, discuss
from database import (
    add_discussion_message, end_discussion, get_active_discussion, get_article,
    get_discussion_history, get_history, get_learning_notes, get_preference_summary,
    get_saved_articles, get_today_article, init_db, record_activity,
    save_learning_note, seed_test_article, start_discussion,
)
from sources import refresh_sources

TOKEN=os.getenv("TELEGRAM_BOT_TOKEN")


def article_keyboard(article):
    aid=article["id"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 Read Article",url=article["url"])],
        [InlineKeyboardButton("🔖 Save",callback_data=f"save:{aid}"),
         InlineKeyboardButton("👍 More Like This",callback_data=f"like:{aid}")],
        [InlineKeyboardButton("👎 Less Like This",callback_data=f"dislike:{aid}"),
         InlineKeyboardButton("💬 Discuss",callback_data=f"discuss:{aid}")],
    ])


def format_article(article, heading="Today's Recommended Read"):
    return (
        f"📖 <b>{escape(heading)}</b>\n\n"
        f"<b>{escape(article['title'])}</b>\n{escape(article['publication'])}\n\n"
        f"🎯 <b>Why I picked this:</b>\n{escape(article['why_recommended'])}\n\n"
        f"🏷 {escape(article['topic'])}\n⏱ ~{article['reading_time']} min read"
    )


async def start(update:Update, context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 Welcome to My Marketing Brief.\n\n"
        "/today — Next recommended read\n/saved — Saved articles\n/history — Recent recommendations\n"
        "/topics — Preference signals\n/notes — Learning notes\n/refresh — Find new articles\n"
        "/end — End an active discussion\n/help — Commands"
    )


async def help_command(update:Update, context:ContextTypes.DEFAULT_TYPE):
    await start(update,context)


async def refresh_command(update:Update, context:ContextTypes.DEFAULT_TYPE):
    msg=await update.message.reply_text("🔎 Checking the publications now…")
    result=await asyncio.to_thread(refresh_sources)
    await msg.edit_text(
        f"✅ Refresh complete.\n\nFound {result['found']} candidates.\nAdded {result['added']} new articles.\n"
        "Existing article metadata was refreshed too."
    )


async def today(update:Update, context:ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    await asyncio.to_thread(refresh_sources,False)
    article=get_today_article(uid)
    if not article:
        await update.message.reply_text("You've reached the end of the current queue. Try /refresh.")
        return
    record_activity(article["id"],"delivered",uid)
    await update.message.reply_text(format_article(article),parse_mode="HTML",reply_markup=article_keyboard(article))


async def saved(update:Update, context:ContextTypes.DEFAULT_TYPE):
    rows=get_saved_articles(update.effective_user.id,10)
    if not rows:
        await update.message.reply_text("🔖 You haven't saved any articles yet.")
        return
    text=["🔖 <b>Your Saved Reading</b>"]
    for i,a in enumerate(rows,1):
        text.append(f'{i}. <a href="{escape(a["url"],quote=True)}">{escape(a["title"])}</a>\n   {escape(a["publication"])} · {escape(a["topic"])}')
    await update.message.reply_text("\n\n".join(text),parse_mode="HTML",disable_web_page_preview=True)


async def history(update:Update, context:ContextTypes.DEFAULT_TYPE):
    rows=get_history(update.effective_user.id,10)
    if not rows:
        await update.message.reply_text("📚 No recommendation history yet.")
        return
    text=["📚 <b>Recent Recommendations</b>"]
    for i,a in enumerate(rows,1):
        text.append(f'{i}. <a href="{escape(a["url"],quote=True)}">{escape(a["title"])}</a>\n   {escape(a["publication"])} · {escape(a["topic"])}')
    await update.message.reply_text("\n\n".join(text),parse_mode="HTML",disable_web_page_preview=True)


async def topics(update:Update, context:ContextTypes.DEFAULT_TYPE):
    rows=get_preference_summary(update.effective_user.id)
    if not rows:
        await update.message.reply_text("🧭 Use 👍 and 👎 on a few recommendations first.")
        return
    lines=["🧭 <b>What The Brief Is Learning</b>"]
    for r in rows:
        net=r["likes"]-r["dislikes"]
        sig="↑" if net>0 else "↓" if net<0 else "→"
        lines.append(f'{sig} <b>{escape(r["topic"])}</b> — {r["likes"]} 👍 · {r["dislikes"]} 👎')
    await update.message.reply_text("\n".join(lines),parse_mode="HTML")


async def notes(update:Update, context:ContextTypes.DEFAULT_TYPE):
    rows=get_learning_notes(update.effective_user.id,10)
    if not rows:
        await update.message.reply_text("📝 No learning notes yet. Start an article discussion and use /note.")
        return
    lines=["📝 <b>Learning Notes</b>"]
    for i,r in enumerate(rows,1):
        lines.append(f'{i}. <b>{escape(r["title"])}</b>\n{escape(r["note"])}')
    await update.message.reply_text("\n\n".join(lines),parse_mode="HTML")


async def end_command(update:Update, context:ContextTypes.DEFAULT_TYPE):
    end_discussion(update.effective_user.id)
    await update.message.reply_text("✅ Discussion closed. Use 💬 Discuss on any article to start another.")


async def note_command(update:Update, context:ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    session=get_active_discussion(uid)
    if not session:
        await update.message.reply_text("There isn't an active discussion. Tap 💬 Discuss on an article first.")
        return
    history=get_discussion_history(uid,session["id"])
    if not history:
        await update.message.reply_text("Talk through the article with me first, then use /note.")
        return
    try:
        note=await asyncio.to_thread(create_learning_note,session,history)
    except (AIUnavailable, httpx.HTTPError) as exc:
        await update.message.reply_text("I couldn't create the note right now. Check the AI configuration in Railway.")
        return
    save_learning_note(uid,session["id"],note)
    await update.message.reply_text(f"📝 <b>Learning Note Saved</b>\n\n{escape(note)}",parse_mode="HTML")


async def article_action(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    action,aid_text=q.data.split(":",1)
    aid=int(aid_text)
    uid=update.effective_user.id
    article=get_article(aid)
    if not article:
        await q.answer("Article not found.",show_alert=True)
        return
    if action=="save":
        record_activity(aid,"saved",uid,True); await q.answer("Saved 🔖"); return
    if action=="like":
        record_activity(aid,"liked",uid,True); await q.answer("More like this 👍"); return
    if action=="dislike":
        record_activity(aid,"disliked",uid,True); await q.answer("Weighted down 👎"); return
    if action=="discuss":
        record_activity(aid,"discussed",uid,True)
        start_discussion(uid,aid)
        await q.answer()
        await q.message.reply_text(
            "💬 <b>Discussion started</b>\n\n"
            f"<b>{escape(article['title'])}</b>\n\n"
            "Send me your reaction, a question, or a passage you want to unpack. "
            "I'll stay tied to this article until you use /end.\n\n"
            "Use /note anytime after we've discussed it to save a learning note.",
            parse_mode="HTML"
        )


async def discussion_message(update:Update, context:ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    session=get_active_discussion(uid)
    if not session:
        return
    user_text=update.message.text.strip()
    if not user_text:
        return
    add_discussion_message(uid,session["id"],"user",user_text)
    history=get_discussion_history(uid,session["id"])
    await update.message.chat.send_action("typing")
    try:
        answer=await asyncio.to_thread(discuss,session,history[:-1],user_text)
    except Exception:
        await update.message.reply_text(
            "I couldn't reach the discussion model. If this is the first v0.5 test, "
            "make sure OPENAI_API_KEY is set in Railway."
        )
        return
    add_discussion_message(uid,session["id"],"assistant",answer)
    await update.message.reply_text(answer)


def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured.")
    init_db(); seed_test_article()
    app=Application.builder().token(TOKEN).build()
    for cmd,fn in [
        ("start",start),("help",help_command),("today",today),("saved",saved),
        ("history",history),("topics",topics),("notes",notes),("refresh",refresh_command),
        ("end",end_command),("note",note_command)
    ]:
        app.add_handler(CommandHandler(cmd,fn))
    app.add_handler(CallbackQueryHandler(article_action))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,discussion_message))
    print("My Marketing Brief v0.5 is running...",flush=True)
    app.run_polling()


if __name__=="__main__":
    import httpx
    main()
