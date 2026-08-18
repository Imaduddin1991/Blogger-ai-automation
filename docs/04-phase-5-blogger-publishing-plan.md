# Phase 5 — Blogger Publishing — Implementation Plan

**Status:** Planning only. No code, schema, or config changes in this step.
**Baseline:** HEAD `466d91e`, working tree clean. Default model `qwen2.5:1.5b`.
**Scope:** Blogger API integration, publish workflow, OAuth, frontend UX.
**Constraint:** Phase 5 implementation will NOT start until this plan is approved.

---

## 1. Objective

Complete the end-to-end pipeline: idea -> research -> draft -> SEO -> checks -> images -> review -> **publish to Blogger**. Phase 5 adds the publishing layer so an approved article can be sent to Blogger as a draft or live post, with full status tracking, retry, and duplicate prevention.

## 2. Current system baseline

**What exists (Phase 1–4F complete):**
- Article state machine with all publishing states already defined (`APPROVED`, `SCHEDULED`, `PUBLISHING`, `PUBLISHED`, `PUBLISH_FAILED`) — `backend/pipeline/state.py:22-25`
- `BlogConnection` model (id, blog_id, blog_url, token_encrypted, status) — `backend/db/models.py:37-48`
- `PublishJob` model (article_id, run_at, status, error, retry_count, published_at) — `backend/db/models.py:183-194`
- `PublishLog` model (article_id, action, result, details) — `backend/db/models.py:197-207`
- `Article.blog_id` foreign key to `BlogConnection` — `backend/db/models.py:109`
- `Article.labels` (JSON array) — already populated by SEO stage
- `Article.slug`, `seo_title`, `meta_description` — already populated
- Approval gate: `approve_article()` in `backend/pipeline/article/service.py:262-282`
- Serial runner with job keys — `backend/services/runner.py`
- Settings API (key/value DB) — `backend/app/api/settings.py`
- Frontend `statusLabel()` already maps `scheduled`, `publishing`, `published`, `publish_failed` — `frontend/src/lib/api.ts:286-292`
- Markdown renderer with HTML conversion — `frontend/src/lib/markdown.ts`
- Image URL + attribution metadata — stored per selected image
- `encryption_key` and `local_auth_token` settings already in config — `backend/app/config.py:36-37`

**What does NOT exist:**
- Blogger OAuth flow (no `google-auth-oauthlib` yet)
- Blogger API client (no `blogger_client.py`)
- Publishing service (`pipeline/publish.py` does not exist)
- Markdown-to-HTML converter for Blogger (existing renderer is frontend-only)
- Publish API endpoints
- Frontend publishing UX
- Blog connection UI

## 3. Original-plan alignment

The product discovery doc (`docs/01-product-discovery.md`) specifies:

| Requirement | Source | Phase 5 status |
|---|---|---|
| OAuth 2.0 (authorization code + refresh token, offline access) | §10 | Will implement |
| Scope: `https://www.googleapis.com/auth/blogger` | §10 | Will implement |
| `posts.insert` (draft/live), `posts.patch`, `posts.get`, `posts.list`, `posts.delete` | §10 | Will implement (insert + patch + get + list; delete deferred) |
| `blogs.getByUrl` to resolve blog ID | §10 | Will implement |
| Save as draft, publish now, or schedule | §2, §14 | Will implement (publish now + save as draft; schedule deferred to 5H) |
| Publish status tracked locally and synced from Blogger | §10 | Will implement |
| One blog connection in v1 | §2 | Will implement |
| Post HTML built from article body + images + SEO meta | §10 | Will implement |
| Token encrypted at rest, restricted file perms, never in logs | §11 | Will implement |
| `.env` secrets, `.env.example` committed | §11 | Will implement |
| Publish log audit trail | §11 | Will use existing `PublishLog` model |

## 4. Phase 5 scope

**Does:**
- Blogger OAuth 2.0 connect/reconnect flow (Desktop app type)
- Blog selection (one active blog)
- Token storage (encrypted at rest)
- Markdown-to-HTML conversion for Blogger
- Image embedding in post HTML with attribution
- `posts.insert` (draft or live)
- `posts.patch` (update existing post)
- `posts.get` / `posts.list` (status sync)
- `blogs.getByUrl` (blog ID resolution)
- Publish state machine transitions
- Idempotent publish (no duplicate posts)
- Publish retry with backoff
- Publish audit log
- Frontend: blog connection status, publish button, progress, result
- API: publish, connection status, blog list

**Does NOT:**
- Scheduling (APScheduler integration — deferred; manual publish only in 5A-5G)
- Post deletion/unpublish (deferred to later)
- Multi-blog switching (one blog in v1)
- Post scheduling via `publishDate` (deferred)
- Image downloading/re-hosting (remote URLs only)
- AI image generation
- WordPress or other platforms
- Social media sharing
- Analytics or traffic dashboards

## 5. Non-goals

Explicitly excluded from Phase 5:
- APScheduler publish scheduling (the `PublishJob.run_at` + scheduler is defined but not wired in 5A-5G; deferred)
- Post deletion from Blogger
- Post unpublishing
- Multi-user / multi-account
- OAuth token refresh failure auto-reconnect (manual reconnect in v1)
- HTML sanitization beyond basic script/event-handler stripping (Blogger itself sanitizes)

## 6. Existing approval gate (MUST NOT CHANGE)

```
CHECKED / IMAGE_READY
        ↓  (approve → ready_for_review)
READY_FOR_REVIEW
        ↓  (approve → approved)
APPROVED
        ↓  (publish → publishing)
PUBLISHING
        ↓  (success → published / failure → publish_failed)
PUBLISHED / PUBLISH_FAILED
```

**Hard rules:**
- Publishing is ONLY possible from `APPROVED` state.
- Selecting an image never triggers publishing.
- An LLM can never trigger publishing.
- A background worker can never bypass approval.
- The approve endpoint is the single human checkpoint.

## 7. Blogger API architecture

### API surface (v3, REST)

| Operation | HTTP | Endpoint | Used in Phase 5 |
|---|---|---|---|
| List user's blogs | GET | `/blogger/v3/users/self/blogs` | Yes (blog selection) |
| Get blog by URL | GET | `/blogger/v3/blogs/byurl?url=...` | Yes (blog resolution) |
| Get blog | GET | `/blogger/v3/blogs/{blogId}` | Yes (connection test) |
| List posts | GET | `/blogger/v3/blogs/{blogId}/posts` | Yes (status sync) |
| Get post | GET | `/blogger/v3/blogs/{blogId}/posts/{postId}` | Yes (status sync) |
| Insert post | POST | `/blogger/v3/blogs/{blogId}/posts` | Yes (publish) |
| Update post | PUT | `/blogger/v3/blogs/{blogId}/posts/{postId}` | Yes (re-publish/update) |
| Delete post | DELETE | `/blogger/v3/blogs/{blogId}/posts/{postId}` | No (deferred) |

### Client approach

Use `httpx` (already in the project) for REST calls. Do NOT add `google-api-python-client` (heavy transitive deps). Use `google-auth-oauthlib` for the OAuth flow only. After obtaining credentials, make direct httpx calls with the bearer token.

This keeps Phase 5 deps minimal:
- `google-auth-oauthlib` (~50KB, for OAuth flow)
- `google-auth` (transitive dep of google-auth-oauthlib)

No other new Python deps.

## 8. Authentication/OAuth design

### Flow (Desktop app type, localhost redirect)

1. User clicks "Connect Blogger" in the frontend.
2. Backend generates an authorization URL with `google-auth-oauthlib`'s `InstalledAppFlow` (scope: `https://www.googleapis.com/auth/blogger`, redirect: `http://127.0.0.1:{port}/api/blogger/callback`).
3. User opens the URL in their browser, consents.
4. Google redirects to localhost callback with auth code.
5. Backend exchanges code for access + refresh tokens.
6. Backend calls `blogs.getByUrl` or `users/self/blogs` to resolve the blog list.
7. Backend stores tokens in `BlogConnection.token_encrypted` (encrypted with `ENCRYPTION_KEY` from `.env`).
8. Backend sets `BlogConnection.status = "connected"`.

### Token management

- Access tokens are short-lived (~1 hour). Refresh tokens are long-lived.
- On each publish API call, use `google-auth` credentials to auto-refresh.
- If refresh fails (token revoked): set `BlogConnection.status = "token_expired"`, show "Reconnect" in UI.
- Tokens are encrypted at rest using `cryptography.fernet` (symmetric, key from `ENCRYPTION_KEY`).
- Tokens are NEVER logged, NEVER committed, NEVER stored in plaintext.

### Blog resolution

- `BlogConnection.blog_url` is set by the user (e.g., `https://myblog.blogspot.com`).
- On connect, resolve `blog_id` via `GET /blogger/v3/blogs/byurl?url={blog_url}`.
- Store `blog_id` in `BlogConnection.blog_id`.
- On publish, use `blog_id` for all API calls.

### Configuration (env vars)

```
BLOGGER_CLIENT_ID=     # Google Cloud OAuth client ID
BLOGGER_CLIENT_SECRET= # Google Cloud OAuth client secret
BLOGGER_REDIRECT_URI=http://127.0.0.1:8000/api/blogger/callback
ENCRYPTION_KEY=        # Fernet key for token encryption (generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
```

## 9. Publishing state machine

The existing state machine already defines all needed transitions. No new states are required.

### Current transitions (from `backend/pipeline/state.py:35-51`)

```
APPROVED → {SCHEDULED, READY_FOR_REVIEW, PUBLISHING}
SCHEDULED → {PUBLISHING, APPROVED}
PUBLISHING → {PUBLISHED, PUBLISH_FAILED, APPROVED}
PUBLISH_FAILED → {PUBLISHING, SCHEDULED, APPROVED}
PUBLISHED → {}  (terminal)
```

### Phase 5 usage

| User action | From state | Transition | Notes |
|---|---|---|---|
| Click "Publish now" | APPROVED | APPROVED → PUBLISHING → PUBLISHED | Immediate publish |
| Click "Save as draft" | APPROVED | APPROVED → PUBLISHING → PUBLISHED | Publish as Blogger draft (isDraft=true) |
| Publish fails | PUBLISHING | PUBLISHING → PUBLISH_FAILED | Error recorded |
| Retry publish | PUBLISH_FAILED | PUBLISH_FAILED → PUBLISHING | Re-queue |
| Edit after publish | PUBLISHED | PUBLISHED → (unreachable in v1) | Deferred |

### Why these states are required

| State | Required? | Reason |
|---|---|---|
| `APPROVED` | Yes (exists) | Human gate; publish-only from here |
| `PUBLISHING` | Yes (exists) | In-flight API call; UI shows spinner; prevents duplicate clicks |
| `PUBLISHED` | Yes (exists) | Terminal success; stores Blogger post ID + URL |
| `PUBLISH_FAILED` | Yes (exists) | Named error + retry; article not lost |
| `SCHEDULED` | Deferred | Only needed when APScheduler is wired; not in 5A-5G |

## 10. Idempotency and duplicate prevention

### Duplicate publish prevention

1. **State gate:** Publish only from `APPROVED`. Once `PUBLISHING` starts, the state transitions immediately, blocking concurrent publishes.
2. **Job key:** `start_background_publish(article_id)` uses a unique key `publish:{article_id}` in the serial runner. Submitting while already running is a no-op.
3. **Frontend:** Publish button disabled when `running` is true or status is not `approved`.
4. **Backend:** `_assert_publishable()` checks article status is `APPROVED` and no job is running.

### Idempotency

- If an article already has `blogger_post_id` set (previous publish succeeded), use `posts.update` (PUT) instead of `posts.insert` (POST). This prevents duplicate posts for the same article.
- If the API call fails mid-response (network timeout), check `posts.list` for a post with matching title before retrying. If found, update instead of insert.
- `PublishJob` tracks `article_id` + `status` — only one active job per article.

### Retry behavior

- `PUBLISH_FAILED` articles can be retried via the frontend "Retry" button.
- Retry re-queues the publish job. If `blogger_post_id` exists, it uses `posts.update`; otherwise `posts.insert`.
- No automatic retry (no APScheduler in 5A-5G). Manual retry only.
- `PublishJob.retry_count` increments on each attempt.

## 11. Content/HTML contract

### Markdown-to-HTML conversion

The existing frontend markdown renderer (`frontend/src/lib/markdown.ts`) is frontend-only and limited (no tables, no nested lists, no images). For Blogger publishing, a backend converter is needed.

**Approach:** Use Python's `markdown` library (lightweight, ~100KB) to convert the article body Markdown to HTML. This is a new dependency but justified — the frontend renderer is insufficient for Blogger's HTML requirements.

**Alternative (zero new deps):** Extend the existing minimal renderer in a new backend module. However, this reinvents a well-solved problem and would miss edge cases (tables, nested lists, etc.).

**Decision:** Add `markdown` to Python deps. It is small, maintained, and the right tool.

### Post HTML structure

Blogger expects the `content` field to be HTML. The post body is constructed as:

```html
<article>
  <h1>{seo_title or title}</h1>

  <!-- Body content (markdown converted to HTML) -->
  {converted_html}

  <!-- Selected images with attribution -->
  <figure>
    <img src="{image.url}" alt="{image.alt}" referrerpolicy="no-referrer" loading="lazy" />
    <figcaption>{image.caption}</figcaption>
  </figure>
  <p class="image-attribution">{image.attribution}</p>

  <!-- Source links (optional) -->
  <section class="sources">
    <h2>Sources</h2>
    <ul>
      <li><a href="{source.url}">{source.title}</a></li>
    </ul>
  </section>
</article>
```

### Blogger field mapping

| Blogger field | Source | Notes |
|---|---|---|
| `title` | `article.seo_title` or `article.title` | Capped at Blogger's limit |
| `content` | Constructed HTML (above) | Sanitized before sending |
| `labels` | `article.labels` | Up to Blogger's label limit |
| `isDraft` | User choice (draft vs. live) | `true` = save as draft, `false` = publish live |

### HTML sanitization

Before sending to Blogger, strip:
- `<script>` tags and event handlers (`onclick`, `onerror`, etc.)
- `javascript:` URLs
- `data:` URLs
- `vbscript:` URLs
- `<iframe>` tags (except YouTube embeds if desired — deferred)
- `<object>`, `<embed>` tags

Use a simple regex-based sanitizer (no heavy deps). The sanitizer is defense-in-depth; the source content is already the user's own article.

## 12. Image + attribution handling

### Selected images in post HTML

Each selected image (`Image.status == "selected"`) is embedded in the post HTML:

```html
<figure>
  <img src="https://upload.wikimedia.org/..." alt="..." referrerpolicy="no-referrer" loading="lazy" />
  <figcaption>Caption text</figcaption>
</figure>
<p class="image-attribution">
  Photo: <a href="https://commons.wikimedia.org/...">Author Name</a>,
  <a href="https://creativecommons.org/licenses/...">CC BY-SA 4.0</a>
</p>
```

### Attribution requirements

| License | Attribution required? | What to include |
|---|---|---|
| CC0 | No | Optional credit |
| Public Domain | No | Optional credit |
| CC BY | Yes | Author name + license link |
| CC BY-SA | Yes | Author name + license link + SA notice |

The `attribution_required` field on the `Image` model tracks this. The `attribution` field stores the pre-rendered credit line. Use it directly in the HTML.

### Remote image URLs

- Wikimedia Commons URLs (`upload.wikimedia.org`) are stable and HTTPS.
- Blogger fetches remote images by URL when the post is published.
- No local download needed for v1.
- `referrerpolicy="no-referrer"` prevents leaking referrer to the image host.
- If a remote image is broken at publish time, Blogger still publishes the post (broken image shown to readers). This is an accepted MVP tradeoff.

## 13. Database changes

### Additive migration (no destructive changes)

Add columns to `Article`:

| Column | Type | Default | Purpose |
|---|---|---|---|
| `blogger_post_id` | `String(100)` | `None` | Blogger's post ID for idempotent updates |
| `blogger_post_url` | `String(500)` | `None` | Published URL on Blogger |
| `blogger_published_at` | `DateTime` | `None` | When published to Blogger |
| `blogger_status` | `String(30)` | `None` | Last known Blogger status (live/draft/trashed) |

Add columns to `PublishJob`:

| Column | Type | Default | Purpose |
|---|---|---|---|
| `blogger_post_id` | `String(100)` | `None` | Post ID returned by Blogger API |

### Migration approach

Same pattern as Phase 4C: idempotent `ALTER TABLE ADD COLUMN` in `init_db()` via `PRAGMA table_info` check. No Alembic needed.

## 14. Backend API

### New endpoints

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/api/blogger/status` | Connection status (connected/disconnected/token_expired) | Required |
| GET | `/api/blogger/blogs` | List blogs for the connected account | Required |
| POST | `/api/blogger/connect` | Start OAuth flow (returns auth URL) | Required |
| GET | `/api/blogger/callback` | OAuth redirect handler (no auth — Google redirects here) | None (public) |
| POST | `/api/blogger/disconnect` | Disconnect blog (clear tokens) | Required |
| POST | `/api/articles/{id}/publish` | Publish article to Blogger | Required |
| POST | `/api/articles/{id}/publish/draft` | Save as Blogger draft | Required |
| POST | `/api/articles/{id}/publish/retry` | Retry failed publish | Required |

### Publish endpoint behavior

```
POST /api/articles/{id}/publish
Body: { "as_draft": false }
```

1. Assert article status is `APPROVED`.
2. Assert `BlogConnection` exists and is `connected`.
3. Assert no publish job is running for this article.
4. Transition `APPROVED → PUBLISHING`.
5. Submit background publish job.
6. Return 202 with `{ status: "publishing" }`.

### Background publish job

1. Build post HTML from article body + images + sources.
2. Sanitize HTML.
3. If `blogger_post_id` exists → `posts.update` (PUT).
4. Else → `posts.insert` (POST, `isDraft` from request).
5. On success: store `blogger_post_id`, `blogger_post_url`, `blogger_published_at`.
6. Transition `PUBLISHING → PUBLISHED`.
7. Log to `PublishLog`.
8. On failure: transition `PUBLISHING → PUBLISH_FAILED`. Record error. Log to `PublishLog`.

## 15. Frontend UX

### Settings page: Blog connection

- Show connection status: "Connected to {blog_url}" or "Not connected".
- "Connect Blogger" button → opens OAuth flow in new tab.
- "Disconnect" button (with confirmation).
- Blog URL input field.
- Status indicator (green = connected, yellow = token expired, gray = disconnected).

### Article detail page: Publish controls

When article is `APPROVED`:
- "Publish now" button (prominent, green).
- "Save as draft" button (secondary).
- Both disabled while publishing is in progress.

When article is `PUBLISHING`:
- Spinner + "Publishing..." status.
- Buttons disabled.

When article is `PUBLISHED`:
- "Published" badge with link to Blogger URL.
- "Update on Blogger" button (re-publishes content).
- "Published at {date}" timestamp.

When article is `PUBLISH_FAILED`:
- Error message with details.
- "Retry publish" button.

When article is NOT `APPROVED`:
- Publish buttons hidden or disabled.

### Protection against accidental duplicate publishing

- Publish button disabled when status is not `APPROVED`.
- Publish button disabled when `running` is true.
- Confirmation dialog: "Publish this article to {blog_url}? This will make it publicly visible." (only for live publish, not draft).
- After publish starts, button immediately changes to spinner state.

## 16. Security model

| Threat | Mitigation |
|---|---|
| OAuth token exfiltration | Tokens encrypted at rest with Fernet; never logged; never committed; `.env` gitignored |
| Client secret exposure | `.env` gitignored; never returned by API; settings endpoint masks secrets |
| XSS in post HTML | Sanitize before sending to Blogger; strip `<script>`, event handlers, dangerous URLs |
| CSRF on publish endpoint | Same as existing endpoints: `X-Auth-Token` header when configured |
| HTML injection via image metadata | Image alt/caption text escaped before embedding in HTML |
| Duplicate publish | State gate + job key + idempotent update on retry |
| Token refresh failure | Set `BlogConnection.status = "token_expired"`, UI shows "Reconnect" |
| Logging secrets | Token values never logged; only `BlogConnection.id` and status logged |
| Error messages leaking credentials | API errors return user-friendly messages, never raw token/credential data |

### Encryption key management

- `ENCRYPTION_KEY` is a Fernet key stored in `.env`.
- Generated once: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
- If missing: blog connection fails with a clear error ("ENCRYPTION_KEY not configured").
- The key is never stored in the database or returned by the API.

## 17. Error/retry/recovery behavior

| Failure | Behavior | Recovery |
|---|---|---|
| OAuth consent denied | Connection stays "disconnected" | User retries connect flow |
| Token expired / revoked | `BlogConnection.status = "token_expired"` | User clicks "Reconnect" |
| Blog URL not found | Error returned on connect | User corrects URL |
| Publish API timeout | `PUBLISHING → PUBLISH_FAILED` | User clicks "Retry" |
| Publish API 403 (permissions) | `PUBLISHING → PUBLISH_FAILED` with error | User reconnects OAuth |
| Publish API 404 (blog deleted) | `PUBLISHING → PUBLISH_FAILED` with error | User reconnects, selects different blog |
| Publish API 429 (rate limit) | `PUBLISHING → PUBLISH_FAILED` with retry-after | User retries after backoff |
| Network failure | `PUBLISHING → PUBLISH_FAILED` | User retries |
| Process restart during PUBLISHING | Stale `PUBLISHING` row detected on startup | Lazy-resume: check if post exists on Blogger, update or retry |
| Partial response (ID received but confirmation lost) | Check `posts.list` on retry | Idempotent: use `posts.update` if post exists |

### Stuck publishing job recovery

Same pattern as article/image jobs: on next GET `/api/articles/{id}`, if status is `PUBLISHING` and no job is running, lazy-resume by checking Blogger for an existing post with matching title. If found, transition to `PUBLISHED` with the post ID. If not found, retry the publish.

## 18. Testing strategy

### Backend tests

| Category | Tests | Mock strategy |
|---|---|---|
| Blogger client | OAuth URL generation, token refresh, API calls | Mock httpx responses |
| Publishing service | HTML building, sanitization, idempotent publish | Mock blogger client |
| Publish API | Endpoints, 409 on concurrent, 404 on missing article | Mock service |
| Approval gate | Cannot publish from non-approved states | Real state machine |
| Idempotency | Re-publish uses update, not insert | Mock blogger client |
| Duplicate prevention | Concurrent publish blocked | Real state machine + runner |
| Retry | Failed publish retryable | Mock blogger client |
| Error handling | Network failure, API errors, token expiry | Mock blogger client |
| Content conversion | Markdown to HTML, image embedding, attribution | Real converter |
| HTML sanitization | Script stripping, event handler removal | Real sanitizer |
| Token encryption | Encrypt/decrypt roundtrip | Real Fernet |
| Recovery | Stuck PUBLISHING row detection | Mock blogger client |
| End-to-end flow | IDEA → RESEARCH → DRAFT → SEO → CHECKS → IMAGES → APPROVED → PUBLISHED | Mock blogger client + Ollama |

### Frontend tests

| Category | Tests |
|---|---|
| Publish button gating | Disabled when not approved, disabled when running |
| Connection status | Shows connected/disconnected/expired |
| Publish flow | Button click → spinner → success/failure |
| Draft vs live | Both paths work |
| Retry | Failed state shows retry button |
| Confirmation | Live publish shows confirmation dialog |
| Duplicate click prevention | Button disabled during publish |

## 19. Resource/dependency analysis

### New Python dependencies

| Package | Size | Justification |
|---|---|---|
| `google-auth-oauthlib` | ~50KB | OAuth 2.0 flow (InstalledAppFlow) |
| `google-auth` | ~200KB | Transitive dep of google-auth-oauthlib |
| `markdown` | ~100KB | Markdown-to-HTML conversion for Blogger |

Total new: ~350KB. All well-maintained, widely used.

### RAM impact

- No new heavy services. Publishing is a single HTTP call (httpx).
- No new LLM calls.
- No new workers. Publishing runs in the existing serial runner.
- Estimated additional RAM: <5MB.

### CPU impact

- Markdown conversion is negligible (milliseconds).
- OAuth flow is one-time (on connect).
- Publishing is a single API call.

## 20. Phase 5A–G implementation sequence

### 5A — Blogger client abstraction

**Objective:** Create a `BloggerClient` class that wraps the Blogger API v3 with OAuth token management.

**Files likely affected:**
- NEW: `backend/services/blogger_client.py` — OAuth flow, token management, API calls
- NEW: `backend/tests/test_blogger_client.py` — mocked tests
- MODIFIED: `backend/pyproject.toml` — add `google-auth-oauthlib`, `markdown`
- MODIFIED: `backend/app/config.py` — add `blogger_client_id`, `blogger_client_secret`, `blogger_redirect_uri`

**Database impact:** None (uses existing `BlogConnection` model).

**API impact:** None (no endpoints yet).

**Frontend impact:** None.

**Tests:** Mock httpx, test OAuth URL generation, token refresh, blog resolution, post insert/update/list/get.

**Security risks:** Token storage, client secret handling.

**Dependencies:** Can be completed independently. No other Phase 5 subphase depends on it being done differently.

**Estimated OpenCode complexity:** Medium. ~200-300 lines of Python + tests.

---

### 5B — OAuth connect flow + blog selection

**Objective:** Wire the OAuth flow into the API so the frontend can initiate connection.

**Files likely affected:**
- NEW: `backend/app/api/blogger.py` — connection endpoints
- MODIFIED: `backend/app/main.py` — mount blogger router
- MODIFIED: `backend/app/schemas/common.py` — blogger schemas

**Database impact:** Uses existing `BlogConnection` model. May add `BlogConnection.connected_at` column (additive).

**API impact:** New endpoints: `GET /api/blogger/status`, `GET /api/blogger/blogs`, `POST /api/blogger/connect`, `GET /api/blogger/callback`, `POST /api/blogger/disconnect`.

**Frontend impact:** None (endpoints only).

**Tests:** Test each endpoint, mock blogger client, test OAuth callback, test disconnect.

**Security risks:** OAuth callback is a public endpoint (no auth token required — Google redirects here). Validate state parameter.

**Dependencies:** Depends on 5A (blogger client).

**Estimated OpenCode complexity:** Medium. ~150-200 lines of Python + tests.

---

### 5C — Markdown-to-HTML converter + content builder

**Objective:** Build the post HTML from article data for Blogger.

**Files likely affected:**
- NEW: `backend/pipeline/publish.py` — content builder (markdown conversion, HTML assembly, sanitization)
- NEW: `backend/tests/test_publish_content.py` — converter tests

**Database impact:** None.

**API impact:** None.

**Frontend impact:** None.

**Tests:** Markdown conversion, image embedding, attribution rendering, HTML sanitization, edge cases (empty body, no images, no sources).

**Security risks:** HTML sanitization correctness.

**Dependencies:** Can be completed in parallel with 5B. Only needs `markdown` library.

**Estimated OpenCode complexity:** Medium. ~200-250 lines of Python + tests.

---

### 5D — Publishing service

**Objective:** Orchestrate the publish action: state transition, API call, result persistence, audit logging.

**Files likely affected:**
- NEW: `backend/pipeline/publish.py` — publish service (add to existing or new file)
- NEW: `backend/tests/test_publish_service.py` — publish service tests

**Database impact:** Additive columns on `Article` (blogger_post_id, blogger_post_url, blogger_published_at, blogger_status). Additive column on `PublishJob` (blogger_post_id). Migration via `init_db()`.

**API impact:** None (service layer only).

**Frontend impact:** None.

**Tests:** Publish happy path, idempotent re-publish, failure handling, retry, stuck job recovery, audit log creation.

**Security risks:** Token usage in API calls (ensure no logging).

**Dependencies:** Depends on 5A (client) and 5C (content builder).

**Estimated OpenCode complexity:** High. ~300-400 lines of Python + tests. Core of Phase 5.

---

### 5E — Publish API endpoints

**Objective:** Expose publish actions via REST API.

**Files likely affected:**
- MODIFIED: `backend/app/api/articles.py` — add publish endpoints
- MODIFIED: `backend/app/schemas/common.py` — publish schemas
- MODIFIED: `backend/services/article_runner.py` — add publish background job

**Database impact:** None.

**API impact:** New endpoints: `POST /api/articles/{id}/publish`, `POST /api/articles/{id}/publish/draft`, `POST /api/articles/{id}/publish/retry`.

**Frontend impact:** None (endpoints only).

**Tests:** Publish from approved state, 409 on non-approved, 409 on concurrent publish, 404 on missing article.

**Security risks:** Ensure publish endpoint requires auth, checks approval state.

**Dependencies:** Depends on 5D (publish service).

**Estimated OpenCode complexity:** Medium. ~150-200 lines of Python + tests.

---

### 5F — Frontend publishing UI

**Objective:** Add publish controls to the article detail page and blog connection to settings.

**Files likely affected:**
- NEW: `frontend/src/components/articles/publish-panel.tsx` — publish controls
- MODIFIED: `frontend/src/components/articles/articles-view.tsx` — integrate publish panel
- NEW: `frontend/src/components/settings/blog-connection.tsx` — blog connection UI
- MODIFIED: `frontend/src/app/(app)/settings/page.tsx` — add blog connection section
- MODIFIED: `frontend/src/lib/api.ts` — add publish API functions + types

**Database impact:** None.

**API impact:** None (consumes 5B + 5E endpoints).

**Frontend impact:** New components, new API functions.

**Tests:** Publish button gating, connection status display, publish flow, retry, confirmation dialog.

**Security risks:** None (frontend only).

**Dependencies:** Depends on 5B (connection API) and 5E (publish API).

**Estimated OpenCode complexity:** Medium. ~300-400 lines of TSX + tests.

---

### 5G — Integration testing + security review + documentation

**Objective:** Full end-to-end verification, security pass, documentation update.

**Files likely affected:**
- MODIFIED: `CLAUDE.md` — status update
- MODIFIED: `docs/04-phase-5-blogger-publishing-plan.md` — completion record
- NEW: `backend/tests/test_publish_e2e.py` — end-to-end publish flow test

**Database impact:** None.

**API impact:** None.

**Frontend impact:** None.

**Tests:** Full pipeline test (mocked), security review, gstack review.

**Security risks:** Final security pass.

**Dependencies:** Depends on all previous subphases.

**Estimated OpenCode complexity:** Medium. ~100-200 lines of tests + docs.

---

## 21. Files likely affected per subphase

| Subphase | New files | Modified files |
|---|---|---|
| 5A | `services/blogger_client.py`, `tests/test_blogger_client.py` | `pyproject.toml`, `app/config.py` |
| 5B | `app/api/blogger.py` | `app/main.py`, `app/schemas/common.py` |
| 5C | `pipeline/publish.py`, `tests/test_publish_content.py` | — |
| 5D | `tests/test_publish_service.py` | `pipeline/publish.py`, `db/base.py` |
| 5E | — | `app/api/articles.py`, `app/schemas/common.py`, `services/article_runner.py` |
| 5F | `components/articles/publish-panel.tsx`, `components/settings/blog-connection.tsx` | `articles-view.tsx`, `lib/api.ts`, `settings/page.tsx` |
| 5G | `tests/test_publish_e2e.py` | `CLAUDE.md`, `docs/04-phase-5-blogger-publishing-plan.md` |

## 22. Acceptance criteria

1. User can connect a Blogger blog via OAuth 2.0 flow.
2. Connection status is visible in settings (connected/disconnected/token_expired).
3. User can disconnect and reconnect.
4. An `APPROVED` article can be published to Blogger (live or draft).
5. Publish button is disabled for non-approved articles.
6. Publish button is disabled during in-flight publish.
7. Published article has a visible Blogger URL.
8. Failed publish shows error and retry option.
9. Re-publishing an already-published article updates the existing post (no duplicates).
10. Images are embedded in the post HTML with attribution.
11. HTML is sanitized before sending to Blogger.
12. OAuth tokens are encrypted at rest.
13. Secrets are never logged or returned by API.
14. Full backend test suite passes (existing + new).
15. Frontend tests pass.
16. Frontend lint, typecheck, build clean.

## 23. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Google deprecates Blogger API | Publishing stops | API has been stable since 2013; v3 still active in 2026; fallback: manual copy-paste |
| OAuth client verification required | User can't publish | Desktop type apps don't require verification for personal use |
| Blogger rate limits | Publish fails | Single-user, low volume; retry on 429 |
| Token refresh fails (account disabled) | Can't publish | Clear error + reconnect flow |
| Markdown conversion edge cases | Malformed post HTML | Test with diverse content; fall back to plain text |
| Remote image URLs break | Broken images in post | Accepted MVP tradeoff; images are stable Commons URLs |
| HTML sanitization misses injection | XSS in published post | Defense-in-depth: source is user's own content; Blogger also sanitizes |
| Phase 5 scope creep | Time overrun | Strict non-goals list; schedule + APScheduler explicitly deferred |

## 24. Deferred items

| Item | Deferred to | Reason |
|---|---|---|
| APScheduler publish scheduling | Phase 5H+ | Not needed for manual publish; adds complexity |
| Post deletion/unpublish | Phase 5H+ | Rare operation; can be done in Blogger UI |
| Post scheduling via `publishDate` | Phase 5H+ | Depends on APScheduler |
| Image downloading/re-hosting | Later phase | Remote URLs work for MVP |
| Multi-blog switching | Later phase | Single-user, single-blog v1 |
| OAuth token refresh auto-reconnect | Later phase | Manual reconnect acceptable for v1 |
| Post status sync from Blogger | Phase 5H+ | Nice-to-have; not critical for MVP |
| YouTube embed support | Later phase | Niche; defer |

## 25. CEO review

**Scope:** Right-sized. Phase 5 completes the core product loop (idea -> published post). Publishing is the single most important missing piece. One blog, one user, manual publish, no scheduling — this is the right MVP cut.

**Product risk:** The biggest risk is not technical but behavioral — will the user actually use this instead of copy-pasting from the preview? The publish button must be trivially easy and the OAuth flow must be painless.

**Recommendation:** Proceed as planned. The 5A-5G sequence is independently valuable — each subphase delivers testable, shippable increments.

## 26. Engineering review

**Architecture:** The approach is sound. Using `httpx` for API calls (already in the project) instead of the heavy `google-api-python-client` is the right call. `google-auth-oauthlib` for OAuth flow only keeps deps minimal.

**Data model:** Reusing existing `BlogConnection`, `PublishJob`, `PublishLog` models is correct. The additive columns on `Article` are minimal and non-breaking.

**State machine:** No new states needed. The existing transitions cover all Phase 5 use cases. This is a strong signal the original design was forward-looking.

**Content conversion:** Adding `markdown` as a dependency is justified. The frontend renderer is insufficient for Blogger's needs.

**Security:** The encryption-at-rest approach for tokens is correct. The OAuth callback being a public endpoint is standard and safe (Google validates the redirect).

**Concern:** The `PUBLISHING` → `PUBLISHED` transition assumes the API call succeeds. If the response is ambiguous (network timeout after request sent), the stuck-job recovery must be careful not to create duplicates. The idempotency design (check `posts.list` on retry) addresses this.

## 27. gstack planning review

**MUST-FIX planning issues:** None identified. The plan is complete and well-scoped.

**SHOULD-FIX planning issues:**
- S1: Add `BloggerClient.close()` method for resource cleanup (httpx client lifecycle).
- S2: Document the OAuth callback flow more explicitly (state parameter validation, error handling on callback).
- S3: Consider adding a `BlogConnection.last_sync_at` field for future status sync.

**Rejected scope:** Scheduling (APScheduler), multi-blog, post deletion, image downloading — all correctly deferred.

**Security concerns:** Addressed in §16. No gaps identified.

**Architecture risks:** Low. The serial runner pattern extends naturally to publishing. No new concurrency concerns.

## 28. Final recommendation

Proceed with Phase 5 as specified, in the 5A-5G sequence. Each subphase is independently testable and shippable. The plan aligns with the original product discovery, uses minimal new dependencies, and preserves the approval gate as the single human checkpoint before anything reaches the internet.

The 5A-5G sequence is designed for OpenCode sessions: each subphase is small enough to inspect, implement, test, review, and commit in one session. Total estimated complexity: Medium-High (~1200-1500 lines of Python + ~500 lines of TSX + tests).

---

## GSTACK REVIEW REPORT

Status: PLAN_READY. Planning doc reviewed (CEO + Eng lenses + critical pass). No code modified.
