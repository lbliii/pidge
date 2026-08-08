"""Confirm seal: propose_seal MCP + one-shot browser challenge redeem."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta

import pytest
from chirp.testing import TestClient

from pidge.config import CONFIRM_SCOPES, DESK_SCOPES, TOKEN_PRESETS, infer_preset, PidgeConfig
from pidge.services import PidgeService
from pidge.store import MemoryStore, token_hash
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


def _header(response, name: str) -> str | None:
    needle = name.lower()
    for header, value in response.headers:
        if header.lower() == needle:
            return value
    return None


def _setup_loft(service: PidgeService):
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
    return owner, lucy


def _ready_draft(service: PidgeService, owner):
    return service.enrich_pidge(
        owner,
        service.draft_pidge(
            owner,
            intent="Tell Lucy dinner is on",
            recipient_names=["Lucy"],
        ).id,
        who="Lucy",
        when="tonight · 7:00 PM",
        where="Nowadays, Brooklyn",
    )


async def _login(client: TestClient, *, username: str = "owner") -> str:
    login_page = await client.get("/login")
    assert login_page.status == 200
    chirp_cookie = _cookie(login_page, "chirp_session")
    assert chirp_cookie is not None
    login = await client.post(
        "/login",
        data={
            "_csrf_token": _csrf(login_page),
            "username": username,
            "password": "password-long",
        },
        headers={"Cookie": chirp_cookie},
    )
    assert login.status == 302
    pidge_cookie = _cookie(login, SESSION_COOKIE)
    updated_chirp = _cookie(login, "chirp_session") or chirp_cookie
    assert pidge_cookie is not None
    return f"{updated_chirp}; {pidge_cookie}"


async def _mcp_call(
    client: TestClient, *, secret: str, name: str, arguments: dict, rpc_id: int = 1
):
    response = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": rpc_id,
            "params": {"name": name, "arguments": arguments},
        },
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert response.status == 200
    return json.loads(response.text)


def _tool_payload(body: dict) -> dict:
    """Unwrap MCP tools/call content when present."""
    result = body.get("result") or {}
    if isinstance(result, dict) and "content" in result:
        for block in result["content"]:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return {"text": text}
        return result
    if isinstance(result, dict):
        return result
    return {"raw": result}


def test_confirm_preset_scopes() -> None:
    assert TOKEN_PRESETS["confirm"] == CONFIRM_SCOPES
    assert CONFIRM_SCOPES == DESK_SCOPES | frozenset({"pidge:seal.propose"})
    assert "pidge:seal" not in CONFIRM_SCOPES
    assert infer_preset(CONFIRM_SCOPES) == "confirm"


def test_seal_challenge_create_get_consume_and_double(store: MemoryStore) -> None:
    service = PidgeService(
        store,
        PidgeConfig(
            env="development",
            debug=True,
            database_url=None,
            secret_key="x" * 48,
            bootstrap_token="development-bootstrap-token",
            public_origin=None,
            loft_name="Test Loft",
        ),
    )
    owner, _lucy = _setup_loft(service)
    draft = _ready_draft(service, owner)
    secret = "pidge_sc_testsecret"
    hashed = token_hash(secret)
    expires = datetime.now(UTC) + timedelta(minutes=15)
    created = store.create_seal_challenge(
        token_hash_value=hashed,
        pidge_id=draft.id,
        author_user_id=owner.id,
        created_by_token_id=None,
        expires_at=expires,
    )
    assert created.consumed_at is None
    assert store.get_seal_challenge_by_hash(hashed) == created
    now = datetime.now(UTC)
    consumed = store.consume_seal_challenge(hashed, now)
    assert consumed is not None
    assert consumed.consumed_at == now
    assert store.consume_seal_challenge(hashed, datetime.now(UTC)) is None


def test_propose_seal_uses_public_origin(service: PidgeService) -> None:
    owner, _lucy = _setup_loft(service)
    draft = _ready_draft(service, owner)
    proposed = service.propose_seal(
        owner,
        draft.id,
        public_origin="https://pidge.example",
    )
    assert proposed.seal_url.startswith(
        f"https://pidge.example/compose/{draft.id}/seal-challenge/pidge_sc_"
    )


def test_propose_seal_requires_origin_in_production() -> None:
    store = MemoryStore()
    config = PidgeConfig(
        env="production",
        debug=False,
        database_url="postgresql://unused",
        secret_key="x" * 48,
        bootstrap_token="x" * 24,
        public_origin=None,
        loft_name="Prod Loft",
    )
    service = PidgeService(store, config)
    with pytest.raises(RuntimeError, match="PIDGE_PUBLIC_ORIGIN"):
        service._resolve_public_origin(None)


@pytest.mark.asyncio
async def test_desk_token_denied_propose_seal(app, service: PidgeService) -> None:
    owner, _lucy = _setup_loft(service)
    draft = _ready_draft(service, owner)
    desk = service.mint_agent_token(owner, label="Desk", preset="desk")

    async with TestClient(app) as client:
        denied = await _mcp_call(
            client,
            secret=desk.secret,
            name="propose_seal",
            arguments={"pidge_id": draft.id},
        )
        assert "error" in denied
        detail = str(denied["error"])
        assert "pidge:seal.propose" in detail or "Missing scopes" in detail


@pytest.mark.asyncio
async def test_propose_seal_incomplete_slots(app, service: PidgeService) -> None:
    owner, _lucy = _setup_loft(service)
    draft = service.draft_pidge(owner, intent="Incomplete", recipient_names=["Lucy"])
    confirm = service.mint_agent_token(owner, label="Confirm", preset="confirm")

    async with TestClient(app) as client:
        failed = await _mcp_call(
            client,
            secret=confirm.secret,
            name="propose_seal",
            arguments={"pidge_id": draft.id},
        )
        assert "error" in failed
        assert "Slot" in str(failed["error"]) or "seal" in str(failed["error"]).lower()


@pytest.mark.asyncio
async def test_propose_seal_happy_path_and_redeem_once(
    app, service: PidgeService
) -> None:
    owner, _lucy = _setup_loft(service)
    draft = _ready_draft(service, owner)
    confirm = service.mint_agent_token(owner, label="Confirm", preset="confirm")

    async with TestClient(app) as client:
        proposed = await _mcp_call(
            client,
            secret=confirm.secret,
            name="propose_seal",
            arguments={"pidge_id": draft.id},
        )
        assert "error" not in proposed
        payload = _tool_payload(proposed)
        assert payload["pidge_id"] == draft.id
        seal_url = payload["seal_url"]
        assert "/compose/" in seal_url
        assert "/seal-challenge/pidge_sc_" in seal_url
        secret = seal_url.rsplit("/", 1)[-1]

        session = await _login(client)
        preview = await client.get(
            f"/compose/{draft.id}/seal-challenge/{secret}",
            headers={"Cookie": session},
        )
        assert preview.status == 200
        assert "Confirm seal" in preview.text
        assert "Lucy" in preview.text

        sealed = await client.post(
            f"/compose/{draft.id}/seal-challenge/{secret}",
            data={"_csrf_token": _csrf(preview)},
            headers={"Cookie": session},
        )
        assert sealed.status == 302
        assert f"/p/{draft.id}" in (_header(sealed, "location") or "")
        assert service.store.get_pidge(draft.id).state == "sealed"

        reuse = await client.post(
            f"/compose/{draft.id}/seal-challenge/{secret}",
            data={"_csrf_token": _csrf(preview)},
            headers={"Cookie": session},
        )
        assert reuse.status in {403, 410}


@pytest.mark.asyncio
async def test_non_author_cannot_redeem(app, service: PidgeService) -> None:
    owner, lucy = _setup_loft(service)
    draft = _ready_draft(service, owner)
    confirm = service.mint_agent_token(owner, label="Confirm", preset="confirm")
    proposed = service.propose_seal(owner, draft.id, agent_token_id=confirm.token.id)
    secret = proposed.secret

    async with TestClient(app) as client:
        lucy_session = await _login(client, username="lucy")
        blocked = await client.get(
            f"/compose/{draft.id}/seal-challenge/{secret}",
            headers={"Cookie": lucy_session},
        )
        assert blocked.status == 403
        assert lucy.username == "lucy"


@pytest.mark.asyncio
async def test_bearer_cannot_redeem_seal_challenge(app, service: PidgeService) -> None:
    owner, _lucy = _setup_loft(service)
    draft = _ready_draft(service, owner)
    confirm = service.mint_agent_token(owner, label="Confirm", preset="confirm")
    proposed = service.propose_seal(owner, draft.id, agent_token_id=confirm.token.id)

    async with TestClient(app) as client:
        bare = await client.get(
            f"/compose/{draft.id}/seal-challenge/{proposed.secret}",
            headers={"Authorization": f"Bearer {confirm.secret}"},
        )
        assert bare.status in {302, 401, 403}
        if bare.status == 302:
            assert "/login" in (_header(bare, "location") or "")

        post = await client.post(
            f"/compose/{draft.id}/seal-challenge/{proposed.secret}",
            data={},
            headers={"Authorization": f"Bearer {confirm.secret}"},
        )
        assert post.status in {302, 401, 403}
        assert service.store.get_pidge(draft.id).state == "draft"


@pytest.mark.asyncio
async def test_agents_ui_enables_confirm(app, service: PidgeService) -> None:
    _setup_loft(service)

    async with TestClient(app) as client:
        session = await _login(client)
        agents = await client.get("/settings/agents", headers={"Cookie": session})
        assert agents.status == 200
        assert 'name="preset" value="confirm"' in agents.text
        assert 'name="preset" value="autopilot"' in agents.text
        assert "Autopilot" in agents.text
        assert "coming soon" not in agents.text.lower()
        assert "acknowledge_autopilot" in agents.text
