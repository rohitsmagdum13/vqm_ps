# Codebase Error Audit — VQMS

**Date:** 2026-04-26
**Scope:** Full codebase (backend Python, Angular frontend, tests, config, migrations)
**Method:** Three parallel exploration passes followed by manual verification of every claim. Roughly 4 of the initial agent claims turned out to be false positives and were dropped from this report.
**Status:** Read-only audit — no code changes.

---

## Summary

| Severity | Count | Areas |
|----------|-------|-------|
| CRITICAL | 2 | S3 bucket misconfiguration |
| HIGH     | 3 | JSON serialization, async test markers, frontend type drift |
| MEDIUM   | 7 | Silent SQS skips, dead vector index, doc drift, frontend state bugs |
| LOW      | 3 | Dead-stub method, sanitiser layering, timestamp format |

---

## Findings — Backend (Python)

### CRITICAL

#### 1. `config/settings.py:197` — Trailing space in S3 bucket name

```python
s3_bucket_data_store: str = "vqms-data-store-001 "
```

**Impact:** Every S3 operation will fail with `NoSuchBucket`. Raw email storage, attachment uploads, processed payloads, archive bundles, and the email dashboard all depend on this bucket. Production traffic will silently lose data because the connector doesn't recover from `NoSuchBucket`.

**Why it's wrong:** S3 bucket names are exact-match strings; trailing whitespace creates a name that doesn't exist.

**Fix:** Remove the trailing space → `"vqms-data-store-001"`.

---

#### 2. `.env.copy:150` vs `config/settings.py:197` — Bucket name divergence

`.env.copy` template defines:
```
S3_BUCKET_DATA_STORE=vqms-data-store
```

Settings default is `vqms-data-store-001 ` (with a `-001` suffix and a trailing space).

**Impact:** Different developers and environments will run against different buckets depending on whether `.env` is sourced or the default is used. One of the two is the real bucket; the other will hit `NoSuchBucket`.

**Fix:** Decide which is the real production bucket name and align both files.

---

### HIGH

#### 3. `src/services/draft_approval.py:356` — `json.dumps` instead of `orjson` for JSONB write

```python
await self._postgres.execute(
    """
    UPDATE workflow.case_execution
    SET draft_response = $1::jsonb, updated_at = $2
    WHERE query_id = $3
    """,
    json.dumps(draft),     # <-- inconsistent with rest of codebase
    TimeHelper.ist_now(),
    query_id,
)
```

**Impact:** The rest of the codebase uses `orjson` (see `src/orchestration/nodes/context_loading.py:170`, `src/services/polling.py`). `json.dumps` chokes on `datetime`, `Decimal`, and `UUID` if any of those leak into the draft snapshot — the `_recipient_email` and `_reply_to_message_id` fields are safe today, but any future field could break the approve flow at runtime.

**Fix:** `orjson.dumps(draft).decode("utf-8")`.

---

#### 4. `tests/test_email_intake.py` — Class-based async tests rely on `asyncio_mode = "auto"`

About 11 class methods (e.g. `TestProcessEmailHappyPath.test_process_email_returns_parsed_payload`) are async but lack explicit `@pytest.mark.asyncio` decorators. They work today only because `pyproject.toml` sets `asyncio_mode = "auto"`.

**Impact:** If anyone toggles back to `strict` (the safer default), every class-method test silently no-ops — they appear to pass while not actually executing.

**Fix:** Add `@pytest.mark.asyncio` decorators to every class-method async test. Compare with `tests/test_context_loading.py` which already does this correctly.

---

#### 5. `frontend/src/app/shared/models/triage.ts:42` — Mixed-case enum union for `ai_sentiment`

```typescript
readonly ai_sentiment:
  | 'POSITIVE' | 'NEUTRAL' | 'NEGATIVE' | 'FRUSTRATED'
  | 'positive' | 'neutral' | 'frustrated' | 'angry';
```

**Impact:** Type accepts both casings, so the compiler can't catch case mismatches. This directly enables bug #7 below.

**Fix:** Pick one casing (recommend uppercase to match backend `AnalysisResult.sentiment`) and remove the others.

---

### MEDIUM

#### 6. `src/services/closure.py:686-696` — Reopen SQS skip is silent

```python
if self._sqs is None:
    return
queue_url = self._settings.sqs_query_intake_queue_url
if not queue_url:
    logger.warning(
        "No intake queue configured — reopen not re-enqueued",
        ...
    )
    return
```

**Impact:** When `SQS_QUERY_INTAKE_QUEUE_URL` is empty (which is the **default** in `settings.py:207`), reopens flip the DB status but never re-enter the AI pipeline. The case shows as "reopened" but nothing actually processes it. Documented as "non-critical" but it's a feature regression.

**Fix:** Add startup validation in `app/lifespan.py` — if any `sqs_*_queue_url` is empty, fail fast or log loudly so the missing config isn't masked.

---

#### 7. `src/services/email_intake/service.py:277` — Same empty-queue-URL trap on email intake

```python
queue_url = self._settings.sqs_email_intake_queue_url   # default ""
...
await self._storage.persist_email_atomically(
    ...,
    outbox_queue_url=queue_url,
    outbox_payload=payload_json,
)
```

**Impact:** With an empty queue URL, the outbox row is written with no target. The polling drain in `src/services/polling.py` retries forever. Email processing appears to "succeed" but nothing reaches the LangGraph pipeline.

**Fix:** Same as #6 — startup validation on SQS URLs.

---

#### 8. `src/db/migrations/016_add_embedding_to_episodic_memory.sql` — Vector column added but no writer wires it up

```sql
ALTER TABLE memory.episodic_memory
    ADD COLUMN IF NOT EXISTS embedding vector(1024);
CREATE INDEX IF NOT EXISTS idx_episodic_embedding_hnsw
    ON memory.episodic_memory USING hnsw (embedding vector_cosine_ops)
    ...
    WHERE embedding IS NOT NULL;
```

The migration header explicitly says: "Follow-up: update `src/services/episodic_memory.py → EpisodicMemoryWriter` to call `llm_gateway.llm_embed(summary)` and write the embedding on every closure."

That follow-up has not been done.

**Impact:** Every new closure inserts NULL into `embedding`. The partial HNSW index never gets populated. The reviewer copilot tool `get_similar_past_queries` (`src/mcp_servers/reviewer/tools.py`) returns 0 rows. The Path C copilot is built on a feature that is effectively turned off.

**Fix:** Update `EpisodicMemoryWriter.save_closure` to embed the summary via `llm_embed` and persist it, plus a one-shot backfill script for existing rows.

---

#### 9. `src/orchestration/nodes/context_loading.py:151,200,221,248` — Bare `except Exception` patterns

Each non-critical step catches `Exception` and continues with a default. This is intentional graceful degradation per CLAUDE.md, **but** none of these blocks re-raise `asyncio.CancelledError` explicitly. On Python 3.12 `CancelledError` inherits from `BaseException`, so it's actually fine — flagged here only so the team is aware these blocks would silently swallow cancellation if the inheritance ever changes (or if someone catches `BaseException` by mistake).

**Fix:** Optional. If you want belt-and-braces:
```python
except asyncio.CancelledError:
    raise
except Exception:
    logger.warning(...)
```

---

#### 10. `Flow.md` claims Phase 5; code is at Phase 6

`app/lifespan.py` initializes:
- `ClosureService`
- `AutoCloseScheduler`
- `SlaMonitor`
- `DraftApprovalService`

All four are Phase 6 deliverables. `Flow.md` still says "Current State: Phase 5".

**Fix:** Refresh `Flow.md` to reflect the wired Phase 6 services.

---

## Findings — Frontend (Angular)

### HIGH

#### 11. `frontend/src/app/data/triage.store.ts:90 vs :120` — Sentiment normalization inconsistent

```typescript
// fromQueueItem (line 90):
ai_sentiment: 'neutral',                                    // lowercase

// fromPackage (line 120):
ai_sentiment: ar?.sentiment ?? 'NEUTRAL',                   // uppercase
```

**Impact:** The backend `AnalysisResult.sentiment` returns uppercase (e.g. `'NEUTRAL'`, `'NEGATIVE'`). Any template doing `case 'NEUTRAL':` mismatches the queue path. Any template doing `case 'neutral':` mismatches the detail path. This is the practical consequence of bug #5.

**Fix:** Normalize both producers to one casing. Recommend uppercase to match backend.

---

### MEDIUM

#### 12. `frontend/src/app/data/queries.store.ts:270-272` — Public `appendMessage` is a no-op

```typescript
appendMessage(_id: string, _msg: QueryMessage): void {
  // Reply-to-query is not wired to a backend endpoint yet — kept for UI compat.
}
```

**Impact:** Callers that "send a reply" think the message was persisted. Nothing happens. UI shows the optimistic update, then loses it on refresh.

**Fix:** Either wire it to the backend (preferred) or remove the method so callers fail loudly.

---

#### 13. `frontend/src/app/features/admin-drafts/draft-detail.page.ts:298` — `busy` only tracks `'sending'` mode

```typescript
mode = signal<ActionMode>('idle');
busy = computed<boolean>(() => this.mode() === 'sending');
```

`mode` can also be `'editing'` and `'rejecting'`. During the async `confirmReject()` call `busy()` is `false` because the mode is still `'rejecting'`, not `'sending'`. Buttons remain enabled and a user can double-click to fire two reject calls.

**Fix:** Either set `mode.set('sending')` immediately before every `await`, or maintain a separate `busy = signal<boolean>(false)` toggled around each async block.

---

#### 14. `frontend/src/app/features/email/message-viewer.ts:237` — `bypassSecurityTrustHtml` after a custom regex sanitizer

A custom regex strips dangerous tags before the body is passed to `bypassSecurityTrustHtml`. Vendor email bodies are user input — the regex is unlikely to catch all XSS vectors (event handlers in inline CSS, `javascript:` URLs in `srcdoc`, encoded payloads, etc.).

**Fix:** Use Angular's built-in sanitizer (don't bypass) or DOMPurify with a strict allow-list.

---

### LOW

#### 15. `frontend/src/app/data/copilot.service.ts` — Timestamps use HH:MM:SS format only

Messages older than 24 hours lose date context entirely.

**Fix:** Use ISO format for storage; format for display at render time.

---

## False Positives — Verified Not Bugs

These were flagged by the initial scans but turned out to be incorrect after manual verification:

| Claim | Verification |
|-------|---|
| "Reviewer copilot routes not registered in `app/routes.py`" | They ARE registered. `app/routes.py:13` imports `admin_drafts_router`, `:15` imports `copilot_triage_router`, `:33-34` calls `include_router` for both. |
| "`editSubject().trim()` calls `.trim()` on a signal function object" | This is correct Angular template syntax. `editSubject()` invokes the signal getter and returns a string; `.trim()` then operates on the string. |
| "Embedding dimensions 1024 vs 1536 mismatch across migrations" | Code is consistent at 1024 — `settings.py:101`, `settings.py:145`, `.env.copy:55`, migration `006`, migration `016` all use 1024. CLAUDE.md mentioning 1536 is stale documentation, not a bug. |
| "`closure.py._reenqueue_for_reopen` swallows errors silently on empty queue URL" | It logs a warning and returns. Documented behavior per the docstring at line 683 — graceful degradation. (Operational concern noted as bug #6 instead.) |

---

## Verification Commands

| # | How to verify |
|---|---|
| 1 | `python -c "from config.settings import Settings; print(repr(Settings().s3_bucket_data_store))"` — should print without trailing space |
| 2 | `diff <(grep S3_BUCKET .env.copy) <(grep s3_bucket_data_store config/settings.py)` |
| 3 | Add a `datetime` field to a draft snapshot in a test, call `approve_draft`, observe `TypeError: Object of type datetime is not JSON serializable` |
| 4 | Set `asyncio_mode = "strict"` in `pyproject.toml`, run `pytest tests/test_email_intake.py -v`, observe class-method tests reported as non-coroutine |
| 5, 11 | `grep -rn "ai_sentiment ===" frontend/src` — find places comparing against a single case |
| 6, 7 | Boot the app with empty `SQS_*_QUEUE_URL` env vars, submit a query/email, query the outbox table |
| 8 | Insert a closure via `EpisodicMemoryWriter.save_closure`, then `SELECT embedding FROM memory.episodic_memory WHERE query_id = ...` — will be NULL |
| 10 | `git log --since="2026-01-01" -- Flow.md` vs files added in `app/lifespan.py` for Phase 6 services |
| 12 | Click "reply" in the queries page; restart app; observe message gone |
| 13 | In Chrome DevTools, throttle network to "Slow 3G", click "Confirm reject" twice quickly — second click fires before first completes |
| 14 | Inject an email body containing `<img src=x onerror=alert(1)>` and view it |

---

## Recommended Fix Order

1. **Day 1 — Production-blocking:** #1 (S3 trailing space), #2 (bucket name alignment)
2. **Day 1 — Silent feature breakage:** #6, #7 (SQS URL validation), #8 (episodic memory writer)
3. **Day 2 — Type safety:** #5, #11 (sentiment casing)
4. **Day 2 — Operational:** #3 (orjson consistency), #4 (test markers), #13 (busy state), #14 (sanitizer)
5. **Backlog:** #9, #10, #12, #15

No code changes have been made as part of this audit.
