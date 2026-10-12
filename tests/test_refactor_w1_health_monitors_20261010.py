"""n8n refactor wave 1 — health monitors (no DB, no browser, no sender).

* hermes_pipeline_health.py (cron:L576)
* monitoring/classifier_health_check.py (cron:L222)
* youtube_cookie_health_check.py (cron:L395)
* crawl_v3_dashboard.py (cron:L526)

Each: ``--dry-run`` reaches no write / send / receipt (the writers are patched to raise and asserted
uncalled); a real run leaves a durable receipt with ok_at only on success; findings exit 0 and a
failed check exits non-zero.
"""

from __future__ import annotations

import inspect
import io
import json
import runpy
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# Required CI has no psycopg2 (these tests use fake connections only). Install a minimal stand-in ONLY when the real
# driver is absent, so the dry-run safety tests still run in CI instead of being skipped by importorskip.
try:  # pragma: no cover - depends on the environment
    import psycopg2  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    import types as _types

    _pg = _types.ModuleType("psycopg2")
    _pg_extras = _types.ModuleType("psycopg2.extras")
    _pg_extras.RealDictCursor = object
    _pg.extras = _pg_extras

    def _no_connect(*_a, **_k):
        raise RuntimeError("psycopg2 stub: tests must use fake connections")

    _pg.connect = _no_connect
    _pg.Error = Exception
    _pg.OperationalError = Exception
    sys.modules.setdefault("psycopg2", _pg)
    sys.modules.setdefault("psycopg2.extras", _pg_extras)


def _load(rel: str, key: str):
    import importlib.util

    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


def _boom(*_a, **_k):
    raise AssertionError("a dry run reached a write/send")


def _dry_report(out: str) -> dict:
    line = next(ln for ln in out.splitlines() if ln.startswith("DRY-RUN "))
    return json.loads(line[len("DRY-RUN ") :])


@pytest.fixture
def state_root(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    return tmp_path / "state"


# ── hermes_pipeline_health ───────────────────────────────────────────────────

H = _load("scripts/hermes_pipeline_health.py", "_tested_refactor_w1_hermes_health")
ISSUES = ["promotion precision 611/3382 (18%) over 30d graded — promotion gates not filtering"]


def _fake_db(monkeypatch, result=True):
    calls = []

    def _execute(sql, params=None, fetch=None):
        calls.append(" ".join(sql.split())[:40])
        return result

    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_execute=_execute))
    return calls


def _fake_dispatcher(monkeypatch, fn):
    monkeypatch.setitem(sys.modules, "alert_dispatcher_unified", types.SimpleNamespace(dispatch=fn))


@pytest.fixture
def hermes_dedup_hour(monkeypatch):
    """The producer formats its hourly dedup key with date; tests must never spawn that shell."""
    calls = []

    def fixture_clock(command):
        assert command == "date +%Y%m%d%H", "unexpected shell formatter in Hermes test"
        calls.append(command)
        return io.StringIO("2026101012\n")

    monkeypatch.setattr(H.os, "popen", fixture_clock)
    return calls


def test_hermes_dry_run_with_send_writes_and_sends_nothing(monkeypatch, state_root, capsys):
    monkeypatch.setattr(H, "check", lambda: list(ISSUES))
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_execute=_boom))
    _fake_dispatcher(monkeypatch, _boom)
    assert H.main(["--send", "--dry-run"]) == 0
    rep = _dry_report(capsys.readouterr().out)
    assert rep["lane_id"] == "hermes-pipeline-health" and rep["summary"]["issues"] == 1
    assert any("alert_events" in w for w in rep["would_write"]) and any("send" in w for w in rep["would_write"])
    assert not state_root.exists()


def test_hermes_dry_run_returns_before_first_insert_in_source():
    src = inspect.getsource(H.main)
    assert src.index("if a.dry_run:\n        # Returns before") < src.index("INSERT INTO alert_events")
    assert src.index("if a.dry_run:\n        # Returns before") < src.index("ad.dispatch(")


def test_hermes_findings_are_recorded_and_exit_zero(monkeypatch, state_root, hermes_dedup_hour):
    monkeypatch.setattr(H, "check", lambda: list(ISSUES))
    calls = _fake_db(monkeypatch)
    _fake_dispatcher(monkeypatch, _boom)  # no --send: never dispatched
    assert H.main([]) == 0
    assert hermes_dedup_hour == ["date +%Y%m%d%H"]
    assert [c.split(" (")[0] for c in calls] == ["INSERT INTO alert_events", "INSERT INTO escalation_queue"]
    doc = json.loads((state_root / "data/runtime/hermes-pipeline-health_last.json").read_text())
    assert doc["status"] == "ok" and doc["ok_at"] and doc["summary"]["issues"] == 1


def test_hermes_send_flag_still_dispatches_on_real_run(monkeypatch, state_root, hermes_dedup_hour):
    monkeypatch.setattr(H, "check", lambda: list(ISSUES))
    _fake_db(monkeypatch)
    sent = []
    _fake_dispatcher(monkeypatch, lambda **kw: sent.append(kw))
    assert H.main(["--send"]) == 0
    assert hermes_dedup_hour == ["date +%Y%m%d%H"]
    assert sent and sent[0]["source"] == "hermes_pipeline_health"


def test_hermes_unrecorded_findings_and_check_failure_exit_one(monkeypatch, state_root, hermes_dedup_hour):
    monkeypatch.setattr(H, "check", lambda: list(ISSUES))
    _fake_db(monkeypatch, result=None)  # db_adapter._execute returns None on SQL error
    assert H.main([]) == 1
    assert hermes_dedup_hour == ["date +%Y%m%d%H"]
    path = state_root / "data/runtime/hermes-pipeline-health_last.json"
    doc = json.loads(path.read_text())
    assert doc["status"] == "failed" and doc["ok_at"] is None and doc["summary"]["record_errors"]

    def broken():
        raise ConnectionError("no db")

    monkeypatch.setattr(H, "check", broken)
    assert H.main([]) == 1
    assert hermes_dedup_hour == ["date +%Y%m%d%H"]  # failed check reaches no formatter
    assert json.loads(path.read_text())["status"] == "failed"


def test_hermes_healthy_run_leaves_a_receipt(monkeypatch, state_root):
    monkeypatch.setattr(H, "check", lambda: [])
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_execute=_boom))
    assert H.main([]) == 0
    doc = json.loads((state_root / "data/runtime/hermes-pipeline-health_last.json").read_text())
    assert doc["status"] == "ok" and doc["summary"]["issues"] == 0


# ── classifier_health_check ──────────────────────────────────────────────────

C = _load("scripts/monitoring/classifier_health_check.py", "_tested_refactor_w1_classifier_health")
REGRESSION = {
    "checked_at": "2026-10-10T11:55:01Z",
    "threshold": 3,
    "violation_count": 2,
    "max_strategies_per_ticker_1d": 6,
    "regression_detected": True,
    "top_violators": [],
}


def test_classifier_dry_run_writes_nothing(monkeypatch, state_root, capsys):
    monkeypatch.setattr(C, "check", lambda: dict(REGRESSION))
    monkeypatch.setattr(C, "write_result", _boom)
    assert C.main(["--dry-run"]) == 0
    rep = _dry_report(capsys.readouterr().out)
    assert rep["summary"]["regression_detected"] is True
    assert rep["would_write"] and rep["would_write"][0].endswith("data/monitoring/classifier_health.json")
    assert not state_root.exists()


def test_classifier_result_resolves_persistent_first(monkeypatch, tmp_path):
    persistent = tmp_path / "persistent"
    (persistent / "data" / "monitoring").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(persistent))
    monkeypatch.delenv("TRADEAI_STATE_ROOT", raising=False)  # outranks the persistent root (hermetic bootstrap sets it)
    targets = C.result_targets()
    assert targets[0] == persistent / "data/monitoring/classifier_health.json"
    assert targets[-1] == C.PROJECT_ROOT / "data/monitoring/classifier_health.json"


def test_classifier_regression_is_a_finding_exit_zero(monkeypatch, state_root, tmp_path):
    out = [tmp_path / "p/classifier_health.json", tmp_path / "c/classifier_health.json"]
    monkeypatch.setattr(C, "check", lambda: dict(REGRESSION))
    monkeypatch.setattr(C, "result_targets", lambda: out)
    assert C.main([]) == 0
    for p in out:
        assert json.loads(p.read_text())["checked_at"] == REGRESSION["checked_at"]
    doc = json.loads((state_root / "data/runtime/classifier-health-check_last.json").read_text())
    assert doc["status"] == "ok" and doc["summary"]["regression_detected"] is True


def test_classifier_check_failure_exits_one(monkeypatch, state_root):
    def broken():
        raise OSError("db down")

    monkeypatch.setattr(C, "check", broken)
    assert C.main([]) == 1
    doc = json.loads((state_root / "data/runtime/classifier-health-check_last.json").read_text())
    assert doc["status"] == "failed" and doc["exit"] == 1


def test_classifier_no_cwd_relative_write_left():
    src = (ROOT / "scripts/monitoring/classifier_health_check.py").read_text()
    assert 'open("data/monitoring' not in src and 'os.makedirs("data/monitoring"' not in src


# ── youtube_cookie_health_check ──────────────────────────────────────────────

YT = ROOT / "scripts" / "youtube_cookie_health_check.py"


@pytest.mark.parametrize("prefix", ["", "#HttpOnly_"])
def test_youtube_netscape_auth_cookie_classification_uses_synthetic_lines(prefix):
    mod = _load("scripts/youtube_cookie_health_check.py", "_tested_refactor_w1_youtube_cookie")
    lines = ["# Netscape HTTP Cookie File", "# ordinary comment with\ttabs\tSID",
             f"{prefix}.youtube.com\tTRUE\t/\tTRUE\t9999999999\tSID\tsynthetic-fixture",
             f"{prefix}.youtube.com\tTRUE\t/\tTRUE\t9999999999\tSID\tsynthetic-duplicate",
             f"{prefix}.youtube.com\tTRUE\t/\tTRUE\t9999999999\tLOGIN_INFO\tsynthetic-fixture"]
    assert mod._auth_cookie_names(lines) == {"SID", "LOGIN_INFO"}


def test_youtube_synthetic_comment_rows_are_not_auth_cookies():
    mod = _load("scripts/youtube_cookie_health_check.py", "_tested_refactor_w1_youtube_cookie")
    assert mod._auth_cookie_names(["# ordinary comment\tTRUE\t/\tTRUE\t0\tSID\tfixture",
                                  "#HttpOnly_not-a-row", "malformed", "no\tfull\trow"]) == set()


def _run_yt(monkeypatch, argv, *, sent, sent_kw=None):
    """Run the script as __main__ with fake db_adapter / telegram_alert modules."""

    def send(msg, **kw):
        # SND2 (2026-10-11): the check declares its intent (priority/producer); record both with the text.
        sent.append(msg)
        sends_kw.append(kw)
        return True

    sends_kw = sent_kw if sent_kw is not None else []
    monkeypatch.setitem(sys.modules, "telegram_alert", types.SimpleNamespace(send_telegram=send))
    # The shadow comms ledger publish after a send must not reach a real store from a test.
    monkeypatch.setitem(
        sys.modules,
        "lib.comms",
        types.SimpleNamespace(CommunicationEvent=lambda **kw: kw, publish_communication=lambda ev: None),
    )
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_execute=lambda *a, **k: None))
    monkeypatch.setattr(sys, "argv", [str(YT), *argv])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(YT), run_name="__main__")
    return exc.value.code


@pytest.fixture
def no_cookie(monkeypatch, tmp_path):
    # COOKIE resolves from the script's PROJECT_ROOT; point the check at an absent file.
    import pathlib

    real = pathlib.Path.exists
    target = str(ROOT / "config" / "youtube_cookies.txt")
    monkeypatch.setattr(pathlib.Path, "exists", lambda self: False if str(self) == target else real(self))


def test_youtube_dry_run_neither_sends_nor_writes_receipt(monkeypatch, state_root, no_cookie, capsys):
    sent: list = []
    assert _run_yt(monkeypatch, ["--dry-run"], sent=sent) == 0
    assert sent == []
    rep = _dry_report(capsys.readouterr().out)
    assert rep["summary"]["status"] == "red" and rep["summary"]["would_send"] is True
    assert rep["would_write_receipt"].endswith("data/runtime/youtube_cookie_health_check_last.json")
    assert not state_root.exists()


def test_youtube_no_send_writes_receipt_with_status_and_exit_zero(monkeypatch, state_root, no_cookie):
    sent: list = []
    assert _run_yt(monkeypatch, ["--no-send"], sent=sent) == 0
    assert sent == []
    doc = json.loads((state_root / "data/runtime/youtube_cookie_health_check_last.json").read_text())
    assert doc["schema"] == "ScheduledJobReceipt@v1" and doc["exit"] == 0 and doc["ok_at"] == doc["as_of"]
    assert doc["summary"]["status"] == "red" and doc["summary"]["sent"] is False


def test_youtube_default_still_sends_on_red(monkeypatch, state_root, no_cookie):
    sent: list = []
    kws: list = []
    assert _run_yt(monkeypatch, [], sent=sent, sent_kw=kws) == 0  # red is a finding, not a failed run
    assert len(sent) == 1 and sent[0].startswith("[RED] YouTube cookies")
    # RED must page the operator: a declared P1 intent from this producer (SND2, 2026-10-11).
    assert kws == [{"priority": "P1", "producer": "youtube_cookie_health_check"}]
    doc = json.loads((state_root / "data/runtime/youtube_cookie_health_check_last.json").read_text())
    assert doc["summary"]["sent"] is True


# ── crawl_v3_dashboard ───────────────────────────────────────────────────────

W = _load("scripts/crawl_v3_dashboard.py", "_tested_refactor_w1_crawl_v3")
CONFIRMED = {"risk": {"failed": [("risk/summary", 500)], "console": [], "pageerr": [], "stuck": False}}


@pytest.fixture
def fake_playwright(monkeypatch):
    pkg = types.ModuleType("playwright")
    sub = types.ModuleType("playwright.sync_api")
    sub.sync_playwright = object()
    monkeypatch.setitem(sys.modules, "playwright", pkg)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sub)


@pytest.fixture
def crawl_source_fixture(monkeypatch, tmp_path):
    """The Telegram crawl reads its source-root dotenv; supply an actual empty fixture before that read."""
    root = tmp_path / "crawl_source"
    (root / "scripts").mkdir(parents=True)
    (root / ".env").write_text("", encoding="utf-8")
    monkeypatch.setattr(W, "__file__", str(root / "scripts/crawl_v3_dashboard.py"))
    return root


def test_crawl_dry_run_with_telegram_sends_nothing_and_writes_nothing(
    monkeypatch, state_root, fake_playwright, tmp_path, capsys
):
    monkeypatch.setattr(W, "_crawl", lambda sp, base, shots: (dict(CONFIRMED), dict(CONFIRMED)))
    monkeypatch.setattr(W, "_send_telegram", _boom)
    shots = tmp_path / "shots"
    assert W.main(["--telegram", "--dry-run", "--screenshots", str(shots)]) == 0
    rep = _dry_report(capsys.readouterr().out)
    assert rep["summary"]["confirmed"] == 1 and rep["summary"]["confirmed_routes"] == ["risk"]
    assert not shots.exists() and not state_root.exists()


def test_crawl_findings_exit_zero_with_receipt(monkeypatch, state_root, fake_playwright, crawl_source_fixture):
    monkeypatch.setattr(W, "_crawl", lambda sp, base, shots: (dict(CONFIRMED), dict(CONFIRMED)))
    sent = []
    monkeypatch.setattr(W, "_send_telegram", lambda m: sent.append(m))
    assert W.main(["--telegram"]) == 0
    assert (crawl_source_fixture / ".env").read_text(encoding="utf-8") == ""
    assert len(sent) == 1  # sender behaviour unchanged on a real --telegram run
    doc = json.loads((state_root / "data/runtime/crawl-v3-dashboard_last.json").read_text())
    assert doc["status"] == "ok" and doc["summary"]["routes"] == len(W.ROUTES)
    assert doc["summary"]["flagged"] == 1 and doc["summary"]["confirmed"] == 1


def test_crawl_crash_exits_two_with_failed_receipt(monkeypatch, state_root, fake_playwright):
    def crash(*_a):
        raise RuntimeError("chromium OOM")

    monkeypatch.setattr(W, "_crawl", crash)
    assert W.main([]) == 2
    doc = json.loads((state_root / "data/runtime/crawl-v3-dashboard_last.json").read_text())
    assert doc["status"] == "failed" and doc["ok_at"] is None
