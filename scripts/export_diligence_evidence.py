#!/usr/bin/env python3
"""Export diligence evidence pack — no broker writes."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run_json(cmd: list[str]) -> dict:
    try:
        proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=120)
        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr[:300]}
        return json.loads(proc.stdout)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def export_pack(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    state = _run_json(["python3", "scripts/execution_state.py", "--json"])
    readiness_sample = {"note": "per-intent evaluation via GET /api/v2/execution/readiness"}
    release = _run_json(["python3", "scripts/validate_release_readiness.py", "--json", "--skip-build"])
    kill = {}
    try:
        from brokers.kill_switches import status
        kill = status()
    except Exception as e:
        kill = {"error": str(e)}

    files = {}

    files["CONTROL_MATRIX.md"] = """# Control Matrix

| Control | Owner | Fail mode |
|---------|-------|-----------|
| Global live allowed | Operator env + DB | Fail closed |
| Broker policy | Commit + DB arm | Fail closed |
| Execution readiness | `execution_readiness.py` | Hard block |
| Kill switches | `kill_switches.py` | Hard block |
| Evidence-bound approval | `evidence_approval.py` | Single-use + expiry |
| Broker truth | `order_lifecycle.py` | No live before ack |
| Audit ledger | `audit_ledger.py` | Append-only hash chain |
| LLM role | Advisory only | Never unlocks live |

**LLMs are advisory only.** They may not set policy, DB arm, approval, kill switch, or live eligibility.
"""

    files["CURRENT_EXECUTION_STATE.md"] = subprocess.run(
        ["python3", "scripts/execution_state.py", "--markdown"],
        cwd=ROOT, text=True, capture_output=True, timeout=60,
    ).stdout or "# unavailable\n"

    files["RELEASE_READINESS.md"] = f"""# Release Readiness

```json
{json.dumps(release, indent=2)}
```
"""

    files["RISK_GATE_MATRIX.md"] = """# Risk Gate Matrix

Hard blocks (live path): earnings_blackout, ex_dividend_cc_risk, bs_estimate_only, no_resolved_occ,
oi_below_threshold, volume_below_threshold, spread_too_wide, quote_stale, option_chain_stale,
market_closed, max_contracts_per_order, max_per_strategy_notional, max_net_delta_pct,
max_symbol_notional_pct, assignment_exercise_risk.

Configured in `assets/portfolio_intent.yaml` → `options_desk_settings.hard_risk_limits`.
"""

    files["ORDER_LIFECYCLE.md"] = """# Order Lifecycle

States: PROPOSED → PREFLIGHTED → OPERATOR_APPROVED → SUBMIT_REQUESTED → BROKER_ACKED →
WORKING → PARTIALLY_FILLED → FILLED (or CANCELLED / REJECTED / EXPIRED / ERROR_RECONCILE_REQUIRED).

No trade is live before broker ack. Idempotency key on intent_id+account+symbol.
"""

    files["KILL_SWITCH_MATRIX.md"] = f"""# Kill Switch Matrix

```json
{json.dumps(kill, indent=2, default=str)}
```
"""

    files["TEST_EVIDENCE.md"] = """# Test Evidence

Run: `python -m pytest tests/test_execution_state.py tests/test_execution_readiness.py ...`

Minimum scenarios: live globally prohibited, policy on DB arm off, desk approval missing,
quote stale after approval, kill switch after approval, LLM cannot override hard block,
no broker write bypass, release blocked by dirty live-adjacent file.
"""

    for name, content in files.items():
        (out_dir / name).write_text(content, encoding="utf-8")

    # Audit sample
    ledger = ROOT / "data" / "runtime" / "audit_ledger" / "events.jsonl"
    if ledger.exists():
        shutil.copy(ledger, out_dir / "AUDIT_LEDGER_SAMPLE.jsonl")
    else:
        (out_dir / "AUDIT_LEDGER_SAMPLE.jsonl").write_text("", encoding="utf-8")

    return {"ok": True, "out_dir": str(out_dir), "files": list(files.keys()) + ["AUDIT_LEDGER_SAMPLE.jsonl"],
            "execution_state_ok": state.get("live_architecture_built")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/diligence/current")
    args = ap.parse_args()
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    result = export_pack(out)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())