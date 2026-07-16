"""sector_research_universe.py — Full sector + industry (sub-sector) research coverage.

Ensures every Finviz sector (11) and industry (~144 sub-sectors) has an active
watch_directive and rotates Hermes topic research across the full universe.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "data" / "runtime" / "sector_universe_sync_state.json"
PY = str(ROOT / ".venv" / "bin" / "python")

SECTOR_ETF = {
    "Technology": "XLK", "Financial": "XLF", "Financials": "XLF", "Energy": "XLE",
    "Healthcare": "XLV", "Consumer Cyclical": "XLY", "Consumer Disc.": "XLY",
    "Industrials": "XLI", "Consumer Defensive": "XLP", "Consumer Stapl.": "XLP",
    "Utilities": "XLU", "Real Estate": "XLRE", "Basic Materials": "XLB",
    "Materials": "XLB", "Communication Services": "XLC", "Comm. Services": "XLC",
}

# Skip ETF pseudo-industries for equity sub-sector research
SKIP_INDUSTRY = frozenset({"exchange traded fund", "etf"})


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")[:44]


def fetch_group_snapshot(conn) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT max(snapshot_date) FROM finviz_group_performance")
    latest = cur.fetchone()[0]
    if not latest:
        return {"snapshot_date": None, "sectors": [], "industries": []}
    out = {"snapshot_date": str(latest), "sectors": [], "industries": []}
    for gtype, key in (("sector", "sectors"), ("industry", "industries")):
        cur.execute(
            """SELECT name, change_pct, stocks FROM finviz_group_performance
               WHERE snapshot_date=%s AND group_type=%s
               ORDER BY change_pct DESC NULLS LAST""",
            (latest, gtype),
        )
        out[key] = [
            {"name": r[0], "change_pct": float(r[1]) if r[1] is not None else None, "stocks": r[2] or 0}
            for r in cur.fetchall() if r[0]
        ]
    return out


def _industry_seeds(cur, industry: str, *, limit: int = 8) -> list[str]:
    cur.execute(
        """SELECT UPPER(symbol) FROM incubator_universe
           WHERE industry=%s AND symbol IS NOT NULL
           GROUP BY UPPER(symbol) ORDER BY UPPER(symbol) LIMIT %s""",
        (industry, limit),
    )
    return [r[0] for r in cur.fetchall() if r[0] and re.match(r"^[A-Z]{1,5}$", r[0])]


def build_universe_directives(snapshot: dict) -> list[dict]:
    """One directive per sector + one per industry (sub-sector)."""
    themes = []
    snap_date = snapshot.get("snapshot_date") or "latest"

    for s in snapshot.get("sectors") or []:
        name = s["name"]
        pct = s.get("change_pct")
        etf = SECTOR_ETF.get(name, "")
        themes.append({
            "kind": "sector",
            "label": f"sector {name}",
            "rationale": f"Full universe sector coverage — Finviz RS {pct:+.2f}% ({snap_date})",
            "spec": {
                "finviz_sector": name,
                "gics_sector": name,
                "etf": etf,
                "group_type": "sector",
                "change_pct": pct,
                "keywords": [name, f"{name} sector", f"{name} stocks", "sector rotation", "relative strength"],
                "think_tank_source": "sector_universe",
            },
        })

    for ind in snapshot.get("industries") or []:
        name = ind["name"]
        if (name or "").lower() in SKIP_INDUSTRY:
            continue
        pct = ind.get("change_pct")
        themes.append({
            "kind": "trend",
            "label": f"industry {name}",
            "rationale": f"Full universe sub-sector coverage — {name} RS {pct:+.2f}% ({snap_date})",
            "spec": {
                "finviz_industry": name,
                "group_type": "industry",
                "change_pct": pct,
                "stocks": ind.get("stocks"),
                "keywords": [name, f"{name} industry", f"{name} stocks", "sub-sector", "industry rotation"],
                "think_tank_source": "sector_universe_industry",
            },
        })
    return themes


def _load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except Exception:
            pass
    return {"offset": 0, "total": 0}


def _save_state(state: dict):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, default=str))


def _find_directive(cur, theme: dict) -> int | None:
    spec = theme.get("spec") or {}
    if theme["kind"] == "sector":
        sec = spec.get("finviz_sector")
        if not sec:
            return None
        cur.execute(
            """SELECT id FROM watch_directives
               WHERE kind='sector' AND status='active'
                 AND (spec->>'finviz_sector'=%s OR spec->>'gics_sector'=%s)
               LIMIT 1""",
            (sec, sec),
        )
    else:
        ind = spec.get("finviz_industry")
        if not ind:
            return None
        cur.execute(
            """SELECT id FROM watch_directives
               WHERE kind='trend' AND status='active' AND spec->>'finviz_industry'=%s
               LIMIT 1""",
            (ind,),
        )
    row = cur.fetchone()
    return row[0] if row else None


def sync_universe_batch(
    conn,
    snapshot: dict,
    *,
    apply: bool,
    batch_size: int = 12,
    research_queue: int = 3,
) -> dict:
    """Rotate through full sector+industry universe — upsert directives + queue topic research."""
    all_themes = build_universe_directives(snapshot)
    state = _load_state()
    state["total"] = len(all_themes)
    offset = int(state.get("offset") or 0) % max(len(all_themes), 1)
    batch = all_themes[offset: offset + batch_size]
    if len(batch) < batch_size and all_themes:
        batch += all_themes[: batch_size - len(batch)]

    cur = conn.cursor()
    created = updated = 0
    batch_detail = []
    for theme in batch:
        spec = dict(theme.get("spec") or {})
        if theme["kind"] == "trend" and spec.get("finviz_industry"):
            seeds = _industry_seeds(cur, spec["finviz_industry"])
            if seeds:
                spec["seed_symbols"] = seeds

        existing = _find_directive(cur, theme)
        action = "updated" if existing else "created"
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
                        merged[k] = list(dict.fromkeys((merged.get(k) or []) + (v or [])))[:12]
                    else:
                        merged[k] = v
                merged["sector_universe_refreshed_at"] = datetime.now(timezone.utc).isoformat()
                cur.execute(
                    "UPDATE watch_directives SET spec=%s::jsonb, rationale=%s, updated_at=NOW() WHERE id=%s",
                    (json.dumps(merged), theme.get("rationale"), existing),
                )
            else:
                # Watch Desk v2 (B1): family gate for trend-kind themes
                if theme["kind"] == "trend":
                    from lib.watch_directive_gate import family_gate, attach_alias
                    _g = family_gate(theme["label"], "trend")
                    if not _g["allow"]:
                        attach_alias(_g["survivor_id"], theme["label"][:120],
                                     rationale=theme.get("rationale"), created_by="sector_universe")
                        existing = _g["survivor_id"]
                        action = "aliased"
                        continue
                cur.execute(
                    """INSERT INTO watch_directives
                       (kind, label, spec, rationale, created_by, status, priority,
                        trade_ai_enabled, hermes_enabled, ttl_days)
                       VALUES (%s,%s,%s::jsonb,%s,'sector_universe','active','normal',true,true,180)
                       RETURNING id""",
                    (theme["kind"], theme["label"][:120], json.dumps(spec), theme.get("rationale")),
                )
                existing = cur.fetchone()[0]
            if action == "created":
                created += 1
            else:
                updated += 1
        batch_detail.append({"action": action, "kind": theme["kind"], "label": theme["label"][:80], "id": existing})

    topics_queued = _queue_topic_research(cur, batch[:research_queue], apply=apply)

    if apply:
        conn.commit()
    state["offset"] = (offset + batch_size) % max(len(all_themes), 1)
    state["last_sync_at"] = datetime.now(timezone.utc).isoformat()
    state["snapshot_date"] = snapshot.get("snapshot_date")
    state["sectors_total"] = len(snapshot.get("sectors") or [])
    state["industries_total"] = len(snapshot.get("industries") or [])
    if apply:
        _save_state(state)

    return {
        "universe_total": len(all_themes),
        "batch_offset": offset,
        "batch_size": len(batch),
        "created": created,
        "updated": updated,
        "topics_queued": topics_queued,
        "detail": batch_detail[:8],
        "coverage": {
            "sectors": state["sectors_total"],
            "industries": state["industries_total"],
        },
    }


def _queue_topic_research(cur, themes: list[dict], *, apply: bool) -> int:
    """Mirror sector/industry directives into topic_monitor for Hermes research pipeline."""
    cur.execute("SELECT topic_id FROM topic_monitor")
    existing = {r[0] for r in cur.fetchall()}
    queued = 0
    for theme in themes:
        spec = theme.get("spec") or {}
        name = spec.get("finviz_sector") or spec.get("finviz_industry") or ""
        if not name:
            continue
        gtype = spec.get("group_type") or "sector"
        topic_id = f"su_{gtype}_{_slug(name)}"
        if topic_id in existing:
            continue
        queries = (spec.get("keywords") or [])[:6] or [name, f"{name} stocks outlook 2026"]
        display = f"{gtype.title()}: {name}"
        if apply:
            cur.execute(
                """INSERT INTO topic_monitor
                   (topic_id, display_name, search_queries, priority, agent_owner, owner, enabled,
                    max_age_days, min_articles, personal_context)
                   VALUES (%s,%s,%s::jsonb,3,'Alex','shared',true,14,2,%s)
                   ON CONFLICT (topic_id) DO NOTHING""",
                (
                    topic_id,
                    display[:80],
                    json.dumps(queries),
                    f"Equity {gtype} research — {name}. Market/sector rotation context.",
                ),
            )
        queued += 1
        existing.add(topic_id)
    return queued


def ensure_finviz_snapshot(*, apply: bool) -> dict:
    """Refresh finviz_group_performance if missing or stale."""
    try:
        import psycopg2
        import os
        for ln in (ROOT / ".env").read_text().splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, _, v = ln.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            dbname=os.getenv("DB_NAME", "trade_ai"),
            user=os.getenv("DB_USER", "trade_ai"),
            password=os.getenv("DB_PASSWORD", ""),
        )
        cur = conn.cursor()
        cur.execute("SELECT max(snapshot_date) FROM finviz_group_performance")
        latest = cur.fetchone()[0]
        conn.close()
        stale = latest is None
        if latest:
            age_days = (datetime.now().date() - latest).days
            stale = age_days >= 1
    except Exception as e:
        return {"ran": False, "error": str(e)[:80]}

    if not stale:
        return {"ran": False, "reason": "snapshot_fresh", "snapshot_date": str(latest)}
    if not apply:
        return {"ran": False, "dry_run": True, "would_refresh": True}

    try:
        r = subprocess.run(
            [PY, str(ROOT / "scripts" / "finviz_sector_research.py")],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120,
        )
        return {"ran": True, "ok": r.returncode == 0, "tail": (r.stdout or r.stderr or "")[-200:]}
    except Exception as e:
        return {"ran": True, "ok": False, "error": str(e)[:80]}


def run_sector_universe(
    conn,
    *,
    apply: bool,
    batch_size: int = 12,
    research_queue: int = 3,
    refresh_finviz: bool = False,
) -> dict:
    refresh = ensure_finviz_snapshot(apply=apply) if refresh_finviz else {"ran": False}
    snapshot = fetch_group_snapshot(conn)
    sync = sync_universe_batch(
        conn, snapshot, apply=apply, batch_size=batch_size, research_queue=research_queue,
    )
    return {"finviz_refresh": refresh, "snapshot_date": snapshot.get("snapshot_date"), **sync}