"""Scope Governor decision engine — rules + outcome-aware scoring."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_config, tier_better
from .inputs import fetch_symbol_signals, load_regime_label
from .models import ScopeDecision, TIER_FREQUENCY, heat_of
from .outcome_bus import apply_bus_to_edge_scores, bus_tier_override
from .reactions import (
    apply_reaction_edge_adjustments,
    build_bus_reaction_plan,
    log_reactions_audit,
    write_reactions_runtime,
)
from .scoring import compute_edge_score
from .universe import build_governed_universe, write_universe_feed

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class ScopeGovernorEngine:
    """Single source of truth for Hermes monitoring scope."""

    def __init__(self, project_root: Path | None = None, cfg: dict[str, Any] | None = None):
        self.root = project_root or PROJECT_ROOT
        self.cfg = cfg or load_config(self.root / "config" / "hermes_scope_governor.yaml")

    def _fetch_tier_candidates(
        self,
        cur,
        edge_rank: dict[str, float],
        reaction_plan=None,
        health_map: dict[str, dict[str, Any]] | None = None,
        lifecycle_cfg: dict[str, Any] | None = None,
    ) -> tuple[dict[str, tuple[str, str]], list[dict[str, Any]]]:
        """Desired tier per symbol from live sources + outcome-aware ranking at cap boundaries."""
        from watchlist_priority import PROPOSAL_ACTIVE_STATUSES, holdings_list

        s1 = self.cfg["tiers"]["s1"]
        s2 = self.cfg["tiers"]["s2"]
        scfg = self.cfg.get("scoring") or {}
        hot_min = float(scfg.get("thresholds", {}).get("hot_min_score", 65))
        if reaction_plan and reaction_plan.hot_min_score_delta:
            hot_min += float(reaction_plan.hot_min_score_delta)
        want: dict[str, tuple[str, str]] = {}

        def claim(sym, tier, reason):
            sym = (sym or "").upper().strip()
            if not sym:
                return
            cur_t = want.get(sym)
            if cur_t is None or tier < cur_t[0]:
                want[sym] = (tier, reason)

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
                    (self.cfg["directive_top_n"], self.cfg["directive_global_cap"]))
        directive_capped = {r[0] for r in cur.fetchall()}

        # S0 pinned
        for sym in holdings_list(self.root):
            claim(sym, "S0", "holding")
        try:
            from lib.hermes_scope_governor.inputs import load_open_scalp_symbols
            for sym in load_open_scalp_symbols(self.root):
                claim(sym, "S0", "open_scalp")
        except Exception:
            pass
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

        # S1 active triggers
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

        # Outcome-aware S1 promotion for symbols with proven edge but no throughput trigger
        promote_syms = [
            s for s, score in edge_rank.items()
            if score >= hot_min and want.get(s, ("S3", ""))[0] not in ("S0", "S1")
        ]
        max_promo = int(scfg.get("max_outcome_promotions", 25))
        if reaction_plan and reaction_plan.max_outcome_promotions_delta:
            max_promo = max(0, max_promo + int(reaction_plan.max_outcome_promotions_delta))
        lc_cfg = lifecycle_cfg or {}
        rules = lc_cfg.get("transition_rules") or {}
        block_weak = bool(rules.get("block_weak_outcome_promotions", True))
        blocked_promotions: list[dict[str, Any]] = []
        from .watchlist_health import passes_promotion_health_gate
        for sym in sorted(promote_syms, key=lambda s: -edge_rank[s])[:max_promo]:
            if block_weak and health_map is not None:
                hm = health_map.get(sym) or {}
                ok, gate_reason = passes_promotion_health_gate(
                    float(hm.get("health_score") or 0),
                    str(hm.get("confidence_tier") or "sparse_data"),
                    int(hm.get("graded_n") or 0),
                    lc_cfg,
                )
                if not ok:
                    blocked_promotions.append({
                        "symbol": sym,
                        "edge_score": edge_rank.get(sym),
                        "health_score": hm.get("health_score"),
                        "confidence_tier": hm.get("confidence_tier"),
                        "graded_n": hm.get("graded_n"),
                        "reason": gate_reason,
                    })
                    continue
            claim(sym, "S1", f"outcome_edge>={hot_min}")

        # S2 warm pools
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
        for sym in directive_capped:
            claim(sym, "S2", f"directive_top{self.cfg['directive_top_n']}")

        # Cap enforcement — sort by edge_score (outcome-aware), then composite
        cur.execute("""SELECT UPPER(symbol), MAX(hermes_composite_score)
                       FROM watchlist_items WHERE status IN ('active','researched')
                       GROUP BY UPPER(symbol)""")
        comp = {r[0]: (float(r[1]) if r[1] is not None else -1.0) for r in cur.fetchall()}

        def sort_key(sym: str) -> tuple:
            return (-edge_rank.get(sym, 0.0), -comp.get(sym, -1.0), sym)

        for tier, cap_key, spill in (("S1", s1, "S2"), ("S2", s2, None)):
            members = sorted((s for s, (t, _r) in want.items() if t == tier), key=sort_key)
            for sym in members[int(cap_key["cap"]):]:
                if spill:
                    want[sym] = (spill, f"{tier.lower()}_cap_spill")
                else:
                    del want[sym]

        return want, blocked_promotions

    def _current_tiers(self, cur) -> dict[str, dict]:
        cur.execute("""SELECT UPPER(symbol), MIN(scope_tier), MIN(last_trigger_at::text), MIN(source),
                              MIN(first_seen_at::text)
                       FROM watchlist_items WHERE status IN ('active','researched')
                       GROUP BY UPPER(symbol)""")
        return {r[0]: {"tier": r[1], "last_trigger": r[2], "source": r[3], "first_seen": r[4]}
                for r in cur.fetchall()}

    @staticmethod
    def _age_days(iso_text: str | None) -> int | None:
        if not iso_text:
            return None
        try:
            dt = datetime.fromisoformat(iso_text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - dt).days
        except Exception:
            return None

    def run(self, conn, apply: bool = False, reaction_review: bool = False) -> dict[str, Any]:
        cur = conn.cursor()
        run_id = f"sg_{uuid.uuid4().hex[:10]}"
        regime = load_regime_label(cur)

        signals = fetch_symbol_signals(cur, self.cfg, self.root)
        edge_scores_map: dict[str, float] = {}
        edge_details: dict[str, dict] = {}
        for sym, sig in signals.items():
            es = compute_edge_score(sig, self.cfg, regime)
            edge_scores_map[sym] = es.edge_score
            edge_details[sym] = {
                "edge_score": es.edge_score,
                "components": es.components,
                "outcome_gate": es.outcome_gate,
                "reasons": es.reasons,
            }

        # Reinforce nightly outcome_bus feedback into edge ranking (closed-loop layer)
        edge_scores_map, edge_details = apply_bus_to_edge_scores(
            edge_scores_map, edge_details, self.cfg)

        have = self._current_tiers(cur)
        reaction_plan = build_bus_reaction_plan(
            self.cfg, run_id=run_id, regime_label=regime, review_mode=reaction_review, cur=cur,
        )
        tier_map = {sym: str(st.get("tier") or "S3") for sym, st in have.items()}
        edge_scores_map, edge_details = apply_reaction_edge_adjustments(
            edge_scores_map, edge_details, reaction_plan, tier_map)

        tier_reaction_plan = None if reaction_plan.review_mode else reaction_plan
        lifecycle_cfg: dict[str, Any] = {}
        health_map: dict[str, dict[str, Any]] = {}
        blocked_promotions: list[dict[str, Any]] = []
        try:
            from .watchlist_lifecycle import load_lifecycle_config, prepare_watchlist_health_context
            lifecycle_cfg = load_lifecycle_config()
            if lifecycle_cfg.get("enabled", True):
                health_map, _, _, _ = prepare_watchlist_health_context(
                    cur, signals, edge_scores_map, edge_details, regime, lifecycle_cfg,
                )
        except Exception:
            pass
        want, blocked_promotions = self._fetch_tier_candidates(
            cur, edge_scores_map, reaction_plan=tier_reaction_plan,
            health_map=health_map, lifecycle_cfg=lifecycle_cfg,
        )

        s1_ttl = self.cfg["tiers"]["s1"]["ttl_days"]
        s2_ttl = self.cfg["tiers"]["s2"]["ttl_days"]
        grace = self.cfg["ai_discovered_grace_days"]
        scfg = self.cfg.get("scoring") or {}
        gates = scfg.get("outcome_gates") or {}
        pause_miss = float(gates.get("pause_miss_rate", 0.75))
        min_graded = int(gates.get("min_graded_samples", 3))

        decisions: list[ScopeDecision] = []
        for sym, cur_state in have.items():
            cur_tier = cur_state["tier"]
            desired, reason = want.get(sym, ("S3", "no_active_trigger"))
            detail = edge_details.get(sym, {})
            edge = edge_scores_map.get(sym)

            # Outcome demotion pressure — graft gate: require evidence threshold
            sig = signals.get(sym)
            if sig and cur_tier not in ("S0", None):
                graded = sig.outcome_hits + sig.outcome_misses + sig.outcome_neutral
                if graded >= min_graded:
                    miss_rate = sig.outcome_misses / graded
                    if miss_rate >= pause_miss and desired in ("S1", "S2"):
                        desired = "S3"
                        reason = f"outcome_pause(miss_rate={miss_rate:.0%},n={graded})"

            # Explicit outcome_bus feedback (nightly rollups from feedback agent)
            bus_override = bus_tier_override(sym, desired, cur_tier, self.cfg)
            if bus_override:
                desired, reason = bus_override

            if cur_tier is None:
                if desired == "S3":
                    age = self._age_days(cur_state["first_seen"])
                    if age is not None and age < grace:
                        decisions.append(ScopeDecision(sym, None, "S2", "assign",
                            f"discovery_grace_{grace}d (age {age}d)", edge, heat_of("S2"),
                            TIER_FREQUENCY["S2"], detail))
                    else:
                        decisions.append(ScopeDecision(sym, None, "S3", "assign",
                            f"no_trigger_grace_elapsed({age}d)", edge, heat_of("S3"),
                            TIER_FREQUENCY["S3"], detail))
                else:
                    decisions.append(ScopeDecision(sym, None, desired, "assign", reason, edge,
                        heat_of(desired), TIER_FREQUENCY.get(desired, "on_event_only"), detail))
                continue

            if tier_better(desired, cur_tier):
                act = "reactivate" if cur_tier == "S3" else "promote"
                decisions.append(ScopeDecision(sym, cur_tier, desired, act, reason, edge,
                    heat_of(desired), TIER_FREQUENCY.get(desired, "on_event_only"), detail))
            elif tier_better(cur_tier, desired) and cur_tier != "S0":
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
                    decisions.append(ScopeDecision(sym, cur_tier, step, "demote",
                        f"ttl_{ttl}d_no_trigger", edge, heat_of(step),
                        TIER_FREQUENCY.get(step, "on_event_only"), detail))

        post = {sym: st["tier"] or "S3" for sym, st in have.items()}
        for d in decisions:
            post[d.symbol] = d.to_tier

        n_live = sum(1 for t in post.values() if t in ("S0", "S1", "S2"))
        overflow = max(0, n_live - int(self.cfg["total_cap"]))
        if overflow:
            cur.execute("""SELECT UPPER(symbol), MAX(hermes_composite_score)
                           FROM watchlist_items WHERE status IN ('active','researched')
                           GROUP BY UPPER(symbol)""")
            comp = {r[0]: (r[1] if r[1] is not None else -1) for r in cur.fetchall()}

            def _shed_group(tier, claimed):
                return sorted(
                    (s for s, t in post.items() if t == tier and (s in want) == claimed),
                    key=lambda s: (edge_scores_map.get(s, 0), comp.get(s, -1), s),
                )

            shed_order = (_shed_group("S2", False) + _shed_group("S1", False) +
                          _shed_group("S2", True) + _shed_group("S1", True))
            for sym in shed_order[:overflow]:
                rsn = "total_cap_overflow" + ("" if sym in want else "_ttl_grace_preempted")
                decisions.append(ScopeDecision(sym, post[sym], "S3", "demote", rsn,
                    edge_scores_map.get(sym), heat_of("S3"), TIER_FREQUENCY["S3"],
                    edge_details.get(sym, {})))
                post[sym] = "S3"

        counts = {"S0": 0, "S1": 0, "S2": 0, "S3": 0}
        for t in post.values():
            counts[t] = counts.get(t, 0) + 1

        reaction_audit_logged = 0
        applied = 0
        if apply and decisions:
            for d in decisions:
                trig = "NOW()" if d.action in ("promote", "reactivate", "assign") and d.to_tier in ("S0", "S1", "S2") else "last_trigger_at"
                reason_payload = d.reason
                if d.evidence:
                    try:
                        reason_payload = f"{d.reason}|edge={json.dumps(d.evidence, separators=(',', ':'))}"
                    except Exception:
                        pass
                cur.execute(f"""UPDATE watchlist_items
                                SET scope_tier=%s, trigger_source=%s, last_trigger_at={trig}, updated_at=NOW()
                                WHERE UPPER(symbol)=%s AND status IN ('active','researched')""",
                            (d.to_tier, reason_payload[:500], d.symbol))
                applied += 1 if cur.rowcount else 0
                cur.execute("""INSERT INTO scope_governor_audit (run_id, symbol, action, from_tier, to_tier, reason)
                               VALUES (%s,%s,%s,%s,%s,%s)""",
                            (run_id, d.symbol, d.action, d.from_tier, d.to_tier, reason_payload[:500]))

        if apply:
            reaction_audit_logged = log_reactions_audit(cur, run_id, reaction_plan, apply=True)
            if not reaction_plan.review_mode:
                write_reactions_runtime(reaction_plan, apply=True)
            if applied or reaction_audit_logged:
                conn.commit()

        gov = build_governed_universe(
            run_id, regime, int(self.cfg["total_cap"]), post, edge_scores_map, decisions, self.cfg)
        feed_path = write_universe_feed(gov, apply=apply)

        lifecycle_snap: dict[str, Any] = {}
        try:
            from .watchlist_lifecycle import build_and_persist_lifecycle
            bus_feedback: dict[str, dict[str, Any]] = {}
            try:
                from lib.hermes_outcome_bus.bus import read_outcome_bus
                bus = read_outcome_bus() or {}
                for fb in bus.get("feedback_to_governor") or []:
                    s = str(fb.get("symbol") or "").upper().strip()
                    if s:
                        bus_feedback[s] = fb
            except Exception:
                pass
            lifecycle_snap = build_and_persist_lifecycle(
                run_id, signals, edge_scores_map, edge_details, have, want,
                decisions, post, bus_feedback, apply=apply,
                health_map=health_map, regime_label=regime,
                blocked_promotions=blocked_promotions, cur=cur,
            )
        except Exception as lc_err:
            lifecycle_snap = {"ok": False, "error": str(lc_err)[:120]}

        holdings_snap: dict[str, Any] = {}
        try:
            from lib.hermes_holdings_lifecycle.holdings_lifecycle import build_and_persist_holdings_lifecycle
            holdings_snap = build_and_persist_holdings_lifecycle(run_id=run_id)
        except Exception as hl_err:
            holdings_snap = {"ok": False, "error": str(hl_err)[:120]}

        by_action: dict[str, int] = {}
        for d in decisions:
            by_action[d.action] = by_action.get(d.action, 0) + 1

        result = {
            "ok": True,
            "apply": apply,
            "run_id": run_id,
            "regime_label": regime,
            "desired_claims": len(want),
            "changes": len(decisions),
            "by_action": by_action,
            "applied_symbols": applied,
            "post_counts": counts,
            "counts_by_heat": gov.counts_by_heat,
            "live_universe": gov.live_universe,
            "total_cap": self.cfg["total_cap"],
            "estimated_score_computations_per_day": gov.estimated_score_computations_per_day,
            "universe_feed": str(feed_path) if feed_path else None,
            "sample_changes": [f"{d.symbol}:{d.from_tier}->{d.to_tier} ({d.action}:{d.reason})" for d in decisions[:12]],
            "bus_reactions": reaction_plan.reactions if reaction_plan.enabled else [],
            "bus_reactions_suppressed": reaction_plan.suppressed if reaction_plan.enabled else [],
            "bus_reaction_review_mode": reaction_plan.review_mode,
            "bus_reaction_regime_modifier": reaction_plan.regime_modifier,
            "bus_reaction_metrics": reaction_plan.bus_metrics,
            "bus_reaction_audit_logged": reaction_audit_logged,
            "watchlist_lifecycle": {
                "summary": lifecycle_snap.get("summary") or {},
                "pending_count": lifecycle_snap.get("pending_count", 0),
                "blocked_promotion_count": lifecycle_snap.get("blocked_promotion_count", 0),
                "review_mode": lifecycle_snap.get("review_mode", True),
            },
            "holdings_lifecycle": {
                "summary": holdings_snap.get("summary") or {},
                "position_count": holdings_snap.get("position_count", 0),
                "review_mode": holdings_snap.get("review_mode", True),
            },
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        try:
            from .heartbeat import GOVERNOR_HEARTBEAT, write_heartbeat
            write_heartbeat(GOVERNOR_HEARTBEAT, {
                "ok": True, "apply": apply, "run_id": run_id,
                "live_universe": result["live_universe"],
                "changes": result["changes"],
                "counts_by_heat": result["counts_by_heat"],
            })
        except Exception:
            pass
        return result