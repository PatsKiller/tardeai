#!/usr/bin/env python3
"""process_watchlist_agent_jobs.py — Agent processing with maturity tracking + full narratives.

Polls watchlist_agent_jobs for queued items, routes to the appropriate agent,
captures full narratives, updates maturity state, and triggers synthesis when ready.

Cron: */15 * * * * python3 scripts/process_watchlist_agent_jobs.py --limit 10

Agents:
- maria: catalyst/news/research review
- steph: allocation/account-fit review
- risk_agent: technical/risk/stop review
- tax_agent: tax/location review
- full_chain: orchestrated multi-agent review
"""
import json, os, sys, re, hashlib, urllib.request
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from watchlist_priority import (
    WATCHLIST_TOP_N, holdings_list, is_off_hours_et, job_priority_params,
    off_hours_scope_params, request_type_sla_params, sql_job_priority_case,
    sql_off_hours_scope, sql_request_type_sla_case,
)
from cio_agent_contract import (
    AGENT_JSON_CONTRACT_VERSION,
    GLOBAL_RULES_G1_G10,
    build_base_json_instruction,
    build_synthesis_json_schema,
    format_evidence_for_synthesis,
    merge_structured_into_result,
    normalize_agent_confidence,
    normalize_data_i_doubt,
    normalize_evidence,
    parse_agent_result,
    parse_synthesis_result,
)
from hermes_discovery.symbol_validation import gate_watchlist_symbol
_last_rag_sources = []  # Set by _build_prompt(), read by result saver
_last_peer_agents = []  # Set by _get_peer_agent_notes(), read by result saver
_batch_results_cache = {}  # {symbol: [{agent, recommendation, confidence, summary}]}
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
from local_llm_config import get_local_llm_model, get_local_llm_base_url

# Pipeline telemetry
try:
    from pipeline_registry import PipelineRun
except ImportError:
    class PipelineRun:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def rows(self, n): pass
OLLAMA_URL = get_local_llm_base_url().rstrip("/") + "/api/chat"
OLLAMA_MODEL = get_local_llm_model()

# Agent name normalization (risk_agent/tax_agent → risk/tax for maturity tracking)
AGENT_TO_MATURITY = {
    "maria": "maria", "steph": "steph",
    "risk_agent": "risk", "risk": "risk",
    "tax_agent": "tax", "tax": "tax",
    "full_chain": "full_chain",
}


def _portfolio_symbol_set() -> frozenset[str]:
    path = STATE_DIR / "holdings.json"
    try:
        data = json.loads(path.read_text())
        syms = {
            str(h.get("symbol", "")).upper().strip()
            for h in (data.get("holdings") or [])
            if h.get("symbol")
        }
        return frozenset(s for s in syms if s)
    except Exception:
        return frozenset()


def _fmt_confidence(val) -> str:
    return f"{normalize_agent_confidence(val) * 100:.0f}%"


def _get_conn():
    import psycopg2
    pw = os.environ.get("DB_PASSWORD", "")
    if not pw:
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="):
                pw = line.split("=", 1)[1].strip()
    # keepalives + sslmode=disable: long Ollama calls were idling the connection and
    # causing "SSL connection has been closed unexpectedly" on the post-LLM INSERT.
    return psycopg2.connect(
        host="localhost", dbname="trade_ai", user="trade_ai", password=pw,
        sslmode="disable", connect_timeout=10,
        keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5,
    )


def _refresh_conn(conn):
    """Ping or replace a connection after a long LLM/embed call."""
    try:
        with conn.cursor() as ping:
            ping.execute("SELECT 1")
        return conn
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return _get_conn()


def _check_symbol_data_quality(symbol: str) -> dict:
    """Check if a symbol has minimum data for meaningful agent analysis."""
    enrichment = {}
    try:
        ec_path = STATE_DIR / "ticker_enrichment_cache.json"
        if ec_path.exists():
            enrichment = json.loads(ec_path.read_text()).get(symbol, {})
            if not isinstance(enrichment, dict):
                enrichment = {}
    except Exception:
        pass

    has_price = bool(enrichment.get("price") or enrichment.get("latest_price"))
    has_technicals = bool(enrichment.get("rsi") and (enrichment.get("sma20_pct") or enrichment.get("sma50_pct")))

    # Check news count
    news_count = 0
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM news_articles WHERE symbol=%s AND created_at > NOW() - INTERVAL '14 days'", (symbol,))
        news_count = cur.fetchone()[0]
        conn.close()
    except Exception:
        pass
    has_news = news_count > 0

    missing = []
    if not has_price:
        missing.append("price_data")
    if not has_technicals:
        missing.append("technical_indicators")
    if not has_news:
        missing.append("news_articles")

    score = (40 if has_price else 0) + (40 if has_technicals else 0) + (20 if has_news else 0)
    return {"has_price": has_price, "has_technicals": has_technicals, "has_news": has_news,
            "quality_score": score, "enrichment_needed": missing}


def _attempt_symbol_enrichment(symbol: str, missing: list) -> bool:
    """Try to get missing data using free sources only. Returns True if enriched."""
    enriched = False

    if "price_data" in missing or "technical_indicators" in missing:
        try:
            from phase2_ticker_enrichment import _optional_yfinance
            yf_data = _optional_yfinance(symbol)
            if yf_data:
                # Update enrichment cache
                ec_path = STATE_DIR / "ticker_enrichment_cache.json"
                cache = json.loads(ec_path.read_text()) if ec_path.exists() else {}
                if symbol not in cache or not isinstance(cache.get(symbol), dict):
                    cache[symbol] = {}
                for k, v in yf_data.items():
                    if v not in (None, "", "N/A"):
                        cache[symbol][k] = v
                ec_path.write_text(json.dumps(cache, indent=2, default=str))
                enriched = True
                print(f"  [enrichment] {symbol}: yfinance → {len(yf_data)} fields updated")
        except Exception as e:
            print(f"  [enrichment] {symbol}: yfinance failed — {e}")

    if "news_articles" in missing:
        try:
            from external_market_data_ingest import ingest_yfinance_quotes
            ingest_yfinance_quotes(symbols=[symbol])
            enriched = True
            print(f"  [enrichment] {symbol}: price quote ingested")
        except Exception as e:
            print(f"  [enrichment] {symbol}: quote ingest failed — {e}")

    return enriched


# Maria-only OAuth priority tier (operator 2026-07-09). Free OAuth lanes (grok :8645 → chatgpt :8646)
# for Maria agent_narrative on: portfolio holdings, top-N WAIT setups, manual refresh jobs.
# Steph/Risk/tail research stay on local gemma. Daily cap via llm_consumption_log (~80/day);
# per-run cap prevents a single cron burst from draining the budget.
from maria_oauth_priority import (
    MARIA_OAUTH_DAILY_CAP,
    MARIA_OAUTH_PROCESS_ID,
    MARIA_OAUTH_RUN_CAP,
    WAIT_SETUP_HOURS,
    WAIT_SETUP_LIMIT,
    maria_priority_tier,
)

_CURRENT_JOB_PRIORITY: int | None = None
_CURRENT_JOB_SYMBOL: str | None = None
_CURRENT_AGENT: str | None = None
_CURRENT_JOB_SUBMITTED_FROM: str | None = None
_CURRENT_JOB_REQUEST_TYPE: str | None = None
_PORTFOLIO_SYMS_RUN: frozenset[str] = frozenset()
_WAIT_SETUP_SYMS_RUN: frozenset[str] = frozenset()
_LOCAL_SLOW = False          # telemetry only — no longer widens OAuth routing
_MARIA_OAUTH_RUN_CALLS = 0
_LOCAL_SLOW_S = float(os.environ.get("LOCAL_SLOW_S", "45"))


def _wait_setup_symbol_set(conn) -> frozenset[str]:
    """Top-N symbols with a recent WAIT scan (actionable setup window)."""
    try:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT symbol FROM (
                    SELECT DISTINCT ON (symbol) symbol, score
                    FROM trade_ai_scans
                    WHERE decision = 'WAIT'
                      AND scanned_at > NOW() - INTERVAL '{int(WAIT_SETUP_HOURS)} hours'
                    ORDER BY symbol, scanned_at DESC
                ) latest
                ORDER BY score DESC NULLS LAST
                LIMIT %s""",
            (int(WAIT_SETUP_LIMIT),),
        )
        return frozenset(str(r[0]).upper().strip() for r in cur.fetchall() if r and r[0])
    except Exception:
        return frozenset()


def _job_provider_lane() -> str:
    """AUTO_QUEUE vs MANUAL_OPERATOR vs CHALLENGE. Holdings/WAIT do not force OAuth."""
    payload = {}
    try:
        from agent_job_provider_policy import classify_job_lane
    except ImportError:
        from lib.agent_job_provider_policy import classify_job_lane  # type: ignore
    return classify_job_lane(
        submitted_from=_CURRENT_JOB_SUBMITTED_FROM,
        request_type=_CURRENT_JOB_REQUEST_TYPE,
        priority=_CURRENT_JOB_PRIORITY,
        payload=payload,
    )


def _prefer_maria_oauth() -> bool:
    """OAuth may preempt Flash only for explicit challenge/manual-OAuth — never auto queue.

    maria_priority_tier (holdings / top-N WAIT) remains for legacy/manual compatibility
    diagnostics but MUST NOT silently preempt governed DeepSeek Flash.
    """
    if (_CURRENT_AGENT or "").lower() != "maria":
        return False
    if _MARIA_OAUTH_RUN_CALLS >= MARIA_OAUTH_RUN_CAP:
        return False
    try:
        from llm_consumption import over_daily_cap
        if over_daily_cap(MARIA_OAUTH_PROCESS_ID):
            return False
    except Exception:
        pass
    try:
        from agent_job_provider_policy import oauth_may_preempt_flash
    except ImportError:
        from lib.agent_job_provider_policy import oauth_may_preempt_flash  # type: ignore
    return oauth_may_preempt_flash(_job_provider_lane())


_REFUSAL_PREFIXES = ("i cannot fulfill", "i can't fulfill", "i cannot help", "i can't help",
                     "i'm unable to", "i am unable to", "i cannot act as", "i can't act as",
                     "i cannot provide", "i can't provide")


def _is_refusal(text) -> bool:
    """Cloud-lane persona/jailbreak refusals ("I cannot fulfill...", "**Refusal** This request
    requires the active profile to switch to a trading-advisory identity...") come back as
    successful generations, so they were stored and DISPLAYED as CIO synthesis (FATN/SMCI/WNW,
    2026-07-06). Detect them at the call site and fall back to the local lane instead."""
    if not text:
        return False
    head = str(text).lstrip("*#_ ").lower()[:400]
    if head.startswith(_REFUSAL_PREFIXES):
        return True
    return "**refusal**" in head or "requires the active profile to switch" in head


def _llm(prompt: str, max_tokens: int = 800, task_type: str = "agent_narrative",
         high_impact: bool = False) -> str:
    """Call LLM via router with fallback hierarchy.

    Gate-B.2 (Provider Authority Closure): The OAuth priority tier is a LEGACY
    research facility. It must not present its output as governed financial-agent work.
    Agent identity in metadata is "legacy_watch_research", NOT any of the six
    governed professional identities (alex/maria/steph/guardian/ledger/morgan).

    The router path and Ollama fallback are also legacy research facilities.
    Provider provenance is recorded in _llm._fallback_chain so callers can
    distinguish declared multi-lane research from silent fallback.
    """
    global _MARIA_OAUTH_RUN_CALLS, _LOCAL_SLOW
    _llm._fallback_chain = []  # Gate-B.2: explicit provider provenance
    try:
        from agent_job_provider_policy import (
            first_provider_attempt,
            is_hard_policy_failure,
            oauth_soft_fallback_permitted,
            requested_provider_policy,
        )
    except ImportError:
        from lib.agent_job_provider_policy import (  # type: ignore
            first_provider_attempt,
            is_hard_policy_failure,
            oauth_soft_fallback_permitted,
            requested_provider_policy,
        )
    job_lane = _job_provider_lane()
    _llm._requested_policy = requested_provider_policy(job_lane)
    _llm._first_attempt = first_provider_attempt(job_lane)
    _llm._fallback_reason = None
    _llm._manual_vs_automatic = "manual" if job_lane != "AUTO_QUEUE" else "automatic"

    def _try_maria_oauth(*, fallback_reason: str | None) -> str | None:
        global _MARIA_OAUTH_RUN_CALLS
        if task_type not in ("agent_narrative", "agent_debate"):
            return None
        if (_CURRENT_AGENT or "").lower() != "maria":
            return None
        try:
            from llm_consumption import gate_and_generate
            from maria_oauth_priority import is_manual_refresh
            cloud_prompt = _strip_local_tokens(prompt)
            manual = is_manual_refresh(
                _CURRENT_JOB_SUBMITTED_FROM,
                priority=_CURRENT_JOB_PRIORITY,
                request_type=_CURRENT_JOB_REQUEST_TYPE,
            )
            for lane in ("grok", "chatgpt"):
                try:
                    out = gate_and_generate(
                        cloud_prompt,
                        lane=lane,
                        process_id=MARIA_OAUTH_PROCESS_ID,
                        task_summary=f"maria {task_type} {_CURRENT_JOB_SYMBOL or ''}".strip(),
                        manual_trigger=manual,
                        timeout=120,
                        metadata={
                            "symbol": _CURRENT_JOB_SYMBOL,
                            "agent": "legacy_watch_research",
                            "governed_financial_agent": False,
                            "provenance_identity": "LEGACY_WATCH_RESEARCH_NON_PROFESSIONAL",
                            "declared_lanes": ["grok-oauth", "chatgpt-oauth"],
                            "submitted_from": _CURRENT_JOB_SUBMITTED_FROM,
                        },
                    )
                except Exception:
                    continue
                if _is_refusal(out):
                    continue
                if out and len(str(out).strip()) > 20:
                    _MARIA_OAUTH_RUN_CALLS += 1
                    _llm._last_model = f"{lane}-oauth"
                    _llm._last_provider = lane
                    _llm._last_cost = 0
                    _llm._fallback_reason = fallback_reason
                    _llm._fallback_chain = [
                        {"attempted": "grok-oauth"},
                        {"attempted": "chatgpt-oauth"},
                        {"used": f"{lane}-oauth"},
                        {"fallback_reason": fallback_reason},
                    ]
                    return str(out)
        except Exception:
            return None
        return None

    if task_type in ("agent_narrative", "agent_debate") and _prefer_maria_oauth():
        preempt = _try_maria_oauth(fallback_reason="EXPLICIT_OAUTH_LANE")
        if preempt:
            return preempt
        _llm._fallback_chain = [{"attempted": "grok-oauth", "failed": True},
                                 {"attempted": "chatgpt-oauth", "failed": True}]
    try:
        import time as _tt
        _t0 = _tt.time()
        from llm_router import get_llm_response
        result = get_llm_response(
            task_type=task_type,
            prompt=prompt,
            max_tokens=max_tokens,
            high_impact=high_impact,
            # issue #283: stable job key + metadata for governed Flash (no private PII)
            metadata={
                "symbol": _CURRENT_JOB_SYMBOL,
                "submitted_from": _CURRENT_JOB_SUBMITTED_FROM,
                "agent_path": "process_watchlist_agent_jobs",
            },
            job_key=f"{task_type}:{_CURRENT_JOB_SYMBOL or ''}:{_CURRENT_JOB_SUBMITTED_FROM or ''}",
        )
        if result.get("success"):
            # Saturation valve: one slow local call widens cloud routing to priority-3 jobs.
            if result.get("provider") == "local" and (_tt.time() - _t0) > _LOCAL_SLOW_S:
                _LOCAL_SLOW = True
            # Track which model was used
            _llm._last_model = result.get("model_used", OLLAMA_MODEL)
            _llm._last_provider = result.get("provider", "local")
            _llm._last_cost = result.get("cost_estimate", 0)
            # Gate-B.2: append router step to fallback chain
            if not hasattr(_llm, '_fallback_chain') or not _llm._fallback_chain:
                _llm._fallback_chain = []
            _llm._fallback_chain.append({"used": f"llm_router:{result.get('provider', 'unknown')}",
                                          "model": _llm._last_model})
            return result["response"]
        else:
            err = str(result.get("error", "all providers failed"))
            if is_hard_policy_failure(err):
                _llm._fallback_reason = "HARD_POLICY_FAILURE"
                _llm._fallback_chain.append({"hard_failure": err[:160]})
                return f"LLM error: {err}"
            if oauth_soft_fallback_permitted(job_lane, err):
                oauth_out = _try_maria_oauth(fallback_reason="FLASH_SOFT_FAILURE")
                if oauth_out:
                    return oauth_out
            return f"LLM error: {err}"
    except ImportError:
        # Fallback to direct Ollama if router not available
        try:
            payload = json.dumps({"model": OLLAMA_MODEL, "stream": False, "think": False,
                                  "messages": [{"role": "user", "content": prompt}],
                                  "options": {"temperature": 0.3, "num_predict": max_tokens}}).encode()
            req = urllib.request.Request(OLLAMA_URL, data=payload,
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=120) as resp:
                # Gate-B.2: record raw Ollama as explicit fallback (not silent)
                if not hasattr(_llm, '_fallback_chain') or not _llm._fallback_chain:
                    _llm._fallback_chain = []
                _llm._fallback_chain.append({"used": f"raw_ollama:{OLLAMA_MODEL}", "fallback": True})
                _llm._last_model = OLLAMA_MODEL
                _llm._last_provider = "local"
                _llm._last_cost = 0
                return json.loads(resp.read()).get("message", {}).get("content", "").strip()
        except Exception as e:
            return f"LLM error: {e}"

# Track last model used for logging
_llm._last_model = OLLAMA_MODEL
_llm._last_provider = "local"
_llm._last_cost = 0
_llm._requested_policy = None
_llm._first_attempt = None
_llm._fallback_reason = None
_llm._manual_vs_automatic = None

# ── CIO final-synthesis: free Grok OAuth primary, local gemma fallback (operator 2026-06-14) ──
# The specialist agents (Maria/Steph/Risk) stay on local gemma3:4b; only the FINAL synthesis — the
# one decision per symbol that becomes the CIO View — runs on the stronger free Grok lane, falling
# back to local when the proxy isn't authenticated. Both lanes are free (no metered API).
SYNTHESIS_PROMPT_VERSION = "cio_synth_v7_synthesis_evidence_2026-07-02"   # prompt stamp / audit
SYNTHESIS_VERSION_NUM = 7                                    # integer for the synthesis_version column (bump on prompt/method change)
# F2 (Stage 2b): committee agents emit tagged evidence + data_i_doubt (CIO audit 2026-07-01).
# Contract constants/helpers live in scripts/lib/cio_agent_contract.py (fleet parity).

# Local-lane control tokens (gemma/qwen '/no_think') are meaningless noise on cloud lanes — strip
# before any Grok/ChatGPT call; the local fallback keeps the original prompt (F3, CIO audit 2026-07-01).
_LOCAL_CONTROL_TOKENS = ("/no_think",)


def _strip_local_tokens(prompt: str) -> str:
    out = prompt
    for tok in _LOCAL_CONTROL_TOKENS:
        out = out.replace(tok, "")
    return out.lstrip()


def _synthesis_llm(prompt: str, max_tokens: int = 2000) -> str:
    """Declared multi-lane CIO synthesis (Gate-B.2): initial synthesis is Flash-first
    via llm_router task_type=cio_synthesis. Grok OAuth is an optional high-impact /
    soft-failure challenge lane (declared, not silent). Local gemma remains a
    declared fallback. CIO authority is gated by cio_legacy_watch_gate.py — this
    function produces LEGACY_CIO_REVIEW, never AUTHORITATIVE_CIO_ACTION.

    Provider provenance recorded on _llm._fallback_chain."""
    _llm._fallback_chain = []
    out = _llm(prompt, max_tokens=max_tokens, task_type="cio_synthesis", high_impact=False)
    if out and not str(out).startswith("LLM error") and not _is_refusal(out):
        _llm._fallback_chain = list(getattr(_llm, "_fallback_chain", []) or []) + [
            {"policy": "FLASH_FIRST_INITIAL_SYNTHESIS",
             "declared_lanes": ["grok-oauth", "local-gemma"]},
        ]
        return out
    try:
        import llm_lane
        if llm_lane.available("grok"):
            gout = llm_lane.generate(_strip_local_tokens(prompt), lane="grok", timeout=120)
            if gout and not str(gout).startswith("LLM error") and not _is_refusal(gout):
                _llm._last_model = "grok-3-mini"; _llm._last_provider = "grok-oauth"; _llm._last_cost = 0
                _llm._fallback_reason = "FLASH_SOFT_FAILURE_OR_EMPTY"
                _llm._fallback_chain = [{"attempted": "llm_router:cio_synthesis", "failed": True},
                                         {"used": "grok-oauth", "model": "grok-3-mini",
                                          "declared_lanes": ["grok-oauth", "local-gemma"]}]
                return gout
        # Gate-B.2: declared fallback lane (not silent)
        _llm._fallback_chain = [{"attempted": "grok-oauth", "failed": True},
                                 {"used": "local-gemma", "declared_lanes": ["grok-oauth", "local-gemma"]}]
    except Exception:
        pass
    _llm._last_model = getattr(_llm, "_last_model", OLLAMA_MODEL) or OLLAMA_MODEL
    return out if out else "LLM error: synthesis_failed"


# ── CIO dual-consensus: Grok + ChatGPT (both free OAuth) cross-check the final verdict (operator 2026-06-18).
# Disagreement → take the MORE CAUTIOUS verdict + lower confidence + flag, instead of trusting one model. ──
_DUAL_CHATGPT_CAP = int(os.getenv("CIO_DUAL_CHATGPT_CAP", "40"))  # bound ChatGPT codex latency per batch run
_dual_chatgpt_count = 0
# conservatism rank — lower = more cautious; on disagreement the more cautious verdict wins a buy decision.
_CONSERV = {"SELL": 0, "AVOID": 0, "IGNORE": 1, "TRIM": 2, "RESEARCH_MORE": 3, "NEUTRAL": 3,
            "HOLD": 4, "ADD_ON_PULLBACK": 5, "ADD": 6, "BUY": 7}


def _rec_from(raw):
    """Pull (recommendation, confidence) from an LLM synthesis response (JSON preferred, keyword fallback)."""
    try:
        j = json.loads(raw[raw.find('{'):raw.rfind('}') + 1])
        return (
            str(j.get("recommendation", "")).upper().strip(),
            normalize_agent_confidence(j.get("confidence")),
        )
    except Exception:
        up = (raw or "").upper()
        for r in ("AVOID", "SELL", "TRIM", "ADD_ON_PULLBACK", "BUY", "ADD", "HOLD", "RESEARCH_MORE", "NEUTRAL", "IGNORE"):
            if r in up:
                return r, 0.5
        return "", 0.0


def _synthesis_lanes(prompt: str, lanes=None, max_tokens: int = 2000, manual_trigger: bool = False):
    """Declared multi-lane CIO synthesis (Gate-B.2): Grok + ChatGPT OAuth cross-check
    with explicit reconciliation. On dual-lane failure, local gemma is a declared fallback
    lane (not silent). CIO authority gated by cio_legacy_watch_gate.py — output is
    LEGACY_CIO_REVIEW, never AUTHORITATIVE_CIO_ACTION.

    lanes: None → grok+chatgpt (cron default), ('grok',), ('chatgpt',), or both.
    manual_trigger: route via watchlist_cio_synthesis consumption gate (Manual mode safe)."""
    global _dual_chatgpt_count
    import llm_lane
    cloud_prompt = _strip_local_tokens(prompt)
    want = tuple(l for l in (lanes or ("grok", "chatgpt")) if l in ("grok", "chatgpt"))
    if not want:
        want = ("grok", "chatgpt")
    grok_raw = chatgpt_raw = None
    grok_rec = chatgpt_rec = None
    grok_conf = chatgpt_conf = 0.0
    pid = "watchlist_cio_synthesis" if manual_trigger else None
    task = "CIO synthesis"

    def _gen(lane: str, timeout: int):
        kw = dict(lane=lane, timeout=timeout)
        if pid:
            return llm_lane.generate(
                cloud_prompt, process_id=pid, task_summary=f"{task} {lane}",
                manual_trigger=True, **kw)
        return llm_lane.generate(cloud_prompt, **kw)

    if "grok" in want:
        try:
            if llm_lane.available("grok"):
                grok_raw = _gen("grok", 120)
                if _is_refusal(grok_raw):
                    grok_raw = None
                elif grok_raw and not str(grok_raw).startswith("LLM error"):
                    grok_rec, grok_conf = _rec_from(grok_raw)
        except Exception:
            pass
    if "chatgpt" in want:
        try:
            cap_ok = manual_trigger or _dual_chatgpt_count < _DUAL_CHATGPT_CAP
            if cap_ok and llm_lane.available("chatgpt"):
                if not manual_trigger:
                    _dual_chatgpt_count += 1
                chatgpt_raw = _gen("chatgpt", 180)
                if _is_refusal(chatgpt_raw):
                    chatgpt_raw = None
                elif chatgpt_raw and not str(chatgpt_raw).startswith("LLM error"):
                    chatgpt_rec, chatgpt_conf = _rec_from(chatgpt_raw)
        except Exception:
            pass
    meta = {"grok": ({"recommendation": grok_rec, "confidence": grok_conf} if grok_rec else None),
            "chatgpt": ({"recommendation": chatgpt_rec, "confidence": chatgpt_conf} if chatgpt_rec else None),
            "declared_lanes": want}  # Gate-B.2: explicit multi-lane declaration
    if grok_rec and chatgpt_rec:
        if grok_rec == chatgpt_rec:
            meta.update(agree=True, consensus=grok_rec, consensus_confidence=round(max(grok_conf, chatgpt_conf), 2))
            _llm._last_model = "grok+chatgpt(agree)"
            return grok_raw, meta
        cautious = grok_rec if _CONSERV.get(grok_rec, 9) <= _CONSERV.get(chatgpt_rec, 9) else chatgpt_rec
        meta.update(agree=False, consensus=cautious, consensus_confidence=round(min(grok_conf, chatgpt_conf) * 0.8, 2))
        _llm._last_model = "grok+chatgpt(disagree)"
        return (grok_raw if cautious == grok_rec else chatgpt_raw), meta
    if grok_rec:
        _llm._last_model = "grok-3-mini"
        meta.update(agree=None, consensus=grok_rec, consensus_confidence=round(grok_conf, 2))
        return grok_raw, meta
    if chatgpt_rec:
        _llm._last_model = "gpt-5.4"
        meta.update(agree=None, consensus=chatgpt_rec, consensus_confidence=round(chatgpt_conf, 2))
        return chatgpt_raw, meta
    if manual_trigger:
        meta.update(agree=None, consensus=None, consensus_confidence=None, error="oauth_lane_unavailable")
        return "LLM error: requested OAuth lane(s) unavailable or blocked", meta
    # Gate-B.2: declared fallback to local gemma (not silent)
    out = _llm(prompt, max_tokens=max_tokens, task_type="cio_synthesis", high_impact=False)
    _llm._last_model = getattr(_llm, "_last_model", OLLAMA_MODEL) or OLLAMA_MODEL
    meta.update(agree=None, consensus=None, consensus_confidence=None,
                fallback_lane="local-gemma", declared_fallback=True)
    return out, meta


def _synthesis_dual(prompt: str, max_tokens: int = 2000):
    """Gate-B.2: Declared multi-lane CIO research — grok+chatgpt OAuth dual consensus,
    local gemma as declared fallback. Output classifies LEGACY_CIO_REVIEW."""
    return _synthesis_lanes(prompt, lanes=None, max_tokens=max_tokens, manual_trigger=False)


def _get_context(conn, symbol: str) -> dict:
    """Build rich portfolio context for the agent. Returns dict + formatted string."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    holdings = json.loads((STATE_DIR / "holdings.json").read_text()) if (STATE_DIR / "holdings.json").exists() else {}
    pos = [h for h in holdings.get("holdings", []) if h.get("symbol") == symbol]
    enrichment = json.loads((STATE_DIR / "ticker_enrichment_cache.json").read_text()) if (STATE_DIR / "ticker_enrichment_cache.json").exists() else {}
    e = enrichment.get(symbol, {}) if isinstance(enrichment.get(symbol), dict) else {}

    # Strategy card from DB
    cur.execute("SELECT * FROM watchlist_strategy_cards WHERE symbol=%s", (symbol,))
    sc = cur.fetchone()

    # Recent prices from DB
    cur.execute("SELECT close_price, price_date FROM ticker_prices WHERE symbol=%s ORDER BY price_date DESC LIMIT 5", (symbol,))
    prices = cur.fetchall()

    # Risk data
    rm = json.loads((STATE_DIR / "risk_management.json").read_text()) if (STATE_DIR / "risk_management.json").exists() else {}
    stop_data = next((p for p in rm.get("positions", []) if p.get("symbol") == symbol), {})

    snapshot = {
        "symbol": symbol,
        "position": pos[0] if pos else None,
        "enrichment": {k: e.get(k) for k in ["rsi", "beta", "sector", "industry", "sma20_pct", "sma50_pct", "sma200_pct", "atr", "pe", "forward_pe", "company"]} if e else {},
        "strategy_card": dict(sc) if sc else None,
        "recent_prices": [{"price": float(p["close_price"]), "date": str(p["price_date"])} for p in prices] if prices else [],
        "stop": stop_data if stop_data else None,
    }

    ctx = f"Symbol: {symbol}\n"
    if pos:
        p = pos[0]
        ctx += f"Position: ${p.get('market_value', 0):,.0f}, {p.get('shares', 0):.1f} shares, {p.get('portfolio_pct', 0):.1f}% allocation, account: {p.get('account_name', '?')}\n"
    else:
        # F1 (CIO audit 2026-07-01): silence is not ground-truth — state non-ownership explicitly so
        # agents never infer a position from stale narratives/RAG (AZN: "22% position" vs 0 shares).
        ctx += "Position: NOT CURRENTLY HELD (0 shares in any account). Treat any source claiming this is an existing holding as stale.\n"
    if e:
        ctx += f"RSI: {e.get('rsi', '?')}, Beta: {e.get('beta', '?')}, Sector: {e.get('sector', '?')}, Industry: {e.get('industry', '?')}\n"
        ctx += f"SMA20: {e.get('sma20_pct', '?')}%, SMA50: {e.get('sma50_pct', '?')}%, SMA200: {e.get('sma200_pct', '?')}%\n"
        ctx += f"PE: {e.get('pe', '?')}, Forward PE: {e.get('forward_pe', '?')}, ATR: {e.get('atr', '?')}\n"
    if sc:
        ctx += f"Strategy: {sc.get('strategy_type', '?')}, Support: ${sc.get('support', '?')}, Resistance: ${sc.get('resistance', '?')}\n"
        ctx += f"Stop: ${sc.get('stop_loss', '?')}, Target: ${sc.get('target_price', '?')}, R:R: {sc.get('risk_reward', '?')}\n"
        ctx += f"Account fit: {sc.get('account_fit', '?')}\n"
    if stop_data:
        ctx += f"Active stop: ${stop_data.get('stop_price', '?')} (status: {stop_data.get('status', '?')})\n"
    if prices:
        price_strs = [f"${float(p['close_price']):.2f}" for p in prices[:5]]
        ctx += f"Recent prices: {', '.join(price_strs)}\n"

    # AV news sentiment (pre-scored — no LLM needed)
    try:
        cur2 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur2.execute("""SELECT title, sentiment, sentiment_score, relevance_score, source
                        FROM news_articles
                        WHERE symbol=%s AND source LIKE 'av:%%'
                        AND created_at > NOW() - INTERVAL '14 days'
                        ORDER BY relevance_score DESC LIMIT 5""", (symbol,))
        av_news = cur2.fetchall()
        cur2.close()
        if av_news:
            avg_sent = sum(float(n.get("sentiment_score", 0)) for n in av_news) / len(av_news)
            label = "positive" if avg_sent > 0.15 else "negative" if avg_sent < -0.15 else "neutral"
            ctx += f"News sentiment (AV, {len(av_news)} articles): {label} (score: {avg_sent:.3f})\n"
            for n in av_news[:3]:
                ctx += f"  [{n.get('source','?')}] {n.get('title','')[:60]} (rel:{n.get('relevance_score',0)}%)\n"
    except Exception:
        pass

    # AV fundamentals from fundamental_data
    try:
        cur3 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur3.execute("""SELECT metric_name, metric_value FROM fundamental_data
                        WHERE symbol=%s AND source='alpha_vantage'""", (symbol,))
        av_fund = {r["metric_name"]: r["metric_value"] for r in cur3.fetchall()}
        cur3.close()
        if av_fund:
            parts = []
            if av_fund.get("AnalystTargetPrice"):
                parts.append(f"Analyst target: ${float(av_fund['AnalystTargetPrice']):.2f}")
            if av_fund.get("52WeekHigh"):
                parts.append(f"52W high: ${float(av_fund['52WeekHigh']):.2f}")
            if av_fund.get("52WeekLow"):
                parts.append(f"52W low: ${float(av_fund['52WeekLow']):.2f}")
            if av_fund.get("DividendYield"):
                parts.append(f"Div yield: {float(av_fund['DividendYield'])*100:.2f}%")
            if parts:
                ctx += f"Alpha Vantage: {', '.join(parts)}\n"
    except Exception:
        pass

    # John's past decision preferences (agents learn from his notes)
    try:
        cur4 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur4.execute("""SELECT config FROM agent_intelligence_rules
                        WHERE rule_type='john_preferences' AND rule_key LIKE %s
                        ORDER BY updated_at DESC LIMIT 3""", (f"{symbol}_%",))
        pref_rows = cur4.fetchall()
        cur4.close()
        if pref_rows:
            ctx += "JOHN'S PAST DECISIONS (learn his reasoning):\n"
            for pr in pref_rows:
                cfg = pr.get("config", {})
                if isinstance(cfg, str):
                    cfg = json.loads(cfg)
                if cfg.get("lesson"):
                    ctx += f"  {cfg['lesson']}\n"
                if cfg.get("note"):
                    ctx += f"    John said: \"{cfg['note'][:100]}\"\n"
    except Exception:
        pass

    cur.close()
    # End the read txn — the caller fires a long LLM call next, and an open transaction
    # idling through it is killed at 120s (2026-07-04 idle-txn audit, #3 offender).
    try:
        conn.commit()
    except Exception:
        pass
    return {"text": ctx, "snapshot": snapshot}


# ── Agent prompts (narrative-grade) ──────────────────────────────────

def _get_other_agent_views(symbol: str, current_agent: str) -> str:
    """Pull what other agents already said about this symbol (for collaboration)."""
    try:
        import psycopg2.extras as _pxe
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=_pxe.RealDictCursor)
        cur.execute("""
            SELECT DISTINCT ON (agent) agent, recommendation, confidence, summary
            FROM watchlist_agent_results
            WHERE symbol = %s AND agent != %s AND created_at > NOW() - INTERVAL '7 days'
            ORDER BY agent, created_at DESC
        """, (symbol, current_agent))
        rows = cur.fetchall()
        # DO NOT close: _get_conn() returns a THREAD-LOCAL SHARED connection.
        # Closing it here killed the caller's live cursor mid-run
        # (psycopg2.InterfaceError: cursor already closed, 2026-07-20).
        if not rows:
            return ""
        lines = ["OTHER AGENT VIEWS (consider but form your own opinion):"]
        for r in rows:
            lines.append(f"  {r['agent']}: {r['recommendation']} (conf:{_fmt_confidence(r['confidence'])}) — {(r['summary'] or '')[:80]}")
        return "\n".join(lines) + "\n"
    except Exception:
        return ""


def _get_content_gap_warnings(agent_name: str) -> str:
    """Check if Iris flagged content gaps relevant to this agent."""
    try:
        import psycopg2.extras as _pxe
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=_pxe.RealDictCursor)
        cur.execute("""
            SELECT trigger_data FROM agent_event_queue
            WHERE event_type = 'CONTENT_GAP'
              AND agents_to_notify @> ARRAY[%s]::text[]
              AND created_at > NOW() - INTERVAL '7 days'
              AND status = 'pending'
            ORDER BY created_at DESC LIMIT 5
        """, (agent_name,))
        rows = cur.fetchall()
        # DO NOT close: _get_conn() returns a THREAD-LOCAL SHARED connection.
        # Closing it here killed the caller's live cursor mid-run
        # (psycopg2.InterfaceError: cursor already closed, 2026-07-20).
        if not rows:
            return ""
        lines = ["=== Content Gap Warnings (from Iris) ==="]
        for r in rows:
            td = r["trigger_data"] if isinstance(r["trigger_data"], dict) else json.loads(r["trigger_data"]) if r["trigger_data"] else {}
            lines.append(f"  {td.get('category','?')}: {td.get('message','thin content')}")
        lines.append("When content is thin, note lower confidence in your analysis.")
        lines.append("=== End Gap Warnings ===")
        return "\n".join(lines)
    except Exception:
        return ""


def _get_peer_agent_notes(symbol: str, current_agent: str) -> str:
    """Peer notes — check batch cache first (same-run peers), then DB for 30d history."""
    global _last_peer_agents
    _last_peer_agents = []

    # 1. Batch cache — peers from same process run (available immediately)
    cached = [p for p in _batch_results_cache.get(symbol, []) if p["agent"] != current_agent]
    if cached:
        _last_peer_agents = [p["agent"] for p in cached]
        lines = ["=== Peer Agent Notes ==="]
        for p in cached:
            lines.append(f"  {p['agent'].upper()} [this batch]: {p['recommendation']} (conf:{_fmt_confidence(p['confidence'])})")
            if p.get("summary"):
                lines.append(f"    {p['summary'][:150]}")
        lines.append("=== End Peer Notes ===")
        return "\n".join(lines)

    # 2. DB fallback — cross-run history (30 days)
    try:
        import psycopg2.extras as _pxe
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=_pxe.RealDictCursor)
        cur.execute("""
            SELECT DISTINCT ON (agent) agent, recommendation, confidence,
                   LEFT(summary, 200) as summary, created_at
            FROM watchlist_agent_results
            WHERE symbol = %s AND agent != %s AND created_at > NOW() - INTERVAL '30 days'
            ORDER BY agent, created_at DESC
        """, (symbol, current_agent))
        rows = cur.fetchall()
        # DO NOT close: _get_conn() returns a THREAD-LOCAL SHARED connection.
        # Closing it here killed the caller's live cursor mid-run
        # (psycopg2.InterfaceError: cursor already closed, 2026-07-20).
        if not rows:
            return ""
        _last_peer_agents = [r["agent"] for r in rows]
        lines = ["=== Peer Agent Notes ==="]
        for r in rows:
            dt = r["created_at"].strftime("%Y-%m-%d") if r.get("created_at") else "?"
            lines.append(f"  {r['agent'].upper()} [{dt}]: {r['recommendation']} (conf:{_fmt_confidence(r['confidence'])})")
            if r.get("summary"):
                lines.append(f"    {r['summary'][:150]}")
        lines.append("=== End Peer Notes ===")
        return "\n".join(lines)
    except Exception:
        return ""


def _get_recent_intel(symbol: str) -> str:
    """Pull recent scored intelligence + past outcome feedback for this symbol."""
    parts = []
    try:
        from intel_query import get_intel_summary, get_outcome_feedback
        summary = get_intel_summary(symbol=symbol, min_quality=40, max_chars=300, days=7)
        if summary:
            parts.append(summary)
        feedback = get_outcome_feedback(symbol, limit=3)
        if feedback:
            parts.append(feedback)
    except Exception:
        pass
    return "\n".join(parts) + "\n" if parts else ""


def _get_sentiment_social_context(symbol: str) -> str:
    """Pull news sentiment, social sentiment, and fused signals for a symbol."""
    parts = []
    try:
        import psycopg2.extras as _pxs
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=_pxs.RealDictCursor)

        # News sentiment: recent articles for this symbol
        cur.execute("""
            SELECT sentiment, sentiment_score, title, created_at
            FROM news_articles
            WHERE symbol = %s AND created_at > NOW() - INTERVAL '7 days'
            ORDER BY created_at DESC LIMIT 5
        """, [symbol])
        news = cur.fetchall()
        if news:
            scored = [n for n in news if n.get("sentiment_score") is not None]
            avg_score = sum(float(n["sentiment_score"]) for n in scored) / len(scored) if scored else None
            lines = ["=== News Sentiment (7d) ==="]
            lines.append(f"  Articles: {len(news)}" + (f" | Avg score: {avg_score:.2f}" if avg_score else " | Sentiment: not scored"))
            for n in news[:3]:
                sent = n.get("sentiment") or "unscored"
                score = f" ({float(n['sentiment_score']):.2f})" if n.get("sentiment_score") else ""
                lines.append(f"  - [{sent}{score}] {(n['title'] or '')[:80]}")
            lines.append("=== End News Sentiment ===")
            parts.append("\n".join(lines))

        # Social sentiment: recent posts mentioning this symbol
        cur.execute("""
            SELECT sentiment, sentiment_score, text, platform, post_date
            FROM social_posts
            WHERE symbols_mentioned::text ILIKE %s
              AND ingested_at > NOW() - INTERVAL '7 days'
            ORDER BY ingested_at DESC LIMIT 10
        """, [f'%{symbol}%'])
        social = cur.fetchall()
        if social:
            bullish = sum(1 for s in social if (s.get("sentiment") or "").lower() == "bullish")
            bearish = sum(1 for s in social if (s.get("sentiment") or "").lower() == "bearish")
            neutral = len(social) - bullish - bearish
            scored_social = [s for s in social if s.get("sentiment_score") is not None]
            avg_social = sum(float(s["sentiment_score"]) for s in scored_social) / len(scored_social) if scored_social else None
            lines = ["=== Social Sentiment (7d) ==="]
            lines.append(f"  Posts: {len(social)} | Bullish: {bullish} | Bearish: {bearish} | Neutral: {neutral}" +
                        (f" | Avg score: {avg_social:.2f}" if avg_social else ""))
            for s in social[:3]:
                plat = s.get("platform", "?")
                sent = s.get("sentiment") or "?"
                lines.append(f"  - [{plat}/{sent}] {(s['text'] or '')[:100]}")
            lines.append("=== End Social Sentiment ===")
            parts.append("\n".join(lines))

        # Fused signals (if available)
        cur.execute("""
            SELECT direction, confidence, fused_score, severity, created_at
            FROM fused_signals
            WHERE symbol = %s AND created_at > NOW() - INTERVAL '14 days'
            ORDER BY created_at DESC LIMIT 1
        """, [symbol])
        fused = cur.fetchone()
        if fused:
            parts.append(
                f"=== Fused Signal ===\n  Signal: {fused['direction']} | Confidence: {_fmt_confidence(fused['confidence'])}"
                f" | Score: {float(fused['fused_score'] or 0):.2f}\n=== End Fused Signal ==="
            )

        # DO NOT close: _get_conn() returns a THREAD-LOCAL SHARED connection.
        # Closing it here killed the caller's live cursor mid-run
        # (psycopg2.InterfaceError: cursor already closed, 2026-07-20).
    except Exception as e:
        print(f"  [sentiment] {symbol}: {e}")
    return "\n".join(parts) + "\n" if parts else ""


def _build_prompt(agent: str, symbol: str, context_text: str, note: str = "") -> str:
    # === SCAN INTELLIGENCE — primary context for scalp candidates ===
    scan_block = ""
    scalp_instructions = ""
    try:
        from agent_collab import get_scan_intelligence, get_scalp_agent_instructions
        _sc = _get_conn()
        scan_block = get_scan_intelligence(symbol, _sc)
        scalp_instructions = get_scalp_agent_instructions(symbol, _sc)
        _sc.close()
    except Exception:
        pass

    # Inject cross-agent views and intel
    other_views = _get_other_agent_views(symbol, agent)
    intel = _get_recent_intel(symbol)

    # Sentiment + social context
    sentiment_block = _get_sentiment_social_context(symbol)

    # Hermes intelligence — canonical composite score/rank + research + external-lane opinions
    hermes_block = ""
    try:
        from hermes_data_access import hermes_prompt_block
        hermes_block = hermes_prompt_block(symbol)
    except Exception:
        hermes_block = ""

    # RAG pre-context — prior intelligence from all source types
    rag_block = ""
    global _last_rag_sources
    _last_rag_sources = []
    try:
        from rag_retrieval import get_rag_context, format_rag_context_for_prompt
        rag_results = get_rag_context(symbol=symbol, agent_name=agent, limit=5)
        rag_block = format_rag_context_for_prompt(rag_results, symbol=symbol)
        _last_rag_sources = [{"source_type": r["source_type"], "title": r.get("title", "")[:60], "rag_score": r["rag_score"]} for r in rag_results]
        print(f"  [RAG] {symbol} ({agent}): {len(rag_results)} items" + (f", top score {rag_results[0]['rag_score']:.3f}" if rag_results else ""))
    except Exception as e:
        print(f"  [RAG] {symbol} ({agent}): FAILED — {e}")

    # Research advisories — persistent user research findings relevant to this analysis
    research_block = ""
    try:
        _rc = _get_conn()
        _rcur = _rc.cursor()
        _rcur.execute(
            "SELECT topic, latest_findings, research_count FROM user_research_topics "
            "WHERE status='active' AND latest_findings IS NOT NULL "
            "ORDER BY priority DESC, latest_finding_at DESC LIMIT 3"
        )
        _rtopics = _rcur.fetchall()
        _rcur.close()
        _rc.close()
        if _rtopics:
            _rlines = ["=== Active Research Advisories ==="]
            for _rt in _rtopics:
                _rlines.append(f"- {_rt[0]} (iter #{_rt[2]}): {(_rt[1] or '')[:200]}")
            _rlines.append("=== End Research Advisories ===")
            research_block = "\n".join(_rlines)
    except Exception:
        pass

    # Peer agent notes — what other agents concluded recently
    peer_notes = ""
    try:
        peer_notes = _get_peer_agent_notes(symbol, agent)
    except Exception:
        pass

    # Content gap warnings from Iris librarian
    gap_warnings = ""
    try:
        gap_warnings = _get_content_gap_warnings(agent)
    except Exception:
        pass

    # Confluence + pipeline context injection
    confluence_block = ""
    prospects_block = ""
    calibration_block = ""
    symbol_history_block = ""
    try:
        from agent_collab import get_confluence_context, get_prospects_context, get_calibration_context, get_symbol_history_context, get_strategy_performance_context
        _conn = _get_conn()
        confluence_block = get_confluence_context(symbol, _conn, profile='swing')
        prospects_block = get_prospects_context(symbol, _conn)
        calibration_block = get_calibration_context(agent, _conn)
        symbol_history_block = get_symbol_history_context(symbol, _conn)
        _conn.close()
    except Exception:
        pass

    # Session 24B: Strategy playbook context from YAML config loader
    strategy_playbook_block = ""
    try:
        from strategy_config_loader import get_strategy_prompt_context, load_strategy_config
        # Infer strategy from scan data or proposals
        _strat_id = None
        try:
            _sconn = _get_conn()
            _scur = _sconn.cursor()
            # Check proposals first
            _scur.execute("""
                SELECT strategy_id FROM paper_trade_proposals
                WHERE symbol=%s AND status='PENDING'
                ORDER BY created_at DESC LIMIT 1
            """, [symbol])
            _prow = _scur.fetchone()
            if _prow:
                _strat_id = _prow[0]
            else:
                # Fallback to scan-based inference
                _scur.execute("""
                    SELECT rvol, float_m, gap_pct FROM trade_ai_scans
                    WHERE symbol=%s ORDER BY scanned_at DESC LIMIT 1
                """, [symbol])
                _srow = _scur.fetchone()
                if _srow:
                    _rvol = float(_srow[0] or 0)
                    _flt = float(_srow[1] or 999)
                    _gap = float(_srow[2] or 0)
                    if _rvol >= 5 and _flt <= 100:
                        _strat_id = 'momentum_scalp'
                    elif _gap >= 5:
                        _strat_id = 'gap_and_go'
            _sconn.close()
        except Exception:
            pass

        if _strat_id:
            ctx = get_strategy_prompt_context(_strat_id)
            # Add agent-specific role
            try:
                cfg = load_strategy_config(_strat_id)
                role = (cfg.get('agent_responsibilities') or {}).get(agent)
                if role:
                    ctx += f"\nYour role ({agent}): {role if isinstance(role, str) else str(role)[:200]}"
            except Exception:
                pass
            strategy_playbook_block = f"\n{ctx}\n"

            # Inject strategy performance data so agents adjust confidence
            try:
                _pconn = _get_conn()
                _pcur = _pconn.cursor()
                _pcur.execute("""SELECT governance_state, paper_trades, closed_trades,
                                       win_rate, avg_r, profit_factor, expectancy_r
                                FROM paper_performance_governance
                                WHERE strategy_id=%s ORDER BY created_at DESC LIMIT 1""", [_strat_id])
                _prow = _pcur.fetchone()
                _pconn.close()
                if _prow and _prow[2]:
                    _wr = float(_prow[3] or 0) * 100
                    _pf = float(_prow[5] or 0)
                    _verdict = 'PERFORMING' if _pf >= 1.3 and _wr >= 55 else 'UNDERPERFORMING' if _pf < 0.8 else 'ACCUMULATING'
                    _conf_adj = 'Raise confidence +0.05-0.10' if _verdict == 'PERFORMING' else 'Lower confidence -0.10-0.15' if _verdict == 'UNDERPERFORMING' else 'Use 50% baseline'
                    strategy_playbook_block += (
                        f"\nSTRATEGY PERFORMANCE — {_strat_id}:\n"
                        f"  State: {_prow[0]} | Trades: {_prow[2]} | WR: {_wr:.0f}% | PF: {_pf:.2f} | Avg R: {float(_prow[4] or 0):.2f}\n"
                        f"  Verdict: {_verdict} — {_conf_adj}\n"
                    )
                elif _strat_id:
                    strategy_playbook_block += (
                        f"\nSTRATEGY PERFORMANCE — {_strat_id}:\n"
                        f"  UNVALIDATED — no closed paper trades yet. Use 50% confidence baseline.\n"
                    )
            except Exception:
                pass
    except Exception:
        pass

    context_block = f"""{scan_block}
{context_text}
{hermes_block}
{rag_block}
{research_block}
{peer_notes}
{gap_warnings}
{confluence_block}
{prospects_block}
{symbol_history_block}
{calibration_block}
{strategy_playbook_block}
{scalp_instructions}
{sentiment_block}{other_views}{intel}"""
    base_instruction = build_base_json_instruction(
        context=context_block,
        include_global_rules=True,
        global_rules=GLOBAL_RULES_G1_G10,
    )
    if note:
        base_instruction += f"Additional note: {note}\n"

    prompts = {
        "maria": f"""/no_think You are Maria, a senior research analyst covering equities. Your job is to provide a thorough fundamental and catalyst analysis.

Analyze {symbol}. Cover:
1. Business quality and competitive position
2. Valuation relative to peers and history
3. Upcoming catalysts (earnings, product launches, regulation)
4. News sentiment and analyst consensus
5. Key risks to the thesis

{base_instruction}""",

        "steph": f"""/no_think You are Steph, the income guardian for John's ~$1.2M multi-account portfolio. Your question: "Does this position support the $55K income target? Does the allocation make sense across all four accounts?"

INCOME ANALYSIS FRAMEWORK:
- Portfolio income target: $55,000/yr from investments
- SSDI income: $45,600/yr (stable — do NOT count toward portfolio income target)
- Income gap: $55,000 - current_annual_portfolio_income
- FLAG if: gap > $20,000 → recommend income-building action
- FLAG if: single position > 25% of total portfolio income → concentration risk
- FLAG if: single position > 15% of total portfolio value → hard cap breach

ACCOUNT RULES (non-negotiable):
- Roth IRA: growth focus ONLY (SCHG, SCHD) — no covered calls — tax-free growth
- Rollover IRA: income + growth + Roth conversion candidates
- Taxable: qualified dividends ONLY — no BDC distributions (ordinary income = SSDI MAGI risk)
- 401k (until 2027): constrained to 15 Omnicom plan funds only

NEVER AUTO-ROTATE (income protection — Rule G2):
  dividend_growth_compounder, high_yield_income_bdc, tactical_income,
  reit_income, bond_income, retirement_planning, disability_retirement_planning
  If rotation needed: flag INCOME_CRITICAL, escalate to Alex.

Review {symbol}. Cover:
1. Current allocation vs target — overweight/underweight? Flag if >15%.
2. Account location — is it in the right account per rules above?
3. Income contribution — how much does it add to the $55K target?
4. Rebalance recommendation — add, hold, trim, or rotate?
5. Proposal format: [action] SYMBOL in ACCOUNT: shares → target. Income impact: $+/-N/yr. SSDI impact. IRMAA risk.

{base_instruction}""",

        "risk_agent": f"""/no_think You are the Risk Analyst for John's portfolio. Your question: "Is the price action supportive of entry/exit? Is the stop set appropriately? Is the position protected?"

RISK RULES:
- Stop placement: new position = entry - (2 × ATR). Min 5%, max 15% distance.
- 401k mutual funds: no stops (cannot be placed) → mental stop only.
- RSI >75 + no catalyst: flag OVERBOUGHT → TRIM candidate.
- RSI <25 + thesis intact: flag OVERSOLD → ADD candidate.
- Portfolio heat >5%: do not add new positions. >8%: urgent stop-tightening.
- Target: ≥80% of portfolio value protected (has defined stop).

Assess {symbol}. Cover:
1. Technical trend — above/below key moving averages (SMA20/50/200)
2. RSI and momentum signals (flag extremes per rules above)
3. Support/resistance levels and current price position
4. Stop loss recommendation with reasoning (use ATR rule)
5. Position sizing guidance based on volatility (ATR, beta)
6. Heat contribution — how much risk does this position add?

{base_instruction}""",

        "tax_agent": f"""/no_think You are the Tax Optimizer for John's portfolio. Your question: "What is the tax-optimal execution path? Are there harvest opportunities? Does this affect SSDI/IRMAA/Medicaid?"

JOHN'S TAX SITUATION:
- Filing status: MFS (Married Filing Separately) — lived apart from spouse
- SSDI income: $45,600/yr — counts toward MAGI but NOT SGA (unearned)
- Current MAGI room: ~$66,883 (verified April 2026)
- IRMAA threshold (MFS): $103,000 — NEVER breach without explicit IRMAA warning
- 22% bracket ceiling: $94,300 (MFS)
- Roth conversions done 2026: $35,000
- Golden Window: ages 68.5–73 (2036–2040) — convert aggressively then
- Disability exemption: no 10% early withdrawal penalty
- LTD disability insurance: pretax employer policy — ordinary income, NOT earned income

TAX HARVEST RULES:
- Worthless securities: current_value = 0, cost_basis > 0 → contact Fidelity 1-800-343-3548 for disposal form before Dec 31
- Loss harvest: unrealized_loss > $500, holding_period > 30 days, no wash sale in 30-day window
- Prioritize: highest loss first, long-term losses before short-term
- Roth conversion: available room = $94,300 - current_MAGI. Convert FROM Rollover IRA only.
- IRA distribution > $50,000: Medicaid 5-year lookback warning required
- Capital gains in taxable: estimate MAGI impact before proposing

Review {symbol}. Cover:
1. Optimal account location (taxable = qualified divs only, no BDC; Roth = growth; IRA = income + conversion candidates)
2. Tax-loss harvesting opportunities with wash sale check
3. MAGI impact of any recommended action
4. IRMAA risk assessment (will this push MAGI > $103K?)
5. Roth conversion candidacy (if IRA position)

Output MUST include: tax_impact, magi_impact, irmaa_risk (bool), bracket_impact, deadline if applicable.

{base_instruction}""",

        "full_chain": f"""/no_think You are a portfolio investment committee synthesizing multiple analyst perspectives.

Comprehensive review of {symbol}. Cover:
1. Fundamental case (bull/bear/base)
2. Technical setup and risk levels
3. Allocation and account fit
4. Key risks and mitigants
5. Final committee recommendation with confidence

{base_instruction}""",
    }
    return prompts.get(agent, prompts["maria"])


def _run_maria_two_pass(symbol: str, context_text: str, note: str = "") -> str:
    """Two-pass Maria analysis for higher confidence.

    Pass 1 (local): News sentiment + catalyst extraction
    Pass 2 (local, Grok fallback if low conf): Fundamentals given Pass 1 context + RAG + intel
    Final: Combine both into standard Maria JSON output
    """
    # ── Inject RAG, intel, peer notes for Pass 2 ──
    global _last_rag_sources, _last_peer_agents
    _last_rag_sources = []
    _last_peer_agents = []
    rag_block = ""
    try:
        from rag_retrieval import get_rag_context, format_rag_context_for_prompt
        rag_results = get_rag_context(symbol=symbol, agent_name="maria", limit=5)
        rag_block = format_rag_context_for_prompt(rag_results, symbol=symbol)
        _last_rag_sources = [{"source_type": r["source_type"], "title": r.get("title", "")[:60], "rag_score": r["rag_score"]} for r in rag_results]
        print(f"  [RAG] {symbol} (maria-2pass): {len(rag_results)} items" + (f", top score {rag_results[0]['rag_score']:.3f}" if rag_results else ""))
    except Exception as e:
        print(f"  [RAG] {symbol} (maria-2pass): FAILED — {e}")

    intel = ""
    try:
        intel = _get_recent_intel(symbol)
    except Exception:
        pass

    peer_notes = ""
    try:
        peer_notes = _get_peer_agent_notes(symbol, "maria")
    except Exception:
        pass

    # ── Pass 1: News & Sentiment ──
    pass1_prompt = f"""/no_think You are Maria, a senior research analyst. Your question: "Is there new information that changes the investment thesis for {symbol}?"

CATALYST CRITERIA — mark catalyst_present=true if ANY of:
- Earnings beat >10% + guidance raised
- SEC Form 4: insider purchase >$500K (not options exercise)
- M&A accretive announcement
- Analyst upgrade with target >15% above current price
- FDA approval or positive Phase 3 trial
- Material positive 8-K

BEARISH CATALYST — mark sentiment="negative" if ANY of:
- Insider selling >$1M within 30 days (Form 4)
- EPS miss >10% + guidance cut
- Analyst target downgrade below current price
- Payout ratio >100% for income positions
- SEC investigation or material weakness disclosure

Context (last 7 days):
{context_text[:2000]}

Respond in JSON only:
{{"sentiment": "positive" or "neutral" or "negative",
  "catalyst_present": true or false,
  "catalyst": "string describing the main catalyst, or null if none",
  "confidence": 0-100,
  "key_headlines": ["headline 1", "headline 2", "headline 3 max"]}}"""

    pass1_raw = _llm(pass1_prompt, max_tokens=400, task_type="agent_narrative")
    pass1_model = getattr(_llm, '_last_model', 'unknown')

    # Parse pass 1
    pass1_data = {"sentiment": "neutral", "catalyst": None, "confidence": 50, "key_headlines": []}
    if pass1_raw and not pass1_raw.startswith("LLM error"):
        try:
            # Extract JSON from response
            import re
            json_match = re.search(r'\{[^{}]*\}', pass1_raw, re.DOTALL)
            if json_match:
                pass1_data = json.loads(json_match.group())
        except Exception:
            pass
    print(f"  [maria-p1] {symbol}: sentiment={pass1_data.get('sentiment')} catalyst={str(pass1_data.get('catalyst',''))[:40]} conf={pass1_data.get('confidence')} model={pass1_model}")

    # ── Pass 2: Fundamentals given news context ──
    pass2_prompt = f"""/no_think You are Maria, a senior research analyst. Given this news summary for {symbol}:
Sentiment: {pass1_data.get('sentiment', 'neutral')}
Catalyst: {pass1_data.get('catalyst', 'none identified')}
Catalyst present: {pass1_data.get('catalyst_present', False)}
News confidence: {pass1_data.get('confidence', 50)}%
Headlines: {', '.join(pass1_data.get('key_headlines', [])[:3])}

DECISION RULES:
BUY (ALL must be true): catalyst_present=true, PE below sector avg OR growth justifies premium, analyst target >10% above price, no negative SEC in 30d.
SELL/TRIM: bearish catalyst confirmed OR RSI>75 with no new catalyst. NEVER SELL income-critical positions unless Rule G2 breach.
HOLD: mixed signals, confidence <55%, or no new material catalyst in 7 days.
RESEARCH_MORE (use sparingly): conflicting signals AND confidence <45%.

Fundamentals for {symbol}:
{context_text[:1500]}
{rag_block}
{peer_notes}
{intel}
{note or ''}

Respond in JSON only:
{{"thesis_intact": "yes" or "no" or "maybe",
  "fundamental_signal": "BUY" or "HOLD" or "SELL" or "TRIM" or "RESEARCH_MORE",
  "confidence": 0-100,
  "reasoning": "1-2 sentence reasoning",
  "income_critical": false,
  "evidence": [{{"tag": "fact", "text": "key fact"}}, {{"tag": "risk", "text": "key risk"}}],
  "data_i_doubt": "none or what you distrust"}}"""

    pass2_raw = _llm(pass2_prompt, max_tokens=400, task_type="agent_narrative", high_impact=False)
    pass2_model = getattr(_llm, '_last_model', 'unknown')

    pass2_data = {"thesis_intact": "maybe", "fundamental_signal": "HOLD", "confidence": 50, "reasoning": ""}
    if pass2_raw and not pass2_raw.startswith("LLM error"):
        try:
            import re
            json_match = re.search(r'\{[^{}]*\}', pass2_raw, re.DOTALL)
            if json_match:
                pass2_data = merge_structured_into_result(json.loads(json_match.group()))
        except Exception:
            pass
    print(f"  [maria-p2] {symbol}: signal={pass2_data.get('fundamental_signal')} thesis={pass2_data.get('thesis_intact')} conf={pass2_data.get('confidence')} model={pass2_model}")

    # ── Combine into standard Maria output ──
    news_conf = pass1_data.get("confidence", 50)
    fund_conf = pass2_data.get("confidence", 50)
    combined_conf = round((news_conf * 0.4 + fund_conf * 0.6) / 100, 2)  # weight fundamentals more

    signal = pass2_data.get("fundamental_signal", "HOLD")
    sentiment = pass1_data.get("sentiment", "neutral")
    # Adjust recommendation if news and fundamentals disagree
    if signal == "BUY" and sentiment == "negative":
        recommendation = "RESEARCH_MORE"
    elif signal == "SELL" and sentiment == "positive":
        recommendation = "RESEARCH_MORE"
    else:
        rec_map = {"BUY": "BUY", "HOLD": "HOLD", "SELL": "AVOID"}
        recommendation = rec_map.get(signal, "HOLD")

    catalyst = pass1_data.get("catalyst") or "No catalyst identified"
    reasoning = pass2_data.get("reasoning", "")
    headlines = pass1_data.get("key_headlines", [])

    _maria_evidence = _normalize_evidence(pass2_data.get("evidence"))
    if catalyst and catalyst != "No catalyst identified":
        _maria_evidence.insert(0, {"tag": "fact", "text": f"Catalyst: {catalyst}"})
    for h in (headlines or [])[:2]:
        _maria_evidence.append({"tag": "fact", "text": f"Headline: {h}"})
    _maria_evidence = _maria_evidence[:5]
    _maria_doubt = _normalize_data_i_doubt(pass2_data.get("data_i_doubt"))

    combined = json.dumps({
        "summary": f"{symbol}: {sentiment} sentiment, {signal} signal. {catalyst}. {reasoning}",
        "full_narrative": f"## News Analysis (Pass 1)\nSentiment: {sentiment} ({news_conf}% conf)\nCatalyst: {catalyst}\nHeadlines: {'; '.join(headlines)}\n\n## Fundamental Analysis (Pass 2)\nSignal: {signal} ({fund_conf}% conf)\nThesis intact: {pass2_data.get('thesis_intact', '?')}\nReasoning: {reasoning}\n\nModels: P1={pass1_model}, P2={pass2_model}",
        "recommendation": recommendation,
        "confidence": combined_conf,
        "evidence": _maria_evidence,
        "data_i_doubt": _maria_doubt,
        "reason_codes": [f"news_{sentiment}", f"fund_{signal.lower()}", f"thesis_{pass2_data.get('thesis_intact', 'unknown')}"],
        "next_action": f"{'Review catalyst timing' if catalyst and catalyst != 'No catalyst identified' else 'Monitor for new developments'}",
    })
    print(f"  [maria-final] {symbol}: {recommendation} conf={combined_conf:.0%} (news={news_conf}% fund={fund_conf}%)")
    return combined


def _run_maria_one_pass(symbol: str, context_text: str, note: str = "") -> str:
    """Single FAST governed call combining news + fundamentals (call-count contract).

    Replaces the historical two-pass Maria path for production worker jobs so each
    Maria job makes exactly one provider request via task_type=agent_narrative
    → watchlist_maria_flash_narrative. Does not call _run_maria_two_pass.
    """
    global _last_rag_sources, _last_peer_agents
    _last_rag_sources = []
    _last_peer_agents = []
    rag_block = ""
    try:
        from rag_retrieval import get_rag_context, format_rag_context_for_prompt
        rag_results = get_rag_context(symbol=symbol, agent_name="maria", limit=5)
        rag_block = format_rag_context_for_prompt(rag_results, symbol=symbol)
        _last_rag_sources = [
            {"source_type": r["source_type"], "title": r.get("title", "")[:60], "rag_score": r["rag_score"]}
            for r in rag_results
        ]
        print(
            f"  [RAG] {symbol} (maria-1pass): {len(rag_results)} items"
            + (f", top score {rag_results[0]['rag_score']:.3f}" if rag_results else "")
        )
    except Exception as e:
        print(f"  [RAG] {symbol} (maria-1pass): FAILED — {e}")

    intel = ""
    try:
        intel = _get_recent_intel(symbol)
    except Exception:
        pass
    peer_notes = ""
    try:
        peer_notes = _get_peer_agent_notes(symbol, "maria")
    except Exception:
        pass

    prompt = f"""/no_think You are Maria, a senior research analyst. Analyze {symbol} in ONE response.

Combine news/catalyst review AND fundamentals into a single recommendation.

CATALYST CRITERIA (catalyst_present=true if ANY):
- Earnings beat >10% + guidance raised; SEC Form 4 insider buy >$500K;
- M&A accretive; analyst upgrade target >15% above price; FDA/Phase 3 positive; material positive 8-K.

BEARISH (sentiment=negative if ANY):
- Insider selling >$1M/30d; EPS miss >10% + guidance cut; target below price;
- Payout >100% income; SEC investigation / material weakness.

DECISION RULES:
BUY: catalyst_present=true AND (PE reasonable OR growth justifies) AND target >10% upside AND no negative SEC 30d.
SELL/TRIM: bearish catalyst OR RSI>75 with no catalyst. Never SELL income-critical unless Rule G2.
HOLD: mixed signals, conf <55%, or no material catalyst in 7d.
RESEARCH_MORE: conflicting signals AND conf <45%.

Context (7d):
{context_text[:2000]}
Fundamentals / notes:
{context_text[:1500]}
{rag_block}
{peer_notes}
{intel}
{note or ''}

Respond in JSON only:
{{"sentiment":"positive"|"neutral"|"negative",
  "catalyst_present": true|false,
  "catalyst": "string or null",
  "key_headlines": ["h1","h2","h3 max"],
  "thesis_intact":"yes"|"no"|"maybe",
  "recommendation":"BUY"|"HOLD"|"SELL"|"TRIM"|"RESEARCH_MORE"|"AVOID",
  "confidence": 0-100,
  "summary":"1-2 sentence summary",
  "full_narrative":"short narrative",
  "reasoning":"1-2 sentence reasoning",
  "income_critical": false,
  "evidence":[{{"tag":"fact","text":"..."}},{{"tag":"risk","text":"..."}}],
  "data_i_doubt":"none or what you distrust",
  "reason_codes":["code1","code2"],
  "next_action":"string"}}"""

    # Exactly one LLM invocation — no second pass
    raw = _llm(prompt, max_tokens=600, task_type="agent_narrative", high_impact=False)
    model = getattr(_llm, "_last_model", "unknown")
    print(f"  [maria-1pass] {symbol}: model={model}")

    if not raw or str(raw).startswith("LLM error"):
        return raw or "LLM error: empty"

    data = {}
    try:
        import re as _re
        m = _re.search(r"\{[\s\S]*\}", raw)
        if m:
            data = merge_structured_into_result(json.loads(m.group()))
    except Exception:
        data = {}

    rec = str(data.get("recommendation") or data.get("fundamental_signal") or "HOLD").upper()
    rec_map = {"BUY": "BUY", "HOLD": "HOLD", "SELL": "AVOID", "TRIM": "TRIM",
               "RESEARCH_MORE": "RESEARCH_MORE", "AVOID": "AVOID"}
    recommendation = rec_map.get(rec, "HOLD")
    conf_raw = data.get("confidence", 50)
    try:
        conf = float(conf_raw)
        conf = conf / 100.0 if conf > 1.0 else conf
    except (TypeError, ValueError):
        conf = 0.5

    sentiment = str(data.get("sentiment") or "neutral")
    catalyst = data.get("catalyst") or "No catalyst identified"
    evidence = _normalize_evidence(data.get("evidence"))
    if catalyst and catalyst != "No catalyst identified":
        evidence.insert(0, {"tag": "fact", "text": f"Catalyst: {catalyst}"})
    evidence = evidence[:5]
    doubt = _normalize_data_i_doubt(data.get("data_i_doubt"))
    summary = data.get("summary") or f"{symbol}: {sentiment}, {recommendation}. {catalyst}"
    narrative = data.get("full_narrative") or data.get("reasoning") or summary
    codes = data.get("reason_codes") or [f"news_{sentiment}", f"rec_{recommendation.lower()}"]
    next_action = data.get("next_action") or (
        "Review catalyst timing" if catalyst != "No catalyst identified" else "Monitor for new developments"
    )

    out = json.dumps({
        "summary": summary,
        "full_narrative": f"## Maria one-pass\n{narrative}\n\nModel: {model}",
        "recommendation": recommendation,
        "confidence": conf,
        "evidence": evidence,
        "data_i_doubt": doubt,
        "reason_codes": codes if isinstance(codes, list) else [str(codes)],
        "next_action": next_action,
        "maria_call_count_contract": 1,
    })
    print(f"  [maria-1pass-final] {symbol}: {recommendation} conf={conf:.0%}")
    return out


# Backward-compatible aliases (tests + internal callers)
_normalize_evidence = normalize_evidence
_normalize_data_i_doubt = normalize_data_i_doubt
_format_evidence_for_synthesis = format_evidence_for_synthesis
_parse_result = parse_agent_result


def _update_maturity(conn, symbol: str, agent: str, status: str):
    """Update the analysis maturity record for a symbol after an agent completes/fails."""
    mat_col = AGENT_TO_MATURITY.get(agent, agent) + "_status"
    valid_cols = ["maria_status", "steph_status", "risk_status", "tax_status", "full_chain_status"]
    if mat_col not in valid_cols:
        return

    cur = conn.cursor()

    # Update agent-specific status
    cur.execute(f"""
        UPDATE watchlist_analysis_maturity
        SET {mat_col} = %s, updated_at = now()
        WHERE symbol = %s
    """, (status, symbol))

    if status == "completed":
        # Update completed_agents array and last_completed
        cur.execute("""
            UPDATE watchlist_analysis_maturity
            SET completed_agents = array_append(
                    COALESCE(array_remove(completed_agents, %s), ARRAY[]::text[]),
                    %s
                ),
                last_completed_agent = %s,
                last_completed_at = now(),
                updated_at = now()
            WHERE symbol = %s
        """, (AGENT_TO_MATURITY.get(agent, agent), AGENT_TO_MATURITY.get(agent, agent), agent, symbol))

    # Recompute stage
    import psycopg2.extras
    rcur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    rcur.execute("SELECT * FROM watchlist_analysis_maturity WHERE symbol = %s", (symbol,))
    mat = rcur.fetchone()
    if not mat:
        rcur.close()
        cur.close()
        return

    required = mat.get("required_agents") or []
    completed = mat.get("completed_agents") or []
    missing = [a for a in required if a not in completed]

    # Determine new stage
    if mat.get("final_synthesis_status") == "completed":
        stage = "final_synthesis_complete"
    elif mat.get("full_chain_status") == "completed":
        stage = "full_chain_complete"
    elif required and not missing:
        stage = "specialist_review_complete"
    elif completed:
        stage = "specialist_review_partial"
    elif mat.get("strategy_card_ready"):
        stage = "strategy_card_ready"
    else:
        stage = "raw_data_only"

    # Check for any failed
    agent_statuses = [mat.get(f"{a}_status", "not_required") for a in ["maria", "steph", "risk", "tax", "full_chain"]]
    if "failed" in agent_statuses and not completed:
        stage = "failed"

    needs_iter = bool(missing) or stage in ("raw_data_only", "strategy_card_ready", "routed", "failed")

    cur.execute("""
        UPDATE watchlist_analysis_maturity
        SET analysis_stage = %s,
            missing_agents = %s,
            needs_iteration = %s,
            iteration_reason = %s,
            updated_at = now()
        WHERE symbol = %s
    """, (stage, missing if missing else None,
          needs_iter,
          f"Missing: {', '.join(missing)}" if missing else None,
          symbol))

    rcur.close()
    cur.close()


def _apply_escalation_policy(conn, symbol: str) -> list:
    """Look up strategy type and set required agents in maturity table. Returns required agents."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get strategy type from strategy card
    cur.execute("SELECT strategy_type FROM watchlist_strategy_cards WHERE symbol=%s", (symbol,))
    sc = cur.fetchone()
    strategy_type = sc["strategy_type"] if sc else "core_holding"

    # Get policy
    cur.execute("SELECT required_agents, optional_agents FROM watchlist_escalation_policies WHERE strategy_type=%s", (strategy_type,))
    policy = cur.fetchone()
    required = policy["required_agents"] if policy else ["steph", "risk"]
    optional = policy["optional_agents"] if policy else ["maria"]

    # Ensure maturity row exists
    cur.execute("""
        INSERT INTO watchlist_analysis_maturity (symbol, escalation_policy, required_agents, analysis_stage, raw_data_ready, strategy_card_ready)
        VALUES (%s, %s, %s, 'routed', TRUE, %s)
        ON CONFLICT (symbol) DO UPDATE SET
            escalation_policy = EXCLUDED.escalation_policy,
            required_agents = EXCLUDED.required_agents,
            analysis_stage = 'routed',
            updated_at = now()
    """, (symbol, strategy_type, required, sc is not None))

    # Set required agent statuses
    for agent in required:
        col = agent + "_status"
        if col in ["maria_status", "steph_status", "risk_status", "tax_status", "full_chain_status"]:
            cur.execute(f"""
                UPDATE watchlist_analysis_maturity
                SET {col} = CASE WHEN {col} IN ('not_required', 'required') THEN 'required' ELSE {col} END
                WHERE symbol = %s
            """, (symbol,))

    conn.commit()
    cur.close()
    return list(required)


def _check_synthesis_ready(conn, symbol: str) -> bool:
    """Check if all required agents completed and synthesis should be triggered."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT required_agents, completed_agents, final_synthesis_status FROM watchlist_analysis_maturity WHERE symbol=%s", (symbol,))
    mat = cur.fetchone()
    cur.close()
    if not mat:
        return False
    required = mat.get("required_agents") or []
    completed = mat.get("completed_agents") or []
    if mat.get("final_synthesis_status") in ("completed", "processing", "queued"):
        return False
    return all(a in completed for a in required)


# ── Strategy-aware synthesis weighting ───────────────────────────────

STRATEGY_WEIGHTS = {
    "income": {
        "allocation": 0.35, "account_location": 0.25,
        "fundamentals": 0.20, "technicals": 0.10, "alerts": 0.10,
        "rules": [
            "RSI alone is NOT a reason to TRIM an income/dividend ETF",
            "High RSI on income ETF = wait for pullback to ADD, not SELL",
            "TRIM only if: allocation exceeds target by >3%, thesis deteriorated, or better replacement exists",
            "Underweight = HOLD or ADD_ON_PULLBACK",
            "Overweight = HOLD unless >15% portfolio weight",
        ],
    },
    "defense_thesis": {
        "allocation": 0.25, "account_location": 0.15,
        "fundamentals": 0.25, "technicals": 0.15, "alerts": 0.20,
        "rules": [
            "Evaluate as basket exposure, not individual picks",
            "Geopolitical thesis and valuation dominate",
            "Position sizing based on total defense allocation",
        ],
    },
    "speculative_growth": {
        "allocation": 0.15, "account_location": 0.10,
        "fundamentals": 0.20, "technicals": 0.30, "alerts": 0.25,
        "rules": [
            "Catalyst + risk control required",
            "Technicals heavily influence entry/exit timing",
            "Position size should be limited (max 3-5% portfolio)",
        ],
    },
    "growth_etf": {
        "allocation": 0.30, "account_location": 0.20,
        "fundamentals": 0.25, "technicals": 0.15, "alerts": 0.10,
        "rules": [
            "Overbought = do not chase, wait for pullback",
            "TRIM only if allocation too high or thesis weakens",
            "Use trend + valuation + overlap analysis",
        ],
    },
    "core_holding": {
        "allocation": 0.35, "account_location": 0.20,
        "fundamentals": 0.25, "technicals": 0.10, "alerts": 0.10,
        "rules": [
            "Allocation and thesis dominate",
            "Technicals are timing signals only, NOT recommendation drivers",
            "TRIM only for rebalancing, not technical signals",
        ],
    },
    "swing_trade": {
        "allocation": 0.10, "account_location": 0.05,
        "fundamentals": 0.15, "technicals": 0.40, "alerts": 0.30,
        "rules": [
            "Technicals dominate entry/exit",
            "Entry/stop/target required before position",
            "Time-bound thesis — exit if thesis expires",
        ],
    },
}


def _get_portfolio_context(conn, symbol: str) -> dict:
    """Get portfolio position context for synthesis weighting."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    holdings = json.loads((STATE_DIR / "holdings.json").read_text()) if (STATE_DIR / "holdings.json").exists() else {}
    acct_summaries = holdings.get("account_summaries", {})
    total_portfolio = sum(info.get("total_value", 0) for info in acct_summaries.values())

    sym_holdings = [h for h in holdings.get("holdings", []) if h.get("symbol") == symbol]
    total_shares = sum(float(h.get("shares", 0) or 0) for h in sym_holdings)
    total_mv = sum(float(h.get("market_value", 0) or 0) for h in sym_holdings)
    weight = round(total_mv / total_portfolio * 100, 2) if total_portfolio > 0 else 0

    accounts = []
    for h in sym_holdings:
        aid = h.get("account_id") or h.get("account", "unknown")
        acct_type = "Roth IRA" if "roth" in aid.lower() else "Rollover IRA" if "rollover" in aid.lower() or "ira" in aid.lower() else "401k" if "401k" in aid.lower() else "Taxable"
        accounts.append({"id": aid, "type": acct_type, "shares": float(h.get("shares", 0) or 0), "value": float(h.get("market_value", 0) or 0)})

    # Strategy type
    cur.execute("SELECT strategy_type FROM watchlist_strategy_cards WHERE symbol=%s", (symbol,))
    sc = cur.fetchone()
    strategy_type = sc["strategy_type"] if sc else "core_holding"

    # Recent alerts (last 24h)
    cur.execute("""
        SELECT alert_type, severity, data_quality_status, created_at
        FROM alert_events WHERE symbol = %s AND created_at > NOW() - INTERVAL '24 hours'
        ORDER BY created_at DESC LIMIT 10
    """, (symbol,))
    recent_alerts = cur.fetchall()

    # Data quality issues
    cur.execute("""
        SELECT COUNT(*) as cnt FROM alert_events
        WHERE symbol = %s AND data_quality_status NOT IN ('valid', 'unknown')
        AND created_at > NOW() - INTERVAL '7 days'
    """, (symbol,))
    dq_issues = cur.fetchone()["cnt"]

    # Income profile
    cur2 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur2.execute("SELECT * FROM income_asset_profiles WHERE symbol=%s", (symbol,))
    income_profile = cur2.fetchone()

    # Income goals
    cur2.execute("SELECT * FROM portfolio_income_goals LIMIT 1")
    income_goals = cur2.fetchone()

    # Layer allocation
    cur2.execute("""
        SELECT layer_id, SUM(annual_income) as layer_income
        FROM income_asset_profiles GROUP BY layer_id
    """)
    layer_income = {r["layer_id"]: float(r["layer_income"] or 0) for r in cur2.fetchall()}

    # Total portfolio income
    cur2.execute("SELECT SUM(annual_income) as total FROM income_asset_profiles")
    total_income = float((cur2.fetchone() or {}).get("total", 0) or 0)

    cur2.close()
    cur.close()

    income_ctx = {}
    if income_profile:
        ip = income_profile
        income_ctx = {
            "layer": ip.get("layer_id"),
            "annual_income": float(ip.get("annual_income", 0) or 0),
            "yield_pct": float(ip.get("dividend_yield_pct", 0) or 0),
            "forward_yield_pct": float(ip.get("forward_yield_pct", 0) or 0),
            "yield_on_cost_pct": float(ip.get("yield_on_cost_pct", 0) or 0) if ip.get("yield_on_cost_pct") else None,
            "dividend_growth_5yr": float(ip.get("dividend_growth_5yr_pct", 0) or 0) if ip.get("dividend_growth_5yr_pct") else None,
            "payout_safety": ip.get("payout_safety", "unknown"),
            "income_reliability": ip.get("income_reliability", "unknown"),
            "preferred_account": ip.get("preferred_account"),
            "income_goal_contribution_pct": float(ip.get("income_goal_contribution_pct", 0) or 0),
            "portfolio_income_pct": float(ip.get("portfolio_income_pct", 0) or 0),
        }

    return {
        "total_shares": total_shares,
        "total_value": total_mv,
        "portfolio_weight": weight,
        "accounts": accounts,
        "strategy_type": strategy_type,
        "recent_alerts": [dict(a) for a in recent_alerts],
        "has_active_alerts": len(recent_alerts) > 0,
        "has_stop_triggered": any(a["alert_type"] == "stop_triggered" for a in recent_alerts),
        "data_quality_issues": dq_issues,
        "position_tiny": weight < 0.5,
        "position_small": weight < 2.0,
        "income": income_ctx,
        "total_portfolio_income": total_income,
        "income_target": float(income_goals.get("target_income", 55000)) if income_goals else 55000,
        "income_gap": max(0, float(income_goals.get("target_income", 55000)) - total_income) if income_goals else 0,
    }


def _build_dq_note(conn, symbol: str, dq_alert_count: int) -> str:
    """F4 (CIO audit 2026-07-01): enumerate WHICH synthesis inputs are stale and how old, measured
    directly from the sources the prompt uses (enrichment cache cached_at, ticker_prices date, news
    recency) — the alert_events count alone almost never fires for real tickers. Thresholds are
    weekend-safe (price >4d) / refresh-cadence-based (enrichment >2d, daily 06:40 rebuild) / aligned
    with _check_symbol_data_quality (news 14d). Empty string when everything is fresh."""
    from datetime import datetime, date
    stale = []
    try:
        enrichment = json.loads((STATE_DIR / "ticker_enrichment_cache.json").read_text()) if (STATE_DIR / "ticker_enrichment_cache.json").exists() else {}
        e = enrichment.get(symbol) if isinstance(enrichment.get(symbol), dict) else None
        if e is None:
            stale.append("technicals/fundamentals snapshot (RSI, SMA, PE): MISSING from enrichment cache")
        elif e.get("cached_at"):
            age_d = (datetime.now() - datetime.fromisoformat(str(e["cached_at"]).split("+")[0])).total_seconds() / 86400
            if age_d > 2:
                stale.append(f"technicals/fundamentals snapshot (RSI, SMA, PE): {age_d:.1f} days old")
    except Exception:
        pass
    try:
        cur = conn.cursor()
        cur.execute("SELECT MAX(price_date) FROM ticker_prices WHERE symbol=%s", (symbol,))
        last_px = (cur.fetchone() or [None])[0]
        if last_px is None:
            stale.append("close price: NO price history in DB")
        else:
            px_age = (date.today() - last_px).days
            if px_age > 4:
                stale.append(f"last close price: {last_px} ({px_age} days old)")
        cur.execute("SELECT MAX(created_at)::date FROM news_articles WHERE symbol=%s", (symbol,))
        last_news = (cur.fetchone() or [None])[0]
        if last_news is None:
            stale.append("news: none on record")
        elif (date.today() - last_news).days > 14:
            stale.append(f"news: newest article {(date.today() - last_news).days} days old")
        cur.close()
    except Exception:
        pass
    if dq_alert_count > 0:
        stale.append(f"{dq_alert_count} data-quality alert(s) on this symbol in the last 7 days")
    if not stale:
        return ""
    lines = "\n".join(f"- {s}" for s in stale)
    return (f"\nDATA QUALITY WARNING — stale/missing inputs (down-weight these SPECIFIC fields, "
            f"trust fresh fields normally):\n{lines}\n"
            "If a decision-critical input (price, ownership, income) is stale, cap confidence at 0.5 "
            "or output RESEARCH_MORE instead of a directional verdict; otherwise still produce a "
            "recommendation.\n")


def _build_layer_status(conn) -> str:
    """Build layer allocation status string for synthesis prompt."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT pl.layer_id, pl.layer_name, pl.target_min_pct, pl.target_max_pct,
               COALESCE(SUM(iap.annual_income), 0) as layer_income,
               COUNT(iap.symbol) as symbol_count
        FROM portfolio_layers pl
        LEFT JOIN income_asset_profiles iap ON iap.layer_id = pl.layer_id
        GROUP BY pl.layer_id, pl.layer_name, pl.target_min_pct, pl.target_max_pct
    """)
    layers = cur.fetchall()

    # Get total portfolio value from holdings
    holdings = json.loads((STATE_DIR / "holdings.json").read_text()) if (STATE_DIR / "holdings.json").exists() else {}
    total_portfolio = sum(info.get("total_value", 0) for info in holdings.get("account_summaries", {}).values())

    # Get actual allocation per layer
    cur.execute("SELECT layer_id, SUM(iap.annual_income) as income FROM income_asset_profiles iap GROUP BY layer_id")
    # Need market value by layer — get from holdings
    layer_values = {}
    for h in holdings.get("holdings", []):
        sym = h.get("symbol", "")
        mv = float(h.get("market_value", 0) or 0)
        if h.get("is_cash"):
            continue
        cur.execute("SELECT layer_id FROM income_asset_profiles WHERE symbol=%s", (sym,))
        lr = cur.fetchone()
        lid = lr["layer_id"] if lr else "core_compounders"
        layer_values[lid] = layer_values.get(lid, 0) + mv

    cur.close()

    lines = []
    for l in layers:
        lid = l["layer_id"]
        actual_pct = round(layer_values.get(lid, 0) / total_portfolio * 100, 1) if total_portfolio > 0 else 0
        target_min = float(l["target_min_pct"] or 0)
        target_max = float(l["target_max_pct"] or 100)
        status = "IN RANGE" if target_min <= actual_pct <= target_max else ("OVERWEIGHT" if actual_pct > target_max else "UNDERWEIGHT")
        lines.append(f"  {l['layer_name']:25} actual={actual_pct:>5.1f}%  target={target_min:.0f}-{target_max:.0f}%  [{status}]  income=${float(l['layer_income']):,.0f}/yr")
    return "\n".join(lines)


def run_synthesis(conn, symbol: str, lanes=None, manual_trigger: bool = False, dry_run: bool = False):
    """Run strategy-aware final synthesis combining all analyst narratives.

    dry_run: build prompt + run OAuth/local lanes but do not persist synthesis or maturity."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get all completed narratives
    cur.execute("""
        SELECT agent, full_narrative, summary, recommendation, confidence, reason_codes,
               full_result, created_at
        FROM watchlist_agent_results
        WHERE symbol = %s AND status = 'completed'
        ORDER BY created_at DESC
    """, (symbol,))
    results = cur.fetchall()

    if not results:
        cur.close()
        return {"ok": False, "error": "no_completed_agent_results", "symbol": symbol,
                "hint": "Queue agent reviews first (Refresh on card), then run CIO synthesis."}

    # Mark synthesis as processing (skipped on dry_run — no maturity side effects)
    if not dry_run:
        cur.execute("UPDATE watchlist_analysis_maturity SET final_synthesis_status='processing', updated_at=now() WHERE symbol=%s", (symbol,))
        conn.commit()

    # Get portfolio context and strategy weights
    port_ctx = _get_portfolio_context(conn, symbol)
    strategy_type = port_ctx["strategy_type"]
    weights = STRATEGY_WEIGHTS.get(strategy_type, STRATEGY_WEIGHTS["core_holding"])
    rules = weights.get("rules", [])

    # Build narratives section
    narratives = ""
    for r in results:
        narratives += f"\n--- {r['agent'].upper()} ({r['created_at'].strftime('%Y-%m-%d') if r.get('created_at') else '?'}) ---\n"
        narratives += f"Recommendation: {r.get('recommendation', '?')}, Confidence: {r.get('confidence', '?')}\n"
        _agent_struct = {"evidence": [], "data_i_doubt": "none"}
        try:
            _fr = json.loads(r.get("full_result") or "{}")
            if isinstance(_fr, dict):
                _agent_struct["evidence"] = _fr.get("evidence") or []
                _agent_struct["data_i_doubt"] = _fr.get("data_i_doubt") or "none"
        except Exception:
            pass
        _ev_block = _format_evidence_for_synthesis(_agent_struct)
        if _ev_block:
            narratives += _ev_block
        narratives += f"Narrative: {r.get('full_narrative') or r.get('summary', 'No narrative')}\n"
        if r.get('reason_codes'):
            narratives += f"Reason codes: {', '.join(r['reason_codes'])}\n"

    context = _get_context(conn, symbol)

    # Build portfolio position summary
    position_summary = f"""
PORTFOLIO POSITION:
Total shares: {port_ctx['total_shares']:.1f}
Total value: ${port_ctx['total_value']:,.0f}
Portfolio weight: {port_ctx['portfolio_weight']:.1f}%
Accounts: {', '.join(f"{a['type']} ({a['shares']:.0f} sh, ${a['value']:,.0f})" for a in port_ctx['accounts'])}
"""
    if port_ctx["total_shares"] == 0:
        position_summary += "NOT CURRENTLY HELD (0 shares in any account) — this block is live holdings ground-truth; any analyst narrative describing an existing position is stale.\n"
    elif port_ctx["position_tiny"]:
        position_summary += "NOTE: Position is <0.5% of portfolio — actions have minimal impact.\n"

    # Income context
    income_context = ""
    inc = port_ctx.get("income", {})
    if inc:
        _ai = float(inc.get('annual_income') or 0)
        _yp = float(inc.get('yield_pct') or 0)
        _fy = float(inc.get('forward_yield_pct') or 0)
        _yoc = float(inc.get('yield_on_cost_pct') or 0)
        _igc = float(inc.get('income_goal_contribution_pct') or 0)
        _tpi = float(port_ctx.get('total_portfolio_income') or 0)
        _tig = float(port_ctx.get('income_target') or 55000)
        _gap = float(port_ctx.get('income_gap') or 0)
        income_context = f"""
INCOME PROFILE:
Layer: {inc.get('layer', 'unknown')}
Annual income: ${_ai:,.0f} | Yield: {_yp:.1f}% | Forward: {_fy:.1f}% | YoC: {_yoc:.1f}%
Payout: {inc.get('payout_safety', 'unknown')} | Reliability: {inc.get('income_reliability', 'unknown')}
Preferred account: {inc.get('preferred_account', 'any')}
Contributes {_igc:.1f}% of income target (${_tig:,.0f})
Total portfolio income: ${_tpi:,.0f} — gap: ${_gap:,.0f}
"""

    # Build alert context
    alert_context = ""
    if port_ctx["has_active_alerts"]:
        alert_context = "\nACTIVE ALERTS (last 24h):\n"
        for a in port_ctx["recent_alerts"]:
            alert_context += f"- {a['alert_type']} (severity: {a['severity']})\n"
        if port_ctx["has_stop_triggered"]:
            alert_context += "CRITICAL: Stop was triggered — risk assessment should be weighted heavily.\n"

    # Data quality warning — enumerate WHICH inputs are stale + their age (F4, CIO audit 2026-07-01),
    # not just a count, so the model can down-weight the specific bad fields.
    dq_note = _build_dq_note(conn, symbol, port_ctx["data_quality_issues"])

    # Strategy rules
    rules_text = "\n".join(f"- {r}" for r in rules)

    prompt = f"""/no_think You are the Chief Investment Officer performing final synthesis for the portfolio committee.

STRATEGY TYPE: {strategy_type}
DECISION WEIGHTS for {strategy_type}:
- Allocation/position sizing: {weights['allocation']:.0%}
- Account location: {weights['account_location']:.0%}
- Fundamentals: {weights['fundamentals']:.0%}
- Technicals: {weights['technicals']:.0%}
- Alerts/events: {weights['alerts']:.0%}

STRATEGY-SPECIFIC RULES (you MUST follow these):
{rules_text}

{context['text']}
{position_summary}
{income_context}
{alert_context}
{dq_note}

PORTFOLIO MANDATE:
Goal: Build sustainable retirement income. Target $55K/yr. Current: ${port_ctx.get('total_portfolio_income', 0):,.0f}/yr. Gap: ${port_ctx.get('income_gap', 0):,.0f}. Timeline: 4-8 years.

LAYER ALLOCATION STATUS:
{_build_layer_status(conn)}

ALLOCATION-FIRST RULE: If a layer is outside its target range, the recommendation MUST prioritize fixing layer allocation. Underweight income_generators = ADD income assets. Overweight core_compounders = consider rebalancing INTO income layer.

INCOME PROTECTION RULE: For income assets, TRIM is BLOCKED unless:
- Position exceeds max allocation (>15% portfolio weight)
- Income deterioration detected (payout safety = at_risk/unsafe)
- Superior income replacement identified with better yield/safety

RSI OVERRIDE: RSI cannot trigger SELL/TRIM for income assets. RSI only informs ADD timing (buy on pullback).

INCOME IMPACT: This position provides {float(inc.get('portfolio_income_pct') or 0):.1f}% of total portfolio income. If >20%, require elevated justification for any reduction.

ANALYST NARRATIVES:
{narratives}

CRITICAL INSTRUCTIONS:
1. Your recommendation MUST be consistent with the strategy type and rules above.
2. For income/dividend ETFs: DO NOT recommend TRIM/SELL based solely on RSI or technical overbought signals.
3. For tiny positions (<0.5% weight): downgrade action priority — HOLD or IGNORE unless thesis broken.
4. If recent stop alert exists, weight risk assessment heavily.
5. Account location matters: IRA positions have different tax implications than taxable.
6. State explicitly which analyst you agree with and why you disagree with others.
7. PAST PERFORMANCE GUARDRAIL: Historical returns are evidence/context, NOT predictions. Distinguish between:
   - Historical evidence (what happened before)
   - Current facts (price, yield, allocation now)
   - Forward assumptions (scenario-based, labeled conservative/base/aggressive)
   - Your recommendation (based on all three, not just history)
   Do NOT use "it returned X% before" as the sole rationale. Instead reference current fundamentals, payout quality, and strategy fit.
8. INPUT CONTRADICTION RULE: If input sources conflict on a material fact (ownership, position size, income), the PORTFOLIO POSITION block is the live-holdings ground truth — prefer it over analyst narratives (which may be older snapshots). State the contradiction in "conflicts", lower confidence proportionally, and still produce a verdict; do NOT let a stale-narrative conflict alone collapse confidence below 0.4.
9. STRUCTURED AGENT EVIDENCE: Each analyst block includes tagged evidence ([fact]/[technical]/[risk]) and optional "Data doubt". Reconcile these structured claims first — weight [risk] and "Data doubt" heavily when they flag stale/missing inputs; do not let free-form narrative override tagged [fact] claims that contradict PORTFOLIO POSITION.

{build_synthesis_json_schema()}
"""

    prompt = f"[prompt_version: {SYNTHESIS_PROMPT_VERSION}]\n" + prompt   # version-stamp (tracked in synthesis_version)
    # max_tokens applies to the LOCAL gemma fallback only (cloud lanes send no cap); 1000 truncated the
    # ~11-field JSON contract mid-narrative on the fallback lane (measured: 1/1 local rows truncated).
    if manual_trigger or lanes:
        raw, dual_meta = _synthesis_lanes(prompt, lanes=lanes, max_tokens=2000, manual_trigger=manual_trigger)
    else:
        raw, dual_meta = _synthesis_dual(prompt, max_tokens=2000)   # Grok + ChatGPT dual-consensus, gemma fallback
    # All lanes failed → do NOT upsert: the parser fallback would store the error string as the
    # narrative, clobbering the last good synthesis (404 such rows accumulated Apr 29–May 8 2026,
    # e.g. ANET rendered "LLM error: All providers failed" as its CIO note for 65 days).
    if isinstance(raw, str) and raw.startswith("LLM error"):
        print(f"  [synthesis] {symbol}: all LLM lanes failed ({raw[:80]}) — keeping prior synthesis, no upsert")
        if dry_run:
            try:
                conn.rollback()
            except Exception:
                pass
            return {
                "ok": False, "dry_run": True, "error": "llm_lanes_failed", "symbol": symbol,
                "detail": str(raw)[:200], "prompt": prompt, "prompt_chars": len(prompt),
                "input_agents": [r["agent"] for r in results], "persisted": False,
            }
        # Self-heal (2026-07-03, ANET post-purge): the caller marks the job completed, so without a
        # retry this symbol silently has NO synthesis until some other lane re-queues it. Enqueue a
        # deduped retry so the next worker pass re-runs once lanes recover.
        try:
            cur2 = conn.cursor()
            # Dedupe on QUEUED only — the job we are running inside is itself 'processing', and
            # matching it meant the guard never actually enqueued a retry (SMCI 2026-07-03).
            cur2.execute("""SELECT 1 FROM watchlist_agent_jobs WHERE symbol=%s AND requested_agent='full_chain'
                            AND status = 'queued' LIMIT 1""", (symbol,))
            if not cur2.fetchone():
                from datetime import datetime as _dtt, timezone as _tzz
                try:
                    from agent_job_enqueue_governance import EnqueueRequest, governed_enqueue
                    governed_enqueue(cur2, EnqueueRequest(
                        symbol=symbol,
                        requested_agent="full_chain",
                        request_type="synthesis_retry",
                        submitted_from="run_synthesis_guard",
                        priority=2,
                        note="all LLM lanes failed — automatic retry",
                        job_id=f"synretry-{symbol}-{_dtt.now(_tzz.utc).strftime('%Y%m%d%H%M%S')}",
                        universe_tier="T1",
                        material=True,
                    ))
                except Exception:
                    cur2.execute("""INSERT INTO watchlist_agent_jobs
                                    (id, symbol, requested_agent, request_type, note, priority, status, submitted_from, payload, created_at)
                                    VALUES (%s,%s,'full_chain','synthesis_retry',
                                            'all LLM lanes failed — automatic retry',2,'queued','run_synthesis_guard','{}',NOW())
                                    ON CONFLICT (id) DO NOTHING""",
                                 (f"synretry-{symbol}-{_dtt.now(_tzz.utc).strftime('%Y%m%d%H%M%S')}", symbol))
                # Keep the synthesis gate open for the retry — run_synthesis skips 'completed' maturity.
                cur2.execute("""UPDATE watchlist_analysis_maturity SET final_synthesis_status='pending', analysis_stage='specialist_review_complete', updated_at=now()
                                WHERE symbol=%s AND final_synthesis_status='completed'""", (symbol,))
                conn.commit()
                print(f"  [synthesis] {symbol}: retry job enqueued")
        except Exception as _re:
            print(f"  [synthesis] {symbol}: retry enqueue failed (non-fatal): {str(_re)[:80]}")
        return {"ok": False, "error": "llm_lanes_failed", "symbol": symbol, "detail": str(raw)[:200]}
    syn = parse_synthesis_result(raw)
    parsed = syn
    conflicts = list(syn.get("conflicts") or [])
    unresolved = list(syn.get("unresolved") or [])
    action = syn.get("action") or syn.get("next_action", "")
    next_review = syn.get("next_review_date")
    synthesis_narrative = syn.get("synthesis_narrative") or syn.get("full_narrative", "")
    # LLM refusals ("**I cannot fulfill this request.**...") are failure artifacts, not synthesis —
    # normalize them to the "LLM error:" convention so the display guard + purge/requeue machinery
    # treat them like provider failures (FATN surfaced a raw refusal as its CIO note, 2026-07-06).
    # Prefix-only: partial refusals that continue with real evidence keep their content.
    _nlead = synthesis_narrative.lstrip("*#_ ").lower()[:60]
    if _nlead.startswith(("i cannot fulfill", "i can't fulfill", "i cannot help", "i can't help",
                          "i'm unable to", "i am unable to", "i cannot act as", "i can't act as",
                          "i cannot provide", "i can't provide")):
        synthesis_narrative = "LLM error: model refused the synthesis prompt (refusal suppressed)"
    dual_meta["agent_contract"] = AGENT_JSON_CONTRACT_VERSION
    dual_meta["structured_evidence"] = syn.get("evidence", [])
    dual_meta["data_i_doubt"] = syn.get("data_i_doubt", "none")

    # ── DUAL-CONSENSUS reconciliation: apply the Grok+ChatGPT verdict BEFORE gating. On disagreement we
    # already chose the more cautious recommendation + lowered confidence; surface it as a conflict. ──
    if dual_meta.get("consensus"):
        parsed["recommendation"] = dual_meta["consensus"]
        if dual_meta.get("consensus_confidence") is not None:
            parsed["confidence"] = dual_meta["consensus_confidence"]
        if dual_meta.get("agree") is False:
            conflicts.append(
                f"MODEL DISAGREEMENT — Grok={dual_meta['grok']['recommendation']} vs "
                f"ChatGPT={dual_meta['chatgpt']['recommendation']}; took the more cautious "
                f"({dual_meta['consensus']}) and lowered confidence.")
            synthesis_narrative = (f"[DUAL-CONSENSUS] Grok and ChatGPT disagreed "
                                   f"(Grok={dual_meta['grok']['recommendation']}, "
                                   f"ChatGPT={dual_meta['chatgpt']['recommendation']}). " + synthesis_narrative)

    # ── POST-LLM GATING RULES (hard overrides) ──────────────────────
    rec = parsed["recommendation"].upper()
    inc = port_ctx.get("income", {})

    # Rule 1: Income protection — block TRIM/SELL on safe income assets
    if rec in ("TRIM", "SELL") and inc.get("layer") == "income_generators":
        payout = inc.get("payout_safety", "unknown")
        weight_pct = port_ctx.get("portfolio_weight", 0)
        if payout in ("safe", "moderate") and weight_pct <= 15:
            # Override: income asset with safe payout, not overweight
            parsed["recommendation"] = "HOLD"
            parsed["confidence"] = min(parsed["confidence"], 0.5)
            action = f"HOLD — income protection rule: {payout} payout, {weight_pct:.1f}% weight (<=15% max). Original LLM said {rec}."
            conflicts.append(f"GATING OVERRIDE: LLM recommended {rec} but income protection rule blocked it (payout={payout}, weight={weight_pct:.1f}%)")
            synthesis_narrative = f"[GATED] Original recommendation {rec} overridden by income protection rule. Position has {payout} payout safety and {weight_pct:.1f}% weight (within 15% max). " + synthesis_narrative

    # Rule 2: RSI cannot trigger SELL for income assets
    if rec in ("TRIM", "SELL") and strategy_type == "income":
        reason_codes = parsed.get("reason_codes", [])
        tech_reasons = {"overbought", "rsi_high", "technical_overbought", "overvalued"}
        if reason_codes and set(r.lower() for r in reason_codes) <= tech_reasons:
            parsed["recommendation"] = "HOLD"
            parsed["confidence"] = min(parsed["confidence"], 0.5)
            action = f"HOLD — RSI override: technical signals alone cannot trigger TRIM on income ETF. Original: {rec}."
            conflicts.append(f"GATING OVERRIDE: RSI/technical-only {rec} blocked for income strategy")

    # Rule 3: Income impact >20% requires elevated justification
    income_pct = inc.get("portfolio_income_pct", 0)
    if rec in ("TRIM", "SELL", "AVOID") and income_pct > 20:
        if parsed["confidence"] < 0.8:
            # Not confident enough to reduce major income source
            parsed["recommendation"] = "HOLD"
            action = f"HOLD — position provides {income_pct:.0f}% of portfolio income. Requires >80% confidence to reduce. Original: {rec} at {parsed['confidence']:.0%}."
            conflicts.append(f"GATING OVERRIDE: {income_pct:.0f}% income concentration requires elevated justification (conf was {parsed['confidence']:.0%} < 80%)")

    # Update rec after gating
    rec = parsed["recommendation"].upper()

    # Store synthesis — record the ACTUAL model that ran + the prompt version (not the hardcoded local)
    actual_model = getattr(_llm, "_last_model", OLLAMA_MODEL) or OLLAMA_MODEL

    if dry_run:
        specialist_inputs = [
            {
                "agent": r["agent"],
                "recommendation": r.get("recommendation"),
                "confidence": float(r.get("confidence") or 0),
                "summary": (r.get("summary") or "")[:200],
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            }
            for r in results
        ]
        try:
            conn.rollback()
        except Exception:
            pass
        cur.close()
        print(f"  [synthesis-dry-run] {symbol}: {parsed['recommendation']} conf={parsed['confidence']:.0%} (not persisted)")
        return {
            "ok": True,
            "dry_run": True,
            "symbol": symbol,
            "persisted": False,
            "prompt_version": SYNTHESIS_PROMPT_VERSION,
            "prompt": prompt,
            "prompt_chars": len(prompt),
            "strategy_type": strategy_type,
            "input_agents": [r["agent"] for r in results],
            "specialist_inputs": specialist_inputs,
            "recommendation": parsed["recommendation"],
            "confidence": parsed["confidence"],
            "action": action,
            "conflicts": conflicts,
            "unresolved": unresolved,
            "synthesis_narrative": synthesis_narrative,
            "dual_consensus": dual_meta,
            "model_used": actual_model,
            "raw_response": raw,
            "lanes_run": list(lanes or ("grok", "chatgpt")),
            "manual_trigger": manual_trigger,
        }
    _grok_rec = (dual_meta.get("grok") or {}).get("recommendation")
    _cgpt_rec = (dual_meta.get("chatgpt") or {}).get("recommendation")
    cur.execute("""
        INSERT INTO watchlist_final_synthesis
            (symbol, recommendation, confidence, action, reason_codes, conflicts, unresolved,
             next_review_date, synthesis_narrative, input_agents, model_used, raw_response, synthesis_version,
             grok_recommendation, chatgpt_recommendation, models_agree, dual_consensus_json)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol) DO UPDATE SET
            recommendation=EXCLUDED.recommendation, confidence=EXCLUDED.confidence,
            action=EXCLUDED.action, reason_codes=EXCLUDED.reason_codes,
            conflicts=EXCLUDED.conflicts, unresolved=EXCLUDED.unresolved,
            next_review_date=EXCLUDED.next_review_date,
            synthesis_narrative=EXCLUDED.synthesis_narrative,
            input_agents=EXCLUDED.input_agents, model_used=EXCLUDED.model_used,
            raw_response=EXCLUDED.raw_response, synthesis_version=EXCLUDED.synthesis_version,
            grok_recommendation=EXCLUDED.grok_recommendation, chatgpt_recommendation=EXCLUDED.chatgpt_recommendation,
            models_agree=EXCLUDED.models_agree, dual_consensus_json=EXCLUDED.dual_consensus_json, updated_at=now()
    """, (symbol, parsed["recommendation"], parsed["confidence"], action,
          parsed.get("reason_codes", []), conflicts, unresolved,
          next_review, synthesis_narrative,
          [r["agent"] for r in results], actual_model, raw, SYNTHESIS_VERSION_NUM,
          _grok_rec, _cgpt_rec, dual_meta.get("agree"), json.dumps(dual_meta)))

    # Record decision inputs (data lineage — what influenced this synthesis)
    try:
        # Agent results that fed into this synthesis
        for r in results:
            cur.execute("""INSERT INTO decision_inputs (symbol, source_type, source_table, source_id, title, relevance_score, used_in_synthesis)
                VALUES (%s, 'agent_result', 'watchlist_agent_results', %s, %s, %s, TRUE)""",
                (symbol, r.get("id"), f"{r['agent']}: {r.get('recommendation','?')}", float(r.get("confidence", 0))))
        # Recent news that was in context
        cur.execute("""SELECT id, title, relevance_score FROM news_articles
            WHERE symbol=%s AND created_at > NOW() - INTERVAL '7 days' ORDER BY relevance_score DESC LIMIT 5""", (symbol,))
        for n in cur.fetchall():
            cur.execute("""INSERT INTO decision_inputs (symbol, source_type, source_table, source_id, title, relevance_score, used_in_synthesis)
                VALUES (%s, 'news', 'news_articles', %s, %s, %s, TRUE)""",
                (symbol, n[0], (n[1] or "")[:200], float(n[2] or 0)))
    except Exception:
        pass  # Don't let lineage tracking break synthesis

    # Update maturity
    cur.execute("""
        UPDATE watchlist_analysis_maturity
        SET final_synthesis_status = 'completed',
            analysis_stage = 'final_synthesis_complete',
            needs_iteration = FALSE,
            iteration_reason = NULL,
            updated_at = now()
        WHERE symbol = %s
    """, (symbol,))

    # Update research card with synthesis
    cur.execute("""
        UPDATE watchlist_research_cards
        SET latest_summary = %s, latest_recommendation = %s, confidence = %s,
            research_status = 'synthesis_complete', needs_iteration = FALSE, updated_at = now()
        WHERE symbol = %s
    """, (parsed["summary"][:500], parsed["recommendation"], parsed["confidence"], symbol))

    # Event
    cur.execute("""
        INSERT INTO watchlist_events (event_type, symbol, agent, status, message)
        VALUES ('synthesis_complete', %s, 'synthesis', 'completed', %s)
    """, (symbol, f"Final: {parsed['recommendation']} (conf={parsed['confidence']:.0%}), conflicts={len(conflicts)}, unresolved={len(unresolved)}"))

    conn.commit()

    # ── AUTO-ESCALATION: Detect conflicts and flag for human review ────
    needs_escalation = False
    escalation_reasons = []

    # Check 1: LLM detected conflicts between agents
    if conflicts:
        needs_escalation = True
        escalation_reasons.append(f"{len(conflicts)} agent conflict(s)")

    # Check 2: Low confidence after synthesis
    if parsed["confidence"] < 0.4:
        needs_escalation = True
        escalation_reasons.append(f"Low confidence: {parsed['confidence']:.0%}")

    # Check 3: Gating override happened (agents wanted one thing, rules blocked it)
    gating_overrides = [c for c in conflicts if "GATING OVERRIDE" in c]
    if gating_overrides:
        needs_escalation = True
        escalation_reasons.append(f"{len(gating_overrides)} safety gate override(s)")

    # Check 4: Unresolved questions
    if unresolved and len(unresolved) >= 2:
        needs_escalation = True
        escalation_reasons.append(f"{len(unresolved)} unresolved questions")

    if needs_escalation:
        try:
            from agent_collab import log_handoff
            log_handoff(
                from_agent="synthesis",
                to_agent="human_review",
                symbol=symbol,
                intent=f"Auto-escalation: {'; '.join(escalation_reasons)}",
                confidence=parsed["confidence"],
                response_summary=f"{parsed['recommendation']} — {action[:100]}",
                escalated=True,
            )
            # Telegram notification for high-priority escalations
            if parsed["confidence"] < 0.3 or len(conflicts) >= 3:
                try:
                    from telegram_alert import send_telegram
                    send_telegram(
                        f"\U0001F6A8 *Escalation: {symbol}*\n"
                        f"Synthesis: {parsed['recommendation']} ({parsed['confidence']:.0%} confidence)\n"
                        f"Reasons: {', '.join(escalation_reasons)}\n"
                        f"Review at: /v2/watchlist?symbol={symbol}"
                    )
                except Exception:
                    pass
        except Exception:
            pass
        print(f"  \u26A0 {symbol}: ESCALATED — {', '.join(escalation_reasons)}")

    cur.close()
    print(f"  \u2605 {symbol}: SYNTHESIS {parsed['recommendation']} conf={parsed['confidence']:.0%}")
    return {
        "ok": True, "symbol": symbol,
        "recommendation": parsed["recommendation"],
        "confidence": parsed["confidence"],
        "action": action,
        "dual_consensus": dual_meta,
        "narrative_snip": (synthesis_narrative or "")[:400],
        "lanes_run": list(lanes or ("grok", "chatgpt")),
        "manual_trigger": manual_trigger,
    }


def _effective_job_limit(explicit_limit: int) -> int:
    """Raise intraday throughput when queue depth >100 (Hermes audit 2026-07-02)."""
    if explicit_limit >= 15:
        return explicit_limit
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM watchlist_agent_jobs WHERE status='queued'")
        queued = int(cur.fetchone()[0] or 0)
        conn.close()
        if queued > 100:
            return 15
    except Exception:
        pass
    return explicit_limit


def process_jobs(limit: int = 10):
    conn = _get_conn()
    cur = conn.cursor()
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Reap orphaned jobs: a process killed (12m cron timeout / crash) between marking a job
    # 'processing' and 'completed'/'failed' leaves it stuck forever. Requeue any 'processing'
    # job older than 20 min (> the 12m timeout, so genuinely in-flight jobs are never touched).
    cur.execute("""UPDATE watchlist_agent_jobs
                   SET status='queued', started_at=NULL
                   WHERE status='processing' AND started_at < now() - interval '20 minutes'
                   RETURNING id""")
    reaped = cur.fetchall()
    # Normalize 'pending' → 'queued': aegis_overnight creates health_requeue / stale_refresh
    # jobs as 'pending', but the claim query below only selects 'queued', so they never ran.
    # They have no started_at (not in-flight), so adopting them is always safe.
    cur.execute("UPDATE watchlist_agent_jobs SET status='queued' WHERE status='pending' RETURNING id")
    adopted = cur.fetchall()
    conn.commit()
    if reaped:
        print(f"[watchlist-agent] Reaped {len(reaped)} orphaned 'processing' jobs → requeued")
    if adopted:
        print(f"[watchlist-agent] Adopted {len(adopted)} 'pending' jobs → queued")

    holdings = holdings_list(PROJECT_ROOT)
    off_hours = is_off_hours_et()
    if off_hours:
        scope = sql_off_hours_scope("j.symbol")
        scope_p = off_hours_scope_params(holdings, PROJECT_ROOT)
        cur.execute(f"""UPDATE watchlist_agent_jobs j SET status='expired', completed_at=NOW(),
                         note=COALESCE(note,'') || ' [off-hours tail deprioritized]'
                       WHERE j.status IN ('queued','pending')
                         AND j.created_at < NOW() - INTERVAL '2 hours'
                         AND NOT {scope}
                       RETURNING id""", scope_p)
        expired = cur.fetchall()
        conn.commit()
        if expired:
            print(f"[watchlist-agent] Off-hours: expired {len(expired)} aged tail jobs (outside daily priority)")

    try:
        from agent_job_enqueue_governance import govern_existing_queued
        gov = govern_existing_queued(cur)
        conn.commit()
        if gov.get("superseded") or gov.get("stale_deferred"):
            print(f"[watchlist-agent] queue governance: {gov}")
    except Exception as _ge:
        print(f"[watchlist-agent] queue governance skipped: {type(_ge).__name__}")

    # Get queued jobs — PRIORITIZED: directive · holdings · proposals · buy/start · top-N · active · tail.
    scope_sql = ""
    scope_params: list = []
    if off_hours:
        scope_sql = f" AND {sql_off_hours_scope('j.symbol')}"
        scope_params = list(off_hours_scope_params(holdings, PROJECT_ROOT))
    prio_case = sql_job_priority_case("j.symbol")
    prio_p = job_priority_params(holdings, PROJECT_ROOT)
    sla_case = sql_request_type_sla_case("j.request_type")
    sla_p = request_type_sla_params()
    cur.execute(f"""SELECT * FROM watchlist_agent_jobs j WHERE j.status = 'queued'{scope_sql}
        ORDER BY {sla_case}, {prio_case}, priority, created_at LIMIT %s""",
                (*scope_params, *sla_p, *prio_p, limit))
    jobs = cur.fetchall()

    if not jobs:
        print(f"[watchlist-agent] No queued jobs")
        # Still check for symbols ready for synthesis
        _check_pending_synthesis(conn)
        conn.close()
        return 0

    print(f"[watchlist-agent] Processing {len(jobs)} jobs...")
    completed = 0
    portfolio_syms = _portfolio_symbol_set()
    wait_syms = _wait_setup_symbol_set(conn)
    global _PORTFOLIO_SYMS_RUN, _WAIT_SETUP_SYMS_RUN
    _PORTFOLIO_SYMS_RUN = portfolio_syms
    _WAIT_SETUP_SYMS_RUN = wait_syms
    if wait_syms:
        print(f"[watchlist-agent] WAIT setups (priority only, not OAuth-preempt): {', '.join(sorted(wait_syms))}")

    for job in jobs:
        job_id = job["id"]
        symbol = job["symbol"]
        agent = job["requested_agent"]
        request_type = job["request_type"]
        note = job.get("note", "")
        submitted_from = job.get("submitted_from")
        if not submitted_from:
            payload = job.get("payload")
            if isinstance(payload, str):
                try:
                    submitted_from = json.loads(payload).get("submitted_from")
                except Exception:
                    pass
            elif isinstance(payload, dict):
                submitted_from = payload.get("submitted_from")
        # Expose job context to the LLM wrapper for Maria OAuth tier routing.
        global _CURRENT_JOB_PRIORITY, _CURRENT_JOB_SYMBOL, _CURRENT_AGENT
        global _CURRENT_JOB_SUBMITTED_FROM, _CURRENT_JOB_REQUEST_TYPE
        _CURRENT_JOB_SYMBOL = str(symbol or "").upper()
        _CURRENT_AGENT = str(agent or "").lower()
        _CURRENT_JOB_SUBMITTED_FROM = str(submitted_from or "").strip() or None
        _CURRENT_JOB_REQUEST_TYPE = str(request_type or "").strip() or None
        try:
            _CURRENT_JOB_PRIORITY = int(job.get("priority")) if job.get("priority") is not None else None
        except (TypeError, ValueError):
            _CURRENT_JOB_PRIORITY = None

        # Symbol gate — reject garbage tokens before any LLM spend (e.g. 543354104)
        sym_ok, sym_reason = gate_watchlist_symbol(symbol, portfolio_symbols=portfolio_syms)
        if not sym_ok:
            print(f"  [symbol-gate] {symbol}: REJECTED — {sym_reason}")
            cur.execute(
                "UPDATE watchlist_agent_jobs SET status='failed', completed_at=now(), "
                "note=COALESCE(note,'') || %s WHERE id=%s",
                (f" [invalid_symbol: {sym_reason}]", job_id),
            )
            cur.execute(
                "INSERT INTO watchlist_events (event_type, symbol, agent, status, message) "
                "VALUES ('invalid_symbol', %s, %s, 'failed', %s)",
                (symbol, agent, f"Skipped: {sym_reason}"),
            )
            conn.commit()
            continue

        # Apply escalation policy if not already set
        _apply_escalation_policy(conn, symbol)

        # Mark processing
        cur.execute("UPDATE watchlist_agent_jobs SET status='processing', started_at=now() WHERE id=%s", (job_id,))
        _update_maturity(conn, symbol, agent, "processing")
        cur.execute("INSERT INTO watchlist_events (event_type, symbol, agent, status, message) VALUES ('processing', %s, %s, 'processing', %s)",
                    (symbol, agent, f"Started {agent} {request_type}"))
        conn.commit()

        # ── Risk-first data quality gate ──
        # If this is maria or steph, check if Risk already flagged a data gap
        if agent in ("maria", "steph"):
            risk_cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            risk_cur.execute(
                """SELECT recommendation, confidence FROM watchlist_agent_results
                   WHERE symbol=%s AND agent='risk_agent'
                   AND created_at > NOW() - INTERVAL '2 hours'
                   ORDER BY created_at DESC LIMIT 1""", (symbol,))
            risk_recent = risk_cur.fetchone()
            risk_cur.close()

            if (risk_recent
                    and (risk_recent.get("recommendation") or "").upper() == "RESEARCH_MORE"
                    and normalize_agent_confidence(risk_recent.get("confidence")) < 0.40):
                # Risk had a data gap — check and try to enrich
                quality = _check_symbol_data_quality(symbol)
                if quality["quality_score"] < 60:
                    print(f"  [data-gate] {symbol}: Risk data gap (Q={quality['quality_score']}). Missing: {quality['enrichment_needed']}")
                    enriched = _attempt_symbol_enrichment(symbol, quality["enrichment_needed"])
                    if not enriched:
                        # Cannot enrich — skip this agent, don't waste LLM call
                        print(f"  [data-gate] {symbol}: Enrichment failed. Skipping {agent} to avoid empty analysis.")
                        cur.execute("UPDATE watchlist_agent_jobs SET status='failed', completed_at=now() WHERE id=%s", (job_id,))
                        cur.execute("INSERT INTO watchlist_events (event_type, symbol, agent, status, message) VALUES ('data_gap_skip', %s, %s, 'skipped', %s)",
                                    (symbol, agent, f"Skipped: Risk data gap Q={quality['quality_score']}, enrichment failed"))
                        conn.commit()
                        continue
                    else:
                        print(f"  [data-gate] {symbol}: Enrichment succeeded (Q was {quality['quality_score']}). Proceeding with {agent}.")

        # Build context and prompt
        context = _get_context(conn, symbol)

        # Maria: ONE governed FAST call (call-count contract). Two-pass retained but unused.
        if agent == "maria":
            raw = _run_maria_one_pass(symbol, context["text"], note)
            prompt = f"[one-pass maria for {symbol}]"
            prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        else:
            prompt = _build_prompt(agent, symbol, context["text"], note)
            prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]
            raw = _llm(prompt)

        # LLM/embed can run 90s+ — refresh DB before any writes.
        conn = _refresh_conn(conn)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        if not raw or raw.startswith("LLM error"):
            cur.execute("UPDATE watchlist_agent_jobs SET status='failed', completed_at=now() WHERE id=%s", (job_id,))
            cur.execute("UPDATE watchlist_items SET status='active', updated_at=now() WHERE symbol=%s AND status='queued'", (symbol,))
            _update_maturity(conn, symbol, agent, "failed")
            cur.execute("INSERT INTO watchlist_events (event_type, symbol, agent, status, message) VALUES ('failed', %s, %s, 'failed', %s)",
                        (symbol, agent, raw or "Empty LLM response"))
            conn.commit()
            print(f"  ✗ {symbol} ({agent}): FAILED — {(raw or 'empty')[:50]}")
            continue

        # Parse result
        parsed = _parse_result(raw)

        # Store result with full narrative
        result_id = f"res-{job_id}"
        cur.execute("""
            INSERT INTO watchlist_agent_results
                (id, job_id, symbol, agent, request_type, status, confidence,
                 summary, full_narrative, recommendation, reason_codes,
                 next_action, full_result, model_used, prompt_hash,
                 input_data_snapshot, raw_response, started_at, completed_at)
            VALUES (%s, %s, %s, %s, %s, 'completed', %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, now())
            ON CONFLICT (id) DO UPDATE SET
                summary=EXCLUDED.summary, full_narrative=EXCLUDED.full_narrative,
                recommendation=EXCLUDED.recommendation, confidence=EXCLUDED.confidence,
                reason_codes=EXCLUDED.reason_codes, raw_response=EXCLUDED.raw_response,
                model_used=EXCLUDED.model_used, completed_at=now()
        """, (result_id, job_id, symbol, agent, request_type, parsed["confidence"],
              parsed["summary"][:500], parsed["full_narrative"][:3000],
              parsed["recommendation"], parsed["reason_codes"],
              parsed.get("next_action", ""),
              json.dumps({
                  "raw": raw,
                  "model": getattr(_llm, "_last_model", OLLAMA_MODEL),
                  "provider": getattr(_llm, "_last_provider", "unknown"),
                  "requested_provider_policy": getattr(_llm, "_requested_policy", None),
                  "first_provider_attempted": getattr(_llm, "_first_attempt", None),
                  "actual_provider": getattr(_llm, "_last_provider", None),
                  "fallback_reason": getattr(_llm, "_fallback_reason", None),
                  "cost": getattr(_llm, "_last_cost", 0),
                  "fallback_chain": getattr(_llm, "_fallback_chain", []),
                  "task_type": "agent_narrative",
                  "agent": agent,
                  "symbol": symbol,
                  "manual_vs_automatic": getattr(_llm, "_manual_vs_automatic", None),
                  "agent_contract": AGENT_JSON_CONTRACT_VERSION,
                  "evidence": parsed.get("evidence", []),
                  "data_i_doubt": parsed.get("data_i_doubt", "none"),
              }),
              getattr(_llm, "_last_model", OLLAMA_MODEL), prompt_hash,
              json.dumps(context["snapshot"], default=str),
              raw,
              job.get("started_at")))

        # Store RAG sources + peer notes for audit
        try:
            rag_used = getattr(sys.modules[__name__], '_last_rag_sources', [])
            peer_agents = getattr(sys.modules[__name__], '_last_peer_agents', [])
            cur.execute("UPDATE watchlist_agent_results SET rag_sources_used=%s, peer_notes_symbols=%s WHERE id=%s",
                        (json.dumps(rag_used), peer_agents, result_id))
            if rag_used:
                print(f"  [RAG-STORE] {symbol}: {len(rag_used)} sources saved")
            if peer_agents:
                print(f"  [PEER-STORE] {symbol}: notes from {peer_agents}")
        except Exception as e:
            print(f"  [RAG-STORE] ERROR: {e}")

        # Cache result for peer notes in same batch
        if symbol not in _batch_results_cache:
            _batch_results_cache[symbol] = []
        _batch_results_cache[symbol].append({
            "agent": agent, "recommendation": parsed["recommendation"],
            "confidence": parsed["confidence"], "summary": parsed["summary"][:200]
        })

        # Index new result embedding immediately
        try:
            from rag_indexer import index_source
            index_source("agent_result", hours_back=1, conn=conn)
        except Exception:
            pass

        # === IER WRITE-BACK (non-fatal) ===
        try:
            from intelligence_entity_manager import upsert_entity as _iem_upsert
            from datetime import datetime as _dt, timezone as _tz
            _iem_upsert(conn, symbol, 'market', {
                'last_agent': agent,
                'last_agent_verdict': f"{parsed['recommendation']} ({parsed['confidence']}) — {parsed['summary'][:150]}",
                'last_agent_analysis': _dt.now(_tz.utc),
                'agent_chain_status': 'complete',
            }, source='agent_jobs')
        except Exception:
            pass
        # === END WRITE-BACK ===

        # Self-assessment: low confidence + no RAG → suggest research
        try:
            rag_used = getattr(sys.modules[__name__], '_last_rag_sources', [])
            if float(parsed.get("confidence", 1)) < 0.50 and len(rag_used) == 0:
                cur.execute("""INSERT INTO user_research_topics (topic, priority, source, original_message, created_at)
                    VALUES (%s, 'high', %s, %s, NOW()) ON CONFLICT (topic) DO UPDATE SET priority='high'""",
                    (f"Find content covering {symbol} analysis",
                     f"agent_self_assessment:{agent}",
                     f"{agent} analyzed {symbol} with {parsed['confidence']:.0%} confidence and 0 RAG sources"))
                print(f"  [SELF-ASSESS] {symbol} ({agent}): low conf + no RAG → research topic created")
        except Exception:
            pass

        # Check if both agents complete for this symbol → send summary
        try:
            cur.execute("""SELECT agent, recommendation, confidence FROM watchlist_agent_results
                          WHERE symbol=%s AND created_at > NOW() - INTERVAL '2 hours'
                          ORDER BY created_at DESC""", (symbol,))
            recent = cur.fetchall()
            agents_done = set(r[0] for r in recent)
            if len(agents_done) >= 2 and job.get("submitted_from") in ("event_router", "auto_enrichment"):
                recs = {r[0]: r[1] for r in recent}
                confs = {r[0]: float(r[2] or 0) for r in recent}
                conflict = len(set(recs.values())) > 1
                from telegram_alert import send_telegram
                msg = f"Agent analysis complete: {symbol}\n"
                for a, rec in recs.items():
                    msg += f"  {a}: {rec} ({confs.get(a,0):.0%})\n"
                if conflict:
                    msg += "Agent conflict — review needed"
                    # Auto-trigger debate if not already pending for this symbol
                    try:
                        cur.execute("""SELECT id FROM agent_debate_log
                                      WHERE symbol=%s AND created_at > NOW() - INTERVAL '48 hours'""", (symbol,))
                        if not cur.fetchone():
                            from agent_watchlist_engine import run_agent_debate
                            run_agent_debate(symbol, f"conflict: {recs}", trigger_id=0, trigger_source="conflict_auto")
                            msg += "\nDebate triggered automatically."
                    except Exception as e:
                        print(f"  [debate-trigger] {symbol}: {e}")
                else:
                    msg += f"Consensus: {list(recs.values())[0]}"
                send_telegram(msg)
        except Exception:
            pass

        # Update job — recover from poisoned transaction if needed
        try:
            cur.execute("SELECT 1")  # test transaction health
        except Exception:
            conn.rollback()
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            print(f"  [recovery] {symbol}: rolled back poisoned transaction")

        cur.execute("UPDATE watchlist_agent_jobs SET status='completed', completed_at=now(), result_id=%s WHERE id=%s", (result_id, job_id))

        # Proposal review jobs: sync watchlist verdict back to proposal_agent_reviews
        try:
            payload = job.get("payload") or {}
            if isinstance(payload, str):
                payload = json.loads(payload)
            pid = int(payload.get("proposal_id") or 0)
            if pid and request_type == "proposal_review":
                import broker_promote_oversight as _bpo
                _bpo.sync_proposal_reviews_from_watchlist(pid)
        except Exception as e:
            print(f"  [proposal-sync] {symbol}: {e}")

        # Update watchlist item status
        cur.execute("UPDATE watchlist_items SET status='researched', updated_at=now() WHERE symbol=%s AND status IN ('queued','active')", (symbol,))

        # Upsert research card
        cur.execute("""
            INSERT INTO watchlist_research_cards (symbol, card, research_status, latest_summary, latest_recommendation, confidence, needs_iteration, updated_at)
            VALUES (%s, %s, 'partial', %s, %s, %s, TRUE, now())
            ON CONFLICT (symbol) DO UPDATE SET
                card=EXCLUDED.card, latest_summary=EXCLUDED.latest_summary,
                latest_recommendation=EXCLUDED.latest_recommendation,
                confidence=EXCLUDED.confidence, updated_at=now()
        """, (symbol, json.dumps({"agent": agent, "summary": parsed["summary"], "recommendation": parsed["recommendation"]}),
              parsed["summary"][:500], parsed["recommendation"], parsed["confidence"]))

        # Update maturity
        _update_maturity(conn, symbol, agent, "completed")

        # Event
        cur.execute("INSERT INTO watchlist_events (event_type, symbol, agent, status, message) VALUES ('completed', %s, %s, 'completed', %s)",
                    (symbol, agent, f"{parsed['recommendation']} conf={parsed['confidence']:.0%} codes={parsed['reason_codes']}"))
        conn.commit()
        completed += 1
        print(f"  ✓ {symbol} ({agent}): {parsed['recommendation']} conf={parsed['confidence']:.0%}")

        # Check if synthesis is now ready
        if _check_synthesis_ready(conn, symbol):
            print(f"  → {symbol}: All required reviews complete, running synthesis...")
            try:
                run_synthesis(conn, symbol)
                # Run safety assessment immediately after synthesis
                try:
                    from synthesis_safety import assess_synthesis_safety, persist_safety
                    safety = assess_synthesis_safety(symbol)
                    persist_safety(symbol, safety)
                    print(f"  ⛨ {symbol}: Safety={safety['decision_safety']} actionable={safety['actionable_allowed']}")
                except Exception as se:
                    print(f"  [safety] {symbol}: assessment failed: {se}")
            except Exception as e:
                # Report the ORIGINAL failure first — the recovery write below used
                # to raise InterfaceError on a dead connection, masking this error
                # and aborting the entire job run (2026-07-20).
                print(f"  ✗ {symbol}: Synthesis failed: {type(e).__name__}: {e}")
                import traceback as _tb
                print(_tb.format_exc()[-800:])
                try:
                    cur.execute("UPDATE watchlist_analysis_maturity "
                                "SET final_synthesis_status='failed', updated_at=now() "
                                "WHERE symbol=%s", (symbol,))
                    conn.commit()
                except Exception as _me:
                    # The shared connection may itself be dead. Mark the failure on a
                    # FRESH connection so the symbol does not stay stuck 'processing',
                    # and never let the recovery path kill the run.
                    print(f"  [recover] {symbol}: marking failed on the shared conn "
                          f"raised {type(_me).__name__} — retrying on a fresh conn")
                    try:
                        _rc = _get_conn()
                        with _rc.cursor() as _rcur:
                            _rcur.execute("UPDATE watchlist_analysis_maturity "
                                          "SET final_synthesis_status='failed', updated_at=now() "
                                          "WHERE symbol=%s", (symbol,))
                        _rc.commit()
                    except Exception as _me2:
                        print(f"  [recover] {symbol}: fresh-conn mark ALSO failed: "
                              f"{type(_me2).__name__}: {_me2}")

    # Also check for any other symbols that became ready for synthesis
    _check_pending_synthesis(conn)

    conn.close()
    print(f"[watchlist-agent] Done: {completed}/{len(jobs)} completed")
    return completed


def _check_pending_synthesis(conn):
    """Check all symbols that have all required reviews done but no synthesis yet."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT symbol FROM watchlist_analysis_maturity
        WHERE analysis_stage = 'specialist_review_complete'
        AND final_synthesis_status = 'pending'
    """)
    ready = [r["symbol"] for r in cur.fetchall()]
    cur.close()

    for sym in ready:
        print(f"  → {sym}: Pending synthesis detected, running...")
        try:
            run_synthesis(conn, sym)
            from synthesis_safety import assess_synthesis_safety, persist_safety
            safety = assess_synthesis_safety(sym)
            persist_safety(sym, safety)
            print(f"  ⛨ {sym}: Safety={safety['decision_safety']}")
        except Exception as e:
            print(f"  ✗ {sym}: Synthesis failed: {e}")


def _auto_queue_new_symbols():
    """Auto-queue agent jobs for watchlist symbols that have no analysis yet.

    Runs every 15 minutes as part of the agent processing cycle.
    New symbols get Maria + Steph + Risk queued automatically.
    """
    conn = _get_conn()
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Skip auto-queue if backlog is already large
    cur.execute("SELECT COUNT(*) as cnt FROM watchlist_agent_jobs WHERE status = 'queued'")
    backlog = cur.fetchone()["cnt"]
    if backlog > 50:
        print(f"[watchlist-agent] Skipping auto-queue — backlog too large ({backlog} queued)")
        conn.close()
        return 0

    # Find active watchlist symbols with NO agent jobs at all
    cur.execute("""
        SELECT wi.symbol, tsc.strategy_type
        FROM watchlist_items wi
        LEFT JOIN ticker_strategy_classifications tsc ON wi.symbol = tsc.symbol AND tsc.active = TRUE
        WHERE wi.status = 'active'
          AND wi.symbol NOT IN (SELECT DISTINCT symbol FROM watchlist_agent_jobs)
        LIMIT 5
    """)
    new_symbols = cur.fetchall()

    if not new_symbols:
        return 0

    import uuid
    queued = 0
    agents_to_queue = ["maria", "steph", "risk_agent"]

    for row in new_symbols:
        symbol = row["symbol"]
        strategy_type = row.get("strategy_type") or "unknown"
        for agent in agents_to_queue:
            job_id = f"auto_{symbol.lower()}_{agent}_{uuid.uuid4().hex[:6]}"
            try:
                from agent_job_enqueue_governance import EnqueueRequest, governed_enqueue
                res = governed_enqueue(cur, EnqueueRequest(
                    symbol=symbol,
                    requested_agent=agent,
                    request_type="full_analysis",
                    submitted_from="watchlist_agent_auto_queue",
                    priority=2,
                    note=f"Auto-queued for new watchlist symbol (strategy: {strategy_type})",
                    job_id=job_id,
                    universe_tier="T2",
                ))
                if res.action == "INSERT":
                    queued += 1
            except Exception:
                cur.execute("""
                    INSERT INTO watchlist_agent_jobs
                        (id, symbol, requested_agent, request_type, priority, note, status)
                    VALUES (%s, %s, %s, 'full_analysis', 2, %s, 'queued')
                    ON CONFLICT DO NOTHING
                """, (job_id, symbol, agent, f"Auto-queued for new watchlist symbol (strategy: {strategy_type})"))
                queued += 1

    conn.commit()
    conn.close()
    if queued > 0:
        print(f"[watchlist-agent] Auto-queued {queued} jobs for {len(new_symbols)} new symbol(s)")
    return queued


def run_scheduled_canary(
    *,
    max_provider_calls: int = 1,
    process_id: str = "watchlist_maria_flash_narrative",
    max_tokens: int = 200,
    timeout: float = 90.0,
) -> dict:
    """One-call governed Flash canary — does NOT enter two-pass Maria / process_jobs.

    Guarantees (enforced):
      - exactly one provider call budget (aggregate + per-process)
      - FAST only (allow_fast_think=False)
      - no fan-out to other agents
      - no retries inside this function
      - no second Maria pass
    """
    import time as _time
    from lib import agent_flash_governance as afg
    from lib.agent_flash_governance import (
        FLASH_MODEL,
        FLASH_POLICY,
        governed_flash_call,
        process_for_task,
        reset_run_budget,
        run_budget_snapshot,
    )

    if max_provider_calls != 1:
        raise RuntimeError(
            f"SCHEDULED_CANARY_INVALID: max_provider_calls must be 1, got {max_provider_calls}"
        )
    if process_id != "watchlist_maria_flash_narrative":
        raise RuntimeError(
            f"SCHEDULED_CANARY_INVALID: only watchlist_maria_flash_narrative allowed, got {process_id}"
        )
    # Map process_id → task_type used by governance (maria narrative)
    task_type = "agent_narrative"
    mapped = process_for_task(task_type)
    if mapped != process_id:
        raise RuntimeError(
            f"SCHEDULED_CANARY_INVALID: process_for_task({task_type})={mapped} != {process_id}"
        )

    # Enforce one-call caps at module level (env is also set by wrapper / caller)
    os.environ["AGENT_FLASH_MAX_CALLS_PER_RUN_TOTAL"] = "1"
    os.environ["AGENT_FLASH_MAX_CALLS_PER_PROCESS"] = "1"
    afg.MAX_CALLS_PER_RUN_TOTAL = 1
    afg.MAX_CALLS_PER_PROCESS = 1
    afg.MAX_CALLS_PER_RUN = 1

    run_id = reset_run_budget(
        run_id=f"scheduled_canary_{int(_time.time())}_{os.getpid()}"
    )
    job_key = f"scheduled-canary-{run_id}"
    prompt = (
        "Advisory-only scheduled canary. Respond with JSON only. No tools. No orders. "
        'Schema: {"recommendation":"HOLD"|"BUY"|"SELL","confidence":0-100,"summary":"string"}. '
        "Symbol: CANARY. recommendation=HOLD, confidence=50, summary='scheduled canary ok'."
    )
    print(f"[scheduled-canary] run_id={run_id} process_id={process_id} max_calls=1 policy=FAST")
    result = governed_flash_call(
        prompt,
        task_type=task_type,
        max_tokens=int(max_tokens),
        timeout=float(timeout),
        metadata={
            "symbol": "CANARY",
            "agent": "maria",
            "canary": True,
            "scheduled_canary": True,
            "submitted_from": "scheduled_canary",
            "force_fast_think": False,
        },
        job_key=job_key,
        prompt_version="scheduled_canary_v1",
        allow_fast_think=False,
    )
    budget = run_budget_snapshot()
    out = {
        "mode": "scheduled_canary",
        "run_id": run_id,
        "job_key": job_key,
        "process_id": result.get("process_id") or process_id,
        "requested_policy": result.get("requested_policy") or FLASH_POLICY,
        "executed_policy": result.get("executed_policy"),
        "requested_model": result.get("requested_model_id") or FLASH_MODEL,
        "returned_model": result.get("returned_model") or result.get("model_used"),
        "provider_request_id": result.get("provider_request_id"),
        "tokens": result.get("tokens"),
        "cost_estimate": result.get("cost_estimate"),
        "fallback_used": result.get("fallback_used"),
        "success": bool(result.get("success")),
        "error": result.get("error"),
        "budget": budget,
        "provider_calls": int(budget.get("total_calls") or 0),
        # Prove two-pass path was not used
        "maria_two_pass_entered": False,
        "process_jobs_entered": False,
    }
    print(json.dumps(out, default=str))
    if not out["success"]:
        raise RuntimeError(out.get("error") or "SCHEDULED_CANARY_FAILED")
    if out["provider_calls"] != 1:
        raise RuntimeError(
            f"SCHEDULED_CANARY_CALL_COUNT: expected 1 got {out['provider_calls']}"
        )
    if out["returned_model"] != FLASH_MODEL:
        raise RuntimeError(
            f"SCHEDULED_CANARY_MODEL: expected {FLASH_MODEL} got {out['returned_model']}"
        )
    if out.get("fallback_used"):
        raise RuntimeError("SCHEDULED_CANARY_FALLBACK_FORBIDDEN")
    return out


if __name__ == "__main__":
    import sys as _sys

    # P0 fail-closed containment BEFORE argparse DB/provider work (Gate 4)
    try:
        from lib.agent_jobs_containment import exit_if_contained_worker_entry, WORKER_BLOCKED_EXIT
    except Exception as _imp_err:
        print(
            "CONTAINMENT_CHECK_FAILED: cannot import containment helper; "
            f"worker blocked ({type(_imp_err).__name__})"
        )
        _sys.exit(78)

    _rc = exit_if_contained_worker_entry()
    if _rc is not None:
        _sys.exit(_rc)

    import argparse
    from lib.agent_jobs_lock import OverlapError, acquire_jobs_lock, OVERLAP_EXIT
    from lib.agent_flash_governance import reset_run_budget

    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--scheduled-canary",
        action="store_true",
        help=(
            "One-call governed Flash canary: exactly one FAST deepseek-v4-flash request "
            "for watchlist_maria_flash_narrative. Bypasses process_jobs and Maria two-pass."
        ),
    )
    parser.add_argument(
        "--max-provider-calls",
        type=int,
        default=None,
        help="Hard aggregate provider-call cap for this invocation (required=1 with --scheduled-canary).",
    )
    parser.add_argument(
        "--process-id",
        type=str,
        default="watchlist_maria_flash_narrative",
        help="Registered process id (scheduled-canary only allows watchlist_maria_flash_narrative).",
    )
    args = parser.parse_args()

    try:
        with acquire_jobs_lock(blocking=False):
            if args.scheduled_canary:
                max_calls = 1 if args.max_provider_calls is None else int(args.max_provider_calls)
                if max_calls != 1:
                    print(
                        f"[scheduled-canary] REFUSED max-provider-calls={max_calls} "
                        "(must be 1)"
                    )
                    _sys.exit(2)
                if int(args.limit) != 1:
                    print(
                        f"[scheduled-canary] REFUSED --limit {args.limit} "
                        "(must be 1; limit alone is not a canary guarantee)"
                    )
                    _sys.exit(2)
                # Do NOT call process_jobs / _run_maria_two_pass / _auto_queue_new_symbols
                run_scheduled_canary(
                    max_provider_calls=1,
                    process_id=str(args.process_id or "watchlist_maria_flash_narrative"),
                )
                _sys.exit(0)

            reset_run_budget()
            with PipelineRun("process_watchlist_agent_jobs") as _run:
                _auto_queue_new_symbols()  # Check for new symbols first
                effective = _effective_job_limit(args.limit)
                if effective != args.limit:
                    print(f"[watchlist-agent] Queue depth >100 — raised limit {args.limit}→{effective}")
                process_jobs(effective)
    except OverlapError as e:
        print(f"[watchlist-agent] {e} — exit {OVERLAP_EXIT} (no provider calls)")
        _sys.exit(OVERLAP_EXIT)
    except Exception as e:
        if "--scheduled-canary" in _sys.argv or any(
            a == "--scheduled-canary" for a in _sys.argv
        ):
            print(f"[scheduled-canary] FAILED: {type(e).__name__}: {e}")
            _sys.exit(1)
        raise

