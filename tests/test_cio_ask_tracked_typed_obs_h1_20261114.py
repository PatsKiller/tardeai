"""OBS-H1 (operator, live Chrome, 2026-11-14): generic card labels rode the shared header as tracked ENTITIES.

The operator's header showed "Review BHVN (private)", "WATCH Card (private)" and "Risk (private)" as chips pointing at
the BHVN thread. The cause is in the ledger: the resolver's fallback minted a ``private_entity`` for every capitalised
heading of a pasted card and auto-tracked each one, so ``tracked_entities`` published card chrome as global entities.

The ledger is append-only (AGENTS.md §0 rule 6), so the historical rows are NOT rewritten. The projection stops
promoting a NAME to a header entity: a tracked entity rides only when it has a typed identity — a listed security's
symbol (``typed_tracking_class == 'symbol'``), an account, or a thread. The name keeps its tracking on its own thread.

Synthetic fixtures only (public repo): placeholder guids, symbols and account labels.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.cio_ask_contract import TYPED_TRACKING_CLASSES, typed_tracking_class  # noqa: E402
from scripts.lib.cio_ask_store import AskEventStore  # noqa: E402

BHVN_GUID = "11111111-1111-5111-8111-111111111111"
CARD_REVIEW_GUID = "ent_aaaaaaaa-aaaa-5aaa-8aaa-aaaaaaaaaaaa"
CARD_WATCH_GUID = "ent_bbbbbbbb-bbbb-5bbb-8bbb-bbbbbbbbbbbb"
CARD_RISK_GUID = "ent_cccccccc-cccc-5ccc-8ccc-cccccccccccc"
PRIVATE_GUID = "ent_dddddddd-dddd-5ddd-8ddd-dddddddddddd"


def _entity_resolved(thread_id: str, entity: dict) -> dict:
    return {"schema": "CioAskEvent@v1", "kind": "ask.entity_resolved", "thread_id": thread_id,
            "at": "2026-11-04T15:59:53Z", "entity": entity}


def _tracking_changed(thread_id: str, key: str, name: str, *, symbol=None, state="tracked") -> dict:
    return {"schema": "CioAskEvent@v1", "kind": "ask.tracking_changed", "thread_id": thread_id,
            "entity_key": key, "name": name, "symbol": symbol, "state": state, "by": "auto",
            "at": "2026-11-04T15:59:54Z", "actions": {}}


def _store(tmp_path, events: list[dict]) -> AskEventStore:
    path = tmp_path / "cio_ask_events.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    return AskEventStore(path)


def _ledger_like_the_bhvn_thread() -> list[dict]:
    """The shape the live ledger actually carries (2026-11-04): one real security plus a pasted card's headings."""
    return [
        _entity_resolved("thr_bhvn", {"kind": "security", "name": "BHVN", "symbol": "BHVN", "security_guid": BHVN_GUID,
                                      "issuer_guid": None, "entity_guid": None, "resolution": "CONFIRMED", "note": None}),
        _tracking_changed("thr_bhvn", BHVN_GUID, "BHVN", symbol="BHVN"),
        _entity_resolved("thr_bhvn", {"kind": "private_entity", "name": "Review BHVN", "symbol": None,
                                      "security_guid": None, "issuer_guid": None, "entity_guid": CARD_REVIEW_GUID,
                                      "resolution": "UNRESOLVED_PRIVATE", "note": "no listed security"}),
        _tracking_changed("thr_bhvn", CARD_REVIEW_GUID, "Review BHVN"),
        _entity_resolved("thr_bhvn", {"kind": "private_entity", "name": "WATCH Card", "symbol": None,
                                      "security_guid": None, "issuer_guid": None, "entity_guid": CARD_WATCH_GUID,
                                      "resolution": "UNRESOLVED_PRIVATE", "note": "no listed security"}),
        _tracking_changed("thr_bhvn", CARD_WATCH_GUID, "WATCH Card"),
        _entity_resolved("thr_bhvn", {"kind": "private_entity", "name": "Risk", "symbol": None,
                                      "security_guid": None, "issuer_guid": None, "entity_guid": CARD_RISK_GUID,
                                      "resolution": "UNRESOLVED_PRIVATE", "note": "no listed security"}),
        _tracking_changed("thr_bhvn", CARD_RISK_GUID, "Risk"),
        # a name-only private company: tracked on its thread, but still no typed identity for a global chip
        _entity_resolved("thr_private", {"kind": "private_entity", "name": "SpaceX", "symbol": None,
                                         "security_guid": None, "issuer_guid": None, "entity_guid": PRIVATE_GUID,
                                         "resolution": "UNRESOLVED_PRIVATE", "note": "no listed security"}),
        _tracking_changed("thr_private", PRIVATE_GUID, "SpaceX"),
    ]


def test_typed_tracking_class_names_only_symbol_account_thread():
    assert TYPED_TRACKING_CLASSES == ("symbol", "account", "thread")
    assert typed_tracking_class({"kind": "security", "symbol": "BHVN"}) == "symbol"
    assert typed_tracking_class({"kind": "account", "name": "Schwab Roth"}) == "account"
    assert typed_tracking_class({"kind": "thread", "name": "BHVN thread"}) == "thread"
    assert typed_tracking_class({"kind": "private_entity", "name": "X", "account_key": "schwab_roth"}) == "account"
    # A name alone is not a typed identity — the card-heading case, and a real private company alike.
    assert typed_tracking_class({"kind": "private_entity", "name": "Review BHVN"}) is None
    assert typed_tracking_class({"kind": "private_entity", "name": "SpaceX"}) is None
    assert typed_tracking_class({"kind": "unresolved", "name": "Sources"}) is None
    assert typed_tracking_class({}) is None


def test_tracked_entities_never_publish_a_name_only_private_entity(tmp_path):
    rows = _store(tmp_path, _ledger_like_the_bhvn_thread()).tracked_entities()
    names = {r.get("name") for r in rows}
    assert names == {"BHVN"}, f"card headings must not be header entities; got {sorted(str(n) for n in names)}"
    assert all(r.get("symbol") for r in rows), "every published entity is typed"
    bhvn = rows[0]
    assert bhvn["thread_id"] == "thr_bhvn" and bhvn["symbol"] == "BHVN" and bhvn["security_guid"] == BHVN_GUID
    # "keep the thread context": the real entity still points at the thread it was asked in
    assert bhvn["thread_id"] == "thr_bhvn"


def test_tracked_entities_keeps_account_and_thread_entities(tmp_path):
    acct_key, thread_key = "ent_acct_0001", "ent_thread_0001"
    events = _ledger_like_the_bhvn_thread() + [
        _entity_resolved("thr_acct", {"kind": "account", "name": "Schwab Roth", "symbol": None,
                                      "account_key": "schwab_roth", "entity_guid": acct_key}),
        _tracking_changed("thr_acct", acct_key, "Schwab Roth"),
        _entity_resolved("thr_thr", {"kind": "thread", "name": "BHVN thread", "symbol": None, "entity_guid": thread_key}),
        _tracking_changed("thr_thr", thread_key, "BHVN thread"),
    ]
    rows = _store(tmp_path, events).tracked_entities()
    classes = {typed_tracking_class(r) for r in rows}
    assert classes == {"symbol", "account", "thread"}, classes
    assert {r["thread_id"] for r in rows} == {"thr_bhvn", "thr_acct", "thr_thr"}


def test_untracked_typed_entity_is_not_published(tmp_path):
    events = _ledger_like_the_bhvn_thread() + [_tracking_changed("thr_bhvn", BHVN_GUID, "BHVN", symbol="BHVN",
                                                                state="untracked")]
    rows = _store(tmp_path, events).tracked_entities()
    assert rows == []


# ── F1 (review cc-deepseek-2, 16:50:33Z): the filtered rows must be NAMED, not silently dropped ────────────────
#
# `tracked: []` was byte-identical whether nothing was tracked or a name-only entity was tracked and filtered out.
# That is an absence of evidence served as evidence of absence. The census rides beside the rows; the page may
# render it or not, but the read names the population the header cannot chip.


def test_untyped_tracked_entities_are_named_in_a_census(tmp_path):
    store = _store(tmp_path, _ledger_like_the_bhvn_thread())
    census = store.untyped_tracked_entities()
    assert {r["name"] for r in census} == {"Review BHVN", "WATCH Card", "Risk", "SpaceX"}, census
    assert all(r["thread_id"] for r in census), "the census keeps each row's thread context"
    assert not {r["name"] for r in census} & {r["name"] for r in store.tracked_entities()}, \
        "the two populations are disjoint: the census never promotes a row into the header"
    assert {r["thread_id"] for r in census if r["name"] == "SpaceX"} == {"thr_private"}
    assert census[0]["key"], "each census row is addressable by the key its thread already holds"


if __name__ == "__main__":
    import tempfile

    fails = 0
    with tempfile.TemporaryDirectory() as d:
        for fn in (test_typed_tracking_class_names_only_symbol_account_thread,
                   test_tracked_entities_never_publish_a_name_only_private_entity,
                   test_tracked_entities_keeps_account_and_thread_entities,
                   test_untracked_typed_entity_is_not_published,
                   test_untyped_tracked_entities_are_named_in_a_census):
            try:
                if fn.__code__.co_argcount:
                    fn(Path(d))
                else:
                    fn()
                print(f"  [PASS] {fn.__name__}")
            except AssertionError as exc:  # noqa: BLE001
                fails += 1
                print(f"  [FAIL] {fn.__name__}: {exc}")
    print(f"obs_h1_tracked_typed: {5 - fails} passed, {fails} failed")
    sys.exit(1 if fails else 0)
