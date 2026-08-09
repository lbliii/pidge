"""Public agent discovery endpoints (llms.txt, MCP well-known, /connect)."""

from __future__ import annotations

import json
import re

import pytest
from chirp.testing import TestClient

from pidge.config import PidgeConfig
from pidge.discovery import MCP_TOOLS, mcp_endpoint, resolve_public_origin
from pidge.store import MemoryStore
from pidge.web import SESSION_COOKIE, create_app

HOST = {"Host": "pidge.lol"}


@pytest.fixture
def app():
    config = PidgeConfig(
        env="development",
        debug=True,
        database_url=None,
        secret_key="x" * 48,
        bootstrap_token="development-bootstrap-token",
        public_origin="https://pidge.lol",
        loft_name="Test Loft",
    )
    return create_app(debug=True, store=MemoryStore(), pidge_config=config)


def _header(response, name: str) -> str | None:
    needle = name.lower()
    for header, value in response.headers:
        if header.lower() == needle:
            return value
    return None


def _cookie(response, name: str) -> str | None:
    for header, value in response.headers:
        if header.lower() == "set-cookie" and value.startswith(f"{name}="):
            return value.split(";", 1)[0]
    return None


def _csrf(response) -> str:
    match = re.search(r'<meta name="csrf-token" content="([^"]+)"', response.text)
    if match is None:
        match = re.search(r'name="_csrf_token"[^>]*value="([^"]+)"', response.text)
    assert match is not None
    return match.group(1)


async def _setup_owner(client: TestClient) -> str:
    page = await client.get("/setup", headers=HOST)
    chirp_cookie = _cookie(page, "chirp_session")
    assert chirp_cookie is not None
    response = await client.post(
        "/setup",
        data={
            "_csrf_token": _csrf(page),
            "bootstrap_token": "development-bootstrap-token",
            "loft_name": "Test Loft",
            "username": "owner",
            "display_name": "Owner",
            "password": "password-long",
        },
        headers={**HOST, "Cookie": chirp_cookie},
    )
    pidge_cookie = _cookie(response, SESSION_COOKIE)
    updated = _cookie(response, "chirp_session") or chirp_cookie
    assert pidge_cookie is not None
    return f"{updated}; {pidge_cookie}"


def test_resolve_public_origin_prefers_config() -> None:
    assert resolve_public_origin("https://pidge.lol/", "http://127.0.0.1:8000/") == (
        "https://pidge.lol"
    )


def test_resolve_public_origin_falls_back_to_request() -> None:
    assert resolve_public_origin(None, "http://127.0.0.1:8000/llms.txt") == (
        "http://127.0.0.1:8000"
    )


@pytest.mark.asyncio
async def test_llms_txt_is_public(app) -> None:
    async with TestClient(app) as client:
        response = await client.get("/llms.txt", headers=HOST)
        assert response.status == 200
        assert "text/plain" in (response.content_type or "")
        assert "https://pidge.lol/mcp" in response.text
        assert "/connect" in response.text
        assert "Autopilot" in response.text
        assert "## Addressing" in response.text
        assert "Address book ≠ delivery" in response.text


@pytest.mark.asyncio
async def test_llms_full_lists_tools(app) -> None:
    async with TestClient(app) as client:
        response = await client.get("/llms-full.txt", headers=HOST)
        assert response.status == 200
        for tool in MCP_TOOLS:
            assert tool["name"] in response.text
        assert "tools/list" in response.text
        assert "not cross-loft delivery" in response.text
        assert "address book is local only" in response.text


@pytest.mark.asyncio
async def test_mcp_server_card(app) -> None:
    async with TestClient(app) as client:
        response = await client.get("/.well-known/mcp/server-card.json", headers=HOST)
        assert response.status == 200
        assert _header(response, "access-control-allow-origin") == "*"
        assert "application/json" in (response.content_type or "")
        card = json.loads(response.text)
        assert card["serverInfo"]["name"] == "pidge"
        assert card["transport"]["endpoint"] == "https://pidge.lol/mcp"
        assert card["authentication"]["required"] is True
        names = {t["name"] for t in card["tools"]}
        assert names == {t["name"] for t in MCP_TOOLS}


@pytest.mark.asyncio
async def test_mcp_manifest_and_alias(app) -> None:
    async with TestClient(app) as client:
        primary = await client.get("/.well-known/mcp", headers=HOST)
        alias = await client.get("/.well-known/mcp.json", headers=HOST)
        assert primary.status == 200
        assert alias.status == 200
        body = json.loads(primary.text)
        assert body["endpoints"]["streamable_http"] == mcp_endpoint("https://pidge.lol")
        assert body["authentication"]["required"] is True
        assert json.loads(alias.text) == body


@pytest.mark.asyncio
async def test_robots_and_security_txt(app) -> None:
    async with TestClient(app) as client:
        robots = await client.get("/robots.txt", headers=HOST)
        assert robots.status == 200
        assert "Allow: /llms.txt" in robots.text
        assert "Disallow: /mcp" in robots.text

        security = await client.get("/.well-known/security.txt", headers=HOST)
        assert security.status == 200
        assert "Contact:" in security.text
        assert "github.com/lbliii/pidge" in security.text


@pytest.mark.asyncio
async def test_connect_page_is_public(app) -> None:
    async with TestClient(app) as client:
        page = await client.get("/connect", headers=HOST)
        assert page.status == 200
        assert "https://pidge.lol/mcp" in page.text
        assert "/settings/agents" in page.text
        assert "draft_pidge" in page.text
        assert 'href="/llms.txt"' in page.text
        assert "not cross-loft delivery" in page.text
        assert "Addressing" in page.text


@pytest.mark.asyncio
async def test_login_links_to_connect(app) -> None:
    async with TestClient(app) as client:
        await _setup_owner(client)
        page = await client.get("/login", headers=HOST)
        assert page.status == 200
        assert 'href="/connect"' in page.text
