"""Capture MCP client hints (initialize clientInfo / User-Agent) for harness attribution."""

from __future__ import annotations

import contextvars
import json
from typing import Any

from chirp.http.request import Request

from pidge.harness import extract_initialize_client_info

_client_hints: contextvars.ContextVar[dict[str, str | None]] = contextvars.ContextVar(
    "pidge_mcp_client_hints",
    default={},
)


def current_mcp_client_hints() -> dict[str, str | None]:
    return dict(_client_hints.get())


class McpHarnessMiddleware:
    """Peek /mcp JSON-RPC bodies and User-Agent into a ContextVar for token verify."""

    async def __call__(self, request: Request, next: Any) -> Any:
        hints: dict[str, str | None] = {}
        if request.path == "/mcp" and request.method.upper() == "POST":
            ua = request.headers.get("user-agent")
            if ua:
                hints["user_agent"] = ua
            explicit = request.headers.get("x-pidge-harness")
            if explicit:
                hints["client_name"] = explicit.strip()
            try:
                raw = await request.body()
                body = json.loads(raw) if raw else None
                name, version = extract_initialize_client_info(body)
                if name:
                    hints["client_name"] = name
                if version:
                    hints["client_version"] = version
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
                pass

        token = _client_hints.set(hints)
        try:
            return await next(request)
        finally:
            _client_hints.reset(token)
