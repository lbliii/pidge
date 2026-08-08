"""Typed domain primitives for Pidge."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class LoftSettings:
    name: str
    setup_completed_at: datetime


@dataclass(frozen=True, slots=True)
class User:
    id: int
    username: str
    display_name: str
    password_hash: str
    role: str
    status: str
    created_at: datetime

    @property
    def is_authenticated(self) -> bool:
        return self.status == "active"

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"


@dataclass(frozen=True, slots=True)
class AgentClient:
    """Bearer-authenticated machine client bound to a human owner."""

    id: str
    owner_user_id: int
    scopes: frozenset[str]
    token_id: int
    is_authenticated: bool = True


@dataclass(frozen=True, slots=True)
class AgentToken:
    id: int
    user_id: int
    label: str
    scopes: frozenset[str]
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Contact:
    id: int
    owner_user_id: int
    kind: str  # loft_user | external
    status: str  # pending | accepted | blocked
    display_name: str
    loft_user_id: int | None = None
    external_handle: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ConnectionRequest:
    id: int
    from_user_id: int
    to_user_id: int | None
    external_handle: str | None
    status: str  # pending | accepted | declined
    claim_token_hash: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PidgeMessage:
    id: int
    author_id: int
    state: str  # draft | sealed | revoked | superseded
    summary: str
    intent: str
    slots: dict[str, Any]
    content_hash: str | None
    sealed_at: datetime | None
    seal_user_id: int | None
    created_at: datetime
    updated_at: datetime
    author_name: str = ""
    supersedes_id: int | None = None  # draft successor of a sealed/superseded prior


@dataclass(frozen=True, slots=True)
class PidgeRecipient:
    id: int
    pidge_id: int
    role: str
    loft_user_id: int | None = None
    contact_id: int | None = None
    display_name: str = ""


@dataclass(frozen=True, slots=True)
class Flight:
    id: int
    pidge_id: int
    state: str  # pending | flying | done
    created_at: datetime


@dataclass(frozen=True, slots=True)
class FlightStep:
    id: int
    flight_id: int
    key: str
    label: str
    detail: str
    state: str  # pending | active | done
    position: int


@dataclass(frozen=True, slots=True)
class Act:
    id: int
    pidge_id: int
    actor_user_id: int
    kind: str
    payload: dict[str, Any]
    created_at: datetime
    actor_name: str = ""


@dataclass(frozen=True, slots=True)
class Hold:
    id: int
    pidge_id: int
    owner_user_id: int
    title: str
    starts_at: str | None
    place: str | None
    state: str  # proposed | confirmed
    created_at: datetime


@dataclass(frozen=True, slots=True)
class NotePin:
    id: int
    owner_user_id: int
    pidge_id: int
    title: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SealChallenge:
    id: int
    token_hash: str
    pidge_id: int
    author_user_id: int
    created_by_token_id: int | None
    expires_at: datetime
    consumed_at: datetime | None
    created_at: datetime
