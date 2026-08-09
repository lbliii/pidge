"""Design system: tokens + primitives adopted on desk surfaces."""

from __future__ import annotations

import re

import pytest
from chirp.testing import TestClient

from pidge.config import PidgeConfig
from pidge.store import MemoryStore
from pidge.web import SESSION_COOKIE, create_app

pytestmark = pytest.mark.asyncio


@pytest.fixture
def app():
    config = PidgeConfig(
        env="development",
        debug=True,
        database_url=None,
        secret_key="x" * 48,
        bootstrap_token="development-bootstrap-token",
        public_origin=None,
        loft_name="Test Loft",
    )
    return create_app(debug=True, store=MemoryStore(), pidge_config=config)


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
    pidge_cookie = _cookie(response, SESSION_COOKIE)
    updated = _cookie(response, "chirp_session") or chirp_cookie
    assert pidge_cookie is not None
    return f"{updated}; {pidge_cookie}"


async def test_contacts_uses_field_and_empty_state(app) -> None:
    async with TestClient(app) as client:
        cookies = await _setup_owner(client)
        page = await client.get("/contacts", headers={"Cookie": cookies})
        assert page.status == 200
        assert 'class="field"' in page.text
        assert 'class="empty-state"' in page.text
        assert 'style="color:#8b3a2a"' not in page.text


async def test_login_uses_field_primitive(app) -> None:
    async with TestClient(app) as client:
        await _setup_owner(client)
        page = await client.get("/login")
        assert page.status == 200
        assert 'class="field"' in page.text
        assert 'class="btn btn-seal"' in page.text


async def test_setup_uses_field_primitive(app) -> None:
    async with TestClient(app) as client:
        page = await client.get("/setup")
        assert page.status == 200
        assert 'class="field"' in page.text
        assert 'class="btn btn-seal"' in page.text


async def test_agents_uses_preset_cards(app) -> None:
    async with TestClient(app) as client:
        cookies = await _setup_owner(client)
        page = await client.get("/settings/agents", headers={"Cookie": cookies})
        assert page.status == 200
        assert 'class="preset-grid"' in page.text
        assert "preset-card" in page.text
        assert 'class="btn btn-danger"' in page.text or "No tokens yet" in page.text
