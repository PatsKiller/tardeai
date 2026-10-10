#!/usr/bin/env python3
"""search_spend_report.py — Brave dollar spend vs the routing policy, plus routing-engine health (SearchSpendReport@v1).

Reads, never spends: the canonical search ledger (``data/runtime/search_budget.json``), the routing receipts
(``data/runtime/search_routing_receipts.jsonl``) and ``config/search_routing_policy.json``. Reports:

  * month-to-date GROSS dollars (requests x $0.005), the $5 credit, NET billed, against the $12 / $15 / $18
    lines; the alert level (warning at 80% of the $15 working target, critical at the $18 local ceiling);
  * per pool month/day dollars and today's paced allowance (scripts/lib/search_spend.py);
  * today's routed questions by class and tier, the free-lane share (answered without a paid request), the
    cache hit rate, and the scalp-priority research latency (p50/p95 ms);
  * ledger keys dated in the future (a test or a wrong clock wrote them — they would pre-spend a later month).

    python3 scripts/search_spend_report.py              # dry run: print the report, write nothing (default)
    python3 scripts/search_spend_report.py --write      # also write data/runtime/search_spend_last.json
                                                        # and append data/runtime/search_spend_history.jsonl

``--write`` is the receipt the incident fan-in reads (source ``search_spend``: a P2 at warning/critical); the
notifier — never this script — decides whether the operator hears about it. Not scheduled: a cron/n8n entry
is an operator decision (AGENTS.md §17).

AUTHORITY: READ_ONLY_ADVISORY. No provider call, no send. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import search_budget, search_spend  # noqa: E402
from scripts.lib.search_routing_policy import load_policy  # noqa: E402

SCHEMA = "SearchSpendReport@v1"
RECEIPT_REL = "data/runtime/search_spend_last.json"
HISTORY_REL = "data/runtime/search_spend_history.jsonl"


def _pct(values: list[int], p: float) -> Optional[int]:
    if not values:
        return None
    v = sorted(values)
    k = min(len(v) - 1, max(0, int(round(p * (len(v) - 1)))))
    return int(v[k])


def routing_metrics(receipts_path: Path, now: datetime, max_bytes: int = 4_000_000) -> dict[str, Any]:
    """Today's (UTC day) routed questions from the receipts tail."""
    day = now.astimezone(timezone.utc).strftime("%Y-%m-%d")
    rows: list[dict[str, Any]] = []
    try:
        with open(receipts_path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            raw = fh.read().decode("utf-8", errors="ignore")
        for line in raw.splitlines():
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if str(r.get("ts") or "").startswith(day):
                rows.append(r)
    except OSError:
        pass
    by_class: dict[str, dict[str, Any]] = {}
    for r in rows:
        c = by_class.setdefault(str(r.get("class")), {"n": 0, "tier": {}, "answered": 0, "cost_usd": 0.0,
                                                      "cache_hits": 0, "paid": 0})
        c["n"] += 1
        t = str(r.get("tier"))
        c["tier"][t] = c["tier"].get(t, 0) + 1
        c["answered"] += int(bool(r.get("answered")))
        c["cost_usd"] = round(c["cost_usd"] + float(r.get("cost_usd") or 0.0), 6)
        c["cache_hits"] += int(bool(r.get("cache_hit")))
        c["paid"] += int(r.get("units_paid") or 0)
    answered = [r for r in rows if r.get("answered")]
    free_answered = [r for r in answered if not int(r.get("units_paid") or 0)]
    scalp_lat = [int(r.get("latency_ms") or 0) for r in rows if r.get("class") == "scalp_priority"
                 and not r.get("cache_hit")]
    return {
        "day": day,
        "routed": len(rows),
        "answered": len(answered),
        "free_lane_share": round(len(free_answered) / len(answered), 4) if answered else None,
        "cache_hit_rate": round(sum(1 for r in rows if r.get("cache_hit")) / len(rows), 4) if rows else None,
        "paid_requests": sum(int(r.get("units_paid") or 0) for r in rows),
        "routed_cost_usd": round(sum(float(r.get("cost_usd") or 0.0) for r in rows), 6),
        "scalp_priority_latency_ms": {"n": len(scalp_lat), "p50": _pct(scalp_lat, 0.5), "p95": _pct(scalp_lat, 0.95)},
        "by_class": by_class,
    }


def future_keys(doc: dict[str, Any], now: datetime) -> dict[str, list[str]]:
    """Ledger day/month keys later than ``now`` (UTC) — written by a test fixture or a wrong clock."""
    day, month = now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")
    out: dict[str, list[str]] = {}
    for prov, p in ((doc or {}).get("providers") or {}).items():
        bad: list[str] = []
        for bucket in ("daily", "denied", "refunds", "caller_daily"):
            bad += [f"{bucket}:{k}" for k in (p.get(bucket) or {}) if str(k) > day]
        for bucket in ("monthly", "callers"):
            bad += [f"{bucket}:{k}" for k in (p.get(bucket) or {}) if str(k) > month]
        if bad:
            out[prov] = sorted(bad)
    return out


def build(*, root: Optional[Path] = None, now: Optional[datetime] = None,
          policy: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    pol = policy if policy is not None else load_policy()
    out: dict[str, Any] = {"schema": SCHEMA, "as_of": now.replace(microsecond=0).isoformat(),
                           "authority": "READ_ONLY_ADVISORY"}
    try:
        doc = search_budget.ledger_doc(root=root)
    except Exception as exc:  # noqa: BLE001 — an unreadable ledger is a FAILED report, never a zero
        out.update({"status": "failed", "alert": "critical", "error": f"ledger unreadable: {type(exc).__name__}: {exc}"})
        return out
    spend = search_spend.report(pol, doc, now)
    metrics = routing_metrics(search_budget.routing_receipts_path(root), now)
    fut = future_keys(doc, now)
    status = "ok" if spend["alert"] == "ok" else ("degraded" if spend["alert"] == "warning" else "failed")
    out.update({
        "status": status,
        "alert": spend["alert"],
        "spend": spend,
        "routing": metrics,
        "ledger_future_keys": fut,
        "ledger_path": str(search_budget.budget_path(root)),
        "health_contract": {
            "healthy": "gross month spend < 80% of the working target AND the ledger is readable",
            "degraded": "gross month spend >= 80% of the working target ($12 of $15) — P2 via the incident fan-in",
            "failed": "gross month spend >= the $18 local ceiling, or the ledger is unreadable",
            "measures": ["spend.gross_usd vs spend.lines", "routing.free_lane_share", "routing.scalp_priority_latency_ms"],
        },
    })
    return out


def write(report: dict[str, Any], root: Optional[Path] = None) -> Path:
    base = Path(root) if root else search_budget.budget_path(None).parents[2]
    path = base / RECEIPT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    with open(base / HISTORY_REL, "a", encoding="utf-8") as fh:
        slim = {k: report.get(k) for k in ("schema", "as_of", "status", "alert")}
        slim["gross_usd"] = (report.get("spend") or {}).get("gross_usd")
        slim["free_lane_share"] = (report.get("routing") or {}).get("free_lane_share")
        fh.write(json.dumps(slim, sort_keys=True) + "\n")
    return path


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--write", action="store_true", help="write the receipt + history line (default: dry run)")
    ap.add_argument("--root", type=Path, default=None, help="state root (default: production_state_root)")
    args = ap.parse_args(argv)
    rep = build(root=args.root)
    if args.write:
        p = write(rep, args.root)
        rep["written"] = str(p)
    else:
        rep["dry_run"] = True
    print(json.dumps(rep, indent=2, sort_keys=True))
    return 0 if rep.get("status") != "failed" or rep.get("spend") else 1


if __name__ == "__main__":
    raise SystemExit(main())
