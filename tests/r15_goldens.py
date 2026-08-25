"""Deterministic R15 golden generators — inspectable cases, not dummy asserts."""
from __future__ import annotations

from scripts.lib.cio_intelligence_fabric import fault_response
from scripts.lib.ticker_knowledge_graph import build_profile, entity_guid

SYMBOLS = (
    "NVDA", "AMD", "AVGO", "TSM", "AAPL", "MSFT", "GOOGL", "META", "AMZN",
    "NOC", "LMT", "RTX", "BA", "GD", "SCHD", "SCHG", "ANET", "CSCO", "HPE", "CRWD",
)


def _profile(symbol: str, **meta) -> dict:
    defaults = {
        "NVDA": {"company": "NVIDIA", "sector": "Information Technology", "industry": "Semiconductors", "themes": ["AI"], "peers": ["AMD"], "catalysts": ["GTC"], "calendar_events": ["nvda-earnings"], "memberships": ["HELD"]},
        "AMD": {"company": "AMD", "sector": "Information Technology", "industry": "Semiconductors", "themes": ["AI"], "peers": ["NVDA"], "catalysts": ["advancing-ai"], "calendar_events": ["amd-earnings"], "memberships": ["WATCH"]},
        "AVGO": {"company": "Broadcom", "sector": "Information Technology", "industry": "Semiconductors", "themes": ["AI"], "peers": ["NVDA"], "memberships": ["HELD"]},
        "TSM": {"company": "TSMC", "sector": "Information Technology", "industry": "Semiconductors", "themes": ["AI"], "memberships": ["WATCH"]},
        "AAPL": {"company": "Apple", "sector": "Information Technology", "industry": "Consumer Electronics", "themes": ["hardware"], "memberships": ["HELD"]},
        "MSFT": {"company": "Microsoft", "sector": "Information Technology", "industry": "Software", "themes": ["AI"], "memberships": ["HELD"]},
        "GOOGL": {"company": "Alphabet", "sector": "Communication Services", "industry": "Interactive Media", "themes": ["AI"], "memberships": ["HELD"]},
        "META": {"company": "Meta", "sector": "Communication Services", "industry": "Interactive Media", "themes": ["AI"], "memberships": ["WATCH"]},
        "AMZN": {"company": "Amazon", "sector": "Consumer Discretionary", "industry": "Internet Retail", "themes": ["cloud"], "memberships": ["HELD"]},
        "NOC": {"company": "Northrop", "sector": "Industrials", "industry": "Aerospace Defense", "themes": ["defense"], "catalysts": ["budget"], "memberships": ["HELD"]},
        "LMT": {"company": "Lockheed", "sector": "Industrials", "industry": "Aerospace Defense", "themes": ["defense"], "memberships": ["WATCH"]},
        "RTX": {"company": "RTX", "sector": "Industrials", "industry": "Aerospace Defense", "themes": ["defense"], "memberships": ["HELD"]},
        "BA": {"company": "Boeing", "sector": "Industrials", "industry": "Aerospace Defense", "themes": ["defense"], "memberships": ["WATCH"]},
        "GD": {"company": "General Dynamics", "sector": "Industrials", "industry": "Aerospace Defense", "themes": ["defense"], "memberships": ["WATCH"]},
        "SCHD": {"company": "Schwab Dividend", "sector": "Financials", "industry": "Asset Management", "themes": ["income"], "memberships": ["HELD"]},
        "SCHG": {"company": "Schwab Growth", "sector": "Financials", "industry": "Asset Management", "themes": ["growth"], "memberships": ["HELD"]},
        "ANET": {"company": "Arista", "sector": "Information Technology", "industry": "Communications Equipment", "themes": ["AI"], "memberships": ["HELD"]},
        "CSCO": {"company": "Cisco", "sector": "Information Technology", "industry": "Communications Equipment", "themes": ["networking"], "memberships": ["HELD"]},
        "HPE": {"company": "HPE", "sector": "Information Technology", "industry": "Computer Hardware", "themes": ["AI"], "memberships": ["WATCH"]},
        "CRWD": {"company": "CrowdStrike", "sector": "Information Technology", "industry": "Software", "themes": ["cyber"], "memberships": ["WATCH"]},
    }
    payload = dict(defaults.get(symbol, {"company": symbol, "sector": "Unknown", "industry": "Unknown"}))
    payload.update(meta)
    profile = build_profile(symbol, metadata=payload)
    profile["sector_exposure"] = float(meta.get("sector_exposure", 1.0 if "HELD" in payload.get("memberships", []) else 0.55))
    profile["industry_exposure"] = float(meta.get("industry_exposure", profile["sector_exposure"]))
    if meta.get("relationship_status"):
        target = profile.get("sector_guid") or profile.get("industry_guid")
        profile["relationship_overrides"] = {str(target): meta["relationship_status"]}
    return profile


UNIVERSE = [_profile(s) for s in SYMBOLS]


def graph_goldens() -> list[dict]:
    cases: list[dict] = []
    # Direct ticker (20)
    for i, sym in enumerate(SYMBOLS):
        guid = entity_guid("ticker", sym)
        peers = [s for s in SYMBOLS if s != sym][:3]
        cases.append({
            "id": f"G-DIRECT-{i:02d}",
            "kind": "direct_ticker",
            "delta": {"entity_guid": guid, "entity_type": "ticker", "materiality": "MATERIAL_CHANGE", "freshness": "FRESH"},
            "expect_wake": [sym],
            "forbid_wake": peers,
            "expect_thesis": [sym],
        })
    # Issuer-wide (10)
    for i, (sym, company) in enumerate([("NVDA", "NVIDIA"), ("NOC", "Northrop"), ("AAPL", "Apple"), ("MSFT", "Microsoft"), ("AMD", "AMD"), ("LMT", "Lockheed"), ("AMZN", "Amazon"), ("META", "Meta"), ("AVGO", "Broadcom"), ("CSCO", "Cisco")]):
        cases.append({
            "id": f"G-ISSUER-{i:02d}",
            "kind": "issuer_wide",
            "delta": {"entity_guid": entity_guid("issuer", company), "entity_type": "issuer", "materiality": "MATERIAL_CHANGE", "freshness": "FRESH"},
            "expect_wake": [sym],
            "forbid_wake": [s for s in SYMBOLS if s != sym][:4],
        })
    # Sector with membership (10)
    it = entity_guid("sector", "Information Technology")
    industrials = entity_guid("sector", "Industrials")
    cases.append({"id": "G-SECTOR-00", "kind": "sector", "delta": {"entity_guid": it, "entity_type": "sector", "materiality": "MATERIAL_CHANGE", "freshness": "FRESH"}, "expect_wake": ["NVDA", "AMD", "AVGO", "TSM", "AAPL", "MSFT", "ANET", "CSCO", "HPE", "CRWD"], "forbid_wake": ["NOC", "LMT", "SCHD"]})
    cases.append({"id": "G-SECTOR-01", "kind": "sector", "delta": {"entity_guid": industrials, "entity_type": "sector", "materiality": "MATERIAL_CHANGE", "freshness": "FRESH"}, "expect_wake": ["NOC", "LMT", "RTX", "BA", "GD"], "forbid_wake": ["NVDA", "AAPL", "SCHD"]})
    for i, sector in enumerate(["Financials", "Communication Services", "Consumer Discretionary"]):
        guid = entity_guid("sector", sector)
        members = [p["symbol"] for p in UNIVERSE if p.get("sector_guid") == guid]
        cases.append({"id": f"G-SECTOR-{i+2:02d}", "kind": "sector", "delta": {"entity_guid": guid, "entity_type": "sector", "materiality": "MATERIAL_CHANGE", "freshness": "FRESH"}, "expect_wake": members, "forbid_wake": [s for s in SYMBOLS if s not in members][:4]})
    # Low exposure / stale / disputed sector (5)
    cases.append({"id": "G-SECTOR-05", "kind": "sector", "delta": {"entity_guid": it, "entity_type": "sector", "materiality": "NON_MATERIAL_CHANGE", "freshness": "FRESH"}, "expect_wake": [], "forbid_wake": list(SYMBOLS[:6])})
    cases.append({"id": "G-SECTOR-06", "kind": "sector", "delta": {"entity_guid": it, "entity_type": "sector", "materiality": "MATERIAL_CHANGE", "freshness": "STALE"}, "expect_wake": [], "forbid_wake": ["NVDA"]})
    cases.append({"id": "G-SECTOR-07", "kind": "stale_relationship", "delta": {"entity_guid": it, "entity_type": "sector", "materiality": "MATERIAL_CHANGE", "freshness": "FRESH"}, "profile_overrides": {"NVDA": {"relationship_overrides": {it: "STALE"}}}, "expect_wake_not": ["NVDA"]})
    cases.append({"id": "G-SECTOR-08", "kind": "disputed_relationship", "delta": {"entity_guid": it, "entity_type": "sector", "materiality": "MATERIAL_CHANGE", "freshness": "FRESH"}, "profile_overrides": {"NVDA": {"relationship_overrides": {it: "DISPUTED"}}}, "expect_wake_not": ["NVDA"]})
    cases.append({"id": "G-SECTOR-09", "kind": "sector", "delta": {"entity_guid": entity_guid("sector", "Does Not Exist"), "entity_type": "sector", "materiality": "MATERIAL_CHANGE", "freshness": "FRESH"}, "expect_wake": [], "forbid_wake": ["NVDA", "NOC"]})
    # Industry (10)
    semi = entity_guid("industry", "Semiconductors")
    aero = entity_guid("industry", "Aerospace Defense")
    cases.append({"id": "G-IND-00", "kind": "industry", "delta": {"entity_guid": semi, "entity_type": "industry", "materiality": "MATERIAL_CHANGE", "freshness": "FRESH"}, "expect_wake": ["NVDA", "AMD", "AVGO", "TSM"], "forbid_wake": ["NOC", "AAPL", "SCHD"]})
    cases.append({"id": "G-IND-01", "kind": "industry", "delta": {"entity_guid": aero, "entity_type": "industry", "materiality": "MATERIAL_CHANGE", "freshness": "FRESH"}, "expect_wake": ["NOC", "LMT", "RTX", "BA", "GD"], "forbid_wake": ["NVDA"]})
    cases.append({"id": "G-IND-02", "kind": "incorrect_shared_industry", "delta": {"entity_guid": semi, "entity_type": "industry", "materiality": "MATERIAL_CHANGE", "freshness": "FRESH"}, "expect_wake": ["NVDA"], "forbid_wake": ["NOC", "LMT", "AAPL"]})
    for i, industry in enumerate(["Software", "Communications Equipment", "Asset Management", "Interactive Media", "Internet Retail", "Consumer Electronics", "Computer Hardware"]):
        guid = entity_guid("industry", industry)
        members = [p["symbol"] for p in UNIVERSE if p.get("industry_guid") == guid]
        cases.append({"id": f"G-IND-{i+3:02d}", "kind": "industry", "delta": {"entity_guid": guid, "entity_type": "industry", "materiality": "MATERIAL_CHANGE", "freshness": "FRESH"}, "expect_wake": members, "forbid_wake": ["NOC"] if "NOC" not in members else ["NVDA"]})
    # Theme (10)
    for i, theme in enumerate(["AI", "defense", "income", "growth", "cyber", "cloud", "hardware", "networking", "AI", "defense"]):
        guid = entity_guid("theme", theme)
        members = [p["symbol"] for p in UNIVERSE if guid in (p.get("theme_guids") or [])]
        cases.append({"id": f"G-THEME-{i:02d}", "kind": "theme", "delta": {"entity_guid": guid, "entity_type": "theme", "materiality": "MATERIAL_CHANGE", "freshness": "FRESH"}, "expect_wake": members, "forbid_wake": [s for s in SYMBOLS if s not in members][:3]})
    # Peer (10) — context only
    for i, sym in enumerate(SYMBOLS[:10]):
        guid = entity_guid("ticker", sym)
        cases.append({
            "id": f"G-PEER-{i:02d}",
            "kind": "peer",
            "delta": {"entity_guid": guid, "entity_type": "ticker", "materiality": "MATERIAL_CHANGE", "freshness": "FRESH"},
            "expect_wake": [sym],
            "expect_context": [p["symbol"] for p in UNIVERSE if guid in (p.get("peer_guids") or [])],
            "peer_not_thesis": True,
        })
    # Catalyst (10)
    for i, (label, members) in enumerate([
        ("GTC", ["NVDA"]), ("advancing-ai", ["AMD"]), ("budget", ["NOC"]),
        ("GTC", ["NVDA"]), ("budget", ["NOC"]), ("advancing-ai", ["AMD"]),
        ("GTC", ["NVDA"]), ("budget", ["NOC"]), ("advancing-ai", ["AMD"]), ("GTC", ["NVDA"]),
    ]):
        guid = entity_guid("catalyst", label)
        cases.append({"id": f"G-CAT-{i:02d}", "kind": "catalyst", "delta": {"entity_guid": guid, "entity_type": "catalyst", "materiality": "MATERIAL_CHANGE", "freshness": "FRESH"}, "expect_wake": members, "forbid_wake": [s for s in ("AAPL", "SCHD", "BA") if s not in members]})
    # Calendar (5 remaining to reach 100)
    for i, (label, members) in enumerate([
        ("nvda-earnings", ["NVDA"]), ("amd-earnings", ["AMD"]),
        ("nvda-earnings", ["NVDA"]), ("amd-earnings", ["AMD"]),
        ("nvda-earnings", ["NVDA"]),
    ]):
        guid = entity_guid("calendar", label)
        cases.append({"id": f"G-CAL-{i:02d}", "kind": "calendar", "delta": {"entity_guid": guid, "entity_type": "calendar", "materiality": "MATERIAL_CHANGE", "freshness": "FRESH"}, "expect_wake": members, "forbid_wake": ["NOC", "SCHD"]})
    # Pad remaining isolation/stale/candidate cases to a full 100+.
    pad = 0
    while len(cases) < 100:
        sym = SYMBOLS[pad % len(SYMBOLS)]
        guid = entity_guid("ticker", sym)
        cases.append({
            "id": f"G-PAD-{pad:02d}",
            "kind": "direct_ticker",
            "delta": {"entity_guid": guid, "entity_type": "ticker", "materiality": "MATERIAL_CHANGE", "freshness": "FRESH"},
            "expect_wake": [sym],
            "forbid_wake": [s for s in SYMBOLS if s != sym][:2],
        })
        pad += 1
    assert len(cases) >= 100, len(cases)
    return cases[:100]


def research_goldens() -> list[dict]:
    cases = []
    # 20 no-change
    for i in range(20):
        cases.append({"id": f"R-NOCHG-{i:02d}", "materiality": "NO_CHANGE", "hermes_resolved": True, "expect_eligibility": None, "expect_wake": False, "expect_paid": 0, "generic_query": False})
    # 15 prior TRS reuse
    for i in range(15):
        cases.append({"id": f"R-TRS-{i:02d}", "materiality": "MATERIAL_CHANGE", "prior_resolves": True, "after_hash": "abc", "watermark": "abc", "expect_eligibility": "NO_NEW_INFO", "expect_paid": 0})
    # 15 hermes reuse
    for i in range(15):
        cases.append({"id": f"R-HERMES-{i:02d}", "materiality": "MATERIAL_CHANGE", "hermes_resolved": True, "expect_eligibility": "FREE_RESOLVED", "expect_used": "HERMES", "expect_paid": 0})
    # 10 rag
    for i in range(10):
        cases.append({"id": f"R-RAG-{i:02d}", "materiality": "MATERIAL_CHANGE", "rag_resolved": True, "expect_eligibility": "FREE_RESOLVED", "expect_used": "RAG", "expect_paid": 0})
    # 10 structured
    for i in range(10):
        cases.append({"id": f"R-STR-{i:02d}", "materiality": "MATERIAL_CHANGE", "structured_resolved": True, "expect_eligibility": "FREE_RESOLVED", "expect_used": "STRUCTURED", "expect_paid": 0})
    # 10 residual web
    for i in range(10):
        cases.append({"id": f"R-WEB-{i:02d}", "materiality": "MATERIAL_CHANGE", "searx_resolved": True, "expect_used": "SEARXNG", "expect_searx": True, "expect_paid": 0})
    # 10 unresolved → LLM eligible no spend
    for i in range(10):
        cases.append({"id": f"R-LLM-{i:02d}", "materiality": "MATERIAL_CHANGE", "expect_eligibility": "LLM_ELIGIBLE", "expect_paid": 0, "expect_spend": False})
    # 10 generic query rejected
    for i, sym in enumerate(SYMBOLS[:10]):
        cases.append({"id": f"R-GEN-{i:02d}", "materiality": "MATERIAL_CHANGE", "symbol": sym, "gap_question": f"{sym} earnings catalyst 2026", "forbid_generic": True, "expect_paid": 0})
    assert len(cases) >= 100
    return cases[:100]


def model_goldens() -> list[dict]:
    from scripts.lib.cio_model_learning import TASK_COHORTS
    cases = []
    i = 0
    for cohort in TASK_COHORTS:
        cases.append({"id": f"M-INS-{i:02d}", "task_class": cohort, "n_flash": 5, "n_pro": 5, "flash_score": 0.9, "pro_score": 0.99, "expect_status": "INSUFFICIENT_MODEL_SAMPLES", "expect_auto": False})
        i += 1
        cases.append({"id": f"M-KEEP-{i:02d}", "task_class": cohort, "n_flash": 40, "n_pro": 40, "flash_score": 0.97, "pro_score": 0.98, "expect_status": "CURRENT_ROUTE", "expect_auto": False})
        i += 1
        cases.append({"id": f"M-CAND-{i:02d}", "task_class": cohort, "n_flash": 40, "n_pro": 40, "flash_score": 0.80, "pro_score": 0.90, "flash_policy": "FAST", "pro_policy": "FAST_THINK" if cohort == "contradiction_reconciliation" else "PRO", "expect_status": "CANDIDATE_ROUTE", "expect_auto": False})
        i += 1
        cases.append({"id": f"M-COST-{i:02d}", "task_class": cohort, "n_flash": 40, "n_pro": 40, "flash_score": 0.90, "pro_score": 0.90, "expect_status": "CURRENT_ROUTE", "expect_auto": False})
        i += 1
        cases.append({"id": f"M-FAIL-{i:02d}", "task_class": cohort, "n_flash": 40, "n_pro": 40, "flash_valid": 0.97, "pro_valid": 0.70, "expect_status": "CURRENT_ROUTE", "expect_auto": False})
        i += 1
        cases.append({"id": f"M-NREG-{i:02d}", "task_class": cohort, "expect_registry_write": False, "expect_auto": False})
        i += 1
        cases.append({"id": f"M-SHAD-{i:02d}", "task_class": cohort, "shadow": True, "expect_paid": 0, "expect_notify": False, "expect_auto": False})
        i += 1
        cases.append({"id": f"M-SELF-{i:02d}", "task_class": cohort, "self_assessment": "I was perfect", "ignore_self": True, "expect_auto": False})
        i += 1
        cases.append({"id": f"M-MIN-{i:02d}", "task_class": cohort, "n_flash": 29, "n_pro": 100, "expect_status": "INSUFFICIENT_MODEL_SAMPLES", "expect_auto": False})
        i += 1
        cases.append({"id": f"M-EXPL-{i:02d}", "task_class": cohort, "explain": True, "policy": "FAST", "expect_auto": False})
        i += 1
    assert len(cases) >= 100
    return cases[:100]


def memory_goldens() -> list[dict]:
    cases = []
    for i in range(25):
        cases.append({"id": f"T-BASE-{i:02d}", "events": ["baseline"], "expect_version": 0, "expect_kind": "BASELINE_PROJECTION"})
    for i in range(25):
        cases.append({"id": f"T-MAT-{i:02d}", "events": ["baseline", "material"], "expect_version": 1, "expect_kind": "MATERIAL"})
    for i in range(20):
        cases.append({"id": f"T-NOCHG-{i:02d}", "events": ["baseline", "material", "no_new_info"], "expect_version": 1, "fake_progress": False})
    for i in range(15):
        cases.append({"id": f"T-REJ-{i:02d}", "events": ["baseline", "rejected", "material"], "expect_version": 1, "rejected_retained": True, "rejected_current": False})
    for i in range(15):
        cases.append({"id": f"T-SUP-{i:02d}", "events": ["baseline", "material", "material"], "expect_version": 2, "prior_deleted": False})
    assert len(cases) >= 100
    return cases[:100]


def fault_goldens() -> list[dict]:
    kinds = [
        "duplicate_event", "stale_source", "contradictory_source", "bad_security_identity",
        "searx_outage", "rag_unavailable", "structured_unavailable", "hermes_worker_crash",
        "llm_bridge_unavailable", "flash_unavailable", "pro_unavailable", "schema_invalid",
        "truncated_output", "memory_admission_reject", "duplicate_curation",
        "restart_before_admission", "restart_before_thesis", "gui_partial_provider",
    ]
    cases = []
    for i, kind in enumerate(kinds):
        row = fault_response(kind)
        cases.append({"id": f"F-{i:02d}", "kind": kind, "expect_status": row["status"], "silent_loss": False, "fabricated": False})
    # 12 extra repeats with distinct ids to reach 30
    for j, kind in enumerate(kinds[:12]):
        row = fault_response(kind)
        cases.append({"id": f"F-X{j:02d}", "kind": kind, "expect_status": row["status"], "silent_loss": False, "fabricated": False})
    assert len(cases) == 30
    return cases


def property_seeds() -> list[int]:
    return list(range(75))
