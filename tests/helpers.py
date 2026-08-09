"""Shared test helpers for loft consent and mail."""

from __future__ import annotations

from pidge.models import Contact, User
from pidge.services import PidgeService


def connect_loft_mates(service: PidgeService, a: User, b: User) -> None:
    """Create mutual accepted loft contacts so *a* and *b* can mail each other."""
    service.store.add_contact(
        Contact(
            id=0,
            owner_user_id=a.id,
            kind="loft_user",
            status="accepted",
            display_name=b.display_name,
            loft_user_id=b.id,
        )
    )
    service.store.add_contact(
        Contact(
            id=0,
            owner_user_id=b.id,
            kind="loft_user",
            status="accepted",
            display_name=a.display_name,
            loft_user_id=a.id,
        )
    )
