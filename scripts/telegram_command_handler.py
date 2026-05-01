#!/usr/bin/env python3
"""telegram_command_handler.py — Handle manual research commands from Telegram.

Polls Telegram for messages, parses research commands, routes to LLM, saves results, replies.

Supported commands:
  research <topic>          — Research a topic (e.g., "research Roth conversion ladder")
  find <what>               — Find candidates (e.g., "find new swing candidates")
  analyze <symbol/sector>   — Analyze symbol or sector
  run screener <name>       — Run a named Finviz screener
  status                    — System status summary
  help                      — List commands

Usage:
    python3 scripts/telegram_command_handler.py --poll [--json]
    python3 scripts/telegram_command_handler.py --process "research Roth conversion ladder" [--json]
"""
import json, os, sys, re, urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"

_COMMANDS = {
    "alex": "Alex retirement analysis for a symbol (e.g. alex V)",
    "roth ladder": "5-year Roth conversion ladder with IRMAA + Medicaid",
    "monthly report": "Monthly retirement performance report with gap analysis",
    "tax": "Current tax bracket, Roth room, conversion capacity",
    "intel": "Recent intelligence for a symbol (e.g. intel SCHD)",
    "conflicts": "Show agent disagreements",
    "iris": "Taxonomy intelligence (iris status/approve/reject/run/<question>)",
    "status": "Full system status with portfolio, income, tax, agents",
    "research": "Research a topic — saved persistently",
    "find": "Find candidates — saved for iteration",
    "analyze": "Analyze a symbol or sector",
    "run screener": "Run a named Finviz screener",
    "topics": "List active research topics",
    "help": "List available commands",
}


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _send_telegram(message: str) -> bool:
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from telegram_alert import send_telegram
        return send_telegram(message)
    except Exception as e:
        print(f"[telegram-cmd] Send failed: {e}")
        return False


def parse_command(text: str) -> dict:
    """Parse a Telegram message into a command + arguments."""
    text = text.strip()
    lower = text.lower()

    if lower == "help":
        return {"command": "help", "args": ""}
    if lower == "status":
        return {"command": "status", "args": ""}
    if lower == "topics":
        return {"command": "topics", "args": ""}
    if lower == "tax":
        return {"command": "tax", "args": ""}
    if lower == "conflicts":
        return {"command": "conflicts", "args": ""}
    if lower.startswith("iris"):
        return {"command": "iris", "args": text[4:].strip() if len(text) > 4 else ""}
    if lower.startswith("/iris_approve_"):
        pid = lower.replace("/iris_approve_", "").strip()
        return {"command": "iris", "args": f"approve {pid}"}
    if lower.startswith("/iris_reject_"):
        pid = lower.replace("/iris_reject_", "").strip()
        return {"command": "iris", "args": f"reject {pid}"}
    if lower.startswith("intel"):
        return {"command": "intel", "args": text[5:].strip() if len(text) > 5 else ""}
    # Alex retirement advisor commands
    if lower.startswith("alex "):
        return {"command": "alex", "args": text[5:].strip()}
    if lower.startswith("retirement "):
        return {"command": "alex", "args": text[11:].strip()}
    if lower in ("roth ladder", "roth conversion", "roth conversion ladder"):
        return {"command": "roth_ladder", "args": ""}
    if lower in ("monthly report", "monthly", "monthly retirement"):
        return {"command": "monthly_report", "args": ""}
    if lower.startswith("update "):
        return {"command": "update_credential", "args": text[7:].strip()}
    if lower in ("check credentials", "cred check", "credential check"):
        return {"command": "credential_check", "args": ""}
    if lower.startswith("run screener "):
        return {"command": "run_screener", "args": text[13:].strip()}
    if lower.startswith("research "):
        return {"command": "research", "args": text[9:].strip()}
    if lower.startswith("find "):
        return {"command": "find", "args": text[5:].strip()}
    if lower.startswith("analyze "):
        return {"command": "analyze", "args": text[8:].strip()}

    return {"command": "unknown", "args": text}


def _handle_iris(args: str) -> str:
    """Route Iris Telegram commands."""
    import threading
    parts = args.strip().split(None, 1)
    subcommand = parts[0].lower() if parts else "status"
    rest = parts[1] if len(parts) > 1 else ""

    # iris / iris status
    if subcommand in ("status", ""):
        try:
            from iris_taxonomy_agent import iris_status_summary, get_iris_status
            summary = iris_status_summary()
            status = get_iris_status()
            pending = status.get("pending_proposals", [])
            lines = ["*Iris — Taxonomy Intelligence*", "", summary, ""]
            if pending:
                lines.append("*Proposals:*")
                for p in pending[:5]:
                    lines.append(f"  [{p['id']}] {p['type']}: {p['target']} (conf:{p['confidence']:.0%})")
                lines.append("")
                lines.append("Approve: /iris_approve_ID | /iris_reject_ID")
            return "\n".join(lines)
        except Exception as e:
            return f"Iris status error: {e}"

    # iris approve <id>
    if subcommand == "approve" and rest.strip().isdigit():
        proposal_id = int(rest.strip())
        try:
            conn = _get_conn()
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""UPDATE iris_taxonomy_proposals
                SET status='approved', reviewed_by='john_telegram', reviewed_at=NOW()
                WHERE id=%s AND status='pending' RETURNING target, proposal_type""", (proposal_id,))
            row = cur.fetchone()
            conn.commit()
            conn.close()
            if row:
                from iris_taxonomy_agent import apply_proposal
                apply_proposal(proposal_id)
                return f"Iris: Proposal #{proposal_id} '{row['target']}' ({row['proposal_type']}) approved and activated."
            return f"Iris: Proposal #{proposal_id} not found or already processed."
        except Exception as e:
            return f"Iris approve error: {e}"

    # iris reject <id>
    if subcommand == "reject" and rest.strip().isdigit():
        proposal_id = int(rest.strip())
        try:
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("""UPDATE iris_taxonomy_proposals
                SET status='rejected', reviewed_by='john_telegram', reviewed_at=NOW()
                WHERE id=%s AND status='pending' RETURNING target""", (proposal_id,))
            row = cur.fetchone()
            conn.commit()
            conn.close()
            if row:
                return f"Iris: Proposal #{proposal_id} '{row[0]}' rejected."
            return f"Iris: Proposal #{proposal_id} not found."
        except Exception as e:
            return f"Iris reject error: {e}"

    # iris run
    if subcommand == "run":
        try:
            from iris_taxonomy_agent import run_weekly_scan
            def _run():
                try:
                    run_weekly_scan()
                except Exception as e:
                    print(f"[iris] Background run error: {e}")
            threading.Thread(target=_run, daemon=True).start()
            return "Iris: Taxonomy scan starting in background (~90s). Check results with 'iris status'."
        except Exception as e:
            return f"Iris run error: {e}"

    # iris hygiene <subcommand>
    if subcommand == "hygiene":
        try:
            from iris_taxonomy_agent import handle_iris_hygiene_command
            hyg_parts = rest.strip().split(None, 1)
            hyg_sub = hyg_parts[0].lower() if hyg_parts else "status"
            hyg_args = hyg_parts[1] if len(hyg_parts) > 1 else ""
            return handle_iris_hygiene_command(hyg_sub, hyg_args)
        except Exception as e:
            return f"Iris hygiene error: {e}"

    # iris who / iris identity / iris help
    if subcommand in ("who", "identity", "help"):
        return (
            "*Iris — Taxonomy Intelligence Agent*\n"
            "I keep the classification system current so Maria, Risk, Steph,\n"
            "and Alex all get the content they need.\n\n"
            "*Commands:*\n"
            "  iris status       — coverage + pending proposals\n"
            "  iris approve <id> — approve a proposal\n"
            "  iris reject <id>  — reject a proposal\n"
            "  iris run          — force taxonomy scan\n"
            "  iris hygiene      — content lifecycle management\n"
            "  iris <question>   — ask me anything about content tagging"
        )

    # iris <any question> — free-form Q&A
    full_question = (subcommand + " " + rest).strip()
    try:
        from iris_taxonomy_agent import ask_iris
        return f"*Iris:*\n\n{ask_iris(full_question)}"
    except Exception as e:
        return f"Iris Q&A error: {e}"


def process_command(cmd: dict) -> str:
    """Process a parsed command and return response text."""
    command = cmd["command"]
    args = cmd["args"]

    if command == "help":
        lines = ["*Trade AI Commands:*", ""]
        for c, desc in _COMMANDS.items():
            lines.append(f"  `{c}` — {desc}")
        lines.append("\nExamples:")
        lines.append("  alex V — full retirement analysis")
        lines.append("  roth ladder — 5-year conversion plan")
        lines.append("  monthly report — monthly retirement performance")
        lines.append("  tax — bracket room + conversion capacity")
        lines.append("  intel SCHD — recent intelligence")
        lines.append("  intel — all agent intel (no symbol)")
        lines.append("  iris status — taxonomy coverage + proposals")
        lines.append("  iris <question> — ask Iris about content tagging")
        lines.append("  conflicts — agent disagreements")
        lines.append("  status — portfolio + income + tax + agents")
        lines.append("  check credentials — API key health check")
        lines.append("  update KEY VALUE — update .env credential")
        lines.append("  research Roth conversion ladder")
        lines.append("  run screener dividend_growth")
        return "\n".join(lines)

    if command == "roth_ladder":
        try:
            from alex_retirement_advisor import roth_conversion_analysis
            r = roth_conversion_analysis()
            if r.get("analysis"):
                return f"*Alex: Roth Conversion Ladder Analysis*\n\n{r['analysis'][:2000]}\n\n_via {r.get('provider')} (${r.get('cost', 0):.4f})_"
            return f"Error: {r.get('error', 'Analysis failed')}"
        except Exception as e:
            return f"Roth ladder error: {e}"

    if command == "monthly_report":
        try:
            from alex_retirement_advisor import monthly_retirement_report
            r = monthly_retirement_report(send_telegram=False)
            if r.get("report"):
                return f"\U0001F4CA *Alex: Monthly Retirement Report*\n\n{r['report'][:2000]}\n\n_via {r.get('provider')} (${r.get('cost', 0):.4f})_"
            return f"Error: {r.get('error', 'Report failed')}"
        except Exception as e:
            return f"Monthly report error: {e}"

    if command == "credential_check":
        try:
            from credential_monitor import run_checks
            results = run_checks(send_telegram=False)
            lines = ["🔑 *Credential Health Check*", ""]
            for r in results:
                icon = {"ok": "✅", "warning": "⚠️", "expired": "🔴", "missing": "⬜", "error": "❌", "quota": "🟡"}.get(r["status"], "❓")
                line = f"{icon} *{r['name']}*: {r['status']}"
                if r.get("error"):
                    line += f"\n   _{r['error']}_"
                elif r.get("detail"):
                    line += f" — {r['detail']}"
                lines.append(line)
            return "\n".join(lines)
        except Exception as e:
            return f"Credential check error: {e}"

    if command == "update_credential":
        parts = args.split(None, 1)
        if len(parts) < 2:
            return "Usage: `update FINVIZ_COOKIE value_here`\n\nValid keys: FINVIZ_COOKIE, YOUTUBE_API_KEY, FRED_API_KEY, BRAVE_SEARCH_API_KEY, FINNHUB_API_KEY, FMP_API_KEY, ALPHA_VANTAGE_API_KEY"
        key, value = parts[0].upper(), parts[1].strip()
        allowed = {"FINVIZ_COOKIE", "YOUTUBE_API_KEY", "FRED_API_KEY", "BRAVE_SEARCH_API_KEY",
                    "FINNHUB_API_KEY", "FMP_API_KEY", "ALPHA_VANTAGE_API_KEY", "OPENAI_API_KEY",
                    "ANTHROPIC_API_KEY", "GEMINI_API_KEY"}
        if key not in allowed:
            return f"❌ Key `{key}` not in allowed list.\nAllowed: {', '.join(sorted(allowed))}"
        try:
            from credential_monitor import update_env_key
            if update_env_key(key, value):
                return f"✅ Updated `{key}` in .env ({len(value)} chars)\n\n_Restart services to apply: portfolio-server, tradeai-continuous_"
            return "❌ Failed to update .env"
        except Exception as e:
            return f"Update error: {e}"

    if command == "iris":
        return _handle_iris(args)

    if command == "alex":
        # Route to Alex retirement advisor
        try:
            from alex_retirement_advisor import analyze_for_retirement
            import re
            # Extract symbol from args
            sym_match = re.match(r'^([A-Z]{1,6})\b', args.upper())
            if sym_match:
                sym = sym_match.group(1)
                r = analyze_for_retirement(sym, f"telegram: {args}")
                if r.get("analysis"):
                    return f"*Alex (Retirement Advisor): {sym}*\n\n{r['analysis'][:1500]}\n\n_via {r.get('provider')} (${r.get('cost', 0):.4f})_"
                else:
                    return f"Alex: {r.get('error', 'No analysis available for ' + sym)}"
            else:
                # General retirement question — route to research
                return process_command({"command": "research", "args": args})
        except Exception as e:
            return f"Alex error: {e}"

    if command == "status":
        import psycopg2.extras
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT COUNT(*) as cnt FROM cio_decisions WHERE status='proposed'")
        decisions = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) as cnt FROM watchlist_final_synthesis WHERE actionable=TRUE AND superseded IS NOT TRUE")
        actionable = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) as cnt FROM watchlist_agent_jobs WHERE status='queued'")
        queued = cur.fetchone()["cnt"]
        # New: tax + income + agents
        cur.execute("SELECT agi, roth_conversions_total, standard_deduction FROM personal_tax_history WHERE tax_year=2026")
        tax = cur.fetchone()
        cur.execute("SELECT agent, count(*) as cnt FROM watchlist_agent_results WHERE created_at > NOW() - INTERVAL '24 hours' GROUP BY agent")
        agent_today = {r["agent"]: r["cnt"] for r in cur.fetchall()}
        cur.execute("SELECT count(*) as cnt FROM agent_handoffs WHERE escalated=TRUE AND created_at > NOW() - INTERVAL '24 hours'")
        escalations = cur.fetchone()["cnt"]
        conn.close()

        import json
        from pathlib import Path as _P
        state_dir = _P(__file__).resolve().parent.parent / "data" / "portfolios" / "state"
        try:
            h = json.loads((state_dir / "holdings.json").read_text())
            pv = h.get("portfolio_totals", {}).get("total_value", 0)
        except Exception:
            pv = 0
        try:
            dv = json.loads((state_dir / "dividend_calendar.json").read_text())
            income = dv.get("total_annual", 0)
        except Exception:
            income = 0

        agi = float(tax["agi"]) if tax else 0
        roth = float(tax.get("roth_conversions_total") or 0) if tax else 0
        room = max(0, 100525 + float(tax.get("standard_deduction") or 15700) - agi) if tax else 0
        agents_str = ", ".join(f"{a.replace('_agent','')}: {c}" for a, c in agent_today.items()) if agent_today else "none"

        lines = [
            "\U0001F4CA *System Status*",
            "\u2501" * 22,
            f"\U0001F4B0 Portfolio: ${pv/1e6:.2f}M",
            f"\U0001F4C8 Income: ${income:,.0f}/yr ({int(income/55000*100)}% of $55K)",
            f"\U0001F3E6 Tax: {12 if agi - float(tax.get('standard_deduction') or 15700) < 47150 else 22}% | Room: ${room:,.0f} | Roth: ${roth:,.0f}",
            f"",
            f"\U0001F916 Agent jobs (24h): {agents_str}",
            f"\u26A1 Queued: {queued} | Decisions: {decisions} | Actionable: {actionable}",
            f"\U0001F6A8 Escalations (24h): {escalations}",
            f"",
            f"\U0001F517 http://ms01-openclaw:7777/v2/",
        ]
        return "\n".join(lines)

    if command == "intel":
        # Show recent intelligence for a symbol
        try:
            sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from intel_query import get_intel_summary
            sym = args.strip().upper() if args else None
            summary = get_intel_summary(agent="Alex", symbol=sym, min_quality=30, max_chars=1000, days=7)
            if summary:
                return f"*Intelligence{' for ' + sym if sym else ''}*\n\n{summary}"
            return "No recent intelligence found."
        except Exception as e:
            return f"Intel error: {e}"

    if command == "conflicts":
        # Show agent conflicts
        try:
            sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from telegram_smart_alerts import check_agent_conflicts
            result = check_agent_conflicts()
            if result.get("conflicts", 0) == 0:
                return "\u2705 No agent conflicts detected."
            return f"\u26A0\uFE0F {result['conflicts']} agent conflict(s) detected. Run smart alerts for details."
        except Exception as e:
            return f"Conflicts error: {e}"

    if command == "tax":
        # Show tax situation
        try:
            sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from alex_retirement_advisor import get_tax_context
            tc = get_tax_context(2026)
            if tc.get("error"):
                return f"Tax error: {tc['error']}"
            return (
                f"*2026 Tax Situation*\n"
                f"AGI: ${tc['agi']:,.0f}\n"
                f"Bracket: {tc['current_bracket']}%\n"
                f"22% room: ${tc['bracket_room_22pct']:,.0f}\n"
                f"Roth YTD: ${tc['roth_conversions_ytd']:,.0f}\n"
                f"Max conversion at 22%: ${tc['max_additional_conversion']:,.0f}\n"
                f"Biz loss carryforward: ${tc.get('extra_from_loss',0):,.0f}"
            )
        except Exception as e:
            return f"Tax error: {e}"

    if command == "run_screener":
        conn = _get_conn()
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT display_name, finviz_url, description FROM finviz_screeners WHERE screener_id=%s AND active=TRUE", (args,))
        s = cur.fetchone()
        conn.close()
        if s:
            return f"*Screener: {s['display_name']}*\n{s['description']}\n\nOpen: {s['finviz_url']}"
        else:
            cur2 = _get_conn().cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur2.execute("SELECT screener_id, display_name FROM finviz_screeners WHERE active=TRUE ORDER BY screener_id")
            available = [f"  `{r['screener_id']}` — {r['display_name']}" for r in cur2.fetchall()]
            cur2.close()
            return f"Screener '{args}' not found.\n\nAvailable:\n" + "\n".join(available)

    if command == "topics":
        # List active research topics
        conn = _get_conn()
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, topic, priority, status, research_count FROM user_research_topics WHERE status='active' ORDER BY priority DESC, id")
        topics = cur.fetchall()
        conn.close()
        if not topics:
            return "No active research topics. Use `research <topic>` to add one."
        lines = ["*Active Research Topics:*", ""]
        for t in topics:
            lines.append(f"  [{t['id']}] {t['topic']} ({t['priority']}) — {t['research_count']} researches")
        return "\n".join(lines)

    if command in ("research", "find", "analyze"):
        # Save as persistent research topic
        conn = _get_conn()
        cur = conn.cursor()
        # Check if topic already exists
        cur.execute("SELECT id FROM user_research_topics WHERE topic ILIKE %s AND status='active' LIMIT 1", (f"%{args[:50]}%",))
        existing = cur.fetchone()
        if not existing:
            cur.execute("""
                INSERT INTO user_research_topics (topic, source, original_message, priority)
                VALUES (%s, 'telegram', %s, %s)
            """, (args[:200], f"{command} {args}"[:500],
                  "high" if command == "research" else "normal"))
            conn.commit()
            print(f"  [topics] Saved new topic: {args[:50]}")
        conn.close()

        # Route to LLM for immediate response (enhanced with FRED + outcome lessons)
        try:
            from llm_router import get_llm_response
            task = "agent_narrative"
            extra_ctx = ""
            try:
                from external_market_data_ingest import get_macro_context
                mc = get_macro_context()
                if mc:
                    extra_ctx += f"\n{mc}\n"
            except Exception:
                pass
            try:
                from intel_query import get_intel_summary
                intel = get_intel_summary(agent="Alex", symbol=args.split()[0] if args else None, max_chars=400, source_hint="research")
                if intel:
                    extra_ctx += f"\n{intel[:400]}\n"
            except Exception:
                pass
            prompt = f"/no_think You are a certified retirement planner and financial research assistant.\n\n{command.title()} request: {args}\n\nContext: Managing $1.2M retirement portfolio across 4 accounts (Fidelity 401k, Schwab Rollover IRA, Schwab Roth IRA, Schwab Taxable). Target: $55K/yr income. Current: $14,342/yr. SSDI $3,800/mo. MFS filing. Timeline: 4-8 years.\n{extra_ctx}\nProvide actionable analysis with specific recommendations. If relevant, mention account placement (IRA vs Roth vs Taxable) and SSDI/Medicaid impact."
            result = get_llm_response(task, prompt, max_tokens=600)
            if result.get("success"):
                # Save findings to topic
                conn2 = _get_conn()
                cur2 = conn2.cursor()
                cur2.execute("""
                    UPDATE user_research_topics
                    SET latest_findings = %s, latest_finding_at = now(),
                        research_count = research_count + 1, last_researched_at = now()
                    WHERE topic ILIKE %s AND status = 'active'
                """, (result["response"][:2000], f"%{args[:50]}%"))
                cur2.execute("""
                    INSERT INTO portfolio_intelligence_events (event_type, severity, source, payload)
                    VALUES ('telegram_command', 'info', 'telegram_command_handler.py', %s)
                """, (json.dumps({"command": command, "args": args, "provider": result.get("provider"),
                                   "response_len": len(result.get("response", ""))}, default=str),))
                conn.commit()
                conn.close()

                provider = result.get("provider", "?")
                cost = result.get("cost_estimate", 0)
                return f"*{command.title()}: {args}*\n\n{result['response'][:1500]}\n\n_via {provider} (${cost:.4f})_"
            else:
                return f"LLM failed: {result.get('error', 'unknown')}"
        except Exception as e:
            return f"Error: {e}"

    return f"Unknown command: {cmd['args'][:50]}\nType `help` for available commands."


def poll_and_process():
    """Poll Telegram for new messages and process commands."""
    env = {}
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip("\"'")

    token = env.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("[telegram-cmd] No TELEGRAM_BOT_TOKEN")
        return []

    # Get recent messages
    try:
        url = f"https://api.telegram.org/bot{token}/getUpdates?offset=-5&limit=5"
        req = urllib.request.Request(url, headers={"User-Agent": "TradeAI/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"[telegram-cmd] Poll failed: {e}")
        return []

    results = []
    for update in data.get("result", []):
        msg = update.get("message", {})
        text = msg.get("text", "")
        chat_id = msg.get("chat", {}).get("id")

        if not text or not chat_id:
            continue

        # Only process messages that look like commands
        lower = text.lower().strip()
        is_command = any(lower.startswith(c) for c in ["research ", "find ", "analyze ", "run screener ", "look for ", "alex ", "retirement ", "iris", "/iris_", "status", "help", "topics"])
        if not is_command:
            continue

        cmd = parse_command(text)
        response = process_command(cmd)

        # Reply
        _send_telegram(response)
        results.append({"command": cmd, "response_len": len(response)})

    return results


if __name__ == "__main__":
    if "--process" in sys.argv:
        idx = sys.argv.index("--process")
        text = sys.argv[idx + 1]
        cmd = parse_command(text)
        response = process_command(cmd)
        print(response)
    elif "--poll" in sys.argv:
        results = poll_and_process()
        print(f"[telegram-cmd] Processed {len(results)} commands")
        if "--json" in sys.argv:
            print(json.dumps(results, indent=2, default=str))
    else:
        print("Usage: --process 'research topic' | --poll [--json]")
