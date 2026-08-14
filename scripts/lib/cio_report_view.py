"""cio_report_view.py — Phase 4 shared presentation layer for Institutional Report v2.

Architecture (one truth, many formats):

    build_report_v2()          → canonical *model* (facts only)
         │
    build_report_view(model)   → *view* (normalized units + sections)
         │
    ┌────┴─────┬──────────┬────────────┐
  HTML       DOCX       PDF        Command Center slice

Rules:
  * No format invents numbers. Formatters only display view.facts / view.sections.
  * USD dollars never formatted as percentages.
  * Allocation always exposes both USD and weight %.
  * facts_fingerprint is stable across HTML/DOCX/PDF for the same model.

READ_ONLY_ADVISORY. Pure. No broker / Telegram / writes.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

REPORT_ARCHITECTURE_VERSION = "report_arch_1.0.0"


def _prose(v: Any) -> Any:
    """Map internal enums to professional labels when possible."""
    try:
        from scripts.lib.cio_decision_semantics import professional_label
        s = str(v or "")
        if s and s.upper() == s and "_" in s:
            return professional_label(s)
        if s in ("LEADING", "IMPROVING", "WEAKENING", "LAGGING",
                 "STAGED_DEPLOYMENT", "RESEARCH_FIRST", "NO_DEPLOYMENT"):
            return professional_label(s)
        return v
    except Exception:
        return v


def _is_pseudo_sector(name: Any) -> bool:
    try:
        from scripts.lib.cio_decision_semantics import is_pseudo_sector
        return is_pseudo_sector(name)
    except Exception:
        return "−" in str(name or "") or (str(name or "").count("-") == 1 and len(str(name)) < 12)


def _num(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def fmt_usd(v: Any, *, signed: bool = False) -> str:
    n = _num(v)
    if n is None:
        return "—"
    if signed:
        return f"${n:+,.2f}"
    return f"${n:,.2f}"


def fmt_pct(v: Any, *, signed: bool = False) -> str:
    n = _num(v)
    if n is None:
        return "—"
    # Guard: refuse to print absurd "percentages" that are clearly dollars
    if abs(n) > 1000:
        return f"{n:,.2f} (check units)"
    return f"{n:+,.2f}%" if signed else f"{n:,.2f}%"


def fmt_num(v: Any, digits: int = 2) -> str:
    n = _num(v)
    if n is None:
        return "—"
    return f"{n:,.{digits}f}"


def normalize_allocation(part_b: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Return allocation_usd + allocation_weight_pct from part_b (never $ as %)."""
    pb = part_b or {}
    alloc = dict(pb.get("allocation") or {})
    weights = dict(pb.get("allocation_weight_pct") or {})
    try:
        from scripts.lib.cio_decision_semantics import (
            allocation_weights_from_usd, looks_like_dollar_allocation,
        )
        if not weights and looks_like_dollar_allocation(alloc):
            weights = allocation_weights_from_usd(alloc)
        elif not weights and alloc:
            # Already looks like weights
            weights = {k: round(float(v), 2) for k, v in alloc.items()
                       if _num(v) is not None}
            if looks_like_dollar_allocation(alloc):
                weights = allocation_weights_from_usd(alloc)
    except Exception:
        if not weights and alloc:
            total = sum(max(0.0, _num(v) or 0.0) for v in alloc.values())
            if total > 100:  # treat as dollars
                weights = {
                    k: round(max(0.0, _num(v) or 0.0) / total * 100.0, 2)
                    for k, v in alloc.items()
                }
    return {
        "allocation_usd": {k: _num(v) for k, v in alloc.items()},
        "allocation_weight_pct": weights,
    }


def _canonicalize(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def facts_fingerprint(facts: dict[str, Any]) -> str:
    """Hash of numeric/operator facts only (not prose formatting)."""
    return hashlib.sha256(_canonicalize(facts).encode("utf-8")).hexdigest()


def build_report_view(model: dict[str, Any]) -> dict[str, Any]:
    """Project the canonical report model into a shared presentation view.

    All HTML / DOCX / PDF / CC surfaces must consume this view (or its
    `facts` / `sections`), never re-derive dollars from divergent code paths.
    """
    model = model or {}
    pa = model.get("part_a") or {}
    pb = model.get("part_b") or {}
    coverage = model.get("coverage") or {}
    manifest = model.get("manifest") or {}
    checkpoint = model.get("checkpoint") or {}
    letter = pa.get("letter") or {}
    decisions = list(pa.get("decisions_now") or [])
    capital = dict(pa.get("capital_plan") or {})
    posture = pa.get("portfolio_posture") or {}
    funnel = pa.get("opportunity_funnel") or {}
    risks = pa.get("counter_thesis_risks") or {}
    portfolio = pb.get("portfolio") or {}
    accounts = list(pb.get("accounts") or [])
    perf = pb.get("performance") or {}
    alloc_norm = normalize_allocation(pb)

    # ── Facts (single source of numbers) ──────────────────────────────────
    facts: dict[str, Any] = {
        "as_of": model.get("as_of"),
        "report_version": model.get("report_version"),
        "authority": model.get("authority") or "READ_ONLY_ADVISORY",
        "source_sha": manifest.get("source_sha"),
        "manifest_hash": manifest.get("manifest_hash"),
        "portfolio_total_usd": _num(portfolio.get("total_value")),
        "portfolio_cash_usd": _num(portfolio.get("cash_value")),
        "portfolio_cash_pct": _num(portfolio.get("cash_pct")),
        "positions_count": portfolio.get("positions_count"),
        "cash_total_usd": _num(capital.get("cash_total_usd")),
        "cash_reserved_usd": _num(capital.get("cash_reserved_usd")),
        "cash_investable_usd": _num(capital.get("cash_investable_usd")),
        "cash_earmarked_redeploy_usd": _num(
            capital.get("cash_earmarked_redeploy_usd")
            or (capital.get("sources") or {}).get("earmarked_redeploy_usd")
            or (capital.get("sources") or {}).get("maturities_usd")
        ),
        "recommended_deploy_usd": _num(capital.get("recommended_deploy_usd")),
        "recommended_raise_usd": _num(capital.get("recommended_raise_usd")),
        "post_plan_cash_usd": _num(capital.get("post_plan_cash_usd")),
        "post_plan_cash_pct": _num(capital.get("post_plan_cash_pct")),
        "allocation_usd": alloc_norm["allocation_usd"],
        "allocation_weight_pct": alloc_norm["allocation_weight_pct"],
        "decisions": [
            {
                "symbol": d.get("symbol"),
                "stance": d.get("stance") or d.get("stance_code") or d.get("cio_stance"),
                "stance_code": d.get("stance_code"),
                "current_value_usd": _num(d.get("current_value_usd")),
                "current_weight_pct": _num(d.get("current_weight_pct")),
                "recommended_delta_usd": _num(d.get("recommended_delta_usd")),
                "why_now": d.get("why_now"),
                "risk": d.get("risk"),
            }
            for d in decisions
        ],
        "sector_posture": [
            {
                "sector": s.get("sector"),
                "state": _prose(s.get("state")),
                "exposure_pct": _num(s.get("exposure_pct")),
                "target_pct": _num(s.get("target_pct")),
                "recommendation": _prose(s.get("recommendation")),
            }
            for s in (posture.get("sector_posture") or [])
            if "−" not in str(s.get("sector") or "") and not _is_pseudo_sector(s.get("sector"))
        ],
        "source_traceability_pct": _num(coverage.get("source_traceability_pct")),
        "field_count": coverage.get("field_count"),
    }
    fp = facts_fingerprint(facts)

    # ── Sections (ordered, format-agnostic) ───────────────────────────────
    sections: list[dict[str, Any]] = []

    sections.append({
        "id": "cover",
        "title": "Trade AI — Institutional Report v2",
        "kind": "cover",
        "meta": {
            "as_of": facts["as_of"],
            "authority": facts["authority"],
            "source_sha": facts["source_sha"],
            "manifest_hash_short": (str(facts["manifest_hash"] or "")[:12] or None),
            "traceability_pct": facts["source_traceability_pct"],
            "architecture": REPORT_ARCHITECTURE_VERSION,
        },
    })

    sections.append({
        "id": "cio_letter",
        "title": "CIO Letter / Executive Summary",
        "kind": "letter",
        "stance": letter.get("stance"),
        "thesis_summary": letter.get("thesis_summary"),
        "risk_posture": letter.get("risk_posture"),
        "priorities": list(letter.get("priorities") or []),
        "what_not_to_do": list(letter.get("what_not_to_do") or []),
        "what_changed": list(letter.get("what_changed") or []),
        "bullets": list(letter.get("bullets") or []),
    })

    sections.append({
        "id": "decisions_now",
        "title": "Decisions Now",
        "kind": "table",
        "headers": ["Symbol", "Stance", "Weight", "Value (USD)", "Δ $", "Why now", "Risk"],
        "rows": [
            [
                d.get("symbol") or "—",
                d.get("stance") or "—",
                fmt_pct(d.get("current_weight_pct")),
                fmt_usd(d.get("current_value_usd")),
                fmt_usd(d.get("recommended_delta_usd"), signed=True),
                d.get("why_now") or "—",
                d.get("risk") or "—",
            ]
            for d in facts["decisions"]
        ],
        "empty_message": "No material position decisions at this time.",
    })

    sections.append({
        "id": "capital_plan",
        "title": "Capital Plan",
        "kind": "kv",
        "rows": [
            ("Total cash", fmt_usd(facts["cash_total_usd"])),
            ("Reserved", fmt_usd(facts["cash_reserved_usd"])),
            ("Investable", fmt_usd(facts["cash_investable_usd"])),
            ("Earmarked redeploy", fmt_usd(facts["cash_earmarked_redeploy_usd"])),
            ("Recommended deploy", fmt_usd(facts["recommended_deploy_usd"])),
            ("Recommended raise", fmt_usd(facts["recommended_raise_usd"])),
            ("Post-plan cash", fmt_usd(facts["post_plan_cash_usd"])),
            ("Post-plan cash %", fmt_pct(facts["post_plan_cash_pct"])),
        ],
        "sources": capital.get("sources") or {},
        "uses": capital.get("uses") or {},
        "cash_policy_band": capital.get("cash_policy_band") or {},
    })

    rh = posture.get("risk_heat") or {}
    bp = posture.get("benchmark_posture") or {}
    top = posture.get("top_position") or {}
    sections.append({
        "id": "portfolio_posture",
        "title": "Portfolio Posture",
        "kind": "kv",
        "rows": [
            ("Top position", f"{top.get('symbol') or '—'} ({fmt_pct(top.get('weight_pct'))})"),
            ("Concentration fire %", fmt_pct(posture.get("concentration_fire_pct"))),
            ("Max drawdown", fmt_pct(rh.get("max_drawdown_pct"))),
            ("Sharpe", fmt_num(rh.get("sharpe"), 3)),
            ("Sortino", fmt_num(rh.get("sortino"), 3)),
            ("Benchmark", str(bp.get("label") or "—")),
            ("Portfolio CAGR", fmt_pct(bp.get("port_cagr"))),
            ("Alpha (ann.)", fmt_pct(bp.get("alpha_annualized"), signed=True)),
            ("Stance", str(posture.get("defensive_offensive_stance") or "—")),
        ],
        "sector_table": {
            "headers": ["Sector", "State", "Exposure", "Target", "Recommendation"],
            "rows": [
                [
                    s.get("sector") or "—",
                    s.get("state") or "—",
                    fmt_pct(s.get("exposure_pct")),
                    fmt_pct(s.get("target_pct")),
                    s.get("recommendation") or "—",
                ]
                for s in facts["sector_posture"]
            ],
        },
    })

    sections.append({
        "id": "opportunity_funnel",
        "title": "Opportunity Funnel",
        "kind": "funnel",
        "sector_opportunities": list(funnel.get("sector_opportunities") or []),
        "watch_additions": list(funnel.get("watch_additions") or []),
        "reentry_candidates": list(funnel.get("reentry_candidates") or []),
        "research_gaps": list(funnel.get("research_gaps") or []),
    })

    sections.append({
        "id": "counter_thesis",
        "title": "Counter-Thesis & Risks",
        "kind": "list",
        "highest_impact_unknowns": list(risks.get("highest_impact_unknowns") or []),
        "where_alex_may_be_wrong": list(risks.get("where_alex_may_be_wrong") or []),
        "guardian_hermes_disagreements": list(risks.get("guardian_hermes_disagreements") or []),
    })

    sections.append({
        "id": "portfolio_book",
        "title": "Portfolio Book",
        "part": "B",
        "kind": "kv",
        "rows": [
            ("Total portfolio value", fmt_usd(facts["portfolio_total_usd"])),
            ("Cash", fmt_usd(facts["portfolio_cash_usd"])),
            ("Cash %", fmt_pct(facts["portfolio_cash_pct"])),
            ("Positions", str(facts["positions_count"] if facts["positions_count"] is not None else "—")),
        ],
    })
    if accounts:
        sections.append({
            "id": "accounts",
            "title": "Accounts",
            "kind": "table",
            "headers": ["Account", "Broker", "Value", "Weight", "Gain/Loss", "Status"],
            "rows": [
                [
                    a.get("display_name") or a.get("account_id") or "—",
                    a.get("broker") or "—",
                    fmt_usd(a.get("total_value")),
                    fmt_pct(a.get("weight_pct")),
                    fmt_usd(a.get("gain_loss"), signed=True),
                    a.get("status") or "—",
                ]
                for a in accounts
            ],
        })

    if alloc_norm["allocation_usd"] or alloc_norm["allocation_weight_pct"]:
        keys = list(alloc_norm["allocation_weight_pct"].keys()) or list(alloc_norm["allocation_usd"].keys())
        sections.append({
            "id": "allocation",
            "title": "Asset Allocation",
            "kind": "table",
            "headers": ["Class", "Value (USD)", "Weight"],
            "rows": [
                [
                    k,
                    fmt_usd(alloc_norm["allocation_usd"].get(k)),
                    fmt_pct(alloc_norm["allocation_weight_pct"].get(k)),
                ]
                for k in keys
            ],
        })

    if perf:
        sections.append({
            "id": "performance",
            "title": "Performance",
            "kind": "kv",
            "rows": [
                ("YTD return", fmt_pct(perf.get("ytd_return"))),
                ("Inception return", fmt_pct(perf.get("inception_return"))),
                ("Portfolio CAGR", fmt_pct(perf.get("port_cagr"))),
                ("Benchmark CAGR", fmt_pct(perf.get("bench_cagr"))),
                ("Alpha (annualized)", fmt_pct(perf.get("alpha_annualized"), signed=True)),
                ("Sharpe", fmt_num(perf.get("sharpe"), 3)),
                ("Sortino", fmt_num(perf.get("sortino"), 3)),
                ("Max drawdown", fmt_pct(perf.get("max_drawdown"))),
            ],
        })

    # ── Phase 6 analytic completeness sections ──
    packet = pb.get("analytics_packet") or {}
    if not packet:
        try:
            from scripts.lib.cio_report_analytics import build_analytics_packet
            packet = build_analytics_packet(pb, as_of=model.get("as_of"))
        except Exception:
            packet = {}

    # Performance definitions table
    pdefs = packet.get("performance_definitions") or pb.get("performance_definitions") or {}
    if pdefs.get("metrics"):
        sections.append({
            "id": "performance_definitions",
            "title": "Performance Definitions (methodology truth)",
            "kind": "table",
            "headers": ["Metric", "Value", "Methodology", "Source", "Quality", "Note"],
            "rows": [
                [
                    m.get("metric") or "—",
                    (
                        "DATA_UNAVAILABLE" if m.get("is_unavailable")
                        else (fmt_pct(m.get("value")) if m.get("unit") == "percent"
                              else fmt_num(m.get("value")))
                    ),
                    str(m.get("methodology") or "—").replace("_", " "),
                    m.get("source") or "—",
                    m.get("quality") or "—",
                    (m.get("note") or "")[:80],
                ]
                for m in (pdefs.get("metrics") or [])
            ],
            "source_note": "Every figure carries methodology + source + quality. TWR/QTD not fabricated.",
        })

    # Change in value
    civ = packet.get("change_in_value") or pb.get("change_in_value") or {}
    if civ:
        civ_rows = []
        if civ.get("displayed"):
            c = civ.get("components") or {}
            civ_rows = [
                ("Beginning value", fmt_usd(c.get("beginning_value"))),
                ("Net contributions / withdrawals", fmt_usd(c.get("net_contributions_withdrawals"), signed=True)),
                ("Investment earnings", fmt_usd(c.get("investment_earnings"), signed=True)),
                ("Ending value", fmt_usd(c.get("ending_value"))),
                ("Residual", fmt_usd(civ.get("residual_usd"))),
                ("Status", "Reconciled ✓" if civ.get("reconciles") else str(civ.get("status"))),
            ]
        else:
            civ_rows = [
                ("Status", str(civ.get("status") or "not_displayed")),
                ("Note", str(civ.get("note") or "Bridge withheld — inputs insufficient or non-reconciling.")),
            ]
        sections.append({
            "id": "change_in_value",
            "title": "Change in Portfolio Value",
            "kind": "kv",
            "rows": civ_rows,
            "source_note": civ.get("equation") or "",
        })

    # Benchmark alignment
    ba = packet.get("benchmark_alignment") or pb.get("benchmark_alignment") or {}
    if ba:
        sections.append({
            "id": "benchmark_alignment",
            "title": "Benchmark Comparability",
            "kind": "kv",
            "rows": [
                ("Benchmark", str(ba.get("benchmark_label") or "—")),
                ("Portfolio CAGR", fmt_pct(ba.get("portfolio_cagr"))),
                ("Benchmark CAGR", fmt_pct(ba.get("benchmark_cagr"))),
                ("Portfolio period", str(ba.get("portfolio_period") or "—")),
                ("Benchmark period", str(ba.get("benchmark_period") or "—")),
                ("Comparability", str(ba.get("comparability_label") or "—").replace("_", " ")),
                ("Note", str(ba.get("note") or "")),
            ],
        })

    # Look-through coverage (must be impossible to miss)
    lt = packet.get("lookthrough") or pb.get("lookthrough_coverage") or {}
    if lt:
        lt_rows = [
            ("Coverage", str(lt.get("coverage_label") or "—")),
            ("Quality", str(lt.get("quality") or "—")),
            ("Note", str(lt.get("note") or "")),
        ]
        sections.append({
            "id": "lookthrough_coverage",
            "title": "Look-Through / X-Ray Coverage",
            "kind": "kv",
            "rows": lt_rows,
            "source_note": lt.get("coverage_label"),
        })
        if lt.get("sectors"):
            sections.append({
                "id": "lookthrough_sectors",
                "title": "Sector Exposure (look-through)",
                "kind": "table",
                "headers": ["Sector", "Weight %", "Source"],
                "rows": [
                    [s.get("sector"), fmt_pct(s.get("pct")), s.get("source") or "—"]
                    for s in (lt.get("sectors") or [])[:12]
                ],
            })

    # Valuation with coverage
    val = packet.get("valuation") or pb.get("valuation_coverage") or {}
    if val:
        vrows = [
            ("Coverage", str(val.get("coverage_label") or "—")),
            ("Status", str(val.get("status") or "—")),
            ("Fund/ETF share of book", fmt_pct(val.get("fund_etf_pct"))),
            ("Note", str(val.get("note") or "")),
        ]
        for m in val.get("multiples") or []:
            vrows.append((
                m.get("label") or m.get("metric"),
                f"{m.get('value')}x  (cov {m.get('coverage_pct')}%)" if m.get("coverage_pct") is not None
                else f"{m.get('value')}x",
            ))
        if not val.get("multiples"):
            vrows.append(("Multiples", "DATA_UNAVAILABLE — not shown without coverage"))
        sections.append({
            "id": "valuation_coverage",
            "title": "Valuation (coverage required)",
            "kind": "kv",
            "rows": vrows,
            "source_note": val.get("coverage_label"),
        })

    # Attribution honesty
    attr = packet.get("attribution") or pb.get("attribution_section") or {}
    if attr.get("components"):
        sections.append({
            "id": "attribution",
            "title": "Attribution (no overstatement)",
            "kind": "table",
            "headers": ["Component", "Value", "Methodology", "Quality", "Note"],
            "rows": [
                [
                    c.get("component"),
                    (
                        "DATA_UNAVAILABLE" if c.get("value") is None
                        else fmt_pct(c.get("value"))
                    ),
                    str(c.get("methodology") or "—").replace("_", " "),
                    c.get("quality") or "—",
                    (c.get("note") or "")[:70],
                ]
                for c in (attr.get("components") or [])
            ],
            "source_note": attr.get("note"),
        })

    # Tax lots
    tax = packet.get("tax_lots") or pb.get("tax_lot_section") or {}
    if tax:
        sections.append({
            "id": "tax_lots_summary",
            "title": "Unrealized / Tax Lots (advisory — not filing truth)",
            "kind": "kv",
            "rows": [
                ("Long-term unrealized", fmt_usd(tax.get("lt_unrealized_usd"), signed=True)),
                ("Short-term unrealized", fmt_usd(tax.get("st_unrealized_usd"), signed=True)),
                ("Lots shown", str(tax.get("row_count") or 0)),
                ("Quality", str(tax.get("quality") or "—")),
                ("Disclaimer", str(tax.get("disclaimer") or "")),
            ],
        })
        if tax.get("rows"):
            sections.append({
                "id": "tax_lots_detail",
                "title": "Open Lot Detail (top by |unrealized|)",
                "kind": "table",
                "headers": [
                    "Symbol", "Account", "Qty", "Cost", "MV", "Unrealized $", "Term", "Quality",
                ],
                "rows": [
                    [
                        r.get("symbol") or "—",
                        r.get("account") or "—",
                        fmt_num(r.get("quantity"), 2),
                        fmt_usd(r.get("cost_basis")),
                        fmt_usd(r.get("market_value")),
                        fmt_usd(r.get("unrealized_gl_usd"), signed=True),
                        r.get("holding_period") or "—",
                        r.get("quality_flag") or "ok",
                    ]
                    for r in (tax.get("rows") or [])[:15]
                ],
                "source_note": tax.get("disclaimer"),
            })

    # Income
    income = packet.get("income") or pb.get("income_section") or {}
    if income:
        if income.get("status") == "unavailable":
            sections.append({
                "id": "income",
                "title": "Income",
                "kind": "kv",
                "rows": [
                    ("Status", "DATA_UNAVAILABLE"),
                    ("Note", str(income.get("note") or "")),
                ],
            })
        else:
            sections.append({
                "id": "income",
                "title": "Income",
                "kind": "kv",
                "rows": [
                    ("Trailing income", fmt_usd(income.get("trailing_income_usd"))),
                    ("Forward / estimated", fmt_usd(income.get("forward_income_usd"))),
                    ("Yield", fmt_pct(income.get("yield_pct"))),
                    ("Quality", str(income.get("quality") or "—")),
                    ("Note", str(income.get("note") or "")),
                ],
            })

    # Phase 6 exit gate summary
    gate = packet.get("exit_gate") or {}
    if gate:
        sections.append({
            "id": "phase6_exit_gate",
            "title": "Analytic Completeness Gate",
            "kind": "table",
            "headers": ["Gate", "Result"],
            "rows": [[k, str(v)] for k, v in gate.items() if k != "ALL_PASS"]
                    + [["ALL_PASS", str(gate.get("ALL_PASS"))]],
        })

    sections.append({
        "id": "coverage",
        "title": "Data Coverage & Provenance",
        "kind": "kv",
        "rows": [
            ("Fields tracked", str(coverage.get("field_count") or "—")),
            ("Source traceability", fmt_pct(coverage.get("source_traceability_pct"))),
            ("Fields present", str(len(coverage.get("fields_present") or []))),
            ("Improved vs. reference", str(len(coverage.get("fields_improved_vs_reference") or []))),
            ("Explicitly unavailable", str(len(coverage.get("fields_unavailable") or []))),
            ("Quality flags", str(len(coverage.get("quality_flags") or checkpoint.get("quality_flags") or []))),
        ],
        "unavailable": list(coverage.get("fields_unavailable") or []),
    })
    # Field-coverage matrix + known gaps (same facts as model.fields / KNOWN_GAPS)
    field_rows = []
    for f in (model.get("fields") or [])[:40]:
        if not isinstance(f, dict):
            continue
        field_rows.append([
            f.get("field_id") or "—",
            f.get("status") or "—",
            f.get("source") or "—",
            f.get("quality") or "—",
        ])
    sections.append({
        "id": "field_coverage_matrix",
        "title": "Field-Coverage Matrix",
        "kind": "table",
        "headers": ["Field", "Status", "Source", "Quality"],
        "rows": field_rows,
    })

    gap_rows = []
    try:
        from scripts.lib.cio_report_v2 import KNOWN_GAPS
        for g in KNOWN_GAPS:
            gap_rows.append([
                g.get("gap_id") or "—",
                g.get("title") or "—",
                g.get("resolution") or "—",
                g.get("note") or "",
            ])
    except Exception:
        pass
    sections.append({
        "id": "known_gap_resolutions",
        "title": "Known-Gap Resolutions",
        "kind": "table",
        "headers": ["Gap", "Title", "Resolution", "Note"],
        "rows": gap_rows,
    })

    # Surface performance period sources that are methodology substitutes
    period_flags: list[str] = []
    periods = (perf.get("periods") or {}) if isinstance(perf, dict) else {}
    if isinstance(periods, dict):
        for pname, pdata in periods.items():
            if isinstance(pdata, dict):
                src = str(pdata.get("source") or "")
                if src:
                    period_flags.append(f"{pname}: {src}")
                    if "account-aggregated" in src:
                        period_flags.append(
                            f"{pname} flagged (account-aggregated methodology substitute)"
                        )
    qflags = list(model.get("quality_flags") or coverage.get("quality_flags") or [])
    flag_items = period_flags + [f"flagged field: {q}" for q in qflags[:20]]
    if flag_items:
        sections.append({
            "id": "quality_flags",
            "title": "Quality Flags",
            "kind": "list",
            "items": flag_items,
            "highest_impact_unknowns": flag_items,
        })
    sections.append({
        "id": "disclosure",
        "title": "Disclosure",
        "kind": "prose",
        "text": (
            "This report is generated by the Trade AI investment-office automation in an "
            "advisory-only capacity. No broker, order, or stop authority is exercised. "
            "Figures are composed from a single canonical model snapshot and are not investment advice."
        ),
    })
    # Command Center consumes the same decisions + capital facts
    command_center = {
        "decisions": facts["decisions"][:5],
        "capital": {
            "cash_total_usd": facts["cash_total_usd"],
            "cash_investable_usd": facts["cash_investable_usd"],
            "recommended_deploy_usd": facts["recommended_deploy_usd"],
            "recommended_raise_usd": facts["recommended_raise_usd"],
            "post_plan_cash_usd": facts["post_plan_cash_usd"],
        },
        "facts_fingerprint": fp,
    }

    return {
        "architecture_version": REPORT_ARCHITECTURE_VERSION,
        "authority": facts["authority"],
        "as_of": facts["as_of"],
        "report_version": facts["report_version"],
        "facts": facts,
        "sections": sections,
        "command_center": command_center,
        "facts_fingerprint": fp,
        "section_ids": [s["id"] for s in sections],
    }


def section_by_id(view: dict[str, Any], section_id: str) -> Optional[dict[str, Any]]:
    for s in view.get("sections") or []:
        if s.get("id") == section_id:
            return s
    return None
