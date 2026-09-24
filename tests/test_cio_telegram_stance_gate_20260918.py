"""Hermetic CIO stance gate for investment-shaped Telegram (no HTTP, no live DB).

2026-09-18 audit: Buy/Accumulate could ship while CIO=AVOID (footer only).
Minimum bar: Buy+CIO Avoid → held; Buy+CIO Buy → allowed.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib.cio_telegram_stance_gate import (  # noqa: E402
    HELD_DISAGREEMENT,
    HELD_MISSING,
    check_investment_send,
)
import scripts.lib.comms_editor as ce  # noqa: E402
from datetime import datetime, timezone

NOW = datetime(2026, 9, 18, 20, 0, tzinfo=timezone.utc)


def _cio_rows(rows):
    def q(sql, params=None, fetch="all"):
        wanted = set(params[0]) if params else set()
        return [r for r in rows if r["symbol"] in wanted]
    return q


def _resolve_axti(text):
    return [{"symbol": "AXTI", "guid": "11111111-2222-3333-4444-555555555555"}] if "AXTI" in text else []


def test_buy_text_held_when_cio_says_avoid():
    v = check_investment_send(
        symbol="AXTI",
        message_text="BUY AXTI — Accumulate on weakness",
        asserted_stance="bullish",
        cio_view={"symbol": "AXTI", "action": "AVOID", "created_at": "2026-09-18T12:00:00Z"},
    )
    assert v.allow is False
    assert v.held_reason == HELD_DISAGREEMENT
    assert v.cio_action == "AVOID"


def test_buy_text_allowed_when_cio_says_buy():
    v = check_investment_send(
        symbol="AXTI",
        message_text="BUY AXTI — Accumulate on weakness",
        asserted_stance="bullish",
        cio_view={"symbol": "AXTI", "action": "BUY", "created_at": "2026-09-18T12:00:00Z"},
    )
    assert v.allow is True
    assert v.held_reason is None
    assert v.cio_action == "BUY"


def test_go_held_when_cio_decision_missing_fail_closed():
    v = check_investment_send(
        symbol="ELMT",
        message_text="✅ GO ELMT — scalp setup",
        asserted_stance="bullish",
        db_query=_cio_rows([]),
    )
    assert v.allow is False
    assert v.held_reason == HELD_MISSING


def test_hold_and_neutral_cio_rewrite_bullish_to_watch():
    """HOLD and epistemic gaps pass, with GO/BUY rewritten to WATCH."""
    for action in ("HOLD", "RESEARCH_MORE", "NEUTRAL", "HUMAN_REVIEW", "ADD_REVIEW"):
        v = check_investment_send(
            symbol="AXTI",
            message_text="Strong Buy AXTI",
            asserted_stance="bullish",
            cio_view={"symbol": "AXTI", "action": action},
        )
        assert v.allow is True, action
        assert v.held_reason is None
        assert v.effective_action == "WATCH"
        assert f"[CIO Stance: {action} — Action rewritten to WATCH]" in v.annotation_text


def test_editor_buy_vs_avoid_is_held_not_annotate_only(tmp_path):
    q = _cio_rows([{"symbol": "AXTI", "action": "AVOID", "created_at": "2026-09-18T12:00:00Z"}])
    d = ce.edit(
        "BUY AXTI — Accumulate; bullish setup",
        chat_id="1",
        now=NOW,
        ledger=ce.DuplicateLedger(tmp_path / "l.json"),
        db_query=q,
        resolve=_resolve_axti,
        editor_mode="live",
    )
    assert d.cio_disagreements and d.cio_disagreements[0]["cio_action"] == "AVOID"
    assert d.send is False
    assert d.held_reason == "cio_disagreement"
    assert "held" in d.text.lower()


def test_editor_buy_aligned_with_cio_buy_sends(tmp_path):
    q = _cio_rows([{"symbol": "AXTI", "action": "BUY", "created_at": "2026-09-18T12:00:00Z"}])
    d = ce.edit(
        "BUY AXTI — Accumulate; bullish setup",
        chat_id="1",
        now=NOW,
        ledger=ce.DuplicateLedger(tmp_path / "l.json"),
        db_query=q,
        resolve=_resolve_axti,
        editor_mode="live",
    )
    assert d.cio_disagreements == []
    assert d.send is True
    assert d.held_reason is None


def test_editor_investment_shaped_missing_cio_is_held(tmp_path):
    d = ce.edit(
        "✅ GO *AXTI* — Scalp setup",
        chat_id="1",
        now=NOW,
        ledger=ce.DuplicateLedger(tmp_path / "l.json"),
        db_query=_cio_rows([]),
        resolve=_resolve_axti,
        editor_mode="live",
    )
    assert d.send is False
    assert d.held_reason == "cio_decision_missing"


def test_screener_go_send_held_on_cio_avoid(monkeypatch):
    import screener_go_alerts as g

    item = {
        "row": {
            "symbol": "ELMT", "run_label": "0930", "scanned_at": "2026-09-18T13:31:00",
            "score": 49, "grade": "A+", "decision": "GO", "rvol": 8.2, "price": 6.4,
            "change_pct": 12.0, "gap_pct": 9.5, "float_m": 12.0, "volume": 3_400_000,
            "catalyst": "FDA", "catalyst_verified": True, "source": "screener",
        },
        "tier": "A+",
        "passed": ["price", "float", "rvol", "gap", "volume", "score", "catalyst"],
    }
    calls = []

    def fake_send(msg, **kw):
        calls.append(msg)
        return True

    q = _cio_rows([{"symbol": "ELMT", "action": "AVOID", "created_at": "2026-09-18T12:00:00Z"}])
    monkeypatch.setenv("TELEGRAM_RICH_ALERTS", "0")
    ok, reason = g._send_go(fake_send, item, db_query=q)
    assert ok is False
    assert reason == HELD_DISAGREEMENT
    assert calls == []


def test_screener_go_send_allowed_when_cio_buy_ready(monkeypatch):
    import screener_go_alerts as g

    item = {
        "row": {
            "symbol": "ELMT", "run_label": "0930", "scanned_at": "2026-09-18T13:31:00",
            "score": 49, "grade": "A+", "decision": "GO", "rvol": 8.2, "price": 6.4,
            "change_pct": 12.0, "gap_pct": 9.5, "float_m": 12.0, "volume": 3_400_000,
            "catalyst": "FDA", "catalyst_verified": True, "source": "screener",
        },
        "tier": "A+",
        "passed": ["price", "float", "rvol", "gap", "volume", "score", "catalyst"],
    }
    calls = []

    def fake_send(msg, **kw):
        calls.append(msg)
        return True

    q = _cio_rows([{"symbol": "ELMT", "action": "BUY_READY", "created_at": "2026-09-18T12:00:00Z"}])
    monkeypatch.setenv("TELEGRAM_RICH_ALERTS", "0")
    ok, reason = g._send_go(fake_send, item, db_query=q)
    assert ok is True and reason is None
    assert calls and "ELMT" in calls[0]

def test_hold_writes_durable_receipt(tmp_path, monkeypatch):
    """PARTIAL-telegram-CIO-stance closes on a durable hold receipt, not a log line."""
    import json
    from lib.cio_telegram_stance_gate import HOLD_RECEIPT_SCHEMA, check_investment_send

    receipt = tmp_path / "cio_telegram_stance_holds.jsonl"
    monkeypatch.setenv("CIO_STANCE_HOLD_RECEIPTS", str(receipt))
    v = check_investment_send(
        symbol="AXTI",
        message_text="BUY AXTI",
        asserted_stance="bullish",
        cio_view={"symbol": "AXTI", "action": "AVOID"},
        source="unit_test",
    )
    assert v.allow is False
    assert receipt.is_file()
    rows = [json.loads(line) for line in receipt.read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["schema"] == HOLD_RECEIPT_SCHEMA
    assert rows[0]["held_reason"] == HELD_DISAGREEMENT
    assert rows[0]["symbol"] == "AXTI"
    assert rows[0]["source"] == "unit_test"
    assert rows[0]["mbi_behavior"] == 0
    assert "caller" not in rows[0]


def test_organic_caller_stamps_source_check_investment_send(tmp_path, monkeypatch):
    """Live producers must prove as source=check_investment_send (ledger), caller=producer."""
    import json
    from lib.cio_telegram_stance_gate import check_investment_send

    receipt = tmp_path / "cio_telegram_stance_holds.jsonl"
    monkeypatch.setenv("CIO_STANCE_HOLD_RECEIPTS", str(receipt))
    v = check_investment_send(
        symbol="NOC",
        message_text="GO NOC",
        asserted_stance="bullish",
        cio_view={"symbol": "NOC", "action": "AVOID"},
        source="screener_go_alerts",
    )
    assert v.allow is False
    rows = [json.loads(line) for line in receipt.read_text().splitlines() if line.strip()]
    assert rows[0]["source"] == "check_investment_send"
    assert rows[0]["caller"] == "screener_go_alerts"


def test_canary_source_stays_distinct_from_organic(tmp_path, monkeypatch):
    import json
    from lib.cio_telegram_stance_gate import check_investment_send

    receipt = tmp_path / "cio_telegram_stance_holds.jsonl"
    monkeypatch.setenv("CIO_STANCE_HOLD_RECEIPTS", str(receipt))
    check_investment_send(
        symbol="NOC",
        message_text="BUY NOC",
        asserted_stance="bullish",
        cio_view={"symbol": "NOC", "action": "AVOID"},
        source="controlled_canary_current_tip",
    )
    rows = [json.loads(line) for line in receipt.read_text().splitlines() if line.strip()]
    assert rows[0]["source"] == "controlled_canary_current_tip"
    assert "caller" not in rows[0]


def test_allow_does_not_write_hold_receipt(tmp_path, monkeypatch):
    from lib.cio_telegram_stance_gate import check_investment_send

    receipt = tmp_path / "cio_telegram_stance_holds.jsonl"
    monkeypatch.setenv("CIO_STANCE_HOLD_RECEIPTS", str(receipt))
    v = check_investment_send(
        symbol="AXTI",
        message_text="BUY AXTI",
        asserted_stance="bullish",
        cio_view={"symbol": "AXTI", "action": "BUY"},
        source="unit_test",
    )
    assert v.allow is True
    assert not receipt.exists()


def test_hold_receipts_path_defaults_to_local_state(monkeypatch, tmp_path):
    """Without env pin, primary is ~/.local/state/tradeai (measurable without release-write)."""
    monkeypatch.delenv("CIO_STANCE_HOLD_RECEIPTS", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    from lib import cio_telegram_stance_gate as gate

    path = gate.hold_receipts_path()
    assert path is not None
    assert path == tmp_path / ".local/state/tradeai/cio_telegram_stance_holds.jsonl"


def test_hold_dual_write_mirrors_when_persist_parent_exists(tmp_path, monkeypatch):
    """Default path dual-writes local + persist mirror (outside pytest hold-suppress)."""
    import json
    from lib import cio_telegram_stance_gate as gate
    import scripts.lib.persistent_state_root as psr

    monkeypatch.delenv("CIO_STANCE_HOLD_RECEIPTS", raising=False)
    monkeypatch.delenv("CIO_STANCE_HOLD_RECEIPTS_DISABLE", raising=False)
    # Production persist path is suppressed under pytest unless env pins a path;
    # dual-write is the production default — exercise it with the guard cleared.
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    home = tmp_path / "home"
    (home / ".local" / "state" / "tradeai").mkdir(parents=True)
    persist_root = tmp_path / "persist"
    (persist_root / "data" / "cio").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(psr, "good_persistent_root", lambda: persist_root)

    verdict = gate.StanceGateVerdict(
        allow=False,
        held_reason=gate.HELD_DISAGREEMENT,
        symbol="AXTI",
        message_stance="bullish",
        cio_action="AVOID",
        cio_side="bearish",
    )
    wrote = gate.record_hold(verdict, source="dual_write_test")
    assert wrote is not None
    local = home / ".local" / "state" / "tradeai" / "cio_telegram_stance_holds.jsonl"
    persist = persist_root / "data" / "cio" / "cio_telegram_stance_holds.jsonl"
    assert local.is_file()
    assert persist.is_file()
    local_rows = [json.loads(L) for L in local.read_text().splitlines() if L.strip()]
    persist_rows = [json.loads(L) for L in persist.read_text().splitlines() if L.strip()]
    assert local_rows[0]["symbol"] == "AXTI"
    assert persist_rows[0]["symbol"] == "AXTI"
    assert local_rows[0]["source"] == "dual_write_test"


def test_organic_producers_pass_caller_as_source_kwarg():
    """AST guard: LIVE-cio-stance-governance OBSERVED requires these call sites stamp source=caller.

    Gap closes only when a live producer records source=check_investment_send with
    caller in ORGANIC_HOLD_CALLERS (any day Mon–Sun). A silent rename of the
    source= kwarg would leave the schedule firing and organic=0.
    """
    import ast
    from pathlib import Path

    from lib.cio_telegram_stance_gate import ORGANIC_HOLD_CALLERS

    root = Path(__file__).resolve().parents[1]
    producers = {
        "screener_go_alerts": root / "scripts" / "screener_go_alerts.py",
        "social_scalp_scanner": root / "scripts" / "social_scalp_scanner.py",
        "send_telegram_proposal_alert": root / "scripts" / "send_telegram_proposal_alert.py",
    }
    assert set(producers) == set(ORGANIC_HOLD_CALLERS)

    for caller, path in producers.items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        sources: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (
                fn.attr if isinstance(fn, ast.Attribute) else None
            )
            if name != "check_investment_send":
                continue
            for kw in node.keywords:
                if kw.arg == "source" and isinstance(kw.value, ast.Constant):
                    sources.append(str(kw.value.value))
        assert caller in sources, f"{path.name}: missing source={caller!r} (got {sources})"



def test_commodity_etf_not_auto_allowed_under_asset_agnostic_bar(monkeypatch):
    """GLD/SLV/USO are gated (24/7 asset-agnostic); broad indices may still pass-through."""
    from lib.cio_telegram_stance_gate import check_investment_send

    # Missing CIO view → hold (not auto-allow) for commodity ETF.
    v = check_investment_send(
        symbol="GLD",
        message_text="BUY GLD — Accumulate gold",
        asserted_stance="bullish",
        cio_view=None,
        source="screener_go_alerts",
    )
    assert v.allow is False
    assert v.held_reason == "cio_decision_missing"

    # Broad index context still excluded (pass-through).
    v2 = check_investment_send(
        symbol="SPY",
        message_text="BUY SPY",
        asserted_stance="bullish",
        cio_view={"action": "AVOID"},
        source="screener_go_alerts",
    )
    assert v2.allow is True


def test_summarize_includes_live_cio_stance_gap_id(tmp_path):
    import json
    from lib.cio_telegram_stance_gate import GAP_ID, summarize_stance_holds

    path = tmp_path / "holds.jsonl"
    path.write_text(
        json.dumps(
            {
                "source": "check_investment_send",
                "caller": "screener_go_alerts",
                "symbol": "LSTA",
                "held_reason": "cio_stance_conflict",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    s = summarize_stance_holds(path)
    assert s["gap_id"] == GAP_ID == "LIVE-cio-stance-governance"
    assert s["observed"] is True
    assert "24/7" in s.get("scope", "")


def test_is_organic_hold_row_requires_source_and_caller():
    from lib.cio_telegram_stance_gate import is_organic_hold_row

    assert is_organic_hold_row(
        {"source": "check_investment_send", "caller": "screener_go_alerts"}
    )
    assert not is_organic_hold_row(
        {"source": "check_investment_send", "caller": "unit_test"}
    )
    assert not is_organic_hold_row(
        {"source": "controlled_canary_current_tip", "caller": "screener_go_alerts"}
    )
    assert not is_organic_hold_row({"source": "check_investment_send"})


def test_summarize_stance_holds_observed_only_on_organic(tmp_path):
    import json
    from lib.cio_telegram_stance_gate import summarize_stance_holds

    path = tmp_path / "holds.jsonl"
    path.write_text(
        json.dumps(
            {
                "source": "controlled_canary_current_tip",
                "symbol": "NOC",
            }
        )
        + "\n"
        + json.dumps(
            {
                "source": "check_investment_send",
                "caller": "social_scalp_scanner",
                "symbol": "AXTI",
                "as_of": "2026-09-22T14:00:00Z",
                "held_reason": "cio_stance_conflict",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    s = summarize_stance_holds(path)
    assert s["total"] == 2
    assert s["organic"] == 1
    assert s["non_organic"] == 1
    assert s["observed"] is True
    assert s["latest_organic"]["symbol"] == "AXTI"
    assert s["latest_organic"]["caller"] == "social_scalp_scanner"

    canary_only = tmp_path / "canary.jsonl"
    canary_only.write_text(
        json.dumps({"source": "maturity_agent_local_probe", "symbol": "X"}) + "\n",
        encoding="utf-8",
    )
    s2 = summarize_stance_holds(canary_only)
    assert s2["observed"] is False
    assert s2["organic"] == 0


def test_report_organic_stance_hold_cli_exit_codes(tmp_path):
    import json
    import subprocess
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "report_organic_stance_hold.py"
    canary = tmp_path / "canary.jsonl"
    canary.write_text(
        json.dumps({"source": "controlled_canary_current_tip", "symbol": "NOC"}) + "\n",
        encoding="utf-8",
    )
    r = subprocess.run(
        [sys.executable, str(script), "--path", str(canary)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 2
    assert "PARTIAL" in r.stdout
    assert "LIVE-cio-stance-governance" in r.stdout
    assert "observe windows ET" in r.stdout

    organic = tmp_path / "organic.jsonl"
    organic.write_text(
        json.dumps(
            {
                "source": "check_investment_send",
                "caller": "send_telegram_proposal_alert",
                "symbol": "AXTI",
                "as_of": "2026-09-22T15:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    r2 = subprocess.run(
        [sys.executable, str(script), "--path", str(organic), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r2.returncode == 0
    payload = json.loads(r2.stdout)
    assert payload["observed"] is True
    assert payload["organic"] == 1
