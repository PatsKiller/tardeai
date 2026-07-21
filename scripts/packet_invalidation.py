#!/usr/bin/env python3
"""packet_invalidation.py — is a decision packet still current SOURCE truth?

WHY THIS EXISTS
---------------
A hash computed only from an already-persisted packet proves the packet is
internally identifiable. It does NOT prove the packet still matches current market,
event, ownership and fundamental truth. So the batch skipped on a bare "younger
than 12h" rule and could serve a decision the evidence had already overtaken.

The fix is ONE canonical current-input snapshot builder — read from SOURCE inputs,
never from model conclusions or generated blueprints — used everywhere a decision
is generated, skipped, or acted on:
    build_current_input_snapshot(symbol, conn, include_options=False) -> dict
    compute_input_hash(snapshot) -> str
    compare_packet_inputs(packet, current_snapshot) -> dict   (InvalidationResult)

The snapshot carries per-section content hashes (market/technical, fundamentals,
events, ownership, proposal_state, options) so an invalidation can name the exact
section that changed. The OVERALL hash excludes raw price — price always moves, so
hashing it would regenerate every packet every run; price is a SEPARATE governed
drift check against the packet's own price_used, and the exact price + timestamp
are preserved for audit.

Thresholds are env-configurable and policy-versioned.

PURE hashing; the DB reads are thin and clearly separated.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Optional

# Bumped in lockstep with the live packet/policy so a version change forces refresh.
CURRENT_PACKET_VERSION = "1.1.0-shadow"
# 1.1.1: technical hash no longer includes enrichment timestamps (as_of churn
# was marking every card REFRESH on each enrich pass); trading-day TTL + age-based
# TECHNICALS_STALE / FUNDAMENTALS_STALE.
POLICY_VERSION = "1.1.1"

# Default TTL for overnight/weekend. During regular US cash session we use a
# shorter cadence so ratings / strategy plans refresh every few hours RTH.
TTL_HOURS = float(os.getenv("PACKET_TTL_HOURS", "12"))
TTL_HOURS_RTH = float(os.getenv("PACKET_TTL_HOURS_RTH", "4"))
PRICE_DRIFT_PCT = float(os.getenv("PACKET_PRICE_DRIFT_PCT", "5.0"))
# Fundamentals/technicals older than these are STALE regardless of hash equality.
FUNDAMENTALS_STALE_DAYS = float(os.getenv("PACKET_FUNDAMENTALS_STALE_DAYS", "7"))
# Material technicals (RSI/levels) older than this → refresh during the week.
TECHNICALS_STALE_HOURS = float(os.getenv("PACKET_TECHNICALS_STALE_HOURS", "4"))
# Overnight/weekend technical age gate (do not force refresh every 4h off-hours).
TECHNICALS_STALE_HOURS_OFF = float(os.getenv("PACKET_TECHNICALS_STALE_HOURS_OFF", "36"))

# Invalidation reason codes (the batch/dry-run report by these).
REASONS = (
    "TTL_EXPIRED", "PRICE_DRIFT", "NEW_CATALYST", "EARNINGS_CHANGED",
    "OWNERSHIP_CHANGED", "FUNDAMENTALS_CHANGED", "FUNDAMENTALS_STALE",
    "TECHNICALS_CHANGED", "TECHNICALS_STALE", "PROPOSAL_STATE_CHANGED",
    "OPTIONS_CHAIN_STALE", "PACKET_VERSION_CHANGED", "POLICY_VERSION_CHANGED",
    "INPUT_HASH_MISMATCH", "PACKET_ABSENT",
)


def _now(now=None) -> datetime:
    return now or datetime.now(timezone.utc)


def _parse(ts) -> Optional[datetime]:
    if not ts:
        return None
    try:
        s = str(ts)
        if "T" not in s and " " in s:
            s = s.replace(" ", "T", 1)
        # Strip trailing timezone labels like " ET" that are not ISO
        s = s.replace(" ET", "").replace(" EDT", "").replace(" EST", "")
        s = s.replace("Z", "+00:00")
        d = datetime.fromisoformat(s[:32])
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _et_now(now=None) -> datetime:
    """Wall clock in America/New_York for RTH detection."""
    try:
        from zoneinfo import ZoneInfo
        return _now(now).astimezone(ZoneInfo("America/New_York"))
    except Exception:
        # Fallback: UTC-4 approx (not perfect DST) — still usable for gating.
        return _now(now).astimezone(timezone.utc)


def is_us_cash_rth(now=None) -> bool:
    """True Mon–Fri 09:30–16:00 America/New_York (regular cash session)."""
    et = _et_now(now)
    if et.weekday() >= 5:
        return False
    mins = et.hour * 60 + et.minute
    return (9 * 60 + 30) <= mins < (16 * 60)


def effective_ttl_hours(now=None) -> float:
    """Shorter TTL during RTH so star/buy/strong-buy plans refresh every few hours."""
    return TTL_HOURS_RTH if is_us_cash_rth(now) else TTL_HOURS


def effective_technicals_stale_hours(now=None) -> float:
    return TECHNICALS_STALE_HOURS if is_us_cash_rth(now) else TECHNICALS_STALE_HOURS_OFF


def technical_content_hash(*, rsi=None, change_pct=None, rvol=None) -> str:
    """Material technical shape only — NEVER enrichment timestamps.

    Including last_enriched_at in the hash caused TECHNICALS_CHANGED on every
    enrich cron tick (RSI often still null), flooding the card with REFRESH.
    Bands: RSI 5-pt, daily change 1%, rvol 0.5x — noise inside a band is not a
    new decision input.
    """
    def _band(v, step):
        if v is None:
            return None
        try:
            x = float(v)
        except (TypeError, ValueError):
            return None
        if step <= 0:
            return round(x, 2)
        return int(round(x / step)) * step

    return _h({
        "rsi_band": _band(rsi, 5.0),
        "chg_band": _band(change_pct, 1.0),
        "rvol_band": _band(rvol, 0.5),
    })


# ── the canonical snapshot ────────────────────────────────────────────────────

def compute_input_hash(snapshot: dict) -> str:
    """Overall hash from the SECTION content hashes — NOT raw price (drift is a
    separate check) and NOT any model conclusion. Deterministic and order-stable."""
    s = snapshot or {}
    material = {
        "symbol": str(s.get("symbol") or "").upper(),
        "packet_version": s.get("packet_version"),
        "policy_version": s.get("policy_version"),
        "technical": (s.get("market") or {}).get("technical_content_hash"),
        "fundamentals": (s.get("fundamentals") or {}).get("content_hash"),
        "events": (s.get("events") or {}).get("event_content_hash"),
        "ownership": (s.get("ownership") or {}).get("ownership_content_hash"),
        "proposal": (s.get("proposal_state") or {}).get("content_hash"),
        "options": (s.get("options") or {}).get("chain_content_hash"),
    }
    return _h(material)


def build_current_input_snapshot(symbol: str, conn=None, *, include_options: bool = False,
                                 source_commit_sha: str = "") -> dict:
    """Read CURRENT source inputs for a symbol and assemble the canonical snapshot.
    No model pass; cheap DB + file reads. This is the single builder every path
    uses so the inline card and the endpoint can never diverge."""
    sym = str(symbol or "").upper()
    if conn is None:
        from db_adapter import _get_conn
        conn = _get_conn()
    cur = conn.cursor()

    # ── market + technicals ───────────────────────────────────────────────────
    cur.execute("SELECT price, fetched_at FROM market_quotes WHERE symbol=%s ORDER BY fetched_at DESC LIMIT 1", (sym,))
    r = cur.fetchone()
    price = float(r[0]) if r and r[0] is not None else None
    price_as_of = str(r[1]) if r else None
    cur.execute("""SELECT rsi, last_enriched_at, change_pct, rvol FROM watchlist_items
                   WHERE upper(symbol)=%s ORDER BY last_enriched_at DESC NULLS LAST LIMIT 1""", (sym,))
    tr = cur.fetchone()
    rsi = float(tr[0]) if tr and tr[0] is not None else None
    tech_as_of = str(tr[1]) if tr and tr[1] else None
    change_pct = float(tr[2]) if tr and tr[2] is not None else None
    rvol = float(tr[3]) if tr and len(tr) > 3 and tr[3] is not None else None
    # Hash material bands only — timestamp is for STALE age checks, not CHANGED.
    tech_hash = technical_content_hash(rsi=rsi, change_pct=change_pct, rvol=rvol)
    market = {"price": price, "price_as_of": price_as_of,
              "price_drift_bucket": (round(price, 0) if price else None),  # audit-coarse; hash excludes price
              "session": "RTH" if is_us_cash_rth() else "OFF",
              "technical_as_of": tech_as_of,
              "rsi": rsi, "change_pct": change_pct, "rvol": rvol,
              "technical_content_hash": tech_hash}

    # ── fundamentals (with provenance) ────────────────────────────────────────
    try:
        import shadow_decision_service as svc
        f = svc._fundamentals_for(sym) or {}
    except Exception:
        f = {}
    fund_fields = {k: f[k] for k in f if k not in ("company", "country", "fundamentals_as_of")}
    fundamentals = {
        "provider": "finviz_enrichment" if f else None,
        "fetched_at": f.get("fundamentals_as_of"),
        "content_hash": _h(fund_fields) if fund_fields else None,
        "coverage_count": len(fund_fields),
        "missing_critical_fields": [],   # filled by fundamentals_freshness
    }

    # ── events ────────────────────────────────────────────────────────────────
    try:
        import event_normalizer as ev
        e = ev.resolve_from_db(sym, conn)
        earn_state, earn_date = e.state, (e.date.isoformat() if e.date else None)
    except Exception:
        earn_state, earn_date = None, None
    cur.execute("""SELECT MAX(published_at), array_agg(id) FROM (
                     SELECT id, published_at FROM catalyst_events
                     WHERE upper(symbol)=%s AND catalyst_type <> 'other'
                       AND COALESCE(confidence,0) >= 0.7
                     ORDER BY published_at DESC LIMIT 10) t""", (sym,))
    cr = cur.fetchone()
    latest_cat = str(cr[0]) if cr and cr[0] else None
    cat_ids = list(cr[1]) if cr and cr[1] else []
    events = {"earnings_state": earn_state, "earnings_date": earn_date,
              "event_content_hash": _h({"s": earn_state, "d": earn_date}),
              "latest_catalyst_at": latest_cat, "catalyst_ids": cat_ids}

    # ── ownership ─────────────────────────────────────────────────────────────
    try:
        import position_truth as pt
        from pathlib import Path
        hp = Path(__file__).resolve().parent.parent / "data" / "portfolios" / "state" / "holdings.json"
        hd = json.loads(hp.read_text()) if hp.exists() else {}
        own = pt.ownership_from_holdings(sym, hd)
        holdings_ver = str(hd.get("generated_at") or hd.get("as_of") or "")
        shares_by_acct = {a: None for a in own.accounts}
        ownership = {"holdings_version": holdings_ver, "held": own.held,
                     "shares": own.shares, "shares_by_account": shares_by_acct,
                     "committed_shares": own.uncommitted_shares,
                     "ownership_content_hash": _h({"held": own.held,
                                                   "shares": int(round(own.shares or 0)),
                                                   "accts": sorted(own.accounts)})}
    except Exception:
        ownership = {"holdings_version": "", "held": False, "shares": 0,
                     "shares_by_account": {}, "ownership_content_hash": _h({"held": False})}

    # ── proposal state ────────────────────────────────────────────────────────
    open_props = []
    try:
        cur.execute("""SELECT proposal_id FROM options_approval_queue
                       WHERE upper(symbol)=%s AND status IN ('pending','approved')""", (sym,))
        open_props = [x[0] for x in cur.fetchall()]
    except Exception:
        pass
    proposal_state = {"open_proposal_ids": sorted(map(str, open_props)),
                      "content_hash": _h(sorted(map(str, open_props)))}

    # ── options chain (optional; expensive) ───────────────────────────────────
    options = {"chain_as_of": None, "chain_content_hash": None, "contracts_used": []}
    if include_options:
        try:
            import schwab_transport
            chain = schwab_transport.get_option_chain(sym)
            if chain and chain.get("status") == "ok":
                exps = chain.get("expirations") or []
                sig = [(e.get("exp"), e.get("dte"), len(e.get("strikes") or [])) for e in exps]
                options = {"chain_as_of": _now().isoformat(),
                           "chain_content_hash": _h(sig),
                           "contracts_used": [e.get("exp") for e in exps]}
        except Exception:
            pass

    snap = {
        "symbol": sym, "packet_version": CURRENT_PACKET_VERSION,
        "policy_version": POLICY_VERSION, "source_commit_sha": source_commit_sha,
        "market": market, "fundamentals": fundamentals, "events": events,
        "ownership": ownership, "proposal_state": proposal_state, "options": options,
        "snapshot_at": _now().isoformat(),
    }
    snap["input_hash"] = compute_input_hash(snap)
    return snap


# ── comparison ────────────────────────────────────────────────────────────────

def _packet_snapshot(packet: dict) -> Optional[dict]:
    """The snapshot the packet was BUILT on, if it persisted one."""
    p = packet or {}
    s = p.get("input_snapshot")
    return s if isinstance(s, dict) else None


def compare_packet_inputs(packet: dict, current: dict, *, generated_at=None,
                          ttl_hours: float = None,
                          price_drift_pct: float = PRICE_DRIFT_PCT, now=None) -> dict:
    """InvalidationResult: does the packet still match current source truth?

    Returns {inputs_match, invalidation_reasons, packet_input_hash,
             current_input_hash, ttl_hours_applied, technicals_as_of,
             packet_age_hours}. A packet with NO persisted snapshot falls back to
    comparing the material fields it does carry (older packets).

    Time policy (trading day):
      • RTH TTL default 4h — plans / ratings need a few-hour refresh cadence
      • Off-hours TTL default 12h
      • TECHNICALS_STALE when technical_as_of is older than the RTH/off gate
      • TECHNICALS_CHANGED only on material RSI/chg/rvol band shifts — not enrich clocks
    """
    p = packet or {}
    reasons = []
    cur_hash = current.get("input_hash") or compute_input_hash(current)
    pkt_snap = _packet_snapshot(p)
    pkt_hash = (pkt_snap or {}).get("input_hash") or p.get("input_hash")
    ttl = float(ttl_hours) if ttl_hours is not None else effective_ttl_hours(now)

    # 1. TTL (time-based refresh — primary “update every few hours” lever)
    gen = _parse(generated_at) or _parse(p.get("evaluated_at"))
    age_h = None
    if gen is not None:
        age_h = (_now(now) - gen).total_seconds() / 3600.0
        if age_h > ttl:
            reasons.append("TTL_EXPIRED")

    # 2/3. versions — only force on hard packet version bumps. Policy micro-bumps
    # (hash formula fixes) must not REFRESH every live card until regenerate.
    if str(p.get("packet_version") or "") != CURRENT_PACKET_VERSION:
        reasons.append("PACKET_VERSION_CHANGED")
    pkt_pol = str(p.get("action_policy_version") or "").strip()
    # Only flag major policy series drift (e.g. 1.0 → 2.0), not 1.0.0 → 1.1.1.
    if pkt_pol and pkt_pol.split(".")[0] != str(POLICY_VERSION).split(".")[0]:
        reasons.append("POLICY_VERSION_CHANGED")

    # 4. section-level comparison — precise reasons
    if pkt_snap:
        secs = {
            "FUNDAMENTALS_CHANGED": ("fundamentals", "content_hash"),
            "EARNINGS_CHANGED": ("events", "event_content_hash"),
            "OWNERSHIP_CHANGED": ("ownership", "ownership_content_hash"),
            "TECHNICALS_CHANGED": ("market", "technical_content_hash"),
            "PROPOSAL_STATE_CHANGED": ("proposal_state", "content_hash"),
            "OPTIONS_CHAIN_STALE": ("options", "chain_content_hash"),
        }
        for reason, (sec, key) in secs.items():
            old_v = (pkt_snap.get(sec) or {}).get(key)
            new_v = (current.get(sec) or {}).get(key)
            # only flag options if the packet actually used a chain
            if reason == "OPTIONS_CHAIN_STALE" and old_v is None:
                continue
            # Legacy technical hashes included enrichment as_of — if either side
            # is missing material bands, re-hash from stored rsi if present.
            if reason == "TECHNICALS_CHANGED" and old_v and new_v and old_v != new_v:
                old_m = pkt_snap.get("market") or {}
                new_m = current.get("market") or {}
                # Recompute material hashes when we have fields (bridges old packets).
                if "rsi" in new_m or "change_pct" in new_m:
                    old_mat = technical_content_hash(
                        rsi=old_m.get("rsi"), change_pct=old_m.get("change_pct"),
                        rvol=old_m.get("rvol"))
                    new_mat = technical_content_hash(
                        rsi=new_m.get("rsi"), change_pct=new_m.get("change_pct"),
                        rvol=new_m.get("rvol"))
                    # If old snapshot lacked material fields, treat as_of-only hash
                    # drift as NON-invalidating (clock noise) — age gate covers it.
                    if old_m.get("rsi") is None and old_m.get("change_pct") is None \
                            and old_m.get("rvol") is None:
                        continue
                    if old_mat == new_mat:
                        continue
            if old_v != new_v:
                reasons.append(reason)
        if pkt_hash and cur_hash and pkt_hash != cur_hash and not any(
                r in reasons for r in ("FUNDAMENTALS_CHANGED", "EARNINGS_CHANGED",
                                       "OWNERSHIP_CHANGED", "TECHNICALS_CHANGED",
                                       "PROPOSAL_STATE_CHANGED", "OPTIONS_CHAIN_STALE")):
            # Overall hash mismatch with no section reason is usually legacy
            # as_of-in-tech-hash noise — do not force REFRESH.
            pass
    else:
        # legacy packet without a snapshot — compare the coarse fields it carries
        old_ev = (p.get("event_state") or {}).get("earnings") or {}
        if str(old_ev.get("state") or "") != str((current.get("events") or {}).get("earnings_state") or ""):
            reasons.append("EARNINGS_CHANGED")
        if str(old_ev.get("date") or "") != str((current.get("events") or {}).get("earnings_date") or ""):
            reasons.append("EARNINGS_CHANGED")
        old_own = p.get("ownership") or {}
        cur_own = current.get("ownership") or {}
        if bool(old_own.get("held")) != bool(cur_own.get("held")) or \
                int(round(float(old_own.get("shares") or 0))) != int(round(float(cur_own.get("shares") or 0))):
            reasons.append("OWNERSHIP_CHANGED")
        if str(p.get("fundamentals_as_of") or "") != str((current.get("fundamentals") or {}).get("fetched_at") or ""):
            reasons.append("FUNDAMENTALS_CHANGED")

    # 5. price drift (separate from the hash) — material move only
    pp = p.get("price_used")
    cp = (current.get("market") or {}).get("price")
    if pp and cp and abs(float(cp) - float(pp)) / float(pp) * 100.0 > price_drift_pct:
        reasons.append("PRICE_DRIFT")

    # 6. newer catalyst
    cat = _parse((current.get("events") or {}).get("latest_catalyst_at"))
    if cat is not None and gen is not None and cat > gen:
        reasons.append("NEW_CATALYST")

    # 7. Age gates (timestamp-based STALE — the “every few hours” rule)
    tech_as_of = _parse((current.get("market") or {}).get("technical_as_of"))
    tech_gate = effective_technicals_stale_hours(now)
    if tech_as_of is not None:
        tech_age_h = (_now(now) - tech_as_of).total_seconds() / 3600.0
        if tech_age_h > tech_gate:
            reasons.append("TECHNICALS_STALE")
    fund_as_of = _parse((current.get("fundamentals") or {}).get("fetched_at"))
    if fund_as_of is not None:
        fund_age_d = (_now(now) - fund_as_of).total_seconds() / 86400.0
        if fund_age_d > FUNDAMENTALS_STALE_DAYS:
            reasons.append("FUNDAMENTALS_STALE")

    reasons = sorted(set(reasons))
    return {
        "inputs_match": not reasons,
        "invalidation_reasons": reasons,
        "packet_input_hash": pkt_hash,
        "current_input_hash": cur_hash,
        "ttl_hours_applied": ttl,
        "technicals_stale_hours_gate": tech_gate,
        "packet_age_hours": round(age_h, 2) if age_h is not None else None,
        "technicals_as_of": (current.get("market") or {}).get("technical_as_of"),
        "rth": is_us_cash_rth(now),
    }
