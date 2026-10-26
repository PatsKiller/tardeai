#!/usr/bin/env python3
"""Ticker Prospectus run windows — the n8n lane ``prospectus-build`` (operator 2026-10-26).

Operator, verbatim: "Those new reports shouldn't just run ad hoc independently. They should be queued up and run a
certain time of the day, like if something moves plus or minus the 8% threshold".

Every lane fire (n8n dispatcher, every 15 minutes) does exactly one of:

* **a run window** when one is due (``config/prospectus.json`` ``run_windows``; default 17:45 ET after the close
  for every scope, and 07:00 ET pre-market for holdings only, weekdays): evaluate the cadence and triggers and
  ENQUEUE what is due with its reason, then drain the queue in priority order (operator rewrites, holdings by $
  value, then watch) up to the window's ``max_reports`` and inside the governed credit's daily cap. Leftovers wait
  for the next window.
* **an operator drain** otherwise: only "Rewrite now" rows (operator POST, priority 1) run, so that button stays
  immediate. With no operator row the fire reads the queue file and exits.

Each run that wrote or failed a report leaves one delivery outbox record; the host sender
``scripts/prospectus_deliver.py`` sends it (Telegram summary + PDF + Word; email audit). This lane sends nothing.

    python3 scripts/prospectus_window.py                       # dry run (default): what would run now; writes nothing
    python3 scripts/prospectus_window.py --now 2026-10-26T21:50:00Z
    python3 scripts/prospectus_window.py --apply               # the lane's live form (canary/live only)
    python3 scripts/prospectus_window.py --apply --window post_close   # operator: run a window now

READ_ONLY_ADVISORY (MBI_BEHAVIOR=0): research only; no sizing, orders, stops or weights.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.prospectus import load_config, store  # noqa: E402
from scripts.lib.prospectus import delivery, schedule  # noqa: E402

LANE = "prospectus-build"


def state_root() -> Path:
    from scripts.lib.prospectus.inputs import _imp_any
    return Path(_imp_any("scripts.lib.anthropic_routing", "lib.anthropic_routing").state_root())


def parse(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Ticker Prospectus run windows (dry run by default).")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="default: show what would run now; write nothing")
    mode.add_argument("--apply", action="store_true", help="enqueue triggers, drain, write the outbox and receipt")
    ap.add_argument("--now", default="", help="evaluate as of this ISO instant (tests / what-if)")
    ap.add_argument("--window", default="", help="operator: run this window id now, even off schedule")
    return ap.parse_args(argv)


def _now(args: argparse.Namespace) -> datetime:
    if args.now:
        out = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        return out if out.tzinfo else out.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def pick_window(cfg: dict, base: Path, now: datetime, forced: str = "") -> dict | None:
    if forced:
        zone = schedule.tz(cfg)
        day = now.astimezone(zone).date()
        for win in schedule.window_cfg(cfg).get("windows") or []:
            if win["id"] == forced:
                return dict(win, key=f"{schedule.window_key(win, day)}:manual:{store.stamp(now)}",
                            start=now.isoformat(), manual=True)
        raise SystemExit(f"unknown window {forced!r}")
    return schedule.due_window(cfg, base, now)


def _eligible_for(win: dict | None, skip: set[str]) -> Callable[[dict], bool]:
    if win is None:
        return schedule.is_operator_row
    scopes = set(win.get("scopes") or ["holding", "watch"])
    return lambda row: row.get("symbol") not in skip and (
        schedule.is_operator_row(row) or row.get("scope", "watch") in scopes)


def run(args: argparse.Namespace, cfg: dict, root: Path, *, sources_factory: Callable[[Path, bool], Any],
        run_queue_fn: Callable | None = None, log: Callable[[str], None] = print) -> dict:
    base = store.base_dir(root, cfg)
    now = _now(args)
    zone = schedule.tz(cfg)
    win = pick_window(cfg, base, now, args.window)
    queue = store.read_queue(base)["items"]
    operator_rows = [r for r in queue if r.get("state") in ("queued", None, schedule.HELD) and schedule.is_operator_row(r)]
    out: dict[str, Any] = {"lane": LANE, "now": now.isoformat(), "local": now.astimezone(zone).isoformat(),
                           "window": (win or {}).get("id"), "window_key": (win or {}).get("key"),
                           "next_windows": schedule.next_windows(cfg, now), "queue_depth": len(queue),
                           "operator_rows": [r["symbol"] for r in operator_rows]}
    if not args.apply:
        out.update(mode="dry_run", writes="none", model_calls=0)
        if win:
            sources = sources_factory(root, True)
            holdings = sources.holdings() or {}
            universe = schedule.plan_universe(holdings, sources.watch_symbols() if "watch" in (win.get("scopes") or [])
                                              else [], cfg)
            due = schedule.evaluate_triggers(universe, store.read_index(base), sources, cfg, now=now,
                                             triggers=win.get("triggers") or "all", scopes=win.get("scopes"),
                                             holdings=holdings)
            out["would_enqueue"] = [{k: r[k] for k in ("symbol", "scope", "priority", "reason")} for r in due]
            out["would_run_max"] = int(win.get("max_reports", 12))
        return out

    from scripts.lib.prospectus.pipeline import run_queue
    run_queue_fn = run_queue_fn or run_queue
    schedule.release_held(base)  # a crashed earlier fire never strands a parked row
    if win is None and not operator_rows:
        out.update(mode="apply", ran="nothing_due", produced_count=0)
        return out
    started = now
    sources = sources_factory(root, False)
    holdings = sources.holdings() or {}
    enqueued, skip, batch = 0, set(), {"enabled": bool((schedule.window_cfg(cfg).get("watch_batch") or {}).get("enabled")),
                                       "used": False}
    if win:
        universe = schedule.plan_universe(holdings, sources.watch_symbols() if "watch" in (win.get("scopes") or [])
                                          else [], cfg)
        prior = {r["symbol"]: r for r in store.read_universe(base)}
        merged = universe + [r for s, r in prior.items() if s not in {u["symbol"] for u in universe}
                             and r.get("scope") == "watch" and "watch" not in (win.get("scopes") or [])]
        store.write_universe(base, merged)
        due = schedule.evaluate_triggers(universe, store.read_index(base), sources, cfg, now=now,
                                         triggers=win.get("triggers") or "all", scopes=win.get("scopes"),
                                         holdings=holdings)
        enqueued = store.enqueue(base, due, now=now)
        hook = schedule.batch_hook(cfg)
        if hook is not None and "watch" in (win.get("scopes") or []):
            watch_rows = [r for r in store.read_queue(base)["items"]
                          if r.get("scope") == "watch" and r.get("state") in ("queued", None)
                          and not schedule.is_operator_row(r)]
            if watch_rows:
                res = hook(base, watch_rows, cfg) or {}
                skip = set(res.get("submitted") or [])
                batch.update(used=True, submitted=sorted(skip))
        limit = int(win.get("max_reports", 12))
    else:
        limit = int((schedule.window_cfg(cfg).get("operator_rewrite") or {}).get("max_per_fire", 3))
    before = dict(store.read_index(base)["items"])
    rows = {r["symbol"]: r for r in store.read_queue(base)["items"]}
    summary = schedule.drain(base, sources, cfg, limit=limit, eligible=_eligible_for(win, skip),
                             run_queue_fn=run_queue_fn, holdings=holdings, manual=bool((win or {}).get("manual")))
    universe_by = {r["symbol"]: r for r in store.read_universe(base)}
    items = [it for it in (delivery.report_item(base, cfg, s, row=rows.get(s) or {}, before=before,
                                                 universe=universe_by) for s in summary.get("done") or []) if it]
    items.sort(key=lambda i: (0 if i["scope"] == "holding" else 1, -(i.get("value_usd") or 0), i["symbol"]))
    failed = [{"symbol": s, "error": (store.read_index(base)["items"].get(s) or {}).get("last_error")}
              for s in summary.get("failed") or []]
    month = now.astimezone(zone).strftime("%Y-%m")
    cost = float(summary.get("cost_usd") or 0)
    finished = datetime.now(timezone.utc)
    receipt = {"done": summary.get("done"), "failed": summary.get("failed"), "queued": summary.get("queued"),
               "stopped_reason": summary.get("stopped_reason"), "cost_usd": round(cost, 4), "enqueued": enqueued,
               "finished_at": finished.isoformat()}
    state = schedule.record_window(base, (win or {}).get("key") or "", receipt, month=month, cost_usd=cost)
    queue_left = sum(1 for r in store.read_queue(base)["items"] if r.get("state") in ("queued", None))
    outbox = None
    deliver_operator = bool((delivery.delivery_cfg(cfg)).get("on_operator_rewrite", True))
    if (items or failed) and (win or deliver_operator):
        run_key = (win or {}).get("key") or f"{now.astimezone(zone).date().isoformat()}:operator:{store.stamp(now)}"
        outbox = delivery.write_outbox(base, {
            "run_key": run_key, "window_id": (win or {}).get("id") or "operator_rewrite",
            "window_label": (win or {}).get("label") or ("Rewrite now" if not win else (win or {}).get("id")),
            "local_date": now.astimezone(zone).date().isoformat(), "started_at": started.isoformat(),
            "finished_at": finished.isoformat(), "items": items, "failed": failed, "queue_left": queue_left,
            "enqueued": enqueued, "cost_usd": round(cost, 4), "month": month,
            "month_spend_usd": state["spend_by_month"].get(month), "stopped_reason": summary.get("stopped_reason"),
            "batch": batch})
    out.update(mode="apply", ran="window" if win else "operator_rewrite", **receipt,
               queue_left=queue_left, month_spend_usd=state["spend_by_month"].get(month), batch=batch,
               outbox=str(outbox.relative_to(base)) if outbox else None, produced_count=len(items))
    return out


def write_receipt(root: Path, out: dict, started: str) -> None:
    try:
        from scripts.lib.lane_last_receipt import write_lane_receipt
    except ImportError:  # pragma: no cover
        from lib.lane_last_receipt import write_lane_receipt  # type: ignore
    produced = int(out.get("produced_count") or 0)
    write_lane_receipt(
        LANE, ok=True, exit_code=0, started_at=started, script="scripts/prospectus_window.py",
        summary={k: out.get(k) for k in ("ran", "window", "window_key", "enqueued", "done", "failed", "queue_left",
                                         "cost_usd", "month_spend_usd", "stopped_reason", "outbox")},
        produced_count=produced, attempted_count=produced + len(out.get("failed") or []),
        output_evidence=[{"kind": "file_artifact", "ref": out["outbox"]}] if out.get("outbox") else [],
        empty_reason=None if produced else "no_new_input",
        path=root / "data/runtime" / f"{LANE}_last.json")


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    cfg = load_config()
    root = state_root()
    started = datetime.now(timezone.utc).isoformat()

    def factory(r: Path, read_only: bool):
        from scripts.lib.prospectus.inputs import HouseSources
        return HouseSources(r, read_only=read_only)

    out = run(args, cfg, root, sources_factory=factory)
    if args.apply:
        write_receipt(root, out, started)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    raise SystemExit(main())
