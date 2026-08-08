# Pidge

**Your agent’s secretary — structured mail, calendar, and a wall of notes.**

You don’t type into Pidge. Your agent writes via MCP. You review, seal, and act.

## Status

Runnable Chirp app (no ChirpUI). Design mocks remain in [`design/`](./design/). Product plan lives on GitHub ([saga #1](https://github.com/lbliii/pidge/issues/1)); scratch plans use [`.plan/`](./.plan/) → issue → discard.

## Stack

- Chirp hypermedia + HTMX
- Postgres (Railway) / MemoryStore for tests
- Custom oat/leather CSS from design mocks
- Durable human sessions + scoped agent bearer tokens

## Local development

```bash
uv sync --group dev
uv run pidge serve
# open http://127.0.0.1:8000/setup
# bootstrap token (dev): development-bootstrap-token
```

Optional Postgres:

```bash
export DATABASE_URL=postgresql://...
export PIDGE_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(48))')
export PIDGE_BOOTSTRAP_TOKEN=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
uv run pidge migrate
uv run pidge serve --no-debug
```

## Agent path

1. Log in → **Agents** → mint a token (scopes: `pidge:draft`, `pidge:enrich`, …)
2. Copy the Cursor snippet from that page into `~/.cursor/mcp.json` (URL + `Authorization: Bearer …`)
3. Enable the `pidge` MCP server, then `draft_pidge` → `enrich_pidge` → human **Seal** in the UI (agents cannot seal)

### MCP curl recipe

Mint a bearer token under **Agents** settings, then (agents cannot seal — humans seal in the UI):

```bash
BASE=http://127.0.0.1:8000   # or https://web-production-04a7d.up.railway.app
TOKEN=pidge_at_…

curl -sS "$BASE/mcp" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

curl -sS "$BASE/mcp" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{
        "name":"draft_pidge",
        "arguments":{
          "intent":"Tell Lucy we are meeting tonight at 7 at Nowadays",
          "recipients":["Lucy"],
          "summary":"Tonight at Nowadays"
        }}}'

# Replace pidge_id with the id from draft_pidge
curl -sS "$BASE/mcp" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{
        "name":"enrich_pidge",
        "arguments":{
          "pidge_id":1,
          "who":"Lucy",
          "when":"tonight · 7:00 PM",
          "where":"Nowadays, Brooklyn",
          "extras":{"menu":"kitchen + wine"}
        }}}'
```

## Dogfood — Tonight at Nowadays

One-command story: register owner + Lucy → mint agent → MCP draft/enrich → human seal → Lucy RSVP → hold + pin.

```bash
make dogfood
# or: uv run python scripts/dogfood_nowadays.py
```

Runs against in-process **MemoryStore** (no Postgres). Optional live loft:

```bash
uv run python scripts/dogfood_nowadays.py \
  --base-url https://web-production-04a7d.up.railway.app \
  --bootstrap-token "$PIDGE_BOOTSTRAP_TOKEN" \
  --owner-password '…' --lucy-password '…'
```

Second loft member: the script registers **Lucy** via `/register` (or logs her in if she already exists).

## Addressing

- **Same loft:** directory of members; message anyone on this deployment
- **Out of loft:** must add them to **Contacts** first

## Railway

One app service + Postgres:

| Variable | Notes |
|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
| `PIDGE_ENV` | `production` |
| `PIDGE_SECRET_KEY` | `${{secret(64)}}` |
| `PIDGE_BOOTSTRAP_TOKEN` | `${{secret(32)}}` |
| `RAILPACK_PYTHON_VERSION` | `3.14` |

Healthcheck: `/ready`. Start: `pidge serve --host 0.0.0.0 --port $PORT --no-debug`.

## Tests

```bash
uv run pytest
uv run pidge check
make dogfood
```

## License

TBD.
