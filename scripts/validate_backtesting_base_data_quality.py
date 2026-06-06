#!/usr/bin/env python3
"""validate_backtesting_base_data_quality.py — ADVISORY base-data-quality scorecard for the v3
Backtesting page. Read-only. Produces a per-tab "data trust score" + provenance tiers. Never affects
GO/WAIT or any trading behaviour — purely a diagnostic surface.
  python3 scripts/validate_backtesting_base_data_quality.py [--json PATH]
"""
import os, sys, json, psycopg2


def main():
    c = psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname=os.environ["DB_NAME"],
                         user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"])
    cur = c.cursor()
    def one(s):
        try:
            cur.execute(s); return cur.fetchone()[0]
        except Exception:
            c.rollback(); return None

    def score(linked, total):
        return round(100 * linked / total, 1) if total else None

    rep = {"generated_at_note": "advisory only — does not affect GO/WAIT or trading", "tabs": {}, "tiers": {}}

    # canonical coverage
    ti_total = one("SELECT count(*) FROM trade_instances")
    rep["trade_instances"] = {
        "total": ti_total,
        "strategy_id_pct": score(one("SELECT count(*) FROM trade_instances WHERE strategy_id IS NOT NULL"), ti_total),
        "account_pct": score(one("SELECT count(*) FROM trade_instances WHERE execution_account IS NOT NULL"), ti_total),
        "source_system_pct": score(one("SELECT count(*) FROM trade_instances WHERE source_system IS NOT NULL"), ti_total),
    }

    # AI Trade Eval (structured_backtest_eval)
    ev_t = one("SELECT count(*) FROM trade_llm_reviews WHERE review_stage='structured_backtest_eval'")
    rep["tabs"]["ai_trade_eval"] = {
        "rows": ev_t,
        "trade_instance_linked": one("SELECT count(*) FROM trade_llm_reviews WHERE review_stage='structured_backtest_eval' AND trade_instance_id IS NOT NULL"),
        "account_pct": score(one("SELECT count(*) FROM trade_llm_reviews WHERE review_stage='structured_backtest_eval' AND account IS NOT NULL"), ev_t),
        "provenance_pct": score(one("SELECT count(*) FROM trade_llm_reviews WHERE review_stage='structured_backtest_eval' AND provenance_kind IS NOT NULL"), ev_t),
    }
    # LLM Review Coverage (all)
    lr_t = one("SELECT count(*) FROM trade_llm_reviews")
    rep["tabs"]["llm_review_coverage"] = {
        "rows": lr_t,
        "provenance_pct": score(one("SELECT count(*) FROM trade_llm_reviews WHERE provenance_kind IS NOT NULL"), lr_t),
        "infra_errors": one("SELECT count(*) FROM trade_llm_reviews WHERE error_class LIKE 'ollama_%'"),
        "parser_errors": one("SELECT count(*) FROM trade_llm_reviews WHERE error_class='parse_error'"),
        "stale_basis": one("SELECT count(*) FROM trade_llm_reviews WHERE status='superseded_stale_cost_basis'"),
        "retryable_backlog": one("SELECT count(*) FROM trade_llm_reviews WHERE retryable IS TRUE"),
    }
    # Entry Quality (trade_backtest_results)
    eq_t = one("SELECT count(*) FROM trade_backtest_results")
    rep["tabs"]["entry_quality"] = {
        "rows": eq_t,
        "trade_instance_linked": one("SELECT count(*) FROM trade_backtest_results WHERE trade_instance_id IS NOT NULL"),
        "linked_pct": score(one("SELECT count(*) FROM trade_backtest_results WHERE trade_instance_id IS NOT NULL"), eq_t),
    }
    # Edge comparison
    ec_t = one("SELECT count(*) FROM trade_edge_comparison")
    rep["tabs"]["edge_comparison"] = {"rows": ec_t,
        "trade_instance_linked": one("SELECT count(*) FROM trade_edge_comparison WHERE trade_instance_id IS NOT NULL")}
    # Hermes reflections
    rep["tabs"]["hermes_reflections"] = {
        "rows": one("SELECT count(*) FROM hermes_research_intelligence"),
        "trade_instance_linked": one("SELECT count(*) FROM hermes_research_intelligence WHERE trade_instance_id IS NOT NULL"),
        "closed_backlog": one("SELECT count(*) FROM trade_instances ti WHERE lower(coalesce(status,''))='closed' AND NOT EXISTS (SELECT 1 FROM hermes_research_intelligence h WHERE h.trade_instance_id=ti.id)"),
    }
    # Missed opportunities (dedup quality)
    rep["tabs"]["missed_opportunities"] = {"note": "deduped by proposal_id; verdict incl MIXED (see missed-opportunities endpoint)"}

    # trust tiers across trade_llm_reviews
    rep["tiers"] = {
        "excellent_exact_instance": one("SELECT count(*) FROM trade_llm_reviews WHERE trade_instance_id IS NOT NULL AND account IS NOT NULL AND provenance_confidence LIKE 'exact_%'"),
        "usable_exact_source_no_instance": one("SELECT count(*) FROM trade_llm_reviews WHERE trade_instance_id IS NULL AND provenance_confidence IN ('exact_backtest_trade','exact_backtest_row_no_instance')"),
        "advisory_simulation_or_unlinked": one("SELECT count(*) FROM trade_llm_reviews WHERE provenance_confidence='unlinked_imported_or_simulation' OR provenance_kind='simulation'"),
        "untrusted_stale_or_error": one("SELECT count(*) FROM trade_llm_reviews WHERE status IN ('error','superseded_stale_cost_basis')"),
    }
    print(json.dumps(rep, indent=2, default=str))
    if "--json" in sys.argv:
        json.dump(rep, open(sys.argv[sys.argv.index("--json") + 1], "w"), indent=2, default=str)
    c.close()


if __name__ == "__main__":
    main()
