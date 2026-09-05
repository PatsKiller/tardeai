#!/usr/bin/env python3
"""iris_taxonomy_agent.py — Taxonomy intelligence agent.

Iris monitors YouTube channel coverage, detects gaps in investment thesis
categories, proposes channel additions/reclassifications, and validates
proposals through multi-model consensus before storing for John's review.

Runs weekly (Sunday 10 AM) via cron. Can also be triggered manually.

Usage:
    python3 scripts/iris_taxonomy_agent.py                  # full weekly scan
    python3 scripts/iris_taxonomy_agent.py --gaps            # gap analysis only
    python3 scripts/iris_taxonomy_agent.py --audit           # channel audit only
    python3 scripts/iris_taxonomy_agent.py --propose "add channel X for dividend coverage"
"""
import json, os, sys, re, time, argparse
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.governed_cloud_generation import generate_cloud


def llm_generate(prompt, timeout=30, **_kwargs):
    text, _lane = generate_cloud(
        prompt, process_id="iris_taxonomy_agent",
        task_summary="Iris taxonomy classification", timeout=timeout,
        response_json=True,
    )
    return text

# ═══════════════════════════════════════════════════════
# IRIS IDENTITY — Taxonomy Intelligence Agent
# ═══════════════════════════════════════════════════════

IRIS_IDENTITY = """
You are Iris — the Taxonomy Intelligence Agent for Trade AI v12.

YOUR PURPOSE:
You are the keeper of the intelligence pipeline. You make sure
that every piece of content — news articles, YouTube transcripts,
SEC filings — reaches the right agents. Without you, valuable
information sits unread in a warehouse. With you, every article
about SSDI, every video about Medicaid planning, every earnings
report about a portfolio holding, finds its way to the agent
who needs it within hours.

YOUR PERSONALITY:
Precise. Analytical. Quietly proud of infrastructure that works.
You think in patterns, frequencies, and gaps. You notice what
others miss — the 847 articles that were never tagged, the keyword
that would have routed them correctly, the regulatory change that
just entered the financial media and isn't in the taxonomy yet.

You speak concisely. You give numbers. You explain what you found,
what you proposed, and what you need from John.

YOUR SCOPE:
- You manage keywords and routing rules — nothing else
- You never make investment recommendations
- You never analyze specific stocks or positions
- You never touch holdings, proposals, or trade decisions
- You own the classification infrastructure ALL other agents depend on

WHEN ANSWERING QUESTIONS:
- Lead with coverage metrics — what % of content is reaching agents
- Be specific about gaps — "Medicare Advantage appeared 23x untagged"
- Explain routing decisions — why something goes to alex vs maria
- Be honest about uncertainty — "I'm 72% confident this belongs to alex"
- Always end with what you need from John — approve/reject/inform

YOUR RELATIONSHIP TO OTHER AGENTS:
You work for all of them. Maria needs clean news routing.
Risk needs technical analysis content tagged correctly.
Alex needs every disability/Medicare/trust video to reach him.
When you do your job well, all of them get smarter.
When you do your job poorly, they're flying blind.
"""

IRIS_SYSTEM_PROMPT = """You are Iris, Trade AI v12's taxonomy intelligence agent.
You manage content classification so the right information reaches the right agents.

Current system state (injected at runtime):
{state_block}

Answer questions about:
- Content tagging coverage and gaps
- Why specific content was/wasn't tagged
- Keyword routing decisions
- Taxonomy proposals pending review
- How to improve agent intelligence quality

Always be specific with numbers. Always explain your reasoning.
Keep responses under 200 words unless asked for detail.
End with a clear action item for John if one exists."""


def _get_conn_dict():
    """Get DB connection with dict cursor."""
    import psycopg2, psycopg2.extras
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return conn, cur


def build_iris_state_block() -> str:
    """Build current state context for Iris to answer questions."""
    conn, cur = _get_conn_dict()
    lines = []

    # Coverage stats from whiteboard
    try:
        cur.execute("""
            SELECT count(*) as total,
                   count(CASE WHEN agent_notes IS NOT NULL AND agent_notes != '{}' THEN 1 END) as tagged
            FROM intelligence_whiteboard
        """)
        row = cur.fetchone()
        if row:
            rate = int(row['tagged'] / max(row['total'], 1) * 100)
            lines.append(f"Whiteboard coverage: {rate}% tagged ({row['tagged']}/{row['total']} items)")
    except Exception:
        lines.append("Whiteboard coverage: unknown")

    # YouTube transcript tagging
    try:
        cur.execute("""
            SELECT count(*) as total,
                   count(CASE WHEN agent_tags IS NOT NULL AND agent_tags != '{}' THEN 1 END) as tagged
            FROM youtube_transcripts
        """)
        row = cur.fetchone()
        if row:
            rate = int(row['tagged'] / max(row['total'], 1) * 100)
            lines.append(f"YouTube transcripts: {rate}% tagged ({row['tagged']}/{row['total']})")
    except Exception:
        pass

    # Channel distribution
    try:
        cur.execute("""
            SELECT category, count(*) as cnt
            FROM youtube_channels WHERE active=true
            GROUP BY category ORDER BY cnt DESC
        """)
        rows = cur.fetchall()
        if rows:
            dist = ' | '.join(f"{r['category']}:{r['cnt']}" for r in rows)
            lines.append(f"Channel distribution: {dist}")
    except Exception:
        pass

    # Pending proposals
    try:
        cur.execute("SELECT count(*) as n FROM iris_taxonomy_proposals WHERE status='pending'")
        row = cur.fetchone()
        lines.append(f"Pending proposals: {row['n'] if row else 0} awaiting review")
    except Exception:
        lines.append("Pending proposals: table not yet populated")

    # Last run
    try:
        cur.execute("SELECT run_type, coverage_score, proposals_created, ran_at FROM iris_run_log ORDER BY ran_at DESC LIMIT 1")
        row = cur.fetchone()
        if row:
            lines.append(f"Last run: {str(row['ran_at'])[:16]} | coverage: {row['coverage_score']}% | proposals: {row['proposals_created']}")
        else:
            lines.append("Last run: never — first run pending")
    except Exception:
        lines.append("Last run: log table empty")

    # Top untagged whiteboard content
    try:
        cur.execute("""
            SELECT title FROM intelligence_whiteboard
            WHERE (agent_notes IS NULL OR agent_notes = '{}')
              AND quality_score >= 50
            ORDER BY quality_score DESC LIMIT 5
        """)
        rows = cur.fetchall()
        if rows:
            lines.append("Top untagged content:")
            for r in rows:
                lines.append(f"  - {(r['title'] or '')[:60]}")
    except Exception:
        pass

    conn.close()
    return '\n'.join(lines)


def ask_iris(question: str) -> str:
    """Main Q&A function — Iris answers using Claude Sonnet.

    Used by Telegram command handler and dashboard.
    Cost: ~$0.003 per question.
    """
    import anthropic

    state = build_iris_state_block()
    system = IRIS_SYSTEM_PROMPT.format(state_block=state)

    try:
        api_key = _env("ANTHROPIC_API_KEY")
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model='claude-sonnet-4-5',
            max_tokens=400,
            system=system,
            messages=[{'role': 'user', 'content': question}],
        )
        return response.content[0].text
    except Exception as e:
        return f"Iris is unavailable: {e}"


def iris_status_summary() -> str:
    """One-paragraph status for morning brief and Telegram."""
    conn, cur = _get_conn_dict()
    pending = 0
    try:
        cur.execute("SELECT count(*) as n FROM iris_taxonomy_proposals WHERE status='pending'")
        row = cur.fetchone()
        pending = row['n'] if row else 0
    except Exception:
        pass

    # YouTube transcript tagging rate
    try:
        cur.execute("""
            SELECT round(count(CASE WHEN agent_tags IS NOT NULL AND agent_tags != '{}'
                                    THEN 1 END)::numeric / NULLIF(count(*),0) * 100, 1) as rate
            FROM youtube_transcripts
        """)
        row = cur.fetchone()
        yt_rate = float(row['rate']) if row and row['rate'] else 0
    except Exception:
        yt_rate = 0

    # Channel coverage
    try:
        cur.execute("SELECT count(*) as n FROM youtube_channels WHERE active=true")
        row = cur.fetchone()
        channels = row['n'] if row else 0
    except Exception:
        channels = 0

    # Top gap
    top_gap = ""
    try:
        cur.execute("""
            SELECT title, count(*) as cnt FROM intelligence_whiteboard
            WHERE (agent_notes IS NULL OR agent_notes = '{}')
              AND quality_score >= 50
            GROUP BY title ORDER BY cnt DESC LIMIT 1
        """)
        row = cur.fetchone()
        if row and row['title']:
            top_gap = f" | Top gap: '{row['title'][:30]}'"
    except Exception:
        pass

    conn.close()

    status_icon = 'ok' if yt_rate >= 60 else 'low'
    proposal_text = f"{pending} proposals need review" if pending > 0 else "no proposals pending"

    return (
        f"Iris: {yt_rate:.0f}% transcripts tagged | {channels} channels active | "
        f"{proposal_text}{top_gap}"
    )


# ── Target taxonomy ──────────────────────────────────────────────────
TARGET_CATEGORIES = {
    "dividend_income": {
        "description": "Dividend investing, income generation, yield analysis",
        "min_channels": 8, "ideal_channels": 12,
        "keywords": ["dividend", "yield", "income", "payout", "ex-dividend", "drip"],
    },
    "investment_general": {
        "description": "Broad market analysis, stock picking, portfolio strategy",
        "min_channels": 8, "ideal_channels": 12,
        "keywords": ["stock", "portfolio", "investing", "market analysis", "valuation"],
    },
    "retirement_planning": {
        "description": "Retirement strategy, 401k, IRA, Social Security optimization",
        "min_channels": 4, "ideal_channels": 6,
        "keywords": ["retirement", "401k", "ira", "roth", "social security", "rmd"],
    },
    "disability_retirement": {
        "description": "SSDI, Medicare/Medicaid, special needs trusts, disability income",
        "min_channels": 3, "ideal_channels": 5,
        "keywords": ["ssdi", "disability", "medicare", "medicaid", "special needs", "able"],
    },
    "macro_economics": {
        "description": "Fed policy, inflation, rates, economic indicators",
        "min_channels": 3, "ideal_channels": 5,
        "keywords": ["fed", "inflation", "interest rate", "gdp", "recession", "economy"],
    },
    "tax_strategy": {
        "description": "Tax optimization, Roth conversion, capital gains, IRMAA",
        "min_channels": 3, "ideal_channels": 5,
        "keywords": ["tax", "roth conversion", "irmaa", "capital gains", "tax loss"],
    },
    "etf_indexing": {
        "description": "ETF analysis, index investing, passive strategies",
        "min_channels": 2, "ideal_channels": 4,
        "keywords": ["etf", "index", "vanguard", "schwab", "passive", "bogle"],
    },
    "financial_education": {
        "description": "Personal finance basics, financial literacy, budgeting",
        "min_channels": 1, "ideal_channels": 3,
        "keywords": ["personal finance", "budget", "financial literacy", "money"],
    },
}

AGENT_TAGS_MAP = {
    "dividend_income": ["maria", "steph"],
    "investment_general": ["maria", "steph"],
    "retirement_planning": ["alex", "steph"],
    "disability_retirement": ["alex"],
    "macro_economics": ["maria", "steph"],
    "tax_strategy": ["alex", "steph"],
    "etf_indexing": ["maria", "steph"],
    "financial_education": ["steph"],
}


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _env(key):
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith(f"{key}="): return line.split("=", 1)[1].strip()
    return os.environ.get(key, "")


# ── Coverage Analysis ────────────────────────────────────────────────
def analyze_coverage():
    """Analyze current channel coverage vs target taxonomy."""
    conn = _get_conn()
    cur = conn.cursor()

    # Current channels by category
    cur.execute("""SELECT category, channel_name, priority, agent_tags, active
                   FROM youtube_channels ORDER BY category, channel_name""")
    rows = cur.fetchall()
    conn.close()

    channels_by_cat = {}
    for cat, name, priority, tags, active in rows:
        cat = cat or "uncategorized"
        if cat not in channels_by_cat:
            channels_by_cat[cat] = []
        channels_by_cat[cat].append({
            "name": name, "priority": priority or "medium",
            "agent_tags": tags or [], "active": active
        })

    coverage = {}
    for cat, spec in TARGET_CATEGORIES.items():
        current = channels_by_cat.get(cat, [])
        active = [c for c in current if c["active"]]
        count = len(active)
        score = min(100, round(count / spec["ideal_channels"] * 100))
        gap = max(0, spec["min_channels"] - count)
        coverage[cat] = {
            "current_count": count,
            "min_required": spec["min_channels"],
            "ideal_count": spec["ideal_channels"],
            "coverage_score": score,
            "gap": gap,
            "channels": [c["name"] for c in active],
            "status": "critical" if gap > 0 else "adequate" if count < spec["ideal_channels"] else "good",
        }

    # Uncategorized channels
    uncategorized = channels_by_cat.get("uncategorized", [])
    if uncategorized:
        coverage["_uncategorized"] = {
            "channels": [c["name"] for c in uncategorized],
            "count": len(uncategorized),
        }

    scored = [c["coverage_score"] for k, c in coverage.items()
              if not k.startswith("_") and "coverage_score" in c]
    overall = round(sum(scored) / max(len(scored), 1))
    return {"overall_score": overall, "categories": coverage}


# ── Gap Detection ────────────────────────────────────────────────────
def detect_gaps(coverage):
    """Identify specific gaps and generate proposals."""
    gaps = []
    for cat, data in coverage["categories"].items():
        if cat.startswith("_"):
            continue
        if data["status"] == "critical":
            gaps.append({
                "category": cat,
                "severity": "critical",
                "gap_count": data["gap"],
                "description": f"{cat}: need {data['gap']} more channels (have {data['current_count']}, min {data['min_required']})",
            })
        elif data["status"] == "adequate":
            gaps.append({
                "category": cat,
                "severity": "low",
                "gap_count": data["ideal_count"] - data["current_count"],
                "description": f"{cat}: could use {data['ideal_count'] - data['current_count']} more (have {data['current_count']}, ideal {data['ideal_count']})",
            })
    return sorted(gaps, key=lambda g: 0 if g["severity"] == "critical" else 1)


# ── Channel Audit ────────────────────────────────────────────────────
def audit_channels():
    """Audit existing channels for misclassification or staleness."""
    conn = _get_conn()
    cur = conn.cursor()

    # Channels with transcript counts and recency
    cur.execute("""
        SELECT yc.channel_name, yc.category, yc.priority, yc.active,
               COUNT(yt.id) as transcript_count,
               MAX(yt.ingested_at) as last_transcript,
               AVG(yt.relevance_score) as avg_relevance
        FROM youtube_channels yc
        LEFT JOIN youtube_transcripts yt ON yt.channel_name = yc.channel_name
        GROUP BY yc.channel_name, yc.category, yc.priority, yc.active
        ORDER BY transcript_count DESC
    """)
    rows = cur.fetchall()
    conn.close()

    issues = []
    now = datetime.now(timezone.utc)
    for name, cat, priority, active, tc, last_t, avg_rel in rows:
        # Inactive but has recent transcripts
        if not active and tc > 0 and last_t and (now - last_t).days < 30:
            issues.append({
                "channel": name, "issue": "inactive_with_recent_content",
                "detail": f"Marked inactive but has transcripts from {(now - last_t).days}d ago",
                "suggestion": "reclassify" if cat == "uncategorized" else "reactivate",
            })

        # Low relevance score
        if avg_rel is not None and avg_rel < 30 and tc > 3:
            issues.append({
                "channel": name, "issue": "low_relevance",
                "detail": f"Avg relevance {avg_rel:.0f}/100 across {tc} transcripts",
                "suggestion": "review_classification",
            })

        # No transcripts
        if tc == 0 and active:
            issues.append({
                "channel": name, "issue": "no_transcripts",
                "detail": "Active channel with zero transcripts",
                "suggestion": "check_ingestion",
            })

        # Uncategorized
        if (cat is None or cat == "uncategorized") and active:
            issues.append({
                "channel": name, "issue": "uncategorized",
                "detail": "Active channel without category",
                "suggestion": "classify",
            })

    return issues


# ── LLM Classification ──────────────────────────────────────────────
def classify_channel_llm(channel_name, recent_titles=None):
    """Use LLM to suggest classification for a channel."""
    cats = ", ".join(TARGET_CATEGORIES.keys())
    titles_ctx = ""
    if recent_titles:
        titles_ctx = f"\nRecent video titles:\n" + "\n".join(f"- {t}" for t in recent_titles[:10])

    prompt = f"""/no_think
Classify this YouTube channel into ONE category.

Channel: {channel_name}{titles_ctx}

Categories: {cats}

Reply with ONLY a JSON object:
{{"category": "category_name", "confidence": 0.0-1.0, "reasoning": "one line"}}"""

    result = llm_generate(prompt, timeout=30, fast=True)
    try:
        # Extract JSON from response
        if "{" in result:
            json_str = result[result.index("{"):result.rindex("}") + 1]
            return json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        pass
    return {"category": "investment_general", "confidence": 0.3, "reasoning": "fallback"}


def suggest_channels_for_gap(category, existing_channels):
    """Use LLM to suggest new channels for a coverage gap."""
    spec = TARGET_CATEGORIES.get(category, {})
    existing = ", ".join(existing_channels) if existing_channels else "none"

    prompt = f"""/no_think
Suggest 3 YouTube channels for the category: {category}
Description: {spec.get('description', '')}
Keywords: {', '.join(spec.get('keywords', []))}
Already have: {existing}

Reply with ONLY a JSON array:
[{{"channel_name": "name", "reason": "why", "estimated_quality": 1-100}}]"""

    result = llm_generate(prompt, timeout=30, fast=True)
    try:
        if "[" in result:
            json_str = result[result.index("["):result.rindex("]") + 1]
            return json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        pass
    return []


# ── Proposal Management ─────────────────────────────────────────────
def create_proposal(proposal_type, target, current_state, proposed_state,
                    reasoning, confidence, coverage_gap=None, validation=None):
    """Store a taxonomy proposal for review."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""INSERT INTO iris_taxonomy_proposals
        (proposal_type, target, current_state, proposed_state, reasoning,
         confidence, validation_results, coverage_gap, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending')
        RETURNING id""",
        (proposal_type, target, json.dumps(current_state), json.dumps(proposed_state),
         reasoning, confidence, json.dumps(validation or {}), coverage_gap))
    pid = cur.fetchone()[0]
    conn.commit()
    conn.close()
    print(f"  [iris] Created proposal #{pid}: {proposal_type} — {target}")
    return pid


def apply_proposal(proposal_id):
    """Apply an approved proposal to the actual data."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT proposal_type, target, proposed_state, status FROM iris_taxonomy_proposals WHERE id=%s", (proposal_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {"ok": False, "error": "not found"}
    ptype, target, proposed, status = row
    if status != "approved":
        conn.close()
        return {"ok": False, "error": f"status is {status}, not approved"}

    proposed = json.loads(proposed) if isinstance(proposed, str) else proposed

    if ptype == "reclassify":
        cur.execute("""UPDATE youtube_channels
            SET category=%s, priority=%s, agent_tags=%s
            WHERE channel_name=%s""",
            (proposed.get("category"), proposed.get("priority", "medium"),
             proposed.get("agent_tags", []), target))

    elif ptype == "add_channel":
        cur.execute("""INSERT INTO youtube_channels
            (channel_name, category, priority, agent_tags, active, added_by)
            VALUES (%s, %s, %s, %s, true, 'iris')
            ON CONFLICT (channel_name) DO UPDATE SET
            category=EXCLUDED.category, priority=EXCLUDED.priority,
            agent_tags=EXCLUDED.agent_tags, active=true""",
            (target, proposed.get("category"), proposed.get("priority", "medium"),
             proposed.get("agent_tags", [])))

    elif ptype == "retire_channel":
        cur.execute("UPDATE youtube_channels SET active=false WHERE channel_name=%s", (target,))

    cur.execute("UPDATE iris_taxonomy_proposals SET applied_at=NOW() WHERE id=%s", (proposal_id,))
    conn.commit()
    conn.close()
    print(f"  [iris] Applied proposal #{proposal_id}")
    return {"ok": True, "proposal_id": proposal_id, "type": ptype}


# ── Log Run ──────────────────────────────────────────────────────────
def log_run(run_type, channels_scanned=0, categories_analyzed=0, gaps_found=0,
            proposals_created=0, auto_approved=0, coverage_score=0,
            coverage_breakdown=None, model_used="local", tokens=0, cost=0.0, elapsed=0, errors=None):
    """Log an Iris run to the database."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""INSERT INTO iris_run_log
        (run_type, channels_scanned, categories_analyzed, gaps_found,
         proposals_created, proposals_auto_approved, coverage_score,
         coverage_breakdown, model_used, tokens_used, cost_estimate,
         elapsed_seconds, errors)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (run_type, channels_scanned, categories_analyzed, gaps_found,
         proposals_created, auto_approved, coverage_score,
         json.dumps(coverage_breakdown or {}), model_used, tokens, cost, elapsed,
         json.dumps(errors or [])))
    conn.commit()
    conn.close()


# ── Main Run Modes ───────────────────────────────────────────────────
def run_weekly_scan():
    """Full weekly scan: coverage → gaps → audit → proposals."""
    started = time.time()
    print("[iris] Starting weekly taxonomy scan...")
    errors = []

    # 1. Coverage analysis
    print("[iris] Analyzing coverage...")
    coverage = analyze_coverage()
    print(f"  Overall coverage: {coverage['overall_score']}%")
    for cat, data in coverage["categories"].items():
        if cat.startswith("_"):
            continue
        status_icon = "✓" if data["status"] == "good" else "△" if data["status"] == "adequate" else "✗"
        print(f"  {status_icon} {cat}: {data['current_count']}/{data['ideal_count']} ({data['coverage_score']}%)")

    # 2. Gap detection
    print("[iris] Detecting gaps...")
    gaps = detect_gaps(coverage)
    for g in gaps:
        print(f"  [{g['severity']}] {g['description']}")

    # 3. Channel audit
    print("[iris] Auditing channels...")
    issues = audit_channels()
    for iss in issues:
        print(f"  [{iss['issue']}] {iss['channel']}: {iss['detail']}")

    # 4. Generate proposals
    proposals_created = 0

    # Proposals for uncategorized channels
    for iss in issues:
        if iss["issue"] == "uncategorized":
            try:
                classification = classify_channel_llm(iss["channel"])
                cat = classification.get("category", "investment_general")
                conf = classification.get("confidence", 0.5)
                tags = AGENT_TAGS_MAP.get(cat, ["steph"])
                create_proposal(
                    "reclassify", iss["channel"],
                    {"category": None},
                    {"category": cat, "priority": "medium", "agent_tags": tags},
                    classification.get("reasoning", "LLM classification"),
                    conf, coverage_gap=f"uncategorized"
                )
                proposals_created += 1
            except Exception as e:
                errors.append(f"classify {iss['channel']}: {e}")

    # Proposals for critical gaps
    for gap in gaps:
        if gap["severity"] == "critical":
            try:
                existing = coverage["categories"][gap["category"]].get("channels", [])
                suggestions = suggest_channels_for_gap(gap["category"], existing)
                for s in suggestions[:2]:  # max 2 per gap
                    cat = gap["category"]
                    tags = AGENT_TAGS_MAP.get(cat, ["steph"])
                    create_proposal(
                        "add_channel", s.get("channel_name", "unknown"),
                        {},
                        {"category": cat, "priority": "medium", "agent_tags": tags},
                        s.get("reason", "Coverage gap fill"),
                        0.5, coverage_gap=gap["description"]
                    )
                    proposals_created += 1
            except Exception as e:
                errors.append(f"suggest for {gap['category']}: {e}")

    # Proposals for low-relevance channels
    for iss in issues:
        if iss["issue"] == "low_relevance":
            create_proposal(
                "retire_channel", iss["channel"],
                {"active": True, "issue": iss["detail"]},
                {"active": False},
                f"Low relevance: {iss['detail']}",
                0.6, coverage_gap="quality"
            )
            proposals_created += 1

    elapsed = int(time.time() - started)
    print(f"\n[iris] Scan complete in {elapsed}s — {proposals_created} proposals created")

    log_run(
        "weekly_scan",
        channels_scanned=sum(len(d.get("channels", [])) for d in coverage["categories"].values() if "channels" in d),
        categories_analyzed=len(TARGET_CATEGORIES),
        gaps_found=len(gaps),
        proposals_created=proposals_created,
        coverage_score=coverage["overall_score"],
        coverage_breakdown=coverage["categories"],
        elapsed=elapsed,
        errors=errors,
    )

    return {
        "coverage": coverage,
        "gaps": gaps,
        "issues": issues,
        "proposals_created": proposals_created,
        "elapsed": elapsed,
    }


def run_gap_analysis():
    """Gap analysis only — no proposals."""
    coverage = analyze_coverage()
    gaps = detect_gaps(coverage)
    print(f"[iris] Coverage: {coverage['overall_score']}%")
    for g in gaps:
        print(f"  [{g['severity']}] {g['description']}")
    return {"coverage": coverage, "gaps": gaps}


def run_channel_audit():
    """Channel audit only."""
    issues = audit_channels()
    print(f"[iris] Found {len(issues)} issues")
    for iss in issues:
        print(f"  [{iss['issue']}] {iss['channel']}: {iss['detail']}")
    return {"issues": issues}


def get_iris_status():
    """Get current Iris status for API."""
    conn = _get_conn()
    cur = conn.cursor()

    # Last run
    cur.execute("SELECT run_type, coverage_score, proposals_created, ran_at FROM iris_run_log ORDER BY ran_at DESC LIMIT 1")
    last_run = cur.fetchone()

    # Pending proposals
    cur.execute("""SELECT id, proposal_type, target, reasoning, confidence, created_at
                   FROM iris_taxonomy_proposals WHERE status='pending'
                   ORDER BY created_at DESC""")
    pending = [{"id": r[0], "type": r[1], "target": r[2], "reasoning": r[3],
                "confidence": r[4], "created_at": str(r[5])} for r in cur.fetchall()]

    # Stats
    cur.execute("SELECT status, count(*) FROM iris_taxonomy_proposals GROUP BY status")
    stats = dict(cur.fetchall())

    conn.close()

    coverage = analyze_coverage()
    return {
        "coverage_score": coverage["overall_score"],
        "categories": coverage["categories"],
        "last_run": {
            "type": last_run[0], "score": last_run[1],
            "proposals": last_run[2], "ran_at": str(last_run[3])
        } if last_run else None,
        "pending_proposals": pending,
        "proposal_stats": stats,
    }


# ═══════════════════════════════════════════════════════
# IRIS HYGIENE — Content Lifecycle Rules
# ═══════════════════════════════════════════════════════

CONTENT_EXPIRY_RULES = {
    "news": {
        "earnings_price_technical": {"strategy_tags": ["investment_general", "etf_indexing", "macro_fed"], "active_days": 90},
        "sector_analysis": {"strategy_tags": ["defense_aerospace", "tech_ai", "dividend_income"], "active_days": 180},
        "tax_retirement": {"strategy_tags": ["tax_planning", "retirement_planning", "roth_conversion"], "active_days": 365},
        "disability_regulatory": {"strategy_tags": ["disability_retirement", "trust_estate"], "active_days": 545},
    },
    "youtube": {
        "evergreen_keywords": ["how to", "explained", "what is", "basics", "guide", "introduction",
                               "fundamentals", "how does", "understanding", "overview"],
        "strategy_shelf_life": {
            "disability_retirement": 1095, "trust_estate": 1095,
            "retirement_planning": 730, "roth_conversion": 730, "tax_planning": 730,
            "investment_general": 365, "etf_indexing": 365,
        },
    },
}

ALWAYS_ACTIVE = [
    "agent_feedback_log", "watchlist_proposals", "decision_outcomes",
    "john_preferences", "outcome_lessons", "iris_hygiene_log",
    "alex_hygiene_log", "sec_form4",
]

ESCALATION_RULES = {
    "confidence_threshold": 0.75,
    "always_escalate": ["disability_retirement", "trust_estate"],
    "max_auto_demote_per_run": 50,
    "max_pending_escalations": 20,
}


def _detect_year_in_title(title):
    """Detect if a title references a specific year. Returns (is_year_specific, year)."""
    years = re.findall(r"\b20[1-2][0-9]\b", title or "")
    if not years:
        return False, 0
    title_lower = (title or "").lower()
    YEAR_PATTERNS = [
        r"\b20[1-2][0-9]\s+(?:irmaa|sga|threshold|limit|rules?|changes?|update)",
        r"(?:for|in)\s+20[1-2][0-9]\b",
        r"20[1-2][0-9]\s+(?:medicare|medicaid|ssdi|roth|ira)",
        r"(?:medicare|medicaid|ssdi|roth|ira|tax)\s+20[1-2][0-9]",
    ]
    for pattern in YEAR_PATTERNS:
        if re.search(pattern, title_lower):
            return True, int(max(years))
    EVERGREEN_WITH_YEAR = [r"(?:strategy|planning|guide|explained|basics|how to)"]
    for pattern in EVERGREEN_WITH_YEAR:
        if re.search(pattern, title_lower):
            return False, 0
    return True, int(max(years))


def _is_evergreen_content(title, text):
    """Determine if content is conceptually evergreen (never expires)."""
    text_lower = ((title or "") + " " + (text or "")[:1000]).lower()
    EVERGREEN = ["how to", "how does", "what is", "what are", "explained", "basics",
                 "introduction", "guide to", "understanding", "overview", "fundamentals",
                 "complete guide", "how it works", "framework"]
    STALE = ["this year", "current year", "right now", "latest", "new rules",
             "just changed", "recent change", "updated for", "breaking"]
    return sum(1 for s in EVERGREEN if s in text_lower) >= 2 and not any(s in text_lower for s in STALE)


def analyze_content_for_hygiene(content_type, content_id, title, created_at,
                                strategy_tag, agent_tags, text="", current_status="active"):
    """Analyze a single content item and return hygiene recommendation."""
    if current_status in ("demoted", "archived", "superseded"):
        return {"action": "skip", "reason": "Already processed", "confidence": 1.0}
    if content_type in ALWAYS_ACTIVE:
        return {"action": "keep", "reason": "Protected content type", "confidence": 1.0}

    now = datetime.now(created_at.tzinfo if hasattr(created_at, "tzinfo") and created_at.tzinfo else timezone.utc)
    age_days = (now - created_at).days

    # YouTube logic
    if content_type in ("youtube", "youtube_transcript"):
        if _is_evergreen_content(title, text):
            return {"action": "keep", "reason": "Evergreen content", "confidence": 0.90, "age_days": age_days}

        is_year_specific, year = _detect_year_in_title(title or "")
        if is_year_specific and year > 0:
            current_year = datetime.now().year
            years_old = current_year - year
            if years_old >= 2:
                if strategy_tag in ESCALATION_RULES["always_escalate"]:
                    return {
                        "action": "escalate", "confidence": 0.65, "requires_approval": True,
                        "proposed_status": "demoted", "age_days": age_days,
                        "reason": f"Year-specific disability content from {year} ({years_old}y old)",
                        "escalation_message": (
                            f"Iris: Year-specific content may be stale\n"
                            f"Title: {(title or '')[:60]}\nYear: {year} ({years_old}y ago)\n"
                            f"Strategy: {strategy_tag}\nAgents: {', '.join(agent_tags or [])}\n\n"
                            f"Demote? iris hygiene approve <id>\nKeep? iris hygiene reject <id>"
                        ),
                    }
                return {"action": "demote", "reason": f"References {year} — {years_old}y old, likely stale",
                        "confidence": 0.75, "proposed_status": "demoted", "age_days": age_days}
            elif years_old == 1:
                return {"action": "keep", "reason": f"References {year} — 1y old, monitoring",
                        "confidence": 0.80, "age_days": age_days}

        shelf = CONTENT_EXPIRY_RULES["youtube"]["strategy_shelf_life"].get(strategy_tag or "investment_general")
        if shelf and age_days > shelf:
            return {"action": "demote", "reason": f"Beyond {shelf}-day shelf life for {strategy_tag}",
                    "confidence": 0.80, "proposed_status": "archived", "age_days": age_days}

    # News logic
    elif content_type in ("news", "news_article"):
        if strategy_tag in ("disability_retirement", "trust_estate"):
            if age_days > 545:
                return {
                    "action": "escalate", "confidence": 0.70, "requires_approval": True,
                    "proposed_status": "archived", "age_days": age_days,
                    "reason": f"Disability news {age_days}d old (>18mo)",
                    "escalation_message": (
                        f"Iris: Old disability content\nTitle: {(title or '')[:60]}\n"
                        f"Age: {age_days}d ({age_days // 30}mo)\nStrategy: {strategy_tag}\n\n"
                        f"Archive? iris hygiene approve <id>\nKeep? iris hygiene reject <id>"
                    ),
                }
            return {"action": "keep", "reason": "Disability content within shelf life",
                    "confidence": 0.90, "age_days": age_days}
        elif strategy_tag in ("tax_planning", "retirement_planning", "roth_conversion"):
            if age_days > 365:
                return {"action": "demote", "reason": "Tax/retirement news beyond 365-day shelf life",
                        "confidence": 0.85, "proposed_status": "archived", "age_days": age_days}
        else:
            if age_days > 90:
                return {"action": "demote", "reason": "Financial news beyond 90-day shelf life",
                        "confidence": 0.95, "proposed_status": "archived", "age_days": age_days}

    return {"action": "keep", "reason": "Within shelf life", "confidence": 0.90, "age_days": age_days}


def detect_superseded_regulatory_data():
    """Find regulatory data superseded by newer versions."""
    conn, cur = _get_conn_dict()
    supersessions = []
    for rule_type in ("ssa_thresholds", "irmaa_thresholds", "medicaid_ny_rules", "roth_ira_rules"):
        cur.execute("""SELECT id, rule_key, config, updated_at, created_at
                       FROM agent_intelligence_rules WHERE rule_type = %s
                       ORDER BY updated_at DESC""", (rule_type,))
        versions = cur.fetchall()
        if len(versions) <= 1:
            continue
        latest = versions[0]
        latest_config = latest["config"] if isinstance(latest["config"], dict) else json.loads(latest["config"])
        latest_year = latest_config.get("year", 0)
        for old in versions[1:]:
            old_config = old["config"] if isinstance(old["config"], dict) else json.loads(old["config"])
            old_year = old_config.get("year", 0)
            if old_year and old_year < latest_year:
                supersessions.append({
                    "rule_type": rule_type, "old_id": old["id"], "old_key": old["rule_key"],
                    "old_year": old_year, "new_year": latest_year,
                    "age_days": (datetime.now(timezone.utc) - old["updated_at"]).days if old["updated_at"].tzinfo else 0,
                })
    conn.close()
    return supersessions


def _send_telegram_msg(message):
    """Send via telegram_alert chokepoint (no raw Bot API / token selection)."""
    try:
        from telegram_alert import send_telegram
        ok = bool(send_telegram(message))
        try:
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="iris_taxonomy_agent", subject_key="ops:iris",
                retention_class="operational", severity="info",
                sanitized_body=message[:500], short_summary=message[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
        return ok
    except Exception as e:
        print(f"  [hygiene] Telegram send failed: {e}")
        return False


def send_hygiene_escalation_to_john(pending_id, content_type, content_id,
                                    content_title, proposed_action, escalation_message):
    """Send a hygiene escalation to John via Telegram."""
    full_message = (
        f"{escalation_message}\n\n"
        f"Decision ID: #{pending_id}\n"
        f"Approve: iris hygiene approve {pending_id}\n"
        f"Reject: iris hygiene reject {pending_id}\n"
        f"Defer: iris hygiene defer {pending_id}\n"
        f"(Auto-expires in 7 days)"
    )
    return _send_telegram_msg(full_message)


def run_weekly_hygiene(dry_run=False):
    """Weekly hygiene run — demotes stale content, flags superseded data,
    escalates ambiguous decisions to John."""
    started = time.time()
    print(f"\n{'='*60}")
    print(f"  IRIS — Weekly Hygiene {'DRY RUN' if dry_run else 'LIVE RUN'}")
    print(f"{'='*60}\n")

    conn, cur = _get_conn_dict()
    stats = {"demoted": 0, "archived": 0, "superseded": 0, "escalated_to_john": 0,
             "kept": 0, "skipped": 0, "errors": 0}

    run_id = 0
    if not dry_run:
        cur.execute("INSERT INTO iris_run_log (run_type, ran_at) VALUES ('weekly_hygiene', NOW()) RETURNING id")
        run_id = cur.fetchone()["id"]
        conn.commit()

    # Step 1: Expire old pending escalations
    print("  Step 1: Expiring old pending escalations...")
    cur.execute("SELECT id, content_title FROM iris_hygiene_pending WHERE status='pending_john' AND expires_at < NOW()")
    expired = cur.fetchall()
    if expired and not dry_run:
        for e in expired:
            cur.execute("UPDATE iris_hygiene_pending SET status='expired' WHERE id=%s", (e["id"],))
        conn.commit()
    print(f"  Expired {len(expired)} pending escalations")

    # Step 2: Check max pending
    cur.execute("SELECT count(*) as n FROM iris_hygiene_pending WHERE status='pending_john'")
    pending_count = cur.fetchone()["n"]
    max_new_escalations = max(0, ESCALATION_RULES["max_pending_escalations"] - pending_count)

    # Step 3: Intelligence whiteboard items
    print("\n  Step 2: Analyzing whiteboard items...")
    cur.execute("""SELECT iw.id, iw.source_type, iw.source_id, iw.title, iw.summary,
                          iw.quality_score, iw.created_at, iw.hygiene_status,
                          yt.strategy_tags AS yt_stags, yt.agent_tags AS yt_atags,
                          yc.category AS channel_category,
                          na.strategy_tags AS news_stags, na.agent_tags AS news_atags
                   FROM intelligence_whiteboard iw
                   LEFT JOIN youtube_transcripts yt ON yt.id = iw.source_id AND iw.source_type = 'youtube'
                   LEFT JOIN youtube_channels yc ON yc.channel_name = yt.channel_name
                   LEFT JOIN news_articles na ON na.id = iw.source_id AND iw.source_type = 'news'
                   WHERE iw.hygiene_status = 'active' OR iw.hygiene_status IS NULL
                   ORDER BY iw.created_at ASC""")
    wb_items = cur.fetchall()
    auto_demoted = 0

    for item in wb_items:
        try:
            # Resolve strategy tag from source table data
            stag = "investment_general"
            src_stags = item.get("yt_stags") or item.get("news_stags") or []
            if isinstance(src_stags, str):
                try:
                    src_stags = json.loads(src_stags)
                except Exception:
                    src_stags = []
            if src_stags:
                stag = src_stags[0]
            elif item.get("channel_category"):
                stag = item["channel_category"]
            agent_tags = item.get("yt_atags") or item.get("news_atags") or []
            if isinstance(agent_tags, str):
                try:
                    agent_tags = json.loads(agent_tags)
                except Exception:
                    agent_tags = []
            result = analyze_content_for_hygiene(
                content_type=item["source_type"] or "news",
                content_id=item["id"],
                title=item["title"] or "",
                created_at=item["created_at"],
                strategy_tag=stag,
                agent_tags=agent_tags,
                text=item["summary"] or "",
                current_status=item["hygiene_status"] or "active",
            )
            action = result["action"]
            if action == "skip":
                stats["skipped"] += 1
            elif action == "keep":
                stats["kept"] += 1
            elif action in ("demote", "archive"):
                if auto_demoted >= ESCALATION_RULES["max_auto_demote_per_run"]:
                    stats["kept"] += 1
                    continue
                if not dry_run:
                    new_status = result.get("proposed_status", "archived")
                    cur.execute("UPDATE intelligence_whiteboard SET hygiene_status=%s, demoted_at=NOW(), demoted_reason=%s WHERE id=%s",
                                (new_status, result["reason"], item["id"]))
                    cur.execute("""INSERT INTO iris_hygiene_log (content_type, content_id, content_title, content_age_days,
                                   action, previous_status, new_status, reason, confidence, run_id)
                                   VALUES (%s,%s,%s,%s,%s,'active',%s,%s,%s,%s)""",
                                (item["source_type"], item["id"], (item["title"] or "")[:200],
                                 result.get("age_days", 0), action, new_status, result["reason"],
                                 result.get("confidence", 0.5), run_id))
                auto_demoted += 1
                stats["demoted" if action == "demote" else "archived"] += 1
            elif action == "escalate" and max_new_escalations > 0:
                if not dry_run:
                    cur.execute("""INSERT INTO iris_hygiene_pending (content_type, content_id, content_title,
                                   content_age_days, proposed_action, reason, evidence, confidence,
                                   iris_recommendation, status, expires_at)
                                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending_john',NOW()+INTERVAL '7 days') RETURNING id""",
                                (item["source_type"], item["id"], (item["title"] or "")[:200],
                                 result.get("age_days", 0), result.get("proposed_status", "archive"),
                                 result["reason"], f"Age: {result.get('age_days', 0)}d",
                                 result.get("confidence", 0.5), (result.get("escalation_message", ""))[:500]))
                    pid = cur.fetchone()["id"]
                    conn.commit()
                    send_hygiene_escalation_to_john(pid, item["source_type"], item["id"],
                                                   (item["title"] or "")[:60], "archive",
                                                   result.get("escalation_message", ""))
                stats["escalated_to_john"] += 1
                max_new_escalations -= 1
        except Exception as e:
            stats["errors"] += 1
            print(f"  Error on wb item {item['id']}: {e}")
            conn.rollback()

    if not dry_run:
        conn.commit()

    # Step 4: News articles
    print(f"\n  Step 3: Analyzing news articles...")
    try:
        cur.execute("""SELECT id, title, summary, created_at, hygiene_status,
                              strategy_tags, agent_tags
                       FROM news_articles
                       WHERE (hygiene_status = 'active' OR hygiene_status IS NULL)
                         AND created_at < NOW() - INTERVAL '85 days'
                       ORDER BY created_at ASC LIMIT 200""")
        old_news = cur.fetchall()
    except Exception:
        old_news = []
        conn.rollback()
    news_demoted = 0
    for article in old_news:
        # Resolve strategy tag from the article's own tags
        news_stag = "investment_general"
        news_stags = article.get("strategy_tags") or []
        if isinstance(news_stags, str):
            try:
                news_stags = json.loads(news_stags)
            except Exception:
                news_stags = []
        if news_stags:
            news_stag = news_stags[0]
        news_atags = article.get("agent_tags") or []
        if isinstance(news_atags, str):
            try:
                news_atags = json.loads(news_atags)
            except Exception:
                news_atags = []
        result = analyze_content_for_hygiene(
            content_type="news", content_id=article["id"],
            title=article["title"] or "", created_at=article["created_at"],
            strategy_tag=news_stag, agent_tags=news_atags,
            text=article.get("summary", "") or "", current_status=article["hygiene_status"] or "active",
        )
        if result["action"] in ("demote", "archive") and not dry_run:
            try:
                cur.execute("UPDATE news_articles SET hygiene_status='archived', demoted_at=NOW(), demoted_reason=%s WHERE id=%s",
                            (result["reason"], article["id"]))
                news_demoted += 1
            except Exception:
                conn.rollback()
    stats["archived"] += news_demoted
    if not dry_run:
        conn.commit()
    print(f"  Archived {news_demoted} old news articles")

    # Step 5: Regulatory supersession
    print(f"\n  Step 4: Checking superseded regulatory data...")
    supersessions = detect_superseded_regulatory_data()
    for s in supersessions:
        if not dry_run:
            try:
                cur.execute("""INSERT INTO iris_hygiene_log (content_type, content_id, content_title, action,
                               previous_status, new_status, reason, confidence, run_id)
                               VALUES ('regulatory_rule',%s,%s,'flag_superseded','active','superseded',%s,0.99,%s)""",
                            (s["old_id"], f"{s['rule_type']} ({s['old_year']})",
                             f"Superseded by {s['new_year']} version", run_id))
                conn.commit()
            except Exception:
                conn.rollback()
        stats["superseded"] += 1
        print(f"  Superseded: {s['rule_type']} {s['old_year']} -> {s['new_year']}")

    # Step 6: Year-specific YouTube transcripts
    print(f"\n  Step 5: Checking year-specific YouTube transcripts...")
    try:
        cur.execute("""SELECT id, title, ingested_at, hygiene_status, quality_score
                       FROM youtube_transcripts
                       WHERE (hygiene_status = 'active' OR hygiene_status IS NULL)
                         AND is_year_specific = true AND year_referenced > 0
                         AND year_referenced < EXTRACT(year FROM NOW()) - 1
                       ORDER BY year_referenced ASC LIMIT 100""")
        stale_yt = cur.fetchall()
    except Exception:
        stale_yt = []
        conn.rollback()
    for t in stale_yt:
        result = analyze_content_for_hygiene(
            content_type="youtube", content_id=t["id"], title=t["title"] or "",
            created_at=t["ingested_at"], strategy_tag="investment_general", agent_tags=[],
            current_status=t["hygiene_status"] or "active",
        )
        if result["action"] == "demote" and not dry_run:
            cur.execute("UPDATE youtube_transcripts SET hygiene_status='demoted', demoted_at=NOW(), demoted_reason=%s WHERE id=%s",
                        (result["reason"], t["id"]))
            stats["demoted"] += 1
    if not dry_run:
        conn.commit()

    elapsed = int(time.time() - started)
    if not dry_run and run_id:
        cur.execute("UPDATE iris_run_log SET elapsed_seconds=%s WHERE id=%s", (elapsed, run_id))
        conn.commit()
    conn.close()

    # Telegram summary
    summary = (
        f"Iris Hygiene {'(DRY RUN) ' if dry_run else ''}{datetime.now(timezone.utc).strftime('%b %d')}\n"
        f"Demoted: {stats['demoted']} | Archived: {stats['archived']}\n"
        f"Superseded: {stats['superseded']} regulatory rules\n"
        f"Escalated: {stats['escalated_to_john']} | Kept: {stats['kept']}\n"
        f"Time: {elapsed}s"
    )
    if not dry_run:
        _send_telegram_msg(summary)

    print(f"\n{'='*60}")
    print(f"  Hygiene complete in {elapsed}s")
    print(f"  Demoted: {stats['demoted']} | Archived: {stats['archived']}")
    print(f"  Superseded: {stats['superseded']} | Escalated: {stats['escalated_to_john']}")
    print(f"  Kept: {stats['kept']} | Errors: {stats['errors']}")
    print(f"{'='*60}\n")
    return stats


def handle_iris_hygiene_command(subcommand, args_str):
    """Handle 'iris hygiene <subcommand>' Telegram commands."""
    import psycopg2.extras

    # iris hygiene status
    if subcommand in ("", "status"):
        conn, cur = _get_conn_dict()
        cur.execute("""SELECT count(*) as total_pending,
                              count(CASE WHEN expires_at < NOW() + INTERVAL '2 days' THEN 1 END) as expiring_soon
                       FROM iris_hygiene_pending WHERE status='pending_john'""")
        row = cur.fetchone()
        cur.execute("""SELECT id, content_type, content_title, proposed_action, reason, confidence, expires_at
                       FROM iris_hygiene_pending WHERE status='pending_john'
                       ORDER BY confidence DESC, expires_at ASC LIMIT 5""")
        pending = cur.fetchall()
        conn.close()
        if not row or row["total_pending"] == 0:
            return "Iris Hygiene: No pending decisions. All clean."
        lines = [f"Iris Hygiene — {row['total_pending']} decisions pending",
                 f"({row['expiring_soon']} expiring within 2 days)", ""]
        for p in pending:
            exp_days = (p["expires_at"] - datetime.now(p["expires_at"].tzinfo)).days if p["expires_at"] else 0
            lines.append(f"#{p['id']} [{(p['proposed_action'] or '').upper()}] "
                         f"{(p['content_title'] or '')[:40]}\n"
                         f"  {(p['reason'] or '')[:60]} | Conf: {(p['confidence'] or 0)*100:.0f}% | {exp_days}d left")
        lines.append(f"\niris hygiene approve/reject/defer <id>")
        return "\n".join(lines)

    # iris hygiene approve <id>
    if subcommand == "approve" and args_str.strip().isdigit():
        pid = int(args_str.strip())
        conn, cur = _get_conn_dict()
        cur.execute("SELECT content_type, content_id, content_title, proposed_action FROM iris_hygiene_pending WHERE id=%s AND status='pending_john'", (pid,))
        p = cur.fetchone()
        if not p:
            conn.close()
            return f"Iris: Pending item #{pid} not found."
        table_map = {"news": "news_articles", "news_article": "news_articles",
                     "youtube": "youtube_transcripts", "youtube_transcript": "youtube_transcripts"}
        table = table_map.get(p["content_type"], "intelligence_whiteboard")
        new_status = "archived" if p["proposed_action"] == "archive" else "demoted"
        cur.execute(f"UPDATE {table} SET hygiene_status=%s, demoted_at=NOW(), demoted_reason='John approved via Telegram' WHERE id=%s",
                    (new_status, p["content_id"]))
        cur.execute("UPDATE iris_hygiene_pending SET status='approved', resolved_at=NOW() WHERE id=%s", (pid,))
        cur.execute("""INSERT INTO iris_hygiene_log (content_type, content_id, content_title, action,
                       previous_status, new_status, reason, confidence, escalated_to_john, john_decision, john_decided_at)
                       VALUES (%s,%s,%s,%s,'active',%s,'John approved via Telegram',0.99,true,'approved',NOW())""",
                    (p["content_type"], p["content_id"], p["content_title"], new_status, new_status))
        conn.commit()
        conn.close()
        return f"Iris: #{pid} '{(p['content_title'] or '')[:40]}' has been {new_status}."

    # iris hygiene reject <id>
    if subcommand == "reject" and args_str.strip().isdigit():
        pid = int(args_str.strip())
        conn, cur = _get_conn_dict()
        cur.execute("UPDATE iris_hygiene_pending SET status='rejected', resolved_at=NOW() WHERE id=%s AND status='pending_john' RETURNING content_title", (pid,))
        row = cur.fetchone()
        conn.commit()
        conn.close()
        if row:
            return f"Iris: #{pid} kept active. Re-evaluate in 30 days."
        return f"Iris: Item #{pid} not found."

    # iris hygiene defer <id>
    if subcommand == "defer" and args_str.strip().isdigit():
        pid = int(args_str.strip())
        conn, cur = _get_conn_dict()
        cur.execute("UPDATE iris_hygiene_pending SET expires_at=NOW()+INTERVAL '7 days' WHERE id=%s AND status='pending_john' RETURNING content_title", (pid,))
        row = cur.fetchone()
        conn.commit()
        conn.close()
        if row:
            return f"Iris: #{pid} deferred 7 more days."
        return f"Iris: Item #{pid} not found."

    # iris hygiene preview / dry-run
    if subcommand in ("dry-run", "preview", "check"):
        st = run_weekly_hygiene(dry_run=True)
        return (f"Iris Hygiene Preview (no changes):\n"
                f"Would demote: {st['demoted']} | archive: {st['archived']}\n"
                f"Would escalate: {st['escalated_to_john']} | supersede: {st['superseded']}\n\n"
                f"Run live: iris hygiene run")

    # iris hygiene run
    if subcommand == "run":
        import threading
        threading.Thread(target=lambda: run_weekly_hygiene(dry_run=False), daemon=True).start()
        return "Iris: Weekly hygiene starting in background (~2 min). Results via Telegram."

    return ("Iris Hygiene commands:\n"
            "  iris hygiene status    — pending decisions\n"
            "  iris hygiene approve N — approve demotion\n"
            "  iris hygiene reject N  — keep active\n"
            "  iris hygiene defer N   — decide in 7 days\n"
            "  iris hygiene preview   — dry run\n"
            "  iris hygiene run       — force run now")


# ═══════════════════════════════════════════════════════
# MODE 3 — INTELLIGENCE LIBRARIAN (Daily 7:00 AM)
# ═══════════════════════════════════════════════════════

def run_library_audit(dry_run=False):
    """Daily librarian audit: RAG coverage, stale analyses, routing, dupes, gaps."""
    started = time.time()
    print(f"\n{'='*60}")
    print(f"  IRIS — Library Audit {'(DRY RUN)' if dry_run else ''}")
    print(f"{'='*60}\n")

    conn, cur = _get_conn_dict()
    report = {}

    # 3a. RAG Coverage Audit
    print("  [3a] RAG Coverage...")
    try:
        import urllib.request as _ur
        with _ur.urlopen("http://localhost:7777/api/v2/rag/status", timeout=10) as r:
            rag = json.loads(r.read()).get("data", {})
        coverage = rag.get("coverage_pct", 0)
        # pct is None when embeddings outnumber current rows (orphans of pruned rows) — that is
        # NOT low coverage, so exclude those sources rather than re-triggering the indexer.
        low_sources = [s for s, v in rag.get("by_source", {}).items()
                       if v.get("pct") is not None and v["pct"] < 80]
        report["rag_coverage_pct"] = coverage
        report["rag_low_sources"] = low_sources
        print(f"  Coverage: {coverage if coverage is not None else 'n/a (orphaned embeddings)'}% | Low sources: {low_sources or 'none'}")
        if low_sources and not dry_run:
            import subprocess
            subprocess.Popen([str(PROJECT_ROOT / ".venv/bin/python"),
                              str(PROJECT_ROOT / "scripts/rag_indexer.py"),
                              "--source", ",".join(low_sources), "--hours", "48"],
                             cwd=str(PROJECT_ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"  Triggered indexer for: {', '.join(low_sources)}")
    except Exception as e:
        print(f"  RAG check failed: {e}")
        report["rag_error"] = str(e)

    # 3b. Stale Analysis Detection
    print("\n  [3b] Stale Analyses...")
    try:
        cur.execute("""
            SELECT h.symbol, h.name,
                   MAX(war.created_at) as last_analysis,
                   EXTRACT(days FROM NOW() - MAX(war.created_at)) as days_since
            FROM (SELECT DISTINCT symbol, name FROM (
                SELECT symbol, name FROM json_array_elements(
                    (SELECT holdings::json FROM (SELECT holdings::text FROM
                     json_each_text((SELECT data::json FROM
                     (SELECT read_text FROM (VALUES (pg_read_file(%s))) v(read_text)) t(data)
                     )) je(k,v) WHERE k='holdings') sub(holdings)
                    )) WITH ORDINALITY AS h(val, idx),
                    json_to_record(h.val) AS x(symbol text, name text)
                WHERE x.symbol IS NOT NULL AND x.symbol != 'CASH'
            ) sq) h
            LEFT JOIN watchlist_agent_results war ON war.symbol = h.symbol
            GROUP BY h.symbol, h.name
            HAVING MAX(war.created_at) IS NULL OR MAX(war.created_at) < NOW() - INTERVAL '7 days'
            ORDER BY days_since DESC NULLS FIRST
        """, (str(PROJECT_ROOT / "data/portfolios/state/holdings.json"),))
        stale = cur.fetchall()
    except Exception:
        conn.rollback()
        # Simpler fallback query
        cur.execute("""
            SELECT DISTINCT na.symbol, na.symbol as name,
                   MAX(war.created_at) as last_analysis,
                   EXTRACT(days FROM NOW() - MAX(war.created_at))::int as days_since
            FROM news_articles na
            LEFT JOIN watchlist_agent_results war ON war.symbol = na.symbol
            WHERE na.symbol IS NOT NULL AND na.symbol != ''
            GROUP BY na.symbol
            HAVING MAX(war.created_at) IS NULL OR MAX(war.created_at) < NOW() - INTERVAL '7 days'
            ORDER BY days_since DESC NULLS FIRST LIMIT 20
        """)
        stale = cur.fetchall()

    report["stale_symbols"] = len(stale)
    if stale:
        print(f"  {len(stale)} symbols with stale/no analysis:")
        for s in stale[:10]:
            days = int(s["days_since"]) if s.get("days_since") else "never"
            print(f"    {s['symbol']}: last analyzed {days} days ago" if days != "never" else f"    {s['symbol']}: never analyzed")

    # 3c. Routing Audit
    print("\n  [3c] Intelligence Routing...")
    try:
        cur.execute("""
            SELECT count(*) as n FROM youtube_transcripts
            WHERE quality_score >= 55 AND promoted_to_whiteboard IS NOT TRUE
              AND (agent_tags IS NULL OR agent_tags = '[]'::jsonb)
        """)
        unrouted = cur.fetchone()["n"]
        report["unrouted_transcripts"] = unrouted
        print(f"  Unrouted high-quality transcripts: {unrouted}")

        cur.execute("""
            SELECT count(*) as n FROM news_articles
            WHERE retirement_relevance = 'high'
              AND created_at > NOW() - INTERVAL '7 days'
              AND symbol NOT IN (SELECT DISTINCT symbol FROM watchlist_agent_results WHERE created_at > NOW() - INTERVAL '7 days')
        """)
        unseen = cur.fetchone()["n"]
        report["unseen_high_relevance"] = unseen
        print(f"  High-relevance news unseen by agents: {unseen}")
    except Exception as e:
        print(f"  Routing audit error: {e}")

    # 3d. Duplicate Detection
    print("\n  [3d] Duplicate Detection...")
    try:
        cur.execute("""
            SELECT LEFT(title, 80) as title, count(*) as cnt, array_agg(DISTINCT source) as sources
            FROM news_articles
            WHERE created_at > NOW() - INTERVAL '30 days'
            GROUP BY LEFT(title, 80)
            HAVING count(*) > 1
            ORDER BY cnt DESC LIMIT 10
        """)
        dupes = cur.fetchall()
        report["duplicate_articles"] = len(dupes)
        total_dupe_rows = sum(d["cnt"] - 1 for d in dupes)
        print(f"  {len(dupes)} duplicate title groups ({total_dupe_rows} extra rows)")
        for d in dupes[:5]:
            print(f"    [{d['cnt']}x] {d['title'][:60]}")
    except Exception as e:
        conn.rollback()
        print(f"  Dupe check error: {e}")

    # 3e. Content Gap Alerts (reads from topic_monitor table)
    print("\n  [3e] Content Gaps...")
    try:
        gap_categories = []
        # Pull topics from topic_monitor DB table (DB-driven, not hardcoded)
        try:
            cur.execute("SELECT topic_id, max_age_days, min_articles FROM topic_monitor WHERE enabled = true")
            topic_rows = cur.fetchall()
        except Exception:
            # Fallback to hardcoded if topic_monitor table doesn't exist yet
            topic_rows = [(cat, 30, 3) for cat in [
                "disability_retirement", "ssdi", "trust_estate", "roth_conversion",
                "retirement_planning", "tax_planning", "dividend_income"]]
        for row in topic_rows:
            cat = row["topic_id"] if isinstance(row, dict) else row[0]
            max_age = row["max_age_days"] if isinstance(row, dict) else row[1]
            min_arts = row["min_articles"] if isinstance(row, dict) else row[2]
            cur.execute("SELECT count(*) as n FROM news_articles WHERE strategy_type=%s AND created_at > NOW() - INTERVAL '%s days'", (cat, max_age))
            cnt = cur.fetchone()["n"]
            if cnt < min_arts:
                gap_categories.append({"category": cat, "articles_30d": cnt, "min_required": min_arts})
                print(f"  GAP: {cat} — only {cnt} articles in last {max_age} days (need {min_arts})")
        report["content_gaps"] = gap_categories
        if not gap_categories:
            print(f"  No critical gaps")
    except Exception as e:
        print(f"  Gap check error: {e}")

    # 3e.1 AUTO-REMEDIATION: trigger topic_ingestion for gap categories
    remediation_results = {}
    if not dry_run and gap_categories:
        print("\n  [3e.1] Auto-Remediation: running topic_ingestion for gaps...")
        try:
            import subprocess
            gap_topic_ids = [g["category"] for g in gap_categories if g.get("articles_30d", 0) < 3]
            for topic_id in gap_topic_ids:
                print(f"    Triggering topic_ingestion --topic {topic_id} --gaps-only ...")
                result = subprocess.run(
                    [sys.executable, str(Path(__file__).parent / "topic_ingestion.py"),
                     "--topic", topic_id],
                    capture_output=True, text=True, timeout=180,
                    cwd=str(Path(__file__).resolve().parent.parent)
                )
                # Parse output for saved counts
                saved_articles = 0
                saved_transcripts = 0
                for line in result.stdout.splitlines():
                    if "Articles saved:" in line:
                        try:
                            saved_articles = int(line.split("Articles saved:")[1].strip().split()[0])
                        except (ValueError, IndexError):
                            pass
                    if "Transcripts saved:" in line:
                        try:
                            saved_transcripts = int(line.split("Transcripts saved:")[1].strip().split()[0])
                        except (ValueError, IndexError):
                            pass
                remediation_results[topic_id] = {
                    "articles": saved_articles, "transcripts": saved_transcripts
                }
                total_remediated = saved_articles + saved_transcripts
                if total_remediated > 0:
                    print(f"    REMEDIATED {topic_id}: {saved_articles}a + {saved_transcripts}t")
                else:
                    print(f"    No new content found for {topic_id}")
                if result.returncode != 0 and result.stderr:
                    print(f"    stderr: {result.stderr[:200]}")
        except Exception as e:
            print(f"    Remediation error: {e}")
        report["remediation_results"] = remediation_results

    # 3f. Notify agents of critical content gaps
    CRITICAL_GAP_AGENTS = {
        "ssdi": ["alex"], "disability_retirement": ["alex"],
        "trust_estate": ["alex", "tax_agent"], "roth_conversion": ["alex", "tax_agent"],
        "tax_planning": ["tax_agent", "maria"], "retirement_planning": ["alex", "steph"],
        "dividend_income": ["steph", "maria"], "macro_fed": ["maria", "risk_agent"],
    }
    gap_events_fired = 0
    if not dry_run and report.get("content_gaps"):
        print("\n  [3f] Notifying agents of content gaps...")
        conn2, cur2 = _get_conn_dict()
        for gap in report["content_gaps"]:
            cat = gap["category"]
            agents = CRITICAL_GAP_AGENTS.get(cat, [])
            if agents and gap.get("articles_30d", 0) == 0:
                try:
                    cur2.execute("""
                        INSERT INTO agent_event_queue (event_type, symbol, agents_to_notify, priority, trigger_data, status, created_at)
                        VALUES ('CONTENT_GAP', %s, %s, 'normal', %s, 'pending', NOW())
                    """, (f"CATEGORY:{cat}", agents,
                          json.dumps({"category": cat, "articles_30d": gap.get("articles_30d", 0),
                                      "youtube_30d": gap.get("youtube_30d", 0),
                                      "message": f"No fresh {cat.replace('_',' ')} content in 30 days. Rely on RAG embeddings + gov sources."})))
                    gap_events_fired += 1
                    print(f"    CONTENT_GAP event for {cat} → {agents}")
                except Exception as e:
                    print(f"    Event error for {cat}: {e}")
                    conn2.rollback()
        conn2.commit()
        conn2.close()
        report["gap_events_fired"] = gap_events_fired

    # 3g. Auto-flag clear duplicates
    if not dry_run:
        print("\n  [3g] Flagging clear duplicates...")
        try:
            conn3, cur3 = _get_conn_dict()
            cur3.execute("""
                UPDATE news_articles SET is_duplicate = TRUE
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY LEFT(LOWER(TRIM(title)), 60)
                            ORDER BY relevance_score DESC NULLS LAST, created_at ASC
                        ) as rn
                        FROM news_articles WHERE created_at > NOW() - INTERVAL '90 days'
                    ) sq WHERE rn > 1
                ) AND NOT COALESCE(is_duplicate, FALSE)
            """)
            flagged_dupes = cur3.rowcount
            conn3.commit()
            conn3.close()
            report["dupes_flagged"] = flagged_dupes
            print(f"    Flagged {flagged_dupes} duplicate articles")
        except Exception as e:
            print(f"    Dedup error: {e}")

    conn.close()
    elapsed = int(time.time() - started)
    print(f"\n{'='*60}")
    print(f"  Library audit complete in {elapsed}s")
    print(f"{'='*60}\n")

    # Telegram summary
    if not dry_run:
        summary = (
            f"Iris Library Audit\n"
            f"RAG: {report.get('rag_coverage_pct', '?')}% coverage\n"
            f"Stale: {report.get('stale_symbols', 0)} symbols need refresh\n"
            f"Unrouted: {report.get('unrouted_transcripts', 0)} transcripts\n"
            f"Dupes: {report.get('duplicate_articles', 0)} groups ({report.get('dupes_flagged', 0)} auto-flagged)\n"
            f"Gaps: {len(report.get('content_gaps', []))} thin ({report.get('gap_events_fired', 0)} agent events fired)"
        )
        _send_telegram_msg(summary)
        # Critical gap Telegram alerts (with remediation status)
        for gap in report.get("content_gaps", []):
            cat = gap["category"]
            if gap.get("articles_30d", 0) == 0 and cat in ("ssdi", "disability_retirement", "trust_estate"):
                remed = report.get("remediation_results", {}).get(cat, {})
                remed_a = remed.get("articles", 0)
                remed_t = remed.get("transcripts", 0)
                if remed_a + remed_t > 0:
                    _send_telegram_msg(
                        f"Iris Library Alert: {cat.replace('_',' ')} — was 0 in 30 days. "
                        f"Auto-remediated: {remed_a} articles + {remed_t} transcripts ingested."
                    )
                else:
                    _send_telegram_msg(
                        f"Iris Library Alert: {cat.replace('_',' ')} — 0 articles + 0 YouTube in 30 days. "
                        f"Auto-remediation found no new content. Agents notified."
                    )

        # Weekly Sunday: channel recommendations for gaps
        if datetime.now(timezone.utc).weekday() == 6:  # Sunday
            recs = []
            for gap in report.get("content_gaps", []):
                cat = gap["category"]
                try:
                    prompt = f"/no_think Suggest 2 real YouTube channels covering {cat.replace('_',' ')} for a disability retirement investor. Just channel names, one per line."
                    result = llm_generate(prompt, timeout=20)
                    if result:
                        recs.append(f"  {cat.replace('_',' ')}: {result.strip()[:100]}")
                except Exception:
                    recs.append(f"  {cat.replace('_',' ')}: (LLM unavailable)")
            if recs:
                _send_telegram_msg("Iris Weekly Content Recommendations\n\nGaps found:\n" + "\n".join(recs) + "\n\nAdd channels: /v3/intelligence → YouTube → + Channel")

    # 3h. Intelligence Entity Curation
    print("\n  [3h] Intelligence Entity Curation...")
    try:
        ier_summary = curate_intelligence_entities(conn if not conn.closed else _get_conn_dict()[0])
        report["ier_summary"] = ier_summary
        print(f"  {ier_summary}")
    except Exception as e:
        print(f"  Entity curation error: {e}")
        report["ier_error"] = str(e)

    return report


def curate_intelligence_entities(conn):
    """
    Iris entity curation — audits all intelligence_entities for freshness,
    coverage, and agent staleness. Writes iris_freshness/iris_coverage back.
    Returns summary string.
    """
    from datetime import datetime as _dt, timezone as _tz
    try:
        from intelligence_entity_manager import upsert_entity
    except ImportError:
        from scripts.intelligence_entity_manager import upsert_entity

    cur = conn.cursor()
    now = _dt.now(_tz.utc)

    issues = {'critical': [], 'stale': [], 'thin': []}

    cur.execute("SELECT * FROM intelligence_entities WHERE active = true")
    cols = [d[0] for d in cur.description]
    entities = [dict(zip(cols, row)) for row in cur.fetchall()]

    for entity in entities:
        eid = entity['entity_id']
        etype = entity['entity_type']
        freshness = 'FRESH'
        coverage = 'ADEQUATE'
        notes = []
        action = None

        # === FRESHNESS CHECKS ===
        if etype == 'market':
            if entity.get('price_updated_at'):
                price_age_hr = (now - entity['price_updated_at']).total_seconds() / 3600
                if price_age_hr > 24:
                    freshness = 'STALE'
                    notes.append(f'Price {price_age_hr:.0f}hr old')
                    issues['stale'].append(eid)
                elif price_age_hr > 6:
                    freshness = 'AGING'
            else:
                freshness = 'CRITICAL'
                notes.append('No price data')
                issues['critical'].append(eid)
                action = 'Run finviz_enrichment for this symbol'
        else:  # subject
            if entity.get('thresholds_updated'):
                thresh_age_days = (now - entity['thresholds_updated']).total_seconds() / 86400
                if thresh_age_days > 90:
                    freshness = 'CRITICAL'
                    notes.append(f'Thresholds {thresh_age_days:.0f}d old')
                    issues['critical'].append(eid)
                    action = f'Run alex_gov_research --refresh for {eid}'
                elif thresh_age_days > 30:
                    freshness = 'STALE'
                    notes.append(f'Thresholds {thresh_age_days:.0f}d old')
                    issues['stale'].append(eid)
            else:
                if not entity.get('john_impact'):
                    freshness = 'CRITICAL'
                    notes.append('No threshold data')
                    issues['critical'].append(eid)

        # === COVERAGE CHECKS ===
        rag_count = entity.get('rag_item_count', 0) or 0
        if rag_count == 0:
            coverage = 'EMPTY'
            notes.append('No RAG coverage')
            issues['thin'].append(eid)
        elif rag_count < 3:
            coverage = 'THIN'
            notes.append(f'Only {rag_count} RAG items')
            issues['thin'].append(eid)
        elif rag_count > 20:
            coverage = 'RICH'

        # Write Iris assessment back
        upsert_entity(conn, eid, etype, {
            'iris_freshness': freshness,
            'iris_coverage': coverage,
            'iris_notes': ' | '.join(notes) if notes else None,
            'iris_action_needed': action,
            'iris_last_audit': now,
        }, source='iris_librarian')

    # Summary
    if issues['critical'] or issues['stale']:
        parts = [f"[IRIS ENTITY AUDIT] {len(entities)} entities"]
        if issues['critical']:
            parts.append(f"CRITICAL({len(issues['critical'])}): {', '.join(issues['critical'][:5])}")
        if issues['stale']:
            parts.append(f"Stale({len(issues['stale'])}): {', '.join(issues['stale'][:5])}")
        if issues['thin']:
            parts.append(f"Thin({len(issues['thin'])}): {', '.join(issues['thin'][:5])}")
        return ' | '.join(parts)

    return f"[IRIS ENTITY AUDIT] {len(entities)} entities — all OK"


def get_library_status():
    """GET /api/v2/iris/library-status — RAG + routing audit summary."""
    conn, cur = _get_conn_dict()
    result = {}

    # RAG coverage — query DB directly (HTTP self-call deadlocks single-threaded api_v2)
    try:
        cur.execute("SELECT count(*) as n FROM content_embeddings")
        total_emb = int((cur.fetchone() or {}).get("n", 0))
        sources = {
            "news": "news_articles", "youtube": "youtube_transcripts", "social_post": "social_posts",
            "sec_form4": "sec_form4", "hermes_research": "hermes_research_intelligence",
        }
        by_source = {}
        total_rows = 0
        total_embedded = 0
        for src, tbl in sources.items():
            if src == "hermes_research":
                cur.execute("SELECT count(*) as n FROM hermes_research_intelligence WHERE status='promoted'")
            else:
                cur.execute(f"SELECT count(*) as n FROM {tbl}")
            t = int((cur.fetchone() or {}).get("n", 0))
            cur.execute("SELECT count(*) as n FROM content_embeddings WHERE source_type=%s", (src,))
            e = int((cur.fetchone() or {}).get("n", 0))
            by_source[src] = {"total": t, "embedded": e, "pct": round(e / max(t, 1) * 100, 1)}
            total_rows += t
            total_embedded += e
        cur.execute("SELECT max(created_at) as t FROM content_embeddings")
        last = (cur.fetchone() or {}).get("t")
        result["rag"] = {
            "total_rows": total_rows, "total_embedded": total_embedded,
            "coverage_pct": round(total_embedded / max(total_rows, 1) * 100, 1),
            "by_source": by_source, "total_embeddings": total_emb,
            "last_indexed": str(last)[:19] if last else None,
        }
    except Exception:
        result["rag"] = {"coverage_pct": 0}

    # Stale symbols
    try:
        cur.execute("""
            SELECT symbol, MAX(created_at) as last_analysis,
                   EXTRACT(days FROM NOW() - MAX(created_at))::int as days_since
            FROM watchlist_agent_results GROUP BY symbol
            HAVING MAX(created_at) < NOW() - INTERVAL '7 days'
            ORDER BY days_since DESC LIMIT 20
        """)
        result["stale_symbols"] = [dict(r) for r in cur.fetchall()]
    except Exception:
        result["stale_symbols"] = []

    # Content gaps
    try:
        gaps = []
        for cat in ["disability_retirement", "ssdi", "trust_estate", "roth_conversion",
                     "retirement_planning", "tax_planning", "dividend_income"]:
            cur.execute("SELECT count(*) as n FROM news_articles WHERE strategy_type=%s AND created_at > NOW() - INTERVAL '30 days'", (cat,))
            cnt = cur.fetchone()["n"]
            if cnt < 3:
                gaps.append({"category": cat, "articles_30d": cnt})
        result["content_gaps"] = gaps
    except Exception:
        result["content_gaps"] = []

    # Duplicates
    try:
        cur.execute("SELECT count(*) as n FROM (SELECT LEFT(title,80), count(*) FROM news_articles WHERE created_at > NOW()-INTERVAL '30 days' GROUP BY LEFT(title,80) HAVING count(*)>1) sq")
        result["duplicate_groups"] = cur.fetchone()["n"]
    except Exception:
        result["duplicate_groups"] = 0

    conn.close()
    return result


def get_stale_symbols():
    """GET /api/v2/iris/stale-symbols — Holdings not analyzed in >7 days."""
    conn, cur = _get_conn_dict()
    try:
        cur.execute("""
            SELECT symbol, MAX(created_at) as last_analysis,
                   EXTRACT(days FROM NOW() - MAX(created_at))::int as days_since,
                   count(*) as total_analyses
            FROM watchlist_agent_results
            GROUP BY symbol
            HAVING MAX(created_at) < NOW() - INTERVAL '7 days'
            ORDER BY days_since DESC
        """)
        return [{"symbol": r["symbol"], "last_analysis": str(r["last_analysis"])[:16],
                 "days_since": r["days_since"], "total_analyses": r["total_analyses"]}
                for r in cur.fetchall()]
    except Exception:
        return []
    finally:
        conn.close()


def get_content_gaps():
    """GET /api/v2/iris/content-gaps — Categories with thin recent content."""
    conn, cur = _get_conn_dict()
    try:
        gaps = []
        for cat in ["disability_retirement", "ssdi", "trust_estate", "roth_conversion",
                     "retirement_planning", "tax_planning", "dividend_income",
                     "etf_indexing", "macro_fed", "bond_income"]:
            cur.execute("SELECT count(*) as n FROM news_articles WHERE strategy_type=%s AND created_at > NOW()-INTERVAL '30 days'", (cat,))
            cnt = cur.fetchone()["n"]
            cur.execute("SELECT count(*) as n FROM youtube_transcripts yt JOIN youtube_channels yc ON yc.channel_name=yt.channel_name WHERE yc.category=%s AND yt.ingested_at > NOW()-INTERVAL '30 days'", (cat,))
            yt_cnt = cur.fetchone()["n"]
            gaps.append({"category": cat, "news_30d": cnt, "youtube_30d": yt_cnt, "thin": cnt < 3 and yt_cnt < 5})
        return [g for g in gaps if g["thin"]]
    except Exception:
        return []
    finally:
        conn.close()


def run_discovery_mode(send_telegram=False):
    """Mode 4: Identify symbols mentioned heavily in intelligence but not on watchlist."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Find symbols mentioned in YouTube/news matched_keywords that aren't on watchlist or in positions
    cur.execute("""
        WITH keyword_mentions AS (
            SELECT kw, count(*) as mention_count,
                   array_agg(DISTINCT content_category) FILTER (WHERE content_category IS NOT NULL) as themes,
                   max(ingested_at) as latest_mention
            FROM youtube_transcripts,
                 jsonb_array_elements_text(matched_keywords) as kw
            WHERE ingested_at > NOW() - INTERVAL '30 days'
              AND matched_keywords IS NOT NULL
              AND jsonb_typeof(matched_keywords) = 'array'
            GROUP BY 1
            HAVING count(*) >= 5
        ),
        news_mentions AS (
            SELECT symbol as kw, count(*) as news_count
            FROM news_articles
            WHERE created_at > NOW() - INTERVAL '30 days'
              AND symbol IS NOT NULL
            GROUP BY 1
            HAVING count(*) >= 3
        )
        SELECT k.kw as symbol, k.mention_count,
               COALESCE(n.news_count, 0) as news_mentions,
               k.themes, k.latest_mention
        FROM keyword_mentions k
        LEFT JOIN news_mentions n ON k.kw = n.kw
        WHERE k.kw ~ '^[A-Z]{1,5}$'
          AND k.kw NOT IN (SELECT symbol FROM watchlist_items)
          AND k.kw NOT IN ('ETF', 'NYSE', 'CEO', 'IPO', 'SEC', 'FED', 'GDP', 'CPI', 'FOMC', 'AI', 'US', 'USA', 'IRA')
        ORDER BY k.mention_count + COALESCE(n.news_count, 0) DESC
        LIMIT 10
    """)
    candidates = cur.fetchall()

    if not candidates:
        print("[iris-discovery] No new symbol candidates found.")
        conn.close()
        return {"candidates": 0}

    proposals_created = 0
    for c in candidates:
        total = c["mention_count"] + c.get("news_mentions", 0)
        themes = c.get("themes") or []
        cur.execute("""
            INSERT INTO iris_taxonomy_proposals
                (proposal_type, target, current_state, proposed_state, reasoning,
                 confidence, status, created_at)
            VALUES ('discovery', %s, '{}'::jsonb, %s, %s, %s, 'pending', NOW())
            ON CONFLICT DO NOTHING
        """, [
            c["symbol"],
            json.dumps({"action": "add_to_watchlist", "themes": themes[:5]}),
            f"Iris detected {c['mention_count']} YouTube + {c.get('news_mentions', 0)} news mentions in 30 days across {len(themes)} themes",
            min(0.9, 0.5 + (total / 50)),
        ])
        proposals_created += 1

    conn.commit()
    print(f"[iris-discovery] {proposals_created} discovery proposals created from {len(candidates)} candidates")

    if send_telegram and candidates:
        try:
            sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from telegram_alert import send_telegram as _tg
            msg = f"\U0001f50d *Iris Discovery Mode*\n\nFound {len(candidates)} potential watchlist additions:\n"
            for c in candidates[:5]:
                total = c["mention_count"] + c.get("news_mentions", 0)
                themes = c.get("themes") or []
                msg += f"\u2022 {c['symbol']} \u2014 {total} mentions ({', '.join(str(t) for t in themes[:2])})\n"
            msg += f"\nApprove via: `iris approve <id>`"
            _tg(msg)
        except Exception as e:
            print(f"[iris-discovery] Telegram failed: {e}")

    conn.close()
    return {"candidates": len(candidates), "proposals_created": proposals_created}


def run_freshness_validation():
    """Iris librarian duty: validate all data products and cron health.
    Creates alerts for stale products, missed crons, and zero-output jobs."""
    import urllib.request
    print("[iris] Running data freshness validation...")

    try:
        # Check data product health via API
        with urllib.request.urlopen("http://localhost:7777/api/v2/data-product-health", timeout=10) as r:
            dp = json.loads(r.read()).get("data", {})
        products = dp.get("products", [])
        stale = [p for p in products if p.get("status") == "stale" and not p.get("weekend_market_closed")]
        if stale:
            print(f"  [freshness] {len(stale)} stale products (non-weekend):")
            for s in stale:
                print(f"    {s['product']}: {s.get('age_hours',0):.0f}h old (max {s['max_stale_hours']}h) — remedy: {s.get('remediation','?')}")

        # Check pipeline health
        with urllib.request.urlopen("http://localhost:7777/api/v2/pipeline-health-master", timeout=10) as r:
            ph = json.loads(r.read())
        summary = ph.get("summary", ph.get("data", {}).get("summary", {}))
        critical = summary.get("critical", 0)
        never_run = summary.get("never_run", 0)
        if critical > 0 or never_run > 0:
            print(f"  [pipeline] ALERT: {critical} critical, {never_run} never-run stages")

        # Check agent queue backlog
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM watchlist_agent_jobs WHERE status='queued'")
        queued = cur.fetchone()[0]
        if queued > 100:
            print(f"  [queue] ALERT: {queued} queued agent jobs (>100 threshold)")

        # Check research topic freshness
        cur.execute("SELECT COUNT(*) FROM topic_monitor WHERE enabled=true AND last_searched < NOW() - INTERVAL '14 days'")
        stale_topics = cur.fetchone()[0]
        if stale_topics > 0:
            print(f"  [topics] ALERT: {stale_topics} topics stale >14 days")

        conn.close()

        total_issues = len(stale) + (1 if critical > 0 else 0) + (1 if queued > 100 else 0) + (1 if stale_topics > 0 else 0)
        print(f"[iris] Freshness validation complete: {total_issues} issues found")

        # AUTO-REMEDIATE: run the remediation command for stale products
        if stale:
            import subprocess
            for s in stale:
                cmd = s.get("remediation")
                if cmd and not s.get("weekend_market_closed"):
                    print(f"  [auto-remediate] Running: {cmd}")
                    try:
                        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120,
                                                cwd=str(PROJECT_ROOT))
                        if result.returncode == 0:
                            print(f"    ✅ Success")
                        else:
                            print(f"    ❌ Failed (exit {result.returncode}): {result.stderr[:100]}")
                    except subprocess.TimeoutExpired:
                        print(f"    ⏰ Timeout after 120s")
                    except Exception as e:
                        print(f"    ❌ Error: {e}")

        # AUTO-REMEDIATE: drain agent queue if backlogged
        if queued > 100:
            print(f"  [auto-remediate] Draining agent queue ({queued} queued)...")
            try:
                import subprocess
                subprocess.run(
                    [str(PROJECT_ROOT / ".venv/bin/python"), str(PROJECT_ROOT / "scripts/process_watchlist_agent_jobs.py"), "--limit", "5"],
                    capture_output=True, text=True, timeout=180, cwd=str(PROJECT_ROOT))
                print(f"    ✅ Drained 5 jobs")
            except Exception as e:
                print(f"    ❌ Drain error: {e}")

        # Log the run
        log_run("freshness_validation", categories_analyzed=len(products), gaps_found=total_issues)
        return {"issues": total_issues, "stale_products": len(stale), "critical_stages": critical, "queued_jobs": queued, "stale_topics": stale_topics}

    except Exception as e:
        print(f"[iris] Freshness validation error: {e}")
        return {"error": str(e)}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Iris taxonomy intelligence agent")
    p.add_argument("--gaps", action="store_true", help="Gap analysis only")
    p.add_argument("--audit", action="store_true", help="Channel audit only")
    p.add_argument("--freshness", action="store_true", help="Validate data product freshness and cron health")
    p.add_argument("--propose", type=str, help="Manual proposal description")
    p.add_argument("--status", action="store_true", help="Print current status")
    p.add_argument("--hygiene", action="store_true", help="Run weekly hygiene")
    p.add_argument("--hygiene-dry-run", action="store_true", help="Preview hygiene without changes")
    p.add_argument("--library-audit", action="store_true", help="Run library audit")
    p.add_argument("--library-audit-dry-run", action="store_true", help="Preview library audit")
    p.add_argument("--discovery", action="store_true", help="Discovery mode — find symbols in intel not on watchlist")
    p.add_argument("--telegram", action="store_true", help="Send results to Telegram")
    args = p.parse_args()

    if args.freshness:
        run_freshness_validation()
    elif args.discovery:
        run_discovery_mode(send_telegram=args.telegram)
    elif args.library_audit:
        run_library_audit(dry_run=False)
    elif args.library_audit_dry_run:
        run_library_audit(dry_run=True)
    elif args.hygiene:
        run_weekly_hygiene(dry_run=False)
    elif args.hygiene_dry_run:
        run_weekly_hygiene(dry_run=True)
    elif args.gaps:
        run_gap_analysis()
    elif args.audit:
        run_channel_audit()
    elif args.status:
        s = get_iris_status()
        print(json.dumps(s, indent=2, default=str))
    elif args.propose:
        print(f"[iris] Manual proposal not yet implemented: {args.propose}")
    else:
        run_weekly_scan()
