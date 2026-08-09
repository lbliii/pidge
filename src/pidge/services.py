"""Application workflows for the Pidge loft."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from chirp.security.passwords import hash_password, verify_login

from pidge.config import (
    ALL_AGENT_SCOPES,
    DEFAULT_TOKEN_PRESET,
    TOKEN_PRESETS,
    PidgeConfig,
)
from pidge.models import (
    Act,
    AgentClient,
    AgentToken,
    ConnectionRequest,
    Contact,
    Flight,
    FlightStep,
    Hold,
    NotePin,
    PidgeMessage,
    PidgeRecipient,
    SealChallenge,
    User,
)
from pidge.store import Store, token_hash

SESSION_TTL = timedelta(days=30)
SEAL_CHALLENGE_TTL = timedelta(minutes=15)
USERNAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{2,31}$")
REQUIRED_SLOTS = ("who", "when", "where")
PIDGE_KINDS = frozenset({"invite", "share", "ask", "fyi", "remind", "note"})
ACTS_BY_KIND: dict[str, frozenset[str]] = {
    "invite": frozenset({"rsvp_yes", "rsvp_no", "propose_time", "decline"}),
    "share": frozenset({"ack", "pin"}),
    "ask": frozenset({"ack", "decline"}),
    "fyi": frozenset({"ack"}),
    "remind": frozenset({"ack"}),
    "note": frozenset({"pin"}),
}


@dataclass(frozen=True, slots=True)
class SetupResult:
    user: User
    session_token: str


@dataclass(frozen=True, slots=True)
class AgentTokenResult:
    token: AgentToken
    secret: str


@dataclass(frozen=True, slots=True)
class SealProposeResult:
    challenge: SealChallenge
    secret: str
    seal_url: str
    message: PidgeMessage
    recipients: tuple[PidgeRecipient, ...]


class PidgeService:
    def __init__(self, store: Store, config: PidgeConfig) -> None:
        self.store = store
        self.config = config

    # --- identity -----------------------------------------------------------

    def setup(
        self,
        *,
        bootstrap_token: str,
        loft_name: str,
        username: str,
        display_name: str,
        password: str,
    ) -> SetupResult:
        if self.store.settings() is not None:
            raise PermissionError("Loft setup is already complete.")
        if not secrets.compare_digest(bootstrap_token, self.config.bootstrap_token):
            raise PermissionError("The bootstrap token is not valid.")
        username = _validate_username(username)
        display_name = display_name.strip() or username
        _validate_password(password)
        user = self.store.bootstrap(
            loft_name=(loft_name.strip() or self.config.loft_name)[:100],
            username=username,
            display_name=display_name[:80],
            password_hash=hash_password(password),
        )
        return SetupResult(user, self._issue_session(user.id))

    def login(self, username: str, password: str) -> tuple[User, str]:
        try:
            user = self.store.get_user_by_username(username.strip().casefold())
        except LookupError:
            user = None
        verified = verify_login(password, user.password_hash if user else None)
        if not verified or user is None:
            raise PermissionError("Username or password is incorrect.")
        if user.status != "active":
            raise PermissionError("This account is suspended.")
        return user, self._issue_session(user.id)

    def register(self, *, username: str, display_name: str, password: str) -> SetupResult:
        if self.store.settings() is None:
            raise PermissionError("Loft is not set up yet.")
        username = _validate_username(username)
        display_name = display_name.strip() or username
        _validate_password(password)
        user = self.store.register_user(
            username=username,
            display_name=display_name[:80],
            password_hash=hash_password(password),
        )
        return SetupResult(user, self._issue_session(user.id))

    def current_user(self, session_token: str | None) -> User | None:
        if not session_token:
            return None
        return self.store.user_for_session(token_hash(session_token), datetime.now(UTC))

    def logout(self, session_token: str | None) -> None:
        if session_token:
            self.store.revoke_session(token_hash(session_token))

    def _issue_session(self, user_id: int) -> str:
        value = secrets.token_urlsafe(32)
        self.store.create_session(
            user_id, token_hash(value), datetime.now(UTC) + SESSION_TTL
        )
        return value

    # --- agent tokens -------------------------------------------------------

    def mint_agent_token(
        self,
        user: User,
        *,
        label: str,
        scopes: frozenset[str] | None = None,
        preset: str | None = None,
        days: int | None = 90,
        intended_harness: str | None = None,
    ) -> AgentTokenResult:
        if scopes is not None:
            chosen = frozenset(scopes)
        elif preset is not None:
            if preset not in TOKEN_PRESETS:
                raise ValueError(f"Unknown preset: {preset}")
            chosen = TOKEN_PRESETS[preset]
        else:
            chosen = TOKEN_PRESETS[DEFAULT_TOKEN_PRESET]
        unknown = chosen - ALL_AGENT_SCOPES
        if unknown:
            raise ValueError(f"Unknown scopes: {', '.join(sorted(unknown))}")
        secret = f"pidge_at_{secrets.token_urlsafe(32)}"
        expires = datetime.now(UTC) + timedelta(days=days) if days else None
        from pidge.harness import KNOWN_HARNESS_SLUGS, HARNESS_OTHER

        intent = (intended_harness or "").strip() or None
        if intent and intent not in KNOWN_HARNESS_SLUGS:
            intent = HARNESS_OTHER
        token = self.store.create_agent_token(
            user_id=user.id,
            token_hash_value=token_hash(secret),
            label=(label.strip() or "Agent")[:80],
            scopes=chosen,
            expires_at=expires,
            intended_harness=intent,
        )
        return AgentTokenResult(token, secret)

    def list_agent_tokens(self, user: User) -> tuple[AgentToken, ...]:
        return self.store.list_agent_tokens(user.id)

    def revoke_agent_token(self, user: User, token_id: int) -> None:
        self.store.revoke_agent_token(user.id, token_id)

    def verify_agent_token(
        self,
        raw_token: str,
        *,
        client_name: str | None = None,
        client_version: str | None = None,
        user_agent: str | None = None,
    ) -> AgentClient | None:
        now = datetime.now(UTC)
        found = self.store.agent_client_for_token(token_hash(raw_token), now)
        if found is None:
            return None
        client, token_id = found
        harness_kwargs: dict[str, str] = {}
        if client_name or client_version or user_agent:
            from pidge.harness import normalize_harness

            slug, name, version = normalize_harness(
                client_name=client_name,
                client_version=client_version,
                user_agent=user_agent,
            )
            harness_kwargs["last_harness"] = slug
            if name:
                harness_kwargs["last_client_name"] = name
            if version:
                harness_kwargs["last_client_version"] = version
        self.store.touch_agent_token(token_id, now, **harness_kwargs)
        return client

    def record_agent_harness(
        self,
        token_id: int,
        *,
        client_name: str | None = None,
        client_version: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Update harness attribution for an already-authenticated agent token."""
        from pidge.harness import normalize_harness

        slug, name, version = normalize_harness(
            client_name=client_name,
            client_version=client_version,
            user_agent=user_agent,
        )
        kwargs: dict[str, str] = {"last_harness": slug}
        if name:
            kwargs["last_client_name"] = name
        if version:
            kwargs["last_client_version"] = version
        self.store.touch_agent_token(token_id, datetime.now(UTC), **kwargs)

    def agent_token_revoked(self, token_id: int) -> bool:
        return self.store.is_agent_token_revoked(token_id)

    # --- addressing ---------------------------------------------------------

    def directory(self, viewer: User) -> tuple[User, ...]:
        return tuple(u for u in self.store.list_users() if u.id != viewer.id)

    def contacts(self, viewer: User) -> tuple[Contact, ...]:
        return self.store.list_contacts(viewer.id)

    def add_external_contact(self, viewer: User, *, handle: str, display_name: str) -> Contact:
        handle = handle.strip()
        if not handle:
            raise ValueError("External handle is required.")
        name = display_name.strip() or handle
        self.store.create_connection_request(
            ConnectionRequest(
                id=0,
                from_user_id=viewer.id,
                to_user_id=None,
                external_handle=handle,
                status="pending",
                claim_token_hash=token_hash(secrets.token_urlsafe(24)),
                created_at=datetime.now(UTC),
            )
        )
        return self.store.add_contact(
            Contact(
                id=0,
                owner_user_id=viewer.id,
                kind="external",
                status="pending",
                display_name=name[:80],
                external_handle=handle[:120],
            )
        )

    def request_loft_connection(self, viewer: User, *, username: str) -> ConnectionRequest:
        target = self.store.get_user_by_username(username.strip().casefold())
        if target.id == viewer.id:
            raise ValueError("You are already in the loft.")
        return self.store.create_connection_request(
            ConnectionRequest(
                id=0,
                from_user_id=viewer.id,
                to_user_id=target.id,
                external_handle=None,
                status="pending",
                claim_token_hash=None,
                created_at=datetime.now(UTC),
            )
        )

    def accept_connection(self, viewer: User, request_id: int) -> Contact:
        return self.store.accept_connection_request(request_id, viewer.id)

    def can_address(
        self, sender: User, *, loft_user_id: int | None = None, contact_id: int | None = None
    ) -> bool:
        if loft_user_id is not None:
            # Same loft: any active user is addressable without a friend edge.
            try:
                user = self.store.get_user(loft_user_id)
            except LookupError:
                return False
            return user.status == "active" and user.id != sender.id
        if contact_id is not None:
            try:
                contact = self.store.get_contact(contact_id)
            except LookupError:
                return False
            return (
                contact.owner_user_id == sender.id
                and contact.status in {"accepted", "pending"}
                and contact.kind == "external"
            )
        return False

    def resolve_target_name(self, sender: User, name: str) -> PidgeRecipient:
        needle = name.strip()
        if not needle:
            raise ValueError("Recipient name is required.")
        # Prefer loft directory match
        for user in self.store.list_users():
            if user.id == sender.id:
                continue
            if user.username.casefold() == needle.casefold() or user.display_name.casefold() == needle.casefold():
                return PidgeRecipient(
                    id=0,
                    pidge_id=0,
                    role="to",
                    loft_user_id=user.id,
                    display_name=user.display_name,
                )
        for contact in self.store.list_contacts(sender.id):
            if contact.status == "blocked":
                continue
            if contact.display_name.casefold() == needle.casefold() or (
                contact.external_handle and contact.external_handle.casefold() == needle.casefold()
            ):
                if contact.kind == "loft_user" and contact.loft_user_id:
                    return PidgeRecipient(
                        id=0,
                        pidge_id=0,
                        role="to",
                        loft_user_id=contact.loft_user_id,
                        display_name=contact.display_name,
                    )
                if contact.kind == "external" and contact.status in {"accepted", "pending"}:
                    return PidgeRecipient(
                        id=0,
                        pidge_id=0,
                        role="to",
                        contact_id=contact.id,
                        display_name=contact.display_name,
                    )
        raise LookupError(f"No addressable person named {needle!r}.")

    # --- mail ---------------------------------------------------------------

    def draft_pidge(
        self,
        author: User,
        *,
        intent: str,
        recipient_names: list[str],
        summary: str = "",
        kind: str = "invite",
    ) -> PidgeMessage:
        intent = intent.strip()
        if not intent:
            raise ValueError("Intent is required.")
        if not recipient_names:
            raise ValueError("At least one recipient is required.")
        kind = _validate_kind(kind)
        recipients = [self.resolve_target_name(author, name) for name in recipient_names]
        for recipient in recipients:
            if not self.can_address(
                author,
                loft_user_id=recipient.loft_user_id,
                contact_id=recipient.contact_id,
            ):
                raise PermissionError(f"Cannot address {recipient.display_name}.")
        slots: dict[str, Any] = {
            "who": {"status": "pending", "value": None},
            "when": {"status": "pending", "value": None},
            "where": {"status": "pending", "value": None},
        }
        msg = self.store.create_pidge(
            PidgeMessage(
                id=0,
                author_id=author.id,
                state="draft",
                summary=summary.strip() or intent[:140],
                intent=intent,
                slots=slots,
                content_hash=None,
                sealed_at=None,
                seal_user_id=None,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                kind=kind,
            ),
            recipients,
        )
        steps = [
            FlightStep(0, 0, "who", "Resolve recipients", ", ".join(r.display_name for r in recipients), "pending", 0),
            FlightStep(0, 0, "when", "Parse time", "pending", "pending", 1),
            FlightStep(0, 0, "where", "Find place", "pending", "pending", 2),
            FlightStep(0, 0, "extras", "Gather extras", "pending", "pending", 3),
        ]
        self.store.create_flight(Flight(0, msg.id, "pending", datetime.now(UTC)), steps)
        return msg

    def enrich_pidge(
        self,
        author: User,
        pidge_id: int,
        *,
        who: str | None = None,
        when: str | None = None,
        where: str | None = None,
        extras: dict[str, Any] | None = None,
        mark_none: tuple[str, ...] = (),
    ) -> PidgeMessage:
        msg = self.store.get_pidge(pidge_id)
        if msg.author_id != author.id:
            raise PermissionError("Not your draft.")
        if msg.state != "draft":
            raise PermissionError("Only drafts can be enriched.")
        slots = dict(msg.slots)
        flight = self.store.get_flight_for_pidge(pidge_id)
        if flight and flight.state == "pending":
            self.store.set_flight_state(flight.id, "flying")

        def _set(key: str, value: Any | None, *, none: bool = False) -> None:
            if none:
                slots[key] = {"status": "none", "value": None}
            elif value is not None:
                slots[key] = {"status": "ready", "value": value}

        _set("who", who, none="who" in mark_none)
        _set("when", when, none="when" in mark_none)
        _set("where", where, none="where" in mark_none)
        if extras:
            slots["extras"] = {"status": "ready", "value": _normalize_extras(extras)}

        if flight:
            for step in self.store.list_flight_steps(flight.id):
                slot = slots.get(step.key)
                if isinstance(slot, dict) and slot.get("status") in {"ready", "none"}:
                    detail = "none" if slot["status"] == "none" else str(slot.get("value") or "")
                    self.store.set_flight_step_state(step.id, "done", detail=detail)
            if all(
                isinstance(slots.get(k), dict) and slots[k].get("status") in {"ready", "none"}
                for k in REQUIRED_SLOTS
            ):
                self.store.set_flight_state(flight.id, "done")

        summary = msg.summary
        if who or when or where:
            parts = [p for p in (who, when, where) if p]
            if parts:
                summary = " · ".join(parts)[:200]
        return self.store.update_pidge_slots(pidge_id, summary=summary, slots=slots)

    def ready_to_seal(self, user: User, pidge_id: int) -> PidgeMessage:
        """Shared precheck for UI seal and propose_seal / challenge redeem."""
        msg = self.store.get_pidge(pidge_id)
        if msg.author_id != user.id:
            raise PermissionError("Only the author can seal this Pidge.")
        if msg.state != "draft":
            raise PermissionError("Only drafts can be sealed.")
        for key in REQUIRED_SLOTS:
            slot = msg.slots.get(key)
            if not isinstance(slot, dict) or slot.get("status") not in {"ready", "none"}:
                raise ValueError(f"Slot {key!r} must be filled or marked none before seal.")
        return msg

    def seal_pidge(self, user: User, pidge_id: int) -> PidgeMessage:
        self.ready_to_seal(user, pidge_id)
        sealed = self.store.seal_pidge(pidge_id, user.id, datetime.now(UTC))
        # Auto-confirm calendar hold for author when when/where present
        when_slot = sealed.slots.get("when", {})
        where_slot = sealed.slots.get("where", {})
        if isinstance(when_slot, dict) and when_slot.get("status") == "ready":
            self.store.create_hold(
                Hold(
                    id=0,
                    pidge_id=sealed.id,
                    owner_user_id=user.id,
                    title=sealed.summary or sealed.intent[:80],
                    starts_at=str(when_slot.get("value")),
                    place=(
                        str(where_slot.get("value"))
                        if isinstance(where_slot, dict) and where_slot.get("status") == "ready"
                        else None
                    ),
                    state="confirmed",
                    created_at=datetime.now(UTC),
                )
            )
        return sealed

    def propose_seal(
        self,
        user: User,
        pidge_id: int,
        *,
        agent_token_id: int | None = None,
        public_origin: str | None = None,
    ) -> SealProposeResult:
        msg = self.ready_to_seal(user, pidge_id)
        origin = self._resolve_public_origin(public_origin)
        secret = f"pidge_sc_{secrets.token_urlsafe(32)}"
        now = datetime.now(UTC)
        challenge = self.store.create_seal_challenge(
            token_hash_value=token_hash(secret),
            pidge_id=pidge_id,
            author_user_id=user.id,
            created_by_token_id=agent_token_id,
            expires_at=now + SEAL_CHALLENGE_TTL,
        )
        seal_url = f"{origin}/compose/{pidge_id}/seal-challenge/{secret}"
        return SealProposeResult(
            challenge=challenge,
            secret=secret,
            seal_url=seal_url,
            message=msg,
            recipients=self.store.recipients_for(pidge_id),
        )

    def load_seal_challenge(
        self, user: User, pidge_id: int, secret: str
    ) -> SealChallenge:
        """Validate a challenge for human preview (does not consume)."""
        challenge = self.store.get_seal_challenge_by_hash(token_hash(secret))
        if challenge is None:
            raise LookupError("Seal challenge not found.")
        if challenge.pidge_id != pidge_id:
            raise PermissionError("Seal challenge does not match this draft.")
        if challenge.author_user_id != user.id:
            raise PermissionError("Only the author can redeem this seal challenge.")
        now = datetime.now(UTC)
        if challenge.consumed_at is not None:
            raise PermissionError("This seal challenge was already used.")
        if challenge.expires_at <= now:
            raise PermissionError("This seal challenge has expired.")
        msg = self.store.get_pidge(pidge_id)
        if msg.author_id != user.id:
            raise PermissionError("Only the author can redeem this seal challenge.")
        return challenge

    def redeem_seal_challenge(self, user: User, pidge_id: int, secret: str) -> PidgeMessage:
        challenge = self.load_seal_challenge(user, pidge_id, secret)
        self.ready_to_seal(user, challenge.pidge_id)
        consumed = self.store.consume_seal_challenge(token_hash(secret), datetime.now(UTC))
        if consumed is None:
            raise PermissionError("This seal challenge was already used or expired.")
        return self.seal_pidge(user, challenge.pidge_id)

    def _resolve_public_origin(self, override: str | None = None) -> str:
        origin = (override or self.config.public_origin or "").strip().rstrip("/")
        if origin:
            return origin
        if self.config.production:
            raise RuntimeError(
                "PIDGE_PUBLIC_ORIGIN is required to build seal challenge URLs."
            )
        return "http://127.0.0.1:8000"

    def discard_pidge(self, user: User, pidge_id: int) -> PidgeMessage:
        msg = self.store.get_pidge(pidge_id)
        if msg.author_id != user.id:
            raise PermissionError("Only the author can discard this draft.")
        if msg.state != "draft":
            raise PermissionError("Only drafts can be discarded.")
        return self.store.discard_pidge(pidge_id, datetime.now(UTC))

    def revoke_sealed_pidge(self, user: User, pidge_id: int) -> PidgeMessage:
        """Author-only revoke of a sealed Pidge (session UI). Preserves content_hash."""
        msg = self.store.get_pidge(pidge_id)
        if msg.author_id != user.id:
            raise PermissionError("Only the author can revoke this Pidge.")
        if msg.state != "sealed":
            raise PermissionError("Only sealed Pidges can be revoked.")
        return self.store.revoke_sealed_pidge(pidge_id, datetime.now(UTC))

    def supersede_pidge(self, user: User, pidge_id: int) -> PidgeMessage:
        """Mark sealed as superseded; return a new draft linked via supersedes_id."""
        msg = self.store.get_pidge(pidge_id)
        if msg.author_id != user.id:
            raise PermissionError("Only the author can supersede this Pidge.")
        if msg.state != "sealed":
            raise PermissionError("Only sealed Pidges can be superseded.")
        _prior, draft = self.store.supersede_pidge(pidge_id, datetime.now(UTC))
        recipients = self.store.recipients_for(draft.id)
        steps = [
            FlightStep(
                0,
                0,
                "who",
                "Resolve recipients",
                ", ".join(r.display_name for r in recipients),
                "pending",
                0,
            ),
            FlightStep(0, 0, "when", "Parse time", "pending", "pending", 1),
            FlightStep(0, 0, "where", "Find place", "pending", "pending", 2),
            FlightStep(0, 0, "extras", "Gather extras", "pending", "pending", 3),
        ]
        self.store.create_flight(Flight(0, draft.id, "pending", datetime.now(UTC)), steps)
        return draft

    def get_pidge_for(self, user: User, pidge_id: int) -> PidgeMessage:
        msg = self.store.get_pidge(pidge_id)
        if msg.author_id == user.id:
            return msg
        if any(r.loft_user_id == user.id for r in self.store.recipients_for(pidge_id)):
            if msg.state != "sealed":
                raise PermissionError("Draft not visible to recipients.")
            return msg
        raise PermissionError("Not allowed to view this Pidge.")

    def record_act(self, user: User, pidge_id: int, kind: str, payload: dict[str, Any] | None = None) -> Act:
        msg = self.get_pidge_for(user, pidge_id)
        if msg.state != "sealed":
            raise PermissionError("Acts apply to sealed Pidges only.")
        allowed = ACTS_BY_KIND.get(msg.kind, ACTS_BY_KIND["invite"])
        if kind not in allowed:
            raise ValueError(f"Unknown act {kind!r} for kind {msg.kind!r}.")
        return self.store.add_act(
            Act(
                id=0,
                pidge_id=pidge_id,
                actor_user_id=user.id,
                kind=kind,
                payload=payload or {},
                created_at=datetime.now(UTC),
            )
        )

    def propose_hold(
        self,
        user: User,
        pidge_id: int,
        *,
        title: str,
        starts_at: str | None = None,
        place: str | None = None,
    ) -> Hold:
        msg = self.store.get_pidge(pidge_id)
        if msg.author_id != user.id and msg.state != "sealed":
            raise PermissionError("Cannot propose a hold for this Pidge.")
        return self.store.create_hold(
            Hold(
                id=0,
                pidge_id=pidge_id,
                owner_user_id=user.id,
                title=(title.strip() or msg.summary or "Hold")[:120],
                starts_at=starts_at,
                place=place,
                state="proposed",
                created_at=datetime.now(UTC),
            )
        )

    def pin_note(self, user: User, pidge_id: int, title: str | None = None) -> NotePin:
        msg = self.get_pidge_for(user, pidge_id)
        if msg.state != "sealed":
            raise PermissionError("Only sealed Pidges can be pinned.")
        return self.store.pin_note(
            NotePin(
                id=0,
                owner_user_id=user.id,
                pidge_id=pidge_id,
                title=(title or msg.summary or msg.intent)[:120],
                created_at=datetime.now(UTC),
            )
        )


def _validate_username(value: str) -> str:
    username = value.strip()
    if not USERNAME_RE.fullmatch(username):
        raise ValueError(
            "Usernames must be 3-32 characters and use letters, numbers, dots, dashes, or underscores."
        )
    return username


def _validate_password(password: str) -> None:
    if len(password) < 10:
        raise ValueError("Password must be at least 10 characters.")


def _validate_kind(kind: str) -> str:
    value = (kind or "invite").strip().casefold()
    if value not in PIDGE_KINDS:
        raise ValueError(f"Unknown kind {kind!r}.")
    return value


def _normalize_extras(extras: dict[str, Any]) -> dict[str, Any]:
    """Light-validate extras.blocks; preserve unknown block types and other keys."""
    out = dict(extras)
    if "blocks" not in out:
        return out
    blocks = out["blocks"]
    if not isinstance(blocks, list):
        raise ValueError("extras.blocks must be a list")
    normalized: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            raise ValueError("each extras.blocks item must be a dict")
        block_type = block.get("type")
        if not isinstance(block_type, str) or not block_type.strip():
            raise ValueError("each block must have a string type")
        normalized.append(dict(block))
    out["blocks"] = normalized
    return out
