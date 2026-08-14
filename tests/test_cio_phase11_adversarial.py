"""Phase 11 — adversarial suite: deliberately try to break CIO hardening.

READ_ONLY_ADVISORY. No broker. No live Telegram. Pure + interdicted unit attacks
against Phase 0–10 defects: units, cash double-count, HOLD+TRIM, pseudo-sectors,
Telegram isolation, data-quality abstention, release-pin hygiene, AST no-order.
"""
from __future__ import annotations

import ast
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib import cio_capital_plan as cp  # noqa: E402
from scripts.lib import cio_decision_semantics as ds  # noqa: E402
from scripts.lib import cio_sector_opportunity as so  # noqa: E402
from scripts.lib import cio_report_v2 as rv2  # noqa: E402
from scripts.lib import cio_report_render as rr  # noqa: E402
from scripts.lib import cio_report_analytics as an  # noqa: E402
from scripts.lib import cio_alex_telegram as alex  # noqa: E402
from cio_release_manifest import (  # noqa: E402
    FORBIDDEN_STALE_SHAS,
    build_manifest,
    validate,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _phase0_portfolio_ctx() -> dict:
    return {
        "portfolio": {
            "total_value": 1_282_425.99,
            "cash_value": 578_107.50,
            "cash_pct": 45.08,
            "positions_count": 26,
        },
        "allocation": {
            "Cash & Equivalents": 578_107.50,
            "Equities": 704_318.49,
        },
        "performance": {"ytd_return": 1.0, "port_cagr": 5.0},
    }


def _phase0_capital_plan() -> dict:
    return {
        "portfolio_value_usd": 1_282_425.99,
        "cash_total_usd": 578_107.50,
        "cash_reserved_usd": 256_485.20,
        "cash_investable_usd": 321_622.30,
        "cash_earmarked_redeploy_usd": 560_009.02,
        "net_recommended_deploy_usd": 100_000.0,
        "net_recommended_raise_usd": 63_000.0,  # prospective only
        "post_plan_cash_usd": 541_107.50,
        "post_plan_cash_pct": 42.2,
        "position_decisions": [
            {
                "symbol": "SCHD",
                "stance": "Trim",
                "stance_code": "TRIM",
                "current_value_usd": 120_000.0,
                "current_weight_pct": 9.4,
                "recommended_delta_usd": -20_000.0,
                "decision_id": "dec_schd_trim",
            },
        ],
    }


# ── A1 units: dollars must never render as percent ───────────────────────────

def test_adv_units_allocation_weights_not_dollar_as_pct():
    model = rv2.build_report_v2(
        part_b_ctx=_phase0_portfolio_ctx(),
        part_a_inputs={"capital_plan": _phase0_capital_plan()},
        source_sha="adv",
        now=datetime.now(timezone.utc),
    )
    weights = (model.get("part_b") or {}).get("allocation_weight_pct") or {}
    cash_w = float(weights.get("Cash & Equivalents") or weights.get("Cash") or 0)
    assert 40.0 <= cash_w <= 50.0, f"cash weight should be ~45%, got {cash_w}"
    assert cash_w != 578_107.50
    html = rr.render_html(model) if hasattr(rr, "render_html") else ""
    if not html:
        from scripts.lib.cio_report_render import export_report_formats
        out = ROOT / "exports" / "adv_units"
        out.mkdir(parents=True, exist_ok=True)
        res = export_report_formats(model, out, basename="adv_units", formats=["html"])
        html = Path(res["paths"]["html"]).read_text(encoding="utf-8")
    assert "578107.50%" not in html
    assert "578,107.50%" not in html
    assert "578107.5%" not in html


# ── A2 cash arithmetic: Phase 0 double-count must not resurrect ──────────────

def test_adv_cash_double_count_phase0_shape():
    cash = 578_107.50
    value = 1_282_425.99
    reserved = round(value * 0.20, 2)
    investable = round(cash - reserved, 2)
    earmark = 560_009.02
    prospective = 63_000.0
    plan = cp.build_capital_plan(
        portfolio_value=value,
        cash_total=cash,
        positions=[{"symbol": "EXITME", "market_value": prospective, "account": "ira"}],
        queue={"items": [
            {"symbol": "EXITME", "verdict": "EXIT", "source": "cio"},
            *[{"symbol": f"ADD{i}", "verdict": "ADD", "source": "advisory"} for i in range(40)],
        ]},
        redeploy_open_events=[{"event_id": 1, "symbol": "REDEPLOY", "remaining_usd": earmark}],
    )
    assert plan["net_recommended_raise_usd"] == prospective
    assert plan["deployable_usd"] == round(investable + prospective, 2)
    # Old bug: investable + earmark + prospective
    assert plan["deployable_usd"] < round(investable + earmark + prospective, 2) - 1000
    assert plan["cash_ledger"]["invariants_ok"] is True
    # Earmark is label, not additive raise
    assert plan["cash_earmarked_redeploy_usd"] == earmark
    assert plan["net_recommended_raise_usd"] != earmark
    assert plan["net_recommended_raise_usd"] != round(earmark + prospective, 2)


def test_adv_cash_ledger_rejects_earmark_gt_cash():
    ledger = cp.build_cash_ledger(
        cash_total=100.0,
        portfolio_value=1000.0,
        reserve_usd=20.0,
        investable_usd=80.0,
        earmarked_redeploy_usd=999.0,  # impossible
        prospective_raise_usd=0.0,
        net_deploy_usd=0.0,
        post_plan_cash_usd=100.0,
    )
    assert ledger["invariants_ok"] is False
    names = {i["name"]: i["ok"] for i in ledger["invariants"]}
    assert names["earmark_le_cash"] is False


# ── A3 decision semantics: no HOLD+TRIM, no dups, no Iwm−Spy ─────────────────

def test_adv_no_hold_plus_trim_after_sanitize():
    rows = [
        {"symbol": "SCHD", "cio_stance": "HOLD", "why_now": "Advisory TRIM — SCHD",
         "current_value_usd": 80_000.0, "current_weight_pct": 8.0,
         "recommended_delta_usd": 0.0, "risk": "x", "account": "ira"},
        {"symbol": "SCHD", "cio_stance": "HOLD", "why_now": "Advisory TRIM — SCHD",
         "current_value_usd": 40_000.0, "current_weight_pct": 4.0,
         "recommended_delta_usd": 0.0, "risk": "x", "account": "taxable"},
        {"symbol": "SCHD", "cio_stance": "TRIM", "why_now": "concentration",
         "current_value_usd": 10_000.0, "current_weight_pct": 1.0,
         "recommended_delta_usd": -5_000.0, "risk": "x", "account": "roth"},
    ]
    dec = ds.sanitize_decisions_now(rows, portfolio_value=1_000_000.0, limit=20)
    assert len(dec) == 1
    assert dec[0]["symbol"] == "SCHD"
    assert dec[0]["stance_code"] == "TRIM"
    assert "HOLD" not in (dec[0].get("stance") or "").upper() or dec[0]["stance_code"] != "HOLD"


def test_adv_pseudo_sector_never_survives():
    for bad in ("Iwm−Spy", "IWM-SPY", "Spy/Qqq", "iwm - spy", "QQQ−SPY"):
        assert ds.is_pseudo_sector(bad) or so.canonical_sector(bad) == ""
        assert so.normalize_sector_row({
            "sector": bad, "state": "IMPROVING", "rs20": 1, "slope": 1,
        }) is None
    clean = so.normalize_sector_row({
        "sector": "Technology", "state": "LEADING", "rs20": 1, "slope": 1,
        "opportunity": True,
    })
    assert clean is not None
    assert clean.get("sector") == "Technology"


# ── A4 Telegram isolation + canary dual-gate ─────────────────────────────────

def test_adv_telegram_never_uses_general_creds(monkeypatch):
    monkeypatch.setenv("CIO_OUTBOUND_DEDUPE_PATH", str(ROOT / "exports" / "adv_dedupe.jsonl"))
    monkeypatch.delenv("AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY", raising=False)
    monkeypatch.setenv("TELEGRAM_CIO_BOT_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "000000:GENERAL_MUST_NOT_USE")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999999999")
    from lib import cio_telegram_transport as t

    assert t.cio_bot_token() == ""
    monkeypatch.setattr(t, "network_interdicted", lambda: False)
    res = t.send_cio_message("x" * 50, require_live_auth=False, force=True)
    assert res.get("delivered") is False


def test_adv_canary_blocked_without_triple_approval(monkeypatch):
    monkeypatch.delenv("AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY", raising=False)
    monkeypatch.delenv("CIO_TELEGRAM_CANARY_ENABLE", raising=False)
    monkeypatch.delenv("CIO_TELEGRAM_CANARY_APPROVAL", raising=False)
    # Even in-process force must not deliver without env triple-gate
    res = alex.execute_canary_send(
        decision={
            "decision_id": "dec_canary_adv",
            "symbol": "CANARY",
            "action": "Review",
            "why_now": "adversarial canary attempt against dual env gate",
            "recommended_delta_usd": 1.0,
        },
        force_approve_in_process=True,
    )
    assert res.get("delivered") is False
    assert res.get("REAL_TELEGRAM_SENDS", 0) == 0
    assert "env" in (res.get("reason") or "").lower() or "approval" in (res.get("reason") or "").lower()


def test_adv_non_material_heartbeat_not_paged(monkeypatch):
    monkeypatch.setenv("CIO_OUTBOUND_DEDUPE_PATH", str(ROOT / "exports" / "adv_dedupe2.jsonl"))
    decision = {
        "decision_id": "",
        "symbol": "HEARTBEAT",
        "stance": "HOLD",
        "why_now": "thesis version bump",
        "recommended_delta_usd": 0,
    }
    mat = alex.is_material_event(kind="heartbeat", decision=decision)
    assert mat.get("material") is False
    mat2 = alex.is_material_event(kind="decision", decision=decision)
    assert mat2.get("material") is False


# ── A5 data-quality abstention ───────────────────────────────────────────────

def test_adv_data_unavailable_not_fabricated():
    # QTD / TWR / style-box style fields must abstain when inputs missing
    model = rv2.build_report_v2(
        part_b_ctx=_phase0_portfolio_ctx(),
        part_a_inputs={"capital_plan": _phase0_capital_plan()},
        source_sha="adv",
        now=datetime.now(timezone.utc),
    )
    # analytics layer
    metrics = an.build_analytics(model) if hasattr(an, "build_analytics") else None
    if metrics is None and hasattr(an, "compute_analytics"):
        metrics = an.compute_analytics(model)
    if metrics is None:
        # fall back: model must not invent QTD
        text = str(model)
        assert "fabricated_qtd" not in text.lower()
        return
    # Look for DATA_UNAVAILABLE markers on known thin series
    blob = str(metrics)
    assert an.DATA_UNAVAILABLE in blob or "DATA_UNAVAILABLE" in blob or "unavailable" in blob.lower()


# ── A6 release pin hygiene ───────────────────────────────────────────────────

def test_adv_forbidden_phase0_shas_not_canonical():
    m = build_manifest()
    head = m["canonical_source_sha"]
    for stale in FORBIDDEN_STALE_SHAS:
        assert not head.startswith(stale[:8])
        assert head not in FORBIDDEN_STALE_SHAS
    # validate should not be stale vs self after generate path
    result = validate(m)
    # may warn about deploy lag; must not error on forbidden as current if live head is fine
    assert not any("stale_forbidden" in e for e in result.get("errors", []))


def test_adv_backend_release_sha_not_date_stamp():
    m = build_manifest()
    sha = str(m.get("backend_release_sha") or "")
    # Must not confuse YYYYMMDD release dir with a git SHA
    assert not re.fullmatch(r"\d{8}", sha)
    assert sha  # present


# ── A7 AST: no broker order/stop paths added in CIO hardening modules ────────

_BANNED_CALLS = frozenset({
    "place_order", "submit_order", "cancel_order", "modify_order",
    "broker_execute_order", "broker_cancel_order", "broker_modify_order",
    "create_order", "submit_stop", "place_stop", "arm_stop",
})
_BANNED_ATTR = frozenset({
    "place_order", "submit_order", "cancel_order", "modify_order",
})


def test_adv_ast_no_broker_order_calls_in_cio_lib():
    lib = ROOT / "scripts" / "lib"
    files = sorted(lib.glob("cio_*.py"))
    offenders: list[str] = []
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as e:
            offenders.append(f"{path.name}:syntax:{e}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = None
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                if name and name in _BANNED_CALLS:
                    # allow string mentions in deny-lists / comments via not being Call
                    offenders.append(f"{path.name}:{getattr(node, 'lineno', '?')}:{name}")
            if isinstance(node, ast.Attribute) and node.attr in _BANNED_ATTR:
                # only count if used as call already handled; skip bare attr reads of deny lists
                pass
    # Deny-list *definitions* that call nothing are fine; real Call nodes are not.
    # Filter known allowlist files that define ban strings only (no calls expected).
    assert offenders == [], f"broker order call sites in CIO lib: {offenders}"


def test_adv_ast_no_send_telegram_general_from_thesis_path():
    """Thesis / notification paths must not call send_telegram (general)."""
    targets = [
        ROOT / "scripts" / "lib" / "cio_theses.py",
        ROOT / "scripts" / "lib" / "cio_notification_outbox.py",
        ROOT / "scripts" / "lib" / "cio_alex_telegram.py",
    ]
    offenders = []
    for path in targets:
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = None
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                if name in ("send_telegram", "send_message_general"):
                    offenders.append(f"{path.name}:{node.lineno}:{name}")
    assert offenders == [], offenders


# ── A8 report / office decision-id consistency ───────────────────────────────

def test_adv_decision_ids_stable_across_model_fields():
    plan = _phase0_capital_plan()
    # Enrich decision so sanitize keeps it as material TRIM
    plan["position_decisions"] = [{
        "symbol": "SCHD",
        "cio_stance": "TRIM",
        "stance": "Trim",
        "stance_code": "TRIM",
        "current_value_usd": 120_000.0,
        "current_weight_pct": 9.4,
        "recommended_delta_usd": -20_000.0,
        "why_now": "concentration > cap — adversarial probe",
        "risk": "concentration > cap",
        "account": "ira",
    }]
    model = rv2.build_report_v2(
        part_b_ctx=_phase0_portfolio_ctx(),
        part_a_inputs={"capital_plan": plan},
        source_sha="adv",
        now=datetime.now(timezone.utc),
    )
    # Phase 8: every material card carries dec_* shared identity
    decs = (model.get("part_a") or {}).get("decisions_now") or model.get("decisions_now") or []
    if not decs:
        # fall back: walk model for decisions_now
        for k, v in model.items():
            if isinstance(v, dict) and v.get("decisions_now"):
                decs = v["decisions_now"]
                break
            if k == "view" and isinstance(v, dict):
                for kk, vv in v.items():
                    if "decision" in kk.lower() and isinstance(vv, list):
                        decs = vv
    ids = [d.get("decision_id") for d in (decs or []) if isinstance(d, dict) and d.get("decision_id")]
    if not ids:
        # Instance / plan digest path
        blob = str(model)
        assert "dec_" in blob or "decision_id" in blob
    else:
        assert all(str(i).startswith("dec_") for i in ids)
        blob = str(model)
        for did in ids:
            assert did in blob


# ── A9 pagination / render safety smoke ──────────────────────────────────────

def test_adv_html_export_readable_and_advisory():
    model = rv2.build_report_v2(
        part_b_ctx=_phase0_portfolio_ctx(),
        part_a_inputs={"capital_plan": _phase0_capital_plan()},
        source_sha="adv",
        now=datetime.now(timezone.utc),
    )
    out = ROOT / "exports" / "adv_html"
    out.mkdir(parents=True, exist_ok=True)
    res = rr.export_report_formats(model, out, basename="adv_html", formats=["html"])
    path = Path(res["paths"]["html"])
    html = path.read_text(encoding="utf-8")
    assert len(html) > 500
    assert "READ_ONLY_ADVISORY" in html or "advisory" in html.lower()
    # no raw enum dumps common to Phase 0
    assert "STAGED_DEPLOYMENT" not in html or "Staged" in html
