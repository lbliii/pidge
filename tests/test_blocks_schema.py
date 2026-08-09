"""Schema contract for pidge kind + extras.blocks (#72)."""

from __future__ import annotations

import pytest

from pidge.config import PidgeConfig
from pidge.services import PidgeService
from pidge.store import MemoryStore

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
def service(store: MemoryStore, config: PidgeConfig) -> PidgeService:
    return PidgeService(store, config)


def _setup_loft(service: PidgeService):
    result = service.setup(
        bootstrap_token="development-bootstrap-token",
        loft_name="Test Loft",
        username="owner",
        display_name="Owner",
        password="password-long",
    )
    lucy = service.register(
        username="lucy", display_name="Lucy", password="password-long"
    )
    return result.user, lucy.user


def test_default_kind_is_invite(service: PidgeService) -> None:
    owner, _lucy = _setup_loft(service)
    draft = service.draft_pidge(owner, intent="Meet Lucy", recipient_names=["Lucy"])
    assert draft.kind == "invite"


def test_draft_accepts_share_kind(service: PidgeService) -> None:
    owner, _lucy = _setup_loft(service)
    draft = service.draft_pidge(
        owner, intent="Share note", recipient_names=["Lucy"], kind="share"
    )
    assert draft.kind == "share"
    fetched = service.store.get_pidge(draft.id)
    assert fetched.kind == "share"


def test_seal_blocked_without_slots_even_with_blocks(service: PidgeService) -> None:
    owner, _lucy = _setup_loft(service)
    draft = service.draft_pidge(owner, intent="Tonight", recipient_names=["Lucy"])
    service.enrich_pidge(
        owner,
        draft.id,
        extras={
            "blocks": [
                {"type": "place", "title": "Nowadays", "blurb": "Bushwick"},
            ]
        },
    )
    with pytest.raises(ValueError, match="who"):
        service.seal_pidge(owner, draft.id)


def test_blocks_absent_seal_ok(service: PidgeService) -> None:
    owner, _lucy = _setup_loft(service)
    draft = service.draft_pidge(owner, intent="Tonight", recipient_names=["Lucy"])
    service.enrich_pidge(
        owner,
        draft.id,
        who="Lucy",
        when="Tonight · 7pm",
        where="Nowadays",
    )
    sealed = service.seal_pidge(owner, draft.id)
    assert sealed.state == "sealed"
    extras = sealed.slots.get("extras")
    assert extras is None or "blocks" not in (extras.get("value") or {})


def test_blocks_round_trip_get_pidge(service: PidgeService) -> None:
    owner, _lucy = _setup_loft(service)
    draft = service.draft_pidge(owner, intent="Tonight", recipient_names=["Lucy"])
    blocks = [
        {"type": "place", "title": "Nowadays", "blurb": "Bushwick"},
        {"type": "map", "address": "56 Bogart St", "lat": 40.706, "lng": -73.923},
        {"type": "weird_future", "note": "preserved unknown type"},
    ]
    service.enrich_pidge(
        owner,
        draft.id,
        who="Lucy",
        when="Tonight · 7pm",
        where="Nowadays",
        extras={"menu": "kitchen + wine", "blocks": blocks},
    )
    fetched = service.get_pidge_for(owner, draft.id)
    value = fetched.slots["extras"]["value"]
    assert value["menu"] == "kitchen + wine"
    assert value["blocks"][0]["type"] == "place"
    assert value["blocks"][2]["type"] == "weird_future"
    sealed = service.seal_pidge(owner, draft.id)
    after = service.get_pidge_for(owner, sealed.id)
    assert after.slots["extras"]["value"]["blocks"][1]["address"] == "56 Bogart St"


def test_blocks_must_be_list(service: PidgeService) -> None:
    owner, _lucy = _setup_loft(service)
    draft = service.draft_pidge(owner, intent="Tonight", recipient_names=["Lucy"])
    with pytest.raises(ValueError, match="extras.blocks must be a list"):
        service.enrich_pidge(owner, draft.id, extras={"blocks": {"type": "place"}})


def test_block_requires_string_type(service: PidgeService) -> None:
    owner, _lucy = _setup_loft(service)
    draft = service.draft_pidge(owner, intent="Tonight", recipient_names=["Lucy"])
    with pytest.raises(ValueError, match="string type"):
        service.enrich_pidge(owner, draft.id, extras={"blocks": [{"title": "x"}]})


def test_share_kind_acts(service: PidgeService) -> None:
    owner, lucy = _setup_loft(service)
    draft = service.draft_pidge(
        owner, intent="Read this", recipient_names=["Lucy"], kind="share"
    )
    service.enrich_pidge(
        owner,
        draft.id,
        who="Lucy",
        mark_none=("when", "where"),
        extras={"blocks": [{"type": "article", "title": "Note", "blurb": "hi"}]},
    )
    sealed = service.seal_pidge(owner, draft.id)
    act = service.record_act(lucy, sealed.id, "ack")
    assert act.kind == "ack"
    with pytest.raises(ValueError, match="rsvp_yes"):
        service.record_act(lucy, sealed.id, "rsvp_yes")
