"""Contract tests for the Pidge loft (MemoryStore)."""

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
    updated_chirp = _cookie(response, "chirp_session") or chirp_cookie
    assert pidge_cookie is not None
    return f"{updated_chirp}; {pidge_cookie}"


async def test_setup_login_desk(app) -> None:
    async with TestClient(app) as client:
        cookies = await _setup_owner(client)
        desk = await client.get("/", headers={"Cookie": cookies})
        assert desk.status == 200
        assert "Good day" in desk.text
        assert "Owner" in desk.text


async def test_register_second_user_and_directory(app, service: PidgeService) -> None:
    async with TestClient(app) as client:
        cookies = await _setup_owner(client)
        page = await client.get("/register", headers={"Cookie": cookies})
        response = await client.post(
            "/register",
            data={
                "_csrf_token": _csrf(page),
                "username": "lucy",
                "display_name": "Lucy",
                "password": "password-long",
            },
            headers={"Cookie": cookies},
        )
        assert response.status == 302

    owner = service.store.get_user_by_username("owner")
    people = service.directory(owner)
    assert any(u.username == "lucy" for u in people)


async def test_mail_seal_inbox_act_calendar_wall(service: PidgeService) -> None:
    owner = service.setup(
        bootstrap_token="development-bootstrap-token",
        loft_name="Test Loft",
        username="owner",
        display_name="Owner",
        password="password-long",
    ).user
    lucy = service.register(
        username="lucy", display_name="Lucy", password="password-long"
    ).user

    draft = service.draft_pidge(
        owner,
        intent="Tell Lucy we're meeting tonight at 7 at Nowadays",
        recipient_names=["Lucy"],
    )
    assert draft.state == "draft"
    enriched = service.enrich_pidge(
        owner,
        draft.id,
        who="Lucy",
        when="tonight · 7:00 PM",
        where="Nowadays, Brooklyn",
        extras={"menu": "kitchen + wine"},
    )
    assert enriched.slots["where"]["status"] == "ready"
    sealed = service.seal_pidge(owner, draft.id)
    assert sealed.state == "sealed"
    assert sealed.content_hash

    inbox = service.store.list_inbox(lucy.id)
    assert len(inbox) == 1
    assert inbox[0].id == sealed.id

    act = service.record_act(lucy, sealed.id, "rsvp_yes")
    assert act.kind == "rsvp_yes"

    holds = service.store.list_holds(owner.id)
    assert len(holds) == 1
    assert holds[0].state == "confirmed"

    pin = service.pin_note(lucy, sealed.id)
    assert pin.pidge_id == sealed.id
    assert service.store.list_pins(lucy.id)


async def test_external_contact_required_for_out_of_loft(service: PidgeService) -> None:
    owner = service.setup(
        bootstrap_token="development-bootstrap-token",
        loft_name="Test Loft",
        username="owner",
        display_name="Owner",
        password="password-long",
    ).user
    with pytest.raises(LookupError):
        service.draft_pidge(owner, intent="hi", recipient_names=["Stranger"])
    contact = service.add_external_contact(
        owner, handle="stranger@elsewhere", display_name="Stranger"
    )
    assert contact.status == "pending"
    draft = service.draft_pidge(owner, intent="hi stranger", recipient_names=["Stranger"])
    assert draft.state == "draft"


async def test_agent_token_mcp_tools(app, service: PidgeService) -> None:
    owner = service.setup(
        bootstrap_token="development-bootstrap-token",
        loft_name="Test Loft",
        username="owner",
        display_name="Owner",
        password="password-long",
    ).user
    service.register(username="lucy", display_name="Lucy", password="password-long")
    minted = service.mint_agent_token(owner, label="Secretary")

    async with TestClient(app) as client:
        listed = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1, "params": {}},
            headers={"Authorization": f"Bearer {minted.secret}"},
        )
        assert listed.status == 200
        payload = json.loads(listed.text)
        names = {t["name"] for t in payload["result"]["tools"]}
        assert "draft_pidge" in names
        assert "enrich_pidge" in names
        assert "seal_pidge" not in names

        drafted = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "id": 2,
                "params": {
                    "name": "draft_pidge",
                    "arguments": {
                        "intent": "Meet Lucy at Nowadays",
                        "recipients": ["Lucy"],
                    },
                },
            },
            headers={"Authorization": f"Bearer {minted.secret}"},
        )
        assert drafted.status == 200
        body = json.loads(drafted.text)
        assert "result" in body

        denied = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "id": 3,
                "params": {
                    "name": "draft_pidge",
                    "arguments": {"intent": "x", "recipients": ["Lucy"]},
                },
            },
        )
        assert denied.status == 200
        denied_body = json.loads(denied.text)
        assert "error" in denied_body or "error" in str(denied_body.get("result", ""))


async def test_cannot_seal_without_slots(service: PidgeService) -> None:
    owner = service.setup(
        bootstrap_token="development-bootstrap-token",
        loft_name="Test Loft",
        username="owner",
        display_name="Owner",
        password="password-long",
    ).user
    service.register(username="lucy", display_name="Lucy", password="password-long")
    draft = service.draft_pidge(owner, intent="soon", recipient_names=["Lucy"])
    with pytest.raises(ValueError, match="Slot"):
        service.seal_pidge(owner, draft.id)


async def test_ready_endpoint(app) -> None:
    async with TestClient(app) as client:
        response = await client.get("/ready")
        assert response.status == 200
        assert "ready" in response.text
