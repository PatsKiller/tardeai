"""WAVE B2+B3 — failure surfaces must be legible; success claims must be conditional.

B2 — Opaque failure summaries
    Health-recovery SUCCESS rows already carry `rc=` / `rate_limit_hits=`.
    Live failed pipeline_runs rows for trade_ai_orchestrator stored only
    `{"errors": "2"}` — the SystemExit code. Make the failure path record the
    same diagnostic fields, then the underlying failures become legible.

B3 — Silent-success mechanisms
    Four components declared success about work they watched fail:
      - aegis_overnight: PHASE FAILED → still COMPLETE; Briefs=synthesis count
      - portfolio_orchestrator: "Bundle send failed" → "all stages completed"
      - cio_command_center: bare except served unrendered product + stamped
        canonical_cio_source
      - trade_ai_orchestrator: RUN_FAILED still published dashboard/PDF/live

AGENTS.md §9.1: a failure must reach a surface, not just a log line.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

tao = importlib.import_module("trade_ai_orchestrator")
ao = importlib.import_module("aegis_overnight")


# ── B2: failure path diagnostic fields ─────────────────────────────────────

def test_format_failure_diagnostic_matches_health_recovery_shape():
    """Success recovery notes look like:
    `health recovery rc=orchestrator_yfinance_rate_limit; rate_limit_hits=32`
    Failure must carry the same keys.
    """
    d = tao.format_failure_diagnostic(
        rc="RUN_FAILED",
        rate_limit_hits=32,
        reasons=["UNIVERSE_TOO_SMALL"],
        symbols=0,
        stage_errors=1,
    )
    assert "rc=RUN_FAILED" in d
    assert "rate_limit_hits=32" in d
    assert "symbols=0" in d
    assert "UNIVERSE_TOO_SMALL" in d
    assert "stage_errors=1" in d


def test_enrich_opaque_exit_turns_bare_2_into_diagnostic(tmp_path):
    """The live defect: summary `{\"errors\": \"2\"}`. After enrichment the
    string PipelineRun stores must contain rc= and rate_limit_hits=."""
    got = tao._enrich_opaque_exit(2, tmp_path)
    assert isinstance(got, str)
    assert "rc=" in got
    assert "rate_limit_hits=" in got
    assert "2" in got or "exit_2" in got


def test_enrich_leaves_already_formatted_diagnostic_alone(tmp_path):
    already = "rc=RUN_FAILED; rate_limit_hits=5; symbols=0; stage_errors=1"
    assert tao._enrich_opaque_exit(already, tmp_path) == already


def test_write_failure_run_summary_is_a_surface(tmp_path):
    path = tao.write_failure_run_summary(tmp_path, {
        "run_label": "0900",
        "diagnostic": "rc=RUN_FAILED; rate_limit_hits=0; symbols=0; stage_errors=1",
        "rate_limit_hits": 0,
        "published_dashboard": False,
    })
    assert path.exists()
    doc = json.loads(path.read_text())
    assert doc["status"] == "FAILED"
    assert doc["published_dashboard"] is False
    assert "rc=RUN_FAILED" in doc["diagnostic"]


def test_stage_errors_accumulate_via_err():
    tao._STAGE_ERRORS.clear()
    tao._err("scoring", "boom")
    tao._err("finviz_ingestion", "rate limited")
    assert len(tao._STAGE_ERRORS) == 2
    assert tao._STAGE_ERRORS[0]["stage"] == "scoring"
    tao._STAGE_ERRORS.clear()


# ── B3: trade_ai RUN_FAILED must not publish ───────────────────────────────

def test_run_failed_publish_gate_is_in_source():
    src = (ROOT / "scripts" / "trade_ai_orchestrator.py").read_text(encoding="utf-8")
    assert "_publish_artifacts = False" in src
    assert "publish refused after" in src
    assert "published_dashboard_live" in src
    # Must not leave the old "proceed anyway" print as the only action.
    assert "Refusing to publish dashboard/PDF/live" in src


def test_run_failed_path_writes_diagnostic_not_bare_exit_code():
    src = (ROOT / "scripts" / "trade_ai_orchestrator.py").read_text(encoding="utf-8")
    assert "format_failure_diagnostic(" in src
    assert "write_failure_run_summary(" in src
    # The failure return is the diagnostic string, not a bare int 2.
    assert "return _diag" in src


# ── B3: aegis_overnight (from live 6-night observation) ────────────────────

def test_aegis_live_2026_08_30_payload_is_no_effect():
    assert ao._phase_did_nothing({
        "delivered": False, "reason": "semantic_duplicate",
        "key": "MORNING:2026-08-30:ec5a2e56de503f25",
        "source": "cio.operator_product.current"}) is True


def test_aegis_live_2026_08_29_payload_is_real_work():
    assert ao._phase_did_nothing({
        "delivered": True, "reason": "canonical_cio_operator_product",
        "key": "MORNING:2026-08-29:ec5a2e56de503f25"}) is False


def test_aegis_error_payload_is_recognised():
    assert ao._phase_did_nothing({"error": "No module named 'scripts'"}) is True


def test_aegis_silence_is_not_treated_as_failure():
    assert ao._phase_did_nothing({"briefs": 15, "rotations": 27}) is False
    assert ao._phase_did_nothing({}) is False
    assert ao._phase_did_nothing(None) is False


def test_aegis_phase_that_did_nothing_does_not_report_complete():
    got = ao._run_phase("probe", lambda: {"delivered": False, "reason": "dup"})
    assert got["phase_status"] == "NO_EFFECT"


def test_aegis_raising_phase_reports_failed_with_cause():
    def boom():
        raise ModuleNotFoundError("No module named 'scripts'")
    got = ao._run_phase("probe", boom)
    assert got["phase_status"] == "FAILED"
    assert "No module named" in got["error"]


def test_aegis_digest_distinguishes_delivered_from_generated():
    src = (ROOT / "scripts" / "aegis_overnight.py").read_text(encoding="utf-8")
    assert "delivered / " in src and "generated" in src
    assert "AEGIS OVERNIGHT INCOMPLETE" in src
    assert "f\"Briefs: {synth.get('briefs',0)}" not in src


def test_aegis_benign_dedup_does_not_cry_wolf():
    for reason in ("already_sent", "semantic_duplicate"):
        st = "NO_EFFECT"
        incomplete = st in ("FAILED", "TIMEOUT") or (
            st == "NO_EFFECT" and reason not in ao.BENIGN_NO_EFFECT)
        assert incomplete is False


def test_aegis_unrecognised_no_effect_still_incomplete():
    assert "some_new_thing" not in ao.BENIGN_NO_EFFECT


# ── B3: portfolio_orchestrator Bundle send ─────────────────────────────────

def test_bundle_send_failure_is_a_stage_failure():
    src = (ROOT / "scripts" / "portfolio_orchestrator.py").read_text(encoding="utf-8")
    # The except that used to only print must now record a stage failure.
    assert '_stage_failed("morning_command_bundle"' in src
    idx_fail = src.index('_stage_failed("morning_command_bundle"')
    idx_print = src.index("Bundle send failed")
    # stage_failed is recorded at the failure site (near the print).
    assert abs(idx_fail - idx_print) < 400


def test_all_stages_completed_is_gated_on_empty_failures():
    """_report_stage_failures only prints 'all pipeline stages completed'
    when _STAGE_FAILURES is empty — so a Bundle failure cannot claim it."""
    import portfolio_orchestrator as po
    po._STAGE_FAILURES.clear()
    # Dry: with a recorded failure, the success phrase must not appear.
    po._STAGE_FAILURES.append({
        "stage": "morning_command_bundle",
        "error_type": "RuntimeError",
        "error": "send failed",
        "traceback": "",
        "fatal": False,
        "at": "2026-08-31T00:00:00",
    })
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        n = po._report_stage_failures(ROOT / "data" / "portfolios" / "state")
    out = buf.getvalue()
    assert n == 1
    assert "all pipeline stages completed" not in out
    assert "INCOMPLETE" in out or "FAILED" in out
    po._STAGE_FAILURES.clear()


# ── B3: cio_command_center bare except / canonical stamp ───────────────────

def test_render_failure_does_not_stamp_canonical_cio_source(monkeypatch):
    from scripts.lib import cio_command_center as cc

    def _boom(_product):
        raise RuntimeError("renderer exploded")

    monkeypatch.setattr(
        "scripts.lib.cio_operator_renderers.command_center_view",
        _boom,
        raising=False,
    )
    # Also patch the import path used inside build_office_home
    import scripts.lib.cio_operator_renderers as rend
    monkeypatch.setattr(rend, "command_center_view", _boom)

    home = cc.build_office_home(operator_product={"available": True, "status": "ok"})
    assert "canonical_cio_source" not in home
    op = home["operator_product"]
    assert op.get("loaded") is False
    assert "render_error" in op or "renderer exploded" in str(op)


def test_successful_render_still_stamps_canonical(monkeypatch):
    from scripts.lib import cio_command_center as cc
    import scripts.lib.cio_operator_renderers as rend

    def _ok(product):
        return {"source": "cio.operator_product.current", "loaded": True,
                "status": product.get("status"), "earnings": []}

    monkeypatch.setattr(rend, "command_center_view", _ok)
    home = cc.build_office_home(operator_product={"available": True, "status": "ok"})
    assert home.get("canonical_cio_source") == "cio.operator_product.current"
    assert home["operator_product"]["loaded"] is True


def test_missing_operator_product_does_not_stamp_canonical():
    """No product rendered → no provenance stamp (same rule as render failure)."""
    from scripts.lib import cio_command_center as cc
    home = cc.build_office_home()
    assert "canonical_cio_source" not in home
    assert home["operator_product"]["loaded"] is False


# ── Source-level contracts quoted for dry-run evidence ─────────────────────

def test_trade_ai_source_quotes_the_b2_contract():
    src = (ROOT / "scripts" / "trade_ai_orchestrator.py").read_text(encoding="utf-8")
    assert "rate_limit_hits" in src
    assert "rc=" in src
    assert "_enrich_opaque_exit" in src
