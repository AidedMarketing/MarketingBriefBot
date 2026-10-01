# Jev pilot: Brief Bot → Aided Marketing → AidedMind

## Purpose and scope

Learn whether Jev improves our narrow content judgments before changing daily recommendations. The first release is **shadow-only**: Jev records its judgments alongside the existing bot. It does not change article selection, topic records, content status, daily cards, discussion responses, notes, or private excerpts.

The pilot evaluates five independent questions against the **entire stored public article body**: dominant content kind, topic, practical value for professional marketing learning, concrete examples, and access-message signals. This is an assessment of supplied text, not proof that extraction captured the full original article or that its claims are true.

## Activate on Railway

1. Deploy this repository's updated worker code. `init_db()` creates an additive `jev_evaluations` table; existing reading data is preserved.
2. Create an API key at https://console.typesafe.ai and put it directly in the worker's Railway Variables as `TYPESAFE_API_KEY`. Do not paste credentials into Telegram, GitHub, or a chat.
3. Set `JEV_MODE=shadow`. Optional settings: `JEV_MODEL=jev-1.13.0`, `JEV_TIMEOUT_SECONDS=5`. The pilot pins a version so comparisons remain meaningful. Timeouts are bounded to 1–10 seconds.
4. Redeploy the worker with its new variables. Run `/today`, then `/jev evaluate` after full-text enrichment has finished. Use `/debugarticle` to inspect the stored context separately.
5. Use `/jev` to inspect the cached judgment and `/jev report` to see evaluation coverage for articles you received. `/jev active` and `/jev evaluate active` inspect the active discussion's public article body.
6. Disable API calls at any time by setting `JEV_MODE=off` and redeploying. Stored diagnostics are retained.

Code deployment alone does not activate live Jev calls. With the default mode or a missing key, normal reading continues. There is no active-selection mode in this release.

## Automatic collection

- Already-full daily articles are evaluated in a background task after delivery and activity recording.
- Other selected articles are evaluated after the existing enrichment attempt. The evaluation reloads the **committed** public content so an extraction rejected by the database cannot become the evaluated text.
- Reader excerpts, learning notes, user IDs, discussion history, and URLs are excluded from the API state. Imported subscriber passages remain private reader context and are not sent by this pilot.
- Empty bodies are recorded as skipped, not evaluated from their headline.
- Requests with state over 24,000 UTF-8 JSON bytes are skipped. This is a conservative budget below the documented token limits. Oversized bodies are not clipped, summarized, or judged as if complete. Chunked evaluation is a later capability.
- The model receives the body once with five independent questions. It cannot execute actions or alter the bot's data.

## Resilience and auditability

`jev.py` owns the rubric, input construction, HTTP transport, and response validation. `jev_pilot.py` owns database caching and fail-open operation. `jev_evaluations` stores one result per article/input fingerprint; the fingerprint includes text, metadata, requested model, rubric version, and question definitions.

Successful and skipped results are reused. Provider errors have a 15-minute retry cooldown; there is no immediate retry loop. A process-local lock permits one live evaluation at a time, returning `busy` for overlapping attempts. Multiple worker replicas are not coordinated by this lock; run one Telegram polling worker as usual.

Returned probabilities, answer types, options, score ranges, and token counts are validated before storage. HTTP credentials cannot be forwarded through redirects. Operational logs include article ID, status, model, duration, and usage, not text, secrets, headers, or provider error bodies. Network/database failures do not change delivery or recommendation behavior.

Confidence summarizes a probability distribution; it is not measured correctness on our data. Topic probabilities, practical-value scores, and access-signal probabilities answer different questions and should not share an assumed universal threshold.

`/jev report` aggregates the latest stored evaluation per delivered article across all recorded rubrics/models. It is **not** an accuracy report or a total billing ledger: earlier fingerprints are excluded. Compare runs within the same rubric/model/input scope. Actual billing should be checked in TypeSafe's console.

## Evaluation before enabling any decision

Start with 20–30 articles for qualitative review, then build a labeled set of 100–200 examples. Include full public articles, partial but useful passages, teasers, login/limit pages, page noise, off-topic texts, mixed content, and unfamiliar sources. Include articles where keyword classification gets the topic wrong. Test prompt-injection cases and multilingual examples separately if those workloads are introduced.

For each example, record the reference topic, dominant content kind, and practical-value rubric level before examining Jev's result. Practical value is an ordered judgment, not a precise business outcome. Preserve disagreements instead of retroactively treating Jev's answer as truth.

Measure:

- Topic agreement with human labels and with the keyword baseline, including disagreements.
- Incorrect rejection of useful partial text and incorrect acceptance of access/noise pages.
- Practical-value agreement within one rubric level and reviewer's usefulness judgment.
- Coverage: successful, empty, oversized, failed, and uncertain cases.
- API latency distribution, input usage, cache reuse, and provider errors.
- Error rate among decisions above each candidate confidence threshold, evaluated on held-out examples.

Do not claim improved recommendations from classification agreement alone. The shadow pilot does not choose articles. A later selection experiment must compare ranked candidates and user outcomes, preserving source/topic diversity and the stable daily pick.

## Stage 2: Aided Marketing

After the bot pilot shows useful judgments, reuse the transport and evaluation pattern with **new task-specific rubrics**, not the bot's scores:

1. Classify anonymized interview notes and customer feedback into problems, objections, desired outcomes, and questions.
2. Review content drafts for explicit audience, offer, supporting evidence, and CTA. Use generative models for revisions; keep publishing under existing controls.
3. Route inquiries by requested service and missing information. Test against labeled historical inquiries before introducing lead-fit scoring.

For each workflow, define its allowed outputs, reference labels, error costs, uncertain route, and user correction process. Start in shadow mode. Research organization is the lowest entry point; campaign prediction and autonomous outreach are outside this pilot.

## Stage 3: AidedMind

Defer integration until the first two stages are evaluated. Potential later uses: extraction-quality review, source-grounding checks, retrieval filtering, and evaluating shortlisted concept relationships. AidedMind needs per-user data isolation, provenance, reversible automatic links, broader workload tests, and its own deployment plan. This change does not touch that repository.

## Validation

Run `python -m unittest discover -s tests -v` on Python 3.12 with `requirements.txt` installed. GitHub Actions runs the full suite without API keys or a live database. Provider calls and database operations are mocked; these tests verify request integrity, failure behavior, caching, command behavior, and delivery integration. They do not establish live model quality, provider reachability, Railway deployment health, or live Postgres migration compatibility.

Official references: https://docs.typesafe.ai/api, https://docs.typesafe.ai/models, https://docs.typesafe.ai/confidence, https://docs.typesafe.ai/model-jaggedness/jev-1.13.
