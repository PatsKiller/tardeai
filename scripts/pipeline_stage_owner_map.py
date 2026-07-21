"""
pipeline_stage_owner_map.py — Canonical ownership map for all 31 pipeline stages.

Read-only. No trades, no orders. Importable by other scripts/API.

Usage:
    python scripts/pipeline_stage_owner_map.py --output-json stages.json --output-md stages.md --verbose
"""

import argparse
import json
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))
from dotenv import load_dotenv; load_dotenv(PROJ / ".env")


# ─────────────────────────────────────────────────────────────────────────────
# Canonical stage ownership registry — 31 stages, 7 categories
# ─────────────────────────────────────────────────────────────────────────────

STAGE_OWNERS: dict[str, dict] = {

    # ── Data Collection (5) ──────────────────────────────────────────────────
    "finviz_screener_runner": {
        "pipeline_key": "finviz_screener_runner",
        "display_name": "Finviz Screener",
        "category": "Data Collection",
        "owning_script": "scripts/finviz_screener_runner.py",
        "owning_wrapper": "scripts/cron_wrapper.sh",
        "cron_pattern": "6:35 AM M-F (via classify pipeline)",
        "log_paths": ["logs/finviz_screener.log"],
        "output_tables": ["trade_ai_scans"],
        "safe_dry_run_cmd": "python scripts/finviz_screener_runner.py --dry-run",
        "expected_rows_desc": "200-800 scan rows per run",
        "failure_hint": "Check Finviz rate limits; verify network connectivity.",
        "operator_next_action": "Run dry-run to confirm Finviz is reachable, then check logs/finviz_screener.log.",
    },
    "social_ingest": {
        "pipeline_key": "social_ingest",
        "display_name": "Social Ingest",
        "category": "Data Collection",
        "owning_script": "scripts/social_ingest.py",
        "owning_wrapper": None,
        "cron_pattern": "7:15 AM M-F",
        "log_paths": ["logs/social_ingest.log"],
        "output_tables": ["social_mentions"],
        "safe_dry_run_cmd": "python scripts/social_ingest.py --dry-run",
        "expected_rows_desc": "50-500 social mention rows per run",
        "failure_hint": "Check Reddit/Twitter API keys in .env; verify rate limits.",
        "operator_next_action": "Run dry-run to confirm API connectivity, then review logs.",
    },
    "news_ingestion": {
        "pipeline_key": "news_ingestion",
        "display_name": "News Ingestion",
        "category": "Data Collection",
        "owning_script": "scripts/news_ingestion.py",
        "owning_wrapper": None,
        "cron_pattern": "6:30 AM M-F",
        "log_paths": ["logs/news_ingestion.log"],
        "output_tables": ["news_articles"],
        "safe_dry_run_cmd": "python scripts/news_ingestion.py --priority --dry-run",
        "expected_rows_desc": "100-1000 news articles per run",
        "failure_hint": "Check Brave/DuckDuckGo API keys; verify web_news_fetcher.py works.",
        "operator_next_action": "Run dry-run, check logs/news_ingestion.log for HTTP errors.",
    },
    "fred_data_ingest": {
        "pipeline_key": "fred_data_ingest",
        "display_name": "FRED Data Ingest",
        "category": "Data Collection",
        "owning_script": "scripts/fred_data_ingest.py",
        "owning_wrapper": None,
        "cron_pattern": "7:20 AM M-F",
        "log_paths": ["logs/fred_data.log"],
        "output_tables": ["fred_economic_data"],
        "safe_dry_run_cmd": "python scripts/fred_data_ingest.py --dry-run",
        "expected_rows_desc": "20-50 economic indicator rows per run",
        "failure_hint": "Check FRED_API_KEY in .env; FRED may be down for maintenance.",
        "operator_next_action": "Verify FRED API key, run dry-run, check logs/fred_data.log.",
    },
    "sec_data_ingest": {
        "pipeline_key": "sec_data_ingest",
        "display_name": "SEC Data Ingest",
        "category": "Data Collection",
        "owning_script": "scripts/sec_data_ingest.py",
        "owning_wrapper": None,
        "cron_pattern": "7:25 AM M-F",
        "log_paths": ["logs/sec_data.log"],
        "output_tables": ["sec_filings"],
        "safe_dry_run_cmd": "python scripts/sec_data_ingest.py --dry-run",
        "expected_rows_desc": "10-100 SEC filing rows per run",
        "failure_hint": "SEC EDGAR has rate limits (10 req/sec); check User-Agent header.",
        "operator_next_action": "Run dry-run, verify SEC EDGAR connectivity in logs/sec_data.log.",
    },

    # ── Enrichment (4) ───────────────────────────────────────────────────────
    "finviz_enrichment": {
        "pipeline_key": "finviz_enrichment",
        "display_name": "Finviz Enrichment",
        "category": "Enrichment",
        "owning_script": "scripts/finviz_enrichment.py",
        "owning_wrapper": None,
        "cron_pattern": "7:10 AM M-F",
        "log_paths": ["logs/finviz_enrichment.log"],
        "output_tables": ["finviz_fundamentals"],
        "safe_dry_run_cmd": "python scripts/finviz_enrichment.py --dry-run",
        "expected_rows_desc": "200-600 enriched ticker rows per run",
        "failure_hint": "Finviz scraping may hit rate limits; check for HTML changes.",
        "operator_next_action": "Run dry-run, inspect logs/finviz_enrichment.log for scrape errors.",
    },
    "catalyst_enrichment": {
        "pipeline_key": "catalyst_enrichment",
        "display_name": "Catalyst Enrichment",
        "category": "Enrichment",
        "owning_script": "scripts/catalyst_enrichment.py",
        "owning_wrapper": None,
        "cron_pattern": "7:30 AM M-F",
        "log_paths": ["logs/catalyst_enrichment.log"],
        "output_tables": ["catalysts"],
        "safe_dry_run_cmd": "python scripts/catalyst_enrichment.py --dry-run",
        "expected_rows_desc": "50-300 catalyst rows per run",
        "failure_hint": "LLM API quota or news source timeout; check API keys.",
        "operator_next_action": "Run dry-run, review logs/catalyst_enrichment.log.",
    },
    "symbol_enrichment": {
        "pipeline_key": "symbol_enrichment",
        "display_name": "Symbol Enrichment",
        "category": "Enrichment",
        "owning_script": "scripts/symbol_enrichment.py",
        "owning_wrapper": None,
        "cron_pattern": "7:40 AM M-F",
        "log_paths": ["logs/symbol_enrichment.log"],
        "output_tables": ["symbol_metadata"],
        "safe_dry_run_cmd": "python scripts/symbol_enrichment.py --dry-run",
        "expected_rows_desc": "100-500 symbol metadata rows per run",
        "failure_hint": "Check data provider API keys; possible ticker delisting issues.",
        "operator_next_action": "Run dry-run, check logs/symbol_enrichment.log.",
    },
    "rag_indexer": {
        "pipeline_key": "rag_indexer",
        "display_name": "RAG Indexer",
        "category": "Enrichment",
        "owning_script": "scripts/rag_indexer.py",
        "owning_wrapper": None,
        "cron_pattern": "7:50 AM M-F",
        "log_paths": ["logs/rag_indexer.log"],
        "output_tables": ["rag_documents", "rag_embeddings"],
        "safe_dry_run_cmd": "python scripts/rag_indexer.py --dry-run",
        "expected_rows_desc": "50-500 document embeddings per run",
        "failure_hint": "Embedding API quota exhausted or vector DB connection failure.",
        "operator_next_action": "Run dry-run, check logs/rag_indexer.log for embedding errors.",
    },

    # ── Scoring (4) ──────────────────────────────────────────────────────────
    "trade_ai_orchestrator": {
        "pipeline_key": "trade_ai_orchestrator",
        "display_name": "Orchestrator",
        "category": "Scoring",
        "owning_script": "scripts/trade_ai_orchestrator.py",
        "owning_wrapper": None,
        "cron_pattern": "8:00 AM M-F",
        "log_paths": ["logs/orchestrator.log"],
        "output_tables": ["pipeline_runs", "trade_ai_scores"],
        "safe_dry_run_cmd": "python scripts/trade_ai_orchestrator.py --dry-run",
        "expected_rows_desc": "Full pipeline pass; 200-800 scored tickers",
        "failure_hint": "Upstream data may be stale; check finviz/news stages first.",
        "operator_next_action": "Verify upstream stages completed, then run dry-run.",
    },
    "indicator_engine": {
        "pipeline_key": "indicator_engine",
        "display_name": "Indicator Engine",
        "category": "Scoring",
        "owning_script": "scripts/indicator_engine.py",
        "owning_wrapper": None,
        "cron_pattern": "8:10 AM M-F",
        "log_paths": ["logs/indicator_engine.log"],
        "output_tables": ["technical_indicators"],
        "safe_dry_run_cmd": "python scripts/indicator_engine.py --dry-run",
        "expected_rows_desc": "200-600 indicator rows per run",
        "failure_hint": "Price data source may be down; check market data API.",
        "operator_next_action": "Run dry-run, check logs/indicator_engine.log.",
    },
    "premarket_watcher": {
        "pipeline_key": "premarket_watcher",
        "display_name": "Premarket Watcher",
        "category": "Scoring",
        "owning_script": "scripts/premarket_watcher.py",
        "owning_wrapper": None,
        "cron_pattern": "every 5m 6:00-9:30 AM M-F",
        "log_paths": ["logs/premarket_watcher.log"],
        "output_tables": ["premarket_movers"],
        "safe_dry_run_cmd": "python scripts/premarket_watcher.py --dry-run",
        "expected_rows_desc": "10-50 premarket mover rows per cycle",
        "failure_hint": "Premarket data only available before open; check timing.",
        "operator_next_action": "Run dry-run during premarket hours, check logs.",
    },
    "agent_router": {
        "pipeline_key": "agent_router",
        "display_name": "Agent Router",
        "category": "Scoring",
        "owning_script": "scripts/agent_router.py",
        "owning_wrapper": "scripts/agent_router_cron.sh",
        "cron_pattern": "6:15 AM M-F (full), intraday refreshes",
        "log_paths": ["logs/agent_router.log", "logs/agent_router_cron.log"],
        "output_tables": ["agent_analysis", "agent_context"],
        "safe_dry_run_cmd": "python scripts/agent_router.py --dry-run",
        "expected_rows_desc": "50-200 agent analysis rows per run",
        "failure_hint": "LLM API quota or agent timeout; check agent_router_cron.sh logs.",
        "operator_next_action": "Run dry-run, review logs/agent_router.log for LLM errors.",
    },

    # ── Intelligence (4) ─────────────────────────────────────────────────────
    "process_watchlist_agent_jobs": {
        "pipeline_key": "process_watchlist_agent_jobs",
        "display_name": "Agent Jobs Processor",
        "category": "Intelligence",
        "owning_script": "scripts/process_watchlist_agent_jobs.py",
        "owning_wrapper": None,
        "cron_pattern": "every 15m M-F",
        "log_paths": ["logs/watchlist_agent_jobs.log"],
        "output_tables": ["agent_job_results"],
        "safe_dry_run_cmd": "python scripts/process_watchlist_agent_jobs.py --dry-run",
        "expected_rows_desc": "5-50 processed job rows per cycle",
        "failure_hint": "Agent queue may be empty; check upstream agent_router output.",
        "operator_next_action": "Run dry-run, check logs/watchlist_agent_jobs.log.",
    },
    "agent_watchlist_engine": {
        "pipeline_key": "agent_watchlist_engine",
        "display_name": "Watchlist Engine",
        "category": "Intelligence",
        "owning_script": "scripts/agent_watchlist_engine.py",
        "owning_wrapper": "scripts/agent_intelligence_cron.sh",
        "cron_pattern": "6:25 AM M-F (daily)",
        "log_paths": ["logs/agent_watchlist_engine.log"],
        "output_tables": ["watchlist_items", "watchlist_research"],
        "safe_dry_run_cmd": "python scripts/agent_watchlist_engine.py --dry-run",
        "expected_rows_desc": "20-100 watchlist item updates per run",
        "failure_hint": "Check agent_intelligence_cron.sh; LLM may be over quota.",
        "operator_next_action": "Run dry-run, check logs/agent_watchlist_engine.log.",
    },
    "cio_decision_engine": {
        "pipeline_key": "cio_decision_engine",
        "display_name": "CIO Decision Engine",
        "category": "Intelligence",
        "owning_script": "scripts/cio_decision_engine.py",
        "owning_wrapper": None,
        "cron_pattern": "7:00 AM M-F",
        "log_paths": ["logs/cio_decisions.log"],
        "output_tables": ["cio_decisions"],
        "safe_dry_run_cmd": "python scripts/cio_decision_engine.py --run --dry-run",
        "expected_rows_desc": "5-20 CIO decision rows per run",
        "failure_hint": "LLM quota or missing upstream enrichment data.",
        "operator_next_action": "Run dry-run, check logs/cio_decisions.log for LLM errors.",
    },
    "pipeline_watchdog": {
        "pipeline_key": "pipeline_watchdog",
        "display_name": "Pipeline Watchdog",
        "category": "Intelligence",
        "owning_script": "scripts/pipeline_watchdog.py",
        "owning_wrapper": None,
        "cron_pattern": "every 5m M-F",
        "log_paths": ["logs/pipeline_watchdog.log"],
        "output_tables": ["watchdog_actions", "pipeline_runs"],
        "safe_dry_run_cmd": "python scripts/pipeline_watchdog.py --dry-run",
        "expected_rows_desc": "0-10 watchdog action rows per cycle",
        "failure_hint": "DB connection issue or stale pipeline_schedule table.",
        "operator_next_action": "Run dry-run, check logs/pipeline_watchdog.log.",
    },

    # ── Proposal Pipeline (6) ────────────────────────────────────────────────
    "weekly_incubator_builder": {
        "pipeline_key": "weekly_incubator_builder",
        "display_name": "Weekly Incubator Builder",
        "category": "Proposal Pipeline",
        "owning_script": "scripts/weekly_incubator_builder.py",
        "owning_wrapper": None,
        "cron_pattern": "Sunday 8 PM",
        "log_paths": ["logs/incubator_builder.log"],
        "output_tables": ["incubator_candidates"],
        "safe_dry_run_cmd": "python scripts/weekly_incubator_builder.py --dry-run",
        "expected_rows_desc": "10-50 incubator candidate rows per weekly run",
        "failure_hint": "Runs weekly; check if Sunday cron fired. Verify upstream scoring.",
        "operator_next_action": "Run dry-run, check logs/incubator_builder.log.",
    },
    "daily_incubator_refresh": {
        "pipeline_key": "daily_incubator_refresh",
        "display_name": "Daily Incubator Refresh",
        "category": "Proposal Pipeline",
        "owning_script": "scripts/daily_incubator_refresh.py",
        "owning_wrapper": None,
        "cron_pattern": "8:00 AM M-F",
        "log_paths": ["logs/incubator_refresh.log"],
        "output_tables": ["incubator_candidates"],
        "safe_dry_run_cmd": "python scripts/daily_incubator_refresh.py --dry-run",
        "expected_rows_desc": "10-50 refreshed incubator rows per run",
        "failure_hint": "Check upstream scoring stages; incubator table may be empty.",
        "operator_next_action": "Run dry-run, check logs/incubator_refresh.log.",
    },
    "incubator_rolloff_engine": {
        "pipeline_key": "incubator_rolloff_engine",
        "display_name": "Incubator Rolloff Engine",
        "category": "Proposal Pipeline",
        "owning_script": "scripts/incubator_rolloff_engine.py",
        "owning_wrapper": None,
        "cron_pattern": "8:15 AM M-F",
        "log_paths": ["logs/incubator_rolloff.log"],
        "output_tables": ["incubator_candidates"],
        "safe_dry_run_cmd": "python scripts/incubator_rolloff_engine.py --dry-run",
        "expected_rows_desc": "0-10 rolled-off candidates per run",
        "failure_hint": "No candidates to roll off is normal; check incubator table.",
        "operator_next_action": "Run dry-run, check logs/incubator_rolloff.log.",
    },
    "incubator_proposal_promoter": {
        "pipeline_key": "incubator_proposal_promoter",
        "display_name": "Proposal Promoter",
        "category": "Proposal Pipeline",
        "owning_script": "scripts/incubator_proposal_promoter.py",
        "owning_wrapper": None,
        "cron_pattern": "8:30 AM M-F",
        "log_paths": ["logs/proposal_promoter.log"],
        "output_tables": ["proposals"],
        "safe_dry_run_cmd": "python scripts/incubator_proposal_promoter.py --dry-run",
        "expected_rows_desc": "0-5 promoted proposals per run",
        "failure_hint": "No promotions is normal if incubator is empty or scores low.",
        "operator_next_action": "Run dry-run, check logs/proposal_promoter.log.",
    },
    "proposal_enrichment_loop": {
        "pipeline_key": "proposal_enrichment_loop",
        "display_name": "Proposal Enrichment Loop",
        "category": "Proposal Pipeline",
        "owning_script": "scripts/proposal_enrichment_loop.py",
        "owning_wrapper": None,
        "cron_pattern": "every 5m 9:00-16:00 M-F",
        "log_paths": ["logs/proposal_enrichment.log"],
        "output_tables": ["proposals", "proposal_enrichment_log"],
        "safe_dry_run_cmd": "python scripts/proposal_enrichment_loop.py --dry-run",
        "expected_rows_desc": "0-20 enriched proposal rows per cycle",
        "failure_hint": "LLM quota; check upstream proposal_promoter for pending proposals.",
        "operator_next_action": "Run dry-run, check logs/proposal_enrichment.log.",
    },
    "proposal_lifecycle": {
        "pipeline_key": "proposal_lifecycle",
        "display_name": "Proposal Lifecycle",
        "category": "Proposal Pipeline",
        "owning_script": "scripts/proposal_lifecycle.py",
        "owning_wrapper": None,
        "cron_pattern": "every 30m 9:00-16:00 M-F",
        "log_paths": ["logs/proposal_lifecycle.log"],
        "output_tables": ["proposals", "proposal_state_log"],
        "safe_dry_run_cmd": "python scripts/proposal_lifecycle.py --dry-run",
        "expected_rows_desc": "0-10 lifecycle transitions per cycle",
        "failure_hint": "No transitions is normal; check proposal state distribution.",
        "operator_next_action": "Run dry-run, check logs/proposal_lifecycle.log.",
    },

    # ── Execution (4) ────────────────────────────────────────────────────────
    "risk_gate": {
        "pipeline_key": "risk_gate",
        "display_name": "Risk Gate",
        "category": "Execution",
        "owning_script": "scripts/risk_gate.py",
        "owning_wrapper": None,
        "cron_pattern": None,
        "log_paths": ["logs/risk_gate.log"],
        "output_tables": ["risk_gate_decisions"],
        "safe_dry_run_cmd": None,
        "expected_rows_desc": "On-demand; 1 row per proposal evaluation",
        "failure_hint": "Triggered by proposal approval flow; not scheduled.",
        "operator_next_action": "No manual run -- execution-only stage, runs when proposal reaches approval.",
    },
    "tradeai_automated": {
        "pipeline_key": "tradeai_automated",
        "display_name": "Alpaca Paper Trading",
        "category": "Execution",
        "owning_script": "scripts/alpaca_paper_adapter.py",
        "owning_wrapper": None,
        "cron_pattern": None,
        "log_paths": ["logs/alpaca_paper.log"],
        "output_tables": ["paper_trades", "paper_orders"],
        "safe_dry_run_cmd": None,
        "expected_rows_desc": "On-demand; 1 row per trade submission",
        "failure_hint": "Triggered by risk_gate approval; check Alpaca API keys.",
        "operator_next_action": "No manual run -- execution-only stage, runs when proposal reaches approval.",
    },
    "broker_reconciliation": {
        "pipeline_key": "broker_reconciliation",
        "display_name": "Broker Reconciliation",
        "category": "Execution",
        "owning_script": "scripts/alpaca_paper_reconciler.py",
        "owning_wrapper": None,
        "cron_pattern": "4:30 PM M-F",
        "log_paths": ["logs/broker_reconciliation.log"],
        "output_tables": ["reconciliation_log"],
        "safe_dry_run_cmd": "python scripts/alpaca_paper_reconciler.py --dry-run",
        "expected_rows_desc": "1-20 reconciliation rows per run",
        "failure_hint": "Alpaca API may be down; check ALPACA_* keys in .env.",
        "operator_next_action": "Run dry-run, check logs/broker_reconciliation.log.",
    },
    "execution_quality": {
        "pipeline_key": "execution_quality",
        "display_name": "Execution Quality",
        "category": "Execution",
        "owning_script": "scripts/paper_execution_quality.py",
        "owning_wrapper": None,
        "cron_pattern": "5:00 PM M-F",
        "log_paths": ["logs/execution_quality.log"],
        "output_tables": ["execution_quality_metrics"],
        "safe_dry_run_cmd": "python scripts/paper_execution_quality.py --dry-run",
        "expected_rows_desc": "1-20 quality metric rows per run",
        "failure_hint": "Needs completed trades to analyze; check paper_trades table.",
        "operator_next_action": "Run dry-run, check logs/execution_quality.log.",
    },

    # ── Overnight (4) ────────────────────────────────────────────────────────
    "overnight_batch": {
        "pipeline_key": "overnight_batch",
        "display_name": "Overnight Batch",
        "category": "Overnight",
        "owning_script": "scripts/overnight_batch.py",
        "owning_wrapper": None,
        "cron_pattern": "8:00 PM M-F",
        "log_paths": ["logs/overnight_batch.log"],
        "output_tables": ["overnight_batch_runs", "overnight_analysis"],
        "safe_dry_run_cmd": "python scripts/overnight_batch.py --dry-run",
        "expected_rows_desc": "50-200 overnight analysis rows per run",
        "failure_hint": "LLM quota exhausted; check Gemma/Ollama availability.",
        "operator_next_action": "Run dry-run, check logs/overnight_batch.log.",
    },
    "agent_outcome_scorer": {
        "pipeline_key": "agent_outcome_scorer",
        "display_name": "Outcome Scorer",
        "category": "Overnight",
        "owning_script": "scripts/agent_outcome_scorer.py",
        "owning_wrapper": None,
        "cron_pattern": "9:00 PM M-F",
        "log_paths": ["logs/outcome_scorer.log"],
        "output_tables": ["agent_outcome_scores"],
        "safe_dry_run_cmd": "python scripts/agent_outcome_scorer.py --dry-run",
        "expected_rows_desc": "10-100 scored outcome rows per run",
        "failure_hint": "Needs completed agent analyses; check agent_analysis table.",
        "operator_next_action": "Run dry-run, check logs/outcome_scorer.log.",
    },
    "strategy_weekly_review": {
        "pipeline_key": "strategy_weekly_review",
        "display_name": "Strategy Weekly Review",
        "category": "Overnight",
        "owning_script": "scripts/strategy_weekly_review.py",
        "owning_wrapper": None,
        "cron_pattern": "Sunday 9 PM",
        "log_paths": ["logs/strategy_weekly_review.log"],
        "output_tables": ["strategy_reviews"],
        "safe_dry_run_cmd": "python scripts/strategy_weekly_review.py --dry-run",
        "expected_rows_desc": "5-20 strategy review rows per weekly run",
        "failure_hint": "Weekly run; check if Sunday cron fired.",
        "operator_next_action": "Run dry-run, check logs/strategy_weekly_review.log.",
    },
    "overnight_batch_embeddings": {
        "pipeline_key": "overnight_batch_embeddings",
        "display_name": "Overnight Embeddings",
        "category": "Overnight",
        "owning_script": "scripts/overnight_batch.py",
        "owning_wrapper": None,
        "cron_pattern": "10:00 PM M-F",
        "log_paths": ["logs/overnight_embeddings.log"],
        "output_tables": ["rag_embeddings"],
        "safe_dry_run_cmd": "python scripts/overnight_batch.py --embeddings-only --dry-run",
        "expected_rows_desc": "50-300 embedding rows per run",
        "failure_hint": "Embedding API quota or overnight_batch must complete first.",
        "operator_next_action": "Run dry-run, check logs/overnight_embeddings.log.",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def get_stage_owner(pipeline_key: str) -> dict | None:
    """Return ownership metadata for a single pipeline stage, or None."""
    return STAGE_OWNERS.get(pipeline_key)


def get_all_stages() -> list[dict]:
    """Return the full list of stage ownership dicts."""
    return list(STAGE_OWNERS.values())


# ─────────────────────────────────────────────────────────────────────────────
# CLI output helpers
# ─────────────────────────────────────────────────────────────────────────────

def _render_md(stages: list[dict]) -> str:
    lines = ["# Pipeline Stage Owner Map", "", f"**Total stages:** {len(stages)}", ""]
    categories = {}
    for s in stages:
        categories.setdefault(s["category"], []).append(s)
    for cat, entries in categories.items():
        lines.append(f"## {cat} ({len(entries)} stages)")
        lines.append("")
        for e in entries:
            lines.append(f"### {e['display_name']} (`{e['pipeline_key']}`)")
            lines.append(f"- **Script:** `{e['owning_script'] or 'N/A'}`")
            lines.append(f"- **Wrapper:** `{e['owning_wrapper'] or 'N/A'}`")
            lines.append(f"- **Cron:** {e['cron_pattern'] or 'On-demand'}")
            lines.append(f"- **Log:** {', '.join(f'`{p}`' for p in e['log_paths'])}")
            lines.append(f"- **Tables:** {', '.join(f'`{t}`' for t in e['output_tables'])}")
            lines.append(f"- **Dry-run:** `{e['safe_dry_run_cmd'] or 'N/A'}`")
            lines.append(f"- **Expected rows:** {e['expected_rows_desc']}")
            lines.append(f"- **Failure hint:** {e['failure_hint']}")
            lines.append(f"- **Next action:** {e['operator_next_action']}")
            lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Pipeline stage ownership map")
    parser.add_argument("--output-json", type=str, help="Write JSON output to this path")
    parser.add_argument("--output-md", type=str, help="Write Markdown output to this path")
    parser.add_argument("--verbose", action="store_true", help="Print summary to stdout")
    args = parser.parse_args()

    stages = get_all_stages()

    if args.verbose:
        categories = {}
        for s in stages:
            categories.setdefault(s["category"], []).append(s)
        print(f"Pipeline Stage Owner Map — {len(stages)} stages across {len(categories)} categories\n")
        for cat, entries in categories.items():
            print(f"  {cat}: {len(entries)} stages")
            for e in entries:
                cron = e["cron_pattern"] or "on-demand"
                print(f"    - {e['pipeline_key']:40s}  {cron}")
        print()

    if args.output_json:
        path = Path(args.output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(stages, indent=2))
        print(f"JSON written to {path}")

    if args.output_md:
        path = Path(args.output_md)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_render_md(stages))
        print(f"Markdown written to {path}")

    if not args.output_json and not args.output_md and not args.verbose:
        print(json.dumps(stages, indent=2))


if __name__ == "__main__":
    main()
