"""Operator 2026-10-16: "how do i know whats n8n did, also some scalp and active traders didn't have catalyst".

1. Provenance footer at the send chokepoint (scripts/telegram_alert.py operator_wire_text):
   "· via n8n <lane> <HH:MM>" from the executor's TRADEAI_RUN_ID, "· via cron <lane>" otherwise; never costs a
   Telegram message (chunk count unchanged, every chunk <= 4,096 UTF-16 units).
2. Every Active Trader alert carries an explicit catalyst line: Trade-AI scan catalyst -> Hermes scalp research
   through the data broker (lib.data_broker.scalp_list.get_scalp_catalyst) -> "catalyst: none found (<reason>)".

Hermetic: env passed explicitly, temp research stores, injected broker fn and fake DB cursor. No token manager,
no live store, no network, no send.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import telegram_alert as ta  # noqa: E402
from active_trader import momentum_alert_pass as mp  # noqa: E402
from active_trader import momentum_alerts as ma  # noqa: E402
from active_trader import premarket_watch as pw  # noqa: E402
from lib.data_broker import scalp_list as sl  # noqa: E402

DAY = "2026-10-16"


# ── 1. provenance footer ─────────────────────────────────────────────────────

def test_footer_names_n8n_lane_and_slot_time():
    env = {"TRADEAI_RUN_ID": "d:hermes-momentum-catalyst-scalp:live:20261016T1025", "TRADEAI_RUN_MODE": "live"}
    assert ta.provenance_footer(env) == "· via n8n hermes-momentum-catalyst-scalp 10:25"


def test_footer_marks_non_live_n8n_mode():
    env = {"TRADEAI_RUN_ID": "d:trade-ai-scalp-live:dry_run:20261016T0935"}
    assert ta.provenance_footer(env) == "· via n8n trade-ai-scalp-live dry-run 09:35"


def test_footer_cron_uses_lane_env_then_script_name_markdown_safe():
    assert ta.provenance_footer({"TRADEAI_LANE": "scalp-hot-list"}, argv0="x.py") == "· via cron scalp-hot-list"
    # underscores would open Markdown italics; the footer never carries one
    assert ta.provenance_footer({}, argv0="/p/scripts/incident_notifier.py") == "· via cron incident-notifier"
    assert ta.provenance_footer({"INVOCATION_ID": "abc"}, argv0="api_v2.py") == "· via systemd api-v2"


def test_footer_empty_for_unnamed_process():
    assert ta.provenance_footer({}, argv0="-c") == ""
    assert ta.provenance_footer({}, argv0="/usr/lib/python3/pytest/__main__.py") == ""


def test_footer_appended_once():
    out = ta.with_provenance_footer("STOP HEALTH ok", footer="· via cron stop-health-check")
    assert out == "STOP HEALTH ok\n· via cron stop-health-check"
    assert ta.with_provenance_footer(out, footer="· via cron stop-health-check") == out


def test_footer_never_pushes_a_message_over_the_limit():
    footer = "· via n8n some-lane 10:25"
    near = "x" * (ta.MAX_MSG_LEN - 5)
    assert ta.with_provenance_footer(near, footer=footer) == near  # would add a chunk -> skipped
    emoji = "🟢" * 2047  # 4,094 UTF-16 units in one chunk
    assert ta.with_provenance_footer(emoji, footer=footer) == emoji
    fits = "y" * 100
    out = ta.with_provenance_footer(fits, footer=footer)
    assert out.endswith(footer) and len(ta._smart_split(out, ta.MAX_MSG_LEN)) == 1
    for chunk in ta._smart_split(out, ta.MAX_MSG_LEN):
        assert ta._utf16_len(chunk) <= ta.TELEGRAM_UTF16_LIMIT


def test_footer_kill_switch(monkeypatch):
    monkeypatch.setenv("TELEGRAM_PROVENANCE_FOOTER", "0")
    assert ta.with_provenance_footer("hi", footer="· via cron x") == "hi"


def test_wire_text_adds_footer_outside_pytest(monkeypatch):
    """operator_wire_text is the single place the wire copy and the ledger row are made: the footer is there."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("TRADEAI_RUN_ID", "d:incident-notifier:live:20261016T1030")
    out = ta.operator_wire_text("SYSTEM INCIDENT")
    assert out.endswith("· via n8n incident-notifier 10:30")


def test_executor_exports_run_id_to_lane_env():
    """The footer depends on the executor's attempt identity; pin that the export exists."""
    src = (ROOT / "scripts" / "n8n_run_executor.py").read_text()
    assert "lane_env[RUN_ID_ENV] = run_id" in src
    from lib import lane_last_receipt as llr
    assert llr.RUN_ID_ENV == "TRADEAI_RUN_ID"


# ── 2. broker catalyst read model ────────────────────────────────────────────

def _store(tmp_path, rows):
    d = tmp_path / "data" / "hermes" / "momentum_catalysts"
    d.mkdir(parents=True)
    (d / f"{DAY}_catalysts.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return tmp_path


def test_broker_catalyst_statuses(tmp_path):
    assert sl.get_scalp_catalyst("XLAB", DAY, root=tmp_path)["status"] == "STORE_MISSING"
    root = _store(tmp_path, [
        {"symbol": "XLAB", "research_timestamp": "2026-10-16T06:25:00-04:00", "catalyst_type": "no_clear_catalyst",
         "catalyst_summary": "No clear catalyst found"},
        {"symbol": "XLAB", "research_timestamp": "2026-10-16T10:25:00-04:00", "catalyst_type": "contract",
         "catalyst_summary": "XLAB wins contract", "confidence": 0.6, "source_count": 3},
        {"symbol": "AZIO", "research_timestamp": "2026-10-16T10:25:00-04:00", "catalyst_type": "no_clear_catalyst"},
    ])
    x = sl.get_scalp_catalyst("xlab", DAY, root=root)
    assert x["status"] == "FOUND" and x["summary"] == "XLAB wins contract" and x["provider_calls"] == 0
    assert sl.get_scalp_catalyst("AZIO", DAY, root=root)["status"] == "NONE_FOUND"
    assert sl.get_scalp_catalyst("IAM", DAY, root=root)["status"] == "NOT_RESEARCHED"


# ── 3. AT catalyst line ──────────────────────────────────────────────────────

def _broker(status, **kw):
    return lambda sym, day: {"symbol": sym, "status": status, **kw}


def test_catalyst_from_trade_ai_scan_first():
    t = {"decision": "GO", "setup_evidence": {"catalyst": {"text": "FDA approval", "source": "news"}}}
    line = ma.catalyst_line("ABCD", t, DAY, broker_fn=_broker("FOUND", summary="ignored"))
    assert line == "catalyst: FDA approval · news"


def test_catalyst_falls_back_to_earlier_scan_row_of_the_day():
    t = {"decision": "MANUAL_REVIEW", "setup_evidence": {"catalyst": {"text": None}},
         "day_catalyst": {"text": "Nasdaq notice", "source": "finviz"}}
    assert ma.catalyst_line("NCPL", t, DAY, broker_fn=_broker("NOT_RESEARCHED")) == "catalyst: Nasdaq notice · finviz"


def test_catalyst_from_hermes_research_via_broker():
    line = ma.catalyst_line("XLAB", None, DAY, broker_fn=_broker(
        "FOUND", summary="XLAB wins contract", catalyst_type="contract",
        researched_at="2026-10-16T10:25:00-04:00"))
    assert line == "catalyst: XLAB wins contract · Hermes contract 10:25"


@pytest.mark.parametrize("status,expect", [
    ("NONE_FOUND", "catalyst: none found (Hermes researched 10:25 — no clear catalyst)"),
    ("NOT_RESEARCHED", "catalyst: none found (not in today's Hermes scalp research; no same-day Trade-AI scan)"),
    ("STORE_MISSING", "catalyst: none found (no Hermes scalp research today; no same-day Trade-AI scan)"),
])
def test_catalyst_none_found_is_explicit(status, expect):
    assert ma.catalyst_line("IAM", None, DAY, broker_fn=_broker(
        status, researched_at="2026-10-16T10:25:00-04:00")) == expect


def test_catalyst_lookup_failure_is_explicit():
    assert ma.catalyst_line("IAM", {"decision": "WAIT"}, DAY, broker_fn=lambda s, d: None) == \
        "catalyst: none found (catalyst lookup unavailable; scan had no catalyst)"


def test_fast_loop_alert_body_always_has_a_catalyst_line(monkeypatch):
    """The 2026-10-16 IAM/SHMD/SDEV alerts came from the fast loop with no Trade-AI scan: no catalyst at all."""
    monkeypatch.setattr(ma, "_broker_catalyst", _broker("NOT_RESEARCHED"))
    c = ma.Candidate(symbol="IAM", lane="FAST", ign=0.0, fsm_state="ARMED", last=2.0, break_level=2.1,
                     source="fast", session_date=DAY)
    _title, body = ma.build_message(c, ma.APPROACHING, {"source": "moomoo", "levels": 10}, {}, {})
    lines = [ln for ln in body.splitlines() if ln.lower().startswith("catalyst:")]
    assert lines == ["catalyst: none found (not in today's Hermes scalp research; no same-day Trade-AI scan)"]


def test_transport_appendix_defers_to_the_explicit_catalyst_line():
    from lib.momentum_setup_evidence import enrich_active_trader_notification
    msg = (f"{ma.AT_SCALP_ALERT_HEADER}\n🔵 APPROACHING · IAM · about to fire\n{ma.NOT_AN_ORDER}\n"
           "catalyst: none found (not in today's Hermes scalp research; no same-day Trade-AI scan)")
    out = enrich_active_trader_notification(msg, message_class="active_trader_scalp_alert",
                                            primary_symbols=["IAM"], snapshot_loader=lambda: None)
    assert "Catalyst: UNKNOWN" not in out


def test_premarket_body_has_catalyst_line(monkeypatch):
    monkeypatch.setattr(ma, "_broker_catalyst", _broker(
        "FOUND", summary="XLAB contract", catalyst_type="contract", researched_at="2026-10-16T06:25:00-04:00"))
    feat = {"gap_pct": 12.0, "last": 1.0, "prev_close": 0.9, "pm_high": 1.1, "pm_vwap": 0.95, "pm_volume": 100000,
            "rotation_pct": 2.0, "float_mm": 5.0, "last_bar_at": "07:09", "pm_high_at": "07:01"}
    _t, body = pw.build_message("XLAB", feat, {}, {}, {}, None, day=DAY)
    assert "catalyst: XLAB contract · Hermes contract 06:25" in body.splitlines()


class _Cur:
    def __init__(self, rows):
        self.rows, self.sql = rows, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        self.sql.append((sql, params))

    def fetchall(self):
        return self.rows


class _Conn:
    def __init__(self, rows):
        self.cur = _Cur(rows)

    def cursor(self):
        return self.cur

    def rollback(self):
        pass


def test_attach_day_catalyst_only_for_symbols_without_one():
    out = {"NCPL": {"catalyst": None}, "TCRT": {"catalyst": "Velaris deal"}}
    conn = _Conn([{"symbol": "NCPL", "catalyst": "Nasdaq notice", "catalyst_source": "finviz",
                   "scanned_at": "2026-10-16T09:35:00-04:00"}])
    mp._attach_day_catalyst(conn, out, DAY)
    assert out["NCPL"]["day_catalyst"]["text"] == "Nasdaq notice"
    assert "day_catalyst" not in out["TCRT"]
    sql, params = conn.cur.sql[0]
    assert "SELECT" in sql and "INSERT" not in sql.upper() and params == (DAY, ["NCPL"])
