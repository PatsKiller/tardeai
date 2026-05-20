"""Tests for DOC-RECON-1 post-audit documentation reconciliation."""
import subprocess, sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
DOCS = PROJ / "docs" / "operator_hygiene" / "phase_post_audit_ops1_remaining_backend_fixes"


def test_truth_script_compiles():
    r = subprocess.run([sys.executable, "-m", "py_compile",
                        str(PROJ / "scripts" / "report_doc_recon1_post_audit_truth.py")])
    assert r.returncode == 0


def test_truth_report_exists():
    assert (DOCS / "doc_recon1_truth_report.md").exists()


def test_readme_says_fixed():
    text = (DOCS / "00_README.md").read_text()
    assert "FIXED" in text
    assert "5/5" in text


def test_readme_contains_all_commits():
    text = (DOCS / "00_README.md").read_text()
    for commit in ["03baf9d", "00a6967", "50c0846", "d8ef77f", "442c46b"]:
        assert commit in text, f"Commit {commit} missing from README"


def test_closure_memo_exists():
    assert (DOCS / "post_audit_ops1_5_of_5_closure_memo.md").exists()


def test_supersession_notes():
    for fname in ["regime_cron1_staleness_report.md",
                   "agent_fix1_queue_health_report.md",
                   "llm_fix1_overnight_fallback_report.md",
                   "count_truth1_drift_contract_report.md",
                   "attr1_benchmark_alpha_report.md"]:
        fpath = DOCS / fname
        if fpath.exists():
            text = fpath.read_text()
            assert "SUPERSEDED" in text, f"{fname} missing supersession note"


def test_safety_terms_present():
    text = (DOCS / "00_README.md").read_text()
    for term in ["no trades", "No trades", "no orders", "No orders"]:
        if term.lower() in text.lower():
            return
    assert False, "Safety terms missing from README"


def test_a5_date_gate():
    text = (DOCS / "00_README.md").read_text()
    assert "2026-05-22" in text


def test_env_safety():
    env = (PROJ / ".env").read_text()
    assert "ALPACA_MODE=paper" in env
    assert "LLM_DISABLE_LIVE_EXECUTION=true" in env
