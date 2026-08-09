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
from chirp.middleware.csp_nonce import CSPNonceMiddleware
from chirp.middleware.csrf import CSRFConfig
from chirp.middleware.security_headers import SecurityHeadersConfig
from chirp.middleware.stack import secure_stack
from chirp.middleware.static import StaticFiles

from pidge.config import (
    ALL_AGENT_SCOPES,
    AUTOPILOT_TOKEN_TTL_DAYS,
    DEFAULT_TOKEN_PRESET,
    DESK_TOKEN_TTL_DAYS,
    PidgeConfig,
    infer_preset,
)
from pidge.discovery import (
    DISCOVERY_CACHE_CONTROL,
    DISCOVERY_CORS,
    llms_full_txt,
    llms_txt,
    mcp_manifest,
    resolve_public_origin,
    robots_txt,
    security_txt,
    server_card,
)
from pidge.discovery import (
    dumps as discovery_dumps,
)
from pidge.models import AgentClient, User
from pidge.services import PidgeService
from pidge.store import Store, store_from_url

ROOT = Path(__file__).parent
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"
SESSION_COOKIE = "pidge_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30
# script-src is appended by CSPNonceMiddleware with the per-request nonce;
# everything else is ours. Chirp injects inline bootstraps (safe-target,
# sse-lifecycle) that only a nonce can allow without 'unsafe-inline'.
CSP_BASE = (
    "default-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; connect-src 'self'; base-uri 'self'; "
    "form-action 'self'; frame-ancestors 'none'; object-src 'none'"
)
SCRIPT_ORIGINS = "https://cdn.jsdelivr.net"


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
        # CSP is owned by CSPNonceMiddleware below; two middlewares emitting the
        # header would have the browser enforce both policies.
        headers=SecurityHeadersConfig(content_security_policy=None),
    ):
        app.add_middleware(middleware, priority=0)

    async def verify_token(token: str) -> AgentClient | None:
        return service.verify_agent_token(token)

    app.add_middleware(
        AuthMiddleware(AuthConfig(verify_token=verify_token, login_url=None)),
        priority=1,
    )
    app.add_middleware(StaticFiles(directory=str(STATIC), prefix="/static"), priority=20)
    # Inside StaticFiles (assets need no nonce) but outside Chirp's builtin
    # inject middleware, so its snippets render with the live nonce.
    app.add_middleware(_csp_nonce_middleware(), priority=21)

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
        intent: str,
        recipients: list[str] | str,
        summary: str = "",
        kind: str = "invite",
    ) -> dict[str, Any]:
        _, owner = require_agent("pidge:draft")
        names = (
            [recipients]
            if isinstance(recipients, str)
            else list(recipients)
        )
        msg = service.draft_pidge(
            owner,
            intent=intent,
            recipient_names=names,
            summary=summary,
            kind=kind,
        )
        return {
            "id": msg.id,
            "state": msg.state,
            "summary": msg.summary,
            "intent": msg.intent,
            "kind": msg.kind,
        }

    @app.tool(
        "enrich_pidge",
        description=(
            "Fill structured slots on a draft Pidge. "
            "Optional extras may include blocks: [{type, ...}] (place/map/menu/reviews/article)."
        ),
    )
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
        return {
            "id": msg.id,
            "summary": msg.summary,
            "slots": msg.slots,
            "state": msg.state,
            "kind": msg.kind,
        }

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
            "kind": msg.kind,
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

    @app.tool(
        "seal_pidge",
        description=(
            "Seal a ready draft over MCP. Requires Autopilot scope pidge:seal. "
            "Irreversible — prefer propose_seal unless the human opted into Autopilot."
        ),
    )
    def seal_pidge_tool(pidge_id: int) -> dict[str, Any]:
        _, owner = require_agent("pidge:seal")
        sealed = service.seal_pidge(owner, pidge_id)
        return {
            "id": sealed.id,
            "state": sealed.state,
            "summary": sealed.summary,
            "slots": sealed.slots,
        }

    # --- HTTP routes -------------------------------------------------------

    def _loft_origin(request: Request) -> str:
        return resolve_public_origin(config.public_origin, request.url)

    def _loft_display_name() -> str:
        settings = database.settings()
        return settings.name if settings else config.loft_name

    def _discovery_json(payload: dict[str, Any]) -> Response:
        return Response(
            discovery_dumps(payload),
            content_type="application/json; charset=utf-8",
            headers=(
                ("Cache-Control", DISCOVERY_CACHE_CONTROL),
                ("Access-Control-Allow-Origin", DISCOVERY_CORS),
                ("X-Content-Type-Options", "nosniff"),
            ),
        )

    def _discovery_text(body: str, *, content_type: str) -> Response:
        return Response(
            body if body.endswith("\n") else f"{body}\n",
            content_type=content_type,
            headers=(
                ("Cache-Control", DISCOVERY_CACHE_CONTROL),
                ("Access-Control-Allow-Origin", DISCOVERY_CORS),
                ("X-Content-Type-Options", "nosniff"),
            ),
        )

    @app.route("/.well-known/mcp/server-card.json")
    def mcp_server_card(request: Request):
        origin = _loft_origin(request)
        return _discovery_json(server_card(origin, loft_name=_loft_display_name()))

    @app.route("/.well-known/mcp")
    def mcp_well_known_manifest(request: Request):
        return _discovery_json(mcp_manifest(_loft_origin(request)))

    @app.route("/.well-known/mcp.json")
    def mcp_well_known_manifest_alias(request: Request):
        # Early clients sometimes probe .json; same body as /.well-known/mcp.
        return _discovery_json(mcp_manifest(_loft_origin(request)))

    @app.route("/.well-known/security.txt")
    def well_known_security(request: Request):
        return _discovery_text(
            security_txt(_loft_origin(request)),
            content_type="text/plain; charset=utf-8",
        )

    @app.route("/llms.txt")
    def llms_document(request: Request):
        return _discovery_text(
            llms_txt(_loft_origin(request), loft_name=_loft_display_name()),
            content_type="text/plain; charset=utf-8",
        )

    @app.route("/llms-full.txt")
    def llms_full_document(request: Request):
        return _discovery_text(
            llms_full_txt(_loft_origin(request), loft_name=_loft_display_name()),
            content_type="text/plain; charset=utf-8",
        )

    @app.route("/robots.txt")
    def robots_document(request: Request):
        return _discovery_text(
            robots_txt(_loft_origin(request)),
            content_type="text/plain; charset=utf-8",
        )

    @app.route("/connect", referenced=True, template="connect.html")
    def connect_page(request: Request):
        origin = _loft_origin(request)
        name = _loft_display_name()
        return render(
            request,
            "connect.html",
            mcp_url=f"{origin}/mcp",
            origin=origin,
            tools=server_card(origin, loft_name=name)["tools"],
        )

    @app.route("/")
    def index(request: Request):
        if database.settings() is None:
            return Redirect("/setup")
        user = viewer(request)
        if user is None:
            return Redirect("/login")
        return render(request, "desk.html", **_desk_context(service, user))

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
        return render(
            request,
            "inbox.html",
            rows=_mail_rows(service, user, service.store.list_inbox(user.id), facet="in"),
        )

    @app.route("/sent")
    def sent(request: Request):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        return render(
            request,
            "sent.html",
            rows=_mail_rows(service, user, service.store.list_sent(user.id), facet="out"),
        )

    @app.route("/sent/{pidge_id:int}")
    def sent_delivery(request: Request, pidge_id: int):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        try:
            msg = service.get_pidge_for(user, pidge_id)
        except (LookupError, PermissionError):
            return Response("Not found", status=404)
        if msg.author_id != user.id or msg.state not in {"sealed", "revoked", "superseded"}:
            return Redirect(f"/p/{pidge_id}")
        return render(request, "delivery.html", **_delivery_context(service, msg))

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
        return Redirect(f"/sent/{sealed.id}")

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
        return Redirect(f"/sent/{sealed.id}")

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
            kind_label=_kind_label(msg.kind),
            error=None,
            **_enrich_view(msg),
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
                kind_label=_kind_label(msg.kind),
                error=str(exc),
                **_enrich_view(msg),
            )
        return Redirect(f"/p/{pidge_id}")

    @app.route("/people")
    def people_loft(request: Request):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        return render(request, "people.html", **_people_loft_context(service, user, error=None))

    @app.route("/people/address-book")
    def people_address_book(request: Request):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        return render(
            request,
            "people.html",
            facet="beyond",
            **_people_beyond_context(service, user, error=None),
        )

    @app.route("/directory")
    def directory(request: Request):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        return Redirect("/people")

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
        return render(request, "people.html", **_people_loft_context(service, user, error=error))

    @app.route("/directory/accept", methods=["POST"], referenced=True)
    async def directory_accept(request: Request):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        form = await request.form()
        with contextlib.suppress(PermissionError, LookupError, ValueError):
            service.accept_connection(user, int(form.get("request_id", "0")))
        return Redirect("/people")

    @app.route("/contacts")
    def contacts_page(request: Request):
        user = _gate(request, require_human)
        if not isinstance(user, User):
            return user
        return Redirect("/people/address-book")

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
        return render(
            request,
            "people.html",
            facet="beyond",
            **_people_beyond_context(service, user, error=error),
        )

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
        return f"{_loft_origin(request)}/mcp"

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
            minted_preset=None,
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
        error = None
        secret = None
        minted_preset = None
        if preset == "autopilot":
            ack = str(form.get("acknowledge_autopilot", "")).strip().lower()
            if ack not in {"1", "on", "true", "yes"}:
                error = (
                    "Autopilot mint requires acknowledging that this token can "
                    "seal Pidges over MCP."
                )
            days = AUTOPILOT_TOKEN_TTL_DAYS
        else:
            days = DESK_TOKEN_TTL_DAYS
        if error is None:
            try:
                result = service.mint_agent_token(
                    user,
                    label=str(form.get("label", "Agent")),
                    preset=preset,
                    days=days,
                )
                secret = result.secret
                minted_preset = preset
            except ValueError as exc:
                error = str(exc)
                secret = None
                minted_preset = None
        return render(
            request,
            "agents.html",
            tokens=service.list_agent_tokens(user),
            scopes=sorted(ALL_AGENT_SCOPES),
            default_preset=DEFAULT_TOKEN_PRESET,
            infer_preset=infer_preset,
            minted_secret=secret,
            minted_preset=minted_preset,
            mcp_url=_mcp_url(request),
            error=error,
        )

    return app


def _csp_nonce_middleware() -> CSPNonceMiddleware:
    middleware = CSPNonceMiddleware(base_csp=CSP_BASE)
    # Chirp defaults script-src to unpkg + jsdelivr; the desk only loads
    # jsdelivr. Slotted attribute — a rename upstream fails loudly at startup.
    middleware._script_origins = SCRIPT_ORIGINS
    return middleware


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


def _enrich_view(msg: Any, *, skel: bool = False) -> dict[str, Any]:
    """Build fact-strip + block views for enrich-stack templates."""
    slots = getattr(msg, "slots", {}) or {}
    facts: list[dict[str, str]] = []
    for key, label in (("who", "Who"), ("when", "When"), ("where", "Where")):
        slot = slots.get(key)
        if isinstance(slot, dict) and slot.get("status") == "ready" and slot.get("value"):
            facts.append({"label": label, "value": str(slot["value"])})

    extras_slot = slots.get("extras")
    extras_value = extras_slot.get("value") if isinstance(extras_slot, dict) else None
    raw_blocks: list[Any] = []
    leftover: dict[str, Any] = {}
    if isinstance(extras_value, dict):
        maybe_blocks = extras_value.get("blocks")
        if isinstance(maybe_blocks, list):
            raw_blocks = maybe_blocks
        leftover = {k: v for k, v in extras_value.items() if k != "blocks"}
    elif extras_value is not None:
        leftover = {"extras": extras_value}

    blocks: list[dict[str, Any]] = []
    for block in raw_blocks:
        if not isinstance(block, dict):
            continue
        btype = str(block.get("type") or "")
        skipped = block.get("status") == "skipped" or bool(block.get("degraded"))
        if skipped:
            blocks.append(
                {
                    "variant": "degraded",
                    "label": btype or "Block",
                    "blurb": str(
                        block.get("blurb")
                        or block.get("detail")
                        or "Couldn't fetch — seal still OK."
                    ),
                    "meta": "skipped",
                }
            )
            continue
        if btype == "place":
            title = str(block.get("title") or "Place")
            blocks.append(
                {
                    "variant": "place",
                    "title": title,
                    "blurb": block.get("blurb") or "",
                    "has_art": bool(block.get("image")),
                    "mark": title[:1].upper() or "P",
                    "meta": "place" + (" · fetched" if block.get("fetched_at") else ""),
                }
            )
        elif btype == "map":
            meta = ""
            if block.get("lat") is not None and block.get("lng") is not None:
                meta = f"{block.get('lat')} · {block.get('lng')}"
            blocks.append(
                {
                    "variant": "map",
                    "title": str(block.get("address") or block.get("title") or "Map"),
                    "meta": meta,
                }
            )
        elif btype == "menu":
            items = block.get("items") if isinstance(block.get("items"), list) else []
            blocks.append(
                {
                    "variant": "menu",
                    "title": str(block.get("title") or "Menu"),
                    "items": [str(i) for i in items],
                    "blurb": str(block.get("blurb") or ""),
                }
            )
        elif btype == "reviews":
            rating = block.get("rating")
            title = str(rating) if rating is not None else ""
            if block.get("blurb"):
                title = f"{title} · “{block.get('blurb')}”" if title else str(block.get("blurb"))
            blocks.append(
                {
                    "variant": "reviews",
                    "title": title or "Reviews",
                    "rating": rating,
                }
            )
        elif btype in {"article", "link"}:
            blocks.append(
                {
                    "variant": "article",
                    "label": "Article" if btype == "article" else "Link",
                    "title": str(block.get("title") or "Shared link"),
                    "blurb": str(block.get("blurb") or ""),
                    "meta": str(block.get("source_url") or ""),
                }
            )
        else:
            blocks.append(
                {
                    "variant": "article",
                    "label": btype or "Block",
                    "title": str(block.get("title") or btype or "Note"),
                    "blurb": str(block.get("blurb") or block.get("note") or ""),
                    "meta": "",
                }
            )

    if not raw_blocks:
        where = slots.get("where")
        if isinstance(where, dict) and where.get("status") == "ready" and where.get("value"):
            title = str(where["value"])
            blocks.append(
                {
                    "variant": "place",
                    "title": title,
                    "blurb": "",
                    "has_art": False,
                    "mark": title[:1].upper() or "P",
                    "meta": "place · from slots",
                }
            )
        for key, val in leftover.items():
            blocks.append(
                {
                    "variant": "article",
                    "label": str(key),
                    "title": str(val),
                    "blurb": "",
                    "meta": "",
                }
            )

    return {
        "enrich_facts": facts,
        "enrich_blocks": blocks,
        "enrich_skel": skel,
    }


def _kind_label(kind: str) -> str:
    return (kind or "invite").replace("_", " ").title()


def _compose_context(service: PidgeService, msg: Any, *, error: str | None = None) -> dict[str, Any]:
    flight = service.store.get_flight_for_pidge(msg.id)
    steps = service.store.list_flight_steps(flight.id) if flight else ()
    enriching = bool(flight and flight.state == "flying")
    return {
        "message": msg,
        "recipients": service.store.recipients_for(msg.id),
        "flight": flight,
        "steps": steps,
        "can_seal": _can_seal(msg),
        "seal_block_reason": _seal_block_reason(msg),
        "error": error,
        "kind_label": _kind_label(getattr(msg, "kind", "invite")),
        **_enrich_view(msg, skel=enriching and not _can_seal(msg)),
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


def _desk_context(service: PidgeService, user: User) -> dict[str, Any]:
    """Attention blotter: Needs you first, quiet residue below."""
    drafts = service.store.list_drafts(user.id)
    inbox = service.store.list_inbox(user.id)
    holds = service.store.list_holds(user.id)[:5]
    pins = service.store.list_pins(user.id)[:5]

    ready: list[dict[str, Any]] = []
    enriching: list[dict[str, Any]] = []
    for draft in drafts:
        title = draft.summary or draft.intent or "Untitled draft"
        if _can_seal(draft):
            ready.append(
                {
                    "href": f"/compose/{draft.id}",
                    "title": title,
                    "why": "Slots ready — seal to send",
                    "badge": "Ready to seal",
                    "badge_class": "ready",
                    "mark": "!",
                    "mark_class": "warn",
                    "action": "Seal",
                    "time": None,
                }
            )
        else:
            reason = _seal_block_reason(draft) or "Draft → Enrich in progress"
            enriching.append(
                {
                    "href": f"/compose/{draft.id}",
                    "title": title,
                    "why": reason.replace("Seal blocked — waiting on ", "Waiting on "),
                    "badge": "Enriching",
                    "badge_class": "enriching",
                    "mark": "…",
                    "mark_class": "agent",
                    "action": None,
                    "time": "now",
                }
            )

    needs_act: list[dict[str, Any]] = []
    mail_peek: list[dict[str, Any]] = []
    for msg in inbox:
        acts = tuple(a for a in service.store.list_acts(msg.id) if a.actor_user_id == user.id)
        kind = msg.kind or "invite"
        kind_label = _kind_label(kind)
        title = msg.summary or msg.intent or "Sealed Pidge"
        author = msg.author_name or "Someone"
        stamp = _format_desk_time(msg.sealed_at or msg.updated_at)
        if _message_needs_act(kind, acts):
            needs_act.append(
                {
                    "href": f"/p/{msg.id}",
                    "title": title,
                    "why": f"From {author} — needs your act",
                    "badge": f"{kind_label} · needs act",
                    "badge_class": kind if kind in {"invite", "share"} else "kind",
                    "mark": (author[:1] or "?").upper(),
                    "mark_class": "",
                    "action": None,
                    "time": stamp,
                }
            )
        else:
            stance = _act_stance_label(acts)
            mail_peek.append(
                {
                    "href": f"/p/{msg.id}",
                    "title": title,
                    "preview": f"{author} · {stance}",
                    "badge": f"Result · {stance}",
                    "mark": (author[:1] or "?").upper(),
                    "time": stamp,
                }
            )

    needs = [*ready, *enriching, *needs_act]
    return {
        "needs": needs,
        "mail_peek": mail_peek[:4],
        "holds": holds,
        "pins": pins,
    }


def _mail_rows(
    service: PidgeService, viewer: User, messages: tuple[Any, ...], *, facet: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for msg in messages:
        kind = msg.kind or "invite"
        kind_label = _kind_label(kind)
        if facet == "in":
            acts = tuple(
                a for a in service.store.list_acts(msg.id) if a.actor_user_id == viewer.id
            )
            if _message_needs_act(kind, acts):
                badge = f"{kind_label} · needs act"
                badge_class = kind if kind in {"invite", "share"} else "kind"
            else:
                badge = f"Result · {_act_stance_label(acts)}"
                badge_class = ""
            avatar = (msg.author_name or "?")[:1]
            preview = f"From {msg.author_name or 'Someone'}"
            if msg.intent:
                preview = f"{preview} · {msg.intent}"
        else:
            acts = service.store.list_acts(msg.id)
            if acts:
                badge = f"Result · {_act_stance_label(acts)}"
                badge_class = ""
            else:
                badge = f"{kind_label} · sealed"
                badge_class = kind if kind in {"invite", "share"} else "kind"
            recipients = service.store.recipients_for(msg.id)
            names = [r.display_name for r in recipients if getattr(r, "display_name", None)]
            preview = f"To {', '.join(names)}" if names else (msg.intent or "sealed")
            avatar = (msg.summary or msg.intent or "?")[:1]
        stamp = msg.sealed_at or msg.updated_at
        rows.append(
            {
                "id": msg.id,
                "href": f"/p/{msg.id}",
                "title": msg.summary or msg.intent or "Sealed Pidge",
                "preview": preview,
                "badge": badge,
                "badge_class": badge_class,
                "avatar": (avatar or "?").upper(),
                "sealed": msg.state == "sealed",
                "time": _format_desk_time(stamp),
                "time_iso": stamp.isoformat() if stamp is not None else None,
            }
        )
    return rows


def _delivery_context(service: PidgeService, msg: Any) -> dict[str, Any]:
    recipients = service.store.recipients_for(msg.id)
    names = [r.display_name for r in recipients if getattr(r, "display_name", None)]
    primary = names[0] if names else "your recipient"
    if len(names) > 1:
        hero = "On their desks"
        lead_names = ", ".join(names[:-1]) + f" and {names[-1]}"
    else:
        hero = f"On {primary}'s desk"
        lead_names = primary
    acts = service.store.list_acts(msg.id)
    waiting = "Waiting on act…" if not acts else f"Act landed · {_act_stance_label(acts)}"
    sealed_at = msg.sealed_at
    sealed_clock = sealed_at.strftime("%-I:%M:%S %p") if sealed_at else "—"
    return {
        "message": msg,
        "hero_title": hero,
        "recipient_line": lead_names,
        "kind_label": _kind_label(msg.kind or "invite"),
        "timeline": [
            {"time": sealed_clock, "text": "Drafted · intent captured"},
            {"time": sealed_clock, "text": "Enriched · sealed (who · when · where · blocks)"},
            {
                "time": sealed_clock,
                "text": f"Delivered to {lead_names}",
            },
            {"time": "—", "text": waiting},
        ],
    }


def _message_needs_act(kind: str, acts: tuple[Any, ...]) -> bool:
    kinds = {a.kind for a in acts}
    if kind == "invite":
        return not kinds.intersection({"rsvp_yes", "rsvp_no", "decline", "maybe"})
    if kind == "share":
        return not kinds.intersection({"ack", "pin"})
    return not kinds.intersection({"ack", "pin", "rsvp_yes", "rsvp_no", "decline"})


def _act_stance_label(acts: tuple[Any, ...]) -> str:
    kinds = {a.kind for a in acts}
    if "rsvp_yes" in kinds:
        return "accepted"
    if "rsvp_no" in kinds or "decline" in kinds:
        return "declined"
    if "maybe" in kinds:
        return "maybe"
    if "pin" in kinds:
        return "pinned"
    if "ack" in kinds:
        return "acked"
    return "sealed"


def _format_desk_time(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return value.strftime("%-I:%M %p")
    except (AttributeError, ValueError, TypeError):
        return None


def _people_loft_context(service: PidgeService, user: User, *, error: str | None) -> dict[str, Any]:
    people = service.directory(user)
    raw_requests = service.store.list_connection_requests(user.id)
    introductions: list[dict[str, Any]] = []
    pending_usernames: set[str] = set()
    for req in raw_requests:
        if req.to_user_id is None:
            # External address-book claims belong on Beyond, not loft intros.
            continue
        from_user = _safe_user(service, req.from_user_id)
        to_user = _safe_user(service, req.to_user_id)
        from_name = from_user.display_name if from_user else "Someone"
        to_name = to_user.display_name if to_user else "you"
        if req.from_user_id == user.id and req.status == "pending" and to_user is not None:
            pending_usernames.add(to_user.username)
        introductions.append(
            {
                "id": req.id,
                "from_name": from_name,
                "to_name": to_name if req.to_user_id != user.id else "you",
                "status": req.status,
                "can_accept": req.to_user_id == user.id and req.status == "pending",
                "inbound": req.to_user_id == user.id,
            }
        )
    return {
        "facet": "loft",
        "people": people,
        "people_count": len(people),
        "introductions": introductions,
        "pending_intro_count": sum(1 for i in introductions if i["status"] == "pending"),
        "pending_usernames": pending_usernames,
        "error": error,
    }


def _safe_user(service: PidgeService, user_id: int | None) -> User | None:
    if user_id is None:
        return None
    try:
        return service.store.get_user(user_id)
    except LookupError:
        return None


def _external_contacts(service: PidgeService, user: User):
    return tuple(c for c in service.contacts(user) if c.kind == "external")


def _people_beyond_context(
    service: PidgeService, user: User, *, error: str | None
) -> dict[str, Any]:
    contacts = _external_contacts(service, user)
    return {
        "contacts": contacts,
        "contacts_count": len(contacts),
        "error": error,
    }


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
    """Accept the canonical origin plus Railway-provided public hostnames."""
    import os

    hosts: list[str] = []
    if config.public_origin:
        host = urlparse(config.public_origin).hostname
        if host:
            hosts.append(host)
    for key in ("RAILWAY_PUBLIC_DOMAIN", "RAILWAY_STATIC_URL", "RAILWAY_SERVICE_WEB_URL"):
        raw = (os.environ.get(key) or "").strip()
        if not raw:
            continue
        if "://" in raw:
            parsed = urlparse(raw).hostname
            if parsed:
                hosts.append(parsed)
        else:
            hosts.append(raw.split("/", 1)[0])
    # De-dupe, preserve order.
    unique = tuple(dict.fromkeys(h for h in hosts if h))
    return unique or ("*",)
