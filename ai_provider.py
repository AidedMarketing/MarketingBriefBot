import os
from typing import Iterable

import httpx

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
OPENAI_URL = "https://api.openai.com/v1/responses"


class AIUnavailable(RuntimeError):
    pass


def _extract_output_text(payload: dict) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    pieces = []
    for item in payload.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                pieces.append(content["text"])
    return "\n".join(pieces).strip()


def _article_context(article: dict) -> str:
    summary = (article.get("summary") or "").strip()
    return (
        f"Title: {article['title']}\n"
        f"Publication: {article['publication']}\n"
        f"Topic: {article['topic']}\n"
        f"URL: {article['url']}\n"
        f"Available article context: {summary or 'No article body is available. Do not pretend to know details beyond the title and metadata.'}"
    )


def _history_text(history: Iterable[dict]) -> str:
    lines = []
    for message in history:
        role = "User" if message["role"] == "user" else "The Brief"
        lines.append(f"{role}: {message['content']}")
    return "\n".join(lines[-12:])


def _call_openai(instructions: str, prompt: str, max_output_tokens: int = 700) -> str:
    if not OPENAI_API_KEY:
        raise AIUnavailable("OPENAI_API_KEY is not configured.")

    response = httpx.post(
        OPENAI_URL,
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": OPENAI_MODEL,
            "instructions": instructions,
            "input": prompt,
            "max_output_tokens": max_output_tokens,
        },
        timeout=45.0,
    )
    response.raise_for_status()
    text = _extract_output_text(response.json())
    if not text:
        raise AIUnavailable("The AI provider returned no text.")
    return text


def discuss(article: dict, history: list[dict], user_message: str) -> str:
    instructions = (
        "You are The Brief, a thoughtful professional-reading discussion partner. "
        "Help the user learn business, marketing, strategy, leadership, and technology through the selected article. "
        "Be concise but substantive. Do not simply agree: test assumptions, explain unfamiliar concepts, connect ideas to practical work, "
        "and ask at most one useful follow-up question when it advances learning. "
        "Never claim to have read details that are not present in the supplied article context. "
        "If the user asks about a passage or claim not represented in context, ask them to paste that excerpt. "
        "Do not reproduce long copyrighted passages."
    )
    prompt = (
        f"ARTICLE\n{_article_context(article)}\n\n"
        f"RECENT DISCUSSION\n{_history_text(history) or '(none yet)'}\n\n"
        f"USER MESSAGE\n{user_message}"
    )
    return _call_openai(instructions, prompt)


def create_learning_note(article: dict, history: list[dict]) -> str:
    instructions = (
        "Create a compact learning note from a professional-reading discussion. "
        "Use exactly three short sections: Key idea, My takeaway, Application. "
        "Base it only on the supplied article context and discussion. "
        "Do not invent claims from the article."
    )
    prompt = (
        f"ARTICLE\n{_article_context(article)}\n\n"
        f"DISCUSSION\n{_history_text(history)}"
    )
    return _call_openai(instructions, prompt, max_output_tokens=400)
