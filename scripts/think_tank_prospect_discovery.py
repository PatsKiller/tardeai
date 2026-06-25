"""think_tank_prospect_discovery.py — Continuous prospect + watchlist discovery for Hermes.

Turns mined signals (RS/RSI leaders, research clusters, intel mentions) into staged
directive hits and watchlist_items via the governed promotion pipeline.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "bin" / "python")


def _classified_symbols(cur) -> set[str]:
    cur.execute("SELECT DISTINCT UPPER(symbol) FROM ticker_strategy_classifications WHERE active = true")
    return {r[0] for r in cur.fetchall() if r[0]}


def mine_signal_prospects(conn, signals: dict, *, max_prospects: int = 12) -> list[dict]:
    """Prospects from RS/RSI clusters and Hermes research symbol hits.

    New symbols are discovered normally. Held + watchlist names are re-mined as refresh
    prospects with portfolio priority boosts so catalyst updates reach staging.
    """
    from momentum_scalp_lead_miner import load_portfolio_priority

    cur = conn.cursor()
    priority = load_portfolio_priority(conn)
    classified = _classified_symbols(cur)
    prospects: list[dict] = []
    seen: set[str] = set()

    def _add(sym: str, thesis: str, strength: float, source: str, sector: str = ""):
        s = str(sym or "").upper()
        if not re.match(r"^[A-Z]{1,5}$", s) or s in seen:
            return

        is_held = s in priority.get("held", ())
        on_watchlist = s in priority.get("known_watchlist", ())
        refresh = is_held or on_watchlist
        if not refresh and s in classified:
            return

        boost = 0.0
        tags: list[str] = []
        if is_held:
            boost += 0.15
            tags.append("held")
        if s in priority.get("watchlist_directive", ()):
            boost += 0.05
            tags.append("directive_watch")
        if s in priority.get("watchlist_active", ()):
            boost += 0.08
            tags.append("active_watchlist")
        elif s in priority.get("watchlist_buy", ()):
            boost += 0.05
            tags.append("buy_rated")

        seen.add(s)
        prospects.append({
            "symbol": s,
            "thesis": (f"[refresh] {thesis}" if refresh else thesis)[:120],
            "strength": round(min(1.0, max(0.3, strength + boost)), 2),
            "source": source,
            "sector": sector or "",
            "refresh": refresh,
            "priority_tags": tags,
        })

    rs = signals.get("rs_rsi") or {}
    for r in (rs.get("weekly_rs_leaders") or [])[:10]:
        pw = r.get("perf_week_pct") or 0
        _add(
            r["symbol"],
            f"Weekly RS leader {pw:+.1f}% (RSI {r.get('rsi', 0):.0f})",
            pw / 50.0,
            "rs_weekly_leader",
            r.get("sector") or "",
        )
    for r in (rs.get("rsi_momentum") or [])[:6]:
        _add(
            r["symbol"],
            f"RSI momentum thrust {r.get('rsi', 0):.0f} / 1W {r.get('perf_week_pct', 0):+.1f}%",
            0.65,
            "rsi_momentum",
            r.get("sector") or "",
        )
    for r in (rs.get("rsi_oversold_bounce") or [])[:6]:
        _add(
            r["symbol"],
            f"RSI oversold bounce RSI {r.get('rsi', 0):.0f} / 1W {r.get('perf_week_pct', 0):+.1f}%",
            0.55,
            "rsi_oversold_bounce",
            r.get("sector") or "",
        )
    for cluster in (rs.get("sector_rs") or [])[:4]:
        sec = cluster.get("sector") or ""
        for sym in (cluster.get("leaders") or [])[:4]:
            _add(sym, f"{sec} sector RS cluster leader", 0.6, "sector_rs_cluster", sec)

    for row in signals.get("hermes_research") or []:
        theme = str(row.get("theme") or "")
        if theme.lower() in ("earnings", "news momentum", "youtube discovery", "regulatory"):
            continue
        for sym in (row.get("symbols") or [])[:6]:
            _add(sym, f"Hermes research: {theme} ({row.get('count', 0)} rows)", 0.5, "hermes_research", "")

    def _sort_key(p: dict):
        tags = p.get("priority_tags") or []
        tier = 0 if "held" in tags else 1 if tags else 2
        return (tier, -float(p.get("strength") or 0))

    prospects.sort(key=_sort_key)
    return prospects[:max_prospects]


def _load_directives(cur) -> list[dict]:
    cur.execute(
        """SELECT id, kind, label, spec FROM watch_directives
           WHERE status = 'active' AND hermes_enabled = true AND kind IN ('trend', 'sector')"""
    )
    out = []
    for did, kind, label, spec in cur.fetchall():
        s = spec if isinstance(spec, dict) else json.loads(spec or "{}")
        out.append({"id": did, "kind": kind, "label": label, "spec": s})
    return out


def _pick_directive(directives: list[dict], prospect: dict) -> int | None:
    sec = (prospect.get("sector") or "").strip()
    src = prospect.get("source") or ""
    # Sector RS / sector cluster → matching sector directive
    if sec:
        for d in directives:
            if d["kind"] != "sector":
                continue
            spec = d["spec"]
            if spec.get("gics_sector") == sec or spec.get("finviz_sector") == sec:
                return d["id"]
            if sec.lower() in (d["label"] or "").lower():
                return d["id"]
    # Industry-matched prospects → industry sub-sector directive
    ind = (prospect.get("industry") or prospect.get("finviz_industry") or "").strip()
    if ind:
        for d in directives:
            spec = d["spec"]
            if spec.get("finviz_industry") == ind:
                return d["id"]
            if ind.lower() in (d["label"] or "").lower():
                return d["id"]
    # RS leaders → weekly RS or small-cap rotation trend
    if src.startswith("rs") or src.startswith("rsi"):
        for d in directives:
            lbl = (d["label"] or "").lower()
            if "rs" in lbl or "momentum" in lbl or "rotation" in lbl:
                return d["id"]
    # Research cluster → keyword overlap
    thesis = (prospect.get("thesis") or "").lower()
    for d in directives:
        kws = [str(k).lower() for k in (d["spec"].get("keywords") or [])]
        if any(k in thesis for k in kws if len(k) > 4):
            return d["id"]
    # Seed symbols match
    sym = prospect.get("symbol")
    for d in directives:
        seeds = [str(s).upper() for s in (d["spec"].get("seed_symbols") or [])]
        if sym in seeds:
            return d["id"]
    # Fallback: first think_tank trend
    for d in directives:
        if d["kind"] == "trend" and "think_tank" in str(d["spec"].get("think_tank_source") or ""):
            return d["id"]
    return directives[0]["id"] if directives else None


def stage_signal_prospects(
    conn,
    prospects: list[dict],
    *,
    apply: bool,
    max_stage: int = 8,
) -> dict:
    """Stage mined prospects into hermes_directive_hits_staging for governed promotion."""
    if not prospects:
        return {"staged": 0, "skipped": 0, "detail": []}

    cur = conn.cursor()
    directives = _load_directives(cur)
    if not directives:
        return {"staged": 0, "skipped": len(prospects), "detail": [], "note": "no_active_directives"}

    staged = 0
    detail = []
    for p in prospects[:max_stage]:
        did = _pick_directive(directives, p)
        if not did:
            continue
        sym = p["symbol"]
        cur.execute(
            """SELECT 1 FROM hermes_directive_hits_staging
               WHERE directive_id=%s AND symbol=%s AND drained=false LIMIT 1""",
            (did, sym),
        )
        if cur.fetchone():
            continue
        cur.execute(
            """SELECT 1 FROM watch_directive_hits
               WHERE directive_id=%s AND symbol=%s AND surfaced_at > now() - interval '24 hours' LIMIT 1""",
            (did, sym),
        )
        if cur.fetchone():
            continue
        if apply:
            cur.execute(
                """INSERT INTO hermes_directive_hits_staging
                   (directive_id, symbol, thesis, narrative_strength, source_detail)
                   VALUES (%s, %s, %s, %s, %s::jsonb)""",
                (
                    did,
                    sym,
                    p["thesis"],
                    p["strength"],
                    json.dumps({
                        "producer": "think_tank_prospect_discovery",
                        "source": p["source"],
                        "sector": p.get("sector"),
                        "refresh": p.get("refresh", False),
                        "priority_tags": p.get("priority_tags") or [],
                    }),
                ),
            )
        staged += 1
        detail.append({"symbol": sym, "directive_id": did, "source": p["source"]})
    if apply and staged:
        conn.commit()
    return {"staged": staged, "skipped": len(prospects) - staged, "detail": detail[:10]}


def run_intel_discovery(*, apply: bool, max_add: int = 3) -> dict:
    """Scan news/YT/social for unknown tickers → watchlist_items."""
    try:
        from intel_auto_discovery import scan_for_discoveries, add_discoveries_to_watchlist
    except Exception as e:
        return {"added": 0, "error": str(e)[:80]}

    discoveries = scan_for_discoveries(days=2, min_mentions=2)
    if not discoveries:
        return {"found": 0, "added": 0}
    discoveries = discoveries[:max_add]
    if apply:
        result = add_discoveries_to_watchlist(discoveries, dry_run=False)
        return {"found": len(discoveries), "added": result.get("added", 0), "symbols": [d["symbol"] for d in discoveries]}
    return {"found": len(discoveries), "added": 0, "dry_run": [d["symbol"] for d in discoveries]}


def _run_script(script: str, args: list[str], timeout: int = 600) -> dict:
    try:
        r = subprocess.run(
            [PY, str(ROOT / "scripts" / script)] + args,
            cwd=str(ROOT), capture_output=True, text=True, timeout=timeout,
        )
        tail = (r.stdout or r.stderr or "").strip()
        parsed = None
        if tail:
            try:
                parsed = json.loads(tail if tail.startswith("{") else tail.splitlines()[-1])
            except Exception:
                parsed = {"tail": tail[-300:]}
        return {"ok": r.returncode == 0, "exit": r.returncode, "result": parsed}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def run_prospect_pipeline(
    conn,
    signals: dict,
    *,
    apply: bool,
    skip_watchlist_drain: bool,
    max_prospects_stage: int = 6,
    max_intel_discover: int = 3,
    directive_discovery_limit: int = 4,
    max_scalp_mine: int = 24,
    max_scalp_stage: int = 8,
) -> dict:
    """Full prospect → staging → watchlist pipeline for one curator tick."""
    from momentum_scalp_lead_miner import run_scalp_lead_pipeline

    prospects = mine_signal_prospects(conn, signals, max_prospects=max_prospects_stage * 2)
    staged = stage_signal_prospects(conn, prospects, apply=apply, max_stage=max_prospects_stage)

    report = {
        "prospects_mined": len(prospects),
        "signal_staging": staged,
        "scalp_leads": run_scalp_lead_pipeline(
            conn,
            signals,
            apply=apply,
            max_mine=max_scalp_mine,
            max_stage=max_scalp_stage,
        ),
        "intel_discovery": run_intel_discovery(apply=apply, max_add=max_intel_discover),
        "directive_discovery": _run_script(
            "hermes_directive_discovery.py",
            ["--apply", "--limit-per-directive", str(directive_discovery_limit)] if apply
            else ["--limit-per-directive", str(directive_discovery_limit)],
        ),
        "watchlist_drain": {},
    }

    if apply and not skip_watchlist_drain:
        report["watchlist_drain"] = _run_script(
            "watch_directives_service.py",
            ["--apply", "--max-hermes-drain", "5"],
            timeout=600,
        )
        drain = (report["watchlist_drain"].get("result") or {})
        report["promoted_to_watchlist"] = drain.get("promoted", 0)
        report["staged_for_review"] = drain.get("staged", 0)
        report["hermes_drained"] = drain.get("hermes_drained", 0)
    else:
        report["promoted_to_watchlist"] = 0
        report["staged_for_review"] = 0
        report["hermes_drained"] = 0

    report["updated_at"] = datetime.now(timezone.utc).isoformat()
    return report