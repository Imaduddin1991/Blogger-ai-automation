# blogger-ai-automation

A FREE, self-hosted AI Blogger automation platform. Turn a blog idea into a
researched, quality-checked, image-ready article and publish it to Blogger.

This is a **planning-only workspace**. No application code yet. See `docs/`
for the product discovery and architecture plan.

## What it does

1. User enters a blog idea
2. Research the topic using free resources
3. Create a research summary with sources
4. Generate a high-quality original article
5. Generate SEO metadata
6. Run quality / policy checks
7. Generate or attach suitable images
8. User reviews the article
9. Save draft
10. Schedule or publish
11. Publish to Blogger via the official Blogger API v3
12. Track publishing status

## Non-negotiables

- Free-first. No mandatory paid API, SaaS, OpenAI, Anthropic, or image API.
- AI runs locally through Ollama.
- Blogger is the first and primary publishing platform. WordPress is out of v1.
- Lightweight: runs on ~8 GB RAM, Intel Core i5 6th gen.
- Modular monolith. No microservices.

## Status

**Step 1 complete: workspace + product discovery.** Planning in `docs/`.
Implementation has not started.
