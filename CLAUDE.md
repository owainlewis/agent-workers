# Background Agents

You are an autonomous agent dispatched by a worker script. You receive tasks as natural language — interpret what's needed and use the right skill.

## Rules

- Do not wait for human input. Pick the best option and keep moving.
- Save all content drafts to `workspace/linkedin/` with descriptive filenames.
- After creating content, push a record to Airtable if `.env` has credentials.

## Available Skills

- **LinkedIn Post** — `.claude/skills/linkedin-post/SKILL.md` — Write LinkedIn posts (hooks-first process with autonomous mode)
- **YouTube Repurpose** — `.claude/skills/youtube-repurpose/SKILL.md` — Repurpose a YouTube video into 3 LinkedIn posts + push to Airtable
- **Airtable** — `.claude/skills/airtable/SKILL.md` — CRUD operations on Airtable via CLI

## YouTube Tool

Download transcripts:

```bash
uv run tools/youtube.py get_transcript VIDEO_ID
```

## Airtable CLI

```bash
uv run .claude/skills/airtable/scripts/airtable.py <command>
```

## Reference Files

- `reference/brand.md` — Voice and positioning
- `reference/pillars.md` — Content pillars and audiences
- `reference/offers.md` — Offers and CTAs

## How to Handle Tasks

When you receive a task:

1. Read the task description and determine what's being asked
2. If it's about writing a LinkedIn post → follow `.claude/skills/linkedin-post/SKILL.md`
3. If it mentions a YouTube video or URL → follow `.claude/skills/youtube-repurpose/SKILL.md`
4. Always read the reference files for voice and positioning
5. Save output to `workspace/` and push to Airtable
