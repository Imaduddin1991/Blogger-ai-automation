# CLAUDE.md

Project instruction file for working in this repo with OpenCode/gstack.

## Project

- **Name:** blogger-ai-automation
- **Purpose:** Free, self-hosted AI Blogger automation platform (idea -> research -> article -> SEO -> checks -> images -> review -> publish to Blogger).
- **Constraints:** free-first, local AI via Ollama, Blogger-only for v1, lightweight (8 GB RAM, i5 6th gen), modular monolith.
- **Status:** planning only. No application code yet. See `docs/`.

## Ground rules

- **Never touch `/home/imad_uddin/ai-blog-automation`.** It is the old project and must remain untouched.
- Do not promise "guaranteed AdSense approval / ranking / indexing". The product provides checks and human review, not guarantees.
- Prefer SQLite over PostgreSQL unless a concrete reason emerges.
- No paid APIs, no microservices, no unnecessary dependencies.

## Key decisions (product discovery, Step 1)

- v1 is **self-hosted, single-user** (no account system; one Blogger connection, one Ollama).
- Research uses **structured free APIs only**: Wikimedia/Wikipedia REST, Wikidata, DuckDuckGo Instant Answer.
- Images via **free CC/stock sources first** (Wikimedia Commons, optional Pexels/Unsplash free tiers). Local generation is a later, optional module.
- Default Ollama model class is **3-4B** (configurable per task).

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
