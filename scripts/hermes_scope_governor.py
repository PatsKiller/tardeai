#!/usr/bin/env python3
"""hermes_scope_governor.py — sole owner of watchlist_items.scope_tier (Phase 1, 2026-07-02).

Replaces the flat 4.1k always-scored universe with a governed ledger
(docs/design/HERMES_MATURITY_5_DESIGN.md §1.1):

  S0 pinned    holdings, open positions, live proposals, operator ticker directives
  S1 active    earned a live trigger (composite>=70, catalyst<48h, active watchlist,
               fresh directive hit); 14d without a fresh trigger -> S2
  S2 warm      incubator / strategy watchpool / capped directive names; 30d -> S3
  S3 archived  everything else — never scored on the clock; a fresh event reactivates to S1

Hard rails (config/hermes_scope_governor.yaml): |S0+S1+S2| <= total_cap; directive names
capped top-N per directive and globally; ai_discovered names get a grace TTL to earn a
trigger. Every tier change lands in scope_governor_audit with a reason. Advisory-only:
touches ONLY scope_tier/scope_expires_at/last_trigger_at/trigger_source — never status,
orders, gates, or 2FA. Honors data/runtime/HERMES_DISABLED.

  python3 scripts/hermes_scope_governor.py --dry-run     # default
  python3 scripts/hermes_scope_governor.py --apply
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))

KILL_SWITCH = PROJECT_ROOT / "data" / "runtime" / "HERMES_DISABLED"
CFG_FILE = PROJECT_ROOT / "config" / "hermes_scope_governor.yaml"


def _cfg():
    import yaml
    return yaml.safe_load(CFG_FILE.read_text())


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _fetch_tier_candidates(cur, cfg):
    """Compute the DESIRED tier per symbol from live sources. Returns {symbol: (tier, reason)}
    where tier is the best (lowest) tier the symbol qualifies for right now."""
    from watchlist_priority import PROPOSAL_ACTIVE_STATUSES, holdings_list

    s1 = cfg["tiers"]["s1"]
    s2 = cfg["tiers"]["s2"]
    want: dict[str, tuple[str, str]] = {}

    def claim(sym, tier, reason):
        sym = (sym or "").upper().strip()
        if not sym:
            return
        cur_t = want.get(sym)
        if cur_t is None or tier < cur_t[0]:
            want[sym] = (tier, reason)

    # Capped directive set FIRST — a raw directive hit is NOT a trigger (the discovery loop
    # restages hits every 30 min; uncapped it inflated 989 names into priority). Only names
    # inside top-N-per-directive / global cap may claim a tier via directives.
    # Deterministic winners (ORDER BY score then symbol) — an unordered LIMIT here made a
    # different 200 win every run, flapping hundreds of symbols between S3 and live tiers.
    cur.execute("""WITH ranked AS (
                     SELECT h.directive_id, UPPER(h.symbol) AS symbol,
                            MAX(wi.hermes_composite_score) AS comp,
                            ROW_NUMBER() OVER (PARTITION BY h.directive_id
                                               ORDER BY MAX(wi.hermes_composite_score) DESC NULLS LAST,
                                                        UPPER(h.symbol)) AS rn
                     FROM watch_directive_hits h
                     JOIN watch_directives d ON d.id = h.directive_id AND d.status='active'
                     LEFT JOIN watchlist_items wi ON UPPER(wi.symbol)=UPPER(h.symbol)
                                                  AND wi.status IN ('active','researched')
                     GROUP BY h.directive_id, UPPER(h.symbol)
                   )
                   SELECT symbol FROM ranked WHERE rn <= %s
                   GROUP BY symbol
                   ORDER BY MAX(comp) DESC NULLS LAST, symbol
                   LIMIT %s""",
                (cfg["directive_top_n"], cfg["directive_global_cap"]))
    directive_capped = {r[0] for r in cur.fetchall()}

    # ── S0 pinned ──────────────────────────────────────────────────────────
    for sym in holdings_list(PROJECT_ROOT):
        claim(sym, "S0", "holding")
    cur.execute("SELECT DISTINCT UPPER(symbol) FROM paper_trades WHERE status IN ('open','filled')")
    for (sym,) in cur.fetchall():
        claim(sym, "S0", "open_position")
    cur.execute("SELECT DISTINCT UPPER(symbol) FROM paper_trade_proposals WHERE status = ANY(%s)",
                (list(PROPOSAL_ACTIVE_STATUSES),))
    for (sym,) in cur.fetchall():
        claim(sym, "S0", "live_proposal")
    cur.execute("""SELECT DISTINCT UPPER(h.symbol)
                   FROM watch_directive_hits h
                   JOIN watch_directives d ON d.id = h.directive_id
                   WHERE d.status='active' AND d.kind='ticker'
                     AND d.created_by IN ('operator','operator_audit')""")
    for (sym,) in cur.fetchall():
        claim(sym, "S0", "operator_ticker_directive")

    # ── S1 active (trigger-earned) ─────────────────────────────────────────
    cur.execute("""SELECT DISTINCT UPPER(symbol) FROM watchlist_items
                   WHERE status IN ('active','researched') AND hermes_composite_score >= %s""",
                (s1["entry"]["composite_min"],))
    for (sym,) in cur.fetchall():
        claim(sym, "S1", f"composite>={s1['entry']['composite_min']}")
    cur.execute("""SELECT DISTINCT UPPER(symbol) FROM catalyst_events
                   WHERE created_at > NOW() - make_interval(hours => %s)""",
                (s1["entry"]["catalyst_hours"],))
    for (sym,) in cur.fetchall():
        claim(sym, "S1", "fresh_catalyst")
    cur.execute("SELECT DISTINCT UPPER(symbol) FROM watchlist_items WHERE status='active'")
    for (sym,) in cur.fetchall():
        claim(sym, "S1", "active_watchlist")
    cur.execute("""SELECT DISTINCT UPPER(symbol) FROM watch_directive_hits
                   WHERE surfaced_at > NOW() - make_interval(hours => %s)""",
                (s1["entry"]["directive_hit_hours"],))
    for (sym,) in cur.fetchall():
        if sym in directive_capped:
            claim(sym, "S1", "fresh_directive_hit")

    # ── S2 warm (structured pools) ─────────────────────────────────────────
    cur.execute("""SELECT DISTINCT UPPER(symbol) FROM incubator_universe
                   WHERE UPPER(status)='ACTIVE'
                     AND last_seen_at > NOW() - make_interval(days => %s)""",
                (s2["incubator_seen_days"],))
    for (sym,) in cur.fetchall():
        claim(sym, "S2", "incubator_active")
    cur.execute("""SELECT DISTINCT UPPER(symbol) FROM strategy_watchpool
                   WHERE UPPER(current_status)='ACTIVE'
                     AND (expires_at IS NULL OR expires_at > NOW())
                     AND last_evaluated_at > NOW() - make_interval(days => %s)""",
                (s2["watchpool_eval_days"],))
    for (sym,) in cur.fetchall():
        claim(sym, "S2", "watchpool_active")

    # Directive names without a fresh hit still hold warm S2 membership (capped set only).
    for sym in directive_capped:
        claim(sym, "S2", f"directive_top{cfg['directive_top_n']}")

    # ── Per-tier caps: excess S1 (by composite, S0 exempt) cascades to S2; excess S2 to no-claim ──
    cur.execute("""SELECT UPPER(symbol), MAX(hermes_composite_score)
                   FROM watchlist_items WHERE status IN ('active','researched')
                   GROUP BY UPPER(symbol)""")
    comp = {r[0]: (float(r[1]) if r[1] is not None else -1.0) for r in cur.fetchall()}
    for tier, cap_key, spill in (("S1", s1, "S2"), ("S2", s2, None)):
        members = sorted((s for s, (t, _r) in want.items() if t == tier),
                         key=lambda s: (-comp.get(s, -1.0), s))
        for sym in members[int(cap_key["cap"]):]:
            if spill:
                want[sym] = (spill, f"{tier.lower()}_cap_spill")
            else:
                del want[sym]

    return want


def _current_tiers(cur):
    cur.execute("""SELECT UPPER(symbol), MIN(scope_tier), MIN(last_trigger_at::text), MIN(source),
                          MIN(first_seen_at::text)
                   FROM watchlist_items WHERE status IN ('active','researched')
                   GROUP BY UPPER(symbol)""")
    return {r[0]: {"tier": r[1], "last_trigger": r[2], "source": r[3], "first_seen": r[4]}
            for r in cur.fetchall()}


def _age_days(iso_text):
    if not iso_text:
        return None
    try:
        dt = datetime.fromisoformat(iso_text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return None


def run(apply: bool = False) -> dict:
    if KILL_SWITCH.exists():
        out = {"ok": False, "reason": "HERMES_DISABLED kill switch present — governor idle"}
        print(json.dumps(out))
        return out

    cfg = _cfg()
    conn = _conn()
    cur = conn.cursor()
    run_id = f"sg_{uuid.uuid4().hex[:10]}"

    want = _fetch_tier_candidates(cur, cfg)
    have = _current_tiers(cur)

    # TTL demotions: an S1/S2 symbol whose desired tier is now worse (no live trigger claim)
    # only steps DOWN one tier per run, and only once its TTL since last_trigger_at expires.
    # A symbol in the universe with no claim at all is desired S3.
    s1_ttl = cfg["tiers"]["s1"]["ttl_days"]
    s2_ttl = cfg["tiers"]["s2"]["ttl_days"]
    grace = cfg["ai_discovered_grace_days"]

    changes = []   # (symbol, from, to, action, reason)
    for sym, cur_state in have.items():
        cur_tier = cur_state["tier"]
        desired, reason = want.get(sym, ("S3", "no_active_trigger"))
        if cur_tier is None:
            # first assignment — a recently discovered name with no claim yet gets its grace
            # window as S2 (time to earn a trigger) instead of instant S3
            if desired == "S3":
                age = _age_days(cur_state["first_seen"])
                if age is not None and age < grace:
                    changes.append((sym, None, "S2", "assign", f"discovery_grace_{grace}d (age {age}d)"))
                else:
                    changes.append((sym, None, "S3", "assign", f"no_trigger_grace_elapsed({age}d)"))
            else:
                changes.append((sym, None, desired, "assign", reason))
            continue
        if desired < cur_tier:                      # promotion — instant
            act = "reactivate" if cur_tier == "S3" else "promote"
            changes.append((sym, cur_tier, desired, act, reason))
        elif desired > cur_tier and cur_tier != "S0":
            # demotion — one step, TTL-gated on last_trigger_at
            ttl = s1_ttl if cur_tier == "S1" else s2_ttl
            lt = cur_state["last_trigger"]
            expired = True
            if lt:
                try:
                    lt_dt = datetime.fromisoformat(lt)
                    if lt_dt.tzinfo is None:
                        lt_dt = lt_dt.replace(tzinfo=timezone.utc)
                    expired = (datetime.now(timezone.utc) - lt_dt).days >= ttl
                except Exception:
                    pass
            if expired:
                step = {"S1": "S2", "S2": "S3"}[cur_tier]
                changes.append((sym, cur_tier, step, "demote", f"ttl_{ttl}d_no_trigger"))

    # Enforce the total cap: count post-change S0/S1/S2; truncate S2 then S1 tails to S3.
    post = {}
    for sym, st in have.items():
        post[sym] = st["tier"] or "S3"
    for sym, _f, to, _a, _r in changes:
        post[sym] = to
    n_live = sum(1 for t in post.values() if t in ("S0", "S1", "S2"))
    overflow = max(0, n_live - int(cfg["total_cap"]))
    if overflow:
        # Shed UNCLAIMED symbols first (TTL demotion-grace holders with no live trigger claim) —
        # shedding claimed symbols re-reactivates them next run and the universe flaps forever.
        # Within each group: S2 before S1, lowest composite first, never S0.
        cur.execute("""SELECT UPPER(symbol), MAX(hermes_composite_score)
                       FROM watchlist_items WHERE status IN ('active','researched')
                       GROUP BY UPPER(symbol)""")
        comp = {r[0]: (r[1] if r[1] is not None else -1) for r in cur.fetchall()}

        def _shed_group(tier, claimed):
            return sorted((s for s, t in post.items()
                           if t == tier and (s in want) == claimed),
                          key=lambda s: (comp.get(s, -1), s))
        shed_order = (_shed_group("S2", False) + _shed_group("S1", False) +
                      _shed_group("S2", True) + _shed_group("S1", True))
        for sym in shed_order[:overflow]:
            reason = "total_cap_overflow" + ("" if sym in want else "_ttl_grace_preempted")
            changes.append((sym, post[sym], "S3", "demote", reason))
            post[sym] = "S3"

    counts = {"S0": 0, "S1": 0, "S2": 0, "S3": 0}
    for t in post.values():
        counts[t] = counts.get(t, 0) + 1

    applied = 0
    if apply and changes:
        for sym, frm, to, action, reason in changes:
            trig = "NOW()" if action in ("promote", "reactivate", "assign") and to in ("S0", "S1", "S2") else "last_trigger_at"
            cur.execute(f"""UPDATE watchlist_items
                            SET scope_tier=%s, trigger_source=%s, last_trigger_at={trig}, updated_at=NOW()
                            WHERE UPPER(symbol)=%s AND status IN ('active','researched')""",
                        (to, reason, sym))
            applied += 1 if cur.rowcount else 0
            cur.execute("""INSERT INTO scope_governor_audit (run_id, symbol, action, from_tier, to_tier, reason)
                           VALUES (%s,%s,%s,%s,%s,%s)""", (run_id, sym, action, frm, to, reason))
        conn.commit()

    by_action = {}
    for _s, _f, _t, a, _r in changes:
        by_action[a] = by_action.get(a, 0) + 1
    out = {
        "ok": True, "apply": apply, "run_id": run_id,
        "desired_claims": len(want),
        "changes": len(changes), "by_action": by_action,
        "applied_symbols": applied,
        "post_counts": counts,
        "live_universe": counts["S0"] + counts["S1"] + counts["S2"],
        "total_cap": cfg["total_cap"],
        "sample_changes": [f"{s}:{f}->{t} ({a}:{r})" for s, f, t, a, r in changes[:12]],
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    print(json.dumps(out, indent=2))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    run(apply=args.apply and not args.dry_run)


if __name__ == "__main__":
    main()
