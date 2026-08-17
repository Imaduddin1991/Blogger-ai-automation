# Phase 4 — Images — Reviewed Implementation Plan

**Status:** COMPLETE (Phase 4A–4F). See §18 for final completion record.
**Baseline:** HEAD `ddeb716`, working tree clean. Default model `qwen2.5:1.5b`.
**Scope:** Design the image stage only. Blogger publishing (Phase 5) is out of scope here.

---

## 1. Executive summary

Phase 4 adds the image stage to the existing serial pipeline:
`checked -> images_searching -> image_ready -> ready_for_review -> approved`.

It uses **one free provider (Wikimedia Commons)** behind a ResearchProvider-style abstraction,
deterministic (no-LLM) query + relevance logic, an **allowlist-only license policy** that rejects
anything ambiguous or non-commercial, **URL-only storage** (no local downloads), and a review UI
where images are human-selected and human-approved. Images are **optional**: if search fails or
returns nothing usable, the article stays fully usable and proceeds to review without images.

Everything is free, keyless, dependency-free for MVP (reuses httpx), and fits the serial runner
with no new workers and no new LLM calls.

## 2. Phase 4 scope

**Does:**
- `ImageProvider` abstraction + registry (Commons first; more later without touching the pipeline).
- Wikimedia Commons image search with license metadata (Commons `api.php` `generator=search` +
  `prop=imageinfo`, `iiprop=url|size|mime|extmetadata`).
- Deterministic search-query generation from topic / title / headings (no LLM).
- Candidate relevance scoring + filtering (reuses the research relevance approach).
- License verification with allow/deny rules; reject on missing/ambiguous license.
- `Image` model extension (candidate/suggested/selected/rejected lifecycle) + additive migration.
- Pipeline integration: new `images_searching` state; image stage runs as the last step of the
  article job; approve gate extended to `IMAGE_READY -> READY_FOR_REVIEW`.
- REST endpoints: search / list / select / remove / retry.
- Frontend review UI: search results, preview + license metadata, select/remove/replace, status.
- Tests: provider, licensing, relevance, dedupe, failure/retry, API, frontend, security.

**Does NOT:**
- No paid API, no required key, no subscription. Commons is keyless; Pexels/Unsplash stay optional.
- No local image generation (Stable Diffusion/ComfyUI). Non-MVP, documented only.
- No local image downloads in MVP (URL + metadata only; Blogger fetches by URL).
- No image editing (crop/resize/filters).
- No automated publishing (Phase 5), no duplicate-image governance across the blog, no image CDN.
- No new dependencies in MVP, no new workers, no LLM calls in the MVP image stage.

## 3. Architecture decision

**Provider abstraction mirroring the research providers** (`backend/pipeline/images/`):

```
backend/pipeline/images/
├── __init__.py          # run_image_search(...) entry point (mirrors research.service)
└── providers/
    ├── __init__.py
    ├── base.py          # ImageProvider ABC, ImageResult, errors, license policy, dedupe/relevance helpers
    ├── registry.py      # @register / get_provider / enabled_providers (mirrors research registry)
    └── commons.py       # Wikimedia Commons provider (Phase 4B)
```

The pipeline and API depend only on the `ImageProvider` interface. Adding a provider = one class +
one `@register`; no pipeline/data-model changes. This is the same pattern the project already
proved with research providers.

`ImageResult` (normalized record, regardless of provider):
`provider, image_url, page_url, thumb_url, title, author, license, license_url,
attribution_required, usage_notes, mime, width, height, file_size, relevance`

Errors: `ImageProviderError(RuntimeError)` (mirrors `ResearchProviderError`).

## 4. Provider decision

| Provider | Free | Key | MVP/Optional | Notes |
|---|---|---|---|---|
| Wikimedia Commons (`commons.py`) | Yes, keyless | None | **MVP** | Stable REST API, explicit license metadata via `extmetadata`, hotlink-friendly URLs, already-used Wikimedia ecosystem in this repo. |
| Pexels free tier | Yes | User-supplied key | Optional, later | Free quota; needs a key and API contract; keep behind user opt-in, never blocking. |
| Unsplash free tier | Yes | User-supplied key | Optional, later | Same as Pexels. |
| Openverse (WordPress) | Yes | None | Optional, later | Aggregate of CC sources; would be a good second provider. |
| Local generation | — | — | NON-MVP | CPU-only hardware; minutes per image; RAM too tight. Documented only. |

**Per-provider detail:**

- **Wikimedia Commons (MVP, keyless).** API: documented public REST (`api.php` as below), no key,
  no registration. Free: yes, $0. Licensing: explicit per-file `extmetadata` (LicenseShortName,
  LicenseUrl, Artist, UsageTerms, AttributionRequired) plus a page-url to verify on
  commons.wikimedia.org. Attribution: required for CC BY / CC BY-SA; the app stores and renders it
  (author + license + source page). Rate limits: not published numerically; Wikimedia mandates a
  descriptive User-Agent and frowns on bursts; mitigation = per-topic cache, serial requests via the
  shared runner, polite timeout/backoff. Reliability: high (the repo already depends on the
  Wikimedia ecosystem for research). Provider API:
  `GET https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrsearch=filetype:bitmap|filetype:drawing <query>&gsrnamespace=6&gsrlimit=<n>&prop=imageinfo&iiprop=url|size|mime|extmetadata&iiurlwidth=400&format=json`
- **Pexels (optional, later).** API: free tier with per-user key; requires registration.
  Free: yes, quota-limited. Licensing: Pexels license (royalty-free, commercial OK, no attribution
  required). Rate limits: published quota per key/month. Reliability: good. Never blocking; user opt-in.
- **Unsplash (optional, later).** API: free tier with per-user key; requires registration.
  Free: yes, quota-limited. Licensing: Unsplash license (royalty-free, commercial OK, no attribution
  required). Rate limits: published quota per key/month. Reliability: good. Never blocking; user opt-in.
- **Openverse (optional, later).** API: public, keyless (rate-limited anonymously).
  Free: yes, $0. Licensing: aggregates CC-licensed works with machine-readable license metadata,
  good as a second no-key provider. Reliability: good. Not required for MVP.
- **Local generation (NON-MVP).** Not free-of-cost on this hardware (CPU-only, minutes per image,
  RAM too tight); documented only. All other rows verified free (no paid API/subscription/card).

## 5. Licensing strategy

**Mandatory persisted metadata per image:** `provider`, `image_url`, `page_url` (Commons file page),
`title`, `author`, `license`, `license_url`, `attribution_required`, `usage_notes`, `mime`,
`retrieved_at`, plus `relevance`, `status`, `position`.

**Allowlist** (commercial-compatible, AdSense-safe): Public Domain (`CC0`, `PD`, `Public domain`),
`CC BY`, `CC BY-SA`, `GFDL`. **Denylist** (reject): `CC BY-NC*`, `CC BY-ND*`, `Fair use`,
`Non-free`, `Permission`, `Copyrighted`, any unknown/empty license.

**Rejection rules (any one triggers reject, with a visible reason):**
1. License empty or unknown -> reject.
2. License not in allowlist -> reject.
3. License allows attribution but `author`/`attribution` missing -> reject (cannot render credit).
4. `image_url` or `page_url` scheme not `https` -> reject.
5. `mime` not in `{image/jpeg, image/png, image/webp, image/gif}` -> reject (blocks SVG/scripts).
6. `file_size` > 10 MB, or width/height > 10000 px -> reject (oversized).
7. `attribution_required` unknown AND license is not PD/CC0 -> reject.

Verified metadata is treated as untrusted data: stored raw, escaped at render, injected into the
post HTML attribution line only via an escaping helper.

## 6. Data model changes

Minimal, additive. No new tables in MVP.

Extend `Image` (backend/db/models.py) with columns:
`status` (String(20), default `candidate`) — `candidate | suggested | selected | rejected`;
`page_url` (String(1000)), `author` (Text), `license_url` (String(500)),
`attribution_required` (Boolean, default False), `usage_notes` (Text),
`thumb_url` (String(1000)), `mime` (String(50)), `width`/`height` (Integer, nullable),
`file_size` (Integer, nullable), `relevance` (Float, default 0.0),
`retrieved_at` (DateTime, default now).

Existing columns (`provider, url, alt, caption, attribution, license, position`) are reused.

Migration: additive `ALTER TABLE images ADD COLUMN ...` run at startup (idempotent, checks
`PRAGMA table_info`). No alembic, no data rewrite; existing dev rows (if any) get
`status='selected'`.

## 7. State-machine changes

New state: `images_searching` (in-flight image stage). Everything else exists.

Additions to `TRANSITIONS` in backend/pipeline/state.py:
- `CHECKED -> IMAGES_SEARCHING` (start search)
- `IMAGES_SEARCHING -> IMAGE_READY` (done; 0..N images — images are optional)
- `IMAGES_SEARCHING -> CHECKED` (provider failure -> stable, retryable)
- `IMAGE_READY -> IMAGES_SEARCHING` (re-search / replace)

Kept unchanged: `CHECKED -> READY_FOR_REVIEW` (manual skip-images path),
`IMAGE_READY -> READY_FOR_REVIEW`, `READY_FOR_REVIEW -> APPROVED`.

`approve_article` accepts `{CHECKED, IMAGE_READY} -> READY_FOR_REVIEW`, then
`READY_FOR_REVIEW -> APPROVED` as today. `update_article` content-edit reset list gains
`IMAGES_SEARCHING`.

The image stage runs inside the existing article job as the last step after checks
(`_checks_stage -> _images_stage -> IMAGE_READY`), so the happy path needs no new job.
A separate runner key `article-images:{id}` + `start_background_images()` handles manual
re-search/retry only.

## 8. Pipeline flow

```
checked
  -> images_searching          (image stage starts; deterministic queries from topic/title/headings)
      -> [Commons search -> normalize -> license verify -> relevance score -> dedupe]
      -> image_ready           (≥0 suggested candidates persisted; best candidate auto-marked "suggested",
                                NOT auto-approved; human selects/rejects in review)
      -> ready_for_review      (human "Mark ready for review")
      -> approved              (human "Approve" — records review_approved_at; Phase 5 requires this)
```

Failures:
- Provider error -> `images_searching -> checked`, `generation_errors["images"]` set, article usable.
- Zero usable images -> `image_ready` with 0 images + UI empty state; article proceeds without images.
- Content edits (existing path) reset to `drafted` and clear CheckResults; attached images persist
  and are re-reviewed by the human at approval (no auto-invalidation in MVP).

### Image relevance (query generation)

Query terms are built deterministically — **no LLM call in the MVP image stage** (free-quota and
hardware constraints). Term sources, in priority order:
1. Article topic (the idea/research topic).
2. Article title words.
3. Top 3 heading words from the body.
4. Top research source titles (reuse research sources already in the DB — no extra fetch).

Terms are extracted with the existing `_content_words`-style tokenizer (no stopword NLP, no new
deps), producing 1-3 query strings (topic phrase; topic + strongest keyword; strongest keyword).

Candidate relevance: reuse the research `compute_relevance` approach — the fraction of query term
words (or 4-char stems) present in the candidate title; filter below `MIN_RELEVANCE` (0.2).
This keeps Commons results on-topic and drops the equivalent of the "Katy Perry for a cats query"
case.

Duplicate avoidance:
- Within a search: dedupe by canonical `image_url` (normalize protocol/host/trailing-slash/query);
  also collapse near-identical titles (normalized title match).
- Across articles: a candidate already used on another article is flagged in the UI as
  "used in <other article>" (informational, 4F); MVP does not hard-block reuse.

### Failure/retry behavior (per case)

| Case | Behavior |
|---|---|
| No images found (all filtered/rejected) | `image_ready` with 0 images; `generation_errors["images"]` notes it; UI empty state; article proceeds without images |
| Provider unavailable / HTTP error | `images_searching -> checked`; error in `generation_errors["images"]`; retry re-runs search; article usable |
| API timeout | Same as provider unavailable (timeout = named error, retryable) |
| Invalid license metadata | Candidate rejected with stored reason; remaining candidates still returned |
| Download failure | N/A for MVP (no local download); broken thumb at render falls back to a placeholder; full URL still shown |
| Duplicate image | Deduped/skipped within the result set; flagged across articles |
| Corrupted image | No local decode in MVP; mime allowlist + size/dimension guards reject suspicious candidates at search time |
| Image too large | Rejected by `file_size` > 10 MB or width/height > 10000 px rule |
| Article does not need an image | User removes/ignores suggestions; proceeds to `ready_for_review` with 0 images (or from `checked` via the skip path) |

The pipeline is never blocked by image failures: images are optional in every path.

### Storage decision

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| URLs only | Zero disk, zero cleanup, Blogger fetches by URL | Hotlink breakage risk, no offline copy | Preferred base |
| Download locally | Copy survives remote churn | Disk growth, cleanup, storage paths, Blogger re-hosts anyway | Not MVP |
| Metadata + remote URL | Full license/attribution provenance, no downloads | None meaningful | **Chosen (MVP)** |
| Hybrid (metadata + local thumb cache) | Cheap previews, resilient | Caching lifecycle, extra code | Deferred (4F+ hardening) |

**Recommendation:** metadata + remote URL only for MVP. Full images are never stored or uploaded;
`thumb_url` is used for UI previews directly from the provider. Blogger (Phase 5) embeds the remote
URLs into post HTML per the existing discovery decision. No local file-upload surface, no secrets,
no cleanup jobs.

## 9. Frontend design

New section in the existing article review screen (`frontend/src/components/articles/`):
- `images/image-search.tsx` — search bar (pre-filled with generated query), triggers
  `POST /api/articles/{id}/images/search`, shows spinner while `images_searching`.
- `images/image-results-grid.tsx` — candidate cards: thumbnail (`thumb_url`), license badge,
  author, relevance %, Select / Reject actions, rejection reason tooltip.
- `images/image-preview-dialog.tsx` — full-size preview + metadata panel (page_url link,
  author, license + license_url, attribution text, usage notes, retrieved date).
- `images/image-selection.tsx` — selected images with order and Remove; "Replace" opens search.

Integration: status banner shows image state ("2 of 4 selected", spinner on `images_searching`);
empty state "No suitable images found — retry or continue without images".
`canApprove` gains `image_ready`. Remote images render via plain `<img>` only (never
`dangerouslySetInnerHTML`) with `referrerPolicy="no-referrer"` and `loading="lazy"`. License and
author text go through the existing escape path (untrusted metadata).

API (backend): `POST /api/articles/{id}/images/search` (async, 202),
`GET /api/articles/{id}/images` (candidates + selected + running),
`POST /api/articles/{id}/images/{image_id}/select`,
`DELETE /api/articles/{id}/images/{image_id}`,
`POST /api/articles/{id}/images/retry`.

## 10. Security considerations

- SSRF: server fetches only allowlisted hosts (`commons.wikimedia.org`, `upload.wikimedia.org`),
  https-only, and never a user-supplied URL. Search terms go to the Commons API as a parameter.
- Unsafe redirects: redirects confined to the allowlisted host set.
- MIME spoofing: metadata `mime` allowlist + size/dimension caps (no local decode in MVP, so no
  magic-byte sniffing yet — noted as a 4F hardening option).
- SVG/script risk: SVG excluded by mime allowlist; frontend renders `<img>` only.
- Oversized files: rejected by `file_size` / dimension rules.
- Remote content: images load from `upload.wikimedia.org` via `<img>` with no-referrer; no local
  storage, no file-upload surface.
- Metadata injection: Commons metadata is untrusted data; escaped at render, never interpolated
  into HTML unescaped.

## 11. Testing strategy

Backend (mocked httpx, mirroring existing provider tests):
- Provider: normalizes results; non-200/timeout -> `ImageProviderError`; extmetadata variants
  (PD, CC0, CC BY, CC BY-SA, NC/ND, missing) parse correctly; limit respected.
- Licensing: accept/reject matrix incl. missing license, non-commercial, missing attribution.
- Relevance: query generation from title/headings; off-topic candidate filtered; dedupe by URL.
- Failure/retry: provider timeout -> `checked` + `generation_errors`; zero results ->
  `image_ready` with 0; article usable without images; retry re-runs.
- API: search/select/remove/retry happy paths, 404/409, state transitions,
  approve from `image_ready`.
- Security: SVG/non-https/oversized rejected; metadata display escaping.
- State machine: new transitions valid; impossible ones still rejected.

Frontend (vitest, mirroring existing): image section renders; select/remove flows; empty state;
license badge; `canApprove` includes `image_ready`.

## 12. Hardware / resource considerations

- Zero new Python deps in MVP (httpx already present). No Pillow, no image libs.
- No new background workers: reuse the serial runner (one extra job key).
- No LLM calls in the MVP image stage -> no Ollama RAM impact, no extra generation time.
- Disk: ~0 (URL-only storage; no local images).
- RAM: negligible (small JSON metadata responses).
- Free OpenCode quota: Phase 4 split into small slices (below), each independently reviewed.

## 13. Phase 4 implementation sequence (4A-4F)

- **4A — Image provider abstraction.** `images/` package: `ImageResult`, `ImageProvider` ABC,
  `ImageProviderError`, license policy constants, registry. Tests.
- **4B — Wikimedia Commons provider.** `commons.py`: search + extmetadata/license parsing,
  URL/thumb normalization, `verify_license`. Tests.
- **4C — Schema + licensing + relevance.** `Image` model columns + additive migration; rejection
  rules; deterministic query generation + relevance scoring + dedupe. Tests.
- **4D — Pipeline + API.** `images_searching` state; `_images_stage` in the article job; images
  runner key; `approve_article`/`update_article`/`recheck_article` updates; API endpoints +
  schemas. Tests.
- **4E — Frontend review UI.** Image section, search grid, preview dialog, selection, status,
  empty states, `canApprove`. Tests.
- **4F — Hardening + docs.** Security pass, `/review` + `/qa`, cross-article duplicate flags,
  docs/CLAUDE.md update, acceptance-criteria sign-off.

## 14. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Commons API change/outage | Image stage fails | Provider error -> `checked`, article usable; retry; provider interface isolates the change |
| Wrong/missing license metadata | Legal/reputation risk | Allowlist only; reject on any ambiguity; human gate; attribution rendered |
| Irrelevant images | Poor quality post | Relevance filter + human select |
| Hotlink breakage | Broken image in post | Stable Commons URLs; local caching is a documented 4F+ option |
| Scope creep / heavy features | Quota + hardware | Images optional; MVP is one keyless provider; local gen + stock keys explicitly non-MVP |
| Extra LLM cost | Quota | No LLM in MVP image stage; deterministic queries |

## 15. Exact acceptance criteria

1. `POST /api/articles/{id}/images/search` returns 202; with Commons results the article reaches
   `image_ready` and ≥1 candidate is marked `suggested` (never auto-approved).
2. Every persisted image row has non-null `image_url`, `page_url`, `license`, `retrieved_at`;
   `attribution_required` is true for CC BY / CC BY-SA.
3. A CC BY-NC / CC BY-ND / non-free / missing-license candidate is rejected with a visible reason
   and can never be selected.
4. SVG, non-https, and >10 MB candidates are rejected.
5. Zero results or all-rejected leaves the article usable: `image_ready`, 0 images, UI empty
   state, still able to reach `ready_for_review -> approved`.
6. Provider timeout/500 does not break the pipeline: article returns to `checked`, error recorded
   in `generation_errors["images"]`, retry re-runs the search.
7. No image reaches any publish path without passing `ready_for_review -> approved` (existing
   human gate; images visible before approval).
8. No server-side fetch of user-supplied URLs; only allowlisted Commons hosts are fetched.
9. Full backend pytest, frontend tests, typecheck, lint, build all green; image suites added.
10. Adding a second provider is one class + one registry entry; pipeline and data model unchanged.

## 16. gstack review findings

Review lenses applied to this plan (planning only; no code reviewed).

- CEO (HOLD SCOPE): Scope is right-sized. Images materially improve a generated post and a
  no-key Commons provider keeps the "free-first" promise intact. No scope expansion recommended
  for MVP; Pexels/Unsplash and Openverse are written down as later optional providers, local
  generation as non-MVP. The strongest product risk is licensing mistakes; the allowlist +
  reject-on-unknown + human gate directly targets it.
- Eng: architecture mirrors the proven research-provider pattern (DRY); no new deps; images are
  optional so the pipeline degrades gracefully; URL-only storage is the cheapest safe MVP.
- **MUST-FIX (all resolved in plan):**
  - M1 Auto-suggested image must not bypass the human approval gate -> suggestions are never
    auto-approved; approval still requires `ready_for_review -> approved`.
  - M2 Ambiguous license must reject, never silently accept -> allowlist + reject-on-unknown.
  - M3 Image failure must not break the pipeline -> `images_searching -> checked` on provider
    error; `image_ready` with 0 images on no results.
  - M4 SVG/non-https/oversized candidates must be blocked -> mime allowlist, https-only, size
    caps.
- **SHOULD-FIX (resolved or accepted as documented tradeoffs):**
  - S1 Avoid per-image LLM calls -> deterministic query generation (also protects free quota).
  - S2 Content edits can change image relevance -> attached images persist and are re-reviewed
    by the human at approval (accepted MVP tradeoff; auto-invalidation deferred).
  - S3 Cross-article duplicate images -> deferred to 4F as an informational flag, not a hard
    blocker.
  - S4 Candidate rejection reasons must reach the UI -> rejection reason returned per candidate.
  - S5 MIME spoofing via magic bytes -> deferred to 4F hardening (no local decode in MVP).

## 17. Final recommendation

Proceed with Phase 4 as specified, in the 4A-4F sequence, one slice per review cycle. MVP = one
keyless provider (Wikimedia Commons), URL-only storage, no LLM, images strictly optional. No
Phase 5 (Blogger) work in this task.

## GSTACK REVIEW REPORT

Status: PLAN_READY. Planning doc reviewed (CEO + Eng lenses + critical pass). No code modified.

---

## 18. Phase 4 completion record (4A–4F)

**Completed:** 2026-08-17

### Commit history

| Phase | Commit | Description |
|-------|--------|-------------|
| 4A | `1ec2264` | Image provider abstraction |
| 4B | `ef683ab` | Wikimedia Commons image provider |
| 4C | `dca00ae` | Image validation and deduplication |
| 4D | `8d52a3b` | Image search integration into article pipeline |
| 4E | `88446d2` | Frontend image review UI |
| 4F | *(pending commit)* | Harden phase 4 image workflow |

### Phase 4F hardening findings

**Added: dangerous file-extension rejection (`.exe`, `.php`, `.js`, `.sh`, `.zip`, etc.).**
The MIME allowlist blocks non-raster types, but a spoofed MIME could let a dangerous URL slip through
without a matching extension. Extension check is now applied to both `image_url` and `thumb_url`.

**No other new vulnerabilities found.** Existing defenses verified complete:

| Control | Status | Evidence |
|---------|--------|----------|
| HTTPS-only URLs (all 4 fields) | PASS | `_scheme_problem()` in `validate.py` |
| SVG rejection (MIME + extension) | PASS | `validate.py` lines 96–97 |
| Dangerous file extensions | PASS (4F) | `_DANGEROUS_EXTENSIONS` in `validate.py` |
| License allowlist (CC0/PD/CC BY/CC BY-SA) | PASS | `verify_license()` + `normalize_license()` |
| NC/ND/fair-use/unknown license rejection | PASS | `DENIED_LICENSE_MARKERS` + normalized match |
| Attrib-required license + missing author | PASS | `ATTRIBUTION_REQUIRED_LICENSES` check |
| No local image downloads | PASS | `run_image_search()` only calls `provider.search()` |
| No SSRF (no user-supplied URL fetched) | PASS | Commons API only; no arbitrary fetch |
| No XSS in new code | PASS | React JSX interpolation + `safeUrl()` + `referrerPolicy="no-referrer"` |
| Concurrent job guard | PASS | `_assert_searchable()` in `articles.py` |
| Race-safe status transition | PASS | `populate_existing=True` re-read before final transition |
| Stale job recovery | PASS | `run_images_job()` restarts stuck `images_searching` rows |
| Approval gate not bypassable | PASS | `select_image()` never calls `approve_article()` |
| Cross-article reuse is informational only | PASS | `find_image_usage()` never blocks selection |
| No new Python dependencies | PASS | Only existing `httpx` + stdlib |
| No new LLM calls | PASS | Deterministic query generation only |
| Serial runner remains serial | PASS | Images run inline in article job |

### Security findings

- **Fixed in 4F:** Extension-based spoofing gap (dangerous extensions now blocked).
- **Deferred (MVP tradeoff):** MIME spoofing via magic bytes — deferred to future phase with local
  decode (Pillow or equivalent). The extension check is a strong mitigation for MVP.

### Test results (4F)

```
Backend:  341 passed (was 314 before 4F hardening tests)
Frontend: 53 passed
Lint:     0 errors (1 pre-existing warning: <img> for external URLs)
Typecheck: clean
Build:    clean
```

### Known limitations

- Only one provider (Wikimedia Commons). Adding a second provider is one class + one registry entry.
- Image metadata is untrusted provider-supplied data; validated but not decoded locally.
- No local image caching (URL-only storage). Hotlink breakage is an accepted MVP tradeoff.
- Content edits do not auto-invalidate selected images; human re-reviews at approval gate.

### Licensing policy (MVP)

Allowed: CC0, Public Domain, CC BY, CC BY-SA.
Rejected: everything else (NC, ND, fair use, unknown, ambiguous, permission-required).
Attribution licenses (CC BY, CC BY-SA) require author metadata to persist.

### Human approval requirement

Images are visible to the human in the review UI. No image ever bypasses the
`ready_for_review -> approved` gate. Selecting an image never auto-approves the article.
Blockers: none. Next: user approval to start Phase 4A.
