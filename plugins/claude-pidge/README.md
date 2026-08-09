# Claude plugin: Pidge mail secretary

Bundles skills that teach Claude how to use a loft’s remote MCP tools.
Point Claude Code / Cowork at this plugin and add the loft MCP URL as a
custom connector (see `/connect` on your loft).

## Install

1. Mint a **Desk** token under `/settings/agents`.
2. Add the loft MCP endpoint with `Authorization: Bearer <token>`.
3. Install this plugin (local path or directory listing when published).
4. Ask Claude to draft mail with Pidge.

## Skills

- `pidge-mail` — draft → enrich → propose seal ritual

Pidge does not own the agent loop; this plugin only teaches vocabulary.
