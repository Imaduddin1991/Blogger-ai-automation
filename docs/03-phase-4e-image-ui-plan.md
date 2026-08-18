# Phase 4E — Frontend Image Review UI — Implementation Plan

Status: **PLANNING ONLY** (no code written yet).
See `docs/02-phase-4-image-plan.md` for the Phase 4 backend plan (unchanged, do not modify).

---

## 1. Objective

Give the human reviewer an image panel inside the existing article detail view so they can:

1. See the image pipeline state (`images_searching` / `image_ready`) per article.
2. Trigger a Commons image search from a `checked` article.
3. Review the auto-suggested candidate images (thumbnail, caption, source, license).
4. Select / remove images for the article — without that ever being an approval.
5. Re-search / retry when the suggestion set is weak or the job errored.

The existing **human approval gate is preserved exactly**: `checked -> ready_for_review -> approved`.
Images are **auto-suggested, never auto-approved**; selecting images does **not** change article status.

Success criteria:
- Full article flow (idea -> research -> article -> SEO -> checks -> images -> review -> publish) works from the UI.
- Backend tests remain green (314) and new frontend tests pass.
- Zero new npm dependencies. No new LLM calls. No image downloads or local storage.

---

## 2. Frontend Architecture Findings (Phase 4E inspection)

- **Framework:** Next.js App Router (`frontend/`). `next.config.ts` rewrites `/api/:path*` -> `http://127.0.0.1:8000/api/:path*`, so the frontend calls the backend via relative `/api/...` URLs — no CORS or env config needed.
- **Article UI:** `frontend/src/app/(app)/articles/page.tsx` renders `frontend/src/components/articles/articles-view.tsx` — a single large `"use client"` component (`ArticlesView` + `ArticleDetailCard`).
- **Data layer:** `frontend/src/lib/api.ts` — typed `request<T>()` wrapper with `ApiError`; exports `statusLabel` and `formatDate`. `statusLabel` already maps `image_ready`, `ready_for_review`; `images_searching` currently falls through to the raw value (must be added).
- **Existing UI primitives (`src/components/ui/`):** `badge`, `button`, `card`, `dropdown-menu`, `input`, `label`, `scroll-area`, `separator`, `sheet`, `skeleton`. **No `dialog`/`alert-dialog` exists** — use the existing `Sheet` for the image detail panel (already used in app-shell) or an inline card section.
- **State components (`src/components/states/`):** `loading-state.tsx`, `empty-state.tsx`, `error-state.tsx` — reusable, already used by the articles view.
- **Markdown safety:** `frontend/src/lib/markdown.ts` — `escapeHtml` + `renderMarkdown` with a link-scheme allowlist. Metadata rendering must go through the same safe renderer, never `dangerouslySetInnerHTML`.
- **Tests:** vitest + React Testing Library + jsdom (`vitest.config.ts`, `src/test/setup.ts`). Existing conventions: `states.test.tsx` (component rendering), `api.test.ts` (pure function tests). New tests follow the same patterns — no new test framework.
- **Polling precedent:** the articles view already polls `getArticle` while `article.running` is true (~2s). The images panel reuses this same simple refetch approach — no new polling machinery.

---

## 3. Backend API Contract (Phase 4D — already implemented, do NOT change)

All endpoints return `ArticleImagesRead`:

```json
{
  "article_id": 1,
  "status": "image_ready",
  "running": false,
  "images": [ { "id": 1, "provider": "commons", "status": "suggested", "...": "..." } ]
}
```

| Method | Path | Notes |
|---|---|---|
| GET | `/api/articles/{id}/images` | Snapshot of article image state |
| POST | `/api/articles/{id}/images/search` | 202. Only when article status in {checked, image_ready}. 409 when `is_running` or status == `images_searching`. Kicks the background job. |
| POST | `/api/articles/{id}/images/retry` | 202. Same guards. Re-runs the search after failure. |
| POST | `/api/articles/{id}/images/{image_id}/select` | 404 if image not owned by article. 409 if image status == `rejected` (detail carries `rejection_reason`) or a job is running. **Never changes article status.** |
| DELETE | `/api/articles/{id}/images/{image_id}` | Removes a candidate. Same ownership/state guards. |

`ImageRead` fields available for the UI:

| Field | Type | UI use |
|---|---|---|
| `id` | int | identity |
| `status` | str | `candidate` / `suggested` / `selected` / `rejected` |
| `url`, `thumb_url` | str? | image source (render `thumb_url` when present, else `url`) |
| `alt`, `caption` | str? | display text |
| `provider` | str | `commons` (only provider in v1) |
| `license`, `license_url`, `attribution_required` | str?, str?, bool | license chip + attribution block |
| `attribution`, `author`, `page_url` | str? | attribution line, links out to source page |
| `usage_notes` | str? | license usage notes (e.g. share-alike / attribution wording) |
| `relevance` | float | sort hint |
| `rejection_reason` | str? | reason shown on rejected images |
| `position` | int | ordering within the article |
| `mime`, `width`, `height`, `file_size` | various | detail-panel metadata |
| `retrieved_at` | datetime | detail-panel metadata via `formatDate` |

---

## 4. UX Scope (what the reviewer can do)

**In scope:**
- See per-article image pipeline status and running state.
- Start a search from a `checked` article; watch it move `images_searching -> image_ready`.
- Retry a failed search (banner on error).
- Browse suggested images (grid) with caption + relevance.
- Open a detail panel per image: full caption, source link, license + attribution, usage notes, metadata.
- **Select** an image (marks `suggested -> selected`). Selecting never approves the article.
- **Remove** a selection (returns it to the pool).
- **Reject via "hide"/remove** a candidate they do not want (DELETE).
- Keep the existing **human approve gate untouched**: the approve button stays the only way to reach `ready_for_review`.

**Out of scope (explicit non-goals):**
- No image downloads / save-to-disk / local storage of images.
- No reordering or positioning UI (position is backend-managed for now).
- No caption/license editing.
- No Pexels/Unsplash/Openverse/AI-generation tabs.
- No approval-from-images-path (see section 9).

---

## 5. Component Plan

Reuse the existing patterns; do not add a `dialog` primitive.

1. **`ArticleImagesPanel`** (new, `src/components/articles/article-images-panel.tsx`) — the image section of `ArticleDetailCard`. Owns image state, fetches `GET /api/articles/{id}/images`, renders one of:
   - Not yet searched (`status == "checked"`): "Generate image suggestions" CTA button + helper text.
   - Searching (`images_searching` / `running`): skeleton grid + running badge.
   - Ready (`image_ready`): the image grid + actions.
   - Error: reuse `ErrorState` with the retry call.
2. **`ImageCard`** (new, `src/components/articles/image-card.tsx`) — thumbnail, caption line, license chip, selection state (border/checkmark), actions.
3. **`ImageDetailSheet`** (new, `src/components/articles/image-detail-sheet.tsx`) — wraps the existing `Sheet` UI component; full caption, attribution, license + license link, `page_url` source link, `usage_notes`, metadata rows.
4. **`ImageGrid`** (new, `src/components/articles/image-grid.tsx`) — the responsive grid; uses skeleton placeholders while fetching.
5. **`SelectImageButton`** / **`RemoveImageButton`** — small inline buttons on `ImageCard`; disabled during in-flight requests.

No new UI primitives under `src/components/ui/`; no new npm deps. All buttons use the existing `Button` variants; states use the existing `badge` / `skeleton` / `card`.

---

## 6. States: Loading / Empty / Error / Running

| State | Trigger | UI |
|---|---|---|
| Loading | `getArticleImages` in flight | Existing `LoadingState` / skeleton grid (`aria-busy`) |
| Searching | `running == true` or `status == images_searching` | Running badge on panel header; skeleton cards; search button disabled |
| Empty (never searched) | `status == checked`, no images | CTA button "Search Commons for images" + helper text |
| Empty (searched, none) | `status == image_ready`, `images.length == 0` | `EmptyState` "No images found" + "Retry search" |
| Empty (all rejected/removed) | `image_ready`, all images deleted | Same empty state + retry |
| Error | request fails | Existing `ErrorState` with retry; per-action failures surface as inline alert-style text near the action, never silent |
| Selected | at least one image `selected` | Selected cards show checkmark; selection count chip in header |

**Anti-silent-failure rule:** every failed API call (search, retry, select, delete, load) renders a visible error message near the action that failed. No swallowed exceptions.

---

## 7. Image Card Behavior

- **Thumbnail:** `thumb_url` when present, else `url` — plain `<img>` with `referrerPolicy="no-referrer"` and an `onError` fallback to a local neutral placeholder (CSS muted rectangle — no external placeholder service). Lazy `loading="lazy"`.
- **Caption:** 1-2 lines (CSS line clamp), rendered via the safe markdown renderer if it contains markup; otherwise plain text.
- **License chip:** `license` text; `attribution_required` appends a small "attribution required" marker.
- **Selection affordance:** border highlight + check icon for `selected`; controls hidden for `rejected`.
- **Rejected:** dimmed/greyed, `rejection_reason` shown (title attribute + detail sheet), no select action.
- **Detail:** clicking the card opens `ImageDetailSheet` with full attribution, license + `license_url`, source `page_url`, `usage_notes`, and metadata (`width x height`, `file_size`, `mime`, `provider`, `retrieved_at`).

---

## 8. License & Attribution UX

- Every image card and the detail sheet **always show** the `license` value and any `attribution`/`author` string.
- When `attribution_required` is true, show a persistent note: "Attribution required — must credit the author when publishing." This note is not dismissible.
- `license_url` links out (new tab, `target="_blank" rel="noopener noreferrer"`) to the license text.
- `page_url` links to the source page on Wikimedia Commons.
- The selected-image summary in the panel header lists how many selected images carry `attribution_required` — a pre-publish reminder.
- **Nothing about licensing is ever hidden by the UI.**

---

## 9. Selection / Removal / Re-search

Flow rules enforced by the UI (backend enforces them too — UI is a second line):

1. **Search** is only offered when article status in {`checked`, `image_ready`}. If the backend returns 409, show the server's message verbatim.
2. **Select** an image: `POST .../images/{id}/select` -> on success refetch. **Does not change article status.**
3. **Remove** a selection: `DELETE .../images/{id}` -> on success refetch.
4. **Rejected** images: no select action; `rejection_reason` displayed.
5. **Re-search**: only when status in {`checked`, `image_ready`} and no job `running`. Buttons disabled otherwise.

---

## 10. Approval Gate Preservation

- The approve action in `ArticleDetailCard` remains the single path to `ready_for_review`. The images panel renders **no** approve control.
- `images_searching` / `image_ready` states do not weaken the existing `checked -> ready_for_review -> approved` transition.
- The approve button stays **disabled** while the image job is `running` (backend enforces too; UI shows the server message as the reason).
- Regression tests assert both: the panel renders no approve control, and the approve button is disabled while `running`.

---

## 11. Security

- **No new backend surface** — the 4D endpoints already enforce ownership (`_owned_image`), state guards, and 409 on rejected-selection.
- **External images** are rendered with `<img>` (not `next/image`), `referrerPolicy="no-referrer"`, `loading="lazy"`, no `srcset` from untrusted hosts. No image content is ever executed as HTML/JS.
- **No `dangerouslySetInnerHTML`.** All strings rendered via the existing `escapeHtml` / `renderMarkdown` allowlist (`src/lib/markdown.ts`).
- **Links** (`page_url`, `license_url`) open via `target="_blank" rel="noopener noreferrer"`; URLs only ever appear in `href` attributes from backend data (no user-entered HTML).
- **CSRF / auth:** v1 is single-user self-hosted; the existing fetch wrapper is used unchanged.
- **Metadata rendering** (caption/attribution/usage_notes): treat all as untrusted text -> escape; only allow the existing markdown subset (no raw HTML, no arbitrary schemes).
- **Rejected-state integrity:** the UI never ships a select action for a `rejected` image; even if it did, the backend 409s.

---

## 12. API Integration

Add to `src/lib/api.ts` (typed, matching existing conventions):

```ts
export interface ImageRecord { /* mirrors ImageRead fields above */ }
export interface ArticleImages { article_id: number; status: string; running: boolean; images: ImageRecord[]; }

export function getArticleImages(articleId: number): Promise<ArticleImages>       // GET
export function searchArticleImages(articleId: number): Promise<ArticleImages>    // POST search (202)
export function retryArticleImages(articleId: number): Promise<ArticleImages>     // POST retry (202)
export function selectArticleImage(articleId: number, imageId: number): Promise<ArticleImages>
export function removeArticleImage(articleId: number, imageId: number): Promise<ArticleImages>
```

- All return the refetched `ArticleImages` — single response drives state; **no optimistic mutation, no hand-rolled client store** ("prefer simple refetch").
- `statusLabel`: add `images_searching -> "Searching for images..."` (confirm `image_ready` and `ready_for_review` mappings already exist — they do).
- Errors: reuse `ApiError`; surface `error.detail` verbatim when present (backend returns human-readable 409 messages).

---

## 13. Testing Plan

Follow existing vitest conventions. No new framework, no new mocking setup beyond `src/test/setup.ts`.

**Unit — `api.test.ts` (or new `api-images.test.ts`):**
- `statusLabel` mappings for `images_searching`, `image_ready`, `ready_for_review`, unknown passthrough.
- Each new API function: correct method/URL/body, error propagation (`ApiError` with detail).

**Component — `article-images-panel.test.tsx` (modeled on `states.test.tsx`):**
- Renders CTA when `checked` and no images.
- Renders skeleton + running badge while `running`.
- Renders grid when `image_ready`.
- Select button calls `selectArticleImage` and refetches; select button absent for `rejected`.
- Delete/remove calls `DELETE`; 409 message shown verbatim.
- License chip + attribution-required note render from fixture data.
- Approve control is NOT rendered by the panel (approval-gate regression test).
- Error path shows `ErrorState` with retry.

**Integration / e2e (manual QA, no new framework):**
- Full happy path: article -> `checked` -> search -> `images_searching` -> `image_ready` -> select -> review -> approve.
- Backend 314 tests must stay green.

---

## 14. Responsive / Mobile

- Grid: `grid-cols-2 sm:grid-cols-3 lg:grid-cols-4` responsive layout matching the existing design system.
- Detail view: `Sheet` slides in on mobile; content scrolls via existing `ScrollArea`.
- Touch targets >= 44px on card actions; sheet close and select buttons reachable without hover (no hover-only affordances).
- Running/search state works on small screens (skeleton cards shrink fine).

---

## 15. Performance

- **No new polling added for images** — the images panel refetches only on: panel mount, action success/failure, and while `running` (reuse the articles view's existing running-refetch cadence, ~2s).
- **Bounded rendering:** images are capped by the backend candidate limit; the grid renders only `images.length` cards (no pagination needed at this scale).
- **Lazy images** (`loading="lazy"`), small thumbnails (`thumb_url`), no `srcset` from untrusted hosts.
- **No heavy client deps** — only existing `lucide-react` icons already in the project.
- Refetch responses are small JSON; no client state library.

---

## 16. Implementation Sequence

Ordered so each step is independently testable. (Adjusted from the initial 4E-1..4E-7 sketch to match repo structure.)

- **4E-1. API client + labels** — `src/lib/api.ts`: types, five functions, `statusLabel` additions. Tests in `api.test.ts`.
- **4E-2. Panel shell + state machine** — `ArticleImagesPanel`: fetch on mount, render Loading/Empty/Error/Running per section 6, running-refetch. Tests: panel state rendering.
- **4E-3. Search + retry actions** — CTA button, retry on error, 409 verbatim display. Tests: action wiring.
- **4E-4. Grid + cards** — `ImageGrid`, `ImageCard` (thumbnail, caption, license chip, selection state, lazy images). Tests: card rendering from fixture.
- **4E-5. Detail sheet** — `ImageDetailSheet`: full attribution/license/usage/metadata. Tests: sheet rendering + no approve control.
- **4E-6. Select / remove / rejected** — select, remove, rejected-dimming + `rejection_reason`, selected-count chip, attribution-required reminder. Tests: gate regression, 409 path.
- **4E-7. Final review** — run `/review` on the diff, full backend + frontend suites, manual QA of the happy path, `/qa`-style check of the panel.

---

## 17. Files to Change

- `frontend/src/lib/api.ts` — types + 5 API functions + `statusLabel` additions.
- `frontend/src/components/articles/articles-view.tsx` — mount `ArticleImagesPanel` in `ArticleDetailCard`; disable approve while image job running.
- `frontend/src/components/articles/article-images-panel.tsx` — **new**.
- `frontend/src/components/articles/image-grid.tsx` — **new**.
- `frontend/src/components/articles/image-card.tsx` — **new**.
- `frontend/src/components/articles/image-detail-sheet.tsx` — **new**.
- `frontend/src/lib/api.test.ts` (or `api-images.test.ts`) — tests.
- `frontend/src/components/articles/article-images-panel.test.tsx` — tests.
- `docs/03-phase-4e-image-ui-plan.md` — this plan (revision notes only).

---

## 18. Files NOT to Change

- `backend/**` — no backend changes in 4E (contract already exists).
- `frontend/src/components/ui/**` — no new primitives, no edits.
- `frontend/src/components/states/**` — reused as-is.
- `frontend/src/lib/markdown.ts` — reused as-is (only if a genuinely missing safe-markup case arises, and only with review).
- `frontend/package.json` / `frontend/package-lock.json` — **zero new dependencies**.
- `frontend/next.config.ts`, `frontend/eslint.config.mjs`, `frontend/vitest.config.ts`, `frontend/src/test/setup.ts` — unchanged.
- `docs/02-phase-4-image-plan.md`, `CLAUDE.md`, other `docs/` files — unchanged.
- Any DB/schema/migration files — unchanged.

---

## 19. Dependencies

- **Zero new npm dependencies.** All components, icons (`lucide-react`), and primitives already exist in the project.
- Zero new Python/pip dependencies.
- Zero new LLM calls (image search is the existing Commons provider path from 4D, already tested).

---

## 20. Non-Goals

- No approval, publish, or scheduling behavior from the images panel.
- No image upload, download, or local persistence.
- No AI image generation; no Pexels/Unsplash/Openverse providers.
- No caption/license editing; no drag-reorder of images.
- No multi-article bulk image management.
- No new UI primitives or styling system changes.
- Phase 4F and Phase 5 (Blogger publishing) are explicitly **not** started here.

---

## 21. gstack CEO Review Findings

Review lens: **HOLD SCOPE** with one selective expansion offered. The core product decision (images are suggestions, human approves) is already correct and matches the CLAUDE.md ground rules, so the review did not push scope expansion.

Findings:
1. **Approval gate is the crown jewel — protect it.** The single most valuable property of this phase is that image selection never implies approval. Confirmed the plan keeps the approve control exclusively in `ArticleDetailCard` and adds a regression test asserting the panel renders no approve control. No action needed beyond the plan.
2. **Attribution compliance is a product risk, not just a legal nicety.** A user could publish without crediting the author. The plan's always-visible license chip + attribution-required note + pre-publish reminder count chip directly address this. Accepted as-is.
3. **"Images ready but none selected" is the real-world default state.** The reviewer will not always pick an image. The plan must make it obvious the article can proceed to review/publish without an image (backend permits it). Added to Empty-state copy intent: the empty/zero-selected state should hint that publishing without an image is allowed and acceptable.
4. **Deferred (selective expansion, not taken):** auto-suggest a "cover image" / default selection. Rejected for v1 — it contradicts the "no auto-approval" spirit and the product rule. Noted as a future idea in section 20's spirit, not committed.

Net: scope holds. No MUST-FIX from the CEO lens; three polish notes above are folded into sections 6 and 9.

---

## 22. gstack Engineering Review Findings

Review lens: architecture / data flow / edge cases / tests / performance on the plan.

**MUST-FIX:**
1. **`running` vs `status` reconciliation.** During `images_searching`, the article-level `running` flag may also be true from other jobs. The panel must render the searching state from `status == images_searching` (the panel's own field), and treat `running` only as a secondary "in-flight" signal, so a concurrent non-image job does not falsely render the image grid as searching. Folded into section 6.
2. **Race: user clicks search, then article is edited / status changes.** Backend 4D already hardens this (populate_existing + status re-read); the UI must simply show the 409 message verbatim and refetch. Folded into section 9.1. No UI-level optimistic state.
3. **`onError` image fallback must not loop.** The fallback handler must swap to a placeholder state once, not re-render infinitely on error. Add explicit "already failed" guard in `ImageCard` (section 7.1).
4. **Approve-during-running must be tested on the frontend too.** Backend blocks it; the UI disables the button. Add a component test asserting the approve button is disabled while `running` (new assertion in `article-images-panel.test.tsx`).

**SHOULD-FIX:**
5. **Bounded refetch while `running`:** cap the running-refetch to a max duration (e.g. stop after ~120s of continuous `running`) so a hung job does not poll forever. Backend will eventually surface an error; UI should show the last known state with a retry. Folded into section 15.
6. **Sort stability:** render images in `position` then `relevance` order so re-search results do not visibly reorder between refetches. Folded into section 7.
7. **Accessibility:** the sheet must trap focus / close on Escape (the existing `Sheet` primitive already handles this); selection state must not rely on color alone (add the check icon). Folded into sections 7 and 13.

**Performance:** no new polling beyond the running-refetch cadence; bounded rendering; lazy images. No findings.

**Tests:** covered in section 13; the two new assertions from findings 4 and 2 are added.

Net: 4 MUST-FIX + 3 SHOULD-FIX, all folded into the plan sections. No architecture change required.

---

## 23. Final Recommendation

**Proceed with Phase 4E as planned** after approval. The plan:

- Ships a reviewer-facing image panel with zero new dependencies and zero backend changes.
- Preserves the human approval gate and attribution compliance as first-class UX, enforced on both sides (backend from 4D, UI checks here).
- Adds focused vitest coverage for every state and the approval-gate regression.
- Stays within Phase 4E scope: Phase 4F and Phase 5 are not started.

Implementation order: 4E-1 .. 4E-7 (section 16). Each step is independently testable; 4E-7 ends with a `/review` + full-suite run before any ship discussion.

Wait for approval before writing any application code.
