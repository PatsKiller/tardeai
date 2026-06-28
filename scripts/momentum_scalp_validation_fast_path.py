#!/usr/bin/env python3
"""Momentum Scalp VALIDATION fast path — canonical operator-facing module.

Terminology note: "validation execution" is the operator-facing term for sandbox/simulated
strategy-sample collection used to build the empirical sample before promotion. It has nothing to
do with operator approval or live trading. Some legacy storage/adapters still use ``paper_*`` names
(e.g. the paper_trades table, proposal_paper_submitter, the alpaca_paper sandbox account) for
backward compatibility — but the canonical TradeAI lifecycle term is VALIDATION, not paper.

This module is a thin canonical wrapper over the existing deterministic gate logic in
``momentum_scalp_paper_fast_path`` (the legacy filename). It re-uses the EXACT same gates — nothing
is weakened — and adds cadence-safe scheduling. Validation execution is sandbox/simulated only and
never routes to a live broker submit. Live trading is unchanged (operator confirmation + 2FA).

    python3 scripts/momentum_scalp_validation_fast_path.py --dry-run        # read-only (default)
    python3 scripts/momentum_scalp_validation_fast_path.py --submit-sandbox # gate-pass → sandbox submit
    python3 scripts/momentum_scalp_validation_fast_path.py --loop --sleep-seconds 120 --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# Reuse the legacy module's gate logic verbatim (single source of truth; no safety divergence).
import momentum_scalp_paper_fast_path as _legacy  # noqa: E402

SOURCE_TAG = "momentum_scalp_validation_fast_path"

# Canonical aliases for the deterministic evaluator / runner (same gates, same safety).
evaluate_validation_fast_path = _legacy.evaluate_paper_fast_path
submission_allowed = _legacy.submission_allowed


def _to_validation_taxonomy(rep: dict) -> dict:
    """Map the legacy run() result onto canonical validation field names (legacy kept as aliases)."""
    if not rep or not rep.get("ok"):
        return rep
    out = dict(rep)
    out["validation_fast_path"] = True
    out["sandbox_account"] = _legacy.PAPER_ACCOUNT      # alpaca_paper = sandbox validation account
    out["would_submit_validation"] = rep.get("would_submit_paper")
    out["validation_submitted_symbols"] = rep.get("paper_submitted_symbols")
    out["source_tag"] = SOURCE_TAG
    out["legacy_aliases"] = {
        "paper_fast_path": "validation_fast_path",
        "would_submit_paper": "would_submit_validation",
        "paper_submitted_symbols": "validation_submitted_symbols",
    }
    out["note"] = ("Deterministic VALIDATION fast path (sandbox/simulated). NO human validation "
                   "approval — gates replace it. Sandbox-only via the existing safe submitter; never "
                   "the live broker path. Quote-freshness/TTL/window/liquidity/route/risk gates "
                   "unchanged. Operator confirmation / 2FA unchanged. Large-float scouts + social-only "
                   "are excluded.")
    return out


def run(dry_run: bool = True) -> dict:
    """Run one validation fast-path pass (canonical wrapper over the legacy gate runner)."""
    return _to_validation_taxonomy(_legacy.run(dry_run=dry_run))


def validation_quality_gate(candidate: dict, cfg: dict = None) -> dict:
    """P0-6: deterministic pre-submit QUALITY gates (improve sample quality, not just quantity).

    Cannot be overridden by an LLM. Unknown CRITICAL data → DEFER_DATA_UNKNOWN (never submit);
    unknown non-critical data → WARN_DATA_MISSING (allowed). Returns
    {decision: PASS|REJECT|DEFER, reason_codes, warnings}. Pure/testable.
    """
    cfg = cfg or {}
    max_spread = float(cfg.get("max_spread_pct", 5.0))
    rc, warns = [], []

    def num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    # Hard rejects (deterministic).
    spread = num(candidate.get("spread_pct"))
    if spread is not None and spread > max_spread:
        rc.append(f"SPREAD_TOO_WIDE({spread:.1f}%>{max_spread:.1f}%)")
        return {"decision": "REJECT", "reason_codes": rc, "warnings": warns}
    if candidate.get("halted") is True:
        rc.append("RECENT_HALT"); return {"decision": "REJECT", "reason_codes": rc, "warnings": warns}
    if candidate.get("reverse_split_recent") is True and not candidate.get("reverse_split_allowed"):
        rc.append("RECENT_REVERSE_SPLIT"); return {"decision": "REJECT", "reason_codes": rc, "warnings": warns}
    if candidate.get("offering_dilution_risk") is True:
        rc.append("OFFERING_DILUTION_RISK"); return {"decision": "REJECT", "reason_codes": rc, "warnings": warns}
    if candidate.get("same_sector_open") is True:
        rc.append("SAME_SECTOR_CONCENTRATION"); return {"decision": "REJECT", "reason_codes": rc, "warnings": warns}
    rr = num(candidate.get("rr"))
    if rr is not None and rr < 1.5:
        rc.append(f"RR_BELOW_MIN({rr:.2f})"); return {"decision": "REJECT", "reason_codes": rc, "warnings": warns}

    # Critical unknowns → DEFER (never submit on unknown high-risk data).
    if spread is None and candidate.get("liquidity_known") is False:
        rc.append("DEFER_DATA_UNKNOWN:spread+liquidity")
        return {"decision": "DEFER", "reason_codes": rc, "warnings": warns}
    if candidate.get("catalyst_still_valid") is False:
        rc.append("DEFER_DATA_UNKNOWN:catalyst_stale")
        return {"decision": "DEFER", "reason_codes": rc, "warnings": warns}

    # Non-critical missing data → WARN (allowed).
    if candidate.get("sector") in (None, ""):
        warns.append("WARN_DATA_MISSING:sector")
    if rr is not None and rr < 2.0:
        warns.append("RR_BELOW_PREFERRED(<2.0)")

    rc.append("QUALITY_GATES_PASS")
    return {"decision": "PASS", "reason_codes": rc, "warnings": warns}


def heartbeat(rep: dict) -> str:
    """One-line operator heartbeat: candidates / passes / submitted / deferred / rejected + top reasons."""
    if not rep.get("ok"):
        return f"validation fast-path: WARN ({rep.get('note', 'unavailable')})"
    from collections import Counter
    reasons = Counter()
    for c in rep.get("candidates", []):
        for rc in (c.get("reason_codes") or []):
            if rc != "ALL_GATES_PASS":
                reasons[rc] += 1
    top = ", ".join(f"{k}:{v}" for k, v in reasons.most_common(3)) or "—"
    return (f"validation fast-path [{rep.get('mode')}]: candidates={rep.get('candidates_evaluated')} "
            f"gate_pass={rep.get('would_submit_validation')} submitted={len(rep.get('validation_submitted_symbols') or [])} "
            f"deferred={rep.get('would_defer')} rejected={rep.get('would_reject')} | top_reject={top}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Momentum Scalp validation fast path (sandbox/simulated)")
    ap.add_argument("--dry-run", action="store_true", help="read-only (default)")
    ap.add_argument("--submit-sandbox", action="store_true", help="gate-pass → sandbox validation submit")
    ap.add_argument("--once", action="store_true", help="run a single pass (default)")
    ap.add_argument("--loop", action="store_true", help="run repeatedly (cadence-safe; idempotent)")
    ap.add_argument("--sleep-seconds", type=int, default=120, help="loop interval (default 120s)")
    ap.add_argument("--max-iterations", type=int, default=0, help="loop cap (0 = unbounded)")
    args = ap.parse_args()

    # Default and loop default to dry-run; sandbox submit must be EXPLICIT.
    dry = not args.submit_sandbox

    def _pass():
        rep = run(dry_run=dry)
        print(heartbeat(rep) if (args.loop) else json.dumps(rep, indent=2, default=str))
        return rep

    if not args.loop:
        _pass()
        return 0
    i = 0
    while True:
        _pass()
        i += 1
        if args.max_iterations and i >= args.max_iterations:
            break
        try:
            time.sleep(max(30, int(args.sleep_seconds)))
        except KeyboardInterrupt:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
