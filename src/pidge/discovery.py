"""Public discovery documents for agents probing a Pidge loft.

Discovery is intentional: endpoints and docs are public; credentials are not.
A human still mints a scoped bearer under /settings/agents before MCP works.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from pidge import __version__

# Align with streamable-HTTP MCP clients common in 2025-2026.
MCP_PROTOCOL_VERSION = "2025-06-18"

# Static catalog for pre-connection probes (must stay in sync with @app.tool names).
MCP_TOOLS: tuple[dict[str, str], ...] = (
    {
        "name": "draft_pidge",
        "description": "Create a draft Pidge from intent and recipients.",
        "scopes": "pidge:draft",
    },
    {
        "name": "enrich_pidge",
        "description": "Fill structured slots on a draft Pidge.",
        "scopes": "pidge:enrich",
    },
    {
        "name": "list_drafts",
        "description": "List the owner's draft Pidges.",
        "scopes": "pidge:draft",
    },
    {
        "name": "discard_pidge",
        "description": "Discard one of the owner's draft Pidges.",
        "scopes": "pidge:draft",
    },
    {
        "name": "get_pidge",
        "description": "Fetch one Pidge the owner can see.",
        "scopes": "pidge:draft",
    },
    {
        "name": "list_directory",
        "description": "List other people in this loft.",
        "scopes": "pidge:draft",
    },
    {
        "name": "list_contacts",
        "description": "List the owner's address book.",
        "scopes": "pidge:draft",
    },
    {
        "name": "add_contact",
        "description": "Add an external contact to the address book.",
        "scopes": "pidge:draft",
    },
    {
        "name": "propose_hold",
        "description": "Propose a calendar hold for a Pidge.",
        "scopes": "pidge:calendar.propose",
    },
    {
        "name": "pin_note",
        "description": "Pin a sealed Pidge to the owner's wall.",
        "scopes": "pidge:notes.pin",
    },
    {
        "name": "propose_seal",
        "description": (
            "Propose sealing a ready draft; returns a one-time seal_url for the human."
        ),
        "scopes": "pidge:seal.propose",
    },
    {
        "name": "seal_pidge",
        "description": (
            "Seal a ready draft over MCP (Autopilot only). Prefer propose_seal."
        ),
        "scopes": "pidge:seal",
    },
)

DISCOVERY_CACHE_CONTROL = "public, max-age=3600"
DISCOVERY_CORS = "*"
GITHUB_REPO = "https://github.com/lbliii/pidge"
SECURITY_CONTACT = f"{GITHUB_REPO}/security/advisories/new"


def resolve_public_origin(public_origin: str | None, request_url: str | Any) -> str:
    """Canonical loft origin for discovery URLs."""
    if public_origin:
        return public_origin.rstrip("/")
    if isinstance(request_url, str):
        parsed = urlparse(request_url)
        scheme = parsed.scheme or "http"
        netloc = parsed.netloc or "127.0.0.1:8000"
        return f"{scheme}://{netloc}"
    scheme = getattr(request_url, "scheme", None) or "http"
    netloc = getattr(request_url, "netloc", None) or "127.0.0.1:8000"
    return f"{scheme}://{netloc}"


def mcp_endpoint(origin: str) -> str:
    return f"{origin.rstrip('/')}/mcp"


def server_card(origin: str, *, loft_name: str = "Pidge") -> dict[str, Any]:
    """SEP-1649-shaped MCP server card (draft; pre-connection catalog)."""
    endpoint = mcp_endpoint(origin)
    return {
        "$schema": "https://modelcontextprotocol.io/schemas/server-card.json",
        "version": "1.0",
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "serverInfo": {
            "name": "pidge",
            "title": f"{loft_name} — Pidge MCP",
            "version": __version__,
        },
        "description": (
            "Agent secretary desk: draft and enrich structured mail (Pidges), "
            "propose calendar holds, and pin wall notes. Humans seal and act; "
            "agents never share the browser session. Bearer token required — "
            "mint under /settings/agents (Desk preset by default)."
        ),
        "homepage": f"{origin}/connect",
        "documentation": f"{origin}/llms.txt",
        "transport": {
            "type": "streamable-http",
            "endpoint": endpoint,
        },
        "capabilities": {
            "tools": {"listChanged": False},
            "resources": {"subscribe": False, "listChanged": False},
            "prompts": {"listChanged": False},
        },
        "authentication": {
            "required": True,
            "schemes": ["bearer"],
            "instructions": (
                "Log in as a loft member, open /settings/agents, mint a Desk "
                "(or narrower) token, then send Authorization: Bearer <secret> "
                "on every MCP request. Never paste Autopilot tokens into chats."
            ),
        },
        "tools": [
            {"name": t["name"], "description": t["description"]} for t in MCP_TOOLS
        ],
    }


def mcp_manifest(origin: str) -> dict[str, Any]:
    """SEP-1960-shaped MCP discovery manifest (draft; connect/auth focus)."""
    endpoint = mcp_endpoint(origin)
    return {
        "mcp_version": "1.0",
        "server_version": __version__,
        "endpoints": {
            "streamable_http": endpoint,
        },
        "capabilities": {
            "tools": True,
            "resources": False,
            "prompts": False,
            "sampling": False,
            "roots": False,
        },
        "authentication": {
            "required": True,
            "methods": ["api_key"],
            "api_key": {
                "header": "Authorization",
                "scheme": "Bearer",
                "prefix": "pidge_at_",
                "mint_url": f"{origin}/settings/agents",
                "connect_url": f"{origin}/connect",
            },
        },
        "security": {
            "tls_required": origin.startswith("https://"),
            "security_contact": SECURITY_CONTACT,
        },
        "registration": {"dynamic": False},
        "documentation": f"{origin}/llms.txt",
        "homepage": f"{origin}/connect",
    }


def llms_txt(origin: str, *, loft_name: str = "Pidge") -> str:
    """Compact llms.txt for crawlers and agents (llmstxt.org-style)."""
    endpoint = mcp_endpoint(origin)
    lines = [
        f"# {loft_name} (Pidge)",
        "",
        "> Agent secretary desk — structured mail, calendar holds, and wall notes.",
        "> Agents draft/enrich via MCP; humans seal and act in the browser.",
        "> One deployment = one loft. Discovery is public; credentials are not.",
        "",
        "## Connect",
        "",
        f"- [Connect guide]({origin}/connect): human mints a bearer; host-specific install matrix",
        f"- [MCP endpoint]({endpoint}): streamable HTTP; Authorization: Bearer pidge_at_…",
        f"- [Agents settings]({origin}/settings/agents): mint Desk / Draft / Confirm / Autopilot tokens",
        f"- [Health]({origin}/livez): liveness probe",
        f"- Compatible hosts: Cursor, Claude Code, Claude.ai, Codex, ChatGPT Apps",
        "",
        "## Discovery",
        "",
        f"- [llms.txt]({origin}/llms.txt): this file",
        f"- [llms-full.txt]({origin}/llms-full.txt): tools, scopes, curl recipe",
        f"- [MCP server card]({origin}/.well-known/mcp/server-card.json): SEP-1649-shaped catalog",
        f"- [MCP manifest]({origin}/.well-known/mcp): SEP-1960-shaped connect/auth",
        "",
        "## Trust ladder",
        "",
        "- Desk (default): draft, enrich, propose holds, pin notes — human seals in UI",
        "- Confirm: Desk + propose_seal (one-shot human challenge URL)",
        "- Autopilot: Confirm + seal_pidge over MCP — never paste into shared chats",
        "",
        "## Optional",
        "",
        f"- [Source]({GITHUB_REPO})",
        f"- [Login]({origin}/login)",
        "",
    ]
    return "\n".join(lines)


def llms_full_txt(origin: str, *, loft_name: str = "Pidge") -> str:
    """Expanded agent onboarding text."""
    endpoint = mcp_endpoint(origin)
    tool_lines = [
        f"- `{t['name']}` ({t['scopes']}): {t['description']}" for t in MCP_TOOLS
    ]
    body = [
        llms_txt(origin, loft_name=loft_name).rstrip(),
        "",
        "## MCP tools",
        "",
        *tool_lines,
        "",
        "## Cursor snippet",
        "",
        "After minting under /settings/agents, paste (also Claude Code / Codex / ChatGPT on /connect):",
        "",
        "```json",
        "{",
        '  "mcpServers": {',
        '    "pidge": {',
        f'      "url": "{endpoint}",',
        '      "headers": {',
        '        "Authorization": "Bearer pidge_at_…"',
        "      }",
        "    }",
        "  }",
        "}",
        "```",
        "",
        "## Claude plugin",
        "",
        f"- Skills pack: {GITHUB_REPO}/tree/main/plugins/claude-pidge",
        "",
        "## Smoke test (after mint)",
        "",
        "```bash",
        f'BASE="{origin}"',
        'TOKEN="pidge_at_…"  # from /settings/agents — Desk preferred',
        "",
        'curl -sS "$BASE/mcp" -H "Authorization: Bearer $TOKEN" \\',
        "  -H 'Content-Type: application/json' \\",
        "  -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\",\"params\":{}}'",
        "",
        'curl -sS "$BASE/mcp" -H "Authorization: Bearer $TOKEN" \\',
        "  -H 'Content-Type: application/json' \\",
        "  -d '{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{",
        '        "name":"list_directory",',
        '        "arguments":{}',
        "      }}'",
        "```",
        "",
        "## Do not",
        "",
        "- Expect anonymous MCP — bearer required",
        "- Call seal_pidge without an Autopilot token the human knowingly minted",
        "- Paste Autopilot secrets into shared chats or tickets",
        "",
    ]
    return "\n".join(body)


def robots_txt(origin: str) -> str:
    return "\n".join(
        [
            "User-agent: *",
            "Allow: /connect",
            "Allow: /llms.txt",
            "Allow: /llms-full.txt",
            "Allow: /.well-known/",
            "Allow: /login",
            "Allow: /livez",
            "Allow: /ready",
            "Allow: /static/",
            "Disallow: /inbox",
            "Disallow: /sent",
            "Disallow: /compose",
            "Disallow: /p/",
            "Disallow: /people",
            "Disallow: /settings/",
            "Disallow: /calendar",
            "Disallow: /wall",
            "Disallow: /mcp",
            f"Sitemap: {origin}/llms.txt",
            "",
        ]
    )


def security_txt(origin: str) -> str:
    return "\n".join(
        [
            f"Contact: {SECURITY_CONTACT}",
            f"Canonical: {origin}/.well-known/security.txt",
            "Preferred-Languages: en",
            f"Policy: {GITHUB_REPO}/security",
            "",
        ]
    )


def dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=False) + "\n"
