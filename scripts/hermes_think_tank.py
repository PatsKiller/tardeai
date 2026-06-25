#!/usr/bin/env python3
"""hermes_think_tank.py — Deep synthesis pass (trends + sector rotations → prospects).

Continuous 24/7 curation runs via hermes_research_curator.py on every coordinator tick.
This script is the deeper scheduled pass (cron 2x/day weekdays + --force-deep curator).

No operator step. Each run:
  1. Cleans orphan Hermes directive staging (archived directives — the 521-hit stall).
  2. Mines multi-source signals: Hermes research, RSS/news, catalyst API, web (SearXNG),
     RS/RSI leaders, and new-site candidates (registered into research_sources).
  3. Reads Finviz sector RS + IWM/SPY style rotation signals.
  4. Synthesizes emerging themes (LLM over full signal bundle, then rules).
  5. Upserts watch_directives (trend/sector) + enhances keywords/seeds.
  6. Runs Hermes directive discovery + watch_directives_service drain.
  7. Optionally nudges rotation_autopilot when style rotation is active.

Usage:
    python scripts/hermes_think_tank.py [--apply] [--max-themes N] [--skip-drain]
        [--skip-web] [--skip-llm] [--skip-sites]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
AUDIT = ROOT / "data" / "runtime" / "think_tank_latest.json"
PY = str(ROOT / ".venv" / "bin" / "python")

SECTOR_ETF = {
    "Technology": "XLK", "Financial": "XLF", "Financials": "XLF", "Energy": "XLE",
    "Healthcare": "XLV", "Consumer Cyclical": "XLY", "Consumer Disc.": "XLY",
    "Industrials": "XLI", "Consumer Defensive": "XLP", "Consumer Stapl.": "XLP",
    "Utilities": "XLU", "Real Estate": "XLRE", "Basic Materials": "XLB",
    "Materials": "XLB", "Communication Services": "XLC", "Comm. Services": "XLC",
}
LEADER_MIN_PCT = 0.75
LAGGARD_MAX_PCT = -0.75
MAX_THEMES_DEFAULT = 10


def _env():
    for ln in (ROOT / ".env").read_text().splitlines():
        if "=" in ln and not ln.strip().startswith("#"):
            k, _, v = ln.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def _db():
    import psycopg2
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def _norm_label(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def cleanup_orphan_staging(conn, *, apply: bool) -> int:
    """Drain staging rows tied to non-active directives (root cause of STALLED monitor)."""
    cur = conn.cursor()
    cur.execute(
        """SELECT count(*) FROM hermes_directive_hits_staging h
           JOIN watch_directives d ON d.id = h.directive_id
           WHERE h.drained = false AND d.status <> 'active'"""
    )
    n = cur.fetchone()[0] or 0
    if apply and n:
        cur.execute(
            """UPDATE hermes_directive_hits_staging h
               SET drained = true, drained_at = NOW()
               FROM watch_directives d
               WHERE h.directive_id = d.id AND h.drained = false AND d.status <> 'active'"""
        )
        conn.commit()
    return n


def fetch_sector_snapshot(conn) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT max(snapshot_date) FROM finviz_group_performance")
    latest = cur.fetchone()[0]
    if not latest:
        return {"snapshot_date": None, "sectors": [], "leaders": [], "laggards": []}
    cur.execute(
        """SELECT name, change_pct FROM finviz_group_performance
           WHERE snapshot_date=%s AND group_type='sector'
           ORDER BY change_pct DESC NULLS LAST""",
        (latest,),
    )
    sectors = [{"name": r[0], "change_pct": float(r[1]) if r[1] is not None else None} for r in cur.fetchall()]
    leaders = [s for s in sectors if (s["change_pct"] or 0) >= LEADER_MIN_PCT][:3]
    laggards = [s for s in reversed(sectors) if (s["change_pct"] or 0) <= LAGGARD_MAX_PCT][:3]
    return {"snapshot_date": str(latest), "sectors": sectors, "leaders": leaders, "laggards": laggards}


def fetch_style_rotation() -> dict:
    try:
        from market_rotation_signals import detect_small_cap_rotation
        return detect_small_cap_rotation()
    except Exception as e:
        return {"signal": None, "error": str(e)[:120]}


def _rule_themes(sector_snap: dict, style: dict) -> list[dict]:
    themes = []
    for s in sector_snap.get("leaders") or []:
        name = s["name"]
        pct = s.get("change_pct")
        etf = SECTOR_ETF.get(name, "")
        themes.append({
            "kind": "sector",
            "label": f"sector {name} leadership",
            "rationale": f"Finviz sector RS leader ({pct:+.2f}% on {sector_snap.get('snapshot_date')})",
            "spec": {
                "finviz_sector": name,
                "gics_sector": name,
                "etf": etf,
                "keywords": [f"{name} sector rotation", f"{name} relative strength", "sector leadership"],
                "think_tank_source": "finviz_sector_leader",
            },
        })
    for s in sector_snap.get("laggards") or []:
        name = s["name"]
        pct = s.get("change_pct")
        themes.append({
            "kind": "trend",
            "label": f"trend Rotation out of {name}",
            "rationale": f"Finviz sector laggard ({pct:+.2f}%) — watch rotation beneficiaries",
            "spec": {
                "keywords": [f"rotation out of {name}", f"{name} sector weakness", "sector rotation"],
                "think_tank_source": "finviz_sector_laggard",
            },
        })
    if style.get("signal") == "small_cap_outperform":
        themes.append({
            "kind": "trend",
            "label": "trend Small/mid-cap rotation vs megacaps",
            "rationale": f"Style rotation: {style.get('explain', 'IWM vs SPY')}",
            "spec": {
                "keywords": ["small cap rotation", "Russell 2000 relative strength", "mid-cap rotation",
                             "IWM vs SPY"],
                "seed_symbols": ["IWM", "IWN", "IWO"],
                "think_tank_source": "style_rotation",
            },
        })
    return themes


def _merge_themes(*theme_lists: list[dict]) -> list[dict]:
    """Dedupe by (kind, normalized label); earlier lists win."""
    seen: set[tuple[str, str]] = set()
    merged: list[dict] = []
    for themes in theme_lists:
        for t in themes:
            key = (t["kind"], _norm_label(t["label"]))
            if key in seen:
                continue
            seen.add(key)
            merged.append(t)
    return merged


def _find_existing(cur, theme: dict) -> int | None:
    kind = theme["kind"]
    norm = _norm_label(theme["label"])
    cur.execute(
        """SELECT id, label FROM watch_directives
           WHERE kind=%s AND status='active'""",
        (kind,),
    )
    for did, lbl in cur.fetchall():
        if _norm_label(lbl) == norm:
            return did
    if kind == "sector":
        sec = (theme.get("spec") or {}).get("finviz_sector")
        if sec:
            cur.execute(
                """SELECT id FROM watch_directives
                   WHERE kind='sector' AND status='active'
                     AND (spec->>'finviz_sector'=%s OR spec->>'gics_sector'=%s)
                   LIMIT 1""",
                (sec, sec),
            )
            row = cur.fetchone()
            if row:
                return row[0]
    return None


def upsert_themes(conn, themes: list[dict], *, apply: bool, max_themes: int) -> list[dict]:
    from directive_keyword_enhancer import enhance

    cur = conn.cursor()
    results = []
    for theme in themes[:max_themes]:
        existing = _find_existing(cur, theme)
        spec = dict(theme.get("spec") or {})
        if not spec.get("keywords"):
            enh = enhance(theme["label"], theme["kind"])
            spec["keywords"] = enh.get("keywords") or []
            if enh.get("seed_symbols"):
                spec.setdefault("seed_symbols", enh["seed_symbols"])
            spec["keywords_source"] = f"think_tank:{enh.get('lane', 'rules')}"

        action = "updated" if existing else "created"
        did = existing
        if apply:
            if existing:
                cur.execute("SELECT spec FROM watch_directives WHERE id=%s", (existing,))
                old = cur.fetchone()[0]
                if isinstance(old, str):
                    old = json.loads(old)
                merged = dict(old or {})
                for k, v in spec.items():
                    if k == "keywords":
                        merged[k] = list(dict.fromkeys((merged.get(k) or []) + v))[:14]
                    elif k == "seed_symbols":
                        merged[k] = list(dict.fromkeys((merged.get(k) or []) + v))[:12]
                    else:
                        merged[k] = v
                merged["think_tank_refreshed_at"] = datetime.now(timezone.utc).isoformat()
                cur.execute(
                    "UPDATE watch_directives SET spec=%s::jsonb, rationale=%s, updated_at=NOW() WHERE id=%s",
                    (json.dumps(merged), theme.get("rationale"), existing),
                )
            else:
                cur.execute(
                    """INSERT INTO watch_directives
                       (kind, label, spec, rationale, created_by, status, priority,
                        trade_ai_enabled, hermes_enabled, ttl_days)
                       VALUES (%s,%s,%s::jsonb,%s,'think_tank','active','normal',true,true,90)
                       RETURNING id""",
                    (theme["kind"], theme["label"][:120], json.dumps(spec), theme.get("rationale")),
                )
                did = cur.fetchone()[0]
                action = "created"
        results.append({"action": action, "id": did, "kind": theme["kind"], "label": theme["label"]})
    if apply:
        conn.commit()
    return results


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


def run_think_tank(
    *,
    apply: bool,
    max_themes: int,
    skip_drain: bool,
    skip_web: bool = False,
    skip_llm: bool = False,
    skip_sites: bool = False,
    max_site_register: int = 12,
) -> dict:
    _env()
    conn = _db()

    from think_tank_signal_miner import (
        llm_themes_from_signals,
        mine_all_signals,
        auto_activate_discovered_sites,
        refresh_site_candidate_hits,
        register_site_candidates,
        themes_from_rs_rsi,
        themes_from_signals,
    )

    orphans = cleanup_orphan_staging(conn, apply=apply)
    signals = mine_all_signals(conn, skip_web=skip_web)
    sector_snap = fetch_sector_snapshot(conn)
    style = fetch_style_rotation()

    llm_themes = [] if skip_llm else llm_themes_from_signals(signals, sector_snap, style)
    rs_themes = themes_from_rs_rsi(signals.get("rs_rsi") or {})
    signal_themes = themes_from_signals(signals)
    rule_themes = _rule_themes(sector_snap, style)
    themes = _merge_themes(llm_themes, rs_themes, signal_themes, rule_themes)

    site_registration = {"registered": 0, "skipped": 0, "sample": []}
    site_activation = {"activated": 0, "sample": []}
    if apply and not skip_sites:
        candidates = signals.get("site_candidates") or []
        site_registration = register_site_candidates(
            conn, candidates, apply=True,
            max_register=max_site_register,
        )
        refresh_site_candidate_hits(conn, candidates, apply=True)
        site_activation = auto_activate_discovered_sites(conn, apply=True)

    upserted = upsert_themes(conn, themes, apply=apply, max_themes=max_themes)

    drain_report = {}
    if apply and not skip_drain:
        drain_report["discovery"] = _run_script(
            "hermes_directive_discovery.py",
            ["--apply", "--limit-per-directive", "12"],
        )
        drain_report["directives_service"] = _run_script(
            "watch_directives_service.py",
            ["--apply"],
        )
        if style.get("signal") == "small_cap_outperform":
            drain_report["rotation_autopilot"] = _run_script(
                "rotation_autopilot.py",
                ["--tick", "--force-bridge"],
                timeout=300,
            )

    conn.close()
    report = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if apply else "dry-run",
        "orphans_cleaned": orphans,
        "signals": signals,
        "sector_snapshot": sector_snap,
        "style_rotation": style,
        "site_registration": site_registration,
        "site_activation": site_activation,
        "site_candidates_found": len(signals.get("site_candidates") or []),
        "themes_by_source": {
            "llm_signals": len(llm_themes),
            "rs_rsi": len(rs_themes),
            "mined_rules": len(signal_themes),
            "finviz_style_rules": len(rule_themes),
        },
        "themes_proposed": len(themes),
        "themes_upserted": upserted,
        "drain": drain_report,
    }
    if apply:
        AUDIT.write_text(json.dumps(report, indent=2, default=str))
    return report


def main():
    parser = argparse.ArgumentParser(description="Hermes autonomous macro think tank")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-themes", type=int, default=MAX_THEMES_DEFAULT)
    parser.add_argument("--skip-drain", action="store_true", help="Skip discovery + directive drain steps")
    parser.add_argument("--skip-web", action="store_true", help="Skip SearXNG web probe (faster light pass)")
    parser.add_argument("--skip-llm", action="store_true", help="Skip LLM synthesis; use mined + finviz rules only")
    parser.add_argument("--skip-sites", action="store_true", help="Skip registering new web domains into research_sources")
    args = parser.parse_args()
    report = run_think_tank(
        apply=args.apply,
        max_themes=args.max_themes,
        skip_drain=args.skip_drain,
        skip_web=args.skip_web,
        skip_llm=args.skip_llm,
        skip_sites=args.skip_sites,
    )
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())