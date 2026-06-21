#!/usr/bin/env python3
"""sync_research_directives_to_topics.py — route operator research topics (trend watch_directives added via
the OpenClaw `add-topic` skill) into the KNOWLEDGE-research pipeline (topic_monitor → hermes_topic_monitor
_bridge → Hermes research → topic_research rows).

Why: `add-topic` only created trend directives, which feed TICKER DISCOVERY — useless for knowledge themes
like "Roth conversion ladder" / "Medicaid Asset Protection Trust". Those need topic_monitor (the proven
research path that already handles Trust & Estate / Tax Loss Harvesting). This mirrors each active trend
directive into a topic_monitor row (owner='shared' → researched by both Hermes + TradeAI), idempotently.

  python3 scripts/sync_research_directives_to_topics.py [--apply]   (default dry-run)
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_adapter import _get_conn

# Operator's planning context (matches the existing trust_estate/tax_loss_harvest topics) — attached to the
# retirement/estate/tax/Medicare/SSDI topics so Hermes researches them in the operator's actual situation.
PLANNING_CTX = ("Operator age 58 (59 in Aug 2026), on SSDI, NY resident, Medicare eligibility ~Dec 2026, "
                "Golden-Window Roth conversion strategy, asset/estate protection (MAPT), ~$1.2M portfolio.")
_PLANNING_RX = re.compile(r"roth|irmaa|medicaid|medicare|ssdi|estate|trust|mapt|retire|tax|conversion|"
                          r"dividend|covered call|income|cef|pty|nav|bond|annuit", re.I)


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")[:44]


def sync(apply=False):
    conn = _get_conn(); cur = conn.cursor()
    cur.execute("""SELECT id, label, spec, rationale FROM watch_directives
                   WHERE kind='trend' AND status='active' ORDER BY id""")
    dirs = cur.fetchall()
    # existing topic_ids (idempotent)
    cur.execute("SELECT topic_id FROM topic_monitor")
    existing = {r[0] for r in cur.fetchall()}
    created, skipped = [], 0
    for did, label, spec, rationale in dirs:
        sp = spec if isinstance(spec, dict) else json.loads(spec or "{}")
        kws = [k for k in (sp.get("keywords") or []) if k and len(str(k).split()) >= 1]
        theme = re.sub(r"^trend\s+", "", label or "", flags=re.I).strip()
        topic_id = f"d{did}_{_slug(theme)}"
        if topic_id in existing:
            skipped += 1
            continue
        is_planning = bool(_PLANNING_RX.search(f"{theme} {' '.join(kws)}"))
        # search queries = the directive's LLM-enhanced keywords (fallback to the theme)
        queries = kws[:8] if kws else [theme]
        ctx = PLANNING_CTX if is_planning else ""
        prio = 2 if is_planning else 4
        owner = "shared"
        agent = "Steph" if is_planning else "Alex"   # Steph = income/allocation/retirement; Alex = CIO
        created.append({"topic_id": topic_id, "display_name": theme[:80], "queries": queries,
                        "planning": is_planning, "directive_id": did})
        if apply:
            cur.execute("""INSERT INTO topic_monitor
                (topic_id, display_name, search_queries, priority, agent_owner, owner, enabled,
                 max_age_days, min_articles, personal_context)
                VALUES (%s,%s,%s::jsonb,%s,%s,%s,true,30,3,%s)
                ON CONFLICT (topic_id) DO NOTHING""",
                (topic_id, theme[:80], json.dumps(queries), prio, agent, owner, ctx))
    if apply:
        conn.commit()
    planning_n = sum(1 for c in created if c["planning"])
    print(json.dumps({"mode": "APPLIED" if apply else "DRY-RUN", "active_trend_directives": len(dirs),
                      "already_in_topic_monitor": skipped, "to_create": len(created),
                      "planning_topics": planning_n, "market_topics": len(created) - planning_n,
                      "sample": [{"topic_id": c["topic_id"], "planning": c["planning"]} for c in created[:6]]},
                     indent=2))
    return 0


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(str(Path(__file__).resolve().parent.parent / ".env"))
    raise SystemExit(sync("--apply" in sys.argv))
