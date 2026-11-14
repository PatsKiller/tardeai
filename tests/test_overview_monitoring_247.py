"""INC-OVW / OP-042: the two EXISTING monitoring paths see the overview lane's real states.

The incident was not that nothing watched the lane - ``ccv3_audit_remeasure`` had a row for it and
``desk_truth_monitor`` read its file. It is that both asked one question ("is the file younger than 300 s?")
that could not name the cause: a missed slot, a failed run, a build lock nobody released, or a last-good window
that is too short for the schedule all looked the same. These tests pin each state to its own finding, on the
lanes' own modules (no second copy of the cadence), with synthetic fixtures and isolated clocks.

Hermetic: tmp state roots, injected source callables, a monkeypatched clock where the module takes one, no DB,
no network, no live state root, and synthetic symbols/values only - the repository is public.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import desk_truth_monitor as DTM  # noqa: E402
from scripts.lib import overview_lane_contract as C  # noqa: E402
from scripts.lib import overview_projection as OP  # noqa: E402
from scripts.ops import ccv3_audit_remeasure as M  # noqa: E402

NOW = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)   # a Saturday, in no market session
#: the real body shape (flat: the producer stores what the route computes) with a Friday data clock
BODY = {"as_of": "2026-11-13T16:00:00-05:00", "data_as_of": "2026-11-13", "lookthrough_as_of": "2026-11-13",
        "journal": {"last_close_date": "2026-11-10"},
        "clock_provenance": {"positions": {"as_of": "2026-11-13T16:00:00Z"}, "day_pnl": {"as_of": None}},
        "market_session": {"as_of": "2026-11-14T15:00:00Z"}}


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _projection(root: Path, *, age_s: float = 30, status: str = "ok", clocks: bool = True) -> Path:
    rt = root / "data" / "runtime"
    rt.mkdir(parents=True, exist_ok=True)
    built = NOW.timestamp() - age_s
    doc = {"schema": "OverviewProjection@v1", "status": status, "built_at_epoch": built, "built_at": _iso(built),
           "code_identity": "sha:cafe", "body": BODY}
    if clocks:
        doc["source_clocks"] = C.source_clocks(BODY)
    path = rt / "overview_projection.json"
    path.write_text(json.dumps(doc))
    return path


def _receipt(root: Path, *, age_s: float = 20, status: str = "ok", empty_reason=None) -> Path:
    rt = root / "data" / "runtime"
    rt.mkdir(parents=True, exist_ok=True)
    stamp = _iso(NOW.timestamp() - age_s)
    path = rt / "overview-projection_last.json"
    path.write_text(json.dumps({"schema": "LaneRunReceipt@v2", "lane_id": "overview-projection", "mode": "live",
                                "status": status, "ok_at": stamp, "finished_at": stamp, "code_sha": "cafe",
                                "consecutive_failures": 0 if status == "ok" else 3,
                                "empty_reason": empty_reason}))
    return path


def _patched_contract(**over) -> dict:
    """The contract a release runs with once the shipped patch is applied: the window is the PATCH's, not the
    tree's (``scripts/lib/overview_projection.py`` is held by the R8 fold; see ``C.PATCH_REL``)."""
    doc = dict(C.contract(ROOT))
    window = C.patched_window(ROOT)
    assert window is not None, f"{C.PATCH_REL} is missing or sets no window"
    doc.update(reader="stored_only", last_good_max_s=window, headroom_s=window - doc["floor_s"], ok=True,
               invariant_applies=True)
    doc.update(over)
    return doc


def _inline_contract(**over) -> dict:
    """R8's reader: computes on the request thread, so there is no window and no body can expire."""
    doc = dict(C.contract(ROOT))
    doc.update(reader="inline", last_good_max_s=None, headroom_s=None, ok=True, invariant_applies=False)
    doc.update(over)
    return doc


@pytest.fixture
def patched(monkeypatch):
    """Put the shipped window on the live module, the way the release will run."""
    window = C.patched_window(ROOT)
    assert window is not None, f"{C.PATCH_REL} is missing or sets no window"
    monkeypatch.setattr(OP, "LAST_GOOD_MAX_S", window, raising=False)
    C._contract_cached.cache_clear()
    return window


def _health(**over) -> dict:
    """lane_health for a body of a chosen age, from synthetic documents only."""
    proj = {"status": "ok", "built_at_epoch": NOW.timestamp() - over.pop("age_s", 30), "code_identity": "sha:cafe",
            "source_clocks": C.source_clocks(BODY)}
    rec = {"status": "ok", "ok_at": _iso(NOW.timestamp() - 20), "finished_at": _iso(NOW.timestamp() - 20),
           "empty_reason": None, "consecutive_failures": 0}
    proj.update(over.pop("proj", {}))
    rec.update(over.pop("rec", {}))
    kw = dict(projection=proj, projection_readable=True, receipt=rec, receipt_readable=True, now=NOW.timestamp(),
              contract_doc=over.pop("contract_doc", _patched_contract()))
    kw.update(over)
    return C.lane_health(**kw)


@pytest.fixture(autouse=True)
def _fresh_contract():
    """The derived contract is lru_cached per root; a test that patches a term must not leak into the next."""
    C._contract_cached.cache_clear()
    yield
    C._contract_cached.cache_clear()


def _by(rows, metric):
    return next(r for r in rows if r.metric == metric)


# ── ccv3_audit_remeasure: the rows, against the derived contract ───────────────────────────────────────────────
def test_a_healthy_lane_passes_every_row(tmp_path, patched):
    _projection(tmp_path)
    _receipt(tmp_path)
    rows = M.overview_projection(tmp_path, NOW)
    assert {r.status for r in rows} == {"PASS"}, [(r.metric, r.value, r.detail) for r in rows if r.status != "PASS"]
    # the thresholds are the DERIVED floor, not a hand-picked 300 s: name them so a future edit cannot re-hardcode
    contract = C.contract(ROOT)
    assert contract["floor_s"] == contract["max_gap_s"] + contract["retry"]["retry_span_s"] + contract["dispatch_delay_s"]
    assert f"{contract['floor_s']:.0f}" in _by(rows, "body_age_s").threshold
    assert _by(rows, "contract_headroom_s").value == round(contract["headroom_s"], 1)


def test_a_missing_body_fails_and_names_the_action(tmp_path, patched):
    """A stored-only reader with no body has no source clocks at all - that row must FAIL, not pass vacuously."""
    rows = M.overview_projection(tmp_path, NOW)
    assert _by(rows, "body_age_s").status == "FAIL" and _by(rows, "body_age_s").value is None
    assert _by(rows, "source_clocks_present").status == "FAIL"
    verdict = _by(rows, "verdict")
    assert verdict.status == "FAIL" and "missing" in verdict.value
    assert "Re-dispatch" in verdict.detail  # the operator's next step, not just a number


def test_an_expired_body_fails_and_says_expired(tmp_path, patched):
    _projection(tmp_path, age_s=patched + 120)
    _receipt(tmp_path)
    rows = M.overview_projection(tmp_path, NOW)
    assert _by(rows, "body_age_s").status == "FAIL"
    assert "expired" in _by(rows, "verdict").value.split(",")


def test_a_missed_slot_is_distinct_from_expiry(tmp_path, patched):
    """A body older than one slot + retries + delay has MISSED a slot while the reader can still serve it."""
    _projection(tmp_path, age_s=C.contract(ROOT)["floor_s"] + 60)
    _receipt(tmp_path)
    rows = M.overview_projection(tmp_path, NOW)
    assert _by(rows, "body_age_s").status == "FAIL"
    broken = _by(rows, "verdict").value.split(",")
    assert "missed" in broken and "expired" not in broken
    assert _by(rows, "verdict").status == "FAIL"


def test_a_failed_receipt_is_a_finding_even_when_the_body_is_fresh(tmp_path):
    _projection(tmp_path)
    _receipt(tmp_path, age_s=C.contract(ROOT)["max_gap_s"] + 600, status="failed")
    rows = M.overview_projection(tmp_path, NOW)
    assert "failed" in _by(rows, "verdict").value
    assert "failed" in _by(rows, "lane_receipt_age_s").detail


def test_a_lowered_last_good_window_fails_the_contract_row(tmp_path, monkeypatch):
    """Mutant M3: LAST_GOOD_MAX_S = 240. The producer is perfectly healthy; only the constant moved."""
    monkeypatch.setattr(OP, "LAST_GOOD_MAX_S", 240.0, raising=False)
    C._contract_cached.cache_clear()
    _projection(tmp_path, age_s=30)
    _receipt(tmp_path, age_s=20)
    rows = M.overview_projection(tmp_path, NOW)
    assert _by(rows, "contract_headroom_s").status == "FAIL"
    assert _by(rows, "contract_headroom_s").value < 0


def test_an_unreadable_contract_is_an_ERROR_not_a_crash(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise C.ContractError("registry row missing")

    monkeypatch.setattr(C, "contract", boom)
    rows = M.overview_projection(tmp_path, NOW)
    assert rows[0].metric == "contract" and rows[0].status == "ERROR"
    assert "ContractError" in rows[0].detail


def test_the_step_table_runs_the_new_metric(tmp_path, patched):
    """The measure() step table must still find the rows - a rename that misses it silently drops the item."""
    _projection(tmp_path)
    _receipt(tmp_path)
    db = _NoDB()
    rows = M.measure(db, tmp_path, {"lanes": []}, lambda: "", NOW)
    assert any(r.item == "overview_projection" and r.metric == "body_age_s" for r in rows)


class _NoDB:
    """The overview rows read files only; any SQL here is a defect and fails loudly."""

    def __call__(self, sql, params):
        raise AssertionError(f"the overview row must not query: {sql[:60]}")


# ── desk_truth_monitor: one finding per lane state ─────────────────────────────────────────────────────────────
def test_each_lane_state_maps_to_its_own_finding():
    cases = {
        "missing": ("DT_PROJECTION_UNKNOWN", True),
        "expired": ("DT_PROJECTION_UNKNOWN", True),
        "missed": ("DT_PROJECTION_MISSED_SLOT", True),
        "failed": ("DT_PROJECTION_RUN_FAILED", True),
        "refused_streak": ("DT_PROJECTION_LOCK_HELD", True),
        "headroom_low": ("DT_PROJECTION_HEADROOM", False),
    }
    for verdict, (code, alert) in cases.items():
        health = _health()
        health["verdicts"] = {k: k == verdict for k in health["verdicts"]}
        health["broken"] = [verdict]
        found = DTM._projection_findings(health)
        assert [f["code"] for f in found] == [code], (verdict, found)
        assert found[0]["alert"] is alert, verdict
        assert found[0]["evidence"]["next_action"], verdict


def test_a_healthy_lane_produces_no_finding(patched):
    assert DTM._projection_findings(_health()) == []


# ── R8's reader: no window at all, and saying so is not the same as passing an inequality ─────────────────────
def test_an_inline_reader_is_named_and_no_window_row_claims_a_pass(tmp_path, monkeypatch):
    monkeypatch.delattr(OP, "LAST_GOOD_MAX_S", raising=False)
    C._contract_cached.cache_clear()
    assert C.contract(ROOT)["reader"] == "inline"
    _projection(tmp_path)
    _receipt(tmp_path)
    rows = M.overview_projection(tmp_path, NOW)
    assert {r.status for r in rows} == {"PASS"}, [(r.metric, r.status, r.detail) for r in rows if r.status != "PASS"]
    assert _by(rows, "contract_headroom_s").value is None
    assert "n/a (inline reader)" == _by(rows, "contract_headroom_s").threshold
    assert "inline" in _by(rows, "body_age_s").detail


def test_an_inline_reader_can_never_answer_unknown_from_an_old_body(monkeypatch):
    """The incident state must not exist on R8: however old the body, the page computes instead."""
    monkeypatch.delattr(OP, "LAST_GOOD_MAX_S", raising=False)
    C._contract_cached.cache_clear()
    health = _health(age_s=7 * 24 * 3600, contract_doc=_inline_contract())
    assert health["reader"] == "inline"
    assert health["verdicts"]["expired"] is False and health["verdicts"]["headroom_low"] is False
    assert "expired" not in DTM._projection_findings(health) and health["broken"] == ["missed"]


def test_the_inline_contract_does_not_pass_the_inequality_it_never_ran():
    doc = C.contract(ROOT)
    if doc["reader"] == "stored_only":
        return  # this tree carries the reader; the inline case is simulated by the tests above
    assert doc["last_good_max_s"] is None and doc["invariant_applies"] is False and doc["ok"] is True


def test_no_injected_lane_source_is_silence_and_an_error_is_never_silence():
    assert DTM._projection_findings(None) == []
    found = DTM._projection_findings({"error": "PermissionError: denied"})
    assert [f["code"] for f in found] == ["DT_PROJECTION_UNREADABLE"] and found[0]["alert"] is True


def test_the_expired_state_carries_the_numbers_it_is_judged_by(patched):
    health = _health(age_s=patched + 60)
    found = DTM._projection_findings(health)
    ev = found[0]["evidence"]
    assert ev["age_s"] > ev["last_good_max_s"] and ev["last_good_max_s"] == C.contract(ROOT)["last_good_max_s"]
    assert "last-good window" in found[0]["detail"]


# ── the wiring: display_truth reports it, the heal plan routes it, the runner never aborts on it ───────────────
POSITIONS = [{"account_key": "schwab_taxable", "symbol": "ZQAA", "qty": 100, "is_cash": False,
              "asset_type": "equity", "as_of": "2026-11-13T20:55:00+00:00"}]
QUOTES = [{"symbol": "ZQAA", "source": "finviz", "price": 10.0, "prev_close": 9.5,
           "fetched_at": "2026-11-13T20:58:00+00:00"}]
OVERVIEW = {"total_value": 1000.0, "day_pnl": 50.0, "as_of": "2026-11-13T20:59:30+00:00",
            "accounts": [{"account": "schwab_taxable", "market_value": 1000.0}]}


def test_display_truth_carries_the_lane_finding_and_the_heal_routes_it():
    D = DTM.load_config()["display_truth"]
    health = _health()
    health["verdicts"] = {k: k == "missed" for k in health["verdicts"]}
    health["broken"] = ["missed"]
    rep = DTM.display_truth(POSITIONS, QUOTES, [], {"overview": OVERVIEW}, D, now=NOW, session=False,
                            projection_lane=health)
    assert "DT_PROJECTION_MISSED_SLOT" in [f["code"] for f in rep["findings"]]
    assert rep["heal"]["lanes"]["DT_PROJECTION_MISSED_SLOT"] == "overview-projection"
    assert "DT_PROJECTION_MISSED_SLOT" not in rep["heal"]["unhealable"]


def test_a_held_lock_is_not_auto_healed():
    """Re-dispatching a lane that is refusing the lock is a no-op; the plan must say so, not loop."""
    health = _health()
    health["verdicts"] = {k: k == "refused_streak" for k in health["verdicts"]}
    health["broken"] = ["refused_streak"]
    D = DTM.load_config()["display_truth"]
    rep = DTM.display_truth(POSITIONS, QUOTES, [], {"overview": OVERVIEW}, D, now=NOW, session=False,
                            projection_lane=health)
    assert "DT_PROJECTION_LOCK_HELD" in rep["heal"]["unhealable"]


def test_run_check_without_a_lane_source_still_runs(tmp_path, monkeypatch):
    """Injected-source callers predate this source; a missing one must not turn the check into an error."""
    D = DTM.load_config()
    sources = {"positions_current": lambda: POSITIONS, "stop_last_known": lambda: [],
               "market_quotes": lambda: QUOTES, "displayed": lambda: {"overview": OVERVIEW},
               "previous_display": lambda: None}
    rep = DTM.run_check("display-truth", now=NOW, cfg=D, sources=sources, trading_day=lambda _n: False)
    assert not rep.get("error"), rep.get("error")
    assert "DT_PROJECTION_UNREADABLE" not in [f["code"] for f in rep.get("findings") or []]


def test_run_check_reports_a_lane_source_that_raises(tmp_path):
    D = DTM.load_config()

    def boom():
        raise PermissionError("denied")

    sources = {"positions_current": lambda: POSITIONS, "stop_last_known": lambda: [],
               "market_quotes": lambda: QUOTES, "displayed": lambda: {"overview": OVERVIEW},
               "previous_display": lambda: None, "projection_lane": boom}
    rep = DTM.run_check("display-truth", now=NOW, cfg=D, sources=sources, trading_day=lambda _n: False)
    assert not rep.get("error"), rep.get("error")
    assert "DT_PROJECTION_UNREADABLE" in [f["code"] for f in rep.get("findings") or []]
    assert rep["alertable"] == ["projection:lane"]  # alertable is keyed by finding KEY, not code
