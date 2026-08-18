# Phase 6 — Publish Workflow Completion — Implementation Plan

**Status:** Planning only. No code, schema, or config changes in this step.
**Baseline:** HEAD `6f1d6b9`, working tree clean. Default model `qwen2.5:1.5b`.
**Scope:** Complete the publish workflow: history/status view, scheduled publishing, token refresh, post lifecycle.
**Constraint:** Phase 6 implementation will NOT start until this plan is approved.

---

## 1. Objective

Complete the publish workflow so the full pipeline is usable end-to-end. Phase 5 delivered the publish action (approved → published), but three gaps remain: (a) no visibility into publish history or status, (b) no scheduled publishing despite the `SCHEDULED` state existing in the state machine, and (c) OAuth token refresh is not automated — users must manually reconnect when tokens expire. Phase 6 fills these gaps without adding new features beyond what the original product discovery defined.

## 2. Current system baseline

**What exists (Phase 1–5F complete):**
- Full pipeline: idea → research → draft → SEO → checks → images → review → approve → publish
- State machine with `SCHEDULED` defined but not wired (`backend/pipeline/state.py:22`)
- `PublishJob` model with `run_at`, `status`, `retry_count` — created but never consumed by a scheduler (`backend/db/models.py:189-204`)
- `PublishLog` model for audit trail — populated on publish but not exposed in UI (`backend/db/models.py:206-216`)
- `BlogConnection` model with `token_encrypted` — tokens stored but no auto-refresh (`backend/db/models.py:37-48`)
- Publish API: `POST /api/articles/{id}/publish`, `POST .../publish/retry` (`backend/app/api/articles.py:340-388`)
- Blogger connection API: `GET /api/blogger/status`, `POST /blogger/connect`, `POST /blogger/disconnect` (`backend/app/api/blogger.py`)
- Frontend publish panel with publish/retry/update buttons (`frontend/src/components/articles/article-publish-panel.tsx`)
- Frontend settings page with blog connection UI (`frontend/src/app/(app)/settings/page.tsx`)
- Scheduler page: placeholder only (`frontend/src/app/(app)/scheduler/page.tsx`)
- Publishing page: placeholder only (`frontend/src/app/(app)/publishing/page.tsx`)
- Dashboard: 4 stat cards (ideas, research, articles, publish jobs) — no publish success/failure stats

**What does NOT exist:**
- APScheduler integration (no scheduler process)
- Scheduled publish UI (no date/time picker for scheduling)
- Publish history view (no list of past publish attempts with status)
- OAuth auto-refresh (manual reconnect only)
- Post deletion from Blogger
- Post status sync from Blogger
- Dashboard publish metrics (success rate, failure count)

## 3. Original-plan alignment

The product discovery doc (`docs/01-product-discovery.md`) defines:

| Requirement | Source | Phase 6 status |
|---|---|---|
| Save as draft, publish now, or schedule | §2, §14 | Schedule deferred → Phase 6B |
| Serial in-process scheduler (APScheduler) | §4, §14 | Not implemented → Phase 6B |
| Status state machine with explicit error + retry | §8 | Implemented (Phase 5); history view → 6A |
| Publish status tracked locally and synced from Blogger | §10 | Partial (local only); sync → 6C |
| Publish log audit trail | §11 | Implemented (Phase 5); UI → 6A |
| OAuth token refresh | §10 | Not automated → Phase 6C |
| Token refresh failure → clear reconnect | §10 | Manual reconnect exists; auto-refresh → 6C |
| Post deletion from Blogger | §10 | Not implemented → 6D |

Phase 6 completes the items the original plan intended for the publish workflow but deferred from Phase 5A-5G.

## 4. Phase 6 scope

**Does:**
- Publish history/status view (list of all publish attempts with status, errors, timestamps)
- Scheduled publishing (APScheduler consuming `PublishJob.run_at` rows)
- Schedule UI (date/time picker on approved articles)
- OAuth token auto-refresh (background refresh before expiry)
- Publish log audit view (per-article publish history)
- Dashboard publish metrics (success rate, failure count, scheduled count)
- Post deletion from Blogger (with state rollback)

**Does NOT:**
- Multi-blog switching (single-user, single-blog v1)
- Advanced analytics / traffic dashboards
- Bulk article generation or content calendars
- Social media sharing
- WordPress or other platforms
- AI image generation
- Local image downloading/re-hosting (remote URLs work)
- YouTube embed support
- Comment moderation

## 5. Non-goals

Explicitly excluded from Phase 6:
- Multi-user accounts / per-user Blogger connections
- Paid AI providers as mandatory path
- Team workflows, roles, review chains
- Indexing/ranking automation
- Local image generation (Stable Diffusion)
- Advanced SEO analytics beyond existing checks
- Content calendars or bulk scheduling
- Webhook integrations

## 6. Existing approval gate (MUST NOT CHANGE)

```
CHECKED / IMAGE_READY
        ↓  (approve → ready_for_review)
READY_FOR_REVIEW
        ↓  (approve → approved)
APPROVED
        ↓  (schedule → scheduled)  [NEW: wired in 6B]
SCHEDULED
        ↓  (scheduler fires → publishing)
PUBLISHING
        ↓  (success → published / failure → publish_failed)
PUBLISHED / PUBLISH_FAILED
```

**Hard rules (unchanged from Phase 5):**
- Publishing is ONLY possible from `APPROVED` or `SCHEDULED` state.
- Scheduling is ONLY possible from `APPROVED` state.
- An LLM can never trigger publishing or scheduling.
- A background worker can never bypass approval.
- The approve endpoint is the single human checkpoint.

---

## 7A — Publish History & Status View

### Objective

Replace the placeholder Publishing page with a real publish history view showing all publish attempts, their status, and details.

### User value

See what's been published, what failed, and what's pending. Know at a glance which articles are live on Blogger.

### Exact scope

- New backend endpoint: `GET /api/publish-log` — returns paginated publish log entries with article titles, status, timestamps, errors.
- New backend endpoint: `GET /api/articles/{id}/publish-log` — returns publish history for a specific article.
- Replace `frontend/src/app/(app)/publishing/page.tsx` placeholder with a real table/list view.
- Add publish status badges (published, failed, scheduled) to the articles list view.
- Dashboard: add publish success/failure/scheduled counts.

### Files/modules likely affected

- NEW: `backend/app/api/publish_log.py` — publish log endpoints
- MODIFIED: `backend/app/main.py` — mount publish log router
- MODIFIED: `backend/app/schemas/common.py` — PublishLogRead schema
- MODIFIED: `frontend/src/app/(app)/publishing/page.tsx` — replace placeholder
- NEW: `frontend/src/components/publishing/publish-history.tsx` — publish history component
- MODIFIED: `frontend/src/lib/api.ts` — add publish log API functions
- MODIFIED: `frontend/src/components/dashboard/dashboard-view.tsx` — add publish stats
- MODIFIED: `backend/app/api/dashboard.py` — add publish success/failure counts

### Database impact

None. Uses existing `PublishLog` and `PublishJob` tables.

### API impact

- `GET /api/publish-log` — new, paginated, returns `[{article_id, article_title, action, result, details, created_at}]`
- `GET /api/articles/{id}/publish-log` — new, returns per-article history
- `GET /api/dashboard` — extended with `publish_success_count`, `publish_fail_count`, `scheduled_count`

### Frontend impact

- Publishing page becomes a real table with columns: Article, Action, Result, Date, Error (if failed)
- Dashboard shows 6 stat cards instead of 4
- Articles list shows publish status badges

### Dependencies

None. Can be implemented independently.

### LLM requirements

None.

### External API requirements

None.

### Security considerations

- Publish log endpoints require auth (same as existing endpoints).
- Error details in publish log may contain sanitized errors — ensure no token leakage (already handled by `_sanitize_error`).

### Failure/recovery behavior

- If publish log query fails, show error state with retry button.
- Empty state shows "No publish history yet" with link to articles.

### Testing requirements

- Backend: test publish log endpoints (empty, populated, paginated, per-article).
- Frontend: test publish history rendering, empty state, error state.
- Integration: test dashboard stats accuracy.

### Acceptance criteria

1. Publishing page shows a list of all publish attempts with article title, action, result, date.
2. Failed attempts show error details.
3. Dashboard shows publish success/failure/scheduled counts.
4. Articles list shows publish status badges.
5. Empty state is shown when no publish history exists.
6. All existing tests continue to pass.

### Explicit non-goals

- Real-time publish status updates (polling is sufficient).
- Publish log export.
- Publish log filtering/search (can be added later).

---

## 7B — Scheduled Publishing

### Objective

Wire APScheduler into the backend process so articles can be scheduled for future publish times. Add a schedule UI to the article detail page.

### User value

Set a publish time for an approved article and have it auto-publish at that time. No need to be online at publish time.

### Exact scope

- Add APScheduler dependency.
- Create `backend/scheduler.py` — in-process APScheduler that scans `PublishJob` rows with `run_at <= now` and `status = "pending"`, transitions article to `PUBLISHING`, and fires the publish job.
- Scheduler starts on app startup (in `lifespan`), shuts down on app shutdown.
- New backend endpoint: `POST /api/articles/{id}/schedule` — creates a `PublishJob` with `run_at`, transitions `APPROVED → SCHEDULED`.
- New backend endpoint: `DELETE /api/articles/{id}/schedule` — cancels a scheduled job, transitions `SCHEDULED → APPROVED`.
- New backend endpoint: `GET /api/scheduled` — returns all scheduled articles with their `run_at` times.
- Frontend schedule UI: date/time picker on approved articles, "Schedule" button, "Cancel schedule" button.
- Frontend scheduler page: list of scheduled articles with countdown/time remaining.

### Files/modules likely affected

- MODIFIED: `backend/pyproject.toml` — add `apscheduler>=3.10`
- NEW: `backend/scheduler.py` — APScheduler integration
- MODIFIED: `backend/app/main.py` — start/stop scheduler in lifespan
- NEW: `backend/app/api/schedule.py` — schedule endpoints
- MODIFIED: `backend/app/main.py` — mount schedule router
- MODIFIED: `backend/app/schemas/common.py` — schedule schemas
- MODIFIED: `frontend/src/components/articles/article-publish-panel.tsx` — add schedule UI
- MODIFIED: `frontend/src/app/(app)/scheduler/page.tsx` — replace placeholder
- NEW: `frontend/src/components/scheduler/scheduled-list.tsx` — scheduled articles list
- MODIFIED: `frontend/src/lib/api.ts` — add schedule API functions

### Database impact

None. Uses existing `PublishJob` table with `run_at` and `status` columns.

### API impact

- `POST /api/articles/{id}/schedule` — new, body: `{ "run_at": "2026-08-20T14:00:00Z" }`, transitions `APPROVED → SCHEDULED`
- `DELETE /api/articles/{id}/schedule` — new, cancels schedule, transitions `SCHEDULED → APPROVED`
- `GET /api/scheduled` — new, returns `[{article_id, article_title, run_at, status}]`

### Frontend impact

- Article detail page gets a date/time picker when status is `APPROVED` or `SCHEDULED`.
- Scheduler page shows a list of scheduled articles with time remaining.
- Publish panel shows "Scheduled for {date}" when article is in `SCHEDULED` state.

### Dependencies

- Requires `apscheduler>=3.10` (new Python dependency, ~200KB, well-maintained).
- Can be implemented after 7A (publish history) or in parallel.

### LLM requirements

None.

### External API requirements

None.

### Security considerations

- Schedule endpoints require auth.
- Scheduler runs in-process — no external broker, no network exposure.
- `run_at` must be validated: must be in the future, must be within 30 days (Blogger limit).
- Timezone: use UTC in the database, convert in the UI.

### Failure/recovery behavior

- If scheduler fails to fire (process restart), the `PublishJob` row persists. On next startup, the scheduler scans for due jobs and fires them.
- If the publish job fails after scheduler fires, the article transitions to `PUBLISH_FAILED` (same as manual publish).
- If `run_at` is in the past when scheduler starts, fire immediately (catch-up).

### Testing requirements

- Backend: test scheduler startup/shutdown, due job scanning, past-due catch-up, future scheduling, cancel.
- Backend: test schedule endpoint (schedule, cancel, list, validation).
- Frontend: test schedule UI (date picker, schedule button, cancel button).
- Integration: test end-to-end schedule → fire → publish flow.

### Acceptance criteria

1. User can schedule an approved article for a future date/time.
2. Scheduled article transitions to `SCHEDULED` state.
3. Scheduler fires at the scheduled time and publishes the article.
4. User can cancel a scheduled article (returns to `APPROVED`).
5. Scheduler page shows all scheduled articles with time remaining.
6. Process restart does not lose scheduled jobs.
7. Past-due jobs fire on startup.
8. All existing tests continue to pass.

### Explicit non-goals

- Recurring scheduling (daily/weekly publish).
- Content calendar view.
- Timezone selection in UI (use browser local time, store UTC).
- Batch scheduling (one article at a time).

---

## 7C — OAuth Token Auto-Refresh

### Objective

Automatically refresh Blogger OAuth tokens before they expire, so users don't need to manually reconnect.

### User value

Set it and forget it. The Blogger connection stays alive without manual intervention.

### Exact scope

- Add background token refresh: on each publish API call, check token expiry. If expired or near-expiry (< 5 minutes), refresh automatically.
- If refresh fails, set `BlogConnection.status = "token_expired"` and log the failure.
- Add `BlogConnection.token_expires_at` column (additive migration) to track when the access token expires.
- On connect, store the expiry time from the OAuth token response.
- Add `POST /api/blogger/refresh` endpoint for manual token refresh (testing/debugging).
- Frontend: show token expiry status in settings (e.g., "Token expires in 45 minutes" or "Token expired — reconnect").

### Files/modules likely affected

- MODIFIED: `backend/services/blogger_client.py` — add token refresh logic
- MODIFIED: `backend/db/models.py` — add `token_expires_at` column to `BlogConnection`
- MODIFIED: `backend/db/base.py` — add migration for `token_expires_at`
- MODIFIED: `backend/app/api/blogger.py` — add refresh endpoint, update connect callback
- MODIFIED: `backend/app/schemas/common.py` — add `token_expires_at` to `BloggerStatusRead`
- MODIFIED: `frontend/src/app/(app)/settings/page.tsx` — show token expiry status

### Database impact

Additive column on `BlogConnection`:

| Column | Type | Default | Purpose |
|---|---|---|---|
| `token_expires_at` | `DateTime` | `None` | When the access token expires |

Migration via `init_db()` with idempotent `PRAGMA table_info` check (same pattern as Phase 4C/5D).

### API impact

- `POST /api/blogger/refresh` — new, triggers manual token refresh, returns updated status.
- `GET /api/blogger/status` — extended with `token_expires_at` field.

### Frontend impact

- Settings page shows token expiry time.
- If token is expired or near-expiry, show warning with "Refresh now" button.

### Dependencies

None. Can be implemented independently.

### LLM requirements

None.

### External API requirements

None. Uses existing Blogger OAuth token endpoint (already used by `google-auth-oauthlib`).

### Security considerations

- Token refresh uses the same encrypted token storage.
- Refresh failure is logged but not exposed in detail to the user.
- No new attack surface — refresh uses the existing OAuth client credentials.

### Failure/recovery behavior

- If refresh fails (revoked token): `BlogConnection.status = "token_expired"`, UI shows "Reconnect".
- If refresh succeeds: update `token_encrypted` and `token_expires_at`.
- If network is down during refresh: token expiry clock continues; user sees "Token expired" when they try to publish.

### Testing requirements

- Backend: test auto-refresh on publish, refresh failure handling, expiry tracking.
- Backend: test manual refresh endpoint.
- Frontend: test token expiry display, refresh button.
- Integration: test connect → wait → auto-refresh → publish flow.

### Acceptance criteria

1. OAuth tokens are automatically refreshed before expiry.
2. Token expiry time is stored and displayed in settings.
3. Failed refresh sets connection status to "token_expired".
4. Manual refresh endpoint works.
5. Users don't need to manually reconnect for token expiry.
6. All existing tests continue to pass.

### Explicit non-goals

- Refresh token rotation (Google handles this).
- Multi-account token management.
- Token refresh webhooks.

---

## 7D — Post Deletion & Cleanup

### Objective

Allow users to delete published posts from Blogger and clean up local state.

### User value

Remove posts that were published by mistake or are no longer wanted on the blog.

### Exact scope

- Add `DELETE /api/articles/{id}/publish` endpoint — deletes the Blogger post, resets article state.
- Add `BloggerClient.delete_post()` method using Blogger API `posts.delete`.
- State transition: `PUBLISHED → DRAFT` (allows re-editing and re-publishing).
- Add "Delete from Blogger" button to the publish panel (with confirmation dialog).
- Add `PublishLog` entry for deletion actions.

### Files/modules likely affected

- MODIFIED: `backend/services/blogger_client.py` — add `delete_post()` method
- MODIFIED: `backend/pipeline/publish.py` — add delete service function
- MODIFIED: `backend/app/api/articles.py` — add DELETE publish endpoint
- MODIFIED: `backend/pipeline/state.py` — add `PUBLISHED → DRAFT` transition
- MODIFIED: `frontend/src/components/articles/article-publish-panel.tsx` — add delete button

### Database impact

None. Uses existing models.

### API impact

- `DELETE /api/articles/{id}/publish` — new, deletes Blogger post, resets article to `DRAFT`.

### Frontend impact

- Publish panel shows "Delete from Blogger" button when article is `PUBLISHED`.
- Confirmation dialog: "Delete this post from Blogger? This cannot be undone."

### Dependencies

None. Can be implemented independently.

### LLM requirements

None.

### External API requirements

Blogger API `posts.delete` (already documented in product discovery §10).

### Security considerations

- Delete endpoint requires auth.
- Confirmation dialog prevents accidental deletion.
- Publish log records the deletion.

### Failure/recovery behavior

- If Blogger API delete fails (network error, 404): show error, article stays `PUBLISHED`.
- If delete succeeds but local state update fails: article stays `PUBLISHED` locally (Blogger post is deleted). User can retry or manually reconcile.

### Testing requirements

- Backend: test delete endpoint (happy path, 404, network error).
- Backend: test state transition `PUBLISHED → DRAFT`.
- Frontend: test delete button visibility, confirmation dialog.
- Integration: test publish → delete → re-publish flow.

### Acceptance criteria

1. User can delete a published post from Blogger.
2. Article returns to `DRAFT` state after deletion.
3. Deletion is recorded in publish log.
4. Confirmation dialog prevents accidental deletion.
5. Failed deletion shows error and keeps article in `PUBLISHED` state.
6. All existing tests continue to pass.

### Explicit non-goals

- Bulk deletion.
- Soft delete (trash before permanent delete).
- Unpublish without delete (Blogger doesn't support unpublish via API).

---

## 8. Architecture impact

Phase 6 adds one new dependency (`apscheduler`) and one new background process (in-process scheduler). The architecture remains a modular monolith:

```
┌─────────────────────────────── LOCALHOST ───────────────────────────────┐
│                                                                          │
│  ┌─────────────────────┐          ┌───────────────────────────────────┐ │
│  │  Next.js frontend    │  REST    │  FastAPI backend (single proc)    │ │
│  │  (UI console:        │ ──────►  │                                   │ │
│  │   ideas, review,     │          │  app/ (routing, schemas, auth)    │ │
│  │   publish, settings) │          │  pipeline/ (core modules)         │ │
│  └─────────────────────┘          │  scheduler.py (APScheduler)  [NEW]│ │
│                                    │  services/ (research, ai, image,  │ │
│                                    │   seo, checks, publish)            │ │
│                                    │  db/ (SQLite + SQLAlchemy)         │ │
│                                    └──────────────┬────────────────────┘ │
│                                        ▼          ▼         ▼           │
│                                   ┌─────────┐ ┌──────────┐ ┌───────────┐│
│                                   │ Ollama   │ │ Free web │ │ Blogger   ││
│                                   │ (local)  │ │ APIs     │ │ API v3    ││
│                                   └─────────┘ └──────────┘ └───────────┘│
└──────────────────────────────────────────────────────────────────────────┘
```

The scheduler runs inside the FastAPI process (same as the existing serial runner). No new processes, no message brokers, no Redis.

## 9. State-machine impact

| Transition | Before Phase 6 | After Phase 6 |
|---|---|---|
| `APPROVED → SCHEDULED` | Defined but not wired | Wired via schedule endpoint |
| `SCHEDULED → PUBLISHING` | Defined but not wired | Wired via APScheduler |
| `PUBLISHED → DRAFT` | Not defined | Added in 7D (post deletion) |

All other transitions remain unchanged. The approval gate is preserved.

## 10. Database impact

| Change | Type | Migration |
|---|---|---|
| `BlogConnection.token_expires_at` | Additive column | `init_db()` PRAGMA check (Phase 6C) |

No destructive changes. No new tables. No schema changes to existing columns.

## 11. API impact

| Endpoint | Method | Phase | Purpose |
|---|---|---|---|
| `/api/publish-log` | GET | 6A | Paginated publish history |
| `/api/articles/{id}/publish-log` | GET | 6A | Per-article publish history |
| `/api/articles/{id}/schedule` | POST | 6B | Schedule article for future publish |
| `/api/articles/{id}/schedule` | DELETE | 6B | Cancel scheduled article |
| `/api/scheduled` | GET | 6B | List all scheduled articles |
| `/api/blogger/refresh` | POST | 6C | Manual token refresh |
| `/api/articles/{id}/publish` | DELETE | 6D | Delete published post from Blogger |

All endpoints require auth (existing `X-Auth-Token` pattern). No public endpoints added.

## 12. Frontend impact

| Page | Change | Phase |
|---|---|---|
| Publishing page | Replace placeholder with publish history table | 6A |
| Dashboard | Add publish success/failure/scheduled counts | 6A |
| Articles list | Add publish status badges | 6A |
| Article detail | Add schedule date/time picker | 6B |
| Scheduler page | Replace placeholder with scheduled articles list | 6B |
| Settings page | Show token expiry status, refresh button | 6C |
| Article detail | Add "Delete from Blogger" button | 6D |

## 13. Security

| Threat | Mitigation |
|---|---|
| Scheduler fires publish without approval | Scheduler only processes `SCHEDULED` articles (already approved) |
| Token refresh exposes credentials | Same encryption-at-rest as existing tokens |
| Post deletion without confirmation | Frontend confirmation dialog; backend logs action |
| Schedule endpoint allows past dates | Backend validates `run_at` is in the future |
| APScheduler in-process failure | Jobs persist in SQLite; retry on restart |

## 14. Resource constraints

| Resource | Impact | Notes |
|---|---|---|
| RAM | +5-10MB | APScheduler is lightweight; in-process |
| CPU | Negligible | Scheduler polls every 30 seconds; no heavy computation |
| Disk | +1 row per scheduled article | `PublishJob` table already exists |
| Network | +1 request per scheduled publish | Same as manual publish |
| Ollama | No change | No new LLM calls |
| Dependencies | +1 (`apscheduler`) | ~200KB, well-maintained |

Total estimated additional RAM: <10MB. Fits comfortably in the 8GB budget.

## 15. LLM usage

None. Phase 6 adds no new LLM calls. All operations are deterministic API calls and database queries.

## 16. External services

| Service | Usage | Phase |
|---|---|---|
| Blogger API v3 `posts.delete` | Post deletion | 6D |
| Blogger OAuth token endpoint | Token refresh | 6C |

No new external services. No paid APIs.

## 17. Testing strategy

### Backend tests

| Category | Tests | Phase |
|---|---|---|
| Publish log API | Empty state, populated, paginated, per-article | 6A |
| Dashboard stats | Publish counts accurate | 6A |
| Scheduler | Startup, shutdown, due job scanning, past-due catch-up | 6B |
| Schedule API | Schedule, cancel, list, validation (past date, missing article) | 6B |
| Token refresh | Auto-refresh on publish, refresh failure, expiry tracking | 6C |
| Manual refresh | Refresh endpoint, success/failure | 6C |
| Post deletion | Delete endpoint, 404 handling, state rollback | 6D |
| State transitions | `PUBLISHED → DRAFT`, `APPROVED → SCHEDULED`, `SCHEDULED → APPROVED` | 6B, 6D |

### Frontend tests

| Category | Tests | Phase |
|---|---|---|
| Publish history | Table rendering, empty state, error state | 6A |
| Dashboard stats | 6-card layout, correct counts | 6A |
| Schedule UI | Date picker, schedule button, cancel button, validation | 6B |
| Scheduler page | Scheduled list, countdown, empty state | 6B |
| Token expiry | Expiry display, refresh button, expired warning | 6C |
| Delete button | Visibility, confirmation dialog, disabled states | 6D |

### Test counts (estimated)

- Backend: 614 existing + ~80 new = ~694 total
- Frontend: 73 existing + ~30 new = ~103 total

## 18. Failure/recovery strategy

| Failure | Behavior | Recovery |
|---|---|---|
| Scheduler fails to fire | `PublishJob` persists in SQLite | Fires on next startup (catch-up) |
| Process restart during scheduled wait | Job persists; scheduler rescans on startup | Automatic |
| Token refresh fails during publish | `PUBLISHING → PUBLISH_FAILED` | User reconnects OAuth |
| Post delete fails (Blogger 404) | Article stays `PUBLISHED` | User retries or ignores |
| Schedule endpoint receives past date | 400 Bad Request | User selects future date |
| APScheduler misconfiguration | Scheduler fails to start; manual publish still works | Log error; app remains functional |

## 19. Migration strategy

All database changes are additive columns with defaults. No destructive changes, no data migration needed. Same pattern as Phase 4C and 5D:

```python
# In init_db()
columns = {row[1] for row in db.execute("PRAGMA table_info(blog_connections)").fetchall()}
if "token_expires_at" not in columns:
    db.execute("ALTER TABLE blog_connections ADD COLUMN token_expires_at DATETIME")
```

## 20. Acceptance criteria (all phases)

1. Publishing page shows a table of all publish attempts with status and timestamps.
2. Dashboard shows publish success/failure/scheduled counts.
3. User can schedule an approved article for a future date/time.
4. Scheduler fires at the scheduled time and publishes the article.
5. User can cancel a scheduled article.
6. OAuth tokens are automatically refreshed before expiry.
7. Token expiry is displayed in settings.
8. User can delete a published post from Blogger.
9. Deleted posts return to `DRAFT` state.
10. All existing tests continue to pass.
11. New tests cover all new functionality.
12. No paid APIs, no new LLM calls, no new workers.

## 21. Rollback strategy

Each subphase is independently reversible:
- **6A:** Remove publish log endpoints and UI. No data changes.
- **6B:** Remove APScheduler dependency and schedule endpoints. `PublishJob` rows remain but are unused.
- **6C:** Remove token refresh logic. Tokens expire normally; manual reconnect works.
- **6D:** Remove delete endpoint and button. Published posts remain on Blogger.

No migration rollback needed (additive columns are harmless if unused).

## 22. Dependencies

| Dependency | Type | Phase | Size | Justification |
|---|---|---|---|---|
| `apscheduler>=3.10` | Python package | 6B | ~200KB | In-process scheduler for scheduled publishing |

No other new dependencies. All other changes use existing libraries.

## 23. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| APScheduler in-process crash | Scheduled jobs don't fire | Jobs persist in SQLite; catch-up on restart |
| Token refresh race condition | Two refresh attempts simultaneously | Use existing serial runner pattern; single-writer |
| Blogger API delete rate limit | Deletion fails | Single-user, low volume; retry on 429 |
| Timezone confusion in scheduling | Wrong publish time | Store UTC, convert in UI, show timezone |
| Future `run_at` validation gap | Schedule too far in future | Cap at 30 days (Blogger limit) |

## 24. MUST HAVE / SHOULD HAVE / LATER / OUT OF SCOPE

### MUST HAVE (Phase 6A-6D)
- Publish history view (6A)
- Dashboard publish stats (6A)
- Scheduled publishing with APScheduler (6B)
- Schedule UI with date/time picker (6B)
- OAuth token auto-refresh (6C)
- Post deletion from Blogger (6D)

### SHOULD HAVE (can be deferred to Phase 6.1 if needed)
- Token expiry display in settings (6C) — nice-to-have, not blocking
- Publish status badges on articles list (6A) — cosmetic

### LATER (after Phase 6)
- Post status sync from Blogger (check Blogger for status changes)
- Recurring scheduling (daily/weekly)
- Content calendar view
- Bulk scheduling
- Publish log export
- Publish log filtering/search

### OUT OF SCOPE (explicitly excluded)
- Multi-user accounts
- WordPress or other platforms
- AI image generation
- Local image downloading
- Social media sharing
- Analytics dashboards
- Content calendars
- Team workflows
- Indexing/ranking automation

## 25. CEO review

**Does this directly advance the existing product?** Yes. The publish workflow is incomplete without visibility (history), automation (scheduling), and maintenance (token refresh, deletion). These are the minimum gaps to make the pipeline truly usable.

**Is it necessary now?** Yes. Without scheduling, the user must manually publish at the right time. Without token refresh, the connection breaks silently. Without history, there's no audit trail. These are core workflow gaps, not nice-to-haves.

**Can it be deferred?** Partially. 6A (history) and 6C (token refresh) are most urgent — they affect daily usage. 6B (scheduling) is important but not blocking for manual publish. 6D (deletion) is least urgent — can be done via Blogger UI. Recommended: implement all four, but 6D can be cut if time is tight.

**Does it introduce unnecessary complexity?** No. APScheduler is a well-chosen, lightweight dependency that the original plan already anticipated. Token refresh is a natural extension of the existing OAuth flow. Deletion is a single API call.

**Does it require paid services?** No.

**Does it create operational burden?** Minimal. APScheduler runs in-process with no external dependencies. Token refresh is automatic.

**Does it threaten the approval/publishing safety model?** No. Scheduling only works from `APPROVED` state. Deletion requires explicit user action with confirmation.

**Recommendation:** Proceed with 6A-6D as specified. The sequence is independently valuable — each subphase delivers testable, shippable increments.

## 26. Engineering review

**Architecture:** The APScheduler approach is the right call for a single-user, single-process app. No Redis, no Celery, no external broker. The scheduler runs inside the FastAPI process and uses SQLite as its job store — exactly what the original plan specified.

**Data model:** Reusing `PublishJob` for scheduling is correct. The `run_at` column already exists and is indexed. Adding `token_expires_at` to `BlogConnection` is minimal and non-breaking.

**State machine:** Adding `PUBLISHED → DRAFT` for deletion is clean. The transition is reversible and doesn't affect the approval gate. `APPROVED → SCHEDULED` is already defined and just needs wiring.

**Concurrency:** The serial runner pattern extends naturally to scheduled publishes. APScheduler's default pool is `ThreadPoolExecutor(max_workers=1)` — matches the existing single-writer model.

**Idempotency:** Scheduled publishes use the same `start_background_publish` path as manual publishes — same dedup, same idempotent update logic.

**Security:** Token refresh uses the same encrypted storage. No new attack surface. Deletion is a simple API call with the same auth model.

**Concern 1:** APScheduler's `BackgroundScheduler` relies on threading. If the FastAPI process uses `uvicorn` with multiple workers (not the case today, but possible in the future), the scheduler would fire multiple times. Mitigation: document that the app must run with a single worker.

**Concern 2:** The `PUBLISHED → DRAFT` transition for deletion means the article can be re-published. This is intentional (allows correction) but should be logged clearly.

**Concern 3:** Token refresh timing — if the refresh happens during a publish call and fails, the publish fails. This is the correct behavior (fail-fast), but the error message should distinguish "token expired" from "publish failed."

## 27. gstack planning review

**MUST-FIX planning issues:** None identified.

**SHOULD-FIX planning issues:**
- S1: Add `BloggerClient.delete_post()` to the Phase 5 completion record — it's a new API surface that should be documented.
- S2: APScheduler worker count should be explicitly set to 1 in the configuration to prevent future multi-worker issues.
- S3: Consider adding a `PublishJob.scheduled_by` field to distinguish user-scheduled from system-scheduled jobs (currently all are user-scheduled, but future automation may need this).

**Rejected scope:** Multi-blog, content calendars, bulk scheduling, analytics — all correctly deferred.

**Security concerns:** Addressed in §13. No gaps identified.

**Architecture risks:** Low. The serial runner pattern and in-process scheduler are well-proven for this scale.

## 28. Recommended implementation sequence

1. **6A** (Publish History) — no dependencies, immediate user value, establishes the publish log UI pattern.
2. **6C** (Token Auto-Refresh) — no dependencies, critical for reliability, small scope.
3. **6B** (Scheduled Publishing) — depends on 6A for the scheduler page pattern, adds APScheduler dependency.
4. **6D** (Post Deletion) — no dependencies, smallest scope, can be done last.

6A and 6C can be implemented in parallel. 6B should come after 6A (reuses the publish history UI pattern). 6D is independent and can slot in anywhere.

## 29. Approval checkpoint

- [ ] Phase 6 scope approved (6A-6D)
- [ ] APScheduler dependency approved
- [ ] `PUBLISHED → DRAFT` state transition approved
- [ ] Token expiry tracking approved
- [ ] Post deletion workflow approved
- [ ] Implementation sequence approved (6A → 6C → 6B → 6D)

---

## GSTACK REVIEW REPORT

Status: PLAN_READY. Planning doc reviewed (CEO + Eng lenses + critical pass). No code modified.
