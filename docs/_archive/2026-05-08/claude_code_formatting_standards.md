# Trade AI v12 — Code & Document Formatting Standards
**Server:** ms01-openclaw | `johnclaw@192.168.50.16`
**Root:** `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/`
**Bible:** v7.8 | **Ref Arch doc:** v1.7

This prompt tells you how I (Claude) format code and documents in this project.
Do not change these patterns. If you see something formatted differently, bring
it to this standard — do not invent new patterns.

---

## SECTION 1 — Python Files

### General rules

```python
# File header — every script gets this block
"""
script_name.py

One-sentence description of what this script does.
Called by: [who calls this — cron/event_router/manual]
"""

# Imports: stdlib first, then third-party, then local
import sys
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

# Local — always add ROOT to sys.path for scripts/ directory
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
```

### Logging — always use this pattern, never print()

```python
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [script_name] %(levelname)s %(message)s'
)
logger = logging.getLogger(__name__)

# Use these levels correctly:
logger.info("Normal operation — pipeline step completed")
logger.warning("Non-fatal — missing data, fallback used")
logger.error("Failed — job couldn't complete", exc_info=True)
logger.debug("Verbose detail — only when debugging")
```

### Database connections — always use this pattern

```python
# ALWAYS use -h localhost flag — peer auth on socket will fail
# ALWAYS load from env, never hardcode credentials
import os
from dotenv import load_dotenv
load_dotenv()

def get_db():
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=int(os.getenv('DB_PORT', 5432)),
        dbname=os.getenv('DB_NAME', 'trade_ai'),
        user=os.getenv('DB_USER', 'trade_ai'),
        password=os.getenv('DB_PASSWORD')
    )

# Always use RealDictCursor for SELECT queries
cur = conn.cursor(cursor_factory=RealDictCursor)

# Always close connections — use try/finally
conn = get_db()
try:
    # ... work ...
    conn.commit()
finally:
    conn.close()
```

### Error handling — always non-fatal for secondary features

```python
# CRITICAL path — let it propagate, log it
def run_agent_job(symbol, conn):
    try:
        result = _process(symbol, conn)
        return result
    except Exception as e:
        logger.error(f"Agent job failed for {symbol}: {e}", exc_info=True)
        raise  # re-raise on critical paths

# OPTIONAL feature (RAG, peer notes, sector data) — swallow and continue
try:
    rag_context = get_rag_context(symbol, conn=conn)
except Exception as e:
    logger.warning(f"RAG fetch failed for {symbol}: {e}")
    rag_context = ""  # non-fatal fallback
```

### Telegram alerts — always use the shared module

```python
# CORRECT — uses shared module that sends to ALL configured chat IDs
from telegram_alert import send_telegram
send_telegram(f"🔴 Stop triggered: {symbol} breached at ${price:.2f}")

# WRONG — never call the Telegram API directly or hardcode chat IDs
# import requests
# requests.post(f"https://api.telegram.org/bot{token}/sendMessage", ...)
```

### SQL — formatting rules

```python
# Multi-line queries: use triple-quoted strings, indent consistently
cur.execute("""
    SELECT agent_name, symbol, recommendation, confidence,
           rag_sources_used IS NOT NULL as has_rag,
           created_at
    FROM watchlist_agent_results
    WHERE symbol = %s
      AND agent_name = %s
      AND created_at > NOW() - INTERVAL '30 days'
    ORDER BY created_at DESC
    LIMIT %s
""", [symbol, agent_name, limit])

# UPSERT pattern — always ON CONFLICT for insert/update operations
cur.execute("""
    INSERT INTO agent_intelligence_rules
        (agent_name, rule_type, config, created_at)
    VALUES (%s, %s, %s, NOW())
    ON CONFLICT (agent_name, rule_type) DO UPDATE
    SET config = EXCLUDED.config, updated_at = NOW()
""", [agent_name, rule_type, json.dumps(config)])

# Never use f-strings in SQL — always %s parameterization
# WRONG:  f"WHERE symbol = '{symbol}'"
# CORRECT: "WHERE symbol = %s", [symbol]
```

### Function docstrings — short, factual

```python
def get_rag_context(symbol: str, limit: int = 7, conn=None) -> list:
    """
    Retrieve top-ranked RAG items for a symbol.
    Returns list of dicts with keys: source_type, title, content, score.
    Returns [] on any error — always non-fatal.
    """
```

### Non-ASCII characters in scripts — strict rule

**NEVER put emoji or non-ASCII characters directly in Python source files.**
They cause encoding errors in log redirection on this server.

```python
# WRONG — will break log redirection
logger.info(f"✅ Agent {agent_name} complete")
msg = f"🔴 STOP TRIGGERED: {symbol}"

# CORRECT — emoji only in Telegram message strings (sent as data, not logged)
logger.info(f"Agent {agent_name} complete: {recommendation}")
send_telegram(f"🔴 STOP TRIGGERED: {symbol} at ${price:.2f}")  # OK in telegram strings
```

---

## SECTION 2 — React / TypeScript (Frontend)

### Component structure

```tsx
// Always default exports
// Always explicit return types on functions that return JSX

interface WatchlistRowProps {
  item: WatchlistItem;
  onSelect: (symbol: string) => void;
}

export default function WatchlistRow({ item, onSelect }: WatchlistRowProps) {
  // 1. State declarations
  const [loading, setLoading] = useState(false);

  // 2. Data fetching / effects
  useEffect(() => { /* ... */ }, [item.symbol]);

  // 3. Event handlers
  const handleEscalate = async () => { /* ... */ };

  // 4. Render
  return (
    <div className="watchlist-row" onClick={() => onSelect(item.symbol)}>
      {/* ... */}
    </div>
  );
}
```

### API calls — always async/await with error handling

```tsx
// CORRECT pattern — used throughout the codebase
async function escalateToAlex(symbol: string, reason: string) {
  try {
    const res = await fetch(`/api/v2/watchlist/${symbol}/escalate-alex`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason })
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'Unknown error');
    showToast(`⭐ ${symbol} escalated to Alex`);
  } catch (e) {
    console.error('Escalate failed:', e);
    showToast(`Error: ${e.message}`);
  }
}

// Null-safety — ALWAYS guard API response fields before using
// The API may not include every field for every ticker
const tradeType = item?.trade_type ?? 'WATCH';
const inPortfolio = item?.in_portfolio ?? false;
const portfolioWeight = item?.portfolio_weight ?? 0;
const sectorNews = item?.sector_news ?? [];
```

### Colors — always use these exact values (system design tokens)

```typescript
// These are the only colors used in this system — do not introduce new ones
const COLORS = {
  navy:         '#0F1C2E',   // dark backgrounds, headers
  navy2:        '#1B2D45',
  navy3:        '#243B55',
  blue:         '#1E6FBF',   // primary blue
  blue2:        '#2E86D4',
  blueLight:    '#DBEAFE',
  teal:         '#0D9488',   // INCOME badge, H2 headings
  tealLight:    '#CCFBF1',
  green:        '#16A34A',   // success, BUY, confirmed
  greenLight:   '#DCFCE7',
  amber:        '#D97706',   // warning, WAIT, SWING badge
  amberLight:   '#FEF3C7',
  red:          '#DC2626',   // danger, SELL, stop trigger
  redLight:     '#FEE2E2',
  purple:       '#7C3AED',   // Alex/Sonnet, escalation
  purpleLight:  '#EDE9FE',
  text:         '#1F2937',   // body text
  textMuted:    '#6B7280',   // secondary text
  textLight:    '#9CA3AF',   // placeholder, disabled
  bgGray:       '#F8FAFC',   // alternate row
  bgGray2:      '#F1F5F9',   // code background
  border:       '#CBD5E1',   // table/card borders
  white:        '#FFFFFF',
};

// Trade type badge colors — fixed mapping
const TRADE_TYPE_COLORS = {
  INCOME: '#0D9488',   // teal
  LONG:   '#16A34A',   // green
  SWING:  '#D97706',   // amber
  SHORT:  '#DC2626',   // red
  WATCH:  '#6B7280',   // gray
};

// Signal colors
const SIGNAL_COLORS = {
  GO:     '#16A34A',
  WAIT:   '#D97706',
  AVOID:  '#6B7280',
  BUY:    '#16A34A',
  SELL:   '#DC2626',
  HOLD:   '#2E86D4',
  TRIM:   '#D97706',
  ADD:    '#0D9488',
};
```

### Badge/tag components — always this pattern

```tsx
// Small monospace badge — used for agent names, trade types, source tags
function Badge({
  label,
  color,
  bg
}: { label: string; color: string; bg?: string }) {
  return (
    <span style={{
      fontSize: '10px',
      fontFamily: 'monospace',
      padding: '2px 6px',
      borderRadius: '3px',
      border: `1px solid ${color}`,
      color,
      background: bg || 'transparent',
      whiteSpace: 'nowrap',
    }}>
      {label}
    </span>
  );
}

// Usage
<Badge label="INCOME" color="#0D9488" />
<Badge label="HELD 26%" color="#DC2626" bg="rgba(220,38,38,0.1)" />
<Badge label="AI Discover" color="#7C3AED" bg="rgba(124,58,237,0.1)" />
```

### Toast notifications — always this pattern (no libraries)

```tsx
function showToast(msg: string, duration = 3000) {
  const t = document.createElement('div');
  t.style.cssText = [
    'position:fixed', 'bottom:24px', 'right:24px',
    'background:#1E293B', 'color:#E2EAF4',
    'padding:12px 20px', 'border-radius:8px',
    'font-size:13px', 'font-family:Calibri,sans-serif',
    'z-index:9999', 'border:1px solid #334155',
    'box-shadow:0 4px 12px rgba(0,0,0,0.3)',
  ].join(';');
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), duration);
}
```

---

## SECTION 3 — API Endpoints (api_v2.py)

### Endpoint structure — always this pattern

```python
@app.route('/api/v2/watchlist/<symbol>/escalate-alex', methods=['POST'])
def escalate_to_alex(symbol):
    """Queue Alex analysis for a symbol. Sends Telegram notification."""
    data = request.json or {}
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Do the work
        cur.execute("""
            INSERT INTO watchlist_agent_jobs
                (symbol, requested_agent, task_type, priority, status, submitted_from)
            VALUES (%s, 'alex', 'user_escalation', 'high', 'pending', 'watchlist_panel')
        """, [symbol])
        conn.commit()

        # Telegram notification
        from telegram_alert import send_telegram
        send_telegram(f"⭐ *{symbol}* escalated to Alex from watchlist")

        return jsonify({'ok': True, 'symbol': symbol, 'queued': True})

    except Exception as e:
        logger.error(f"escalate_to_alex failed for {symbol}: {e}", exc_info=True)
        conn.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()
```

### Response envelope — always `{"ok": true/false, "data": {...}}` or `{"ok": false, "error": "..."}`

```python
# Success
return jsonify({'ok': True, 'data': {'items': rows, 'count': len(rows)}})

# Error
return jsonify({'ok': False, 'error': 'Symbol not found'}), 404

# Never return bare dicts without the ok wrapper
# WRONG: return jsonify({'items': rows})
# CORRECT: return jsonify({'ok': True, 'data': {'items': rows}})
```

---

## SECTION 4 — Documentation Files

### SKILL.md — update this after EVERY session that changes the system

The SKILL.md at `docs/project/SKILL.md` is the quick-reference for Claude Code.
It is currently at **v7.3** but the system is at **v7.8**. It needs updating.

**Fields to keep current in SKILL.md:**
- System Bible version in the header
- DB table count
- Cron job count
- Telegram command count
- API route count
- Any new scripts added to the Key Files section
- Any renamed agents (maria→maria_research, steph→steph_allocation)

**Do NOT change in SKILL.md:**
- Server address, paths, venv location — these are stable
- Quick commands section — only change if commands actually change
- The Iron Rule section — never change this

### Reference Architecture doc — update after major feature additions

The doc at `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/docs/project/`
or the copy maintained in this Claude project is the canonical reference.

**Numbers that change and need periodic updates (done via Claude, not Claude Code):**
- RAG total items and coverage % — changes daily
- Agent analyses count — grows daily
- DB table count — changes when new tables are created

**Numbers Claude Code should update immediately when they change:**
- DB table count — after `CREATE TABLE`
- Cron job count — after adding/removing crons
- Telegram command count — after adding new commands
- Script line counts in Key Files table — after major rewrites

---

## SECTION 5 — What NOT to Change

**Never touch these files without explicit instruction:**
- `data/portfolios/state/holdings.json` — portfolio state, never overwrite
- `data/portfolios/state/personal_situation.json` — financial context
- `data/portfolios/state/risk_management.json` — stop levels
- `data/portfolios/state/dividend_calendar.json` — dividend dates
- `.env` — API keys, never log or echo these values

**Never change these patterns without explicit instruction:**
- The LLM fallback chain (local→grok→claude→openai) in `llm_router.py`
- The G1-G10 global rules in `_build_prompt()` in `process_watchlist_agent_jobs.py`
- Agent soul files in `~/.openclaw/agents/*/agent/SOUL.md`
- The `trade_ai` DB user — always connect as trade_ai with `-h localhost`

**Never introduce these anti-patterns:**
- Hardcoded chat IDs anywhere — use TELEGRAM_CHAT_ID from env
- Direct psycopg2 connection without `-h localhost` (peer auth will fail)
- `print()` in Python scripts that run on cron (use `logger.info()`)
- Non-ASCII in Python source files (use only in Telegram string payloads)
- f-strings in SQL queries (use %s parameterization)
- `localStorage` or `sessionStorage` in React components
- Inline `style` objects duplicated across multiple components (extract to constants)

---

## SECTION 6 — Session Discipline

### Before starting any session

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

# 1. Holdings guard — always
python3 -c "import json; d=json.load(open('data/portfolios/state/holdings.json')); assert d['portfolio_totals']['total_value']>1000000; print('Holdings OK:', d['portfolio_totals']['total_value'])"

# 2. Preflight
python3 scripts/system_preflight_check.py

# 3. Note the pass/fail count — do not end session with fewer passes
```

### After any Python file change

```bash
# Syntax check immediately — before doing anything else
python3 -c "import ast; ast.parse(open('scripts/CHANGED_FILE.py').read()); print('syntax OK')"
```

### After any api_v2.py change

```bash
# Restart the server to pick up changes
pkill -f portfolio_server.py && sleep 3
nohup .venv/bin/python scripts/portfolio_server.py > logs/portfolio_server.log 2>&1 &
sleep 5
curl -s http://localhost:7777/api/v2/system-health | python3 -m json.tool | head -5
```

### After adding new tables

```bash
# Update the SKILL.md DB table count
psql -h localhost -U trade_ai -d trade_ai -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"
# Then update SKILL.md line that says "N tables in trade_ai database"
```

### After adding new cron entries

```bash
crontab -l | grep -v "^#" | grep -c "."  # count active crons
# Update SKILL.md and bible accordingly
```

---

## What Good Output Looks Like

A well-formatted change in this codebase:
1. Uses the logging pattern above — never print()
2. Wraps optional features in try/except — non-fatal
3. Uses RealDictCursor for all SELECT queries
4. Returns `{"ok": true/false, "data": {...}}` from API endpoints
5. Uses %s parameterized SQL — no f-strings in queries
6. Has no emoji or non-ASCII in Python source (only in Telegram payload strings)
7. Updates SKILL.md with any new counts or file additions
8. Syntax-checks every modified Python file before moving on
9. Verifies holdings are intact after any deploy or state-touching operation

**If you see code that violates these patterns — fix it to the standard.**
**If you are unsure — ask before inventing a new pattern.**
