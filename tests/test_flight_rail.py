"""Compose flight-rail SSE wiring."""

from __future__ import annotations

import json
import re

import pytest
from chirp.testing import TestClient
from chirp.testing.sse import extract_sse_attrs
from chirp.tools.events import ToolCallEvent

from pidge.config import PidgeConfig
from pidge.services import PidgeService
from pidge.store import MemoryStore
from pidge.web import (
    SESSION_COOKIE,
    _tool_event_touches_draft,
    create_app,
)


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


def test_tool_event_filter_matches_enrich_args() -> None:
    event = ToolCallEvent(
        tool_name="enrich_pidge",
        arguments={"pidge_id": 7, "who": "Lucy"},
        result={"id": 7},
        timestamp=0.0,
    )
    assert _tool_event_touches_draft(event, 7)
    assert not _tool_event_touches_draft(event, 8)


@pytest.mark.asyncio
async def test_compose_page_wires_sse_without_self_swap(
    app, service: PidgeService
) -> None:
    async with TestClient(app) as client:
        cookies = await _setup_owner(client)
        owner = service.store.get_user_by_username("owner")
        assert owner is not None
        service.register(username="lucy", display_name="Lucy", password="password-long")
        draft = service.draft_pidge(owner, intent="Meet Lucy", recipient_names=["Lucy"])

        page = await client.get(f"/compose/{draft.id}", headers={"Cookie": cookies})
        assert page.status == 200
        assert f'sse-connect="/compose/{draft.id}/flight"' in page.text
        assert 'sse-swap="flight_rail"' in page.text
        assert 'sse-swap="compose_live"' in page.text
        assert "hx-disinherit" in page.text
        assert "Seal blocked" in page.text
        assert "disabled" in page.text

        connects, swaps = extract_sse_attrs(page.text)
        assert any(f"/compose/{draft.id}/flight" in url for url in connects)
        assert "flight_rail" in swaps
        assert "compose_live" in swaps

        # sse-swap must not sit on the same element as sse-connect (Chirp ERROR).
        for chunk in page.text.split("sse-connect=")[1:]:
            tag = chunk.split(">", 1)[0]
            assert "sse-swap" not in tag

        stream = await client.sse(
            f"/compose/{draft.id}/flight",
            headers={"Cookie": cookies},
            max_events=2,
        )
        assert stream.status == 200
        emitted = {evt.event or "message" for evt in stream.events}
        assert "flight_rail" in emitted
        assert "compose_live" in emitted
        assert any("Flight" in evt.data for evt in stream.events)
        assert any("slot-list" in evt.data for evt in stream.events)


@pytest.mark.asyncio
async def test_compose_live_updates_after_enrich(app, service: PidgeService) -> None:
    async with TestClient(app) as client:
        cookies = await _setup_owner(client)
        owner = service.store.get_user_by_username("owner")
        assert owner is not None
        service.register(username="lucy", display_name="Lucy", password="password-long")
        draft = service.draft_pidge(
            owner, intent="Meet Lucy tonight", recipient_names=["Lucy"]
        )
        minted = service.mint_agent_token(owner, label="Secretary")

        before = await client.get(f"/compose/{draft.id}", headers={"Cookie": cookies})
        assert "Seal blocked" in before.text
        assert "waiting" in before.text

        enriched = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "id": 1,
                "params": {
                    "name": "enrich_pidge",
                    "arguments": {
                        "pidge_id": draft.id,
                        "who": "Lucy",
                        "when": "tonight · 7:00 PM",
                        "where": "Nowadays",
                    },
                },
            },
            headers={"Authorization": f"Bearer {minted.secret}"},
        )
        assert enriched.status == 200
        body = json.loads(enriched.text)
        assert "result" in body

        after = await client.get(f"/compose/{draft.id}", headers={"Cookie": cookies})
        assert after.status == 200
        assert "Slots ready" in after.text
        assert 'type="submit"' in after.text
        assert "Seal blocked" not in after.text

        flight = service.store.get_flight_for_pidge(draft.id)
        assert flight is not None
        assert flight.state == "done"
        steps = service.store.list_flight_steps(flight.id)
        assert any(s.state == "done" and s.key == "who" for s in steps)
