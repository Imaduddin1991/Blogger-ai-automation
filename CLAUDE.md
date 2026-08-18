# CLAUDE.md

Project instruction file for working in this repo with OpenCode/gstack.

## Project

- **Name:** blogger-ai-automation
- **Purpose:** Free, self-hosted AI Blogger automation platform (idea -> research -> article -> SEO -> checks -> images -> review -> publish to Blogger).
- **Constraints:** free-first, local AI via Ollama, Blogger-only for v1, lightweight (8 GB RAM, i5 6th gen), modular monolith.
- **Status:** Phase 1 + 2 + 3 + 4 + 5 + 6A/6B/6C implemented and tested (backend 660 tests, frontend 73 tests). Phase 6C (Token Auto-Refresh) complete: token_expires_at column, auto-refresh on publish, manual refresh endpoint, settings UI with expiry display. Phase 6B (Scheduled Publishing) complete: APScheduler integration, schedule/cancel/list endpoints, frontend schedule UI on publish panel, scheduled articles page. Phase 6A (Publish History & Status) complete: publish log API, publish history UI, dashboard stats, status badges. Phase 5 (Blogger Publishing) complete: 5A client abstraction, 5B OAuth connect, 5C content builder, 5D publishing service, 5E API, 5F frontend UI. Phase 4 (images) complete: 4A provider abstraction, 4B Wikimedia Commons, 4C validation/dedup, 4D pipeline integration, 4E frontend review UI, 4F hardening. Phase 3.1 quality fixes shipped. See `docs/`.

## Ground rules

- **Never touch `/home/imad_uddin/ai-blog-automation`.** It is the old project and must remain untouched.
- Do not promise "guaranteed AdSense approval / ranking / indexing". The product provides checks and human review, not guarantees.
- Prefer SQLite over PostgreSQL unless a concrete reason emerges.
- No paid APIs, no microservices, no unnecessary dependencies.
- Editing SEO fields (seo_title / meta_description / slug) invalidates checks just like content edits — run Recheck afterwards. Any publish job (Phase 5) must require `approved`.
- Research sources are relevance-scored against the topic; off-topic results (e.g. a "Katy Perry" hit for a cats query) are filtered before persistence.

## Key decisions (product discovery, Step 1)

- v1 is **self-hosted, single-user** (no account system; one Blogger connection, one Ollama).
- Research uses a **strict ResearchProvider abstraction**. Initial free providers: Wikimedia/Wikipedia REST, Wikidata, DuckDuckGo Instant Answer. More providers can be added without touching the core pipeline.
- Images via **free CC/stock sources first** (Wikimedia Commons, optional Pexels/Unsplash free tiers). Local generation is a later, optional module.
- Default Ollama model is **1.5B** (`qwen2.5:1.5b`) — a 4B model exhausts RAM on this hardware and never finishes a draft (configurable per task). Verified installed models: `qwen2.5:1.5b` (default), `qwen3:4b`.

## Commands

- `python --version` / `node --version` / `ollama --version` — verify toolchain before any implementation phase.

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming -> invoke /office-hours
- Strategy/scope -> invoke /plan-ceo-review
- Architecture -> invoke /plan-eng-review
- Design system/plan review -> invoke /design-consultation or /plan-design-review
- Full review pipeline -> invoke /autoplan
- Bugs/errors -> invoke /investigate
- QA/testing site behavior -> invoke /qa or /qa-only
- Code review/diff check -> invoke /review
- Visual polish -> invoke /design-review
- Ship/deploy/PR -> invoke /ship or /land-and-deploy
- Save progress -> invoke /context-save
- Resume context -> invoke /context-restore
- Author a backlog-ready spec/issue -> invoke /spec
