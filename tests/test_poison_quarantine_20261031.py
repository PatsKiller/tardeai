"""Poison-item quarantine (coordinator 2026-10-31; operator: "validate all stuck agents and processes fix montior and
make auto healings with claude code"). Example: Ask-the-CIO thread thr_b00c8806cf63a6bf failed cio-ask-lifecycle
three runs in a row on 2026-10-30, opened the n8n breaker and stopped every other thread for a day.

Pins (incl. the independent review of 2026-10-31): deterministic errors only (transient ones neither count nor
reset); a success resets; threshold -> quarantine with a receipt and one P2 (message_class passed); at most
max_per_run / max_share quarantined per run so an outage still fails the lane; one store per lane under a flock with
read-modify-write; a corrupt store raises (and the lifecycle run fails loudly); expiry re-checks once; release CLI;
disabled and dry run are inert. End to end through the real cio_ask_lifecycle.run_once. Hermetic, TRADE_AI_CI=1.
"""

from __future__ import annotations

#: C1 firing coverage — this module injects the condition and asserts the message reaches the (stubbed) transport.
COVERS = ["scripts/lib/poison_quarantine.py"]

import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from scripts.lib import poison_quarantine as PQ  # noqa: E402

CFG = PQ.load_config()
NOW = datetime(2026, 10, 31, 15, 0, tzinfo=timezone.utc)
DET = "CHECK_FAILED:ValueError: fact rejected"


@pytest.fixture
def sent(monkeypatch):
    box: list[dict] = []
    mod = types.ModuleType("telegram_alert")
    mod.send_telegram = lambda message, **kw: box.append({"message": message, **kw}) or True
    monkeypatch.setitem(sys.modules, "telegram_alert", mod)
    return box


def _q(tmp_path, now=NOW, **over):
    return PQ.Quarantine("cio-ask-lifecycle", {**CFG, "enabled": True, **over}, tmp_path, now=now)


HEALTHY = {f"thr_ok{i}": False for i in range(9)}  # healthy neighbours: a failing item is a minority, not systemic


def _h(outcomes):
    return {**HEALTHY, **outcomes}


def _runs(tmp_path, outcomes, reasons, n, **kw):
    out = []
    for i in range(n):
        q = _q(tmp_path, now=NOW + timedelta(hours=i), **kw)
        out.append(q.record_run(_h(outcomes), reasons=reasons))
        assert q.save() == []
    return out


def test_streak_threshold_reset_receipt_and_p2(tmp_path, sent):
    _runs(tmp_path, {"thr_a": True, "thr_b": True}, {"thr_a": DET, "thr_b": DET}, 2, max_share=1.0, max_per_run=5)
    q = _q(tmp_path)
    q.record_run(_h({"thr_b": False}))  # a success resets thr_b only
    q.save()
    q = _q(tmp_path, max_share=1.0, max_per_run=5)
    newly = q.record_run(_h({"thr_a": True, "thr_b": True}), reasons={"thr_a": DET, "thr_b": DET})
    assert [r["item"] for r in newly] == ["thr_a"] and newly[0]["consecutive_failures"] == 3
    assert q.save() == []
    assert len(sent) == 1 and sent[0]["priority"] == "P2" and sent[0]["message_class"] == CFG["message_class"]
    rec = [json.loads(x) for x in (tmp_path / CFG["receipts_rel"]).read_text().splitlines()]
    assert rec[0]["item"] == "thr_a" and rec[0]["reason"] == DET
    assert _q(tmp_path).is_quarantined("thr_a") and not _q(tmp_path).is_quarantined("thr_b")
    assert (tmp_path / CFG["store_dir_rel"] / "cio-ask-lifecycle.json").exists()  # one store per lane


def test_transient_errors_never_count_or_reset(tmp_path, sent):
    for reason in (
        "ConnectionError: refused",
        "ReadTimeout",
        "HTTP 503",
        "SEARCH_CAP",
        "OperationalError",
        "CHECK_FAILED:ValueError:SOURCE_CHECK_INCOMPLETE",
    ):
        assert PQ.is_transient(reason, CFG), reason
    _runs(tmp_path, {"thr_a": True}, {"thr_a": DET}, 2)
    _runs(tmp_path, {"thr_a": True}, {"thr_a": "ConnectionError: refused"}, 5)  # an outage: no count, no reset
    q = _q(tmp_path)
    assert q.doc["streaks"]["thr_a"] == 2 and not q.is_quarantined("thr_a")
    assert [r["item"] for r in q.record_run(_h({"thr_a": True}), reasons={"thr_a": DET})] == ["thr_a"]


def test_cap_per_run_and_systemic_failure(tmp_path, sent):
    items = {f"thr_{i}": i < 2 for i in range(10)}  # 2 of 10 fail: a minority
    reasons = {k: DET for k, v in items.items() if v}
    runs = _runs(tmp_path / "minority", items, reasons, 3)
    assert len(runs[2]) == 1  # max_per_run 1: the other one keeps failing the run
    many = {f"thr_{i}": i < 5 for i in range(10)}  # 5 of 10 fail: systemic (> max_share)
    q = _q(tmp_path / "systemic")
    for _ in range(4):
        assert q.record_run(many, reasons={k: DET for k in many}) == []
    assert q.systemic == {"failing": 5, "items": 10} and q.doc["streaks"] == {}  # nothing moves; the lane fails


def test_corrupt_store_raises_never_empty(tmp_path):
    p = tmp_path / CFG["store_dir_rel"] / "cio-ask-lifecycle.json"
    p.parent.mkdir(parents=True)
    p.write_text("{half")
    with pytest.raises(PQ.PoisonStoreCorrupt):
        _q(tmp_path)


def test_concurrent_writers_merge_under_the_flock(tmp_path):
    a, b = _q(tmp_path), _q(tmp_path)  # two runs loaded the same (empty) store
    a.record_run(_h({"thr_a": True}), reasons={"thr_a": DET})
    b.record_run(_h({"thr_b": True}), reasons={"thr_b": DET})
    a.save()
    b.save()  # read-modify-write: b must not erase a's streak
    assert _q(tmp_path).doc["streaks"] == {"thr_a": 1, "thr_b": 1}


def test_expiry_rechecks_once(tmp_path, sent):
    _runs(tmp_path, {"thr_a": True}, {"thr_a": DET}, 3)
    later = NOW + timedelta(hours=CFG["expire_hours"] + 3)
    q = _q(tmp_path, now=later)
    assert not q.is_quarantined("thr_a")  # expired: processed once more
    assert [r["item"] for r in q.record_run(_h({"thr_a": True}), reasons={"thr_a": DET})] == ["thr_a"]  # fails: again
    q.save()
    q2 = _q(tmp_path, now=later + timedelta(hours=CFG["expire_hours"] + 1))
    q2.record_run(_h({"thr_a": False}))  # passes on its re-check: released
    q2.save()
    assert "thr_a" not in _q(tmp_path, now=later).doc["quarantined"]


def test_release_cli(tmp_path, monkeypatch, sent):
    import poison_quarantine as CLI

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(PQ, "load_config", lambda path=None: {**CFG, "enabled": True})
    _runs(tmp_path, {"thr_a": True}, {"thr_a": DET}, 3)
    assert CLI.main(["release", "--lane", "cio-ask-lifecycle", "--item", "thr_a", "--note", "fixed"]) == 0  # dry
    assert _q(tmp_path).is_quarantined("thr_a")
    assert CLI.main(["release", "--lane", "cio-ask-lifecycle", "--item", "thr_a", "--note", "fixed", "--apply"]) == 0
    assert not _q(tmp_path).is_quarantined("thr_a")
    rec = [json.loads(x) for x in (tmp_path / CFG["receipts_rel"]).read_text().splitlines()]
    assert rec[-1]["action"] == "released" and rec[-1]["note"] == "fixed"


def test_disabled_and_dry_run_are_inert(tmp_path, sent):
    q = PQ.Quarantine("lane", CFG, tmp_path)
    assert CFG["enabled"] is False
    for _ in range(5):
        assert q.record_run(_h({"x": True}), reasons={"x": DET}) == []
    assert q.save() == [] and not q.is_quarantined("x") and list(tmp_path.iterdir()) == []
    d = PQ.Quarantine("lane", {**CFG, "enabled": True}, tmp_path, dry_run=True)
    for _ in range(3):
        d.record_run({"x": True}, reasons={"x": DET})
    assert d.save() == [] and list(tmp_path.iterdir()) == [] and sent == []


def test_send_failure_is_returned(tmp_path, monkeypatch):
    mod = types.ModuleType("telegram_alert")
    mod.send_telegram = lambda message, **kw: False
    monkeypatch.setitem(sys.modules, "telegram_alert", mod)
    q = _q(tmp_path, threshold=1)
    q.record_run(_h({"x": True}), reasons={"x": DET})
    assert q.save() == ["send_telegram returned falsy"]


# ---------------------------------------------------------------- end to end: the real Ask-the-CIO lifecycle
def _boom(_):
    raise ValueError("fact rejected")


def test_lifecycle_quarantines_the_poison_thread_and_runs_on(tmp_path, monkeypatch, sent):
    import test_cio_ask_hourly_20261026 as H

    state = tmp_path / "state"
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    monkeypatch.setattr(PQ, "load_config", lambda path=None: {**CFG, "enabled": True, "max_share": 1.0})
    d = H.fixture(tmp_path)
    results = [H.run(d, collect=_boom, now=H.NOW + timedelta(hours=i)) for i in range(4)]
    assert [r["ok"] for r in results[:2]] == [False, False]  # failing, not yet poison
    assert results[2].get("quarantined_now") == [H.TID] and results[2]["ok"] is True  # third: quarantined, lane ok
    assert results[3].get("quarantined_skipped") == [H.TID] and results[3]["ok"] is True  # then skipped
    assert len(sent) == 1 and H.TID in sent[0]["message"]


def test_lifecycle_outage_is_never_poison(tmp_path, monkeypatch, sent):
    import test_cio_ask_hourly_20261026 as H

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setattr(PQ, "load_config", lambda path=None: {**CFG, "enabled": True, "max_share": 1.0})
    d = H.fixture(tmp_path)
    refused = lambda _: {"source_runs": [{"source": "web", "status": "refused", "reason": "SEARCH_CAP"}]}  # noqa: E731
    results = [H.run(d, collect=refused, now=H.NOW + timedelta(hours=i)) for i in range(4)]
    assert not results[0]["ok"]  # the outage stays visible as a failing run
    assert not any(r.get("quarantined_now") for r in results) and sent == []


def test_lifecycle_corrupt_store_fails_the_run_loudly(tmp_path, monkeypatch):
    import test_cio_ask_hourly_20261026 as H

    state = tmp_path / "state"
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    monkeypatch.setattr(PQ, "load_config", lambda path=None: {**CFG, "enabled": True})
    p = state / CFG["store_dir_rel"] / "cio-ask-lifecycle.json"
    p.parent.mkdir(parents=True)
    p.write_text("{half")
    r = H.run(H.fixture(tmp_path))
    assert r["ok"] is False and any(e.startswith("quarantine_store:") for e in r["source_errors"])


# ---------------------------------------------------------------- review round 2 (2026-10-31)
@pytest.mark.parametrize(
    "reason",
    [
        "OSError: [Errno 5]",
        "httpx.ConnectError",
        "socket.gaierror",
        "ssl.SSLError",
        "JSONDecodeError: Expecting value",
        "BrokenPipeError",
        "RemoteProtocolError",
        "anthropic.APIStatusError: 529",
        None,
        "",
        "SomethingNew",
    ],
)
def test_unknown_or_outage_reasons_never_count(reason):
    assert PQ.counts_as_poison(reason, CFG) is False


def test_known_deterministic_reasons_count_unless_transient():
    assert PQ.counts_as_poison("CHECK_FAILED:ValueError: fact rejected", CFG)
    assert PQ.counts_as_poison("KeyError: 'symbol'", CFG)
    assert not PQ.counts_as_poison("CHECK_FAILED:ValueError:SOURCE_CHECK_INCOMPLETE", CFG)  # transient wins


def test_single_item_lane_never_quarantines_its_only_item(tmp_path, sent):
    q = _q(tmp_path)
    for _ in range(4):
        assert q.record_run({"thr_only": True}, reasons={"thr_only": DET}) == []
    assert q.systemic == {"failing": 1, "items": 1}
