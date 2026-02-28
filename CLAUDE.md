# Background Agents

Autonomous agent dispatched by a worker script. Tasks arrive as natural language. Figure out what's needed, pick the right skill, and execute.

Do not wait for human input. Make decisions and keep moving.

## Skills

| Skill | File | Description |
|-------|------|-------------|
| LinkedIn Post | `.claude/skills/linkedin-post/SKILL.md` | Write LinkedIn posts |
| YouTube Repurpose | `.claude/skills/youtube-repurpose/SKILL.md` | Repurpose a YouTube video into LinkedIn posts |
| Content Ideation | `.claude/skills/content-ideation/SKILL.md` | Generate video ideas from real YouTube data |
| Airtable | `.claude/skills/airtable/SKILL.md` | CRUD operations on Airtable |

Read the skill file before doing anything. The skill is the process.

## Tools

- `uv run .claude/skills/youtube-repurpose/scripts/youtube.py` — YouTube search, channel scanning, transcripts
- `uv run .claude/skills/airtable/scripts/airtable.py` — Airtable CLI

## Reference

- `reference/brand.md` — Voice and positioning
- `reference/pillars.md` — Content pillars
- `reference/offers.md` — Offers and CTAs
