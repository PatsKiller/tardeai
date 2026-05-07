"""
morning_digest.py — Pre-market intelligence digest via Telegram.
Uses Ollama for narrative. Reads ticker_memory + latest run results.

Schedule (called by continuous_runner.py):
  6:55 AM — Full pre-market digest
  9:25 AM — Pre-open final brief

Digest sections:
  1. Market regime + key levels
  2. Building momentum tickers (score rising across runs)
  3. Trap/dilution warnings from memory
  4. GO tickers (if any)
  5. Ollama narrative summary
"""
from __future__ import annotations
import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).parent.parent


def _load_latest_run(project_root: Path) -> Optional[Dict]:
    """Load the most recent run_summary.json."""
    reports_dir = project_root / "reports"
    today = datetime.now().strftime("%Y-%m-%d")
    # Find today's run summaries
    pattern = list(reports_dir.glob(f"{today}/*/run_summary.json"))
    if not pattern:
        # Try dashboard_live.html for scored tickers
        live = project_root / "reports" / "dashboard_live.html"
        if live.exists():
            return {"source": "live_dashboard"}
        return None
    # Get most recent
    latest = sorted(pattern)[-1]
    try:
        return json.loads(latest.read_text())
    except Exception:
        return None


def _load_state(project_root: Path) -> Dict:
    """Load state.json for delta/trend data."""
    state_path = project_root / "data" / "state.json"
    if state_path.exists():
        try:
            return json.loads(state_path.read_text())
        except Exception:
            pass
    return {}


def _load_ticker_memory(project_root: Path) -> Dict:
    """Load ticker memory."""
    mem_path = project_root / "data" / "state" / "ticker_memory.json"
    if mem_path.exists():
        try:
            return json.loads(mem_path.read_text())
        except Exception:
            pass
    return {}


def _get_env_var(key: str, project_root: Path) -> str:
    """Get env var, falling back to .env file."""
    val = os.getenv(key, "")
    if val:
        return val
    env_path = project_root / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"')
    return ""


def _send_telegram(message: str, project_root: Path) -> bool:
    """Send Telegram message to all configured chat IDs."""
    bot_token = _get_env_var("TELEGRAM_BOT_TOKEN", project_root)
    chat_ids_raw = _get_env_var("TELEGRAM_CHAT_ID", project_root)

    if not bot_token or not chat_ids_raw:
        print("  [digest] No Telegram creds — printing only")
        print(message)
        return False

    success = False
    for cid in chat_ids_raw.split(","):
        cid = cid.strip()
        if not cid:
            continue
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            data = urllib.parse.urlencode({
                "chat_id": cid,
                "text": message,
                "parse_mode": "HTML"
            }).encode()
            req = urllib.request.Request(url, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
                if result.get("ok"):
                    print(f"  [digest] Telegram sent to {cid}")
                    success = True
        except Exception as e:
            print(f"  [digest] Telegram error for {cid}: {e}")
    return success


def _ollama_narrative(prompt: str, timeout: int = 90) -> str:
    """Generate narrative via Ollama."""
    try:
        try:
            from local_llm_config import get_local_llm_model
            _model = get_local_llm_model()
        except ImportError:
            _model = os.getenv("LOCAL_LLM_MODEL", "qwen3:14b")
        payload = json.dumps({
            "model": _model,
            "stream": False,
            "messages": [{"role": "user", "content": prompt}],
            "think": False,
            "options": {"temperature": 0.3}
        }).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            return data.get("message", {}).get("content", "").strip()
    except Exception as e:
        print(f"  [digest] Ollama error: {e}")
        return ""


def build_premarket_digest(project_root: Path = PROJECT_ROOT) -> str:
    """Build the 6:55AM pre-market digest message."""
    run_data = _load_latest_run(project_root)
    memory = _load_ticker_memory(project_root)
    state = _load_state(project_root)
    now = datetime.now()
    date_str = now.strftime("%b %d, %Y")
    time_str = now.strftime("%I:%M %p")

    # Extract scored tickers from run data
    scored = []
    market = {}
    if run_data and run_data.get("source") != "live_dashboard":
        scored = run_data.get("scored_tickers", run_data.get("tickers", []))
        market = run_data.get("market_snapshot", {})

    go_tickers = [t for t in scored if t.get("decision") == "GO"]
    wait_tickers = [t for t in scored if t.get("decision") == "WAIT"]

    # Memory analysis
    trap_warnings = []
    building_momentum = []
    for sym, data in memory.items():
        pattern = data.get("pattern", "")
        times_seen = data.get("times_seen", 0)
        # Check if currently in scored list
        current = next((t for t in scored if t.get("symbol") == sym), None)
        if not current:
            continue
        score = current.get("score", 0)
        if pattern in ("repeat_trap", "dilution_repeat", "trap_history"):
            trap_warnings.append({
                "symbol": sym,
                "score": score,
                "pattern": pattern,
                "times_seen": times_seen,
                "risk": data.get("observations", [{}])[-1].get("ollama_risk", "")
            })
        if pattern == "building_momentum" and score >= 25:
            building_momentum.append({
                "symbol": sym,
                "score": score,
                "times_seen": times_seen
            })

    # Build sections
    sections = []

    # Market regime
    spy_chg = market.get("spy_change_pct", 0) or 0
    vix = market.get("vix", 0) or 0
    regime = market.get("regime", "Neutral")
    regime_emoji = "🟢" if spy_chg > 0.5 else "🔴" if spy_chg < -0.5 else "🟡"
    sections.append(
        f"{regime_emoji} <b>Market:</b> SPY {spy_chg:+.2f}% | VIX {vix:.1f} | {regime}"
    )

    # GO tickers
    if go_tickers:
        go_lines = " · ".join(
            f"{t['symbol']} ({t.get('score', 0)}pts)"
            for t in go_tickers[:5]
        )
        sections.append(f"🔥 <b>GO:</b> {go_lines}")
    else:
        sections.append("⏳ <b>GO:</b> No GO tickers yet")

    # Building momentum
    if building_momentum:
        mom_lines = " · ".join(
            f"{t['symbol']} (seen {t['times_seen']}x, score {t['score']})"
            for t in building_momentum[:3]
        )
        sections.append(f"📈 <b>Building:</b> {mom_lines}")

    # Trap warnings
    if trap_warnings:
        trap_lines = " · ".join(
            f"{t['symbol']} ({t['pattern'].replace('_', ' ')})"
            for t in trap_warnings[:3]
        )
        sections.append(f"⚠️ <b>Traps:</b> {trap_lines}")

    # WAIT tickers worth watching
    top_wait = sorted(wait_tickers, key=lambda t: t.get("score", 0), reverse=True)[:3]
    if top_wait:
        wait_lines = " · ".join(
            f"{t['symbol']} ({t.get('score', 0)}pts)"
            for t in top_wait
        )
        sections.append(f"👀 <b>Watch:</b> {wait_lines}")

    # Ollama narrative (2-3 sentences)
    if scored:
        prompt = f"""Pre-market intelligence brief for a scalp trader. Be direct, 2-3 sentences max.

Date: {date_str} {time_str}
Market: SPY {spy_chg:+.2f}%, VIX {vix:.1f}, Regime: {regime}
GO tickers: {len(go_tickers)} | WAIT: {len(wait_tickers)} | Total scanned: {len(scored)}
Building momentum: {[t['symbol'] for t in building_momentum[:3]]}
Trap warnings: {[t['symbol'] for t in trap_warnings[:3]]}
Top WAIT: {[t['symbol'] for t in top_wait]}

Write 2-3 sentences: overall market posture, what to focus on, what to avoid."""

        narrative = _ollama_narrative(prompt, timeout=60)
        if narrative:
            sections.append(f"\n💬 {narrative}")

    # Assemble message
    header = f"📊 <b>Pre-Market Brief — {date_str} {time_str}</b>"
    body = "\n".join(sections)
    return f"{header}\n\n{body}"


def build_preopen_brief(project_root: Path = PROJECT_ROOT) -> str:
    """Build the 9:25AM pre-open brief — shorter, action-focused."""
    run_data = _load_latest_run(project_root)
    memory = _load_ticker_memory(project_root)
    now = datetime.now()
    time_str = now.strftime("%I:%M %p")

    scored = []
    market = {}
    if run_data and run_data.get("source") != "live_dashboard":
        scored = run_data.get("scored_tickers", run_data.get("tickers", []))
        market = run_data.get("market_snapshot", {})

    go_tickers = [t for t in scored if t.get("decision") == "GO"]
    spy_chg = market.get("spy_change_pct", 0) or 0
    vix = market.get("vix", 0) or 0

    if go_tickers:
        go_detail = "\n".join(
            f"  • {t['symbol']}: {t.get('score', 0)}pts | "
            f"RVOL {t.get('rvol', 0):.1f}x | "
            f"{t.get('top_catalyst', {}).get('title', 'No catalyst')[:50] if isinstance(t.get('top_catalyst'), dict) else 'No catalyst'}"
            for t in go_tickers[:5]
        )
        prompt = f"""Market opens in 5 minutes. Write ONE sentence telling a scalp trader what to focus on.
GO tickers: {[t['symbol'] for t in go_tickers]}
SPY: {spy_chg:+.2f}%, VIX: {vix:.1f}
Be specific and actionable. Max 20 words."""
        narrative = _ollama_narrative(prompt, timeout=30)
        return (
            f"⚡ <b>Pre-Open Brief — {time_str}</b>\n\n"
            f"🔥 <b>{len(go_tickers)} GO tickers:</b>\n{go_detail}\n\n"
            f"💬 {narrative}"
        )
    else:
        return (
            f"⚡ <b>Pre-Open Brief — {time_str}</b>\n\n"
            f"No GO tickers. SPY {spy_chg:+.2f}% | VIX {vix:.1f}\n"
            f"Stay patient. Wait for strong setups."
        )


def send_digest(digest_type: str = "premarket",
                project_root: Path = PROJECT_ROOT) -> None:
    """Main entry point. digest_type: 'premarket' or 'preopen'"""
    print(f"[morning-digest] Building {digest_type} digest...")

    if digest_type == "preopen":
        message = build_preopen_brief(project_root)
    else:
        message = build_premarket_digest(project_root)

    print(f"\n{message}\n")
    _send_telegram(message, project_root)
    print(f"[morning-digest] Done.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", default="premarket",
                        choices=["premarket", "preopen"])
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()
    send_digest(args.type, Path(args.project_root))
