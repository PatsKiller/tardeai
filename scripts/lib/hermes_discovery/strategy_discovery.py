"""White-Space Strategy Discovery — candidate-strategy catalog + lane runner (spec Part B).

A curated catalog of strategy families the system does NOT run yet, diffed
live against the strategy registry (config/strategies/*.yaml strategy_id).
Each missing strategy is emitted as a STRATEGY_CANDIDATE payload for
inbox.upsert_candidate (idempotent; re-runs bump seen_count, never duplicate).

Registry diff rules:
  * an entry with a LIVE registry equivalent (status not in PARKED_STATUSES)
    is SKIPPED — it is not white space;
  * a PARKED/RETIRED/DISABLED equivalent still emits (the strategy exists on
    paper but is not running — that IS white space) with the registry id +
    status stamped into meta.registry_equivalent / meta.registry_status;
  * tax_loss_harvest is live in the registry and therefore not in the catalog
    at all (per spec).

Every candidate's meta.strategy_json carries EXACTLY the spec's schema:
strategy_name / family / domain / underlying_type / required_data / use_case /
risks / missing_system_components / required_backtest / required_policy_gate /
educational_only / operator_review_required — with educational_only and
operator_review_required HARD-FORCED to True by the builder regardless of
what any catalog edit says.

Advisory-only: no broker/execution/order imports, no promotion API. The lane
runner is registered for the 'strategy' worker-pool lane at import time; all
writes go through the pool's gated inbox.upsert_candidate loop.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
STRATEGIES_DIR = PROJECT_ROOT / "config" / "strategies"

LANE_ID = "strategy"

# Registry statuses that mean "defined but NOT running" — still white space.
PARKED_STATUSES = frozenset({"PARKED", "RETIRED", "DISABLED", "ARCHIVED"})

# Research domains the 'strategy' worker lane may emit into
# (config/hermes_research_worker_lanes.yaml allowed_domains).
_OPTIONS_DOMAIN = "watchlist"
_PROXY_DOMAIN = "industry_themes"
_SECTOR_DOMAIN = "sectors"

_OPTIONS_GATE = ("Operator review required. Options desk gates (options_desk_"
                 "enterprise fail-closed queue) + a dedicated strategy YAML with "
                 "risk limits must exist, backtest must PASS, and paper-first "
                 "validation must complete before any live enablement.")
_PROXY_GATE = ("Operator review required. Proxy exposure is thesis-tracking, not "
               "the private asset itself: correlation evidence + concentration "
               "limits must be defined in a strategy YAML before any promotion; "
               "manual-review-only proposals per the ETF/sleeve policy.")

# ── the catalog (spec Part B seed list; tax_loss_harvest exists → not seeded) ──
# Each entry: catalog_id, registry_equivalents (strategy_id values that make it
# non-white-space), and the strategy_json fields.
STRATEGY_CATALOG: list[dict[str, Any]] = [
    {
        "catalog_id": "deep_itm_call",
        "registry_equivalents": [],
        "strategy_name": "Deep ITM Call (stock replacement)",
        "family": "options_leverage",
        "domain": _OPTIONS_DOMAIN,
        "underlying_type": "equity_option",
        "required_data": ["option_chain", "greeks_delta", "iv", "open_interest",
                          "earnings_calendar", "underlying_quote"],
        "use_case": "Replace 100-share exposure with a 0.80-0.95 delta call at a "
                    "fraction of the capital; defined max loss = premium paid.",
        "risks": ["time decay on extrinsic value", "wide spreads on deep strikes",
                  "no dividend received", "assignment/liquidity around earnings",
                  "total premium loss if underlying falls below strike"],
        "missing_system_components": ["options strategy YAML + risk limits",
                                      "long-options position lifecycle (no covered shares)",
                                      "options backtest harness", "greeks-aware sizing"],
        "required_backtest": "Multi-year deep-ITM vs shares total-return comparison "
                             "incl. rolls, spreads, and earnings gaps; PASS required.",
        "required_policy_gate": _OPTIONS_GATE,
    },
    {
        "catalog_id": "covered_call",
        "registry_equivalents": ["covered_call_income"],
        "strategy_name": "Covered Call Income",
        "family": "options_income",
        "domain": _OPTIONS_DOMAIN,
        "underlying_type": "equity_option",
        "required_data": ["option_chain", "iv_rank", "holdings_100_share_lots",
                          "cost_basis", "earnings_calendar"],
        "use_case": "Sell calls against 100-share lots already held to harvest "
                    "premium income; strike above cost basis.",
        "risks": ["upside capped / shares called away", "tax events on assignment",
                  "premium rarely compensates a sharp drawdown"],
        "missing_system_components": ["execution wiring (registry entry is PARKED — "
                                      "options not executable)", "assignment handling",
                                      "covered-lot accounting"],
        "required_backtest": "Premium yield vs called-away opportunity cost across "
                             "held names; include earnings cycles.",
        "required_policy_gate": _OPTIONS_GATE,
    },
    {
        "catalog_id": "cash_secured_put",
        "registry_equivalents": [],
        "strategy_name": "Cash-Secured Put",
        "family": "options_income",
        "domain": _OPTIONS_DOMAIN,
        "underlying_type": "equity_option",
        "required_data": ["option_chain", "iv_rank", "cash_buying_power",
                          "watchlist_entry_levels", "earnings_calendar"],
        "use_case": "Sell puts at strikes where the desk already wants to own the "
                    "stock; collect premium or acquire at an effective discount.",
        "risks": ["full downside below strike (minus premium)",
                  "capital locked as collateral", "assignment into falling names"],
        "missing_system_components": ["collateral/cash-reservation ledger",
                                      "assignment→position handoff",
                                      "options strategy YAML + risk limits"],
        "required_backtest": "Wheel-entry CSP vs limit-buy entries on the governed "
                             "watchlist; drawdown + assignment-rate analysis.",
        "required_policy_gate": _OPTIONS_GATE,
    },
    {
        "catalog_id": "collar",
        "registry_equivalents": [],
        "strategy_name": "Collar (protective put + covered call)",
        "family": "options_hedge",
        "domain": _OPTIONS_DOMAIN,
        "underlying_type": "equity_option",
        "required_data": ["option_chain", "greeks_delta", "holdings_100_share_lots",
                          "cost_basis", "iv"],
        "use_case": "Bracket a concentrated held position: long put floor financed "
                    "by a short call cap — cheap tail protection.",
        "risks": ["upside capped at the call strike", "roll management burden",
                  "net debit when put skew is rich"],
        "missing_system_components": ["multi-leg position model", "roll scheduler",
                                      "options strategy YAML + risk limits"],
        "required_backtest": "Collared vs unhedged concentrated holdings through "
                             "drawdown regimes; cost-of-carry accounting.",
        "required_policy_gate": _OPTIONS_GATE,
    },
    {
        "catalog_id": "leaps_long_call",
        "registry_equivalents": [],
        "strategy_name": "LEAPS Long Call (12+ month)",
        "family": "options_leverage",
        "domain": _OPTIONS_DOMAIN,
        "underlying_type": "equity_option",
        "required_data": ["option_chain_leaps", "greeks_delta", "iv_term_structure",
                          "long_thesis_coverage"],
        "use_case": "Express a multi-year thesis (e.g. defense/AI) with defined-risk "
                    "long-dated calls instead of full share capital.",
        "risks": ["IV crush on entry at rich vol", "illiquid LEAPS spreads",
                  "thesis timing risk — decay accelerates in the final months"],
        "missing_system_components": ["LEAPS liquidity screening", "roll policy",
                                      "options backtest harness"],
        "required_backtest": "LEAPS vs shares on thesis names across entry-IV "
                             "regimes; roll-cost sensitivity.",
        "required_policy_gate": _OPTIONS_GATE,
    },
    {
        "catalog_id": "synthetic_long",
        "registry_equivalents": [],
        "strategy_name": "Synthetic Long (long call + short put)",
        "family": "options_leverage",
        "domain": _OPTIONS_DOMAIN,
        "underlying_type": "equity_option",
        "required_data": ["option_chain", "greeks_delta", "margin_requirements",
                          "borrow/carry rates"],
        "use_case": "Replicate share exposure at the same strike with near-zero net "
                    "premium; capital efficiency for high-conviction names.",
        "risks": ["short-put side carries full downside", "margin calls",
                  "NOT defined-risk — riskier than deep ITM calls"],
        "missing_system_components": ["margin-aware risk model", "short-option "
                                      "monitoring", "options strategy YAML"],
        "required_backtest": "Synthetic vs shares vs deep-ITM capital efficiency and "
                             "tail-risk comparison.",
        "required_policy_gate": _OPTIONS_GATE,
    },
    {
        "catalog_id": "protective_put",
        "registry_equivalents": [],
        "strategy_name": "Protective Put",
        "family": "options_hedge",
        "domain": _OPTIONS_DOMAIN,
        "underlying_type": "equity_option",
        "required_data": ["option_chain", "greeks_delta", "holdings_100_share_lots",
                          "iv", "drawdown_tolerance_policy"],
        "use_case": "Hard floor under a held position (complements synthetic stops "
                    "for fractional lots — a put cannot gap through).",
        "risks": ["persistent premium drag", "strike/tenor selection error",
                  "over-hedging destroys expectancy"],
        "missing_system_components": ["hedge-budget policy", "put-roll scheduler",
                                      "options strategy YAML + risk limits"],
        "required_backtest": "Put-protected vs stop-protected holdings incl. gap "
                             "scenarios; annual premium drag accounting.",
        "required_policy_gate": _OPTIONS_GATE,
    },
    {
        "catalog_id": "call_spread",
        "registry_equivalents": [],
        "strategy_name": "Vertical Call Spread (debit/credit)",
        "family": "options_spread",
        "domain": _OPTIONS_DOMAIN,
        "underlying_type": "equity_option",
        "required_data": ["option_chain", "greeks_delta", "iv_rank",
                          "multi_leg_pricing"],
        "use_case": "Defined-risk directional expression: buy a call, sell a higher "
                    "strike to cut premium; both risk and reward capped.",
        "risks": ["max profit capped", "leg/execution risk on wide markets",
                  "early-assignment on the short leg around dividends"],
        "missing_system_components": ["multi-leg order/position model",
                                      "spread P&L attribution", "options backtest harness"],
        "required_backtest": "Spread vs outright call expectancy across IV regimes "
                             "on liquid watchlist names.",
        "required_policy_gate": _OPTIONS_GATE,
    },
    {
        "catalog_id": "diagonal_spread",
        "registry_equivalents": [],
        "strategy_name": "Diagonal Spread (long-dated long / short-dated short)",
        "family": "options_spread",
        "domain": _OPTIONS_DOMAIN,
        "underlying_type": "equity_option",
        "required_data": ["option_chain", "iv_term_structure", "greeks_delta",
                          "greeks_theta", "multi_leg_pricing"],
        "use_case": "Own a long-dated (often deep ITM/LEAPS) call and rent it out "
                    "via short near-dated calls — 'poor man's covered call'.",
        "risks": ["short-leg breach on fast rallies", "term-structure inversion",
                  "complex roll management"],
        "missing_system_components": ["calendar-aware multi-leg model",
                                      "roll scheduler", "options backtest harness"],
        "required_backtest": "Diagonal vs covered call vs buy-and-hold income and "
                             "drawdown comparison over multi-year windows.",
        "required_policy_gate": _OPTIONS_GATE,
    },
    {
        "catalog_id": "dividend_capture",
        "registry_equivalents": [],
        "strategy_name": "Dividend Capture Rotation",
        "family": "income_capture",
        "domain": _OPTIONS_DOMAIN,
        "underlying_type": "equity",
        "required_data": ["ex_dividend_calendar", "dividend_amounts",
                          "post_ex_drift_history", "borrow/liquidity data",
                          "tax_treatment (qualified holding periods)"],
        "use_case": "Hold names across ex-dividend dates to collect distributions, "
                    "rotating capital through a dividend calendar.",
        "risks": ["ex-date price drop typically ≈ dividend", "unqualified-dividend "
                  "tax drag on short holds", "transaction-cost bleed"],
        "missing_system_components": ["ex-div calendar ingestion", "capture-window "
                                      "scheduler", "tax-aware expectancy model"],
        "required_backtest": "Net-of-tax, net-of-slippage capture expectancy vs "
                             "buy-and-hold on the income sleeve.",
        "required_policy_gate": ("Operator review required. Tax-aware expectancy must "
                                 "be proven positive net of costs in backtest before "
                                 "any strategy YAML is drafted."),
    },
    {
        "catalog_id": "private_company_proxy",
        "registry_equivalents": [],
        "strategy_name": "Private-Company Proxy Exposure",
        "family": "proxy_exposure",
        "domain": _PROXY_DOMAIN,
        "underlying_type": "equity",
        "required_data": ["private_company_watch_topics", "supplier/customer/investor "
                          "relationship maps", "public-comparable fundamentals",
                          "news/filing flow"],
        "use_case": "Track a private company thesis (e.g. Anduril, OpenAI) via "
                    "listed suppliers, customers, or shareholders when the name "
                    "itself is uninvestable.",
        "risks": ["proxy correlation is unproven and drifts", "conglomerate dilution "
                  "of the thesis", "event risk unique to the proxy"],
        "missing_system_components": ["PRIVATE_COMPANY_PROXY_CANDIDATE research lane "
                                      "wiring", "proxy-correlation evidence model",
                                      "thesis→proxy lineage tracking"],
        "required_backtest": "Historical proxy-basket tracking error vs private-round "
                             "marks / sector benchmarks where observable.",
        "required_policy_gate": _PROXY_GATE,
    },
    {
        "catalog_id": "comparable_basket",
        "registry_equivalents": [],
        "strategy_name": "Comparable-Company Basket",
        "family": "proxy_exposure",
        "domain": _PROXY_DOMAIN,
        "underlying_type": "equity_basket",
        "required_data": ["comparable screens (Finviz)", "factor/beta data",
                          "correlation matrices", "rebalance calendar"],
        "use_case": "Express a theme through an equal/score-weighted basket of "
                    "public comparables instead of a single-name bet.",
        "risks": ["basket dilutes the winner", "correlation regime shifts",
                  "rebalance cost + tracking drift"],
        "missing_system_components": ["basket position primitive (multi-symbol "
                                      "sleeve)", "basket rebalancer", "basket-level "
                                      "risk limits"],
        "required_backtest": "Basket vs best-single-name vs sector ETF on historical "
                             "themes; turnover-cost sensitivity.",
        "required_policy_gate": _PROXY_GATE,
    },
    {
        "catalog_id": "sector_etf_proxy",
        "registry_equivalents": [],
        "strategy_name": "Sector-ETF Proxy Exposure",
        "family": "proxy_exposure",
        "domain": _SECTOR_DOMAIN,
        "underlying_type": "etf",
        "required_data": ["etf_holdings_lookthrough", "expense_ratios",
                          "sector classification", "theme→sector mapping"],
        "use_case": "Take theme exposure through the sector ETF (e.g. ITA/XAR for "
                    "defense) when single-name selection edge is unproven.",
        "risks": ["theme diluted by index weights", "expense drag",
                  "look-through overlap with existing holdings"],
        "missing_system_components": ["theme→ETF mapping layer over the existing "
                                      "ETF look-through analyst", "overlap guard vs "
                                      "current holdings"],
        "required_backtest": "ETF proxy vs curated basket vs single names on past "
                             "theses (defense thesis as the reference case).",
        "required_policy_gate": _PROXY_GATE,
    },
    {
        "catalog_id": "listed_pe_proxy",
        "registry_equivalents": [],
        "strategy_name": "Listed Private-Equity Proxy",
        "family": "proxy_exposure",
        "domain": _SECTOR_DOMAIN,
        "underlying_type": "equity",
        "required_data": ["listed PE/BDC universe (KKR, BX, APO, ARCC, ...)",
                          "NAV discount/premium history", "fee structures",
                          "credit-cycle indicators"],
        "use_case": "Access private-markets return streams through listed PE "
                    "managers and BDCs instead of inaccessible LP interests.",
        "risks": ["public-market beta swamps PE exposure", "NAV marks lag and "
                  "smooth true volatility", "credit-cycle drawdowns"],
        "missing_system_components": ["NAV premium/discount tracker",
                                      "listed-PE universe screen + strategy YAML"],
        "required_backtest": "Listed-PE sleeve vs S&P and vs the existing "
                             "high_yield_income_bdc allocation policy.",
        "required_policy_gate": _PROXY_GATE,
    },
]


# ── registry diff ────────────────────────────────────────────────────────────

def registry_strategy_ids(strategies_dir: Path | str | None = None) -> dict[str, str]:
    """{strategy_id: status} from config/strategies/*.yaml (read-only).

    Only files whose top level carries a string ``strategy_id`` count —
    schema/shared-rules yamls are ignored. Unparseable files are skipped
    (a broken yaml must not hide the rest of the registry).
    """
    import yaml
    d = Path(strategies_dir) if strategies_dir else STRATEGIES_DIR
    out: dict[str, str] = {}
    for p in sorted(d.glob("*.yaml")):
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if isinstance(data, dict) and isinstance(data.get("strategy_id"), str):
            out[data["strategy_id"].strip()] = str(data.get("status") or "").strip().upper()
    return out


def build_strategy_json(entry: dict[str, Any]) -> dict[str, Any]:
    """The spec's meta.strategy_json schema — EXACT keys, flags hard-forced."""
    return {
        "strategy_name": entry["strategy_name"],
        "family": entry["family"],
        "domain": entry["domain"],
        "underlying_type": entry["underlying_type"],
        "required_data": list(entry["required_data"]),
        "use_case": entry["use_case"],
        "risks": list(entry["risks"]),
        "missing_system_components": list(entry["missing_system_components"]),
        "required_backtest": entry["required_backtest"],
        "required_policy_gate": entry["required_policy_gate"],
        # HARD-FORCED — never trust the catalog literal for these two.
        "educational_only": True,
        "operator_review_required": True,
    }


def catalog_diff(strategies_dir: Path | str | None = None) -> dict[str, Any]:
    """Diff the catalog against the live strategy registry.

    Returns {registry_ids, missing: [entries...], skipped: [{catalog_id,
    reason, registry_id, registry_status}]}. See module docstring for the
    LIVE vs PARKED rule.
    """
    registry = registry_strategy_ids(strategies_dir)
    missing: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for entry in STRATEGY_CATALOG:
        hit = next((rid for rid in entry.get("registry_equivalents") or []
                    if rid in registry), None)
        if hit and registry[hit] not in PARKED_STATUSES:
            skipped.append({"catalog_id": entry["catalog_id"],
                            "reason": "live_registry_equivalent",
                            "registry_id": hit, "registry_status": registry[hit]})
            continue
        e = dict(entry)
        if hit:  # defined-but-parked equivalent: still white space, but say so
            e["_registry_equivalent"] = hit
            e["_registry_status"] = registry[hit]
        missing.append(e)
    return {"registry_ids": registry, "missing": missing, "skipped": skipped}


# ── STRATEGY_CANDIDATE payloads + lane runner ────────────────────────────────

def build_payloads(strategies_dir: Path | str | None = None) -> list[dict[str, Any]]:
    """inbox.upsert_candidate payload dicts for every missing strategy.

    Read-only: builds dicts, writes nothing — the worker pool owns all writes
    (gated, capped, candidates-only)."""
    diff = catalog_diff(strategies_dir)
    payloads: list[dict[str, Any]] = []
    for entry in diff["missing"]:
        sj = build_strategy_json(entry)
        meta: dict[str, Any] = {
            "research_domain": entry["domain"],   # lane-allowed pin
            "discovery_lane": LANE_ID,
            "catalog_id": entry["catalog_id"],
            "strategy_json": sj,
        }
        evidence = [{"note": f"strategy registry diff: no live strategy_id "
                             f"covers '{entry['catalog_id']}' "
                             f"({len(diff['registry_ids'])} registry entries checked)"}]
        if entry.get("_registry_equivalent"):
            meta["registry_equivalent"] = entry["_registry_equivalent"]
            meta["registry_status"] = entry["_registry_status"]
            evidence.append({"note": f"registry has {entry['_registry_equivalent']} "
                                     f"but status={entry['_registry_status']} — "
                                     f"defined on paper, not running"})
        payloads.append({
            "candidate_type": "STRATEGY_CANDIDATE",
            "label": f"Strategy white-space: {sj['strategy_name']}"[:120],
            "summary": sj["use_case"][:400],
            "evidence": evidence,
            "meta": meta,
            "safe_action_level": "OPERATOR_REVIEW_REQUIRED",
            "normalized_key": f"strategy:{entry['catalog_id']}",
        })
    return payloads


def strategy_lane_runner(lane_cfg: dict[str, Any], *,
                         dry_run: bool = False) -> list[dict[str, Any]]:
    """Worker-pool runner for the 'strategy' lane (read-only; pool writes)."""
    return build_payloads()


def register() -> None:
    """Idempotently register the 'strategy' lane runner with the pool."""
    from . import worker_pool
    worker_pool.register_lane_runner(LANE_ID, strategy_lane_runner, replace=True)


register()
