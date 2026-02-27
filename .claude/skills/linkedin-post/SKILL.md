---
name: linkedin-post
description: "Write a LinkedIn post. Two-phase process — hooks first, full post after approval. Use when the user wants to write, draft, or create a LinkedIn post, or repurpose content for LinkedIn."
---

# LinkedIn Post

Write a LinkedIn post for: $ARGUMENTS

## Autonomous Mode

When running without a human in the loop (e.g. dispatched by the agent worker):

1. **Pick the strongest hook yourself.** Generate 3 hook options, evaluate them against hooks.md patterns, and select the one with the highest scroll-stop potential. Do not wait for input.
2. **Skip all "wait for user" steps.** Move directly from hook selection to full post writing.
3. **Self-review inline.** Instead of spawning a separate reviewer agent, review your own draft against the criteria in the reviewer agent file (`.claude/agents/linkedin-reviewer.md`). Fix issues before outputting.
4. **Save the final draft** to `workspace/linkedin/` and push to Airtable if credentials are available.

If a human is present, follow the standard two-phase process below.

---

This is a two-phase process. Do NOT write a full post in Phase 1.

## Before starting, read:

- `reference/brand.md` — Voice and positioning
- `reference/pillars.md` — Content pillars and audiences
- `reference/offers.md` — Offers and CTAs
- `references/strategy.md` — Content buckets, cadence, idea sources, formats

---

## Phase 1: Hook Options

Read `references/hooks.md` for hook patterns.

The algorithm gives 3-5x more weight to the first 1-2 sentences. The hook classifies and distributes the post — make it directional, not generic.

Propose 3 hook options. Each one should:
- Take a different angle on the topic
- Be 1-2 lines, under 10 words per line
- Feel written for this specific topic, not filled into a formula
- Be clearly about one of the 3 content buckets

Present as a numbered list. **Wait for the user to pick one before continuing.**

---

## Phase 2: Full Post

After the user picks a hook, read:
- `references/examples.md` — match voice and structure
- `references/competitor-examples.md` — study the language simplicity

### Writing Principle

**Explain first, persuade second.**

If the post is about a tool, feature, or concept — explain what it is and how it works BEFORE telling the reader why it matters. A post that says "this will change everything" before the reader knows what "this" is will lose them.

### Flow (adapt as needed)

1. **Hook** — the approved hook from Phase 1
2. **Explanation** — what is this? How does it work? Concrete example. The reader should be able to explain it after reading this.
3. **Why it matters** — your take. What does this change?
4. **Practical details** — limitations, how to try it, what to watch out for
5. **Close** (1-2 lines) — land honestly
6. **CTA** — pick from the 3 standard CTAs below based on post type

### How to Write

- **Assume zero context.** Explain any tool or concept in one sentence the first time.
- **Short sentences. Common words.** If it sounds like writing, rewrite until it sounds like talking.
- **Reframe, don't just explain.** Make familiar things click in a new way.
- **One concrete number per post.** Engineering specifics, not claims.
- **Earn the list.** Set up the problem before giving the solution.
- **Don't force a numbered list.** Let the topic decide the structure.

---

## Standard CTAs

Every post must end with one of these three CTAs. Pick based on post type. Use the exact text — do not improvise.

### Join Newsletter:

---

Enjoy this? ♻️ Repost it to your network and follow Owain Lewis for more.

Want to master AI engineering?

Join thousands of professionals from top tech companies (Google, Amazon, Oracle) and level up your AI skills for free: https://newsletter.owainlewis.com.

### YouTube Subscribe:

---

PS - I make videos about building real software with AI agents. Subscribe on YouTube to see the full walkthroughs: https://youtube.com/@owainlewis

### Repost:

---

Repost this if it was useful. Follow Owain Lewis for more on AI engineering.

### Community Join:

---

PS: I run a community for engineers building with AI. Coding tools, production systems, agentic automations. Join here: https://www.skool.com/aiengineer/about

---

## Constraints

- Plain text only. No markdown, no asterisks, no backticks.
- No external links in the post body.
- Under 3000 characters.
- One idea per post.
- One thought per line. White space matters.
- Never use em dashes (—). Use a hyphen (-) or rewrite the sentence instead.

---

## Phase 3: Review

After writing the full post, run the `linkedin-reviewer` agent in a separate context window using the Task tool (subagent_type: "general-purpose" or the linkedin-reviewer agent).

Pass the reviewer:
1. The full draft text
2. The topic/source material it was based on

The reviewer checks against brand rules, structure, voice, and truth. It returns:
- Issues found (with specific lines quoted)
- Gaps needing author input (real examples, experiences)
- A revised draft

**Hard rule:** The reviewer NEVER fabricates stories, examples, or results. If the post needs a real example to land, it flags it as `[NEEDS REAL EXAMPLE]` for the author to fill in.

Present the user with:
- The revised post
- A summary of what changed
- Any `[NEEDS REAL EXAMPLE]` flags they need to fill in before publishing

---

## Output

Save to `workspace/linkedin/` with a descriptive filename.

Include the complete post (ready to copy-paste), hook pattern used, and character count.
