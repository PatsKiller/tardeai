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
    "run promoter": "Run incubator proposal promoter (add 'dry' for dry-run)",
    "topics": "List active research topics",
    "topic status": "Show topic monitor gaps + article counts",
    "topic add <name>": "Add a new research topic",
    "topic url <id> <url>": "Add a saved Google search URL to a topic",
    "topic run <id>": "Run topic ingestion for one topic (or 'all')",
    "proposals": "List pending watchlist proposals",
    "tasks": "List pending tasks needing your decision",
    "debates": "List recent agent debates",
    "approve proposal <id>": "Approve a watchlist proposal",
    "reject proposal <id>": "Reject a watchlist proposal",
    "approve task <id>": "Approve/resolve a pending task",
    "reject task <id>": "Reject a pending task",
    "lessons": "Show outcome lessons learned by agents",
    "scalp stats": "30-day scalp hit rate + best/worst symbols",
    "rag <symbol>": "Show what agents see in RAG for symbol",
    "confidence <agent>": "Agent confidence trend last 30 days",
    "learning": "Learning loop status — lessons, outcomes, RAG",
    "watchlist health": "Watchlist data quality: LLM errors, stale analyses, missing entries",
    "/pt SYMBOL auto": "Open paper trade from plan (e.g. /pt FTCI auto)",
    "/pt SYMBOL SHARES ENTRY STOP TARGET": "Open paper trade manually",
    "/ptclose SYMBOL PRICE": "Close paper trade at price",
    "/cio": "CIO dashboard — portfolio, actions, Hermes research",
    "/cio actions": "Open CIO action items",
    "/cio portfolio": "CIO portfolio snapshot",
    "/cio hermes": "Latest Hermes research topics",
    "/cio risk": "CIO risk overview",
    "/advisory": "Advisory desk brief (3 things / top rows)",
    "/advisory rate SYM useful|notuseful CODE": "Rate an advisory row",
    "/advisory ack SYM": "Acknowledge advisory row",
    "/advisory snooze SYM": "Snooze advisory row",
    "/advisory history SYM": "Prior verdicts + feedback",
    "/advisory calibration": "Desk outcome hit rates",
    "/ptopen": "Show open paper trades",
    "/ptpnl": "Paper trading P&L summary",
    "halt trading": "Global halt — block all strategies",
    "resume trading": "Resume all trading",
    "halt live": "Block live trades only (paper continues)",
    "resume live": "Resume live trading",
    "halt strategy <id>": "Halt a specific strategy",
    "resume strategy <id>": "Resume a specific strategy",
    "risk status": "Show halt flags and risk gate summary",
    "add video <urls>": "Add YouTube videos to ingestion (paste 1+ URLs)",
    "add article <urls>": "Add article URLs to ingestion (paste 1+ URLs)",
    "backup docs": "Sync latest documentation to Google Drive",
    "watch ticker SYM [because …]": "Watch a ticker (operator directive)",
    "watch sector NAME": "Watch a sector (ETF + Finviz constituents)",
    "watch trend KEYWORDS": "Watch a narrative/trend (Hermes discovers)",
    "promote SYM": "One-tap promote a staged directive hit",
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


_WL_SKILL = os.path.expanduser("~/.openclaw/skills/tradeai-watchlist/scripts/tradeai_watchlist.py")
_AGENT_NAMES = ("maria", "aegis", "alex", "iris", "steph")
# common English words that follow "add" but aren't tickers — so "add a note" / "add task" don't get
# treated as ticker adds (tickers are accepted case-insensitively otherwise).
_NOT_TICKER = {"the", "and", "for", "you", "list", "watch", "note", "task", "todo", "item", "this",
               "that", "some", "more", "news", "info", "link", "url", "new", "all", "one", "two", "my"}


def _ticker_tokens(s):
    """Return uppercase ticker tokens if every token in `s` looks like a ticker (2-5 letters, not an
    English filler word); else []. Lets bare 'add aapl' / 'add AAPL HOOD' work, rejects 'add a note'."""
    toks = s.split()
    if toks and len(toks) <= 4 and all(t.isalpha() and 2 <= len(t) <= 5 and t.lower() not in _NOT_TICKER for t in toks):
        return [t.upper() for t in toks]
    return []


def _strip_agent_prefix(text: str) -> str:
    """Drop a leading 'Maria, ' / 'maria ' agent address so 'maria watch HOOD' gets the deterministic
    skill path instead of the hallucinating gateway agent."""
    m = re.match(r"^(?:" + "|".join(_AGENT_NAMES) + r")\b[,:]?\s+(.+)$", text.strip(), re.I)
    return m.group(1).strip() if m else text.strip()


def _run_wl_skill(*args) -> str:
    """Run the tradeai-watchlist bridge skill and return its RAW stdout — the deterministic, honest path
    for watchlist/research/ask actions (the LLM agents hallucinate these). HTTP-only skill, no deps."""
    import subprocess
    try:
        r = subprocess.run(["python3", _WL_SKILL, *args], capture_output=True, text=True, timeout=90)
        return ((r.stdout or "").strip() or (r.stderr or "").strip() or "(no output from skill)")
    except Exception as e:
        return f"❌ skill error: {str(e)[:140]}"


def parse_command(text: str) -> dict:
    """Parse a Telegram message into a command + arguments."""
    text = _strip_agent_prefix(text)        # 'maria watch X' -> 'watch X'
    lower = text.lower()

    if lower == "help":
        return {"command": "help", "args": ""}
    if lower == "status":
        return {"command": "status", "args": ""}
    # /cio commands — CIO dashboard (deterministic, zero model calls)
    if lower in ("/cio", "cio"):
        return {"command": "cio", "args": "status"}
    if lower in ("/cio actions", "cio actions", "/cio status", "cio status"):
        return {"command": "cio", "args": "actions" if "actions" in lower else "status"}
    if lower in ("/cio portfolio", "cio portfolio"):
        return {"command": "cio", "args": "portfolio"}
    if lower in ("/cio hermes", "cio hermes"):
        return {"command": "cio", "args": "hermes"}
    if lower in ("/cio risk", "cio risk"):
        return {"command": "cio", "args": "risk"}
    # /advisory — Advisory Desk (deterministic; feedback writes JSONL only)
    if lower in ("/advisory", "advisory"):
        return {"command": "advisory", "args": "brief"}
    if lower.startswith("/advisory ") or lower.startswith("advisory "):
        raw_args = text.split(None, 1)[1] if " " in text else ""
        return {"command": "advisory", "args": raw_args.strip()}
    # Deterministic watchlist / research / LLM actions — run the REAL skill (agents fabricate these).
    if lower.startswith("watch ") and not lower.startswith("watchlist"):
        return {"command": "wl_add", "args": text[6:].strip()}
    if lower.startswith("add ") and " to " in lower and ("watch" in lower or "list" in lower):
        return {"command": "wl_add_phrase", "args": text[4:].strip()}
    # bare "add aapl" / "add SOFI HOOD" (ticker tokens, any case) → general watchlist
    if lower.startswith("add ") and " to " not in lower and not any(w in lower for w in ("video", "article", "topic ")):
        _toks = _ticker_tokens(text[4:].strip())
        if _toks:
            return {"command": "wl_add", "args": " ".join(_toks)}
    for _v in ("trend ", "tren ", "trnd ", "research topic "):   # tolerate the common 'trend' typos
        if lower.startswith(_v) and not lower.startswith("trends"):
            return {"command": "wl_topic", "args": text[len(_v):].strip()}
    if lower.startswith("ask "):
        return {"command": "wl_ask", "args": text[4:].strip()}
    if lower in ("trends", "research trends", "latest trends", "latest research"):
        return {"command": "wl_trends", "args": ""}
    if lower == "topics":
        return {"command": "topics", "args": ""}
    if lower.startswith("topic add "):
        return {"command": "topic_add", "args": text[10:].strip()}
    if lower.startswith("topic url "):
        return {"command": "topic_url", "args": text[10:].strip()}
    if lower.startswith("topic run "):
        return {"command": "topic_run", "args": text[10:].strip()}
    if lower == "topic run" or lower == "topic run all":
        return {"command": "topic_run", "args": "all"}
    if lower == "topic status" or lower == "topic gaps":
        return {"command": "topic_status", "args": ""}
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
    if lower.startswith("run promoter"):
        return {"command": "run_promoter", "args": text[12:].strip()}
    if lower.startswith("research "):
        return {"command": "research", "args": text[9:].strip()}
    if lower.startswith("find "):
        return {"command": "find", "args": text[5:].strip()}
    if lower.startswith("analyze "):
        return {"command": "analyze", "args": text[8:].strip()}
    # Proposal/task approval commands
    if lower.startswith("approve proposal "):
        return {"command": "approve_proposal", "args": text[17:].strip()}
    if lower.startswith("reject proposal "):
        return {"command": "reject_proposal", "args": text[16:].strip()}
    if lower.startswith("approve task "):
        return {"command": "approve_task", "args": text[13:].strip()}
    if lower.startswith("reject task "):
        return {"command": "reject_task", "args": text[12:].strip()}
    if lower == "proposals":
        return {"command": "list_proposals", "args": ""}
    if lower == "tasks":
        return {"command": "list_tasks", "args": ""}
    if lower == "debates":
        return {"command": "list_debates", "args": ""}
    # v7.7 autonomy commands
    if lower == "lessons":
        return {"command": "lessons", "args": ""}
    if lower in ("scalp stats", "scalp", "scalp status"):
        return {"command": "scalp_stats", "args": ""}
    if lower.startswith("rag "):
        return {"command": "rag", "args": text[4:].strip()}
    if lower.startswith("confidence "):
        return {"command": "confidence", "args": text[11:].strip()}
    if lower == "learning":
        return {"command": "learning", "args": ""}
    if lower in ("watchlist health", "wl health"):
        return {"command": "watchlist_health", "args": ""}
    # Session 13/14: paper trade commands (order matters — specific before general)
    if lower in ("/ptpending", "ptpending"):
        return {"command": "pt_pending", "args": ""}
    if lower.startswith("/ptapprove ") or lower.startswith("ptapprove "):
        pt_text = text[10:].strip() if lower.startswith("/ptapprove") else text[9:].strip()
        return {"command": "pt_approve", "args": pt_text}
    if lower.startswith("/ptreject ") or lower.startswith("ptreject "):
        pt_text = text[9:].strip() if lower.startswith("/ptreject") else text[8:].strip()
        return {"command": "pt_reject", "args": pt_text}
    if lower.startswith("/ptclose ") or lower.startswith("ptclose "):
        pt_text = text[8:].strip() if lower.startswith("/ptclose") else text[7:].strip()
        return {"command": "pt_close", "args": pt_text}
    if lower in ("/ptopen", "ptopen"):
        return {"command": "pt_positions", "args": ""}
    if lower in ("/ptpnl", "ptpnl"):
        return {"command": "pt_pnl", "args": ""}
    if lower.startswith("/pt ") or lower.startswith("pt "):
        pt_text = text[3:].strip() if lower.startswith("/pt") else text[2:].strip()
        return {"command": "pt_open", "args": pt_text}

    # Session 27: paper order modification commands
    if lower in ("paper mods", "/paper mods", "paper modifications"):
        return {"command": "paper_mods_list", "args": ""}
    if lower.startswith("paper mod ") or lower.startswith("/paper mod "):
        mod_text = lower.replace("/paper mod ", "").replace("paper mod ", "").strip()
        return {"command": "paper_mod_detail", "args": mod_text}
    if lower.startswith("approve paper mod ") or lower.startswith("/approve paper mod "):
        parts = lower.replace("/approve paper mod ", "").replace("approve paper mod ", "").strip()
        return {"command": "paper_mod_approve", "args": parts}
    if lower.startswith("reject paper mod ") or lower.startswith("/reject paper mod "):
        parts = lower.replace("/reject paper mod ", "").replace("reject paper mod ", "").strip()
        return {"command": "paper_mod_reject", "args": parts}
    if lower.startswith("execute approved paper mod ") or lower.startswith("/execute approved paper mod "):
        parts = lower.replace("/execute approved paper mod ", "").replace("execute approved paper mod ", "").strip()
        return {"command": "paper_mod_execute", "args": parts}
    if lower.startswith("cancel paper mod ") or lower.startswith("/cancel paper mod "):
        parts = lower.replace("/cancel paper mod ", "").replace("cancel paper mod ", "").strip()
        return {"command": "paper_mod_cancel", "args": parts}

    # Session 27B: execution revalidation commands
    if lower in ("paper pending entries", "/paper pending entries"):
        return {"command": "paper_pending_entries", "args": ""}
    if lower.startswith("recheck paper entry ") or lower.startswith("/recheck paper entry "):
        pid = lower.replace("/recheck paper entry ", "").replace("recheck paper entry ", "").strip()
        return {"command": "paper_recheck_entry", "args": pid}
    if lower.startswith("approve updated paper entry ") or lower.startswith("/approve updated paper entry "):
        parts = lower.replace("/approve updated paper entry ", "").replace("approve updated paper entry ", "").strip()
        return {"command": "paper_approve_updated_entry", "args": parts}
    if lower.startswith("reject updated paper entry ") or lower.startswith("/reject updated paper entry "):
        parts = lower.replace("/reject updated paper entry ", "").replace("reject updated paper entry ", "").strip()
        return {"command": "paper_reject_updated_entry", "args": parts}
    if lower.startswith("execute ready paper entry ") or lower.startswith("/execute ready paper entry "):
        pid = lower.replace("/execute ready paper entry ", "").replace("execute ready paper entry ", "").strip()
        return {"command": "paper_execute_ready_entry", "args": pid}

    # Session 28: Learning Governance commands
    if lower in ("learning status", "/learning status"):
        return {"command": "learning_status", "args": ""}
    if lower in ("learning hypotheses", "/learning hypotheses"):
        return {"command": "learning_hypotheses", "args": ""}
    if lower.startswith("learning hypothesis ") or lower.startswith("/learning hypothesis "):
        hid = lower.replace("/learning hypothesis ", "").replace("learning hypothesis ", "").strip()
        return {"command": "learning_hypothesis_detail", "args": hid}
    if lower in ("learning recommendations", "/learning recommendations"):
        return {"command": "learning_recommendations", "args": ""}
    if lower.startswith("learning rec ") or lower.startswith("/learning rec "):
        rid = lower.replace("/learning rec ", "").replace("learning rec ", "").strip()
        return {"command": "learning_rec_detail", "args": rid}
    if lower in ("learning proposals", "/learning proposals"):
        return {"command": "learning_proposals", "args": ""}
    if lower.startswith("learning proposal ") or lower.startswith("/learning proposal "):
        pid = lower.replace("/learning proposal ", "").replace("learning proposal ", "").strip()
        return {"command": "learning_proposal_detail", "args": pid}
    if lower.startswith("approve learning shadow ") or lower.startswith("/approve learning shadow "):
        parts = lower.replace("/approve learning shadow ", "").replace("approve learning shadow ", "").strip()
        return {"command": "learning_approve_shadow", "args": parts}
    if lower.startswith("reject learning proposal ") or lower.startswith("/reject learning proposal "):
        parts = lower.replace("/reject learning proposal ", "").replace("reject learning proposal ", "").strip()
        return {"command": "learning_reject_proposal", "args": parts}
    if lower.startswith("approve learning implementation ") or lower.startswith("/approve learning implementation "):
        parts = lower.replace("/approve learning implementation ", "").replace("approve learning implementation ", "").strip()
        return {"command": "learning_approve_implementation", "args": parts}
    if lower.startswith("rollback learning proposal ") or lower.startswith("/rollback learning proposal "):
        parts = lower.replace("/rollback learning proposal ", "").replace("rollback learning proposal ", "").strip()
        return {"command": "learning_rollback", "args": parts}

    # Session 29: Agent Calibration commands
    if lower in ("agent calibration", "/agent calibration"):
        return {"command": "agent_calibration_status", "args": ""}
    if lower.startswith("agent calibration ") and lower.split()[-1] not in ("run","normalize","link","score"):
        agent = lower.replace("/agent calibration ", "").replace("agent calibration ", "").strip()
        return {"command": "agent_calibration_detail", "args": agent}
    if lower in ("agent disagreements", "/agent disagreements"):
        return {"command": "agent_disagreements", "args": ""}
    if lower in ("agent weight proposals", "/agent weight proposals"):
        return {"command": "agent_weight_proposals", "args": ""}
    if lower.startswith("approve agent shadow ") or lower.startswith("/approve agent shadow "):
        parts = lower.replace("/approve agent shadow ", "").replace("approve agent shadow ", "").strip()
        return {"command": "agent_approve_shadow", "args": parts}
    if lower.startswith("reject agent shadow ") or lower.startswith("/reject agent shadow "):
        parts = lower.replace("/reject agent shadow ", "").replace("reject agent shadow ", "").strip()
        return {"command": "agent_reject_shadow", "args": parts}

    # Session 30: Weekly Learning + Thesis Review commands
    if lower in ("weekly learning", "/weekly learning"):
        return {"command": "weekly_learning_summary", "args": ""}
    if lower in ("weekly learning generate", "/weekly learning generate"):
        return {"command": "weekly_learning_generate", "args": ""}
    if lower in ("weekly learning send", "/weekly learning send"):
        return {"command": "weekly_learning_send", "args": ""}
    if lower in ("thesis reviews", "/thesis reviews"):
        return {"command": "thesis_reviews_list", "args": ""}
    if lower.startswith("thesis review run") or lower.startswith("/thesis review run"):
        return {"command": "thesis_review_run", "args": ""}

    # Session 31: Backtesting commands
    if lower in ("backtest status", "/backtest status"):
        return {"command": "backtest_status", "args": ""}
    if lower in ("backtest strategies", "/backtest strategies"):
        return {"command": "backtest_strategies", "args": ""}
    if lower in ("backtest results", "/backtest results"):
        return {"command": "backtest_results", "args": ""}
    if lower in ("challenger list", "/challenger list"):
        return {"command": "challenger_list", "args": ""}

    # Session 33: Risk Regime commands
    if lower in ("regime", "/regime"):
        return {"command": "regime_status", "args": ""}
    if lower in ("strategy rotation", "/strategy rotation"):
        return {"command": "strategy_rotation_signals", "args": ""}
    if lower in ("regime alignments", "/regime alignments"):
        return {"command": "regime_alignments", "args": ""}

    # Session 11: halt/resume trading commands
    if lower == "halt trading":
        return {"command": "halt_trading", "args": "all"}
    if lower == "resume trading":
        return {"command": "resume_trading", "args": "all"}
    if lower == "halt live":
        return {"command": "halt_trading", "args": "live"}
    if lower == "resume live":
        return {"command": "resume_trading", "args": "live"}
    if lower.startswith("halt strategy "):
        return {"command": "halt_trading", "args": f"strategy:{text[14:].strip()}"}
    if lower.startswith("resume strategy "):
        return {"command": "resume_trading", "args": f"strategy:{text[16:].strip()}"}
    if lower in ("backup docs", "backup documentation", "backup docs to google", "sync docs"):
        return {"command": "backup_docs", "args": ""}
    if lower in ("risk status", "risk"):
        return {"command": "risk_status", "args": ""}

    # Session 36: add video command — also auto-detect bare YouTube URLs
    if lower.startswith("add video ") or lower.startswith("add videos "):
        return {"command": "add_video", "args": text.split(None, 2)[-1] if len(text.split(None, 2)) > 2 else ""}
    if "youtube.com/watch" in lower or "youtu.be/" in lower:
        return {"command": "add_video", "args": text}

    # Session 36: add article command — also auto-detect bare article URLs
    if lower.startswith("add article ") or lower.startswith("add articles "):
        return {"command": "add_article", "args": text.split(None, 2)[-1] if len(text.split(None, 2)) > 2 else ""}
    if re.search(r'https?://\S+', lower) and "youtube.com" not in lower and "youtu.be" not in lower:
        return {"command": "add_article", "args": text}

    # Watch Directives (operator add-path) — watch ticker/sector/trend …, promote SYM
    if lower.startswith("watch "):
        return {"command": "watch", "args": text[6:].strip()}
    if lower.startswith("promote "):
        return {"command": "promote", "args": text[8:].strip()}

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

    # iris library
    if subcommand == "library":
        try:
            from iris_taxonomy_agent import get_library_status
            ls = get_library_status()
            rag = ls.get("rag", {})
            lines = [f"*Iris Library*", f"RAG: {rag.get('coverage_pct', 0)}% embedded",
                     f"Stale: {len(ls.get('stale_symbols', []))} symbols >7d old",
                     f"Dupes: {ls.get('duplicate_groups', 0)} groups",
                     f"Gaps: {len(ls.get('content_gaps', []))} categories thin"]
            return "\n".join(lines)
        except Exception as e:
            return f"Library error: {e}"

    # iris stale / iris gaps / iris dupes
    if subcommand == "stale":
        try:
            from iris_taxonomy_agent import get_stale_symbols
            stale = get_stale_symbols()
            if not stale:
                return "Iris: All symbols analyzed within 7 days."
            lines = [f"*Stale Symbols ({len(stale)}):*"]
            for s in stale[:10]:
                lines.append(f"  {s['symbol']}: {s['days_since']}d ago ({s['total_analyses']} total)")
            return "\n".join(lines)
        except Exception as e:
            return f"Stale check error: {e}"

    if subcommand == "gaps":
        try:
            from iris_taxonomy_agent import get_content_gaps
            gaps = get_content_gaps()
            if not gaps:
                return "Iris: No critical content gaps."
            lines = ["*Content Gaps (thin categories):*"]
            for g in gaps:
                lines.append(f"  {g['category']}: {g['news_30d']} news, {g['youtube_30d']} YT in 30d")
            return "\n".join(lines)
        except Exception as e:
            return f"Gaps error: {e}"

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


def _handle_add_video(args: str) -> str:
    """Add YouTube videos to ingestion. Accepts 1+ URLs, adds channels to tracking,
    and attempts immediate transcript ingestion."""
    import urllib.request as _ureq

    # Extract all YouTube URLs from the message
    urls = re.findall(r'https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})', args)
    if not urls:
        return "No YouTube URLs found. Paste one or more youtube.com/watch?v= links."

    video_ids = list(dict.fromkeys(urls))  # dedupe, preserve order
    lines = [f"*Processing {len(video_ids)} video(s)...*", ""]

    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from youtube_transcript_ingest import (
        ingest_video, get_video_metadata, extract_channel_id, get_channel_info, _get_conn as _yt_conn
    )

    # Resolve channels and add to tracking
    channels_added = set()
    for vid in video_ids:
        meta = get_video_metadata(vid)
        channel_name = meta.get("channel_name", "")
        if channel_name and channel_name not in channels_added:
            # Look up channel ID via YouTube Data API
            try:
                api_key = ""
                for line in (PROJECT_ROOT / ".env").read_text().splitlines():
                    if line.startswith("YOUTUBE_API_KEY="):
                        api_key = line.split("=", 1)[1].strip()
                        break
                if api_key:
                    lookup = f"https://www.googleapis.com/youtube/v3/videos?part=snippet&id={vid}&key={api_key}"
                    with _ureq.urlopen(lookup, timeout=10) as resp:
                        data = json.loads(resp.read())
                        if data.get("items"):
                            ch_id = data["items"][0]["snippet"]["channelId"]
                            conn = _yt_conn()
                            cur = conn.cursor()
                            cur.execute("""
                                INSERT INTO youtube_channels (channel_id, channel_name, channel_url, strategy_focus, added_by)
                                VALUES (%s, %s, %s, 'general', 'telegram')
                                ON CONFLICT (channel_id) DO UPDATE SET channel_name=EXCLUDED.channel_name
                            """, (ch_id, channel_name, f"https://www.youtube.com/channel/{ch_id}"))
                            conn.commit()
                            conn.close()
                            channels_added.add(channel_name)
            except Exception:
                pass

    # Attempt to ingest each video
    ingested = 0
    queued = 0
    skipped = 0
    for vid in video_ids:
        url = f"https://www.youtube.com/watch?v={vid}"
        result = ingest_video(url, added_by="telegram")

        if result.get("status") == "ingested":
            ingested += 1
            q = result.get("quality_score", 0)
            r = result.get("relevance_score", 0)
            lines.append(f"Ingested: _{result.get('title', vid)[:50]}_ (Q:{q} R:{r:.2f})")
        elif result.get("status") == "already_exists":
            skipped += 1
            lines.append(f"Already exists: `{vid}`")
        else:
            # Transcript fetch failed — queue for retry
            queued += 1
            meta = get_video_metadata(vid)
            try:
                conn = _yt_conn()
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO youtube_ingest_queue (video_id, url, title, channel_name)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (video_id) DO NOTHING
                """, (vid, url, meta.get("title", ""), meta.get("channel_name", "")))
                conn.commit()
                conn.close()
            except Exception:
                pass
            lines.append(f"Queued (IP blocked): _{meta.get('title', vid)[:50]}_")

    lines.append("")
    if channels_added:
        lines.append(f"*Channels tracked:* {', '.join(channels_added)}")
    lines.append(f"*Result:* {ingested} ingested, {skipped} existing, {queued} queued")
    if queued > 0:
        lines.append("_Queued videos will retry when YouTube IP block clears._")

    return "\n".join(lines)


def _handle_add_article(args: str) -> str:
    """Add article URLs to ingestion. Fetches page content, scores, and stores."""
    import urllib.request as _ureq

    # Extract all HTTP(S) URLs from the message
    urls = re.findall(r'https?://\S+', args)
    if not urls:
        return "No URLs found. Paste one or more article links."

    # Strip trailing punctuation from URLs
    urls = [re.sub(r'[),.\]}>]+$', '', u) for u in urls]
    urls = list(dict.fromkeys(urls))  # dedupe

    lines = [f"*Processing {len(urls)} article(s)...*", ""]

    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from content_scoring import score_content, tag_content

    conn = _get_conn()
    cur = conn.cursor()
    ingested = 0
    skipped = 0
    errors = 0

    for url in urls:
        try:
            # Check if already ingested
            cur.execute("SELECT 1 FROM news_articles WHERE source_url = %s LIMIT 1", (url[:500],))
            if cur.fetchone():
                skipped += 1
                lines.append(f"Already exists: `{url[:60]}`")
                continue

            # Fetch page content
            req = _ureq.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
            })
            with _ureq.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="replace")

            # Extract text with BS4
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            title = soup.title.string.strip() if soup.title and soup.title.string else url[:80]
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()

            # Prefer article/main content
            main = soup.find("article") or soup.find("main") or soup.find("div", class_="content") or soup
            text = main.get_text(separator=" ", strip=True)[:10000]

            if len(text) < 100:
                errors += 1
                lines.append(f"Too short: _{title[:50]}_")
                continue

            # Score and tag
            scores = score_content(title=title, text=text[:5000], source="telegram_article")
            tags = tag_content(text=text[:5000], title=title)

            # Save
            cur.execute("SAVEPOINT article_save")
            cur.execute("""
                INSERT INTO news_articles
                    (symbol, strategy_type, title, summary, source, source_url,
                     published_at, relevance_score, strategy_tags, agent_tags)
                VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s)
            """, (
                "manual_add",
                "manual_add",
                title[:500],
                text[:1000],
                "telegram_article",
                url[:500],
                scores.get("relevance_score", 0.5),
                json.dumps(tags.get("strategy_tags", [])),
                json.dumps(tags.get("agent_tags", [])),
            ))
            conn.commit()
            ingested += 1
            q = scores.get("quality_score", 0)
            r = scores.get("relevance_score", 0)
            lines.append(f"Ingested: _{title[:50]}_ (Q:{q} R:{r:.2f})")

        except Exception as e:
            errors += 1
            try:
                cur.execute("ROLLBACK TO SAVEPOINT article_save")
            except Exception:
                conn.rollback()
            lines.append(f"Error: `{url[:40]}` — {str(e)[:60]}")

    conn.close()

    lines.append("")
    lines.append(f"*Result:* {ingested} ingested, {skipped} existing, {errors} errors")

    return "\n".join(lines)


def _notify_both(msg: str):
    """Broadcast a one-line directive event to BOTH operator chat IDs (best-effort)."""
    try:
        import requests
        tok = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not tok:
            return
        for cid in __import__("tg_chat_ids").chat_ids():
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          json={"chat_id": cid, "text": msg}, timeout=8)
    except Exception:
        pass


def _handle_watch(args: str) -> str:
    """watch ticker RKLB [because <thesis>] | watch sector Semiconductors | watch trend AI datacenter.
    Creates an operator directive under the app role (firewall: Hermes can never write this)."""
    import json as _j
    parts = args.split(None, 1)
    if not parts:
        return "Usage: watch ticker SYM [because …] | watch sector NAME | watch trend KEYWORDS"
    kind = parts[0].lower()
    rest = (parts[1].strip() if len(parts) > 1 else "")
    if kind not in ("ticker", "sector", "trend"):
        # bareword → treat as a ticker symbol ("watch RKLB")
        kind, rest = "ticker", args.strip()
    rationale = None
    low = rest.lower()
    if " because " in low:
        i = low.index(" because ")
        rest, rationale = rest[:i].strip(), rest[i + 9:].strip()
    if kind == "ticker":
        sym = (rest.split()[0].upper() if rest.split() else "")
        if not sym:
            return "Need a symbol: watch ticker RKLB"
        spec, label = {"symbol": sym}, f"watch {sym}"
    elif kind == "sector":
        if not rest:
            return "Need a sector: watch sector Semiconductors"
        spec, label = {"finviz_sector": rest}, f"sector {rest}"
    else:
        kws = [k.strip() for k in (rest.split(",") if "," in rest else rest.split())]
        spec, label = {"keywords": [k for k in kws if k]}, f"trend {rest[:40]}"
    try:
        # Watch Desk v2 (B1): operator creations get a SOFT warning, never a block
        _dup_warn = ""
        if kind == "trend":
            try:
                from lib.watch_directive_gate import family_gate
                _g = family_gate(label, "trend")
                if not _g["allow"]:
                    _dup_warn = (f"\n⚠ near-duplicate of #{_g['survivor_id']} "
                                 f"'{_g['survivor_label']}' — consider merging instead.")
            except Exception:
                pass
        conn = _get_conn(); cur = conn.cursor()
        cur.execute("""INSERT INTO watch_directives (kind, label, spec, rationale, created_by)
                       VALUES (%s, %s, %s::jsonb, %s, 'operator') RETURNING id""",
                    (kind, label, _j.dumps(spec), rationale))
        did = cur.fetchone()[0]; conn.commit()
        msg = (f"✓ Watch directive #{did}: {kind} — {label}" + _dup_warn
               + (f"\nthesis: {rationale}" if rationale else "")
               + "\nTrade AI + Hermes will honor it (Hermes proposes via staging only).")
        _notify_both(f"📌 New watch directive #{did}: {kind} — {label}")
        return msg
    except Exception as e:
        return f"watch error: {e}"


def _handle_promote(args: str) -> str:
    """promote SYM — operator one-tap promote the latest STAGED hit for SYM through the real engine."""
    sym = (args.split()[0].upper() if args.split() else "")
    if not sym:
        return "Usage: promote SYM"
    try:
        conn = _get_conn(); cur = conn.cursor()
        cur.execute("""SELECT directive_id FROM watch_directive_hits
                       WHERE symbol=%s AND promotion_status='STAGED_FOR_REVIEW'
                       ORDER BY surfaced_at DESC LIMIT 1""", (sym,))
        row = cur.fetchone()
        if not row:
            return f"No staged hit for {sym} to promote (nothing awaiting one-tap)."
        did = row[0]
        import directive_promotion as _dp
        res = _dp.promote_directive_lead(sym, did, "telegram operator one-tap", "operator",
                                         auto=True, actor="operator")
        st = res.get("status")
        qual = res.get("qualified_strategies") or []
        out = f"{sym}: {st}" + (f" → {', '.join(qual)}" if qual else "")
        _notify_both(f"✅ Operator promoted {sym} → {st}")
        return out
    except Exception as e:
        return f"promote error: {e}"


def process_command(cmd: dict) -> str:
    """Process a parsed command and return response text."""
    command = cmd["command"]
    args = cmd["args"]

    if command == "watch":
        return _handle_watch(args)
    if command == "promote":
        return _handle_promote(args)

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

    if command == "cio":
        # Route to CIO query engine — deterministic, zero model calls
        import subprocess
        cio_cmd = [str(PROJECT_ROOT / ".venv/bin/python"), str(PROJECT_ROOT / "scripts/cio_commands.py")]
        if args in ("actions", "portfolio", "hermes", "risk", "status"):
            cio_cmd.append(args)
        else:
            cio_cmd.append("status")  # default: full dashboard
        try:
            result = subprocess.run(cio_cmd, capture_output=True, text=True, timeout=15, cwd=str(PROJECT_ROOT))
            output = result.stdout.strip()
            return f"🤖 *CIO Alex*\n\n{output}\n\n_Zero model calls · CIO Data Broker · Shadow-advisory only_"
        except Exception as e:
            return f"CIO query error: {e}"

    if command == "advisory":
        # Advisory desk brief + rate/ack/snooze/history — zero model calls
        import subprocess
        py = str(PROJECT_ROOT / ".venv/bin/python")
        a = (args or "").strip()
        try:
            if not a or a in ("brief", "status", "desk"):
                result = subprocess.run(
                    [py, str(PROJECT_ROOT / "scripts/advisory_telegram_brief.py"), "--print"],
                    capture_output=True, text=True, timeout=20, cwd=str(PROJECT_ROOT),
                )
                body = result.stdout.strip()
                return f"📋 *Advisory Desk*\n\n{body}\n\n_READ_ONLY_ADVISORY · Open /v3/advisory_"
            # Subcommands → advisory_commands.py
            parts = a.split()
            cmd = [py, str(PROJECT_ROOT / "scripts/advisory_commands.py")] + parts
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, cwd=str(PROJECT_ROOT))
            out = (result.stdout or result.stderr or "").strip()
            return f"📋 *Advisory*\n\n{out}"
        except Exception as e:
            return f"Advisory command error: {e}"

    if command in ("calibration", "accuracy"):
        try:
            import psycopg2.extras
            conn = _get_conn()
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT agent_name, accuracy_pct, correct_count, wrong_count, trending
                FROM agent_calibration WHERE window_days=90 AND strategy_type IS NULL
                ORDER BY agent_name
            """)
            rows = cur.fetchall()
            conn.close()
            if not rows:
                return "No calibration data yet — need more closed trades (≥3 per agent)"
            lines = ["*Agent Accuracy (90 days):*"]
            for r in rows:
                acc = f"{r['accuracy_pct']:.0f}%" if r['accuracy_pct'] else "N/A"
                trend = {'IMPROVING': '↑', 'DECLINING': '↓', 'STABLE': '→'}.get(r.get('trending') or '', '')
                lines.append(f"• {r['agent_name']}: {acc} ({r.get('correct_count',0)}✓/{r.get('wrong_count',0)}✗) {trend}")
            return '\n'.join(lines)
        except Exception as e:
            return f"Calibration error: {e}"

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

    if command == "run_promoter":
        import subprocess
        dry = "dry" in (args or "").lower()
        cmd = [sys.executable, os.path.join(str(PROJECT_ROOT), "scripts", "incubator_proposal_promoter.py")]
        cmd.append("--dry-run" if dry else "--run")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=str(PROJECT_ROOT))
            output = (result.stdout or "") + (result.stderr or "")
            # Extract the summary lines
            lines = [l.strip() for l in output.strip().splitlines() if l.strip()]
            summary = "\n".join(lines[-10:]) if len(lines) > 10 else "\n".join(lines)
            prefix = "[DRY RUN] " if dry else ""
            return f"{prefix}Promoter executed:\n{summary}"
        except subprocess.TimeoutExpired:
            return "Promoter timed out after 120s"
        except Exception as e:
            return f"Promoter failed: {e}"

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

    # ── Topic Monitor commands ──
    if command == "topic_status":
        conn = _get_conn()
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT t.topic_id, t.display_name, t.priority, t.last_searched,
                (SELECT COUNT(*) FROM news_articles WHERE strategy_type = t.topic_id
                 AND created_at > NOW() - INTERVAL '1 day' * t.max_age_days) as articles,
                (SELECT COUNT(*) FROM youtube_transcripts WHERE added_by = 'topic_ingestion'
                 AND ingested_at > NOW() - INTERVAL '1 day' * t.max_age_days
                 AND strategy_tags::text LIKE '%%' || t.topic_id || '%%') as transcripts,
                t.min_articles
            FROM topic_monitor t WHERE t.enabled = true ORDER BY t.priority
        """)
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return "No active topics in topic_monitor table."
        lines = ["*Topic Monitor Status:*", ""]
        for r in rows:
            total = (r['articles'] or 0) + (r['transcripts'] or 0)
            gap = "GAP" if total < r['min_articles'] else "OK"
            last = r['last_searched'].strftime('%m/%d') if r['last_searched'] else 'never'
            lines.append(f"  P{r['priority']} [{gap}] {r['display_name']}: {r['articles']}a + {r['transcripts']}t (last: {last})")
        return "\n".join(lines)

    if command == "topic_add":
        # Parse: "topic add SSDI trust NY" → creates topic with that name
        topic_text = args.strip()
        if not topic_text:
            return "Usage: `topic add <topic name>`\nExample: `topic add SSDI trust NY asset protection`"
        topic_id = topic_text.lower().replace(" ", "_")[:50]
        display = topic_text.title()[:100]
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO topic_monitor (topic_id, display_name, search_queries, video_queries,
                priority, agent_owner, agent_tags, strategy_tags,
                personal_context, saved_search_urls)
            VALUES (%s, %s, %s, %s, 3, 'Alex', '["Alex"]'::jsonb, '[]'::jsonb,
                    '', '[]'::jsonb)
            ON CONFLICT (topic_id) DO NOTHING
        """, (topic_id, display,
              json.dumps([topic_text + " 2026", topic_text + " strategy"]),
              json.dumps([topic_text + " explained", topic_text + " planning"])))
        conn.commit()
        conn.close()
        return f"Topic added: *{display}* (`{topic_id}`)\nRun: `topic run {topic_id}`"

    if command == "topic_url":
        # Parse: "topic url trust_estate https://google.com/search?..."
        parts = args.split(None, 1)
        if len(parts) < 2 or not parts[1].startswith("http"):
            return "Usage: `topic url <topic_id> <google_search_url>`\nExample: `topic url trust_estate https://www.google.com/search?udm=7&q=SSDI+trusts+NY`"
        topic_id = parts[0].strip()
        url = parts[1].strip()
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE topic_monitor
            SET saved_search_urls = saved_search_urls || %s::jsonb, updated_at = NOW()
            WHERE topic_id = %s AND enabled = true
        """, (json.dumps([url]), topic_id))
        affected = cur.rowcount
        conn.commit()
        conn.close()
        if affected == 0:
            return f"Topic `{topic_id}` not found or disabled."
        return f"URL added to *{topic_id}*. Run `topic run {topic_id}` to ingest."

    if command == "topic_run":
        topic_id = args.strip() if args.strip() != "all" else None
        try:
            import subprocess
            cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / "topic_ingestion.py")]
            if topic_id:
                cmd.extend(["--topic", topic_id])
            subprocess.Popen(cmd, stdout=open(str(PROJECT_ROOT / "logs" / "topic_ingestion.log"), "a"),
                             stderr=subprocess.STDOUT, cwd=str(PROJECT_ROOT))
            label = f"`{topic_id}`" if topic_id else "all topics"
            return f"Topic ingestion started for {label}. Check logs/topic_ingestion.log or /v2/topic-monitor"
        except Exception as e:
            return f"Error starting topic ingestion: {e}"

    # Session 36: Add YouTube videos from Telegram
    if command == "add_video":
        return _handle_add_video(args)

    # Session 36: Add articles from Telegram
    if command == "add_article":
        return _handle_add_article(args)

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

    # ── Proposal approval/rejection ──
    if command == "approve_proposal":
        try:
            pid = int(args.split()[0])
            reason = " ".join(args.split()[1:]) or "approved via Telegram"
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("UPDATE watchlist_proposals SET status='approved', reviewed_by='john_telegram', reviewed_at=NOW() WHERE id=%s AND status='proposed' RETURNING id, symbol, action", (pid,))
            row = cur.fetchone()
            if not row:
                conn.close()
                return f"Proposal #{pid} not found or already processed."
            cur.execute("""INSERT INTO agent_feedback_log (proposal_id, symbol, action, decision, reviewer, reason, created_at)
                          VALUES (%s, %s, %s, 'approved', 'john_telegram', %s, NOW())""",
                        (row[0], row[1], row[2], reason))
            conn.commit()
            conn.close()
            return f"Proposal #{pid} approved: {row[1]} {row[2]}"
        except ValueError:
            return "Usage: approve proposal <id> [reason]"
        except Exception as e:
            return f"Approve error: {e}"

    if command == "reject_proposal":
        try:
            pid = int(args.split()[0])
            reason = " ".join(args.split()[1:]) or "rejected via Telegram"
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("UPDATE watchlist_proposals SET status='rejected', reviewed_by='john_telegram', reviewed_at=NOW() WHERE id=%s AND status='proposed' RETURNING id, symbol, action", (pid,))
            row = cur.fetchone()
            if not row:
                conn.close()
                return f"Proposal #{pid} not found or already processed."
            cur.execute("""INSERT INTO agent_feedback_log (proposal_id, symbol, action, decision, reviewer, reason, created_at)
                          VALUES (%s, %s, %s, 'rejected', 'john_telegram', %s, NOW())""",
                        (row[0], row[1], row[2], reason))
            conn.commit()
            conn.close()
            return f"Proposal #{pid} rejected: {row[1]} {row[2]}"
        except ValueError:
            return "Usage: reject proposal <id> [reason]"
        except Exception as e:
            return f"Reject error: {e}"

    # ── Task approval/rejection ──
    if command == "approve_task":
        try:
            tid = int(args.split()[0])
            decision = " ".join(args.split()[1:]) or "approved via Telegram"
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("""UPDATE john_decision_queue SET status='decided_action', john_decision=%s,
                          john_reasoning='approved via Telegram', decided_at=NOW()
                          WHERE id=%s AND status='pending_john' RETURNING id, symbol, title""", (decision, tid))
            row = cur.fetchone()
            if not row:
                conn.close()
                return f"Task #{tid} not found or already resolved."
            cur.execute("""INSERT INTO john_decision_history (decision_id, old_status, new_status, decision, reasoning)
                          VALUES (%s, 'pending_john', 'decided_action', %s, 'Telegram approval')""", (row[0], decision))
            conn.commit()
            conn.close()
            return f"Task #{tid} approved: {row[1]} — {row[2]}"
        except ValueError:
            return "Usage: approve task <id> [decision]"
        except Exception as e:
            return f"Task approve error: {e}"

    if command == "reject_task":
        try:
            tid = int(args.split()[0])
            reason = " ".join(args.split()[1:]) or "rejected via Telegram"
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("""UPDATE john_decision_queue SET status='rejected', john_decision=%s,
                          john_reasoning='rejected via Telegram', decided_at=NOW()
                          WHERE id=%s AND status='pending_john' RETURNING id, symbol, title""", (reason, tid))
            row = cur.fetchone()
            if not row:
                conn.close()
                return f"Task #{tid} not found or already resolved."
            cur.execute("""INSERT INTO john_decision_history (decision_id, old_status, new_status, decision, reasoning)
                          VALUES (%s, 'pending_john', 'rejected', %s, 'Telegram rejection')""", (row[0], reason))
            conn.commit()
            conn.close()
            return f"Task #{tid} rejected: {row[1]} — {row[2]}"
        except ValueError:
            return "Usage: reject task <id> [reason]"
        except Exception as e:
            return f"Task reject error: {e}"

    # ── List pending proposals ──
    if command == "list_proposals":
        try:
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("SELECT id, symbol, action, confidence FROM watchlist_proposals WHERE status='proposed' ORDER BY id LIMIT 10")
            rows = cur.fetchall()
            conn.close()
            if not rows:
                return "No pending proposals."
            lines = ["*Pending Proposals:*"]
            for r in rows:
                lines.append(f"  #{r[0]} {r[1]} → {r[2]} (conf:{r[3]:.0%})" if r[3] else f"  #{r[0]} {r[1]} → {r[2]}")
            lines.append(f"\n_approve proposal <id>_ or _reject proposal <id>_")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    # ── List pending tasks ──
    if command == "list_tasks":
        try:
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("SELECT id, symbol, title, priority FROM john_decision_queue WHERE status='pending_john' ORDER BY priority, id LIMIT 10")
            rows = cur.fetchall()
            conn.close()
            if not rows:
                return "No pending tasks."
            lines = ["*Pending Tasks:*"]
            for r in rows:
                lines.append(f"  #{r[0]} [{r[3]}] {r[1]} — {r[2][:60]}")
            lines.append(f"\n_approve task <id>_ or _reject task <id>_")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    # ── List debates ──
    if command == "list_debates":
        try:
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("SELECT id, symbol, trigger_source, consensus_recommendation, consensus_score, created_at FROM agent_debate_log ORDER BY created_at DESC LIMIT 10")
            rows = cur.fetchall()
            conn.close()
            if not rows:
                return "No debates recorded."
            lines = ["*Recent Debates:*"]
            for r in rows:
                score = f"{float(r[4]):.0%}" if r[4] else "?"
                lines.append(f"  #{r[0]} {r[1]} — {r[3] or 'pending'} ({score}) via {r[2]}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    # ── Outcome lessons ──
    if command == "lessons":
        try:
            conn = _get_conn()
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT config FROM agent_intelligence_rules WHERE rule_type='outcome_lessons' AND rule_key='latest'")
            row = cur.fetchone()
            conn.close()
            if row and row.get("config"):
                cfg = row["config"]
                if isinstance(cfg, str):
                    cfg = json.loads(cfg)
                lt = cfg.get("text", "")
                if lt:
                    return f"\U0001f4da *Outcome Lessons (latest)*\n\n{lt}"
            return "\U0001f4da No outcome lessons yet (accumulating — need 7+ days of decisions)."
        except Exception as e:
            return f"Lessons error: {e}"

    # ── Scalp stats ──
    if command == "scalp_stats":
        try:
            conn = _get_conn()
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT count(*) as total,
                       count(*) FILTER (WHERE outcome_status LIKE 'profit%%') as wins,
                       count(*) FILTER (WHERE outcome_status LIKE 'loss%%') as losses,
                       count(*) FILTER (WHERE outcome_status = 'flat') as flat,
                       round(avg(pct_move_24h)::numeric, 2) as avg_move
                FROM scalp_decision_outcomes
                WHERE scored_at > NOW() - INTERVAL '30 days'
            """)
            r = cur.fetchone()
            conn.close()
            if not r or r["total"] == 0:
                return "\U0001f4ca No scalp outcomes scored yet (need 24h of alerts first)."
            win_rate = r["wins"] / r["total"] * 100
            return (f"\U0001f4ca *Scalp 30-day stats*\n"
                    f"Total alerts: {r['total']}\n"
                    f"Wins: {r['wins']} ({win_rate:.1f}%)\n"
                    f"Flat: {r['flat']}\n"
                    f"Losses: {r['losses']}\n"
                    f"Avg 24h move: {float(r['avg_move'] or 0):.2f}%")
        except Exception as e:
            return f"Scalp stats error: {e}"

    # ── RAG context for a symbol ──
    if command == "rag":
        sym = args.strip().upper() if args else None
        if not sym:
            return "Usage: `rag SCHD` — show what agents see in RAG for a symbol."
        try:
            sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from rag_retrieval import get_rag_context, format_rag_context_for_prompt
            conn = _get_conn()
            items = get_rag_context(sym, limit=7, conn=conn)
            conn.close()
            if items:
                return f"*RAG Context for {sym}*\n\n{format_rag_context_for_prompt(items, sym)}"
            return f"No RAG context found for {sym}."
        except Exception as e:
            return f"RAG error: {e}"

    # ── Agent confidence trend ──
    if command == "confidence":
        agent = args.strip().lower() if args else None
        if not agent:
            return "Usage: `confidence maria` — 30-day confidence trend for an agent."
        try:
            conn = _get_conn()
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT date_trunc('day', created_at)::date as day,
                       round(avg(confidence)::numeric, 3) as avg_conf, count(*) as cnt
                FROM watchlist_agent_results
                WHERE agent ILIKE %s AND created_at > NOW() - INTERVAL '30 days'
                GROUP BY 1 ORDER BY 1 DESC LIMIT 10
            """, (f"%{agent}%",))
            rows = cur.fetchall()
            conn.close()
            if not rows:
                return f"No results for agent '{agent}' in last 30 days."
            lines = [f"\U0001f4c8 *Confidence: {agent}* (last 30d)", ""]
            for r in rows:
                bar = "\u2588" * int(float(r["avg_conf"]) * 20)
                lines.append(f"  {r['day']} | {float(r['avg_conf']):.3f} ({r['cnt']}x) {bar}")
            return "\n".join(lines)
        except Exception as e:
            return f"Confidence error: {e}"

    # ── Learning loop status ──
    if command == "learning":
        try:
            conn = _get_conn()
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT count(*) as cnt FROM agent_intelligence_rules WHERE rule_type='outcome_lessons'")
            lessons = cur.fetchone()["cnt"]
            cur.execute("SELECT count(*) as total, count(*) FILTER (WHERE outcome_score IS NOT NULL) as scored FROM decision_outcomes")
            outcomes = cur.fetchone()
            cur.execute("SELECT count(*) FROM content_embeddings")
            rag_total = cur.fetchone()["count"]
            cur.execute("SELECT count(*) FROM scalp_decision_outcomes")
            scalp_scored = cur.fetchone()["count"]
            conn.close()
            return (f"\U0001f9e0 *Learning Loop Status*\n\n"
                    f"Outcome lessons: {lessons} rules written\n"
                    f"Decision outcomes: {outcomes['scored']}/{outcomes['total']} scored\n"
                    f"RAG items indexed: {rag_total}\n"
                    f"Scalp outcomes scored: {scalp_scored}\n\n"
                    f"_Lessons feed into all agent prompts at 5:30 AM._")
        except Exception as e:
            return f"Learning status error: {e}"

    # ── Watchlist health ──
    if command == "watchlist_health":
        try:
            conn = _get_conn()
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT count(*) as cnt FROM watchlist_final_synthesis wfs
                JOIN watchlist_symbol_master wsm ON wfs.symbol = wsm.symbol
                WHERE (wsm.in_ai_watchlist = true OR wsm.in_personal_watchlist = true)
                  AND (wfs.synthesis_narrative ILIKE '%%LLM error%%'
                       OR wfs.synthesis_narrative ILIKE '%%All providers failed%%')
            """)
            llm_errors = cur.fetchone()['cnt']
            cur.execute("""
                SELECT count(*) as cnt FROM watchlist_symbol_master
                WHERE (in_ai_watchlist = true OR in_personal_watchlist = true)
                  AND updated_at < NOW() - INTERVAL '48 hours'
            """)
            stale = cur.fetchone()['cnt']
            cur.execute("""
                SELECT count(*) as cnt FROM watchlist_symbol_master
                WHERE (in_ai_watchlist = true OR in_personal_watchlist = true)
                  AND ideal_entry IS NULL
            """)
            no_entry = cur.fetchone()['cnt']
            conn.close()
            ok = llm_errors == 0 and stale == 0
            icon = "\u2705" if ok else "\u26a0\ufe0f"
            return (
                f"{icon} *Watchlist Health*\n\n"
                f"LLM errors: {llm_errors}\n"
                f"Stale (48h+): {stale}\n"
                f"Missing entry levels: {no_entry}\n\n"
                f"{'All clean.' if ok else 'Aegis will auto-fix tonight at 8PM.'}"
            )
        except Exception as e:
            return f"Watchlist health error: {e}"

    # Session 11: halt/resume/risk commands
    if command == "halt_trading":
        try:
            conn = _get_conn()
            cur = conn.cursor()
            target = args
            if target == "all":
                cur.execute("UPDATE system_controls SET value='true', updated_at=NOW(), updated_by='telegram' WHERE key='halt_all_trading'")
                cur.execute("INSERT INTO audit_log (event_type, decision, reason_text, actor) VALUES ('halt', 'halt_all_trading', 'Global halt via Telegram', 'john')")
                conn.commit(); conn.close()
                return "\U0001f6d1 GLOBAL TRADING HALT ENABLED\nAll strategies blocked until `resume trading`."
            elif target == "live":
                cur.execute("UPDATE system_controls SET value='true', updated_at=NOW(), updated_by='telegram' WHERE key='halt_live_only'")
                cur.execute("INSERT INTO audit_log (event_type, decision, reason_text, actor) VALUES ('halt', 'halt_live_only', 'Live halt via Telegram', 'john')")
                conn.commit(); conn.close()
                return "\U0001f6d1 LIVE TRADING HALT ENABLED\nPaper trading continues. Live blocked until `resume live`."
            elif target.startswith("strategy:"):
                sid = target.split(":", 1)[1].strip()
                key = f"halt_{sid}_strategy"
                cur.execute("UPDATE system_controls SET value='true', updated_at=NOW(), updated_by='telegram' WHERE key=%s", [key])
                if cur.rowcount == 0:
                    conn.close()
                    return f"Unknown strategy: {sid}"
                cur.execute("INSERT INTO audit_log (event_type, decision, reason_text, actor) VALUES ('halt', %s, %s, 'john')", [key, f'Strategy halt via Telegram: {sid}'])
                conn.commit(); conn.close()
                return f"\U0001f6d1 STRATEGY HALT: {sid}\nBlocked until `resume strategy {sid}`."
            conn.close()
            return "Unknown halt target"
        except Exception as e:
            return f"Halt error: {e}"

    if command == "resume_trading":
        try:
            conn = _get_conn()
            cur = conn.cursor()
            target = args
            if target == "all":
                cur.execute("UPDATE system_controls SET value='false', updated_at=NOW(), updated_by='telegram' WHERE key='halt_all_trading'")
                cur.execute("INSERT INTO audit_log (event_type, decision, reason_text, actor) VALUES ('resume', 'halt_all_trading', 'Global resume via Telegram', 'john')")
                conn.commit(); conn.close()
                return "\u2705 GLOBAL TRADING RESUMED\nAll strategies active."
            elif target == "live":
                cur.execute("UPDATE system_controls SET value='false', updated_at=NOW(), updated_by='telegram' WHERE key='halt_live_only'")
                cur.execute("INSERT INTO audit_log (event_type, decision, reason_text, actor) VALUES ('resume', 'halt_live_only', 'Live resume via Telegram', 'john')")
                conn.commit(); conn.close()
                return "\u2705 LIVE TRADING RESUMED"
            elif target.startswith("strategy:"):
                sid = target.split(":", 1)[1].strip()
                key = f"halt_{sid}_strategy"
                cur.execute("UPDATE system_controls SET value='false', updated_at=NOW(), updated_by='telegram' WHERE key=%s", [key])
                cur.execute("INSERT INTO audit_log (event_type, decision, reason_text, actor) VALUES ('resume', %s, %s, 'john')", [key, f'Strategy resume via Telegram: {sid}'])
                conn.commit(); conn.close()
                return f"\u2705 STRATEGY RESUMED: {sid}"
            conn.close()
            return "Unknown resume target"
        except Exception as e:
            return f"Resume error: {e}"

    if command == "backup_docs":
        try:
            import subprocess
            result = subprocess.run(
                [str(PROJECT_ROOT / ".venv/bin/python"), str(PROJECT_ROOT / "scripts/sync-docs-to-drive.py")],
                capture_output=True, text=True, timeout=600, cwd=str(PROJECT_ROOT)
            )
            # Parse last log line for summary
            lines = result.stdout.strip().split('\n')
            summary = lines[-1] if lines else "completed"
            if result.returncode == 0:
                return f"*\U0001f4e4 Docs backed up to Google Drive*\n\n{summary}"
            else:
                return f"*\u26a0 Backup had issues*\n\n{summary}\n\nstderr: {result.stderr[-200:]}"
        except subprocess.TimeoutExpired:
            return "\u26a0 Backup timed out (>10 min). Check logs/drive-docs-sync.log"
        except Exception as e:
            return f"Backup error: {e}"

    if command == "risk_status":
        try:
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("SELECT key, value, updated_at FROM system_controls ORDER BY key")
            rows = cur.fetchall()
            lines = ["*\U0001f6e1 Risk Gate Status*", ""]
            active_halts = 0
            for key, value, updated_at in rows:
                icon = "\U0001f534" if value == 'true' else "\U0001f7e2"
                lines.append(f"{icon} `{key}`: {value}")
                if value == 'true':
                    active_halts += 1
            # Risk gate summary (24h)
            cur.execute("""
                SELECT result, COUNT(*) FROM risk_gate_results
                WHERE created_at > NOW() - INTERVAL '24 hours'
                GROUP BY result
            """)
            rg_rows = cur.fetchall()
            if rg_rows:
                lines.append("")
                lines.append("*Risk Gate (24h):*")
                for result, cnt in rg_rows:
                    lines.append(f"  {result}: {cnt}")
            conn.close()
            if active_halts > 0:
                lines.insert(1, f"\u26a0\ufe0f {active_halts} active halt(s)")
            return "\n".join(lines)
        except Exception as e:
            return f"Risk status error: {e}"

    # Session 13: paper trade commands
    if command == "pt_open":
        try:
            from paper_trade_logger import parse_pt_command, create_proposal, create_manual_proposal
            ok, params, err = parse_pt_command(args)
            if not ok:
                return f"\u274c {err}"
            if params.get('auto'):
                result = create_proposal(params['symbol'], account=params.get('account', 'ALPACA_PAPER'))
            else:
                result = create_manual_proposal(
                    params['symbol'], params['shares'], params['entry'],
                    params['stop'], params['target'], params.get('account', 'ALPACA_PAPER'))
            if result.get('success'):
                pid = result['proposal_id']
                sym = result['symbol']
                e, s, t = result.get('entry', 0), result.get('stop', 0), result.get('target', 0)
                sh = result.get('shares', 0)
                dr = result.get('dollar_risk', 0)
                rr = result.get('rr', 0)
                rg = result.get('risk_gate_result', '?')
                return (f"\U0001f4dd PAPER PROPOSAL #{pid}\n"
                        f"{sym} | {result.get('account', 'ALPACA_PAPER')}\n"
                        f"Entry: ${e:.2f} x {sh} = ${e*sh:.0f}\n"
                        f"Stop: ${s:.2f} | Target: ${t:.2f}\n"
                        f"Risk: ${dr:.0f} | R:R {rr:.1f}\n"
                        f"Risk gate: {rg}\n\n"
                        f"Approve: /ptapprove {pid}\n"
                        f"Reject: /ptreject {pid} reason\n"
                        f"View all: /ptpending")
            return f"\u274c {result.get('message', 'Proposal failed')}"
        except Exception as e:
            return f"\u274c Paper proposal error: {e}"

    if command == "pt_pending":
        try:
            from paper_trade_logger import get_pending_proposals
            proposals = get_pending_proposals()
            if not proposals:
                return "\U0001f4cb No pending paper proposals.\nCreate one: /pt SYMBOL auto"
            lines = [f"\U0001f4cb PENDING PAPER PROPOSALS ({len(proposals)})\n"]
            for p in proposals[:10]:
                lines.append(
                    f"#{p['id']} {p['symbol']} {p.get('signal_grade','?')} "
                    f"${float(p.get('proposed_entry',0)):.2f} x {p.get('proposed_shares',0)} "
                    f"risk=${float(p.get('proposed_dollar_risk',0)):.0f} "
                    f"RG:{p.get('risk_gate_result','?')}")
            lines.append(f"\nApprove: /ptapprove ID\nReject: /ptreject ID reason")
            return '\n'.join(lines)
        except Exception as e:
            return f"\u274c Pending proposals error: {e}"

    if command == "pt_approve":
        try:
            from paper_trade_logger import approve_proposal
            from telegram_callback_handler import parse_pt_command
            parts = args.split()
            if not parts:
                return "\u274c Usage: /ptapprove ID [shares=N target=N stop=N]"
            # Support both positional (legacy) and key=value (new) syntax
            has_kv = any("=" in p for p in parts[1:])
            if has_kv:
                pid, kv_overrides = parse_pt_command("/ptapprove " + args)
                overrides = {}
                if kv_overrides.get("shares"):
                    overrides["override_shares"] = kv_overrides["shares"]
                if kv_overrides.get("target"):
                    overrides["override_target"] = kv_overrides["target"]
                if kv_overrides.get("stop"):
                    overrides["override_stop"] = kv_overrides["stop"]
            else:
                pid = int(parts[0])
                overrides = {}
                if len(parts) >= 5:
                    overrides = {'override_shares': int(parts[1]), 'override_entry': float(parts[2]),
                                 'override_stop': float(parts[3]), 'override_target': float(parts[4])}
            result = approve_proposal(pid, **overrides)
            if result.get('success'):
                return (f"\u2705 PAPER TRADE #{result['paper_trade_id']} OPENED\n"
                        f"{result['symbol']} | {result.get('account','ALPACA_PAPER')}\n"
                        f"Entry: ${result['entry']:.2f} x {result['shares']}\n"
                        f"Stop: ${result['stop']:.2f} | Target: ${result['target']:.2f}\n"
                        f"Risk: ${result['dollar_risk']:.0f}\n"
                        f"Risk gate: {result.get('risk_gate','?')}\n"
                        f"Close: /ptclose {result['symbol']} PRICE")
            return f"\u274c {result.get('message', 'Approval failed')}"
        except Exception as e:
            return f"\u274c Approve error: {e}"

    if command == "pt_reject":
        try:
            from paper_trade_logger import reject_proposal
            parts = args.split(maxsplit=1)
            if not parts:
                return "\u274c Usage: /ptreject ID [reason]"
            pid = int(parts[0])
            reason = parts[1] if len(parts) > 1 else 'manual'
            result = reject_proposal(pid, reason)
            return f"\u2705 {result['message']}" if result.get('success') else f"\u274c {result['message']}"
        except Exception as e:
            return f"\u274c Reject error: {e}"

    if command == "pt_close":
        try:
            from paper_trade_logger import close_paper_trade, format_close_response
            parts = args.split()
            if len(parts) < 2:
                return "\u274c Usage: /ptclose SYMBOL PRICE [reason]"
            symbol = parts[0].upper()
            try:
                exit_price = float(parts[1])
            except ValueError:
                return "\u274c Invalid price. Usage: /ptclose SYMBOL PRICE [reason]"
            reason = parts[2] if len(parts) > 2 else 'manual'
            result = close_paper_trade(symbol, exit_price, reason)
            if result.get('success'):
                return format_close_response(result)
            return f"\u274c {result.get('message', 'Close failed')}"
        except Exception as e:
            return f"\u274c Paper close error: {e}"

    if command == "pt_positions":
        try:
            from paper_trade_logger import get_open_positions, format_positions_response
            positions = get_open_positions()
            return format_positions_response(positions)
        except Exception as e:
            return f"\u274c Paper positions error: {e}"

    if command == "pt_pnl":
        try:
            from paper_trade_logger import get_pnl_summary, format_pnl_response
            summary = get_pnl_summary()
            return format_pnl_response(summary)
        except Exception as e:
            return f"\u274c Paper P&L error: {e}"

    # ── Session 27: Paper Order Modification handlers ──────────────────
    if command == "paper_mods_list":
        try:
            from session13_db import get_conn
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("""SELECT proposal_id, symbol, action, reason, confidence, status, created_at
                           FROM paper_order_modification_proposals
                           WHERE status IN ('proposed', 'approved')
                           ORDER BY created_at DESC LIMIT 10""")
            rows = cur.fetchall()
            conn.close()
            if not rows:
                return "No pending paper modification proposals."
            lines = ["Paper Mod Proposals:"]
            for r in rows:
                lines.append(f"  {r[0]}: {r[1]} {r[2]} [{r[5]}] conf={r[4]} — {r[3][:60]}")
            lines.append("\nDetails: paper mod <id>\nApprove: approve paper mod <id>")
            return "\n".join(lines)
        except Exception as e:
            return f"Error listing mods: {e}"

    if command == "paper_mod_detail":
        try:
            from session13_db import get_conn
            pid = args.strip()
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("""SELECT proposal_id, symbol, action, current_stop, proposed_stop,
                                  current_limit, proposed_limit, reason, confidence, status,
                                  evidence, created_at, expires_at
                           FROM paper_order_modification_proposals WHERE proposal_id=%s""", [pid])
            r = cur.fetchone()
            conn.close()
            if not r:
                return f"Proposal {pid} not found."
            return (f"Proposal: {r[0]}\nSymbol: {r[1]}\nAction: {r[2]}\n"
                    f"Stop: {r[3]} -> {r[4]}\nLimit: {r[5]} -> {r[6]}\n"
                    f"Reason: {r[7]}\nConfidence: {r[8]}\nStatus: {r[9]}\n"
                    f"Created: {r[11]}\nExpires: {r[12]}\n"
                    f"\nApprove: approve paper mod {r[0]}\nReject: reject paper mod {r[0]}")
        except Exception as e:
            return f"Error: {e}"

    if command == "paper_mod_approve":
        try:
            from session13_db import get_conn
            parts = args.strip().split(None, 1)
            pid = parts[0]
            reason = parts[1] if len(parts) > 1 else "approved_via_telegram"
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("""UPDATE paper_order_modification_proposals
                           SET status='approved', admin_decision='approve', admin_reason=%s,
                               approved_by='john_telegram', approved_at=now(), updated_at=now()
                           WHERE proposal_id=%s AND status='proposed' RETURNING proposal_id""",
                        [reason, pid])
            updated = cur.fetchone()
            conn.commit()
            conn.close()
            if updated:
                return f"Approved: {pid}\nTo execute: execute approved paper mod {pid}"
            return f"Proposal {pid} not found or not in 'proposed' status."
        except Exception as e:
            return f"Approve error: {e}"

    if command == "paper_mod_reject":
        try:
            from session13_db import get_conn
            parts = args.strip().split(None, 1)
            pid = parts[0]
            reason = parts[1] if len(parts) > 1 else "rejected_via_telegram"
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("""UPDATE paper_order_modification_proposals
                           SET status='rejected', admin_decision='reject', admin_reason=%s,
                               rejected_at=now(), updated_at=now()
                           WHERE proposal_id=%s AND status='proposed' RETURNING proposal_id""",
                        [reason, pid])
            updated = cur.fetchone()
            conn.commit()
            conn.close()
            return f"Rejected: {pid}" if updated else f"Proposal {pid} not found or not 'proposed'."
        except Exception as e:
            return f"Reject error: {e}"

    if command == "paper_mod_execute":
        try:
            from open_trade_manager import execute_approved
            from session13_db import get_conn
            pid = args.strip()
            conn = get_conn()
            result = execute_approved(conn, pid)
            conn.close()
            status = result.get("status", "unknown")
            if status == "executed":
                return f"Executed: {pid}\n{json.dumps(result.get('broker_response', {}), indent=2, default=str)[:200]}"
            return f"Execution {status}: {result.get('error', 'unknown')}"
        except Exception as e:
            return f"Execute error: {e}"

    if command == "paper_mod_cancel":
        try:
            from session13_db import get_conn
            pid = args.strip()
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("""UPDATE paper_order_modification_proposals
                           SET status='cancelled', updated_at=now()
                           WHERE proposal_id=%s AND status IN ('proposed', 'approved')
                           RETURNING proposal_id""", [pid])
            updated = cur.fetchone()
            conn.commit()
            conn.close()
            return f"Cancelled: {pid}" if updated else f"Proposal {pid} not found or already resolved."
        except Exception as e:
            return f"Cancel error: {e}"

    # ── Session 27B: Execution Revalidation handlers ───────────────────
    if command == "paper_pending_entries":
        try:
            from session13_db import get_conn
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("""SELECT id, symbol, strategy_id, proposed_entry, proposed_stop,
                                  status, created_at, approved_at,
                                  COALESCE(execution_recheck_required, true) as recheck_req,
                                  COALESCE(material_change_pending_approval, false) as mat_change
                           FROM paper_trade_proposals
                           WHERE status IN ('APPROVED', 'APPROVED_FOR_PAPER_TEST', 'PENDING')
                           ORDER BY created_at DESC LIMIT 10""")
            rows = cur.fetchall()
            conn.close()
            if not rows:
                return "No pending paper entries."
            lines = ["Pending Paper Entries:"]
            for r in rows:
                age = ""
                if r[6]:
                    from datetime import datetime, timezone
                    age_min = (datetime.now(timezone.utc) - r[6].replace(tzinfo=timezone.utc)).total_seconds() / 60
                    age = f" age={age_min:.0f}m"
                recheck = " RECHECK" if r[8] else ""
                mat = " MAT_CHANGE" if r[9] else ""
                lines.append(f"  #{r[0]}: {r[1]} {r[3]}/{r[4]} [{r[5]}]{age}{recheck}{mat}")
            lines.append("\nRecheck: recheck paper entry <id>")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    if command == "paper_recheck_entry":
        try:
            from paper_execution_revalidator import revalidate, get_pending_proposals, save_recheck
            from session13_db import get_conn
            pid = int(args.strip())
            conn = get_conn()
            proposals = get_pending_proposals(conn, proposal_id=pid)
            if not proposals:
                conn.close()
                return f"Proposal #{pid} not found or not pending."
            result = revalidate(conn, proposals[0])
            save_recheck(conn, result)
            conn.close()
            r = result
            return (f"Recheck #{pid} ({r['symbol']}):\n"
                    f"Status: {r['status']}\nScore: {r['execution_readiness_score']}\n"
                    f"Session: {r['market_session']}\nDrift: {r.get('price_drift_pct', 0):.1f}%\n"
                    f"Material changes: {r.get('material_change_reasons', [])}\n"
                    f"Reapproval needed: {r['requires_reapproval']}\n"
                    f"Reason: {r['reason'][:120]}")
        except Exception as e:
            return f"Recheck error: {e}"

    if command == "paper_approve_updated_entry":
        try:
            from session13_db import get_conn
            parts = args.strip().split(None, 1)
            pid = int(parts[0])
            reason = parts[1] if len(parts) > 1 else "approved_updated_via_telegram"
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("""UPDATE paper_trade_proposals
                           SET material_change_pending_approval=false,
                               execution_recheck_required=true,
                               approved_pending_recheck=false,
                               execution_recheck_reason=%s
                           WHERE id=%s AND material_change_pending_approval=true
                           RETURNING id, symbol""", [reason, pid])
            row = cur.fetchone()
            conn.commit()
            conn.close()
            if row:
                return f"Updated entry #{row[0]} ({row[1]}) approved. Run recheck again before execution."
            return f"Proposal #{pid} not found or no material change pending."
        except Exception as e:
            return f"Error: {e}"

    if command == "paper_reject_updated_entry":
        try:
            from session13_db import get_conn
            parts = args.strip().split(None, 1)
            pid = int(parts[0])
            reason = parts[1] if len(parts) > 1 else "rejected_updated_via_telegram"
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("""UPDATE paper_trade_proposals
                           SET status='REJECTED', material_change_pending_approval=false,
                               execution_recheck_reason=%s
                           WHERE id=%s AND status IN ('APPROVED', 'APPROVED_FOR_PAPER_TEST', 'PENDING')
                           RETURNING id""", [reason, pid])
            row = cur.fetchone()
            conn.commit()
            conn.close()
            return f"Rejected updated entry #{pid}" if row else f"Proposal #{pid} not found."
        except Exception as e:
            return f"Error: {e}"

    if command == "paper_execute_ready_entry":
        try:
            from paper_execution_revalidator import revalidate, get_pending_proposals, save_recheck, check_safety
            from market_session import is_market_open, current_market_session
            from session13_db import get_conn
            import os
            pid = int(args.strip())

            # Safety gates
            safe, safety_errors = check_safety()
            if not safe:
                return f"BLOCKED: Safety check failed: {safety_errors}"
            if os.getenv("ALPACA_MODE", "paper").lower() != "paper":
                return "BLOCKED: ALPACA_MODE is not paper"

            conn = get_conn()
            proposals = get_pending_proposals(conn, proposal_id=pid)
            if not proposals:
                conn.close()
                return f"Proposal #{pid} not found or not pending."

            # Run revalidation
            result = revalidate(conn, proposals[0])
            save_recheck(conn, result)

            p = proposals[0]
            if result["status"] != "valid_original":
                conn.close()
                return (f"NOT READY #{pid} ({result['symbol']}):\n"
                        f"Status: {result['status']}\nScore: {result['execution_readiness_score']}\n"
                        f"Session: {result['market_session']}\nDrift: {result.get('price_drift_pct', 0) or 0:.1f}%\n"
                        f"Reason: {result['reason'][:120]}\n"
                        f"Reapproval: {result['requires_reapproval']}")

            if p.get("material_change_pending_approval"):
                conn.close()
                return f"BLOCKED #{pid}: Material change pending approval. Use: approve updated paper entry {pid}"

            if not is_market_open():
                conn.close()
                return f"BLOCKED #{pid}: Market not open (session={current_market_session()}). Cannot submit."

            # Ready to execute — call the paper submitter
            try:
                from proposal_paper_submitter import submit_paper
                sub_result = submit_paper(conn, pid)
                conn.close()
                if sub_result.get("ok"):
                    return (f"EXECUTED #{pid} ({result['symbol']}):\n"
                            f"Recheck: {result['recheck_id']}\n"
                            f"Score: {result['execution_readiness_score']}\n"
                            f"Alpaca order submitted (paper)")
                else:
                    return f"SUBMIT FAILED #{pid}: {sub_result.get('error', 'unknown')}"
            except Exception as e:
                conn.close()
                return f"SUBMIT ERROR #{pid}: {e}"

        except Exception as e:
            return f"Execute error: {e}"

    # Session 28: Learning Governance handlers
    if command == "learning_status":
        try:
            from learning_governance import get_learning_status, _get_conn
            conn = _get_conn()
            s = get_learning_status(conn)
            conn.close()
            return (f"Learning Status:\n"
                    f"  Hypotheses: {s['hypotheses_total']}\n"
                    f"  Experiments: {s['experiments_total']}\n"
                    f"  Recommendations: {s['recommendations_total']}\n"
                    f"  Config proposals: {s['config_proposals_total']}\n"
                    f"  Closed paper trades: {s['closed_paper_trades']}\n"
                    f"  Sample tier: {s['sample_size_tier']}")
        except Exception as e:
            return f"Error: {e}"

    if command == "learning_hypotheses":
        try:
            from session13_db import get_conn
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT hypothesis_id, title, domain, status, sample_size FROM learning_hypotheses ORDER BY created_at DESC LIMIT 10")
            rows = cur.fetchall()
            conn.close()
            if not rows:
                return "No learning hypotheses yet."
            lines = ["Learning Hypotheses:"]
            for r in rows:
                lines.append(f"  {r[0][:20]}: {r[1][:50]} [{r[3]}, n={r[4]}]")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    if command == "learning_recommendations":
        try:
            from session13_db import get_conn
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT recommendation_id, title, domain, status, sample_size, confidence FROM learning_recommendations ORDER BY created_at DESC LIMIT 10")
            rows = cur.fetchall()
            conn.close()
            if not rows:
                return "No learning recommendations yet."
            lines = ["Learning Recommendations:"]
            for r in rows:
                conf = f"{float(r[5]):.0%}" if r[5] else "?"
                lines.append(f"  {r[0][:20]}: {r[1][:50]} [{r[3]}, n={r[4]}, conf={conf}]")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    if command == "learning_proposals":
        try:
            from session13_db import get_conn
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT proposal_id, domain, target_key, change_type, status FROM config_change_proposals ORDER BY created_at DESC LIMIT 10")
            rows = cur.fetchall()
            conn.close()
            if not rows:
                return "No config change proposals yet."
            lines = ["Config Change Proposals:"]
            for r in rows:
                lines.append(f"  {r[0][:20]}: {r[1]}/{r[2]} {r[3]} [{r[4]}]")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    if command == "learning_approve_shadow":
        try:
            from session13_db import get_conn
            parts = args.strip().split(None, 1)
            pid = parts[0]
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("UPDATE config_change_proposals SET status='shadow_only', approved_by='telegram', approved_at=now() WHERE proposal_id=%s AND status='proposed' RETURNING proposal_id", [pid])
            row = cur.fetchone()
            conn.commit()
            conn.close()
            return f"Approved for shadow: {pid}" if row else f"Proposal {pid} not found or not proposed."
        except Exception as e:
            return f"Error: {e}"

    if command == "learning_reject_proposal":
        try:
            from session13_db import get_conn
            parts = args.strip().split(None, 1)
            pid = parts[0]
            reason = parts[1] if len(parts) > 1 else "rejected_via_telegram"
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("UPDATE config_change_proposals SET status='rejected', rejected_at=now(), rejection_reason=%s WHERE proposal_id=%s RETURNING proposal_id", [reason, pid])
            row = cur.fetchone()
            conn.commit()
            conn.close()
            return f"Rejected: {pid}" if row else f"Proposal {pid} not found."
        except Exception as e:
            return f"Error: {e}"

    if command == "learning_approve_implementation":
        try:
            from session13_db import get_conn
            parts = args.strip().split(None, 1)
            pid = parts[0]
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("UPDATE config_change_proposals SET status='approved', approved_by='telegram', approved_at=now() WHERE proposal_id=%s AND status IN ('proposed','shadow_only') RETURNING proposal_id", [pid])
            row = cur.fetchone()
            conn.commit()
            conn.close()
            return f"Approved for implementation (manual apply required): {pid}" if row else f"Proposal {pid} not found."
        except Exception as e:
            return f"Error: {e}"

    if command == "learning_rollback":
        try:
            from learning_governance import record_rollback_event, _get_conn
            parts = args.strip().split(None, 1)
            pid = parts[0]
            reason = parts[1] if len(parts) > 1 else "rollback_via_telegram"
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("UPDATE config_change_proposals SET status='rolled_back' WHERE proposal_id=%s RETURNING domain, target_key", [pid])
            row = cur.fetchone()
            if row:
                record_rollback_event(conn, pid, row[0], row[1], reason)
                conn.commit()
            conn.close()
            return f"Rollback recorded: {pid}" if row else f"Proposal {pid} not found."
        except Exception as e:
            return f"Error: {e}"

    # Session 29: Agent Calibration handlers
    if command == "agent_calibration_status":
        try:
            from session13_db import get_conn
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM agent_recommendation_registry")
            total_recs = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM agent_calibration_events")
            total_events = cur.fetchone()[0]
            cur.execute("SELECT agent_name, resolved, accuracy, calibration_error, sample_size_status FROM agent_calibration_windows ORDER BY created_at DESC LIMIT 5")
            windows = cur.fetchall()
            conn.close()
            lines = [f"Agent Calibration:\n  Recommendations: {total_recs}\n  Calibration events: {total_events}"]
            for w in windows:
                acc = f"{float(w[2]):.0%}" if w[2] else "?"
                cal = f"{float(w[3]):.2f}" if w[3] else "?"
                lines.append(f"  {w[0]}: resolved={w[1]}, acc={acc}, cal_err={cal} [{w[4]}]")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    if command == "agent_disagreements":
        try:
            from session13_db import get_conn
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT symbol, disagreement_type, resolved, outcome_summary FROM agent_disagreement_outcomes ORDER BY created_at DESC LIMIT 10")
            rows = cur.fetchall()
            conn.close()
            if not rows:
                return "No agent disagreements recorded yet."
            lines = ["Agent Disagreements:"]
            for r in rows:
                lines.append(f"  {r[0]}: {r[1]} | resolved={r[2]} | {(r[3] or '')[:60]}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    if command == "agent_weight_proposals":
        try:
            from session13_db import get_conn
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT shadow_proposal_id, agent_name, current_weight, proposed_weight, status FROM agent_weight_shadow_proposals ORDER BY created_at DESC LIMIT 10")
            rows = cur.fetchall()
            conn.close()
            if not rows:
                return "No agent weight shadow proposals yet."
            lines = ["Agent Weight Proposals:"]
            for r in rows:
                lines.append(f"  {r[0][:15]}: {r[1]} {r[2]}→{r[3]} [{r[4]}]")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    if command == "agent_approve_shadow":
        try:
            from session13_db import get_conn
            pid = args.strip().split()[0]
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("UPDATE agent_weight_shadow_proposals SET status='approved_for_shadow', updated_at=now() WHERE shadow_proposal_id=%s AND status='proposed' RETURNING shadow_proposal_id", [pid])
            row = cur.fetchone()
            conn.commit(); conn.close()
            return f"Approved for shadow: {pid}" if row else f"Proposal {pid} not found or not proposed."
        except Exception as e:
            return f"Error: {e}"

    if command == "agent_reject_shadow":
        try:
            from session13_db import get_conn
            parts = args.strip().split(None, 1)
            pid = parts[0]
            reason = parts[1] if len(parts) > 1 else "rejected_via_telegram"
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("UPDATE agent_weight_shadow_proposals SET status='rejected', updated_at=now() WHERE shadow_proposal_id=%s RETURNING shadow_proposal_id", [pid])
            row = cur.fetchone()
            conn.commit(); conn.close()
            return f"Rejected: {pid}" if row else f"Proposal {pid} not found."
        except Exception as e:
            return f"Error: {e}"

    # Session 30: Weekly Learning + Thesis Review handlers
    if command == "weekly_learning_summary":
        try:
            from session13_db import get_conn
            conn = get_conn(); cur = conn.cursor()
            cur.execute("SELECT digest_id, period_start, period_end, paper_trades_closed, win_rate, low_sample_size, status FROM weekly_learning_digests ORDER BY created_at DESC LIMIT 1")
            row = cur.fetchone()
            conn.close()
            if not row:
                return "No weekly digests generated yet. Run: weekly learning generate"
            wr = f"{float(row[4]):.0%}" if row[4] else "?"
            ls = " (LOW SAMPLE)" if row[5] else ""
            return f"Weekly Digest: {row[1]}—{row[2]}\nClosed: {row[3]} | WR: {wr}{ls}\nStatus: {row[6]}\nID: {row[0]}"
        except Exception as e:
            return f"Error: {e}"

    if command == "weekly_learning_generate":
        try:
            import subprocess
            r = subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" / "weekly_learning_digest.py"),
                               "--current-week", "--dry-run", "--json"],
                              capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT))
            d = json.loads(r.stdout)
            return f"Digest (dry-run): {d.get('period','?')}\nClosed: {d.get('closed_trades',0)} | Lessons: {d.get('lessons',0)} | Reviews: {d.get('review_items',0)}\nLow sample: {d.get('low_sample',True)}"
        except Exception as e:
            return f"Error: {e}"

    if command == "thesis_reviews_list":
        try:
            from session13_db import get_conn
            conn = get_conn(); cur = conn.cursor()
            cur.execute("SELECT review_id, symbol, thesis_validity, thesis_score, lesson_summary FROM trade_thesis_reviews ORDER BY created_at DESC LIMIT 10")
            rows = cur.fetchall()
            conn.close()
            if not rows:
                return "No thesis reviews yet. Run: thesis review run"
            lines = ["Thesis Reviews:"]
            for r in rows:
                lines.append(f"  {r[1]}: {r[2]} (score={r[3]}) — {(r[4] or '')[:60]}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    if command == "thesis_review_run":
        try:
            import subprocess
            r = subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" / "trade_thesis_review_engine.py"),
                               "--dry-run", "--json"],
                              capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT))
            d = json.loads(r.stdout)
            return f"Thesis Review (dry-run): {d.get('trades_reviewed',0)} trades\nBy validity: {d.get('by_validity',{})}\nLow sample: {d.get('low_sample_size',True)}"
        except Exception as e:
            return f"Error: {e}"

    # Session 31: Backtesting handlers
    if command == "backtest_status":
        try:
            from session13_db import get_conn
            conn = get_conn(); cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM strategy_backtest_runs")
            runs = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM strategy_backtest_trades")
            trades = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM challenger_definitions")
            challengers = cur.fetchone()[0]
            conn.close()
            return f"Backtest Status:\n  Runs: {runs}\n  Simulated trades: {trades}\n  Challengers: {challengers}"
        except Exception as e:
            return f"Error: {e}"

    if command == "backtest_strategies":
        try:
            from strategy_rule_adapter import load_strategy_configs
            configs = load_strategy_configs()
            lines = [f"Strategies ({len(configs)}):"]
            for sid, data in list(configs.items())[:15]:
                lines.append(f"  {sid}: {data['config'].get('name', sid)}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    if command == "backtest_results":
        try:
            from session13_db import get_conn
            conn = get_conn(); cur = conn.cursor()
            cur.execute("SELECT run_id, strategy_id, status, duration_seconds FROM strategy_backtest_runs ORDER BY created_at DESC LIMIT 5")
            rows = cur.fetchall()
            conn.close()
            if not rows:
                return "No backtest runs yet. Run: .venv/bin/python scripts/strategy_backtester.py --all-strategies --apply --json"
            lines = ["Recent Backtest Runs:"]
            for r in rows:
                lines.append(f"  {r[0][:15]}: {r[1]} [{r[2]}] {r[3]}s")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    if command == "challenger_list":
        try:
            from session13_db import get_conn
            conn = get_conn(); cur = conn.cursor()
            cur.execute("SELECT challenger_id, name, strategy_id, status FROM challenger_definitions ORDER BY created_at DESC LIMIT 10")
            rows = cur.fetchall()
            conn.close()
            if not rows:
                return "No challengers defined yet."
            lines = ["Challengers:"]
            for r in rows:
                lines.append(f"  {r[0][:15]}: {r[1]} [{r[3]}]")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    # Session 33: Risk Regime handlers
    if command == "regime_status":
        try:
            from session13_db import get_conn
            conn = get_conn(); cur = conn.cursor()
            cur.execute("SELECT regime_label, confidence, stale_data, summary FROM market_regime_snapshots ORDER BY created_at DESC LIMIT 1")
            row = cur.fetchone()
            conn.close()
            if not row:
                return "No regime snapshot. Run: .venv/bin/python scripts/market_regime_classifier.py --apply --json"
            stale = " (STALE)" if row[2] else ""
            return f"Regime: {row[0]} (conf={float(row[1]):.0%}){stale}\n{row[3]}"
        except Exception as e:
            return f"Error: {e}"

    if command == "strategy_rotation_signals":
        try:
            from session13_db import get_conn
            conn = get_conn(); cur = conn.cursor()
            cur.execute("SELECT strategy_id, signal, signal_strength, reason FROM strategy_rotation_signals ORDER BY created_at DESC LIMIT 15")
            rows = cur.fetchall()
            conn.close()
            if not rows:
                return "No rotation signals. Run rotation engine first."
            lines = ["Strategy Rotation:"]
            for r in rows:
                lines.append(f"  {r[0]}: {r[1]} (str={float(r[2]):.2f}) — {(r[3] or '')[:50]}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    if command == "regime_alignments":
        try:
            from session13_db import get_conn
            conn = get_conn(); cur = conn.cursor()
            cur.execute("SELECT symbol, strategy_id, alignment_label, regime_label, reason FROM regime_trade_alignment ORDER BY created_at DESC LIMIT 10")
            rows = cur.fetchall()
            conn.close()
            if not rows:
                return "No trade/proposal alignments. Run rotation engine first."
            lines = ["Regime Alignments:"]
            for r in rows:
                lines.append(f"  {r[0]} ({r[1]}): {r[2]} in {r[3]} — {(r[4] or '')[:50]}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    if command == "wl_add":
        syms = [s.upper() for s in args.replace(",", " ").split() if s.isalpha() and len(s) <= 5]
        return _run_wl_skill("add", *syms) if syms else "Usage: watch SYM [SYM2 …]"
    if command == "wl_add_phrase":
        import re as _re
        parts = _re.split(r"\s+to\s+", args, maxsplit=1)
        syms = [s.upper() for s in parts[0].replace(",", " ").split() if s.isalpha() and len(s) <= 5]
        listname = ""
        if len(parts) > 1:
            listname = _re.sub(r"\b(my|the|watch|watchlist|list)\b", "", parts[1], flags=_re.I).strip()
        if not syms:
            return "Usage: add SYM to watchlist (or: add SYM to my Data Center list)"
        a = ["add", *syms] + (["--label", listname] if listname else [])
        return _run_wl_skill(*a)
    if command == "wl_topic":
        return _run_wl_skill("add-topic", args) if args.strip() else "Usage: trend <theme to research>"
    if command == "wl_ask":
        return _run_wl_skill("ask", args)
    if command == "wl_trends":
        return _run_wl_skill("trends")

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

    # Dedup: getUpdates?offset=-5 re-reads recent messages every poll, so track the last handled
    # update_id and never reply twice. First run (no state) just sets the watermark — it does NOT
    # reply to old messages. Makes a 1-min cadence safe.
    _state = PROJECT_ROOT / "data" / "runtime" / "telegram_cmd_state.json"
    _bootstrap = not _state.exists()
    try:
        last_id = json.loads(_state.read_text()).get("last_update_id", 0)
    except Exception:
        last_id = 0
    max_id = last_id

    results = []
    for update in data.get("result", []):
        uid = update.get("update_id", 0)
        if uid <= last_id:
            continue                       # already handled in a prior poll
        max_id = max(max_id, uid)
        if _bootstrap:
            continue                       # first run: establish watermark, don't re-reply to old msgs
        msg = update.get("message", {})
        text = msg.get("text", "")
        chat_id = msg.get("chat", {}).get("id")

        if not text or not chat_id:
            continue

        # Pending modify-size / modify-risk capture (operator 2026-06-19): after the operator taps ✏️ Size
        # or 🎯 Risk on a proposal alert, the NEXT numeric message from this chat is the new value. Applied
        # via the SAME sizing engine (trade_modify → account_policy) and audited in queue_decision_audit.
        try:
            import trade_modify as _tm
            _pend = _tm.pop_pending(chat_id) if chat_id else None
        except Exception:
            _pend, _tm = None, None
        if _pend and _tm:
            import re as _re2
            m = _re2.search(r"-?\d+(?:\.\d+)?", text)
            if not m:
                _send_telegram(f"Couldn't read a number from '{text[:40]}'. Tap the ✏️/🎯 button again to retry.")
                continue
            val = float(m.group())
            _from = msg.get("from", {}) or {}
            actor = str(_from.get("username") or _from.get("first_name") or chat_id)
            if _pend["kind"] == "size":
                r = _tm.apply_size(_pend["proposal_id"], int(val), actor=actor, channel="telegram")
                _send_telegram(f"✅ {r['symbol']} size set to {r['shares']} sh (${r['dollar_size']:,.0f})"
                               if r.get("ok") else f"⚠ modify failed: {r.get('error')}")
            else:
                r = _tm.apply_risk(_pend["proposal_id"], val, actor=actor, channel="telegram")
                _send_telegram(f"✅ {r['symbol']} stop set to ${r['stop']:.2f} → {r['shares']} sh "
                               f"(risk ${r['dollar_risk']:,.0f}, {r['binding']})"
                               if r.get("ok") else f"⚠ modify failed: {r.get('error')}")
            results.append({"modify": _pend, "value": val})
            continue

        # Only process messages that look like commands or ingestible URLs (after dropping an agent prefix
        # so 'maria watch HOOD' is treated as the deterministic command 'watch HOOD').
        lower = _strip_agent_prefix(text).lower().strip()
        is_command = any(lower.startswith(c) for c in [
            "research ", "find ", "analyze ", "run screener ", "run promoter", "look for ",
            "alex ", "retirement ", "iris", "/iris_", "status", "help",
            "topics", "topic ", "add video", "add article",
            "backup", "sync docs",
            "watch ", "ask ", "trends", "trend ", "tren ", "trnd ", "research topic ",
            "latest research", "latest trends",
        ]) or (lower.startswith("add ") and " to " in lower and ("watch" in lower or "list" in lower))
        # bare "add aapl" / "add SOFI HOOD" (ticker tokens, any case)
        if not is_command and lower.startswith("add ") and " to " not in lower and not any(w in lower for w in ("video", "article", "topic ")):
            if _ticker_tokens(_strip_agent_prefix(text)[4:].strip()):
                is_command = True
        has_url = "http://" in lower or "https://" in lower
        if not is_command and not has_url:
            continue

        cmd = parse_command(text)
        response = process_command(cmd)

        # Reply
        _send_telegram(response)
        results.append({"command": cmd, "response_len": len(response)})

    # persist the high-water mark so the next poll skips everything already handled
    try:
        _state.parent.mkdir(parents=True, exist_ok=True)
        _state.write_text(json.dumps({"last_update_id": max_id}))
    except Exception:
        pass
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
