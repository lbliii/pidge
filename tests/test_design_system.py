"""Design system: tokens + primitives adopted on desk surfaces."""

from __future__ import annotations

import re

import pytest
from chirp.testing import TestClient

from pidge.config import PidgeConfig
from pidge.store import MemoryStore
from pidge.web import SESSION_COOKIE, create_app


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


@pytest.mark.asyncio
async def test_people_address_book_uses_field_and_empty_state(app) -> None:
    async with TestClient(app) as client:
        cookies = await _setup_owner(client)
        page = await client.get("/people/address-book", headers={"Cookie": cookies})
        assert page.status == 200
        assert 'class="field"' in page.text
        assert 'class="empty-state"' in page.text
        assert 'aria-label="People facet"' in page.text
        assert 'href="/people"' in page.text
        assert 'style="color:#8b3a2a"' not in page.text


@pytest.mark.asyncio
async def test_login_uses_field_primitive(app) -> None:
    async with TestClient(app) as client:
        await _setup_owner(client)
        page = await client.get("/login")
        assert page.status == 200
        assert 'class="field"' in page.text
        assert 'class="btn btn-seal"' in page.text


@pytest.mark.asyncio
async def test_setup_uses_field_primitive(app) -> None:
    async with TestClient(app) as client:
        page = await client.get("/setup")
        assert page.status == 200
        assert 'class="field"' in page.text
        assert 'class="btn btn-seal"' in page.text


@pytest.mark.asyncio
async def test_agents_uses_preset_cards(app) -> None:
    async with TestClient(app) as client:
        cookies = await _setup_owner(client)
        page = await client.get("/settings/agents", headers={"Cookie": cookies})
        assert page.status == 200
        assert 'class="preset-grid"' in page.text
        assert "preset-card" in page.text
        assert 'class="btn btn-danger"' in page.text or "No tokens yet" in page.text


def _stylesheet_blocks() -> list[tuple[str, int]]:
    """Return (selector, brace_depth_before) for each rule opener in styles.css."""
    from pathlib import Path

    css = Path(__file__).resolve().parents[1] / "src" / "pidge" / "static" / "styles.css"
    text = css.read_text(encoding="utf-8")
    # Strip comments so nested braces inside them don't confuse the depth walk.
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    blocks: list[tuple[str, int]] = []
    depth = 0
    buf: list[str] = []
    for ch in text:
        if ch == "{":
            selector = "".join(buf).strip()
            blocks.append((selector, depth))
            depth += 1
            buf = []
        elif ch == "}":
            depth = max(0, depth - 1)
            buf = []
        else:
            buf.append(ch)
    assert depth == 0, "styles.css has unbalanced braces"
    return blocks


def test_styles_css_keeps_primitives_top_level() -> None:
    """A stray `.btn {` once nested `.segmented` and every rule after it."""
    blocks = _stylesheet_blocks()
    required = (".segmented", ".empty-state", ".person-row", ".object-row", ".field")
    found: dict[str, int] = {}
    for selector, depth in blocks:
        parts = [p.strip() for p in selector.split(",")]
        for name in required:
            if any(p == name or p.startswith(f"{name} ") or p.startswith(f"{name}:") for p in parts):
                found[name] = min(depth, found.get(name, depth))
    for name in required:
        assert name in found, f"{name} rule missing from styles.css"
        assert found[name] == 0, f"{name} must be top-level (depth 0), got {found[name]}"


@pytest.mark.asyncio
async def test_mail_segmented_facet_markup(app) -> None:
    async with TestClient(app) as client:
        cookies = await _setup_owner(client)
        inbox = await client.get("/inbox", headers={"Cookie": cookies})
        assert inbox.status == 200
        assert 'class="segmented"' in inbox.text
        assert 'aria-label="Mail facet"' in inbox.text
        assert 'href="/inbox"' in inbox.text
        assert 'href="/sent"' in inbox.text
        assert 'aria-current="page">In</a>' in inbox.text

        sent = await client.get("/sent", headers={"Cookie": cookies})
        assert sent.status == 200
        assert 'aria-current="page">Out</a>' in sent.text


@pytest.mark.asyncio
async def test_people_loft_hub_and_nav(app) -> None:
    async with TestClient(app) as client:
        cookies = await _setup_owner(client)
        page = await client.get("/people", headers={"Cookie": cookies})
        assert page.status == 200
        assert 'aria-label="People facet"' in page.text
        assert 'aria-current="page">In the loft</a>' in page.text
        assert "You’re the only one here" in page.text or "just you" in page.text
        assert "No introductions yet" in page.text
        assert 'href="/people"' in page.text
        assert 'aria-current="page">People</a>' in page.text
        assert 'href="/directory"' not in page.text  # Directory left Account menu


@pytest.mark.asyncio
async def test_legacy_people_routes_redirect(app) -> None:
    async with TestClient(app) as client:
        cookies = await _setup_owner(client)
        contacts = await client.get("/contacts", headers={"Cookie": cookies})
        assert contacts.status == 302
        assert _header(contacts, "location") == "/people/address-book"
        directory = await client.get("/directory", headers={"Cookie": cookies})
        assert directory.status == 302
        assert _header(directory, "location") == "/people"


def _header(response, name: str) -> str | None:
    needle = name.lower()
    for header, value in response.headers:
        if header.lower() == needle:
            return value
    return None
