# Content Ideation Skill

Generate scored video ideas backed by real YouTube data. Scans competitor channels, searches trending topics, and produces ideas with titles, hooks, and scores — then pushes them to Airtable.

## Tools

```bash
# Search YouTube for videos by keyword
uv run .claude/skills/youtube-repurpose/scripts/youtube.py search_videos "QUERY" --max 20 --order view_count --json

# Scan a channel's recent videos with outlier detection
uv run .claude/skills/youtube-repurpose/scripts/youtube.py get_channel_videos @HANDLE --days 14 --json

# Airtable CLI
uv run .claude/skills/airtable/scripts/airtable.py <command>
```

## Workflow

### Step 1: Load Context

Read these files first:

- `reference/pillars.md` — Content pillars and audiences
- `reference/brand.md` — Voice and positioning
- `.claude/skills/content-ideation/references/competitors.yaml` — Channels and search queries to scan

### Step 2: Scan Competitors

For each channel in `competitors.yaml`, run:

```bash
uv run .claude/skills/youtube-repurpose/scripts/youtube.py get_channel_videos @HANDLE --days 14 --json
```

Collect all videos. Flag outliers where `outlier_score > 2.0`. These are videos performing significantly above the channel's average — they reveal what topics are resonating right now.

Run channels in batches of 3-4 to stay within API limits.

### Step 3: Run Search Queries

For each query in `pillar_searches` from `competitors.yaml`:

```bash
uv run .claude/skills/youtube-repurpose/scripts/youtube.py search_videos "QUERY" --days 30 --order view_count --max 10 --json
```

Collect the top performing videos from each search.

### Step 4: Generate Ideas

From the scan data, generate the requested number of ideas (default 10).

For each idea:
- **Title** — Compelling YouTube title, under 60 chars
- **Pillar** — AI Coding, AI Engineering, AI for Business, Business, or AI Tools
- **Format** — tutorial, build, opinion, comparison, or review
- **Hook** — 2-3 sentence hook (what makes the viewer click and stay)
- **Source** — What inspired this: outlier video title + URL, or search trend
- **Score** — Weighted score 0-100 (see scoring below)

**Idea generation approach:**
1. Start with the strongest outliers — what topic angles are working?
2. Look for gaps — topics that appear in searches but aren't well covered
3. Cross-reference with pillars — does this fit the channel?
4. Apply the unique angle — 20 years engineering experience, production depth, honest delivery
5. Aim for distribution: ~30% AI for Business, ~25% AI Coding, ~20% AI Engineering, ~15% Business, ~10% AI Tools

### Step 5: Score Each Idea (0-100)

| Factor | Weight | Scoring |
|--------|--------|---------|
| Outlier Performance | 30% | Outlier score * 20, capped at 100. If from search trend, use 50. |
| Search Signal | 20% | Queries matched: 0 = 20, 1-2 = 50, 3+ = 80, cross-channel = 100 |
| Brand Pillar Fit | 25% | Direct match = 100, adjacent = 60, tangential = 30 |
| Content Gap | 15% | No competitors covered it = 100, 1-2 = 60, 3+ = 20 |
| Feasibility | 10% | Can demo + have expertise = 100, needs setup = 70, theory only = 40 |

Final score = weighted sum, rounded to nearest integer.

### Step 6: Push to Airtable

List tables first to find the right one:

```bash
uv run .claude/skills/airtable/scripts/airtable.py table list
```

Look for a table with "YouTube", "Video", or "Ideas" in the name. If none exists, create one:

```bash
uv run .claude/skills/airtable/scripts/airtable.py table create "YouTube Ideas" --schema '[
  {"name": "Title", "type": "singleLineText"},
  {"name": "Pillar", "type": "singleLineText"},
  {"name": "Format", "type": "singleLineText"},
  {"name": "Score", "type": "number"},
  {"name": "Hook", "type": "multilineText"},
  {"name": "Notes", "type": "multilineText"},
  {"name": "Status", "type": "singleLineText"}
]'
```

Before creating records, check for duplicates:

```bash
uv run .claude/skills/airtable/scripts/airtable.py record list "YouTube Ideas" --json
```

Skip any idea whose title matches an existing record.

Create records for each non-duplicate idea:

```bash
uv run .claude/skills/airtable/scripts/airtable.py record create "YouTube Ideas" '{
  "Title": "...",
  "Pillar": "...",
  "Format": "...",
  "Score": ...,
  "Hook": "...",
  "Notes": "Source: outlier | Inspired by: [title](url)",
  "Status": "Idea"
}'
```

### Step 7: Save Summary

Save a summary to `workspace/youtube-ideas.md` with:
- Scan stats (channels scanned, videos analyzed, outliers found)
- Top 3 outliers with title, channel, views, score
- All ideas ranked by score with title, pillar, format, hook preview
- Airtable results (records created, duplicates skipped)
