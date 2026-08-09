# Agent OS loft — compose hub + host distribution

Product stance for saga [#121](https://github.com/lbliii/pidge/issues/121).

## Stance

- Pidge is a **SaaS loft on top of the agent OS** — not an agent host.
- Compose stays **agent-inbound** (no free-type box).
- MCP is the contract; humans seal (Desk / Confirm / Autopilot ladder unchanged).

## Compose status modes

| Mode | When | Surface |
|------|------|---------|
| setup | No tokens | Mint CTA + harness wall |
| quiet | Tokens never used | Labels + install nudge |
| active | `last_used_at` set | Label · preset · seen harness |

## Harness attribution

Captured on authenticated `/mcp` traffic from:

1. MCP `initialize` `clientInfo.name` / `version`
2. `User-Agent`
3. Optional `X-Pidge-Harness` header
4. Optional mint-time **intended harness** until traffic confirms

Normalized slugs: `cursor`, `claude_code`, `claude_web`, `codex`, `chatgpt`, `other`.

## Host matrix

Documented on `/connect` and Agents mint ritual:

- Cursor — `mcp.json` / Settings → MCP
- Claude Code — HTTP MCP + [plugins/claude-pidge](../plugins/claude-pidge/)
- Claude.ai — custom connector URL
- Codex — HTTP `config.toml`
- ChatGPT — Developer Mode / Apps (OAuth later for stores)

## Experience system

See [experience-system.md](./experience-system.md) — Workflow compose empty = status hub;
Discovery = multi-host install matrix.
