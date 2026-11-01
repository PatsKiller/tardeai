#!/usr/bin/env python3
"""Where leadership is moving: the rotation advisor's CLI (dry run by default).

Operator 2026-10-31, verbatim: "if stuff is turning for the long term, I should have advisement of what I should be
getting into". Reads (read-only) the daily bars through the engine's PgReader, the CIO opportunity projection, the
current holdings file and the market-risk snapshot's tier; prints the advisory payload and the card. ``--apply`` sends
the P2 card only when ``leadership.card_enabled`` is true in policy AND the leadership signature changed since the last
sent card (state under the persistent state root); otherwise it says why it did not send. Never a size, weight, price,
order or stop (``MBI_BEHAVIOR = 0``).

  python3 scripts/market_risk_rotation.py [--json] [--apply]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.lib.market_risk import contract as c  # noqa: E402
from scripts.lib.market_risk import leadership, rotation_advice  # noqa: E402
from scripts.lib.market_risk.policy import load_policy  # noqa: E402


def state_root() -> Path:
    env = os.environ.get("TRADEAI_STATE_ROOT") or os.environ.get("TRADEAI_PERSISTENT_STATE_ROOT")
    return Path(env or Path.home() / "trade-ai-releases" / "persistent-state")


def _store_path(root: Path) -> Path:
    """The position store under ``root`` — the path is owned by lib/portfolio_positions (STORE_REL), not copied here."""
    from scripts.lib import portfolio_positions as pp

    return pp.store_path(root)


def load_holdings(path: Path) -> list[dict]:
    """Current holdings (the file Home reads). Market value = shares x price when the row has no market_value."""
    from scripts.lib import portfolio_positions as pp

    doc = pp.load_store(Path(path))  # the sanctioned position-store reader; {} when missing or unreadable
    out = []
    for h in doc.get("holdings") or []:
        if not isinstance(h, dict) or not h.get("symbol"):
            continue
        sh = h.get("shares") or h.get("quantity") or 0
        px = h.get("canonical_mark") or h.get("price") or 0  # never the legacy current_price (R3)
        try:
            mv = float(h.get("market_value") or (float(sh) * float(px)))
        except (TypeError, ValueError):
            mv = 0.0
        out.append({"symbol": str(h["symbol"]).upper(), "sector": h.get("sector"), "market_value": mv})
    return out


def current_tier(root: Path) -> str | None:
    from scripts.lib.market_risk_projection import SNAPSHOT_REL

    try:
        return json.loads((root / SNAPSHOT_REL).read_text(encoding="utf-8")).get("tier")
    except (OSError, ValueError):
        return None


def earnings_map(reader, now: datetime, sessions: int) -> dict[str, str]:
    try:
        rows = reader.earnings_calendar(start=now, end=now + timedelta(days=int(sessions * 1.5)), now=now)
    except Exception as exc:  # noqa: BLE001 — an unreadable calendar is reported, never fatal
        print(f"market_risk_rotation: earnings calendar unavailable ({type(exc).__name__}: {exc})", file=sys.stderr)
        return {}
    return {str(r.get("symbol")).upper(): str(r.get("earnings_date") or r.get("date"))[:10] for r in rows or []}


def build(now: datetime, reader, policy: dict, root: Path) -> dict:
    ctx = c.EvalContext(now=now, reader=reader, policy=policy)
    block = leadership.measure(ctx)
    if block.get("state") != "evaluated":
        return {"state": "UNKNOWN", "leadership": block}
    cfg = policy.get("leadership") or {}
    payload = rotation_advice.advise(
        block,
        policy=policy,
        tier=current_tier(root),
        candidates=rotation_advice.load_candidates(root / "data" / "cio" / "cio_opportunity_projection.json"),
        holdings=load_holdings(_store_path(root)),
        earnings=earnings_map(reader, now, int(cfg.get("earnings_window_sessions") or 10)),
    )
    tr = ROOT / str(cfg.get("track_record_path") or "")
    try:
        payload["track_record"] = json.loads(tr.read_text(encoding="utf-8")).get("summary")
    except (OSError, ValueError):
        payload["track_record"] = None
    return payload


def _opportunity_items(root: Path) -> list[dict]:
    try:
        doc = json.loads((root / "data" / "cio" / "cio_opportunity_projection.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = doc.get("items") or {}
    rows = list(items.values()) if isinstance(items, dict) else list(items)
    for r in rows:
        r.setdefault("as_of", doc.get("as_of"))
    return [r for r in rows if isinstance(r, dict) and r.get("symbol")]


def _instrument_records(root: Path) -> dict[str, dict]:
    """symbol -> latest CIO InstrumentRecord (read-only)."""
    from scripts.lib import cio_instrument_record as ir

    try:
        st = ir._store_for_root(None)  # noqa: SLF001 — the registered store resolver
        out = {}
        for rec in st.all():
            for sym in rec.get("symbols") or []:
                out.setdefault(str(sym).upper(), rec)
        return out
    except Exception as exc:  # noqa: BLE001 — an unreadable store is reported, never fatal
        print(f"market_risk_rotation: instrument records unavailable ({type(exc).__name__})", file=sys.stderr)
        return {}


def _exits(root: Path, snapshot: dict) -> list[dict]:
    """Names exited recently (holdings closed_today), with the groups stressed at the time (from the snapshot)."""
    from scripts.lib import portfolio_positions as pp

    doc = pp.load_store(_store_path(root))
    if not doc:
        return []
    stressed = (
        list(((snapshot.get("sectors") or {}).get("stressed") or []))
        if isinstance(snapshot.get("sectors"), dict)
        else []
    )
    out, seen = [], set()
    for rows in (doc.get("closed_today") or {}).values() if isinstance(doc.get("closed_today"), dict) else []:
        for r in rows or []:
            sym = str((r or {}).get("symbol") or "").upper()
            if sym and sym not in seen:
                seen.add(sym)
                out.append(
                    {
                        "symbol": sym,
                        "date": str(doc.get("aggregate_published_at") or "")[:10],
                        "stressed_groups": stressed,
                    }
                )
    return out


def fanout(payload: dict, policy: dict, root: Path, now: datetime, block: dict) -> dict:
    """Plan (never write) the CIO memories and the research jobs for today's transitions."""
    from scripts.lib.cio_watch_instrument_admit import load_watchlist
    from scripts.lib.market_risk import cio_memory_fanout as F
    from scripts.lib.market_risk_projection import SNAPSHOT_REL

    try:
        snapshot = json.loads((root / SNAPSHOT_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        snapshot = {}
    groups = block.get("groups") or {}
    st = snapshot.get("shock_type")
    cur = {
        "as_of": block.get("as_of"),
        "leadership": {k: g.get("class") for k, g in groups.items()},
        "shock_type": st.get("class") if isinstance(st, dict) else None,
        "tier": snapshot.get("tier"),
        "reentry": {s: p.get("stance") for s, p in (snapshot.get("positions") or {}).items() if isinstance(p, dict)},
    }
    state_file = root / "data" / "runtime" / "market_risk" / "rotation_fanout_state.json"
    try:
        prev = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prev = {}
    day = ledger_day(now)
    trigs = F.triggers(prev.get("state") or {}, cur)
    items = _opportunity_items(root)
    recs = _instrument_records(root)
    wl = load_watchlist(None) or {}
    try:
        wl = json.loads((root / "data" / "portfolios" / "state" / "watchlist.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    tiers = {}
    for k, g in groups.items():
        if g.get("class") in ("LEADERSHIP_CONFIRMED", "LEADERSHIP_EMERGING"):
            tiers[k] = F.tiered_candidates(
                k,
                group_symbols=list(g.get("symbols") or []),
                opportunity_items=items,
                watchlist=wl,
                instrument_records=recs,
                group_of=lambda it: rotation_advice.group_of(it, groups),
                policy=policy,
                now=now,
            )
    try:
        from scripts.lib import search_budget

        brave_status = search_budget.status("brave")
    except Exception as exc:  # noqa: BLE001 — unknown budget -> no Brave jobs (fail closed in plan_research)
        print(f"market_risk_rotation: brave budget unavailable ({type(exc).__name__})", file=sys.stderr)
        brave_status = None
    research = F.plan_research(
        trigs,
        groups=groups,
        tiers_by_group=tiers,
        policy=policy,
        brave_status=brave_status,
        already=set(prev.get("trigger_ids") or []),
        used_today=F.used_counts((prev.get("days") or {}).get(day)),
    )
    memory = F.plan_memory(
        trigs,
        groups=groups,
        cur=cur,
        exits=_exits(root, snapshot),
        tiers_by_group=tiers,
        snapshot_ref=str(SNAPSHOT_REL),
        policy=policy,
    )
    return {
        "triggers": trigs,
        "tiers": tiers,
        "research": research,
        "memory": memory,
        "state": cur,
        "state_file": str(state_file),
        "prev": prev,
        "day": day,
    }


LEDGER_KEEP_DAYS = 14
LEDGER_KEEP_IDS = 2000


def ledger_day(now: datetime) -> str:
    from scripts.lib.market_risk.sessions import ET

    return now.astimezone(ET).date().isoformat()


def ledger_after(plan: dict, now: datetime, *, status: str, receipts: dict | None = None) -> dict:
    """R6: the fan-out ledger once this plan is claimed. Trigger ids and memory keys are recorded, and today's Hermes and
    Brave job counts are added to the per-day ledger the next run's caps read."""
    from scripts.lib.market_risk import cio_memory_fanout as F

    prev = plan.get("prev") or {}
    day = plan["day"]
    days = {k: dict(v) for k, v in (prev.get("days") or {}).items() if isinstance(v, dict)}
    today = days.setdefault(day, {"hermes": 0, "brave": 0, "trigger_ids": []})
    today["hermes"] = int(today.get("hermes") or 0) + len(plan["research"].get("hermes") or [])
    today["brave"] = int(today.get("brave") or 0) + len(plan["research"].get("brave") or [])
    today["trigger_ids"] = sorted(set(today.get("trigger_ids") or []) | {t["id"] for t in plan["triggers"]})
    keep = sorted(days)[-LEDGER_KEEP_DAYS:]
    ids = list(dict.fromkeys([*(prev.get("trigger_ids") or []), *(t["id"] for t in plan["triggers"])]))
    applied = list(
        dict.fromkeys(
            [*(prev.get("applied") or []), *(F.applied_key(m) for m in plan["memory"] if not m.get("refused"))]
        )
    )
    out = {
        "state": plan["state"],
        "trigger_ids": ids[-LEDGER_KEEP_IDS:],
        "applied": applied[-LEDGER_KEEP_IDS:],
        "days": {k: days[k] for k in keep},
        "status": status,
        "at": now.isoformat(),
    }
    if receipts is not None:
        out["receipts"] = receipts
    return out


def write_ledger(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, default=str), encoding="utf-8")
    os.replace(tmp, path)


def apply_fanout(plan: dict, policy: dict, now: datetime, *, conn_factory, root=None) -> dict:
    """R6: claim first, then write. The ledger (state, trigger ids, today's job counts) is written BEFORE any memory or
    research write, so a crash mid-apply never re-sends the same triggers or exceeds the day's cap on the next run (at
    most once). Memory writes skip keys already in the ledger (idempotent by trigger id)."""
    from scripts.lib.market_risk import cio_memory_fanout as F

    sf = Path(plan["state_file"])
    write_ledger(sf, ledger_after(plan, now, status="claimed"))
    done = set((plan.get("prev") or {}).get("applied") or [])
    mem = F.apply_memory(plan["memory"], root=root, done=done)
    res = F.apply_research(plan["research"], conn_factory=conn_factory, policy=policy)
    receipts = {"memory_receipts": mem, "research_receipts": res}
    write_ledger(sf, ledger_after(plan, now, status="applied", receipts=receipts))
    return receipts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="send the card when enabled and changed")
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--fanout", action="store_true", help="plan CIO memories + research jobs (writes only with --apply)"
    )
    a = ap.parse_args(argv)
    policy = load_policy()
    from scripts.lib.market_risk.reader import PgReader

    root = state_root()
    payload = build(datetime.now(timezone.utc), PgReader(), policy, root)
    if payload.get("state") == "UNKNOWN":
        print(json.dumps(payload, indent=2, default=str))
        return 3
    print(json.dumps(payload, indent=2, default=str) if a.json else rotation_advice.render_card(payload))
    if a.fanout:
        from scripts.lib.market_risk import cio_memory_fanout as F

        now = datetime.now(timezone.utc)
        block = leadership.measure(c.EvalContext(now=now, reader=PgReader(), policy=policy))
        plan = fanout(payload, policy, root, now, block)
        print(F.to_json({k: v for k, v in plan.items() if k not in ("state_file", "prev")}))
        if a.apply:
            from scripts.lib.cio_market_context_state import connect_trade_ai_readonly  # noqa: F401 — read path proof

            from db_adapter import _get_conn  # the repo's write connection, used by the existing research-gaps route

            print(F.to_json(apply_fanout(plan, policy, now, conn_factory=_get_conn)))
        else:
            print("DRY RUN: fan-out planned; nothing written, nothing enqueued", file=sys.stderr)
    cfg = policy.get("leadership") or {}
    state_file = root / "data" / "runtime" / "market_risk" / "rotation_state.json"
    sig = rotation_advice.signature(payload)
    try:
        last = json.loads(state_file.read_text(encoding="utf-8")).get("signature")
    except (OSError, ValueError):
        last = None
    if not a.apply:
        print(
            f"DRY RUN: would {'send' if cfg.get('card_enabled') and sig != last else 'not send'} "
            f"(card_enabled={bool(cfg.get('card_enabled'))}, changed={sig != last})",
            file=sys.stderr,
        )
        return 0
    if not cfg.get("card_enabled"):
        print("not sent: leadership.card_enabled is false (operator decision; no demonstrated edge)", file=sys.stderr)
        return 0
    if sig == last:
        print("not sent: leadership signature unchanged", file=sys.stderr)
        return 0
    ok = rotation_advice.send_card(payload, policy)
    if not ok:
        print("send failed", file=sys.stderr)
        return 1
    state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_file.with_suffix(".tmp")
    tmp.write_text(json.dumps({"signature": sig, "sent_at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
    os.replace(tmp, state_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
