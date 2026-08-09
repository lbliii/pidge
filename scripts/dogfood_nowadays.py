#!/usr/bin/env python3
"""Tonight at Nowadays — end-to-end dogfood path.

Default (no network): MemoryStore + Chirp TestClient.

    uv run python scripts/dogfood_nowadays.py
    make dogfood

Against a running loft (local serve or Railway):

    uv run python scripts/dogfood_nowadays.py \\
      --base-url https://pidge.lol \\
      --bootstrap-token \"$PIDGE_BOOTSTRAP_TOKEN\" \\
      --owner-password '…' --lucy-password '…'

If the loft is already claimed, pass existing credentials; the script logs in
instead of calling /setup. Register Lucy when she is missing.

Agent MCP curl recipe (mint a token under Settings → Agents first)::

    BASE=https://pidge.lol   # or http://127.0.0.1:8000
    TOKEN=pidge_at_…

    curl -sS \"$BASE/mcp\" -H \"Authorization: Bearer $TOKEN\" \\
      -H 'Content-Type: application/json' \\
      -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\",\"params\":{}}'

    curl -sS \"$BASE/mcp\" -H \"Authorization: Bearer $TOKEN\" \\
      -H 'Content-Type: application/json' \\
      -d '{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{
            \"name\":\"draft_pidge\",
            \"arguments\":{
              \"intent\":\"Tell Lucy we are meeting tonight at 7 at Nowadays\",
              \"recipients\":[\"Lucy\"],
              \"summary\":\"Tonight at Nowadays\"
            }}}'

    curl -sS \"$BASE/mcp\" -H \"Authorization: Bearer $TOKEN\" \\
      -H 'Content-Type: application/json' \\
      -d '{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/call\",\"params\":{
            \"name\":\"enrich_pidge\",
            \"arguments\":{
              \"pidge_id\":1,
              \"who\":\"Lucy\",
              \"when\":\"tonight · 7:00 PM\",
              \"where\":\"Nowadays, Brooklyn\",
              \"extras\":{\"menu\":\"kitchen + wine\"}
            }}}'

Humans seal in the UI by default; Autopilot tokens with pidge:seal may seal over MCP. Lucy RSVPs from her inbox thread.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

from pidge.config import PidgeConfig
from pidge.services import PidgeService
from pidge.store import MemoryStore
from pidge.web import SESSION_COOKIE, create_app

INTENT = "Tell Lucy we're meeting tonight at 7 at Nowadays"
SUMMARY = "Tonight at Nowadays"
WHO = "Lucy"
WHEN = "tonight · 7:00 PM"
WHERE = "Nowadays, Brooklyn"
EXTRAS = {"menu": "kitchen + wine"}
OWNER_USER = "owner"
OWNER_DISPLAY = "Owner"
LUCY_USER = "lucy"
LUCY_DISPLAY = "Lucy"
DEFAULT_PASSWORD = "password-long"
BOOTSTRAP = "development-bootstrap-token"


@dataclass
class DogfoodResult:
    pidge_id: int
    agent_token_prefix: str
    hold_state: str
    pin_count: int
    act_kinds: tuple[str, ...]


def _csrf(html: str) -> str:
    match = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
    if match is None:
        match = re.search(r'name="_csrf_token"[^>]*value="([^"]+)"', html)
    if match is None:
        raise RuntimeError("CSRF token not found in page HTML")
    return match.group(1)


def _set_cookie(headers: Any, name: str) -> str | None:
    items = headers.items() if hasattr(headers, "items") else headers
    for header, value in items:
        if str(header).lower() == "set-cookie" and str(value).startswith(f"{name}="):
            return str(value).split(";", 1)[0]
    return None


def _merge(*parts: str | None) -> str:
    return "; ".join(p for p in parts if p)


def _header(headers: Any, name: str) -> str | None:
    needle = name.lower()
    items = headers.items() if hasattr(headers, "items") else headers
    for header, value in items:
        if str(header).lower() == needle:
            return str(value)
    return None


def _mcp_payload(body: dict[str, Any]) -> dict[str, Any]:
    if "error" in body:
        raise RuntimeError(f"MCP error: {body['error']}")
    text = body["result"]["content"][0]["text"]
    return json.loads(text)


async def _run_in_process(*, password: str, bootstrap: str) -> DogfoodResult:
    from chirp.testing import TestClient

    store = MemoryStore()
    config = PidgeConfig(
        env="development",
        debug=True,
        database_url=None,
        secret_key="dogfood-secret-key-" + ("x" * 32),
        bootstrap_token=bootstrap,
        public_origin=None,
        loft_name="Nowadays Loft",
    )
    app = create_app(debug=True, store=store, pidge_config=config)
    service = PidgeService(store, config)

    async with TestClient(app) as client:
        setup_page = await client.get("/setup")
        chirp = _set_cookie(setup_page.headers, "chirp_session")
        if not chirp:
            raise RuntimeError("missing chirp_session cookie on /setup")
        setup = await client.post(
            "/setup",
            data={
                "_csrf_token": _csrf(setup_page.text),
                "bootstrap_token": bootstrap,
                "loft_name": "Nowadays Loft",
                "username": OWNER_USER,
                "display_name": OWNER_DISPLAY,
                "password": password,
            },
            headers={"Cookie": chirp},
        )
        if setup.status != 302:
            raise RuntimeError(f"setup failed: {setup.status}")
        owner_cookies = _merge(
            _set_cookie(setup.headers, "chirp_session") or chirp,
            _set_cookie(setup.headers, SESSION_COOKIE),
        )

        reg_page = await client.get("/register")
        chirp = _set_cookie(reg_page.headers, "chirp_session") or chirp
        reg = await client.post(
            "/register",
            data={
                "_csrf_token": _csrf(reg_page.text),
                "username": LUCY_USER,
                "display_name": LUCY_DISPLAY,
                "password": password,
            },
            headers={"Cookie": chirp},
        )
        if reg.status != 302:
            raise RuntimeError(f"Lucy register failed: {reg.status}")
        lucy_cookies = _merge(
            _set_cookie(reg.headers, "chirp_session") or chirp,
            _set_cookie(reg.headers, SESSION_COOKIE),
        )

        # Owner session was replaced by Lucy's registration — log owner back in.
        login_page = await client.get("/login")
        chirp = _set_cookie(login_page.headers, "chirp_session")
        if not chirp:
            raise RuntimeError("missing chirp_session cookie on /login")
        login = await client.post(
            "/login",
            data={
                "_csrf_token": _csrf(login_page.text),
                "username": OWNER_USER,
                "password": password,
            },
            headers={"Cookie": chirp},
        )
        if login.status != 302:
            raise RuntimeError(f"owner login failed: {login.status}")
        owner_cookies = _merge(
            _set_cookie(login.headers, "chirp_session") or chirp,
            _set_cookie(login.headers, SESSION_COOKIE),
        )

        owner = service.store.get_user_by_username(OWNER_USER)
        minted = service.mint_agent_token(owner, label="Nowadays Secretary")

        drafted = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "draft_pidge",
                    "arguments": {
                        "intent": INTENT,
                        "recipients": [LUCY_DISPLAY],
                        "summary": SUMMARY,
                    },
                },
            },
            headers={"Authorization": f"Bearer {minted.secret}"},
        )
        draft = _mcp_payload(json.loads(drafted.text))
        pidge_id = int(draft["id"])

        enriched = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "enrich_pidge",
                    "arguments": {
                        "pidge_id": pidge_id,
                        "who": WHO,
                        "when": WHEN,
                        "where": WHERE,
                        "extras": EXTRAS,
                    },
                },
            },
            headers={"Authorization": f"Bearer {minted.secret}"},
        )
        slots = _mcp_payload(json.loads(enriched.text))["slots"]
        if slots.get("where", {}).get("status") != "ready":
            raise RuntimeError(f"enrich incomplete: {slots}")

        compose = await client.get(f"/compose/{pidge_id}", headers={"Cookie": owner_cookies})
        seal = await client.post(
            f"/compose/{pidge_id}/seal",
            data={"_csrf_token": _csrf(compose.text)},
            headers={"Cookie": owner_cookies},
        )
        if seal.status != 302:
            raise RuntimeError(f"seal failed: {seal.status} {_header(seal.headers, 'location')}")

        inbox = await client.get("/inbox", headers={"Cookie": lucy_cookies})
        if f"/p/{pidge_id}" not in inbox.text:
            raise RuntimeError("sealed invite missing from Lucy inbox HTML")

        lucy = service.store.get_user_by_username(LUCY_USER)
        if not any(m.id == pidge_id for m in service.store.list_inbox(lucy.id)):
            raise RuntimeError("sealed invite missing from Lucy store inbox")

        thread = await client.get(f"/p/{pidge_id}", headers={"Cookie": lucy_cookies})
        rsvp = await client.post(
            f"/p/{pidge_id}/act",
            data={"_csrf_token": _csrf(thread.text), "kind": "rsvp_yes"},
            headers={"Cookie": lucy_cookies},
        )
        if rsvp.status != 302:
            raise RuntimeError(f"RSVP failed: {rsvp.status}")

        pin_page = await client.get(f"/p/{pidge_id}", headers={"Cookie": lucy_cookies})
        pin = await client.post(
            "/wall/pin",
            data={"_csrf_token": _csrf(pin_page.text), "pidge_id": str(pidge_id)},
            headers={"Cookie": lucy_cookies},
        )
        if pin.status != 302:
            raise RuntimeError(f"pin failed: {pin.status}")

        holds = service.store.list_holds(owner.id)
        if not holds or holds[0].state != "confirmed":
            raise RuntimeError(f"expected confirmed hold, got {holds!r}")
        pins = service.store.list_pins(lucy.id)
        acts = tuple(a.kind for a in service.store.list_acts(pidge_id))
        if "rsvp_yes" not in acts:
            raise RuntimeError(f"expected rsvp_yes act, got {acts}")

        return DogfoodResult(
            pidge_id=pidge_id,
            agent_token_prefix=minted.secret[:16] + "…",
            hold_state=holds[0].state,
            pin_count=len(pins),
            act_kinds=acts,
        )


class _HttpSession:
    def __init__(self, client: Any, base_url: str) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/") + "/"
        self.cookies: dict[str, str] = {}

    def _url(self, path: str) -> str:
        return urljoin(self.base_url, path.lstrip("/"))

    def _cookie_header(self) -> dict[str, str]:
        if not self.cookies:
            return {}
        return {"Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items())}

    def _absorb(self, response: Any) -> None:
        # httpx exposes .cookies; also parse Set-Cookie for chirp/pidge names.
        for name, value in response.cookies.items():
            self.cookies[name] = value
        raw = response.headers.get_list("set-cookie") if hasattr(response.headers, "get_list") else []
        if not raw:
            sc = response.headers.get("set-cookie")
            raw = [sc] if sc else []
        for item in raw:
            for name in (SESSION_COOKIE, "chirp_session"):
                if item.startswith(f"{name}="):
                    self.cookies[name] = item.split(";", 1)[0].split("=", 1)[1]

    async def get(self, path: str) -> Any:
        response = await self.client.get(self._url(path), headers=self._cookie_header())
        self._absorb(response)
        return response

    async def post_form(self, path: str, data: dict[str, str]) -> Any:
        response = await self.client.post(
            self._url(path),
            data=data,
            headers=self._cookie_header(),
        )
        self._absorb(response)
        return response

    async def post_json(self, path: str, payload: dict[str, Any], *, bearer: str | None = None) -> Any:
        headers = {"Content-Type": "application/json", **self._cookie_header()}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        response = await self.client.post(self._url(path), json=payload, headers=headers)
        return response


async def _ensure_owner(session: _HttpSession, *, password: str, bootstrap: str) -> None:
    setup = await session.get("/setup")
    if setup.status_code == 200 and "bootstrap" in setup.text.lower():
        response = await session.post_form(
            "/setup",
            {
                "_csrf_token": _csrf(setup.text),
                "bootstrap_token": bootstrap,
                "loft_name": "Nowadays Loft",
                "username": OWNER_USER,
                "display_name": OWNER_DISPLAY,
                "password": password,
            },
        )
        if response.status_code not in {200, 302}:
            raise RuntimeError(f"remote setup failed: {response.status_code}")
        return
    login = await session.get("/login")
    response = await session.post_form(
        "/login",
        {
            "_csrf_token": _csrf(login.text),
            "username": OWNER_USER,
            "password": password,
        },
    )
    if response.status_code not in {200, 302}:
        raise RuntimeError(f"remote owner login failed: {response.status_code}")


async def _ensure_lucy(session: _HttpSession, *, password: str) -> None:
    # Fresh cookie jar for Lucy (separate human session).
    session.cookies.pop(SESSION_COOKIE, None)
    login = await session.get("/login")
    attempt = await session.post_form(
        "/login",
        {
            "_csrf_token": _csrf(login.text),
            "username": LUCY_USER,
            "password": password,
        },
    )
    # Login page re-render on failure still 200 — detect error copy vs success.
    if (
        attempt.status_code in {200, 302}
        and SESSION_COOKIE in session.cookies
        and "Username or password" not in attempt.text
    ):
        return
    session.cookies.pop(SESSION_COOKIE, None)
    reg = await session.get("/register")
    response = await session.post_form(
        "/register",
        {
            "_csrf_token": _csrf(reg.text),
            "username": LUCY_USER,
            "display_name": LUCY_DISPLAY,
            "password": password,
        },
    )
    if response.status_code not in {200, 302}:
        raise RuntimeError(f"remote Lucy register failed: {response.status_code}")
    if SESSION_COOKIE not in session.cookies:
        raise RuntimeError("Lucy session cookie missing after register/login")


async def _mint_agent_http(session: _HttpSession, *, label: str = "Nowadays Secretary") -> str:
    page = await session.get("/settings/agents")
    if page.status_code != 200:
        raise RuntimeError(f"agents page failed: {page.status_code}")
    minted = await session.post_form(
        "/settings/agents",
        {"_csrf_token": _csrf(page.text), "action": "mint", "label": label},
    )
    # Secret is shown once on the agents page after mint.
    match = re.search(r"pidge_at_[A-Za-z0-9_-]+", minted.text)
    if match is None:
        raise RuntimeError("minted agent token not found in agents page HTML")
    return match.group(0)


async def _run_remote(
    *,
    base_url: str,
    password: str,
    lucy_password: str,
    bootstrap: str,
    agent_token: str | None,
) -> DogfoodResult:
    import httpx

    async with httpx.AsyncClient(follow_redirects=False, timeout=30.0) as client:
        owner = _HttpSession(client, base_url)
        await _ensure_owner(owner, password=password, bootstrap=bootstrap)
        secret = agent_token or await _mint_agent_http(owner)

        mcp_draft = await owner.post_json(
            "/mcp",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "draft_pidge",
                    "arguments": {
                        "intent": INTENT,
                        "recipients": [LUCY_DISPLAY],
                        "summary": SUMMARY,
                    },
                },
            },
            bearer=secret,
        )
        draft = _mcp_payload(mcp_draft.json())
        pidge_id = int(draft["id"])

        mcp_enrich = await owner.post_json(
            "/mcp",
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "enrich_pidge",
                    "arguments": {
                        "pidge_id": pidge_id,
                        "who": WHO,
                        "when": WHEN,
                        "where": WHERE,
                        "extras": EXTRAS,
                    },
                },
            },
            bearer=secret,
        )
        _mcp_payload(mcp_enrich.json())

        compose = await owner.get(f"/compose/{pidge_id}")
        seal = await owner.post_form(
            f"/compose/{pidge_id}/seal",
            {"_csrf_token": _csrf(compose.text)},
        )
        if seal.status_code != 302:
            raise RuntimeError(f"remote seal failed: {seal.status_code}")

        lucy = _HttpSession(client, base_url)
        await _ensure_lucy(lucy, password=lucy_password)
        inbox = await lucy.get("/inbox")
        if f"/p/{pidge_id}" not in inbox.text:
            raise RuntimeError("remote: sealed invite missing from Lucy inbox")

        thread = await lucy.get(f"/p/{pidge_id}")
        rsvp = await lucy.post_form(
            f"/p/{pidge_id}/act",
            {"_csrf_token": _csrf(thread.text), "kind": "rsvp_yes"},
        )
        if rsvp.status_code != 302:
            raise RuntimeError(f"remote RSVP failed: {rsvp.status_code}")

        pin_page = await lucy.get(f"/p/{pidge_id}")
        pin = await lucy.post_form(
            "/wall/pin",
            {"_csrf_token": _csrf(pin_page.text), "pidge_id": str(pidge_id)},
        )
        if pin.status_code != 302:
            raise RuntimeError(f"remote pin failed: {pin.status_code}")

        wall = await lucy.get("/wall")
        if SUMMARY not in wall.text and "Nowadays" not in wall.text:
            raise RuntimeError("remote: pin not visible on Lucy wall")

        calendar = await owner.get("/calendar")
        # Hold title is summary; accept place, when fragment, or summary.
        if (
            "Nowadays" not in calendar.text
            and WHEN.split("·")[0].strip() not in calendar.text
            and SUMMARY not in calendar.text
        ):
            raise RuntimeError("remote: confirmed hold not visible on owner calendar")

        return DogfoodResult(
            pidge_id=pidge_id,
            agent_token_prefix=secret[:16] + "…",
            hold_state="confirmed",
            pin_count=1,
            act_kinds=("rsvp_yes",),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--base-url",
        default=None,
        help="Optional live loft URL (local serve or Railway). Default: in-process MemoryStore.",
    )
    parser.add_argument("--bootstrap-token", default=BOOTSTRAP)
    parser.add_argument("--owner-password", default=DEFAULT_PASSWORD)
    parser.add_argument("--lucy-password", default=None, help="Defaults to --owner-password")
    parser.add_argument("--agent-token", default=None, help="Reuse a minted bearer token (remote)")
    args = parser.parse_args(argv)
    lucy_password = args.lucy_password or args.owner_password

    if args.base_url:
        result = asyncio.run(
            _run_remote(
                base_url=args.base_url,
                password=args.owner_password,
                lucy_password=lucy_password,
                bootstrap=args.bootstrap_token,
                agent_token=args.agent_token,
            )
        )
        mode = f"remote {args.base_url}"
    else:
        result = asyncio.run(
            _run_in_process(password=args.owner_password, bootstrap=args.bootstrap_token)
        )
        mode = "in-process MemoryStore"

    print(f"Nowadays dogfood OK ({mode})")
    print(f"  pidge_id={result.pidge_id}")
    print(f"  agent_token={result.agent_token_prefix}")
    print(f"  hold={result.hold_state} pins={result.pin_count} acts={list(result.act_kinds)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Nowadays dogfood FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
