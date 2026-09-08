# The Brief Bot — version 1.0 release plan

Reviewed September 8, 2026. Baseline: 43ba762.

## Product promise

Open Telegram, find one worthwhile professional read, understand why it fits,
and discuss or apply an idea with a companion that remembers your learning.
Keep the backend detailed and capable and the front end calm. No required
planning, tagging, streaks, dashboards, or maintenance rituals.

## What already exists

- Railway worker running app.py, PostgreSQL persistence, Telegram interface.
- HBR, MIT Sloan and Marketing Brew discovery and on-demand public text extraction.
- Full / partial / metadata grounding, long-article context retrieval, private excerpts.
- Reading Lens, discussion, Key Ideas, Apply It, Challenge Me, saved learning notes.
- Passive engagement memory and a deterministic recommendation scoring layer.
- Daily card with rationale, focus and reading mode.

These are verified in repository code, not against the running Railway service.
The README already calls the last feature v1.0; this plan treats release quality
as a separate milestone from the presence of the feature.

## Fixes implemented on fix/brief-v1-readiness

1. Persist one daily selection and explanation per user and Miami calendar date.
   /today reopens that selection; /next explicitly replaces it. Selections use a
   database lock to avoid concurrent selection races. Failed sends remain retryable.
2. Record delivery only after Telegram sends successfully; reopening the same read
   does not inflate exposure. Activity and memory updates share a transaction.
3. Protect enriched classification from title-only discovery updates; protect
   existing article content against a weaker public extraction.
4. Saving a note now updates memory atomically. Startup also recovers note signals
   from previously saved notes. Preferences use the latest choice; repeated taps
   do not accumulate preference weight. /topics reads that same current state.
5. New formal imports are stored as private reader excerpts. Word count no longer
   produces an unsupported full-context claim. Empty imports remain open.
   Legacy non-public shared content is excluded from normal retrieval; completed
   import-session buffers are copied into their owner's excerpts without deleting
   originals. Older imports whose owner cannot be recovered from surviving session
   records require manual review; they are not guessed or exposed to other users.
6. /saved sorts by saving time. The deployment seed article is excluded from daily
   selection and is no longer inserted at startup.
7. A frequently repeated publication no longer produces a false source-rotation
   explanation. Wording avoids implying discovery time is publication freshness.

## Remaining release work, in priority order

### 1. Verify against staging PostgreSQL and Telegram

Run init_db twice against a copy of the existing database. Confirm existing articles,
notes, preferences and excerpts survive. Exercise /today twice, a process restart,
/next, next-day rollover, empty queue, Telegram send failure, and two concurrent
requests. Check per-user isolation with two test users. Check like → dislike → like,
both note-save paths, and a long import. Verify source refresh cannot erase enriched
fields. Keep the current production worker running until staging is verified.

### 2. Finish responsiveness and failure recovery

Discovery currently runs ahead of /today even when a daily card already exists.
Move discovery to a bounded, cached background job; serve stored selections promptly.
Do not assume asyncio timeout cancels the worker thread. Coalesce overlapping
refreshes and surface a useful cached response during publication outages. Add a
central error handler and paginate /notes and long saved-note responses.
Target: an existing daily card within 2 seconds under normal service conditions;
slow refreshes must not hold up an unrelated reading action.

### 3. Improve recommendation quality without more user work

Extract trustworthy publication dates before claiming actual freshness. Retain
transparent scoring, but tune topic/source repetition from real reading sessions.
Make reading focus article-specific using available text, with a grounded fallback.
Use saved notes to recall an earlier idea when it materially helps a discussion;
the current engagement profile is not yet semantic recall of past learning.
Treat nonresponse as unknown, never a dislike. Keep partial HBR context useful and
state limitations only when they matter to the question.

### 4. Run a seven-day personal pilot

Track quietly: successful delivery, time to card, extraction failures, duplicate
exposure, recommendation relevance and whether discussions produce useful ideas.
Review logs and actual conversations; no new user dashboard. Call the release 1.0
when the daily loop stays reliable across restarts and slow sources, notes and
preferences persist correctly, and recommendations feel useful without upkeep.

## Validation completed here

Seven focused regression tests passed (mocked database and Telegram boundaries):
failed/successful delivery ordering, stored daily explanation, atomic note-memory
call, private import storage and completeness, empty import, honest source rationale.
Python compilation and git diff whitespace checks passed.

Live PostgreSQL migrations/SQL, Railway configuration, Telegram behavior, publisher
extraction and model responses have not been tested in this session. These are
release gates, not claims of completed deployment validation.

## Deployment and rollback

Run the existing Procfile entrypoint: python app.py. Schema changes are additive.
Do not launch a second production polling worker for the same Telegram token.
Take a database backup before staging/production migration. Rollback to the prior
code leaves the new tables intact, but restores the old import privacy and daily
selection behavior; account for that limitation before reverting.

## After 1.0

Consider a small weekly synthesis only after the core loop earns its place.
Defer more publications, extra channels, vector infrastructure and elaborate
planning tools until a concrete reading need justifies them.
