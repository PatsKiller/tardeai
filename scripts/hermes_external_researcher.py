#!/usr/bin/env python3
"""hermes_external_researcher.py — Hermes External Researcher lanes (Phase 210D/G). Claude lane implemented.

ADVISORY-ONLY. MANUAL / escalation-triggered (NOT auto-scheduled). Sends a REDACTED escalation packet to an
external cloud model and stores the structured response in hermes_external_research. NEVER touches broker/
order/stop/proposal/holdings/trading. The API key is read from the environment at call-time only — never
stored, logged, or returned. DRY-RUN by default (shows exactly what WOULD be sent); --apply to call out.

  python3 scripts/hermes_external_researcher.py --lane claude --question "..." [--symbol AAPL]      # dry-run
  python3 scripts/hermes_external_researcher.py --lane claude --question "..." --apply               # send
Redaction (hard): strips $ amounts, account numbers, API keys/tokens, .env content, broker creds, emails,
long digit runs — and only a whitelisted, high-level context is ever assembled.
"""
import os, sys, re, json, argparse, atexit, urllib.request
from pathlib import Path
from datetime import date
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from cio_agent_contract import build_external_research_json_schema, parse_external_research_result
from llm_net import urlopen_retry  # retry transient network/DNS/5xx; surfaces 4xx (e.g. credit) immediately
from lib.research_call_accounting import accounting_identity, append_event as append_call_event

ROOT = Path(__file__).resolve().parent.parent
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
# Per-lane config. key_env read at call-time only (never stored/logged). Cost-aware default models;
# operator may override with --model.
HERMES_CLI = str(Path.home() / ".local" / "bin" / "hermes")
LANE_CFG = {
    # Claude: Anthropic API (key from env). ChatGPT: FREE ChatGPT-subscription OAuth via Hermes Codex CLI
    # (provider openai-codex) — NOT the metered OpenAI API. Grok: xAI API key (or the free xai-oauth proxy).
    # DeepSeek: governed V4 Flash via scripts/llm_lane.py (cost-governed, no fallback).
    "claude":  {"kind": "anthropic", "url": ANTHROPIC_URL, "key_env": "ANTHROPIC_API_KEY", "default_model": "claude-sonnet-4-6"},
    "chatgpt": {"kind": "codex_cli", "provider": "openai-codex", "default_model": "gpt-5.4",
                "auth_hint": "hermes auth add openai-codex --type oauth   (operator OAuth — free under your ChatGPT subscription)"},
    "grok":    {"kind": "xai_proxy", "url": os.environ.get("HERMES_XAI_PROXY_URL", "http://127.0.0.1:8645/v1/chat/completions"),
                "default_model": "grok-3-mini",
                "auth_hint": "hermes auth add xai-oauth --type oauth  then  hermes proxy start --provider xai  (free xAI OAuth, no API key)"},
    "deepseek": {"kind": "governed_deepseek", "default_model": "deepseek-v4-flash",
                 "auth_hint": "governed DeepSeek V4 Flash via llm_lane.py (process hermes_external_research) — no OAuth"},
}
DEFAULT_MODEL = "claude-sonnet-4-6"


def _account_from_env(event: str, *, reason: str, attempt_no: int = 0, fallback_from: str | None = None) -> None:
    """Emit provider-boundary events using identities established by main()."""
    try:
        run_id = os.getenv("TRADEAI_LLM_RUN_ID", "").strip()
        call_id = os.getenv("TRADEAI_LLM_CALL_ID", "").strip()
        producer = os.getenv("TRADEAI_LLM_PRODUCER", "").strip()
        if not (run_id and call_id and producer):
            return
        append_call_event(
            event, producer=producer, family=os.getenv("TRADEAI_LLM_FAMILY", "REGISTERED"),
            run_id=run_id, call_id=call_id, symbol=os.getenv("TRADEAI_LLM_SYMBOL") or None,
            lane=os.getenv("TRADEAI_LLM_LANE", "unknown"),
            trigger=os.getenv("TRADEAI_LLM_TRIGGER", "unknown"), reason=reason,
            attempt_no=attempt_no, apply=True, fallback_from=fallback_from,
        )
    except Exception:
        pass

# ---- redaction ----
_PATTpairs = [
    (re.compile(r"\$\s?\d[\d,]*(\.\d+)?"), "$[REDACTED_AMOUNT]"),
    (re.compile(r"\b\d{6,}\b"), "[REDACTED_NUM]"),                 # account #s / long digit runs
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
    (re.compile(r"sk-[A-Za-z0-9]{16,}|AKIA[A-Z0-9]{16}|ghp_[A-Za-z0-9]{36}|xoxb-[A-Za-z0-9-]+"), "[REDACTED_KEY]"),
    (re.compile(r"\b\d{1,3}(,\d{3})+(\.\d+)?\b"), "[REDACTED_NUM]"),
]
_FORBIDDEN_SUBSTR = ["api_key", "apikey", "secret", "password", "token", "credential", "ANTHROPIC", "ALPACA",
                     "DB_PASSWORD", "BEGIN PRIVATE", "-----BEGIN"]


def redact(text):
    if text is None:
        return None
    s = str(text)
    for pat, repl in _PATTpairs:
        s = pat.sub(repl, s)
    low = s.lower()
    for f in _FORBIDDEN_SUBSTR:
        if f.lower() in low:
            # drop the whole line containing a forbidden marker
            s = "\n".join(ln for ln in s.splitlines() if f.lower() not in ln.lower())
    return s


def safe_context(symbol):
    """Whitelisted, high-level context only — NO dollar amounts, account ids, positions, or secrets.
    Reads safe summary fields and redacts the result as defense-in-depth."""
    if not symbol:
        return {}
    import psycopg2
    for ln in (ROOT / ".env").read_text().splitlines():
        if "=" in ln and not ln.strip().startswith("#"):
            k, _, v = ln.partition("="); os.environ.setdefault(k.strip(), v.strip())
    ctx = {"symbol": symbol}
    try:
        c = psycopg2.connect(host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"), dbname=os.getenv("DB_NAME"),
                             user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD")); cur = c.cursor()
        cur.execute("""SELECT strategy_id, status, count(*) FROM trade_instances WHERE symbol=%s
                       GROUP BY 1,2 ORDER BY 3 DESC LIMIT 5""", (symbol,))
        ctx["trade_strategy_status_counts"] = [list(map(str, r)) for r in cur.fetchall()]  # counts only, no $
        cur.execute("""SELECT topic FROM hermes_research_intelligence WHERE symbol=%s
                       ORDER BY created_at DESC LIMIT 5""", (symbol,))
        ctx["recent_research_topics"] = [redact(r[0]) for r in cur.fetchall()]
        c.close()
    except Exception as e:
        ctx["context_error"] = str(e)[:80]
    # Canonical Hermes intelligence (composite score/rank + research thesis + prior lane opinions).
    # Contains NO dollar amounts / account ids / positions / secrets; still redacted as defense-in-depth.
    try:
        from hermes_data_access import hermes_prompt_block
        blk = hermes_prompt_block(symbol)
        if blk:
            ctx["hermes_intelligence"] = redact(blk)
    except Exception:
        pass
    return ctx


PROMPT = """You are an external high-stakes research analyst (governed DeepSeek lane) advising a PAPER-trading
research system. This is ADVISORY ONLY — you do not execute or recommend executing any live trade. You are
given a REDACTED packet (no dollar amounts, account ids, or secrets). Provide a careful external challenge.

Question: {question}
Redacted context (JSON): {context}

The recommendation field IS the living thesis (not a one-line call). It must include the ticker, one numbered/symbol-specific fact, invalidation, role, and at least 8 sentences. Do not hide the thesis in evidence[]. JSON contract still required.
Compare new evidence with the standing thesis and return a ResearchThesisDelta@v1, not a first-impression essay. Never return chain-of-thought.

""" + build_external_research_json_schema()


def canonical_prompt_context(symbol, question):
    """Return the redacted stateful contract, retaining safe legacy context."""
    if not symbol:
        return {"symbol": None, "question": question, "authority": "READ_ONLY_ADVISORY"}
    try:
        from lib.research_prompt_context import build_research_prompt_context
    except ImportError:
        from scripts.lib.research_prompt_context import build_research_prompt_context
    context = build_research_prompt_context(symbol, question=question, root=ROOT)
    legacy = safe_context(symbol)
    if legacy:
        context["legacy_safe_context"] = legacy
    return json.loads(redact(json.dumps(context)))


def reconcile_accepted_research(symbol, rid, parsed, prompt_context, args):
    """Bridge a stored, accepted external result into delta/thesis/product review."""
    if str(parsed.get("classification") or "").upper() not in {
        "CONFIRMS", "STRENGTHENS", "WEAKENS", "INVALIDATES", "NO_NEW_INFO",
        "CONFLICTED", "INSUFFICIENT_DATA",
    }:
        return {"skipped": True, "reason": "structured_delta_classification_required"}
    memberships = {str(x).upper() for x in (prompt_context.get("memberships") or [])}
    material = bool(memberships & {"HELD", "REENTRY", "WATCH", "WATCHLIST", "PROPOSAL", "T0", "T1"})
    if not symbol or not material:
        return {"skipped": True, "reason": "non_material_symbol"}
    try:
        from lib.cio_product_reassessment import reassess_on_research_completed
    except ImportError:
        from scripts.lib.cio_product_reassessment import reassess_on_research_completed
    result = dict(parsed)
    result.update({
        "result_id": f"hermes_external_research:{rid}",
        "research_id": str(rid),
        "symbol": symbol,
        "status": "completed",
        "provider": args.lane,
        "model": args.model,
        "prompt_context": prompt_context,
    })
    return reassess_on_research_completed(
        {
            "plan_id": f"external_research_{rid}",
            "symbol": symbol,
            "question": args.question,
            "prompt_context": prompt_context,
        },
        result,
        critique={"verdict": "VALID"},
        root=ROOT,
        notify=True,
    )


def _get_key(env_name):
    key = os.environ.get(env_name)
    if not key:
        for ln in (ROOT / ".env").read_text().splitlines():
            if ln.startswith(env_name + "="):
                key = ln.split("=", 1)[1].strip()
    if not key:
        raise RuntimeError(f"no {env_name} in environment — operator must set it; key is never stored by this tool")
    return key


def _codex_authed():
    """True if the openai-codex OAuth login is present (free ChatGPT-subscription route)."""
    import subprocess
    try:
        out = subprocess.run([HERMES_CLI, "auth", "list"], capture_output=True, text=True, timeout=15).stdout
        if "openai-codex" in out.lower() or "codex" in out.lower():
            return True
    except Exception:
        pass
    # auth.json may hold codex creds
    aj = Path.home() / ".hermes" / "auth.json"
    try:
        return "codex" in aj.read_text().lower() if aj.exists() else False
    except Exception:
        return False


def _call_codex_proxy(model, prompt, timeout=240):
    """ChatGPT via the local ChatGPT OAuth proxy (scripts/chatgpt_oauth_proxy.py, :8646) — the same free
    openai-codex OAuth, served OpenAI-compatible so ALL Hermes tasks can use it headless. Returns None if the
    proxy is unreachable/unauthenticated (caller falls back to the CLI)."""
    import os as _os
    base = _os.environ.get("CHATGPT_PROXY_URL", "http://127.0.0.1:8646").rstrip("/")
    try:
        import requests
        h = requests.get(base + "/health", timeout=4).json()
        if not h.get("authenticated") or h.get("token_expired"):
            return None  # proxy up but session not usable → let caller decide (CLI / auth hint)
        _account_from_env("ATTEMPTED", reason="chatgpt_oauth_proxy", attempt_no=1)
        r = requests.post(base + "/v1/chat/completions",
                          json={"model": model or "gpt-5.4", "messages": [{"role": "user", "content": prompt}]},
                          timeout=timeout)
        if r.status_code == 401:
            return None
        r.raise_for_status()
        return (r.json().get("choices") or [{}])[0].get("message", {}).get("content", "") or None
    except Exception:
        return None


def call_codex_cli(model, prompt):
    """ChatGPT via the FREE openai-codex OAuth (no API key, no metered billing). Prefers the local ChatGPT
    OAuth proxy (:8646, works headless for any Hermes task); falls back to the pseudo-TTY one-shot CLI."""
    # 1) Proxy first — works headless and is shared by all Hermes tasks.
    via_proxy = _call_codex_proxy(model, prompt)
    if via_proxy:
        return via_proxy
    # 2) Fallback: direct CLI under a pseudo-TTY.
    import subprocess
    if not _codex_authed():
        raise RuntimeError("AUTH_PENDING: openai-codex not logged in. Operator must run: "
                           "hermes auth add openai-codex --type oauth (free under ChatGPT subscription).")
    _account_from_env("FALLBACK", reason="oauth_proxy_to_cli", attempt_no=2,
                      fallback_from="chatgpt_oauth_proxy")
    _account_from_env("ATTEMPTED", reason="openai_codex_cli", attempt_no=2)
    import shlex, re
    inner = f"{shlex.quote(HERMES_CLI)} -z {shlex.quote(prompt)} --provider openai-codex"
    if model:
        inner += f" -m {shlex.quote(model)}"
    r = subprocess.run(["script", "-qec", inner, "/dev/null"], capture_output=True, text=True, timeout=240,
                       env={**os.environ, "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}"})
    out = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", r.stdout or "").replace("\r", "").strip()
    if (not out) or out.lower().startswith("hermes -z:") or "no final response" in out.lower() or "treating the run as failed" in out.lower():
        raise RuntimeError("CODEX_HEADLESS_UNAVAILABLE: openai-codex is authed but did not finalize a "
                           "response even under a pseudo-TTY (proxy at :8646 also unavailable — re-login: "
                           "hermes auth add openai-codex --type oauth).")
    return out


def call_xai_proxy(url, model, prompt, max_tokens=1500):
    """Grok via the FREE xAI OAuth proxy (hermes proxy start --provider xai). No xAI API key.
    The proxy attaches the real OAuth creds; any bearer token works. auth_pending if proxy not running."""
    import socket as _s
    from urllib.parse import urlparse as _up
    u = _up(url)
    try:
        with _s.create_connection((u.hostname, u.port or 8645), timeout=4):
            pass
    except Exception:
        raise RuntimeError("AUTH_PENDING: xAI OAuth proxy not reachable. Operator must run: "
                           "hermes auth add xai-oauth --type oauth ; hermes proxy start --provider xai")
    body = json.dumps({"model": model, "max_tokens": max_tokens,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": "Bearer hermes-proxy", "content-type": "application/json"})
    _account_from_env("ATTEMPTED", reason="xai_oauth_proxy", attempt_no=1)
    resp = json.loads(urlopen_retry(req, timeout=120))
    return resp.get("choices", [{}])[0].get("message", {}).get("content", "")


def _import_llm_generate():
    """scripts/llm_lane.py — never scripts/lib/llm_lane (that module does not exist).

    The 2026-08-13..21 DeepSeek store was 100% `[ERROR] No module named 'lib.llm_lane'`
    because this file imported `lib.llm_lane` while sys.path has scripts/lib as `lib`.
    """
    try:
        from llm_lane import generate
        return generate
    except ImportError:
        from scripts.llm_lane import generate  # type: ignore
        return generate


def call_governed_deepseek(model, prompt, max_tokens=1500):
    """DeepSeek V4 Flash via llm_lane.generate → gate_and_generate.

    This is the SCHEDULER path (research_scheduler subprocesses this file).
    Cost-governed, circuit-breakered, fail-closed (no silent local fallback).
    """
    generate = _import_llm_generate()
    accounting_meta = {
        "research_run_id": os.getenv("TRADEAI_LLM_RUN_ID") or None,
        "research_call_id": os.getenv("TRADEAI_LLM_CALL_ID") or None,
        "research_producer": os.getenv("TRADEAI_LLM_PRODUCER") or None,
        "research_family": os.getenv("TRADEAI_LLM_FAMILY") or None,
        "symbol": os.getenv("TRADEAI_LLM_SYMBOL") or None,
        "trigger": os.getenv("TRADEAI_LLM_TRIGGER") or None,
    }
    text = generate(
        prompt,
        lane="deepseek-flash",
        process_id="hermes_external_research",
        task_summary="hermes_external_research"[:160],
        timeout=120,
        max_tokens=int(max_tokens or 2048),
        metadata={k: v for k, v in accounting_meta.items() if v},
    )
    return str(text or "").strip()


def call_external(lane, model, prompt, max_tokens=1500):
    cfg = LANE_CFG[lane]
    if cfg["kind"] == "codex_cli":
        return call_codex_cli(model, prompt)
    if cfg["kind"] == "xai_proxy":
        return call_xai_proxy(cfg["url"], model, prompt)
    if cfg["kind"] == "governed_deepseek":
        return call_governed_deepseek(model, prompt, max_tokens=max_tokens)
    key = _get_key(cfg["key_env"])
    if cfg["kind"] == "anthropic":
        body = json.dumps({"model": model, "max_tokens": max_tokens,
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request(cfg["url"], data=body, headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        _account_from_env("ATTEMPTED", reason="anthropic_api", attempt_no=1)
        resp = json.loads(urlopen_retry(req, timeout=120))
        return "".join(p.get("text", "") for p in resp.get("content", []) if p.get("type") == "text")
    # openai-compatible (chatgpt + grok)
    body = json.dumps({"model": model, "max_tokens": max_tokens,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(cfg["url"], data=body, headers={
        "Authorization": f"Bearer {key}", "content-type": "application/json"})
    _account_from_env("ATTEMPTED", reason="openai_compatible_api", attempt_no=1)
    resp = json.loads(urlopen_retry(req, timeout=120))
    return resp.get("choices", [{}])[0].get("message", {}).get("content", "")


CAP_CACHE = ROOT / "data" / "runtime" / "hermes_llm_capabilities.json"

# Auth-failure circuit breaker: 6,133 Grok HTTP-403 error rows landed in one week because every
# producer kept re-attempting a lane whose OAuth was rejecting. If the last N stored calls on a
# lane inside the window are ALL 401/403 errors, skip the call (DEFER) — never fall back to paid.
BREAKER_N = int(os.environ.get("HERMES_LANE_BREAKER_N", "6"))
BREAKER_WINDOW_MIN = int(os.environ.get("HERMES_LANE_BREAKER_WINDOW_MIN", "60"))


def _load_env():
    for ln in (ROOT / ".env").read_text().splitlines():
        if "=" in ln and not ln.strip().startswith("#"):
            k, _, v = ln.partition("="); os.environ.setdefault(k.strip(), v.strip())


def lane_circuit_open(lane):
    """True when the lane's recent history is nothing but auth failures. Fails open on any error."""
    try:
        import psycopg2
        _load_env()
        c = psycopg2.connect(host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"), dbname=os.getenv("DB_NAME"),
                             user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"))
        cur = c.cursor()
        cur.execute("""SELECT status, recommendation FROM hermes_external_research
                       WHERE lane=%s AND created_at >= NOW() - (%s || ' minutes')::interval
                       ORDER BY created_at DESC LIMIT %s""", (lane, BREAKER_WINDOW_MIN, BREAKER_N))
        rows = cur.fetchall()
        c.close()
        if len(rows) < BREAKER_N:
            return False
        return all(st == "error" and ("HTTP 403" in (rec or "") or "HTTP 401" in (rec or ""))
                   for st, rec in rows)
    except Exception:
        return False


def read_capability(lane):
    """Return the cached capability dict for a lane, or {} if absent/unreadable."""
    try:
        return json.loads(CAP_CACHE.read_text()).get("lanes", {}).get(lane, {})
    except Exception:
        return {}


def cache_blocks_lane(cap, force_retest):
    """True if the capability cache says this lane is not headless-ready and we're inside the retest window.
    Prevents re-running a known-bad path (e.g. Codex headless) on every status check."""
    if force_retest:
        return False
    hs = cap.get("headless_status")
    if not hs or hs == "ready":
        return False
    nb = cap.get("next_retest_not_before")
    if nb:
        from datetime import datetime
        try:
            if datetime.now().isoformat() >= nb:   # retest window elapsed → allow one attempt
                return False
        except Exception:
            pass
    return True   # known-blocked and (no retest date, or not yet due)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lane", default="claude", choices=["claude", "chatgpt", "grok", "deepseek"])
    ap.add_argument("--question", required=True)
    ap.add_argument("--symbol", default=None)
    ap.add_argument("--priority", default="P1")
    ap.add_argument("--trigger", default="manual")
    ap.add_argument("--model", default=None, help="override; defaults to the lane's cost-aware model")
    ap.add_argument("--apply", action="store_true", help="actually call the external model (default dry-run)")
    ap.add_argument("--force-retest", action="store_true",
                    help="bypass the capability cache and re-attempt a known-blocked lane (e.g. Codex headless)")
    ap.add_argument("--max-output-tokens", type=int, default=None,
                    help="sandbox/override only; cron does not pass this. Process registry still caps production.")
    ap.add_argument("--prompt-file", default=None,
                    help="sandbox only: replace PROMPT template ({question}/{context} placeholders). Cron unused.")
    ap.add_argument("--no-store", action="store_true",
                    help="sandbox: do not INSERT into hermes_external_research")
    ap.add_argument("--run-id", default=None, help="accounting run identity supplied by the producer")
    ap.add_argument("--call-id", default=None, help="stable accounting call identity supplied by the producer")
    ap.add_argument("--producer", default="hermes_external_researcher")
    ap.add_argument("--family", default=None, choices=["A", "B", "MANUAL", "REGISTERED"])
    args = ap.parse_args()
    if not args.model:
        args.model = LANE_CFG[args.lane]["default_model"]
    family = args.family or ("MANUAL" if args.trigger == "manual" else "REGISTERED")
    run_id, call_id = accounting_identity(
        producer=args.producer, family=family, symbol=args.symbol, lane=args.lane,
        run_id=args.run_id, call_id=args.call_id,
    )
    terminal_recorded = False

    def account(event: str, *, reason: str | None = None, attempt_no: int = 0, metadata=None):
        nonlocal terminal_recorded
        try:
            append_call_event(
                event, producer=args.producer, family=family, run_id=run_id,
                call_id=call_id, symbol=args.symbol, lane=args.lane,
                trigger=args.trigger, reason=reason, attempt_no=attempt_no,
                apply=args.apply, metadata=metadata,
            )
            if event in {"DRY_RUN", "DEDUPED", "SKIP_GATED", "COMPLETED", "ERROR", "COST_CAP_EXCEEDED"}:
                terminal_recorded = True
        except Exception as exc:
            print(f"[accounting] error={type(exc).__name__}:{exc}")

    def close_unfinished_accounting() -> None:
        if not terminal_recorded:
            account("ERROR", reason="PROCESS_EXIT_WITHOUT_TERMINAL")

    atexit.register(close_unfinished_accounting)

    account("SCHEDULED", metadata={"priority": args.priority, "model": args.model})
    os.environ["TRADEAI_LLM_RUN_ID"] = run_id
    os.environ["TRADEAI_LLM_CALL_ID"] = call_id
    os.environ["TRADEAI_LLM_PRODUCER"] = args.producer
    os.environ["TRADEAI_LLM_FAMILY"] = family
    os.environ["TRADEAI_LLM_SYMBOL"] = args.symbol or ""
    os.environ["TRADEAI_LLM_LANE"] = args.lane
    os.environ["TRADEAI_LLM_TRIGGER"] = args.trigger

    # Budget guard (central chokepoint): any producer that shells through this script is gated.
    # Hard-enforce the broad-universe-no-LLM invariant + fail-closed for unknown triggers. The
    # deliberate paid (claude) oversight lane is operator-authorized and not auto-blocked here; the
    # "no paid fallback" rule is enforced where automated lane-selection happens (the budget guard).
    args.budget_decision = "ALLOW"
    try:
        from hermes_research_budget_guard import decide as _bdecide
        _trig = (args.trigger or "manual").split(":")[0]   # normalize 'paper_postmortem:13' -> 'paper_postmortem'
        _lk = "cloud_paid" if args.lane in ("claude", "deepseek") else "cloud_" + args.lane
        _gd = _bdecide(symbol=args.symbol or "_", trigger_source=_trig, research_type="external_research",
                       lane=_lk, urgency=args.priority)
        args.budget_decision = _gd["decision"]
        # Enforce only the broad-universe / cold / fail-closed cuts. Never block the paid oversight lane.
        if _gd["decision"] in ("METADATA_ONLY", "BLOCK") and _gd["tier"] in ("T3", "T4", "UNKNOWN") and args.lane != "claude":
            print(f"\n[budget-guard] {args.lane}/{_trig} -> {_gd['decision']} (tier={_gd['tier']}): {_gd['reason']}")
            print("  broad-universe / cold / unknown trigger — no external LLM call. (metadata-only path elsewhere.)")
            account("SKIP_GATED", reason=f"BUDGET_GUARD_{_gd['decision']}", metadata={"tier": _gd["tier"]})
            return
    except Exception as _be:
        print(f"[budget-guard] advisory check skipped: {_be}")

    _load_env()
    question = redact(args.question)
    ctx = canonical_prompt_context(args.symbol, question)
    from lib.research_data_quality import assess_prompt_context
    input_quality = assess_prompt_context(ctx)
    ctx["research_data_quality"] = input_quality
    if not input_quality["provider_call_allowed"]:
        print("\n[DATA_QUALITY_BLOCK] no provider call: " + ",".join(input_quality["reason_codes"]))
        print("Create/refresh the deterministic market-data acquisition gap before retrying.")
        account("SKIP_GATED", reason="DATA_QUALITY_BLOCK", metadata={"reason_codes": input_quality["reason_codes"]})
        return
    # .format() breaks on the appended JSON schema's literal {braces} — every call
    # since ~2026-07-02 died with KeyError before reaching any API (lanes "stalled").
    # Placeholder substitution must not interpret the schema as format fields.
    prompt_template = PROMPT
    if args.prompt_file:
        prompt_template = Path(args.prompt_file).read_text(encoding="utf-8")
    prompt = prompt_template.replace("{question}", question).replace("{context}", json.dumps(ctx))
    max_out = args.max_output_tokens

    print(f"=== Hermes External Researcher — lane={args.lane} model={args.model} apply={args.apply} ===")
    print("REDACTED packet that WOULD be sent:")
    print(json.dumps({"question": question, "context": ctx}, indent=2)[:1200])
    if not args.apply:
        print("\n(dry-run — nothing sent. Re-run with --apply to call the external model.)")
        account("DRY_RUN", reason="provider_not_called")
        return

    if lane_circuit_open(args.lane):
        print(f"\n[circuit-breaker] lane={args.lane} OPEN — last {BREAKER_N} calls in {BREAKER_WINDOW_MIN}m "
              f"were all HTTP 401/403. Deferring (no call, no row); re-auth the lane "
              f"(hermes auth add …) and the breaker self-closes on the next non-403 result.")
        try:
            from db_adapter import _execute
            from datetime import datetime as _dt
            _execute("""INSERT INTO alert_events (alert_uid, alert_type, symbol, severity, source_script, raw_text, created_at)
                        VALUES (%s,'system_health',NULL,'warning','hermes_external_researcher',%s,NOW())
                        ON CONFLICT (alert_uid) DO NOTHING""",
                     (f"lane_breaker_{args.lane}_{_dt.now().strftime('%Y%m%d%H')}",
                      f"Hermes lane '{args.lane}' circuit OPEN: {BREAKER_N} consecutive HTTP 401/403 — "
                      f"external calls deferred until re-auth."), fetch=None)
        except Exception:
            pass
        account("SKIP_GATED", reason="LANE_CIRCUIT_OPEN")
        return

    import psycopg2
    _load_env()

    # Capability-cache gate: don't re-run a known-blocked lane (e.g. Codex headless) on every call.
    cap = read_capability(args.lane)
    if cache_blocks_lane(cap, args.force_retest):
        reason = cap.get("reason_code", "unavailable")
        status = cap.get("headless_status", "unavailable")
        guidance = cap.get("guidance") or f"{args.lane} headless is {status} ({reason}); see capability cache."
        print(f"\n[capability-cache] {args.lane} skipped — headless_status={status} reason={reason}")
        print(f"  {guidance}")
        print(f"  (override with --force-retest; next auto-retest: {cap.get('next_retest_not_before') or cap.get('next_retest_condition')})")
        parsed = {"recommendation": f"[{status.upper()}] {guidance} (cached reason: {reason}; not retried)"}
        c = psycopg2.connect(host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"), dbname=os.getenv("DB_NAME"),
                             user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD")); cur = c.cursor()
        cur.execute("""INSERT INTO hermes_external_research
            (lane, trigger_reason, priority, symbol, question, redacted_context, model, status, recommendation)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (args.lane, args.trigger, args.priority, args.symbol, question, json.dumps(ctx), args.model,
             status, parsed["recommendation"]))
        rid = cur.fetchone()[0]; c.commit(); c.close()
        print(f"stored hermes_external_research id={rid} status={status} (cache-gated, no external call)")
        account("SKIP_GATED", reason="CAPABILITY_CACHE", metadata={"status": status, "reason_code": reason})
        return

    status, parsed, raw = "sent", {}, ""
    try:
        raw = call_external(args.lane, args.model, prompt, max_tokens=max_out or 4096)
        parsed = parse_external_research_result(raw) or {}
        from lib.research_data_quality import validate_research_output
        output_quality = validate_research_output(
            "\n".join([str(raw or ""), str(parsed.get("recommendation") or "")])
        )
        if not output_quality["accepted"]:
            status = "rejected_data_quality"
            parsed = {
                "recommendation": "[REJECTED_DATA_QUALITY] " + ",".join(output_quality["reason_codes"]),
                "risk_flags": output_quality["reason_codes"],
                "operator_action": "REFRESH_DETERMINISTIC_DATA",
            }
        # Truncated JSON stored status=sent with recommendation=NULL.
        # RAW-store health treats empty as an error streak. Keep the prose.
        if status == "sent" and not str(parsed.get("recommendation") or "").strip() and str(raw or "").strip():
            parsed["recommendation"] = str(raw).strip()[:4000]
    except urllib.error.HTTPError as he:
        detail = ""
        try:
            detail = json.loads(he.read()).get("error", {}).get("message", "")
        except Exception:
            detail = str(he)
        status = "error"; parsed = {"recommendation": f"[ERROR HTTP {he.code}] {detail}"[:300], "error": detail[:300]}
    except Exception as e:
        msg = str(e)[:240]
        # Budget throttle is not a lane failure. A third of the desk was
        # buried in error_streak=0 because COST_CAP_EXCEEDED wrote [ERROR].
        if "COST_CAP_EXCEEDED" in msg:
            status = "skipped"
            rec = f"[SKIPPED_BUDGET] {args.symbol or '_'} {msg}"
            parsed = {"recommendation": rec, "error": msg, "skip_code": "SKIPPED_BUDGET"}
        else:
            status = ("auth_pending" if "AUTH_PENDING" in msg else
                      "unavailable" if "UNAVAILABLE" in msg else "error")
            parsed = {"recommendation": f"[{status.upper()}] {msg}", "error": msg}
    if getattr(args, "no_store", False):
        print(json.dumps({
            "stored": False,
            "sandbox": True,
            "status": status,
            "symbol": args.symbol,
            "max_output_tokens": max_out,
            "recommendation": (parsed.get("recommendation") or "")[:4000],
            "dissent": parsed.get("dissent"),
            "evidence": parsed.get("evidence"),
            "raw_chars": len(raw or ""),
            "rec_chars": len(str(parsed.get("recommendation") or "")),
            "raw": (raw or "")[:8000],
        }, indent=2, default=str))
        if status == "skipped":
            account("COST_CAP_EXCEEDED", reason=parsed.get("error") or "COST_CAP_EXCEEDED", attempt_no=1)
        elif status in {"sent", "rejected_data_quality"}:
            account("COMPLETED", reason=status, attempt_no=1)
        else:
            account("ERROR", reason=f"provider_status:{status}", attempt_no=1)
        return
    c = psycopg2.connect(host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"), dbname=os.getenv("DB_NAME"),
                         user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD")); cur = c.cursor()
    cur.execute("""INSERT INTO hermes_external_research
        (lane, trigger_reason, priority, symbol, question, redacted_context, model, status,
         recommendation, evidence_json, dissent, confidence, risk_flags, learning_candidate, operator_action,
         trigger_source, budget_decision, lane_used, raw_response)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (args.lane, args.trigger, args.priority, args.symbol, question, json.dumps(ctx), args.model, status,
         parsed.get("recommendation"), json.dumps(parsed.get("evidence", [])), parsed.get("dissent"),
         parsed.get("confidence"), json.dumps(parsed.get("risk_flags")), parsed.get("learning_candidate"),
         parsed.get("operator_action"),
         (args.trigger or "manual").split(":")[0], getattr(args, "budget_decision", "ALLOW"), args.lane,
         str(raw)[:16000]))
    rid = cur.fetchone()[0]; c.commit(); c.close()
    print(f"\nstored hermes_external_research id={rid} status={status}")
    if status == "skipped":
        account("COST_CAP_EXCEEDED", reason=parsed.get("error") or "COST_CAP_EXCEEDED", attempt_no=1,
                metadata={"research_id": rid})
        print("SKIPPED_BUDGET", args.symbol or "_", parsed.get("error") or "")
    elif status == "sent":
        account("COMPLETED", reason="accepted", attempt_no=1, metadata={"research_id": rid})
        print("recommendation:", (parsed.get("recommendation") or "")[:200])
        try:
            reconciliation = reconcile_accepted_research(args.symbol, rid, parsed, ctx, args)
            print("research_thesis_reconciliation:", json.dumps(reconciliation, default=str)[:1200])
        except Exception as exc:
            print(f"research_thesis_reconciliation: ERROR {type(exc).__name__}:{exc}")
    elif status == "rejected_data_quality":
        account("COMPLETED", reason="REJECTED_DATA_QUALITY", attempt_no=1, metadata={"research_id": rid})
    else:
        account("ERROR", reason=f"provider_status:{status}", attempt_no=1, metadata={"research_id": rid})


if __name__ == "__main__":
    main()
