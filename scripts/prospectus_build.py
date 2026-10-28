#!/usr/bin/env python3
"""Build Ticker Prospectuses (operator 2026-10-26: "Opus for all, Fable for top").

Dry run is the default: it reads the house stores, assembles inputs and prompts, prints a size and cost estimate
per ticker, and writes nothing and calls no model.

    python3 scripts/prospectus_build.py                                  # dry run, all scopes, first 5
    python3 scripts/prospectus_build.py --symbols AAA,BBB --limit 2      # dry run for named symbols
    python3 scripts/prospectus_build.py --apply --first-build --limit 40 # enqueue everything (premium top 5 →
                                                                         # other holdings → watch), run 40
    python3 scripts/prospectus_build.py --apply --due --limit 12         # scheduled lane: enqueue due, run 12
    python3 scripts/prospectus_build.py --apply --limit 12               # drain the queue (incl. operator refreshes)
    python3 scripts/prospectus_build.py --gate-only --all                # data-quality gate over stored reports (dry)
    python3 scripts/prospectus_build.py --gate-only --all --apply        # + Haiku read, index gate fields, enqueue
                                                                         # only the rewrites (and data repairs)

Every model call goes through the governed credit path (``llm_consumption.gate_and_generate``) as process
``prospectus_writer`` (Opus 5.5) or ``prospectus_writer_premium`` (Fable 5.1). When the credit is paused, exhausted
or unavailable the job stays QUEUED; there is no paid fallback for this job. READ_ONLY_ADVISORY (MBI_BEHAVIOR=0).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.prospectus import load_config, store  # noqa: E402
from scripts.lib.prospectus import batch  # noqa: E402
from scripts.lib.prospectus.generate import writer_prompt  # noqa: E402
from scripts.lib.prospectus.domains import full_assemble  # noqa: E402
from scripts.lib.prospectus.inputs import HouseSources, key_gaps  # noqa: E402
from scripts.lib.prospectus.pipeline import (  # noqa: E402
    PRIORITY_OPERATOR, due_rows, estimate, first_build_rows, plan_universe, run_queue,
)

LANE = "prospectus-build"


def state_root() -> Path:
    from scripts.lib.prospectus.inputs import _imp_any
    return Path(_imp_any("scripts.lib.anthropic_routing", "lib.anthropic_routing").state_root())


def _pricing() -> dict:
    from scripts.lib.prospectus.inputs import _imp_any
    return _imp_any("scripts.lib.anthropic_transport", "lib.anthropic_transport").load_policy().get("pricing") or {}


def parse(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Build Ticker Prospectuses (dry run by default).")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="default: assemble and estimate, write nothing")
    mode.add_argument("--apply", action="store_true", help="write the queue/index and call the governed model path")
    ap.add_argument("--symbols", default="", help="comma-separated symbols (operator-requested; run first)")
    ap.add_argument("--scope", choices=("holdings", "watch", "all"), default="all")
    ap.add_argument("--limit", type=int, default=5, help="tickers to process this run")
    ap.add_argument("--first-build", action="store_true", help="enqueue the whole universe in first-build order")
    ap.add_argument("--due", action="store_true", help="enqueue what the cadence and triggers say is due")
    ap.add_argument("--manual", action="store_true", help="operator-initiated run (manual trigger)")
    ap.add_argument("--no-batch", action="store_true", help="write Watch rows synchronously this run (no batch)")
    ap.add_argument("--batch-now", action="store_true", help="submit every queued Watch row now (ignore size/wait)")
    ap.add_argument("--gate-only", action="store_true",
                    help="run the data-quality gate over EXISTING stored reports and list which need a rewrite")
    ap.add_argument("--all", action="store_true", help="--gate-only: every stored report (default when no --symbols)")
    ap.add_argument("--ai", action="store_true", help="--gate-only dry run: also run the paid Haiku read (layer 2)")
    ap.add_argument("--no-ai", action="store_true", help="--gate-only --apply: skip the Haiku read")
    ap.add_argument("--show-prompt", action="store_true", help="dry run: print the first assembled prompt")
    return ap.parse_args(argv)


def dry_run(args: argparse.Namespace, sources, cfg: dict, base: Path) -> dict:
    symbols = [s for s in args.symbols.split(",") if s.strip()]
    universe = plan_universe(sources, cfg, scope=args.scope, symbols=symbols or None)
    order = first_build_rows(universe) if (args.first_build or not args.due) else due_rows(
        universe, store.read_index(base), sources, cfg, now=datetime.now(timezone.utc))
    pricing = _pricing()
    holdings = sources.holdings() if any(r["scope"] == "holding" for r in order) else {}
    rows = []
    for row in order[: max(0, args.limit)]:
        b = full_assemble(sources, row["symbol"], row["scope"], cfg=cfg, holding=holdings.get(row["symbol"]),
                          request_refresh=False)
        prompt = writer_prompt(b, cfg, mode="full", previous=None)
        est = estimate(prompt, cfg, premium=row["premium"], pricing=pricing, scope=row["scope"])
        rows.append({"symbol": row["symbol"], "scope": row["scope"], "premium": row["premium"],
                     "reason": row.get("reason"), "facts": len(b.facts), "gaps": b.gaps, "key_gaps": key_gaps(b),
                     "registry_coverage": {s: [r["domain"] for r in b.context.get("registry_coverage") or [] if r["status"] == s]
                                           for s in ("used", "stale", "empty", "failed")},
                     "web_searches_max": int(((cfg.get("web") or {}).get("max_uses") or {}).get(row["scope"], 0)), **est})
        if args.show_prompt and len(rows) == 1:
            print(prompt)
            print("-" * 80)
    out = {"mode": "dry_run", "universe": {"holdings": sum(r["scope"] == "holding" for r in universe),
                                           "watch": sum(r["scope"] == "watch" for r in universe)},
           "planned": len(order), "shown": rows,
           "est_total_usd_for_planned": round(sum(r["cost_usd_est"] for r in rows) / max(1, len(rows)) * len(order), 2)
           if rows else 0.0,
           "writes": "none", "model_calls": 0}
    return out


def apply(args: argparse.Namespace, sources, cfg: dict, base: Path) -> dict:
    now = datetime.now(timezone.utc)
    symbols = [s for s in args.symbols.split(",") if s.strip()]
    universe = plan_universe(sources, cfg, scope="all")
    store.write_universe(base, universe)
    queued = 0
    if args.first_build:
        queued += store.enqueue(base, first_build_rows(universe), now=now)
    if args.due:
        queued += store.enqueue(base, due_rows(universe, store.read_index(base), sources, cfg, now=now), now=now)
    if symbols:
        by_sym = {r["symbol"]: r for r in universe}
        queued += store.enqueue(base, [{"symbol": s, "scope": (by_sym.get(store.norm_symbol(s)) or {}).get("scope", "watch"),
                                        "premium": (by_sym.get(store.norm_symbol(s)) or {}).get("premium", False),
                                        "priority": PRIORITY_OPERATOR, "mode": "full", "reason": "operator_cli",
                                        "requested_by": "cli"} for s in symbols], now=now)
    summary = run_queue(base, sources, cfg, limit=max(0, args.limit), manual=args.manual,
                        batch_enabled=not args.no_batch)
    if not args.no_batch:  # Watch rows: collect what finished, then submit what is due (gate first, then submit)
        from scripts.lib.prospectus.pipeline import handle_blocked
        summary["batch_collect"] = batch.collect(base, cfg, now=datetime.now(timezone.utc))
        summary["batch_submit"] = batch.submit_due(base, sources, cfg, now=datetime.now(timezone.utc),
                                                   force=args.batch_now,
                                                   on_blocked=lambda sym, exc: handle_blocked(base, sym, exc))
    signal = {"ok_at": datetime.now(timezone.utc).isoformat(), "lane": LANE, "enqueued": queued, **summary,
              "queue_depth": len(store.read_queue(base)["items"])}
    store.write_json(Path(state_root()) / "data/runtime" / f"{LANE}_last.json", signal)
    return signal


def gate_only(args: argparse.Namespace, cfg: dict, base: Path, *, ai_fn=None, gap_fn=None) -> dict:
    """Layers 1-2 over stored reports' packets + layer 3 over their sections. Dry: writes nothing, calls nothing paid."""
    from scripts.lib.prospectus import quality_gate as qg
    settings = qg.load_settings()
    use_ai = (args.apply and not args.no_ai) or (not args.apply and args.ai)
    if use_ai and ai_fn is None:
        ai_fn = qg.governed_ai_call
    index = store.read_index(base)["items"]
    wanted = [store.norm_symbol(s) for s in args.symbols.split(",") if s.strip()]
    symbols = [s for s in wanted if s] or sorted(index)
    universe = {r["symbol"]: r for r in store.read_universe(base)}
    rows, now = [], datetime.now(timezone.utc)
    for sym in symbols:
        doc = store.read_prospectus(base, sym)
        if doc is None:
            rows.append({"symbol": sym, "gate_status": None, "needs_rewrite": False, "rewrite_reasons": ["no_report"]})
            continue
        res = qg.review_doc(doc, settings=settings, ai_fn=ai_fn if use_ai else None)
        rows.append(res)
        if not args.apply:
            continue
        store.update_index(base, sym, **qg.index_fields(res["gate"], res["post_write"]))
        if res["gate_status"] == qg.HARD:
            res["repairs"] = qg.request_repairs(sym, res["gate"], gap_fn=gap_fn)
        if res["needs_rewrite"]:
            u = universe.get(sym) or {}
            store.enqueue(base, [{"symbol": sym, "scope": u.get("scope") or doc.get("scope") or "watch",
                                  "premium": bool(u.get("premium")), "mode": "full", "priority": PRIORITY_OPERATOR + 50,
                                  "reason": "gate_rewrite:" + ",".join(res["rewrite_reasons"]),
                                  "requested_by": "quality_gate"}], now=now)
    counts: dict = {}
    for r in rows:
        counts[r.get("gate_status") or "no_report"] = counts.get(r.get("gate_status") or "no_report", 0) + 1
    codes: dict = {}
    for r in rows:
        for c in r.get("codes") or []:
            codes[c] = codes.get(c, 0) + 1
    why: dict = {}
    for r in rows:
        for c in r.get("rewrite_reasons") or []:
            why[c] = why.get(c, 0) + 1
    ai_cost = qg.ai_cost_estimate(settings, _pricing_safe())
    return {"mode": "gate_only_apply" if args.apply else "gate_only_dry_run", "reports": len(rows),
            "gate_status_counts": counts, "finding_code_counts": dict(sorted(codes.items())),
            "rewrite_reason_counts": why, "needs_rewrite": [r["symbol"] for r in rows if r.get("needs_rewrite")],
            "blocked_data": [r["symbol"] for r in rows if r.get("gate_status") == qg.HARD],
            "layer2": {"ran": bool(use_ai), "est_usd_per_ticker": ai_cost, "est_usd_for_these": round(ai_cost * len(rows), 4)},
            "rows": [{k: r.get(k) for k in ("symbol", "gate_status", "codes", "rewrite_reasons", "post_write")} for r in rows],
            "writes": "index gate fields + queue" if args.apply else "none"}


def _pricing_safe() -> dict:
    try:
        return _pricing()
    except Exception:  # noqa: BLE001 - estimate falls back to the module's list price
        return {}


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    cfg = load_config()
    root = state_root()
    base = store.base_dir(root, cfg)
    if args.gate_only:
        print(json.dumps(gate_only(args, cfg, base), indent=2, default=str))
        return 0
    sources = HouseSources(root, read_only=not args.apply)
    if args.apply:
        out = apply(args, sources, cfg, base)
    else:
        out = dry_run(args, sources, cfg, base)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    raise SystemExit(main())
