#!/usr/bin/env python3
"""reporting_engine.py — Prospectus & analyst report orchestration.

Ad-hoc and scheduled generation for Command Center v3:
  - Summary prospectus-style reports (holdings, watchlist, sectors, portfolio)
  - Daily / weekly intelligence digests
  - Batch regeneration for BUY / STRONG BUY / ADD holdings (weekly delta refresh)
  - Optional Grok OAuth editorial pass (llm_lane) for polish and correlation

Registry: data/portfolios/reports/analyst/registry.json tracks fingerprints and export paths.

CLI:
  .venv/bin/python scripts/reporting_engine.py batch-holdings --grok
  .venv/bin/python scripts/reporting_engine.py generate --symbol RKLB --type symbol_holding
  .venv/bin/python scripts/reporting_engine.py registry
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
REPORT_OUT = PROJECT_ROOT / "data" / "portfolios" / "reports" / "analyst"
PROSPECTUS_DIR = REPORT_OUT / "prospectus"
REGISTRY_PATH = REPORT_OUT / "registry.json"

BUY_RECOMMENDATIONS = frozenset({
    "BUY", "STRONG BUY", "STRONG_BUY", "ADD", "ADD_ON_PULLBACK", "ACCUMULATE",
    "WAIT FOR PULLBACK", "WAIT_PULLBACK", "ADD ON PULLBACK",
})

ACTION_SIGNALS = frozenset({
    "BUY", "STRONG BUY", "STRONG_BUY", "ADD", "ACCUMULATE", "ADD_ON_PULLBACK", "ADD ON PULLBACK",
})

MANUAL_WATCHLIST_SOURCES = frozenset({"operator", "personal_watchlist"})

PROSPECTUS_SECTIONS = [
    "header_context", "executive_summary", "personal_performance", "report_continuity",
    "news_catalysts", "technical_analysis", "fundamental_valuation", "intelligence_view",
    "risk_assessment", "action_plan",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def prospectus_needs_refresh(
    prev: dict | None,
    current_fingerprint: str,
    *,
    stale_days: int | None = None,
) -> tuple[bool, str]:
    """True when report should regenerate — fingerprint delta or weekly age gate."""
    if not prev:
        return True, "never_generated"
    if prev.get("fingerprint") != current_fingerprint:
        return True, "fingerprint_changed"
    if stale_days and stale_days > 0:
        gen = _parse_iso(prev.get("generated_at"))
        if gen is None:
            return True, "missing_timestamp"
        age_days = (datetime.now(timezone.utc) - gen).total_seconds() / 86400
        if age_days >= stale_days:
            return True, f"stale_{int(age_days)}d"
    return False, "current"


def _load_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default if default is not None else {}


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def load_registry() -> dict:
    reg = _load_json(REGISTRY_PATH, {"version": 1, "reports": []})
    if not isinstance(reg.get("reports"), list):
        reg["reports"] = []
    reg["reports"] = _dedupe_registry_reports(reg["reports"])
    return reg


def _dedupe_registry_reports(reports: list[dict]) -> list[dict]:
    """Keep newest entry per (report_type, symbol); list is newest-first."""
    seen_sym: set[tuple[str, str]] = set()
    seen_id: set[str] = set()
    out: list[dict] = []
    for r in reports:
        rtype = r.get("report_type") or ""
        sym = (r.get("symbol") or "").upper()
        if rtype in ("symbol_holding", "symbol_watchlist") and sym:
            key = (rtype, sym)
            if key in seen_sym:
                continue
            seen_sym.add(key)
        else:
            rid = r.get("id")
            if rid:
                if rid in seen_id:
                    continue
                seen_id.add(rid)
        out.append(r)
    return out[:500]


def save_registry(reg: dict) -> None:
    reg["updated_at"] = _now_iso()
    _save_json(REGISTRY_PATH, reg)


def _import_builder():
    import sys
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    import analyst_report_builder as arb
    return arb


def symbol_fingerprint(symbol: str) -> str:
    """Content hash for change detection — holdings, synthesis, ensemble, technicals, proposals."""
    arb = _import_builder()
    sym = symbol.upper()
    holding = arb._holding_for_symbol(sym)
    enrich = arb._enriched(sym, holding)
    wl = arb._watchlist_row(sym)
    syn = arb._synthesis(sym)
    ens = arb._ensemble(sym)
    proposal = arb._proposal_context(sym)
    rec = arb._watchlist_rating(wl, syn)
    payload = {
        "symbol": sym,
        "recommendation": rec,
        "price": enrich.get("price") or enrich.get("latest_price"),
        "day_change_pct": enrich.get("day_change_pct") or (holding or {}).get("day_change_pct"),
        "synthesis_updated": (syn or {}).get("updated_at"),
        "decision_safety": (syn or {}).get("decision_safety"),
        "portfolio_pct": (holding or {}).get("portfolio_pct"),
        "market_value": (holding or {}).get("market_value"),
        "score": (wl or {}).get("score"),
        "rsi": enrich.get("rsi"),
        "ensemble_score": (ens or {}).get("final_score"),
        "ensemble_decision": (ens or {}).get("final_decision"),
        "proposal_status": (proposal or {}).get("status"),
        "proposal_id": (proposal or {}).get("id"),
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def holding_recommendation(symbol: str) -> str:
    arb = _import_builder()
    sym = symbol.upper()
    return arb._watchlist_rating(arb._watchlist_row(sym), arb._synthesis(sym))


def _action_signals_map() -> dict[str, str]:
    data = _load_json(STATE_DIR / "action_signals.json") or {}
    out: dict[str, str] = {}
    for row in data.get("signals") or []:
        sym = str(row.get("symbol") or "").upper()
        if sym:
            out[sym] = str(row.get("signal") or "").upper().replace("_", " ")
    return out


def recommendation_actionable(rec: str) -> bool:
    """True for BUY / ADD / STRONG BUY / pullback-wait actionable stances."""
    u = str(rec or "").upper().replace("_", " ").strip()
    if not u or u in ("REVIEW", "IGNORE", "NONE", "EXIT", "AVOID", "SELL"):
        return False
    if "REBALANCE" in u or u.startswith("TRIM"):
        return False
    for token in BUY_RECOMMENDATIONS | ACTION_SIGNALS:
        t = token.replace("_", " ")
        if t == u or u.startswith(t) or t in u:
            return True
    if "PULLBACK" in u and any(x in u for x in ("ADD", "WAIT", "BUY")):
        return True
    return False


def watchlist_manually_added(*, source: str = "", origin_system: str = "") -> bool:
    """Operator-seeded or personal watchlist names (any CIO stance)."""
    src = str(source or "").lower()
    origin = str(origin_system or "").lower()
    return src in MANUAL_WATCHLIST_SOURCES or origin == "operator"


def watchlist_report_eligible(
    *,
    source: str = "",
    origin_system: str = "",
    latest_recommendation: str = "",
    holdings_llm_action: str = "",
    synthesis_rec: str = "",
) -> bool:
    """Manual/operator watchlist OR buy / strong buy / wait-for-pullback CIO view."""
    if watchlist_manually_added(source=source, origin_system=origin_system):
        return True
    for rec in (latest_recommendation, holdings_llm_action, synthesis_rec):
        if recommendation_actionable(rec):
            return True
    return False


def _holding_symbols_set() -> set[str]:
    arb = _import_builder()
    h = arb._load(STATE_DIR / "holdings.json")
    return {
        str(r.get("symbol", "")).upper()
        for r in (h.get("holdings") or [])
        if r.get("symbol") and not r.get("is_cash")
    }


def eligible_holding_symbols(
    *,
    min_market_value: float = 0.0,
    recommendations: frozenset[str] | None = None,
) -> list[dict]:
    """All portfolio holdings above min market value (deduped by symbol)."""
    arb = _import_builder()
    sig_map = _action_signals_map()
    h = arb._load(STATE_DIR / "holdings.json")
    out: list[dict] = []
    for row in h.get("holdings") or []:
        if row.get("is_cash") or not row.get("symbol"):
            continue
        if arb._f(row.get("market_value")) < min_market_value:
            continue
        sym = str(row["symbol"]).upper()
        if recommendations:
            rec_check = holding_recommendation(sym).upper().replace("_", " ")
            action_sig = sig_map.get(sym, "")
            if not recommendation_actionable(rec_check) and not recommendation_actionable(action_sig):
                if not any(t.replace("_", " ") in rec_check for t in recommendations):
                    continue
        rec = holding_recommendation(sym).upper().replace("_", " ")
        rec_norm = rec.replace("  ", " ").strip()
        action_sig = sig_map.get(sym, "")
        display_rec = (
            action_sig if recommendation_actionable(action_sig) and not recommendation_actionable(rec_norm)
            else (rec_norm or action_sig or "HOLD")
        )
        entry = {
            "symbol": sym,
            "recommendation": display_rec,
            "market_value": arb._f(row.get("market_value")),
            "portfolio_pct": arb._f(row.get("portfolio_pct")),
            "fingerprint": symbol_fingerprint(sym),
            "action_signal": action_sig or None,
        }
        prev = next((x for x in out if x["symbol"] == sym), None)
        if prev is None:
            out.append(entry)
        elif entry["market_value"] > prev["market_value"]:
            out.remove(prev)
            out.append(entry)
    return sorted(out, key=lambda x: x["market_value"], reverse=True)


def eligible_watchlist_symbols(*, limit: int = 120) -> list[dict]:
    """Watchlist-only: manually added OR buy / strong buy / wait-for-pullback."""
    arb = _import_builder()
    held = _holding_symbols_set()
    rows = arb._db_query(
        """SELECT DISTINCT ON (wi.symbol)
                  wi.symbol, wi.source, wi.origin_system, wi.holdings_llm_action, wi.status,
                  wfs.recommendation AS synthesis_rec,
                  rc.latest_recommendation
           FROM watchlist_items wi
           LEFT JOIN watchlist_final_synthesis wfs ON wfs.symbol = wi.symbol
           LEFT JOIN watchlist_research_cards rc ON rc.symbol = wi.symbol
           WHERE wi.status <> 'removed'
           ORDER BY wi.symbol,
                    (wi.source IN ('operator', 'personal_watchlist') OR wi.origin_system = 'operator') DESC,
                    wi.updated_at DESC""",
    ) or []
    manual_rows: list[dict] = []
    buy_rows: list[dict] = []
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        if not sym or sym in held:
            continue
        source = str(row.get("source") or "")
        origin = str(row.get("origin_system") or "")
        syn_rec = str(row.get("synthesis_rec") or "")
        llm_rec = str(row.get("holdings_llm_action") or "")
        latest = str(row.get("latest_recommendation") or "")
        if not watchlist_report_eligible(
            source=source,
            origin_system=origin,
            latest_recommendation=latest,
            holdings_llm_action=llm_rec,
            synthesis_rec=syn_rec,
        ):
            continue
        display_rec = latest or llm_rec or syn_rec or "WATCH"
        manual = watchlist_manually_added(source=source, origin_system=origin)
        entry = {
            "symbol": sym,
            "recommendation": display_rec,
            "source": source.lower(),
            "operator_added": manual,
            "fingerprint": symbol_fingerprint(sym),
        }
        if manual:
            manual_rows.append(entry)
        else:
            buy_rows.append(entry)
    manual_rows.sort(key=lambda x: x["symbol"])
    buy_rows.sort(key=lambda x: x["symbol"])
    return (manual_rows + buy_rows)[:limit]


def validate_report_coverage() -> dict:
    """Compare eligible universe vs verified on-disk prospectus files."""
    holdings = eligible_holding_symbols()
    watchlist = eligible_watchlist_symbols(limit=200)
    links = report_links_map(limit=500).get("links") or {}
    h_syms = {r["symbol"] for r in holdings}
    w_syms = {r["symbol"] for r in watchlist}
    linked = set(links.keys())
    return {
        "holdings_eligible": len(h_syms),
        "holdings_with_links": len(h_syms & linked),
        "holdings_missing": sorted(h_syms - linked),
        "watchlist_eligible": len(w_syms),
        "watchlist_with_links": len(w_syms & linked),
        "watchlist_missing": sorted(w_syms - linked),
        "watchlist_missing_truncated": sorted(w_syms - linked)[:50],
        "total_links": len(links),
    }


def verified_export_urls(symbol: str, report_type: str = "symbol_holding") -> dict | None:
    """Return docx/pdf URLs only when files exist on disk (no phantom links)."""
    from report_lineage import canonical_export_paths

    sym = symbol.upper()
    paths = canonical_export_paths(sym, report_type)
    docx_p = paths["docx"] if paths["docx"].exists() else None
    pdf_p = paths["pdf"] if paths["pdf"].exists() else None
    if not docx_p and not pdf_p:
        return None

    def _url(p: Path | None) -> str | None:
        if not p:
            return None
        try:
            rel = p.relative_to(PROJECT_ROOT)
            return "/" + str(rel).replace("\\", "/")
        except ValueError:
            return str(p)

    generated_at = None
    if paths["json"].exists():
        meta = (_load_json(paths["json"]) or {}).get("meta") or {}
        generated_at = meta.get("generated_at")
        grok = bool((meta.get("grok_editorial") or {}).get("applied"))
    else:
        grok = False

    return {
        "docx": _url(docx_p),
        "pdf": _url(pdf_p),
        "generated_at": generated_at,
        "grok_edited": grok,
        "report_type": report_type,
    }


def report_links_map(*, symbols: list[str] | None = None, limit: int = 300) -> dict:
    """Symbol → verified prospectus links (holding preferred, then watchlist)."""
    reg = load_registry()
    from report_lineage import canonical_registry_map

    by_holding = canonical_registry_map(reg.get("reports") or [], "symbol_holding")
    by_watchlist = canonical_registry_map(reg.get("reports") or [], "symbol_watchlist")
    filter_set = {s.upper() for s in symbols if s} if symbols else None

    links: dict[str, dict] = {}
    candidates: list[tuple[str, str]] = []

    for sym, row in by_holding.items():
        candidates.append((sym, "symbol_holding"))
        _ = row
    for sym, row in by_watchlist.items():
        if sym not in by_holding:
            candidates.append((sym, "symbol_watchlist"))
        _ = row

    for pattern, rtype in (("prospectus_*_latest.json", "symbol_holding"), ("watchlist_*_latest.json", "symbol_watchlist")):
        for json_path in REPORT_OUT.glob(pattern):
            stem = json_path.stem
            sym = stem.replace("prospectus_", "").replace("watchlist_", "").replace("_latest", "").upper()
            if sym and (sym, rtype) not in candidates:
                candidates.append((sym, rtype))

    for sym, rtype in candidates:
        if filter_set and sym not in filter_set:
            continue
        if sym in links:
            continue
        verified = verified_export_urls(sym, rtype)
        if not verified:
            continue
        reg_row = (by_holding if rtype == "symbol_holding" else by_watchlist).get(sym) or {}
        links[sym] = {**verified, "recommendation": reg_row.get("recommendation")}

    ordered = sorted(links.items(), key=lambda kv: kv[1].get("generated_at") or "", reverse=True)
    if limit and len(ordered) > limit:
        ordered = ordered[:limit]
    out = dict(ordered)
    return {"links": out, "count": len(out), "updated_at": reg.get("updated_at")}


def apply_grok_editorial(report: dict, *, lane: str = "grok", timeout: int = 120) -> dict:
    """Polish executive summary and recommendation via Grok OAuth (free llm_lane)."""
    try:
        import llm_lane
    except Exception:
        return report

    if not llm_lane.available(lane):
        report.setdefault("meta", {})["grok_editorial"] = {"applied": False, "reason": f"{lane} unavailable"}
        return report

    meta = report.get("meta") or {}
    sym = meta.get("symbol") or "Portfolio"
    sections = report.get("sections") or []
    exec_sec = next((s for s in sections if s.get("id") == "executive_summary"), {})
    rec_sec = next((s for s in sections if s.get("id") in ("action_plan", "recommendation")), {})
    kpis = meta.get("kpis") or {}

    cont_sec = next((s for s in sections if s.get("id") == "report_continuity"), {})
    cont_ctx = cont_sec.get("content", "")[:500] if cont_sec else ""

    intel_sec = next((s for s in sections if s.get("id") == "intelligence_view"), {})
    callouts = exec_sec.get("callouts") or []

    prompt = f"""You are a senior equity research editor at an institutional analyst firm.
Polish the following machine-generated holding prospectus for {sym} into sharp, confident analyst prose.
Write like a published research note — synthesized and actionable, not a data dump.
Keep all facts accurate; do not invent prices, ratings, or catalysts.

EXECUTIVE SUMMARY (draft):
{exec_sec.get('content', '')[:1200]}

ACTION CALLOUTS (preserve meaning exactly):
{json.dumps(callouts, default=str)[:500]}

RECOMMENDATION / ACTION PLAN (draft):
{rec_sec.get('content', '') or '; '.join((rec_sec.get('bullets') or [])[:4])}

INTELLIGENCE SYNTHESIS (draft):
{(intel_sec.get('content') or '')[:600]}

CONTINUITY VS PRIOR REPORT:
{cont_ctx or 'First report — no prior baseline.'}

KEY METRICS: {json.dumps(kpis, default=str)[:600]}

Respond in JSON only:
{{"executive_summary": "One confident lead paragraph (3-5 sentences) with clear stance",
  "recommendation": "1-2 sentences reiterating specific action with price discipline",
  "intelligence_view": "2-3 sentences synthesizing agent panel — no verbatim quotes",
  "editor_notes": "brief list of what you refined"}}"""

    try:
        raw = llm_lane.generate(prompt, lane=lane, timeout=timeout)
        m = re.search(r"\{[\s\S]*\}", raw)
        parsed = json.loads(m.group(0)) if m else {}
        if parsed.get("executive_summary"):
            for s in sections:
                if s.get("id") == "executive_summary":
                    s["content"] = parsed["executive_summary"]
                    s["grok_edited"] = True
        if parsed.get("recommendation"):
            for s in sections:
                if s.get("id") in ("recommendation", "action_plan"):
                    s["content"] = parsed["recommendation"]
                    s["grok_edited"] = True
        if parsed.get("intelligence_view"):
            for s in sections:
                if s.get("id") == "intelligence_view":
                    s["content"] = parsed["intelligence_view"]
                    s["grok_edited"] = True
        meta["grok_editorial"] = {
            "applied": True,
            "lane": lane,
            "editor_notes": parsed.get("editor_notes"),
            "edited_at": _now_iso(),
        }
        report["meta"] = meta
        report["sections"] = sections
    except Exception as e:
        meta["grok_editorial"] = {"applied": False, "reason": str(e)[:200]}
        report["meta"] = meta
    return report


def generate_report(
    *,
    report_type: str,
    symbol: str | None = None,
    sector: str | None = None,
    topic: str | None = None,
    sections: list[str] | None = None,
    formats: list[str] | None = None,
    grok_edit: bool = False,
    output_stem: str | None = None,
    generation_mode: str = "adhoc",
) -> dict:
    """Build one report, optionally Grok-edit, export DOCX/PDF, register in manifest."""
    import sys
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from analyst_report_builder import build_report, save_report_json
    from report_export import export_report
    from report_lineage import (
        archive_report,
        archive_snapshot_before_update,
        canonical_export_paths,
        compute_continuity,
        load_prior_report,
        next_generation_number,
        stable_registry_id,
        upsert_registry_reports,
    )

    reg = load_registry()
    sym_u = (symbol or "").strip().upper() or None
    prior = None
    if sym_u and report_type.startswith("symbol_"):
        prior = load_prior_report(sym_u, report_type, registry_reports=reg.get("reports"))

    sections = sections or (PROSPECTUS_SECTIONS if report_type.startswith("symbol_") else None)
    gen_num = next_generation_number(sym_u) if sym_u else 1
    report = build_report(
        report_type=report_type,
        symbol=symbol,
        sector=sector,
        topic=topic,
        sections=sections,
        prior_report=prior,
        generation=gen_num,
    )
    meta = report.setdefault("meta", {})
    meta["document_class"] = "summary_prospectus" if report_type.startswith("symbol_") else report_type
    meta["generation_mode"] = generation_mode
    if sym_u and report_type.startswith("symbol_"):
        meta["living_document"] = True
        meta["export_stem"] = canonical_export_paths(sym_u, report_type)["json"].stem

    fp = symbol_fingerprint(symbol) if symbol else None
    if symbol and fp:
        meta["content_fingerprint"] = fp

    if sym_u and prior and report_type.startswith("symbol_"):
        kpis = meta.get("kpis") or {}
        continuity = compute_continuity(
            prior,
            price=float(kpis.get("price") or 0),
            recommendation=str(kpis.get("recommendation") or "Review"),
            unrealized_pnl_pct=kpis.get("unrealized_pnl_pct"),
            thesis_status=str(kpis.get("thesis_status") or "Review"),
            fingerprint=fp,
        )
        for sec in report.get("sections") or []:
            if sec.get("id") == "report_continuity":
                sec.update({
                    "content": continuity.get("content"),
                    "bullets": continuity.get("bullets"),
                    "metrics": continuity.get("metrics"),
                })
                break
        meta["generation"] = continuity.get("generation", gen_num)

    if grok_edit and report_type.startswith("symbol_"):
        report = apply_grok_editorial(report)

    sym = symbol or meta.get("report_type", "report")
    in_place = bool(sym_u and report_type.startswith("symbol_"))
    if in_place:
        paths = canonical_export_paths(sym_u, report_type)
        archive_snapshot_before_update(sym_u, report_type)
        stem = paths["json"].stem
        json_path = paths["json"]
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(report, indent=2, default=str))
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = output_stem or f"{sym}_{report_type}_{ts}"
        json_path = save_report_json(report, stem=stem)

    exports: dict[str, Any] = {}
    docx_path: Path | None = None
    pdf_path: Path | None = None
    for fmt in formats or ["docx", "pdf"]:
        result = export_report(report, fmt, output_stem=stem, in_place=in_place)
        if result.get("ok"):
            p = Path(str(result.get("path") or ""))
            if fmt == "docx":
                docx_path = p if p.exists() else None
            if fmt == "pdf":
                pdf_path = p if p.exists() else None
            exports[fmt] = result.get("url") or result.get("path")
        else:
            exports[fmt] = {"error": result.get("error")}

    if in_place:
        from report_lineage import _export_url
        exports["json"] = _export_url(json_path)
        archive_report(
            report,
            report_id=stable_registry_id(sym_u, report_type),
            report_type=report_type,
            symbol=sym_u,
            json_path=Path(json_path),
            fingerprint=fp,
        )
    else:
        exports["json"] = str(json_path)

    entry = {
        "id": stable_registry_id(sym_u, report_type) if in_place else stem,
        "report_type": report_type,
        "symbol": symbol,
        "sector": sector,
        "topic": topic,
        "title": meta.get("title"),
        "recommendation": (meta.get("kpis") or {}).get("recommendation"),
        "fingerprint": fp,
        "grok_edited": bool((meta.get("grok_editorial") or {}).get("applied")),
        "generated_at": meta.get("generated_at") or _now_iso(),
        "generation": meta.get("generation"),
        "prior_report_at": meta.get("prior_report_at"),
        "exports": exports,
    }
    reg = load_registry()
    reg["reports"] = upsert_registry_reports(reg.get("reports") or [], entry)
    save_registry(reg)

    return {"ok": True, "report": report, "registry_entry": entry, "exports": exports}


def generate_holding_prospectus_batch(
    *,
    force: bool = False,
    grok_edit: bool = True,
    formats: list[str] | None = None,
    limit: int = 120,
    stale_days: int | None = None,
    generation_mode: str = "batch",
) -> dict:
    """Generate/update prospectus for all portfolio holdings.

    Skips when fingerprint unchanged unless force=True. Optional stale_days only when
    explicitly passed (autonomous daily/weekly modes do NOT refresh on age alone).
    Living documents overwrite prospectus_{SYMBOL}_latest.* in place; prior JSON
    snapshots go to history/ before each update.
    """
    eligible = eligible_holding_symbols()[:limit]
    from report_lineage import canonical_registry_map

    reg = load_registry()
    by_sym = canonical_registry_map(reg.get("reports") or [], "symbol_holding")

    results = {
        "generated": [], "skipped": [], "failed": [], "eligible": len(eligible),
        "stale_days": stale_days, "force": force,
    }
    for row in eligible:
        sym = row["symbol"]
        prev = by_sym.get(sym)
        if not force:
            needs, reason = prospectus_needs_refresh(
                prev, row["fingerprint"], stale_days=stale_days,
            )
            if not needs:
                results["skipped"].append({
                    "symbol": sym, "reason": reason, "fingerprint": row["fingerprint"],
                })
                continue
        else:
            reason = "forced"
        try:
            use_grok = grok_edit and reason in ("never_generated", "fingerprint_changed", "forced")
            out = generate_report(
                report_type="symbol_holding",
                symbol=sym,
                sections=PROSPECTUS_SECTIONS,
                formats=formats or ["docx", "pdf"],
                grok_edit=use_grok,
                generation_mode=generation_mode,
            )
            results["generated"].append({
                "symbol": sym,
                "id": out["registry_entry"]["id"],
                "exports": out["exports"],
                "grok_edited": out["registry_entry"].get("grok_edited"),
                "refresh_reason": reason,
            })
        except Exception as e:
            results["failed"].append({"symbol": sym, "error": str(e)[:200]})

    results["ok"] = len(results["failed"]) == 0
    results["completed_at"] = _now_iso()
    batch_path = PROSPECTUS_DIR / f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    PROSPECTUS_DIR.mkdir(parents=True, exist_ok=True)
    _save_json(batch_path, results)
    results["batch_log"] = str(batch_path)
    return results


def generate_watchlist_prospectus_batch(
    *,
    force: bool = False,
    grok_edit: bool = True,
    formats: list[str] | None = None,
    limit: int = 30,
    generation_mode: str = "batch_watchlist",
) -> dict:
    """Generate/update watchlist prospectus for operator-added / BUY-side names not held."""
    eligible = eligible_watchlist_symbols(limit=limit)
    from report_lineage import canonical_registry_map

    reg = load_registry()
    by_sym = canonical_registry_map(reg.get("reports") or [], "symbol_watchlist")
    results = {
        "generated": [], "skipped": [], "failed": [], "eligible": len(eligible), "force": force,
    }
    for row in eligible:
        sym = row["symbol"]
        prev = by_sym.get(sym)
        if not force:
            needs, reason = prospectus_needs_refresh(prev, row["fingerprint"], stale_days=None)
            if not needs:
                results["skipped"].append({"symbol": sym, "reason": reason})
                continue
        else:
            reason = "forced"
        try:
            use_grok = grok_edit and reason in ("never_generated", "fingerprint_changed", "forced")
            out = generate_report(
                report_type="symbol_watchlist",
                symbol=sym,
                sections=PROSPECTUS_SECTIONS,
                formats=formats or ["docx", "pdf"],
                grok_edit=use_grok,
                generation_mode=generation_mode,
            )
            results["generated"].append({
                "symbol": sym,
                "id": out["registry_entry"]["id"],
                "exports": out["exports"],
                "grok_edited": out["registry_entry"].get("grok_edited"),
                "refresh_reason": reason,
            })
        except Exception as e:
            results["failed"].append({"symbol": sym, "error": str(e)[:200]})

    results["ok"] = len(results["failed"]) == 0
    results["completed_at"] = _now_iso()
    return results


def generate_scheduled(report_type: str, *, formats: list[str] | None = None) -> dict:
    """Daily digest or weekly review wrapper."""
    formats = formats or ["docx", "pdf"]
    return generate_report(report_type=report_type, formats=formats, grok_edit=False)


def registry_list(
    *,
    symbol: str | None = None,
    report_type: str | None = None,
    limit: int = 50,
    canonical_only: bool = True,
) -> dict:
    reg = load_registry()
    rows = reg.get("reports") or []
    if report_type and canonical_only:
        from report_lineage import canonical_registry_map
        rows = list(canonical_registry_map(rows, report_type).values())
    if symbol:
        rows = [r for r in rows if (r.get("symbol") or "").upper() == symbol.upper()]
    if report_type and not canonical_only:
        rows = [r for r in rows if r.get("report_type") == report_type]
    rows = sorted(rows, key=lambda r: r.get("generated_at") or "", reverse=True)
    return {"reports": rows[:limit], "total": len(rows), "updated_at": reg.get("updated_at")}


def republish_canonical_from_registry(*, report_type: str = "symbol_holding") -> dict:
    """Copy versioned exports to prospectus_{SYMBOL}_latest.* for all registry rows."""
    from report_lineage import (
        canonical_registry_map,
        publish_canonical_exports,
        upsert_registry_reports,
        _resolve_report_json,
    )

    reg = load_registry()
    rows = list(canonical_registry_map(reg.get("reports") or [], report_type).values())
    results = {"republished": [], "failed": []}
    for row in rows:
        sym = (row.get("symbol") or "").upper()
        if not sym:
            continue
        ex = row.get("exports") or {}
        try:
            json_p = _resolve_report_json(ex.get("versioned_json") or ex.get("json"))
            docx_p = _resolve_report_json(ex.get("docx"))
            pdf_p = _resolve_report_json(ex.get("pdf"))
            if docx_p and not str(docx_p).endswith("_latest.docx"):
                docx_p = Path(str(docx_p)) if docx_p else None
            if pdf_p and not str(pdf_p).endswith("_latest.pdf"):
                pdf_p = Path(str(pdf_p)) if pdf_p else None
            # Resolve docx/pdf from REPORT_OUT by stem id
            rid = row.get("id") or ""
            if not docx_p or not docx_p.exists():
                for hit in REPORT_OUT.glob(f"{rid}*.docx"):
                    docx_p = hit
                    break
            if not pdf_p or not pdf_p.exists():
                for hit in REPORT_OUT.glob(f"{rid}*.pdf"):
                    pdf_p = hit
                    break
            urls = publish_canonical_exports(
                sym, report_type=report_type,
                json_path=json_p, docx_path=docx_p, pdf_path=pdf_p,
            )
            if urls:
                row["exports"] = {**ex, **urls}
                results["republished"].append({"symbol": sym, "urls": urls})
        except Exception as e:
            results["failed"].append({"symbol": sym, "error": str(e)[:120]})
    if results["republished"]:
        reg = load_registry()
        by_sym = canonical_registry_map(reg.get("reports") or [], report_type)
        for item in results["republished"]:
            sym = item["symbol"]
            if sym in by_sym:
                entry = by_sym[sym]
                entry["exports"] = {**(entry.get("exports") or {}), **item["urls"]}
                reg["reports"] = upsert_registry_reports(reg.get("reports") or [], entry)
        save_registry(reg)
    results["ok"] = len(results["failed"]) == 0
    return results


def run_autonomous_cycle(
    *,
    mode: str = "weekly",
    force: bool = False,
    grok_edit: bool = True,
    limit: int = 120,
) -> dict:
    """Autonomous report cycle — holdings + watchlist prospectus refresh."""
    mode = (mode or "weekly").lower()
    gen_mode = {
        "daily": "autonomous_daily",
        "weekly": "autonomous_weekly",
        "full": "autonomous_full",
    }.get(mode)
    if not gen_mode:
        return {"ok": False, "error": f"unknown mode: {mode}"}
    holding = generate_holding_prospectus_batch(
        force=force or mode == "full",
        grok_edit=grok_edit,
        limit=limit,
        stale_days=None,
        generation_mode=gen_mode,
    )
    watchlist = generate_watchlist_prospectus_batch(
        force=force or mode == "full",
        grok_edit=grok_edit,
        limit=limit,
        generation_mode=gen_mode + "_watchlist",
    )
    return {
        "ok": holding.get("ok") and watchlist.get("ok"),
        "mode": mode,
        "holdings": holding,
        "watchlist": watchlist,
        "generated": (holding.get("generated") or []) + (watchlist.get("generated") or []),
        "skipped": (holding.get("skipped") or []) + (watchlist.get("skipped") or []),
        "failed": (holding.get("failed") or []) + (watchlist.get("failed") or []),
        "completed_at": _now_iso(),
    }


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Trade AI v12 Reporting Engine")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_gen = sub.add_parser("generate", help="Generate one report")
    p_gen.add_argument("--type", default="symbol_holding")
    p_gen.add_argument("--symbol")
    p_gen.add_argument("--sector")
    p_gen.add_argument("--topic")
    p_gen.add_argument("--grok", action="store_true")
    p_gen.add_argument("--format", default="all", choices=("docx", "pdf", "all", "json"))

    p_batch = sub.add_parser("batch-holdings", help="Batch prospectus for all portfolio holdings")
    p_batch.add_argument("--force", action="store_true")
    p_batch.add_argument("--grok", action="store_true", default=True)
    p_batch.add_argument("--no-grok", action="store_true")
    p_batch.add_argument("--limit", type=int, default=120)
    p_batch.add_argument("--stale-days", type=int, default=0, help="refresh if older than N days (weekly: 6)")

    p_wl = sub.add_parser("batch-watchlist", help="Batch prospectus for manual / buy-side watchlist names")
    p_wl.add_argument("--force", action="store_true")
    p_wl.add_argument("--grok", action="store_true", default=True)
    p_wl.add_argument("--no-grok", action="store_true")
    p_wl.add_argument("--limit", type=int, default=40)

    p_reg = sub.add_parser("registry", help="List registry")
    p_reg.add_argument("--symbol")
    p_reg.add_argument("--type")

    p_sched = sub.add_parser("scheduled", help="Run scheduled digest")
    p_sched.add_argument("kind", choices=("daily_digest", "weekly_review"))
    p_sched.add_argument("--format", default="all", choices=("docx", "pdf", "all"))

    p_repub = sub.add_parser("republish-canonical", help="Publish stable prospectus_{SYM}_latest.* from registry")
    p_repub.add_argument("--type", default="symbol_holding")

    p_auto = sub.add_parser("autonomous", help="Autonomous holding prospectus cycle")
    p_auto.add_argument("--mode", default="weekly", choices=("daily", "weekly", "full"))
    p_auto.add_argument("--force", action="store_true")
    p_auto.add_argument("--grok", action="store_true", default=True)
    p_auto.add_argument("--no-grok", action="store_true")
    p_auto.add_argument("--limit", type=int, default=120)

    args = ap.parse_args()

    if args.cmd == "generate":
        fmts = None if args.format == "json" else (["docx", "pdf"] if args.format == "all" else [args.format])
        out = generate_report(
            report_type=args.type,
            symbol=args.symbol,
            sector=args.sector,
            topic=args.topic,
            grok_edit=args.grok,
            formats=fmts,
        )
        print(json.dumps({"meta": out["report"].get("meta"), "exports": out["exports"]}, indent=2, default=str))
        return 0

    if args.cmd == "batch-holdings":
        stale = args.stale_days if args.stale_days > 0 else None
        out = generate_holding_prospectus_batch(
            force=args.force,
            grok_edit=not args.no_grok,
            limit=args.limit,
            stale_days=stale,
        )
        print(json.dumps(out, indent=2, default=str))
        return 0 if out.get("ok") else 1

    if args.cmd == "batch-watchlist":
        out = generate_watchlist_prospectus_batch(
            force=args.force,
            grok_edit=not args.no_grok,
            limit=args.limit,
        )
        print(json.dumps(out, indent=2, default=str))
        return 0 if out.get("ok") else 1

    if args.cmd == "registry":
        out = registry_list(symbol=args.symbol, report_type=args.type)
        print(json.dumps(out, indent=2, default=str))
        return 0

    if args.cmd == "scheduled":
        fmts = ["docx", "pdf"] if args.format == "all" else [args.format]
        out = generate_scheduled(args.kind, formats=fmts)
        print(json.dumps({"exports": out["exports"]}, indent=2, default=str))
        return 0

    if args.cmd == "republish-canonical":
        out = republish_canonical_from_registry(report_type=args.type)
        print(json.dumps(out, indent=2, default=str))
        return 0 if out.get("ok") else 1

    if args.cmd == "autonomous":
        out = run_autonomous_cycle(
            mode=args.mode,
            force=args.force,
            grok_edit=not args.no_grok,
            limit=args.limit,
        )
        print(json.dumps(out, indent=2, default=str))
        return 0 if out.get("ok") else 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())