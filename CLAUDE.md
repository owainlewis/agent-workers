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

When you receive a task, match it to a skill and follow that skill file exactly. Do not improvise a workflow — the skill file is the process.

### Routing

| If the task contains... | Skill to follow |
|------------------------|----------------|
| A YouTube URL or video ID (e.g. `dQw4w9WgXcQ`, `youtube.com/watch?v=...`, `youtu.be/...`), or says "repurpose" | `.claude/skills/youtube-repurpose/SKILL.md` |
| "LinkedIn post" or "write a post" (no video involved) | `.claude/skills/linkedin-post/SKILL.md` |
| "Airtable" with no content creation | `.claude/skills/airtable/SKILL.md` |

### Steps for every task

1. Match the task to a skill using the table above
2. Read that skill file **first** before doing anything
3. Read `reference/brand.md`, `reference/pillars.md`, `reference/offers.md` for voice
4. Follow every step in the skill file in order — do not skip steps
5. Save output to `workspace/` and push to Airtable
