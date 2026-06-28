#!/usr/bin/env python3
"""Evidence-bound approval revalidation — like-to-like hash methodology (P0-2).

Each regenerated bundle hash is compared ONLY against the stored hash of the same
bundle type. The overall approval-evidence hash is never compared against a single
bundle hash. Runs under pytest (assert-based) and standalone (__main__ runner).
"""
import datetime as dt
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")
    assert cond, f"{name} {detail}"


def _clear_killswitch():
    return mock.patch("brokers.kill_switches.is_blocked", return_value=(False, []))


def _rec(**over):
    """Build an approval record with distinct, separate bundle hashes."""
    from brokers import evidence_approval as ea
    readiness_snap = {"ok": True, "evidence_hash": "READINESS_HASH_AAA"}
    risk_snap = {"net_delta": 0.1, "buying_power": 50000}
    chain_snap = {"occ": "V250101C00100000", "as_of": "t0"}
    quote_snap = {"mid": 1.0}
    hashes = ea.compute_bundle_hashes(
        readiness_snapshot=readiness_snap, risk_snapshot=risk_snap,
        chain_snapshot=chain_snap, quote_snapshot=quote_snap,
    )
    rec = {
        "id": 1, "intent_id": "i1", "evidence_hash": hashes["approval_evidence_hash"],
        "hashes": hashes, "used_at": None,
        "expires_at": dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10),
        "quote_snapshot": quote_snap, "risk_snapshot": risk_snap, "chain_snapshot": chain_snap,
        "readiness_snapshot": readiness_snap,
        "_risk_snap": risk_snap, "_chain_snap": chain_snap,
    }
    rec.update(over)
    return rec


def test_passes_when_identical_evidence_regenerated():
    from brokers import evidence_approval as ea
    rec = _rec()
    with mock.patch.object(ea, "fetch_approval", return_value=rec), _clear_killswitch():
        r = ea.revalidate_before_submit(
            "i1",
            current_quote={"mid": 1.0},
            current_readiness={"ok": True, "evidence_hash": "READINESS_HASH_AAA"},
            current_risk=rec["_risk_snap"],
            current_chain=rec["_chain_snap"],
        )
    check("identical evidence passes", r.get("ok") is True, r.get("reason", ""))


def test_does_not_compare_unrelated_hash_types():
    """The crux: approval_evidence_hash != readiness_hash, yet a matching readiness
    bundle must PASS. The prior bug compared readiness hash to the overall hash."""
    from brokers import evidence_approval as ea
    rec = _rec()
    check("overall != readiness hash",
          rec["hashes"]["approval_evidence_hash"] != rec["hashes"]["readiness_hash"])
    with mock.patch.object(ea, "fetch_approval", return_value=rec), _clear_killswitch():
        r = ea.revalidate_before_submit(
            "i1", current_quote={"mid": 1.0},
            current_readiness={"ok": True, "evidence_hash": "READINESS_HASH_AAA"},
            current_risk=rec["_risk_snap"], current_chain=rec["_chain_snap"],
        )
    check("no false block from cross-type hash compare", r.get("ok") is True, r.get("reason", ""))


def test_blocks_when_quote_moves_beyond_tolerance():
    from brokers import evidence_approval as ea
    rec = _rec()
    with mock.patch.object(ea, "fetch_approval", return_value=rec), _clear_killswitch():
        r = ea.revalidate_before_submit("i1", current_quote={"mid": 1.05},
                                        current_readiness={"ok": True, "evidence_hash": "READINESS_HASH_AAA"})
    check("quote move blocks", not r["ok"] and "quote_moved" in r.get("reason", ""))


def test_blocks_when_risk_state_changes():
    from brokers import evidence_approval as ea
    rec = _rec()
    with mock.patch.object(ea, "fetch_approval", return_value=rec), _clear_killswitch():
        r = ea.revalidate_before_submit(
            "i1", current_quote={"mid": 1.0},
            current_readiness={"ok": True, "evidence_hash": "READINESS_HASH_AAA"},
            current_risk={"net_delta": 0.9, "buying_power": 1000})
    check("risk change blocks", not r["ok"] and r.get("reason") == "risk_state_changed")


def test_blocks_when_readiness_changes_to_hard_block():
    from brokers import evidence_approval as ea
    rec = _rec()
    with mock.patch.object(ea, "fetch_approval", return_value=rec), _clear_killswitch():
        r = ea.revalidate_before_submit("i1", current_quote={"mid": 1.0},
                                        current_readiness={"ok": False, "hard_blocks": [{"reason": "x"}]})
    check("readiness hard block blocks", not r["ok"] and r.get("reason") == "readiness_changed_to_block")


def test_blocks_when_readiness_hash_changes():
    from brokers import evidence_approval as ea
    rec = _rec()
    with mock.patch.object(ea, "fetch_approval", return_value=rec), _clear_killswitch():
        r = ea.revalidate_before_submit("i1", current_quote={"mid": 1.0},
                                        current_readiness={"ok": True, "evidence_hash": "DIFFERENT_HASH"})
    check("readiness hash change blocks", not r["ok"] and r.get("reason") == "readiness_hash_changed")


def test_blocks_when_chain_changes_materially():
    from brokers import evidence_approval as ea
    rec = _rec()
    with mock.patch.object(ea, "fetch_approval", return_value=rec), _clear_killswitch():
        r = ea.revalidate_before_submit(
            "i1", current_quote={"mid": 1.0},
            current_readiness={"ok": True, "evidence_hash": "READINESS_HASH_AAA"},
            current_chain={"occ": "DIFFERENT", "as_of": "t9"})
    check("chain change blocks", not r["ok"] and r.get("reason") == "chain_changed_materially")


def test_blocks_when_approval_reused():
    from brokers import evidence_approval as ea
    rec = _rec(used_at=dt.datetime.now(dt.timezone.utc))
    with mock.patch.object(ea, "fetch_approval", return_value=rec):
        r = ea.revalidate_before_submit("i1")
    check("single use blocks replay", not r["ok"] and "used" in r.get("reason", ""))


def test_blocks_when_expired():
    from brokers import evidence_approval as ea
    rec = _rec(expires_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1))
    with mock.patch.object(ea, "fetch_approval", return_value=rec):
        r = ea.revalidate_before_submit("i1")
    check("expired blocks", not r["ok"] and "expired" in r.get("reason", ""))


def test_blocks_when_kill_switch_after_approval():
    from brokers import evidence_approval as ea
    rec = _rec()
    with mock.patch.object(ea, "fetch_approval", return_value=rec):
        with mock.patch("brokers.kill_switches.is_blocked", return_value=(True, ["kill_switch:global"])):
            r = ea.revalidate_before_submit("i1", current_quote={"mid": 1.0},
                                            current_readiness={"ok": True, "evidence_hash": "READINESS_HASH_AAA"})
    check("kill switch after approval blocks", not r["ok"] and "kill_switch" in r.get("reason", ""))


def test_blocks_when_readiness_missing_fail_closed():
    from brokers import evidence_approval as ea
    rec = _rec()
    with mock.patch.object(ea, "fetch_approval", return_value=rec):
        r = ea.revalidate_before_submit("i1", current_quote={"mid": 1.0})
    check("missing readiness fails closed", not r["ok"] and "fail_closed" in r.get("reason", ""))


def test_blocks_when_no_approval():
    from brokers import evidence_approval as ea
    with mock.patch.object(ea, "fetch_approval", return_value=None):
        r = ea.revalidate_before_submit("nope")
    check("no approval blocks", not r["ok"] and r.get("reason") == "no_evidence_bound_approval")


ALL = [
    test_passes_when_identical_evidence_regenerated,
    test_does_not_compare_unrelated_hash_types,
    test_blocks_when_quote_moves_beyond_tolerance,
    test_blocks_when_risk_state_changes,
    test_blocks_when_readiness_changes_to_hard_block,
    test_blocks_when_readiness_hash_changes,
    test_blocks_when_chain_changes_materially,
    test_blocks_when_approval_reused,
    test_blocks_when_expired,
    test_blocks_when_kill_switch_after_approval,
    test_blocks_when_readiness_missing_fail_closed,
    test_blocks_when_no_approval,
]


if __name__ == "__main__":
    print("\n— evidence bound approval (like-to-like hashes) —")
    for t in ALL:
        try:
            t()
        except AssertionError:
            pass
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)
