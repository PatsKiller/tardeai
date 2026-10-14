"""Notification intents, wave 2 (SND2, 2026-10-11; AGENTS.md §24.1 and §9.1 5.1.0).

Wave 1 (#1685, tests/test_notification_intents_20261010.py) moved the ``bypass_router=True`` senders. Wave 2
moves the 40 highest-volume NON-broker senders that called the notifier with no priority -- so the text
classifier guessed, from wording, whether the operator's phone buzzed. Each now declares an intent:

  P1  operator-action (dedupe off) or time-critical: delivered now, never capped or quiet-held.
  P2  reports and operator-attention findings: delivered now, held 22:00-07:00 ET for the digest.
  P3  FYI: never an interrupt. Archived (``notification_intent_p3:<producer>``) and folded by the digest --
      what the classifier's DIGEST verdict gave most of these producers, now declared. An archive that
      cannot be written is delivered instead: never dropped.

Every send here is captured at the transport (``alarm_capture``); nothing reaches Telegram, no .env is read
(the worktree and CI have none), and durable state is redirected to tmp. The gates at the bottom are
shrink-only: undeclared sends (scripts/check_notification_intents.py) and the Telegram/provider chokepoint
baselines can only go down.
"""
from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts" / "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import telegram_alert as TA  # noqa: E402
import telegram_alert_router as TR  # noqa: E402

import check_notification_intents as CNI  # noqa: E402

# Captured at collection, before any test runs: some older tests assign telegram_alert.send_telegram = <lambda>
# without restoring it (e.g. tests/test_m5_guardrails_20260923.py), which would leak into these in a full run.
_REAL_TA = {n: getattr(TA, n) for n in ("send_telegram", "send_telegram_with_id", "send_telegram_document",
                                        "publish_operator_message", "_legacy_send", "_intent_send")}
_REAL_TR = {n: getattr(TR, n) for n in ("route_intent", "intent_archive_report_type", "record_intent_receipt",
                                        "mark_intent_sent")}


@pytest.fixture
def no_psycopg2(monkeypatch):
    """Stub psycopg2 when it is not installed (CI has no DB driver).

    These senders import psycopg2 at module scope for their DB work; the notifier functions under test never
    connect. A stub that raises on connect keeps the test from silently touching a database, and leaves a host
    with the real driver untouched.
    """
    try:
        import psycopg2  # noqa: F401
        import psycopg2.extras  # noqa: F401
        return
    except ImportError:
        pass
    import types

    def _no_db(*_a, **_k):
        raise RuntimeError("psycopg2 stub: tests must not connect to a database")

    pg = types.ModuleType("psycopg2")
    pg.connect = _no_db
    pg.Error = pg.OperationalError = pg.DatabaseError = Exception
    extras = types.ModuleType("psycopg2.extras")
    extras.RealDictCursor = extras.DictCursor = object
    extras.execute_values = extras.execute_batch = _no_db
    pg.extras = extras
    monkeypatch.setitem(sys.modules, "psycopg2", pg)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", extras)


@pytest.fixture
def intents(alarm_capture, monkeypatch, tmp_path):
    """Transport stubbed, durable state in tmp, legacy runtime mode, no gateway, no comms-ledger writes."""
    for n, f in _REAL_TA.items():
        monkeypatch.setattr(TA, n, f)
    for n, f in _REAL_TR.items():
        monkeypatch.setattr(TR, n, f)
    monkeypatch.setenv(TR.INTENT_RECEIPTS_ENV, str(tmp_path / "intent_receipts.jsonl"))
    monkeypatch.setenv("CIO_OUTBOUND_DEDUPE_PATH", str(tmp_path / "dedupe.jsonl"))
    monkeypatch.setattr(TR, "_intent_sent", {})
    monkeypatch.setattr(TR, "_durable_recently_sent", lambda key, ttl: False)
    monkeypatch.setattr(TR, "durable_mark_sent", lambda key, meta=None: None)
    import alert_runtime_mode
    monkeypatch.setattr(alert_runtime_mode, "get_mode", lambda **k: alert_runtime_mode.MODE_OFF)
    monkeypatch.setattr(TA, "_comms_gateway_owns", lambda mc: False)
    monkeypatch.setattr(TA, "_best_effort_comms_publish", lambda *a, **k: None)
    for modname in ("lib.comms", "scripts.lib.comms"):
        try:
            mod = __import__(modname, fromlist=["publish_communication"])
            monkeypatch.setattr(mod, "publish_communication", lambda *a, **k: None, raising=False)
        except ImportError:
            pass
    archived: list[dict] = []
    import report_capture
    monkeypatch.setattr(report_capture, "archive_message",
                        lambda message, suppressed=False, reason="", report_type=None:
                        archived.append({"message": message, "report_type": report_type, "reason": reason})
                        or report_type)
    routes: list[dict] = []
    real_route = _REAL_TR["route_intent"]

    def _spy(message, priority, **kw):
        r = real_route(message, priority, **kw)
        routes.append(r)
        return r

    monkeypatch.setattr(TR, "route_intent", _spy)
    monkeypatch.setattr(TR, "intent_in_quiet_hours", lambda now=None: False)
    alarm_capture.archived = archived
    alarm_capture.routes = routes
    alarm_capture.receipts = lambda: [json.loads(line) for line in
                                      (tmp_path / "intent_receipts.jsonl").read_text().splitlines() if line]
    return alarm_capture


def _pp(intents):
    return [(r["priority"], r["producer"]) for r in intents.routes]


# ── P3: FYI goes to the digest, never to the phone, never dropped ──────────────────────────────────────────

def test_p3_routes_to_the_digest_without_consulting_the_classifier():
    r = TR.route_intent("cron-self-heal probe", "P3", producer="cron_self_heal")
    assert r["decision"] == "DIGEST" and r["deliver"] is False
    assert TR.intent_archive_report_type(r) == "notification_intent_p3:cron_self_heal"
    assert TR.intent_archive_report_type({**r, "producer": None}) == TR.DIGEST_P3_REPORT_TYPE


def test_p3_is_archived_not_sent_and_receipted(intents, monkeypatch):
    monkeypatch.setattr(TR, "should_send_telegram", lambda *a, **k: pytest.fail("classifier consulted"))
    assert TA.send_telegram("🛠️ cron-self-heal: probe", priority="P3", producer="cron_self_heal") is True
    assert not intents.fired, "a P3 must never reach the phone"
    assert intents.archived == [{"message": "🛠️ cron-self-heal: probe",
                                 "report_type": "notification_intent_p3:cron_self_heal",
                                 "reason": "intent_p3_digest"}]
    rec = intents.receipts()[-1]
    assert rec["decision"] == "DIGEST" and rec["delivered"] is False
    assert rec["archived_report_type"] == "notification_intent_p3:cron_self_heal"


def test_p3_that_cannot_be_archived_is_delivered_not_dropped(intents, monkeypatch):
    import report_capture
    monkeypatch.setattr(report_capture, "archive_message", lambda *a, **k: None)
    assert TA.send_telegram("FYI probe that cannot be archived", priority="P3") is True
    intents.assert_fired(contains="cannot be archived")
    assert intents.receipts()[-1]["decision"] == "HOLD_UNPERSISTED_DELIVERED"


def test_p3_ignores_the_quiet_window_and_still_never_interrupts(intents, monkeypatch):
    monkeypatch.setattr(TR, "intent_in_quiet_hours", lambda now=None: True)
    TA.send_telegram("night FYI probe", priority="P3", producer="t")
    assert not intents.fired and intents.archived[-1]["report_type"] == "notification_intent_p3:t"


def test_p3_document_caption_is_archived_with_the_file_path(intents, tmp_path):
    doc = tmp_path / "fyi.pdf"
    doc.write_bytes(b"%PDF-1.4 probe")
    assert TA.send_telegram_document(str(doc), caption="FYI doc probe", priority="P3") is True
    assert not intents.documents
    assert str(doc) in intents.archived[-1]["message"]


def test_p3_with_send_with_id_has_no_message_id(intents):
    r = TA.send_telegram_with_id("FYI id probe", priority="P3")
    assert r["accepted"] is True and r["message_id"] is None   # nothing on the phone to acknowledge


def test_p3_is_folded_by_the_digest_reader():
    """The digest groups the Reports archive by report_type, so a P3 shows as its own producer line."""
    import p1_digest_sender as p1
    rows = [(1, None, "notification_intent_p3:cron_self_heal", "🛠️ cron-self-heal: a", "b"),
            (2, None, "notification_intent_p3:cron_self_heal", "🛠️ cron-self-heal: c", "d"),
            (3, None, "notification_intent_p3:rotation_autopilot", "📉 rotation faded", "e")]
    text = p1.render({"rows": rows, "since_hours": 6})
    plain = text.replace("\\_", "_")          # the digest escapes Markdown underscores
    assert "notification_intent_p3:cron_self_heal ×2" in plain and "rotation_autopilot ×1" in plain


def test_invalid_priority_is_still_refused():
    with pytest.raises(ValueError):
        TR.route_intent("x", "P4")


# ── per-module: each migrated sender reaches the router with its declared priority ────────────────────────

def test_process_watchlist_escalation_routes_are_declared_statically():
    src = (ROOT / "scripts/process_watchlist_agent_jobs.py").read_text(encoding="utf-8")
    assert 'priority="P2", producer="process_watchlist_agent_jobs"' in src
    assert 'priority="P3", producer="process_watchlist_agent_jobs"' in src


# claude_escalation_handler is checked statically only: importing it resolves get_live_project_root() and
# load_dotenv()s the LIVE release's .env into the test process (AGENTS.md §24.6/§24.7). Never import it here.


def test_system_health_agent_critical_is_p1_warn_is_p3(intents):
    import system_health_agent as m
    m._send_alert("🚨 SYSTEM HEALTH: probe — dead", urgent=True)
    m._send_alert("⚠️ SYSTEM HEALTH: probe — stale", urgent=False)
    assert _pp(intents) == [("P1", "system_health_agent"), ("P3", "system_health_agent")]
    assert [t["text"] for t in intents.transport] == ["🚨 SYSTEM HEALTH: probe — dead"]


def test_siem_critical_notify_is_p1(intents):
    import siem_critical_notify as m
    assert m._send("🚨 SIEM P0: probe") is True
    assert _pp(intents) == [("P1", "siem_critical_notify")]
    intents.assert_fired(contains="SIEM P0: probe")


def test_system_freshness_monitor_is_p1(intents):
    import system_freshness_monitor as m
    assert m.telegram("SYSTEM FRESHNESS — silent-failure alert: probe") == ["send_telegram:ok"]
    assert _pp(intents) == [("P1", "system_freshness_monitor")]


def test_freshness_watchdog_heartbeat_is_p1(intents):
    import freshness_watchdog_heartbeat as m
    m.telegram("WATCHDOG DOWN (P0):\n- probe")
    assert _pp(intents) == [("P1", "freshness_watchdog_heartbeat")]
    intents.assert_fired(contains="WATCHDOG DOWN")


def test_agent_event_router_defaults_p3_and_urgent_is_p1(intents):
    import agent_event_router as m
    m._send_telegram("Intelligence Gap Filled: PROBE")
    m._send_telegram("🚨 EARNINGS_SURPRISE — PROBE", priority="P1")
    assert _pp(intents) == [("P3", "agent_event_router"), ("P1", "agent_event_router")]
    assert [t["text"] for t in intents.transport] == ["🚨 EARNINGS_SURPRISE — PROBE"]


def test_hermes_score_alerts_is_p3(intents):
    import hermes_score_alerts as m
    m._telegram("🔭 Hermes watchlist alerts:\nprobe")
    assert _pp(intents) == [("P3", "hermes_score_alerts")] and not intents.fired


def test_incubator_pipeline_failure_is_p2(no_psycopg2, intents):
    import incubator_proposal_promoter as m
    m._send_pipeline_alert("❌ Incubator pipeline failure probe")
    assert _pp(intents) == [("P2", "incubator_proposal_promoter")]


def test_social_scalp_wait_is_p2(no_psycopg2, intents, monkeypatch):
    import social_scalp_scanner as m
    # Bound at import (`from telegram_alert import send_telegram`); other tests rebind it -- use the notifier.
    monkeypatch.setattr(m, "send_telegram", _REAL_TA["send_telegram"])
    m._send_wait_alert("PRB", 30, {"rvol": 1.2, "price": 3.5}, 4)
    assert _pp(intents) == [("P2", "social_scalp_scanner")]
    intents.assert_fired(contains="WAIT *PRB*")


def test_pipeline_watchdog_urgent_is_p1_else_p3(no_psycopg2, intents):
    import pipeline_watchdog as m
    m.send_telegram("CRITICAL: probe failed 3x. Manual check needed.", urgent=True)
    m.send_telegram("PRB GO 80pts for 2.0hr with 0 analyses. Queued.")
    assert _pp(intents) == [("P1", "pipeline_watchdog"), ("P3", "pipeline_watchdog")]
    assert len(intents.transport) == 1


def test_portfolio_live_monitor_priority_reaches_the_router(intents, tmp_path):
    import portfolio_live_monitor as m
    # root=tmp_path: _load_env_file finds no .env there, so nothing is read.
    assert m._send_telegram("🔔 PRB down 4% probe", tmp_path, priority="P1")
    m._send_telegram("☀️ morning brief probe", tmp_path)
    assert _pp(intents) == [("P1", "portfolio_live_monitor"), ("P2", "portfolio_live_monitor")]


def test_iris_library_messages_are_p3(intents):
    import iris_taxonomy_agent as m
    m._send_telegram_msg("Iris Weekly Content Recommendations probe")
    assert _pp(intents) == [("P3", "iris_taxonomy_agent")] and not intents.fired


def test_research_lane_health_is_p3(intents):
    import research_lane_health as m
    assert m._deliver_telegram("⚠️ *Research lane RAW-store health* probe") is None
    assert _pp(intents) == [("P3", "research_lane_health")] and not intents.fired


def test_cio_bridge_watchdog_is_p1(intents, tmp_path):
    import cio_bridge_watchdog as m
    receipt = m.run_once(
        apply=True, state_path=tmp_path / "wd.json",
        prober=lambda: {"answered": True, "http": 200,
                        "body": {"circuit_open": True, "last_error": "provider_failure:Probe"}},
        restarter=lambda: pytest.fail("a provider failure is never restarted"),
    )
    assert receipt["status"] == m.CIRCUIT_OPEN
    assert _pp(intents) == [("P1", "cio_bridge_watchdog")]
    intents.assert_fired(contains="circuit open")


def test_material_change_page_is_p1_digest_is_p2_both_dedupe_off(intents, monkeypatch):
    import notify_material_change as m
    monkeypatch.setattr(m, "gateway_notice_enabled", lambda: False)
    monkeypatch.setattr(m, "_held_chunks", lambda: [])
    assert m.deliver_notice("MATERIAL CHANGE — PRB probe", subject_key="k1")[0] is True
    assert m.deliver_notice("📋 Material change — daily digest probe", subject_key="k2", priority="P2")[0]
    assert _pp(intents) == [("P1", "notify_material_change"), ("P2", "notify_material_change")]
    assert {r["window_minutes"] for r in intents.routes} == {0}


# ── the migration contract (static) ───────────────────────────────────────────────────────────────────────

# Each migrated sender file -> the priorities its send calls may declare. Rule (SND2 brief, AGENTS §9.1/§24.1):
# operator-action -> P1 dedupe 0; time-critical -> P1; reports / operator-attention -> P2; FYI -> P3 digest.
MIGRATED_WAVE2 = {
    "scripts/process_reaper.py": {"P3"},
    "scripts/cio_bridge_watchdog.py": {"P1"},
    "scripts/send_telegram_proposal_alert.py": {"P1"},            # operator-action, dedupe 0
    "scripts/claude_escalation_handler.py": {"P3"},
    "scripts/system_health_agent.py": {"P1", "P3"},
    "scripts/health_agent.py": {"P1", "P3"},
    "scripts/notify_material_change.py": {"P1", "P2"},
    "scripts/research_lane_health.py": {"P3"},
    "scripts/siem_critical_notify.py": {"P1"},
    "scripts/system_freshness_monitor.py": {"P1"},
    "scripts/run_proactive_quote_refresh.py": {"P3"},
    "scripts/agent_event_router.py": {"P1", "P3"},
    "scripts/check_gap_resolution.py": {"P2"},
    "scripts/check_operator_answer_quality.py": {"P2"},
    "scripts/freshness_watchdog_heartbeat.py": {"P1"},
    "scripts/hermes_score_alerts.py": {"P3"},
    "scripts/oauth_lane_keepalive.py": {"P1", "P2"},  # >2h in session is P1 (operator 2026-10-11)
    "scripts/process_watchlist_agent_jobs.py": {"P2", "P3"},
    "scripts/cron_self_heal.py": {"P3"},
    "scripts/rotation_autopilot.py": {"P3"},
    "scripts/check_data_source_health.py": {"P2"},
    "scripts/check_expected_services.py": {"P2"},
    "scripts/check_llm_provider_health.py": {"P2"},
    "scripts/check_served_copy_split.py": {"P2"},
    "scripts/portfolio_live_monitor.py": {"P1", "P2"},
    "scripts/hermes_discovery_ingestors.py": {"P2"},
    "scripts/pipeline_watchdog.py": {"P1", "P3"},
    "scripts/trade_ai_news_monitor.py": {"P2"},
    "scripts/watch_directives_service.py": {"P3"},
    "scripts/premarket_watcher.py": {"P2"},
    "scripts/incubator_proposal_promoter.py": {"P1", "P2"},       # proposal card is operator-action, dedupe 0
    "scripts/social_scalp_scanner.py": {"P1", "P2"},
    "scripts/pullback_macd_screener.py": {"P2"},
    "scripts/portfolio_orchestrator.py": {"P1", "P2", "P3"},
    "scripts/finviz_health_check.py": {"P2"},
    "scripts/trade_ai_orchestrator.py": {"P2"},
    "scripts/iris_taxonomy_agent.py": {"P1", "P3"},               # discovery asks to approve: dedupe 0
    "scripts/pipeline_freshness_slo.py": {"P2"},
    "scripts/research_intelligence_queue.py": {"P3"},
    "scripts/send_no_leads_diagnostic_alert.py": {"P2"},
}

# Operator-action sends: P1 with dedupe off (AGENTS.md §9.1, 5.1.0).
OPERATOR_ACTION_DEDUPE_OFF = {
    "scripts/send_telegram_proposal_alert.py", "scripts/incubator_proposal_promoter.py",
    "scripts/iris_taxonomy_agent.py", "scripts/notify_material_change.py",
}


def test_zero_go_and_proposals_are_outcomes_not_producer_liveness(monkeypatch):
    import importlib.util
    import sys
    import types
    path = ROOT / "scripts/pipeline_freshness_slo.py"
    spec = importlib.util.spec_from_file_location("_isolated_freshness_outcomes", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    class Cursor:
        def execute(self, sql):
            self.sql = sql
        def fetchone(self):
            return [100 if "percentile_cont" in self.sql else 0]
    connection = types.SimpleNamespace(cursor=lambda: Cursor())
    adapter = types.ModuleType("db_adapter")
    adapter._get_conn = lambda: connection
    monkeypatch.setitem(sys.modules, "db_adapter", adapter)
    monkeypatch.setattr(module, "_market_open", lambda: False)
    result = module.run(telegram=False)
    for name in ("go_decisions_24h", "proposals_48h"):
        row = next(r for r in result["checks"] if r["check"] == name)
        assert row["recent"] == 0 and row["status"] == "OUTCOME_OBSERVED; PRODUCER_LIVENESS_NOT_MEASURED"
        assert not any(name in finding for finding in result["findings"])

# The broker execution file set and order/stop files are out of scope without an execution-engineering grant.
_BROKER_PREFIXES = ("scripts/brokers/", "scripts/active_trader/", "scripts/moomoo/")


def test_wave2_is_forty_non_broker_senders():
    assert len(MIGRATED_WAVE2) == 40
    for rel in MIGRATED_WAVE2:
        assert not rel.startswith(_BROKER_PREFIXES), rel
        name = Path(rel).name
        assert not any(w in name for w in ("order", "stop", "execut", "broker", "alpaca", "schwab")), rel


def _declared_priorities(tree: ast.AST) -> set[str]:
    """Priority literals the file declares: any ``priority=`` keyword value, and any ``priority`` parameter default."""
    exprs = [k.value for n in ast.walk(tree) if isinstance(n, ast.Call) for k in n.keywords if k.arg == "priority"]
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = n.args
            pos = a.posonlyargs + a.args
            for arg, default in zip(pos[len(pos) - len(a.defaults):], a.defaults):
                if arg.arg == "priority":
                    exprs.append(default)
            for arg, default in zip(a.kwonlyargs, a.kw_defaults):
                if arg.arg == "priority" and default is not None:
                    exprs.append(default)
    return {c.value for e in exprs for c in ast.walk(e)
            if isinstance(c, ast.Constant) and isinstance(c.value, str) and c.value in ("P1", "P2", "P3")}


@pytest.mark.parametrize("rel,allowed", sorted(MIGRATED_WAVE2.items()))
def test_migrated_sender_declares_every_send(rel, allowed):
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    calls = CNI.notifier_calls(tree)
    assert calls, f"{rel}: no notifier call found -- the detector lost it"
    undeclared = [(ln, fn) for ln, fn, declared, _ in calls if not declared]
    assert not undeclared, f"{rel}: undeclared notifier sends {undeclared}"
    assert not [ln for ln, _, _, bypass in calls if bypass], f"{rel} bypasses the router"
    used = _declared_priorities(tree)
    assert used and used <= allowed, (rel, used, allowed)
    if rel in OPERATOR_ACTION_DEDUPE_OFF:
        assert "dedupe_minutes=0" in (ROOT / rel).read_text(encoding="utf-8"), rel


# ── the gates: shrink-only ────────────────────────────────────────────────────────────────────────────────

def test_intent_ratchet_holds_on_this_tree():
    measured = CNI.measure()
    base = CNI._load_baseline()
    assert CNI.compare(measured, base) == []
    assert sum(base.values()) == json.loads(CNI.BASELINE.read_text())["total"]
    for rel in MIGRATED_WAVE2:
        assert rel not in base, f"{rel} migrated but still in the undeclared baseline"


def test_intent_ratchet_detects_each_spelling():
    """Mutation check: the detector must see every alias the producers use, and priority=None is undeclared."""
    for src in ("from telegram_alert import send_telegram\nsend_telegram(m)",
                "from telegram_alert import send_telegram as _tg\n_tg(m)",
                "import telegram_alert as _ta\n_ta.send_telegram(m)",
                "from scripts import telegram_alert\ntelegram_alert.send_telegram_with_id(m)",
                "from telegram_alert import send_telegram\nsend_telegram(m, priority=None)"):
        calls = CNI.notifier_calls(ast.parse(src))
        assert len(calls) == 1 and calls[0][2] is False and calls[0][3] is False, src
    for src in ("from telegram_alert import send_telegram\nsend_telegram(m, priority='P3')",
                "from telegram_alert import send_telegram\nsend_telegram(m, priority=p)"):
        assert CNI.notifier_calls(ast.parse(src))[0][2] is True, src
    # a bypass is counted by the bypass gate (test_notification_intents_20261010), not here
    doc = CNI.notifier_calls(ast.parse("from telegram_alert import send_telegram_document\nsend_telegram_document(p)"))
    assert doc[0][3] is True


def test_intent_ratchet_fails_on_new_growth_and_shrink():
    base = {"scripts/a.py": 2}
    assert CNI.compare({"scripts/a.py": 2}, base) == []
    assert "NEW" in CNI.compare({"scripts/a.py": 2, "scripts/b.py": 1}, base)[0]
    assert "grew" in CNI.compare({"scripts/a.py": 3}, base)[0]
    assert "shrank" in CNI.compare({"scripts/a.py": 1}, base)[0]


def _tmp_tree(tmp_path: Path, checker: str, baseline: str, baseline_doc: dict) -> Path:
    for rel in (checker,):
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dst)
    b = tmp_path / baseline
    b.parent.mkdir(parents=True, exist_ok=True)
    b.write_text(json.dumps(baseline_doc), encoding="utf-8")
    return tmp_path / checker


def test_intent_ratchet_goes_red_and_update_refuses_growth(tmp_path):
    checker = _tmp_tree(tmp_path, "scripts/check_notification_intents.py",
                        "config/notification_intent_baseline.json", {"files": {}})
    (tmp_path / "scripts" / "_probe_sender.py").write_text(
        "from telegram_alert import send_telegram\nsend_telegram('probe')\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(checker)], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert r.returncode == 1 and "NEW undeclared send" in r.stderr
    r = subprocess.run([sys.executable, str(checker), "--update-baseline"], cwd=tmp_path,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 1 and "REFUSED" in r.stderr
    assert json.loads((tmp_path / "config/notification_intent_baseline.json").read_text()) == {"files": {}}


def test_intent_ratchet_update_lowers(tmp_path):
    checker = _tmp_tree(tmp_path, "scripts/check_notification_intents.py",
                        "config/notification_intent_baseline.json", {"files": {"scripts/_probe_sender.py": 2}})
    (tmp_path / "scripts" / "_probe_sender.py").write_text(
        "from telegram_alert import send_telegram\nsend_telegram('a')\nsend_telegram('b', priority='P3')\n",
        encoding="utf-8")
    r = subprocess.run([sys.executable, str(checker)], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert r.returncode == 1 and "shrank 2 -> 1" in r.stderr
    r = subprocess.run([sys.executable, str(checker), "--update-baseline"], cwd=tmp_path,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0
    assert json.loads((tmp_path / "config/notification_intent_baseline.json").read_text())["files"] == {
        "scripts/_probe_sender.py": 1}


@pytest.mark.parametrize("checker,baseline,doc", [
    ("scripts/check_telegram_chokepoint.py", "config/telegram_chokepoint_baseline.json",
     {"files": {"scripts/_gone.py": 1}}),
    ("scripts/check_provider_chokepoint.py", "config/provider_chokepoint_baseline.json",
     {"channels": {"slack": {"scripts/_gone.py": 1}}}),
])
def test_chokepoint_baselines_are_shrink_only(tmp_path, checker, baseline, doc):
    """A baseline entry above the measured count fails until lowered; an update never adds an entry."""
    path = _tmp_tree(tmp_path, checker, baseline, doc)
    (tmp_path / "scripts" / "_pass.py").write_text("x = 1\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(path)], cwd=tmp_path, capture_output=True, text=True, timeout=300)
    assert r.returncode == 1 and "shrank 1 -> 0" in r.stderr, r.stdout + r.stderr
    # A planted Slack webhook / Telegram endpoint must be REFUSED by --update-baseline, not recorded.
    host = "api" + "." + "telegram" + "." + "org"
    frag = "SLACK_" + "WEBHOOK_" + "URL"
    (tmp_path / "scripts" / "_probe.py").write_text(
        f"import os, requests\nrequests.post(os.environ.get('{frag}', ''), json={{}})\n"
        f"requests.post('https://{host}/bot' + os.environ['TELEGRAM_" + "BOT_TOKEN'], json={})\n",
        encoding="utf-8")
    r = subprocess.run([sys.executable, str(path), "--update-baseline"], cwd=tmp_path,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 1 and "REFUSED" in r.stderr, r.stdout + r.stderr
    assert json.loads((tmp_path / baseline).read_text()) == doc


def test_comms_enforcement_runs_the_intent_ratchet():
    import check_comms_gateway_enforcement as E
    assert ("intent", ROOT / "scripts" / "check_notification_intents.py") in E.CHECKS
