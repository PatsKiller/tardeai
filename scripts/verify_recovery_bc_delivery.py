#!/usr/bin/env python3
"""B → C delivery proof for the Recovery & Re-Entry Engine (spec §3.3; piece F's missing contract).

The gap this closes (codex, 2026-11-03): piece A's replay proves that A can *print* a P1. It does not prove
that piece B's state machine hands a real case to piece C's notifier and that a real receipt results — and a
recovery the operator is never told about is the exact failure this row exists to fix. "The pieces each look
right" is not evidence, so this harness drives the REAL modules through a REAL process boundary:

    real B (scripts/lib/recovery_state.py)  ->  real C (scripts/lib/recovery_notify.py)
        with the transport INJECTED, so the proof is about invocations and receipts, never about a
        ``suppressed`` field (cx-openai-2: `suppressed: false` is present on every normal result and
        therefore proves nothing about delivery).

Two sessions, the second in a separate process against the same state directory, so the second pass must
exercise the repeat floor rather than a fresh-start happy path. Four proofs:

  P1  a T1 case that is RECOVERING pages exactly once (one sender invocation, priority P1, marker on line 1);
  P2  the same case, a session later and inside the floor, produces ZERO sender invocations AND a receipt
      that names the dedupe ("repeat floor: …") — the negative with an explanation, not silence;
  P3  the same symbol moving to a NEW state (RE_ENTRY_READY) pages again: dedupe is per (symbol, state),
      not a blanket mute;
  P4  with the batching module unavailable (the code path that exists until v008's batching lands), the
      dedupe moves to the transport: C calls it, the transport refuses the repeat, and the ledger records
      the refusal with its reason. Also never silence.

Non-T1 and non-recovering cases are included and must produce no page at all.

Entry point for piece F:

    python3 scripts/verify_recovery_bc_delivery.py            # human-readable, exit 0 only if every proof holds
    python3 scripts/verify_recovery_bc_delivery.py --json     # the same as one JSON document

No database, no network, no Telegram, no order path: the transport is a callable this harness owns, state
lives in a temporary directory, and the script writes nothing inside the repository.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))

SCHEMA = "RecoveryBcDeliveryProof@v1"
MARKER = "[[RECOVERY_T1]]"

# ── the cases: A's RecoveryCase.to_dict() shape, evaluated by B, handed to C ─────────────────────────────────
CASES = {
    "spcx": {
        "case_key": "SPCX:schwab_taxable:2026-10-30", "symbol": "SPCX", "account": "schwab_taxable",
        "state": "WATCHING", "materiality_tier": "T1", "realized_pnl": -12770.0, "pre_exit_weight_pct": 3.2,
        "exits": [{"symbol": "SPCX", "price": 137.19, "shares": 200, "realized_pnl": -12770.0,
                   "exit_date": "2026-10-30"}],
        "eligibility": [{"account": "schwab_roth_ira", "eligible": True, "eligible_from": None,
                         "reason": "ira eligible now"},
                        {"account": "schwab_taxable", "eligible": False, "eligible_from": "2026-11-27",
                         "reason": "house hold 30 days after a taxable sale"}],
        "residual_pct_of_pre_exit": 14.3,
        "residual_note": "200 of 1,400 shares remain after the 2026-10-30 exit (14.3%)",
    },
    "t2": {
        "case_key": "T2NAME:schwab_roth_ira:2026-10-20", "symbol": "T2NAME", "account": "schwab_roth_ira",
        "state": "WATCHING", "materiality_tier": "T2", "realized_pnl": -800.0,
        "exits": [{"symbol": "T2NAME", "price": 50.0, "shares": 10, "realized_pnl": -800.0}],
        "eligibility": [{"account": "schwab_roth_ira", "eligible": True, "eligible_from": None,
                         "reason": "ira eligible now"}],
    },
    "quiet": {
        "case_key": "QUIET:schwab_taxable:2026-10-20", "symbol": "QUIET", "account": "schwab_taxable",
        "state": "WATCHING", "materiality_tier": "T1", "realized_pnl": -12000.0,
        "exits": [{"symbol": "QUIET", "price": 100.0, "shares": 100, "realized_pnl": -12000.0}],
        "eligibility": [{"account": "schwab_taxable", "eligible": True, "eligible_from": None}],
    },
}

SNAP_NOW = datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc)
SNAPSHOTS = {
    # SPCX reclaims its exit (+3.25%) but is still below the 20-day mean: RECOVERING, not READY.
    "spcx": {"close": 141.65, "rsi": 39.1, "sma20": 151.62, "entry_high": 139.0},
    # T2NAME also reclaims — B says RECOVERING, but C must not page a T2 case (Home card / digest).
    "t2": {"close": 51.5, "rsi": 44.0, "sma20": 49.0, "entry_high": 50.0},
    # QUIET never reclaims.
    "quiet": {"close": 96.0, "rsi": 33.0, "sma20": 101.0, "entry_high": 98.0},
}


def _transport_ledger(state_dir: Path) -> Path:
    return state_dir / "transport.jsonl"


def _make_sender(state_dir: Path, *, transport_dedupes: bool, window_minutes: int = 120):
    """A transport that records EVERY entry, and — in the no-batching configuration — enforces the
    documented dedupe contract (``dedupe_minutes``) itself, exactly as ``telegram_alert.route_intent`` does.
    """
    ledger = _transport_ledger(state_dir)

    def _recent_duplicate(text: str, now: datetime, window: int) -> dict | None:
        try:
            rows = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]
        except (OSError, ValueError):
            return None
        for row in reversed(rows):
            if row.get("text") != text or not row.get("delivered"):
                continue
            sent_at = datetime.fromisoformat(str(row.get("at")).replace("Z", "+00:00"))
            if now - sent_at < timedelta(minutes=window):
                return row
            break
        return None

    def sender(text: str, *, priority: str = "P2", dedupe_minutes: int = 60, producer: str = "", **_: object) -> bool:
        now = datetime.now(timezone.utc)
        row = {"at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "priority": priority, "producer": producer,
               "dedupe_minutes": dedupe_minutes, "text": text, "delivered": True, "suppressed": False}
        prior = None
        if transport_dedupes and dedupe_minutes:
            prior = _recent_duplicate(text, now, int(dedupe_minutes))
        if prior is not None:
            row.update(delivered=False, suppressed=True,
                       reason=f"duplicate within {dedupe_minutes} min (first at {prior.get('at')})")
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
        return bool(row["delivered"])

    return sender


# ── one session, run in its own process (the boundary the proof needs) ──────────────────────────────────────
def run_session(state_dir: Path, now_iso: str, *, no_batch: bool = False,
                transport_dedupes: bool = False) -> dict:
    """Evaluate B over every case, hand the results to C, and return the session's receipts."""
    if no_batch:  # make C's lazy `from lib.telegram_batch import …` fail, exercising its documented fallback
        import importlib.abc

        class _Block(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path=None, target=None):
                if name in {"lib.telegram_batch", "scripts.lib.telegram_batch", "telegram_batch"}:
                    raise ImportError("blocked by the delivery-proof harness")
                return None

        sys.meta_path.insert(0, _Block())

    from lib import recovery_notify as C  # noqa: PLC0415
    from lib import recovery_state as B  # noqa: PLC0415

    now = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    sender = _make_sender(state_dir, transport_dedupes=transport_dedupes)
    receipts = {}
    for key, case in CASES.items():
        decision = B.evaluate(case, SNAPSHOTS[key], now=now)
        handoff = {**case, "state": decision.state, "confidence": round(decision.confidence, 4),
                   "next_trigger": decision.next_trigger,
                   "price": SNAPSHOTS[key]["close"],
                   "exit_price": B.exit_price(case),
                   "pct_vs_exit": (SNAPSHOTS[key]["close"] / B.exit_price(case) - 1.0)
                   if B.exit_price(case) else None}
        # The caller contract (the escalation site): only a state worth the operator's attention is handed
        # to C. C itself pages any T1 case it is given, so handing it a WATCHING case would page on noise —
        # that is the caller's responsibility, and this harness models it rather than papering over it.
        if decision.state in {"RECOVERING", "RE_ENTRY_READY"}:
            result = C.notify_recovery_case(handoff, sender=sender, now=now,
                                            state_path=state_dir / "recovery_nudge_state.json")
        else:
            result = {"sent": False, "suppressed": False, "priority": None, "path": None,
                      "reason": f"caller did not page: state {decision.state} is not a paging state"}
        receipts[key] = {"state_before": case["state"], "state_after": decision.state,
                         "b_confidence": round(decision.confidence, 4),
                         "next_trigger": decision.next_trigger,
                         "notify": result}
    return {"now": now_iso, "no_batch": no_batch, "receipts": receipts}


def _spawn(state_dir: Path, now_iso: str, *, no_batch: bool, transport_dedupes: bool) -> dict:
    """Run one session in a NEW process — the session boundary, not a second call in the same interpreter."""
    out = state_dir / f"session-{now_iso.replace(':', '').replace('-', '')}.json"
    argv = [sys.executable, str(Path(__file__).resolve()), "--session", str(state_dir), now_iso,
            str(out), "--no-batch" if no_batch else "--batch",
            "--transport-dedupes" if transport_dedupes else "--no-transport-dedupe"]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=300,
                          cwd=str(PROJECT_ROOT), env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    if proc.returncode != 0 or not out.exists():
        raise RuntimeError(f"session failed ({proc.returncode}): {(proc.stderr or proc.stdout)[-800:]}")
    return json.loads(out.read_text())


def _entries(state_dir: Path) -> list[dict]:
    path = _transport_ledger(state_dir)
    try:
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    except OSError:
        return []


def _entries_since(state_dir: Path, count_before: int) -> list[dict]:
    return _entries(state_dir)[count_before:]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Prove piece B hands a real case to piece C and a receipt results")
    ap.add_argument("--json", action="store_true", help="print the whole result as JSON")
    ap.add_argument("--session", nargs=3, metavar=("STATE_DIR", "NOW", "OUT"), help=argparse.SUPPRESS)
    ap.add_argument("--no-batch", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--batch", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--transport-dedupes", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--no-transport-dedupe", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.session:
        state_dir, now_iso, out = (Path(args.session[0]), args.session[1], Path(args.session[2]))
        result = run_session(state_dir, now_iso,
                             no_batch=bool(args.no_batch), transport_dedupes=bool(args.transport_dedupes))
        out.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
        return 0

    proofs: dict[str, dict] = {}
    root = Path(tempfile.mkdtemp(prefix="bc-delivery-proof-"))
    with_batch = root / "batch"
    with_batch.mkdir(parents=True, exist_ok=True)
    t0 = SNAP_NOW
    t1 = t0 + timedelta(minutes=30)

    # P1 — one page, through a real B -> C handoff.
    s1 = _spawn(with_batch, t0.strftime("%Y-%m-%dT%H:%M:%SZ"), no_batch=False, transport_dedupes=False)
    e1 = _entries(with_batch)
    spcx = [e for e in e1 if "SPCX" in str(e.get("text"))]
    proofs["P1_one_page_for_recovering_t1"] = {
        "pass": bool(len(spcx) == 1 and spcx[0].get("priority") == "P1"
                     and str(spcx[0].get("text", "")).startswith(MARKER)
                     and s1["receipts"]["spcx"]["state_after"] == "RECOVERING"),
        "b_state": s1["receipts"]["spcx"]["state_after"],
        "sender_entries_for_spcx": len(spcx),
        "priority": spcx[0].get("priority") if spcx else None,
        "marker_on_line_one": bool(spcx and str(spcx[0].get("text", "")).startswith(MARKER)),
        "c_result": {k: v for k, v in s1["receipts"]["spcx"]["notify"].items() if k != "message"},
    }

    # Non-T1 / non-recovering cases must not page at all.
    t2_pages = [e for e in e1 if "T2NAME" in str(e.get("text"))]
    quiet_pages = [e for e in e1 if "QUIET" in str(e.get("text"))]
    proofs["P1b_t2_and_non_recovering_never_page"] = {
        "pass": len(t2_pages) == 0 and len(quiet_pages) == 0,
        "t2_state": s1["receipts"]["t2"]["state_after"], "t2_sender_entries": len(t2_pages),
        "quiet_state": s1["receipts"]["quiet"]["state_after"], "quiet_sender_entries": len(quiet_pages),
        "t2_c_result": {k: v for k, v in s1["receipts"]["t2"]["notify"].items() if k != "message"},
    }

    # P2 — a session later, inside the floor: ZERO sender invocations AND a receipt naming the dedupe.
    before = len(_entries(with_batch))
    s2 = _spawn(with_batch, t1.strftime("%Y-%m-%dT%H:%M:%SZ"), no_batch=False, transport_dedupes=False)
    new_entries = _entries_since(with_batch, before)
    receipt2 = s2["receipts"]["spcx"]["notify"]
    proofs["P2_second_session_does_not_page_again_and_says_why"] = {
        "pass": len(new_entries) == 0 and bool(receipt2.get("deduped_by_floor"))
                and "repeat floor" in str(receipt2.get("reason")),
        "sender_entries_in_second_session": len(new_entries),
        "c_result": {k: v for k, v in receipt2.items() if k != "message"},
        "b_state_still": s2["receipts"]["spcx"]["state_after"],
    }

    # P3 — the same symbol in a NEW state pages again: dedupe is per (symbol, state), not a blanket mute.
    _patch_case_state = {"state": "RE_ENTRY_READY"}
    before = len(_entries(with_batch))
    ready_case = {**CASES["spcx"], "state": "RE_ENTRY_READY"}
    from lib import recovery_notify as C  # noqa: PLC0415  (same process is fine: the boundary proof is P1/P2)
    ready_result = C.notify_recovery_case({**ready_case, "price": 152.0, "exit_price": 137.19},
                                          sender=_make_sender(with_batch, transport_dedupes=False),
                                          now=t1, state_path=with_batch / "recovery_nudge_state.json")
    ready_entries = [e for e in _entries_since(with_batch, before) if "SPCX" in str(e.get("text"))]
    proofs["P3_a_new_state_pages_again"] = {
        "pass": len(ready_entries) == 1 and ready_result.get("sent") is True,
        "sender_entries": len(ready_entries),
        "c_result": {k: v for k, v in ready_result.items() if k != "message"},
    }

    # P4 — without the batching module, dedupe moves to the transport and the refusal is recorded.
    direct = root / "direct"
    direct.mkdir(parents=True, exist_ok=True)
    d1 = _spawn(direct, t0.strftime("%Y-%m-%dT%H:%M:%SZ"), no_batch=True, transport_dedupes=True)
    d2 = _spawn(direct, t1.strftime("%Y-%m-%dT%H:%M:%SZ"), no_batch=True, transport_dedupes=True)
    d_entries = [e for e in _entries(direct) if "SPCX" in str(e.get("text"))]
    d2_first = d1["receipts"]["spcx"]["notify"]
    d2_second = d2["receipts"]["spcx"]["notify"]
    proofs["P4_without_batching_the_transport_refuses_and_records_it"] = {
        "pass": len(d_entries) == 2 and d2_first.get("path") == "direct"
                and d_entries[0].get("delivered") is True and d_entries[1].get("delivered") is False
                and "duplicate within" in str(d_entries[1].get("reason"))
                and d2_second.get("sent") is False and d2_second.get("deduped_by_floor") is not True,
        "transport_entries": len(d_entries),
        "first": {k: d_entries[0].get(k) for k in ("priority", "delivered", "suppressed")} if d_entries else None,
        "second": {k: d_entries[1].get(k) for k in ("priority", "delivered", "suppressed", "reason")}
                  if len(d_entries) > 1 else None,
        "c_result_second_session": {k: v for k, v in d2_second.items() if k != "message"},
    }

    ok = all(p["pass"] for p in proofs.values())
    document = {"schema": SCHEMA, "ok": bool(ok), "state_root": str(root),
                "entry_point": "python3 scripts/verify_recovery_bc_delivery.py",
                "b_module": "scripts/lib/recovery_state.py", "c_module": "scripts/lib/recovery_notify.py",
                "transport": "injected callable; every entry recorded, dedupe enforced where the code path delegates it",
                "proofs": proofs}
    if args.json:
        print(json.dumps(document, indent=1, sort_keys=True))
    else:
        for name, proof in proofs.items():
            print(f"{'PASS' if proof['pass'] else 'FAIL'}  {name}")
            for key, value in proof.items():
                if key != "pass":
                    print(f"        {key}: {value}")
        print(f"\nB->C delivery proof: {'OK' if ok else 'FAILED'} (harness work dir {root})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
