"""Research governance — adversarial tests (PR-R1).

Defect-first checks: the subsystem must not grant trade authority, must not make
provider/broker/DB calls, must fail closed on degenerate inputs, and must not be
gameable in the obvious ways.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance import (  # noqa: E402
    bootstrap_reality_check,
    deflated_sharpe,
    multiple_testing,
    pbo,
    promotion_gate,
    trial_registry,
)
from scripts.lib.research_governance.enums import GateState  # noqa: E402

PKG_DIR = ROOT / "scripts" / "lib" / "research_governance"

FORBIDDEN_NETWORK_OR_DB_TOKENS = [
    "import requests", "from requests",
    "import httpx", "from httpx",
    "import urllib", "from urllib",
    "import socket", "from socket",
    "import psycopg", "from psycopg",
    "import sqlalchemy", "from sqlalchemy",
    "import telegram", "from telegram",
    "import openai", "from openai",
    "import anthropic", "from anthropic",
    "import boto3", "from boto3",
]


def test_no_provider_broker_or_db_imports():
    offenders = []
    for f in PKG_DIR.glob("*.py"):
        text = f.read_text(encoding="utf-8")
        for tok in FORBIDDEN_NETWORK_OR_DB_TOKENS:
            if tok in text:
                offenders.append(f"{f.name}: {tok}")
    assert offenders == [], f"side-effecting imports found: {offenders}"


def test_promotion_gate_never_grants_trade_authority():
    # The gate's highest output is advisory; it has no trade-authority flag.
    assert not any("authority" in g for g in promotion_gate.GATE_IDS)


def test_authority_boundary_unconditional_fail():
    ctx = {
        "source_id": "s", "claim": "c", "page_or_section": "p", "scope": "us",
        "protocol_hash": "ph", "trial_family_id": "f", "family_frozen": True,
        "code_sha": "c", "dataset_hash": "d",
        "in_sample_metric": 1.0, "in_sample_threshold": 0.0,
        "oos_supported": True, "oos_untouched": True,
        "multiple_testing": {"rejected_any": True},
        "reality_check": {"bootstrap_pvalue": 0.001},
        "robustness": {"subperiods": True, "regimes": True, "costs": True},
        "evidence_grade": "A",
        "influence_class": "VALUATION_INPUT",
        "claims_trade_authority": True,
    }
    rep = promotion_gate.run_promotion_gate(ctx)
    assert rep["overall"] == GateState.FAIL.value


def test_dsr_degenerate_moments_fail_closed():
    # Zero-variance returns and huge kurtosis must not produce a fake confidence.
    r = deflated_sharpe.deflated_sharpe(observed_sharpe=0.0, n_observations=100,
                                        skewness=0.0, kurtosis=10 ** 6,
                                        trial_sharpes=[0.0, 0.0], n_trials=5)
    # trial sharpe std = 0 => UNAVAILABLE (fail closed).
    assert r["status"] == "UNAVAILABLE"


def test_pbo_single_config_fails_closed():
    r = pbo.cscv_probability_of_backtest_overfitting([[0.1] * 20])
    assert r["status"] == "NOT_APPLICABLE"


def test_reality_check_degenerate_fails_closed():
    # single observation => UNAVAILABLE
    r = bootstrap_reality_check.reality_check_pvalue([[0.1], [0.1]])
    assert r["status"] == "UNAVAILABLE"


def test_multiple_testing_all_equal_pvalues():
    # Identical p-values: Bonferroni must not reject when m*alpha >= 1.
    r = multiple_testing.bonferroni([0.05] * 20, alpha=0.05)
    assert r["rejected"] == [False] * 20


def test_trial_registry_duplicate_id_overwrites_not_appends():
    reg = trial_registry.TrialRegistry()
    reg.freeze_family("f", "h", protocol_hash="ph")
    reg.record_trial("f", "t1", {"p": 1}, selected_for_followup=False)
    reg.record_trial("f", "t1", {"p": 1}, selected_for_followup=True)
    assert reg.get_family("f").trial_count == 1  # same id is an update, not a new trial


def test_oos_consumption_is_terminal():
    reg = trial_registry.TrialRegistry()
    reg.register_oos_window("f", "w", oos_generation=1)
    reg.consume_oos_window("f", "w")
    # Re-registering the same id does not silently "un-consume" the timestamp.
    reg.register_oos_window("f", "w", oos_generation=1)
    assert reg.get_family("f").oos_windows["w"].oos_consumed_at is not None


def test_promotion_gate_rejects_empty_context():
    rep = promotion_gate.run_promotion_gate({})
    assert rep["overall"] == GateState.FAIL.value
    assert rep["passed"] == 0
