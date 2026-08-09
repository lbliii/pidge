"""Loft mail consent: introductions gate delivery; decline/block."""

from __future__ import annotations

import pytest
from chirp.testing import TestClient

from pidge.config import PidgeConfig
from pidge.services import PidgeService
from pidge.store import MemoryStore
from pidge.web import SESSION_COOKIE, create_app
from tests.helpers import connect_loft_mates


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
    match = __import__("re").search(
        r'name="_csrf_token" value="([^"]+)"', response.text or ""
    )
    assert match is not None
    return match.group(1)


def _setup_pair(service: PidgeService):
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


def test_directory_lists_unconnected_loft_mates(service: PidgeService) -> None:
    owner, lucy = _setup_pair(service)
    people = service.directory(owner)
    assert any(u.id == lucy.id for u in people)
    with pytest.raises(PermissionError, match="not connected"):
        service.draft_pidge(owner, intent="hi", recipient_names=["Lucy"])


def test_accepted_connection_enables_mail_both_ways(service: PidgeService) -> None:
    owner, lucy = _setup_pair(service)
    connect_loft_mates(service, owner, lucy)
    draft = service.draft_pidge(owner, intent="Coffee", recipient_names=["Lucy"])
    assert draft.state == "draft"
    reply = service.draft_pidge(lucy, intent="Sure", recipient_names=["Owner"])
    assert reply.state == "draft"


def test_pending_intro_does_not_enable_mail(service: PidgeService) -> None:
    owner, lucy = _setup_pair(service)
    service.request_loft_connection(owner, username="lucy")
    with pytest.raises(PermissionError, match="not connected"):
        service.draft_pidge(owner, intent="hi", recipient_names=["Lucy"])


def test_decline_allows_reintroduce(service: PidgeService) -> None:
    owner, lucy = _setup_pair(service)
    req = service.request_loft_connection(owner, username="lucy")
    service.decline_connection(lucy, req.id)
    with pytest.raises(PermissionError):
        service.draft_pidge(owner, intent="hi", recipient_names=["Lucy"])
    # Re-intro after decline is allowed.
    again = service.request_loft_connection(owner, username="lucy")
    assert again.status == "pending"
    service.accept_connection(lucy, again.id)
    draft = service.draft_pidge(owner, intent="hi", recipient_names=["Lucy"])
    assert draft.state == "draft"


def test_block_denies_mail_and_reintro(service: PidgeService) -> None:
    owner, lucy = _setup_pair(service)
    connect_loft_mates(service, owner, lucy)
    service.block_loft_user(lucy, username="owner")
    with pytest.raises(PermissionError):
        service.draft_pidge(owner, intent="spam", recipient_names=["Lucy"])
    with pytest.raises(PermissionError, match="blocked"):
        service.request_loft_connection(owner, username="lucy")
    # Blocker also cannot mail the blocked party via can_address.
    with pytest.raises(PermissionError):
        service.draft_pidge(lucy, intent="bye", recipient_names=["Owner"])


def test_unblock_restores_intro_path(service: PidgeService) -> None:
    owner, lucy = _setup_pair(service)
    service.block_loft_user(lucy, username="owner")
    service.unblock_loft_user(lucy, username="owner")
    req = service.request_loft_connection(owner, username="lucy")
    service.accept_connection(lucy, req.id)
    draft = service.draft_pidge(owner, intent="back", recipient_names=["Lucy"])
    assert draft.state == "draft"


@pytest.mark.asyncio
async def test_people_decline_and_block_ui(app, service: PidgeService) -> None:
    async with TestClient(app) as client:
        setup = await client.get("/setup")
        await client.post(
            "/setup",
            data={
                "_csrf_token": _csrf(setup),
                "bootstrap_token": "development-bootstrap-token",
                "loft_name": "Test Loft",
                "username": "owner",
                "display_name": "Owner",
                "password": "password-long",
            },
            headers={"Cookie": _cookie(setup, "chirp_session") or ""},
        )
        # Register Lucy via owner session then login as Lucy.
        owner_login = await client.get("/login")
        owner_resp = await client.post(
            "/login",
            data={
                "_csrf_token": _csrf(owner_login),
                "username": "owner",
                "password": "password-long",
            },
            headers={"Cookie": _cookie(owner_login, "chirp_session") or ""},
        )
        owner_cookie = _cookie(owner_resp, SESSION_COOKIE)
        chirp = _cookie(owner_resp, "chirp_session") or _cookie(owner_login, "chirp_session")
        owner_cookies = f"{chirp}; {owner_cookie}"

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
        assert "Visible in the loft" in people.text
        assert "Mail only after" in people.text

        intro = await client.post(
            "/directory/connect",
            data={"_csrf_token": _csrf(people), "username": "lucy"},
            headers={"Cookie": owner_cookies},
        )
        assert intro.status == 200

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
        lucy_cookies = f"{lucy_chirp}; {lucy_cookie}"

        lucy_people = await client.get("/people", headers={"Cookie": lucy_cookies})
        assert "Decline" in lucy_people.text
        assert "Block" in lucy_people.text
        req_id = service.store.list_connection_requests(
            service.store.get_user_by_username("lucy").id
        )[0].id

        declined = await client.post(
            "/directory/decline",
            data={"_csrf_token": _csrf(lucy_people), "request_id": str(req_id)},
            headers={"Cookie": lucy_cookies},
        )
        assert declined.status == 302
