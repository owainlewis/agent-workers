# Background Agents

Demo repo: Todoist as control plane, Python worker as dispatcher, Claude Code as the agent.

## Available Skills

- **LinkedIn Post** — `.claude/skills/linkedin-post/SKILL.md` — Write LinkedIn posts (hooks-first process with autonomous mode)
- **Airtable** — `.claude/skills/airtable/SKILL.md` — CRUD operations on Airtable via CLI

## Airtable CLI

Run the Airtable CLI with repo-local paths:

```bash
uv run .claude/skills/airtable/scripts/airtable.py <command>
```

## Conventions

- **Autonomous mode**: When dispatched by the agent worker, don't wait for human input. Pick the best option and keep moving.
- **Drafts**: Save all content drafts to `workspace/linkedin/` with descriptive filenames.
- **Airtable push**: After creating content, push a record to the "Content" table in Airtable with fields: Title, Body, Status="draft", Platform.

## Reference Files

- `reference/brand.md` — Voice and positioning
- `reference/pillars.md` — Content pillars and audiences
- `reference/offers.md` — Offers and CTAs
