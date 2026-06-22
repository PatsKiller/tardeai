#!/usr/bin/env python3
"""
generate_system_facts.py — Live system facts manifest.

Outputs:
  data/system_facts.json
  data/system_fact_drift.json
  docs/project/SYSTEM_FACTS_LATEST.md
  DB: system_facts_history table
"""
import hashlib, json, os, platform, re, subprocess, sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

def _env(key, default=""):
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.strip().startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"')
    return os.getenv(key, default)

def _get_conn():
    import psycopg2
    return psycopg2.connect(host="localhost", dbname="trade_ai",
                            user="trade_ai", password=_env("DB_PASSWORD"))

def _safe_count(conn, sql):
    try:
        cur = conn.cursor()
        cur.execute(sql)
        return cur.fetchone()[0]
    except Exception:
        return None

def _run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return None


def collect_facts():
    facts = {"generated_at": datetime.now().isoformat()}

    # Runtime
    facts["runtime"] = {
        "hostname": platform.node(),
        "project_root": str(PROJECT_ROOT),
        "python_version": platform.python_version(),
        "git_branch": _run("git rev-parse --abbrev-ref HEAD 2>/dev/null"),
        "git_commit": _run("git rev-parse --short HEAD 2>/dev/null"),
    }

    # Database
    try:
        conn = _get_conn()
        facts["database"] = {
            "connected": True,
            "table_count": _safe_count(conn, "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'"),
            "row_counts": {
                "trade_ai_scans": _safe_count(conn, "SELECT COUNT(*) FROM trade_ai_scans"),
                "paper_trade_proposals": _safe_count(conn, "SELECT COUNT(*) FROM paper_trade_proposals"),
                "paper_trades": _safe_count(conn, "SELECT COUNT(*) FROM paper_trades"),
                "watchlist_agent_results": _safe_count(conn, "SELECT COUNT(*) FROM watchlist_agent_results"),
                "news_articles": _safe_count(conn, "SELECT COUNT(*) FROM news_articles"),
                "topic_monitor": _safe_count(conn, "SELECT COUNT(*) FROM topic_monitor WHERE enabled=true"),
                "content_embeddings": _safe_count(conn, "SELECT COUNT(*) FROM content_embeddings"),
                "pipeline_stages": _safe_count(conn, "SELECT COUNT(*) FROM pipeline_stages WHERE active=true"),
                "pipeline_runs": _safe_count(conn, "SELECT COUNT(*) FROM pipeline_runs"),
                "config_documents": _safe_count(conn, "SELECT COUNT(*) FROM config_documents WHERE active=true"),
                "content_entity_links": _safe_count(conn, "SELECT COUNT(*) FROM content_entity_links"),
                "blocked_content": _safe_count(conn, "SELECT COUNT(*) FROM blocked_content"),
            },
            "pending_proposals": _safe_count(conn, "SELECT COUNT(*) FROM paper_trade_proposals WHERE status IN ('PROPOSED','ENRICHING','SCORED')"),
            "open_paper_trades": _safe_count(conn, "SELECT COUNT(*) FROM paper_trades WHERE status='open'"),
            "closed_paper_trades": _safe_count(conn, "SELECT COUNT(*) FROM paper_trades WHERE status='closed'"),
        }
        conn.close()
    except Exception as e:
        facts["database"] = {"connected": False, "error": str(e)[:100]}

    # Codebase
    facts["codebase"] = {
        "python_script_count": int(_run("find scripts/ -name '*.py' | wc -l") or 0),
        "sql_migration_count": int(_run("find sql/migrations/ -name '*.sql' | wc -l") or 0),
        "yaml_config_count": int(_run("find config/ assets/ -name '*.yaml' -o -name '*.yml' | wc -l") or 0),
        "json_config_count": int(_run("find config/ -name '*.json' | wc -l") or 0),
        "strategy_count": int(_run("find config/strategies/ -name '*.yaml' ! -name '*schema*' ! -name '*shared*' | wc -l") or 0),
        "frontend_page_count": int(_run("find apps/command-center-v2/src/pages -name '*.tsx' 2>/dev/null | wc -l") or 0),
        "react_component_count": int(_run("find apps/command-center-v2/src -name '*.tsx' 2>/dev/null | wc -l") or 0),
        "cron_job_count": int(_run("crontab -l 2>/dev/null | grep -v '^#' | grep -v '^$' | wc -l") or 0),
    }

    # LLM
    ollama_available = False
    ollama_models = []
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as resp:
            d = json.loads(resp.read())
            ollama_models = [m["name"] for m in d.get("models", [])]
            ollama_available = True
    except Exception:
        pass
    facts["llm"] = {
        "ollama_available": ollama_available,
        "ollama_models": ollama_models,
        "cloud_providers_configured": {
            "anthropic": bool(_env("ANTHROPIC_API_KEY")),
            "openai": bool(_env("OPENAI_API_KEY")),
            "xai": bool(_env("XAI_API_KEY", _env("GROK_API_KEY"))),
        }
    }

    # Topic intelligence
    try:
        conn = _get_conn()
        facts["topic_intelligence"] = {
            "active_topics": _safe_count(conn, "SELECT COUNT(*) FROM topic_monitor WHERE enabled=true"),
            "approved_content": _safe_count(conn, "SELECT COUNT(*) FROM news_articles WHERE rag_status='approved'"),
            "blocked_content": _safe_count(conn, "SELECT COUNT(*) FROM blocked_content"),
            "entity_links": _safe_count(conn, "SELECT COUNT(*) FROM content_entity_links"),
        }
        conn.close()
    except Exception:
        facts["topic_intelligence"] = {}

    # Safety
    try:
        from live_trading_gate import evaluate
        gate = evaluate()
        facts["safety"] = {
            "alpaca_mode": gate["gates"].get("alpaca_mode", "unknown"),
            "live_trading_env_flag": gate["gates"].get("live_trading_env", "unknown"),
            "live_trading_gate_allowed": gate["allowed"],
            "live_trading_gate_blocked_reasons": gate["blocked_reasons"],
        }
    except Exception:
        facts["safety"] = {
            "alpaca_mode": _env("ALPACA_MODE", "unknown"),
            "live_trading_env_flag": _env("LIVE_TRADING_ENABLED", "false"),
            "live_trading_gate_allowed": False,
            "live_trading_gate_blocked_reasons": ["gate_script_error"],
        }

    # Holdings
    try:
        h = json.loads((PROJECT_ROOT / "data/portfolios/state/holdings.json").read_text())
        v = h.get("portfolio_totals", {}).get("total_value", 0)
        facts["safety"]["holdings_value"] = v
        facts["safety"]["holdings_guard_passed"] = v > 1_000_000
    except Exception:
        facts["safety"]["holdings_value"] = 0
        facts["safety"]["holdings_guard_passed"] = False

    # Source health
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT source_key, status, degraded FROM data_source_health")
        facts["source_health"] = {r[0]: {"status": r[1], "degraded": r[2]} for r in cur.fetchall()}
        conn.close()
    except Exception:
        facts["source_health"] = {}

    return facts


def detect_drift(facts):
    """Compare facts against doc claims in active top-level docs only."""
    drift = []
    doc_dir = PROJECT_ROOT / "docs"
    skip_names = {
        "CHANGELOG.md", "LIVE_SYSTEM_FACTS.md",
        "COMMAND_CENTER_PAGE_MATRIX.md",  # historical page-inventory build log
        "PEER_REVIEW_PACKET_COMMAND_CENTER_PAGES.md",
        "HERMES_NEWS_TO_SCALP_CATALYST_INTEGRATION_2026_06_04.md",
    }

    checks = [
        ("table_count", facts.get("database", {}).get("table_count"), r"(\d+)\s+tables"),
        ("strategy_count", facts.get("codebase", {}).get("strategy_count"), r"(\d+)\s+strategies?\b"),
        ("cron_job_count", facts.get("codebase", {}).get("cron_job_count"), r"(\d+)\s+(?:cron|scheduled)\s+job"),
        ("python_script_count", facts.get("codebase", {}).get("python_script_count"), r"(\d+)\s+Python\s+scripts"),
        ("frontend_page_count", facts.get("codebase", {}).get("frontend_page_count"), r"(\d+)\s+pages?\s+\(frozen\)"),
    ]

    for doc_file in sorted(doc_dir.glob("*.md")):
        if doc_file.name in skip_names:
            continue
        try:
            text = doc_file.read_text(errors="replace")
            for fact_name, actual, pattern in checks:
                if actual is None:
                    continue
                for m in re.finditer(pattern, text, re.IGNORECASE):
                    ctx = text[max(0, m.start()-40):m.end()+40]
                    if fact_name == "strategy_count" and "strategy-specific" in ctx.lower():
                        continue
                    if fact_name == "python_script_count" and "python3 scripts/" in ctx.lower():
                        continue
                    claimed = int(m.group(1))
                    if claimed != actual and abs(claimed - actual) > 2:
                        drift.append({
                            "file": str(doc_file.relative_to(PROJECT_ROOT)),
                            "fact": fact_name,
                            "claimed": claimed,
                            "actual": actual,
                            "line_context": ctx.strip(),
                        })
        except Exception:
            pass

    return drift


def generate_markdown(facts, drift):
    lines = [
        "# System Facts — Latest",
        f"\nGenerated: {facts['generated_at']}",
        "",
        "## Runtime",
        f"- Hostname: {facts['runtime']['hostname']}",
        f"- Python: {facts['runtime']['python_version']}",
        f"- Git: {facts['runtime'].get('git_branch', '?')} @ {facts['runtime'].get('git_commit', '?')}",
        "",
        "## Database",
        f"- Connected: {facts.get('database', {}).get('connected', False)}",
        f"- Tables: {facts.get('database', {}).get('table_count', '?')}",
    ]
    for k, v in facts.get("database", {}).get("row_counts", {}).items():
        lines.append(f"- {k}: {v}")
    lines.extend([
        "",
        "## Codebase",
    ])
    for k, v in facts.get("codebase", {}).items():
        lines.append(f"- {k}: {v}")
    lines.extend([
        "",
        "## Safety",
        f"- ALPACA_MODE: {facts.get('safety', {}).get('alpaca_mode', '?')}",
        f"- Live trading: {'ALLOWED' if facts.get('safety', {}).get('live_trading_gate_allowed') else 'BLOCKED'}",
        f"- Holdings: ${facts.get('safety', {}).get('holdings_value', 0):,.0f}",
        f"- Holdings guard: {'PASSED' if facts.get('safety', {}).get('holdings_guard_passed') else 'FAILED'}",
    ])
    if facts.get("safety", {}).get("live_trading_gate_blocked_reasons"):
        lines.append(f"- Blocked reasons: {', '.join(facts['safety']['live_trading_gate_blocked_reasons'])}")

    if drift:
        lines.extend(["", "## Documentation Drift"])
        for d in drift:
            lines.append(f"- **{d['file']}**: {d['fact']} claimed={d['claimed']} actual={d['actual']}")

    return "\n".join(lines)


def main():
    print("Generating system facts...")
    facts = collect_facts()
    drift = detect_drift(facts)
    checksum = hashlib.sha256(json.dumps(facts, sort_keys=True, default=str).encode()).hexdigest()[:16]

    # Write JSON
    facts_path = PROJECT_ROOT / "data" / "system_facts.json"
    facts_path.write_text(json.dumps(facts, indent=2, default=str))
    print(f"Written: {facts_path}")

    drift_path = PROJECT_ROOT / "data" / "system_fact_drift.json"
    drift_path.write_text(json.dumps(drift, indent=2, default=str))
    print(f"Written: {drift_path} ({len(drift)} drift items)")

    # Write markdown
    md_path = PROJECT_ROOT / "docs" / "project" / "SYSTEM_FACTS_LATEST.md"
    md_path.write_text(generate_markdown(facts, drift))
    print(f"Written: {md_path}")

    # Write to DB
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO system_facts_history (facts, drift, checksum)
            VALUES (%s, %s, %s)
        """, (json.dumps(facts, default=str), json.dumps(drift, default=str), checksum))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"  DB write error: {e}")

    # Print summary
    print(f"\nSummary:")
    print(f"  Tables: {facts.get('database', {}).get('table_count', '?')}")
    print(f"  Scripts: {facts.get('codebase', {}).get('python_script_count', '?')}")
    print(f"  Strategies: {facts.get('codebase', {}).get('strategy_count', '?')}")
    print(f"  Cron jobs: {facts.get('codebase', {}).get('cron_job_count', '?')}")
    print(f"  Holdings: ${facts.get('safety', {}).get('holdings_value', 0):,.0f}")
    print(f"  Trading: {'BLOCKED' if not facts.get('safety', {}).get('live_trading_gate_allowed') else 'ALLOWED'}")
    print(f"  Doc drift: {len(drift)} items")


if __name__ == "__main__":
    os.chdir(str(PROJECT_ROOT))
    main()
