#!/usr/bin/env python3
"""Prospectus accuracy auditor — standing QA after each prospectus run window (accuracy audit 2026-10-26).

Re-verifies written prospectuses against the PRIMARY house stores (position store, stop_last_known, ticker_prices,
ticker_dividends, the Finviz cache, fred_economic_series, trade_transactions) with no model call, and reports every
defect with its severity (P1 wrong money/position/stop/price, P2 missing or stale key data, P3 cosmetic).

    python3 scripts/prospectus_accuracy_audit.py                          # dry run: latest version of every report
    python3 scripts/prospectus_accuracy_audit.py --since 2026-10-27T16:00Z  # only versions written since the window
    python3 scripts/prospectus_accuracy_audit.py --apply                  # + findings file, window note, data-gap rows
    python3 scripts/prospectus_accuracy_audit.py --review                 # monthly prose sample: plan + budget (dry)
    python3 scripts/prospectus_accuracy_audit.py --review --apply         # one governed Opus read per sampled report

Dry run is the default and writes nothing. ``--apply`` writes only under ``<state>/data/prospectus/accuracy/``
(``<stamp>.json``, ``latest.json`` with the window's P2 note) and files one governed data-gap request per
(domain, symbol) whose defect a data owner can repair (``data_broker.gap_hook``, requester
``prospectus_accuracy_audit``). It never rewrites a report, never touches the queue, never calls a broker.
``--review`` spends at most $2 per UTC month on process ``prospectus_accuracy_review`` (Opus 5.5, Anthropic credit
only); the month's spend is kept in ``review_ledger.json``. READ_ONLY_ADVISORY (MBI_BEHAVIOR=0).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.prospectus import accuracy_audit as aa  # noqa: E402
from scripts.lib.prospectus import store  # noqa: E402

LANE = "prospectus-accuracy-audit"
REQUESTER = "prospectus_accuracy_audit"


def default_state_root() -> Path:
    from scripts.lib.anthropic_routing import state_root as resolve
    return Path(resolve())


def parse(argv: Optional[list[str]]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Re-verify written prospectuses against the primary stores (dry run by default).",
                                 allow_abbrev=False)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="default: audit and print, write nothing")
    mode.add_argument("--apply", action="store_true", help="write the findings + window note and file data-gap rows")
    ap.add_argument("--symbols", default="", help="comma-separated symbols (default: every stored report)")
    ap.add_argument("--since", default="", help="only versions generated at or after this ISO time (a run window)")
    ap.add_argument("--state-root", default="", help="state root (default: the production persistent-state)")
    ap.add_argument("--no-gaps", action="store_true", help="--apply without data-gap requests")
    ap.add_argument("--review", action="store_true", help="monthly prose-vs-facts sample (Opus, <= $2 / UTC month)")
    ap.add_argument("--review-n", type=int, default=aa.REVIEW_SAMPLE)
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    return ap.parse_args(argv)


def latest_docs(base: Path, symbols: list[str], since: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    names = symbols or sorted(p.name for p in base.iterdir() if p.is_dir() and store.norm_symbol(p.name))
    for sym in names:
        d = base / sym
        versions = sorted(v.name for v in d.iterdir() if v.is_dir() and (v / "prospectus.json").is_file()) if d.is_dir() else []
        if not versions:
            continue
        doc = json.loads((d / versions[-1] / "prospectus.json").read_text(encoding="utf-8"))
        if since and str(doc.get("generated_at") or "") < since:
            continue
        out[sym] = doc
    return out


def _db_query() -> Callable:
    from db_adapter import _execute  # type: ignore

    def query(sql, params=None, fetch="all"):
        if not str(sql).lstrip().upper().startswith("SELECT"):
            raise PermissionError("accuracy audit is read-only")
        return _execute(sql, params, fetch=fetch)
    return query


def _label_fn() -> Callable[[str], str]:
    try:
        from scripts.lib.account_display import account_label
        return account_label
    except Exception:  # noqa: BLE001
        return str


def run_audit(docs: dict[str, dict], primary: aa.Primary, *, label_fn: Callable[[str], str] = str) -> dict:
    results = []
    for sym, doc in docs.items():
        when = aa._dt(doc.get("generated_at")) or datetime.now(timezone.utc)
        results.append(aa.audit(doc, primary, now=when, label_fn=label_fn))
    summary = aa.summarize(results)
    return {"schema": aa.SCHEMA, "generated_at": datetime.now(timezone.utc).isoformat(), "summary": summary,
            "note": aa.window_note(summary), "gap_requests": aa.gap_requests(results),
            "rewrite_due": aa.rewrite_due(results), "results": results}


def write_findings(out_dir: Path, run: dict) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{stamp}.json"
    text = json.dumps(run, default=str, indent=1)
    for target in (path, out_dir / "latest.json"):
        tmp = target.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, target)
    return path


def file_gaps(requests: list[dict], *, enqueue: Optional[Callable] = None) -> list[dict]:
    if enqueue is None:
        try:
            from scripts.lib.data_broker.gap_hook import enqueue_gap as enqueue
        except ImportError:
            from lib.data_broker.gap_hook import enqueue_gap as enqueue  # type: ignore
    out = []
    for r in requests:
        res = enqueue(r["domain"], r["symbol"], f"prospectus accuracy audit: {', '.join(r['codes'])} for {r['symbol']}",
                      why="stale_hours" if any("stale" in c for c in r["codes"]) else "missing", requester=REQUESTER)
        out.append({**r, "result": (res or {}).get("reason") or ("enqueued" if (res or {}).get("enqueued") else "not_enqueued")})
    return out


def governed_review(prompt: str) -> tuple[str, dict]:
    try:
        from lib import llm_consumption as lc  # type: ignore
    except ImportError:
        from scripts.lib import llm_consumption as lc  # type: ignore
    text, prov = lc.gate_and_generate(prompt, process_id=aa.REVIEW_PROCESS, lane="pro_think", max_tokens=4000,
                                      timeout=600, return_provenance=True,
                                      task_summary="prospectus monthly accuracy sample (prose vs facts)")
    return str(text or ""), dict(prov or {})


def run_review(out_dir: Path, run: dict, docs: dict[str, dict], *, apply: bool, n: int,
               review_fn: Callable[[str], tuple[str, dict]] = governed_review,
               now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    month = now.strftime("%Y-%m")
    ledger_path = out_dir / "review_ledger.json"
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ledger = {}
    picks = aa.sample_for_review(run["results"], docs, n=n)
    plan = {"month": month, "sample": picks, "budget": aa.review_budget(ledger, month=month), "reviews": []}
    if not apply:
        return plan
    for sym in picks:
        budget = aa.review_budget(ledger, month=month)
        if not budget["allowed"]:
            plan["stopped"] = f"monthly cap ${budget['cap_usd']:.2f} reached (spent ${budget['spent_usd']:.2f})"
            break
        try:
            text, prov = review_fn(aa.review_prompt(docs[sym]))
        except Exception as exc:  # noqa: BLE001 - a refused or failed read is recorded, never retried here
            plan["reviews"].append({"symbol": sym, "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
            if "CREDIT" in str(exc) or "CAP" in str(exc).upper():
                break
            continue
        cost = float(prov.get("cost_usd") or prov.get("billed_usd") or aa.REVIEW_EST_COST_USD)
        ledger.setdefault(month, []).append({"symbol": sym, "version": docs[sym].get("version"), "cost_usd": cost,
                                             "at": now.isoformat(), "model": prov.get("model")})
        plan["reviews"].append({"symbol": sym, "version": docs[sym].get("version"), "cost_usd": cost,
                                **aa.parse_review(text)})
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(ledger, indent=1), encoding="utf-8")
    (out_dir / f"review_{month}.json").write_text(json.dumps(plan, default=str, indent=1), encoding="utf-8")
    plan["budget"] = aa.review_budget(ledger, month=month)
    return plan


def main(argv: Optional[list[str]] = None) -> int:
    a = parse(argv)
    root = Path(a.state_root) if a.state_root else default_state_root()
    base = root / "data/prospectus"
    out_dir = base / "accuracy"
    symbols = [store.norm_symbol(s) for s in a.symbols.split(",") if store.norm_symbol(s)]
    docs = latest_docs(base, symbols, a.since)
    primary = aa.db_primary(_db_query(), root)
    run = run_audit(docs, primary, label_fn=_label_fn())
    out: dict[str, Any] = {"mode": "apply" if a.apply else "dry_run", "lane": LANE, "reports": len(docs),
                           "summary": {k: v for k, v in run["summary"].items() if k != "codes"},
                           "top": [{k: c[k] for k in ("severity", "klass", "code")} | {"tickers": len(c["tickers"])}
                                   for c in run["summary"]["codes"][:15]],
                           "note": run["note"], "gap_requests": len(run["gap_requests"]),
                           "rewrite_due": run["rewrite_due"]}
    if a.apply:
        out["findings"] = str(write_findings(out_dir, run))
        out["gaps"] = [] if a.no_gaps else file_gaps(run["gap_requests"])
    else:
        out["would_write"] = [str(out_dir / "<stamp>.json"), str(out_dir / "latest.json")] + \
            ([] if a.no_gaps else [f"{len(run['gap_requests'])} data-gap request(s) (data_broker.gap_hook)"])
    if a.review:
        out["review"] = run_review(out_dir, run, docs, apply=a.apply, n=a.review_n)
    print(json.dumps(run if a.json else out, default=str, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
