"""HTTP contract: sealed invite lands in recipient inbox and accepts RSVP."""

from __future__ import annotations

import json
import re

import pytest
from chirp.testing import TestClient

from pidge.config import PidgeConfig
from pidge.services import PidgeService
from pidge.store import MemoryStore
from pidge.web import SESSION_COOKIE, create_app

pytestmark = pytest.mark.asyncio


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
        loft_name="Nowadays Loft",
    )


@pytest.fixture
def app(store: MemoryStore, config: PidgeConfig):
    return create_app(debug=True, store=store, pidge_config=config)


@pytest.fixture
def service(store: MemoryStore, config: PidgeConfig) -> PidgeService:
    return PidgeService(store, config)


def _set_cookie(response, name: str) -> str | None:
    for header, value in response.headers:
        if header.lower() == "set-cookie" and value.startswith(f"{name}="):
            return value.split(";", 1)[0]
    return None


def _merge_cookies(*parts: str | None) -> str:
    return "; ".join(p for p in parts if p)


def _csrf(response) -> str:
    match = re.search(r'<meta name="csrf-token" content="([^"]+)"', response.text)
    if match is None:
        match = re.search(r'name="_csrf_token"[^>]*value="([^"]+)"', response.text)
    assert match is not None
    return match.group(1)


def _mcp_json(response) -> dict:
    body = json.loads(response.text)
    assert "error" not in body, body
    text = body["result"]["content"][0]["text"]
    return json.loads(text)


def _header(response, name: str) -> str | None:
    needle = name.lower()
    for header, value in response.headers:
        if header.lower() == needle:
            return value
    return None


async def _bootstrap_owner(client: TestClient) -> str:
    page = await client.get("/setup")
    assert page.status == 200
    chirp = _set_cookie(page, "chirp_session")
    assert chirp is not None
    response = await client.post(
        "/setup",
        data={
            "_csrf_token": _csrf(page),
            "bootstrap_token": "development-bootstrap-token",
            "loft_name": "Nowadays Loft",
            "username": "owner",
            "display_name": "Owner",
            "password": "password-long",
        },
        headers={"Cookie": chirp},
    )
    assert response.status == 302
    pidge = _set_cookie(response, SESSION_COOKIE)
    chirp = _set_cookie(response, "chirp_session") or chirp
    assert pidge is not None
    return _merge_cookies(chirp, pidge)


async def _register_lucy(client: TestClient) -> str:
    page = await client.get("/register")
    assert page.status == 200
    chirp = _set_cookie(page, "chirp_session")
    assert chirp is not None
    response = await client.post(
        "/register",
        data={
            "_csrf_token": _csrf(page),
            "username": "lucy",
            "display_name": "Lucy",
            "password": "password-long",
        },
        headers={"Cookie": chirp},
    )
    assert response.status == 302
    pidge = _set_cookie(response, SESSION_COOKIE)
    chirp = _set_cookie(response, "chirp_session") or chirp
    assert pidge is not None
    return _merge_cookies(chirp, pidge)


async def _login(client: TestClient, *, username: str, password: str) -> str:
    page = await client.get("/login")
    assert page.status == 200
    chirp = _set_cookie(page, "chirp_session")
    assert chirp is not None
    response = await client.post(
        "/login",
        data={
            "_csrf_token": _csrf(page),
            "username": username,
            "password": password,
        },
        headers={"Cookie": chirp},
    )
    assert response.status == 302
    pidge = _set_cookie(response, SESSION_COOKIE)
    chirp = _set_cookie(response, "chirp_session") or chirp
    assert pidge is not None
    return _merge_cookies(chirp, pidge)


async def test_sealed_invite_appears_in_recipient_inbox_and_rsvp(
    app, service: PidgeService
) -> None:
    """Author seal → Lucy inbox visibility → rsvp_yes (HTTP + MCP path)."""
    async with TestClient(app) as client:
        owner_cookies = await _bootstrap_owner(client)
        lucy_cookies = await _register_lucy(client)

        # Re-login owner: Lucy registration replaced the session cookie.
        owner_cookies = await _login(client, username="owner", password="password-long")
        owner = service.store.get_user_by_username("owner")
        minted = service.mint_agent_token(owner, label="Nowadays Secretary")

        drafted = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "id": 1,
                "params": {
                    "name": "draft_pidge",
                    "arguments": {
                        "intent": "Tell Lucy we're meeting tonight at 7 at Nowadays",
                        "recipients": ["Lucy"],
                        "summary": "Tonight at Nowadays",
                    },
                },
            },
            headers={"Authorization": f"Bearer {minted.secret}"},
        )
        assert drafted.status == 200
        draft = _mcp_json(drafted)
        pidge_id = int(draft["id"])
        assert draft["state"] == "draft"

        enriched = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "id": 2,
                "params": {
                    "name": "enrich_pidge",
                    "arguments": {
                        "pidge_id": pidge_id,
                        "who": "Lucy",
                        "when": "tonight · 7:00 PM",
                        "where": "Nowadays, Brooklyn",
                        "extras": {"menu": "kitchen + wine"},
                    },
                },
            },
            headers={"Authorization": f"Bearer {minted.secret}"},
        )
        assert enriched.status == 200
        slots = _mcp_json(enriched)["slots"]
        assert slots["where"]["status"] == "ready"

        compose = await client.get(f"/compose/{pidge_id}", headers={"Cookie": owner_cookies})
        assert compose.status == 200
        seal = await client.post(
            f"/compose/{pidge_id}/seal",
            data={"_csrf_token": _csrf(compose)},
            headers={"Cookie": owner_cookies},
        )
        assert seal.status == 302
        assert f"/p/{pidge_id}" in (_header(seal, "location") or "")

        # Draft must not leak to Lucy before seal — already sealed here; inbox shows it.
        inbox = await client.get("/inbox", headers={"Cookie": lucy_cookies})
        assert inbox.status == 200
        assert "Tonight at Nowadays" in inbox.text or "Nowadays" in inbox.text
        assert f"/p/{pidge_id}" in inbox.text

        lucy = service.store.get_user_by_username("lucy")
        store_inbox = service.store.list_inbox(lucy.id)
        assert len(store_inbox) == 1
        assert store_inbox[0].id == pidge_id
        assert store_inbox[0].state == "sealed"

        thread = await client.get(f"/p/{pidge_id}", headers={"Cookie": lucy_cookies})
        assert thread.status == 200
        assert "Accept" in thread.text
        assert 'value="rsvp_yes"' in thread.text
        rsvp = await client.post(
            f"/p/{pidge_id}/act",
            data={"_csrf_token": _csrf(thread), "kind": "rsvp_yes"},
            headers={"Cookie": lucy_cookies},
        )
        assert rsvp.status == 302

        acts = service.store.list_acts(pidge_id)
        assert any(a.kind == "rsvp_yes" and a.actor_user_id == lucy.id for a in acts)

        holds = service.store.list_holds(owner.id)
        assert len(holds) == 1
        assert holds[0].state == "confirmed"
        assert "Nowadays" in (holds[0].place or "")

        pin_page = await client.get(f"/p/{pidge_id}", headers={"Cookie": lucy_cookies})
        pin = await client.post(
            "/wall/pin",
            data={"_csrf_token": _csrf(pin_page), "pidge_id": str(pidge_id)},
            headers={"Cookie": lucy_cookies},
        )
        assert pin.status == 302
        assert service.store.list_pins(lucy.id)


async def test_draft_not_visible_in_recipient_inbox(app, service: PidgeService) -> None:
    async with TestClient(app) as client:
        await _bootstrap_owner(client)
        lucy_cookies = await _register_lucy(client)
        owner = service.store.get_user_by_username("owner")
        service.draft_pidge(
            owner,
            intent="Secret draft for Lucy",
            recipient_names=["Lucy"],
            summary="Secret draft",
        )

        inbox = await client.get("/inbox", headers={"Cookie": lucy_cookies})
        assert inbox.status == 200
        assert "Secret draft" not in inbox.text
        assert "No sealed Pidges" in inbox.text
        lucy = service.store.get_user_by_username("lucy")
        assert service.store.list_inbox(lucy.id) == ()
