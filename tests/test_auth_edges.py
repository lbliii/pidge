"""Auth hard edges: revoked tokens, missing scopes, seal stays session-only."""

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


async def _mcp_call(
    client: TestClient,
    *,
    secret: str | None,
    method: str,
    rpc_id: int,
    params: dict | None = None,
):
    headers = {}
    if secret is not None:
        headers["Authorization"] = f"Bearer {secret}"
    response = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": method,
            "id": rpc_id,
            "params": params or {},
        },
        headers=headers,
    )
    assert response.status == 200
    return json.loads(response.text)


async def test_revoked_agent_token_cannot_call_mcp_tools(
    app, service: PidgeService
) -> None:
    """#13: mint → revoke → tools/call auth error; active token still works."""
    owner, _lucy = _setup_loft(service)
    revoked = service.mint_agent_token(owner, label="Revoked Secretary")
    active = service.mint_agent_token(owner, label="Active Secretary")

    async with TestClient(app) as client:
        before = await _mcp_call(
            client,
            secret=revoked.secret,
            method="tools/call",
            rpc_id=1,
            params={
                "name": "list_directory",
                "arguments": {},
            },
        )
        assert "result" in before
        assert "error" not in before

        service.revoke_agent_token(owner, revoked.token.id)

        after = await _mcp_call(
            client,
            secret=revoked.secret,
            method="tools/call",
            rpc_id=2,
            params={
                "name": "list_directory",
                "arguments": {},
            },
        )
        assert "error" in after
        message = str(after["error"]).lower()
        assert "agent" in message or "token" in message or "auth" in message or "401" in message

        still = await _mcp_call(
            client,
            secret=active.secret,
            method="tools/call",
            rpc_id=3,
            params={
                "name": "list_directory",
                "arguments": {},
            },
        )
        assert "result" in still
        assert "error" not in still


async def test_missing_scope_denied_on_scoped_tools(
    app, service: PidgeService
) -> None:
    """#14: no pidge:notes.pin → pin_note denied; draft scope still drafts."""
    owner, lucy = _setup_loft(service)
    draft_only = service.mint_agent_token(
        owner,
        label="Draft Only",
        scopes=frozenset({"pidge:draft"}),
    )

    sealed = service.seal_pidge(
        owner,
        service.enrich_pidge(
            owner,
            service.draft_pidge(
                owner,
                intent="Tell Lucy dinner is on",
                recipient_names=["Lucy"],
            ).id,
            who="Lucy",
            when="tonight · 7:00 PM",
            where="Nowadays, Brooklyn",
        ).id,
    )
    assert sealed.state == "sealed"
    assert lucy.username == "lucy"

    async with TestClient(app) as client:
        drafted = await _mcp_call(
            client,
            secret=draft_only.secret,
            method="tools/call",
            rpc_id=1,
            params={
                "name": "draft_pidge",
                "arguments": {
                    "intent": "Coffee with Lucy",
                    "recipients": ["Lucy"],
                },
            },
        )
        assert "result" in drafted
        assert "error" not in drafted

        denied = await _mcp_call(
            client,
            secret=draft_only.secret,
            method="tools/call",
            rpc_id=2,
            params={
                "name": "pin_note",
                "arguments": {"pidge_id": sealed.id},
            },
        )
        assert "error" in denied
        detail = str(denied["error"])
        assert "pidge:notes.pin" in detail or "Missing scopes" in detail


async def test_seal_not_mcp_and_ui_requires_session(
    app, service: PidgeService
) -> None:
    """#15: no seal MCP tool; unauth seal fails; author session seals when ready."""
    owner, _lucy = _setup_loft(service)
    minted = service.mint_agent_token(owner, label="Secretary")
    draft = service.enrich_pidge(
        owner,
        service.draft_pidge(
            owner,
            intent="Tell Lucy we're meeting tonight at 7 at Nowadays",
            recipient_names=["Lucy"],
        ).id,
        who="Lucy",
        when="tonight · 7:00 PM",
        where="Nowadays, Brooklyn",
        extras={"menu": "kitchen + wine"},
    )
    assert draft.state == "draft"

    async with TestClient(app) as client:
        listed = await _mcp_call(
            client,
            secret=minted.secret,
            method="tools/list",
            rpc_id=1,
        )
        names = {t["name"] for t in listed["result"]["tools"]}
        assert "seal_pidge" not in names
        assert "propose_seal" in names
        assert not any(n == "seal" or n.startswith("seal_") for n in names)

        unauth = await client.post(f"/compose/{draft.id}/seal", data={})
        assert unauth.status in {302, 401, 403}
        if unauth.status == 302:
            location = _header(unauth, "location") or ""
            assert "/login" in location

        # Loft already exists via service.setup — author authenticates through /login.
        login_page = await client.get("/login")
        assert login_page.status == 200
        chirp_cookie = _cookie(login_page, "chirp_session")
        assert chirp_cookie is not None
        login = await client.post(
            "/login",
            data={
                "_csrf_token": _csrf(login_page),
                "username": "owner",
                "password": "password-long",
            },
            headers={"Cookie": chirp_cookie},
        )
        assert login.status == 302
        pidge_cookie = _cookie(login, SESSION_COOKIE)
        updated_chirp = _cookie(login, "chirp_session") or chirp_cookie
        assert pidge_cookie is not None
        session = f"{updated_chirp}; {pidge_cookie}"

        compose = await client.get(
            f"/compose/{draft.id}", headers={"Cookie": session}
        )
        assert compose.status == 200
        sealed = await client.post(
            f"/compose/{draft.id}/seal",
            data={"_csrf_token": _csrf(compose)},
            headers={"Cookie": session},
        )
        assert sealed.status == 302
        location = _header(sealed, "location") or ""
        assert location.startswith("/p/")
        sealed_id = int(location.rsplit("/", 1)[-1])
        msg = service.store.get_pidge(sealed_id)
        assert msg.state == "sealed"
