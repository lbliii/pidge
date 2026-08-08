"""Token presets: Desk default, Draft narrow, Agents mint form."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta

import pytest
from chirp.testing import TestClient

from pidge.config import (
    AUTOPILOT_SCOPES,
    AUTOPILOT_TOKEN_TTL_DAYS,
    DESK_SCOPES,
    DESK_TOKEN_TTL_DAYS,
    TOKEN_PRESETS,
    infer_preset,
    PidgeConfig,
)
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


def _setup_owner(service: PidgeService):
    return service.setup(
        bootstrap_token="development-bootstrap-token",
        loft_name="Test Loft",
        username="owner",
        display_name="Owner",
        password="password-long",
    ).user


def test_infer_preset_matches_draft_and_desk() -> None:
    assert infer_preset(TOKEN_PRESETS["draft"]) == "draft"
    assert infer_preset(DESK_SCOPES) == "desk"
    assert infer_preset(TOKEN_PRESETS["confirm"]) == "confirm"
    assert infer_preset(TOKEN_PRESETS["autopilot"]) == "autopilot"
    assert infer_preset(frozenset({"pidge:draft", "pidge:enrich"})) is None


def test_default_mint_uses_desk_scopes(service: PidgeService) -> None:
    owner = _setup_owner(service)
    minted = service.mint_agent_token(owner, label="Secretary")
    assert minted.token.scopes == DESK_SCOPES
    assert infer_preset(minted.token.scopes) == "desk"


def test_preset_draft_mints_draft_only(service: PidgeService) -> None:
    owner = _setup_owner(service)
    minted = service.mint_agent_token(owner, label="Drafty", preset="draft")
    assert minted.token.scopes == frozenset({"pidge:draft"})
    assert infer_preset(minted.token.scopes) == "draft"


def test_preset_confirm_mints_confirm_scopes(service: PidgeService) -> None:
    owner = _setup_owner(service)
    minted = service.mint_agent_token(owner, label="Confirm Bot", preset="confirm")
    assert minted.token.scopes == TOKEN_PRESETS["confirm"]
    assert infer_preset(minted.token.scopes) == "confirm"
    assert "pidge:seal.propose" in minted.token.scopes
    assert "pidge:seal" not in minted.token.scopes


def test_preset_autopilot_mints_seal_scope(service: PidgeService) -> None:
    owner = _setup_owner(service)
    minted = service.mint_agent_token(owner, label="Auto", preset="autopilot")
    assert minted.token.scopes == AUTOPILOT_SCOPES
    assert infer_preset(minted.token.scopes) == "autopilot"
    assert "pidge:seal" in minted.token.scopes
    assert "pidge:seal.propose" in minted.token.scopes


def test_unknown_preset_raises(service: PidgeService) -> None:
    owner = _setup_owner(service)
    with pytest.raises(ValueError, match="Unknown preset"):
        service.mint_agent_token(owner, label="Nope", preset="bogus")


def test_autopilot_ttl_shorter_than_desk(service: PidgeService) -> None:
    owner = _setup_owner(service)
    before = datetime.now(UTC)
    auto = service.mint_agent_token(
        owner, label="Auto", preset="autopilot", days=AUTOPILOT_TOKEN_TTL_DAYS
    )
    desk = service.mint_agent_token(
        owner, label="Desk", preset="desk", days=DESK_TOKEN_TTL_DAYS
    )
    assert auto.token.expires_at is not None
    assert desk.token.expires_at is not None
    auto_delta = auto.token.expires_at - before
    desk_delta = desk.token.expires_at - before
    assert timedelta(days=29) < auto_delta < timedelta(days=31)
    assert timedelta(days=89) < desk_delta < timedelta(days=91)


def test_explicit_scopes_override_preset(service: PidgeService) -> None:
    owner = _setup_owner(service)
    minted = service.mint_agent_token(
        owner,
        label="Narrow",
        scopes=frozenset({"pidge:draft"}),
        preset="desk",
    )
    assert minted.token.scopes == frozenset({"pidge:draft"})


@pytest.mark.asyncio
async def test_agents_mint_form_posts_preset(app, service: PidgeService) -> None:
    owner = _setup_owner(service)

    async with TestClient(app) as client:
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

        agents = await client.get("/settings/agents", headers={"Cookie": session})
        assert agents.status == 200
        assert 'name="preset" value="desk"' in agents.text
        assert 'name="preset" value="draft"' in agents.text
        assert 'name="preset" value="confirm"' in agents.text
        assert 'name="preset" value="autopilot"' in agents.text
        assert "acknowledge_autopilot" in agents.text
        assert "coming soon" not in agents.text.lower()

        minted = await client.post(
            "/settings/agents",
            data={
                "_csrf_token": _csrf(agents),
                "action": "mint",
                "label": "Draft Bot",
                "preset": "draft",
            },
            headers={"Cookie": session},
        )
        assert minted.status == 200
        tokens = service.list_agent_tokens(owner)
        assert any(t.scopes == frozenset({"pidge:draft"}) for t in tokens)
        assert "Draft" in minted.text

        denied_auto = await client.post(
            "/settings/agents",
            data={
                "_csrf_token": _csrf(minted),
                "action": "mint",
                "label": "Danger Bot",
                "preset": "autopilot",
            },
            headers={"Cookie": session},
        )
        assert denied_auto.status == 200
        assert "acknowledge" in denied_auto.text.lower()
        assert not any(
            infer_preset(t.scopes) == "autopilot" for t in service.list_agent_tokens(owner)
        )

        auto = await client.post(
            "/settings/agents",
            data={
                "_csrf_token": _csrf(denied_auto),
                "action": "mint",
                "label": "Danger Bot",
                "preset": "autopilot",
                "acknowledge_autopilot": "1",
            },
            headers={"Cookie": session},
        )
        assert auto.status == 200
        assert any(
            infer_preset(t.scopes) == "autopilot" for t in service.list_agent_tokens(owner)
        )
        assert "never paste" in auto.text.lower()
        assert "badge autopilot" in auto.text or 'class="badge autopilot"' in auto.text


@pytest.mark.asyncio
async def test_seal_tool_listed_for_schema(app, service: PidgeService) -> None:
    owner = _setup_owner(service)
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
        assert "seal_pidge" in names
        assert "propose_seal" in names
