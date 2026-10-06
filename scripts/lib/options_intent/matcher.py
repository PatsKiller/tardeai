"""Proactive matcher: for each standing options intent, the live Schwab contracts that fit it now.

Pure orchestration over injected callables (chain_fn, holdings, earnings_fn) so tests use fakes.
Writes nothing itself; scripts/options_intent_matcher.py persists the snapshot and decides on the
digest. Advisory only (MBI_BEHAVIOR = 0): no proposal is staged, no order exists on this path.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

try:
    from lib.options_intent import ranking as rk
except ModuleNotFoundError:
    from scripts.lib.options_intent import ranking as rk  # type: ignore

CONTRACT = "options-intent-match-v1"


def shares_by_account(holdings: List[Dict[str, Any]], symbol: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for h in holdings or []:
        if str(h.get("symbol") or "").upper() != symbol or h.get("is_cash"):
            continue
        acct = str(h.get("account") or "unknown")
        out[acct] = out.get(acct, 0.0) + float(h.get("shares") or h.get("quantity") or 0)
    return out


def match_intent(intent: Dict[str, Any], *, chain_fn: Callable[[str, str], Dict[str, Any]],
                 holdings: List[Dict[str, Any]], earnings_fn: Optional[Callable[[str], Dict[str, Any]]] = None,
                 liq: Optional[Dict[str, Any]] = None, top: int = 5,
                 now: Optional[datetime] = None) -> Dict[str, Any]:
    sym = intent["symbol"]
    plays = intent.get("plays") or {}
    earn = (earnings_fn(sym) if earnings_fn else None) or {}
    edate = earn.get("date") or intent.get("earnings_estimate")
    esrc = earn.get("source") if earn.get("date") else ("operator estimate" if intent.get("earnings_estimate") else "unknown")
    avoid = bool(intent.get("avoid_earnings_cross")) and bool(edate)
    out: Dict[str, Any] = {
        "contract": CONTRACT, "directive_id": intent.get("directive_id"), "symbol": sym,
        "intent_updated_at": intent.get("updated_at"),
        "as_of": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "thesis_target": intent.get("thesis_target"), "earnings": {"date": edate, "source": esrc},
        "plays": {}, "errors": [],
    }
    held = shares_by_account(holdings, sym)
    out["shares_by_account"] = held
    chains: Dict[str, Dict[str, Any]] = {}

    def chain(side: str) -> Dict[str, Any]:
        if side not in chains:
            c = chain_fn(sym, side) or {}
            if c.get("status") not in (None, "ok"):
                out["errors"].append(f"{side} chain: {c.get('status')} {str(c.get('error') or '')[:120]}")
                c = {}
            chains[side] = c
        return chains[side]

    if "cash_secured_put" in plays:
        c = chain("put")
        out["spot"] = c.get("underlying_price") or out.get("spot")
        out["quote_time"] = c.get("underlying_quote_time") or out.get("quote_time")
        out["plays"]["cash_secured_put"] = rk.rank_csp(c, plays["cash_secured_put"], earnings_date=edate,
                                                       avoid_earnings_cross=avoid, liq=liq, top=top)
    if "covered_call" in plays or "leap_call" in plays:
        c = chain("call")
        out["spot"] = out.get("spot") or c.get("underlying_price")
        out["quote_time"] = out.get("quote_time") or c.get("underlying_quote_time")
        if "covered_call" in plays:
            out["plays"]["covered_call"] = rk.rank_covered_calls(
                c, plays["covered_call"], thesis_target=intent.get("thesis_target"), shares_by_account=held,
                earnings_date=edate, avoid_earnings_cross=avoid, liq=liq, top=top)
            out["covered_call_floor"] = rk.cc_strike_floor(plays["covered_call"], spot=out.get("spot"),
                                                           thesis_target=intent.get("thesis_target"))
        if "leap_call" in plays:
            out["plays"]["leap_call"] = rk.rank_leaps(c, plays["leap_call"], top=max(1, top - 1))
    out["empty_reasons"] = {
        play: (f"no liquid contract fits DTE {spec.get('dte')} · delta {spec.get('delta')}"
               + (f" · strike ≥ {out.get('covered_call_floor')}" if play == "covered_call" and out.get("covered_call_floor") else "")
               + (f" · strike ≤ {spec.get('strike_max')}" if spec.get("strike_max") else "")
               + (f" · expiring before earnings {edate}" if avoid and play != "leap_call" else ""))
        for play, spec in plays.items() if not out["plays"].get(play)}
    return out


def link_desk_matches(match: Dict[str, Any], proposals: List[Dict[str, Any]], *, registry=None) -> Dict[str, Any]:
    """Join captured intent contracts to the existing identity/lifecycle, without staging.

    A shared contract may express a different strategy. Never inherit its CIO approval
    across strategies/accounts, nor mint a second thesis store for unmatched contracts.
    """
    from copy import deepcopy
    from scripts.lib.options_identity import contract_guid
    out = deepcopy(match)
    sym = str(out.get("symbol") or "").upper()
    linked, unmatched = 0, 0
    for play, rows in (out.get("plays") or {}).items():
        strategy = "long_call" if play == "leap_call" else play
        right = "put" if play == "cash_secured_put" else "call"
        for row in rows:
            guid = contract_guid(sym, right, row.get("strike"), row.get("exp"), registry=registry)
            row["contract_guid"] = guid
            row["source_receipt"] = {"source": "options_intent", "directive_id": out.get("directive_id"),
                                     "captured_at": out.get("as_of"), "quote_time": row.get("quote_time"),
                                     "scope": "standing intent contract match; not full-universe evaluation"}
            matches = []
            for p in proposals:
                same = bool(guid and p.get("contract_guid") == guid)
                if not guid or not p.get("contract_guid"):
                    same = (str(p.get("symbol") or "").upper() == sym
                            and p.get("strike") == row.get("strike")
                            and str(p.get("expiration") or "")[:10] == str(row.get("exp") or "")[:10]
                            and p.get("option_type") == right)
                if not same:
                    continue
                exact = p.get("strategy") == strategy
                matches.append({"proposal_id": p.get("id"), "option_strategy_guid": p.get("option_strategy_guid"),
                                "account": p.get("account"), "strategy": p.get("strategy"),
                                "relationship": "same_strategy" if exact else "same_contract_other_strategy",
                                "options_thesis_pin": (p.get("options_thesis") or {}).get("pin"),
                                "decision_guid": (p.get("cio_decision") or {}).get("decision_guid") if exact else None})
            row["desk_links"] = matches
            row["desk_status"] = "LINKED" if any(m['relationship'] == 'same_strategy' for m in matches) else "NOT_STAGED"
            row["next_action"] = ("Review the linked account-specific idea" if row['desk_status'] == 'LINKED' else
                                  "Account allocation and an account-specific thesis are required before proposal review")
            linked += row['desk_status'] == 'LINKED'
            unmatched += row['desk_status'] == 'NOT_STAGED'
            # Delta is not an assignment probability. Keep no misleading probability alias.
            row.pop("assignment_odds_pct", None)
            row.pop("called_away_odds_pct", None)
    out['desk_link_summary'] = {'linked_matches': linked, 'unstaged_matches': unmatched,
                               'match_count': linked + unmatched}
    return out


def review_packet(intent: Dict[str, Any], match: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Reuse the governed ensemble's persisted result/job store; never call a model on GET."""
    import hashlib
    import json
    facts = {k: intent.get(k) for k in ("symbol", "directive_id", "updated_at", "thesis_target", "goals", "plays", "rationale", "avoid_earnings_cross")}
    facts["captured_scan"] = ({k: match.get(k) for k in ("as_of", "quote_time", "spot", "earnings", "empty_reasons")} if match else None)
    if match:
        fields = ("exp", "strike", "bid", "ask", "mid", "delta", "oi", "quote_time", "credit_per_contract", "collateral_per_contract", "cost_per_contract")
        facts["captured_scan"]["plays"] = {play: [{k: row.get(k) for k in fields} for row in rows[:3]]
                                            for play, rows in (match.get("plays") or {}).items()}
    raw = json.dumps(facts, sort_keys=True, default=str)
    content = ("STANDING OPTIONS PLAN — advisory explanation, not a trade approval. "
               "In your reasoning, give a concise plain-English comparison of the requested strategies: "
               "purpose, capital, capped/unlimited upside, downside, expiry, and missing evidence. "
               "Use only the captured facts below. Do not invent live prices or current research. "
               "Delta is not assignment probability; annualized premium yield is not expected return. "
               "A target is an operator preference, not a forecast. No account allocation or CIO approval is implied.\n"
               + raw[:6900])
    return {"target_type": "options_intent", "target_id": "intent_" + hashlib.sha256(content.encode()).hexdigest()[:40],
            "content": content, "as_of": (match or {}).get("as_of"), "task": "options_intent_quality"}


def material_changes(prev: Optional[Dict[str, Any]], cur: Dict[str, Any], *,
                     min_improvement_pct: float = 10.0) -> List[str]:
    """Plain-English reasons a digest is worth sending: a play's best contract is new, or its
    annualized return / credit improved by at least `min_improvement_pct` percent."""
    reasons: List[str] = []
    for play, rows in (cur.get("plays") or {}).items():
        now_key = rk.best_key(rows)
        if now_key is None:
            continue
        before = rk.best_key(((prev or {}).get("plays") or {}).get(play) or [])
        label = play.replace("_", " ")
        if before is None:
            reasons.append(f"{label}: first match")
        elif now_key[0] != before[0]:
            reasons.append(f"{label}: new best contract")
        elif before[1] > 0 and (now_key[1] - before[1]) / before[1] * 100 >= min_improvement_pct:
            reasons.append(f"{label}: better by {((now_key[1] - before[1]) / before[1] * 100):.0f}%")
    return reasons


def _line(r: Dict[str, Any]) -> str:
    exp, k = r.get("exp"), r.get("strike")
    if r.get("play") == "cash_secured_put":
        return (f"  {exp} ${k:g}P · mid ${r['mid']:.2f} (${r['credit_per_contract']:,.0f} on ${r['collateral_per_contract']:,.0f}) · "
                f"{r['annualized_pct']:.0f}% annualized premium yield (not expected return) · breakeven ${r['breakeven']:.2f} · IV {r.get('iv')}% · Δ {r.get('delta')} · OI {r.get('oi')}")
    if r.get("play") == "covered_call":
        return (f"  {exp} ${k:g}C · mid ${r['mid']:.2f} (${r['credit_per_contract']:,.0f}/contract) · keeps +{r['upside_kept_pct']:.0f}% · "
                f"{r['annualized_pct']:.0f}% annualized premium yield (not expected return) · IV {r.get('iv')}% · Δ {r.get('delta')} · OI {r.get('oi')}")
    return (f"  {exp} ${k:g}C · ${r['cost_per_contract']:,.0f} vs ${r['stock_cost_100']:,.0f} stock · "
            f"time value {r['time_value_pct']:.1f}% · Δ {r.get('delta')} · OI {r.get('oi')}")


def digest_text(m: Dict[str, Any], reasons: List[str], *, per_play: int = 2) -> str:
    sym = m["symbol"]
    lines = [f"OPTIONS INTENT · {sym} · ${m.get('spot')} (Schwab {str(m.get('quote_time') or '')[11:16]} UTC)",
             "ADVISORY ONLY — NOT AN ORDER. Your standing plan" +
             (f", target ${m['thesis_target']:g}" if m.get("thesis_target") else "") + ".",
             "Why now: " + "; ".join(reasons)]
    names = {"cash_secured_put": "Cash-secured puts (get paid to buy lower)",
             "covered_call": "Covered calls (keep the upside)", "leap_call": "LEAP calls"}
    for play, rows in (m.get("plays") or {}).items():
        lines.append(names.get(play, play) + ":")
        if rows:
            lines += [_line(r) for r in rows[:per_play]]
        else:
            lines.append("  none fit now — " + str((m.get("empty_reasons") or {}).get(play) or "no match"))
    e = m.get("earnings") or {}
    lines.append(f"Earnings: {e.get('date') or 'unknown'} ({e.get('source')})")
    return "\n".join(lines)


def state_dir():
    """Where the matcher WRITES and the API READS (pinned to persistent state, like the Active Trader
    journal, so a per-process TRADEAI_ROOT cannot split writer and reader). OPTIONS_INTENT_DIR
    overrides (tests)."""
    import os
    from pathlib import Path
    env = os.environ.get("OPTIONS_INTENT_DIR", "").strip()
    if env:
        return Path(env)
    persistent = Path.home() / "trade-ai-releases" / "persistent-state"
    if (persistent / "PERSISTENT_STATE_ROOT.json").is_file():
        return persistent / "data" / "options_intent"
    try:
        from lib.canonical_store_registry import production_state_root
    except Exception:  # noqa: BLE001
        try:
            from scripts.lib.canonical_store_registry import production_state_root  # type: ignore
        except Exception:  # noqa: BLE001
            return persistent / "data" / "options_intent"
    return Path(production_state_root()) / "data" / "options_intent"


DEFAULT_CONFIG = {"mode": "shadow", "top_per_play": 5, "queue_proposals": False,
                  "liquidity": dict(rk.DEFAULT_LIQUIDITY),
                  "digest": {"min_improvement_pct": 10.0, "min_interval_min": 120, "per_play": 2}}


def load_config(path=None) -> Dict[str, Any]:
    """config/options_intent.yaml over DEFAULT_CONFIG. Unreadable → defaults (shadow: never sends)."""
    from pathlib import Path
    p = Path(path) if path else Path(__file__).resolve().parents[3] / "config" / "options_intent.yaml"
    cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_CONFIG.items()}
    try:
        import yaml
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return cfg
    for k, v in raw.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k] = {**cfg[k], **v}
        else:
            cfg[k] = v
    if cfg.get("mode") not in ("shadow", "send"):
        cfg["mode"] = "shadow"
    return cfg
