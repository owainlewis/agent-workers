# Airtable API Reference

## Meta API (Schema Operations)

Base URL: `https://api.airtable.com/v0/meta`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/bases` | GET | List all accessible bases |
| `/bases/{baseId}/tables` | GET | List tables with full field schemas |
| `/bases/{baseId}/tables` | POST | Create a new table |
| `/bases/{baseId}/tables/{tableId}/fields` | POST | Add a field to a table |

## Data API (Record Operations)

Base URL: `https://api.airtable.com/v0/{baseId}/{tableName}`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | List records (supports `filterByFormula`, `sort`, `maxRecords`, pagination via `offset`) |
| `/{recordId}` | GET | Get single record |
| `/` | POST | Create records (max 10 per request, `typecast: true`) |
| `/` | PATCH | Update records (max 10 per request, `typecast: true`) |
| `/` | DELETE | Delete records (max 10 per request, via `records[]` query params) |

## Authentication

Bearer token in `Authorization` header. Token is a Personal Access Token (PAT) starting with `pat`.

Required scopes:
- `data.records:read`
- `data.records:write`
- `schema.bases:read`
- `schema.bases:write`

## Rate Limits

5 requests per second. On 429, retry after `Retry-After` header value.

## Field Types

Common field types for `table create` and `field add`:

| Type | Description |
|------|-------------|
| `singleLineText` | Short text |
| `multilineText` | Long text |
| `number` | Numeric value |
| `checkbox` | Boolean |
| `singleSelect` | Single choice (options auto-created with typecast) |
| `multipleSelects` | Multiple choices |
| `date` | Date value |
| `email` | Email address |
| `url` | URL |
| `richText` | Rich text with formatting |

## Formula Reference

Common formulas for `--formula` flag:

```
{Field} = 'value'              # Exact match
{Field} != 'value'             # Not equal
{Field} > 5                    # Numeric comparison
NOT({Field} = '')              # Not empty
AND({A} = 'x', {B} > 5)       # Multiple conditions
OR({A} = 'x', {A} = 'y')      # Either condition
FIND('sub', {Field})           # Contains substring
```

## Documentation

- https://airtable.com/developers/web/api/introduction
- https://airtable.com/create/tokens (create Personal Access Tokens)
