---
name: youtube-repurpose
description: "Repurpose a YouTube video into LinkedIn posts. Downloads the transcript, extracts key insights, writes 3 LinkedIn posts, and pushes them to Airtable."
---

# YouTube Repurpose

Repurpose a YouTube video into LinkedIn posts: $ARGUMENTS

## Autonomous Mode

This skill runs without human input. Do not wait for approval at any step. Pick the best options and keep moving.

---

## Step 1: Get the Transcript

Use the YouTube tool to download the transcript.

The input can be a video URL or a video ID. Extract the video ID if given a URL (the part after `v=` or after `youtu.be/`).

```bash
uv run .claude/skills/youtube-repurpose/scripts/youtube.py get_transcript VIDEO_ID
```

Save the transcript to `workspace/transcripts/VIDEO_ID.txt`.

If the transcript fails, check if the video ID is correct. If it still fails, report the error and stop.

---

## Step 2: Extract Key Insights

Read the transcript and identify 3 distinct insights, angles, or takeaways that would each work as a standalone LinkedIn post.

Pick angles that:
- Are self-contained (the reader doesn't need to watch the video)
- Cover different parts of the video (don't cluster around one section)
- Match the content buckets in `references/strategy.md` (Practical AI Skills, Become Irreplaceable, Deep Technical)

For each angle, write a one-line summary before drafting.

---

## Step 3: Write 3 LinkedIn Posts

For each of the 3 angles, follow the LinkedIn post skill:

1. Read `.claude/skills/linkedin-post/SKILL.md` and follow the Autonomous Mode instructions
2. Read `reference/brand.md`, `reference/pillars.md`, `reference/offers.md` for voice
3. Read `.claude/skills/linkedin-post/references/hooks.md` for hook patterns
4. Read `.claude/skills/linkedin-post/references/examples.md` for voice and structure

For each post:
- Generate 3 hooks, pick the strongest
- Write the full post following the skill's flow and constraints
- Self-review against the reviewer criteria in `.claude/agents/linkedin-reviewer.md`
- Use a different CTA for each post (Newsletter, YouTube Subscribe, Community Join)

Save each post to `workspace/linkedin/` with a descriptive filename prefixed with the video ID.

---

## Step 4: Push to Airtable

For each of the 3 posts, create a record in Airtable:

```bash
uv run .claude/skills/airtable/scripts/airtable.py record create "Content" '{"Title": "POST_TITLE", "Body": "POST_BODY", "Status": "draft", "Platform": "LinkedIn", "Source": "YouTube: VIDEO_ID"}'
```

If Airtable credentials are not in `.env`, skip this step and note it in the output.

---

## Output

Save a summary file to `workspace/linkedin/VIDEO_ID-repurpose-summary.md` containing:

- Video ID and title (if available)
- The 3 angles chosen
- Filenames of the 3 posts
- Whether Airtable push succeeded

---

## Constraints

- All posts must follow `.claude/skills/linkedin-post/SKILL.md` constraints (plain text, under 3000 chars, no markdown)
- Each post must be standalone — no "as I discussed in my latest video" references
- Each post must take a different angle on the source material
- Do not fabricate examples or statistics not in the transcript
