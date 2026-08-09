"""Postgres persistence and an in-memory test implementation."""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime
from typing import Any, Protocol

from pidge.models import (
    Act,
    AgentClient,
    AgentToken,
    ConnectionRequest,
    Contact,
    Flight,
    FlightStep,
    Hold,
    LoftSettings,
    NotePin,
    PidgeMessage,
    PidgeRecipient,
    SealChallenge,
    User,
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS loft_settings (
    singleton_id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (singleton_id = 1),
    name TEXT NOT NULL,
    setup_completed_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL,
    normalized_username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member'
        CHECK (role IN ('owner', 'member')),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'suspended')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_sessions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS agent_tokens (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    scopes TEXT[] NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    intended_harness TEXT,
    last_harness TEXT,
    last_client_name TEXT,
    last_client_version TEXT
);

CREATE TABLE IF NOT EXISTS contacts (
    id BIGSERIAL PRIMARY KEY,
    owner_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('loft_user', 'external')),
    status TEXT NOT NULL CHECK (status IN ('pending', 'accepted', 'blocked')),
    display_name TEXT NOT NULL,
    loft_user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    external_handle TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (owner_user_id, loft_user_id),
    UNIQUE (owner_user_id, external_handle)
);

CREATE TABLE IF NOT EXISTS connection_requests (
    id BIGSERIAL PRIMARY KEY,
    from_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    to_user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    external_handle TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'accepted', 'declined')),
    claim_token_hash TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pidges (
    id BIGSERIAL PRIMARY KEY,
    author_id BIGINT NOT NULL REFERENCES users(id),
    state TEXT NOT NULL CHECK (state IN ('draft', 'sealed', 'revoked', 'superseded')),
    summary TEXT NOT NULL DEFAULT '',
    intent TEXT NOT NULL DEFAULT '',
    slots JSONB NOT NULL DEFAULT '{}'::jsonb,
    content_hash TEXT,
    sealed_at TIMESTAMPTZ,
    seal_user_id BIGINT REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    supersedes_id BIGINT REFERENCES pidges(id),
    kind TEXT NOT NULL DEFAULT 'invite'
        CHECK (kind IN ('invite', 'share', 'ask', 'fyi', 'remind', 'note'))
);

CREATE TABLE IF NOT EXISTS pidge_recipients (
    id BIGSERIAL PRIMARY KEY,
    pidge_id BIGINT NOT NULL REFERENCES pidges(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'to',
    loft_user_id BIGINT REFERENCES users(id),
    contact_id BIGINT REFERENCES contacts(id),
    display_name TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS flights (
    id BIGSERIAL PRIMARY KEY,
    pidge_id BIGINT NOT NULL REFERENCES pidges(id) ON DELETE CASCADE,
    state TEXT NOT NULL CHECK (state IN ('pending', 'flying', 'done')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS flight_steps (
    id BIGSERIAL PRIMARY KEY,
    flight_id BIGINT NOT NULL REFERENCES flights(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    label TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL CHECK (state IN ('pending', 'active', 'done')),
    position INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS acts (
    id BIGSERIAL PRIMARY KEY,
    pidge_id BIGINT NOT NULL REFERENCES pidges(id) ON DELETE CASCADE,
    actor_user_id BIGINT NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS holds (
    id BIGSERIAL PRIMARY KEY,
    pidge_id BIGINT NOT NULL REFERENCES pidges(id) ON DELETE CASCADE,
    owner_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    starts_at TEXT,
    place TEXT,
    state TEXT NOT NULL CHECK (state IN ('proposed', 'confirmed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS note_pins (
    id BIGSERIAL PRIMARY KEY,
    owner_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    pidge_id BIGINT NOT NULL REFERENCES pidges(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (owner_user_id, pidge_id)
);

CREATE TABLE IF NOT EXISTS seal_challenges (
    id BIGSERIAL PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    pidge_id BIGINT NOT NULL REFERENCES pidges(id) ON DELETE CASCADE,
    author_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_by_token_id BIGINT REFERENCES agent_tokens(id) ON DELETE SET NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sessions_token ON user_sessions(token_hash, revoked_at);
CREATE INDEX IF NOT EXISTS idx_agent_tokens_hash ON agent_tokens(token_hash, revoked_at);
CREATE INDEX IF NOT EXISTS idx_pidges_author_state ON pidges(author_id, state, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_recipients_user ON pidge_recipients(loft_user_id, pidge_id);
CREATE INDEX IF NOT EXISTS idx_seal_challenges_hash ON seal_challenges(token_hash);
"""


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def content_hash(summary: str, slots: dict[str, Any]) -> str:
    payload = json.dumps({"summary": summary, "slots": slots}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _agent_token_from_row(row: tuple[Any, ...]) -> AgentToken:
    """Map a 12-column agent_tokens SELECT/RETURNING row to AgentToken."""
    return AgentToken(
        id=row[0],
        user_id=row[1],
        label=row[2],
        scopes=frozenset(row[3]),
        created_at=row[4],
        expires_at=row[5],
        revoked_at=row[6],
        last_used_at=row[7],
        intended_harness=row[8],
        last_harness=row[9],
        last_client_name=row[10],
        last_client_version=row[11],
    )

class Store(Protocol):
    def close(self) -> None: ...
    def migrate(self) -> None: ...
    def probe(self) -> bool: ...
    def settings(self) -> LoftSettings | None: ...
    def bootstrap(
        self,
        *,
        loft_name: str,
        username: str,
        display_name: str,
        password_hash: str,
    ) -> User: ...
    def register_user(
        self, *, username: str, display_name: str, password_hash: str
    ) -> User: ...
    def get_user(self, user_id: int) -> User: ...
    def get_user_by_username(self, normalized_username: str) -> User: ...
    def list_users(self) -> tuple[User, ...]: ...
    def create_session(self, user_id: int, token_hash_value: str, expires_at: datetime) -> None: ...
    def user_for_session(self, token_hash_value: str, now: datetime) -> User | None: ...
    def revoke_session(self, token_hash_value: str) -> None: ...
    def create_agent_token(
        self,
        *,
        user_id: int,
        token_hash_value: str,
        label: str,
        scopes: frozenset[str],
        expires_at: datetime | None,
        intended_harness: str | None = None,
    ) -> AgentToken: ...
    def list_agent_tokens(self, user_id: int) -> tuple[AgentToken, ...]: ...
    def revoke_agent_token(self, user_id: int, token_id: int) -> None: ...
    def agent_client_for_token(self, token_hash_value: str, now: datetime) -> tuple[AgentClient, int] | None: ...
    def touch_agent_token(
        self,
        token_id: int,
        now: datetime,
        *,
        last_harness: str | None = None,
        last_client_name: str | None = None,
        last_client_version: str | None = None,
    ) -> None: ...
    def is_agent_token_revoked(self, token_id: int) -> bool: ...
    def list_contacts(self, owner_user_id: int) -> tuple[Contact, ...]: ...
    def get_contact(self, contact_id: int) -> Contact: ...
    def add_contact(self, contact: Contact) -> Contact: ...
    def update_contact_status(self, contact_id: int, status: str) -> Contact: ...
    def create_connection_request(self, req: ConnectionRequest) -> ConnectionRequest: ...
    def list_connection_requests(self, user_id: int) -> tuple[ConnectionRequest, ...]: ...
    def accept_connection_request(self, request_id: int, user_id: int) -> Contact: ...
    def create_pidge(self, msg: PidgeMessage, recipients: list[PidgeRecipient]) -> PidgeMessage: ...
    def update_pidge_slots(
        self, pidge_id: int, *, summary: str, slots: dict[str, Any], intent: str | None = None
    ) -> PidgeMessage: ...
    def seal_pidge(self, pidge_id: int, seal_user_id: int, now: datetime) -> PidgeMessage: ...
    def discard_pidge(self, pidge_id: int, now: datetime) -> PidgeMessage: ...
    def revoke_sealed_pidge(self, pidge_id: int, now: datetime) -> PidgeMessage: ...
    def supersede_pidge(
        self, pidge_id: int, now: datetime
    ) -> tuple[PidgeMessage, PidgeMessage]: ...
    def get_pidge(self, pidge_id: int) -> PidgeMessage: ...
    def list_drafts(self, author_id: int) -> tuple[PidgeMessage, ...]: ...
    def list_inbox(self, user_id: int) -> tuple[PidgeMessage, ...]: ...
    def list_sent(self, author_id: int) -> tuple[PidgeMessage, ...]: ...
    def recipients_for(self, pidge_id: int) -> tuple[PidgeRecipient, ...]: ...
    def create_flight(self, flight: Flight, steps: list[FlightStep]) -> Flight: ...
    def get_flight_for_pidge(self, pidge_id: int) -> Flight | None: ...
    def list_flight_steps(self, flight_id: int) -> tuple[FlightStep, ...]: ...
    def set_flight_state(self, flight_id: int, state: str) -> None: ...
    def set_flight_step_state(self, step_id: int, state: str, detail: str | None = None) -> FlightStep: ...
    def add_act(self, act: Act) -> Act: ...
    def list_acts(self, pidge_id: int) -> tuple[Act, ...]: ...
    def create_hold(self, hold: Hold) -> Hold: ...
    def list_holds(self, owner_user_id: int) -> tuple[Hold, ...]: ...
    def confirm_hold(self, hold_id: int, owner_user_id: int) -> Hold: ...
    def pin_note(self, pin: NotePin) -> NotePin: ...
    def list_pins(self, owner_user_id: int) -> tuple[NotePin, ...]: ...
    def create_seal_challenge(
        self,
        *,
        token_hash_value: str,
        pidge_id: int,
        author_user_id: int,
        created_by_token_id: int | None,
        expires_at: datetime,
    ) -> SealChallenge: ...
    def get_seal_challenge_by_hash(self, token_hash_value: str) -> SealChallenge | None: ...
    def consume_seal_challenge(
        self, token_hash_value: str, now: datetime
    ) -> SealChallenge | None: ...


def store_from_url(database_url: str | None) -> Store:
    if database_url:
        return PostgresStore(database_url)
    return MemoryStore()


class MemoryStore:
    """Thread-safe in-memory store for tests and local dogfood without Postgres."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._settings: LoftSettings | None = None
        self._users: dict[int, User] = {}
        self._by_username: dict[str, int] = {}
        self._sessions: dict[str, tuple[int, datetime, datetime | None]] = {}
        self._agent_tokens: dict[int, dict[str, Any]] = {}
        self._agent_by_hash: dict[str, int] = {}
        self._contacts: dict[int, Contact] = {}
        self._requests: dict[int, ConnectionRequest] = {}
        self._pidges: dict[int, PidgeMessage] = {}
        self._recipients: dict[int, list[PidgeRecipient]] = {}
        self._flights: dict[int, Flight] = {}
        self._flight_by_pidge: dict[int, int] = {}
        self._steps: dict[int, list[FlightStep]] = {}
        self._acts: dict[int, list[Act]] = {}
        self._holds: dict[int, Hold] = {}
        self._pins: dict[int, NotePin] = {}
        self._seal_challenges: dict[int, SealChallenge] = {}
        self._seal_by_hash: dict[str, int] = {}
        self._ids = {
            "user": 0,
            "contact": 0,
            "request": 0,
            "pidge": 0,
            "recipient": 0,
            "flight": 0,
            "step": 0,
            "act": 0,
            "hold": 0,
            "pin": 0,
            "agent": 0,
            "seal_challenge": 0,
        }

    def close(self) -> None:
        return None

    def migrate(self) -> None:
        return None

    def probe(self) -> bool:
        return True

    def _next(self, key: str) -> int:
        self._ids[key] += 1
        return self._ids[key]

    def settings(self) -> LoftSettings | None:
        return self._settings

    def bootstrap(
        self,
        *,
        loft_name: str,
        username: str,
        display_name: str,
        password_hash: str,
    ) -> User:
        with self._lock:
            if self._settings is not None:
                raise PermissionError("Loft setup is already complete.")
            user = self._create_user(
                username=username,
                display_name=display_name,
                password_hash=password_hash,
                role="owner",
            )
            self._settings = LoftSettings(name=loft_name, setup_completed_at=datetime.now(UTC))
            return user

    def register_user(
        self, *, username: str, display_name: str, password_hash: str
    ) -> User:
        with self._lock:
            if self._settings is None:
                raise PermissionError("Loft is not set up yet.")
            return self._create_user(
                username=username,
                display_name=display_name,
                password_hash=password_hash,
                role="member",
            )

    def _create_user(
        self,
        *,
        username: str,
        display_name: str,
        password_hash: str,
        role: str,
    ) -> User:
        normalized = username.casefold()
        if normalized in self._by_username:
            raise ValueError("That username is already taken.")
        user_id = self._next("user")
        user = User(
            id=user_id,
            username=username,
            display_name=display_name,
            password_hash=password_hash,
            role=role,
            status="active",
            created_at=datetime.now(UTC),
        )
        self._users[user_id] = user
        self._by_username[normalized] = user_id
        return user

    def get_user(self, user_id: int) -> User:
        with self._lock:
            try:
                return self._users[user_id]
            except KeyError as exc:
                raise LookupError(user_id) from exc

    def get_user_by_username(self, normalized_username: str) -> User:
        with self._lock:
            user_id = self._by_username.get(normalized_username.casefold())
            if user_id is None:
                raise LookupError(normalized_username)
            return self._users[user_id]

    def list_users(self) -> tuple[User, ...]:
        with self._lock:
            return tuple(sorted(self._users.values(), key=lambda u: u.username.lower()))

    def create_session(self, user_id: int, token_hash_value: str, expires_at: datetime) -> None:
        with self._lock:
            self._sessions[token_hash_value] = (user_id, expires_at, None)

    def user_for_session(self, token_hash_value: str, now: datetime) -> User | None:
        with self._lock:
            row = self._sessions.get(token_hash_value)
            if row is None:
                return None
            user_id, expires_at, revoked_at = row
            if revoked_at is not None or expires_at <= now:
                return None
            return self._users.get(user_id)

    def revoke_session(self, token_hash_value: str) -> None:
        with self._lock:
            row = self._sessions.get(token_hash_value)
            if row is None:
                return
            user_id, expires_at, _ = row
            self._sessions[token_hash_value] = (user_id, expires_at, datetime.now(UTC))

    def create_agent_token(
        self,
        *,
        user_id: int,
        token_hash_value: str,
        label: str,
        scopes: frozenset[str],
        expires_at: datetime | None,
        intended_harness: str | None = None,
    ) -> AgentToken:
        with self._lock:
            token_id = self._next("agent")
            now = datetime.now(UTC)
            token = AgentToken(
                id=token_id,
                user_id=user_id,
                label=label,
                scopes=scopes,
                created_at=now,
                expires_at=expires_at,
                revoked_at=None,
                intended_harness=intended_harness,
            )
            self._agent_tokens[token_id] = {
                "token": token,
                "hash": token_hash_value,
            }
            self._agent_by_hash[token_hash_value] = token_id
            return token

    def list_agent_tokens(self, user_id: int) -> tuple[AgentToken, ...]:
        with self._lock:
            return tuple(
                entry["token"]
                for entry in self._agent_tokens.values()
                if entry["token"].user_id == user_id
            )

    def revoke_agent_token(self, user_id: int, token_id: int) -> None:
        from dataclasses import replace

        with self._lock:
            entry = self._agent_tokens.get(token_id)
            if entry is None or entry["token"].user_id != user_id:
                raise LookupError(token_id)
            token = entry["token"]
            entry["token"] = replace(token, revoked_at=datetime.now(UTC))

    def agent_client_for_token(
        self, token_hash_value: str, now: datetime
    ) -> tuple[AgentClient, int] | None:
        with self._lock:
            token_id = self._agent_by_hash.get(token_hash_value)
            if token_id is None:
                return None
            token: AgentToken = self._agent_tokens[token_id]["token"]
            if token.revoked_at is not None:
                return None
            if token.expires_at is not None and token.expires_at <= now:
                return None
            client = AgentClient(
                id=f"agent:{token.id}",
                owner_user_id=token.user_id,
                scopes=token.scopes,
                token_id=token.id,
            )
            return client, token.id

    def touch_agent_token(
        self,
        token_id: int,
        now: datetime,
        *,
        last_harness: str | None = None,
        last_client_name: str | None = None,
        last_client_version: str | None = None,
    ) -> None:
        from dataclasses import replace

        with self._lock:
            entry = self._agent_tokens.get(token_id)
            if entry is None:
                return
            token = entry["token"]
            updates: dict[str, Any] = {"last_used_at": now}
            if last_harness is not None:
                updates["last_harness"] = last_harness
            if last_client_name is not None:
                updates["last_client_name"] = last_client_name
            if last_client_version is not None:
                updates["last_client_version"] = last_client_version
            entry["token"] = replace(token, **updates)

    def is_agent_token_revoked(self, token_id: int) -> bool:
        with self._lock:
            entry = self._agent_tokens.get(token_id)
            return entry is None or entry["token"].revoked_at is not None

    def list_contacts(self, owner_user_id: int) -> tuple[Contact, ...]:
        with self._lock:
            return tuple(
                c for c in self._contacts.values() if c.owner_user_id == owner_user_id
            )

    def get_contact(self, contact_id: int) -> Contact:
        with self._lock:
            try:
                return self._contacts[contact_id]
            except KeyError as exc:
                raise LookupError(contact_id) from exc

    def add_contact(self, contact: Contact) -> Contact:
        with self._lock:
            contact_id = self._next("contact")
            saved = Contact(
                id=contact_id,
                owner_user_id=contact.owner_user_id,
                kind=contact.kind,
                status=contact.status,
                display_name=contact.display_name,
                loft_user_id=contact.loft_user_id,
                external_handle=contact.external_handle,
                created_at=datetime.now(UTC),
            )
            self._contacts[contact_id] = saved
            return saved

    def update_contact_status(self, contact_id: int, status: str) -> Contact:
        with self._lock:
            contact = self._contacts[contact_id]
            updated = Contact(
                id=contact.id,
                owner_user_id=contact.owner_user_id,
                kind=contact.kind,
                status=status,
                display_name=contact.display_name,
                loft_user_id=contact.loft_user_id,
                external_handle=contact.external_handle,
                created_at=contact.created_at,
            )
            self._contacts[contact_id] = updated
            return updated

    def create_connection_request(self, req: ConnectionRequest) -> ConnectionRequest:
        with self._lock:
            request_id = self._next("request")
            saved = ConnectionRequest(
                id=request_id,
                from_user_id=req.from_user_id,
                to_user_id=req.to_user_id,
                external_handle=req.external_handle,
                status="pending",
                claim_token_hash=req.claim_token_hash,
                created_at=datetime.now(UTC),
            )
            self._requests[request_id] = saved
            return saved

    def list_connection_requests(self, user_id: int) -> tuple[ConnectionRequest, ...]:
        with self._lock:
            return tuple(
                r
                for r in self._requests.values()
                if r.from_user_id == user_id or r.to_user_id == user_id
            )

    def accept_connection_request(self, request_id: int, user_id: int) -> Contact:
        with self._lock:
            req = self._requests[request_id]
            if req.to_user_id != user_id or req.status != "pending":
                raise PermissionError("Cannot accept this connection request.")
            self._requests[request_id] = ConnectionRequest(
                id=req.id,
                from_user_id=req.from_user_id,
                to_user_id=req.to_user_id,
                external_handle=req.external_handle,
                status="accepted",
                claim_token_hash=req.claim_token_hash,
                created_at=req.created_at,
            )
            other = self._users[req.from_user_id]
            me = self._users[user_id]
            # Mutual loft contacts
            a = self.add_contact(
                Contact(
                    id=0,
                    owner_user_id=user_id,
                    kind="loft_user",
                    status="accepted",
                    display_name=other.display_name,
                    loft_user_id=other.id,
                )
            )
            self.add_contact(
                Contact(
                    id=0,
                    owner_user_id=other.id,
                    kind="loft_user",
                    status="accepted",
                    display_name=me.display_name,
                    loft_user_id=me.id,
                )
            )
            return a

    def create_pidge(self, msg: PidgeMessage, recipients: list[PidgeRecipient]) -> PidgeMessage:
        with self._lock:
            pidge_id = self._next("pidge")
            now = datetime.now(UTC)
            author = self._users[msg.author_id]
            saved = PidgeMessage(
                id=pidge_id,
                author_id=msg.author_id,
                state=msg.state,
                summary=msg.summary,
                intent=msg.intent,
                slots=dict(msg.slots),
                content_hash=msg.content_hash,
                sealed_at=msg.sealed_at,
                seal_user_id=msg.seal_user_id,
                created_at=now,
                updated_at=now,
                kind=msg.kind,
                author_name=author.display_name,
                supersedes_id=msg.supersedes_id,
            )
            self._pidges[pidge_id] = saved
            stored_recipients: list[PidgeRecipient] = []
            for recipient in recipients:
                rid = self._next("recipient")
                stored_recipients.append(
                    PidgeRecipient(
                        id=rid,
                        pidge_id=pidge_id,
                        role=recipient.role,
                        loft_user_id=recipient.loft_user_id,
                        contact_id=recipient.contact_id,
                        display_name=recipient.display_name,
                    )
                )
            self._recipients[pidge_id] = stored_recipients
            return saved

    def update_pidge_slots(
        self, pidge_id: int, *, summary: str, slots: dict[str, Any], intent: str | None = None
    ) -> PidgeMessage:
        with self._lock:
            msg = self._pidges[pidge_id]
            if msg.state != "draft":
                raise PermissionError("Only drafts can be enriched.")
            updated = PidgeMessage(
                id=msg.id,
                author_id=msg.author_id,
                state=msg.state,
                summary=summary,
                intent=msg.intent if intent is None else intent,
                slots=dict(slots),
                content_hash=None,
                sealed_at=None,
                seal_user_id=None,
                created_at=msg.created_at,
                updated_at=datetime.now(UTC),
                kind=msg.kind,
                author_name=msg.author_name,
                supersedes_id=msg.supersedes_id,
            )
            self._pidges[pidge_id] = updated
            return updated

    def seal_pidge(self, pidge_id: int, seal_user_id: int, now: datetime) -> PidgeMessage:
        with self._lock:
            msg = self._pidges[pidge_id]
            if msg.state != "draft":
                raise PermissionError("Only drafts can be sealed.")
            if msg.author_id != seal_user_id:
                raise PermissionError("Only the author can seal this Pidge.")
            digest = content_hash(msg.summary, msg.slots)
            updated = PidgeMessage(
                id=msg.id,
                author_id=msg.author_id,
                state="sealed",
                summary=msg.summary,
                intent=msg.intent,
                slots=dict(msg.slots),
                content_hash=digest,
                sealed_at=now,
                seal_user_id=seal_user_id,
                created_at=msg.created_at,
                updated_at=now,
                kind=msg.kind,
                author_name=msg.author_name,
                supersedes_id=msg.supersedes_id,
            )
            self._pidges[pidge_id] = updated
            return updated

    def discard_pidge(self, pidge_id: int, now: datetime) -> PidgeMessage:
        with self._lock:
            msg = self._pidges[pidge_id]
            if msg.state != "draft":
                raise PermissionError("Only drafts can be discarded.")
            updated = PidgeMessage(
                id=msg.id,
                author_id=msg.author_id,
                state="revoked",
                summary=msg.summary,
                intent=msg.intent,
                slots=dict(msg.slots),
                content_hash=msg.content_hash,
                sealed_at=msg.sealed_at,
                seal_user_id=msg.seal_user_id,
                created_at=msg.created_at,
                updated_at=now,
                kind=msg.kind,
                author_name=msg.author_name,
                supersedes_id=msg.supersedes_id,
            )
            self._pidges[pidge_id] = updated
            return updated

    def revoke_sealed_pidge(self, pidge_id: int, now: datetime) -> PidgeMessage:
        with self._lock:
            msg = self._pidges[pidge_id]
            if msg.state != "sealed":
                raise PermissionError("Only sealed Pidges can be revoked.")
            updated = PidgeMessage(
                id=msg.id,
                author_id=msg.author_id,
                state="revoked",
                summary=msg.summary,
                intent=msg.intent,
                slots=dict(msg.slots),
                content_hash=msg.content_hash,
                sealed_at=msg.sealed_at,
                seal_user_id=msg.seal_user_id,
                created_at=msg.created_at,
                updated_at=now,
                kind=msg.kind,
                author_name=msg.author_name,
                supersedes_id=msg.supersedes_id,
            )
            self._pidges[pidge_id] = updated
            return updated

    def supersede_pidge(
        self, pidge_id: int, now: datetime
    ) -> tuple[PidgeMessage, PidgeMessage]:
        with self._lock:
            msg = self._pidges[pidge_id]
            if msg.state != "sealed":
                raise PermissionError("Only sealed Pidges can be superseded.")
            prior = PidgeMessage(
                id=msg.id,
                author_id=msg.author_id,
                state="superseded",
                summary=msg.summary,
                intent=msg.intent,
                slots=dict(msg.slots),
                content_hash=msg.content_hash,
                sealed_at=msg.sealed_at,
                seal_user_id=msg.seal_user_id,
                created_at=msg.created_at,
                updated_at=now,
                kind=msg.kind,
                author_name=msg.author_name,
                supersedes_id=msg.supersedes_id,
            )
            self._pidges[pidge_id] = prior
            recipients = list(self._recipients.get(pidge_id, ()))

        draft = self.create_pidge(
            PidgeMessage(
                id=0,
                author_id=prior.author_id,
                state="draft",
                summary=prior.summary,
                intent=prior.intent,
                slots=dict(prior.slots),
                content_hash=None,
                sealed_at=None,
                seal_user_id=None,
                created_at=now,
                updated_at=now,
                kind=prior.kind,
                author_name=prior.author_name,
                supersedes_id=prior.id,
            ),
            [
                PidgeRecipient(
                    id=0,
                    pidge_id=0,
                    role=r.role,
                    loft_user_id=r.loft_user_id,
                    contact_id=r.contact_id,
                    display_name=r.display_name,
                )
                for r in recipients
            ],
        )
        return prior, draft

    def get_pidge(self, pidge_id: int) -> PidgeMessage:
        with self._lock:
            try:
                return self._pidges[pidge_id]
            except KeyError as exc:
                raise LookupError(pidge_id) from exc

    def list_drafts(self, author_id: int) -> tuple[PidgeMessage, ...]:
        with self._lock:
            return tuple(
                m
                for m in sorted(self._pidges.values(), key=lambda x: x.updated_at, reverse=True)
                if m.author_id == author_id and m.state == "draft"
            )

    def list_inbox(self, user_id: int) -> tuple[PidgeMessage, ...]:
        with self._lock:
            ids = {
                r.pidge_id
                for recipients in self._recipients.values()
                for r in recipients
                if r.loft_user_id == user_id
            }
            return tuple(
                m
                for m in sorted(self._pidges.values(), key=lambda x: x.updated_at, reverse=True)
                if m.id in ids and m.state == "sealed"
            )

    def list_sent(self, author_id: int) -> tuple[PidgeMessage, ...]:
        with self._lock:
            return tuple(
                m
                for m in sorted(self._pidges.values(), key=lambda x: x.updated_at, reverse=True)
                if m.author_id == author_id and m.state == "sealed"
            )

    def recipients_for(self, pidge_id: int) -> tuple[PidgeRecipient, ...]:
        with self._lock:
            return tuple(self._recipients.get(pidge_id, ()))

    def create_flight(self, flight: Flight, steps: list[FlightStep]) -> Flight:
        with self._lock:
            flight_id = self._next("flight")
            saved = Flight(
                id=flight_id,
                pidge_id=flight.pidge_id,
                state=flight.state,
                created_at=datetime.now(UTC),
            )
            self._flights[flight_id] = saved
            self._flight_by_pidge[flight.pidge_id] = flight_id
            stored: list[FlightStep] = []
            for step in steps:
                sid = self._next("step")
                stored.append(
                    FlightStep(
                        id=sid,
                        flight_id=flight_id,
                        key=step.key,
                        label=step.label,
                        detail=step.detail,
                        state=step.state,
                        position=step.position,
                    )
                )
            self._steps[flight_id] = stored
            return saved

    def get_flight_for_pidge(self, pidge_id: int) -> Flight | None:
        with self._lock:
            flight_id = self._flight_by_pidge.get(pidge_id)
            return self._flights.get(flight_id) if flight_id else None

    def list_flight_steps(self, flight_id: int) -> tuple[FlightStep, ...]:
        with self._lock:
            return tuple(sorted(self._steps.get(flight_id, ()), key=lambda s: s.position))

    def set_flight_state(self, flight_id: int, state: str) -> None:
        with self._lock:
            flight = self._flights[flight_id]
            self._flights[flight_id] = Flight(
                id=flight.id,
                pidge_id=flight.pidge_id,
                state=state,
                created_at=flight.created_at,
            )

    def set_flight_step_state(
        self, step_id: int, state: str, detail: str | None = None
    ) -> FlightStep:
        with self._lock:
            for _flight_id, steps in self._steps.items():
                for index, step in enumerate(steps):
                    if step.id == step_id:
                        updated = FlightStep(
                            id=step.id,
                            flight_id=step.flight_id,
                            key=step.key,
                            label=step.label,
                            detail=step.detail if detail is None else detail,
                            state=state,
                            position=step.position,
                        )
                        steps[index] = updated
                        return updated
            raise LookupError(step_id)

    def add_act(self, act: Act) -> Act:
        with self._lock:
            act_id = self._next("act")
            actor = self._users[act.actor_user_id]
            saved = Act(
                id=act_id,
                pidge_id=act.pidge_id,
                actor_user_id=act.actor_user_id,
                kind=act.kind,
                payload=dict(act.payload),
                created_at=datetime.now(UTC),
                actor_name=actor.display_name,
            )
            self._acts.setdefault(act.pidge_id, []).append(saved)
            return saved

    def list_acts(self, pidge_id: int) -> tuple[Act, ...]:
        with self._lock:
            return tuple(self._acts.get(pidge_id, ()))

    def create_hold(self, hold: Hold) -> Hold:
        with self._lock:
            hold_id = self._next("hold")
            saved = Hold(
                id=hold_id,
                pidge_id=hold.pidge_id,
                owner_user_id=hold.owner_user_id,
                title=hold.title,
                starts_at=hold.starts_at,
                place=hold.place,
                state=hold.state,
                created_at=datetime.now(UTC),
            )
            self._holds[hold_id] = saved
            return saved

    def list_holds(self, owner_user_id: int) -> tuple[Hold, ...]:
        with self._lock:
            return tuple(
                h for h in self._holds.values() if h.owner_user_id == owner_user_id
            )

    def confirm_hold(self, hold_id: int, owner_user_id: int) -> Hold:
        with self._lock:
            hold = self._holds[hold_id]
            if hold.owner_user_id != owner_user_id:
                raise PermissionError("Not your hold.")
            updated = Hold(
                id=hold.id,
                pidge_id=hold.pidge_id,
                owner_user_id=hold.owner_user_id,
                title=hold.title,
                starts_at=hold.starts_at,
                place=hold.place,
                state="confirmed",
                created_at=hold.created_at,
            )
            self._holds[hold_id] = updated
            return updated

    def pin_note(self, pin: NotePin) -> NotePin:
        with self._lock:
            for existing in self._pins.values():
                if existing.owner_user_id == pin.owner_user_id and existing.pidge_id == pin.pidge_id:
                    return existing
            pin_id = self._next("pin")
            saved = NotePin(
                id=pin_id,
                owner_user_id=pin.owner_user_id,
                pidge_id=pin.pidge_id,
                title=pin.title,
                created_at=datetime.now(UTC),
            )
            self._pins[pin_id] = saved
            return saved

    def list_pins(self, owner_user_id: int) -> tuple[NotePin, ...]:
        with self._lock:
            return tuple(p for p in self._pins.values() if p.owner_user_id == owner_user_id)

    def create_seal_challenge(
        self,
        *,
        token_hash_value: str,
        pidge_id: int,
        author_user_id: int,
        created_by_token_id: int | None,
        expires_at: datetime,
    ) -> SealChallenge:
        with self._lock:
            challenge_id = self._next("seal_challenge")
            challenge = SealChallenge(
                id=challenge_id,
                token_hash=token_hash_value,
                pidge_id=pidge_id,
                author_user_id=author_user_id,
                created_by_token_id=created_by_token_id,
                expires_at=expires_at,
                consumed_at=None,
                created_at=datetime.now(UTC),
            )
            self._seal_challenges[challenge_id] = challenge
            self._seal_by_hash[token_hash_value] = challenge_id
            return challenge

    def get_seal_challenge_by_hash(self, token_hash_value: str) -> SealChallenge | None:
        with self._lock:
            challenge_id = self._seal_by_hash.get(token_hash_value)
            if challenge_id is None:
                return None
            return self._seal_challenges.get(challenge_id)

    def consume_seal_challenge(
        self, token_hash_value: str, now: datetime
    ) -> SealChallenge | None:
        with self._lock:
            challenge_id = self._seal_by_hash.get(token_hash_value)
            if challenge_id is None:
                return None
            challenge = self._seal_challenges[challenge_id]
            if challenge.consumed_at is not None or challenge.expires_at <= now:
                return None
            updated = SealChallenge(
                id=challenge.id,
                token_hash=challenge.token_hash,
                pidge_id=challenge.pidge_id,
                author_user_id=challenge.author_user_id,
                created_by_token_id=challenge.created_by_token_id,
                expires_at=challenge.expires_at,
                consumed_at=now,
                created_at=challenge.created_at,
            )
            self._seal_challenges[challenge_id] = updated
            return updated


class PostgresStore:
    """Postgres-backed store used on Railway."""

    def __init__(self, database_url: str) -> None:
        from psycopg_pool import ConnectionPool

        self._pool = ConnectionPool(database_url, min_size=1, max_size=8, open=True)

    def close(self) -> None:
        self._pool.close()

    def migrate(self) -> None:
        with self._pool.connection() as conn:
            conn.execute(SCHEMA_SQL)
            conn.execute(
                """
                INSERT INTO schema_migrations (version, name)
                VALUES (1, 'initial')
                ON CONFLICT (version) DO NOTHING
                """
            )
            conn.execute(
                """
                ALTER TABLE pidges
                ADD COLUMN IF NOT EXISTS supersedes_id BIGINT REFERENCES pidges(id)
                """
            )
            conn.execute(
                """
                INSERT INTO schema_migrations (version, name)
                VALUES (2, 'supersedes_id')
                ON CONFLICT (version) DO NOTHING
                """
            )
            conn.execute(
                """
                ALTER TABLE pidges
                ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'invite'
                """
            )
            conn.execute(
                """
                INSERT INTO schema_migrations (version, name)
                VALUES (3, 'pidge_kind')
                ON CONFLICT (version) DO NOTHING
                """
            )
            conn.execute(
                """
                ALTER TABLE agent_tokens
                ADD COLUMN IF NOT EXISTS intended_harness TEXT,
                ADD COLUMN IF NOT EXISTS last_harness TEXT,
                ADD COLUMN IF NOT EXISTS last_client_name TEXT,
                ADD COLUMN IF NOT EXISTS last_client_version TEXT
                """
            )
            conn.execute(
                """
                INSERT INTO schema_migrations (version, name)
                VALUES (4, 'agent_token_harness')
                ON CONFLICT (version) DO NOTHING
                """
            )
            conn.commit()

    def probe(self) -> bool:
        try:
            with self._pool.connection() as conn:
                conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def settings(self) -> LoftSettings | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT name, setup_completed_at FROM loft_settings WHERE singleton_id = 1"
            ).fetchone()
        if row is None:
            return None
        return LoftSettings(name=row[0], setup_completed_at=row[1])

    def bootstrap(
        self,
        *,
        loft_name: str,
        username: str,
        display_name: str,
        password_hash: str,
    ) -> User:
        with self._pool.connection() as conn:
            existing = conn.execute(
                "SELECT 1 FROM loft_settings WHERE singleton_id = 1"
            ).fetchone()
            if existing:
                raise PermissionError("Loft setup is already complete.")
            user = self._insert_user(
                conn,
                username=username,
                display_name=display_name,
                password_hash=password_hash,
                role="owner",
            )
            conn.execute(
                """
                INSERT INTO loft_settings (singleton_id, name, setup_completed_at)
                VALUES (1, %s, now())
                """,
                (loft_name,),
            )
            conn.commit()
            return user

    def register_user(
        self, *, username: str, display_name: str, password_hash: str
    ) -> User:
        with self._pool.connection() as conn:
            if conn.execute("SELECT 1 FROM loft_settings WHERE singleton_id = 1").fetchone() is None:
                raise PermissionError("Loft is not set up yet.")
            user = self._insert_user(
                conn,
                username=username,
                display_name=display_name,
                password_hash=password_hash,
                role="member",
            )
            conn.commit()
            return user

    def _insert_user(
        self,
        conn: Any,
        *,
        username: str,
        display_name: str,
        password_hash: str,
        role: str,
    ) -> User:
        try:
            row = conn.execute(
                """
                INSERT INTO users (username, normalized_username, display_name, password_hash, role)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, username, display_name, password_hash, role, status, created_at
                """,
                (username, username.casefold(), display_name, password_hash, role),
            ).fetchone()
        except Exception as exc:
            raise ValueError("That username is already taken.") from exc
        return User(*row)

    def get_user(self, user_id: int) -> User:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT id, username, display_name, password_hash, role, status, created_at
                FROM users WHERE id = %s
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            raise LookupError(user_id)
        return User(*row)

    def get_user_by_username(self, normalized_username: str) -> User:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT id, username, display_name, password_hash, role, status, created_at
                FROM users WHERE normalized_username = %s
                """,
                (normalized_username.casefold(),),
            ).fetchone()
        if row is None:
            raise LookupError(normalized_username)
        return User(*row)

    def list_users(self) -> tuple[User, ...]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, username, display_name, password_hash, role, status, created_at
                FROM users ORDER BY username
                """
            ).fetchall()
        return tuple(User(*row) for row in rows)

    def create_session(self, user_id: int, token_hash_value: str, expires_at: datetime) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO user_sessions (user_id, token_hash, expires_at)
                VALUES (%s, %s, %s)
                """,
                (user_id, token_hash_value, expires_at),
            )
            conn.commit()

    def user_for_session(self, token_hash_value: str, now: datetime) -> User | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT u.id, u.username, u.display_name, u.password_hash, u.role, u.status, u.created_at
                FROM user_sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = %s AND s.revoked_at IS NULL AND s.expires_at > %s
                """,
                (token_hash_value, now),
            ).fetchone()
        return User(*row) if row else None

    def revoke_session(self, token_hash_value: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE user_sessions SET revoked_at = now() WHERE token_hash = %s",
                (token_hash_value,),
            )
            conn.commit()

    def create_agent_token(
        self,
        *,
        user_id: int,
        token_hash_value: str,
        label: str,
        scopes: frozenset[str],
        expires_at: datetime | None,
        intended_harness: str | None = None,
    ) -> AgentToken:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO agent_tokens (
                    user_id, token_hash, label, scopes, expires_at, intended_harness
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, user_id, label, scopes, created_at, expires_at, revoked_at,
                          last_used_at, intended_harness, last_harness,
                          last_client_name, last_client_version
                """,
                (
                    user_id,
                    token_hash_value,
                    label,
                    list(scopes),
                    expires_at,
                    intended_harness,
                ),
            ).fetchone()
            conn.commit()
        return _agent_token_from_row(row)

    def list_agent_tokens(self, user_id: int) -> tuple[AgentToken, ...]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, label, scopes, created_at, expires_at, revoked_at,
                       last_used_at, intended_harness, last_harness,
                       last_client_name, last_client_version
                FROM agent_tokens WHERE user_id = %s ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()
        return tuple(_agent_token_from_row(r) for r in rows)

    def revoke_agent_token(self, user_id: int, token_id: int) -> None:
        with self._pool.connection() as conn:
            cur = conn.execute(
                """
                UPDATE agent_tokens SET revoked_at = now()
                WHERE id = %s AND user_id = %s AND revoked_at IS NULL
                """,
                (token_id, user_id),
            )
            if cur.rowcount == 0:
                raise LookupError(token_id)
            conn.commit()

    def agent_client_for_token(
        self, token_hash_value: str, now: datetime
    ) -> tuple[AgentClient, int] | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT id, user_id, scopes, expires_at, revoked_at
                FROM agent_tokens WHERE token_hash = %s
                """,
                (token_hash_value,),
            ).fetchone()
        if row is None or row[4] is not None:
            return None
        if row[3] is not None and row[3] <= now:
            return None
        client = AgentClient(
            id=f"agent:{row[0]}",
            owner_user_id=row[1],
            scopes=frozenset(row[2]),
            token_id=row[0],
        )
        return client, row[0]

    def touch_agent_token(
        self,
        token_id: int,
        now: datetime,
        *,
        last_harness: str | None = None,
        last_client_name: str | None = None,
        last_client_version: str | None = None,
    ) -> None:
        with self._pool.connection() as conn:
            if last_harness is None and last_client_name is None and last_client_version is None:
                conn.execute(
                    "UPDATE agent_tokens SET last_used_at = %s WHERE id = %s",
                    (now, token_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE agent_tokens SET
                        last_used_at = %s,
                        last_harness = COALESCE(%s, last_harness),
                        last_client_name = COALESCE(%s, last_client_name),
                        last_client_version = COALESCE(%s, last_client_version)
                    WHERE id = %s
                    """,
                    (
                        now,
                        last_harness,
                        last_client_name,
                        last_client_version,
                        token_id,
                    ),
                )
            conn.commit()

    def is_agent_token_revoked(self, token_id: int) -> bool:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT revoked_at FROM agent_tokens WHERE id = %s",
                (token_id,),
            ).fetchone()
        return row is None or row[0] is not None

    # --- Remaining Postgres methods delegate through SQL mirroring MemoryStore ---

    def list_contacts(self, owner_user_id: int) -> tuple[Contact, ...]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, owner_user_id, kind, status, display_name, loft_user_id,
                       external_handle, created_at
                FROM contacts WHERE owner_user_id = %s ORDER BY display_name
                """,
                (owner_user_id,),
            ).fetchall()
        return tuple(Contact(*row) for row in rows)

    def get_contact(self, contact_id: int) -> Contact:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT id, owner_user_id, kind, status, display_name, loft_user_id,
                       external_handle, created_at
                FROM contacts WHERE id = %s
                """,
                (contact_id,),
            ).fetchone()
        if row is None:
            raise LookupError(contact_id)
        return Contact(*row)

    def add_contact(self, contact: Contact) -> Contact:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO contacts
                    (owner_user_id, kind, status, display_name, loft_user_id, external_handle)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, owner_user_id, kind, status, display_name, loft_user_id,
                          external_handle, created_at
                """,
                (
                    contact.owner_user_id,
                    contact.kind,
                    contact.status,
                    contact.display_name,
                    contact.loft_user_id,
                    contact.external_handle,
                ),
            ).fetchone()
            conn.commit()
        return Contact(*row)

    def update_contact_status(self, contact_id: int, status: str) -> Contact:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                UPDATE contacts SET status = %s WHERE id = %s
                RETURNING id, owner_user_id, kind, status, display_name, loft_user_id,
                          external_handle, created_at
                """,
                (status, contact_id),
            ).fetchone()
            conn.commit()
        if row is None:
            raise LookupError(contact_id)
        return Contact(*row)

    def create_connection_request(self, req: ConnectionRequest) -> ConnectionRequest:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO connection_requests
                    (from_user_id, to_user_id, external_handle, status, claim_token_hash)
                VALUES (%s, %s, %s, 'pending', %s)
                RETURNING id, from_user_id, to_user_id, external_handle, status,
                          claim_token_hash, created_at
                """,
                (req.from_user_id, req.to_user_id, req.external_handle, req.claim_token_hash),
            ).fetchone()
            conn.commit()
        return ConnectionRequest(*row)

    def list_connection_requests(self, user_id: int) -> tuple[ConnectionRequest, ...]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, from_user_id, to_user_id, external_handle, status,
                       claim_token_hash, created_at
                FROM connection_requests
                WHERE from_user_id = %s OR to_user_id = %s
                ORDER BY created_at DESC
                """,
                (user_id, user_id),
            ).fetchall()
        return tuple(ConnectionRequest(*row) for row in rows)

    def accept_connection_request(self, request_id: int, user_id: int) -> Contact:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT id, from_user_id, to_user_id, external_handle, status,
                       claim_token_hash, created_at
                FROM connection_requests WHERE id = %s FOR UPDATE
                """,
                (request_id,),
            ).fetchone()
            if row is None:
                raise LookupError(request_id)
            req = ConnectionRequest(*row)
            if req.to_user_id != user_id or req.status != "pending":
                raise PermissionError("Cannot accept this connection request.")
            conn.execute(
                "UPDATE connection_requests SET status = 'accepted' WHERE id = %s",
                (request_id,),
            )
            other = self.get_user(req.from_user_id)
            me = self.get_user(user_id)
            contact = self.add_contact(
                Contact(
                    id=0,
                    owner_user_id=user_id,
                    kind="loft_user",
                    status="accepted",
                    display_name=other.display_name,
                    loft_user_id=other.id,
                )
            )
            self.add_contact(
                Contact(
                    id=0,
                    owner_user_id=other.id,
                    kind="loft_user",
                    status="accepted",
                    display_name=me.display_name,
                    loft_user_id=me.id,
                )
            )
            conn.commit()
            return contact

    def create_pidge(self, msg: PidgeMessage, recipients: list[PidgeRecipient]) -> PidgeMessage:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO pidges (author_id, state, summary, intent, slots, supersedes_id, kind)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
                RETURNING id, author_id, state, summary, intent, slots, content_hash,
                          sealed_at, seal_user_id, created_at, updated_at, supersedes_id, kind
                """,
                (
                    msg.author_id,
                    msg.state,
                    msg.summary,
                    msg.intent,
                    json.dumps(msg.slots),
                    msg.supersedes_id,
                    msg.kind,
                ),
            ).fetchone()
            author = conn.execute(
                "SELECT display_name FROM users WHERE id = %s", (msg.author_id,)
            ).fetchone()
            pidge_id = row[0]
            for recipient in recipients:
                conn.execute(
                    """
                    INSERT INTO pidge_recipients
                        (pidge_id, role, loft_user_id, contact_id, display_name)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        pidge_id,
                        recipient.role,
                        recipient.loft_user_id,
                        recipient.contact_id,
                        recipient.display_name,
                    ),
                )
            conn.commit()
        return self._message_from_row(row, author_name=author[0] if author else "")

    def update_pidge_slots(
        self, pidge_id: int, *, summary: str, slots: dict[str, Any], intent: str | None = None
    ) -> PidgeMessage:
        with self._pool.connection() as conn:
            current = conn.execute(
                "SELECT state, intent FROM pidges WHERE id = %s FOR UPDATE", (pidge_id,)
            ).fetchone()
            if current is None:
                raise LookupError(pidge_id)
            if current[0] != "draft":
                raise PermissionError("Only drafts can be enriched.")
            new_intent = current[1] if intent is None else intent
            row = conn.execute(
                """
                UPDATE pidges
                SET summary = %s, slots = %s::jsonb, intent = %s, updated_at = now()
                WHERE id = %s
                RETURNING id, author_id, state, summary, intent, slots, content_hash,
                          sealed_at, seal_user_id, created_at, updated_at, supersedes_id, kind
                """,
                (summary, json.dumps(slots), new_intent, pidge_id),
            ).fetchone()
            author = conn.execute(
                "SELECT display_name FROM users WHERE id = %s", (row[1],)
            ).fetchone()
            conn.commit()
        return self._message_from_row(row, author_name=author[0] if author else "")

    def seal_pidge(self, pidge_id: int, seal_user_id: int, now: datetime) -> PidgeMessage:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT id, author_id, state, summary, intent, slots, content_hash,
                       sealed_at, seal_user_id, created_at, updated_at, supersedes_id, kind
                FROM pidges WHERE id = %s FOR UPDATE
                """,
                (pidge_id,),
            ).fetchone()
            if row is None:
                raise LookupError(pidge_id)
            if row[2] != "draft":
                raise PermissionError("Only drafts can be sealed.")
            if row[1] != seal_user_id:
                raise PermissionError("Only the author can seal this Pidge.")
            slots = row[5] if isinstance(row[5], dict) else json.loads(row[5])
            digest = content_hash(row[3], slots)
            updated = conn.execute(
                """
                UPDATE pidges
                SET state = 'sealed', content_hash = %s, sealed_at = %s,
                    seal_user_id = %s, updated_at = %s
                WHERE id = %s
                RETURNING id, author_id, state, summary, intent, slots, content_hash,
                          sealed_at, seal_user_id, created_at, updated_at, supersedes_id, kind
                """,
                (digest, now, seal_user_id, now, pidge_id),
            ).fetchone()
            author = conn.execute(
                "SELECT display_name FROM users WHERE id = %s", (updated[1],)
            ).fetchone()
            conn.commit()
        return self._message_from_row(updated, author_name=author[0] if author else "")

    def discard_pidge(self, pidge_id: int, now: datetime) -> PidgeMessage:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT id, author_id, state, summary, intent, slots, content_hash,
                       sealed_at, seal_user_id, created_at, updated_at, supersedes_id, kind
                FROM pidges WHERE id = %s FOR UPDATE
                """,
                (pidge_id,),
            ).fetchone()
            if row is None:
                raise LookupError(pidge_id)
            if row[2] != "draft":
                raise PermissionError("Only drafts can be discarded.")
            updated = conn.execute(
                """
                UPDATE pidges
                SET state = 'revoked', updated_at = %s
                WHERE id = %s
                RETURNING id, author_id, state, summary, intent, slots, content_hash,
                          sealed_at, seal_user_id, created_at, updated_at, supersedes_id, kind
                """,
                (now, pidge_id),
            ).fetchone()
            author = conn.execute(
                "SELECT display_name FROM users WHERE id = %s", (updated[1],)
            ).fetchone()
            conn.commit()
        return self._message_from_row(updated, author_name=author[0] if author else "")

    def revoke_sealed_pidge(self, pidge_id: int, now: datetime) -> PidgeMessage:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT id, author_id, state, summary, intent, slots, content_hash,
                       sealed_at, seal_user_id, created_at, updated_at, supersedes_id, kind
                FROM pidges WHERE id = %s FOR UPDATE
                """,
                (pidge_id,),
            ).fetchone()
            if row is None:
                raise LookupError(pidge_id)
            if row[2] != "sealed":
                raise PermissionError("Only sealed Pidges can be revoked.")
            updated = conn.execute(
                """
                UPDATE pidges
                SET state = 'revoked', updated_at = %s
                WHERE id = %s
                RETURNING id, author_id, state, summary, intent, slots, content_hash,
                          sealed_at, seal_user_id, created_at, updated_at, supersedes_id, kind
                """,
                (now, pidge_id),
            ).fetchone()
            author = conn.execute(
                "SELECT display_name FROM users WHERE id = %s", (updated[1],)
            ).fetchone()
            conn.commit()
        return self._message_from_row(updated, author_name=author[0] if author else "")

    def supersede_pidge(
        self, pidge_id: int, now: datetime
    ) -> tuple[PidgeMessage, PidgeMessage]:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT id, author_id, state, summary, intent, slots, content_hash,
                       sealed_at, seal_user_id, created_at, updated_at, supersedes_id, kind
                FROM pidges WHERE id = %s FOR UPDATE
                """,
                (pidge_id,),
            ).fetchone()
            if row is None:
                raise LookupError(pidge_id)
            if row[2] != "sealed":
                raise PermissionError("Only sealed Pidges can be superseded.")
            prior_row = conn.execute(
                """
                UPDATE pidges
                SET state = 'superseded', updated_at = %s
                WHERE id = %s
                RETURNING id, author_id, state, summary, intent, slots, content_hash,
                          sealed_at, seal_user_id, created_at, updated_at, supersedes_id, kind
                """,
                (now, pidge_id),
            ).fetchone()
            author = conn.execute(
                "SELECT display_name FROM users WHERE id = %s", (prior_row[1],)
            ).fetchone()
            author_name = author[0] if author else ""
            slots = (
                prior_row[5]
                if isinstance(prior_row[5], dict)
                else json.loads(prior_row[5])
            )
            draft_row = conn.execute(
                """
                INSERT INTO pidges
                    (author_id, state, summary, intent, slots, supersedes_id, kind)
                VALUES (%s, 'draft', %s, %s, %s::jsonb, %s, %s)
                RETURNING id, author_id, state, summary, intent, slots, content_hash,
                          sealed_at, seal_user_id, created_at, updated_at, supersedes_id, kind
                """,
                (
                    prior_row[1],
                    prior_row[3],
                    prior_row[4],
                    json.dumps(slots),
                    prior_row[0],
                    prior_row[12],
                ),
            ).fetchone()
            recipients = conn.execute(
                """
                SELECT role, loft_user_id, contact_id, display_name
                FROM pidge_recipients WHERE pidge_id = %s
                """,
                (pidge_id,),
            ).fetchall()
            for role, loft_user_id, contact_id, display_name in recipients:
                conn.execute(
                    """
                    INSERT INTO pidge_recipients
                        (pidge_id, role, loft_user_id, contact_id, display_name)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (draft_row[0], role, loft_user_id, contact_id, display_name),
                )
            conn.commit()
        prior = self._message_from_row(prior_row, author_name=author_name)
        draft = self._message_from_row(draft_row, author_name=author_name)
        return prior, draft

    def get_pidge(self, pidge_id: int) -> PidgeMessage:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT p.id, p.author_id, p.state, p.summary, p.intent, p.slots, p.content_hash,
                       p.sealed_at, p.seal_user_id, p.created_at, p.updated_at, p.supersedes_id, p.kind,
                       u.display_name
                FROM pidges p JOIN users u ON u.id = p.author_id
                WHERE p.id = %s
                """,
                (pidge_id,),
            ).fetchone()
        if row is None:
            raise LookupError(pidge_id)
        return self._row_to_pidge(row)

    def list_drafts(self, author_id: int) -> tuple[PidgeMessage, ...]:
        return self._list_pidges(author_id=author_id, state="draft")

    def list_sent(self, author_id: int) -> tuple[PidgeMessage, ...]:
        return self._list_pidges(author_id=author_id, state="sealed")

    def list_inbox(self, user_id: int) -> tuple[PidgeMessage, ...]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT p.id, p.author_id, p.state, p.summary, p.intent, p.slots,
                       p.content_hash, p.sealed_at, p.seal_user_id, p.created_at, p.updated_at,
                       p.supersedes_id, p.kind, u.display_name
                FROM pidges p
                JOIN users u ON u.id = p.author_id
                JOIN pidge_recipients r ON r.pidge_id = p.id
                WHERE r.loft_user_id = %s AND p.state = 'sealed'
                ORDER BY p.updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return tuple(self._row_to_pidge(row) for row in rows)

    def _list_pidges(self, *, author_id: int, state: str) -> tuple[PidgeMessage, ...]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT p.id, p.author_id, p.state, p.summary, p.intent, p.slots, p.content_hash,
                       p.sealed_at, p.seal_user_id, p.created_at, p.updated_at, p.supersedes_id, p.kind,
                       u.display_name
                FROM pidges p JOIN users u ON u.id = p.author_id
                WHERE p.author_id = %s AND p.state = %s
                ORDER BY p.updated_at DESC
                """,
                (author_id, state),
            ).fetchall()
        return tuple(self._row_to_pidge(row) for row in rows)

    def _message_from_row(self, row: tuple[Any, ...], *, author_name: str) -> PidgeMessage:
        return PidgeMessage(
            id=row[0],
            author_id=row[1],
            state=row[2],
            summary=row[3],
            intent=row[4],
            slots=row[5] if isinstance(row[5], dict) else json.loads(row[5]),
            content_hash=row[6],
            sealed_at=row[7],
            seal_user_id=row[8],
            created_at=row[9],
            updated_at=row[10],
            supersedes_id=row[11],
            kind=row[12] if len(row) > 12 and row[12] is not None else "invite",
            author_name=author_name,
        )

    def _row_to_pidge(self, row: tuple[Any, ...]) -> PidgeMessage:
        return PidgeMessage(
            id=row[0],
            author_id=row[1],
            state=row[2],
            summary=row[3],
            intent=row[4],
            slots=row[5] if isinstance(row[5], dict) else json.loads(row[5]),
            content_hash=row[6],
            sealed_at=row[7],
            seal_user_id=row[8],
            created_at=row[9],
            updated_at=row[10],
            supersedes_id=row[11],
            kind=row[12] if row[12] is not None else "invite",
            author_name=row[13],
        )

    def recipients_for(self, pidge_id: int) -> tuple[PidgeRecipient, ...]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, pidge_id, role, loft_user_id, contact_id, display_name
                FROM pidge_recipients WHERE pidge_id = %s
                """,
                (pidge_id,),
            ).fetchall()
        return tuple(PidgeRecipient(*row) for row in rows)

    def create_flight(self, flight: Flight, steps: list[FlightStep]) -> Flight:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO flights (pidge_id, state) VALUES (%s, %s)
                RETURNING id, pidge_id, state, created_at
                """,
                (flight.pidge_id, flight.state),
            ).fetchone()
            for step in steps:
                conn.execute(
                    """
                    INSERT INTO flight_steps (flight_id, key, label, detail, state, position)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (row[0], step.key, step.label, step.detail, step.state, step.position),
                )
            conn.commit()
        return Flight(*row)

    def get_flight_for_pidge(self, pidge_id: int) -> Flight | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT id, pidge_id, state, created_at FROM flights
                WHERE pidge_id = %s ORDER BY id DESC LIMIT 1
                """,
                (pidge_id,),
            ).fetchone()
        return Flight(*row) if row else None

    def list_flight_steps(self, flight_id: int) -> tuple[FlightStep, ...]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, flight_id, key, label, detail, state, position
                FROM flight_steps WHERE flight_id = %s ORDER BY position
                """,
                (flight_id,),
            ).fetchall()
        return tuple(FlightStep(*row) for row in rows)

    def set_flight_state(self, flight_id: int, state: str) -> None:
        with self._pool.connection() as conn:
            conn.execute("UPDATE flights SET state = %s WHERE id = %s", (state, flight_id))
            conn.commit()

    def set_flight_step_state(
        self, step_id: int, state: str, detail: str | None = None
    ) -> FlightStep:
        with self._pool.connection() as conn:
            if detail is None:
                row = conn.execute(
                    """
                    UPDATE flight_steps SET state = %s WHERE id = %s
                    RETURNING id, flight_id, key, label, detail, state, position
                    """,
                    (state, step_id),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    UPDATE flight_steps SET state = %s, detail = %s WHERE id = %s
                    RETURNING id, flight_id, key, label, detail, state, position
                    """,
                    (state, detail, step_id),
                ).fetchone()
            conn.commit()
        if row is None:
            raise LookupError(step_id)
        return FlightStep(*row)

    def add_act(self, act: Act) -> Act:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO acts (pidge_id, actor_user_id, kind, payload)
                VALUES (%s, %s, %s, %s::jsonb)
                RETURNING id, pidge_id, actor_user_id, kind, payload, created_at
                """,
                (act.pidge_id, act.actor_user_id, act.kind, json.dumps(act.payload)),
            ).fetchone()
            name = conn.execute(
                "SELECT display_name FROM users WHERE id = %s", (act.actor_user_id,)
            ).fetchone()
            conn.commit()
        payload = row[4] if isinstance(row[4], dict) else json.loads(row[4])
        return Act(
            id=row[0],
            pidge_id=row[1],
            actor_user_id=row[2],
            kind=row[3],
            payload=payload,
            created_at=row[5],
            actor_name=name[0] if name else "",
        )

    def list_acts(self, pidge_id: int) -> tuple[Act, ...]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT a.id, a.pidge_id, a.actor_user_id, a.kind, a.payload, a.created_at,
                       u.display_name
                FROM acts a JOIN users u ON u.id = a.actor_user_id
                WHERE a.pidge_id = %s ORDER BY a.created_at
                """,
                (pidge_id,),
            ).fetchall()
        return tuple(
            Act(
                id=r[0],
                pidge_id=r[1],
                actor_user_id=r[2],
                kind=r[3],
                payload=r[4] if isinstance(r[4], dict) else json.loads(r[4]),
                created_at=r[5],
                actor_name=r[6],
            )
            for r in rows
        )

    def create_hold(self, hold: Hold) -> Hold:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO holds (pidge_id, owner_user_id, title, starts_at, place, state)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, pidge_id, owner_user_id, title, starts_at, place, state, created_at
                """,
                (
                    hold.pidge_id,
                    hold.owner_user_id,
                    hold.title,
                    hold.starts_at,
                    hold.place,
                    hold.state,
                ),
            ).fetchone()
            conn.commit()
        return Hold(*row)

    def list_holds(self, owner_user_id: int) -> tuple[Hold, ...]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, pidge_id, owner_user_id, title, starts_at, place, state, created_at
                FROM holds WHERE owner_user_id = %s ORDER BY created_at DESC
                """,
                (owner_user_id,),
            ).fetchall()
        return tuple(Hold(*row) for row in rows)

    def confirm_hold(self, hold_id: int, owner_user_id: int) -> Hold:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                UPDATE holds SET state = 'confirmed'
                WHERE id = %s AND owner_user_id = %s
                RETURNING id, pidge_id, owner_user_id, title, starts_at, place, state, created_at
                """,
                (hold_id, owner_user_id),
            ).fetchone()
            conn.commit()
        if row is None:
            raise PermissionError("Not your hold.")
        return Hold(*row)

    def pin_note(self, pin: NotePin) -> NotePin:
        with self._pool.connection() as conn:
            existing = conn.execute(
                """
                SELECT id, owner_user_id, pidge_id, title, created_at
                FROM note_pins WHERE owner_user_id = %s AND pidge_id = %s
                """,
                (pin.owner_user_id, pin.pidge_id),
            ).fetchone()
            if existing:
                return NotePin(*existing)
            row = conn.execute(
                """
                INSERT INTO note_pins (owner_user_id, pidge_id, title)
                VALUES (%s, %s, %s)
                RETURNING id, owner_user_id, pidge_id, title, created_at
                """,
                (pin.owner_user_id, pin.pidge_id, pin.title),
            ).fetchone()
            conn.commit()
        return NotePin(*row)

    def list_pins(self, owner_user_id: int) -> tuple[NotePin, ...]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, owner_user_id, pidge_id, title, created_at
                FROM note_pins WHERE owner_user_id = %s ORDER BY created_at DESC
                """,
                (owner_user_id,),
            ).fetchall()
        return tuple(NotePin(*row) for row in rows)

    def create_seal_challenge(
        self,
        *,
        token_hash_value: str,
        pidge_id: int,
        author_user_id: int,
        created_by_token_id: int | None,
        expires_at: datetime,
    ) -> SealChallenge:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO seal_challenges (
                    token_hash, pidge_id, author_user_id, created_by_token_id, expires_at
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, token_hash, pidge_id, author_user_id, created_by_token_id,
                          expires_at, consumed_at, created_at
                """,
                (
                    token_hash_value,
                    pidge_id,
                    author_user_id,
                    created_by_token_id,
                    expires_at,
                ),
            ).fetchone()
            conn.commit()
        return SealChallenge(*row)

    def get_seal_challenge_by_hash(self, token_hash_value: str) -> SealChallenge | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT id, token_hash, pidge_id, author_user_id, created_by_token_id,
                       expires_at, consumed_at, created_at
                FROM seal_challenges WHERE token_hash = %s
                """,
                (token_hash_value,),
            ).fetchone()
        return SealChallenge(*row) if row else None

    def consume_seal_challenge(
        self, token_hash_value: str, now: datetime
    ) -> SealChallenge | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                UPDATE seal_challenges
                SET consumed_at = %s
                WHERE token_hash = %s
                  AND consumed_at IS NULL
                  AND expires_at > %s
                RETURNING id, token_hash, pidge_id, author_user_id, created_by_token_id,
                          expires_at, consumed_at, created_at
                """,
                (now, token_hash_value, now),
            ).fetchone()
            conn.commit()
        return SealChallenge(*row) if row else None
