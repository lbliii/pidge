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
from tests.helpers import connect_loft_mates

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
        assert 'class="hero' in desk.text
        assert "floating-seal" in desk.text
        assert "What needs" in desk.text
        assert 'class="blotter"' in desk.text
        assert "Needs you" in desk.text
        assert "pillars-4" not in desk.text
        assert "Nothing needs you" in desk.text
        assert 'href="/compose"' in desk.text
        assert 'href="/settings/agents"' in desk.text
        assert 'class="dictate"' not in desk.text
        assert "<textarea" not in desk.text


async def test_desk_blotter_ready_to_seal_and_needs_act(app, service: PidgeService) -> None:
    async with TestClient(app) as client:
        cookies = await _setup_owner(client)
        register = await client.get("/register", headers={"Cookie": cookies})
        await client.post(
            "/register",
            data={
                "_csrf_token": _csrf(register),
                "username": "lucy",
                "display_name": "Lucy",
                "password": "password-long",
            },
            headers={"Cookie": cookies},
        )

    owner = service.store.get_user_by_username("owner")
    lucy = service.store.get_user_by_username("lucy")
    connect_loft_mates(service, owner, lucy)
    draft = service.draft_pidge(
        owner,
        intent="Tonight at Nowadays with Lucy",
        recipient_names=["Lucy"],
    )
    service.enrich_pidge(
        owner,
        draft.id,
        who="Lucy",
        when="tonight · 7:00 PM",
        where="Nowadays, Brooklyn",
    )
    sealed = service.seal_pidge(owner, draft.id)

    ready = service.draft_pidge(
        owner,
        intent="Coffee with Lucy",
        recipient_names=["Lucy"],
    )
    service.enrich_pidge(
        owner,
        ready.id,
        who="Lucy",
        when="tomorrow · 10:00 AM",
        where="Cafe",
    )
    pending = service.draft_pidge(
        owner,
        intent="Brunch with Sam",
        recipient_names=["Lucy"],
    )

    async with TestClient(app) as client:
        login = await client.get("/login")
        owner_login = await client.post(
            "/login",
            data={
                "_csrf_token": _csrf(login),
                "username": "owner",
                "password": "password-long",
            },
            headers={"Cookie": _cookie(login, "chirp_session") or ""},
        )
        owner_cookie = _cookie(owner_login, SESSION_COOKIE)
        chirp = _cookie(owner_login, "chirp_session") or _cookie(login, "chirp_session")
        assert owner_cookie is not None
        owner_cookies = f"{chirp}; {owner_cookie}"

        desk = await client.get("/", headers={"Cookie": owner_cookies})
        assert desk.status == 200
        assert "Ready to seal" in desk.text
        assert f'href="/compose/{ready.id}"' in desk.text
        assert "Brunch with Sam" in desk.text or "Brunch" in desk.text
        assert "Enriching" in desk.text
        assert f'href="/compose/{pending.id}"' in desk.text
        assert "Coming up" in desk.text
        assert "Nowadays" in desk.text
        assert "pillars-4" not in desk.text

        lucy_login_page = await client.get("/login")
        lucy_resp = await client.post(
            "/login",
            data={
                "_csrf_token": _csrf(lucy_login_page),
                "username": "lucy",
                "password": "password-long",
            },
            headers={"Cookie": _cookie(lucy_login_page, "chirp_session") or ""},
        )
        lucy_cookie = _cookie(lucy_resp, SESSION_COOKIE)
        lucy_chirp = _cookie(lucy_resp, "chirp_session") or _cookie(
            lucy_login_page, "chirp_session"
        )
        assert lucy_cookie is not None
        lucy_cookies = f"{lucy_chirp}; {lucy_cookie}"

        lucy_desk = await client.get("/", headers={"Cookie": lucy_cookies})
        assert lucy_desk.status == 200
        assert "needs act" in lucy_desk.text
        assert f'href="/p/{sealed.id}"' in lucy_desk.text


async def test_mail_stance_badges_and_delivery_ceremony(app, service: PidgeService) -> None:
    async with TestClient(app) as client:
        cookies = await _setup_owner(client)
        register = await client.get("/register", headers={"Cookie": cookies})
        await client.post(
            "/register",
            data={
                "_csrf_token": _csrf(register),
                "username": "lucy",
                "display_name": "Lucy",
                "password": "password-long",
            },
            headers={"Cookie": cookies},
        )

    owner = service.store.get_user_by_username("owner")
    lucy = service.store.get_user_by_username("lucy")
    connect_loft_mates(service, owner, lucy)
    draft = service.draft_pidge(
        owner, intent="Tonight at Nowadays", recipient_names=["Lucy"]
    )
    service.enrich_pidge(
        owner,
        draft.id,
        who="Lucy",
        when="tonight · 7:00 PM",
        where="Nowadays",
    )
    sealed = service.seal_pidge(owner, draft.id)

    async with TestClient(app) as client:
        login = await client.get("/login")
        owner_login = await client.post(
            "/login",
            data={
                "_csrf_token": _csrf(login),
                "username": "owner",
                "password": "password-long",
            },
            headers={"Cookie": _cookie(login, "chirp_session") or ""},
        )
        owner_cookie = _cookie(owner_login, SESSION_COOKIE)
        chirp = _cookie(owner_login, "chirp_session") or _cookie(login, "chirp_session")
        assert owner_cookie is not None
        owner_cookies = f"{chirp}; {owner_cookie}"

        out = await client.get("/sent", headers={"Cookie": owner_cookies})
        assert out.status == 200
        assert "· sealed" in out.text
        delivery = await client.get(f"/sent/{sealed.id}", headers={"Cookie": owner_cookies})
        assert delivery.status == 200
        assert "Sealed · delivered" in delivery.text
        assert "Lucy" in delivery.text
        assert "Open thread" in delivery.text

        lucy_login = await client.get("/login")
        lucy_resp = await client.post(
            "/login",
            data={
                "_csrf_token": _csrf(lucy_login),
                "username": "lucy",
                "password": "password-long",
            },
            headers={"Cookie": _cookie(lucy_login, "chirp_session") or ""},
        )
        lucy_cookie = _cookie(lucy_resp, SESSION_COOKIE)
        lucy_chirp = _cookie(lucy_resp, "chirp_session") or _cookie(lucy_login, "chirp_session")
        assert lucy_cookie is not None
        lucy_cookies = f"{lucy_chirp}; {lucy_cookie}"

        inbox = await client.get("/inbox", headers={"Cookie": lucy_cookies})
        assert inbox.status == 200
        assert "needs act" in inbox.text

        service.record_act(service.store.get_user_by_username("lucy"), sealed.id, "rsvp_yes")
        inbox2 = await client.get("/inbox", headers={"Cookie": lucy_cookies})
        assert "Result · accepted" in inbox2.text
        out2 = await client.get("/sent", headers={"Cookie": owner_cookies})
        assert "Result · accepted" in out2.text


async def test_compose_empty_agent_inbound(app) -> None:
    async with TestClient(app) as client:
        cookies = await _setup_owner(client)
        page = await client.get("/compose", headers={"Cookie": cookies})
        assert page.status == 200
        assert "Connect an agent" in page.text or "Waiting on your agent" in page.text
        assert "draft_pidge" in page.text
        assert "enrich_pidge" in page.text
        assert 'href="/settings/agents"' in page.text
        assert "Draft → enrich → seal" in page.text
        assert "<textarea" not in page.text
        assert "compose-box" not in page.text
        assert "Compatible harnesses" in page.text


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


async def test_people_hub_introduce_accept_and_address_book(app, service: PidgeService) -> None:
    async with TestClient(app) as client:
        owner_cookies = await _setup_owner(client)
        register = await client.get("/register", headers={"Cookie": owner_cookies})
        await client.post(
            "/register",
            data={
                "_csrf_token": _csrf(register),
                "username": "lucy",
                "display_name": "Lucy",
                "password": "password-long",
            },
            headers={"Cookie": owner_cookies},
        )

        people = await client.get("/people", headers={"Cookie": owner_cookies})
        assert people.status == 200
        assert "Lucy" in people.text
        assert "@lucy" in people.text
        assert "from_user_id" not in people.text
        assert "#1" not in people.text or "Introduce" in people.text

        intro = await client.post(
            "/directory/connect",
            data={"_csrf_token": _csrf(people), "username": "lucy"},
            headers={"Cookie": owner_cookies},
        )
        assert intro.status == 200
        assert "Introduction sent" in intro.text or "Introduction to Lucy" in intro.text
        assert "Lucy" in intro.text
        assert "from 1 →" not in intro.text

        # Log in as Lucy and accept.
        login = await client.get("/login")
        lucy_resp = await client.post(
            "/login",
            data={
                "_csrf_token": _csrf(login),
                "username": "lucy",
                "password": "password-long",
            },
            headers={"Cookie": _cookie(login, "chirp_session") or ""},
        )
        lucy_cookie = _cookie(lucy_resp, SESSION_COOKIE)
        chirp = _cookie(lucy_resp, "chirp_session") or _cookie(login, "chirp_session")
        assert lucy_cookie is not None
        lucy_cookies = f"{chirp}; {lucy_cookie}"

        lucy_people = await client.get("/people", headers={"Cookie": lucy_cookies})
        assert lucy_people.status == 200
        assert "Owner wants to connect" in lucy_people.text
        assert "Accept" in lucy_people.text

        accept = await client.post(
            "/directory/accept",
            data={
                "_csrf_token": _csrf(lucy_people),
                "request_id": str(service.store.list_connection_requests(
                    service.store.get_user_by_username("lucy").id
                )[0].id),
            },
            headers={"Cookie": lucy_cookies},
        )
        assert accept.status == 302
        assert any(
            h.lower() == "location" and v == "/people" for h, v in accept.headers
        )

        book = await client.get("/people/address-book", headers={"Cookie": owner_cookies})
        assert book.status == 200
        assert "Add an address" in book.text
        assert "Empty book" in book.text

        added = await client.post(
            "/contacts/add",
            data={
                "_csrf_token": _csrf(book),
                "handle": "maya@garden",
                "display_name": "Maya",
            },
            headers={"Cookie": owner_cookies},
        )
        assert added.status == 200
        assert "Maya" in added.text
        assert "maya@garden" in added.text
        assert "Pending" in added.text


async def test_directory_accept_failure_surfaces_alert(app, service: PidgeService) -> None:
    """#99: failed accept re-renders people with an alert, not a silent redirect."""
    async with TestClient(app) as client:
        owner_cookies = await _setup_owner(client)
        register = await client.get("/register", headers={"Cookie": owner_cookies})
        await client.post(
            "/register",
            data={
                "_csrf_token": _csrf(register),
                "username": "lucy",
                "display_name": "Lucy",
                "password": "password-long",
            },
            headers={"Cookie": owner_cookies},
        )
        people = await client.get("/people", headers={"Cookie": owner_cookies})
        await client.post(
            "/directory/connect",
            data={"_csrf_token": _csrf(people), "username": "lucy"},
            headers={"Cookie": owner_cookies},
        )
        lucy = service.store.get_user_by_username("lucy")
        request_id = service.store.list_connection_requests(lucy.id)[0].id

        # Sender cannot accept; must surface the PermissionError.
        failed = await client.post(
            "/directory/accept",
            data={"_csrf_token": _csrf(people), "request_id": str(request_id)},
            headers={"Cookie": owner_cookies},
        )
        assert failed.status == 200
        assert 'class="alert alert-danger"' in failed.text
        assert "Cannot accept this connection request." in failed.text
        assert service.store.list_connection_requests(lucy.id)[0].status == "pending"


async def test_wall_pin_failure_surfaces_alert(app, service: PidgeService) -> None:
    """#99: failed pin re-renders wall with an alert, not a silent redirect."""
    async with TestClient(app) as client:
        cookies = await _setup_owner(client)
        register = await client.get("/register", headers={"Cookie": cookies})
        await client.post(
            "/register",
            data={
                "_csrf_token": _csrf(register),
                "username": "lucy",
                "display_name": "Lucy",
                "password": "password-long",
            },
            headers={"Cookie": cookies},
        )
        owner = service.store.get_user_by_username("owner")
        draft = service.draft_pidge(
            owner, intent="Draft that must not pin", recipient_names=["Lucy"]
        )

        wall = await client.get("/wall", headers={"Cookie": cookies})
        assert wall.status == 200
        failed = await client.post(
            "/wall/pin",
            data={"_csrf_token": _csrf(wall), "pidge_id": str(draft.id)},
            headers={"Cookie": cookies},
        )
        assert failed.status == 200
        assert 'class="alert alert-danger"' in failed.text
        assert "Only sealed Pidges can be pinned." in failed.text
        assert service.store.list_pins(owner.id) == ()


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
    connect_loft_mates(service, owner, lucy)

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
    lucy = service.store.get_user_by_username("lucy")
    connect_loft_mates(service, owner, lucy)
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
        assert "seal_pidge" in names  # listed for schema; runtime scope-gated

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
    lucy = service.register(username="lucy", display_name="Lucy", password="password-long").user
    connect_loft_mates(service, owner, lucy)
    draft = service.draft_pidge(owner, intent="soon", recipient_names=["Lucy"])
    with pytest.raises(ValueError, match="Slot"):
        service.seal_pidge(owner, draft.id)


async def test_author_can_discard_draft(service: PidgeService) -> None:
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
    connect_loft_mates(service, owner, lucy)
    draft = service.draft_pidge(owner, intent="scratch idea", recipient_names=["Lucy"])
    discarded = service.discard_pidge(owner, draft.id)
    assert discarded.state == "revoked"
    assert service.store.list_drafts(owner.id) == ()
    assert service.store.list_inbox(lucy.id) == ()
    assert service.store.list_sent(owner.id) == ()


async def test_non_author_cannot_discard_draft(service: PidgeService) -> None:
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
    connect_loft_mates(service, owner, lucy)
    draft = service.draft_pidge(owner, intent="private draft", recipient_names=["Lucy"])
    with pytest.raises(PermissionError, match="author"):
        service.discard_pidge(lucy, draft.id)
    assert service.store.get_pidge(draft.id).state == "draft"
    assert len(service.store.list_drafts(owner.id)) == 1


async def test_cannot_discard_sealed_pidge(service: PidgeService) -> None:
    owner = service.setup(
        bootstrap_token="development-bootstrap-token",
        loft_name="Test Loft",
        username="owner",
        display_name="Owner",
        password="password-long",
    ).user
    lucy = service.register(username="lucy", display_name="Lucy", password="password-long").user
    connect_loft_mates(service, owner, lucy)
    draft = service.draft_pidge(owner, intent="meet", recipient_names=["Lucy"])
    service.enrich_pidge(
        owner,
        draft.id,
        who="Lucy",
        when="tonight",
        where="Nowadays",
    )
    sealed = service.seal_pidge(owner, draft.id)
    with pytest.raises(PermissionError, match="drafts"):
        service.discard_pidge(owner, sealed.id)
    assert service.store.get_pidge(sealed.id).state == "sealed"


async def test_discard_draft_via_compose_and_mcp(app, service: PidgeService) -> None:
    owner = service.setup(
        bootstrap_token="development-bootstrap-token",
        loft_name="Test Loft",
        username="owner",
        display_name="Owner",
        password="password-long",
    ).user
    lucy = service.register(username="lucy", display_name="Lucy", password="password-long").user
    connect_loft_mates(service, owner, lucy)
    draft = service.draft_pidge(owner, intent="throw away", recipient_names=["Lucy"])
    other = service.draft_pidge(owner, intent="keep for mcp", recipient_names=["Lucy"])
    minted = service.mint_agent_token(owner, label="Secretary")

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
        cookies = f"{updated_chirp}; {pidge_cookie}"

        compose = await client.get(f"/compose/{draft.id}", headers={"Cookie": cookies})
        assert compose.status == 200
        assert "Discard draft" in compose.text
        discarded = await client.post(
            f"/compose/{draft.id}/discard",
            data={"_csrf_token": _csrf(compose)},
            headers={"Cookie": cookies},
        )
        assert discarded.status == 302
        location = next(
            (v for h, v in discarded.headers if h.lower() == "location"),
            "",
        )
        assert location == "/compose"
        assert service.store.get_pidge(draft.id).state == "revoked"
        assert all(m.id != draft.id for m in service.store.list_drafts(owner.id))

        desk = await client.get("/", headers={"Cookie": cookies})
        assert desk.status == 200
        assert "throw away" not in desk.text

        listed = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1, "params": {}},
            headers={"Authorization": f"Bearer {minted.secret}"},
        )
        names = {t["name"] for t in json.loads(listed.text)["result"]["tools"]}
        assert "discard_pidge" in names

        via_mcp = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "id": 2,
                "params": {
                    "name": "discard_pidge",
                    "arguments": {"pidge_id": other.id},
                },
            },
            headers={"Authorization": f"Bearer {minted.secret}"},
        )
        assert via_mcp.status == 200
        body = json.loads(via_mcp.text)
        assert "result" in body
        assert service.store.get_pidge(other.id).state == "revoked"
        assert service.store.list_drafts(owner.id) == ()


def _seal_ready(service: PidgeService, owner, intent: str = "meet") -> object:
    draft = service.draft_pidge(owner, intent=intent, recipient_names=["Lucy"])
    return service.seal_pidge(
        owner,
        service.enrich_pidge(
            owner,
            draft.id,
            who="Lucy",
            when="tonight",
            where="Nowadays",
        ).id,
    )


async def test_author_can_revoke_sealed_pidge(service: PidgeService) -> None:
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
    connect_loft_mates(service, owner, lucy)
    sealed = _seal_ready(service, owner, intent="cancel later")
    digest = sealed.content_hash
    assert digest
    assert sealed.id in {m.id for m in service.store.list_inbox(lucy.id)}
    assert sealed.id in {m.id for m in service.store.list_sent(owner.id)}

    revoked = service.revoke_sealed_pidge(owner, sealed.id)
    assert revoked.state == "revoked"
    assert revoked.content_hash == digest
    assert service.store.list_inbox(lucy.id) == ()
    assert service.store.list_sent(owner.id) == ()
    still = service.store.get_pidge(sealed.id)
    assert still.state == "revoked"
    assert still.content_hash == digest


async def test_non_author_cannot_revoke_sealed(service: PidgeService) -> None:
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
    connect_loft_mates(service, owner, lucy)
    sealed = _seal_ready(service, owner)
    with pytest.raises(PermissionError, match="author"):
        service.revoke_sealed_pidge(lucy, sealed.id)
    assert service.store.get_pidge(sealed.id).state == "sealed"


async def test_cannot_revoke_draft_via_sealed_path(service: PidgeService) -> None:
    owner = service.setup(
        bootstrap_token="development-bootstrap-token",
        loft_name="Test Loft",
        username="owner",
        display_name="Owner",
        password="password-long",
    ).user
    lucy = service.register(username="lucy", display_name="Lucy", password="password-long").user
    connect_loft_mates(service, owner, lucy)
    draft = service.draft_pidge(owner, intent="not sealed", recipient_names=["Lucy"])
    with pytest.raises(PermissionError, match="sealed"):
        service.revoke_sealed_pidge(owner, draft.id)
    assert service.store.get_pidge(draft.id).state == "draft"


async def test_supersede_creates_linked_draft(service: PidgeService) -> None:
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
    connect_loft_mates(service, owner, lucy)
    sealed = _seal_ready(service, owner, intent="original plan")
    digest = sealed.content_hash
    draft = service.supersede_pidge(owner, sealed.id)
    prior = service.store.get_pidge(sealed.id)
    assert prior.state == "superseded"
    assert prior.content_hash == digest
    assert draft.state == "draft"
    assert draft.supersedes_id == sealed.id
    assert draft.intent == sealed.intent
    assert draft.id != sealed.id
    assert service.store.list_inbox(lucy.id) == ()
    assert service.store.list_sent(owner.id) == ()
    assert draft.id in {m.id for m in service.store.list_drafts(owner.id)}
    recipients = service.store.recipients_for(draft.id)
    assert any(r.loft_user_id == lucy.id for r in recipients)
    flight = service.store.get_flight_for_pidge(draft.id)
    assert flight is not None


async def test_agents_cannot_revoke_or_supersede_via_mcp(
    app, service: PidgeService
) -> None:
    owner = service.setup(
        bootstrap_token="development-bootstrap-token",
        loft_name="Test Loft",
        username="owner",
        display_name="Owner",
        password="password-long",
    ).user
    lucy = service.register(username="lucy", display_name="Lucy", password="password-long").user
    connect_loft_mates(service, owner, lucy)
    sealed = _seal_ready(service, owner)
    minted = service.mint_agent_token(owner, label="Secretary")

    async with TestClient(app) as client:
        listed = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1, "params": {}},
            headers={"Authorization": f"Bearer {minted.secret}"},
        )
        names = {t["name"] for t in json.loads(listed.text)["result"]["tools"]}
        assert "revoke_sealed_pidge" not in names
        assert "revoke_pidge" not in names
        assert "supersede_pidge" not in names
        assert "discard_pidge" in names  # draft discard remains MCP-reachable

        for tool_name in ("revoke_sealed_pidge", "supersede_pidge", "revoke_pidge"):
            denied = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "id": 2,
                    "params": {
                        "name": tool_name,
                        "arguments": {"pidge_id": sealed.id},
                    },
                },
                headers={"Authorization": f"Bearer {minted.secret}"},
            )
            body = json.loads(denied.text)
            assert "error" in body or "error" in str(body.get("result", ""))

        assert service.store.get_pidge(sealed.id).state == "sealed"


async def test_revoke_and_supersede_via_thread_ui(app, service: PidgeService) -> None:
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
    connect_loft_mates(service, owner, lucy)
    sealed = _seal_ready(service, owner, intent="ui revoke")
    other = _seal_ready(service, owner, intent="ui supersede")
    digest = sealed.content_hash

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
        cookies = f"{updated_chirp}; {pidge_cookie}"

        thread = await client.get(f"/p/{sealed.id}", headers={"Cookie": cookies})
        assert thread.status == 200
        assert "Revoke" in thread.text
        assert "Supersede" in thread.text
        assert "Discard draft" not in thread.text

        revoked = await client.post(
            f"/p/{sealed.id}/revoke",
            data={"_csrf_token": _csrf(thread)},
            headers={"Cookie": cookies},
        )
        assert revoked.status == 302
        assert service.store.get_pidge(sealed.id).state == "revoked"
        assert service.store.get_pidge(sealed.id).content_hash == digest
        assert sealed.id not in {m.id for m in service.store.list_inbox(lucy.id)}
        assert sealed.id not in {m.id for m in service.store.list_sent(owner.id)}

        after = await client.get(f"/p/{sealed.id}", headers={"Cookie": cookies})
        assert after.status == 200
        assert "revoked" in after.text.lower()

        other_thread = await client.get(f"/p/{other.id}", headers={"Cookie": cookies})
        assert other_thread.status == 200
        superseded = await client.post(
            f"/p/{other.id}/supersede",
            data={"_csrf_token": _csrf(other_thread)},
            headers={"Cookie": cookies},
        )
        assert superseded.status == 302
        location = next(
            (v for h, v in superseded.headers if h.lower() == "location"),
            "",
        )
        assert location.startswith("/compose/")
        draft_id = int(location.rsplit("/", 1)[-1])
        assert service.store.get_pidge(other.id).state == "superseded"
        draft = service.store.get_pidge(draft_id)
        assert draft.state == "draft"
        assert draft.supersedes_id == other.id
        compose = await client.get(location, headers={"Cookie": cookies})
        assert compose.status == 200
        assert f"#{other.id}" in compose.text


async def test_ready_endpoint(app) -> None:
    async with TestClient(app) as client:
        response = await client.get("/ready")
        assert response.status == 200
        assert "ready" in response.text
