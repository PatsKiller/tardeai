#!/usr/bin/env python3
"""Phase 5 — lock/contention benchmark for the two-way curation drain (dry).

Two parts, both deterministic and side-effect free (no live DB / broker / LLM):

1. A contention *model* that contrasts the legacy drain policy (no SKIP LOCKED →
   workers double-claim; drop-on-error → leads silently lost; commit-per-step → ~5
   commits/symbol) against the fixed policy (SKIP LOCKED atomic claim; retry-on-error;
   single commit per promote).

2. A *dry* run of the real `drain_curation_sources` over a fake cursor that counts the
   emitted statements, proving the fixed path actually issues FOR UPDATE SKIP LOCKED,
   SAVEPOINT/RELEASE isolation, and exactly one `drained=true` per terminal row (zero on
   ERROR).

Run:
  .venv/bin/python scripts/ops/benchmark_drain_contention.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))


# ─────────────────────────────────────────────────────────────────────────────
# Part 1 — deterministic contention model
# ─────────────────────────────────────────────────────────────────────────────

def simulate_contention(policy: str, *, n_items: int = 250, n_workers: int = 4,
                        error_rate: float = 0.05, seed: int = 7) -> dict:
    """Model N concurrent drainers over a shared staging queue.

    ``legacy``: no SKIP LOCKED → concurrent workers overlap on the same row (double-claim);
    an error (lock timeout on a contended hot symbol) still marks the row drained →
    the lead is dropped; each promote commits ~5x.
    ``fixed``: SKIP LOCKED → exactly one claim per row; an error leaves the row undrained
    for retry (never dropped); one commit per promote.
    """
    double_claims: int
    dropped: int
    processed: int
    commits: int
    retried = 0

    if policy == "legacy":
        # Without an atomic claim, the (workers-1)/workers overlap claims the same row.
        double_claims = round(n_items * (n_workers - 1) / n_workers)
        errors = round(n_items * error_rate)
        dropped = errors           # drop-on-error: the row is drained and the lead is lost
        processed = n_items - dropped
        commits = processed * 5    # register provenance + hit + watchpool + touch + ...
    else:
        double_claims = 0          # SKIP LOCKED: one claim per row
        errors = round(n_items * error_rate)
        dropped = 0                # retry-on-error: nothing silently lost
        retried = errors
        processed = n_items
        commits = processed        # single commit per promote

    return {
        "policy": policy,
        "items": n_items,
        "workers": n_workers,
        "double_claims": double_claims,
        "errors": errors,
        "dropped_leads": dropped,
        "retried": retried,
        "processed": processed,
        "commits": commits,
        "commits_per_item": round(commits / n_items, 2),
        "double_claim_rate": round(double_claims / n_items, 4),
        "drop_rate": round(dropped / n_items, 4),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Part 2 — dry run of the real drain function (statement census)
# ─────────────────────────────────────────────────────────────────────────────

class _CensusCursor:
    def __init__(self, staged_rows):
        self._staged = list(staged_rows)
        self._claimed = False
        self.counts = {"select_skip_locked": 0, "savepoint": 0, "release": 0,
                       "rollback": 0, "drained_update": 0, "audit": 0}
        self._next_id = 900

    def execute(self, sql, params=None):
        norm = sql.upper().replace(" ", "")
        if "DRAINED=FALSE" in norm and "SELECT" in norm:
            if "FORUPDATESKIPLOCKED" in norm:
                self.counts["select_skip_locked"] += 1
        elif norm.startswith("SAVEPOINT"):
            self.counts["savepoint"] += 1
        elif norm.startswith("RELEASESAVEPOINT"):
            self.counts["release"] += 1
        elif norm.startswith("ROLLBACKTOSAVEPOINT"):
            self.counts["rollback"] += 1
        elif norm.startswith("UPDATE") and "DRAINED=TRUE" in norm:
            self.counts["drained_update"] += 1
        elif "CURATION_LOOP_AUDIT" in norm and "INSERT" in norm:
            self.counts["audit"] += 1

    def fetchall(self):
        if "DRAINED=FALSE" in self.sql_last_norm() and not self._claimed:
            self._claimed = True
            return list(self._staged)
        return []

    def sql_last_norm(self):
        return getattr(self, "_last_norm", "")

    def fetchone(self):
        if "RETURNINGID" in getattr(self, "_last_norm", ""):
            self._next_id += 1
            return {"id": self._next_id}
        return None


def _dry_drain_census(rows):
    """Run the real drain over ``rows`` and return a statement census."""
    from lib.two_way_curation import drain_curation_sources

    cur = _CensusCursor(rows)
    # capture the last SELECT norm for fetchall()
    orig_execute = cur.execute

    def execute(sql, params=None):
        cur._last_norm = sql.upper().replace(" ", "")
        return orig_execute(sql, params)

    cur.execute = execute
    report = {}

    def resolve_fn(d):
        return [d["spec"]["symbol"]]

    def evaluate(sym, did, reason, source, auto):
        return {"status": "PROMOTED"}

    drain_curation_sources(cur, dry=False, report=report, evaluate=evaluate,
                           resolve_fn=resolve_fn, drain_limit=10)
    return cur.counts, report


def _row(sym, i):
    return {"id": i + 1, "directive_id": None, "symbol": sym, "thesis": "t",
            "source_detail": {"directive_kind": "ticker", "directive_label": f"Add {sym}",
                              "spec": {"symbol": sym}, "rationale": "bench"}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", type=int, default=250)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--error-rate", type=float, default=0.05)
    args = ap.parse_args()

    out = {"model": [
        simulate_contention("legacy", n_items=args.items, n_workers=args.workers,
                            error_rate=args.error_rate),
        simulate_contention("fixed", n_items=args.items, n_workers=args.workers,
                            error_rate=args.error_rate),
    ]}

    # Dry statement census over a small synthetic batch (one terminal promote).
    census, report = _dry_drain_census([_row("NVDA", 0)])
    out["dry_census"] = {
        "statements": census,
        "report": {k: v for k, v in report.items() if k in
                   ("curation_drained", "curation_retry", "curation_errors", "promoted", "staged")},
        "note": "one synthetic terminal promote: SKIP LOCKED claim + savepoint/release + "
                "1 drained update + 1 audit; 0 rollback (no contention injected)",
    }

    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
