"""schwab_position_sync: damaged store is 'no snapshot' to read, but a write keeps its baseline.

Operator execution-engineering grant 43212811c2fe4b17aade58299fea22ef (2026-11-03), mocks/fixtures only:
no live broker call, no credential read, no flag, no order route. Every connection/alert/hook is a fake.
"""
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import schwab_position_sync as S  # noqa: E402

REQUIRED = ["schwab_taxable", "schwab_roth", "schwab_rollover_ira"]


def _row(sym, acct, shares, mv, *, cash=False, basis=1000.0):
    return {"symbol": sym, "account": acct, "account_id": acct, "shares": shares,
            "market_value": mv, "price": (mv / shares if shares else 1.0), "is_cash": cash,
            "cost_basis": mv if cash else basis, "cost_basis_total": mv if cash else basis,
            "avg_cost": (1.0 if cash or not shares else basis / shares)}


def _book():
    return {"holdings": [
        _row("AAA", "schwab_taxable", 100, 60000.0),
        _row("CASH", "schwab_taxable", 20000, 20000.0, cash=True),
        _row("BBB", "schwab_roth", 100, 40000.0),
        _row("CASH", "schwab_roth", 12000, 12000.0, cash=True),
        _row("CCC", "schwab_rollover_ira", 1000, 500000.0),
        _row("CASH", "schwab_rollover_ira", 200000, 200000.0, cash=True),
    ]}


@pytest.fixture
def store(tmp_path, monkeypatch):
    hp = tmp_path / "holdings.json"
    monkeypatch.setattr(S, "HOLDINGS_PATH", hp)
    monkeypatch.setattr(S, "_record", lambda *a, **k: None)
    monkeypatch.setattr(S, "_alert", lambda *a, **k: None)
    # Every post-write hook is a fake: no DB, no broker, no other store.
    monkeypatch.setitem(sys.modules, "holdings_change_trigger",
                        types.SimpleNamespace(check_and_enqueue=lambda **k: {}))
    monkeypatch.setitem(sys.modules, "sync_portfolio_watchlist_membership",
                        types.SimpleNamespace(sync_portfolio_watchlist_membership=lambda d: {}))
    ct = types.ModuleType("lib.cost_basis_transfer")
    ct.process_holdings_change = lambda *a, **k: {}
    monkeypatch.setitem(sys.modules, "lib.cost_basis_transfer", ct)
    return hp


def _backup(hp, doc=None):
    p = hp.parent / (hp.name + ".bak-test")
    p.write_text(json.dumps(doc or _book()))
    return p


# ── (a) READ path: empty/corrupt is 'no snapshot', never a crash ──────────────────────────

def test_read_diff_on_empty_store_is_no_snapshot(store):
    store.write_bytes(b"")
    out = S._sync_rows("schwab_roth_ira", "schwab_roth", [], object(), dry_run=True)
    assert out["status"] == "no_snapshot" and out["wrote"] is False and out["store_state"] == "empty"


def test_read_diff_on_corrupt_store_is_no_snapshot(store):
    store.write_text("{not json")
    out = S._sync_rows("schwab_roth_ira", "schwab_roth", [], object(), dry_run=True)
    assert out["status"] == "no_snapshot" and out["store_state"] == "unparseable"


def test_read_diff_on_absent_store_is_no_holdings_file(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "HOLDINGS_PATH", tmp_path / "missing.json")
    out = S._sync_rows("schwab_roth_ira", "schwab_roth", [], object(), dry_run=True)
    assert out["status"] == "no_holdings_file" and out["store_state"] == "absent"


# ── (b) WRITE path: no baseline at all -> refuse; a backup/candidate -> guards stay live ──

def test_write_without_any_baseline_is_refused(store):
    store.write_bytes(b"")
    out = S._sync_rows("schwab_roth_ira", "schwab_roth", [], object(), dry_run=False)
    assert out["status"] == "rejected_no_baseline" and out["wrote"] is False
    assert store.read_bytes() == b""          # nothing written over the damaged store


def test_write_uses_the_backup_baseline_and_preserves_other_accounts(store, monkeypatch):
    store.write_bytes(b"")
    _backup(store)
    new_roth = _row("BBB", "schwab_roth", 100, 41000.0)
    cash_roth = _row("CASH", "schwab_roth", 12500, 12500.0, cash=True)
    monkeypatch.setattr(S, "_build_account_rows", lambda label, live, existing: ([new_roth], []))
    monkeypatch.setattr(S, "_cash_rows_for_account", lambda label, hold, key, st: [cash_roth])
    out = S._sync_rows("schwab_roth_ira", "schwab_roth", [], object(), dry_run=False)
    assert out["wrote"] is True, out
    assert out["baseline_source"].startswith("backup:")
    doc = json.loads(store.read_text())
    accounts = {h["account"] for h in doc["holdings"]}
    assert {"schwab_taxable", "schwab_roth", "schwab_rollover_ira"} <= accounts, \
        "the write must not drop the accounts it did not sync"
    assert any(h["symbol"] == "BBB" and h["market_value"] == 41000.0 for h in doc["holdings"])


def test_write_that_drops_non_synced_accounts_is_refused(store, monkeypatch):
    store.write_bytes(b"")
    _backup(store)                            # baseline has all three governed accounts
    candidate = {"holdings": [_row("BBB", "schwab_roth", 100, 41000.0)]}   # only the synced account
    out = S.protected_holdings_write(candidate, source="test_drop", target_path=str(store),
                                     baseline=_book())
    assert out["wrote"] is False and out["reason_code"] == "INCOMPLETE_ACCOUNTS", out
    assert store.read_bytes() == b"", "a refused write must leave the store untouched"


def test_protected_write_uses_an_explicit_caller_baseline(store):
    store.write_bytes(b"")
    out = S.protected_holdings_write(_book(), source="test_caller", target_path=str(store), baseline=_book())
    assert out["wrote"] is True and out["baseline_source"] == "caller", out
    assert store.exists() and json.loads(store.read_text())["holdings"]


# ── P0 (cx-openai-2, 2026-11-03): the guard's baseline must be an INDEPENDENT snapshot ────

def _big_book():
    """1,040,000 total with 120,000 cash; the rollover account dominates, as in the review probe."""
    return {"holdings": [
        _row("AAA", "schwab_taxable", 100, 10000.0),
        _row("BBB", "schwab_roth", 80, 8000.0),
        _row("CASH", "schwab_roth", 2000, 2000.0, cash=True),
        _row("CCC", "schwab_rollover_ira", 9020, 902000.0),
        _row("CASH", "schwab_rollover_ira", 118000, 118000.0, cash=True),
    ]}


def test_baseline_is_an_independent_snapshot_of_the_live_store(store, monkeypatch):
    store.write_text(json.dumps(_book()))
    seen = {}

    def spy(cur, **kw):
        seen["cur"], seen["baseline"] = cur, kw.get("baseline")
        return {"wrote": False, "status": "spy"}

    monkeypatch.setattr(S, "protected_holdings_write", spy)
    monkeypatch.setattr(S, "_build_account_rows",
                        lambda label, live, existing: ([_row("BBB", "schwab_roth", 100, 41000.0)], []))
    monkeypatch.setattr(S, "_cash_rows_for_account", lambda *a: [])
    S._sync_rows("schwab_roth_ira", "schwab_roth", [], object(), dry_run=False)
    assert seen["baseline"] is not seen["cur"], "the guard must not receive the mutated candidate"
    original = {(h["symbol"], h["market_value"]) for h in seen["baseline"]["holdings"]}
    assert ("BBB", 40000.0) in original and ("BBB", 41000.0) not in original


def test_baseline_from_a_backup_is_independent_too(store, monkeypatch):
    store.write_bytes(b"")
    _backup(store, _book())
    seen = {}

    def spy(cur, **kw):
        seen["cur"], seen["baseline"] = cur, kw.get("baseline")
        return {"wrote": False, "status": "spy"}

    monkeypatch.setattr(S, "protected_holdings_write", spy)
    monkeypatch.setattr(S, "_build_account_rows",
                        lambda label, live, existing: ([_row("BBB", "schwab_roth", 100, 41000.0)], []))
    monkeypatch.setattr(S, "_cash_rows_for_account", lambda *a: [])
    S._sync_rows("schwab_roth_ira", "schwab_roth", [], object(), dry_run=False)
    assert seen["baseline"] is not seen["cur"]
    assert {h["symbol"] for h in seen["baseline"]["holdings"]} == {"AAA", "BBB", "CASH", "CCC"}


def test_re_aliasing_the_baseline_is_refused_not_written(store, monkeypatch):
    """If a future refactor makes cur and the baseline one object again, fail loudly before writing."""
    store.write_text(json.dumps(_book()))
    monkeypatch.setattr(S.copy, "deepcopy", lambda x: x)          # simulate the regression
    monkeypatch.setattr(S, "_build_account_rows",
                        lambda label, live, existing: ([_row("BBB", "schwab_roth", 100, 41000.0)], []))
    monkeypatch.setattr(S, "_cash_rows_for_account", lambda *a: [])
    before = store.read_bytes()
    with pytest.raises(RuntimeError, match="same object"):
        S._sync_rows("schwab_roth_ira", "schwab_roth", [], object(), dry_run=False)
    assert store.read_bytes() == before, "nothing may be written when the guard would be disarmed"


def _sync_with(store, monkeypatch, rows):
    monkeypatch.setattr(S, "_build_account_rows", lambda label, live, existing: (rows, []))
    monkeypatch.setattr(S, "_cash_rows_for_account", lambda *a: [])
    return S._sync_rows("schwab_rollover_ira", "schwab_rollover_ira", [], object(), dry_run=False)


def test_removing_the_rollover_cash_is_refused_cash_excluded(store, monkeypatch):
    store.write_bytes(b"")
    _backup(store, _big_book())
    before = store.read_bytes()
    out = _sync_with(store, monkeypatch, [_row("CCC", "schwab_rollover_ira", 9020, 902000.0)])
    assert out["wrote"] is False and out["reason_code"] == "CASH_EXCLUDED", out
    assert store.read_bytes() == before, "a refused write must leave the store byte-identical"


def test_collapsing_the_rollover_equity_is_refused_catastrophic_drop(store, monkeypatch):
    store.write_bytes(b"")
    _backup(store, _big_book())
    before = store.read_bytes()
    out = _sync_with(store, monkeypatch, [
        _row("CCC", "schwab_rollover_ira", 210, 21000.0),
        _row("CASH", "schwab_rollover_ira", 118000, 118000.0, cash=True),
    ])
    assert out["wrote"] is False and out["reason_code"] == "CATASTROPHIC_DROP", out
    assert store.read_bytes() == before


# ── P1 (cx-openai-2): shape-corrupt documents are 'no snapshot', never a crash ────────────

@pytest.mark.parametrize("payload", [
    '{"holdings": null}',
    '{"holdings": {"AAA": {}}}',
    '{"holdings": [1]}',
])
def test_shape_corrupt_store_is_no_snapshot_on_read(store, payload):
    store.write_text(payload)
    out = S._sync_rows("schwab_roth_ira", "schwab_roth", [], object(), dry_run=True)
    assert out["status"] == "no_snapshot" and out["wrote"] is False
    assert out["store_state"] == "shape_invalid"


def test_shape_corrupt_store_is_not_used_as_a_write_baseline(store, monkeypatch):
    store.write_text('{"holdings": [1]}')
    before = store.read_bytes()
    monkeypatch.setattr(S, "_build_account_rows",
                        lambda label, live, existing: ([_row("BBB", "schwab_roth", 100, 41000.0)], []))
    monkeypatch.setattr(S, "_cash_rows_for_account", lambda *a: [])
    out = S._sync_rows("schwab_roth_ira", "schwab_roth", [], object(), dry_run=False)
    assert out["wrote"] is False and out["status"] == "rejected_no_baseline", out
    assert store.read_bytes() == before


# ── cc3 (2026-11-03): the GUARD must enforce its own precondition, not trust the caller ─────

def test_the_guard_itself_refuses_a_baseline_that_is_the_candidate(store):
    """cc3's reproduction: without patching anything inside _sync_rows, calling the guard directly
    with the candidate as its own baseline used to return wrote:true and wipe the cash rows."""
    store.write_text(json.dumps(_book()))
    before = store.read_bytes()
    candidate = json.loads(store.read_text())
    candidate["holdings"] = [r for r in candidate["holdings"] if r.get("symbol") != "CASH"]
    out = S.protected_holdings_write(candidate, source="test_alias", target_path=str(store), baseline=candidate)
    assert out["wrote"] is False and out["reason_code"] == "BASELINE_ALIAS" and out["status"] == "rejected_baseline_alias", out
    assert store.read_bytes() == before, "an aliased-baseline refusal must leave the store untouched"


def test_the_same_payload_with_an_independent_baseline_is_refused_by_the_cash_guard(store):
    """The control: the identical candidate against a distinct baseline hits the real guard."""
    store.write_text(json.dumps(_book()))
    before = store.read_bytes()
    candidate = json.loads(store.read_text())
    candidate["holdings"] = [r for r in candidate["holdings"] if r.get("symbol") != "CASH"]
    out = S.protected_holdings_write(candidate, source="test_control", target_path=str(store),
                                     baseline=json.loads(before))
    assert out["wrote"] is False and out["reason_code"] == "CASH_EXCLUDED", out
    assert store.read_bytes() == before


def test_a_write_to_an_alternate_path_never_runs_the_live_side_effects(store, monkeypatch):
    """2026-11-03 incident: a temp-target probe still committed watchlist changes to the live DB.
    The side-effect block is one named hook, and it does not run for a non-canonical target."""
    calls = []
    monkeypatch.setattr(S, "_post_write_side_effects", lambda *a, **k: calls.append(k))
    store.write_text(json.dumps(_book()))          # a healthy store, written to itself
    out = S.protected_holdings_write(_book(), source="test_alt_path", target_path=str(store))
    assert out["wrote"] is True, out
    assert calls == [], "a temp/alternate target must never reach the live watchlist or transfer tables"


def test_a_shallow_copy_baseline_is_the_same_bypass_and_is_refused(store):
    """dict(candidate) shares the holdings list that is then mutated (cc3 residual, 2026-11-03)."""
    store.write_text(json.dumps(_book()))
    before = store.read_bytes()
    candidate = json.loads(store.read_text())
    candidate["holdings"] = [r for r in candidate["holdings"] if r.get("symbol") != "CASH"]
    shallow = dict(candidate)
    out = S.protected_holdings_write(candidate, source="test_shallow", target_path=str(store), baseline=shallow)
    assert out["wrote"] is False and out["reason_code"] == "BASELINE_ALIAS", out
    assert store.read_bytes() == before


def test_an_equal_but_independent_baseline_is_not_refused(store):
    """Identity, not equality: the same book in a separate object is a legitimate write."""
    store.write_text(json.dumps(_book()))
    candidate = json.loads(store.read_text())
    independent = json.loads(store.read_text())
    out = S.protected_holdings_write(candidate, source="test_equal", target_path=str(store), baseline=independent)
    assert out["wrote"] is True, out


# ── cx-openai-2 third P0 (2026-11-03): an EMPTY baseline disables the guards lawfully ──────

def test_an_empty_list_primary_is_not_a_baseline_for_the_sync(store, monkeypatch):
    """Primary {"holdings": []} + a complete backup: the sync must not write a one-position book."""
    store.write_text(json.dumps({"holdings": [], "as_of": "2026-11-03"}))
    _backup(store, _big_book())
    before = store.read_bytes()
    monkeypatch.setattr(S, "_build_account_rows",
                        lambda label, live, existing: ([_row("CCC", "schwab_rollover_ira", 10, 1000.0)], []))
    monkeypatch.setattr(S, "_cash_rows_for_account", lambda *a: [])
    out = S._sync_rows("schwab_rollover_ira", "schwab_rollover_ira", [], object(), dry_run=False)
    assert out["wrote"] is False, out
    assert store.read_bytes() == before, "an unusable baseline must not lead to a write"


def test_an_empty_caller_baseline_cannot_silence_the_coverage_guard(store):
    """A healthy complete primary + baseline={} used to replace every other account."""
    store.write_text(json.dumps(_big_book()))
    before = store.read_bytes()
    candidate = {"holdings": [_row("BBB", "schwab_roth", 10, 1000.0)]}
    out = S.protected_holdings_write(candidate, source="test_empty_baseline",
                                     target_path=str(store), baseline={})
    assert out["wrote"] is False and out["reason_code"] == "INCOMPLETE_ACCOUNTS", out
    assert store.read_bytes() == before


def test_a_nested_alias_is_still_the_same_bypass(store):
    """cc3 fifth boundary: {"holdings": list(cand["holdings"])} shares the row objects."""
    store.write_text(json.dumps(_big_book()))
    before = store.read_bytes()
    book = json.loads(store.read_text())
    cand = json.loads(store.read_text())
    for row in cand["holdings"]:
        if row.get("is_cash") or row.get("symbol") == "CASH":
            row["market_value"] = 0.0
        else:
            row["market_value"] = round((row.get("market_value") or 0) * 0.05, 2)
    nested = {"holdings": list(cand["holdings"])}
    nested["portfolio_totals"] = dict(cand.get("portfolio_totals") or {})
    out = S.protected_holdings_write(cand, source="test_nested_alias", target_path=str(store), baseline=nested)
    assert out["wrote"] is False and out["reason_code"] == "BASELINE_ALIAS", out
    assert store.read_bytes() == before


# ── (c) the baseline substitute must be RECENT, and an absent store is still a bootstrap ─────────
# claude-lead BLOCK on #2543 (2026-11-05): on this host the newest backup was two weeks old, so a
# repeat of the 11-03 zero-byte store would have written every other account's 10-22 rows back into
# the live book — with the relative guards comparing the candidate against that same stale document.

import os  # noqa: E402
import time  # noqa: E402


def test_a_stale_backup_is_not_a_baseline_and_the_write_fails_closed(store, monkeypatch):
    store.write_bytes(b"")
    bak = _backup(store)
    old = time.time() - 14 * 24 * 3600            # the 2-week-old backup the BLOCK measured on this host
    os.utime(bak, (old, old))
    before = store.read_bytes()
    monkeypatch.setattr(S, "_build_account_rows",
                        lambda label, live, existing: ([_row("BBB", "schwab_roth", 100, 41000.0)], []))
    out = S._sync_rows("schwab_roth_ira", "schwab_roth", [], object(), dry_run=False)
    assert out["status"] == "rejected_no_baseline" and out["wrote"] is False, out
    assert out["store_state"] == "empty"
    assert "younger than 24h" in out["reason"], out
    assert store.read_bytes() == before, "a stale baseline must never reach the store"


def test_a_fresh_backup_is_still_used(store, monkeypatch):
    """The age bound must not remove the recovery path it bounds."""
    store.write_bytes(b"")
    bak = _backup(store)
    recent = time.time() - 3600                   # one hour old
    os.utime(bak, (recent, recent))
    monkeypatch.setattr(S, "_build_account_rows",
                        lambda label, live, existing: ([_row("BBB", "schwab_roth", 100, 41000.0)], []))
    monkeypatch.setattr(S, "_cash_rows_for_account",
                        lambda label, hold, key, st: [_row("CASH", "schwab_roth", 12500, 12500.0, cash=True)])
    out = S._sync_rows("schwab_roth_ira", "schwab_roth", [], object(), dry_run=False)
    assert out["wrote"] is True and out["baseline_source"].startswith("backup:"), out


def test_an_absent_store_is_still_a_bootstrap_for_sane_payload(tmp_path, monkeypatch):
    """claude-lead BLOCK on #2543: the backup rule refused every first-time protected_holdings_write
    caller (there is no store and no backup). An absent store has no book to protect, so it keeps
    the pre-PR behaviour; a store that EXISTS but is damaged still fails closed."""
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(S, "HOLDINGS_PATH", missing)
    ok, why = S.sane_payload(_book())
    assert ok is True, why


def test_a_damaged_store_still_refuses_sane_payload_without_a_fresh_backup(store):
    store.write_bytes(b"")
    ok, why = S.sane_payload(_book())
    assert ok is False and "NO_BASELINE" in why and "younger than 24h" in why, why


# ── (d) the refusal names the age, the ceiling is config, and the guard is never asked with a stale book ──

def test_the_refusal_says_how_old_the_newest_backup_is(store, monkeypatch):
    """claude-lead BLOCK on #2543: fail closed and LOUDLY. "no backup younger than 24h" cannot tell an
    operator whether one from last night exists (wait for the next sync) or the newest is a fortnight old
    (the store needs a restore decision) — the refusal must carry the age it measured."""
    store.write_bytes(b"")
    bak = _backup(store)
    old = time.time() - 14 * 24 * 3600
    os.utime(bak, (old, old))
    records = []
    monkeypatch.setattr(S, "_record", lambda key, kind, msg="": records.append((key, kind, msg)))
    monkeypatch.setattr(S, "_build_account_rows",
                        lambda label, live, existing: ([_row("BBB", "schwab_roth", 100, 41000.0)], []))
    out = S._sync_rows("schwab_roth_ira", "schwab_roth", [], object(), dry_run=False)
    assert out["status"] == "rejected_no_baseline", out
    assert "336.0h old" in out["reason"], out["reason"]
    ok, why = S.sane_payload(_book())
    assert ok is False and "336.0h old" in why, why
    assert [r for r in records if r[1] == "rejected_no_baseline"], records


def test_the_guard_is_never_asked_with_a_stale_book(store, monkeypatch):
    """The finding's core: with the stale backup as the baseline the relative guards compared the
    candidate against that same document, so they could not fire. A stale baseline must not reach
    ``validate_payload`` at all — there is nothing trustworthy to compare against."""
    store.write_bytes(b"")
    bak = _backup(store)
    old = time.time() - 14 * 24 * 3600
    os.utime(bak, (old, old))
    seen = []
    monkeypatch.setattr(S, "validate_payload", lambda cand, base: seen.append(base) or types.SimpleNamespace(
        ok=True, reason_code="OK", reason=""))
    monkeypatch.setattr(S, "_build_account_rows",
                        lambda label, live, existing: ([_row("BBB", "schwab_roth", 100, 41000.0)], []))
    out = S._sync_rows("schwab_roth_ira", "schwab_roth", [], object(), dry_run=False)
    assert out["status"] == "rejected_no_baseline", out
    assert seen == [], f"the guard was asked with {seen}"


def test_the_age_ceiling_comes_from_config(tmp_path):
    """The ceiling is ``positions.baseline_max_age_hours`` — a sync-cadence change or an operator
    decision to tolerate a longer substitute is a config edit, not a code change."""
    import yaml
    cfg = tmp_path / "p.yaml"
    cfg.write_text(yaml.safe_dump({"positions": {"baseline_max_age_hours": 6}}), encoding="utf-8")
    assert S._baseline_max_age_hours(cfg) == 6.0
    for bad in ({"positions": {"baseline_max_age_hours": 0}},
                {"positions": {"baseline_max_age_hours": -3}},
                {"positions": {"baseline_max_age_hours": "not-a-number"}},
                {"positions": {}},
                {}):
        cfg.write_text(yaml.safe_dump(bad), encoding="utf-8")
        assert S._baseline_max_age_hours(cfg) == S.BASELINE_BACKUP_MAX_AGE_HOURS, bad
    assert S._baseline_max_age_hours(tmp_path / "absent.yaml") == S.BASELINE_BACKUP_MAX_AGE_HOURS
    # The default is the repo's own freshness contract for this store, not a number invented here.
    from state_freshness_writer import EXPECTED_MAX_AGE_HOURS
    assert S.BASELINE_BACKUP_MAX_AGE_HOURS == float(EXPECTED_MAX_AGE_HOURS["holdings.json"])


def test_the_configured_ceiling_governs_the_recovery(store, monkeypatch):
    """A 12 h backup is fine at the 24 h default and refused under a 6 h ceiling — proving the wiring,
    not just the loader."""
    store.write_bytes(b"")
    bak = _backup(store)
    recent = time.time() - 12 * 3600
    os.utime(bak, (recent, recent))
    monkeypatch.setattr(S, "_build_account_rows",
                        lambda label, live, existing: ([_row("BBB", "schwab_roth", 100, 41000.0)], []))
    monkeypatch.setattr(S, "_cash_rows_for_account",
                        lambda label, hold, key, st: [_row("CASH", "schwab_roth", 12500, 12500.0, cash=True)])
    assert S._baseline_from_backups()[0] is not None
    monkeypatch.setattr(S, "_baseline_max_age_hours", lambda *a, **k: 6.0)
    out = S._sync_rows("schwab_roth_ira", "schwab_roth", [], object(), dry_run=False)
    assert out["status"] == "rejected_no_baseline", out


def test_disabling_the_bound_is_explicit(store):
    """``None`` means "the configured ceiling"; disabling is ``float("inf")`` — documented, explicit,
    and never the default a scheduled run gets by forgetting an argument."""
    store.write_bytes(b"")
    bak = _backup(store)
    old = time.time() - 14 * 24 * 3600
    os.utime(bak, (old, old))
    assert S._baseline_from_backups()[0] is None
    assert S._baseline_from_backups(max_age_hours=float("inf"))[0] is not None
