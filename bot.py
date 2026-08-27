import asyncio
import io
import os
import re
from html import escape

import httpx
from pypdf import PdfReader
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ai_provider import AIUnavailable, create_learning_note, discuss
from database import (
    add_discussion_message,
    append_import_text,
    cancel_import,
    end_discussion,
    finish_import,
    get_active_discussion,
    get_article,
    get_discussion_history,
    get_history,
    get_import_session,
    get_learning_notes,
    get_preference_summary,
    get_saved_articles,
    get_today_article,
    init_db,
    record_activity,
    save_learning_note,
    seed_test_article,
    start_discussion,
    start_import,
)
from importer import ingest_shared_url, source_for_url
from sources import enrich_article, refresh_sources

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


def split_message(text: str, limit: int = 3800):
    text = (text or "").strip()
    if not text:
        return []

    chunks = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        candidates = [
            window.rfind("\n\n"),
            window.rfind("\n- "),
            window.rfind("\n• "),
            window.rfind(". "),
        ]
        break_at = max(candidates)
        if break_at < int(limit * 0.55):
            break_at = limit
        else:
            break_at += 1

        chunk = remaining[:break_at].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[break_at:].strip()

    if remaining:
        chunks.append(remaining)
    return chunks


async def send_long_reply(message, text: str):
    for chunk in split_message(text):
        await message.reply_text(chunk)


def diagnostic_match(article: dict, query: str):
    body = (article.get("plain_text") or "")
    needle = query.strip().lower()

    if not needle:
        return None

    pos = body.lower().find(needle)
    if pos < 0:
        return {"found": False, "position": None, "snippet": ""}

    ratio = pos / max(1, len(body))
    position = "early" if ratio < 0.33 else "middle" if ratio < 0.67 else "late"

    start = max(0, pos - 140)
    end = min(len(body), pos + len(query) + 140)
    snippet = body[start:end].replace("\n", " ").strip()

    return {"found": True, "position": position, "snippet": snippet}



def content_label(article: dict) -> str:
    status = article.get("content_status") or "metadata_only"
    if status == "full":
        return "📄 Full article context"
    if status == "partial":
        return "📑 Partial article context"
    return "🔐 Metadata only — import for full discussion"


def article_keyboard(article: dict) -> InlineKeyboardMarkup:
    aid = article["id"]
    rows = [
        [InlineKeyboardButton("📖 Read Article", url=article["url"])],
        [
            InlineKeyboardButton("🔖 Save", callback_data=f"save:{aid}"),
            InlineKeyboardButton("👍 More Like This", callback_data=f"like:{aid}"),
        ],
        [
            InlineKeyboardButton("👎 Less Like This", callback_data=f"dislike:{aid}"),
            InlineKeyboardButton("💬 Discuss", callback_data=f"discuss:{aid}"),
        ],
    ]
    if (article.get("content_status") or "metadata_only") != "full":
        rows.append([InlineKeyboardButton("📥 Import Article Context", callback_data=f"import:{aid}")])
    return InlineKeyboardMarkup(rows)


def format_article(article: dict, heading: str = "Today's Recommended Read") -> str:
    return (
        f"📖 <b>{escape(heading)}</b>\n\n"
        f"<b>{escape(article['title'])}</b>\n"
        f"{escape(article['publication'])}\n\n"
        f"🎯 <b>Why I picked this:</b>\n{escape(article['why_recommended'])}\n\n"
        f"🏷 {escape(article['topic'])}\n"
        f"⏱ ~{article['reading_time']} min read\n"
        f"{escape(content_label(article))}"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 Welcome to My Marketing Brief.\n\n"
        "/today — Next recommended read\n"
        "/saved — Saved articles\n"
        "/history — Recent recommendations\n"
        "/topics — Preference signals\n"
        "/notes — Learning notes\n"
        "/refresh — Find new articles\n"
        "/debugarticle <keyword> — Inspect stored article context\n"
        "/finishimport — Finish an article import\n"
        "/cancelimport — Cancel an article import\n"
        "/end — End an active discussion\n"
        "/help — Commands"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def refresh_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔎 Checking and reading the publications now…")
    try:
        result = await asyncio.wait_for(asyncio.to_thread(refresh_sources), timeout=45)
    except asyncio.TimeoutError:
        await msg.edit_text("⚠️ Refresh exceeded 45 seconds and was stopped. The bot is still online; /today can continue using the existing queue.")
        return
    await msg.edit_text(
        f"✅ Refresh complete.\n\n"
        f"Found {result['found']} candidates.\n"
        f"Added {result['added']} new articles.\n"
        f"Enriched {result.get('enriched', 0)} article pages with context.\n\n"
        "Send /today for your next recommendation."
    )


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    # Fast discovery only; deep-fetch just the article we are about to recommend.
    try:
        await asyncio.wait_for(asyncio.to_thread(refresh_sources, False), timeout=20)
    except asyncio.TimeoutError:
        pass

    article = get_today_article(uid)
    if not article:
        await update.message.reply_text("You've reached the end of the current queue. Try /refresh.")
        return

    if (article.get("content_status") or "metadata_only") != "full":
        try:
            await asyncio.wait_for(asyncio.to_thread(enrich_article, article), timeout=12)
            article = get_article(article["id"]) or article
        except asyncio.TimeoutError:
            pass

    record_activity(article["id"], "delivered", uid)
    await update.message.reply_text(
        format_article(article),
        parse_mode="HTML",
        reply_markup=article_keyboard(article),
    )


async def saved(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_saved_articles(update.effective_user.id, 10)
    if not rows:
        await update.message.reply_text("🔖 You haven't saved any articles yet.")
        return
    text = ["🔖 <b>Your Saved Reading</b>"]
    for i, a in enumerate(rows, 1):
        text.append(
            f'{i}. <a href="{escape(a["url"], quote=True)}">{escape(a["title"])}</a>\n'
            f'   {escape(a["publication"])} · {escape(a["topic"])}'
        )
    await update.message.reply_text(
        "\n\n".join(text),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_history(update.effective_user.id, 10)
    if not rows:
        await update.message.reply_text("📚 No recommendation history yet.")
        return
    text = ["📚 <b>Recent Recommendations</b>"]
    for i, a in enumerate(rows, 1):
        text.append(
            f'{i}. <a href="{escape(a["url"], quote=True)}">{escape(a["title"])}</a>\n'
            f'   {escape(a["publication"])} · {escape(a["topic"])}'
        )
    await update.message.reply_text(
        "\n\n".join(text),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_preference_summary(update.effective_user.id)
    if not rows:
        await update.message.reply_text("🧭 Use 👍 and 👎 on a few recommendations first.")
        return
    lines = ["🧭 <b>What The Brief Is Learning</b>"]
    for r in rows:
        net = r["likes"] - r["dislikes"]
        sig = "↑" if net > 0 else "↓" if net < 0 else "→"
        lines.append(
            f'{sig} <b>{escape(r["topic"])}</b> — {r["likes"]} 👍 · {r["dislikes"]} 👎'
        )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_learning_notes(update.effective_user.id, 10)
    if not rows:
        await update.message.reply_text("📝 No learning notes yet. Start a discussion and use /note.")
        return
    lines = ["📝 <b>Learning Notes</b>"]
    for i, r in enumerate(rows, 1):
        lines.append(f'{i}. <b>{escape(r["title"])}</b>\n{escape(r["note"])}')
    await update.message.reply_text("\n\n".join(lines), parse_mode="HTML")


async def debug_article_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    article = get_active_discussion(uid)

    if not article:
        await update.message.reply_text(
            "There isn't an active article discussion. Tap 💬 Discuss on an article first."
        )
        return

    query = " ".join(context.args).strip()
    status = article.get("content_status") or "metadata_only"
    source_type = article.get("source_type") or "unknown"
    word_count = article.get("word_count") or 0

    lines = [
        "🧪 Article Diagnostics",
        "",
        f"Title: {article['title']}",
        f"Publication: {article['publication']}",
        f"Content status: {status}",
        f"Source type: {source_type}",
        f"Stored words: {word_count:,}",
    ]

    if query:
        result = diagnostic_match(article, query)
        lines.append(f"Query: {query}")
        lines.append(f"Found in stored text: {'yes' if result['found'] else 'no'}")
        if result["found"]:
            lines.append(f"Approximate location: {result['position']}")
            if result["snippet"]:
                lines.extend(["", "Nearby context:", result["snippet"][:500]])
    else:
        lines.extend([
            "",
            "Add a keyword or short phrase after the command to test whether it exists in stored article text."
        ])

    await update.message.reply_text("\n".join(lines))


async def end_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    end_discussion(update.effective_user.id)
    await update.message.reply_text("✅ Discussion closed.")


async def note_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    session = get_active_discussion(uid)
    if not session:
        await update.message.reply_text("There isn't an active discussion. Tap 💬 Discuss first.")
        return
    history_rows = get_discussion_history(uid, session["id"])
    if not history_rows:
        await update.message.reply_text("Talk through the article with me first, then use /note.")
        return
    try:
        note = await asyncio.to_thread(create_learning_note, session, history_rows)
    except (AIUnavailable, httpx.HTTPError):
        await update.message.reply_text("I couldn't create the note right now.")
        return
    save_learning_note(uid, session["id"], note)
    await update.message.reply_text(
        f"📝 <b>Learning Note Saved</b>\n\n{escape(note)}",
        parse_mode="HTML",
    )


async def finish_import_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    article = finish_import(update.effective_user.id)
    if not article:
        await update.message.reply_text("There isn't an active article import.")
        return
    await update.message.reply_text(
        "✅ <b>Article context imported</b>\n\n"
        f"<b>{escape(article['title'])}</b>\n"
        f"{escape(content_label(article))}\n"
        f"🧾 {article.get('word_count') or 0:,} words\n\n"
        "You can now tap 💬 Discuss on this article for a grounded conversation.",
        parse_mode="HTML",
    )


async def cancel_import_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cancel_import(update.effective_user.id)
    await update.message.reply_text("Import cancelled.")


async def article_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    action, aid_text = q.data.split(":", 1)
    aid = int(aid_text)
    uid = update.effective_user.id
    article = get_article(aid)

    if not article:
        await q.answer("Article not found.", show_alert=True)
        return

    if action == "save":
        record_activity(aid, "saved", uid, True)
        await q.answer("Saved 🔖")
        return
    if action == "like":
        record_activity(aid, "liked", uid, True)
        await q.answer("More like this 👍")
        return
    if action == "dislike":
        record_activity(aid, "disliked", uid, True)
        await q.answer("Weighted down 👎")
        return
    if action == "import":
        start_import(uid, aid)
        await q.answer()
        await q.message.reply_text(
            "📥 <b>Article Import Started</b>\n\n"
            f"<b>{escape(article['title'])}</b>\n\n"
            "Paste the article text here, or upload a text-based PDF from your subscriber access. "
            "You can send multiple text messages.\n\n"
            "When you're done, send /finishimport.\n"
            "Use /cancelimport to stop.",
            parse_mode="HTML",
        )
        return
    if action == "discuss":
        record_activity(aid, "discussed", uid, True)
        start_discussion(uid, aid)
        await q.answer()
        status = article.get("content_status") or "metadata_only"
        grounding = (
            "I have full article context."
            if status == "full"
            else "I only have partial context."
            if status == "partial"
            else "I only have metadata right now. Import the article for article-specific analysis."
        )
        await q.message.reply_text(
            "💬 <b>Discussion started</b>\n\n"
            f"<b>{escape(article['title'])}</b>\n"
            f"{escape(grounding)}\n\n"
            "Send your reaction or question. I'll stay tied to this article until /end.",
            parse_mode="HTML",
        )


async def document_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    session = get_import_session(uid)
    if not session:
        await update.message.reply_text(
            "I received a file, but there isn't an active import. "
            "Share an HBR link or tap 📥 Import Article Context first."
        )
        return

    document = update.message.document
    tg_file = await context.bot.get_file(document.file_id)
    data = bytes(await tg_file.download_as_bytearray())
    filename = (document.file_name or "").lower()
    mime = document.mime_type or ""

    try:
        if filename.endswith(".pdf") or mime == "application/pdf":
            reader = PdfReader(io.BytesIO(data))
            pages = [(page.extract_text() or "").strip() for page in reader.pages]
            text = "\n\n".join(p for p in pages if p)
            source_type = "user_pdf"
        elif filename.endswith(".txt") or mime.startswith("text/"):
            text = data.decode("utf-8", errors="replace")
            source_type = "user_file"
        else:
            await update.message.reply_text("For now I can import PDF or plain-text files.")
            return
    except Exception:
        await update.message.reply_text("I couldn't extract readable text from that file.")
        return

    if len(text.split()) < 20:
        await update.message.reply_text(
            "I couldn't find enough readable text in that file. "
            "If it's a scanned/image PDF, paste the article text instead."
        )
        return

    append_import_text(uid, text)
    article = finish_import(uid, source_type=source_type)
    await update.message.reply_text(
        "✅ <b>Article imported from file</b>\n\n"
        f"{escape(content_label(article))}\n"
        f"🧾 {article.get('word_count') or 0:,} words\n\n"
        "The Brief can now use this context during discussion.",
        parse_mode="HTML",
    )


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_text = update.message.text.strip()
    if not user_text:
        return

    urls = re.findall(r"https?://[^\s<>]+", user_text)
    for raw_url in urls:
        if source_for_url(raw_url):
            try:
                article = await asyncio.to_thread(ingest_shared_url, raw_url.rstrip(".,)"))
            except Exception:
                article = None
            if article:
                status = article.get("content_status") or "metadata_only"
                if article["publication"] == "Harvard Business Review" and status != "full":
                    start_import(uid, article["id"])
                    await update.message.reply_text(
                        "🔐 <b>HBR article recognized</b>\n\n"
                        f"<b>{escape(article['title'])}</b>\n"
                        f"{escape(content_label(article))}\n\n"
                        "Your HBR subscription stays private in HBR. To give The Brief the subscriber text, "
                        "paste the article text here or upload a text-based PDF, then use /finishimport.",
                        parse_mode="HTML",
                    )
                else:
                    await update.message.reply_text(
                        "🔗 <b>Article recognized</b>\n\n"
                        f"<b>{escape(article['title'])}</b>\n"
                        f"{escape(content_label(article))}",
                        parse_mode="HTML",
                        reply_markup=article_keyboard(article),
                    )
                return

    import_session = get_import_session(uid)
    if import_session:
        append_import_text(uid, user_text)
        current_words = len(user_text.split())
        await update.message.reply_text(
            f"📥 Added {current_words:,} words to the import. "
            "Send more text or /finishimport when you're done."
        )
        return

    session = get_active_discussion(uid)
    if not session:
        return

    add_discussion_message(uid, session["id"], "user", user_text)
    history_rows = get_discussion_history(uid, session["id"])
    await update.message.chat.send_action("typing")
    try:
        answer = await asyncio.to_thread(discuss, session, history_rows[:-1], user_text)
    except Exception:
        await update.message.reply_text("I couldn't reach the discussion model right now.")
        return
    add_discussion_message(uid, session["id"], "assistant", answer)
    await send_long_reply(update.message, answer)


def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured.")

    init_db()
    seed_test_article()

    app = Application.builder().token(TOKEN).build()
    for cmd, fn in [
        ("start", start),
        ("help", help_command),
        ("today", today),
        ("saved", saved),
        ("history", history),
        ("topics", topics),
        ("notes", notes),
        ("refresh", refresh_command),
        ("debugarticle", debug_article_command),
        ("end", end_command),
        ("note", note_command),
        ("finishimport", finish_import_command),
        ("cancelimport", cancel_import_command),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    app.add_handler(CallbackQueryHandler(article_action))
    app.add_handler(MessageHandler(filters.Document.ALL, document_import))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    print("My Marketing Brief v0.6 is running...", flush=True)
    app.run_polling()


if __name__ == "__main__":
    main()
