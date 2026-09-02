"""Cross-page consistency assertions for CC semantic fields."""

from __future__ import annotations

from typing import Any


def _unwrap(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    if "data" in payload and isinstance(payload["data"], dict):
        return payload["data"]
    return payload


def extract_semantics(captures: dict[str, Any]) -> dict[str, Any]:
    overview = _unwrap(captures.get("/api/v2/overview"))
    risk = _unwrap(captures.get("/api/v2/risk"))
    perf = _unwrap(captures.get("/api/v2/portfolio/performance"))
    book = _unwrap(captures.get("/api/v2/portfolio/book-map"))
    trade_ai = _unwrap(captures.get("/api/v2/trade-ai/summary"))
    regime = _unwrap(captures.get("/api/v2/risk-regime/latest"))
    proposals = _unwrap(captures.get("/api/v2/paper-proposals"))
    health_prop = _unwrap(captures.get("/api/v2/health/proposals"))
    journal = _unwrap(captures.get("/api/v2/journal"))
    research = _unwrap(captures.get("/api/v2/research-intelligence/freshness"))
    build = captures.get("/v3/build-meta.json") or {}
    if isinstance(build, dict) and "data" in build and isinstance(build["data"], dict):
        build = build["data"]

    j = overview.get("journal") if isinstance(overview.get("journal"), dict) else {}
    stop_health = risk.get("stop_health") if isinstance(risk.get("stop_health"), dict) else {}

    return {
        "portfolio_value": overview.get("portfolio_value"),
        "cash": overview.get("total_cash"),
        "position_count_overview": overview.get("position_count"),
        "position_count_risk": risk.get("position_count"),
        "day_pnl": overview.get("today_change"),
        "realized_pnl": j.get("realized_pnl"),
        "prices_last_repriced": (overview.get("pricing") or {}).get("last_repriced")
        if isinstance(overview.get("pricing"), dict)
        else overview.get("last_repriced"),
        "reprice_source": overview.get("reprice_source"),
        "data_as_of": overview.get("data_as_of"),
        "as_of": overview.get("as_of"),
        "pipeline_status": overview.get("pipeline_status"),
        "stops_unprotected": stop_health.get("unprotected_count") or risk.get("unprotected_count"),
        "pct_protected": risk.get("pct_protected"),
        "regime": regime.get("regime_label") or regime.get("regime"),
        "vix": trade_ai.get("vix") or overview.get("trade_ai", {}).get("vix")
        if isinstance(overview.get("trade_ai"), dict)
        else trade_ai.get("vix"),
        "setups_go": trade_ai.get("go_count"),
        "setups_run_date": trade_ai.get("run_date"),
        "last_run": overview.get("pipeline_completed") or trade_ai.get("cached_at"),
        "proposals_pending": proposals.get("pending_count") if isinstance(proposals, dict) else None,
        "approvals_pending": overview.get("pending_approvals"),
        "journal_win_rate": j.get("win_rate"),
        "research_state": research.get("status") or research.get("state"),
        "perf_current_value": perf.get("current_value") or perf.get("portfolio_value"),
        "book_total": book.get("total_value") or book.get("invested_value"),
        "build_sha": build.get("git_sha") or build.get("build_sha") or build.get("source_sha"),
        "health_proposals": health_prop.get("pending") or health_prop.get("count"),
    }


def assert_cross_page(semantics: dict[str, Any], *, expect_consistent_positions: bool = True) -> list[dict[str, Any]]:
    """Return list of assertion rows for CSV."""
    rows: list[dict[str, Any]] = []

    def row(concept: str, a_name: str, a_val: Any, b_name: str, b_val: Any, consistent: str, notes: str = "") -> None:
        rows.append(
            {
                "semantic_concept": concept,
                "endpoint_a": a_name,
                "value_a": a_val,
                "endpoint_b": b_name,
                "value_b": b_val,
                "consistent": consistent,
                "notes": notes,
            }
        )

    pv = semantics.get("portfolio_value")
    perf = semantics.get("perf_current_value")
    if pv is not None and perf is not None:
        ok = abs(float(pv) - float(perf)) < 0.02
        row("portfolio_value", "overview", pv, "performance", perf, "YES" if ok else "NO")
    else:
        row("portfolio_value", "overview", pv, "performance", perf, "MISSING", "one side missing")

    po = semantics.get("position_count_overview")
    pr = semantics.get("position_count_risk")
    if po is not None and pr is not None:
        same = int(po) == int(pr)
        if expect_consistent_positions:
            row(
                "position_count",
                "overview",
                po,
                "risk",
                pr,
                "YES" if same else "NO",
                "must match" if same else "inconsistent position count",
            )
        else:
            row(
                "position_count",
                "overview",
                po,
                "risk",
                pr,
                "NO" if not same else "UNEXPECTED_YES",
                "negative control expects mismatch",
            )
    else:
        row("position_count", "overview", po, "risk", pr, "MISSING")

    # Cash presence
    row(
        "cash",
        "overview.total_cash",
        semantics.get("cash"),
        "—",
        "",
        "PRESENT" if semantics.get("cash") is not None else "MISSING",
    )
    row(
        "day_pnl",
        "overview.today_change",
        semantics.get("day_pnl"),
        "—",
        "",
        "PRESENT" if semantics.get("day_pnl") is not None else "MISSING",
    )
    row(
        "realized_pnl",
        "overview.journal.realized_pnl",
        semantics.get("realized_pnl"),
        "—",
        "",
        "PRESENT" if semantics.get("realized_pnl") is not None else "MISSING",
    )
    row(
        "prices",
        "overview.pricing.last_repriced",
        semantics.get("prices_last_repriced"),
        "reprice_source",
        semantics.get("reprice_source"),
        "PRESENT" if semantics.get("prices_last_repriced") else "MISSING",
    )
    row(
        "stops_protection",
        "risk.stop_health",
        semantics.get("stops_unprotected"),
        "pct_protected",
        semantics.get("pct_protected"),
        "PRESENT" if semantics.get("stops_unprotected") is not None else "MISSING",
    )
    row(
        "regime_vix",
        "risk-regime",
        semantics.get("regime"),
        "trade-ai.vix",
        semantics.get("vix"),
        "PRESENT" if semantics.get("vix") is not None else "MISSING",
    )
    row(
        "setups",
        "trade-ai.go_count",
        semantics.get("setups_go"),
        "run_date",
        semantics.get("setups_run_date"),
        "PRESENT" if semantics.get("setups_run_date") else "MISSING",
    )
    row(
        "last_run",
        "pipeline_completed|cached_at",
        semantics.get("last_run"),
        "—",
        "",
        "PRESENT" if semantics.get("last_run") else "MISSING",
    )
    row(
        "proposals",
        "paper-proposals",
        semantics.get("proposals_pending"),
        "health/proposals",
        semantics.get("health_proposals"),
        "PRESENT" if semantics.get("proposals_pending") is not None else "MISSING",
    )
    row(
        "approvals",
        "overview.pending_approvals",
        semantics.get("approvals_pending"),
        "—",
        "",
        "PRESENT" if semantics.get("approvals_pending") is not None else "MISSING",
    )
    row(
        "journal",
        "overview.journal.win_rate",
        semantics.get("journal_win_rate"),
        "—",
        "",
        "PRESENT" if semantics.get("journal_win_rate") is not None else "MISSING",
    )
    row(
        "research_state",
        "research-intelligence/freshness",
        semantics.get("research_state"),
        "—",
        "",
        "PRESENT" if semantics.get("research_state") else "MISSING",
    )
    row(
        "build_sha",
        "build-meta",
        semantics.get("build_sha"),
        "—",
        "",
        "PRESENT" if semantics.get("build_sha") else "MISSING",
    )

    return rows


def cross_page_failures(rows: list[dict[str, Any]]) -> list[str]:
    fails = []
    for r in rows:
        if r["consistent"] in {"NO", "MISSING"} and r["semantic_concept"] in {
            "portfolio_value",
            "position_count",
            "build_sha",
        }:
            fails.append(f"{r['semantic_concept']}:{r['consistent']}")
    return fails
