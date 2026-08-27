import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from database import upsert_article

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; MyMarketingBriefBot/0.4; "
        "+https://github.com/AidedMarketing/MarketingBriefBot)"
    )
}

SOURCES = [
    {
        "name": "Harvard Business Review",
        "home": "https://hbr.org/",
        "allowed_host": "hbr.org",
        "path_patterns": ("/20", "/podcast/", "/video/"),
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
    "Strategy": {
        "strategy", "strategic", "competitive", "positioning", "growth",
        "business model", "pricing", "market", "advantage",
    },
    "Marketing": {
        "marketing", "brand", "advertising", "customer", "consumer",
        "campaign", "social", "creator", "media", "seo", "retail",
    },
    "Technology / AI": {
        "ai", "artificial intelligence", "technology", "digital",
        "automation", "data", "algorithm", "machine learning", "llm",
    },
    "Leadership / Career": {
        "leader", "leadership", "manager", "management", "career",
        "communication", "team", "workplace", "employee", "talent",
    },
}

BASE_SCORE = {
    "Harvard Business Review": 30,
    "Marketing Brew": 28,
    "MIT Sloan Management Review": 29,
}

TOPIC_WHY = {
    "Strategy": "This strengthens strategic thinking — moving beyond execution into how companies compete, grow, position themselves, and make tradeoffs.",
    "Marketing": "This is directly useful for sharpening your marketing judgment around brands, customers, channels, campaigns, and what is changing in the field.",
    "Technology / AI": "This sits at the intersection of business and technology, helping build the AI and digital fluency that is increasingly valuable in modern marketing and management.",
    "Leadership / Career": "This develops the management, communication, and career judgment that becomes more important as responsibility grows.",
    "Business / Management": "This broadens business judgment beyond marketing and helps connect day-to-day work to how organizations actually operate.",
}

PUBLICATION_WHY = {
    "Harvard Business Review": "HBR adds a deeper business and management lens.",
    "Marketing Brew": "Marketing Brew adds a current, industry-facing lens.",
    "MIT Sloan Management Review": "MIT Sloan adds a technology, innovation, and management lens.",
}


def classify(title: str):
    lowered = title.lower()
    scores = {}

    for topic, words in KEYWORDS.items():
        scores[topic] = sum(1 for word in words if word in lowered)

    topic = max(scores, key=scores.get)
    matches = scores[topic]

    if matches == 0:
        topic = "Business / Management"

    return topic, matches


def build_why(source_name: str, title: str, topic: str) -> str:
    lowered = title.lower()
    hooks = []

    if "ai" in lowered or "artificial intelligence" in lowered:
        hooks.append("It also gives you a concrete way to think about how AI is changing business decisions.")
    if "brand" in lowered:
        hooks.append("The brand angle makes it especially relevant to your marketing development.")
    if "customer" in lowered or "consumer" in lowered:
        hooks.append("The customer lens is useful for connecting marketing activity to actual behavior and value.")
    if "leadership" in lowered or "manager" in lowered or "management" in lowered:
        hooks.append("It is also a useful read-ahead topic for developing management judgment before you need it.")
    if "strategy" in lowered or "strategic" in lowered:
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

        if len(title) < 18 or len(title) > 220:
            continue

        if not valid_link(source, href):
            continue

        url = urljoin(source["home"], href).split("#")[0]

        if url in seen:
            continue

        seen.add(url)
        candidates.append((title, url))

    return candidates[:30]


def article_payload(source: dict, title: str, url: str):
    topic, keyword_matches = classify(title)
    score = BASE_SCORE[source["name"]] + keyword_matches * 8

    lowered = title.lower()
    priority_terms = (
        "strategy", "brand", "marketing", "customer", "ai",
        "leadership", "career", "growth", "innovation",
    )
    score += sum(4 for term in priority_terms if term in lowered)

    return {
        "title": title,
        "publication": source["name"],
        "url": url,
        "author": None,
        "published_date": None,
        "topic": topic,
        "summary": "",
        "why_recommended": build_why(source["name"], title, topic),
        "reading_time": 8 if source["name"] != "Marketing Brew" else 5,
        "recommendation_score": score,
    }


def refresh_sources(force: bool = True):
    found = 0
    added = 0
    errors = []

    timeout = httpx.Timeout(12.0, connect=8.0)

    with httpx.Client(
        headers=HEADERS,
        follow_redirects=True,
        timeout=timeout,
    ) as client:
        for source in SOURCES:
            try:
                response = client.get(source["home"])
                response.raise_for_status()
                candidates = extract_candidates(source, response.text)
                found += len(candidates)

                for title, url in candidates:
                    if upsert_article(article_payload(source, title, url)):
                        added += 1

            except Exception as exc:
                errors.append(f"{source['name']}: {type(exc).__name__}")

    if errors:
        print("Source refresh warnings:", "; ".join(errors), flush=True)

    return {
        "found": found,
        "added": added,
        "errors": errors,
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
    }
