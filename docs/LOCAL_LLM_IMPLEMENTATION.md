# Local LLM Implementation — MS-01 (qwen3:14b via Ollama)
## Document Version: April 16, 2026
## Status: Production

---

## OVERVIEW

MS-01 runs Ollama with qwen3:14b (9.3GB) locally.
All Ollama calls are **$0 cost**. Cloud fallback (Sonnet/GPT-4-mini) only fires if Ollama fails.

**Model:** qwen3:14b (bdbd181c33f2)
**Ollama endpoint:** http://127.0.0.1:11434
**Average response time:** 22-45 seconds depending on prompt length
**Warm response time:** 2-5 seconds (model already loaded)

---

## THE QUEUE LAW — NON-NEGOTIABLE

**Ollama processes ONE request at a time.** If multiple calls fire simultaneously,
they queue internally in Ollama and later ones time out waiting.

**RULE: Every Ollama call in a loop MUST go through `_ollama_serialized()`**

```python
# scoring.py — THE ONLY APPROVED PATTERN
_ollama_lock = threading.Lock()

def _ollama_serialized(prompt: str, num_predict: int = 10, timeout: int = 90) -> str:
    """Serialized Ollama call — one at a time, no pile-up."""
    import urllib.request
    import json as _json
    payload = _json.dumps({
        "model": "qwen3:14b", "stream": False, "prompt": prompt,
        "options": {"temperature": 0.1, "num_predict": num_predict}
    }).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    with _ollama_lock:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return _json.loads(resp.read()).get("response", "").strip()
```

**NEVER do this:**
```python
# BAD — simultaneous calls, timeouts guaranteed
for ticker in tickers:
    urllib.request.urlopen(ollama_url, ...)  # NO
```

**ALWAYS do this:**
```python
# GOOD — serialized through lock
for ticker in tickers:
    result = _ollama_serialized(prompt, num_predict=10, timeout=90)
```

---

## BATCH PROCESSING — LARGE TICKER LISTS

For portfolio analysis (70 tickers) or any batch > 20:
- Chunk into groups of 10
- Process each chunk sequentially
- Sleep 2 seconds between chunks (memory pressure relief)

```python
CHUNK_SIZE = 10
for i in range(0, len(tickers), CHUNK_SIZE):
    chunk = tickers[i:i+CHUNK_SIZE]
    for ticker in chunk:
        result = _ollama_serialized(prompt, num_predict=50, timeout=150)
        # process result
    time.sleep(2)  # brief pause between chunks
```

---

## WARM-UP PROTOCOL

qwen3:14b takes 30-60 seconds to load from cold.
Once loaded, stays in memory for ~10 minutes of inactivity.

**Always warm up before a batch run:**
```python
def _warmup_ollama():
    """Ping Ollama with tiny prompt to pre-load model."""
    try:
        import urllib.request, json
        payload = json.dumps({
            "model": "qwen3:14b", "stream": False,
            "prompt": "hi", "options": {"num_predict": 1}
        }).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/generate",
            data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            json.loads(resp.read())
            print("  [ollama] Model warmed up")
    except Exception as e:
        print(f"  [ollama] Warm-up skipped: {e}")
```

Called at start of `run_pipeline()` in `trade_ai_orchestrator.py`.

---

## TIMEOUT GUIDELINES

| Use case | num_predict | timeout |
|---|---|---|
| Catalyst score (integer only) | 5-10 | 90s |
| One-line classification | 10-20 | 90s |
| Pre-plan (2 sentences) | 60-80 | 120s |
| Portfolio narrative (3-4 sentences) | 100-150 | 150s |
| Weekly summary | 200 | 180s |
| Full analysis section | 400 | 300s |

---

## FALLBACK CHAIN

All Ollama calls should have a fallback:

```
Ollama qwen3:14b (primary — $0)
  → timeout/error
OpenAI gpt-5.4-mini (fallback — $0.75/1M tokens)
  → timeout/error
Anthropic claude-sonnet-4-6 (last resort — $3/1M tokens)
```

For simple scoring tasks (catalyst 0-15):
- Ollama → Claude Haiku fallback (implemented in scoring.py)

For narrative tasks (weekly summary, portfolio analysis):
- Ollama → Claude Sonnet fallback (implemented in local_llm.py)

---

## IMPLEMENTATIONS TO DATE (April 16, 2026)

### 1. Catalyst Scoring — `scripts/scoring.py`
**Replaces:** Claude Haiku (`claude-haiku-4-5-20251001`)
**Function:** `_haiku_score_catalyst()` — now calls `_ollama_serialized()`
**Prompt:** Score catalyst 0-15, integer only
**Fallback:** Claude Haiku if Ollama unavailable
**Trigger:** When `is_ambiguous=True` (medium_impact catalyst)
**Cost saved:** ~$0.001 per call × ~5 calls per run × 4 runs/day = ~$0.02/day

### 2. Pre-Plan Generation — `scripts/scoring.py`
**New function:** `_ollama_preplan()`
**Replaces:** Nothing (new capability)
**Prompt:** 2-sentence scalp setup for tickers scoring 25-47
**Trigger:** `25 <= total < 48` and `decision in ("WAIT", "GO")`
**Fallback:** Empty string (graceful skip)

### 3. Weekly Portfolio Summary — `scripts/weekly_summary_local.py`
**Replaces:** Would have used Claude Sonnet
**Prompt:** 3-4 sentence weekly narrative with account breakdown
**Trigger:** Sunday 8PM weekly pipeline run
**Fallback:** Claude Sonnet via `local_llm.py`
**Cost saved:** ~$0.01 per week (minimal but principle matters)

### 4. Morning Digest — `scripts/morning_digest.py`
**New capability**
**Prompts:** Pre-market brief (6:55AM) + pre-open brief (9:25AM)
**Trigger:** continuous_runner.py at 06:55 and 09:25
**Fallback:** Sends partial message without Ollama narrative if timeout

### 5. OpenClaw Agents (Maria + Steph)
**Primary model:** `ollama/qwen3:14b`
**Fallback chain:** `openai/gpt-5.4-mini` → `anthropic/claude-sonnet-4-6`
**Use cases:** Calendar lookups (gog), portfolio questions, general chat
**Cost saved:** ~$0.75-3.00/day depending on usage

---

## PENDING IMPLEMENTATIONS

### 6. Stage 6 — Catalyst Intelligence (NEXT)
**File:** `scripts/catalyst_intelligence.py`
**Purpose:** Ollama classifies catalyst type, detects dilution/traps, scores 0-15
**Wire point:** After `catalyst_enrichment` in `trade_ai_orchestrator.py`
**Memory:** Writes to `ticker_memory.json` (14-day rolling)
**Queue:** Uses `_ollama_serialized()` — already enforced

### 7. Portfolio Intelligence Analysis (PLANNED)
**Use case:** Analyze all 70 portfolio + watchlist tickers with Ollama
**Pattern:** Chunk 10 at a time, 2s sleep between chunks
**Expected time:** ~15-20 minutes for 70 tickers
**Run schedule:** Weekly Sunday (time-insensitive)
**Output:** Per-ticker narrative injected into portfolio dashboard

### 8. Trade Journal Pattern Analysis (PLANNED)
**Use case:** Ollama reads 619 closed trades, finds patterns
**Questions:** What setups work best? What time of day? What catalysts?
**Output:** Weekly insight added to journal tab

### 9. Brave Search Integration (NEXT SESSION)
**Purpose:** Give Ollama web search capability
**API:** Brave Search API (free tier 2,000 queries/month)
**Use cases:** Pre-market news, catalyst verification, company research
**Pattern:** Tool call from Ollama prompt → Brave API → result injected back

---

## FILE LOCATIONS (MS-01)

| File | Purpose |
|---|---|
| `scripts/scoring.py` | `_ollama_lock`, `_ollama_serialized()`, `_ollama_preplan()` |
| `scripts/trade_ai_orchestrator.py` | `_warmup_ollama()`, pipeline warm-up call |
| `scripts/local_llm.py` | General-purpose Ollama wrapper with fallback |
| `scripts/weekly_summary_local.py` | Weekly portfolio narrative |
| `scripts/morning_digest.py` | Pre-market + pre-open Telegram briefs |
| `scripts/catalyst_intelligence.py` | Stage 6 catalyst classification (pending wire) |
| `scripts/ticker_memory.py` | 14-day ticker observation store |
| `data/state/ticker_memory.json` | Live memory file |

---

## TESTING COMMANDS

```bash
# Test Ollama is responding
curl -s http://127.0.0.1:11434/api/tags | python3 -m json.tool | grep name

# Test single call with timing
python3 -c "
import urllib.request, json, time
payload = json.dumps({'model':'qwen3:14b','stream':False,'prompt':'hi','options':{'num_predict':5}}).encode()
req = urllib.request.Request('http://127.0.0.1:11434/api/generate',data=payload,headers={'Content-Type':'application/json'},method='POST')
start=time.time()
with urllib.request.urlopen(req,timeout=60) as r: d=json.loads(r.read())
print(f'Response: {d.get(\"response\",\"\")} | Time: {round(time.time()-start,1)}s')
"

# Test full pipeline with Ollama scoring
python3 scripts/trade_ai_orchestrator.py --run-label 0900 --skip-market-check --no-alerts 2>&1 | grep -E "ollama|scoring|warmed|✅|❌"

# Test morning digest
python3 scripts/morning_digest.py --type premarket --project-root .

# Test weekly summary
python3 scripts/weekly_summary_local.py
```

---

## MONITORING

Check Ollama is running:
```bash
ps aux | grep ollama
curl -s http://127.0.0.1:11434/api/tags | python3 -m json.tool | grep name
```

Ollama does NOT run as a systemd service — it auto-starts when first called.
If it's not responding: `ollama serve &` to start manually.

---

## COST COMPARISON

| Task | Before (Cloud) | After (Ollama) | Savings/day |
|---|---|---|---|
| Catalyst scoring (4 runs) | ~$0.02 Haiku | $0 | $0.02 |
| Agent interactions (Maria+Steph) | ~$1-3 GPT | $0 | $1-3 |
| Weekly summary | ~$0.05 Sonnet | $0 | $0.05/week |
| Morning digest (2x daily) | ~$0.10 Sonnet | $0 | $0.10 |
| **Monthly estimate** | ~$35-90 | ~$5 (fallbacks only) | **$30-85/mo** |
