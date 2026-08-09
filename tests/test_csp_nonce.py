"""CSP contract: one policy header, nonced inline scripts, no 'unsafe-inline'."""

from __future__ import annotations

import re

import pytest
from chirp.testing import TestClient

from pidge.config import PidgeConfig
from pidge.store import MemoryStore
from pidge.web import SESSION_COOKIE, create_app

pytestmark = pytest.mark.asyncio

INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)([^>]*)>", re.IGNORECASE)


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
def app(config: PidgeConfig):
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


def _csp_headers(response) -> list[str]:
    return [v for name, v in response.headers if name.lower() == "content-security-policy"]


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
    updated_chirp = _cookie(response, "chirp_session") or chirp_cookie
    assert pidge_cookie is not None
    return f"{updated_chirp}; {pidge_cookie}"


async def test_desk_pages_send_exactly_one_csp_header(app) -> None:
    async with TestClient(app) as client:
        cookies = await _setup_owner(client)
        for path in ("/", "/inbox", "/sent", "/compose"):
            response = await client.get(path, headers={"Cookie": cookies})
            assert response.status == 200
            assert len(_csp_headers(response)) == 1, path


async def test_injected_inline_scripts_carry_the_policy_nonce(app) -> None:
    async with TestClient(app) as client:
        cookies = await _setup_owner(client)
        for path in ("/inbox", "/sent"):
            response = await client.get(path, headers={"Cookie": cookies})
            policy = _csp_headers(response)[0]
            nonce = re.search(r"'nonce-([^']+)'", policy)
            assert nonce is not None, f"{path} policy has no nonce: {policy}"

            inline = INLINE_SCRIPT.findall(response.text)
            assert inline, f"{path} rendered no inline scripts to check"
            for attrs in inline:
                assert f'nonce="{nonce.group(1)}"' in attrs, f"{path} unnonced script: {attrs}"


async def test_script_src_stays_strict(app) -> None:
    async with TestClient(app) as client:
        cookies = await _setup_owner(client)
        response = await client.get("/inbox", headers={"Cookie": cookies})
        policy = _csp_headers(response)[0]
        script_src = next(
            part.strip() for part in policy.split(";") if part.strip().startswith("script-src")
        )
        assert "'unsafe-inline'" not in script_src
        assert "'unsafe-eval'" not in script_src
        assert "https://cdn.jsdelivr.net" in script_src
        # Google Fonts still reachable for stylesheet + font files.
        assert "https://fonts.googleapis.com" in policy
        assert "https://fonts.gstatic.com" in policy
