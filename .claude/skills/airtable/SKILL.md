---
name: airtable
description: "Manage Airtable bases, tables, fields, and records via CLI. Use this skill whenever the user mentions Airtable, wants to interact with Airtable data, manage content pipelines, track ideas or projects in Airtable, or perform any CRUD operations on table data. Also use when the user references record IDs (rec...), base IDs (app...), or mentions syncing data to/from a spreadsheet-like database."
---

# Airtable CLI Skill

A script-backed skill for full CRUD on Airtable bases, tables, fields, and records. Wraps both the Meta API (schema management) and Data API (records).

## Setup

Create a `.env` file in the working directory with:

```dotenv
AIRTABLE_API_KEY=patXXXXXXXXXXXXXX
AIRTABLE_BASE_ID=appXXXXXXXXXXXXXX
```

- `AIRTABLE_API_KEY` (Personal Access Token) is required.
- `AIRTABLE_BASE_ID` is optional. If not set, pass `--base BASE_ID` on commands that need it, or run `base list` first to discover available bases.

## CLI Reference

All commands output JSON to stdout. Errors go to stderr as JSON with exit code 1.

Run commands with:

```bash
uv run .claude/skills/airtable/scripts/airtable.py <command>
```

Global option: `--base BASE_ID` overrides the base ID for a single command.

### base

| Command | Description |
|---------|-------------|
| `base list` | List all accessible bases (no base ID required) |

```bash
uv run .claude/skills/airtable/scripts/airtable.py base list
```

### table

| Command | Description |
|---------|-------------|
| `table list` | List tables with full field schemas |
| `table create NAME --schema JSON` | Create a new table |

```bash
uv run .claude/skills/airtable/scripts/airtable.py table list --base appXXX
uv run .claude/skills/airtable/scripts/airtable.py table create "Ideas" --schema '[{"name":"Name","type":"singleLineText"}]' --base appXXX
```

### field

| Command | Description |
|---------|-------------|
| `field add TABLE --name NAME --type TYPE [--options JSON]` | Add a field to a table |

```bash
uv run .claude/skills/airtable/scripts/airtable.py field add "Ideas" --name Score --type number --base appXXX
```

### record

| Command | Description |
|---------|-------------|
| `record list TABLE [--formula F] [--view V] [--max N] [--sort FIELD:DIR]` | List records with optional filter/sort |
| `record get TABLE RECORD_ID` | Get a single record by ID |
| `record create TABLE FIELDS_JSON` | Create one or more records (auto-batches in groups of 10) |
| `record update TABLE RECORD_ID FIELDS_JSON` | Update a record by ID |
| `record delete TABLE RECORD_ID [RECORD_ID...]` | Delete one or more records |
| `record find TABLE FIELD_NAME VALUE` | Find a record by field value |

```bash
# List with filter
uv run .claude/skills/airtable/scripts/airtable.py record list "Ideas" --formula "{Status} = 'approved'" --sort "Created:desc" --base appXXX

# Get single record
uv run .claude/skills/airtable/scripts/airtable.py record get "Ideas" recXXX --base appXXX

# Create one record
uv run .claude/skills/airtable/scripts/airtable.py record create "Ideas" '{"Title":"Test"}' --base appXXX

# Batch create (array input, auto-chunked)
uv run .claude/skills/airtable/scripts/airtable.py record create "Ideas" '[{"Title":"A"},{"Title":"B"}]' --base appXXX

# Update
uv run .claude/skills/airtable/scripts/airtable.py record update "Ideas" recXXX '{"Status":"approved"}' --base appXXX

# Delete
uv run .claude/skills/airtable/scripts/airtable.py record delete "Ideas" recXXX --base appXXX

# Find by field value
uv run .claude/skills/airtable/scripts/airtable.py record find "Ideas" Title "Test" --base appXXX
```

## Common Patterns

### Discover bases first

If `AIRTABLE_BASE_ID` is not set, start by listing bases to find the right one:

```bash
uv run .claude/skills/airtable/scripts/airtable.py base list
```

Then use `--base` on subsequent commands, or ask the user to set `AIRTABLE_BASE_ID` in `.env`.

### Discover table schema

Before creating or updating records, list the tables to understand field names and types:

```bash
uv run .claude/skills/airtable/scripts/airtable.py table list --base appXXX
```

### Find then update

Look up a record by a known field value, get its ID, then update it:

```bash
uv run .claude/skills/airtable/scripts/airtable.py record find "Ideas" Title "Test" --base appXXX
# Use the returned record ID to update
uv run .claude/skills/airtable/scripts/airtable.py record update "Ideas" recXXX '{"Status":"approved"}' --base appXXX
```

### Filter with formulas

Airtable formulas work in the `--formula` flag. Common patterns:

```bash
# Exact match
--formula "{Status} = 'approved'"

# Not empty
--formula "NOT({Title} = '')"

# Multiple conditions
--formula "AND({Status} = 'approved', {Score} > 5)"
```

## Error Handling

Errors are JSON on stderr:

```json
{"error": "Airtable API 422: INVALID_REQUEST_UNKNOWN - Field 'title' does not exist"}
```

- If `record find` returns no match: `{"found": false, "record": null}`
- If no base ID is available, the CLI tells you to run `base list` and pass `--base`
- On rate limit (429), the CLI automatically retries after the `Retry-After` header value

## Output Format

All commands return JSON. Record responses look like:

```json
{
  "table": "Ideas",
  "total_records": 1,
  "records": [
    {
      "id": "recXXXXXXXXXXXXXX",
      "fields": {"Title": "My Idea", "Status": "inbox"},
      "created_time": "2026-02-25T10:00:00.000Z"
    }
  ]
}
```
