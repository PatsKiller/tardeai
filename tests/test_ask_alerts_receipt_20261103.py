"""ask-alerts: the registry reads the lane's LaneRunReceipt, not the alert store's mtime.

Jobs coverage audit (2026-11-03): `ask-alerts` (cron `*/30 8-18 * * 1-5`, `scripts/ask_alerts.py --check`) declared
`output_signal` as `file_mtime` on `data/runtime/ask_alerts.json` — the alert STORE, which `check_alerts()` saves
unconditionally, so a failed evaluation advanced the mtime and looked fresh. The script has written a
`LaneRunReceipt` since shard 03 (success writes `ok`/`ok_at`, a failure writes `failed` with the previous `ok_at`
preserved, `--dry-run` writes nothing); the only defect was the registry pointing at the store instead of the receipt.

Hermetic: the module is loaded from source into its own module object, its `STORE` and the state root are redirected to
``tmp_path``, and `check_alerts` is stubbed. No DB, Telegram, provider, lock or live state.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT
import sys  # noqa: E402

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _load():
    """Load scripts/ask_alerts.py into its own module object (its import-time sys.path insert is contained)."""
    path = ROOT / "scripts" / "ask_alerts.py"
    mod = types.ModuleType("ask_alerts_under_test")
    mod.__file__ = str(path)
    exec(compile(path.read_text(encoding="utf-8"), mod.__file__, "exec"), mod.__dict__)
    return mod


@pytest.fixture
def lane(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "ps"))
    mod = _load()
    mod.STORE = tmp_path / "store" / "ask_alerts.json"
    return mod


def _receipt(tmp_path: Path) -> Path:
    return tmp_path / "state" / "data" / "runtime" / "ask-alerts_last.json"


def test_a_completed_check_writes_ok_and_advances_ok_at(tmp_path, lane, capsys):
    lane.check_alerts = lambda: []
    assert lane.main(["--check"]) == 0
    doc = json.loads(_receipt(tmp_path).read_text())
    assert doc["lane_id"] == "ask-alerts" and doc["status"] == "ok" and doc["exit"] == 0
    assert doc["ok_at"] and doc["ok_at"] == doc["finished_at"], doc
    assert doc["summary"] == {"checked": True, "fired": 0, "listed": 0}, doc
    assert "fired" in capsys.readouterr().out


def test_a_failed_evaluation_is_failed_and_never_advances_ok_at(tmp_path, lane):
    """Revert the except-path write -> a failed run reads as the previous success (or never ran)."""
    receipt = _receipt(tmp_path)
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        json.dumps(
            {"lane_id": "ask-alerts", "status": "ok", "ok_at": "2026-11-01T00:00:00+00:00", "consecutive_failures": 0}
        )
    )

    def boom():
        raise RuntimeError("fixture evaluation failure")

    lane.check_alerts = boom
    with pytest.raises(RuntimeError):
        lane.main(["--check"])
    doc = json.loads(receipt.read_text())
    assert doc["status"] == "failed" and doc["exit"] == 1, doc
    assert doc["error"] == "RuntimeError", doc
    assert doc["ok_at"] == "2026-11-01T00:00:00+00:00", "a failed run must not advance ok_at"
    assert doc["consecutive_failures"] == 1, doc


def test_ran_and_found_nothing_is_a_success_not_a_failure(tmp_path, lane):
    lane.STORE.parent.mkdir(parents=True)
    lane.STORE.write_text(
        json.dumps(
            {"alerts": [{"id": "a1", "status": "active", "kind": "ipo", "company": "ACME", "last_checked": None}]}
        )
    )
    lane.check_alerts = lambda: []
    assert lane.main(["--check"]) == 0
    doc = json.loads(_receipt(tmp_path).read_text())
    assert doc["status"] == "ok" and doc["summary"]["fired"] == 0, doc


def test_dry_run_writes_nothing_and_evaluates_nothing(tmp_path, lane, capsys):
    """A dry run cannot reach the write (AGENTS.md section 6) and must not call the evaluator."""

    def must_not_be_called():
        raise AssertionError("dry run evaluated alerts")

    lane.check_alerts = must_not_be_called
    assert lane.main(["--check", "--dry-run"]) == 0
    assert capsys.readouterr().out.startswith("DRY-RUN ask-alerts: would")
    assert not _receipt(tmp_path).exists()
    with pytest.raises(SystemExit) as exc:
        lane.main(["--made-up-flag"])
    assert exc.value.code == 2
    assert not _receipt(tmp_path).exists()


def test_the_registry_signal_is_the_receipt_json_key(tmp_path):
    """Revert the registry row -> the lane reads the alert store's mtime again and a failed run looks fresh."""
    cfg = json.loads((ROOT / "config" / "lane_registry.json").read_text())
    row = next(r for r in (cfg.get("lanes") or []) if r.get("lane_id") == "ask-alerts")
    signal = row["output_signal"]
    # The row is the generator's fixed point, so it also carries evidence/evidence_ref; the signal triple is:
    assert {k: signal.get(k) for k in ("kind", "path", "key")} == {
        "kind": "json_key", "path": "data/runtime/ask-alerts_last.json", "key": "ok_at"}, signal
    assert signal["kind"] != "file_mtime" and signal["path"] != "data/runtime/ask_alerts.json"

    from lib import lane_last_receipt as lr  # noqa: E402

    resolved = lr.receipt_path("ask-alerts", root=tmp_path)
    assert resolved.name == Path(signal["path"]).name
    assert resolved.parent == tmp_path / "data" / "runtime"


# ---------------------------------------------------------------- evaluation honesty (same audit, same lane)
def _store_with(lane, tmp_path, kind="ipo_watch", **extra):
    lane.STORE.parent.mkdir(parents=True, exist_ok=True)
    alert = {
        "id": "a1",
        "question": "when does ACME list?",
        "kind": kind,
        "companies": ["ACME"],
        "symbols": ["ACME"],
        "target_price": None,
        "created_at": "2026-11-01T00:00:00+00:00",
        "status": "active",
        "triggered_at": None,
        **extra,
    }
    lane.STORE.write_text(json.dumps({"alerts": [alert]}))
    return alert


def test_a_failed_news_query_is_a_failed_run_not_no_news(tmp_path, lane, monkeypatch):
    """Revert `_news_hits` to return [] on error -> a database outage reads as a green, quiet run.

    The real `_news_hits` is exercised: only its DB seam (`alert_event_writer._get_conn`) fails.
    """
    _store_with(lane, tmp_path)
    events = types.ModuleType("alert_event_writer")

    def down():
        raise RuntimeError("connection refused")

    events._get_conn = down
    monkeypatch.setitem(sys.modules, "alert_event_writer", events)
    with pytest.raises(lane._EvalError):
        lane.main(["--check"])
    doc = json.loads(_receipt(tmp_path).read_text())
    assert doc["status"] == "failed" and doc["error"] == "_EvalError", doc
    stored = json.loads(lane.STORE.read_text())["alerts"][0]
    assert stored["status"] == "active", "a failed evaluation must not mark the alert triggered"


def test_an_alert_whose_event_was_not_saved_stays_active_and_fails_the_run(tmp_path, lane, monkeypatch):
    """Revert `_fire` -> save_alert_event returning None is ignored, the alert is marked triggered and lost, run green."""
    _store_with(lane, tmp_path)
    lane._news_hits = lambda name, kw: [{"title": "ACME files to go public", "url": "https://x", "at": "now"}]
    events = types.ModuleType("alert_event_writer")
    events._get_conn = lambda: None
    events.save_alert_event = lambda **_k: None  # its real failure shape: swallows the DB error and returns None
    monkeypatch.setitem(sys.modules, "alert_event_writer", events)
    with pytest.raises(lane._EvalError):
        lane.main(["--check"])
    assert json.loads(_receipt(tmp_path).read_text())["status"] == "failed"
    assert json.loads(lane.STORE.read_text())["alerts"][0]["status"] == "active"


def test_a_corrupt_store_fails_the_run_and_is_never_overwritten(tmp_path, lane):
    lane.STORE.parent.mkdir(parents=True, exist_ok=True)
    lane.STORE.write_text("{not json")
    with pytest.raises(lane._EvalError):
        lane.main(["--check"])
    assert lane.STORE.read_text() == "{not json", "an unreadable store must not be replaced by an empty one"
    assert json.loads(_receipt(tmp_path).read_text())["status"] == "failed"


def test_a_confirmed_hit_is_enqueued_and_the_alert_is_triggered(tmp_path, lane, monkeypatch):
    _store_with(lane, tmp_path)
    lane._news_hits = lambda name, kw: [{"title": "ACME files to go public", "url": "https://x", "at": "now"}]
    saved = []

    def save(**kwargs):
        saved.append(kwargs)
        return "evt-1"

    events = types.ModuleType("alert_event_writer")
    events.save_alert_event = save
    monkeypatch.setitem(sys.modules, "alert_event_writer", events)
    assert lane.main(["--check"]) == 0
    doc = json.loads(_receipt(tmp_path).read_text())
    assert doc["status"] == "ok" and doc["summary"]["fired"] == 1, doc
    assert len(saved) == 1 and saved[0]["parsed_payload"]["alert_id"] == "a1"
    assert json.loads(lane.STORE.read_text())["alerts"][0]["status"] == "triggered"


# ---------------------------------------------------------------- cc2 review (2026-11-03) B1/B2
def test_a_malformed_record_after_a_fired_alert_keeps_the_fired_state_and_fails(tmp_path, lane, monkeypatch):
    """B1: a non-numeric target used to escape before _save, so the fired alert fired again next run."""
    lane.STORE.parent.mkdir(parents=True, exist_ok=True)
    lane.STORE.write_text(json.dumps({"alerts": [
        {"id": "a1", "question": "when does ACME list?", "kind": "ipo_watch", "companies": ["ACME"],
         "symbols": [], "target_price": None, "created_at": "x", "status": "active", "triggered_at": None},
        {"id": "bad", "question": "wat", "kind": "price", "companies": [], "symbols": ["ACME"],
         "target_price": {"not": "a number"}, "created_at": "x", "status": "active", "triggered_at": None},
    ]}))
    lane._news_hits = lambda name, kw: [{"title": "ACME files to go public", "url": "https://x", "at": "now"}]
    events = types.ModuleType("alert_event_writer")
    events.save_alert_event = lambda **_k: "evt-1"
    monkeypatch.setitem(sys.modules, "alert_event_writer", events)

    with pytest.raises(lane._EvalError) as raised:
        lane.main(["--check"])
    assert "record:TypeError" in str(raised.value), raised.value
    stored = {a["id"]: a["status"] for a in json.loads(lane.STORE.read_text())["alerts"]}
    assert stored["a1"] == "triggered", "the alert that already fired lost its state"
    assert stored["bad"] == "active"
    assert json.loads(_receipt(tmp_path).read_text())["status"] == "failed"


def test_an_active_alert_the_evaluator_cannot_handle_fails_the_run(tmp_path, lane, monkeypatch):
    """B2: an unsupported/incomplete active alert used to be skipped and the run said ok (a false green)."""
    lane.STORE.parent.mkdir(parents=True, exist_ok=True)
    lane.STORE.write_text(json.dumps({"alerts": [
        {"id": "news-1", "question": "any news?", "kind": "news", "companies": [], "symbols": ["ACME"],
         "target_price": None, "created_at": "x", "status": "active", "triggered_at": None},
    ]}))
    with pytest.raises(lane._EvalError) as raised:
        lane.main(["--check"])
    assert "unsupported active alert" in str(raised.value), raised.value
    assert json.loads(_receipt(tmp_path).read_text())["status"] == "failed"
    assert json.loads(lane.STORE.read_text())["alerts"][0]["status"] == "active"


def test_a_non_dict_record_does_not_stop_later_alerts(tmp_path, lane, monkeypatch):
    """The status check used to sit outside the per-alert try: a junk record aborted the whole scan."""
    lane.STORE.parent.mkdir(parents=True, exist_ok=True)
    lane.STORE.write_text(json.dumps({"alerts": [
        None,
        {"id": "a1", "question": "when does ACME list?", "kind": "ipo_watch", "companies": ["ACME"],
         "symbols": [], "target_price": None, "created_at": "x", "status": "active", "triggered_at": None},
    ]}))
    lane._news_hits = lambda name, kw: [{"title": "ACME files to go public", "url": "https://x", "at": "now"}]
    events = types.ModuleType("alert_event_writer")
    events.save_alert_event = lambda **_k: "evt-1"
    monkeypatch.setitem(sys.modules, "alert_event_writer", events)

    with pytest.raises(lane._EvalError) as raised:
        lane.main(["--check"])
    assert "record is not an object" in str(raised.value), raised.value
    stored = {a["id"]: a["status"] for a in json.loads(lane.STORE.read_text())["alerts"] if isinstance(a, dict)}
    assert stored["a1"] == "triggered", "a junk record must not stop the alerts after it"


def test_a_store_whose_alerts_is_not_a_list_fails_honestly(tmp_path, lane):
    lane.STORE.parent.mkdir(parents=True, exist_ok=True)
    lane.STORE.write_text(json.dumps({"alerts": "x"}))
    with pytest.raises(lane._EvalError) as raised:
        lane.main(["--check"])
    assert "no alert list" in str(raised.value), raised.value
    assert json.loads(_receipt(tmp_path).read_text())["status"] == "failed"


def test_a_thousands_separated_price_is_parsed_as_a_real_target(lane, tmp_path, monkeypatch):
    """'$1,000' used to parse as '000' -> 0.0, which the evaluator cannot handle and now fails every run."""
    lane.STORE = tmp_path / "store" / "ask_alerts.json"
    alert = lane.add_alert("alert me when NVDA hits $1,000",
                           {"positions": [{"symbol": "NVDA", "held": True, "private": False}]})
    assert alert["kind"] == "price" and alert["target_price"] == 1000.0, alert


def test_a_price_target_without_a_dollar_sign_still_parses(lane, tmp_path):
    """codex-cloud #2528: requiring "$" turned "hits 150" (a price alert before the thousands fix) into a refusal."""
    lane.STORE = tmp_path / "store" / "ask_alerts.json"
    ctx = {"positions": [{"symbol": "ACME", "held": True, "private": False}]}
    plain = lane.add_alert("alert me when ACME hits 150", ctx)
    assert plain["kind"] == "price" and plain["target_price"] == 150.0, plain
    marked = lane.add_alert("alert me when ACME hits $150", ctx)
    assert marked["kind"] == "price" and marked["target_price"] == 150.0, marked
    thousands = lane.add_alert("alert me when ACME hits 1,500", ctx)
    assert thousands["kind"] == "price" and thousands["target_price"] == 1500.0, thousands


def test_an_ask_with_no_number_is_still_refused_and_writes_nothing(lane, tmp_path):
    """An optional currency marker must not make a number-less ask parse as a target."""
    lane.STORE = tmp_path / "store" / "ask_alerts.json"
    ctx = {"positions": [{"symbol": "ACME", "held": True, "private": False}]}
    for question in ("alert me when ACME hits the roof", "alert me when ACME hits $"):
        with pytest.raises(ValueError, match="cannot evaluate"):
            lane.add_alert(question, ctx)
    assert not lane.STORE.exists(), "a refused ask must not write an alert"


def test_the_ask_alert_route_accepts_a_price_target_without_a_dollar_sign(lane, tmp_path, monkeypatch):
    """The operator-facing path: AskAgents forwards the question unchanged, so this used to answer HTTP 400."""
    import api_v2

    lane.STORE = tmp_path / "store" / "ask_alerts.json"
    monkeypatch.setitem(sys.modules, "ask_alerts", lane)
    status, payload = api_v2.handle(
        "/api/v2/portfolio/ask-alert", method="POST",
        body={"question": "alert me when ACME hits 150",
              "context": {"positions": [{"symbol": "ACME", "held": True, "private": False}]}})
    assert status == 200, (status, payload)
    assert payload["alert"]["kind"] == "price" and payload["alert"]["target_price"] == 150.0, payload


def test_a_non_finite_target_is_a_record_error(tmp_path, lane):
    lane.STORE.parent.mkdir(parents=True, exist_ok=True)
    for bad in ("nan", "inf"):
        lane.STORE.write_text(json.dumps({"alerts": [
            {"id": "p1", "question": "q", "kind": "price", "companies": [], "symbols": ["ACME"],
             "target_price": bad, "created_at": "x", "status": "active", "triggered_at": None},
        ]}))
        with pytest.raises(lane._EvalError) as raised:
            lane.main(["--check"])
        assert "positive finite" in str(raised.value), (bad, raised.value)


def test_add_alert_refuses_an_intent_the_evaluator_cannot_handle(lane, tmp_path):
    """cc2 re-review: a created `news` alert was inert AND made every run fail; refuse the create instead."""
    lane.STORE = tmp_path / "store" / "ask_alerts.json"
    with pytest.raises(ValueError, match="cannot evaluate"):
        lane.add_alert("alert me when there is news about ACME",
                       {"positions": [{"symbol": "ACME", "held": True, "private": False}]})
    with pytest.raises(ValueError, match="cannot evaluate"):
        lane.add_alert("alert me when ACME hits $0", {"positions": [{"symbol": "ACME", "held": True, "private": False}]})


def test_the_ask_alert_route_maps_a_refused_intent_to_400(monkeypatch):
    """A caller error must not be a 500, and it must not create an alert the evaluator cannot watch."""
    import api_v2

    stub = types.ModuleType("ask_alerts")

    def refuse(question, context):
        raise ValueError("this alert would watch news, which the monitor cannot evaluate")

    stub.add_alert = refuse
    monkeypatch.setitem(sys.modules, "ask_alerts", stub)
    status, payload = api_v2.handle("/api/v2/portfolio/ask-alert", method="POST", body={"question": "news about ACME"})
    assert status == 400, (status, payload)
    assert payload["ok"] is False and "cannot evaluate" in payload["error"], payload


def test_a_digit_inside_a_company_name_is_not_a_price_target(lane, tmp_path):
    """codex-cloud round 2 on #2528: making the "$" optional let the first digit ANYWHERE match.

    "alert me when L3Harris hits $150" produced target 3.0 (the 3 in L3Harris) instead of 150.0, so an
    operator asking for a $150 alert got one at $3. A number embedded in a word is not a price.
    """
    lane.STORE = tmp_path / "store" / "ask_alerts.json"
    ctx = {"positions": [{"symbol": "LHX", "name": "L3Harris", "held": True, "private": False}]}
    alert = lane.add_alert("alert me when L3Harris hits $150", ctx)
    assert alert["kind"] == "price" and alert["target_price"] == 150.0, alert


def test_a_list_run_does_not_clear_a_failed_evaluator_receipt(tmp_path, lane):
    """D52 triage KEEP_BLOCK #2528: `--list` wrote ok=True with checked=False.

    It evaluated no alert, yet it overwrote the lane receipt, so a failed evaluator was silently
    replaced by a healthy-looking one by a read-only listing. Only an evaluating run may claim health.
    """
    def _boom():
        raise RuntimeError("evaluator unavailable")

    lane.check_alerts = _boom
    with pytest.raises(RuntimeError):
        lane.main(["--check"])
    failed = json.loads(_receipt(tmp_path).read_text())
    assert failed["status"] != "ok", failed

    lane.list_alerts = lambda: [{"symbol": "AAA", "target_price": 1.0}]
    assert lane.main(["--list"]) == 0
    after = json.loads(_receipt(tmp_path).read_text())
    assert after == failed, (
        "a listing must leave the evaluator's failed receipt untouched, not clear it")
