"""ANCHOR: FIXTURE_PRIVACY_SYNTHETIC_20261025 — the public-fixture anonymizer's rules, on synthetic inputs only.

The real symbol/account sets are host-only (persistent-state holdings); nothing real is committed here.
"""
import gzip
import importlib.util
import json
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fixture_privacy_anonymize", ROOT / "scripts/fixture_privacy_anonymize.py")
anon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(anon)

# Files that carried real portfolio data until 2026-10-25; they must stay synthetic.
CLEANED = [
    "tests/fixtures/active_trader/xndu_session_20261005.json",
    "tests/fixtures/buy_ready_v_golden_20260924.txt",
    "tests/fixtures/cc_client_compat_20261018/observations.json.gz",
    "tests/fixtures/cio_data_quality/cio_data_quality_20261023.json",
    "tests/fixtures/cio_prospect/navn_20261022.json",
    "tests/fixtures/cio_snapshot_shape_20260913_1856.json",
    "tests/fixtures/conflicts/opportunity_rows.json",
    "tests/fixtures/conflicts/reference_conflict_engine.py.txt",
    "tests/fixtures/conflicts/reference_profiles.py.txt",
    "tests/fixtures/conflicts/reference_tests.py.txt",
    "tests/fixtures/fidelity_rollover_stops_20260713.json",
    "tests/fixtures/header_truth/clock_contradiction_20260903_20260904.json",
    "tests/fixtures/litmus_20260913/desk.json",
    "tests/fixtures/litmus_20260913/holdings.json",
    "tests/fixtures/litmus_20260913/questions.json",
    "tests/fixtures/litmus_20260913/snapshot.json",
    "tests/fixtures/maria_outbound_gate/maria_s_reply_20260923T1226Z.txt",
    "tests/fixtures/material_change_20260924.json",
    "tests/fixtures/operator_questions_20260913.json",
    "tests/fixtures/refactor_shard_07_20261011/price_db_sync.py.txt",
]


def _text(rel):
    raw = (ROOT / rel).read_bytes()
    return (gzip.decompress(raw) if rel.endswith(".gz") else raw).decode("utf-8", errors="ignore")


def test_symbol_map_is_deterministic_letters_only_and_salted():
    syms = {"AAA", "BBBB", "C"}
    first, again = anon.symbol_map(syms, "s1"), anon.symbol_map(syms, "s1")
    assert first == again
    assert set(first) == syms and len(set(first.values())) == 3
    assert all(re.fullmatch(r"ZQ[A-Z]{2}", v) for v in first.values())
    orders = {tuple(sorted(anon.symbol_map(syms, s), key=anon.symbol_map(syms, s).get)) for s in ("s1", "s2", "s3", "s4")}
    assert len(orders) > 1, "order must depend on the private salt, not the alphabet"


def test_account_labels_are_generic_by_kind():
    out = anon.account_map({"brokerx_roth_ira", "brokerx_rollover_ira", "brokerx_taxable", "brokery_taxable_live"})
    assert sorted(out.values()) == ["ira_a", "roth_a", "taxable_a", "taxable_b"]


def test_apply_rewrites_symbols_accounts_and_numbers():
    sym_map = {"AAA": "ZQAA", "V": "ZQAB"}
    acct_map = {"brokerx_roth_ira": "roth_a"}
    text = ('{"symbol": "AAA", "s2": "V", "account": "brokerx_roth_ira"} AAA rose; Visa V stays; AAAB stays; '
            "Rollover IRA #123456789")
    out = anon.anonymize_text(text, sym_map, acct_map)
    assert '"ZQAA"' in out and '"ZQAB"' in out and '"roth_a"' in out
    assert "ZQAA rose" in out and "AAAB stays" in out and "Visa V stays" in out  # short symbols only when quoted
    assert "123456789" not in out and "#0000000" in out


def test_leftovers_counts_without_values():
    left = anon.leftovers("V and AAA in acct 98765432 at brokerx_roth_ira and schwab_roth_ira",
                          {"V", "AAA"}, {"brokerx_roth_ira"})
    assert left == {"symbols": 2, "accounts": 1, "account_numbers": 1, "account_slugs": 1}
    assert all(isinstance(v, int) for v in left.values())


@pytest.mark.parametrize("rel", CLEANED)
def test_cleaned_fixture_carries_no_account_ids_or_numbers(rel):
    left = anon.leftovers(_text(rel), set(), set())
    assert not left, f"{rel}: {left}"


@pytest.mark.host_state("reads the live holdings files to build the check list at test time; skips in CI")
def test_host_cleaned_fixtures_carry_no_real_holdings():
    symbols, accounts = anon.private_terms()
    if not symbols:
        pytest.skip("real holdings are host-only")
    bad = {rel: left for rel in CLEANED if (left := anon.leftovers(_text(rel), symbols, accounts))}
    assert not bad, json.dumps(bad)


ARCHIVED_CAPTURES = "apps/command-center-v3/e2e/screenshots/operator-cards"


def test_tripwire_live_operator_card_captures_stay_out_of_the_repo():
    """The 2026-07-21 live-site captures were archived privately (persistent-state design archive, 0600)."""
    back = sorted(p.name for p in (ROOT / ARCHIVED_CAPTURES).glob("*.png")) if (ROOT / ARCHIVED_CAPTURES).is_dir() else []
    assert not back, f"live captures reappeared in the public repo: {len(back)} file(s)"
    spec = (ROOT / "apps/command-center-v3/e2e/operator-cards-screenshots.spec.ts").read_text(encoding="utf-8")
    assert "OPERATOR_CARD_SYMBOLS" in spec and "screenshots', 'operator-cards'" not in spec
