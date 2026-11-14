"""LQ-20261107-2144 — Home "Trade-ready" verdict: the approved rule, the served read, the lane and its registration.

ANCHOR: HOME_TRADE_READY_20261112

Design: Home v010 (REPORT.md 4-6, DECISION.md 2026-11-11 22:48 ET) and HOME-BACKEND-SPEC-20261111 section 2 LQ-2144.
Lead alignment 22:57 ET: I1 (a READ proven blocker gives NO even when another input is unreadable; the unreadable
inputs are still listed) and I2 (unreadable Portfolio/Orders/Data = UNKNOWN) are build defaults; the incident class
-> P-level map (D2) is NOT decided, so the lane carries no default P0 mapping and cannot report a known P0/P1 state
until the operator approves the map. YES is never served from a stale snapshot.

Everything here is synthetic (ZQ* symbols, tmp_path state roots, an in-memory fake DB). No database, no HTTP, no
broker, nothing durable is written.
"""

from __future__ import annotations

import itertools
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import home_trade_ready as htr  # noqa: E402
from scripts.lib.home_trade_ready import Item, Reading  # noqa: E402
from scripts import home_status_verdict as lane  # noqa: E402

ET = ZoneInfo("America/New_York")
# Wednesday 2026-11-11 10:30 ET: in session. Saturday 2026-11-14 12:00 ET: off session.
NOW = datetime(2026, 11, 11, 10, 30, tzinfo=ET).astimezone(timezone.utc)
SAT = datetime(2026, 11, 14, 12, 0, tzinfo=ET).astimezone(timezone.utc)
LID = "home-status-verdict"
SCRIPT = "scripts/home_status_verdict.py"
SIGNAL = f"data/runtime/{LID}_last.json"
# LQ-2411: the R3 block exactly as shipped in config/home_status_registry.json (every verdict here runs under it).
POLICY = json.loads((ROOT / "config" / "home_status_registry.json").read_text(encoding="utf-8"))["protection_verdict"]


# ── reading builders ────────────────────────────────────────────────────────────────────────────


def fresh(name: str, state: str = htr.OK, items=None, value=None, now: datetime = NOW) -> Reading:
    return Reading(name=name, state=state, value=value, as_of=(now - timedelta(seconds=30)).isoformat(),
                   threshold_s=600, source_id=f"src-{name}", owner="ops", items=list(items or []))


def stale(name: str, now: datetime = NOW) -> Reading:
    return Reading(name=name, state=htr.OK, as_of=(now - timedelta(hours=5)).isoformat(), threshold_s=600,
                   source_id=f"src-{name}", owner="ops")


def blocking_item(name: str) -> Item:
    return Item(id=f"{name}-1", title=f"synthetic {name}", blocks_trading=True, first_seen_at=NOW.isoformat())


def non_blocking_item(name: str) -> Item:
    return Item(id=f"{name}-nb", title=f"synthetic non-blocking {name}", blocks_trading=False)


def all_ok(now: datetime = NOW) -> dict[str, Reading]:
    return {n: fresh(n, now=now) for n in htr.REQUIRED_INPUTS}


def verdict(readings: dict[str, Reading], now: datetime = NOW) -> dict:
    return htr.compute_verdict(list(readings.values()), now, run_id="test:1", policy=POLICY)


# ── 1. the exhaustive truth table ───────────────────────────────────────────────────────────────
#
# Count inputs (p0, p1_blocking, gates) take six variants and row inputs (portfolio, orders, data) six (LQ-2172 / D1
# adds GAP = confirmed unprotected); schedulers takes three. 6**3 * 6**3 * 3 = 139,968 cases, every one checked against
# an independent oracle written from DECISION.md and the operator decisions of 2026-11-11 23:19 ET. LQ-2411 adds the
# D2-b incident_classes guard (ok/unknown) and R3 (true, and false for the no-scheduler slice): 373,248 cases.

COUNT_VARIANTS = ("ok_empty", "ok_non_blocking", "blocking", "stale", "unknown", "timed_out")
ROW_VARIANTS = ("ok", "warn", "gap", "stale", "unknown", "timed_out")
SCHED_VARIANTS = ("ok", "warn", "unknown")


def count_reading(name: str, variant: str) -> Reading:
    if variant == "ok_empty":
        return fresh(name)
    if variant == "ok_non_blocking":
        # a P0 is always blocking, so p0 has no non-blocking variant: draw it as empty
        return fresh(name) if name == htr.P0 else fresh(name, items=[non_blocking_item(name)])
    if variant == "blocking":
        return fresh(name, state=htr.WARN, items=[blocking_item(name)])
    if variant == "stale":
        return stale(name)
    if variant == "unknown":
        return htr.unknown(name, "synthetic unreadable")
    r = htr.unknown(name, "synthetic timeout")
    r.state = htr.TIMED_OUT
    return r


def row_reading(name: str, variant: str) -> Reading:
    if variant == "ok":
        return fresh(name)
    if variant == "warn":
        return fresh(name, state=htr.WARN)
    if variant == "gap":
        return fresh(name, state="GAP")
    if variant == "stale":
        return stale(name)
    if variant == "unknown":
        return htr.unknown(name, "synthetic unreadable")
    r = htr.unknown(name, "synthetic timeout")
    r.state = htr.TIMED_OUT
    return r


def sched_reading(variant: str) -> Reading:
    if variant == "ok":
        return fresh(htr.SCHEDULERS)
    if variant == "warn":
        return fresh(htr.SCHEDULERS, state=htr.WARN, value=2)
    return htr.unknown(htr.SCHEDULERS, "synthetic unreadable")


def oracle(count_v: dict[str, str], row_v: dict[str, str], classes_v: str = "ok",
           r3: bool = True) -> tuple[str, set[str]]:
    """DECISION.md, written independently of compute_verdict: (verdict, the set of unknown inputs).

    LQ-2411: ``classes_v`` is the D2-b incident_classes guard (unknown = an unclassified incident is open; never NO);
    ``r3`` is protection_verdict.confirmed_no_overrides_unknown (false: UNKNOWN beats NO)."""
    no = any(v == "blocking" for v in count_v.values()) or any(v in ("warn", "gap", "stale") for v in row_v.values())
    unknown_set = {n for n, v in count_v.items() if v in ("stale", "unknown", "timed_out")}
    unknown_set |= {n for n, v in row_v.items() if v in ("unknown", "timed_out")}
    if classes_v != "ok":
        unknown_set.add(htr.INCIDENT_CLASSES)
    if no and (r3 or not unknown_set):
        return htr.NO, unknown_set
    if unknown_set:
        return htr.UNKNOWN, unknown_set
    return htr.YES, unknown_set


def test_truth_table_is_exhaustive_and_matches_the_approved_rule():
    counts = (htr.P0, htr.P1_BLOCKING, htr.GATES)
    rows = (htr.PORTFOLIO, htr.ORDERS, htr.DATA)
    seen = {htr.YES: 0, htr.NO: 0, htr.UNKNOWN: 0}
    n = 0
    for cv in itertools.product(COUNT_VARIANTS, repeat=3):
        for rv in itertools.product(ROW_VARIANTS, repeat=3):
            count_v = dict(zip(counts, cv))
            row_v = dict(zip(rows, rv))
            base = [count_reading(k, v) for k, v in count_v.items()] + [row_reading(k, v) for k, v in row_v.items()]
            for sv, gv, r3 in itertools.chain(itertools.product(SCHED_VARIANTS, ("ok", "unknown"), (True,)),
                                              itertools.product(("ok",), ("ok", "unknown"), (False,))):
                expected, expected_unknown = oracle(count_v, row_v, gv, r3)
                guard = (fresh(htr.INCIDENT_CLASSES) if gv == "ok"
                         else htr.unknown(htr.INCIDENT_CLASSES, "synthetic unclassified"))
                out = htr.compute_verdict(base + [sched_reading(sv), guard], NOW,
                                          policy={"confirmed_no_overrides_unknown": r3})
                n += 1
                case = (count_v, row_v, sv, gv, r3)
                assert out["verdict"] == expected, case
                assert {u["input"] for u in out["unknown_inputs"]} == expected_unknown, case
                if r3:
                    assert (out["verdict"] == htr.NO) == bool(out["blockers"]), case
                if out["verdict"] == htr.YES:   # 2172: YES only when every required input was evaluated
                    assert all(f["state"] in (htr.OK, htr.WARN) for f in out["inputs"].values()), case
                    assert all(out["inputs"][k]["state"] == htr.OK for k in rows), case
                assert [b["n"] for b in out["blockers"]] == list(range(1, len(out["blockers"]) + 1)), case
                for b in out["blockers"]:
                    for key in ("category", "cause", "source_id", "owner", "goto"):
                        assert b.get(key), (key, b, case)
                seen[out["verdict"]] += 1
    # LQ-2411: x (3 schedulers x 2 incident_classes under R3 true + 2 incident_classes under R3 false)
    assert n == 6 ** 3 * 6 ** 3 * (3 * 2 + 2) == 373_248
    assert all(seen.values()), seen


def test_every_input_carries_age_threshold_and_state():
    out = verdict(all_ok())
    assert set(out["inputs"]) == set(htr.REQUIRED_INPUTS)
    for name, f in out["inputs"].items():
        assert f["schema"] == "HomeField@v1"
        assert f["state"] == htr.OK
        assert f["age_s"] == 30.0 and f["threshold_s"] == 600 and f["as_of"]


# ── 2. the spec's named cases ───────────────────────────────────────────────────────────────────


def test_p0_gives_no():
    r = all_ok()
    r[htr.P0] = fresh(htr.P0, state=htr.WARN, items=[Item(id="i1", title="position_unprotected",
                                                          category="Unprotected Position", owner="risk")])
    out = verdict(r)
    assert out["verdict"] == htr.NO
    assert out["blockers"][0]["category"] == "Unprotected Position"
    assert out["blockers"][0]["kind"] == "p0" and out["blockers"][0]["goto"] == "#card-action"


def test_a_p0_item_blocks_even_without_the_blocks_trading_flag():
    r = all_ok()
    r[htr.P0] = fresh(htr.P0, items=[Item(id="i1", title="x", blocks_trading=False)])
    assert verdict(r)["verdict"] == htr.NO


def test_blocking_gate_gives_no_and_non_blocking_gate_gives_yes():
    r = all_ok()
    r[htr.GATES] = fresh(htr.GATES, state=htr.WARN, items=[blocking_item(htr.GATES)])
    out = verdict(r)
    assert out["verdict"] == htr.NO and out["blockers"][0]["category"] == "Open Validation Gate"
    assert out["blockers"][0]["goto"] == "#card-gates"
    r[htr.GATES] = fresh(htr.GATES, items=[non_blocking_item(htr.GATES)])
    out = verdict(r)
    assert out["verdict"] == htr.YES
    assert [g["input"] for g in out["non_blocking"]] == [htr.GATES]


def test_p1_gives_yes_unless_it_blocks_trading():
    r = all_ok()
    r[htr.P1_BLOCKING] = fresh(htr.P1_BLOCKING, items=[non_blocking_item(htr.P1_BLOCKING)])
    out = verdict(r)
    assert out["verdict"] == htr.YES and out["non_blocking"][0]["input"] == htr.P1_BLOCKING
    r[htr.P1_BLOCKING] = fresh(htr.P1_BLOCKING, state=htr.WARN, items=[blocking_item(htr.P1_BLOCKING)])
    out = verdict(r)
    assert out["verdict"] == htr.NO and out["blockers"][0]["kind"] == "p1"


def test_schedulers_warn_is_yes_with_a_non_blocking_row():
    r = all_ok()
    r[htr.SCHEDULERS] = fresh(htr.SCHEDULERS, state=htr.WARN, value=2)
    out = verdict(r)
    assert out["verdict"] == htr.YES
    assert out["non_blocking"] == [{"category": "Schedulers", "kind": "info", "input": "schedulers", "state": "WARN",
                                    "count": 2, "cause": "warn", "source_id": "src-schedulers", "owner": "ops",
                                    "goto": "#row-schedulers"}]
    assert out["rows"]["schedulers"]["state"] == htr.WARN


def test_orders_unreadable_gives_unknown():
    r = all_ok()
    r[htr.ORDERS] = htr.unknown(htr.ORDERS, "stop-coverage receipt missing")
    out = verdict(r)
    assert out["verdict"] == htr.UNKNOWN
    assert out["unknown_inputs"] == [{"input": "orders", "state": "UNKNOWN", "reason": "stop-coverage receipt missing"}]


def test_orders_unreadable_plus_p0_gives_no_with_unknown_listed():
    r = all_ok()
    r[htr.ORDERS] = htr.unknown(htr.ORDERS, "stop-coverage receipt missing")
    r[htr.P0] = fresh(htr.P0, state=htr.WARN, items=[blocking_item(htr.P0)])
    out = verdict(r)
    assert out["verdict"] == htr.NO
    assert [u["input"] for u in out["unknown_inputs"]] == ["orders"]


def test_all_ok_gives_yes_and_lists_every_input():
    out = verdict(all_ok())
    assert out["verdict"] == htr.YES
    assert out["blockers"] == [] and out["unknown_inputs"] == []
    assert list(out["inputs"]) == list(htr.REQUIRED_INPUTS)


@pytest.mark.parametrize("row", [htr.PORTFOLIO, htr.ORDERS, htr.DATA])
def test_a_row_not_ok_gives_no_and_links_its_row(row):
    r = all_ok()
    r[row] = stale(row)
    out = verdict(r)
    assert out["verdict"] == htr.NO
    assert out["blockers"][0]["goto"] == f"#row-{row}" and out["blockers"][0]["state"] == htr.STALE


# ── 3. unknown never reads as OK ────────────────────────────────────────────────────────────────


def test_a_missing_required_input_is_unknown_never_ok():
    r = all_ok()
    del r[htr.DATA]
    out = verdict(r)
    assert out["verdict"] == htr.UNKNOWN and out["unknown_inputs"][0]["input"] == htr.DATA


@pytest.mark.parametrize("mutate,why", [
    (lambda r: setattr(r, "as_of", None), "no as_of"),
    (lambda r: setattr(r, "as_of", "not a time"), "no as_of"),
    (lambda r: setattr(r, "as_of", "2026-11-11T10:00:00"), "no as_of"),  # naive: zone unknown
    (lambda r: setattr(r, "threshold_s", None), "no threshold"),
    (lambda r: setattr(r, "as_of", (NOW + timedelta(hours=1)).isoformat()), "future"),
    (lambda r: setattr(r, "state", "GREEN"), "unknown reading state"),
])
def test_an_unprovable_ok_is_unknown(mutate, why):
    r = all_ok()
    mutate(r[htr.PORTFOLIO])
    out = verdict(r)
    assert out["verdict"] == htr.UNKNOWN, why
    assert out["inputs"]["portfolio"]["state"] == htr.UNKNOWN
    assert why in out["inputs"]["portfolio"]["reason"]


def test_a_stale_empty_incident_list_cannot_prove_zero_p0():
    r = all_ok()
    r[htr.P0] = stale(htr.P0)
    assert verdict(r)["verdict"] == htr.UNKNOWN


def test_since_last_close_basis_is_not_re_aged():
    r = all_ok()
    r[htr.DATA] = Reading(name=htr.DATA, state=htr.OK, as_of=(NOW - timedelta(hours=40)).isoformat(),
                          threshold_s=900, threshold_basis="since_last_close", owner="data")
    assert verdict(r)["inputs"]["data"]["state"] == htr.OK


def test_a_non_ok_field_without_owner_is_visible_as_unregistered():
    r = all_ok()
    r[htr.ORDERS] = htr.unknown(htr.ORDERS, "x")
    assert verdict(r)["inputs"]["orders"]["owner"] == "UNREGISTERED"


def test_naive_now_is_refused():
    with pytest.raises(ValueError):
        htr.compute_verdict([], datetime(2026, 11, 11, 10, 30))


# ── 4. the served read: GET /api/v2/home/status ────────────────────────────────────────────────


def stored(now: datetime, *, verdict_word: str = htr.YES, age_s: float = 30.0) -> dict:
    readings = all_ok(now - timedelta(seconds=age_s))
    doc = htr.compute_verdict(list(readings.values()), now - timedelta(seconds=age_s), run_id="test:snap",
                              policy=POLICY)
    if verdict_word == htr.NO:
        readings[htr.P0] = fresh(htr.P0, state=htr.WARN, items=[blocking_item(htr.P0)], now=now - timedelta(seconds=age_s))
        doc = htr.compute_verdict(list(readings.values()), now - timedelta(seconds=age_s), run_id="test:snap",
                              policy=POLICY)
    assert doc["verdict"] == verdict_word
    return doc


def db_returning(doc):
    calls = []

    def q(sql, params=None):
        calls.append(sql)
        return [] if doc is None else [{"payload": json.dumps(doc), "computed_at": doc["computed_at"], "run_id": "r"}]
    q.calls = calls
    return q


def test_fresh_yes_is_served_with_every_input_and_recomputed_ages(tmp_path):
    q = db_returning(stored(NOW, age_s=60))
    out = htr.served_status(query=q, mirror=tmp_path / "m.json", now=NOW)
    assert out["verdict"] == htr.YES and out["state"] == htr.OK and out["read_from"] == "db"
    assert out["snapshot"]["age_s"] == 60.0 and out["snapshot"]["threshold_s"] == 300
    assert set(out["inputs"]) == set(htr.REQUIRED_INPUTS)
    assert out["inputs"]["p0"]["age_s"] == 90.0  # 30 s old when computed + 60 s since
    assert q.calls == [htr.SNAPSHOT_SQL]


def test_stale_yes_is_never_served_as_yes(tmp_path):
    out = htr.served_status(query=db_returning(stored(NOW, age_s=412)), mirror=tmp_path / "m.json", now=NOW)
    assert out["verdict"] == htr.UNKNOWN
    assert out["unknown_inputs"] == [{"input": "verdict_snapshot", "state": "STALE", "reason": "age 412.0 s > 300 s"}]
    assert out["last_known"]["verdict"] == htr.YES and out["last_known"]["age_s"] == 412.0
    assert out["blocker_count"] is None


def test_stale_no_keeps_its_blockers_under_last_known(tmp_path):
    out = htr.served_status(query=db_returning(stored(NOW, verdict_word=htr.NO, age_s=900)),
                            mirror=tmp_path / "m.json", now=NOW)
    assert out["verdict"] == htr.UNKNOWN and out["blockers"] == []
    assert out["last_known"]["blockers"][0]["kind"] == "p0"


def test_off_session_limit_is_900_s(tmp_path):
    doc = stored(SAT, age_s=600)
    assert htr.served_status(query=db_returning(doc), mirror=tmp_path / "m", now=SAT)["verdict"] == htr.YES
    doc = stored(SAT, age_s=901)
    assert htr.served_status(query=db_returning(doc), mirror=tmp_path / "m", now=SAT)["verdict"] == htr.UNKNOWN


def test_a_snapshot_written_off_session_is_held_to_the_session_limit_once_the_session_opens(tmp_path):
    doc = stored(NOW, age_s=600)
    doc["snapshot_max_age_s"] = 900  # written at 09:20 ET by the 5-minute off-session cadence
    assert htr.served_status(query=db_returning(doc), mirror=tmp_path / "m", now=NOW)["verdict"] == htr.UNKNOWN


def test_no_row_is_unknown(tmp_path):
    out = htr.served_status(query=db_returning(None), mirror=tmp_path / "m.json", now=NOW)
    assert out["verdict"] == htr.UNKNOWN and out["reason"] == "no snapshot written" and out["snapshot"] is None


def test_db_down_reads_the_mirror_and_says_so(tmp_path):
    mirror = tmp_path / "m.json"
    mirror.write_text(json.dumps(stored(NOW)), encoding="utf-8")
    out = htr.served_status(query=lambda sql, params=None: None, mirror=mirror, now=NOW)
    assert out["verdict"] == htr.YES and out["read_from"] == "mirror" and out["db_readable"] is False


def test_a_readable_db_with_no_row_does_not_fall_back_to_an_old_mirror(tmp_path):
    mirror = tmp_path / "m.json"
    mirror.write_text(json.dumps(stored(NOW)), encoding="utf-8")
    assert htr.served_status(query=db_returning(None), mirror=mirror, now=NOW)["verdict"] == htr.UNKNOWN


def test_db_down_and_no_mirror_is_unknown(tmp_path):
    out = htr.served_status(query=lambda sql, params=None: None, mirror=tmp_path / "none.json", now=NOW)
    assert out["verdict"] == htr.UNKNOWN and out["read_from"] is None


@pytest.mark.parametrize("field,value", [("schema", "Other@v1"), ("verdict", "MAYBE"), ("computed_at", None),
                                         ("rule_version", "home-v009")])
def test_an_invalid_snapshot_is_unknown(tmp_path, field, value):
    doc = stored(NOW)
    doc[field] = value
    out = htr.served_status(query=db_returning(doc), mirror=tmp_path / "m", now=NOW)
    assert out["verdict"] == htr.UNKNOWN and out["reason"].startswith("verdict_unreadable")


def test_a_future_snapshot_is_unknown(tmp_path):
    doc = stored(NOW + timedelta(hours=1), age_s=0)
    assert htr.served_status(query=db_returning(doc), mirror=tmp_path / "m", now=NOW)["verdict"] == htr.UNKNOWN


# ── 5. the lane's providers (stubbed DB) ────────────────────────────────────────────────────────

def _approved() -> dict:
    """The shipped registry (approved by the boolean, LQ-2264) plus three synthetic classes cloned from shipped ones
    of the same priority, so they pass the same validator the lane uses (LQ-2411: one approval reader)."""
    doc = json.loads((ROOT / "config" / "home_status_registry.json").read_text(encoding="utf-8"))
    c = doc["incident_classes"]
    c["zq_unprotected"] = {**c["position_unprotected"], "category": "Unprotected Position", "ttl_h": 1}
    c["zq_integrity"] = {**c["data_integrity"], "category": "Data Integrity"}
    c["zq_telemetry"] = dict(c["job_telemetry"])
    return doc


APPROVED = _approved()


def inc(alert_type, blocks=None, n=1):
    return {"incident_id": f"ZQ-{alert_type}-{n}", "alert_type": alert_type, "severity": "critical", "symbol": "ZQA",
            "first_seen_at": NOW - timedelta(hours=2), "last_seen_at": NOW - timedelta(minutes=5),
            "blocks_trading": blocks}


def by_name(readings):
    return {r.name: r for r in readings}


@pytest.mark.parametrize("registry,why", [
    (None, "not present"),
    ({"incident_classes": {}}, "empty"),
    ({**APPROVED, "incident_classes_approved": False}, "not operator-approved"),
    # READY-2397: the old dict shape alone (no boolean) is not an approval; the shared validator rejects it
    ({**{k: v for k, v in APPROVED.items() if k != "incident_classes_approved"},
      "incident_classes_approval": {"approved_by": "x", "approved_at": "2026-11-12T00:00:00Z"}}, "invalid"),
])
def test_d2_without_an_approved_class_map_p0_and_p1_are_unknown(registry, why):
    out = by_name(lane.incident_readings([], registry, NOW))
    for name in (htr.P0, htr.P1_BLOCKING, htr.ALERTS):
        assert out[name].state == htr.UNKNOWN and why in out[name].reason
    assert verdict({**all_ok(), **{k: v for k, v in out.items() if k != htr.ALERTS}})["verdict"] == htr.UNKNOWN


def test_the_lane_ships_no_default_class_map():
    assert lane.class_map_status(None)[0] is None
    src = (ROOT / SCRIPT).read_text(encoding="utf-8")
    assert '"P0"' in src and "position_unprotected" in src  # named only as the orders input and a priority word
    assert "incident_classes" not in json.dumps({k: v for k, v in vars(lane).items()
                                                 if isinstance(v, dict) and k.isupper()})


def test_an_unmapped_open_incident_is_unknown_on_its_own_input_and_keeps_classified_counts():
    """LQ-2411 / D2-b (supersedes 2144's "unmapped keeps p0 UNKNOWN", which hid a confirmed P0 behind UNKNOWN)."""
    out = by_name(lane.incident_readings([inc("zq_never_seen")], APPROVED, NOW))
    assert out[htr.INCIDENT_CLASSES].state == htr.UNKNOWN and "zq_never_seen=1" in out[htr.INCIDENT_CLASSES].reason
    assert out[htr.P0].state == htr.OK and out[htr.P1_BLOCKING].state == htr.OK
    assert out[htr.ALERTS].state == htr.WARN


def test_approved_map_classifies_p0_p1_and_info():
    rows = [inc("zq_unprotected"), inc("zq_integrity"), inc("zq_telemetry")]
    out = by_name(lane.incident_readings(rows, APPROVED, NOW))
    assert out[htr.P0].state == htr.WARN and out[htr.P0].items[0].category == "Unprotected Position"
    assert out[htr.P1_BLOCKING].state == htr.OK and out[htr.P1_BLOCKING].value == 0
    assert out[htr.ALERTS].state == htr.WARN and out[htr.ALERTS].value == 1


def test_the_incident_blocks_trading_column_overrides_the_class_default():
    out = by_name(lane.incident_readings([inc("zq_integrity", blocks="true")], APPROVED, NOW))
    assert out[htr.P1_BLOCKING].state == htr.WARN and out[htr.P1_BLOCKING].value == 1
    r = {**all_ok(), htr.P1_BLOCKING: out[htr.P1_BLOCKING]}
    r[htr.P1_BLOCKING].as_of = NOW.isoformat()
    assert verdict(r)["verdict"] == htr.NO
    out = by_name(lane.incident_readings([inc("zq_unprotected", blocks="false")], APPROVED, NOW))
    assert out[htr.P0].state == htr.WARN  # a P0 blocks regardless


class FakeDB:
    """Answers the lane's SQL by substring. A value that is an Exception is raised."""

    def __init__(self, answers):
        self.answers = answers
        self.seen = []

    def __call__(self, sql, params=None):
        self.seen.append(sql)
        for key, value in self.answers.items():
            if key in sql:
                if isinstance(value, Exception):
                    raise value
                return value
        raise AssertionError(f"unexpected SQL: {sql[:80]}")


def test_schedulers_without_an_aggregate_row_is_unknown_not_zero_late():
    """tq missing-as-zero: an empty answer must not read as "0 lanes late" (OK)."""
    db = FakeDB({"to_regclass": [{"present": True}], "FROM lane_health_current": []})
    assert lane.read_schedulers(db, NOW).state == htr.UNKNOWN
    db = FakeDB({"to_regclass": [{"present": True}], "FROM lane_health_current": [{"as_of": None, "bad": None}]})
    assert lane.read_schedulers(db, NOW).state == htr.UNKNOWN



def receipt(state_root: Path, lane_id: str, ok_at: datetime) -> None:
    p = state_root / "data" / "runtime" / f"{lane_id}_last.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"ok_at": ok_at.isoformat()}), encoding="utf-8")


def test_gates_missing_table_or_receipt_is_unknown(tmp_path):
    q = FakeDB({"to_regclass('public.validation_gates')": [{"present": False}]})
    assert lane.read_gates(q, NOW, tmp_path).state == htr.UNKNOWN
    q = FakeDB({"to_regclass('public.validation_gates')": [{"present": True}]})
    r = lane.read_gates(q, NOW, tmp_path)
    assert r.state == htr.UNKNOWN and "not evidence" in r.reason


def test_gates_open_blocking_gate_is_warn_and_closed_gates_are_ignored(tmp_path):
    receipt(tmp_path, "validation-gates-sync", NOW - timedelta(minutes=3))
    gates = [{"g": {"gate_id": "VG-ZQ-1", "title": "synthetic", "status": "OPEN", "blocks_trading": True}},
             {"g": {"gate_id": "VG-ZQ-2", "title": "synthetic", "status": "OPEN", "blocks_trading": False}},
             {"g": {"gate_id": "VG-ZQ-3", "title": "synthetic", "status": "PASSED", "blocks_trading": True}},
             {"g": {"gate_id": "VG-ZQ-4", "title": "synthetic", "closed_at": "2026-11-10", "blocks_trading": True}}]
    q = FakeDB({"to_regclass('public.validation_gates')": [{"present": True}], "FROM validation_gates g": gates})
    r = lane.read_gates(q, NOW, tmp_path)
    assert r.state == htr.WARN and r.value == 1 and [i.id for i in r.items] == ["VG-ZQ-1", "VG-ZQ-2"]


def test_gates_failing_with_undeclared_blocks_trading_are_unknown_never_a_pass(tmp_path):
    """LQ-2141: blocks_trading NULL is 'not declared' = unknown. A FAIL/ERROR/unevaluated open gate with no declared
    classification must not render as 'OK, 0 blocking' (operator correction 2026-11-13)."""
    receipt(tmp_path, "validation-gates-sync", NOW - timedelta(minutes=3))
    gates = [{"g": {"gate_id": "VG-ZQ-F", "title": "synthetic fail", "status": "OPEN", "last_eval_result": "FAIL"}},
             {"g": {"gate_id": "VG-ZQ-E", "title": "synthetic error", "status": "OPEN", "blocks_trading": None,
                    "last_eval_result": "ERROR"}},
             {"g": {"gate_id": "VG-ZQ-A", "title": "synthetic advisory", "status": "OPEN", "blocks_trading": False,
                    "last_eval_result": "FAIL"}}]
    q = FakeDB({"to_regclass('public.validation_gates')": [{"present": True}], "FROM validation_gates g": gates})
    r = lane.read_gates(q, NOW, tmp_path)
    assert r.state == htr.UNKNOWN and r.value is None
    assert "VG-ZQ-F" in r.reason and "VG-ZQ-E" in r.reason and "VG-ZQ-A" not in r.reason
    out = verdict({**all_ok(), htr.GATES: r})
    assert out["verdict"] == htr.UNKNOWN
    assert any(u.get("input") == htr.GATES or u.get("name") == htr.GATES for u in out["unknown_inputs"])


def test_gates_declared_advisory_failure_stays_non_blocking_and_undeclared_pass_is_ok(tmp_path):
    receipt(tmp_path, "validation-gates-sync", NOW - timedelta(minutes=3))
    gates = [{"g": {"gate_id": "VG-ZQ-A", "title": "advisory", "status": "OPEN", "blocks_trading": False,
                    "last_eval_result": "FAIL"}},
             {"g": {"gate_id": "VG-ZQ-P", "title": "in proof window", "status": "OPEN", "last_eval_result": "PASS"}}]
    q = FakeDB({"to_regclass('public.validation_gates')": [{"present": True}], "FROM validation_gates g": gates})
    r = lane.read_gates(q, NOW, tmp_path)
    assert r.state == htr.OK and r.value == 0


def test_a_declared_blocking_gate_still_wins_over_undeclared_ones(tmp_path):
    receipt(tmp_path, "validation-gates-sync", NOW - timedelta(minutes=3))
    gates = [{"g": {"gate_id": "VG-ZQ-B", "title": "blocks", "status": "OPEN", "blocks_trading": True,
                    "last_eval_result": "FAIL"}},
             {"g": {"gate_id": "VG-ZQ-F", "title": "undeclared", "status": "OPEN", "last_eval_result": "ERROR"}}]
    q = FakeDB({"to_regclass('public.validation_gates')": [{"present": True}], "FROM validation_gates g": gates})
    r = lane.read_gates(q, NOW, tmp_path)
    assert r.state == htr.WARN and r.value == 1


def test_gates_with_a_stale_writer_are_unknown_through_the_rule(tmp_path):
    receipt(tmp_path, "validation-gates-sync", NOW - timedelta(hours=2))
    q = FakeDB({"to_regclass('public.validation_gates')": [{"present": True}], "FROM validation_gates g": []})
    r = lane.read_gates(q, NOW, tmp_path)
    assert verdict({**all_ok(), htr.GATES: r})["verdict"] == htr.UNKNOWN


def coverage(state_root: Path, ok_at, **counts) -> None:
    """A synthetic StopCoverageIncidentsRun@v1 heartbeat as the LQ-2145 lane writes it (counts are list lengths)."""
    doc = {"schema": "StopCoverageIncidentsRun@v1", "status": "ok", "ok_at": ok_at.isoformat() if ok_at else None,
           "gaps": 0, "day_stop_expired": 0, "unresolved_unknown": 0, **counts}
    p = state_root / "data" / "runtime" / "stop_coverage_incidents_last.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding="utf-8")


def test_orders_reads_the_2145_heartbeat_and_is_ok_only_when_protection_is_active(tmp_path):
    r = lane.read_orders(None, NOW, tmp_path, [])
    assert r.state == htr.UNKNOWN and r.needs_backend      # no source -> UNKNOWN + NEEDS BACKEND
    coverage(tmp_path, NOW - timedelta(minutes=4))
    assert lane.read_orders(None, NOW, tmp_path, []).state == htr.OK
    assert lane.read_orders(None, NOW, tmp_path, None).state == htr.UNKNOWN
    coverage(tmp_path, NOW - timedelta(minutes=20))
    r = lane.read_orders(None, NOW, tmp_path, [])
    assert verdict({**all_ok(), htr.ORDERS: r})["inputs"]["orders"]["state"] == htr.STALE


def test_d1_an_expired_day_stop_as_only_protection_is_orders_warn_never_ok(tmp_path):
    coverage(tmp_path, NOW - timedelta(minutes=4), day_stop_expired=2)
    r = lane.read_orders(None, NOW, tmp_path, [])
    assert r.state == htr.WARN and "DAY stop" in r.cause
    out = verdict({**all_ok(), htr.ORDERS: r})
    assert out["verdict"] == htr.NO and out["blockers"][0]["state"] == htr.WARN


def test_d1_a_confirmed_gap_is_orders_gap_and_trade_ready_no(tmp_path):
    coverage(tmp_path, NOW - timedelta(minutes=4), gaps=1, day_stop_expired=1)
    r = lane.read_orders(None, NOW, tmp_path, [])
    assert r.state == htr.GAP and r.value == {"gaps": 1, "day_stop_expired": 1, "unresolved_unknown": 0}
    out = verdict({**all_ok(), htr.ORDERS: r})
    assert out["inputs"]["orders"]["state"] == htr.GAP          # a known state word, not demoted to UNKNOWN
    assert out["verdict"] == htr.NO and out["blockers"][0]["state"] == htr.GAP
    coverage(tmp_path, NOW - timedelta(minutes=4))              # a structured-producer incident is also a gap
    open_row = {**inc("position_unprotected"), "source_producer": "stop_coverage_incidents"}
    assert lane.read_orders(None, NOW, tmp_path, [open_row]).state == htr.GAP


@pytest.mark.parametrize("doc", [
    {"status": "error"},                  # failed read -> UNKNOWN
    {"unresolved_unknown": 1},            # cannot be determined -> UNKNOWN
    {"gaps": None},                       # missing data -> UNKNOWN
    {"day_stop_expired": "x"},            # unreadable count -> UNKNOWN
])
def test_d1_orders_that_cannot_be_determined_are_unknown(tmp_path, doc):
    coverage(tmp_path, NOW - timedelta(minutes=4), **doc)
    r = lane.read_orders(None, NOW, tmp_path, [])
    assert r.state == htr.UNKNOWN and not r.needs_backend


def test_i2_no_source_is_unknown_plus_needs_backend_in_the_verdict(tmp_path):
    q = FakeDB({"to_regclass('public.validation_gates')": [{"present": False}],
                "to_regclass('public.lane_health_current')": [{"present": False}]})
    gates, sched = lane.read_gates(q, NOW, tmp_path), lane.read_schedulers(q, NOW)
    assert gates.needs_backend and sched.needs_backend and gates.state == sched.state == htr.UNKNOWN
    p = by_name(lane.incident_readings([], None, NOW, None))
    assert p[htr.P0].needs_backend and p[htr.P0].state == htr.UNKNOWN
    out = verdict({**all_ok(), htr.GATES: gates, htr.SCHEDULERS: sched})
    assert out["verdict"] == htr.UNKNOWN
    assert out["needs_backend"] == ["gates", "schedulers"]
    assert out["unknown_inputs"] == [{"input": "gates", "state": "UNKNOWN", "reason": gates.reason,
                                      "needs_backend": True}]
    assert out["inputs"]["gates"]["needs_backend"] is True and gates.reason.startswith("NEEDS BACKEND")
    # an unapproved class map is an operator decision, not a missing backend
    p = by_name(lane.incident_readings([], {"incident_classes": {"x": {"priority": "P0"}}}, NOW, None))
    assert p[htr.P0].state == htr.UNKNOWN and not p[htr.P0].needs_backend


def held(symbol, asset_type, as_of, mv=1000.0):
    return {"symbol": symbol, "asset_type": asset_type, "as_of": as_of, "market_value": mv}


def nav_held(symbol, asset_type, quote_as_of, broker_as_of, broker_source="schwab_api", mv=5000.0):
    """A held row as DATA_SQL returns it after LQ-2643: the intraday quote AND the broker NAV read."""
    return {**held(symbol, asset_type, quote_as_of, mv), "broker_as_of": broker_as_of,
            "broker_source": broker_source if broker_as_of is not None else None}


def test_i2_data_missing_quotes_are_never_healthy_mutual_funds_are_not_exempt():
    """LQ-2643: a fund's missing NAV is a per-symbol UNKNOWN, not a gate-wide NEEDS BACKEND."""
    t = NOW - timedelta(minutes=2)
    rows = [held("$VIX", "INDEX", t, None), held("ZQA", "EQUITY", t), nav_held("ZQFNDX", "MUTUAL_FUND", None, None)]
    r = lane.read_data(FakeDB({"WITH held": rows}), NOW)
    assert r.state == htr.UNKNOWN and r.value["missing"] == ["ZQFNDX"] and not r.needs_backend
    assert r.value["missing_nav"] == ["ZQFNDX"] and r.value["missing_quotes"] == []
    assert r.value["symbols"] == 3 and "no daily NAV for 1 counted mutual fund(s): ZQFNDX" in r.reason
    # The rest of the gate is still computed: the priced symbols' oldest read is carried with the unknown.
    assert r.value["oldest_symbol"] in ("$VIX", "ZQA") and r.as_of is not None


def test_a_mutual_fund_is_graded_on_its_daily_broker_nav_source_named():
    """LQ-2643 (operator P0): a fund has one NAV a day; the broker row that carries it is the named source."""
    t = NOW - timedelta(minutes=2)
    broker = NOW - timedelta(minutes=5)
    rows = [held("$VIX", "INDEX", t, None), held("ZQA", "EQUITY", t),
            nav_held("ZQFNDX", "MUTUAL_FUND", None, broker)]
    r = lane.read_data(FakeDB({"WITH held": rows}), NOW)
    assert r.state == htr.OK and not r.needs_backend
    assert r.value["fund_nav"] == {"ZQFNDX": "positions_current:schwab_api"}
    assert r.value["oldest_symbol"] == "ZQFNDX"            # the NAV read is graded, not ignored
    assert r.source_id == "market_quotes+positions_current:schwab_api" and r.as_of is not None


def test_a_fund_nav_from_the_last_close_is_fresh_while_the_market_is_open():
    """LQ-2643: fresh = the last trading day's NAV. At 10:30 ET a 19:00 ET NAV read must not be STALE."""
    t = NOW - timedelta(minutes=2)
    rows = [held("$VIX", "INDEX", t, None), held("ZQA", "EQUITY", t),
            nav_held("ZQFNDX", "MUTUAL_FUND", None, NOW - timedelta(hours=16))]
    r = lane.read_data(FakeDB({"WITH held": rows}), NOW)
    assert r.state == htr.OK and r.value["oldest_symbol"] == "ZQFNDX"
    assert r.threshold_s == 72 * 3600                       # graded against the closed (daily NAV) threshold


def test_a_stale_fund_nav_ages_the_gate_and_names_the_fund():
    t = NOW - timedelta(minutes=2)
    rows = [held("$VIX", "INDEX", t, None), held("ZQA", "EQUITY", t),
            nav_held("ZQFNDX", "MUTUAL_FUND", None, NOW - timedelta(hours=80))]
    r = lane.read_data(FakeDB({"WITH held": rows}), NOW)
    assert r.state == htr.STALE and r.value["oldest_symbol"] == "ZQFNDX"
    assert "mutual fund NAV" in (r.cause or "")


def test_a_stale_quote_is_not_masked_by_an_older_but_fresh_fund_nav():
    """Each counted symbol is graded on its own rule; the gate's state is the worst, not the oldest."""
    rows = [held("$VIX", "INDEX", NOW - timedelta(minutes=2), None), held("ZQA", "EQUITY", NOW - timedelta(hours=1)),
            nav_held("ZQFNDX", "MUTUAL_FUND", None, NOW - timedelta(hours=16))]
    r = lane.read_data(FakeDB({"WITH held": rows}), NOW)
    assert r.state == htr.STALE and r.value["oldest_symbol"] == "ZQA" and r.cause == "quotes behind"


def test_a_fund_with_only_a_non_yfinance_quote_still_grades_on_it():
    t = NOW - timedelta(minutes=2)
    rows = [held("$VIX", "INDEX", t, None), nav_held("ZQFNDX", "MUTUAL_FUND", t, None)]
    r = lane.read_data(FakeDB({"WITH held": rows}), NOW)
    assert r.state == htr.OK and "fund_nav" not in r.value and r.source_id == "market_quotes"


def test_an_equity_with_a_stale_quote_stays_stale_even_with_a_fresh_broker_row():
    """LQ-2684 (REVIEW-2671 survivor 1): the NAV rule is a FUND rule. A broker positions read must never grade
    an equity, or a fresh positions read would hide a stale quote for every held equity."""
    t = NOW - timedelta(minutes=2)
    rows = [held("$VIX", "INDEX", t, None),
            nav_held("ZQETA", "EQUITY", NOW - timedelta(hours=1), NOW - timedelta(minutes=1))]
    r = lane.read_data(FakeDB({"WITH held": rows}), NOW)
    assert r.state == htr.STALE and r.value["oldest_symbol"] == "ZQETA"
    assert r.cause == "quotes behind"                    # not "mutual fund NAV behind"
    assert "fund_nav" not in r.value and r.source_id == "market_quotes"


def test_a_fund_with_both_a_quote_and_a_nav_is_graded_on_the_nav():
    """LQ-2684 (REVIEW-2671 survivor 2): the documented order is NAV first. When a fund also carries a quote,
    the NAV is still the price that grades it and the one the gate names."""
    t = NOW - timedelta(minutes=2)
    rows = [held("$VIX", "INDEX", t, None),
            nav_held("ZQFNDX", "MUTUAL_FUND", t, NOW - timedelta(hours=1))]   # quote 2 min, NAV 1 h
    r = lane.read_data(FakeDB({"WITH held": rows}), NOW)
    assert r.state == htr.OK
    assert r.value["fund_nav"] == {"ZQFNDX": "positions_current:schwab_api"}
    assert r.value["oldest_symbol"] == "ZQFNDX"          # the NAV read, not the fresher quote
    assert r.source_id == "market_quotes+positions_current:schwab_api"


def test_a_missing_equity_quote_is_still_a_missing_source_needing_backend():
    """Unchanged rail: no quote and no broker NAV for a non-fund is a source gap (NEEDS BACKEND)."""
    t = NOW - timedelta(minutes=2)
    rows = [held("$VIX", "INDEX", t, None), nav_held("ZQA", "EQUITY", None, None)]
    r = lane.read_data(FakeDB({"WITH held": rows}), NOW)
    assert r.state == htr.UNKNOWN and r.needs_backend and r.value["missing"] == ["ZQA"]


def test_data_lines_under_100_dollars_are_listed_not_counted_and_unknown_value_is_counted():
    t = NOW - timedelta(minutes=2)
    rows = [held("$VIX", "INDEX", t, None), held("ZQA", "EQUITY", t), held("ZQS", "EQUITY", None, 40.0),
            held("ZQMM", "MONEY_MARKET", None)]
    r = lane.read_data(FakeDB({"WITH held": rows}), NOW)
    assert r.state == htr.OK
    assert r.value == {"symbols": 2, "listed_not_counted": ["ZQS"], "unvalued": [], "exempt": ["ZQMM"],
                       "oldest_symbol": "$VIX"}
    # LQ-20261113-3068 C1: a $0 value on a held quantity does not prove the row is small. It is never "under $100":
    # it is listed UNVALUED (UNKNOWN, with why) and stays counted, so a $0 row with no quote is a missing quote.
    zero = rows + [held("999999ZZ9", "EQUITY", None, 0.0)]
    r = lane.read_data(FakeDB({"WITH held": zero}), NOW)
    assert r.state != htr.OK and r.value["missing"] == ["999999ZZ9"]
    assert r.value["listed_not_counted"] == ["ZQS"]
    assert r.value["unvalued"] == [{"symbol": "999999ZZ9", "state": htr.UNKNOWN,
                                    "why": "market value <= 0 on a held quantity"}]
    rows.append(held("ZQB", "EQUITY", None, None))      # value unknown: cannot prove it is under $100
    assert lane.read_data(FakeDB({"WITH held": rows}), NOW).state == htr.UNKNOWN
    assert lane.read_data(FakeDB({"WITH held": rows[1:2]}), NOW).state == htr.UNKNOWN  # no VIX row


def test_data_sql_never_reads_yfinance():
    assert "m.source <> 'yfinance'" in lane.DATA_SQL


def test_data_sql_reads_the_broker_nav_of_a_held_mutual_fund():
    """LQ-2643: the fund's NAV and its source must come from the broker row itself, not be fabricated in Python."""
    assert "FROM positions_current" in lane.DATA_SQL
    assert "THEN as_of END) AS broker_as_of" in lane.DATA_SQL
    assert "THEN source END) AS broker_source" in lane.DATA_SQL


def test_portfolio_fresh_but_last_sync_partial_is_warn():
    q = FakeDB({"FROM positions_current": [{"as_of": NOW - timedelta(minutes=5), "n": 3}],
                "FROM positions_sync_runs": [{"status": "partial"}]})
    assert lane.read_portfolio(q, NOW).state == htr.WARN
    q.answers["FROM positions_sync_runs"] = [{"status": "complete"}]
    assert lane.read_portfolio(q, NOW).state == htr.OK
    q.answers["FROM positions_sync_runs"] = []
    assert lane.read_portfolio(q, NOW).state == htr.UNKNOWN


def test_a_query_timeout_is_timed_out_and_never_ok(tmp_path):
    q = FakeDB({"WITH held": RuntimeError("boom"), "FROM alert_incidents": lane.Timeout(),
                "to_regclass": lane.Timeout(), "FROM positions_current": lane.Timeout()})
    out = by_name(lane.gather(q, NOW, state_root=tmp_path, registry=APPROVED))
    assert out[htr.P0].state == htr.TIMED_OUT and out[htr.P1_BLOCKING].state == htr.TIMED_OUT
    assert out[htr.GATES].state == htr.TIMED_OUT and out[htr.PORTFOLIO].state == htr.TIMED_OUT
    assert out[htr.DATA].state == htr.UNKNOWN and out[htr.DATA].reason == "read failed: RuntimeError"
    assert out[htr.ORDERS].state == htr.UNKNOWN
    assert htr.compute_verdict(list(out.values()), NOW, policy=POLICY)["verdict"] == htr.UNKNOWN


# ── 6. the scheduled argv: dry run writes nothing; apply writes row + mirror + receipt ─────────


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))
        if self.conn.fail_write and "INSERT INTO home_snapshots" in sql:
            raise RuntimeError("relation home_snapshots does not exist")
        self.rowcount = 2 if sql.startswith("DELETE") else 1


class FakeConn:
    def __init__(self, fail_write=False):
        self.executed, self.commits, self.rollbacks, self.closed = [], 0, 0, False
        self.autocommit = True
        self.fail_write = fail_write

    def cursor(self, *a, **k):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


@pytest.fixture
def emulated(monkeypatch, tmp_path):
    import scripts.lib.lane_last_receipt as llr
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("TRADEAI_RUN_ID", "run:zq-1")
    readonly = []
    monkeypatch.setattr(llr, "enforce_readonly", lambda conn: readonly.append(conn) or conn)
    monkeypatch.setattr(lane, "make_query", lambda conn: FakeDB({}))
    monkeypatch.setattr(lane, "gather", lambda q, now, **k: list(all_ok(now).values()))
    monkeypatch.setattr(lane, "load_registry", lambda: {"protection_verdict": POLICY})
    return tmp_path, readonly


def files_under(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def test_dry_run_is_read_only_and_writes_nothing(emulated, monkeypatch, capsys):
    root, readonly = emulated
    conns = []
    monkeypatch.setattr(lane, "pg_connect", lambda readonly: conns.append((readonly, FakeConn())) or conns[-1][1])
    assert lane.main(["--dry-run"]) == 0
    assert conns[0][0] is True and readonly == [conns[0][1]]
    assert conns[0][1].executed == [] and files_under(root) == []
    assert "DRY-RUN" in capsys.readouterr().out
    assert lane.main([]) == 0 and files_under(root) == []  # the default is a dry run


def test_apply_writes_row_retention_mirror_and_receipt_in_one_transaction(emulated, monkeypatch):
    root, readonly = emulated
    conn = FakeConn()
    monkeypatch.setattr(lane, "pg_connect", lambda readonly: conn)
    assert lane.main(["--apply"]) == 0
    sqls = [s for s, _ in conn.executed]
    assert sqls == [lane.UPSERT_SQL, lane.RETENTION_SQL] and conn.commits == 1 and readonly == []
    params = conn.executed[0][1]
    assert params[0] == "status" and params[1] == "HomeStatus@v1" and params[2] == htr.RULE_VERSION
    assert params[4] == "run:zq-1"
    assert conn.executed[1][1] == ("status", "7 days")
    files = files_under(root)
    assert files[:2] == ["data/runtime/home-status-verdict_last.json", "data/runtime/home_status_latest.json"]
    assert len(files) == 3 and files[2].startswith("data/runtime/lane_attempts/home-status-verdict/run")
    rec = json.loads((root / SIGNAL).read_text())
    assert rec["status"] == "ok" and rec["ok_at"] and rec["produced_count"] == 1 and rec["summary"]["subject_status"] == htr.YES
    assert "verdict" not in rec["summary"] and "status" not in rec["summary"]
    mirror = json.loads((root / htr.MIRROR_REL).read_text())
    assert mirror["schema"] == "HomeStatus@v1" and mirror["run_id"] == "run:zq-1"
    served = htr.served_status(query=lambda sql, params=None: None, mirror=root / htr.MIRROR_REL)
    assert served["read_from"] == "mirror" and served["verdict"] == htr.YES


def test_apply_with_the_table_missing_writes_an_honest_failed_receipt(emulated, monkeypatch):
    root, _ = emulated
    conn = FakeConn(fail_write=True)
    monkeypatch.setattr(lane, "pg_connect", lambda readonly: conn)
    assert lane.main(["--apply"]) == 1
    assert conn.rollbacks == 1 and conn.commits == 0
    rec = json.loads((root / SIGNAL).read_text())
    assert rec["status"] == "failed" and rec["produced_count"] == 0 and rec.get("ok_at") is None
    assert not (root / htr.MIRROR_REL).exists()


# ── 7. the registration: row, dispatch, allowlist, contract, ci gate ───────────────────────────


def cfg(name):
    return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))


def row():
    return next(r for r in cfg("lane_registry.json")["lanes"] if r["lane_id"] == LID)


def entry():
    return next(e for e in cfg("n8n_run_allowlist.json")["lanes"] if e["lane_id"] == LID)


def contract():
    return next(c for c in cfg("n8n_health_contracts.json")["contracts"] if c.get("id") == LID)


def test_registry_row_is_a_valid_shadow_dispatcher_row():
    from scripts.lib.lane_dispatch import dispatch_eligible, parse_dispatch_block, validate_dispatch_block
    from scripts.lib.lane_registry import validate_row
    r = row()
    assert validate_row(r) == []
    s, d = r["scheduler"], r["dispatch"]
    assert (s["kind"], s["expression"], s["match"], s["stage"]) == ("n8n", "dispatcher", SCRIPT, "shadow")
    assert s["cadence"] == d["cron"][0] and d["mode"] == "dry_run" and d["tz"] == "America/New_York"
    assert r["output_signal"]["path"] == SIGNAL and r["output_signal"]["key"] == "ok_at"
    assert parse_dispatch_block(r) is not None
    known = {x["lane_id"] for x in cfg("lane_registry.json")["lanes"]}
    policies = set(cfg("n8n_retry_policies.json").get("policies", {}))
    assert validate_dispatch_block(r, known_lane_ids=known, retry_policy_names=policies or None) == []
    ok, why = dispatch_eligible(r)
    assert ok, why


def test_the_cron_lines_fire_exactly_at_the_lanes_own_cadence():
    """Every gap between consecutive fires over a week (DST-safe) equals cadence_s at the earlier fire."""
    from scripts.lib.cron_schedule import fires_between
    start = datetime(2026, 11, 9, 0, 0, tzinfo=ET)  # Monday
    end = start + timedelta(days=7)
    fires = sorted({f.at for expr in row()["dispatch"]["cron"] for f in fires_between(expr, start, end,
                                                                                    tz="America/New_York")})
    assert len(fires) == 5 * 420 + (5 * 17 * 12) + (2 * 288)
    for a, b in zip(fires, fires[1:]):
        assert (b - a).total_seconds() == htr.cadence_s(a), a
    # the served staleness bound is at least three cadences everywhere
    assert htr.SESSION_SNAPSHOT_MAX_AGE_S >= 3 * htr.SESSION_CADENCE_S
    assert htr.OFF_SESSION_SNAPSHOT_MAX_AGE_S >= 3 * htr.OFF_SESSION_CADENCE_S


def test_allowlist_entry_is_the_shadow_argv_and_its_signal_is_the_receipt_path(tmp_path):
    from scripts.lib.lane_last_receipt import receipt_path
    from scripts.n8n_run_executor import validate_entry
    e = entry()
    assert validate_entry(e) is None
    assert e["command"] == ["$PY", SCRIPT] and e["dry_run_arg"] == ["--dry-run"] and e["live_arg"] is None
    assert e["output_signal"] == SIGNAL == row()["output_signal"]["path"]
    assert Path(receipt_path(LID, tmp_path)) == tmp_path / SIGNAL
    assert not set(e["env_names"]) & {n for n in e["env_names"] if "SCHWAB" in n or "BROKER" in n or "TOKEN" in n}


def test_health_contract_is_reviewed_and_matches_the_row():
    from scripts.lib.n8n_health_contracts import validate_contract
    from scripts.lib.n8n_output_verdict import validate_expected_output
    c = contract()
    assert validate_contract(c) == [] and c["status"] == "REVIEWED"
    assert c["stage"] == row()["scheduler"]["stage"]
    assert validate_expected_output(c["expected_output"]) == []
    assert c["expected_output"]["produced_field"] == "produced_count"
    assert c["baseline"]["timeout_s"] == entry()["timeout_s"]


def test_ci_gate_names_this_file():
    g = cfg("ci_gates/home_trade_ready_20261112.json")
    assert g["schema"] == "CiGate@v1" and g["files"] == ["tests/test_home_trade_ready_20261112.py"]
    assert g["anchor"] in Path(__file__).read_text(encoding="utf-8")


def test_api_handler_reads_what_the_lane_wrote(emulated, monkeypatch):
    root, _ = emulated
    monkeypatch.setattr(lane, "pg_connect", lambda readonly: FakeConn())
    assert lane.main(["--apply"]) == 0
    out = htr.api_handler(lambda sql, params=None: None, state_root=root)
    assert out["verdict"] == htr.YES and out["read_from"] == "mirror"
    assert out["writer"]["last_ok_at"] == json.loads((root / SIGNAL).read_text())["ok_at"]
    assert out["writer"]["receipt"] == SIGNAL


def test_api_handler_with_nothing_written_is_unknown(tmp_path):
    out = htr.api_handler(lambda sql, params=None: [], state_root=tmp_path)
    assert out["verdict"] == htr.UNKNOWN and out["writer"]["last_ok_at"] is None


# ── 8. LQ-2411: D2-a..d wired into the verdict, R3 read from config ─────────────────────────────
#
# Operator decisions of 2026-11-12 10:12 ET: D2-a P0 -> CRITICAL / Trade Ready NO; D2-b an unclassified incident ->
# UNKNOWN (never ignored, never OK); D2-c the per-incident blocks_trading column may raise a class to blocking and
# never lower a P0; D2-d orphaned_stop is P1 non-blocking. R3 (11-12 08:40 ET): a NO from a good read overrides
# UNKNOWN. The class map is the shipped config/home_status_registry.json (approved by LQ-2264); fixtures synthetic.

SHIPPED = json.loads((ROOT / "config" / "home_status_registry.json").read_text(encoding="utf-8"))
R3_ON = {"confirmed_no_overrides_unknown": True}
R3_OFF = {"confirmed_no_overrides_unknown": False}


def d2(rows, registry=SHIPPED):
    return by_name(lane.incident_readings(rows, registry, NOW, None))


def d2_verdict(rows, registry=SHIPPED, policy=R3_ON, **over):
    r = {**all_ok(), **d2(rows, registry), **over}
    return htr.compute_verdict(list(r.values()), NOW, run_id="test:2411", policy=policy)


def test_2411_shipped_registry_is_approved_by_the_boolean_and_carries_r3_true():
    assert SHIPPED["incident_classes_approved"] is True and "incident_classes_approval" not in SHIPPED
    assert SHIPPED["protection_verdict"]["confirmed_no_overrides_unknown"] is True
    classes, why = lane.class_map_status(SHIPPED)
    assert why is None and classes is not None


def test_2411_clean_shipped_map_with_nothing_open_is_yes():
    out = d2_verdict([])
    assert out["verdict"] == htr.YES and out["unknown_inputs"] == [] and out["data_quality"] == []


@pytest.mark.parametrize("atype", ["position_unprotected", "trading_impact_outage", "emergency_kill_or_revoke"])
def test_2411_d2a_an_open_p0_is_no(atype):
    out = d2_verdict([inc(atype)])
    assert out["verdict"] == htr.NO
    assert [b["kind"] for b in out["blockers"]] == ["p0"] and out["blockers"][0]["items"][0]["title"] == atype


@pytest.mark.parametrize("atype", ["stop_warning", "data_integrity", "platform_availability", "orphaned_stop"])
def test_2411_d2a_a_p1_alone_leaves_the_verdict_unchanged(atype):
    out = d2_verdict([inc(atype)])
    assert out["verdict"] == htr.YES and out["blockers"] == []
    assert out["inputs"]["p1_blocking"]["value"] == 0
    assert any(g["kind"] == "p1" for g in out["non_blocking"])


def test_2411_d2a_info_never_changes_the_verdict():
    out = d2_verdict([inc("job_telemetry", n=i) for i in range(23)])
    assert out["verdict"] == htr.YES and out["blockers"] == []


def test_2411_d2b_an_unclassified_incident_alone_is_unknown_named():
    out = d2_verdict([inc("zq_never_seen"), inc("zq_never_seen", n=2)])
    assert out["verdict"] == htr.UNKNOWN
    entry = [u for u in out["unknown_inputs"] if u["input"] == htr.INCIDENT_CLASSES]
    assert len(entry) == 1 and "zq_never_seen=2" in entry[0]["reason"]
    assert out["inputs"][htr.P0]["state"] == htr.OK   # a classified read of P0 is still a good read


def test_2411_d2b_r3_an_open_p0_plus_an_unclassified_incident_is_no_with_the_unknown_listed():
    out = d2_verdict([inc("emergency_kill_or_revoke"), inc("zq_never_seen")])
    assert out["verdict"] == htr.NO
    assert [u["input"] for u in out["unknown_inputs"]] == [htr.INCIDENT_CLASSES]


def test_2411_d2c_an_override_never_lowers_a_p0_and_is_reported():
    lane_p0 = d2([inc("position_unprotected", blocks="false")])[htr.P0]
    assert lane_p0.state == htr.WARN and [i.blocks_trading for i in lane_p0.items] == [True]
    out = d2_verdict([inc("position_unprotected", blocks="false")])
    assert out["verdict"] == htr.NO and out["blockers"][0]["items"][0]["blocks_trading"] is True
    dq = out["data_quality"]
    assert len(dq) == 1 and dq[0]["input"] == htr.P0 and "override ignored" in dq[0]["cause"]


@pytest.mark.parametrize("atype", ["data_integrity", "orphaned_stop", "job_telemetry"])
def test_2411_d2c_an_override_raises_a_p1_or_info_to_blocking(atype):
    out = d2_verdict([inc(atype, blocks="true")])
    assert out["verdict"] == htr.NO and [b["kind"] for b in out["blockers"]] == ["p1"]


def test_2411_d2d_orphaned_stop_is_p1_non_blocking():
    cls = SHIPPED["incident_classes"]["orphaned_stop"]
    assert (cls["priority"], cls["blocks_trading_default"]) == ("P1", False)
    out = d2_verdict([inc("orphaned_stop", n=i) for i in range(3)])
    assert out["verdict"] == htr.YES and out["rows"]["alerts"]["state"] == htr.WARN


@pytest.mark.parametrize("registry,why", [
    (None, "not present"),
    ({**SHIPPED, "incident_classes_approved": False}, "not operator-approved"),
    ({k: v for k, v in SHIPPED.items() if k != "incident_classes_approved"}, "invalid"),
    ({**SHIPPED, "incident_classes_approved": "true"}, "invalid"),
    ({**SHIPPED, "incident_classes": {**SHIPPED["incident_classes"],
                                      "zq_bad": {**SHIPPED["incident_classes"]["position_unprotected"],
                                                 "blocks_trading_default": False}}}, "invalid"),
])
def test_2411_d2_an_unapproved_or_invalid_map_never_classifies(registry, why):
    out = d2(([inc("position_unprotected")]), registry)
    for name in (htr.P0, htr.P1_BLOCKING, htr.ALERTS, htr.INCIDENT_CLASSES):
        assert out[name].state == htr.UNKNOWN and why in out[name].reason, name
    assert d2_verdict([], registry)["verdict"] == htr.UNKNOWN


def test_2411_r3_true_a_good_read_no_overrides_unknown():
    out = d2_verdict([inc("position_unprotected")], data=htr.unknown(htr.DATA, "synthetic unreadable"))
    assert out["verdict"] == htr.NO and [u["input"] for u in out["unknown_inputs"]] == [htr.DATA]
    gap = fresh(htr.ORDERS, state=htr.GAP)
    out = d2_verdict([], orders=gap, data=htr.unknown(htr.DATA, "synthetic unreadable"))
    assert out["verdict"] == htr.NO


def test_2411_r3_false_unknown_beats_no():
    out = d2_verdict([inc("position_unprotected")], policy=R3_OFF, data=htr.unknown(htr.DATA, "synthetic unreadable"))
    assert out["verdict"] == htr.UNKNOWN and out["blockers"]          # the blocker is still listed
    assert d2_verdict([inc("position_unprotected")], policy=R3_OFF)["verdict"] == htr.NO
    assert d2_verdict([], policy=R3_OFF)["verdict"] == htr.YES


@pytest.mark.parametrize("policy", [None, {}, {"confirmed_no_overrides_unknown": "yes"},
                                    {"confirmed_no_overrides_unknown": 1}, "true"])
@pytest.mark.parametrize("rows", [[], [inc("position_unprotected")]])
def test_2411_r3_missing_or_invalid_config_is_unknown_config_invalid_never_yes_never_silent_no(policy, rows):
    out = d2_verdict(rows, policy=policy)
    assert out["verdict"] == htr.UNKNOWN
    assert any(u["input"] == "protection_verdict" and "config invalid" in u["reason"] for u in out["unknown_inputs"])
    assert any(d["input"] == "protection_verdict" and "config invalid" in d["cause"] for d in out["data_quality"])


def test_2411_the_lane_passes_the_registry_r3_block_to_the_rule(monkeypatch):
    seen = {}
    real = htr.compute_verdict
    monkeypatch.setattr(htr, "compute_verdict", lambda r, now, **k: seen.update(k) or real(r, now, **k))
    monkeypatch.setattr(lane, "pg_connect", lambda readonly: FakeConn())
    monkeypatch.setattr(lane, "make_query", lambda conn: FakeDB({}))
    monkeypatch.setattr(lane, "gather", lambda q, now, **k: list(all_ok(now).values()))
    import scripts.lib.lane_last_receipt as llr
    monkeypatch.setattr(llr, "enforce_readonly", lambda conn: conn)
    assert lane.main(["--dry-run"]) == 0
    assert seen["policy"] == SHIPPED["protection_verdict"]


def test_2411_rule_version_names_d2_and_r3():
    assert htr.RULE_VERSION == "home-v010-d2r3-20261112"
