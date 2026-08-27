from urllib.parse import urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from database import find_article_by_url, save_article_content, upsert_article
from sources import HEADERS, SOURCES, article_payload, extract_article_page


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme or "https", parts.netloc, parts.path, "", ""))


def source_for_url(url: str):
    normalized = normalize_url(url)
    host = urlsplit(normalized).netloc.lower()
    for source in SOURCES:
        if source["allowed_host"] in host:
            return source
    return None


def _page_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for selector in (
        ("meta", {"property": "og:title"}),
        ("meta", {"name": "twitter:title"}),
    ):
        tag = soup.find(selector[0], attrs=selector[1])
        if tag and tag.get("content"):
            return tag["content"].strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(" ", strip=True)
    if soup.title:
        return soup.title.get_text(" ", strip=True)
    return "Shared article"


def ingest_shared_url(url: str):
    normalized = normalize_url(url)
    existing = find_article_by_url(normalized)
    if existing:
        return existing

    source = source_for_url(normalized)
    if not source:
        return None

    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=15.0) as client:
        response = client.get(normalized)
        response.raise_for_status()
        title = _page_title(response.text)
        page = extract_article_page(source, response.text)

    upsert_article(article_payload(source, title, normalized, page))
    save_article_content(
        url=normalized,
        source_type="public_web",
        content_status=page["content_status"],
        plain_text=page["plain_text"],
        meta_description=page["meta_description"],
        word_count=page["word_count"],
        content_hash=page["content_hash"],
    )
    return find_article_by_url(normalized)
