#!/usr/bin/env python3
"""journal_agent_coach.py — Agents analyze the trade journal and provide coaching.

Maria: entry quality, setup patterns, market timing
Steph: position sizing, R-multiple discipline, allocation
Aegis: psychology, discipline, emotion patterns

Uses Ollama (qwen3:1.7b) by default. Falls back to Anthropic if unavailable.
"""
import json, os, sys, time, logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

# Load env
for line in (PROJECT_ROOT / ".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from db_adapter import _execute, _get_conn


# ── LLM ──────────────────────────────────────────────────────────────────────

def _call_ollama(prompt: str, timeout: int = 90) -> str:
    """Call Ollama following existing local_llm.py pattern."""
    import urllib.request
    from local_llm_config import get_local_llm_model, get_local_llm_base_url
    _model = get_local_llm_model()
    _base = get_local_llm_base_url().rstrip("/")
    payload = json.dumps({
        "model": _model,
        "stream": False,
        "messages": [{"role": "user", "content": prompt}],
        "think": False,
        "options": {"temperature": 0.3, "num_predict": 1024}
    }).encode()
    try:
        req = urllib.request.Request(
            f"{_base}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            text = data.get("message", {}).get("content", "").strip()
            dur = round(data.get("total_duration", 0) / 1e9, 1)
            log.info(f"  Ollama OK — {dur}s, {data.get('eval_count', 0)} tokens")
            return text
    except Exception as e:
        log.warning(f"  Ollama failed: {e}")
        return ""


def call_llm_DEPRECATED(prompt: str) -> tuple[str, str]:
    """Deprecated — migrated to llm_lane.generate() for fallback."""
    text = _call_ollama(prompt)
    if text:
        from local_llm_config import get_local_llm_model
        return text, get_local_llm_model()

    # Fallback to Anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            msg = client.messages.create(
                model="claude-sonnet-4-6", max_tokens=1024,
                messages=[{"role": "user", "content": prompt}]
            )
            return msg.content[0].text, "claude-sonnet-4-6"
        except Exception as e:
            log.error(f"  Anthropic failed: {e}")

    log.error("No LLM available")
    return "", "none"


def call_llm(prompt: str) -> tuple[str, str]:
    """Returns (response_text, model_used). Tries Ollama first, then DeepSeek Flash."""
    text = _call_ollama(prompt)
    if text:
        from local_llm_config import get_local_llm_model
        return text, get_local_llm_model()

    # Fallback to DeepSeek Flash via llm_lane
    try:
        from llm_lane import generate
        result = generate(prompt, lane="deepseek-flash", timeout=90)
        if result:
            return result, "deepseek-v4-flash"
    except Exception as e:
        log.error(f"  DeepSeek flash failed: {e}")

    log.error("No LLM available")
    return "", "none"


def parse_json_response(text: str) -> list:
    """Parse LLM response as JSON array, stripping markdown fences."""
    clean = text.strip()
    # Strip thinking tags (qwen3 sometimes outputs these)
    if "<think>" in clean:
        idx = clean.find("</think>")
        if idx >= 0:
            clean = clean[idx + len("</think>"):].strip()
    if clean.startswith("```"):
        parts = clean.split("```")
        if len(parts) >= 3:
            clean = parts[1]
        else:
            clean = parts[1] if len(parts) > 1 else clean
        if clean.startswith("json"):
            clean = clean[4:]
    clean = clean.strip()
    # Find the array
    start = clean.find("[")
    end = clean.rfind("]")
    if start >= 0 and end > start:
        clean = clean[start:end + 1]
    return json.loads(clean)


# ── Data loading ─────────────────────────────────────────────────────────────

def _ser(v):
    if isinstance(v, Decimal): return float(v)
    if hasattr(v, "isoformat"): return str(v)
    return v


def load_annotated_trades() -> list:
    conn = _get_conn()
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT
            (t.symbol || ':' || t.account || ':' || t.close_date::text) as trade_key,
            t.symbol, t.account, t.open_date, t.close_date,
            t.trade_type, t.buy_price, t.sell_price, t.pnl, t.pnl_pct,
            t.hold_days, t.shares,
            r.setup_types, r.entry_signals, r.exit_signals,
            r.emotion_before, r.emotion_during, r.emotion_after,
            r.execution_quality_score, r.sizing_quality_score,
            r.risk_management_score, r.planned_r, r.realized_r,
            r.followed_plan, r.well_executed,
            r.lesson_learned, r.review_notes,
            r.mistake_tags, r.strength_tags,
            b.entry_rsi, b.entry_grade, b.exit_grade,
            b.left_on_table_20d, b.exit_was_early
        FROM trade_closed t
        JOIN journal_trade_reviews r
          ON r.trade_key = (t.symbol || ':' || t.account || ':' || t.close_date::text)
        LEFT JOIN trade_backtest_results b
          ON b.trade_key = (t.symbol || ':' || t.account || ':' || t.close_date::text)
        WHERE (
            array_length(r.entry_signals, 1) > 0
            OR array_length(r.setup_types, 1) > 0
            OR (r.lesson_learned IS NOT NULL AND r.lesson_learned != ''
                AND r.lesson_learned NOT LIKE '%%Auto-classified%%')
        )
        ORDER BY t.close_date DESC
    """)
    rows = [{k: _ser(v) for k, v in dict(r).items()} for r in cur.fetchall()]
    conn.close()
    log.info(f"Loaded {len(rows)} annotated trades")
    return rows


def build_summary(trades: list) -> str:
    lines = []
    for t in trades[:20]:
        line = f"- {t['symbol']} ({t['trade_type']}, {t['hold_days']}d): P&L ${t['pnl']:,.0f} ({t['pnl_pct']:.1f}%)"
        if t.get("setup_types"): line += f" | Setups: {', '.join(t['setup_types'])}"
        if t.get("entry_signals"): line += f" | Signals: {', '.join(t['entry_signals'][:3])}"
        if t.get("emotion_before"): line += f" | Emotion: {t['emotion_before']}"
        if t.get("entry_rsi"): line += f" | RSI: {t['entry_rsi']:.0f}"
        if t.get("entry_grade"): line += f" | Grade: {t['entry_grade']}"
        if t.get("lesson_learned") and "Auto-classified" not in (t["lesson_learned"] or ""):
            line += f" | Lesson: {t['lesson_learned'][:60]}"
        lines.append(line)
    return "\n".join(lines)


# ── Agent prompts ────────────────────────────────────────────────────────────

def run_maria(trades: list) -> list:
    """Maria: entry quality, setup patterns, market timing."""
    summary = build_summary(trades)
    entry_rsis = [t["entry_rsi"] for t in trades if t.get("entry_rsi")]
    avg_rsi = sum(entry_rsis) / len(entry_rsis) if entry_rsis else 0

    setup_counts = {}
    for t in trades:
        for s in (t.get("setup_types") or []):
            setup_counts[s] = setup_counts.get(s, 0) + 1

    signal_pnl = {}
    for t in trades:
        for sig in (t.get("entry_signals") or []):
            if sig not in signal_pnl:
                signal_pnl[sig] = {"pnl": 0, "count": 0, "wins": 0}
            signal_pnl[sig]["pnl"] += t["pnl"]
            signal_pnl[sig]["count"] += 1
            if t["pnl"] > 0: signal_pnl[sig]["wins"] += 1

    sig_stats = {k: {"avg_pnl": round(v["pnl"]/v["count"]), "wr": round(v["wins"]/v["count"]*100)}
                 for k, v in signal_pnl.items() if v["count"] >= 2}

    prompt = f"""You are Maria, a professional trading coach for technical analysis and market timing.
Analyze this trader's journal and provide 2-3 coaching insights.

TRADE JOURNAL ({len(trades)} annotated trades):
{summary}

STATS:
- Average RSI at entry: {avg_rsi:.0f}
- Setup types: {json.dumps(setup_counts)}
- Signal performance: {json.dumps(sig_stats)}

Respond with a JSON array. Each item:
{{"coaching_type":"entry"|"pattern"|"timing","severity":"high"|"medium"|"low","title":"5-8 words","body":"2-3 sentences from actual data","action_item":"one specific change","supporting_trade_keys":["up to 3 trade_keys"]}}

Only reference patterns visible in the data. Return ONLY the JSON array."""

    text, model = call_llm(prompt)
    if not text: return []
    try:
        insights = parse_json_response(text)
        return [{"agent_name": "maria", "model": model, **i} for i in insights]
    except Exception as e:
        log.error(f"Maria parse failed: {e}\nRaw: {text[:300]}")
        return []


def run_steph(trades: list) -> list:
    """Steph: position sizing, R-multiple discipline."""
    summary = build_summary(trades)
    sizing_scores = [t["sizing_quality_score"] for t in trades if t.get("sizing_quality_score")]
    avg_sizing = sum(sizing_scores) / len(sizing_scores) if sizing_scores else 0

    has_r = [(t.get("planned_r"), t.get("realized_r")) for t in trades if t.get("planned_r")]
    mistake_counts = {}
    for t in trades:
        for m in (t.get("mistake_tags") or []):
            mistake_counts[m] = mistake_counts.get(m, 0) + 1

    prompt = f"""You are Steph, a trading coach for position sizing and risk management.
Analyze this trader's sizing discipline.

TRADE JOURNAL ({len(trades)} trades):
{summary}

STATS:
- Avg sizing score: {avg_sizing:.1f}/5 ({len(sizing_scores)} scored)
- R-multiples (planned, realized): {has_r[:5]}
- Mistakes: {json.dumps(dict(sorted(mistake_counts.items(), key=lambda x: -x[1])[:5]))}

Respond with 2-3 JSON coaching insights:
{{"coaching_type":"sizing"|"risk"|"r_multiple","severity":"high"|"medium"|"low","title":"5-8 words","body":"2-3 sentences","action_item":"one change","supporting_trade_keys":["up to 3"]}}

Return ONLY the JSON array."""

    text, model = call_llm(prompt)
    if not text: return []
    try:
        insights = parse_json_response(text)
        return [{"agent_name": "steph", "model": model, **i} for i in insights]
    except Exception as e:
        log.error(f"Steph parse failed: {e}\nRaw: {text[:300]}")
        return []


def run_aegis(trades: list) -> list:
    """Aegis: psychology, discipline, emotion patterns."""
    summary = build_summary(trades)
    emotion_pnl = {}
    for t in trades:
        e = t.get("emotion_before") or "unknown"
        if e not in emotion_pnl: emotion_pnl[e] = {"pnl": 0, "count": 0, "wins": 0}
        emotion_pnl[e]["pnl"] += t["pnl"]
        emotion_pnl[e]["count"] += 1
        if t["pnl"] > 0: emotion_pnl[e]["wins"] += 1

    emo_stats = {k: {"avg_pnl": round(v["pnl"]/v["count"]), "wr": round(v["wins"]/v["count"]*100), "n": v["count"]}
                 for k, v in emotion_pnl.items() if v["count"] >= 2}

    followed = [t for t in trades if t.get("followed_plan")]
    broke = [t for t in trades if t.get("followed_plan") is False]
    f_avg = sum(t["pnl"] for t in followed) / len(followed) if followed else 0
    b_avg = sum(t["pnl"] for t in broke) / len(broke) if broke else 0

    prompt = f"""You are Aegis, a trading coach for psychology and discipline.
Analyze this trader's emotional and behavioral patterns.

TRADE JOURNAL ({len(trades)} trades):
{summary}

STATS:
- Emotion at entry vs P&L: {json.dumps(emo_stats)}
- Followed plan ({len(followed)}): avg P&L ${f_avg:,.0f}
- Broke plan ({len(broke)}): avg P&L ${b_avg:,.0f}

Respond with 2-3 JSON coaching insights:
{{"coaching_type":"psychology"|"discipline"|"emotion","severity":"high"|"medium"|"low","title":"5-8 words","body":"2-3 sentences","action_item":"one change","supporting_trade_keys":["up to 3"]}}

Return ONLY the JSON array."""

    text, model = call_llm(prompt)
    if not text: return []
    try:
        insights = parse_json_response(text)
        return [{"agent_name": "aegis", "model": model, **i} for i in insights]
    except Exception as e:
        log.error(f"Aegis parse failed: {e}\nRaw: {text[:300]}")
        return []


# ── Save + Main ──────────────────────────────────────────────────────────────

def save_coaching(insights: list, trade_count: int):
    if not insights:
        log.info("No insights to save")
        return 0
    conn = _get_conn()
    cur = conn.cursor()
    agents = list(set(i.get("agent_name", "?") for i in insights))
    for agent in agents:
        cur.execute("DELETE FROM journal_agent_coaching WHERE agent_name=%s", [agent])

    saved = 0
    for i in insights:
        try:
            cur.execute("""
                INSERT INTO journal_agent_coaching
                    (agent_name, coaching_type, severity, title, body,
                     action_item, supporting_trades, model_used, trades_analyzed, data_points)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, [
                i.get("agent_name", "?"), i.get("coaching_type", "pattern"),
                i.get("severity", "medium"), i.get("title", ""),
                i.get("body", ""), i.get("action_item", ""),
                i.get("supporting_trade_keys", []),
                i.get("model", "unknown"), trade_count,
                json.dumps(i.get("data_points", {}))
            ])
            saved += 1
        except Exception as e:
            log.error(f"Save failed: {e}")
    conn.commit()
    conn.close()
    log.info(f"Saved {saved} coaching insights")
    return saved


def main():
    log.info("=== Journal Agent Coach ===")
    trades = load_annotated_trades()
    if len(trades) < 3:
        log.warning(f"Only {len(trades)} annotated trades — need 3+ for coaching. Exiting.")
        return

    all_insights = []
    log.info("Running Maria (entry/pattern)...")
    all_insights.extend(run_maria(trades))
    time.sleep(1)
    log.info("Running Steph (sizing/risk)...")
    all_insights.extend(run_steph(trades))
    time.sleep(1)
    log.info("Running Aegis (psychology/discipline)...")
    all_insights.extend(run_aegis(trades))

    saved = save_coaching(all_insights, len(trades))
    print(f"\n=== Agent Coaching Complete ===")
    print(f"Trades analyzed: {len(trades)}")
    print(f"Insights generated: {len(all_insights)}, saved: {saved}")
    for i in all_insights:
        print(f"  [{i.get('agent_name')}][{i.get('severity')}] {i.get('title')}")


if __name__ == "__main__":
    main()
