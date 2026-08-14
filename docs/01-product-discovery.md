# Product Discovery — blogger-ai-automation

**Status:** Complete (Step 1). No application code exists yet.
**Method:** gstack workflow — office-hours (product discovery), plan-ceo-review + plan-eng-review (review lenses) applied to this document.
**Decisions locked in this step (user-confirmed):**
- Self-hosted, single-user (no account system in v1)
- Research via structured free APIs only (Wikimedia, Wikidata, DuckDuckGo Instant Answer)
- Images via free CC/stock sources first (Wikimedia Commons primary; Pexels/Unsplash optional)
- Default Ollama model class: 3-4B, configurable per task

---

## 1. Product definition

**One-liner:** A free, self-hosted pipeline that turns a blog idea into a researched, quality-checked, image-ready article and publishes it to Blogger.

**Target user (discovery item 1):** A solo blogger / hobbyist writer who runs one or more Blogger sites, wants consistent output, and will not pay for AI SaaS. Likely the user themselves first. Single human operator, single machine, one Ollama instance, one Blogger connection. All workflows are async (generation takes minutes on CPU), so the UI is a review-and-approve console, not a live editor.

**Core problem (discovery item 2):** Writing a researched, decent article per day is slow: research, drafting, SEO, images, formatting, and publishing are separate drudgery steps. Paid tools (Jasper, Copy.ai, Surfer, Rytr) solve parts of it but cost money and lock content into their model APIs. Free-first, local, Blogger-native automation does not exist as a turnkey package.

**Core workflow (discovery item 3):** idea -> research (free APIs) -> research summary with sources -> article draft -> SEO metadata -> quality/policy checks -> image selection -> human review -> save draft -> schedule or publish -> Blogger API -> status tracking.

**Main user journey (discovery item 6):**
1. Create a project: enter a blog idea (a sentence, a title, a keyword) and pick a target Blogger blog.
2. Run research. See a summary with clickable sources; edit or regenerate.
3. Generate the article. Read and edit the draft in the review screen.
4. Review the automated checks (SEO score, policy risk, repetition warning, source coverage). Fix or accept.
5. Pick images (auto-suggested free CC images). Approve or swap.
6. Save as draft, or pick a publish time.
7. Watch status move: scheduled -> publishing -> published (or error with retry).

**Critical risks (discovery item 7):**
- **Content quality on a 3-4B local model** — acceptable but mediocre for long-form. Mitigation: strong prompting, research grounding, human review gate, configurable bigger model for the drafting step.
- **Factual accuracy / hallucination** — model invents facts. Mitigation: source-grounded drafting (model sees the research summary), inline source links, checks that flag claims not traceable to a source, human review.
- **Publisher policy violations** — Blogger/AdSense content rules. Mitigation: policy checks before publish, human gate, no guarantees promised.
- **Free API reliability** — Wikimedia is stable; DuckDuckGo IA is limited; rate limits. Mitigation: caching, backoff, graceful degradation (research can proceed with fewer sources).
- **OAuth/token failure** — Blogger token expires or is revoked. Mitigation: refresh token, clear error + reconnect flow, status kept in DB.
- **Low-resource runtime** — 8 GB RAM shared with Ollama. Mitigation: small default models, one model loaded at a time, serial pipeline, SQLite WAL.
- **Duplicate/low-value content** — repetition across articles. Mitigation: originality/repetition warnings against published articles.
- **Scope creep** — the platform-shaped ambition. Mitigation: strict v1 scope (section 2), everything else deferred (section 3).

**Free-resource constraints (discovery item 8):** Total external cost must be $0. No mandatory API keys, no paid tiers, no paid model. Everything used must have a free tier that is genuinely usable, or run locally. The only exceptions are optional connectors a user can enable themselves (e.g. a free-tier Pexels key).

**Blogger integration requirements (discovery item 9):**
- OAuth 2.0 (authorization code + refresh token, offline access).
- Blogger API v3 operations: `blogs.getByUrl`, `posts.insert` (draft/live), `posts.patch`, `posts.list` (status sync), `posts.get`, `posts.delete`.
- Scope: `https://www.googleapis.com/auth/blogger`.
- Scheduled posts via `publishDate` (ISO 8601) — Blogger supports future publish dates.
- Images: Blogger fetches images referenced by URL in post HTML; no upload API needed for v1.
- Publish status tracked both locally and synced back from Blogger (live/draft/scheduled).
- One blog connection in v1 (single-user), designed so the table allows more later.

**AI requirements (discovery item 10):**
- Ollama is the only AI provider. Optional later: a per-task "provider" switch (e.g. free OpenAI trial) — deferred, never mandatory.
- Default model 3-4B (qwen2.5:3b class). Drafting may use a larger model if the user sets one.
- Tasks: research summarization, article drafting, SEO metadata, checks (policy, quality, repetition), image search query generation, title variants.
- Streaming generation where the UI can show progress; cancel support.
- Deterministic structured output where possible (JSON with strict schema for SEO meta; the rest as prose with a parsing fallback).
- Guardrails: system prompt pinned; research text treated as untrusted data (prompt-injection resistant); human review is the final gate.

**Research requirements (discovery item 11):**
- **ResearchProvider is a strict abstraction** (design constraint). The core pipeline depends only on the provider interface, never on a specific provider. Each provider implements a common contract (search/query -> normalized `Source` results) and registers itself in a provider registry.
- Initial free providers: Wikimedia REST API (search, summary, page images, categories), Wikidata REST/SPARQL, DuckDuckGo Instant Answer API. These are the first implementations, **not** assumed to be comprehensive coverage for every topic.
- Additional free providers can be added later (a new class implementing the interface + registry entry) **without changing the core research pipeline** — no changes to pipeline logic, article generation, or the data model.
- The orchestrator runs all enabled providers for a topic, merges results, deduplicates, and produces the research summary plus a list of sources (title, URL, snippet, relevance).
- Research is cached by topic hash; re-research is explicit.
- Graceful degradation: if a provider is down, continue with the others and note coverage.
- Every article section can reference its sources; sources are surfaced in the review UI and optionally injected into the post as links.

**Image requirements (discovery item 12):**
- Primary: Wikimedia Commons (free, no key) — image search by topic, CC/PD licensed.
- Optional: Pexels / Unsplash free tiers (require user-supplied key).
- Selection: model generates search queries from the topic; candidate images listed with license + attribution; user approves in review.
- Output: image URL + alt text + optional caption + attribution line embedded in post HTML.
- No local image generation in v1 (hardware reality: minutes-per-image on CPU, 8 GB RAM). Documented as a later optional module.

**SEO requirements (discovery item 13):**
- Metadata: title (<=60 chars), meta description (<=160 chars), slug, one H1, section headings, alt text, internal/external link suggestions, target keyword variants.
- Checks: title/description length, keyword presence in title/first paragraph/H1, heading structure, image alt coverage, readability, word count vs. target.
- Honest framing only: output is SEO *checks and suggestions*, not "guaranteed ranking" (product principle below).

**Publishing requirements (discovery item 14):**
- Save as Blogger draft, publish now, or schedule at a chosen time.
- Serial in-process scheduler (APScheduler) in the backend process; DB is the source of truth for due jobs.
- Status state machine per article (section 8) with explicit error + retry states.
- Post-build HTML: converted from the article body + images + SEO meta, injected into the Blogger template-compatible content.
- On failure: keep the article in a recoverable state, show a named error, allow retry.

**Security requirements (discovery item 15):**
- Bind the web app to 127.0.0.1 by default (single-user local tool). If exposed, an API token.
- Blogger OAuth tokens stored with restricted file permissions, never committed, not in logs.
- Secrets via `.env` (gitignored); `.env.example` committed.
- Outgoing research fetches restricted to https + known hosts.
- Prompt injection defense: research/source text is data, not instructions; strip/escape in prompts.
- Content policy: publisher-policy checks run before any publish; user must review before publish.
- CSRF/local auth: cookie-based session is sufficient for localhost; add a simple auth token if bound to a network interface.
- Dependency discipline: minimal, maintained libraries only (supply-chain risk stays low).
- Audit trail: publish log records who/what/when/result for every external action.

---

## 2. MVP scope

| Area | In v1 |
|---|---|
| Idea -> research -> summary + sources | Yes |
| Article draft (Ollama, source-grounded) | Yes |
| SEO metadata + SEO checks | Yes |
| Quality / policy / repetition checks | Yes |
| Image suggestion from free CC/stock sources | Yes |
| Human review + inline editing | Yes |
| Save draft / publish now / schedule | Yes |
| Blogger API v3 publish + status tracking | Yes |
| Local scheduling (APScheduler) | Yes |
| Single Blogger connection | Yes |
| Settings: Ollama model, image sources, blog | Yes |

MVP definition (discovery item 4): the full pipeline above working end-to-end for one user on one machine, with every stage resumable and every failure visible.

**Main data entities (section 7) and workflow (section 8) are part of MVP.**

## 3. Non-MVP scope (discovery item 5)

- Multi-user accounts / per-user Blogger connections / SaaS hosting.
- WordPress or any second publishing platform.
- Local image generation (Stable Diffusion).
- Paid AI providers as mandatory path (optional per-task provider switch deferred).
- Advanced analytics / AdSense reporting / traffic dashboards.
- Bulk article generation or content calendars beyond simple scheduling.
- Team workflows, roles, review chains.
- Comment moderation, blog management beyond posting.
- Indexing/ranking automation of any kind.

Each of these is written down as a deferred item, not an unstated promise.

---

## 4. Proposed architecture

**Modular monolith.** One backend process (FastAPI) exposing a REST API and running APScheduler; one frontend (Next.js) served by the backend in production or run separately in dev. All pipeline logic lives in the backend as Python modules. No message broker, no Redis, no microservices. PostgreSQL only if a concrete reason appears (none yet — SQLite first).

```
┌─────────────────────────────── LOCALHOST ───────────────────────────────┐
│                                                                          │
│  ┌─────────────────────┐          ┌───────────────────────────────────┐ │
│  │  Next.js frontend    │  REST    │  FastAPI backend (single proc)    │ │
│  │  (UI console:        │ ──────►  │                                   │ │
│  │   ideas, review,     │          │  app/ (routing, schemas, auth)    │ │
│  │   publish, settings) │          │  pipeline/ (core modules)         │ │
│  └─────────────────────┘          │  scheduler.py (APScheduler)       │ │
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

Data flow (all four paths are designed, section 5 of the review lens):

```
IDEA ──► RESEARCH ──► SUMMARY ──► DRAFT ──► SEO ──► CHECKS ──► IMAGES ──► REVIEW ──► SCHEDULE/PUBLISH ──► STATUS
  │          │            │          │        │        │         │          │             │
  │          ▼            ▼          ▼        ▼        ▼         ▼          ▼             ▼
  [nil?]   [no hits?]  [0 sources?] [empty?] [none?]  [fail?]  [no match?] [rejected?] [OAuth fail?]
  [empty?] [timeout?]  [tiny?]      [error?] [error?] [error?] [licence?]  [stale?]   [rate limit?]
  [wrong type?]                        (every stage persists to SQLite -> resumable, no data loss)
```

- Every stage is a Python module with a stable input/output (Pydantic schema) persisted to SQLite. A stage can be re-run without re-running the whole pipeline.
- The pipeline runs inside the backend process, serialized (concurrency = 1) to protect Ollama and RAM.
- The frontend polls or uses SSE for stage progress; generation streams where feasible.

## 5. Proposed technology stack

| Layer | Choice | Why (boring by default, proven, light) |
|---|---|---|
| Frontend | Next.js (App Router, TypeScript), Tailwind CSS, shadcn/ui | Requested; mainstream; fine on this hardware when kept lean |
| Backend | FastAPI + Pydantic + Python 3.11/3.12 | Requested; async-friendly; single process |
| DB | SQLite (WAL mode) via SQLAlchemy | Zero-ops, zero cost, plenty for single user; PostgreSQL noted as the documented upgrade path if ever needed |
| AI | Ollama (local), default 3-4B model | Free, local, private |
| Scheduler | APScheduler in-process | No broker, no Redis; DB is the durable job store |
| Publishing | Blogger API v3, google-auth-oauthlib + httpx | Official OAuth flow, light |
| Images | Wikimedia Commons REST (Pexels/Unsplash optional) | Free, no mandatory key |
| Container | Dockerfiles provided; local dev runs bare metal | Keep dev simple |
| HTTP client | httpx | Async, one client for web + APIs |

Deferred / explicitly not in v1: Celery+Redis, PostgreSQL, Kafka, any queue, Docker Compose as a requirement, paid providers.

## 6. Proposed directory structure

```
blogger-ai-automation/
├── README.md
├── CLAUDE.md
├── .gitignore
├── .env.example
├── docs/                       # planning + design docs
├── backend/
│   ├── pyproject.toml          # or requirements.txt
│   ├── app/
│   │   ├── main.py             # FastAPI app, route mounting, scheduler start
│   │   ├── config.py           # settings (pydantic-settings) from .env
│   │   ├── api/                # routers: ideas, articles, publish, settings, auth
│   │   ├── schemas/            # Pydantic request/response models
│   │   └── deps.py             # auth guard (local token)
│   ├── pipeline/
│   │   ├── state.py            # article state machine + transitions
│   │   ├── research/           # orchestrator: runs enabled providers, merges + dedupes, caches
│   │   │   ├── __init__.py     # run_research(topic, ...) entry point
│   │   │   └── providers/      # ResearchProvider interface + registry
│   │   │       ├── __init__.py
│   │   │       ├── base.py     # ResearchProvider ABC + Source model (strict contract)
│   │   │       ├── registry.py # provider registry (add a provider here + one class)
│   │   │       ├── wikimedia.py# initial provider: Wikimedia REST
│   │   │       ├── wikidata.py # initial provider: Wikidata REST
│   │   │       └── duckduckgo.py# initial provider: DDG Instant Answer
│   │   ├── summarize.py        # research -> summary + sources (LLM)
│   │   ├── draft.py            # summary -> article draft (LLM)
│   │   ├── seo.py              # SEO metadata + checks (LLM + rules)
│   │   ├── checks.py           # quality / policy / repetition checks
│   │   ├── images.py           # image search + selection + attribution
│   │   ├── html.py             # post HTML build (content + images + meta)
│   │   └── publish.py          # Blogger API wrapper + status sync
│   ├── services/
│   │   ├── ollama_client.py    # HTTP client, streaming, structured output
│   │   ├── blogger_client.py   # OAuth token mgmt + API calls
│   │   └── image_providers.py  # commons / pexels / unsplash adapters
│   ├── db/
│   │   ├── base.py             # SQLAlchemy engine/session (SQLite WAL)
│   │   ├── models.py
│   │   └── seed.py
│   ├── scheduler.py            # APScheduler jobs (due publish scan)
│   ├── tests/
│   └── Dockerfile
├── frontend/
│   ├── package.json
│   ├── next.config.ts
│   ├── src/
│   │   ├── app/                # pages: dashboard, idea/new, article/[id], settings
│   │   ├── components/         # ui/ (shadcn), article-review, checks, images, publish
│   │   ├── lib/                # api client, types
│   │   └── styles/
│   └── Dockerfile
└── scripts/                    # oauth setup, ollama model pull, dev runners
```

## 7. Main data entities

| Entity | Key fields | Notes |
|---|---|---|
| `Setting` | key, value | Ollama URL/model, image sources, defaults |
| `BlogConnection` | id, blog_id, blog_url, token_data (encrypted at rest), status | one active in v1; table allows more |
| `Idea` | id, title, prompt/notes, created_at | the starting input |
| `Research` | id, idea_id, topic_key (cache hash), summary_text, status | cached per topic |
| `Source` | id, research_id, title, url, snippet, relevance, license | pulled from research; used for grounding + links |
| `Article` | id, idea_id, blog_id, title, slug, body (HTML), seo_title, meta_description, word_count, status, review_approved_at | central entity |
| `Image` | id, article_id, provider, url, alt, caption, attribution, license, order | approved set embedded in post |
| `CheckResult` | id, article_id, check_type, passed, severity, message, details | SEO / quality / policy / repetition |
| `PublishJob` | id, article_id, run_at, status, error, retry_count, published_at | scheduled or immediate publish |
| `PublishLog` | id, article_id, action, result, details, created_at | audit trail |

## 8. Main workflow / state machine

Article lifecycle (persisted; every transition writes a log row):

```
draft                        # idea recorded
  -> researching             # pipeline running research
  -> researched              # summary + sources ready (reviewable)
  -> drafting                # LLM generating article
  -> drafted                 # body ready (reviewable/editable)
  -> seo_done                # SEO meta + checks generated
  -> checked                 # all checks run, results visible
  -> image_ready             # images selected/attached
  -> ready_for_review        # user edits + approves
  -> approved                # user approved content + images
  -> scheduled               # PublishJob queued with run_at
  -> publishing              # job running (Blogger API call)
  -> published               # success; verified from Blogger
  -> publish_failed          # error; named, retryable (goes back to scheduled)
```

Invalid/impossible transitions are blocked by the state module (single writer). Stuck states (e.g. `publishing` for >N minutes) are auto-flagged to `publish_failed` by a watchdog. Any stage can also be re-run manually from its parent state.

## 9. Free-resource strategy

| Need | Free resource | Cost | Key/limits | Risk + mitigation |
|---|---|---|---|---|
| Research | Wikimedia REST + Wikidata REST/SPARQL | $0 | none; polite UA + cache | stable; cache by topic |
| Research (extra) | DuckDuckGo Instant Answer | $0 | none | shallow; degrade gracefully |
| Images | Wikimedia Commons | $0 | none | license/attribution handled |
| Images (optional) | Pexels / Unsplash free tier | $0 (key required) | free API quota | optional; user enables |
| AI | Ollama (3-4B) | $0 (electricity) | local CPU | quality; see section 1 risks |
| Publish | Blogger API v3 | $0 | free tier ~unlimited | OAuth mgmt |
| Hosting | localhost | $0 | — | bind 127.0.0.1 |

Rule: no stage may require a paid anything. Optional connectors exist only behind user opt-in, never blocking the core path.

## 10. Blogger integration strategy

1. **Setup:** user creates a Google Cloud OAuth client (Desktop type) + enables Blogger API. The app provides a guided "Connect Blogger" flow and a script (`scripts/oauth_setup.py`) that completes the authorization-code flow on localhost and stores a refresh token.
2. **Token handling:** `google-auth-oauthlib` stores token data in `BlogConnection` (encrypted with a local key from `.env`), refreshes automatically via the refresh token. If refresh fails: article stays `ready_for_review`-safe, connection shows "reconnect", nothing is lost.
3. **Operations:** `posts.insert` (status draft|live), `posts.patch`, `posts.get`, `posts.list` with `status` filter, `blogs.getByUrl` to resolve the blog id.
4. **Scheduling:** publish time passed as `publishDate` in ISO 8601 to Blogger; local PublishJob tracks `run_at`. After publish, status sync reads `posts.list(statuses=...)` and reconciles local state.
5. **Post HTML:** body built from article content; image URLs + alt + attribution embedded; SEO meta applied to Blogger fields (`title`, `metaDescription` where supported, `labels` from SEO keywords).
6. **Failure handling:** named errors (OAuth, 429, 404 blog, validation) mapped to user-visible messages with retry/backoff. Every call logged in `PublishLog`.

## 11. Security risks

| Risk | Likelihood | Impact | Mitigation (in plan) |
|---|---|---|---|
| Blogger token exfiltration | Low | High | Tokens encrypted at rest, file perms 600, never in logs/git |
| Prompt injection via research/source text | Medium | Medium | Sources treated as data; pinned system prompt; human review gate |
| Local service exposed on network | Medium | High if exposed | Bind 127.0.0.1 by default; token auth if bound to LAN |
| Content policy violation published | Medium | Medium | Policy checks before publish; human approval gate; no guarantees promised |
| SSRF from research fetch | Low | Medium | https-only, allowlisted hosts, no arbitrary user URLs in v1 |
| Secrets in repo | Medium | High | `.env` gitignored; `.env.example` only; CI secret scan |
| Dependency supply chain | Medium | Medium | Minimal pinned deps; review before adding |
| Duplicate/spammy content published | Medium | Medium | Repetition warning vs published history; human gate |

No credentials are ever committed. OAuth secrets and tokens live only in local storage with restricted permissions.

## 12. Performance considerations for low-resource hardware (8 GB RAM, i5-6500, CPU-only)

- **Ollama:** default 3-4B model (qwen2.5:3b class). One model loaded at a time (`OLLAMA_KEEP_ALIVE` tuned); pipeline runs serially (concurrency = 1). Drafting on a larger model is user-optional, expected slow (minutes), UI must be async/progress-aware.
- **SQLite WAL** + minimal indexes on `Article.status`, `PublishJob.run_at`. No heavy ORM overhead at this scale.
- **Research cache** by topic hash avoids repeat network + LLM cost.
- **No heavy NLP** (no spaCy/torch outside Ollama). Checks use regex/rules + small LLM calls.
- **Frontend:** lean Tailwind/shadcn; no heavy chart libs; static generation where possible; Next dev server on `--turbo` or built static served by FastAPI in prod.
- **Memory budget (estimated):** backend ~200 MB, Next dev ~500 MB, Ollama 3B ~2-3 GB, OS + browser rest. Fits 8 GB. Watchdog logs RAM if Ollama is forced to swap.
- **Resumability:** every stage persists; a failed long generation can be retried without losing earlier stages.

## 13. Proposed development phases

Each phase ends with `/review` (and `/qa` once a usable app exists) before the next begins. Phase 1 not started — awaiting approval.

- **Phase 0 (done):** workspace, git init, planning files, this discovery doc.
- **Phase 1 — Skeleton:** backend FastAPI app + SQLite schema + settings; Next.js shell (dashboard, settings, idea form); health check; docker files optional. Verify toolchain (python, node, ollama).
- **Phase 2 — AI + Research:** Ollama client; research (Wikimedia/Wikidata/DDG) with cache; summarize stage; research review UI.
- **Phase 3 — Generation + checks:** draft stage; SEO metadata + checks; quality/policy/repetition checks; review UI with inline editing and check panel.
- **Phase 4 — Images:** Commons image search + attribution; image selection UI; post HTML builder.
- **Phase 5 — Blogger:** OAuth connect flow; publish now / draft / schedule; APScheduler jobs; status tracking + sync; publish log.
- **Phase 6 — Hardening + QA:** `/qa` full pass on the running app, `/investigate` for any bugs, security pass, README/docs, release.

---

## Product principle (baked into scope and UI)

The app **does not promise** "guaranteed AdSense approval", "guaranteed Google ranking", or "guaranteed indexing". It delivers: SEO checks, content quality checks, publisher-policy risk checks, originality/repetition warnings, source tracking, and a mandatory human review before publication. All copy, docs, and UI wording reflect this.

## Review lens findings (CEO + Eng, applied to this plan)

- **Premise challenge (CEO):** Core premise holds — free local-first Blogger automation is a real niche; wedge = the full single-user pipeline working end-to-end, not a component. The biggest risk is quality, so review-gated generation and honest checks are features, not overhead. No reason to widen to multi-user before v1 proves the loop on one user.
- **Architecture (Eng):** Modular monolith + SQLite + in-process scheduler is the right-sized call for one user on one machine; Redis/Celery/PostgreSQL would be accidental complexity today. Model (boring by default): FastAPI, SQLAlchemy, APScheduler, google-auth, httpx are all proven.
- **Error & rescue:** every named failure (OAuth expiry, API 429/timeout, malformed LLM JSON, empty research, publish race) has a mapped rescue + user-visible message + retry path. No silent failures.
- **Security:** covered in section 11; the human approval gate is the strongest control against bad output reaching the internet.
- **Data flow:** all four shadow paths (nil, empty, error, stale) traced per stage; every stage persisted so nothing is lost mid-pipeline.
- **Observability:** structured logs per stage, publish audit log, RAM/queue watchdog, stuck-state detection.
- **Reversibility:** SQLite + local tokens + simple REST = every decision two-way door; nothing one-way in v1.
- **Deferred, written down:** multi-user, WordPress, local image gen, analytics, bulk calendars, paid-provider path. No unstated promises.

## Open questions for approval

1. Approve this discovery document and scope as-is?
2. Approve phases 1-6 sequencing (Phase 1 skeleton first)?
3. Commit these planning files to the new git repo (recommended: yes)?
