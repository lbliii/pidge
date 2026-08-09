"""Harness attribution + intelligent compose / connect surfaces."""

from __future__ import annotations

import re

import pytest
from chirp.testing import TestClient

from pidge.config import PidgeConfig
from pidge.harness import HARNESS_CLAUDE_CODE, HARNESS_CURSOR, normalize_harness
from pidge.services import PidgeService
from pidge.store import MemoryStore
from pidge.web import SESSION_COOKIE, create_app


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def config() -> PidgeConfig:
    return PidgeConfig(
        env="development",
        debug=True,
        database_url=None,
        secret_key="x" * 48,
        bootstrap_token="development-bootstrap-token",
        public_origin=None,
        loft_name="Test Loft",
    )


@pytest.fixture
def app(store: MemoryStore, config: PidgeConfig):
    return create_app(debug=True, store=store, pidge_config=config)


@pytest.fixture
def service(store: MemoryStore, config: PidgeConfig) -> PidgeService:
    return PidgeService(store, config)


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
    page = await client.get("/setup")
    assert page.status == 200
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
        headers={"Cookie": chirp_cookie},
    )
    assert response.status == 302
    pidge_cookie = _cookie(response, SESSION_COOKIE)
    assert pidge_cookie is not None
    return f"{chirp_cookie}; {pidge_cookie}"


def test_normalize_harness_claude_code() -> None:
    slug, name, _ = normalize_harness(client_name="claude-code", client_version="2.0")
    assert slug == HARNESS_CLAUDE_CODE
    assert name == "claude-code"


def test_normalize_harness_cursor_ua() -> None:
    slug, _, _ = normalize_harness(user_agent="Cursor/1.0 (MCP)")
    assert slug == HARNESS_CURSOR


@pytest.mark.asyncio
async def test_compose_setup_mode_shows_harness_wall(app) -> None:
    async with TestClient(app) as client:
        cookies = await _setup_owner(client)
        page = await client.get("/compose", headers={"Cookie": cookies})
        assert page.status == 200
        assert "Connect an agent" in page.text
        assert "Compatible harnesses" in page.text
        assert "harness-wall" in page.text
        assert "Cursor" in page.text
        assert "Claude.ai" in page.text
        assert "<textarea" not in page.text


@pytest.mark.asyncio
async def test_compose_quiet_then_active_after_mcp(
    app, service: PidgeService
) -> None:
    async with TestClient(app) as client:
        cookies = await _setup_owner(client)
        owner = service.store.get_user_by_username("owner")
        minted = service.mint_agent_token(
            owner, label="Secretary", intended_harness="cursor"
        )

        quiet = await client.get("/compose", headers={"Cookie": cookies})
        assert quiet.status == 200
        assert "Minted but quiet" in quiet.text or "never used" in quiet.text
        assert "Secretary" in quiet.text
        assert "Manage agents" in quiet.text

        init = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "claude-code", "version": "1.2.3"},
                },
            },
            headers={
                "Authorization": f"Bearer {minted.secret}",
                "User-Agent": "claude-code/1.2.3",
            },
        )
        assert init.status == 200

        tokens = service.list_agent_tokens(owner)
        assert tokens[0].last_harness == HARNESS_CLAUDE_CODE
        assert tokens[0].last_client_name == "claude-code"
        assert tokens[0].last_used_at is not None

        active = await client.get("/compose", headers={"Cookie": cookies})
        assert active.status == 200
        assert "Your agents are ready" in active.text
        assert "Claude Code" in active.text
        assert "Secretary" in active.text


@pytest.mark.asyncio
async def test_agents_list_shows_harness(app, service: PidgeService) -> None:
    async with TestClient(app) as client:
        cookies = await _setup_owner(client)
        owner = service.store.get_user_by_username("owner")
        minted = service.mint_agent_token(owner, label="Wally", intended_harness="codex")
        await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={
                "Authorization": f"Bearer {minted.secret}",
                "User-Agent": "codex-cli/0.1",
                "X-Pidge-Harness": "codex",
            },
        )
        page = await client.get("/settings/agents", headers={"Cookie": cookies})
        assert page.status == 200
        assert "Wally" in page.text
        assert "Codex" in page.text
        assert "intended_harness" in page.text


@pytest.mark.asyncio
async def test_connect_host_matrix(app) -> None:
    async with TestClient(app) as client:
        page = await client.get("/connect")
        assert page.status == 200
        assert 'id="host-cursor"' in page.text
        assert 'id="host-claude-code"' in page.text
        assert 'id="host-claude-web"' in page.text
        assert 'id="host-codex"' in page.text
        assert 'id="host-chatgpt"' in page.text
        assert "mcp_servers.pidge" in page.text or "config.toml" in page.text
        assert "plugins/claude-pidge" in page.text
