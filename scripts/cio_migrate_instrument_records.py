#!/usr/bin/env python3
"""Seed InstrumentRecord@v1 from rows the desk already has. No LLM.

Mints one record per subject:
  HELD:<SYM>   every non-dust held equity
  SLEEVE:CASH  the cash question, as a SLEEVE and never a fake ticker
  EXIT:<SYM>   Surface A exits that carry a plan or a case summary

Everything written here already existed somewhere — a holdings row, a plan, an
operator disposition. The point of the record is that it is now in ONE place
keyed by subject, so the next wake can rehydrate what the desk already knew
instead of re-deriving it and forgetting the operator's defer.

Dust, TEST tickers and cash-as-a-ticker are refused at mint (is_mintable).

Dry-run by default. READ_ONLY_ADVISORY. MBI_BEHAVIOR=0.

  cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
  python3 scripts/cio_migrate_instrument_records.py [--apply]

cwd MUST be the served release — the stores use relative paths.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

NO_CONSUMER_REASON = (
    "operator CLI, run on demand; InstrumentRecordMigration@v1 is a stdout "
    "receipt, the durable artifact is cio.instrument_records"
)


def _jsonl(path: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    p = Path(path)
    if not p.is_file():
        return out
    with open(p, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:                                # noqa: BLE001
                    continue
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--root", default=None,
                    help="served tree (default $TRADEAI_ROOT, else cwd)")
    args = ap.parse_args()

    # Explicit root beats implicit cwd. holdings_universe resolves its own
    # project root from the MODULE's location, so running a copy of this script
    # from a tree without data/ silently reports zero held names — which is
    # exactly what happened on the first run.
    import os as _os
    data_root = args.root or _os.environ.get("TRADEAI_ROOT") or "."

    from scripts.lib.cio_instrument_record import (
        CASH_SLEEVE, InstrumentRecordStore, cc_narrative, content_hash,
        is_mintable, new_record, subject_key,
    )
    from scripts.lib.holdings_universe import (
        held_position_rows, is_cash_row, is_held_equity_ticker,
        load_holdings_doc,
    )

    store = InstrumentRecordStore()
    minted: list[str] = []
    refused: dict[str, int] = {}

    def _refuse(reason: str) -> None:
        refused[reason] = refused.get(reason, 0) + 1

    # ── operator dispositions, keyed by symbol ────────────────────────────
    turns: dict[str, dict[str, Any]] = {}
    for row in _jsonl("data/cio/cio_operator_learning.jsonl"):
        for sym in row.get("symbols") or []:
            s = str(sym).strip().upper()
            prev = turns.get(s)
            if not prev or str(row.get("ts") or "") > str(prev.get("ts") or ""):
                turns[s] = row

    # ── latest open plan per symbol, for a narrative seed ─────────────────
    plans_by_sym: dict[str, dict[str, Any]] = {}
    try:
        from scripts.api_v3_cio import get_cio_plans
        res = get_cio_plans(limit=900)
        for p in (res.get("plans") if isinstance(res, dict) else res) or []:
            for sym in p.get("symbols") or []:
                s = str(sym).strip().upper()
                prev = plans_by_sym.get(s)
                if not prev or str(p.get("updated_ts") or p.get("created_ts") or "") > \
                        str(prev.get("updated_ts") or prev.get("created_ts") or ""):
                    plans_by_sym[s] = p
    except Exception:                                            # noqa: BLE001
        pass

    def _seed(kind: str, sym: str, *, mv: float | None = None) -> None:
        ok, why = is_mintable(kind, sym, market_value=mv)
        if not ok:
            _refuse(why)
            return
        plan = plans_by_sym.get(sym.upper()) or {}
        turn = turns.get(sym.upper())
        narrative = cc_narrative(
            what=str(plan.get("summary") or "")[:600],
            thesis_fit=str(plan.get("thesis_alignment") or "")[:400],
            recommendation_option_id=plan.get("option_id"),
            risks=list(plan.get("risks") or [])[:4],
            evidence_refs=list(plan.get("evidence_refs") or [])[:6],
            writer="migration:deterministic",
        )
        # An operator disposition outranks the plan's own prose: it is the last
        # thing a human actually said about this subject.
        nxt = None
        if turn and str(turn.get("disposition") or "").lower() == "defer":
            note = str(turn.get("note") or "").strip()
            narrative["what"] = (
                f"Operator deferred: {note}." + (
                    f" {narrative['what']}" if narrative["what"] else "")
            ).strip()
            nxt = (f"Has the condition behind the defer changed ({note})?"
                   if note else "Has the condition behind the defer changed?")
        rec = new_record(
            kind, sym,
            symbols=[sym.upper()] if kind != "SLEEVE" else [],
            thesis_ref=plan.get("thesis_version"),
            desk_pin=plan.get("thesis_version"),
            cc_narrative=narrative,
            next_research_question=nxt,
            last_operator_turn=({
                "intent": turn.get("disposition"),
                "text_hash": content_hash(turn.get("note")),
                "note": turn.get("note"),
                "plan_id": turn.get("plan_id"),
                "ts": turn.get("ts"),
            } if turn else None),
            last_artifact_id=plan.get("hermes_result_id"),
            hashes={
                "price": None, "analyst": None, "earnings": None,
                "weight": content_hash(mv) if mv is not None else None,
            },
        )
        if args.apply:
            store.upsert(rec)
        minted.append(rec["subject_key"])

    # ── held equities ─────────────────────────────────────────────────────
    for row in held_position_rows(root=Path(data_root)):
        if is_cash_row(row):
            continue
        sym = str(row.get("symbol") or "").strip().upper()
        if not sym or not is_held_equity_ticker(sym):
            _refuse("not_equity_ticker")
            continue
        mv = row.get("market_value")
        try:
            mv = float(mv) if mv is not None else None
        except (TypeError, ValueError):
            mv = None
        _seed("HELD", sym, mv=mv)

    if not minted:
        print(f"FATAL: no held equity rows under root={data_root!r}; refusing "
              f"to mint records against an empty book. Pass --root or run from "
              f"the served release.", file=sys.stderr)
        return 2

    # ── the cash sleeve (the $630k question), never a ticker ──────────────
    totals = (load_holdings_doc(root=Path(data_root)) or {}).get("portfolio_totals") or {}
    cash_usd = totals.get("total_cash")
    cash_rec = new_record(
        "SLEEVE", "CASH",
        cc_narrative=cc_narrative(
            what=(f"Cash sleeve {cash_usd}." if cash_usd is not None
                  else "Cash sleeve: DATA_UNAVAILABLE."),
            thesis_fit="Cash is intentional optionality under the desk thesis.",
            recommendation_option_id="hold_cash",
            writer="migration:deterministic",
        ),
        cash_usd=cash_usd,
        cash_source=totals.get("total_cash_source"),
        cash_written_at=totals.get("total_cash_written_at"),
        hashes={"price": content_hash(cash_usd)},
    )
    if args.apply:
        store.upsert(cash_rec)
    minted.append(CASH_SLEEVE)

    # ── Surface A exits carrying a plan or case summary ───────────────────
    exits = 0
    try:
        from scripts.lib.cio_investment_product import collect_previously_traded
        for row in collect_previously_traded() or []:
            sym = str(row.get("symbol") or "").strip().upper()
            if not sym:
                continue
            if sym not in plans_by_sym:
                _refuse("exit_without_plan")
                continue
            _seed("EXIT", sym)
            exits += 1
    except Exception:                                            # noqa: BLE001
        _refuse("previously_traded_unavailable")

    out = {
        "schema": "InstrumentRecordMigration@v1",
        "authority": "READ_ONLY_ADVISORY",
        "memory_behavior_influence": 0,
        "minted": len(minted),
        "by_kind": {k: sum(1 for m in minted if m.startswith(k + ":"))
                    for k in ("HELD", "EXIT", "WATCH", "SECTOR", "SLEEVE")},
        "exits_with_plan": exits,
        "refused": refused,
        "apply": bool(args.apply),
        "financial_action": False,
        "notify": False,
    }
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        print(f"minted={out['minted']} by_kind={out['by_kind']} "
              f"refused={refused} apply={args.apply}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
