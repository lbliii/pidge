"""Chirp application factory and hypermedia desk routes."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from chirp import EventStream, Fragment, Page
from chirp.app import App
from chirp.config import AppConfig
from chirp.health import HealthCheck
from chirp.http.cookies import SetCookie
from chirp.http.request import Request
from chirp.http.response import Redirect, Response
from chirp.middleware.auth import AuthConfig, AuthMiddleware, get_user
from chirp.middleware.auth_rate_limit import AuthRateLimitConfig, AuthRateLimitMiddleware
from chirp.middleware.csrf import CSRFConfig
from chirp.middleware.security_headers import SecurityHeadersConfig
from chirp.middleware.stack import secure_stack
from chirp.middleware.static import StaticFiles

from pidge.config import (
    ALL_AGENT_SCOPES,
    DEFAULT_TOKEN_PRESET,
    infer_preset,
    PidgeConfig,
)
from pidge.models import AgentClient, User
from pidge.services import PidgeService
from pidge.store import Store, store_from_url

ROOT = Path(__file__).parent
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"
SESSION_COOKIE = "pidge_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; connect-src 'self'; base-uri 'self'; "
    "form-action 'self'; frame-ancestors 'none'; object-src 'none'"
)


def create_app(
    *,
    debug: bool = True,
    store: Store | None = None,
    pidge_config: PidgeConfig | None = None,
) -> App:
    config = pidge_config or PidgeConfig.from_env(debug=debug)
    database = store or store_from_url(config.database_url)
    database.migrate()
    service = PidgeService(database, config)

    app_config = AppConfig(
        template_dir=TEMPLATES,
        debug=debug,
        env=config.env,
        secret_key=config.secret_key,
        allowed_hosts=_allowed_hosts(config),
        htmx=True,
        health_path="/livez",
        ready_path="/ready",
        workers=1,
        worker_mode="async" if config.production else "auto",
    )
    app = App(app_config)
    app.on_shutdown(database.close)
    app.add_health_check(
        HealthCheck("database", check=database.probe, message="database unavailable")
    )

    for scope in sorted(ALL_AGENT_SCOPES):
        app.register_scope(scope)

    app.add_middleware(
        AuthRateLimitMiddleware(
            AuthRateLimitConfig(
                paths=("/login", "/setup", "/register"),
                requests=10,
                window_seconds=60,
                block_seconds=300,
            )
        ),
        priority=-10,
    )
    for middleware in secure_stack(
        app_config,
        csrf=CSRFConfig(exempt_paths=frozenset({"/mcp"})),
        headers=SecurityHeadersConfig(content_security_policy=CONTENT_SECURITY_POLICY),
    ):
        app.add_middleware(middleware, priority=0)

    async def verify_token(token: str) -> AgentClient | None:
        return service.verify_agent_token(token)

    app.add_middleware(
        AuthMiddleware(AuthConfig(verify_token=verify_token, login_url=None)),
        priority=1,
    )
    app.add_middleware(StaticFiles(directory=str(STATIC), prefix="/static"), priority=20)

    def viewer(request: Request) -> User | None:
        return service.current_user(_cookie(request))

    def require_human(request: Request) -> User:
        user = viewer(request)
        if user is None:
            raise PermissionError("login_required")
        return user

    def render(request: Request, template: str, **context: object) -> Page:
        settings = database.settings()
        return Page(
            template,
            "page_content",
            page_block_name="page_root",
            settings=settings,
            viewer=viewer(request),
            loft_name=settings.name if settings else config.loft_name,
            current_path=request.path,
            **context,
        )

    def require_agent(*scopes: str) -> tuple[AgentClient, User]:
        # Raise plain PermissionError (not chirp.HTTPError): frozen HTTPError
        # cannot carry a traceback under Chirp's tool.call trace_span, which
        # collapses MCP auth failures into an opaque FrozenInstanceError.
        client = get_user()
        if not isinstance(client, AgentClient):
            raise PermissionError("Agent bearer token required.")
        missing = [s for s in scopes if s not in client.scopes]
        if missing:
            raise PermissionError(f"Missing scopes: {', '.join(missing)}")
        owner = service.store.get_user(client.owner_user_id)
        return client, owner

    # --- MCP tools (agent write path) --------------------------------------

    @app.tool("draft_pidge", description="Create a draft Pidge from intent and recipients.")
    def draft_pidge(
        intent: str, recipients: list[str] | str, summary: str = ""
    ) -> dict[str, Any]:
        _, owner = require_agent("pidge:draft")
        msg = service.draft_pidge(owner, intent=intent, recipient_names=recipients, summary=summary)
        return {"id": msg.id, "state": msg.state, "summary": msg.summary, "intent": msg.intent}

    @app.tool("enrich_pidge", description="Fill structured slots on a draft Pidge.")
    def enrich_pidge(
        pidge_id: int,
        who: str | None = None,
        when: str | None = None,
        where: str | None = None,
        extras: dict[str, Any] | None = None,
        mark_none: list[str] | None = None,
    ) -> dict[str, Any]:
        _, owner = require_agent("pidge:enrich")
        msg = service.enrich_pidge(
            owner,
            pidge_id,
            who=who,
            when=when,
            where=where,
            extras=extras,
            mark_none=tuple(mark_none or ()),
        )
        return {"id": msg.id, "summary": msg.summary, "slots": msg.slots, "state": msg.state}

    @app.tool("list_drafts", description="List the owner's draft Pidges.")
    def list_drafts() -> list[dict[str, Any]]:
        _, owner = require_agent("pidge:draft")
        return [
            {"id": m.id, "summary": m.summary, "intent": m.intent, "updated_at": m.updated_at}
            for m in service.store.list_drafts(owner.id)
        ]

    @app.tool("discard_pidge", description="Discard one of the owner's draft Pidges.")
    def discard_pidge_tool(pidge_id: int) -> dict[str, Any]:
        _, owner = require_agent("pidge:draft")
        msg = service.discard_pidge(owner, pidge_id)
        return {"id": msg.id, "state": msg.state}

    @app.tool("get_pidge", description="Fetch one Pidge the owner can see.")
    def get_pidge_tool(pidge_id: int) -> dict[str, Any]:
        _, owner = require_agent("pidge:draft")
        msg = service.get_pidge_for(owner, pidge_id)
        return {
            "id": msg.id,
            "state": msg.state,
            "summary": msg.summary,
            "intent": msg.intent,
            "slots": msg.slots,
            "recipients": [
                {"display_name": r.display_name, "loft_user_id": r.loft_user_id, "contact_id": r.contact_id}
                for r in service.store.recipients_for(msg.id)
            ],
        }

    @app.tool("list_directory", description="List other people in this loft.")
    def list_directory() -> list[dict[str, Any]]:
        _, owner = require_agent("pidge:draft")
        return [
            {"id": u.id, "username": u.username, "display_name": u.display_name}
            for u in service.directory(owner)
        ]

    @app.tool("list_contacts", description="List the owner's address book.")
    def list_contacts_tool() -> list[dict[str, Any]]:
        _, owner = require_agent("pidge:draft")
        return [
            {
                "id": c.id,
                "kind": c.kind,
                "status": c.status,
                "display_name": c.display_name,
                "external_handle": c.external_handle,
                "loft_user_id": c.loft_user_id,
            }
            for c in service.contacts(owner)
        ]

    @app.tool("add_contact", description="Add an external contact to the address book.")
    def add_contact_tool(handle: str, display_name: str = "") -> dict[str, Any]:
        _, owner = require_agent("pidge:draft")
        contact = service.add_external_contact(owner, handle=handle, display_name=display_name)
        return {
            "id": contact.id,
            "display_name": contact.display_name,
            "status": contact.status,
            "handle": contact.external_handle,
        }

    @app.tool("propose_hold", description="Propose a calendar hold for a Pidge.")
    def propose_hold_tool(
        pidge_id: int, title: str = "", starts_at: str | None = None, place: str | None = None
    ) -> dict[str, Any]:
        _, owner = require_agent("pidge:calendar.propose")
        hold = service.propose_hold(owner, pidge_id, title=title, starts_at=starts_at, place=place)
        return {
            "id": hold.id,
            "title": hold.title,
            "starts_at": hold.starts_at,
            "place": hold.place,
            "state": hold.state,
        }

    @app.tool("pin_note", description="Pin a sealed Pidge to the owner's wall.")
    def pin_note_tool(pidge_id: int, title: str = "") -> dict[str, Any]:
        _, owner = require_agent("pidge:notes.pin")
        pin = service.pin_note(owner, pidge_id, title=title or None)
        return {"id": pin.id, "pidge_id": pin.pidge_id, "title": pin.title}

    @app.tool(
        "propose_seal",
        description=(
            "Propose sealing a ready draft. Returns a one-time seal_url for the "
            "human author to confirm in the browser. Does not seal by itself."
        ),
    )
    def propose_seal_tool(pidge_id: int) -> dict[str, Any]:
        client, owner = require_agent("pidge:seal.propose")
        result = service.propose_seal(
            owner,
            pidge_id,
            agent_token_id=client.token_id,
            public_origin=config.public_origin,
        )
        msg = result.message
        return {
            "pidge_id": msg.id,
            "summary": msg.summary,
            "slots": msg.slots,
            "recipients": [
                {
                    "display_name": r.display_name,
                    "loft_user_id": r.loft_user_id,
                    "contact_id": r.contact_id,
                }
                for r in result.recipients
            ],
            "expires_at": result.challenge.expires_at.isoformat(),
            "seal_url": result.seal_url,
        }

    # --- HTTP routes -------------------------------------------------------

    @app.route("/")
    def index(request: Request):
        if database.settings() is None:
            return Redirect("/setup")
        user = viewer(request)
        if user is None:
            return Redirect("/login")
        return render(
            request,
            "desk.html",
            drafts=service.store.list_drafts(user.id),
            inbox=service.store.list_inbox(user.id)[:8],
            holds=service.store.list_holds(user.id)[:5],
            pins=service.store.list_pins(user.id)[:5],
        )

    @app.route("/setup", referenced=True, template="setup.html")
    def setup_page(request: Request):
        if database.settings() is not None:
            return Redirect("/")
        return render(
            request,
            "setup.html",
            error=None,
            show_development_hint=not config.production,
            values={
                "loft_name": config.loft_name,
                "username": "",
                "display_name": "",
            },
        )

    @app.route("/setup", methods=["POST"], referenced=True, template="setup.html")
    async def setup_submit(request: Request):
        if database.settings() is not None:
            return Redirect("/")
        form = await request.form()
        values = {
            "loft_name": str(form.get("loft_name", "")),
            "username": str(form.get("username", "")),
            "display_name": str(form.get("display_name", "")),
        }
        try:
            result = service.setup(
                bootstrap_token=str(form.get("bootstrap_token", "")),
                loft_name=values["loft_name"],
                username=values["username"],
                display_name=values["display_name"],
                password=str(form.get("password", "")),
            )
        except (PermissionError, ValueError) as exc:
            return render(request, "setup.html", error=str(exc), show_development_hint=not config.production, values=values)
        return _session_redirect("/", result.session_token, config)

    @app.route("/login", referenced=True, template="login.html")
    def login_page(request: Request):
        if database.settings() is None:
            return Redirect("/setup")
        if viewer(request):
            return Redirect("/")
        return render(request, "login.html", error=None)

    @app.route("/login", methods=["POST"], referenced=True, template="login.html")
    async def login_submit(request: Request):
        form = await request.form()
        try:
            _user, token = service.login(str(form.get("username", "")), str(form.get("password", "")))
        except PermissionError as exc:
            return render(request, "login.html", error=str(exc))
        return _session_redirect("/", token, config)

    @app.route("/register", referenced=True, template="register.html")
    def register_page(request: Request):
        if database.settings() is None:
            return Redirect("/setup")
        return render(request, "register.html", error=None, values={"username": "", "display_name": ""})

    @app.route("/register", methods=["POST"], referenced=True, template="register.html")
    async def register_submit(request: Request):
        form = await request.form()
        values = {
            "username": str(form.get("username", "")),
            "display_name": str(form.get("display_name", "")),
        }
        try:
            result = service.register(
                username=values["username"],
                display_name=values["display_name"],
                password=str(form.get("password", "")),
            )
        except (PermissionError, ValueError) as exc:
            return render(request, "register.html", error=str(exc), values=values)
        return _session_redirect("/", result.session_token, config)

    @app.route("/logout", methods=["POST"], referenced=True)
    async def logout(request: Request):
        service.logout(_cookie(request))
        return Response(
            "",
            status=302,
            headers=(("Location", "/login"),),
            cookies=(_clear_session_cookie(config),),
        )

    @app.route("/inbox")
    def inbox(request: Request):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        return render(request, "inbox.html", messages=service.store.list_inbox(user.id))

    @app.route("/sent")
    def sent(request: Request):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        return render(request, "sent.html", messages=service.store.list_sent(user.id))

    @app.route("/compose")
    def compose_index(request: Request):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        drafts = service.store.list_drafts(user.id)
        if drafts:
            return Redirect(f"/compose/{drafts[0].id}")
        return render(request, "compose_empty.html")

    @app.route("/compose/{draft_id:int}")
    def compose_draft(request: Request, draft_id: int):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        try:
            msg = service.get_pidge_for(user, draft_id)
        except (LookupError, PermissionError):
            return Response("Not found", status=404)
        if msg.state == "revoked":
            return Redirect("/compose")
        return render(request, "compose.html", **_compose_context(service, msg))

    @app.route("/compose/{draft_id:int}/seal", methods=["POST"], referenced=True)
    async def seal_draft(request: Request, draft_id: int):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        try:
            sealed = service.seal_pidge(user, draft_id)
        except (PermissionError, ValueError, LookupError) as exc:
            msg = service.store.get_pidge(draft_id)
            return render(
                request,
                "compose.html",
                **_compose_context(service, msg, error=str(exc)),
            )
        return Redirect(f"/p/{sealed.id}")

    @app.route("/compose/{draft_id:int}/discard", methods=["POST"], referenced=True)
    async def discard_draft(request: Request, draft_id: int):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        try:
            service.discard_pidge(user, draft_id)
        except (PermissionError, LookupError):
            return Response("Not found", status=404)
        return Redirect("/compose")

    @app.route(
        "/compose/{draft_id:int}/seal-challenge/{secret}",
        referenced=True,
        template="seal_challenge.html",
    )
    def seal_challenge_get(request: Request, draft_id: int, secret: str):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        try:
            service.load_seal_challenge(user, draft_id, secret)
            msg = service.get_pidge_for(user, draft_id)
        except LookupError:
            return Response("Seal challenge not found.", status=404)
        except PermissionError as exc:
            detail = str(exc)
            status = (
                410
                if "expired" in detail.lower() or "already used" in detail.lower()
                else 403
            )
            return Response(detail, status=status)
        except ValueError as exc:
            return Response(str(exc), status=403)
        return render(
            request,
            "seal_challenge.html",
            **_compose_context(service, msg),
            challenge_token=secret,
        )

    @app.route(
        "/compose/{draft_id:int}/seal-challenge/{secret}",
        methods=["POST"],
        referenced=True,
    )
    async def seal_challenge_post(request: Request, draft_id: int, secret: str):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        try:
            sealed = service.redeem_seal_challenge(user, draft_id, secret)
        except LookupError:
            return Response("Seal challenge not found.", status=404)
        except PermissionError as exc:
            detail = str(exc)
            status = (
                410
                if "expired" in detail.lower() or "already used" in detail.lower()
                else 403
            )
            return Response(detail, status=status)
        except ValueError as exc:
            return Response(str(exc), status=403)
        return Redirect(f"/p/{sealed.id}")

    @app.route("/compose/{draft_id:int}/flight", referenced=True)
    def compose_flight_feed(request: Request, draft_id: int):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        try:
            service.get_pidge_for(user, draft_id)
        except (LookupError, PermissionError):
            return Response("Not found", status=404)

        async def generate():
            # Replay current rail + seal panel, then refresh when this draft's tools run.
            for fragment in _compose_live_fragments(service, draft_id):
                yield fragment
            async for event in app.tool_events.subscribe():
                if not _tool_event_touches_draft(event, draft_id):
                    continue
                for fragment in _compose_live_fragments(service, draft_id):
                    yield fragment

        return EventStream(generate())

    @app.route("/p/{pidge_id:int}")
    def pidge_detail(request: Request, pidge_id: int):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        try:
            msg = service.get_pidge_for(user, pidge_id)
        except (LookupError, PermissionError):
            return Response("Not found", status=404)
        return render(
            request,
            "thread.html",
            message=msg,
            recipients=service.store.recipients_for(msg.id),
            acts=service.store.list_acts(msg.id),
            is_author=msg.author_id == user.id,
            is_recipient=any(
                r.loft_user_id == user.id for r in service.store.recipients_for(msg.id)
            ),
            error=None,
        )

    @app.route("/p/{pidge_id:int}/revoke", methods=["POST"], referenced=True)
    async def revoke_sealed(request: Request, pidge_id: int):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        try:
            service.revoke_sealed_pidge(user, pidge_id)
        except (PermissionError, LookupError):
            return Response("Not found", status=404)
        return Redirect(f"/p/{pidge_id}")

    @app.route("/p/{pidge_id:int}/supersede", methods=["POST"], referenced=True)
    async def supersede_sealed(request: Request, pidge_id: int):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        try:
            draft = service.supersede_pidge(user, pidge_id)
        except (PermissionError, LookupError):
            return Response("Not found", status=404)
        return Redirect(f"/compose/{draft.id}")

    @app.route("/p/{pidge_id:int}/act", methods=["POST"], referenced=True)
    async def pidge_act(request: Request, pidge_id: int):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        form = await request.form()
        kind = str(form.get("kind", ""))
        try:
            service.record_act(user, pidge_id, kind)
        except (PermissionError, ValueError, LookupError) as exc:
            msg = service.store.get_pidge(pidge_id)
            return render(
                request,
                "thread.html",
                message=msg,
                recipients=service.store.recipients_for(msg.id),
                acts=service.store.list_acts(msg.id),
                is_author=msg.author_id == user.id,
                is_recipient=True,
                error=str(exc),
            )
        return Redirect(f"/p/{pidge_id}")

    @app.route("/directory")
    def directory(request: Request):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        return render(
            request,
            "directory.html",
            people=service.directory(user),
            requests=service.store.list_connection_requests(user.id),
            error=None,
        )

    @app.route("/directory/connect", methods=["POST"], referenced=True)
    async def directory_connect(request: Request):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        form = await request.form()
        try:
            service.request_loft_connection(user, username=str(form.get("username", "")))
            error = None
        except (LookupError, ValueError, PermissionError) as exc:
            error = str(exc)
        return render(
            request,
            "directory.html",
            people=service.directory(user),
            requests=service.store.list_connection_requests(user.id),
            error=error,
        )

    @app.route("/directory/accept", methods=["POST"], referenced=True)
    async def directory_accept(request: Request):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        form = await request.form()
        with contextlib.suppress(PermissionError, LookupError, ValueError):
            service.accept_connection(user, int(form.get("request_id", "0")))
        return Redirect("/contacts")

    @app.route("/contacts")
    def contacts_page(request: Request):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        return render(
            request,
            "contacts.html",
            contacts=service.contacts(user),
            error=None,
        )

    @app.route("/contacts/add", methods=["POST"], referenced=True)
    async def contacts_add(request: Request):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        form = await request.form()
        try:
            service.add_external_contact(
                user,
                handle=str(form.get("handle", "")),
                display_name=str(form.get("display_name", "")),
            )
            error = None
        except ValueError as exc:
            error = str(exc)
        return render(request, "contacts.html", contacts=service.contacts(user), error=error)

    @app.route("/calendar")
    def calendar(request: Request):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        return render(request, "calendar.html", holds=service.store.list_holds(user.id))

    @app.route("/wall")
    def wall(request: Request):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        return render(request, "wall.html", pins=service.store.list_pins(user.id))

    @app.route("/wall/pin", methods=["POST"], referenced=True)
    async def wall_pin(request: Request):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        form = await request.form()
        with contextlib.suppress(PermissionError, LookupError, ValueError):
            service.pin_note(user, int(form.get("pidge_id", "0")))
        return Redirect("/wall")

    def _mcp_url(request: Request) -> str:
        if config.public_origin:
            return f"{config.public_origin}/mcp"
        url = request.url
        if isinstance(url, str):
            parsed = urlparse(url)
            scheme = parsed.scheme or "http"
            netloc = parsed.netloc or "127.0.0.1:8000"
            return f"{scheme}://{netloc}/mcp"
        return f"{url.scheme}://{url.netloc}/mcp"

    @app.route("/settings/agents")
    def agents_settings(request: Request):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        return render(
            request,
            "agents.html",
            tokens=service.list_agent_tokens(user),
            scopes=sorted(ALL_AGENT_SCOPES),
            default_preset=DEFAULT_TOKEN_PRESET,
            infer_preset=infer_preset,
            minted_secret=None,
            mcp_url=_mcp_url(request),
            error=None,
        )

    @app.route("/settings/agents", methods=["POST"], referenced=True)
    async def agents_mint(request: Request):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        form = await request.form()
        action = str(form.get("action", "mint"))
        if action == "revoke":
            with contextlib.suppress(LookupError):
                service.revoke_agent_token(user, int(form.get("token_id", "0")))
            return Redirect("/settings/agents")
        preset = str(form.get("preset", DEFAULT_TOKEN_PRESET)).strip() or DEFAULT_TOKEN_PRESET
        try:
            result = service.mint_agent_token(
                user,
                label=str(form.get("label", "Agent")),
                preset=preset,
            )
            error = None
            secret = result.secret
        except ValueError as exc:
            error = str(exc)
            secret = None
        return render(
            request,
            "agents.html",
            tokens=service.list_agent_tokens(user),
            scopes=sorted(ALL_AGENT_SCOPES),
            default_preset=DEFAULT_TOKEN_PRESET,
            infer_preset=infer_preset,
            minted_secret=secret,
            mcp_url=_mcp_url(request),
            error=error,
        )

    return app


def _can_seal(msg: Any) -> bool:
    return _seal_block_reason(msg) is None and getattr(msg, "state", None) == "draft"


def _seal_block_reason(msg: Any) -> str | None:
    if getattr(msg, "state", None) != "draft":
        return None
    slots = getattr(msg, "slots", {}) or {}
    missing = [
        key
        for key in ("who", "when", "where")
        if not isinstance(slots.get(key), dict)
        or slots[key].get("status") not in {"ready", "none"}
    ]
    if not missing:
        return None
    return f"Seal blocked — waiting on {', '.join(missing)} via enrich_pidge."


def _compose_context(service: PidgeService, msg: Any, *, error: str | None = None) -> dict[str, Any]:
    flight = service.store.get_flight_for_pidge(msg.id)
    steps = service.store.list_flight_steps(flight.id) if flight else ()
    return {
        "message": msg,
        "recipients": service.store.recipients_for(msg.id),
        "flight": flight,
        "steps": steps,
        "can_seal": _can_seal(msg),
        "seal_block_reason": _seal_block_reason(msg),
        "error": error,
    }


def _compose_live_fragments(service: PidgeService, draft_id: int) -> list[Fragment]:
    try:
        msg = service.store.get_pidge(draft_id)
    except LookupError:
        return []
    ctx = _compose_context(service, msg)
    return [
        Fragment("compose.html", "flight_rail", target="flight_rail", **ctx),
        Fragment("compose.html", "compose_live", target="compose_live", **ctx),
    ]


def _tool_event_touches_draft(event: Any, draft_id: int) -> bool:
    """Return True when a tool_events payload likely changed this draft."""
    name = getattr(event, "tool_name", "") or ""
    args = getattr(event, "arguments", None) or {}
    result = getattr(event, "result", None)
    if name == "enrich_pidge":
        try:
            return int(args.get("pidge_id", -1)) == draft_id
        except (TypeError, ValueError):
            return False
    if name == "draft_pidge" and isinstance(result, dict):
        try:
            return int(result.get("id", -1)) == draft_id
        except (TypeError, ValueError):
            return False
    if isinstance(result, dict):
        try:
            return int(result.get("id", -1)) == draft_id
        except (TypeError, ValueError):
            return False
    return False


def _gate(request: Request, require_human: Any) -> User | Redirect:
    try:
        return require_human(request)
    except PermissionError:
        return Redirect("/login")


def _cookie(request: Request) -> str | None:
    value = request.cookies.get(SESSION_COOKIE)
    return value if value else None


def _session_redirect(location: str, value: str, config: PidgeConfig) -> Response:
    return Response(
        "",
        status=302,
        headers=(("Location", location),),
        cookies=(_session_cookie(value, config),),
    )


def _session_cookie(value: str, config: PidgeConfig) -> SetCookie:
    return SetCookie(
        SESSION_COOKIE,
        value,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=config.production,
        path="/",
    )


def _clear_session_cookie(config: PidgeConfig) -> SetCookie:
    return SetCookie(
        SESSION_COOKIE,
        "",
        max_age=0,
        httponly=True,
        samesite="lax",
        secure=config.production,
        path="/",
    )


def _allowed_hosts(config: PidgeConfig) -> tuple[str, ...]:
    if not config.public_origin:
        return ("*",)
    host = urlparse(config.public_origin).hostname
    return (host,) if host else ("*",)
