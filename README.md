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

Tokens default to the **Desk** preset (draft, enrich, calendar propose, notes pin; 90-day TTL). Narrower **Draft**, **Confirm** (`propose_seal` + human one-shot challenge), and opt-in **Autopilot** (`pidge:seal`; 30-day TTL) live under **Agents**. MCP seal is scope-gated: only Autopilot tokens with `pidge:seal` may call `seal_pidge`. Trust ladder: [saga #26](https://github.com/lbliii/pidge/issues/26) / [epic #29](https://github.com/lbliii/pidge/issues/29).

**Warning:** Never paste Autopilot tokens into shared chats. They can seal Pidges over MCP without a browser challenge.

**Discovery (public):** [https://pidge.lol/connect](https://pidge.lol/connect) · [/llms.txt](https://pidge.lol/llms.txt) · [MCP server card](https://pidge.lol/.well-known/mcp/server-card.json) · [MCP manifest](https://pidge.lol/.well-known/mcp). Credentials still require a human-minted bearer.

1. Log in → **Agents** → mint a token (Desk by default; Autopilot requires an acknowledge checkbox)
2. Copy a host snippet (Cursor, Claude Code, Codex, …) from Agents or [/connect](https://pidge.lol/connect) — URL + `Authorization: Bearer …`
3. Enable the `pidge` MCP server in your harness, then `draft_pidge` → `enrich_pidge` → human **Seal** in the UI (or Autopilot `seal_pidge` when intentionally opted in). Discard unwanted drafts with `discard_pidge` (scope `pidge:draft`) or the Discard button on compose/desk — discarded drafts become `revoked` and leave draft lists. Sealed Pidges are immutable: authors revoke or supersede from the thread UI only (agents cannot); revoke hides from inbox/sent without rewriting `content_hash`, and supersede opens a new draft linked via `supersedes_id`.
4. Open **Compose** to see which agents are quiet vs active (and which harness last used each token).
### MCP curl recipe

Mint a bearer token under **Agents** settings (Desk by default). Desk/Confirm cannot seal; Autopilot with `pidge:seal` can:

```bash
BASE=http://127.0.0.1:8000   # or https://pidge.lol
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
  --base-url https://pidge.lol \
  --bootstrap-token "$PIDGE_BOOTSTRAP_TOKEN" \
  --owner-password '…' --lucy-password '…'
```

Second loft member: the script registers **Lucy** via `/register` (or logs her in if she already exists).

## Addressing

- **Same loft:** People → In the loft; message anyone on this deployment
- **Beyond the loft:** People → Beyond the loft; add the handle before agents can address them

## Railway

Production loft: **https://pidge.lol** (custom domain; Railway service domain still works as fallback).

One app service + Postgres:

| Variable | Notes |
|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
| `PIDGE_ENV` | `production` |
| `PIDGE_PUBLIC_ORIGIN` | `https://pidge.lol` (seal challenge + MCP snippet URLs) |
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
