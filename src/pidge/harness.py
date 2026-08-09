"""Compatible agent harnesses and MCP client attribution.

Pidge does not own the agent loop. This module catalogs hosts that speak MCP
to a loft, maps clientInfo / User-Agent hints onto stable slugs, and renders
host-specific install snippets for compose / connect / Agents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Normalized harness slugs persisted on agent_tokens.last_harness
HARNESS_CURSOR = "cursor"
HARNESS_CLAUDE_CODE = "claude_code"
HARNESS_CLAUDE_WEB = "claude_web"
HARNESS_CODEX = "codex"
HARNESS_CHATGPT = "chatgpt"
HARNESS_OTHER = "other"

KNOWN_HARNESS_SLUGS = frozenset(
    {
        HARNESS_CURSOR,
        HARNESS_CLAUDE_CODE,
        HARNESS_CLAUDE_WEB,
        HARNESS_CODEX,
        HARNESS_CHATGPT,
        HARNESS_OTHER,
    }
)


@dataclass(frozen=True, slots=True)
class HarnessInfo:
    slug: str
    display_name: str
    short_mark: str
    blurb: str
    install_anchor: str  # fragment id on /connect


HARNESS_CATALOG: tuple[HarnessInfo, ...] = (
    HarnessInfo(
        slug=HARNESS_CURSOR,
        display_name="Cursor",
        short_mark="Cu",
        blurb="IDE agent via remote MCP in mcp.json",
        install_anchor="host-cursor",
    ),
    HarnessInfo(
        slug=HARNESS_CLAUDE_CODE,
        display_name="Claude Code",
        short_mark="CC",
        blurb="CLI / Desktop with remote MCP or project config",
        install_anchor="host-claude-code",
    ),
    HarnessInfo(
        slug=HARNESS_CLAUDE_WEB,
        display_name="Claude.ai",
        short_mark="Cl",
        blurb="Web + mobile custom connector (remote MCP URL)",
        install_anchor="host-claude-web",
    ),
    HarnessInfo(
        slug=HARNESS_CODEX,
        display_name="Codex",
        short_mark="Cx",
        blurb="CLI / Desktop HTTP MCP in config.toml",
        install_anchor="host-codex",
    ),
    HarnessInfo(
        slug=HARNESS_CHATGPT,
        display_name="ChatGPT",
        short_mark="GPT",
        blurb="Apps / Developer Mode remote MCP (OAuth for stores later)",
        install_anchor="host-chatgpt",
    ),
)


def harness_by_slug(slug: str | None) -> HarnessInfo | None:
    if not slug:
        return None
    for item in HARNESS_CATALOG:
        if item.slug == slug:
            return item
    return None


def harness_display_name(slug: str | None, *, client_name: str | None = None) -> str:
    info = harness_by_slug(slug)
    if info is not None:
        return info.display_name
    if client_name:
        return client_name
    if slug == HARNESS_OTHER:
        return "Other"
    return "Unknown"


def normalize_harness(
    *,
    client_name: str | None = None,
    client_version: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, str | None, str | None]:
    """Map client hints to (harness_slug, raw_name, raw_version)."""
    name = (client_name or "").strip() or None
    version = (client_version or "").strip() or None
    ua = (user_agent or "").strip()

    blob = " ".join(p for p in (name or "", ua) if p).lower()
    slug = _match_blob(blob)
    if slug is None:
        slug = HARNESS_OTHER
    return slug, name, version


def _match_blob(blob: str) -> str | None:
    if not blob:
        return None
    # Order matters: more specific before generic "claude"
    if re.search(r"claude\s*code|claude-code|claude_code", blob):
        return HARNESS_CLAUDE_CODE
    if re.search(r"claude\.ai|claude\s*desktop|anthropic.*connector", blob):
        return HARNESS_CLAUDE_WEB
    if "cursor" in blob:
        return HARNESS_CURSOR
    if re.search(r"\bcodex\b|openai.?codex", blob):
        return HARNESS_CODEX
    if re.search(r"chatgpt|openai.?mcp|openai.?agents", blob):
        return HARNESS_CHATGPT
    if "claude" in blob:
        return HARNESS_CLAUDE_WEB
    return None


def extract_client_info_from_mcp_params(
    params: dict[str, Any] | None,
) -> tuple[str | None, str | None]:
    """Pull clientInfo.name / version from an MCP initialize params object."""
    if not isinstance(params, dict):
        return None, None
    info = params.get("clientInfo") or params.get("client_info")
    if not isinstance(info, dict):
        return None, None
    name = info.get("name")
    version = info.get("version")
    return (
        str(name).strip() if name else None,
        str(version).strip() if version else None,
    )


def extract_initialize_client_info(
    body: dict[str, Any] | None,
) -> tuple[str | None, str | None]:
    """From a JSON-RPC MCP request body, return clientInfo if method is initialize."""
    if not isinstance(body, dict):
        return None, None
    if body.get("method") != "initialize":
        return None, None
    params = body.get("params")
    if not isinstance(params, dict):
        return None, None
    return extract_client_info_from_mcp_params(params)


def cursor_mcp_snippet(mcp_url: str, token_placeholder: str) -> str:
    return (
        "{\n"
        '  "mcpServers": {\n'
        '    "pidge": {\n'
        f'      "url": "{mcp_url}",\n'
        '      "headers": {\n'
        f'        "Authorization": "Bearer {token_placeholder}"\n'
        "      }\n"
        "    }\n"
        "  }\n"
        "}"
    )


def claude_code_mcp_snippet(mcp_url: str, token_placeholder: str) -> str:
    return (
        "{\n"
        '  "mcpServers": {\n'
        '    "pidge": {\n'
        '      "type": "http",\n'
        f'      "url": "{mcp_url}",\n'
        '      "headers": {\n'
        f'        "Authorization": "Bearer {token_placeholder}"\n'
        "      }\n"
        "    }\n"
        "  }\n"
        "}"
    )


def codex_toml_snippet(mcp_url: str, token_placeholder: str) -> str:
    return (
        "[mcp_servers.pidge]\n"
        f'url = "{mcp_url}"\n'
        "http_headers = { Authorization = "
        f'"Bearer {token_placeholder}" }}\n'
    )


def chatgpt_connect_blurb(mcp_url: str) -> str:
    return (
        "In ChatGPT: Settings → Apps / Plugins → enable Developer mode → "
        f"create an app with MCP server URL `{mcp_url}`. "
        "Prefer OAuth once the loft supports store-grade auth; until then use "
        "token auth where the host allows it. Never paste Autopilot tokens."
    )


def claude_web_connect_blurb(mcp_url: str) -> str:
    return (
        "In Claude.ai: Customize → Connectors → Add custom connector → "
        f"paste `{mcp_url}`. Add an Authorization bearer header with your Desk "
        "token when static headers are available, or complete OAuth when listed "
        "in the directory."
    )


def cursor_deeplink_hint(mcp_url: str) -> str:
    return (
        f"Cursor: Settings → MCP → Add new MCP server → URL `{mcp_url}` "
        "with Authorization: Bearer <Desk token>. "
        "Or paste the JSON snippet into ~/.cursor/mcp.json."
    )
