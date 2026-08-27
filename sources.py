import hashlib
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from database import save_article_content, upsert_article

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; MyMarketingBriefBot/0.6; "
        "+https://github.com/AidedMarketing/MarketingBriefBot)"
    )
}

SOURCES = [
    {
        "name": "Harvard Business Review",
        "home": "https://hbr.org/",
        "allowed_host": "hbr.org",
        "path_patterns": ("/20",),
    },
    {
        "name": "Marketing Brew",
        "home": "https://www.marketingbrew.com/",
        "allowed_host": "marketingbrew.com",
        "path_patterns": ("/stories/",),
    },
    {
        "name": "MIT Sloan Management Review",
        "home": "https://sloanreview.mit.edu/",
        "allowed_host": "sloanreview.mit.edu",
        "path_patterns": ("/article/",),
    },
]

KEYWORDS = {
    "Strategy": (
        "strategy", "strategic", "competitive", "positioning", "growth",
        "business model", "pricing", "market", "advantage",
    ),
    "Marketing": (
        "marketing", "brand", "advertising", "customer", "consumer",
        "campaign", "social", "creator", "media", "seo", "retail",
    ),
    "Technology / AI": (
        "ai", "artificial intelligence", "technology", "digital",
        "automation", "data", "algorithm", "machine learning", "llm",
    ),
    "Leadership / Career": (
        "leader", "leadership", "manager", "management", "career",
        "communication", "team", "workplace", "employee", "talent",
    ),
}

BASE_SCORE = {
    "Harvard Business Review": 30,
    "Marketing Brew": 28,
    "MIT Sloan Management Review": 29,
}

TOPIC_WHY = {
    "Strategy": "This strengthens strategic thinking by focusing on how companies compete, grow, position themselves, and make tradeoffs.",
    "Marketing": "This is directly useful for sharpening your marketing judgment around brands, customers, channels, campaigns, and changes in the field.",
    "Technology / AI": "This builds the business-and-technology fluency that is increasingly valuable in modern marketing and management.",
    "Leadership / Career": "This develops management, communication, and career judgment that becomes more important as responsibility grows.",
    "Business / Management": "This broadens business judgment beyond marketing and connects day-to-day work to how organizations operate.",
}

PUBLICATION_WHY = {
    "Harvard Business Review": "HBR adds a deeper business and management lens.",
    "Marketing Brew": "Marketing Brew adds a current, industry-facing lens.",
    "MIT Sloan Management Review": "MIT Sloan adds a technology, innovation, and management lens.",
}


def _term_match(text: str, term: str) -> bool:
    pattern = r"(?<!\w)" + re.escape(term.lower()) + r"(?!\w)"
    return re.search(pattern, text.lower()) is not None


def classify(text: str):
    scores = {
        topic: sum(1 for term in terms if _term_match(text, term))
        for topic, terms in KEYWORDS.items()
    }
    topic = max(scores, key=scores.get)
    matches = scores[topic]
    if matches == 0:
        topic = "Business / Management"
    return topic, matches


def build_why(source_name: str, context: str, topic: str) -> str:
    hooks = []
    if _term_match(context, "ai") or _term_match(context, "artificial intelligence"):
        hooks.append("It also gives you a concrete way to think about how AI is changing business decisions.")
    if _term_match(context, "brand"):
        hooks.append("The brand angle makes it especially relevant to your marketing development.")
    if _term_match(context, "customer") or _term_match(context, "consumer"):
        hooks.append("The customer lens helps connect marketing activity to behavior and value.")
    if _term_match(context, "leadership") or _term_match(context, "management"):
        hooks.append("It is also a useful read-ahead topic for developing management judgment.")
    if _term_match(context, "strategy") or _term_match(context, "strategic"):
        hooks.append("The strategy angle helps build the habit of asking why a business choice works, not just how to execute it.")

    core = TOPIC_WHY.get(topic, TOPIC_WHY["Business / Management"])
    publication = PUBLICATION_WHY[source_name]
    extra = f" {hooks[0]}" if hooks else ""
    return f"{core} {publication}{extra}"


def clean_title(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def valid_link(source: dict, href: str) -> bool:
    if not href:
        return False
    absolute = urljoin(source["home"], href)
    parsed = urlparse(absolute)
    if source["allowed_host"] not in parsed.netloc:
        return False
    path = parsed.path or "/"
    if path in ("", "/"):
        return False
    if any(fragment in path for fragment in ("/subscribe", "/about", "/events", "/sign-up")):
        return False
    return any(pattern in path for pattern in source["path_patterns"])


def extract_candidates(source: dict, html: str):
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    candidates = []
    for link in soup.find_all("a", href=True):
        title = clean_title(link.get_text(" ", strip=True))
        href = link.get("href")
        if len(title) < 18 or len(title) > 220 or not valid_link(source, href):
            continue
        url = urljoin(source["home"], href).split("#")[0]
        if url in seen:
            continue
        seen.add(url)
        candidates.append((title, url))
    return candidates[:30]


def extract_article_page(source: dict, html: str, url: str = ""):
    soup = BeautifulSoup(html, "html.parser")

    meta = soup.find("meta", attrs={"name": "description"})
    if not meta:
        meta = soup.find("meta", attrs={"property": "og:description"})
    description = clean_title(meta.get("content", "")) if meta else ""

    # Prefer the semantic article/main container so navigation and footer text do not
    # inflate our confidence score.
    root = soup.find("article") or soup.find("main") or soup

    # Preserve article structure instead of collecting only <p> elements.
    # This fixes checklist/list sections such as HBR's "Bringing It to Life".
    blocks = []
    seen = set()
    heading_count = 0
    list_item_count = 0

    for node in root.find_all(["h2", "h3", "h4", "p", "li", "blockquote"]):
        text = clean_title(node.get_text(" ", strip=True))
        if not text:
            continue

        tag = node.name.lower()
        minimum = 4 if tag in ("h2", "h3", "h4", "li") else 25
        if len(text) < minimum:
            continue

        # Avoid duplicate text caused by nested markup.
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)

        if tag in ("h2", "h3", "h4"):
            heading_count += 1
            blocks.append(f"\n## {text}\n")
        elif tag == "li":
            list_item_count += 1
            blocks.append(f"- {text}")
        elif tag == "blockquote":
            blocks.append(f"> {text}")
        else:
            blocks.append(text)

    body = "\n\n".join(blocks).strip()
    word_count = len(body.split())
    block_count = len(blocks)

    page_text = soup.get_text(" ", strip=True).lower()
    paywall_signal = any(
        marker in page_text
        for marker in (
            "subscribe to read",
            "subscribe to continue",
            "subscriber exclusive",
            "you have reached your limit",
            "sign in to continue",
            "register to continue",
        )
    )

    # Source-aware completeness checks. Word count alone must never mean "full".
    parsed_path = urlparse(url).path.lower() if url else ""
    is_hbr_sponsored = (
        source["name"] == "Harvard Business Review"
        and "/sponsored/" in parsed_path
    )

    # HBR sponsored articles expose their full editorial body publicly; an ending
    # disclosure/author section is a strong completion marker.
    hbr_completion_signal = any(
        marker in page_text
        for marker in (
            "the views reflected in this article",
            "also contributed to this article",
            "learn more about how the",
        )
    )

    # For normal article pages, require meaningful structure and a substantial body.
    structural_complete = (
        word_count >= 450
        and block_count >= 10
        and (heading_count >= 1 or list_item_count >= 3)
    )

    if paywall_signal:
        status = "partial" if (word_count >= 60 or description) else "metadata_only"
    elif is_hbr_sponsored and structural_complete and hbr_completion_signal:
        status = "full"
    elif source["name"] == "Marketing Brew" and structural_complete:
        status = "full"
    elif source["name"] == "MIT Sloan Management Review" and structural_complete:
        status = "full"
    elif source["name"] == "Harvard Business Review":
        # Regular HBR pages are deliberately conservative. If we cannot prove that
        # we reached the article boundary, call it partial rather than overclaiming.
        status = "partial" if (word_count >= 60 or description) else "metadata_only"
    elif structural_complete:
        status = "full"
    elif word_count >= 60 or description:
        status = "partial"
    else:
        status = "metadata_only"

    return {
        "meta_description": description,
        "plain_text": body,
        "word_count": word_count,
        "content_status": status,
        "content_hash": hashlib.sha256(body.encode("utf-8")).hexdigest() if body else None,
        "block_count": block_count,
        "heading_count": heading_count,
        "list_item_count": list_item_count,
    }


def article_payload(source: dict, title: str, url: str, page: dict | None = None):
    page = page or {}
    context = " ".join(
        part for part in (
            title,
            page.get("meta_description", ""),
            (page.get("plain_text", "") or "")[:4000],
        ) if part
    )
    topic, keyword_matches = classify(context)
    score = BASE_SCORE[source["name"]] + keyword_matches * 8

    priority_terms = (
        "strategy", "brand", "marketing", "customer",
        "leadership", "career", "growth", "innovation", "ai",
    )
    score += sum(4 for term in priority_terms if _term_match(context, term))

    words = page.get("word_count", 0)
    reading_time = max(3, round(words / 225)) if words else (5 if source["name"] == "Marketing Brew" else 8)

    return {
        "title": title,
        "publication": source["name"],
        "url": url,
        "author": None,
        "published_date": None,
        "topic": topic,
        "summary": page.get("meta_description", ""),
        "why_recommended": build_why(source["name"], context, topic),
        "reading_time": reading_time,
        "recommendation_score": score,
    }


def _fetch_article_page(source: dict, title: str, url: str):
    try:
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=8.0) as client:
            response = client.get(url)
            response.raise_for_status()
            page = extract_article_page(source, response.text, url)
            return title, url, page, None
    except Exception as exc:
        return title, url, {}, type(exc).__name__


def refresh_sources(force: bool = True):
    found = 0
    added = 0
    enriched = 0
    errors = []
    candidates_all = []

    # Homepage discovery stays sequential and cheap.
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=8.0) as client:
        for source in SOURCES:
            try:
                response = client.get(source["home"])
                response.raise_for_status()
                candidates = extract_candidates(source, response.text)
                found += len(candidates)
                for title, url in candidates:
                    candidates_all.append((source, title, url))
            except Exception as exc:
                errors.append(f"{source['name']} homepage: {type(exc).__name__}")

    # Deep article enrichment runs in parallel so /refresh doesn't take many minutes.
    max_workers = min(8, max(1, len(candidates_all)))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            pool.submit(_fetch_article_page, source, title, url)
            for source, title, url in candidates_all
        ]

        source_by_url = {url: source for source, _, url in candidates_all}

        for future in as_completed(futures):
            title, url, page, error = future.result()
            source = source_by_url[url]

            if error:
                errors.append(f"{source['name']} article: {error}")

            if upsert_article(article_payload(source, title, url, page)):
                added += 1

            if page:
                enriched += 1
                save_article_content(
                    url=url,
                    source_type="public_web",
                    content_status=page["content_status"],
                    plain_text=page["plain_text"],
                    meta_description=page["meta_description"],
                    word_count=page["word_count"],
                    content_hash=page["content_hash"],
                )

    if errors:
        print("Source refresh warnings:", "; ".join(errors[:10]), flush=True)

    return {
        "found": found,
        "added": added,
        "enriched": enriched,
        "errors": errors,
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
    }
