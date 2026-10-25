#!/usr/bin/env python3
"""options_desk_quote_refresh.py — re-quote the cards already on the options desk; never rebuild it.

Why (operator 2026-10-22, "fix all of these n8n first for scheduling and monitoring"): the full desk build
(scripts/run_options_monitor.py -> options_engine.generate_proposals) runs `*/10 12-15` because its ensemble queue
feeds the local GPU worker, and 09:30-11:59 ET is the momentum-scalp GPU window (crontab comment 2026-07-17;
scripts/llm_priority_guard.sh defers tier-3 LLM work 06:00-11:59 ET). So the desk snapshot
(data/portfolios/state/options_proposals.json) carried 09:30 quotes until noon. This lane refreshes QUOTES ONLY in that
window: no proposal is added, removed, re-ranked or re-priced, no ensemble job is queued, no LLM is called, and no GPU is
touched.

What a real run (--apply) does, and nothing else:
  1. reads options_proposals.json and groups its cards by (symbol, expiration);
  2. for each group, up to --max-requests groups (default 25), makes ONE read-only, expiration-pinned option-chain read
     (scripts/schwab_transport.get_option_chain, all strikes of that one expiration, one side when every card in the
     group is the same side) — so the request count is the number of distinct (symbol, expiration) pairs, bounded;
  3. writes, per card, a `live_quote` block {bid, ask, mid, spread_pct, quote_time, occ_symbol, underlying_price,
     underlying_quote_time, received_at, market_session} (a spread card gets one entry per leg), and at the top level a
     `quote_refresh` block {at, market_session, requests, request_budget, cards_requoted, cards_skipped, source};
  4. writes the file atomically (tmp + rename) and only when the file did not change since it was read (the full build
     owns the file; a concurrent rebuild wins and this run reports `snapshot_changed_during_refresh`);
  5. writes its LaneRunReceipt@v2 (data/runtime/options-desk-quote-refresh_last.json).

The card's own economics (premium, max_loss, breakeven, pop, ...) and `generated_at` are NOT changed: they belong to the
build that reviewed them. `live_quote` is labelled as a quote observation (provenance `schwab_chain`, its own as_of).

Access: Schwab READS only, and only while config/schwab_access_mode.yaml resolves to exactly `read_only` (the
operator's mode since 2026-10-16). `normal` and `forbidden` both refuse the run (`schwab_access_mode_not_read_only`):
this lane never reads Schwab outside the mode the operator chose for scheduled reads. No order route, no account or
position read, no token refresh is reachable from this file (get_option_chain is a GET).

    python3 scripts/options_desk_quote_refresh.py              # --dry-run (default): OFFLINE plan, no broker call
    python3 scripts/options_desk_quote_refresh.py --apply      # chain reads + live_quote write + receipt

The dry run reads only the local snapshot and prints the plan (groups, request count vs budget). It never imports the
broker transport. Exit 0 = completed (a skipped card is output, not failure); 1 = snapshot unreadable / access mode
refused / every read failed; 2 = usage.

MBI_BEHAVIOR = 0. Authority: READ_ONLY_ADVISORY. Never sizes, orders, stops or weights.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

ROOT = Path(__file__).resolve().parent.parent
LANE_ID = "options-desk-quote-refresh"
SCRIPT = "scripts/options_desk_quote_refresh.py"
SCHEMA = "OptionsDeskQuoteRefresh@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
SOURCE = "schwab_chain"
#: Hard ceiling on chain reads per run. Measured 2026-10-22 09:30 ET snapshot: 5 cards, 4 (symbol, expiration)
#: groups -> 4 reads per run, 10 runs per morning (09:35..11:50 every 15 min) -> ~40 reads/morning. The full build
#: makes on the order of hundreds per tick; 25 leaves headroom for a larger desk and still bounds a bad snapshot.
DEFAULT_MAX_REQUESTS = 25
MAX_REQUESTS_CEILING = 60
REQUIRED_ACCESS_MODE = "read_only"
#: Quotes are refreshed only in the regular session (scripts/lib/canonical_observation.market_session labels).
REFRESH_SESSIONS = frozenset({"REGULAR"})

SKIP_BUDGET = "request_budget_exhausted"
SKIP_NO_CONTRACT = "card_has_no_contract"
SKIP_CHAIN = "chain_unavailable"
SKIP_NOT_FOUND = "contract_not_in_chain"


# ── pure helpers ────────────────────────────────────────────────────────────────────────────────────────────────


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN -> None


def _proposals_path() -> Path:
    try:
        from scripts.lib.desk_session import proposals_path
    except ImportError:  # pragma: no cover - scripts/ on sys.path
        from lib.desk_session import proposals_path  # type: ignore[no-redef]
    return proposals_path()


def market_session(at: datetime) -> str:
    """REGULAR only inside NYSE regular hours (scripts/lib/desk_session: calendar- and DST-aware); otherwise the
    desk's coarse vocabulary. The gate never reads quotes before the open or on a holiday."""
    try:
        from scripts.lib.desk_session import market_session as ms
    except ImportError:  # pragma: no cover - scripts/ on sys.path
        from lib.desk_session import market_session as ms  # type: ignore[no-redef]
    return ms(at)


def card_legs(card: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The contracts a card holds: [{side, strike}] for one expiration. A spread names short_strike / long_strike on
    one option_type; any other card names `strike`. A card without a usable contract returns []. Pure."""
    right = str(card.get("option_type") or "").lower()
    if right not in ("call", "put") or not card.get("expiration"):
        return []
    short, long_ = _num(card.get("short_strike")), _num(card.get("long_strike"))
    if short is not None and long_ is not None:
        return [{"leg": "short", "side": right, "strike": short}, {"leg": "long", "side": right, "strike": long_}]
    strike = _num(card.get("strike"))
    return [] if strike is None else [{"leg": "single", "side": right, "strike": strike}]


def plan_groups(cards: Iterable[Mapping[str, Any]], max_requests: int) -> dict[str, Any]:
    """Group cards by (symbol, expiration) in first-seen order; the first `max_requests` groups are read. Pure."""
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    no_contract: list[str] = []
    for i, card in enumerate(cards):
        legs = card_legs(card)
        sym = str(card.get("symbol") or card.get("underlying") or "").upper()
        if not legs or not sym:
            no_contract.append(str(card.get("id") or i))
            continue
        key = (sym, str(card.get("expiration"))[:10])
        g = groups.setdefault(key, {"symbol": key[0], "expiration": key[1], "cards": [], "sides": set(),
                                    "account": card.get("account")})
        g["cards"].append(i)
        g["sides"].update(leg["side"] for leg in legs)
    ordered = list(groups.values())
    for g in ordered:
        g["contract_type"] = next(iter(g["sides"])) if len(g["sides"]) == 1 else None
        g["sides"] = sorted(g["sides"])
    return {"read": ordered[:max_requests], "over_budget": ordered[max_requests:], "no_contract": no_contract,
            "groups": len(ordered), "requests_planned": min(len(ordered), max_requests)}


def find_row(chain: Mapping[str, Any], expiration: str, side: str, strike: float) -> Optional[dict[str, Any]]:
    rows = [r for e in chain.get("expirations") or [] if str(e.get("exp"))[:10] == expiration
            for r in e.get("strikes") or [] if r.get("side") == side and _num(r.get("strike")) == strike]
    return dict(rows[0]) if len(rows) == 1 else None


def leg_quote(row: Mapping[str, Any]) -> dict[str, Any]:
    bid, ask = _num(row.get("bid")), _num(row.get("ask"))
    mid = round((bid + ask) / 2, 4) if bid is not None and ask is not None else None
    spread = round(100.0 * (ask - bid) / mid, 1) if mid and bid is not None and ask is not None else None
    return {"bid": bid, "ask": ask, "mid": mid, "spread_pct": spread, "quote_time": row.get("quote_time"),
            "occ_symbol": row.get("symbol") or row.get("occ_symbol")}


def apply_group(doc_cards: list[dict[str, Any]], group: Mapping[str, Any], chain: Mapping[str, Any], *,
                received_at: str, session: str) -> dict[str, int]:
    """Write `live_quote` onto each card of one group from one chain answer. Returns {requoted, not_found}. Mutates
    only the `live_quote` key of the group's cards."""
    out = {"requoted": 0, "not_found": 0}
    under = {"underlying_price": _num(chain.get("underlying_price")),
             "underlying_quote_time": chain.get("underlying_quote_time"),
             "chain_fetched_at": chain.get("fetched_at"), "received_at": received_at, "market_session": session,
             "source": SOURCE, "provenance": "observed_quote", "writer": SCRIPT}
    for idx in group["cards"]:
        card = doc_cards[idx]
        legs = []
        missing = False
        for leg in card_legs(card):
            row = find_row(chain, group["expiration"], leg["side"], leg["strike"])
            if row is None:
                missing = True
                break
            legs.append({"leg": leg["leg"], "strike": leg["strike"], **leg_quote(row)})
        if missing or not legs:
            card["live_quote"] = {**under, "status": SKIP_NOT_FOUND}
            out["not_found"] += 1
            continue
        block = {**under, "status": "ok"}
        if len(legs) == 1:
            block.update({k: v for k, v in legs[0].items() if k not in ("leg", "strike")})
        else:
            block["legs"] = legs
        card["live_quote"] = block
        out["requoted"] += 1
    return out


# ── I/O ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def _default_chain_fn() -> Callable[..., Mapping[str, Any]]:
    """The production chain reader, imported only on --apply (the dry run never loads a broker module)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import schwab_transport as st  # noqa: PLC0415 — lazy by design: read-only GET, no order surface

    return st.get_option_chain


def access_mode() -> str:
    try:
        from scripts.lib import schwab_access_mode as sam
    except ImportError:  # pragma: no cover
        from lib import schwab_access_mode as sam  # type: ignore[no-redef]
    return sam.mode()


def write_atomic_if_unchanged(path: Path, doc: Mapping[str, Any], expected_mtime_ns: int) -> bool:
    """Write doc to path via tmp + rename, only if path still has the mtime it had when it was read."""
    try:
        if path.stat().st_mtime_ns != expected_mtime_ns:
            return False
    except OSError:
        return False
    target = path.resolve()
    tmp = target.with_name(f".{target.name}.quote_refresh.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
    try:
        if path.stat().st_mtime_ns != expected_mtime_ns:
            tmp.unlink(missing_ok=True)  # our own temp file, never the snapshot
            return False
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return True


def run(*, proposals: Path, apply: bool, max_requests: int, now: datetime,
        chain_fn: Optional[Callable[..., Mapping[str, Any]]] = None,
        mode_fn: Callable[[], str] = access_mode) -> dict[str, Any]:
    report: dict[str, Any] = {"schema": SCHEMA, "authority": AUTHORITY, "as_of": now.isoformat(),
                              "proposals": str(proposals), "mode": "apply" if apply else "dry_run",
                              "request_budget": max_requests}
    try:
        st = proposals.stat()
        doc = json.loads(proposals.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        report["error"] = f"snapshot_unreadable: {type(exc).__name__}"
        return report
    cards = doc.get("proposals") if isinstance(doc, dict) else None
    if not isinstance(cards, list):
        report["error"] = "snapshot_has_no_proposals_list"
        return report
    plan = plan_groups(cards, max_requests)
    report.update(cards=len(cards), groups=plan["groups"], requests_planned=plan["requests_planned"],
                  generated_at=doc.get("generated_at"),
                  plan=[{"symbol": g["symbol"], "expiration": g["expiration"], "cards": len(g["cards"]),
                         "contract_type": g["contract_type"]} for g in plan["read"]])
    skipped: dict[str, int] = {}
    if plan["no_contract"]:
        skipped[SKIP_NO_CONTRACT] = len(plan["no_contract"])
    over = sum(len(g["cards"]) for g in plan["over_budget"])
    if over:
        skipped[SKIP_BUDGET] = over
    if not apply:
        report.update(skipped=skipped, requests_made=0)
        return report
    mode = mode_fn()
    report["schwab_access_mode"] = mode
    if mode != REQUIRED_ACCESS_MODE:
        report["error"] = f"schwab_access_mode_not_read_only:{mode}"
        return report
    session = market_session(now)
    if session not in REFRESH_SESSIONS:
        # one cadence "5,20,35,50 9-11" covers 09:35-11:50; its 09:05 / 09:20 fires land here and read nothing
        report.update(skipped=skipped, requests_made=0, cards_requoted=0, empty_reason="market_closed",
                      market_session=session)
        return report
    if not cards:
        report.update(skipped=skipped, requests_made=0, cards_requoted=0, empty_reason="no_new_input")
        return report
    reader = chain_fn or _default_chain_fn()
    requests = requoted = 0
    for g in plan["read"]:
        requests += 1
        try:
            chain = reader(g["symbol"], expiration=g["expiration"], contract_type=g["contract_type"],
                           all_strikes=True)
        except Exception as exc:  # noqa: BLE001 — one failed read skips its group, never the run
            chain = {"status": "error", "error": type(exc).__name__}
        received = datetime.now(timezone.utc).isoformat() if chain_fn is None else now.isoformat()
        if not isinstance(chain, Mapping) or chain.get("status") != "ok":
            skipped[SKIP_CHAIN] = skipped.get(SKIP_CHAIN, 0) + len(g["cards"])
            for idx in g["cards"]:
                cards[idx]["live_quote"] = {"status": SKIP_CHAIN, "received_at": received, "market_session": session,
                                            "source": SOURCE,
                                            "detail": str((chain or {}).get("status") if isinstance(chain, Mapping)
                                                          else "bad_payload")[:60]}
            continue
        res = apply_group(cards, g, chain, received_at=received, session=session)
        requoted += res["requoted"]
        if res["not_found"]:
            skipped[SKIP_NOT_FOUND] = skipped.get(SKIP_NOT_FOUND, 0) + res["not_found"]
    doc["quote_refresh"] = {"at": now.isoformat(), "market_session": session, "requests": requests,
                            "request_budget": max_requests, "cards_requoted": requoted,
                            "cards_skipped": dict(sorted(skipped.items())), "source": SOURCE, "writer": SCRIPT,
                            "note": "quote-only refresh; card economics and generated_at are from the build"}
    report.update(requests_made=requests, cards_requoted=requoted, skipped=skipped, market_session=session)
    if requests and not requoted and skipped.get(SKIP_CHAIN, 0) >= sum(len(g["cards"]) for g in plan["read"]):
        report["error"] = "every_chain_read_failed"
        return report
    if not write_atomic_if_unchanged(proposals, doc, st.st_mtime_ns):
        report["error"] = "snapshot_changed_during_refresh"
        return report
    report["wrote"] = True
    return report


def lane_output(report: Mapping[str, Any]) -> dict[str, Any]:
    if report.get("error"):
        reason = "dependency_unavailable"
        if str(report["error"]).startswith("schwab_access_mode"):
            reason = "disabled"
        elif str(report["error"]).startswith("snapshot_changed"):
            reason = "superseded_by_build"
        return {"produced_count": 0, "attempted_count": report.get("cards") or 0, "skipped_reasons": {reason: 1},
                "empty_reason": None}
    return {"produced_count": int(report.get("cards_requoted") or 0), "attempted_count": int(report.get("cards") or 0),
            "skipped_reasons": dict(report.get("skipped") or {}), "empty_reason": report.get("empty_reason")}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="the default: offline plan, no broker call, no write")
    g.add_argument("--apply", action="store_true", help="read chains (read_only mode only) and write live_quote")
    ap.add_argument("--proposals", help="desk snapshot (default: lib.desk_session.proposals_path(), the persistent-state copy)")
    ap.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS,
                    help=f"chain reads per run (1..{MAX_REQUESTS_CEILING}, default {DEFAULT_MAX_REQUESTS})")
    ap.add_argument("--state-root", help="persistent-state root for the receipt (default TRADEAI_STATE_ROOT)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--now", help=argparse.SUPPRESS)  # tests: pin the clock
    try:
        a = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    if not 1 <= a.max_requests <= MAX_REQUESTS_CEILING:
        print(f"--max-requests must be 1..{MAX_REQUESTS_CEILING}", file=sys.stderr)
        return 2
    now = datetime.fromisoformat(a.now.replace("Z", "+00:00")) if a.now else datetime.now(timezone.utc)
    proposals = Path(a.proposals) if a.proposals else _proposals_path()
    report = run(proposals=proposals, apply=bool(a.apply), max_requests=a.max_requests, now=now)
    from scripts.lib import lane_last_receipt as R

    receipt = R.receipt_path(LANE_ID, a.state_root)
    if not a.apply:
        if a.json:
            print(json.dumps(report, indent=1, default=str, sort_keys=True))
        else:
            print(f"options desk quote refresh (dry run, offline)  cards {report.get('cards')}  groups "
                  f"{report.get('groups')}  requests planned {report.get('requests_planned')}/{a.max_requests}")
            for p in report.get("plan") or []:
                print(f"  read {p['symbol']} {p['expiration']} ({p['cards']} card(s), side {p['contract_type'] or 'both'})")
            R.dry_run_report(LANE_ID, {k: report.get(k) for k in ("cards", "groups", "requests_planned", "skipped",
                                                                   "error")},
                             would_write=[str(proposals) + " (live_quote + quote_refresh only)", str(receipt)],
                             receipt=receipt)
        return 1 if report.get("error") else 0
    ok = not report.get("error")
    summary = {k: report.get(k) for k in ("schema", "as_of", "cards", "groups", "requests_made", "request_budget",
                                          "cards_requoted", "skipped", "market_session", "schwab_access_mode",
                                          "generated_at", "error")}
    written = R.write_lane_receipt(LANE_ID, ok=ok, exit_code=0 if ok else 1, started_at=now, script=SCRIPT,
                                   summary=summary, error=report.get("error"), path=receipt,
                                   output=lane_output(report))
    print(json.dumps({"mode": "apply", "ok": ok, "receipt": str(written) if written else None,
                      **{k: summary[k] for k in ("requests_made", "cards_requoted", "skipped", "error")}}, default=str))
    return 0 if ok and written is not None else 1


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
