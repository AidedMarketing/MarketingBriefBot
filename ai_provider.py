import os
from typing import Iterable

import httpx

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
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


def _split_article_chunks(body: str, max_chars: int = 4200):
    parts = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    chunks = []
    current = []

    for part in parts:
        proposed = "\n\n".join(current + [part])
        if current and len(proposed) > max_chars:
            chunks.append("\n\n".join(current))
            current = [part]
        else:
            current.append(part)

    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _query_terms(text: str):
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]{2,}", text.lower())
    stop = {
        "the","and","that","this","with","from","have","about","what","when","where",
        "which","would","could","should","article","please","tell","explain","mentioned",
        "toward","near","does","into","more","full","sentence","paragraph"
    }
    return [w for w in words if w not in stop]


def _select_article_context(body: str, user_message: str, max_total_chars: int = 60000) -> str:
    if not body:
        return ""

    # Short/normal professional articles fit comfortably in Luna's context window.
    # Sending the whole article is safer than silently clipping the ending.
    if len(body) <= max_total_chars:
        return body

    chunks = _split_article_chunks(body)
    if not chunks:
        return body[:max_total_chars]

    selected = set()

    # Always include the beginning and ending so questions about conclusions,
    # final checklists, and late-article examples remain grounded.
    for idx in range(min(2, len(chunks))):
        selected.add(idx)
    for idx in range(max(0, len(chunks) - 3), len(chunks)):
        selected.add(idx)

    lower_body = body.lower()
    lower_query = user_message.lower().strip()

    # If the user's wording or a substantial phrase appears exactly, include the
    # containing chunk plus its neighbors.
    phrase_candidates = [
        p.strip()
        for p in re.split(r"[.!?\n]", lower_query)
        if len(p.strip()) >= 18
    ]
    for phrase in phrase_candidates:
        pos = lower_body.find(phrase)
        if pos >= 0:
            running = 0
            for i, chunk in enumerate(chunks):
                end_pos = running + len(chunk)
                if running <= pos <= end_pos:
                    selected.update({max(0, i-1), i, min(len(chunks)-1, i+1)})
                    break
                running = end_pos + 2

    terms = _query_terms(user_message)
    scored = []
    for i, chunk in enumerate(chunks):
        lowered = chunk.lower()
        score = sum(lowered.count(term) for term in terms)
        if any(term in lowered for term in terms):
            score += 2
        scored.append((score, i))

    for score, i in sorted(scored, reverse=True):
        if score <= 0:
            break
        selected.update({max(0, i-1), i, min(len(chunks)-1, i+1)})
        if len(selected) >= 10:
            break

    ordered = [chunks[i] for i in sorted(selected)]
    assembled = "\n\n---\n\n".join(ordered)

    if len(assembled) > max_total_chars:
        assembled = assembled[:max_total_chars]

    return assembled


def _article_context(article: dict, user_message: str = "") -> str:
    status = article.get("content_status") or "metadata_only"
    description = (article.get("meta_description") or article.get("summary") or "").strip()
    body = (article.get("plain_text") or "").strip()

    if status == "full":
        context_rule = (
            "FULL CONTEXT: You may attribute claims to the article when supported by the supplied text. "
            "The supplied context may be query-selected from a longer stored article; do not claim a detail is absent "
            "unless you have checked the supplied context and state that limitation carefully."
        )
    elif status == "partial":
        context_rule = (
            "PARTIAL CONTEXT: Only attribute claims that appear in the supplied excerpt/metadata. "
            "Do not present inferred themes as the article's argument."
        )
    else:
        context_rule = (
            "METADATA ONLY: Do not say 'the article argues', 'the article says', 'the core lesson is', "
            "or otherwise attribute substantive claims to the article. You may discuss the topic generally, "
            "but label that clearly as topic-level analysis. Ask for an excerpt/import when article-specific analysis is requested."
        )

    body_for_model = _select_article_context(body, user_message)

    return (
        f"Title: {article['title']}\n"
        f"Publication: {article['publication']}\n"
        f"Topic: {article['topic']}\n"
        f"URL: {article['url']}\n"
        f"Content status: {status}\n"
        f"Stored word count: {article.get('word_count') or 0}\n"
        f"Grounding rule: {context_rule}\n"
        f"Description: {description or '(none)'}\n"
        f"Article text/context:\n{body_for_model or '(none)'}"
    )

