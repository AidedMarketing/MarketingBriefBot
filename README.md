# MarketingBriefBot

A mobile-first Telegram bot for curated professional reading and active learning.

## v0.6 — Article Intelligence

### What changed
- Public article pages are now fetched and parsed for readable context.
- The bot stores a content status for every article:
  - `full`
  - `partial`
  - `metadata_only`
- Recommendation cards display what level of article context The Brief actually has.
- Classification now uses word-boundary matching, so `AI` no longer matches words such as `campaign`.
- Topic classification and recommendation reasoning use headline + description + available article text.
- GPT-5.6 Luna is now the code fallback model.
- AI grounding rules are stricter: metadata-only discussions cannot be presented as article claims.

### HBR subscriber workflow
HBR discovery remains automatic. Your HBR login stays in HBR; it is never stored in Railway.

When you share an HBR URL into the Telegram chat:
1. The Brief matches it to the existing article.
2. It starts a private import session.
3. Paste article text or upload a text-based PDF.
4. Use `/finishimport`.
5. The stored article context becomes `full` or `partial` based on what was imported.

The bot does not bypass subscription authentication or redistribute full article text.

### Import commands
- `/finishimport` — finalize pasted/PDF content
- `/cancelimport` — cancel the active import

### Existing commands
- `/today`
- `/saved`
- `/history`
- `/topics`
- `/notes`
- `/refresh`
- `/note`
- `/end`

### Railway variables
- `TELEGRAM_BOT_TOKEN`
- `DATABASE_URL`
- `OPENAI_API_KEY`
- optional `OPENAI_MODEL` (recommended: `gpt-5.6-luna`)


## v0.6.1 — Extraction Integrity

- Article extraction now preserves headings, lists, blockquotes, and paragraphs in document order.
- Word count alone can no longer mark an article as full.
- HBR completeness is deliberately conservative.
- Public HBR sponsored content uses structural + end-of-article signals before receiving a full-context label.
- The regression case for the Fiserv/EY-Parthenon article now captures the "Bringing It to Life" checklist rather than stopping before the list.


## v0.6.2 — Context Recall

- Removed the old 30,000-character first-half clipping behavior.
- Normal-length articles are now sent to Luna in full.
- Longer articles use query-aware chunk retrieval.
- The beginning and final sections are always included for long articles.
- Exact user phrases/keywords pull the matching article chunk plus neighboring context.
- Public, non-paywalled JSON-LD `articleBody` is used when it is materially more complete than DOM extraction.
- Luna is no longer allowed to treat an omitted retrieval chunk as proof that the article itself never mentioned something.


## v0.7 — Partial Intelligence

- Partial-context articles are now treated as usable reading contexts, not failure states.
- The Brief answers normally from available partial text and only mentions missing context when it actually affects the question.
- During an active partial/metadata discussion, pasted passages are automatically stored as private reader context when they look like article excerpts.
- Reader-added excerpts persist in Postgres and are supplied to Luna on future turns for that article.
- Recommendation/context labels now show stored word count and reader-excerpt count.
- `/debugarticle` now reports reader-excerpt count alongside stored article diagnostics.
- Sharing an HBR link no longer automatically forces a formal import session; you can read in HBR, discuss in Telegram, and paste only the section that matters.
- The full PDF/text import workflow remains available as an optional fallback.


## v0.8 — Guided Learning Loop

- Added a **Reading Lens** button to recommendation cards for a short pre-reading guide.
- Discussion sessions now include guided actions:
  - **Key Ideas** — distills the highest-value concepts.
  - **Apply It** — converts ideas into practical marketing/business/career application.
  - **Challenge Me** — asks one comprehension/critical-thinking question.
  - **Save Note** — creates and stores a learning note from the discussion.
- Guided actions use the same full/partial/reader-supplied context rules as normal conversation.
- Guided outputs are recorded in discussion history so the learning conversation can continue naturally.
