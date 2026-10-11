"""W5 — event-triggered consumers on the Data Broker domain as_of (CONSOLIDATION_PLAN §B.3 W5, §E.4).

coordination/due source "event" (scripts/lib/n8n_due.py `_event_evals`), the file-only as_of readers and the owner
emit (scripts/lib/data_broker/as_of_signal.py, scripts/news_ingestion.py), the `broker_as_of` / `run_done` trigger
schema (scripts/lib/lane_dispatch.py), and the three registry rows that carry triggers.

Paths covered: producer as_of -> due item (dry_run, reason event, e: key) -> gateway `run` accepts the key -> the
executor runs it under the stage clamp (dry_run) with the cron line's flock lock; and no double fire when the cron
line and the event are both due — at due level (a schedule slot due/in flight absorbs the event; the cron line's
receipt watermark covers it) and at run level (the shared flock lock: RUN_SKIPPED_LOCK, then the key is DONE).

Hermetic: tmp_path state root and ledger (TRADEAI_STATE_ROOT is monkeypatched), frozen clocks, the repo's retry
policies read as data, a real `flock` binary on a tmp lock with `/bin/true` as the command. No socket, no live
ledger, no DB, no provider, no send.
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import n8n_run_executor as X  # noqa: E402
from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib import n8n_coordination_gateway as G  # noqa: E402
from scripts.lib import n8n_due as D  # noqa: E402
from scripts.lib import n8n_retry_policy as RP  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore  # noqa: E402

AS = LD.as_of_signal_module()
POLICIES = RP.load_policies(ROOT / "config" / "n8n_retry_policies.json")
SCHEMA_PATH = ROOT / "docs" / "implementation" / "n8n-maturity" / "schemas" / "due-response.schema.json"
# Wednesday 2026-10-14 10:10 America/New_York (EDT) = 14:10 UTC
NOW = datetime(2026, 10, 14, 14, 10, tzinfo=timezone.utc)
LANE = "fusion-lane"
W5_LANES = {
    "signal-fusion-active": [{"source": "broker_as_of", "domain": "scalp_list"}],
    "news-to-catalyst": [
        {"source": "broker_as_of", "domain": "catalyst_news"},
        {"source": "run_done", "lane_id": "hermes-news-bridge"},
    ],
    "research-insight-extractor": [{"source": "run_done", "lane_id": "news-to-catalyst"}],
}
#: W5 trigger rows that canary wave 1 moved to canary (live cron slots; event fires inert while live).
W5_CANARY_LANES = frozenset({"research-insight-extractor"})


# ── fixtures and helpers ────────────────────────────────────────────────────────────────────────


@pytest.fixture
def state(tmp_path, monkeypatch):
    root = tmp_path / "state"
    (root / "data" / "runtime").mkdir(parents=True)
    (root / "data" / "trade_ai").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(root))
    monkeypatch.delenv("MOMENTUM_SCALP_REFRESH_RECEIPT", raising=False)
    monkeypatch.delenv("DATA_BROKER_AS_OF_EMIT", raising=False)
    return root


@pytest.fixture
def store(tmp_path):
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    yield LedgerRunStore(ledger)
    ledger.close()


def _row(lane=LANE, cron=("0 9 * * *",), *, mode="dry_run", triggers=None, min_interval=None, signal=True):
    d = {"mode": mode, "cron": list(cron), "class": "monitor", "priority": 5, "retry_policy": "none", "wave": "W3"}
    d["triggers"] = triggers if triggers is not None else [{"source": "broker_as_of", "domain": "scalp_list"}]
    if min_interval is not None:
        d["min_interval_s"] = min_interval
    row = {"lane_id": lane, "scheduler": {"kind": "cron", "expression": cron[0], "stage": "shadow"}, "dispatch": d}
    if signal:
        row["output_signal"] = {"kind": "json_key", "path": f"data/runtime/{lane}_last.json", "key": "ok_at"}
    return row


def _allow(*lanes, lock_dir: Path | None = None):
    out = {}
    for lane in lanes:
        out[lane] = {
            "lane_id": lane,
            "command": ["/bin/true"],
            "dry_run_arg": ["--dry-run"],
            "live_arg": None,
            "lock": str((lock_dir or Path("/nonexistent")) / f"{lane}.lock"),
            "lock_kind": "flock",
            "timeout_s": 30,
            "market_gate": False,
            "env_names": ["PATH"],
            "output_signal": f"data/runtime/{lane}_last.json",
        }
    return out


def _universe(root: Path, as_of: datetime) -> None:
    doc = {
        "schema": "TradeAIScalpUniverse@v1",
        "as_of": as_of.isoformat(),
        "writer": "run_trade_ai_scalp_live",
        "rows": [{"symbol": "ABC"}],
    }
    (root / "data" / "trade_ai" / "scalp_universe_latest.json").write_text(json.dumps(doc))


def _refresh(root: Path, at: datetime, state_: str = "DONE") -> None:
    doc = {
        "schema": "MomentumScalpRefreshReceipt@v1",
        "state": state_,
        "at": at.isoformat(),
        "screener_ids": ["prime_setups"],
    }
    (root / "data" / "runtime" / "momentum_scalp_refresh_receipt.json").write_text(json.dumps(doc))


def _lane_receipt(root: Path, lane: str, started: datetime, status: str = "ok") -> None:
    doc = {
        "schema": "LaneRunReceipt@v1",
        "lane_id": lane,
        "status": status,
        "started_at": started.isoformat(),
        "finished_at": (started + timedelta(seconds=5)).isoformat(),
    }
    (root / "data" / "runtime" / f"{lane}_last.json").write_text(json.dumps(doc))


def _put(store, run_id, lane, mode, state_, *, requested=None, started=None, finished=None):
    store.request(
        run_id=run_id,
        lane_id=lane,
        mode=mode,
        requested_by="t",
        caller_id="t",
        now=(requested or NOW - timedelta(minutes=1)).timestamp(),
    )
    if state_ != "REQUESTED":
        store._l._conn.execute(
            "UPDATE runs SET state = ?, started_at = ?, finished_at = ? WHERE run_id = ?",
            (state_, started.isoformat() if started else None, finished.isoformat() if finished else None, run_id),
        )
        store._l._conn.commit()


def _event(rows, allow, store=None, now=NOW, **kw):
    return D.compute_due(rows, allow, POLICIES, store, now, source="event", **kw)


def _keys(resp):
    return [i["idempotency_key"] for i in resp["items"]]


def _validate(resp):
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        import jsonschema  # type: ignore
    except ImportError:
        from tests.test_n8n_maturity_due_20261009 import _check

        _check(resp, schema, schema)
    else:
        jsonschema.validate(resp, schema)


# ── 1. the as_of readers and the owner emit ───────────────────────────────────────────────────────


def test_scalp_list_as_of_is_the_fresher_owner_file(state):
    assert AS.read_as_of("scalp_list").as_of is None
    _universe(state, NOW - timedelta(minutes=20))
    _refresh(state, NOW - timedelta(minutes=4))
    got = AS.read_as_of("scalp_list")
    assert got.as_of == NOW - timedelta(minutes=4) and got.error is None
    _refresh(state, NOW - timedelta(minutes=1), state_="RUNNING")  # not DONE: not an as_of
    assert AS.read_as_of("scalp_list").as_of == NOW - timedelta(minutes=20)


def test_naive_writer_stamps_are_host_local(state):
    naive = (NOW - timedelta(minutes=3)).astimezone().replace(tzinfo=None)
    _refresh(state, naive)
    assert AS.read_as_of("scalp_list").as_of == NOW - timedelta(minutes=3)


def test_emit_advances_as_of_only_when_rows_were_written(state):
    t1, t2 = NOW - timedelta(minutes=30), NOW - timedelta(minutes=5)
    assert AS.read_as_of("catalyst_news").error == "missing"
    p = AS.emit_as_of("catalyst_news", rows_written=3, lane_id="news-ingestion", source="t", at=t1)
    assert p == state / "data" / "runtime" / "broker_as_of" / "catalyst_news.json"
    AS.emit_as_of("catalyst_news", rows_written=0, lane_id="news-ingestion", source="t", at=t2)
    doc = json.loads(p.read_text())
    assert doc["schema"] == "BrokerAsOf@v1" and doc["as_of"] == t1.isoformat() and doc["checked_at"] == t2.isoformat()
    assert AS.read_as_of("catalyst_news").as_of == t1


def test_emit_flag_off_unknown_domain_and_unwritable_root_write_nothing_and_never_raise(state, tmp_path):
    assert (
        AS.emit_as_of(
            "catalyst_news",
            rows_written=1,
            lane_id="x",
            source="t",
            env={"DATA_BROKER_AS_OF_EMIT": "0", "TRADEAI_STATE_ROOT": str(state)},
        )
        is None
    )
    assert AS.emit_as_of("scalp_list", rows_written=1, lane_id="x", source="t") is None  # owner already emits
    blocker = tmp_path / "file-not-dir"
    blocker.write_text("x")
    assert AS.emit_as_of("catalyst_news", rows_written=1, lane_id="x", source="t", root=blocker) is None
    assert not (state / "data" / "runtime" / "broker_as_of").exists()
    assert AS.read_as_of("nope").error == "unknown_domain"


def test_news_ingestion_owner_emits_after_its_run(state, monkeypatch):
    import news_ingestion as NI

    NI._emit_catalyst_news_as_of("priority", 2)
    doc = json.loads((state / "data" / "runtime" / "broker_as_of" / "catalyst_news.json").read_text())
    assert doc["lane_id"] == "news-ingestion" and doc["rows_written"] == 2 and doc["as_of"]
    NI._emit_catalyst_news_as_of("tail_rotate", 0)
    doc2 = json.loads((state / "data" / "runtime" / "broker_as_of" / "catalyst_news.json").read_text())
    assert doc2["lane_id"] == "news-ingestion-tail" and doc2["as_of"] == doc["as_of"]
    src = (ROOT / "scripts" / "news_ingestion.py").read_text()
    assert src.count('_emit_catalyst_news_as_of(mode, stats["new_articles"])') == 1  # once, after the heartbeat


# ── 2. trigger schema ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "trig,needle",
    [
        ({"source": "broker_as_of"}, "needs a domain"),
        ({"source": "run_done"}, "needs a lane_id"),
        ({"source": "receipt", "domain": "scalp_list"}, "only for source broker_as_of"),
        ({"source": "broker_as_of", "domain": "Bad-Name"}, "not a domain name"),
    ],
)
def test_malformed_triggers_fail_closed(trig, needle):
    with pytest.raises(LD.DispatchBlockError) as exc:
        LD.parse_dispatch_block(_row(triggers=[trig]))
    assert needle in str(exc.value)


def test_unknown_broker_domain_is_a_registry_finding():
    issues = LD.validate_dispatch_block(
        _row(triggers=[{"source": "broker_as_of", "domain": "no_such_domain"}]),
        known_lane_ids={LANE},
        retry_policy_names={"none"},
    )
    assert [i.code for i in issues] == [LD.ISSUE_BAD_BLOCK] and "no as_of reader" in issues[0].detail


# ── 3. event -> due -> run -> dry_run fire ────────────────────────────────────────────────────────


def test_event_to_due_to_gateway_run_to_dry_run_fire(state, store, tmp_path):
    _refresh(state, NOW - timedelta(minutes=3))  # 10:07 ET
    rows = [_row()]
    allow = _allow(LANE, lock_dir=tmp_path)
    resp = _event(rows, allow, store)
    _validate(resp)
    assert resp["items"] == [
        {
            "lane_id": LANE,
            "mode": "dry_run",
            "idempotency_key": f"e:{LANE}:dry_run:20261014T1007",
            "attempt": 1,
            "slot_local": "20261014T1007",
            "reason": "event",
            "priority": 5,
        }
    ]
    assert _due_schedule_is_unchanged(rows, allow, store)
    key = resp["items"][0]["idempotency_key"]
    sources = D.DueSources(
        load_registry=lambda: (rows, "1" * 64),
        load_allowlist=lambda: (allow, "2" * 64),
        load_policies=lambda: (POLICIES, "3" * 64),
    )
    out = G._run(
        {"lane_id": LANE, "mode": "dry_run", "idempotency_key": key},
        {"caller_id": "n8n-relay"},
        run_store=store,
        run_allowlist=set(allow),
        now=NOW.timestamp(),
        peer=None,
        due_sources=sources,
    )
    assert out.get("state") == "REQUESTED", out
    forged = f"e:{LANE}:dry_run:20261014T1001"
    refused = G._run(
        {"lane_id": LANE, "mode": "dry_run", "idempotency_key": forged},
        {"caller_id": "n8n-relay"},
        run_store=store,
        run_allowlist=set(allow),
        now=NOW.timestamp(),
        peer=None,
        due_sources=sources,
    )
    assert refused.get("reason") == "run_slot_not_due" and refused.get("slot_state") == "NOT_A_SLOT"
    claimed = store.claim_next(now=NOW.timestamp())
    assert claimed["run_id"] == key
    receipt = X.execute(
        claimed,
        allow[LANE],
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        state_root=state,
        code_root=ROOT,
        stage_rows=rows,
    )
    assert receipt["state"] == "RUN_DONE" and receipt["mode"] == "dry_run" and receipt["argv"][-1] == "--dry-run"
    assert receipt["argv"][:5] == ["flock", "-n", "-E", str(X.FLOCK_CONFLICT_EXIT), str(tmp_path / f"{LANE}.lock")]
    store.finish(key, state=receipt["state"], receipt=receipt, now=(NOW + timedelta(seconds=30)).timestamp())
    later = _event(rows, allow, store, now=NOW + timedelta(minutes=1))
    assert later["items"] == []  # the fire is the new watermark


def _due_schedule_is_unchanged(rows, allow, store) -> bool:
    """The event source mints no d: key and the schedule source mints no e: key."""
    sched = D.compute_due(rows, allow, POLICIES, store, NOW, source="schedule")
    return all(k.startswith("d:") for k in _keys(sched))


def test_run_done_trigger_chains_a_dry_run_stage(state, store):
    rows = [
        _row("up-lane", triggers=[{"source": "broker_as_of", "domain": "catalyst_news"}]),
        _row("down-lane", triggers=[{"source": "run_done", "lane_id": "up-lane"}]),
    ]
    allow = _allow("up-lane", "down-lane")
    assert _keys(_event(rows, allow, store)) == []
    _put(
        store,
        "e:up-lane:dry_run:20261014T1001",
        "up-lane",
        "dry_run",
        "RUN_DONE",
        started=NOW - timedelta(minutes=8),
        finished=NOW - timedelta(minutes=6),
    )
    assert _keys(_event(rows, allow, store)) == ["e:down-lane:dry_run:20261014T1004"]


def test_live_block_triggers_fire_nothing_shadow_first(state, store):
    _refresh(state, NOW - timedelta(minutes=3))
    resp = _event([_row(mode="live")], {LANE: {**_allow(LANE)[LANE], "live_arg": ["--apply"]}}, store)
    assert resp["items"] == [] and D.EVENT_MODES == ("dry_run",)


# ── 4. watermark, window, debounce ────────────────────────────────────────────────────────────────


def test_cron_receipt_watermark_covers_the_event(state, store):
    _refresh(state, NOW - timedelta(minutes=3))
    _lane_receipt(state, LANE, NOW - timedelta(minutes=2))  # the cron line started after the as_of
    assert _event([_row()], _allow(LANE), store)["items"] == []
    _lane_receipt(state, LANE, NOW - timedelta(minutes=9))  # it started before: still an event
    assert _keys(_event([_row()], _allow(LANE), store)) == [f"e:{LANE}:dry_run:20261014T1007"]
    _lane_receipt(state, LANE, NOW - timedelta(minutes=1), status="failed")
    assert len(_event([_row()], _allow(LANE), store)["items"]) == 1  # a failed run is no watermark


def test_as_of_outside_the_window_or_in_the_future(state, store):
    _refresh(state, NOW - timedelta(minutes=45))  # policy none: catchup 30 min
    assert _event([_row()], _allow(LANE), store)["items"] == []
    _refresh(state, NOW + timedelta(minutes=10))
    resp = _event([_row()], _allow(LANE), store)
    assert resp["items"] == [] and resp["errors"][0]["code"] == "trigger_source_unreadable"


def test_missing_source_is_reported_not_fatal(state, store):
    rows = [_row("news-lane", triggers=[{"source": "broker_as_of", "domain": "catalyst_news"}]), _row()]
    _refresh(state, NOW - timedelta(minutes=3))
    resp = _event(rows, _allow("news-lane", LANE), store)
    _validate(resp)
    assert _keys(resp) == [f"e:{LANE}:dry_run:20261014T1007"]
    assert resp["errors"] == [
        {
            "lane_id": "news-lane",
            "code": "trigger_source_unreadable",
            "detail": "triggers[0] broker_as_of catalyst_news: missing",
        }
    ]


def test_min_interval_debounces_a_burst(state, store):
    rows = [_row(min_interval=900)]
    _put(
        store,
        f"e:{LANE}:dry_run:20261014T1001",
        LANE,
        "dry_run",
        "RUN_DONE",
        requested=NOW - timedelta(minutes=8),
        started=NOW - timedelta(minutes=8),
        finished=NOW - timedelta(minutes=7),
    )
    _refresh(state, NOW - timedelta(minutes=2))  # a newer as_of 6 min after the last fire
    assert _event(rows, _allow(LANE), store)["items"] == []
    chk = D.check_slot_key(
        f"e:{LANE}:dry_run:20261014T1008",
        LANE,
        "dry_run",
        registry_rows=rows,
        allowlist=_allow(LANE),
        policies=POLICIES,
        run_store=store,
        now=NOW,
    )
    assert tuple(chk) == (False, "DEBOUNCED")
    later = NOW + timedelta(minutes=8)  # 16 min after the last request
    assert _keys(_event(rows, _allow(LANE), store, now=later)) == [f"e:{LANE}:dry_run:20261014T1008"]


def test_two_advances_in_one_minute_coalesce_into_one_key(state, store):
    _refresh(state, NOW - timedelta(seconds=50))
    first = _keys(_event([_row()], _allow(LANE), store))
    _refresh(state, NOW - timedelta(seconds=10))
    assert _keys(_event([_row()], _allow(LANE), store)) == first == [f"e:{LANE}:dry_run:20261014T1009"]


# ── 5. no double fire when the cron line / schedule and the event are both due ─────────────────────


def test_schedule_slot_due_now_absorbs_the_event(state, store):
    rows = [_row(cron=("*/30 * * * *",))]  # 10:00 slot is in the catch-up window
    _refresh(state, NOW - timedelta(minutes=3))
    assert _keys(D.compute_due(rows, _allow(LANE), POLICIES, store, NOW)) == [f"d:{LANE}:dry_run:20261014T1000"]
    assert _event(rows, _allow(LANE), store)["items"] == []
    chk = D.check_slot_key(
        f"e:{LANE}:dry_run:20261014T1007",
        LANE,
        "dry_run",
        registry_rows=rows,
        allowlist=_allow(LANE),
        policies=POLICIES,
        run_store=store,
        now=NOW,
    )
    assert tuple(chk) == (False, "COALESCED")


def test_in_flight_schedule_run_holds_the_event_until_it_finishes(state, store):
    rows = [_row(cron=("*/30 * * * *",))]
    _refresh(state, NOW - timedelta(minutes=3))
    _put(store, f"d:{LANE}:dry_run:20261014T1000", LANE, "dry_run", "RUNNING", started=NOW - timedelta(minutes=9))
    assert _event(rows, _allow(LANE), store)["items"] == []
    store._l._conn.execute(
        "UPDATE runs SET state='RUN_DONE', finished_at=? WHERE run_id=?",
        ((NOW - timedelta(seconds=30)).isoformat(), f"d:{LANE}:dry_run:20261014T1000"),
    )
    store._l._conn.commit()
    # that run started BEFORE the as_of, so it did not see the new list: the event fires now
    assert _keys(_event(rows, _allow(LANE), store)) == [f"e:{LANE}:dry_run:20261014T1007"]


def test_cron_line_holding_the_lock_makes_the_event_fire_a_lock_skip_and_no_refire(state, store, tmp_path):
    _refresh(state, NOW - timedelta(minutes=3))
    rows = [_row()]
    allow = _allow(LANE, lock_dir=tmp_path)
    key = _keys(_event(rows, allow, store))[0]
    store.request(
        run_id=key, lane_id=LANE, mode="dry_run", requested_by="t", caller_id="n8n-relay", now=NOW.timestamp()
    )
    claimed = store.claim_next(now=NOW.timestamp())
    lock = tmp_path / f"{LANE}.lock"
    with open(lock, "w") as held:  # the live cron line's `flock -n` holds it
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipt = X.execute(
            claimed,
            allow[LANE],
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
            state_root=state,
            code_root=ROOT,
            stage_rows=rows,
        )
    assert receipt["state"] == "RUN_SKIPPED_LOCK" and receipt["lock_skipped"] is True
    store.finish(key, state=receipt["state"], receipt=receipt, now=NOW.timestamp())
    resp = _event(rows, allow, store, now=NOW + timedelta(minutes=1))
    assert resp["items"] == [] and resp["counts"]["DONE"] == 1  # one run per as_of: no refire storm


def test_event_due_is_read_only(state, store):
    _refresh(state, NOW - timedelta(minutes=3))
    before = store._l._conn.total_changes
    _event([_row()], _allow(LANE), store)
    assert store._l._conn.total_changes == before
    assert sorted(p.name for p in (state / "data" / "runtime").iterdir()) == ["momentum_scalp_refresh_receipt.json"]


# ── 6. the registry rows ──────────────────────────────────────────────────────────────────────────


def test_w5_registry_rows_are_shadow_dry_run_with_their_triggers():
    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text())
    allow = {e["lane_id"]: e for e in json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())["lanes"]}
    by_id = {r["lane_id"]: r for r in reg["lanes"]}
    with_triggers = {r["lane_id"] for r in reg["lanes"] if (r.get("dispatch") or {}).get("triggers")}
    assert with_triggers == set(W5_LANES)
    for lane, trig in W5_LANES.items():
        row = by_id[lane]
        block = LD.parse_dispatch_block(row)
        assert row["dispatch"]["triggers"] == trig and block.min_interval_s >= 900
        if lane in W5_CANARY_LANES:
            # canary wave 1 (2026-10-11, merged in train-migration-20261011) moved this row to canary: dispatch.mode
            # live on its cron slots; its triggers stay inert (n8n_due.EVENT_MODES is dry_run only) until the
            # operator rules an event canary.
            assert block.mode == "live" and block.mode not in D.EVENT_MODES
            assert row["scheduler"]["stage"] == "canary" and allow[lane]["live_arg"] is not None
        else:
            assert block.mode == "dry_run"
            assert row["scheduler"]["stage"] == "shadow" and allow[lane]["live_arg"] is None
        assert LD.dispatch_eligible(row)[0] and LD.r1_class_admission(row, allow[lane])[0]
        assert all(t.domain in AS.DOMAINS for t in block.triggers if t.source == "broker_as_of")
        assert LD.validate_dispatch_block(row, known_lane_ids=set(by_id), retry_policy_names={"none"}) == []


def test_w5_rows_fire_on_the_real_registry(state, store):
    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text())
    allow = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())
    # Wednesday 06:20 ET: before signal-fusion-active's next */30 slot is due, after its 06:00 slot ran
    now = datetime(2026, 10, 14, 10, 20, tzinfo=timezone.utc)
    _put(
        store,
        "d:signal-fusion-active:dry_run:20261014T0600",
        "signal-fusion-active",
        "dry_run",
        "RUN_DONE",
        started=now - timedelta(minutes=20),
        finished=now - timedelta(minutes=19),
    )
    _refresh(state, now - timedelta(minutes=2))
    AS.emit_as_of("catalyst_news", rows_written=5, lane_id="news-ingestion", source="t", at=now - timedelta(minutes=4))
    resp = D.compute_due(reg, allow, POLICIES, store, now, source="event")
    _validate(resp)
    assert _keys(resp) == ["e:news-to-catalyst:dry_run:20261014T0616", "e:signal-fusion-active:dry_run:20261014T0618"]
    assert {i["mode"] for i in resp["items"]} == {"dry_run"} and resp["errors"] == []
