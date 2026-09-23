"""CIO operator desk loop — DeepSeek analyzes; Trade-AI supplies truth.

Contract (READ_ONLY_ADVISORY):
  1. Flash analyzes what the operator is asking (intent JSON only).
  2. Evidence is pulled only from controlled Trade-AI artifacts
     (re-entry desk, CIO snapshot / Data Broker paths) — never invented by the model.
  3. meta_system asks (which LLM, how Alex works) answer from runtime policy facts —
     never dump re-entry READY/NEAR cards.
  4. freeform asks → soft Trade-AI gather + Flash grounded answer (general reasoning
     OK; numbers only from facts; gaps flagged; optional Hermes soft-queue).
  5. If required desk evidence is missing → register a gap, ack the operator
     ("pulling into Trade-AI — will reply when it lands"), and ledger a pending reply.
  6. When evidence arrives → fulfill pending and Telegram-reply with vetted facts.
  7. Flash may only rewrite wording of vetted desk facts for Telegram clarity.

No broker / order / stop / 2FA authority.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PENDING_PATH = PROJECT_ROOT / "data" / "cio" / "cio_operator_pending_replies.jsonl"
AUTHORITY = "READ_ONLY_ADVISORY"

#: Buy / perspective asks must not lead with a hollow DeepSeek reword of thin
#: house facts (live 2026-09-22: "im thinking of buying S give me the perspective"
#: → Sep-04 STALE price essay + queue footnote). Research-then-ack instead.
_BUY_PERSPECTIVE_RE = re.compile(
    r"(?is)\b("
    r"thinking\s+of\s+buying|considering\s+(?:a\s+)?buy|want\s+to\s+buy|"
    r"should\s+i\s+buy|worth\s+buying|give\s+me\s+(?:the\s+)?perspective|"
    r"(?:your|the)\s+perspective|buy\s+perspective|"
    # Deliberately NOT "is it a buy" — that is the analyst-target litmus
    # ("is it a buy and what's the target") and must stay needs=['analyst_view'].
    r"good\s+investment|investment\s+perspective"
    r")\b"
)
#: technicals.stale_after_hours in data_source_authority (26h).
_QUOTE_STALE_HOURS = 26.0

SendFn = Callable[..., dict[str, Any]]

# Desk-trading needs that pull market/book evidence
_DESK_NEEDS = frozenset({
    "reentry_ready",
    "reentry_levels",
    "cash",
    "portfolio",
    "risk",
    "research",
    # "is it a buy / what's the target" is an ANALYST question, and answering it
    # from research rows gave the operator three stop-curation reviews on
    # 2026-09-13. The data was already on file and nothing read it.
    "analyst_view",
})
_RUNTIME_NEEDS = frozenset({"runtime_llm", "runtime_status"})
_META_HEURISTIC = re.compile(
    r"(?is)\b("
    r"llm|model(?!\s+portfolios?)|deepseek|flash|pro\b|"
    r"which\s+(?:ai|model(?!\s+portfolios?)|llm)|"
    r"what\s+(?:\w+\s+){0,4}(?:using|model(?!\s+portfolios?)|llm)|"
    r"how\s+(?:do\s+)?you\s+work|"
    r"bot\s+status|what\s+version|which\s+version"
    r")\b"
    # "read only" / "authority" are meta only when ASKED about the bot. As a bare
    # word they were a disclaimer: "What should I watch on SCHD this week?
    # READ_ONLY advisory only." routed to runtime facts and never touched SCHD.
    r"|\b(?:are|is)\s+(?:you|alex|it|this|the\s+bot)\s+(?:\w+\s+)?read[_\s-]?only\b"
    r"|\bread[_\s-]?only\s*\?"
    r"|\b(?:what|which)\s+(?:is\s+)?(?:your\s+)?authority\b"
    r"|\b(?:your|alex'?s)\s+authority\b"
    r"|\bauthority\s+(?:do|does)\s+(?:you|alex)\b"
)
_FREEFORM_HEURISTIC = re.compile(
    r"(?is)\b("
    r"explain|compare|versus|\bvs\.?\b|summarize|summary|"
    r"thoughts|opinion|posture|fit(?:s|ting)?|"
    r"should\s+i\s+think|what\s+do\s+you\s+think|"
    r"tell\s+me\s+about|walk\s+me\s+through"
    r")\b"
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _env(k: str, default: str = "") -> str:
    return (os.environ.get(k) or default).strip()


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except Exception:
        return []
    return rows


def _looks_like_meta_system(text: str) -> bool:
    return bool(_META_HEURISTIC.search(text or ""))


def _looks_like_freeform(text: str) -> bool:
    return bool(_FREEFORM_HEURISTIC.search(text or ""))


def load_runtime_llm_facts() -> dict[str, Any]:
    """Vetted runtime / policy facts for meta_system answers. Fail-soft."""
    facts: dict[str, Any] = {
        "authority": AUTHORITY,
        "converse_path": "call_governed_llm",
        "use_pro_default": False,
        "model_flash": "deepseek-flash",
        "model_pro": "deepseek-flash",
        "prefer_flash": True,
        "policy_path": "config/cio_llm_policy.yaml",
        "bridge_endpoint": None,
        "caller_flash": None,
        "gaps": [],
    }
    try:
        from scripts.lib.cio_plan_enrichment import load_llm_policy

        policy = load_llm_policy() or {}
        llm = policy.get("llm") if isinstance(policy.get("llm"), dict) else {}
        facts["prefer_flash"] = bool(llm.get("prefer_flash", True))
        facts["bridge_endpoint"] = llm.get("bridge_endpoint")
        facts["caller_flash"] = llm.get("caller_flash")
        facts["caller_pro"] = llm.get("caller_pro")
        facts["policy_enabled"] = bool(policy.get("enabled", True))
        # Hardcoded bridge model ids from call_governed_llm (use_pro=False → flash)
        facts["model_flash"] = "deepseek-flash"
        facts["model_pro"] = "deepseek-flash"
        facts["operator_intent_uses"] = "deepseek-flash (use_pro=False)"
    except Exception as exc:
        facts["gaps"].append(f"policy:{type(exc).__name__}:{exc}")
    if not facts.get("bridge_endpoint"):
        facts["gaps"].append("bridge_endpoint:DATA_UNAVAILABLE")
    return facts


def format_meta_system_reply(facts: dict[str, Any], *, operator_text: str = "") -> str:
    """Deterministic meta answer — no market numbers, no re-entry dump."""
    flash = facts.get("model_flash") or "DATA_UNAVAILABLE"
    pro = facts.get("model_pro") or "DATA_UNAVAILABLE"
    bridge = facts.get("bridge_endpoint") or "DATA_UNAVAILABLE"
    lines = [
        "🧠 *Alex · runtime / LLM*",
        f"• Converse + intent classify: governed bridge **`{flash}`** "
        f"(`call_governed_llm`, `use_pro=False`)",
        f"• Pro lane (material synthesis only when policy says so): **`{pro}`**",
        f"• Policy: `{facts.get('policy_path')}` · prefer_flash="
        f"{facts.get('prefer_flash')}",
        f"• Bridge: `{bridge}`",
        f"• Authority: **{AUTHORITY}** — no orders / stops / 2FA from chat",
    ]
    gaps = facts.get("gaps") or []
    if gaps:
        lines.append("• Gaps: " + "; ".join(str(g) for g in gaps[:4]))
    lines.append("READ_ONLY_ADVISORY")
    return "\n".join(lines)


def format_unclear_reply(text: str) -> str:
    return (
        "🧠 *Alex*\n"
        "I didn't map that to a desk ask. Try one of:\n"
        "• re-entry / READY / levels\n"
        "• cash / portfolio / risk\n"
        "• which LLM / how you work\n"
        "• `/cio help`\n"
        "READ_ONLY_ADVISORY"
    )


# ── symbol extraction ────────────────────────────────────────────────────────
# 2026-09-13 18:50: "Is now a good time to get back into schg" resolved NO symbol
# because only UPPER-CASE tokens were tickers, so the desk answered with the
# book-wide re-entry dump instead of SCHG's own row. A token is a symbol when it
# is one we KNOW -- held, on the re-entry desk, or in the identity registry --
# whatever its case. Unknown tokens keep the upper-case rule.
_SYMBOL_STOP = frozenset({
    "I", "A", "THE", "AND", "OR", "TO", "FOR", "ON", "IN", "OF", "IS", "IT", "AN", "AT", "BY", "BE",
    "WHAT", "CAN", "NOW", "ETC", "DAY", "SMA", "RSI", "CIO", "READ", "ONLY", "USD", "READY", "NEAR",
    "ZONE", "STOP", "ALEX", "LLM", "YOU", "HOW", "WHICH", "USING", "MODEL", "FLASH", "PRO", "AI", "WHY",
    "GOOD", "TIME", "GET", "BACK", "INTO", "BUY", "SELL", "HOLD", "MY", "ME", "WE", "US", "DO", "DOES",
    "ARE", "WAS", "ALL", "ANY", "NOT", "NO", "YES", "OK", "SO", "IF", "AS", "UP", "OUT", "NEW", "OLD",
})
_KNOWN_SYMBOLS_CACHE: dict[str, Any] = {"at": 0.0, "syms": frozenset()}


def _known_symbols(ttl_s: float = 120.0) -> frozenset[str]:
    """The operator's BOOK: holdings + re-entry desk. These match in any case.

    The identity registry is deliberately NOT part of this set. Its branch below
    read `symbol`/`ticker` keys that registry entities do not carry (they carry
    `ticker_alias` and `aliases`), so in production it contributed nothing -- 106
    known symbols on 2026-09-13, all from the book. Reading `by_symbol` instead
    would add 5,391 symbols of which 514 are English words (BACK, INTO, CASH,
    TECH), so "get back into" would bind issuers. Registry symbols are resolved in
    `operator_subject_resolver`, upper-case or $cashtag only, with their GUID.
    """
    import time as _time
    if _time.monotonic() - float(_KNOWN_SYMBOLS_CACHE["at"]) < ttl_s and _KNOWN_SYMBOLS_CACHE["syms"]:
        return _KNOWN_SYMBOLS_CACHE["syms"]
    syms: set[str] = set()
    try:
        for p in _held_positions_map().keys():
            syms.add(p)
    except Exception:
        pass
    try:
        from scripts.lib.cio_telegram_converse import load_reentry_desk_rows
        rows, _a, _p = load_reentry_desk_rows()
        for r in rows or []:
            if isinstance(r, dict) and r.get("symbol"):
                syms.add(str(r["symbol"]).upper())
    except Exception:
        pass
    out = frozenset(s for s in syms if s and s.isalpha() and 1 <= len(s) <= 5)
    if out:
        _KNOWN_SYMBOLS_CACHE.update({"at": _time.monotonic(), "syms": out})
    return out


def _extract_symbols(text: str) -> list[str]:
    """Symbols the question names: book tickers any case, registry/unknown tickers
    upper-case, and company names the broker instrument feed resolves.

    Kept as a thin wrapper because `cio_converse_core` imports it to decide whether
    the book-wide re-entry interceptor must step aside.
    """
    try:
        from scripts.lib.operator_subject_resolver import resolve_subjects, symbols_of
        return symbols_of(resolve_subjects(text or "", book=_known_symbols()))
    except Exception:
        t = text or ""
        return [tok for tok in dict.fromkeys(re.findall(r"\b([A-Z]{1,5})\b", t))
                if tok not in _SYMBOL_STOP][:12]


def is_buy_perspective_ask(text: str) -> bool:
    """True when the operator wants a buy / investment perspective, not a price ping."""
    return bool(_BUY_PERSPECTIVE_RE.search(text or ""))


def _price_age_hours(price: dict[str, Any]) -> Optional[float]:
    """Hours since the stored close date; None when unknown."""
    if not isinstance(price, dict):
        return None
    age = price.get("age_hours")
    if age is not None:
        try:
            return float(age)
        except (TypeError, ValueError):
            pass
    pd = str(price.get("price_date") or "")[:10]
    if not pd:
        return None
    try:
        return (datetime.now(timezone.utc).date() - datetime.fromisoformat(pd).date()).days * 24.0
    except Exception:
        return None


def subject_price_is_stale(price: Optional[dict[str, Any]], *, stale_hours: float = _QUOTE_STALE_HOURS) -> bool:
    """True when a subject quote is missing, flagged stale, or older than the technicals window."""
    if not price or price.get("close") is None:
        return True
    if price.get("stale"):
        return True
    age = _price_age_hours(price)
    return age is not None and age > stale_hours


def house_research_thin(evidence: dict[str, Any]) -> bool:
    """True when no promoted Hermes rows are available for this turn's subject."""
    items = ((evidence.get("available") or {}).get("hermes_research") or {}).get("items") or []
    return not bool(items)


def buy_perspective_needs_research_first(intent: dict[str, Any], evidence: dict[str, Any]) -> bool:
    """Buy/perspective with thin research and/or stale quotes must not lead with a hollow essay."""
    if not is_buy_perspective_ask(str(intent.get("text") or "")):
        return False
    if not (intent.get("symbols") or []):
        return False
    if house_research_thin(evidence):
        return True
    prices = (evidence.get("available") or {}).get("subject_price") or {}
    syms = [str(s).upper() for s in (intent.get("symbols") or [])]
    if not prices:
        return True
    return any(subject_price_is_stale(prices.get(s)) for s in syms if s)


def _held_positions_map() -> dict[str, dict[str, Any]]:
    """symbol -> {shares, market_value, account} from holdings.json (store of record)."""
    path = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
    out: dict[str, dict[str, Any]] = {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return out
    rows = doc.get("holdings") or doc.get("positions") or []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or not r.get("symbol"):
            continue
        sym = str(r["symbol"]).upper()
        out[sym] = {
            "shares": r.get("shares", r.get("quantity")),
            "market_value": r.get("market_value"),
            "account": r.get("account") or r.get("account_id"),
            "as_of": r.get("as_of") or r.get("updated_at"),
        }
    return out


def _merge_flash_symbols(out: dict[str, Any], flash_symbols: list[Any]) -> None:
    """Flash may ADD a symbol, never remove a resolved one, and never invent one.

    Before 2026-09-13 Flash's list REPLACED the heuristic's and was then unioned
    with a re-extraction; any alphabetic string was accepted, so "SPACEX" would
    have become a symbol and the unanswerable SpaceX question a pending that could
    never close. Additions now bind only when the registry or the book holds them;
    the rest are kept, visibly, in `flash_unverified_symbols`.
    """
    from scripts.lib.operator_subject_resolver import verify_added_symbol

    symbols = list(out.get("symbols") or [])
    subjects = list(out.get("subjects") or [])
    unverified: list[str] = []
    book = _known_symbols()
    for raw in flash_symbols[:24]:
        sym = str(raw or "").strip().lstrip("$").upper()
        if not sym or sym in symbols:
            continue
        subj = verify_added_symbol(sym, book=book)
        if subj is None:
            if sym not in unverified:
                unverified.append(sym)
            continue
        symbols.append(sym)
        subjects.append(subj)
    out["symbols"] = symbols[:12]
    out["subjects"] = subjects
    if unverified:
        out["flash_unverified_symbols"] = unverified[:12]


def _stamp_answerable(out: dict[str, Any]) -> dict[str, Any]:
    """Record, on the intent itself, whether the ask can ever be answered.

    `is_answerable` was consulted only when evidence produced a BLOCKING gap. The
    SpaceX ask produced none (Agent D replay, 2026-09-13): intent analyst_view, no
    symbol, no gap, reply "Queued a pull -- I'll reply when it lands", nothing
    queued. The verdict is knowable at intent time, so it travels with the intent
    and a handler can refuse before gathering anything.
    """
    if not out.get("symbols") and out.get("text_for_candidates"):
        try:
            from scripts.lib.operator_subject_resolver import ticker_candidates
            cands = ticker_candidates(out["text_for_candidates"], book=_known_symbols())
            if cands:
                out["ticker_candidates"] = cands
        except Exception:
            pass
    out.pop("text_for_candidates", None)
    ok, why = is_answerable(out)
    out["answerable"] = ok
    out["unanswerable_reason"] = why or None
    return out


def analyze_operator_intent(text: str) -> dict[str, Any]:
    """DeepSeek Flash → structured intent. Numbers never come from this step."""
    out: dict[str, Any] = {
        "ok": False,
        "source": "heuristic",
        "model": None,
        "intent": "freeform",
        "symbols": [],
        "subjects": [],
        "needs": [],
        "error": None,
    }
    t = (text or "").strip()
    if not t:
        out["intent"] = "unclear"
        out["error"] = "empty"
        return out

    needs: list[str] = []

    # Subjects FIRST, registry-first (operator_subject_resolver), on every path.
    # `symbols` stays the flat list every caller reads; `subjects` adds kind,
    # GUID and confidence. The book is passed from THIS module so a caller that
    # patches `_known_symbols` is honoured.
    scan = t
    try:
        from scripts.lib.operator_subject_resolver import name_spans, resolve_subjects, symbols_of

        subjects = resolve_subjects(t, book=_known_symbols())
        out["subjects"] = subjects
        out["text_for_candidates"] = t   # consumed and removed by _stamp_answerable
        out["symbols"] = symbols_of(subjects)
        # A company name is not a request: "Nonesuch Holdings" asked about a
        # company, not for the operator's holdings. Intent regexes read `scan`.
        for span in name_spans(subjects):
            scan = scan.replace(span, " ")
    except Exception as exc:
        out["symbols"] = [tok for tok in dict.fromkeys(re.findall(r"\b([A-Z]{1,5})\b", t))
                          if tok not in _SYMBOL_STOP][:12]
        out["error"] = f"subjects:{type(exc).__name__}:{exc}"

    # P0: attention / why-nothing is deterministic office state, not Flash.
    if re.search(
        r"(?is)\bwhy\s+(haven'?t|have\s+not|didn'?t)\s+you\s+(?:tell|told)|"
        r"\bwhat\s+should\s+i\s+be\s+paying\s+attention\s+to\b|"
        r"\banything\s+today\b|"
        r"\bnothing\s+today\b",
        t,
    ):
        out["intent"] = "attention"
        out["needs"] = ["portfolio", "cash"]
        out["ok"] = True
        out["source"] = "heuristic"
        return _stamp_answerable(out)

    # P0: meta_system BEFORE desk defaults — never fall through to re-entry dump
    if _looks_like_meta_system(t):
        out["intent"] = "meta_system"
        if re.search(r"(?is)\b(llm|model|deepseek|flash|pro|ai)\b", t):
            needs.append("runtime_llm")
        needs.append("runtime_status")
        out["needs"] = list(dict.fromkeys(needs))
    else:
        if re.search(
            r"(?is)\bre[\s\-]?(?:entr|enter)|rentr|ready\s+to\s+(?:buy|purchase|review)|buy\s+back|"
            r"get\s+back\s+in(?:to)?\b|\bback\s+in(?:to)?\s+[A-Za-z]{1,5}\b|re-?buy|add\s+back|good\s+time\s+to\s+(?:get\s+)?(?:back\s+)?in(?:to)?\b|"
            # Adding to a position is the re-entry decision: zone, gates, levels.
            r"\badd(?:ing)?\s+(?:more\s+)?to\b(?!\s+(?:my\s+|the\s+|a\s+)?watch\s*list)|\badd\s+more\b|"
            r"\bbuy\s+more\b|\baverag(?:e|ing)\s+down\b",
            scan,
        ):
            needs.append("reentry_ready")
            out["intent"] = "reentry"
        if re.search(
            r"(?is)\b(support|suport|resistance|resistence|s/?r|50[\s\-]?day|sma\s*50|sma50|sma\s*20|levels?|stop)\b",
            scan,
        ):
            needs.append("reentry_levels")
            if out["intent"] in ("unclear", "general"):
                out["intent"] = "reentry"
        # "what's jepi doing" / "NOC price today" -- the desk row carries price,
        # RSI, SMAs and levels. Only with a resolved symbol: without one there is
        # no row, and the question belongs to the freeform agent.
        if out["symbols"] and "reentry_levels" not in needs and re.search(
            r"(?is)\b(?:what'?s|what\s+is|how'?s|how\s+is)\s+(?:my\s+)?\$?[A-Za-z]{1,5}\s+(?:doing|looking|trading)\b|"
            r"\bwhere\s+is\s+\$?[A-Za-z]{1,5}\s+trading\b|\bprice\s+(?:today|now|right\s+now)\b",
            scan,
        ):
            needs.append("reentry_levels")
        if re.search(r"(?is)\b(cash|buying\s+power)\b", scan):
            needs.append("cash")
            if out["intent"] in ("unclear", "freeform"):
                out["intent"] = "cash"
        if re.search(r"(?is)\b(portfolio|profolio|portfolo|portfollio|protfolio|porfolio|holdings|book)\b", scan):
            needs.append("portfolio")
            if out["intent"] in ("unclear", "freeform"):
                out["intent"] = "portfolio"
        if re.search(r"(?is)\b(risk|heat|drawdown|concentration)\b", scan):
            needs.append("risk")
            if out["intent"] in ("unclear", "freeform"):
                out["intent"] = "risk"
        # Trimming is a sizing question about a held position: the book and its risk.
        if re.search(
            r"(?is)\btrim(?:ming)?\b|\btake\s+(?:some\s+)?profits?\b|\bsell\s+some\b|"
            r"\breduce\s+(?:my\s+)?(?:position|exposure|stake)\b",
            scan,
        ):
            needs.extend(n for n in ("portfolio", "risk") if n not in needs)
            if out["intent"] in ("unclear", "freeform", "risk"):
                out["intent"] = "portfolio"
        # Rotation / over-/under-weight is allocation posture. A soft book hint;
        # the intent stays freeform so the freeform builder reads sector weights
        # and the investment policy.
        if re.search(
            r"(?is)\brotat(?:e|ing|ion)\s+(?:in)?to\b|\brotate\s+out\b|\b(?:over|under)[\s-]?weight(?:ed)?\b",
            scan,
        ) and "portfolio" not in needs:
            needs.append("portfolio")
        if re.search(
            r"(?is)\b(research|hermes|thesis|why\s+(?:own|hold|watch)|deep\s+dive)\b",
            scan,
        ):
            needs.append("research")
            if out["intent"] in ("unclear", "freeform"):
                out["intent"] = "research"
        # Analyst opinion and price targets. Deliberately BEFORE the freeform
        # check so "is it a buy and what's the target" reaches the analyst
        # domain rather than falling through to whatever research happens to
        # exist for the symbol. Valuation words ("is X cheap here") are the same
        # question, and the operator's typos ("anaylst") are real inputs.
        if re.search(
            r"(?is)\b(analysts?|anaylsts?|analists?|anlysts?|analsyts?|annalysts?|price\s+target|target\s+price|\bpt\b|"
            r"\ba\s+buy\b|\bbuy\s+or\s+sell\b|upgrade|downgrade|consensus|"
            r"rating|\btargets?\b|"
            r"cheap|expensive|over[\s-]?valued|under[\s-]?valued|valuation|fair\s+value)\b",
            scan,
        ):
            needs.append("analyst_view")
            if out["intent"] in ("unclear", "freeform"):
                out["intent"] = "analyst_view"
        # Buy / investment perspective: need analyst + research, never a hollow
        # price-only essay while Hermes is empty (plan Option B, live 2026-09-22).
        if out["symbols"] and is_buy_perspective_ask(scan):
            for n in ("analyst_view", "research"):
                if n not in needs:
                    needs.append(n)
            if out["intent"] in ("unclear", "freeform", "general"):
                out["intent"] = "analyst_view"

        # Explainer/comparison language → freeform (soft desk hints OK, no reentry)
        # Buy/perspective stays on the subject brief path — freeform would drop
        # research from needs and re-open the hollow-essay failure.
        if (
            _looks_like_freeform(scan)
            and out["intent"] not in ("reentry", "meta_system")
            and not is_buy_perspective_ask(scan)
        ):
            soft = [n for n in needs if n in ("portfolio", "cash", "risk", "research")]
            out["intent"] = "freeform"
            out["needs"] = list(dict.fromkeys(soft))
        # P0: NO default reentry_ready/portfolio — unmatched → freeform agent
        elif not needs:
            out["intent"] = "freeform"
            out["needs"] = []
        else:
            out["needs"] = list(dict.fromkeys(needs))

    # Flash refine (intent only) — may not override clear heuristic meta_system
    heuristic_intent = out["intent"]
    heuristic_needs = list(out["needs"])

    if _env("CIO_OPERATOR_INTENT_FLASH", "1").lower() not in ("0", "false", "off", "no"):
        try:
            from scripts.lib.cio_plan_enrichment import call_governed_llm, load_llm_policy

            system = (
                "You classify CIO Telegram operator questions. "
                "Return ONE JSON object only with keys: "
                "intent (meta_system|reentry|portfolio|cash|risk|research|analyst_view|desk_question|"
                "freeform|unclear|other), "
                "symbols (list of tickers), "
                "needs (subset of: runtime_llm, runtime_status, reentry_ready, reentry_levels, "
                "cash, portfolio, risk, research, analyst_view). "
                "Use analyst_view for analyst ratings, price targets, valuation or 'is it a buy'. "
                "Use intent=meta_system and needs runtime_llm/runtime_status for questions about "
                "which LLM/model/DeepSeek/Flash/Pro, how Alex works, authority, or bot status. "
                "For meta_system do NOT include reentry_ready or portfolio. "
                "Use freeform for general CIO conversation, comparisons, explainers, "
                "book posture, or anything not a narrow desk pull — needs may be empty "
                "or soft hints (portfolio/research) but never invent reentry_ready. "
                "Use unclear only for empty/nonsense. "
                "No prose. No invented tickers not implied by the question."
            )

            try:
                from scripts.lib.agent_untrusted_data import untrusted_delimiter
                _user_content = untrusted_delimiter(
                    content_type="operator_message", source="telegram", content=(t or "")[:800],
                )
            except Exception:
                _user_content = (t or "")[:800]
            llm = call_governed_llm(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": _user_content},
                ],
                load_llm_policy(),
                use_pro=False,
                task_type="operator_reply",
            )
            if llm.get("ok"):
                raw = str(llm.get("content") or "").strip()
                if raw.startswith("```"):
                    raw = re.sub(r"^```(?:json)?\s*", "", raw)
                    raw = re.sub(r"\s*```$", "", raw).strip()
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    flash_intent = str(parsed.get("intent") or "").strip()[:40]
                    allowed_needs = _DESK_NEEDS | _RUNTIME_NEEDS
                    flash_needs = []
                    if isinstance(parsed.get("needs"), list):
                        flash_needs = [
                            str(n) for n in parsed["needs"] if str(n) in allowed_needs
                        ]

                    # Heuristic meta wins if Flash tries to desk-route a meta ask
                    if heuristic_intent == "meta_system":
                        out["intent"] = "meta_system"
                        out["needs"] = heuristic_needs or ["runtime_llm", "runtime_status"]
                    elif flash_intent == "meta_system" or (
                        flash_needs and set(flash_needs) <= _RUNTIME_NEEDS
                    ):
                        out["intent"] = "meta_system"
                        out["needs"] = flash_needs or ["runtime_llm", "runtime_status"]
                    elif flash_intent in (
                        "reentry", "portfolio", "cash", "risk", "research", "analyst_view",
                        "desk_question", "freeform", "unclear", "other",
                    ):
                        if flash_intent in ("other", "unclear", "desk_question"):
                            out["intent"] = "freeform"
                        else:
                            out["intent"] = flash_intent
                        if out["intent"] == "freeform":
                            # Soft hints only — never force reentry onto freeform
                            out["needs"] = [
                                n for n in flash_needs
                                if n in ("portfolio", "cash", "risk", "research")
                            ]
                        elif flash_needs:
                            out["needs"] = flash_needs
                        else:
                            out["needs"] = heuristic_needs
                    else:
                        out["needs"] = flash_needs or heuristic_needs
                    # Heuristic freeform stays freeform unless Flash picked a desk intent
                    if heuristic_intent == "freeform" and out["intent"] not in (
                        "meta_system", "reentry", "portfolio", "cash", "risk", "research", "analyst_view",
                    ):
                        out["intent"] = "freeform"
                        out["needs"] = [
                            n for n in (out["needs"] or [])
                            if n in ("portfolio", "cash", "risk", "research")
                        ]

                    if isinstance(parsed.get("symbols"), list):
                        # Resolved subjects stay; Flash may only add verified ones.
                        _merge_flash_symbols(out, parsed["symbols"])
                    # A price / levels / get-back-in ask the regexes matched is a desk
                    # pull, and Flash may not demote it. 2026-09-14 AXTI: Flash said
                    # freeform, the re-entry needs were dropped, and the reply said
                    # price and support were DATA_UNAVAILABLE while the desk row held both.
                    kept = [n for n in heuristic_needs if n in ("reentry_ready", "reentry_levels")]
                    if kept and heuristic_intent != "meta_system" and out["intent"] != "meta_system":
                        if out["intent"] in ("freeform", "unclear", "other", "desk_question"):
                            out["intent"] = heuristic_intent
                        out["needs"] = list(dict.fromkeys(list(out.get("needs") or []) + kept))
                    out["ok"] = True
                    out["source"] = "deepseek_flash"
                    out["model"] = llm.get("model") or "deepseek-flash"
                    # Final guard: meta heuristic always blocks desk needs
                    if _looks_like_meta_system(t):
                        out["intent"] = "meta_system"
                        out["needs"] = [
                            n for n in (out["needs"] or []) if n in _RUNTIME_NEEDS
                        ] or ["runtime_llm", "runtime_status"]
                    return _stamp_answerable(out)
            out["error"] = str(llm.get("error") or "intent_flash_failed")
        except Exception as exc:
            out["error"] = f"intent:{type(exc).__name__}:{exc}"

    out["ok"] = True  # heuristic is acceptable
    return _stamp_answerable(out)


def _domain_payload(snap: dict[str, Any], name: str) -> dict[str, Any]:
    domains = snap.get("domains") or {}
    d = domains.get(name) or {}
    if isinstance(d, dict) and "data" in d and d.get("data") is not None:
        return d.get("data") if isinstance(d.get("data"), dict) else {"value": d.get("data")}
    return d if isinstance(d, dict) else {}


def _research_db_query(sql: str, params: Any = None, fetch: str = "all") -> list[dict[str, Any]]:
    """Read-only query for the broker's research projections. Lazy driver import.

    A read-only session, a 5 s statement timeout, dict rows. Raises on failure --
    search_research() turns that into an envelope with ``ok: False`` and no rows.
    """
    import psycopg2  # noqa: PLC0415
    import psycopg2.extras  # noqa: PLC0415

    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        dbname=os.environ.get("DB_NAME", "trade_ai"),
        user=os.environ.get("DB_USER", "trade_ai"),
        password=os.environ.get("DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD"),
        connect_timeout=3,
        options="-c statement_timeout=5000",
    )
    try:
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() if fetch == "all" else [cur.fetchone()]
        return [dict(r) for r in rows if r is not None]
    finally:
        conn.close()


def _broker_subject_research():
    """The subject_research projection module under whichever spelling imports."""
    try:
        from scripts.lib.data_broker import subject_research as mod  # noqa: PLC0415
    except ImportError:
        from lib.data_broker import subject_research as mod  # type: ignore[no-redef]  # noqa: PLC0415
    return mod


#: Summaries that report a research run found nothing usable.
_RESEARCH_NON_FINDING = re.compile(
    r"(?i)(none\s+of\s+which\s+address|weak\s+or\s+no\s+applicability|returned\s+no\s+(?:usable\s+)?(?:sources|results)|"
    r"no\s+relevant\s+sources|could\s+not\s+find\s+(?:any\s+)?(?:relevant|usable))"
)


def search_topic_research(question: str, *, limit: int = 5) -> dict[str, Any]:
    """House research on a THEME (no symbol), read through the broker, before any model.

    Returns {keywords, items, as_of, ok, error?}. Items carry topic / summary /
    symbol / research_type / as_of only -- what the research SAYS, never a count.
    Fail-soft: an unreachable DB is ``ok: False`` with no items, and the caller
    says there is no house research rather than pretending the model's
    general knowledge is Trade-AI's.
    """
    try:
        mod = _broker_subject_research()
        kws = mod.salient_keywords(question)
        res = mod.search_research(_research_db_query, kws, limit=limit)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "keywords": [], "items": [], "as_of": None, "error": f"{type(exc).__name__}"}
    items = []
    for r in res.get("items") or []:
        body = str(r.get("summary") or r.get("thesis") or "")
        # Measured 2026-09-13 on the live table: promoted rows whose summary is the
        # crawler reporting it found nothing ("none of which address…", "weak or no
        # applicability"). A note that research failed is not research on the topic.
        if _RESEARCH_NON_FINDING.search(body):
            continue
        created = str(r.get("created_at") or "")[:10] or None
        items.append({
            "topic": (r.get("topic") or "")[:160] or None,
            "summary": (r.get("summary") or r.get("thesis") or "")[:300] or None,
            "symbol": r.get("symbol"),
            "research_type": r.get("research_type"),
            "sector": r.get("gics_sector") or r.get("category_sector"),
            "keyword_hits": r.get("keyword_hits"),
            "as_of": created,
        })
    out = {"ok": bool(res.get("ok")), "keywords": (res.get("key") or {}).get("keywords") or [],
           "items": items, "as_of": res.get("as_of"), "stale": res.get("stale")}
    if res.get("error"):
        out["error"] = str(res["error"])[:120]
    return out


def _cash_facts(snap: dict[str, Any], total_value: Any) -> Optional[dict[str, Any]]:
    """cash_buying_power -> facts. The payload keys are total_cash /
    total_buying_power_estimate / cash_positions; cash_pct is derived. None when absent."""
    cash = _domain_payload(snap, "cash_buying_power")
    nested = cash.get("data") if isinstance(cash.get("data"), dict) else {}
    total_cash = cash.get("total_cash", nested.get("total_cash", cash.get("cash")))
    buying_power = cash.get("total_buying_power_estimate",
                            nested.get("total_buying_power_estimate", nested.get("buying_power", cash.get("buying_power"))))
    if not cash or (total_cash is None and buying_power is None):
        return None
    cash_positions = cash.get("cash_positions") or nested.get("cash_positions") or []
    try:
        cash_pct = (round(float(total_cash) / float(total_value) * 100.0, 1)
                    if total_cash is not None and total_value else cash.get("cash_pct", nested.get("cash_pct")))
    except (TypeError, ValueError, ZeroDivisionError):
        cash_pct = None
    env = ((snap.get("domains") or {}).get("cash_buying_power") or {})
    return {
        "total_cash": total_cash,
        "cash_pct": cash_pct,
        "buying_power": buying_power,
        "by_account": [
            {"account": cp.get("account"), "cash": cp.get("market_value")}
            for cp in sorted((c for c in cash_positions if isinstance(c, dict)),
                             key=lambda c: -(c.get("market_value") or 0))
        ][:8],
        "quality_state": cash.get("quality_state") or cash.get("state") or env.get("quality_state"),
        "source": cash.get("source") or nested.get("source"),
        "as_of": cash.get("as_of") or nested.get("as_of"),
    }


def _portfolio_facts(snap: dict[str, Any]) -> Optional[dict[str, Any]]:
    port = _domain_payload(snap, "portfolio")
    if not port or port.get("total_value") is None:
        return None
    return {
        "total_value": port.get("total_value"),
        "holdings_count": port.get("holdings_count"),
        "day_change_pct": port.get("day_change_pct"),
        "as_of": port.get("as_of"),
    }


def _model_portfolio_facts(snap: dict[str, Any]) -> Optional[dict[str, Any]]:
    mp = _domain_payload(snap, "model_portfolio")
    if not mp or mp.get("cash_target_pct") is None and mp.get("equity_target_pct") is None:
        return None
    return {
        "equity_target_pct": mp.get("equity_target_pct"),
        "fixed_income_target_pct": mp.get("fixed_income_target_pct"),
        "cash_target_pct": mp.get("cash_target_pct"),
        "actual_equity_pct": mp.get("actual_equity_pct"),
        "rebalancing_threshold_pct": mp.get("rebalancing_threshold_pct"),
        "drift": [
            {k: d.get(k) for k in ("bucket", "target_pct", "actual_pct", "drift_pct", "status")}
            for d in (mp.get("drift_summary") or []) if isinstance(d, dict)
        ][:6],
    }


def _rotation_facts(snap: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Rotation ladders -- 'what to concentrate on' in the house's own terms.

    Ranked ONLY over rows the ladder actually measured (data_quality > 0 and an
    rs_raw or return present). Measured 2026-09-13 23:14Z: all 13 sector rows were
    rs_score 50 / data_quality 0 / returns null -- a flat default, not a ranking.
    Presenting its first three as "top sectors" would be an invented answer, so
    ladder_state says UNMEASURED and top3 is empty.
    """
    rot = _domain_payload(snap, "rotation")
    rows = rot.get("sectors") if isinstance(rot, dict) else None
    if not isinstance(rows, list) or not rows:
        return None

    def measured(r: dict[str, Any]) -> bool:
        return bool((r.get("data_quality") or 0) > 0 and any(
            r.get(k) is not None for k in ("rs_raw", "return_1m", "return_3m", "return_6m")))

    ladder = [
        {k: r.get(k) for k in ("name", "etf", "rs_score", "return_1m", "return_3m", "return_6m", "data_quality")}
        for r in rows if isinstance(r, dict)
    ]
    ranked = sorted((x for x in ladder if measured(x)), key=lambda x: -(x.get("rs_score") or 0))
    transitions = [
        {"symbol": t.get("symbol"), "thesis_status": t.get("thesis_status")}
        for t in (rot.get("transitions") or []) if isinstance(t, dict) and t.get("needs_review")
    ]
    return {
        "computed_at": rot.get("computed_at"),
        "source": rot.get("source"),
        "ladder_state": "MEASURED" if ranked else "UNMEASURED",
        "sectors_total": len(ladder),
        "sectors_measured": len(ranked),
        "top3": ranked[:3],
        "ladder": ladder[:16],
        "transitions_needing_review": transitions[:8],
        "transitions_needing_review_count": len(transitions),
    }


def _fmt_usd(v: Any) -> str:
    """$710,933 / $1.27M style; 'n/a' for None. Rounds, never invents."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "n/a"
    if abs(x) >= 1_000_000:
        return f"${x / 1_000_000:,.2f}M"
    return f"${x:,.0f}"


def _office_state_facts(snap: dict[str, Any]) -> Optional[dict[str, Any]]:
    """'What should I be paying attention to' in the office's own state: open
    reconciliation actions and inconsistencies, theses needing review, re-entry and
    watch counts, recent closed trades. Counts and codes only -- no narrative."""
    out: dict[str, Any] = {}
    rec = _domain_payload(snap, "reconciliation")
    if rec:
        out["reconciliation"] = {
            "actions_open": rec.get("actions_open"),
            "actions_operator": rec.get("actions_operator"),
            "inconsistencies": [i.get("code") for i in (rec.get("inconsistencies") or []) if isinstance(i, dict)][:8],
            "holdings_source_freshness": rec.get("holdings_source_freshness"),
            "reconciled_at": rec.get("reconciled_at"),
        }
    rot = _rotation_facts(snap)
    if rot and rot.get("transitions_needing_review"):
        out["transitions_needing_review"] = rot["transitions_needing_review"]
    ren = _domain_payload(snap, "reentry")
    if ren.get("counts"):
        out["reentry_counts"] = ren.get("counts")
    wi = _domain_payload(snap, "watch_intelligence")
    if wi.get("counts"):
        out["watch_counts"] = wi.get("counts")
    tx = _domain_payload(snap, "transactions")
    if tx.get("closed_trades_total") is not None:
        out["recent_closed_trades"] = {
            "closed_trades_total": tx.get("closed_trades_total"),
            "last": [
                {k: t.get(k) for k in ("symbol", "exit_date", "realized_pnl", "account")}
                for t in (tx.get("recent_closed") or [])[:3] if isinstance(t, dict)
            ],
            "last_updated": tx.get("last_updated"),
        }
    return out or None


def _attach_contract_findings(intent: dict[str, Any], evidence: dict[str, Any], snap: dict[str, Any]) -> None:
    """Run the evidence contract; attach findings + 'contract' soft gaps. Never raises."""
    try:
        try:
            from scripts.lib import operator_evidence_contract as contract  # noqa: PLC0415
        except ImportError:
            from lib import operator_evidence_contract as contract  # type: ignore[no-redef]  # noqa: PLC0415
        findings = contract.check(intent, evidence, snap)
        evidence["contract_findings"] = findings
        if findings:
            gaps = evidence.setdefault("gaps", [])
            for g in contract.findings_to_gaps(findings):
                gaps.append(g)
    except Exception as exc:  # noqa: BLE001
        evidence["contract_findings"] = []
        evidence["contract_error"] = f"{type(exc).__name__}"


def _thematic_research_status(question: str) -> str:
    """One operator-facing line when the house holds no research on a theme.

    It never promises a follow-up. The base version called gap_resolver.resolve()
    from inside the evidence gather and, on outcome ``queued``, said "research
    queued via … ≈ N min, I will follow up". Nothing stood behind that promise:
    no pending row was opened for the chat, ``_v_operator_ask`` returns
    ``queued`` + ETA even in dry run, ``_v_hermes_research`` without a context
    enqueues for real from a READ step, and ``try_fulfill_pending_replies`` re-runs
    a freeform gather that always reports complete -- so no fulfiller could ever
    deliver it (Agent D replay, 2026-09-13). The follow-up promise now lives only
    where a pending row is written and read back (handle_operator_desk_question,
    _drop_unbacked_follow_up). ``question`` is kept for the caller's signature.
    """
    return ("Trade-AI holds no house research on this topic, and nothing was queued. "
            "Say 'research this' to queue it.")


#: Promises that something will come later. Timed ones need an ETA on the pending row.
_TIMED_PROMISE = re.compile(
    r"(?i)(\bfollow\s+up\b|\bget\s+back\s+to\s+you\b|\breply\s+(?:here\s+)?when\b|"
    r"\bwill\s+(?:reply|report\s+back|let\s+you\s+know)\b|≈\s*\d+\s*min)"
)
#: Claims that work was queued. Need a pending row, ETA or not.
_QUEUED_CLAIM = re.compile(r"(?i)\b(research\s+queued|queued\s+via|queued\s+(?:a|the)\s+pull)\b")
FOLLOW_UP_WITHDRAWN = "Nothing was queued; no automatic follow-up will come."


def _open_pending_row(pending_id: str, chat_id: str) -> Optional[dict[str, Any]]:
    """The latest ledger row for this pending_id if it is open and belongs to this chat."""
    latest = None
    try:
        for r in _read_jsonl(PENDING_PATH)[-200:]:
            if str(r.get("pending_id") or "") == str(pending_id):
                latest = r
    except Exception:
        return None
    if not latest or latest.get("status") != "open":
        return None
    if chat_id and str(latest.get("chat_id") or "") not in ("", str(chat_id)):
        return None
    return latest


def _drop_unbacked_follow_up(text: str, pending_row: Optional[dict[str, Any]]) -> str:
    """Withdraw any line promising later delivery that no pending row backs.

    * open pending row WITH eta_seconds -> text unchanged
    * open pending row without an ETA   -> timed promises removed; "queued … Pending" lines stay
    * no open pending row               -> timed promises AND queued claims removed, and one
                                           line says nothing was queued
    The model's own wording ("I'll get back to you") is held to the same rule.
    """
    if not text:
        return text
    has_row = bool(pending_row)
    has_eta = has_row and pending_row.get("eta_seconds") not in (None, "", 0)
    if has_eta:
        return text
    kept: list[str] = []
    dropped = False
    for line in text.splitlines():
        timed = bool(_TIMED_PROMISE.search(line))
        queued = bool(_QUEUED_CLAIM.search(line))
        if timed or (queued and not has_row):
            dropped = True
            continue
        kept.append(line)
    if not dropped:
        return text
    if not has_row:
        tail = kept[-1] if kept and kept[-1].strip() == AUTHORITY else None
        body = kept[:-1] if tail else kept
        # keep the Sources footer as the line just above the authority line
        insert_at = len(body)
        if body and body[-1].startswith("Sources: "):
            insert_at -= 1
        body.insert(insert_at, f"• {FOLLOW_UP_WITHDRAWN}")
        kept = body + ([tail] if tail else [])
    return "\n".join(kept)


def gather_freeform_context(intent: dict[str, Any]) -> dict[str, Any]:
    """Best-effort Trade-AI context for freeform agent. Never attaches reentry card."""
    symbols = [str(s).upper() for s in (intent.get("symbols") or [])]
    available: dict[str, Any] = {}
    soft_gaps: list[dict[str, Any]] = []
    sources: list[str] = []
    facts: dict[str, Any] = {
        "authority": AUTHORITY,
        "as_of": _now(),
        "symbols_mentioned": symbols,
        "portfolio": None,
        "cash": None,
        "risk": None,
        "holdings_for_symbols": [],
        "theses": {},
        "hermes": None,
    }

    snap: dict[str, Any] = {}
    try:
        from scripts.lib.data_broker.cio_portfolio import get_cio_snapshot

        snap = get_cio_snapshot(max_age_s=60) or {}
        sources.append("get_cio_snapshot")
    except Exception as exc:
        soft_gaps.append({
            "domain": "cio_snapshot",
            "symbol": None,
            "field": "snapshot",
            "reason": f"snapshot:{type(exc).__name__}",
            "gap_type": "soft",
        })

    facts["portfolio"] = _portfolio_facts(snap)
    if facts["portfolio"] is None:
        soft_gaps.append({
            "domain": "portfolio", "symbol": None, "field": "totals",
            "reason": "portfolio totals DATA_UNAVAILABLE", "gap_type": "soft",
        })

    # 2026-09-13 18:56: the model told the operator "cash_pct, buying_power ... are all
    # empty" while the snapshot carried total_cash $710,933. The payload keys are
    # data.total_cash / data.total_buying_power_estimate; cash_pct is derived.
    facts["cash"] = _cash_facts(snap, (facts.get("portfolio") or {}).get("total_value"))
    if facts["cash"] is None:
        soft_gaps.append({
            "domain": "cash_buying_power", "symbol": None, "field": "cash",
            "reason": "cash DATA_UNAVAILABLE", "gap_type": "soft",
        })

    risk = _domain_payload(snap, "risk")
    if risk and risk.get("portfolio_heat_pct") is not None:
        facts["risk"] = {
            "portfolio_heat_pct": risk.get("portfolio_heat_pct"),
            "positions_at_risk": risk.get("positions_at_risk"),
            "max_drawdown_pct": risk.get("max_drawdown_pct"),
            "stops_active": risk.get("stops_active"),
        }

    # Sector exposure and the investment policy are house facts a "what should I
    # concentrate on" question cannot be answered without. They were never passed.
    sec = _domain_payload(snap, "sectors")
    sec_rows = sec.get("sectors") if isinstance(sec, dict) else None
    if isinstance(sec_rows, list) and sec_rows:
        facts["sector_exposure"] = [
            {
                "sector": r.get("sector"), "weight_pct": r.get("weight_pct"),
                "value": r.get("value"), "symbols": list(dict.fromkeys(r.get("symbols") or []))[:6],
            }
            for r in sorted((x for x in sec_rows if isinstance(x, dict)), key=lambda x: -(x.get("weight_pct") or 0))[:8]
        ]
        facts["sector_exposure_total_value"] = sec.get("total_value")
    else:
        soft_gaps.append({
            "domain": "sectors", "symbol": None, "field": "exposure",
            "reason": "sector exposure DATA_UNAVAILABLE", "gap_type": "soft",
        })
    pol = _domain_payload(snap, "investment_policy")
    if pol and (pol.get("primary_objective") or pol.get("risk_level")):
        facts["investment_policy"] = {
            k: pol.get(k) for k in (
                "primary_objective", "risk_level", "max_single_position_pct", "max_drawdown_pct",
                "target_return_pct", "status", "next_review",
            ) if pol.get(k) is not None
        }
    # The model portfolio is the house's own answer to "how much should be in
    # equities vs cash" (75/15/5 targets, 56% cash actual on 2026-09-13), and the
    # rotation ladder is its answer to "which sectors" -- both unread before.
    mp = _model_portfolio_facts(snap)
    if mp:
        facts["model_portfolio"] = mp
    rot = _rotation_facts(snap)
    if rot:
        facts["rotation"] = rot
    else:
        soft_gaps.append({
            "domain": "rotation", "symbol": None, "field": "ladder",
            "reason": "rotation ladder DATA_UNAVAILABLE", "gap_type": "soft",
        })
    hold = _domain_payload(snap, "holdings_detail")
    positions = hold.get("positions") if isinstance(hold, dict) else None
    if isinstance(positions, list) and symbols:
        for p in positions:
            if not isinstance(p, dict):
                continue
            sym = str(p.get("symbol") or "").upper()
            if sym in symbols:
                facts["holdings_for_symbols"].append({
                    "symbol": sym,
                    "quantity": p.get("quantity") or p.get("shares"),
                    "market_value": p.get("market_value"),
                    "weight_pct": p.get("weight_pct"),
                    "cost_basis": p.get("cost_basis") or p.get("avg_cost"),
                    "account": p.get("account"),
                })
        missing_held = [s for s in symbols if not any(h["symbol"] == s for h in facts["holdings_for_symbols"])]
        for s in missing_held:
            soft_gaps.append({
                "domain": "holdings_detail", "symbol": s, "field": "position",
                "reason": f"{s} not in holdings snapshot (may be flat/watch)", "gap_type": "soft",
            })

    # A named stock's last close and desk levels. Without them the model was told
    # to say DATA_UNAVAILABLE for price and support/resistance that the house held.
    if symbols:
        px = subject_price_facts(symbols[:3])
        if px:
            facts["price_for_symbols"] = {
                s: {k: v for k, v in p.items() if k != "bars"} for s, p in px.items()
            }
            sources.append("ticker_prices")
        lv, lv_as_of, _lv_path = _subject_levels(symbols[:3])
        if lv:
            facts["levels_for_symbols"] = {s: _level_facts(row) for s, row in lv.items()}
            facts["levels_as_of"] = lv_as_of
            sources.append("reentry_decision_desk")
        for s in symbols[:3]:
            if s not in (px or {}) and s not in (lv or {}):
                soft_gaps.append({
                    "domain": "quote_price", "symbol": s, "field": "price",
                    "reason": f"no close or desk row on file for {s}", "gap_type": "soft",
                })

    # Symbol theses (fail-soft)
    for sym in symbols[:6]:
        try:
            from scripts.lib.symbol_thesis_attach import thesis_fields_for_symbol

            th = thesis_fields_for_symbol(sym, root=PROJECT_ROOT) or {}
            if th.get("has_current_symbol_thesis") or th.get("thesis_state"):
                facts["theses"][sym] = {
                    "thesis_state": th.get("thesis_state"),
                    "portfolio_role": th.get("portfolio_role"),
                    "thesis_summary": (th.get("thesis_summary") or "")[:400] or None,
                    "why_owned_or_watched": (th.get("why_owned_or_watched") or "")[:300] or None,
                    "symbol_thesis_version": th.get("symbol_thesis_version"),
                }
            else:
                soft_gaps.append({
                    "domain": "symbol_thesis", "symbol": sym, "field": "thesis",
                    "reason": f"{sym} thesis DATA_UNAVAILABLE", "gap_type": "research",
                })
        except Exception:
            soft_gaps.append({
                "domain": "symbol_thesis", "symbol": sym, "field": "thesis",
                "reason": f"{sym} thesis attach failed", "gap_type": "research",
            })

    # The freeform path had the SAME defect as the reentry composer: it put the
    # global pipeline counters into TRADE_AI_FACTS, so the model was handed
    # "2502 rows exist somewhere" as a fact about whatever was asked. Fixing
    # only the composer would have left this one feeding the other answer path.
    research_items = subject_research(symbols) if symbols else []
    question = str(intent.get("text") or intent.get("operator_text") or "")
    if research_items:
        facts["research_on_subject"] = research_items
    elif not symbols:
        # Thematic / macro question with no subject. HOUSE FIRST (operator rule
        # 2026-09-13: "routing should be internal Command Center first"): search
        # promoted research for the question's own words BEFORE the model sees
        # anything. Only when the store has nothing on the theme does
        # research_status say so and consult the Phase 7 resolver.
        topic = search_topic_research(question) if question.strip() else {"items": [], "keywords": []}
        if topic.get("items"):
            facts["research_on_topic"] = {
                "keywords": topic.get("keywords"),
                "as_of": topic.get("as_of"),
                "stale": topic.get("stale"),
                "items": topic["items"],
            }
            sources.append("hermes_research_intelligence (topic search)")
            newest_day = str(topic.get("as_of") or "")[:10]
            facts["research_status"] = (
                f"Trade-AI research on file for this topic: {len(topic['items'])} promoted "
                f"row(s) matching {', '.join(topic.get('keywords') or [])}"
                + (f" (newest {newest_day})" if newest_day else "") + "."
            )
        else:
            facts["research_status"] = _thematic_research_status(question)
            if topic.get("error"):
                facts["research_search_error"] = topic["error"]
            soft_gaps.append({
                "domain": "hermes_research", "symbol": None, "field": "topic",
                "reason": "no Trade-AI research on this topic; general market history is model knowledge",
                "gap_type": "research",
            })
    elif symbols:
        soft_gaps.append({
            "domain": "hermes_research",
            "symbol": symbols[0],
            "field": "research",
            "reason": f"no promoted research for {', '.join(symbols)}",
            "gap_type": "research",
        })

    available["freeform_context"] = facts
    available["soft_gaps"] = soft_gaps
    evidence = {
        "ok": True,
        "authority": AUTHORITY,
        "available": available,
        "gaps": soft_gaps,
        "blocking_gaps": [],  # freeform answers immediately
        "sources": sources,
        "complete": True,
    }
    # Coverage contract: the store had it -> the facts must carry it. Findings go
    # into the facts too, so the model and the fail-soft reply can say "available
    # but not assembled" instead of "empty". soft_gaps is the same list object as
    # evidence["gaps"], so the contract gaps reach both.
    _attach_contract_findings({**intent, "intent": "freeform"}, evidence, snap)
    if evidence.get("contract_findings"):
        facts["contract_findings"] = [
            {"code": f["code"], "fact": f["fact"], "domain": f["domain"], "store_has": f["store_has"]}
            for f in evidence["contract_findings"]
        ]
    return evidence


def _format_freeform_failsoft(context: dict[str, Any], soft_gaps: list[dict[str, Any]]) -> str:
    """Deterministic freeform reply when Flash is off or fails."""
    lines = ["🧠 *Alex · freeform (Trade-AI grounded)*"]
    port = context.get("portfolio") or {}
    if port:
        lines.append(
            f"• Book: {_fmt_usd(port.get('total_value'))} · {port.get('holdings_count')} holdings"
            + (f" · as of {str(port.get('as_of'))[:10]}" if port.get("as_of") else "")
        )
    cash = context.get("cash") or {}
    if cash and (cash.get("total_cash") is not None or cash.get("buying_power") is not None):
        top = (cash.get("by_account") or [{}])[0]
        lines.append(
            f"• Cash: {_fmt_usd(cash.get('total_cash'))}"
            + (f" ({cash.get('cash_pct')}% of book)" if cash.get("cash_pct") is not None else "")
            + (f" · largest {top.get('account')} {_fmt_usd(top.get('cash'))}" if top.get("account") else "")
            + f" · buying power est {_fmt_usd(cash.get('buying_power'))}"
            + (f" ({cash.get('quality_state')})" if cash.get("quality_state") else "")
        )
    mp = context.get("model_portfolio") or {}
    if mp:
        drift = " · ".join(
            f"{d.get('bucket')} target {d.get('target_pct')}% vs actual {d.get('actual_pct')}%"
            for d in (mp.get("drift") or []) if d.get("status") == "DRIFT"
        )
        lines.append(
            "• Model portfolio: "
            + (drift + " (DRIFT)" if drift else
               f"equity target {mp.get('equity_target_pct')}% · cash target {mp.get('cash_target_pct')}%")
        )
    rot = context.get("rotation") or {}
    if rot:
        when = str(rot.get("computed_at") or "")[:16].replace("T", " ")
        if rot.get("ladder_state") == "MEASURED" and rot.get("top3"):
            top3 = " · ".join(f"{r.get('name')} ({r.get('etf')}) RS {r.get('rs_score')}" for r in rot["top3"])
            lines.append(f"• Rotation ladder (computed {when}): top 3 by relative strength — {top3}")
        else:
            lines.append(
                f"• Rotation ladder (computed {when}): {rot.get('sectors_total')} sectors, none measured "
                f"(returns null, data_quality 0) — no ranking to cite."
            )
        tr = rot.get("transitions_needing_review") or []
        if tr:
            lines.append(
                f"• Theses needing review: {rot.get('transitions_needing_review_count')} — "
                + ", ".join(str(t.get("symbol")) for t in tr[:6])
            )
    risk = context.get("risk") or {}
    if risk:
        lines.append(
            f"• Risk: heat={risk.get('portfolio_heat_pct')} "
            f"at_risk={risk.get('positions_at_risk')} stops={risk.get('stops_active')}"
        )
    for h in context.get("holdings_for_symbols") or []:
        lines.append(
            f"• Held `{h.get('symbol')}`: qty={h.get('quantity')} mv={h.get('market_value')} "
            f"wt%={h.get('weight_pct')}"
        )
    sec = context.get("sector_exposure") or []
    if sec:
        lines.append("• Sectors: " + " · ".join(f"{x.get('sector')} {x.get('weight_pct')}%" for x in sec[:6]))
    pol = context.get("investment_policy") or {}
    if pol:
        lines.append(f"• Policy: {pol.get('risk_level')} · max single {pol.get('max_single_position_pct')}% · {str(pol.get('primary_objective') or '')[:90]}")
    topic = context.get("research_on_topic") or {}
    if topic.get("items"):
        lines.append(f"• House research on this topic (matched: {', '.join(topic.get('keywords') or [])}):")
        for it in topic["items"][:3]:
            body = str(it.get("summary") or "").strip().replace("\n", " ")
            lines.append(f"  – {it.get('as_of') or ''} {it.get('topic') or it.get('research_type') or 'research'}"
                         + (f" — {body[:140]}" if body else ""))
    if context.get("research_status"):
        lines.append(f"• {context['research_status']}")
    for sym, th in (context.get("theses") or {}).items():
        summary = th.get("thesis_summary") or th.get("why_owned_or_watched") or th.get("thesis_state")
        lines.append(f"• Thesis `{sym}`: {summary}")
    contract_gaps = [g for g in (soft_gaps or []) if g.get("gap_type") == "contract"]
    if context.get("contract_findings") or contract_gaps:
        found = context.get("contract_findings") or [
            {"domain": g.get("domain"), "fact": g.get("field"), "code": g.get("code")} for g in contract_gaps
        ]
        lines.append(
            "• Facts available but not assembled (the store had them; this reply could not use them): "
            + "; ".join(f"{f.get('domain')} → {str(f.get('fact')).rsplit('.', 1)[-1]} ({f.get('code')})" for f in found[:6])
        )
    soft_gaps = [g for g in (soft_gaps or []) if g.get("gap_type") != "contract"]
    if soft_gaps:
        gap_bits = []
        for g in soft_gaps[:8]:
            sym = g.get("symbol") or "book"
            gap_bits.append(f"{sym}:{g.get('field') or g.get('reason')}")
        lines.append("• Gaps (DATA_UNAVAILABLE): " + "; ".join(gap_bits))
    if len(lines) == 1:
        lines.append("• Limited Trade-AI context for that ask — reasoning deferred; gaps noted above.")
    lines.append("READ_ONLY_ADVISORY")
    return "\n".join(lines)


def _freeform_flash_enabled() -> bool:
    raw = (_env("CIO_OPERATOR_FREEFORM_FLASH") or _env("CIO_OPERATOR_INTENT_FLASH") or "1").lower()
    return raw not in ("0", "false", "off", "no")


#: The label rule 2b of the freeform prompt requires before general market history.
MODEL_KNOWLEDGE_LABEL = "General market history (model knowledge"

#: Seasonality / cycle lore. A line stating any of these must sit in a paragraph
#: that carries MODEL_KNOWLEDGE_LABEL -- the house holds no such data.
_SEASONAL_CLAIM = re.compile(
    r"(?i)\b(seasonal(?:ity|ly)?|september\s+(?:effect|is|has|tends|historically|averages?)|"
    r"(?:worst|best|weakest|strongest)\s+month|mid-?term\s+(?:election\s+)?(?:year|cycle)|"
    r"(?:presidential|election|four-year|4-year)\s+cycle|sell\s+in\s+may|santa\s+(?:claus\s+)?rally|"
    r"year-end\s+rally|historically|on\s+average\s+since|since\s+(?:19|20)\d\d)\b"
)

#: Phrases a reply uses to call something empty. Checked per sentence against the
#: subject words in _EMPTY_CLAIM_SUBJECTS.
_EMPTY_WORDS = re.compile(
    r"(?i)\b(not\s+available|unavailable|data_unavailable|are\s+(?:all\s+)?empty|is\s+empty|all\s+empty|"
    r"(?:no|don'?t\s+have|do\s+not\s+have|lack|missing)\s+(?:\w+\s+){0,3}(?:data|facts|information|visibility)|"
    r"not\s+in\s+my\s+(?:current\s+)?facts|can'?t\s+see|cannot\s+see)\b"
)
_EMPTY_CLAIM_SUBJECTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    # (reason key, subject regex, facts paths any of which being populated makes the claim false)
    ("cash", r"\b(cash(?:_pct)?|buying[\s_]power|dry\s+powder|liquidity)\b", ("cash.total_cash", "cash.buying_power")),
    ("holdings", r"\b(holdings(?:_for_symbols)?|positions|weights?|allocations?|exposure|portfolio)\b",
     ("sector_exposure", "portfolio.total_value")),
    ("sectors", r"\bsectors?(?:_exposure)?\b", ("sector_exposure",)),
    ("policy", r"\b(investment[\s_]policy|risk\s+(?:level|tolerance|profile)|mandate)\b", ("investment_policy",)),
    ("research", r"\b(research|house\s+view|trade-ai\s+view)\b", ("research_on_topic", "research_on_subject")),
    ("rotation", r"\b(rotation|ladder|relative\s+strength)\b", ("rotation",)),
)

_NUMBER_TOKEN = re.compile(
    r"(?P<usd>\$)\s?(?P<n1>\d[\d,]*(?:\.\d+)?)\s*(?P<suf1>[KkMmBb](?![a-z]))?"
    r"|(?P<n2>\d[\d,]*(?:\.\d+)?)\s*(?P<pct>%)"
)


def _facts_path_populated(context: dict[str, Any], path: str) -> bool:
    cur: Any = context
    for hop in path.split("."):
        if not isinstance(cur, dict) or hop not in cur:
            return False
        cur = cur[hop]
    return cur not in (None, "", [], {})


def _numbers_in(obj: Any, out: list[float]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _numbers_in(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numbers_in(v, out)
    elif isinstance(obj, str):
        for m in re.finditer(r"-?\d[\d,]*(?:\.\d+)?", obj):
            try:
                out.append(float(m.group(0).replace(",", "")))
            except ValueError:
                pass


def _number_is_sourced(value: float, pool: list[float]) -> bool:
    for f in pool:
        for cand in (f, abs(f)):
            tol = max(0.051, abs(cand) * 0.005)
            if abs(abs(value) - cand) <= tol:
                return True
    return False


def _labelled_blocks(text: str) -> list[tuple[str, bool]]:
    """(line, inside a model-knowledge block). A block starts at a line carrying the
    label and runs to the next blank line."""
    out: list[tuple[str, bool]] = []
    inside = False
    for line in (text or "").splitlines():
        if not line.strip():
            inside = False
            out.append((line, False))
            continue
        if MODEL_KNOWLEDGE_LABEL.lower() in line.lower():
            inside = True
        out.append((line, inside))
    return out


def _validate_freeform_reply(text: str, context: dict[str, Any]) -> Optional[str]:
    """Reject a Flash reply that misstates the house's facts. None == accept.

    Original checks: S0 wallpaper, invented READY/NEAR dumps. Added 2026-09-13
    after the 18:56 reply ("cash_pct, buying_power, holdings_for_symbols all empty"
    while the snapshot carried $710,933 cash, sector weights and the policy):

    (a) ``false_empty_claim:<subject>`` -- a sentence says cash / holdings / sectors /
        policy / research / rotation is empty or unavailable while facts carry it.
    (b) ``unlabelled_model_knowledge`` -- seasonality / cycle lore outside a
        paragraph labelled 'General market history (model knowledge…'.
    (c) ``unsourced_number:<token>`` -- a $ amount or % outside a labelled paragraph
        that matches no number anywhere in the facts (±0.5%, ±0.05 abs; K/M/B
        suffixes expanded). General history may cite its own numbers; house
        figures may not be invented.
    """
    if not text:
        return "empty"
    low = text.lower()
    if "defensive_observe" in low and "acknowledge and monitor" in low:
        return "s0_wallpaper"
    # READY TO REVIEW dump only OK if context somehow included it (freeform never does)
    if "ready to review" in low or re.search(r"\bNEAR ENTRY\b", text):
        return "invented_reentry_dump"
    ctx = context if isinstance(context, dict) else {}
    lines = _labelled_blocks(text)

    # (a) false empty claims, sentence by sentence, labelled paragraphs included --
    # "model knowledge" is no licence to call house data empty.
    for sentence in re.split(r"(?<=[.!?;])\s+|\n", text):
        if not _EMPTY_WORDS.search(sentence):
            continue
        for key, subject_rx, paths in _EMPTY_CLAIM_SUBJECTS:
            if re.search(subject_rx, sentence, re.I) and any(_facts_path_populated(ctx, p) for p in paths):
                return f"false_empty_claim:{key}"

    # (b) seasonality / cycle lore must be labelled.
    for line, inside in lines:
        if not inside and _SEASONAL_CLAIM.search(line):
            return "unlabelled_model_knowledge"

    # (c) house numbers must come from the facts.
    pool: list[float] = []
    _numbers_in(ctx, pool)
    for line, inside in lines:
        if inside:
            continue
        for m in _NUMBER_TOKEN.finditer(line):
            raw = (m.group("n1") or m.group("n2") or "").replace(",", "")
            try:
                val = float(raw)
            except ValueError:
                continue
            suf = (m.group("suf1") or "").upper()
            val *= {"K": 1e3, "M": 1e6, "B": 1e9}.get(suf, 1.0)
            if m.group("pct") and val in (0.0, 100.0):
                continue
            if not _number_is_sourced(val, pool):
                return f"unsourced_number:{m.group(0).strip()}"
    return None


def _facts_for_model(context: dict[str, Any], *, budget: int = 9000) -> str:
    """TRADE_AI_FACTS as JSON that is never cut mid-structure.

    The old ``json.dumps(context)[:6000]`` sliced the object: once sectors, policy,
    rotation and research were added, the tail -- where the model looks for cash --
    could be cut off, and a cut fact reads as a missing one. Trim in a fixed order
    instead: full ladder rows, research summaries, holdings rows, then drop keys.
    """
    ctx = json.loads(json.dumps(context or {}, default=str))
    text = json.dumps(ctx, default=str)
    if len(text) <= budget:
        return text
    rot = ctx.get("rotation")
    if isinstance(rot, dict):
        rot.pop("ladder", None)
    for key in ("research_on_topic",):
        block = ctx.get(key)
        if isinstance(block, dict):
            for it in block.get("items") or []:
                if isinstance(it, dict) and it.get("summary"):
                    it["summary"] = str(it["summary"])[:140]
    for it in ctx.get("research_on_subject") or []:
        if isinstance(it, dict) and it.get("summary"):
            it["summary"] = str(it["summary"])[:140]
    text = json.dumps(ctx, default=str)
    for drop in ("theses", "holdings_for_symbols", "symbols_mentioned", "hermes"):
        if len(text) <= budget:
            break
        ctx.pop(drop, None)
        text = json.dumps(ctx, default=str)
    return text


def answer_freeform_with_flash(
    operator_text: str,
    context: dict[str, Any],
    soft_gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    """Flash freeform answer grounded in Trade-AI facts. Fail-soft to deterministic."""
    failsoft = _format_freeform_failsoft(context, soft_gaps)
    if not _freeform_flash_enabled():
        return {"ok": True, "text": failsoft, "source": "freeform_failsoft", "model": None}

    try:
        from scripts.lib.cio_plan_enrichment import call_governed_llm, load_llm_policy

        # The model sees ONLY the assembled facts, never cut mid-structure.
        facts_json = _facts_for_model(context)
        gaps_json = json.dumps(soft_gaps[:12], default=str)[:2000]
        system = (
            "You are Alex, Trade-AI CIO assistant on Telegram. READ_ONLY_ADVISORY — "
            "no orders/stops. Answer the operator in a helpful free-form style.\n"
            "Rules:\n"
            "1) You MAY reason generally (strategy, comparisons, explainers).\n"
            "2) Prices, weights, READY/NEAR lists, R:R, cash, sector exposure, heat, quantities — "
            "ONLY from TRADE_AI_FACTS. If missing, say DATA_UNAVAILABLE. Never say a field is "
            "empty when TRADE_AI_FACTS carries it.\n"
            "2b) Anything from general market history or theory (seasonality, election cycles, "
            "sector rotation lore) must be prefixed '🟣 AI model (DeepSeek) — General market history (model knowledge, not "
            "Trade-AI data):' and kept to one short paragraph.\n"
            "2c) If TRADE_AI_FACTS.research_status is present, repeat it verbatim as its own line.\n"
            "2d) House first: when TRADE_AI_FACTS.research_on_topic is present, cite what those rows "
            "say (topic and as_of) BEFORE any general market history.\n"
            "2e) Sector questions: use sector_exposure, model_portfolio drift and rotation. If "
            "rotation.ladder_state is UNMEASURED, say the rotation ladder has no measured ranking — "
            "never rank sectors from it.\n"
            "2f) If TRADE_AI_FACTS.contract_findings is present, say those facts were available but not "
            "assembled for this reply — never that they are empty.\n"
            "2g) Never promise to follow up or say anything was queued.\n"
            "2h) For a named stock, when TRADE_AI_FACTS.price_for_symbols or levels_for_symbols is "
            "present, give its last close with the date, then support (entry zone, SMA50, stop) and "
            "resistance and target from those facts — never DATA_UNAVAILABLE for them.\n"
            "3) Never invent holdings or re-entry candidate dumps.\n"
            "4) Mention SOFT_GAPS briefly when relevant.\n"
            "5) Keep reply under ~900 chars; Telegram markdown ok (*bold*, `code`).\n"
            "6) End with READ_ONLY_ADVISORY."
        )
        try:
            from scripts.lib.agent_untrusted_data import untrusted_delimiter
            _ask = untrusted_delimiter(
                content_type="operator_message",
                source="telegram",
                content=(operator_text or "")[:800],
            )
        except Exception:
            _ask = f"OPERATOR_ASK:\n{(operator_text or '')[:800]}"
        user = (
            f"{_ask}\n\n"
            f"TRADE_AI_FACTS:\n{facts_json}\n\n"
            f"SOFT_GAPS:\n{gaps_json}"
        )
        llm = call_governed_llm(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            load_llm_policy(),
            use_pro=False,
            task_type="operator_reply",
        )
        if not llm.get("ok"):
            return {
                "ok": True,
                "text": failsoft,
                "source": "freeform_failsoft",
                "model": None,
                "flash_error": llm.get("error"),
            }
        text = str(llm.get("content") or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:\w+)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text).strip()
        # Model-level PI guard (maturity Production Ready — output exfil/echo scan).
        try:
            from scripts.lib.agent_model_pi_guard import refuse_text, scan_model_output
            _pi = scan_model_output(text)
            if _pi.get("refuse"):
                return {
                    "ok": True,
                    "text": refuse_text(_pi),
                    "source": "freeform_pi_refuse",
                    "model": llm.get("model"),
                    "flash_error": "model_pi_guard:" + ",".join(_pi.get("matches") or [])[:120],
                }
        except Exception:
            pass
        bad = _validate_freeform_reply(text, context)
        if bad:
            return {
                "ok": True,
                "text": failsoft,
                "source": "freeform_failsoft",
                "model": llm.get("model"),
                "flash_error": f"rejected:{bad}",
            }
        if "READ_ONLY" not in text:
            text = text.rstrip() + "\nREAD_ONLY_ADVISORY"
        # Phase 1: DecisionPayload@v1 for freeform (flag-gated, fail-soft).
        try:
            from scripts.lib.agent_decision_payload import (
                build_decision_payload,
                emit_decision_payload,
                infer_decision_origin,
            )

            syms = []
            if isinstance(context, dict):
                syms = [str(s).upper() for s in (context.get("symbols") or []) if s][:1]
            emit_decision_payload(
                build_decision_payload(
                    decision_id=f"dec_freeform_{(syms[0] if syms else 'ask')}",
                    wake_id=f"wake_freeform_{uuid.uuid4().hex[:10]}",
                    symbol=syms[0] if syms else None,
                    surface="freeform",
                    current_action="ADVISORY_REPLY",
                    decision_origin=infer_decision_origin(trigger="OPERATOR_ASK"),
                ),
                role="freeform",
            )
        except Exception:
            pass
        return {
            "ok": True,
            "text": text,
            "source": "freeform_flash",
            "model": llm.get("model") or "deepseek-flash",
        }
    except Exception as exc:
        return {
            "ok": True,
            "text": failsoft,
            "source": "freeform_failsoft",
            "model": None,
            "flash_error": f"{type(exc).__name__}:{exc}",
        }


def _gather_tradeai_evidence_core(intent: dict[str, Any]) -> dict[str, Any]:
    """Pull vetted Trade-AI evidence only. Report gaps — never invent fills."""
    needs = list(intent.get("needs") or [])
    intent_name = str(intent.get("intent") or "")
    symbols = [str(s).upper() for s in (intent.get("symbols") or [])]
    available: dict[str, Any] = {}
    gaps: list[dict[str, Any]] = []
    sources: list[str] = []

    # ── meta_system: runtime facts only ─────────────────────────────────────
    if intent_name == "meta_system" or (set(needs) & _RUNTIME_NEEDS and not (set(needs) & _DESK_NEEDS)):
        facts = load_runtime_llm_facts()
        available["meta_card"] = format_meta_system_reply(facts)
        available["runtime_llm"] = facts
        sources.append(str(facts.get("policy_path") or "cio_llm_policy"))
        return {
            "ok": True,
            "authority": AUTHORITY,
            "available": available,
            "gaps": [
                {"domain": "runtime", "symbol": None, "field": g, "reason": g, "gap_type": "soft"}
                for g in (facts.get("gaps") or [])
            ],
            "blocking_gaps": [],
            "sources": sources,
            "complete": True,
        }

    # ── freeform / leftover unclear: soft Trade-AI context (no reentry dump) ─
    if intent_name in ("freeform", "unclear") and not (set(needs) & {"reentry_ready", "reentry_levels"}):
        # If freeform also asked soft portfolio/cash/risk/research, still soft-gather
        return gather_freeform_context(intent)

    # ── re-entry only when needed ───────────────────────────────────────────
    want_reentry = (
        "reentry_ready" in needs
        or "reentry_levels" in needs
        or intent_name == "reentry"
    )
    _reentry_rows_loaded: list[Any] = []
    if want_reentry:
        from scripts.lib.cio_telegram_converse import (
            format_reentry_purchase_reply,
            format_reentry_symbol_reply,
            load_reentry_desk_rows,
            _row_levels,
        )

        rows, as_of, path = load_reentry_desk_rows()
        _reentry_rows_loaded = list(rows or [])
        if path:
            sources.append(str(path))
        if not rows:
            gaps.append({
                "domain": "reentry_decision_desk",
                "symbol": None,
                "field": "rows",
                "reason": "reentry_decision_desk_latest.json missing or empty",
                "gap_type": "missing_market_data",
            })
        else:
            available["reentry_card"] = format_reentry_purchase_reply(
                desk_rows=rows,
                computed_at=as_of,
                include_levels=True,
                operator_text="support resistance 50day",
            )
            available["reentry_as_of"] = as_of
            by_sym = {
                str(r.get("symbol") or "").upper(): r
                for r in rows
                if isinstance(r, dict) and r.get("symbol")
            }
            # A question that NAMES a symbol is answered about that symbol -- its
            # own row, gates, levels and held status -- never with the book dump.
            if symbols:
                held_map = _held_positions_map()
                cards: dict[str, str] = {}
                for sym in symbols[:6]:
                    row = by_sym.get(sym)
                    if row:
                        cards[sym] = format_reentry_symbol_reply(row, holding=held_map.get(sym), computed_at=as_of)
                if cards:
                    available["reentry_symbol_cards"] = cards
            check_syms = symbols or [
                str(r.get("symbol") or "").upper()
                for r in rows
                if isinstance(r, dict)
                and ((r.get("intel") or {}).get("state") == "READY TO REVIEW")
            ]
            for sym in check_syms[:15]:
                r = by_sym.get(sym)
                if not r:
                    if symbols:
                        gaps.append({
                            "domain": "reentry_decision_desk",
                            "symbol": sym,
                            "field": "row",
                            "reason": f"{sym} not on re-entry desk",
                            "gap_type": "missing_market_data",
                        })
                    continue
                if "reentry_levels" in needs:
                    lv = _row_levels(r)
                    missing = [
                        k for k in ("sma_50", "stop", "resistance_level")
                        if lv.get(k) is None
                    ]
                    if missing:
                        gaps.append({
                            "domain": "reentry_decision_desk",
                            "symbol": sym,
                            "field": ",".join(missing),
                            "reason": f"{sym} missing levels: {','.join(missing)}",
                            "gap_type": "missing_market_data",
                        })

    # ── CIO snapshot domains (cash / portfolio / risk / research) ───────────
    want_snap = any(n in needs for n in ("cash", "portfolio", "risk", "research"))
    snap: dict[str, Any] = {}
    if want_snap:
        try:
            from scripts.lib.data_broker.cio_portfolio import get_cio_snapshot

            snap = get_cio_snapshot(max_age_s=60) or {}
            sources.append("get_cio_snapshot")
        except Exception as exc:
            gaps.append({
                "domain": "cio_snapshot",
                "symbol": None,
                "field": "snapshot",
                "reason": f"snapshot:{type(exc).__name__}:{exc}",
                "gap_type": "missing_market_data",
            })

    if "cash" in needs or "portfolio" in needs:
        # Prefer snapshot; fall back to holdings helper.
        # 2026-09-13: this path read cash_pct / buying_power / cash -- keys the
        # cash_buying_power payload never had -- so a "how much cash" ask on the
        # desk path built "cash_pct=None buying_power=None" while total_cash was
        # $710,933. It now reads the same helpers as the freeform builder and
        # carries structured book_facts the evidence contract can check.
        book_bits: list[str] = []
        hold_dom = _domain_payload(snap, "holdings_detail")
        port_f = _portfolio_facts(snap)
        cash_f = _cash_facts(snap, (port_f or {}).get("total_value"))
        book_facts: dict[str, Any] = {}
        if cash_f:
            book_facts["cash"] = cash_f
            accts = ", ".join(f"{a.get('account')} {_fmt_usd(a.get('cash'))}" for a in cash_f["by_account"][:4])
            book_bits.append(
                f"cash={_fmt_usd(cash_f.get('total_cash'))} ({cash_f.get('cash_pct')}% of book)"
                f" buying_power_est={_fmt_usd(cash_f.get('buying_power'))} quality={cash_f.get('quality_state')}"
                + (f" by account: {accts}" if accts else "")
            )
        elif (_domain_payload(snap, "cash_buying_power") or {}).get("quality_state") == "DATA_UNAVAILABLE":
            gaps.append({
                "domain": "cash_buying_power",
                "symbol": None,
                "field": "cash",
                "reason": "cash domain unavailable",
                "gap_type": "missing_market_data",
            })
        if port_f:
            book_facts["portfolio"] = port_f
            book_bits.append(
                f"portfolio_value={_fmt_usd(port_f.get('total_value'))} "
                f"holdings={port_f.get('holdings_count')}"
            )
        if book_facts:
            available["book_facts"] = book_facts
        if intent_name == "attention":
            office = _office_state_facts(snap)
            if office:
                available["office_state"] = office
        if hold_dom and hold_dom.get("position_count") is not None:
            book_bits.append(f"positions={hold_dom.get('position_count')}")
        if not book_bits:
            try:
                from scripts.lib.cio_telegram_converse import _portfolio_cash_fact_lines

                legacy = _portfolio_cash_fact_lines()
                if legacy:
                    book_bits.extend(legacy)
                    sources.append("holdings.json")
            except Exception:
                pass
        if book_bits:
            available["book"] = "; ".join(book_bits)
        elif "portfolio" in needs or "cash" in needs:
            gaps.append({
                "domain": "portfolio",
                "symbol": None,
                "field": "holdings",
                "reason": "portfolio/cash unavailable",
                "gap_type": "missing_market_data",
            })

    if "risk" in needs:
        risk_dom = _domain_payload(snap, "risk")
        if risk_dom and (risk_dom.get("state") not in (None, "DATA_UNAVAILABLE") or risk_dom.get("portfolio_heat_pct") is not None):
            available["risk"] = {
                "portfolio_heat_pct": risk_dom.get("portfolio_heat_pct"),
                "total_risk_dollars": risk_dom.get("total_risk_dollars"),
                "positions_at_risk": risk_dom.get("positions_at_risk"),
                "max_drawdown_pct": risk_dom.get("max_drawdown_pct"),
                "stops_active": risk_dom.get("stops_active"),
            }
        else:
            gaps.append({
                "domain": "risk",
                "symbol": None,
                "field": "risk",
                "reason": "risk domain unavailable",
                "gap_type": "missing_market_data",
            })

    if "research" in needs:
        # Subject first. The pipeline counters that used to live here are
        # identical for every question and describe the machine, not the
        # company -- see subject_research() for what shipping them cost.
        items = subject_research(
            symbols, include_operational=bool(_STOP_QUESTION.search(str(intent.get("text") or ""))),
        )
        if items:
            available["hermes_research"] = {
                "items": items,
                "symbols": sorted({i["symbol"] for i in items if i.get("symbol")}),
                "model_provider": (_domain_payload(snap, "hermes_research") or {}).get(
                    "model_provider"),
            }
        else:
            # No research about THIS subject is a gap even when the pipeline is
            # busy. "2502 rows exist" was never evidence about Walmart.
            gaps.append({
                "domain": "hermes_research",
                "symbol": symbols[0] if symbols else None,
                "field": "research",
                "reason": (
                    f"no promoted research for {', '.join(symbols)}"
                    if symbols else "no subject named to research"
                ),
                "gap_type": "missing_research",
            })

    if "analyst_view" in needs and symbols:
        view = subject_analyst_view(symbols)
        if view:
            available["analyst_view"] = {"items": view,
                                         "symbols": [v["symbol"] for v in view]}
        else:
            # No coverage is a gap, not a reason to answer with something else.
            gaps.append({
                "domain": "analyst_view",
                "symbol": symbols[0],
                "field": "analyst_view",
                "reason": f"no analyst coverage on file for {', '.join(symbols)}",
                "gap_type": "missing_analyst_coverage",
            })

    # How is the named stock doing: last close, 30-day change, its desk levels.
    # 2026-09-13 "How is Visa doing ... analyst recommendations": the reply had no
    # price, no levels and no analyst line although all three were on file.
    subject_syms = [s for s in symbols[:3]] if (symbols and ({"research", "analyst_view"} & set(needs))
                                                and not want_reentry) else []
    if subject_syms:
        available["subject_symbols"] = subject_syms
        prices = subject_price_facts(subject_syms)
        if prices:
            available["subject_price"] = prices
            sources.append("ticker_prices")
        lv, lv_as_of, lv_path = _subject_levels(subject_syms)
        if lv:
            available["subject_levels"] = lv
            available["subject_levels_as_of"] = lv_as_of
            if lv_path:
                sources.append(str(lv_path))
        # Phase 2A (2026-09-22): subject brief with only analyst_view never loaded
        # hermes, so soft gaps stayed empty, DeepSeek reworded a hollow house card,
        # and nothing opened a pending for Hermes follow-up. Soft (non-blocking)
        # missing_research when research was not already requested as a need.
        if "research" not in needs and not available.get("hermes_research"):
            items = subject_research(
                subject_syms,
                include_operational=bool(_STOP_QUESTION.search(str(intent.get("text") or ""))),
            )
            if items:
                available["hermes_research"] = {
                    "items": items,
                    "symbols": sorted({i["symbol"] for i in items if i.get("symbol")}),
                }
            else:
                gaps.append({
                    "domain": "hermes_research",
                    "symbol": subject_syms[0],
                    "field": "research",
                    "reason": f"no promoted research for {', '.join(subject_syms)}",
                    "gap_type": "missing_research",
                })
        # Phase 3: stale / missing quotes on a named subject are gaps (resolver
        # can refresh_producer / yfinance backup). Buy-perspective treats them
        # as blocking below so we refuse hollow price narration.
        for sym in subject_syms:
            p = (available.get("subject_price") or {}).get(sym)
            if subject_price_is_stale(p):
                age = _price_age_hours(p) if p else None
                reason = (
                    f"no daily close on file for {sym}"
                    if not p or p.get("close") is None
                    else f"quote for {sym} is STALE"
                         + (f" ({age:.0f}h old, last {p.get('price_date')})" if age is not None else "")
                )
                gaps.append({
                    "domain": "quote_price",
                    "symbol": sym,
                    "field": "price",
                    "reason": reason,
                    "gap_type": "missing_market_data",
                })

    # Blocking gaps
    blocking: list[dict[str, Any]] = []
    if want_reentry and not available.get("reentry_card"):
        blocking = [g for g in gaps if g.get("domain") == "reentry_decision_desk"]
    if symbols and ("reentry_ready" in needs or "reentry_levels" in needs):
        blocking.extend(
            g for g in gaps
            if g.get("symbol") in symbols and g.get("field") == "row"
        )
    # Research-only ask with no hermes → blocking so we enqueue
    if "research" in needs and not available.get("hermes_research") and not available.get("reentry_card"):
        blocking.extend(g for g in gaps if g.get("domain") == "hermes_research")
    # Buy/perspective Option B: thin house research OR stale quotes block the
    # hollow answer-now path — operator gets research-first status instead.
    if symbols and is_buy_perspective_ask(str(intent.get("text") or "")):
        if not available.get("hermes_research"):
            blocking.extend(
                g for g in gaps
                if g.get("domain") == "hermes_research" and g not in blocking
            )
        blocking.extend(
            g for g in gaps
            if g.get("domain") == "quote_price" and g.get("gap_type") == "missing_market_data"
            and g not in blocking
        )

    evidence = {
        "ok": True,
        "authority": AUTHORITY,
        "available": available,
        "gaps": gaps,
        "blocking_gaps": blocking,
        "sources": sources,
        "complete": not blocking and bool(available),
    }
    # Coverage contract (config/operator_evidence_contract.json). The re-entry desk
    # file is its own store of record, so when this turn did not need the CIO
    # snapshot the desk rows it loaded stand in as the "reentry" domain.
    contract_snap: dict[str, Any] = dict(snap or {})
    if want_reentry and "reentry" not in (contract_snap.get("domains") or {}):
        contract_snap["domains"] = {
            **(contract_snap.get("domains") or {}),
            "reentry": {"state": "AVAILABLE" if _reentry_rows_loaded else "DATA_UNAVAILABLE",
                        "rows": _reentry_rows_loaded},
        }
    _attach_contract_findings(intent, evidence, contract_snap)
    return evidence


#: The desk's gap vocabulary mapped onto the resolver's. Only a gap the resolver
#: has an action for is queued. Anything else is counted as not registered, so a
#: reply never claims a refresh that nothing will perform.
def _registry_gap_type(gap: dict[str, Any]) -> Optional[str]:
    if not str((gap or {}).get("symbol") or "").strip():
        return None
    gap_type = str(gap.get("gap_type") or "")
    domain = str(gap.get("domain") or "")
    if gap_type == "missing_market_data":
        return "missing_market_data"
    if domain == "symbol_thesis":
        return "missing_thesis"
    if gap_type in ("research", "missing_research"):
        # `missing_research` is what THIS module emits (see the hermes_research
        # branch of subject_evidence) when no promoted research exists for the
        # named symbol. It returned None here, so the desk could not feed
        # data_gap_registry -- the only working RAISED->WORKED->ANSWERED machine
        # in the system, which has had no new row since 2026-05-24. Measured
        # 2026-09-14 in data/cio/cio_operator_gap_requests.jsonl: HPE,
        # "no promoted research for HPE", `"registered": 0, "not_registered": 1`.
        # It maps to `stale_news` because that is the resolver action that
        # FETCHES research (_resolve_stale_news -> _resolve_missing_catalyst
        # dispatches a maria_research job for the symbol); `missing_thesis`
        # merely recovers a prior buy thesis from proposals and would answer a
        # different question.
        return "stale_news"
    return None


def _gap_registry_enabled() -> bool:
    return _env("CIO_OPERATOR_GAP_REGISTRY", "1").lower() not in ("0", "false", "off", "no")


def _gap_registry_write_conn():
    """A write connection for the data gap queue, or None when there is no database."""
    if os.environ.get("TRADE_AI_CI") == "1":
        return None
    password = os.environ.get("DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD")
    if not password:
        return None
    import psycopg2  # noqa: PLC0415

    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        dbname=os.environ.get("DB_NAME", "trade_ai"),
        user=os.environ.get("DB_USER", "trade_ai"),
        password=password,
        connect_timeout=3,
        options="-c statement_timeout=5000",
    )


def _resolver_cron_exprs(crontab_text: str) -> list[str]:
    """Schedules of the live data_gap_resolver lines; the weekly audit only abandons."""
    exprs: list[str] = []
    for line in (crontab_text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "data_gap_resolver.py" not in s or "--weekly-audit" in s:
            continue
        parts = s.split()
        if len(parts) > 5 and not parts[0].startswith("@"):
            exprs.append(" ".join(parts[:5]))
    return exprs


_RESOLVER_CRON_CACHE: dict[str, Any] = {"at": 0.0, "exprs": []}


def _gap_resolver_schedule() -> list[str]:
    """When the gap resolver runs, read from the crontab that runs it.

    The crontab is the schedule's only source. Copying it into config would make
    a second one that drifts. An unreadable crontab yields [] and the reply says
    no run time is known.
    """
    import subprocess  # noqa: PLC0415
    import time  # noqa: PLC0415

    now = time.monotonic()
    if _RESOLVER_CRON_CACHE["exprs"] and now - float(_RESOLVER_CRON_CACHE["at"]) < 600:
        return list(_RESOLVER_CRON_CACHE["exprs"])
    try:
        out = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    exprs = _resolver_cron_exprs(out)
    _RESOLVER_CRON_CACHE.update(at=now, exprs=exprs)
    return exprs


def _next_gap_resolver_run(now: Optional[datetime] = None) -> Optional[datetime]:
    try:
        from lib.cron_schedule import next_run_any  # noqa: PLC0415
    except ImportError:
        from scripts.lib.cron_schedule import next_run_any  # noqa: PLC0415
    # cron fires in the host's local time
    return next_run_any(_gap_resolver_schedule(), now or datetime.now().astimezone())


def _gap_queue_note(reg: dict[str, Any]) -> str:
    """The soft-gap note when the queue accepted gaps: which rows, and when they are worked."""
    ids = [f"#{i}" for i in (reg.get("gap_ids") or [])][:6]
    head = "logged in the data gap queue" + (f" ({', '.join(ids)})" if ids else "")
    when = None
    try:
        if reg.get("resolver_next_run"):
            when = datetime.fromisoformat(str(reg["resolver_next_run"])).astimezone().strftime("%a %H:%M %Z")
    except ValueError:
        when = None
    if when:
        return f"{head}; the gap resolver picks it up {when}. Ask again after that._"
    return f"{head}; no resolver run time is known, so no follow-up is promised._"


def _register_gap_ids_on_spine(conn: Any, gap_ids: list[int]) -> dict[str, Any]:
    """Put the queue's integer ids on the subject spine. Returns a receipt.

    `data_gap_registry.id` is a bigserial, so it can never be joined to a goal,
    a question or a material change on its own. The row already knows its
    symbol; this reads it back on the same connection and registers the edge,
    leaving the id itself untouched.

    The receipt (``written``, and ``error`` when something went wrong) is
    returned rather than logged because this module has no logger and writes no
    stdout -- it reports through the JSONL receipt its caller already appends,
    so a failure here is visible instead of silent.

    Fail-safe by construction: the gaps are committed before this runs, so a
    spine failure costs a join, never a queued gap.
    """
    if not gap_ids:
        return {"written": 0}
    try:
        from scripts.lib.cio_identity_spine import register_symbol_on_spine  # noqa: PLC0415

        cur = conn.cursor()
        cur.execute(
            "SELECT id, symbol FROM data_gap_registry WHERE id = ANY(%s)",
            [[int(i) for i in gap_ids]],
        )
        rows = cur.fetchall() or []
        written = 0
        for gap_id, symbol in rows:
            if register_symbol_on_spine("data_gap_registry", gap_id, symbol, cur=cur):
                written += 1
        conn.commit()
        return {"written": written, "rows_seen": len(rows)}
    except Exception as exc:  # noqa: BLE001 -- a link is never worth a queued gap
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        return {"written": 0, "error": f"{type(exc).__name__}:{exc}"[:160]}


def _register_gaps(gaps: list[dict[str, Any]], *, chat_id: str, pending_id: str) -> dict[str, Any]:
    """Queue the gaps the resolver can act on into data_gap_registry.

    Writes only through the store's write module
    (scripts/lib/writers/data_gap_registry_writer.py). The operator approved the
    desk as a caller on 2026-09-13; the grant is on the `data_gaps` domain in
    config/data_source_authority.json.

    Returns ``registered`` (gaps now in the queue, new or already open),
    ``gap_ids``, ``not_registered`` (gaps with no resolver action),
    ``resolver_next_run`` and, on failure, ``error``. Before this the function
    imported a bridge module that never reached main and registered 0 every call.
    """
    rows: list[dict[str, Any]] = []
    skipped = 0
    for g in gaps or []:
        gap_type = _registry_gap_type(g)
        if gap_type is None:
            skipped += 1
            continue
        what = g.get("field") or g.get("reason") or "missing"
        rows.append({
            "symbol": g.get("symbol"),
            "gap_type": gap_type,
            "gap_detail": f"operator desk {pending_id}: {g.get('domain') or 'desk'} {what}",
        })
    out: dict[str, Any] = {"registered": 0, "gap_ids": [], "not_registered": skipped, "resolver_next_run": None}
    if rows and not _gap_registry_enabled():
        out["error"] = "gap registry disabled (CIO_OPERATOR_GAP_REGISTRY=0)"
    elif rows:
        conn = None
        try:
            conn = _gap_registry_write_conn()
            if conn is None:
                out["error"] = "no database credentials for the gap registry"
            else:
                try:
                    from lib.writers.data_gap_registry_writer import register_gaps  # noqa: PLC0415
                except ImportError:
                    from scripts.lib.writers.data_gap_registry_writer import register_gaps  # noqa: PLC0415
                rec = register_gaps(
                    conn.cursor(), rows,
                    detected_by="cio_operator_desk", source="cio_operator_desk_loop", run_id=pending_id,
                )
                conn.commit()
                out["gap_ids"] = rec.queued_ids
                out["registered"] = len(rec.queued_ids)
                out["receipt"] = rec.as_dict()
                out["spine_links"] = _register_gap_ids_on_spine(conn, rec.queued_ids)
        except Exception as exc:  # noqa: BLE001
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:  # noqa: BLE001
                    pass
            out["error"] = f"{type(exc).__name__}:{exc}"
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
    if out["registered"]:
        try:
            nxt = _next_gap_resolver_run()
        except Exception:  # noqa: BLE001
            nxt = None
        out["resolver_next_run"] = nxt.isoformat() if nxt else None
    _append_jsonl(
        PROJECT_ROOT / "data" / "cio" / "cio_operator_gap_requests.jsonl",
        {
            "ts": _now(),
            "pending_id": pending_id,
            "chat_id": chat_id,
            "gaps": gaps,
            "registered": out["registered"],
            "gap_ids": out["gap_ids"],
            "not_registered": skipped,
            "resolver_next_run": out["resolver_next_run"],
            "error": out.get("error"),
            "authority": AUTHORITY,
        },
    )
    return out


#: Rows kept per research type before selection (see subject_research).
SUBJECT_RESEARCH_PER_TYPE = 3
SUBJECT_RESEARCH_SQL = """SELECT symbol, research_type, topic, body, confidence_score, created_at
     FROM (SELECT symbol, research_type, topic, COALESCE(summary, thesis, '') AS body,
                  confidence_score, created_at,
                  row_number() OVER (PARTITION BY research_type ORDER BY created_at DESC) AS rn
             FROM hermes_research_intelligence
            WHERE upper(symbol) = ANY(%s) AND status = 'promoted') per_type
    WHERE rn <= %s
    ORDER BY created_at DESC
    LIMIT %s"""


#: Research rows that are operational notes about the book's own stops and
#: protection, not research about the company. Shown only when the question is
#: about stops or protection.
_OPERATIONAL_RESEARCH = frozenset({"stop_curation", "stop_health", "protection_advisory"})
#: Useful but repetitive: the options desk writes a near-identical covered-call
#: row on every run. At most one, after the substantive research.
_SECONDARY_RESEARCH = frozenset({"options_desk"})
_STOP_QUESTION = re.compile(r"(?i)\b(stops?|stop[\s-]?loss|protect\w*|trailing|hedg\w*)\b")
_LONG_FLOAT = re.compile(r"(\d+\.\d{2})\d{3,}")
_MARKDOWN_CHARS = re.compile(r"[*_`\[\]]")


def _tidy_numbers(text: Any) -> str:
    """'edge 67.61000000000001' -> 'edge 67.61'. Stored summaries carry float noise."""
    return _LONG_FLOAT.sub(r"\1", str(text or ""))


def select_subject_research(items: list[dict[str, Any]], *, include_operational: bool = False,
                            limit: int = 4) -> list[dict[str, Any]]:
    """The research worth showing, from rows newest first.

    2026-09-13, "How is Visa doing ... supporting research ... analyst
    recommendations": V had 1,018 research rows. The newest four were the
    options desk's covered-call note, three of them identical and one with
    'edge 67.61000000000001'. 110 stop-curation notes and 'stop health' rows
    ('if fired: -$4,224,901') sat behind them, and the one deep-research row
    never surfaced. So: drop operational notes unless asked, one row per
    research type, near-duplicates merged (numbers ignored when comparing),
    substantive research before options-desk notes, float noise rounded.
    """
    seen: set[str] = set()
    types: set[str] = set()
    primary: list[dict[str, Any]] = []
    secondary: list[dict[str, Any]] = []
    for it in items or []:
        rtype = str(it.get("research_type") or "")
        if rtype in _OPERATIONAL_RESEARCH and not include_operational:
            continue
        key = re.sub(r"\d+(?:[.,]\d+)*", "#", str(it.get("summary") or "").lower())[:160]
        if key in seen or rtype in types:
            continue
        seen.add(key)
        types.add(rtype)
        clean = {**it, "summary": _tidy_numbers(it.get("summary")), "topic": _tidy_numbers(it.get("topic"))}
        (secondary if rtype in _SECONDARY_RESEARCH else primary).append(clean)
    return (primary + secondary)[: max(1, int(limit))]


def subject_price_facts(symbols: list[str], *, days: int = 45) -> dict[str, dict[str, Any]]:
    """Last close and the change over about 30 days, read through the broker's daily bars.

    Read-only. Degrades to {} per symbol when there are no bars or no database.
    """
    try:
        from lib.data_broker import daily_bars  # noqa: PLC0415
    except ImportError:
        try:
            from scripts.lib.data_broker import daily_bars  # noqa: PLC0415
        except ImportError:
            return {}
    out: dict[str, dict[str, Any]] = {}
    for sym in [str(s).upper() for s in symbols or [] if str(s).strip()]:
        try:
            res = daily_bars.get_daily_bars(_research_db_query, sym, days=days)
        except Exception:  # noqa: BLE001
            continue
        bars = sorted((b for b in (res.get("bars") or []) if b.get("close")), key=lambda b: str(b.get("price_date")))
        if not bars:
            continue
        last = bars[-1]
        start = bars[0]
        try:
            cutoff = datetime.fromisoformat(str(last["price_date"])[:10]) - timedelta(days=30)
            before = [b for b in bars if datetime.fromisoformat(str(b["price_date"])[:10]) <= cutoff]
            start = before[-1] if before else bars[0]
        except (ValueError, KeyError):
            pass
        change = None
        if start is not last and start.get("close"):
            change = round((float(last["close"]) - float(start["close"])) / float(start["close"]) * 100.0, 1)
        price_date = str(last["price_date"])[:10]
        age_hours = None
        try:
            age_hours = (datetime.now(timezone.utc).date()
                         - datetime.fromisoformat(price_date).date()).days * 24.0
        except Exception:
            age_hours = None
        stale_flag = bool(res.get("stale")) or (
            age_hours is not None and age_hours > _QUOTE_STALE_HOURS
        )
        out[sym] = {
            "close": float(last["close"]), "price_date": price_date,
            "start_close": float(start["close"]) if start is not last else None,
            "start_date": str(start["price_date"])[:10] if start is not last else None,
            "change_30d_pct": change, "stale": stale_flag,
            "age_hours": age_hours,
            "bars": [[str(b["price_date"])[:10], float(b["close"])] for b in bars],
        }
    return out


def _subject_levels(symbols: list[str]) -> tuple[dict[str, dict[str, Any]], Optional[str], Any]:
    """Each symbol's re-entry desk row (price, zone, stop, target, resistance, SMAs, RSI)."""
    try:
        from scripts.lib.cio_telegram_converse import load_reentry_desk_rows  # noqa: PLC0415
    except ImportError:
        from lib.cio_telegram_converse import load_reentry_desk_rows  # noqa: PLC0415
    try:
        rows, as_of, path = load_reentry_desk_rows()
    except Exception:  # noqa: BLE001
        return {}, None, None
    by = {str(r.get("symbol") or "").upper(): r for r in rows or [] if isinstance(r, dict)}
    return {s: by[s] for s in symbols if s in by}, as_of, path


def _level_facts(row: dict[str, Any]) -> dict[str, Any]:
    """The levels a price / support / resistance question needs, from one desk row."""
    res = row.get("resistance")
    out = {k: row.get(k) for k in ("price", "price_as_of", "rsi", "sma_20", "sma_50", "sma_200",
                                   "entry_low", "entry_high", "stop", "target", "rr")
           if row.get(k) is not None}
    if isinstance(res, dict):
        out["resistance"] = {k: res.get(k) for k in ("level", "state", "as_of") if res.get(k) is not None}
    elif res is not None:
        out["resistance"] = res
    return out


def _fmt_price(v: Any) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_day(d: Any) -> str:
    try:
        dt = datetime.fromisoformat(str(d)[:10])
    except ValueError:
        return str(d or "")
    return dt.strftime("%b %d") if dt.year == datetime.now().year else dt.strftime("%b %d %Y")


def _research_label(rtype: str) -> str:
    return {"deep_research_local": "deep research", "options_desk": "options desk",
            "ticker_thesis_challenge": "thesis challenge"}.get(rtype, rtype.replace("_", " ") or "research")


def _subject_takeaway(sym: str, price: dict[str, Any], row: Optional[dict[str, Any]],
                      analyst: Optional[dict[str, Any]], research: list[dict[str, Any]]) -> str:
    bits: list[str] = []
    close = price.get("close") if price else None
    if row and close:
        res = row.get("resistance")
        res_lvl = res.get("level") if isinstance(res, dict) else res
        try:
            if res_lvl:
                gap = (float(res_lvl) - float(close)) / float(close) * 100.0
                bits.append(f"price is {abs(gap):.1f}% {'below' if gap >= 0 else 'above'} resistance {_fmt_price(res_lvl)}")
            if row.get("stop"):
                cushion = (float(close) - float(row["stop"])) / float(close) * 100.0
                bits.append(f"{abs(cushion):.1f}% {'above' if cushion >= 0 else 'below'} the stop {_fmt_price(row['stop'])}")
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    if analyst and close and analyst.get("target_mean"):
        try:
            up = (float(analyst["target_mean"]) - float(close)) / float(close) * 100.0
            s = (f"analysts' mean target {_fmt_price(analyst['target_mean'])} is {abs(up):.1f}% "
                 f"{'above' if up >= 0 else 'below'} the last close")
            if analyst.get("stale"):
                s += f", but that view is {analyst.get('age_days')} days old"
            bits.append(s)
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    substantive = [r for r in research if str(r.get("research_type") or "") not in _SECONDARY_RESEARCH]
    if not research:
        bits.append(f"there is no house research on {sym}")
    elif not substantive:
        bits.append(f"house research on {sym} is thin, options-desk notes only")
    if not bits:
        return ""
    text = "; ".join(bits)
    text = text[0].upper() + text[1:] + "."
    if not substantive or not analyst or (analyst and analyst.get("stale")):
        # Auto-enqueue path (enqueue_research_gap) owns the operator ack; do not
        # prompt "say 'research X'" — that left single-letter names like S unqueued.
        text += f" House research for {sym} is thin or missing."
    return text


def format_subject_brief(symbols: list[str], avail: dict[str, Any]) -> str:
    """How a named stock is doing, from house data only: price, levels, analysts, research, meaning."""
    prices = avail.get("subject_price") or {}
    levels = avail.get("subject_levels") or {}
    lv_asof = _fmt_day(avail.get("subject_levels_as_of")) if avail.get("subject_levels_as_of") else ""
    analyst_domain = avail.get("analyst_view")
    analysts = {str(v.get("symbol") or "").upper(): v for v in ((analyst_domain or {}).get("items") or [])}
    research = (avail.get("hermes_research") or {}).get("items") or []
    blocks: list[str] = []
    for sym in symbols:
        lines = [f"*{sym}*"]
        p = prices.get(sym) or {}
        if p.get("close") is not None:
            line = f"Price {_fmt_price(p['close'])} (close {_fmt_day(p.get('price_date'))})"
            if p.get("change_30d_pct") is not None:
                line += (f" · 30-day {p['change_30d_pct']:+.1f}% from {_fmt_price(p.get('start_close'))} "
                         f"on {_fmt_day(p.get('start_date'))}")
            # Surface multi-day staleness so a Sep-04 close cannot read as "today".
            age_h = p.get("age_hours")
            if age_h is None and p.get("price_date"):
                try:
                    pd = str(p.get("price_date"))[:10]
                    age_h = (datetime.now(timezone.utc).date()
                             - datetime.fromisoformat(pd).date()).days * 24.0
                except Exception:
                    age_h = None
            try:
                if age_h is not None and float(age_h) > 26.0:
                    line += f" · STALE ({float(age_h):.0f}h old)"
            except (TypeError, ValueError):
                pass
            lines.append(line)
        else:
            lines.append("Price: no daily close on file.")
        row = levels.get(sym)
        if row:
            res = row.get("resistance")
            res_lvl = res.get("level") if isinstance(res, dict) else res
            parts = []
            if row.get("entry_low") and row.get("entry_high"):
                parts.append(f"entry zone {_fmt_price(row['entry_low'])}-{_fmt_price(row['entry_high'])}")
            for label, val in (("stop", row.get("stop")), ("target", row.get("target")),
                               ("resistance", res_lvl), ("SMA20", row.get("sma_20")), ("SMA50", row.get("sma_50"))):
                if val not in (None, "", 0):
                    parts.append(f"{label} {_fmt_price(val)}")
            if row.get("rsi") is not None:
                try:
                    parts.append(f"RSI {float(row['rsi']):.1f}")
                except (TypeError, ValueError):
                    pass
            lines.append("Levels (re-entry desk" + (f", computed {lv_asof}" if lv_asof else "") + "): "
                         + (" · ".join(parts) or "none recorded"))
        else:
            lines.append(f"Levels: {sym} is not on the re-entry desk, so no support, resistance or stop is on file.")
        a = analysts.get(sym)
        if a:
            rating = str(a.get("rating") or "no rating").replace("_", " ").title()
            age = (f", {a.get('age_days')} days old, may be out of date" if a.get("stale") else "")
            line = f"Analysts (Yahoo, as of {_fmt_day(a.get('as_of'))}{age}): {rating}"
            if a.get("analysts"):
                line += f" · {a['analysts']} analysts"
            if a.get("target_mean") is not None:
                line += f" · mean target {_fmt_price(a['target_mean'])}"
                if a.get("target_low") is not None and a.get("target_high") is not None:
                    line += f" (low {_fmt_price(a['target_low'])}, high {_fmt_price(a['target_high'])})"
            lines.append(line)
        elif analyst_domain is not None or "analyst" in str(avail.get("subject_question") or "").lower():
            lines.append(f"Analysts: no coverage on file for {sym}.")
        items = [r for r in research if str(r.get("symbol") or "").upper() == sym]
        if items:
            lines.append("Research on file:")
            for it in items:
                body = _MARKDOWN_CHARS.sub(" ", str(it.get("summary") or it.get("topic") or "")).strip()
                lines.append(f"- {_fmt_day(it.get('as_of'))} · {_research_label(str(it.get('research_type') or ''))}: {body[:260]}")
        else:
            lines.append(f"Research on file: none about {sym}.")
        take = _subject_takeaway(sym, p, row, a, items)
        if take:
            lines.append("What this means: " + take)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _subject_required_tokens(symbols: list[str], avail: dict[str, Any]) -> list[str]:
    """What a summary must keep: each symbol's close and, with coverage, the mean target and its date."""
    req: list[str] = []
    analysts = {str(v.get("symbol") or "").upper(): v for v in ((avail.get("analyst_view") or {}).get("items") or [])}
    for sym in symbols:
        p = (avail.get("subject_price") or {}).get(sym) or {}
        if p.get("close") is not None:
            req.append(_fmt_price(p["close"]))
        a = analysts.get(sym)
        if a and a.get("target_mean") is not None:
            req += [_fmt_price(a["target_mean"]), _fmt_day(a.get("as_of"))]
    return req


def _subject_flash_enabled() -> bool:
    return _env("CIO_SUBJECT_FLASH", "1").lower() not in ("0", "false", "off", "no")


def _subject_flash_call(messages: list[dict[str, str]]) -> dict[str, Any]:
    from scripts.lib.cio_plan_enrichment import call_governed_llm, load_llm_policy  # noqa: PLC0415

    return call_governed_llm(messages, load_llm_policy(), use_pro=False, task_type="operator_reply")


_SUBJECT_FLASH_BANNED = ("ORDER PLACED", "BUYING NOW", "SUBMITTED", "FILLED", "I WILL BUY", "EXECUTING",
                         "BROKER ORDER", "YOU SHOULD BUY", "YOU SHOULD SELL")


def _subject_flash_problems(text: str, *, facts: str, symbols: list[str], required: list[str]) -> list[str]:
    problems: list[str] = []
    if not text or len(text) < 60 or len(text) > 2500:
        problems.append("length")
    upper = (text or "").upper()
    for sym in symbols:
        if not re.search(rf"(?<![A-Z]){re.escape(sym.upper())}(?![A-Z])", upper):
            problems.append(f"missing_symbol:{sym}")
    for tok in required:
        if tok and tok not in (text or ""):
            problems.append(f"missing:{tok}")
    if any(b in upper for b in _SUBJECT_FLASH_BANNED):
        problems.append("banned_phrase")
    try:
        try:
            from lib.agent_number_grounding import check_grounding  # noqa: PLC0415
        except ImportError:
            from scripts.lib.agent_number_grounding import check_grounding  # noqa: PLC0415
        rep_ = check_grounding([text or ""], facts, min_unsupported=1, max_share=0.0)
        if rep_["unsupported"]:
            problems.append("numbers_not_in_facts:" + "|".join(rep_["unsupported"][:5]))
    except Exception as exc:  # noqa: BLE001
        problems.append(f"grounding_check_failed:{type(exc).__name__}")
    return problems


def curate_subject_reply_with_flash(*, operator_text: str, facts: str, symbols: list[str],
                                    required: list[str]) -> dict[str, Any]:
    """A short DeepSeek Flash summary of the subject brief, kept only if it is faithful.

    Rejected (and the brief itself is sent) unless every number in the summary is
    in the brief, each symbol, close, mean target and as-of date survive, and it
    carries no order language. The model words; the house supplies every fact.
    """
    out: dict[str, Any] = {"ok": False, "text": facts, "source": "deterministic", "model": None, "error": None}
    system = (
        "You are Alex, the CIO desk assistant on Telegram. Authority: READ_ONLY_ADVISORY. "
        "Summarise the FACTS into a short, plain answer to the operator's question: how the stock is doing, "
        "its levels, what analysts say with the as-of date and age, what the research on file says, and what it means. "
        "Use only the FACTS. Every number you write must appear in the FACTS exactly as written there. "
        "Keep the as-of dates. Say plainly when something is old, thin or missing. "
        "Do not add facts, forecasts, or buy or sell instructions. Do not place orders. "
        "Short lines with *bold* labels, about 12 lines at most."
    )
    try:
        from scripts.lib.agent_untrusted_data import untrusted_delimiter
        _ask = untrusted_delimiter(
            content_type="operator_message", source="telegram", content=(operator_text or "")[:300],
        )
    except Exception:
        _ask = f"Operator asked: {(operator_text or '')[:300]}"
    user = f"{_ask}\n\nFACTS (the only source you may use):\n{facts}"
    try:
        llm = _subject_flash_call([{"role": "system", "content": system}, {"role": "user", "content": user}])
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"flash_call:{type(exc).__name__}"
        return out
    if not llm.get("ok"):
        out["error"] = str(llm.get("error") or llm.get("governance_code") or "flash_failed")
        out["model"] = llm.get("model")
        return out
    text = str(llm.get("content") or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:markdown|md|text)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    problems = _subject_flash_problems(text, facts=facts, symbols=symbols, required=required)
    if problems:
        out["error"] = "flash_validation_rejected:" + ",".join(problems)[:300]
        out["model"] = llm.get("model")
        return out
    if "READ_ONLY" not in text.upper():
        text = text.rstrip() + "\nREAD_ONLY_ADVISORY"
    out.update({"ok": True, "text": text, "source": "deepseek_flash",
                "model": llm.get("model") or "deepseek-flash", "error": None})
    return out


#: Per-subject conversation recall (2026-09-13, operator: "connect chat memory
#: recall per guid"). Operator questions and agent replies were already stored in
#: operator_conversation_turns bound to subject_guid, but the desk never read them,
#: so every question about a company started from nothing.
SUBJECT_MEMORY_SQL = """SELECT o.message_id, o.occurred_at, o.symbol, o.subject_guid::text AS subject_guid,
       o.text AS question,
       (SELECT a.text FROM operator_conversation_turns a
         WHERE a.role = 'agent' AND a.chat_id = o.chat_id
           AND a.reply_to_message_id = o.message_id
         ORDER BY a.occurred_at ASC LIMIT 1) AS answer
  FROM operator_conversation_turns o
 WHERE o.role = 'operator'
   AND o.subject_guid = ANY(%s::uuid[])
   AND o.chat_id = %s
   AND o.message_id IS DISTINCT FROM %s
   AND o.occurred_at > NOW() - (%s * INTERVAL '1 day')
 ORDER BY o.occurred_at DESC
 LIMIT %s"""
_MEMORY_DROP_LINE = re.compile(r"(?i)^\s*(sources:|went outside|read_only_advisory|no orders|cc:|pending:)")


def _subject_memory_enabled() -> bool:
    return _env("CIO_SUBJECT_MEMORY", "1").lower() not in ("0", "false", "off", "no")


def _subject_guids(intent: dict[str, Any]) -> dict[str, str]:
    """symbol -> subject_guid for the named symbols: the intent's resolved subjects first, then the registry."""
    out: dict[str, str] = {}
    for s in intent.get("subjects") or []:
        if isinstance(s, dict) and s.get("symbol") and s.get("guid"):
            out.setdefault(str(s["symbol"]).upper(), str(s["guid"]))
    for sym in [str(x).upper() for x in (intent.get("symbols") or []) if str(x).strip()]:
        if sym in out:
            continue
        try:
            try:
                from lib.writers.receipt import resolve_subject_identity  # noqa: PLC0415
            except ImportError:
                from scripts.lib.writers.receipt import resolve_subject_identity  # noqa: PLC0415
            guid, _verdict = resolve_subject_identity({"symbol": sym})
        except Exception:  # noqa: BLE001
            guid = None
        if guid:
            out[sym] = str(guid)
    return out


def subject_memory(intent: dict[str, Any], *, chat_id: str, message_id: Any,
                   days: Optional[int] = None, per_symbol: int = 3) -> dict[str, list[dict[str, Any]]]:
    """Earlier exchanges about each named subject in this chat, newest first. Read-only.

    Keyed by subject_guid, so "Visa" and "V" are the same memory. The question
    being answered is excluded by message id. Degrades to {} on any failure.
    """
    if not _subject_memory_enabled() or not str(chat_id or "").strip():
        return {}
    try:
        window = int(days if days is not None else _env("CIO_SUBJECT_MEMORY_DAYS", "30"))
    except ValueError:
        window = 30
    try:
        current = int(message_id) if message_id not in (None, "") else None
    except (TypeError, ValueError):
        current = None
    out: dict[str, list[dict[str, Any]]] = {}
    for sym, guid in list(_subject_guids(intent).items())[:3]:
        try:
            rows = _research_db_query(SUBJECT_MEMORY_SQL, ([guid], str(chat_id), current, window, int(per_symbol)))
        except Exception:  # noqa: BLE001
            continue
        exchanges = []
        for r in rows or []:
            asked = r.get("occurred_at")
            exchanges.append({
                "asked_at": asked.isoformat() if hasattr(asked, "isoformat") else (str(asked) if asked else None),
                "question": str(r.get("question") or ""),
                "answer": str(r.get("answer") or "") or None,
                "message_id": r.get("message_id"),
                "subject_guid": r.get("subject_guid") or guid,
            })
        if exchanges:
            out[sym] = exchanges
    return out


def _memory_excerpt(text: Any, limit: int) -> str:
    lines = [ln for ln in str(text or "").splitlines() if ln.strip() and not _MEMORY_DROP_LINE.match(ln)]
    body = _MARKDOWN_CHARS.sub(" ", " ".join(lines))
    body = " ".join(_tidy_numbers(body).split())
    return body if len(body) <= limit else body[: limit - 1].rstrip() + "…"


def _asked_label(iso: Any) -> str:
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%b %d %H:%M")
    except (TypeError, ValueError):
        return ""


def _close_on_or_before(bars: list[Any], day: str) -> Optional[tuple[str, float]]:
    best = None
    for d, c in bars or []:
        if str(d)[:10] <= day and c:
            best = (str(d)[:10], float(c))
    return best


def format_subject_memory(symbols: list[str], avail: dict[str, Any]) -> str:
    """'Earlier on V': prior questions, what was answered, and the price move since."""
    memory = avail.get("subject_memory") or {}
    prices = avail.get("subject_price") or {}
    blocks: list[str] = []
    for sym in symbols:
        exchanges = memory.get(sym) or []
        if not exchanges:
            continue
        lines = [f"Earlier on {sym} (from our conversation):"]
        for ex in exchanges:
            when = _asked_label(ex.get("asked_at"))
            q = _memory_excerpt(ex.get("question"), 90)
            lines.append(f"- {when} you asked: \"{q}\"")
            if ex.get("answer"):
                lines.append(f"  I answered then: \"{_memory_excerpt(ex['answer'], 140)}\"")
            else:
                lines.append("  No reply to it is on record.")
        p = prices.get(sym) or {}
        last_asked = str(exchanges[0].get("asked_at") or "")[:10]
        if p.get("close") is not None and last_asked:
            then = _close_on_or_before(p.get("bars") or [], last_asked)
            if then and str(p.get("price_date") or "")[:10] > then[0]:
                move = (float(p["close"]) - then[1]) / then[1] * 100.0
                lines.append(f"Since you last asked ({_fmt_day(last_asked)}): close {_fmt_price(then[1])} on "
                             f"{_fmt_day(then[0])}, now {_fmt_price(p['close'])} ({move:+.1f}%).")
            elif then:
                lines.append(f"Since you last asked ({_fmt_day(last_asked)}): no new close yet; "
                             f"last close {_fmt_price(p['close'])} on {_fmt_day(p.get('price_date'))}.")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def subject_research(symbols: list[str], *, limit: int = 4,
                     include_operational: bool = False) -> list[dict[str, Any]]:
    """The research rows that are ABOUT these symbols, with their content.

    WHY THIS EXISTS. The `hermes_research` evidence domain carried four values:
    promoted_research_count, staged_research_count, latest_topics and
    model_provider. Not one of them is about any particular company. The counts
    are `SELECT COUNT(*) FROM hermes_research_intelligence` with no symbol
    filter, so they are identical for every question ever asked.

    On 2026-09-11 the operator asked "What are the latest analyst predictions on
    Walmart" and was answered, in full:

        Hermes: promoted=2502 staged=342 topics=[]

    2502 is every research row in the system. WMT had 3. The desk had reported
    on its own pipeline instead of reading the research -- telemetry about the
    machine standing in for knowledge about the subject. No gate in front of
    those counters could have fixed that, because a count of rows is not a
    weaker answer than the rows, it is not an answer at all.

    So the domain now carries ROWS. If there are none for the subject, the
    caller gets nothing and the honest "no vetted facts / queued a pull" path
    runs, which is what should have happened in the first place.

    Read-only. Degrades to empty, never raises: absent research is a legitimate
    state and must not be confused with a broken read.
    """
    syms = [str(x).upper().strip() for x in (symbols or []) if str(x).strip()]
    if not syms:
        return []
    conn = None
    try:
        import psycopg2  # noqa: PLC0415

        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            dbname=os.environ.get("DB_NAME", "trade_ai"),
            user=os.environ.get("DB_USER", "trade_ai"),
            password=os.environ.get("DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD"),
        )
        cur = conn.cursor()
        cur.execute(
            # The newest few rows OF EACH research type. A plain newest-first window
            # let the options desk's per-run rows and the stop-curation notes fill
            # it: V's only deep-research note (2026-09-09) never reached selection.
            SUBJECT_RESEARCH_SQL,
            (syms, SUBJECT_RESEARCH_PER_TYPE, max(40, int(limit) * 15)),
        )
        out: list[dict[str, Any]] = []
        for sym, rtype, topic, body, conf, created in cur.fetchall():
            out.append({
                "symbol": sym,
                "research_type": rtype,
                "topic": topic,
                "summary": (body or "")[:400],
                "confidence": float(conf) if conf is not None else None,
                "as_of": created.strftime("%Y-%m-%d") if created else None,
            })
        return select_subject_research(out, include_operational=include_operational, limit=limit)
    except Exception:
        return []
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


#: Beyond this, a price target is a historical fact, not a current view. Yahoo
#: refreshes covered names daily, so a month-old row means coverage lapsed --
#: which the operator must be told, not shielded from.
ANALYST_STALE_DAYS = 7


def subject_analyst_view(symbols: list[str], *, stale_days: int = ANALYST_STALE_DAYS) -> list[dict[str, Any]]:
    """Analyst rating and price targets for these symbols, with their as-of date.

    WHY THIS EXISTS. On 2026-09-13 the operator asked "what are analysts saying
    about Walmart right now, is it a buy and what's the target" and was answered
    with three stop-curation reviews. Honest -- the reply said "Research on file
    (stop_curation)" -- but it answered a question about analyst opinion with
    risk-management notes, because research rows were the only subject-scoped
    domain the desk could read.

    The data already existed. `yahoo_analyst_targets_history` carries
    recommendation_key, recommendation_mean (a real 1-5 scale, 99.8% on-scale
    across 8,128 rows), and low/mean/high price targets with an analyst count.
    Nothing read it.

    FRESHNESS IS PART OF THE ANSWER, not a filter in front of it. WMT's newest
    row is 2026-08-11: 682 of 1,328 covered symbols are more than 30 days old,
    because a symbol drops out of the refresh set when it leaves the watched
    universe. A month-old target presented as "right now" would be the same
    class of defect as the Finviz column shift -- confidently wrong. So the row
    is returned WITH its age and a `stale` flag, and the caller says so.

    Read-only. Degrades to empty, never raises.
    """
    syms = [str(x).upper().strip() for x in (symbols or []) if str(x).strip()]
    if not syms:
        return []
    conn = None
    try:
        import psycopg2  # noqa: PLC0415

        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            dbname=os.environ.get("DB_NAME", "trade_ai"),
            user=os.environ.get("DB_USER", "trade_ai"),
            password=os.environ.get("DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD"),
        )
        cur = conn.cursor()
        out: list[dict[str, Any]] = []
        for sym in syms:
            cur.execute(
                "SELECT snapshot_date, current_price, recommendation_key,"
                "       recommendation_mean, target_low_price, target_mean_price,"
                "       target_high_price, number_of_analyst_opinions, source"
                "  FROM yahoo_analyst_targets_history"
                " WHERE symbol = %s AND recommendation_key IS NOT NULL"
                " ORDER BY snapshot_date DESC LIMIT 1",
                (sym,),
            )
            row = cur.fetchone()
            if not row:
                continue
            as_of = row[0]
            age = None
            try:
                age = (datetime.now(timezone.utc).date() - as_of).days
            except Exception:
                pass
            mean = row[3]
            # The same 1-5 plausibility rail the Finviz parser now enforces: a
            # rating off its declared scale is not a weak rating, it is not a
            # rating. 20 of 8,128 rows carry 0.000, which is "no coverage".
            if mean is not None and not (1 <= float(mean) <= 5):
                mean = None
            out.append({
                "symbol": sym,
                "as_of": str(as_of),
                "age_days": age,
                "stale": (age is not None and age > stale_days),
                "rating": row[2],
                "rating_mean": float(mean) if mean is not None else None,
                "price_at_snapshot": float(row[1]) if row[1] is not None else None,
                "target_low": float(row[4]) if row[4] is not None else None,
                "target_mean": float(row[5]) if row[5] is not None else None,
                "target_high": float(row[6]) if row[6] is not None else None,
                "analysts": row[7],
                "source": row[8],
            })
        return out
    except Exception:
        return []
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def _enqueue_hermes_research(
    *,
    symbols: list[str],
    chat_id: str,
    pending_id: str,
    operator_text: str,
) -> dict[str, Any]:
    """Operator-forced Hermes research when research need is blocking."""
    out: dict[str, Any] = {"ok": False, "emitted": 0}
    try:
        from datetime import timedelta

        from scripts.lib.hermes_research_loop import emit_research_for_plan
        from scripts.lib.cio_plans import CIOPlanStore

        store = CIOPlanStore()
        revisit = (datetime.now(timezone.utc) + timedelta(hours=6)).replace(microsecond=0).isoformat()
        plan = store.create_plan(
            situation_type="S0_OPERATOR_CONVERSE",
            symbols=symbols[:4] or ["BOOK"],
            title="Operator research pull",
            summary=(operator_text or "")[:400],
            options=[
                {"id": "wait", "label": "Wait for Hermes", "pros": "Vetted", "cons": "Delay"},
                {"id": "pass", "label": "Pass", "pros": "No spend", "cons": "No answer"},
            ],
            recommendation="Pull Hermes research (operator_forced). READ_ONLY.",
            risks=["DATA_UNAVAILABLE until Hermes lands"],
            evidence_refs=[{"domain": "hermes_research", "fields_used": ["operator_forced"]}],
            revisit_at=revisit,
            owner_agent="alex",
        )
        plan_id = plan.get("plan_id") if isinstance(plan, dict) else None
        if not plan_id:
            out["error"] = "no_plan_id"
            return out
        emit = emit_research_for_plan(
            plan if isinstance(plan, dict) else {"plan_id": plan_id, "symbols": symbols},
            operator_forced=True,
            reason="operator_desk_research_need",
            # 2026-09-14 HPE: the operator asked about entry, support/resistance,
            # analysts and volume; Hermes was sent the generic "what research would
            # change the advisory" question and answered that instead.
            questions=operator_research_questions(symbols, operator_text),
        )
        out["ok"] = bool((emit or {}).get("ok", True)) if isinstance(emit, dict) else True
        out["emitted"] = 0 if isinstance(emit, dict) and emit.get("skipped") else 1
        out["plan_id"] = plan_id
        out["emit"] = emit if isinstance(emit, dict) else {"raw": str(emit)[:200]}
        _gap_row = {
                "ts": _now(),
                "pending_id": pending_id,
                "chat_id": chat_id,
                "kind": "hermes_operator_forced",
                "plan_id": plan_id,
                # A reused request answers from ANOTHER plan's result; the join
                # needs the research id to find it.
                "research_id": (emit or {}).get("research_id") if isinstance(emit, dict) else None,
                "symbols": symbols,
                "authority": AUTHORITY,
            }
        try:
            from scripts.lib import research_identity as _RI  # noqa: PLC0415
            _sym0 = (symbols[:1] or [None])[0]
            if _sym0:
                _tag = _RI.resolve(_RI.load_registry(), _sym0)
                if _tag and _tag.get("subject_guid"):
                    _gap_row["subject_guid"] = _tag["subject_guid"]
                    _gap_row["issuer_guid"] = _tag.get("issuer_guid")
        except Exception:  # noqa: BLE001
            pass
        _append_jsonl(OPERATOR_GAP_REQUESTS_PATH, _gap_row)
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}:{exc}"
    return out


#: Per-process dedupe so one turn cannot enqueue the same symbol twice.
_RESEARCH_GAP_ENQUEUED: set[str] = set()


def enqueue_research_gap(
    *,
    symbols: list[str],
    chat_id: str = "",
    pending_id: str = "",
    operator_text: str = "",
) -> dict[str, Any]:
    """Auto-queue Hermes research for named symbols missing house research/levels.

    Enqueues each symbol at most once per process (and once per pending_id+symbol).
    Prefer this over telling the operator to type ``research S``.
    """
    syms = []
    for raw in symbols or []:
        u = str(raw or "").strip().lstrip("$").upper()
        if u and u.isalpha() and 1 <= len(u) <= 5 and u not in syms:
            syms.append(u)
    if not syms:
        return {"ok": False, "emitted": 0, "error": "no_symbols", "ack": ""}
    fresh: list[str] = []
    for sym in syms:
        key = f"{pending_id or '_'}:{sym}"
        if key in _RESEARCH_GAP_ENQUEUED:
            continue
        _RESEARCH_GAP_ENQUEUED.add(key)
        fresh.append(sym)
    if not fresh:
        return {
            "ok": True,
            "emitted": 0,
            "symbols": syms,
            "deduped": True,
            "ack": "",
        }
    result = _enqueue_hermes_research(
        symbols=fresh,
        chat_id=chat_id,
        pending_id=pending_id or f"gap_{uuid.uuid4().hex[:10]}",
        operator_text=operator_text or f"research gap auto-queue for {', '.join(fresh)}",
    )
    labels = ", ".join(fresh[:6])
    result["symbols"] = fresh
    result["ack"] = (
        f"House research for {labels} is queued; fetching fresh quotes and levels."
    )
    return result


# ── Hermes join-back ─────────────────────────────────────────────────────────
#
# 2026-09-14 09:12 ET the operator asked "Do some more research on HPE ...".
# Hermes claimed the request at 09:15, completed it at 09:16 (critic VALID) and
# wrote hermes_research_results.jsonl. The pending opr_74cc87d6ae62 waited on a
# PROMOTED row in hermes_research_intelligence, which the Hermes CIO worker
# never writes, so the answer could not reach the operator: the pending would
# have been retracted as "could not answer" at 11:12 with the research on disk.
# 0 of 2 research pendings on file were ever fulfilled. The join key is the
# pending id recorded next to the Hermes plan / research id at enqueue time.

#: pending_id → Hermes plan_id / research_id, written by _enqueue_hermes_research.
OPERATOR_GAP_REQUESTS_PATH = PROJECT_ROOT / "data" / "cio" / "cio_operator_gap_requests.jsonl"
#: hermes_bridge_backend sends at most 220 characters of each question.
_HERMES_QUESTION_CHARS = 220
_HERMES_OPERATOR_QUESTIONS = 3
_ET = ZoneInfo("America/New_York")


def operator_research_questions(symbols: list[str], operator_text: str) -> Optional[list[dict[str, str]]]:
    """The operator's own question, split into Hermes-sized pieces, then the thesis check.

    None when there is no text, so the Hermes default question set applies.
    """
    words = " ".join(str(operator_text or "").split()).split()
    if not words:
        return None
    subject = ", ".join(str(s).upper() for s in (symbols or []) if str(s).strip())[:40] or "the book"
    prefix = f"{subject} — operator asked: "
    room = _HERMES_QUESTION_CHARS - len(prefix)
    pieces: list[str] = []
    cur = ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > room:
            pieces.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        pieces.append(cur)
    pieces = pieces[:_HERMES_OPERATOR_QUESTIONS]
    out = [{"intent": "operator_question", "text": (prefix + p)[:_HERMES_QUESTION_CHARS]} for p in pieces]
    out.append({"intent": "thesis_check",
                "text": f"What research would change the advisory on {subject} under the live desk thesis?"})
    return out


def _hermes_store():
    try:
        from scripts.lib import cio_hermes_research as hr  # noqa: PLC0415
    except ImportError:  # pragma: no cover -- hub import path
        from lib import cio_hermes_research as hr  # type: ignore  # noqa: PLC0415
    return hr


def _hermes_requests_for_pending(pending_id: str) -> list[dict[str, Any]]:
    """Hermes request metas (projection rows) this pending caused, newest last."""
    if not pending_id:
        return []
    asks = [r for r in _read_jsonl(OPERATOR_GAP_REQUESTS_PATH)
            if r.get("pending_id") == pending_id and r.get("kind") == "hermes_operator_forced"]
    if not asks:
        return []
    try:
        hr = _hermes_store()
        by_rid = (hr._load_projection().get("by_research_id") or {})
    except Exception:  # noqa: BLE001
        return []
    plan_ids = {str(a.get("plan_id")) for a in asks if a.get("plan_id")}
    rids = {str(a.get("research_id")) for a in asks if a.get("research_id")}
    metas = [dict(m, research_id=rid) for rid, m in by_rid.items()
             if isinstance(m, dict) and (rid in rids or str(m.get("plan_id")) in plan_ids)]
    return sorted(metas, key=lambda m: str(m.get("completed_ts") or m.get("created_ts") or ""))


def _hermes_result_by_id(result_id: str) -> Optional[dict[str, Any]]:
    path = _hermes_store().RESULT_PATH
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if result_id in line:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("result_id") == result_id:
                return row
    return None


def hermes_result_for_pending(pending_id: str) -> Optional[dict[str, Any]]:
    """The newest completed Hermes result this pending asked for, or None."""
    for meta in reversed(_hermes_requests_for_pending(pending_id)):
        rid = meta.get("latest_result_id")
        if str(meta.get("status")) == "completed" and rid:
            res = _hermes_result_by_id(str(rid))
            if res:
                return res
    return None


def plain_research_failure(error: str, symbols: list[str]) -> str:
    """Operator-facing reason. Never paste the guard exception into Telegram."""
    names = ", ".join(s for s in symbols[:4] if s) or "the subject"
    low = (error or "").lower()
    if any(p in low for p in (
        "approved primary sources",
        "sufficient_for_synthesis",
        "rag retrieval is split",
    )):
        return (
            f"promoted research did not land for {names}: the evidence was split "
            "between supporting and contradictory items and had no approved primary source"
        )
    if "execution language" in low:
        return (
            f"promoted research did not land for {names}: the research draft was refused "
            "by the read-only guard"
        )
    short = " ".join(str(error or "research run failed").split())[:140]
    return f"promoted research did not land for {names}: {short}"


def _has_house_facts(avail: dict[str, Any], symbols: list[str]) -> bool:
    prices = avail.get("subject_price") or {}
    if any(isinstance(prices.get(s), dict) and prices[s].get("close") is not None for s in symbols):
        return True
    if (avail.get("analyst_view") or {}).get("items"):
        return True
    if avail.get("subject_levels") or avail.get("subject_memory"):
        return True
    if avail.get("news") or avail.get("news_articles") or avail.get("catalyst_events"):
        return True
    return False


def house_evidence_after_research_failure(
    evidence: dict[str, Any], symbols: list[str], error: str,
) -> Optional[dict[str, Any]]:
    """Drop the research block when house facts can still answer.

    A failed Hermes run must not throw away a price, an analyst row, or levels
    that were already gathered. Returns None when those stores are empty.
    """
    avail = dict((evidence or {}).get("available") or {})
    if not symbols or not _has_house_facts(avail, symbols):
        return None
    note = plain_research_failure(error, symbols)
    avail["research_failure_note"] = note
    blocking = [
        g for g in ((evidence or {}).get("blocking_gaps") or [])
        if isinstance(g, dict) and g.get("domain") not in ("hermes_research", "quote_price")
    ]
    ev = dict(evidence or {})
    ev["available"] = avail
    ev["blocking_gaps"] = blocking
    ev["complete"] = not blocking and bool(avail)
    return ev


def hermes_failure_for_pending(pending_id: str) -> Optional[str]:
    """Why Hermes failed this pending's research, when every request it caused failed."""
    metas = _hermes_requests_for_pending(pending_id)
    if metas and all(str(m.get("status")) == "failed" for m in metas):
        return str(metas[-1].get("error") or metas[-1].get("last_error") or "research run failed")[:160]
    return None


def join_hermes_result(evidence: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Evidence with the Hermes result standing in for the research gap it closes."""
    ev = dict(evidence or {})
    avail = dict(ev.get("available") or {})
    answer = next((a.get("summary") for a in (result.get("answers") or [])
                   if isinstance(a, dict) and a.get("summary")), "") or result.get("summary") or ""
    item = {
        "symbol": str(result.get("symbol") or "").upper() or None,
        "research_type": "hermes_operator_research",
        "topic": "Hermes research on your question",
        "summary": _tidy_numbers(answer)[:400],
        "confidence": result.get("confidence"),
        "as_of": str(result.get("completed_ts") or "")[:10] or None,
    }
    hermes = dict(avail.get("hermes_research") or {})
    hermes["items"] = [item] + [i for i in (hermes.get("items") or []) if isinstance(i, dict)]
    hermes["symbols"] = sorted({i["symbol"] for i in hermes["items"] if i.get("symbol")})
    avail["hermes_research"] = hermes
    avail["hermes_result"] = result
    ev["available"] = avail
    ev["gaps"] = [g for g in (ev.get("gaps") or []) if g.get("domain") != "hermes_research"]
    ev["blocking_gaps"] = [g for g in (ev.get("blocking_gaps") or []) if g.get("domain") != "hermes_research"]
    ev["complete"] = not ev["blocking_gaps"] and bool(avail)
    ev["sources"] = list(ev.get("sources") or []) + [f"hermes_research_results · {result.get('result_id')}"]
    return ev


def _plain(text: Any, n: int) -> str:
    s = _MARKDOWN_CHARS.sub(" ", _tidy_numbers(" ".join(str(text or "").split())))
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def format_hermes_section(result: dict[str, Any]) -> str:
    """Hermes' answer, every line labelled as AI-model output (it read Trade-AI evidence)."""
    # Spelled out on every line (operator 2026-09-14: a bare coloured dot means nothing).
    pill = "🟣 AI model:"
    model = str(result.get("model") or "deepseek-flash")
    try:
        done = datetime.fromisoformat(str(result.get("completed_ts")).replace("Z", "+00:00"))
        when = done.astimezone(_ET).strftime("%H:%M ET")
    except Exception:  # noqa: BLE001
        when = "time unknown"
    bits = [f"finished {when}"]
    if result.get("confidence") is not None:
        bits.append(f"confidence {float(result['confidence']):.2f}")
    if result.get("thesis_stance"):
        bits.append(f"stance {_plain(result['thesis_stance'], 20)}")
    n_ev = len(result.get("evidence_links") or result.get("source_refs") or [])
    lines = [f"{pill} Hermes research — {model} read {n_ev} Trade-AI evidence item(s); "
             f"model knowledge where it goes beyond them · " + " · ".join(bits)]
    for a in (result.get("answers") or [])[:4]:
        if isinstance(a, dict) and a.get("summary"):
            lines.append(f"{pill} {_plain(a['summary'], 420)}")
    sev = {"high": 0, "medium": 1, "low": 2}
    findings = sorted((f for f in (result.get("findings") or []) if isinstance(f, dict) and f.get("text")),
                      key=lambda f: sev.get(str(f.get("severity")), 3))
    for f in findings[:3]:
        lines.append(f"{pill} Finding ({_plain(f.get('severity') or 'n/a', 10)}): {_plain(f['text'], 260)}")
    gaps = [g for g in (result.get("research_gaps_remaining") or []) if g][:3]
    if gaps:
        lines.append(f"{pill} Still unknown: " + "; ".join(_plain(g, 140) for g in gaps))
    lims = [x for x in (result.get("limitations") or []) if x][:2]
    if lims:
        lines.append(f"{pill} Limits: " + "; ".join(_plain(x, 160) for x in lims))
    lines.append("🔵 Looked up outside Trade-AI: nothing — Hermes did not search the web; "
                 "it read Trade-AI evidence only.")
    return "\n".join(lines)


def _insert_before_authority_tail(text: str, block: str) -> str:
    """Put a block above the trailing authority line, which must stay last."""
    if not block:
        return text
    lines = (text or "").rstrip().split("\n")
    tail = [lines.pop()] if lines and _AUTHORITY_TAIL_RE.match(lines[-1].strip()) else []
    return "\n".join([*lines, "", block, *tail]).strip("\n")



# The Sources footer lives in ONE module now (scripts/lib/reply_provenance.py) so
# every reply path -- not only this desk loop -- builds its line the same way and
# the converse chokepoint can recognise it. Re-exported under the old name so
# callers and tests that import it from here keep working.
try:
    from scripts.lib.reply_provenance import (  # noqa: E402
        ROLE_GENERAL_KNOWLEDGE as _ROLE_GENERAL_KNOWLEDGE,
        ROLE_WORDING_ONLY as _ROLE_WORDING_ONLY,
        ReplyProvenance as _ReplyProvenance,
        finalize_operator_reply as _finalize_operator_reply,
        labels_from_evidence as _labels_from_evidence,
        with_sources_footer as _with_sources_footer,
    )
except ImportError:  # pragma: no cover -- hub import path (lib.* spelling)
    from lib.reply_provenance import (  # type: ignore  # noqa: E402
        ROLE_GENERAL_KNOWLEDGE as _ROLE_GENERAL_KNOWLEDGE,
        ROLE_WORDING_ONLY as _ROLE_WORDING_ONLY,
        ReplyProvenance as _ReplyProvenance,
        finalize_operator_reply as _finalize_operator_reply,
        labels_from_evidence as _labels_from_evidence,
        with_sources_footer as _with_sources_footer,
    )


def _curate_from_evidence_core(operator_text: str, evidence: dict[str, Any]) -> dict[str, Any]:
    """Flash rewrites vetted facts only — fail-soft to raw card."""
    avail = evidence.get("available") or {}

    # Meta / freeform — never run re-entry Flash curate
    if avail.get("meta_card"):
        return {
            "ok": True,
            "text": avail["meta_card"],
            "source": "runtime_meta",
            "model": None,
        }
    if avail.get("freeform_context") is not None:
        return answer_freeform_with_flash(
            operator_text,
            avail.get("freeform_context") or {},
            list(avail.get("soft_gaps") or evidence.get("gaps") or []),
        )
    if avail.get("unclear_card"):
        return {
            "ok": True,
            "text": avail["unclear_card"],
            "source": "unclear_clarifier",
            "model": None,
        }

    from scripts.lib.cio_telegram_converse import (
        curate_reentry_reply_with_flash,
        _reentry_flash_enabled,
    )

    card = avail.get("reentry_card") or ""
    sym_cards = avail.get("reentry_symbol_cards") or {}
    if sym_cards:
        # The operator named the symbol(s): answer about them, not the whole desk.
        card = "\n\n".join(sym_cards[k] for k in sym_cards)
    book = avail.get("book") or ""
    risk = avail.get("risk")
    hermes = avail.get("hermes_research")
    subject_syms = list(avail.get("subject_symbols") or [])
    if sym_cards and avail.get("subject_memory"):
        mem_cards = format_subject_memory(list(sym_cards), avail)
        if mem_cards:
            card = card + "\n\n" + mem_cards
    if subject_syms and not sym_cards and not card:
        brief = format_subject_brief(subject_syms, avail)
        mem = format_subject_memory(subject_syms, avail)
        if mem:
            brief += "\n\n" + mem
        findings = evidence.get("contract_findings") or []
        if findings:
            brief += ("\nFacts available but not assembled: "
                      + "; ".join(f"{f.get('domain')} ({f.get('code')})" for f in findings[:6]))
        if brief.strip():
            if _subject_flash_enabled():
                flash = curate_subject_reply_with_flash(
                    operator_text=operator_text, facts=brief, symbols=subject_syms,
                    required=_subject_required_tokens(subject_syms, avail),
                )
                if flash.get("ok"):
                    return {"ok": True, "text": flash["text"], "source": "deepseek_flash",
                            "model": flash.get("model"), "flash_error": None}
            return {"ok": True, "text": brief + "\nREAD_ONLY_ADVISORY", "source": "tradeai_deterministic",
                    "model": None}
    facts = card
    extras: list[str] = []
    if book:
        extras.append(f"Book: {book}")
    if risk:
        extras.append(
            "Risk: heat={portfolio_heat_pct} risk$={total_risk_dollars} "
            "at_risk={positions_at_risk} dd={max_drawdown_pct} stops={stops_active}".format(**{
                k: risk.get(k) for k in (
                    "portfolio_heat_pct", "total_risk_dollars", "positions_at_risk",
                    "max_drawdown_pct", "stops_active",
                )
            })
        )
    if hermes and hermes.get("items"):
        # What the research SAYS. Never how many rows there are.
        lines = []
        for it in hermes["items"][:4]:
            head = " ".join(x for x in (it.get("symbol"), it.get("as_of")) if x)
            topic = it.get("topic") or it.get("research_type") or "research"
            body = (it.get("summary") or "").strip()
            lines.append(f"- {head} {topic}: {body}"[:400])
        kinds = sorted({str(i.get("research_type") or "") for i in hermes["items"] if i.get("research_type")})
        extras.append(
            "Research on file ("
            + ", ".join(kinds or ["research"])
            + "):\n" + "\n".join(lines)
        )
    office = avail.get("office_state") or {}
    if office:
        bits = []
        rec = office.get("reconciliation") or {}
        if rec:
            bits.append(f"reconciliation actions open={rec.get('actions_open')} issues={','.join(rec.get('inconsistencies') or []) or 'none'}")
        if office.get("reentry_counts"):
            c = office["reentry_counts"]
            bits.append(f"re-entry ready={c.get('ready')} near={c.get('near')} of {c.get('total')}")
        if office.get("transitions_needing_review"):
            bits.append("theses needing review: " + ", ".join(str(t.get("symbol")) for t in office["transitions_needing_review"][:6]))
        if bits:
            extras.append("Office: " + " · ".join(bits))
    findings = evidence.get("contract_findings") or []
    if findings:
        # The store had these; the desk failed to assemble them. Say that -- never "empty".
        extras.append(
            "Facts available but not assembled (the store had them; this reply could not use them): "
            + "; ".join(f"{f.get('domain')} → {str(f.get('fact')).rsplit('.', 1)[-1]} ({f.get('code')})" for f in findings[:6])
        )
    if extras:
        facts = "\n".join(extras) + ("\n\n" + card if card else "")

    if not str(facts).strip():
        return {
            "ok": False,
            # No promise: nothing on this branch queues a pull or opens a pending.
            # "Queued a pull -- I'll reply when it lands" went to the operator on
            # 2026-09-13 with nothing queued (the gap bridge module does not exist).
            "text": (
                "Trade-AI has no vetted facts for that yet, and nothing was queued. "
                "Say 'research <ticker>' and I will queue it with an ETA.\n"
                "READ_ONLY_ADVISORY"
            ),
            "source": "empty_evidence",
        }

    ready = re.findall(r"\*([A-Z]{1,5})\*", card) if card else []
    near = re.findall(r"`([A-Z]{1,5})`", card) if card else []

    if card and not sym_cards and _reentry_flash_enabled():
        flash = curate_reentry_reply_with_flash(
            operator_text=operator_text,
            deterministic_reply=facts,
            ready_symbols=ready,
            near_symbols=near,
        )
        if flash.get("ok"):
            return {
                "ok": True,
                "text": flash["text"],
                "source": "deepseek_flash",
                "model": flash.get("model"),
            }

    text_out = facts if str(facts).endswith("READ_ONLY_ADVISORY") else str(facts) + "\nREAD_ONLY_ADVISORY"
    return {
        "ok": True,
        "text": text_out,
        "source": "tradeai_deterministic",
        "model": None,
    }


def _emit_telegram_desk_payload(intent: dict[str, Any], result: dict[str, Any]) -> None:
    """DecisionPayload@v1 when a Telegram desk reply states a decision. Fail-soft.

    Freeform already emits in ``answer_freeform_with_flash``. Meta / deferred
    replies do not state a decision. Reentry answers do.
    """
    try:
        if result.get("kind") != "answered":
            return
        iname = str((intent or {}).get("intent") or "")
        if iname != "reentry":
            return
        from scripts.lib.agent_decision_payload import emit_telegram_decision_payload
        syms = [str(s).upper() for s in ((intent or {}).get("symbols") or []) if s]
        emit_telegram_decision_payload(
            symbol=syms[0] if syms else None,
            action="ADVISORY_REPLY",
            surface="reentry",
            origin="OPERATOR_ASK",
            extra={"intent": iname, "reply_source": result.get("reply_source")},
        )
    except Exception:
        pass


#: Phase 7 gap resolver switch. ON by default; "0" restores the pre-Phase-7
#: path (open a pending, enqueue Hermes when research blocks) for the negative
#: control and for rollback.
def _gap_resolver_enabled() -> bool:
    return _env("CIO_GAP_RESOLVER", "1").lower() not in ("0", "false", "off", "no")


def _resolve_blocking_gaps(
    blocking: list[dict[str, Any]],
    *,
    intent: dict[str, Any],
    text: str,
    chat_id: str,
    pending_id: str,
) -> dict[str, Any]:
    """Run the gap resolver over each distinct blocking gap. Never raises.

    Returns the three exits the desk needs -- answered / queued / denied -- plus
    a compact receipt for the pending row and the result payload.
    """
    try:
        from scripts.lib.gap_resolver import Context, DataGap, resolve
    except ImportError:  # pragma: no cover -- hub import path
        from lib.gap_resolver import Context, DataGap, resolve  # type: ignore

    symbols = [str(s).upper() for s in (intent.get("symbols") or []) if str(s).strip()]

    def _recheck() -> Any:
        ev = gather_tradeai_evidence(intent)
        return ev.get("available") if ev.get("complete") else None

    ctx = Context(chat_id=chat_id, pending_id=pending_id, operator_text=text, recheck=_recheck,
                  hermes_enqueue=_enqueue_hermes_research)
    answered: list[dict[str, Any]] = []
    queued: list[dict[str, Any]] = []
    denied: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    for g in blocking[:6]:
        domain = str(g.get("domain") or g.get("field") or "unknown")
        subject = str(g.get("symbol") or (symbols[0] if symbols else "BOOK")).upper()
        if (domain, subject) in seen:
            continue
        seen.add((domain, subject))
        reason = str(g.get("reason") or g.get("gap_type") or "")
        why = "stale_hours" if "stale" in reason.lower() else "no_coverage"
        gap = DataGap(
            domain=domain,
            subject=subject,
            question=(text or f"{domain} for {subject}")[:300],
            why=why,
            requester=f"operator:{chat_id}" if chat_id else "desk",
            symbols=symbols,
        )
        try:
            res = resolve(gap, ctx=ctx)
        except Exception as exc:  # noqa: BLE001 -- the desk must still reply
            errors.append(f"{domain}:{type(exc).__name__}")
            continue
        row = res.to_dict()
        row["desk_domain"] = domain
        if res.answered or (res.outcome == "partial" and res.answer is not None):
            answered.append(row)
        elif res.eta_seconds is not None:
            queued.append(row)
        else:
            denied.append(row)

    etas = [int(r["eta_seconds"]) for r in queued if r.get("eta_seconds") is not None]
    eta_seconds = max(etas) if etas else None
    eta_text = None
    if eta_seconds is not None:
        eta_text = f"≈ {max(1, int(round(eta_seconds / 60.0)))} min"
    receipt = {
        "answered": [f"{r['domain']}:{r['subject']}:{r.get('vector')}" for r in answered],
        "queued": [f"{r['domain']}:{r['subject']}:{r.get('vector')}" for r in queued],
        "denied": [f"{r['domain']}:{r['subject']}" for r in denied],
        "attempts": sum(len(r.get("attempts") or []) for r in answered + queued + denied),
        "errors": errors,
        "eta_seconds": eta_seconds,
    }
    return {
        "answered": answered,
        "queued": queued,
        "denied": denied,
        "errors": errors,
        "eta_seconds": eta_seconds,
        "eta_text": eta_text,
        "receipt": receipt,
    }


def _format_resolved_answer(summary: dict[str, Any], *, intent: dict[str, Any]) -> str:
    """A vector answered. Say what, from where, and how old -- never as 'now'."""
    lines = ["🧠 *Alex · found it through a declared source*"]
    for r in summary.get("answered") or []:
        src = r.get("source") or r.get("vector") or "unknown"
        age = r.get("age_hours")
        age_txt = f", {age:g}h old" if isinstance(age, (int, float)) else ""
        head = f"• *{r.get('subject')}* {str(r.get('domain') or '').replace('_', ' ')} — via `{src}`"
        if r.get("as_of"):
            head += f" · as of {str(r.get('as_of'))[:16]}{age_txt}"
        lines.append(head)
        ans = r.get("answer")
        if isinstance(ans, dict):
            if ans.get("source") == "llm_curation":
                lines.append(f"  _curated by {ans.get('model')} from gathered evidence — not a fact source_")
                lines.append("  " + str(ans.get("text") or "")[:700])
            else:
                bits = [
                    f"{k}={v}" for k, v in ans.items()
                    if k not in ("as_of", "source", "symbol", "provider", "note") and v is not None
                ]
                lines.append("  " + ", ".join(bits)[:600])
        elif ans is not None:
            lines.append("  " + str(ans)[:700])
    if summary.get("queued"):
        lines.append(f"_Also queued: {', '.join(summary['receipt']['queued'])} — {summary.get('eta_text')}_")
    lines.append(f"No orders/stops · {AUTHORITY}")
    return "\n".join(lines)


def _format_no_coverage(summary: dict[str, Any], *, intent: dict[str, Any]) -> str:
    """Every vector denied or empty. Say so; open nothing."""
    lines = ["📭 *Alex · no coverage through any declared source*"]
    for r in summary.get("denied") or []:
        tried = ", ".join(
            f"{a.get('vector')}={a.get('outcome')}" for a in (r.get("attempts") or [])
        ) or "no vectors declared"
        beh = r.get("no_coverage_behaviour") or "say_so"
        lines.append(
            f"• *{r.get('subject')}* {str(r.get('domain') or '').replace('_', ' ')} — tried {tried}; "
            f"declared behaviour `{beh}`"
        )
    if summary.get("errors"):
        lines.append(f"_Resolver errors: {', '.join(summary['errors'])}_")
    lines.append("No pending opened — nothing declared can answer this today. Ask again tomorrow or name a source.")
    lines.append(f"No orders/stops · {AUTHORITY}")
    return "\n".join(lines)


try:
    from scripts.lib.reply_provenance import AUTHORITY_TAIL_RE as _AUTHORITY_TAIL_RE  # noqa: E402
except ImportError:  # pragma: no cover
    from lib.reply_provenance import AUTHORITY_TAIL_RE as _AUTHORITY_TAIL_RE  # noqa: E402


def _dossier_enabled() -> bool:
    return _env("CIO_SUBJECT_DOSSIER", "1").lower() not in ("0", "false", "off", "no")


#: Intents that are not about a stock even when a ticker appears in the text.
_DOSSIER_SKIP_INTENTS = ("meta_system", "attention", "unclear")

#: Dossier section -> the store label the Sources line names.
_DOSSIER_STORES = (
    ("profile", "symbol_profiles"), ("catalysts", "catalyst_events"), ("news", "news_articles"),
    ("analyst", "yahoo_analyst_targets_history"), ("sector", "sector_momentum_latest.json"),
    ("industry", "industry_momentum_latest.json"), ("research", "hermes_research_intelligence"),
    ("thesis", "symbol thesis store"), ("agents", "watchlist_agent_results"),
    ("iv", "options_iv_history"), ("dividends", "ticker_dividend_data"),
)


def _attach_subject_dossier(intent: dict[str, Any], evidence: dict[str, Any]) -> None:
    """Every stored fact about the named stock(s), pill-tagged, for any stock question.

    2026-09-14 08:40 (operator): "What about analyst reviews? What about ... the
    industry? ... not thorough and complete, and all the data is there." The desk
    answered AXTI with the re-entry card alone while symbol_profiles, analyst
    targets, catalysts, news, sector and industry momentum, research and the
    thesis all held AXTI facts. The dossier rides under whatever answer the
    intent produced, so no branch can leave them out.
    """
    syms = [str(s).upper() for s in (intent.get("symbols") or []) if str(s).strip()][:3]
    if not syms or not _dossier_enabled() or str(intent.get("intent") or "") in _DOSSIER_SKIP_INTENTS:
        return
    avail = evidence.setdefault("available", {})
    if avail.get("meta_card") or avail.get("unclear_card"):
        return
    try:
        from scripts.lib import subject_dossier as sd  # noqa: PLC0415
    except ImportError:
        from lib import subject_dossier as sd  # noqa: PLC0415
    try:
        from scripts.lib.symbol_thesis_attach import thesis_fields_for_symbol  # noqa: PLC0415
    except ImportError:
        thesis_fields_for_symbol = None  # type: ignore[assignment]
    dossier = sd.gather(
        syms, db_query=_research_db_query, runtime_dir=PROJECT_ROOT / "data" / "runtime",
        analyst_fn=subject_analyst_view, research_fn=subject_research,
        thesis_fn=(lambda s: thesis_fields_for_symbol(s, root=PROJECT_ROOT)) if thesis_fields_for_symbol else None,
        held=_held_positions_map(),
    )
    prices: dict[str, float] = {}
    known = avail.get("subject_price") or subject_price_facts(syms)
    for s, p in (known or {}).items():
        if isinstance(p, dict) and p.get("close") is not None:
            prices[str(s).upper()] = float(p["close"])
    text = sd.format_dossier(syms, dossier, prices=prices)
    if not text:
        return
    avail["subject_dossier_text"] = text
    avail["subject_dossier"] = dossier
    avail["subject_dossier_symbols"] = syms
    avail["subject_dossier_prices"] = prices
    sources = evidence.setdefault("sources", [])
    for key, label in _DOSSIER_STORES:
        if any((dossier.get(s) or {}).get(key) for s in syms) and label not in sources:
            sources.append(label)
    if any("held" in (dossier.get(s) or {}) for s in syms) and "holdings.json" not in sources:
        sources.append("holdings.json")


def gather_tradeai_evidence(intent: dict[str, Any]) -> dict[str, Any]:
    """Pull vetted Trade-AI evidence only, plus the named stock's full pill-tagged picture."""
    evidence = _gather_tradeai_evidence_core(intent)
    try:
        _attach_subject_dossier(intent, evidence)
    except Exception as exc:  # noqa: BLE001 -- the answer still goes out without it
        evidence["dossier_error"] = f"{type(exc).__name__}:{exc}"
    return evidence


def _curate_from_evidence(operator_text: str, evidence: dict[str, Any]) -> dict[str, Any]:
    """The branch's answer, then the dossier; a pill says who wrote each part."""
    cur = _curate_from_evidence_core(operator_text, evidence)
    avail = (evidence or {}).get("available") or {}
    dossier = avail.get("subject_dossier_text")
    src = str(cur.get("source") or "")
    if not dossier or src in ("runtime_meta", "unclear_clarifier"):
        return cur
    try:
        from scripts.lib import subject_dossier as sd  # noqa: PLC0415
    except ImportError:
        from lib import subject_dossier as sd  # noqa: PLC0415
    body = "" if src == "empty_evidence" else str(cur.get("text") or "").strip()
    # The answer's own authority tail stays the last line of the message.
    tail = ""
    if body:
        head, _, last = body.rpartition("\n")
        if _AUTHORITY_TAIL_RE.match(last):
            body, tail = head.rstrip(), last.strip()
    # A section the answer already printed is not printed twice.
    skip = {k for k, marker in (("research", "Research on file"), ("analyst", "Analysts (")) if marker in body}
    if skip:
        dossier = sd.format_dossier(list(avail.get("subject_dossier_symbols") or []),
                                    avail.get("subject_dossier") or {},
                                    prices=avail.get("subject_dossier_prices") or {}, skip=skip) or dossier
    text = sd.LEGEND + "\n"
    if body:
        if src in ("deepseek_flash", "freeform_flash"):
            header = (f"{sd.PILL_MODEL} wrote the summary below from Trade-AI facts "
                      "(every number comes from 🟢 Trade-AI data; general knowledge only where labelled):")
        else:
            header = f"{sd.PILL_HOUSE} — desk answer, computed from stored data, no AI model:"
        text += f"{header}\n{body}\n\n"
    text += dossier
    if tail:
        text += "\n" + tail
    out = dict(cur)
    out["text"] = text
    if src == "empty_evidence":
        out.update({"ok": True, "source": "tradeai_deterministic", "model": None})
    out["dossier"] = True
    return out


#: Parent-alert titles that carry the subject when the operator replies with
#: deixis ("research this", "has a thesis") and no ticker in the reply body.
_REPLY_ALERT_SYMBOL_RE = re.compile(
    r"(?is)\b(?:READY|NEAR|ENTRY|GO|A\+)\b[^A-Za-z0-9]{0,24}"
    r"(?:ENTRY\s+ALERT|ALERT)?[^A-Za-z0-9]{0,12}"
    r"(?:—|-|–|:)?\s*\$?([A-Z]{1,5})\b"
)
_REPLY_TITLE_SYMBOL_RE = re.compile(
    r"(?is)\b(?:ENTRY\s+ALERT|GO\s+ALERT|MATERIAL\s+CHANGE)[^A-Za-z0-9]{0,24}"
    r"(?:—|-|–|:)?\s*\$?([A-Z]{1,5})\b"
)


def symbols_from_reply_context(
    reply_to_text: Optional[str] = None,
    *,
    explicit: Optional[list[str]] = None,
) -> list[str]:
    """Tickers named by the message being replied to (entry/GO alerts).

    Measured 2026-09-23: reply "research this see is has a thesis" on
    READY ENTRY ALERT — ABNB bound subject BOOK because the reply body has no
    ticker and converse never forwarded the parent alert text into the desk.
    """
    out: list[str] = []
    for raw in explicit or []:
        sym = str(raw or "").strip().upper()
        if sym and sym != "BOOK" and sym not in out:
            out.append(sym)
    text = str(reply_to_text or "")
    if text:
        for rx in (_REPLY_ALERT_SYMBOL_RE, _REPLY_TITLE_SYMBOL_RE):
            for m in rx.finditer(text):
                sym = str(m.group(1) or "").upper()
                if sym and sym not in _SYMBOL_STOP and sym != "BOOK" and sym not in out:
                    out.append(sym)
        if not out:
            # RichMessage title form: "READY ENTRY ALERT — ABNB (advisory)"
            m = re.search(
                r"(?is)ENTRY\s+ALERT\s*[—\-–:]\s*\$?([A-Z]{1,5})\b",
                text,
            )
            if m:
                sym = m.group(1).upper()
                if sym not in _SYMBOL_STOP and sym != "BOOK":
                    out.append(sym)
    return out[:6]


def _apply_reply_context_symbols(
    intent: dict[str, Any],
    *,
    reply_to_text: Optional[str] = None,
    reply_context_symbols: Optional[list[str]] = None,
) -> None:
    """Merge parent-alert tickers into intent when the reply named none."""
    if intent.get("symbols"):
        return
    inherited = symbols_from_reply_context(
        reply_to_text, explicit=reply_context_symbols,
    )
    if not inherited:
        return
    intent["symbols"] = inherited
    intent["reply_context_symbols"] = inherited
    subjects = list(intent.get("subjects") or [])
    have = {
        str(s.get("symbol") or "").upper()
        for s in subjects if isinstance(s, dict)
    }
    for sym in inherited:
        if sym in have:
            continue
        subjects.append({
            "symbol": sym,
            "kind": "ticker",
            "matched": sym,
            "matched_via": "reply_context",
            "identity_status": "CANDIDATE",
        })
        have.add(sym)
    intent["subjects"] = subjects
    ok, why = is_answerable(intent)
    intent["answerable"] = ok
    intent["unanswerable_reason"] = why or None


def _seconds_until_utc_midnight(now: Optional[datetime] = None) -> int:
    n = now or datetime.now(timezone.utc)
    if n.tzinfo is None:
        n = n.replace(tzinfo=timezone.utc)
    nxt = (n + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60, int((nxt - n).total_seconds()))


def _denied_all_budget(summary: dict[str, Any]) -> bool:
    """True when every denial attempt was budget_denied (not empty/error)."""
    denied = summary.get("denied") or []
    if not denied:
        return False
    for row in denied:
        attempts = row.get("attempts") or []
        if not attempts:
            return False
        if any(a.get("outcome") != "budget_denied" for a in attempts):
            return False
    return True


def _should_queue_despite_budget(summary: dict[str, Any], intent: dict[str, Any]) -> bool:
    """Registry ``say_so_queue_only_if_producer_exists``: producer exists → queue.

    Blanket no_coverage with "No pending opened" is wrong when the only reason
    every vector failed is the day cap and Hermes/writer still exists for the
    research domain. Queue honestly for the next UTC-day budget window.
    """
    if not _denied_all_budget(summary):
        return False
    behs = [
        str(r.get("no_coverage_behaviour") or "")
        for r in (summary.get("denied") or [])
    ]
    if not any("queue_only_if_producer" in b for b in behs):
        # Research intents still deserve an honest queue when Hermes is the
        # declared producer, even if the behaviour string was not carried.
        needs = set(intent.get("needs") or [])
        if "research" not in needs and str(intent.get("intent") or "") != "research":
            return False
    return True


def _format_budget_deferred_queue(
    summary: dict[str, Any],
    *,
    intent: dict[str, Any],
    pending_id: str,
    eta_seconds: int,
) -> str:
    syms = [str(s).upper() for s in (intent.get("symbols") or []) if str(s).strip()]
    subject = syms[0] if syms else "BOOK"
    eta_h = max(1, int(round(eta_seconds / 3600.0)))
    lines = [
        "🧠 *Alex · research queued for the next budget window*",
        f"• *{subject}* research thesis — every declared source hit today's "
        f"spend cap; Hermes (declared producer) is still queued.",
    ]
    for r in summary.get("denied") or []:
        tried = ", ".join(
            f"{a.get('vector')}={a.get('outcome')}" for a in (r.get("attempts") or [])
        ) or "no vectors"
        lines.append(f"  tried {tried}")
    lines.append(
        f"Pending `{pending_id}` — ≈ {eta_h} h (UTC day reset). "
        "I will follow up here when it lands."
    )
    lines.append(f"No orders/stops · {AUTHORITY}")
    return "\n".join(lines)


def handle_operator_desk_question(
    text: str,
    *,
    chat_id: str = "",
    message_id: str = "",
    channel: str = "telegram",
    reply_to_text: Optional[str] = None,
    reply_context_symbols: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Full loop: analyze → Trade-AI pull → answer or defer with pending reply.

    reply_to_text / reply_context_symbols: when the operator replies to an alert
    ("research this / has a thesis" on READY ENTRY ALERT — ABNB) the reply body
    often names no ticker. Inherit the parent alert's symbol so the gap resolver
    researches ABNB, not BOOK.
    """
    intent = analyze_operator_intent(text)
    _apply_reply_context_symbols(
        intent,
        reply_to_text=reply_to_text,
        reply_context_symbols=reply_context_symbols,
    )
    if str(intent.get("intent") or "") == "attention":
        from scripts.lib.cio_operator_attention import answer_attention_query
        ans = answer_attention_query(text)
        return {
            "authority": AUTHORITY,
            "intent": intent,
            "evidence_complete": True,
            "gaps": [],
            "blocking_gaps": [],
            "sources": ["cio_operator_attention"],
            "pending_id": None,
            "kind": "attention",
            "text": ans.get("text") or "",
            "reply_source": "attention_state",
            "model": None,
            "same_brain": True,
        }
    intent.setdefault("text", text)
    # The analyzer already knows when a market ask names nothing that resolves
    # (Agent B, 2026-09-13). Refuse before gathering: otherwise an ask with no
    # blocking gap replied "Queued a pull -- I'll reply when it lands" with
    # nothing queued.
    if intent.get("answerable") is False:
        why = intent.get("unanswerable_reason") or "no tradable instrument resolved from that question"
        return {
            "authority": AUTHORITY,
            "intent": intent,
            "evidence_complete": False,
            "gaps": [],
            "blocking_gaps": [],
            "sources": [],
            "contract_findings": None,
            "pending_id": None,
            "kind": "unanswerable",
            "text": "",
            "reply_preview": (
                f"I can't answer that from Trade-AI: {why}.\n\n"
                "If you meant a company I hold or watch, send its ticker and I will "
                "answer from the house data.\n"
                f"{AUTHORITY}"
            ),
            "reply_source": "unanswerable_up_front",
            "model": None,
        }
    evidence = gather_tradeai_evidence(intent)
    pending_id = f"opr_{uuid.uuid4().hex[:12]}"

    result: dict[str, Any] = {
        "authority": AUTHORITY,
        "intent": intent,
        "evidence_complete": evidence.get("complete"),
        "gaps": evidence.get("gaps") or [],
        "blocking_gaps": evidence.get("blocking_gaps") or [],
        "sources": evidence.get("sources") or [],
        # Agent C contract: surfaced on the result so the receipt and the answer-quality
        # monitor see "facts were available but not assembled" findings.
        "contract_findings": evidence.get("contract_findings"),
        "pending_id": None,
        "kind": "answered",
        "text": "",
        "reply_source": None,
        "model": None,
    }

    blocking = evidence.get("blocking_gaps") or []
    if blocking:
        result["gap_registry"] = _register_gaps(blocking, chat_id=str(chat_id), pending_id=pending_id)
        # Hermes when research is the blocker
        # Do not promise a reply about something that can never be answered.
        # "What's the outlook for SpaceX, what are options closing, what are
        # analysts expecting" got a queue ticket and 72 minutes of silence
        # because no symbol resolved (the name index lacked SpaceX -- it is SPCX, which the book holds), so the research gap
        # could not close and the pending could not complete. Say so now.
        _answerable, _why = is_answerable(intent)
        if not _answerable:
            result.update({
                "kind": "unanswerable",
                "pending_id": None,
                "reply_preview": (
                    f"I can't answer that from Trade-AI: {_why}.\n\n"
                    "If you meant a company I hold or watch, send its ticker and I "
                    "will answer from the house data.\n"
                    f"{AUTHORITY}"
                ),
            })
            return result

        # ── Phase 7: go find out, through declared vectors, before promising ──
        # The gap resolver walks the domain's on_gap chain (refresh_producer →
        # backup_provider → governed_search → hermes_research → llm_curation →
        # operator_ask), free before metered before paid, one receipt per
        # attempt. Three exits: a fast vector answered → answer now; only a slow
        # vector was queued → open the pending WITH its ETA; every vector
        # denied or exhausted → say no_coverage, and open nothing. Before this
        # the desk opened a pending and hoped.
        eta_seconds: Optional[int] = None
        eta_text: Optional[str] = None
        resolver_summary: Optional[dict[str, Any]] = None
        if _gap_resolver_enabled():
            resolver_summary = _resolve_blocking_gaps(
                blocking, intent=intent, text=text or "", chat_id=str(chat_id), pending_id=pending_id,
            )
            result["gap_resolution"] = resolver_summary.get("receipt")
            if resolver_summary.get("answered"):
                # Did the store itself now answer? Then the normal curated path
                # runs on real evidence. Otherwise answer from the vector's
                # payload, labelled with where it came from and how old it is.
                evidence2 = gather_tradeai_evidence(intent)
                if evidence2.get("complete"):
                    evidence = evidence2
                    result.update({
                        "evidence_complete": True,
                        "gaps": evidence.get("gaps") or [],
                        "blocking_gaps": [],
                        "sources": evidence.get("sources") or [],
                    })
                    blocking = []
                else:
                    result.update({
                        "kind": "answered",
                        "pending_id": None,
                        "text": _format_resolved_answer(resolver_summary, intent=intent),
                        "reply_source": "gap_resolver:" + str(resolver_summary["answered"][0].get("vector")),
                        "model": resolver_summary["answered"][0].get("model"),
                    })
                    _emit_telegram_desk_payload(intent, result)
                    return result
            elif resolver_summary.get("queued"):
                eta_seconds = resolver_summary.get("eta_seconds")
                eta_text = resolver_summary.get("eta_text")
            elif resolver_summary.get("errors") and not resolver_summary.get("denied"):
                # The resolver itself broke on every gap. That is a defect in
                # the resolver, not a fact about coverage: fall back to the
                # pre-Phase-7 path (pending + Hermes) rather than tell the
                # operator "no coverage" on the strength of a traceback.
                resolver_summary = None
            elif _should_queue_despite_budget(resolver_summary, intent):
                # say_so_queue_only_if_producer_exists: day caps spent, but
                # Hermes/writer still exists. Queue honestly for UTC reset
                # instead of "No pending opened — nothing declared can answer".
                eta_seconds = _seconds_until_utc_midnight()
                eta_text = f"≈ {max(1, int(round(eta_seconds / 3600.0)))} h"
                enqueue_research_gap(
                    symbols=[str(s).upper() for s in (intent.get("symbols") or [])],
                    chat_id=str(chat_id),
                    pending_id=pending_id,
                    operator_text=text or "",
                )
                pending_row = {
                    "pending_id": pending_id,
                    "status": "open",
                    "ts": _now(),
                    "chat_id": str(chat_id),
                    "message_id": str(message_id),
                    "channel": channel,
                    "operator_text": (text or "")[:1000],
                    "intent": intent,
                    "blocking_gaps": blocking,
                    "authority": AUTHORITY,
                    "kind": "budget_deferred_queue",
                    "eta_seconds": int(eta_seconds),
                    "resolver": resolver_summary.get("receipt"),
                }
                _append_jsonl(PENDING_PATH, pending_row)
                result.update({
                    "kind": "deferred",
                    "pending_id": pending_id,
                    "eta_seconds": eta_seconds,
                    "research_queued": True,
                    "text": _format_budget_deferred_queue(
                        resolver_summary,
                        intent=intent,
                        pending_id=pending_id,
                        eta_seconds=eta_seconds,
                    ),
                    "reply_source": "gap_resolver:budget_deferred_queue",
                    "gap_resolution": {
                        **(resolver_summary.get("receipt") or {}),
                        "queued": [
                            f"research_thesis:"
                            f"{(intent.get('symbols') or ['BOOK'])[0]}:hermes_research"
                        ],
                        "budget_deferred": True,
                        "eta_seconds": eta_seconds,
                    },
                })
                result.setdefault("went_outside", []).append(
                    "hermes_research queue — day budget spent; deferred to next UTC window"
                )
                _emit_telegram_desk_payload(intent, result)
                return result
            else:
                # Every declared vector was denied, exhausted or empty. A
                # pending here would be the silent promise this exists to end.
                result.update({
                    "kind": "no_coverage",
                    "pending_id": None,
                    "text": _format_no_coverage(resolver_summary, intent=intent),
                    "reply_source": "gap_resolver:no_coverage",
                })
                _emit_telegram_desk_payload(intent, result)
                return result

        if blocking:
            buy_first = buy_perspective_needs_research_first(intent, evidence)
            if resolver_summary is None and (
                any(g.get("domain") == "hermes_research" for g in blocking)
                or buy_first
            ):
                # Pre-Phase-7 path (resolver disabled): Hermes when research blocks
                # or when a buy/perspective ask must wait for house coverage.
                enqueue_research_gap(
                    symbols=[str(s).upper() for s in (intent.get("symbols") or [])],
                    chat_id=str(chat_id),
                    pending_id=pending_id,
                    operator_text=text or "",
                )
                result.setdefault("went_outside", []).append(
                    "hermes_research queue — no house research on the subject; research requested"
                )
            gap_bits = []
            for g in blocking[:6]:
                sym = g.get("symbol") or "book"
                gap_bits.append(f"{sym}:{g.get('field') or g.get('reason')}")
            # Buy/perspective research-first is the one blocking path that may
            # promise an ETA without a resolver queue (Hermes CIO default 1800s).
            # All other pre-Phase-7 / resolver-off paths must NOT invent ≈ —
            # test_gap_resolver negative controls pin that.
            buy_eta_seconds = 1800 if buy_first and not eta_seconds else None
            effective_eta = eta_seconds if eta_seconds is not None else buy_eta_seconds
            effective_eta_text = eta_text
            if effective_eta_text is None and buy_eta_seconds is not None:
                effective_eta_text = f"≈ {max(1, int(round(buy_eta_seconds / 60.0)))} min"
            pending_row: dict[str, Any] = {
                "pending_id": pending_id,
                "status": "open",
                "ts": _now(),
                "chat_id": str(chat_id),
                "message_id": str(message_id),
                "channel": channel,
                "operator_text": (text or "")[:1000],
                "intent": intent,
                "blocking_gaps": blocking,
                "authority": AUTHORITY,
                "kind": (
                    "buy_perspective_research_first" if buy_first else "blocking_gap"
                ),
            }
            if effective_eta is not None:
                pending_row["eta_seconds"] = int(effective_eta)
            if resolver_summary is not None:
                pending_row["resolver"] = resolver_summary.get("receipt")
            _append_jsonl(PENDING_PATH, pending_row)
            queued_line = (
                f"Queued into the controlled gap pipeline — {effective_eta_text} until it lands. "
                if effective_eta_text else
                "Queued into the controlled gap pipeline. "
            )
            research_only = all(g.get("domain") == "hermes_research" for g in blocking)
            # Buy/perspective with thin/stale house facts: NEVER lead with a hollow
            # DeepSeek essay (live 2026-09-22 operator paste). Lead with pending.
            if buy_first:
                syms = [str(s).upper() for s in (intent.get("symbols") or [])][:3]
                sym_label = ", ".join(syms) if syms else "that name"
                stale_bits = [
                    g.get("reason") for g in blocking
                    if g.get("domain") == "quote_price"
                ][:2]
                thin = house_research_thin(evidence)
                why_bits = []
                if thin:
                    why_bits.append("house research is thin / empty")
                if stale_bits:
                    why_bits.append("; ".join(str(b) for b in stale_bits if b))
                why = " and ".join(why_bits) if why_bits else "required facts are not ready"
                result.update({
                    "kind": "deferred",
                    "pending_id": pending_id,
                    "eta_seconds": effective_eta,
                    "research_queued": True,
                    "text": (
                        "🧠 *Alex · Research first — no hollow perspective*\n"
                        f"You're asking for a buy / investment perspective on `{sym_label}`. "
                        f"I will not invent one from thin or stale house facts ({why}).\n\n"
                        f"Queued: Hermes research"
                        + (" + quote refresh" if stale_bits else "")
                        + f"\n{queued_line}"
                        f"I'll reply here when useful coverage lands.\n"
                        f"Pending: `{pending_id}`\n"
                        "No orders/stops · READ_ONLY_ADVISORY"
                    ),
                    "reply_source": "buy_perspective_research_first",
                    "model": None,
                })
                _emit_telegram_desk_payload(intent, result)
                return result
            if research_only and _env("CIO_OPERATOR_RESEARCH_ANSWER_NOW", "1").lower() not in (
                "0", "false", "off", "no",
            ):
                # 2026-09-14 HPE: "Do some more research on HPE ..." got a queue
                # ticket and nothing else, although price, levels, analysts,
                # earnings, catalysts, news, sector and thesis were all on file.
                # Answer with those now; Hermes' answer follows on the same pending.
                curated_now = _curate_from_evidence(text, evidence)
                queued_now = (
                    "🟣 AI model (DeepSeek) · Deeper research queued: Hermes reads Trade-AI evidence — "
                    + (f"{effective_eta_text} until it lands" if effective_eta_text else "it lands when the worker runs")
                    + f". Its answer follows here as a reply. Pending: `{pending_id}`"
                )
                result.update({
                    "kind": "answered",
                    "pending_id": pending_id,
                    "eta_seconds": effective_eta,
                    "text": _with_sources_footer(
                        _insert_before_authority_tail(curated_now.get("text") or "", queued_now),
                        evidence, curated_now,
                    ),
                    "reply_source": curated_now.get("source"),
                    "model": curated_now.get("model"),
                    "research_queued": True,
                })
                _emit_telegram_desk_payload(intent, result)
                return result
            result.update({
                "kind": "deferred",
                "pending_id": pending_id,
                "eta_seconds": effective_eta,
                "text": (
                    "🧠 *Alex · Trade-AI pull queued*\n"
                    f"I analyzed your ask (`{intent.get('intent')}`). "
                    "Required facts are not fully in Trade-AI yet:\n"
                    + "\n".join(f"• `{b}`" for b in gap_bits)
                    + "\n\n" + queued_line
                    + "I'll reply here when it lands.\n"
                    f"Pending: `{pending_id}`\n"
                    "No orders/stops · READ_ONLY_ADVISORY"
                ),
                "reply_source": "deferred_gap",
            })
            _emit_telegram_desk_payload(intent, result)
            return result

    # Per-subject conversation memory, keyed by subject GUID, this chat only.
    if intent.get("symbols") and isinstance(evidence.get("available"), dict):
        memory = subject_memory(intent, chat_id=str(chat_id), message_id=message_id)
        if memory:
            evidence["available"]["subject_memory"] = memory
            evidence.setdefault("sources", []).append("operator_conversation_turns")
            result["memory_recall"] = {s: len(v) for s, v in memory.items()}
    curated = _curate_from_evidence(text, evidence)
    soft = [g for g in (evidence.get("gaps") or []) if g not in blocking]
    text_out = _with_sources_footer(curated.get("text") or "", evidence, curated)
    intent_name = str(intent.get("intent") or "")

    # Freeform: answer now; optionally soft-queue research gaps for named symbols
    if intent_name == "freeform":
        queue_on = _env("CIO_OPERATOR_FREEFORM_QUEUE", "1").lower() not in (
            "0", "false", "off", "no",
        )
        research_gaps = [
            g for g in soft
            if g.get("symbol") and g.get("gap_type") in ("research", "missing_research")
        ]
        if queue_on and research_gaps:
            _register_gaps(research_gaps[:10], chat_id=str(chat_id), pending_id=pending_id)
            syms = sorted({str(g.get("symbol")) for g in research_gaps if g.get("symbol")})
            enq = enqueue_research_gap(
                symbols=syms,
                chat_id=str(chat_id),
                pending_id=pending_id,
                operator_text=text or "",
            )
            result.setdefault("went_outside", []).append(
                f"hermes_research queue — no house research on {', '.join(syms[:6])}; research requested"
            )
            _append_jsonl(PENDING_PATH, {
                "pending_id": pending_id,
                "status": "open",
                "ts": _now(),
                "chat_id": str(chat_id),
                "message_id": str(message_id),
                "channel": channel,
                "operator_text": (text or "")[:1000],
                "intent": intent,
                "blocking_gaps": research_gaps[:10],
                "authority": AUTHORITY,
                "kind": "freeform_soft_queue",
            })
            ack = enq.get("ack") or (
                f"House research for {', '.join(syms[:6])} is queued; "
                "fetching fresh quotes and levels."
            )
            if f"`{pending_id}`" not in text_out:
                text_out = (
                    text_out.rstrip()
                    + f"\n_{ack} · Pending `{pending_id}`_"
                )
            result["pending_id"] = pending_id
            result["research_queued"] = bool(enq.get("ok") or enq.get("emitted"))
        # A follow-up promise stands only on a pending row that EXISTS for this
        # chat -- read back from the ledger, not assumed from the branch taken.
        text_out = _drop_unbacked_follow_up(text_out, _open_pending_row(pending_id, str(chat_id)))
        result.update({
            "kind": "answered",
            "text": text_out,
            "reply_source": curated.get("source"),
            "model": curated.get("model"),
        })
        _emit_telegram_desk_payload(intent, result)
        return result

    if soft and "DATA_UNAVAILABLE" not in text_out and intent_name != "meta_system":
        soft_syms = sorted({g.get("symbol") for g in soft if g.get("symbol")})
        if soft_syms:
            # Claim "queued" only when the registry accepted the gaps. _register_gaps
            # returned registered=0 on every call (its bridge module is absent), and
            # the note said "queued for Trade-AI refresh" regardless.
            reg = _register_gaps(soft[:10], chat_id=str(chat_id), pending_id=pending_id) or {}
            result["gap_registry"] = reg
            # 2026-09-22: missing house research / levels for a named symbol must
            # auto-enqueue — do not leave the operator typing "research S".
            researchish = [
                g for g in soft
                if g.get("symbol") and (
                    g.get("gap_type") in ("research", "missing_research", "missing_market_data")
                    or g.get("domain") in ("hermes_research", "symbol_thesis", "quote_price",
                                           "reentry_decision_desk")
                )
            ]
            enq = None
            if researchish:
                enq = enqueue_research_gap(
                    symbols=sorted({str(g["symbol"]) for g in researchish if g.get("symbol")}),
                    chat_id=str(chat_id),
                    pending_id=pending_id,
                    operator_text=text or "",
                )
                result["research_queued"] = bool(enq.get("ok") or enq.get("emitted"))
                if enq.get("ack"):
                    result.setdefault("went_outside", []).append(
                        f"hermes_research queue — {enq['ack']}"
                    )
            queued = int(reg.get("registered") or 0) > 0 or bool((enq or {}).get("emitted"))
            if enq and enq.get("ack"):
                note = enq["ack"]
            elif queued:
                note = _gap_queue_note(reg)
            else:
                note = "not refreshed automatically; house research stays thin until queued."
            # Phase 1/2A: soft enqueue without a PENDING_PATH row was fire-and-forget —
            # try_fulfill_pending_replies could never deliver Hermes. Mirror freeform.
            # A pending without eta_seconds / ≈ in the reply fails the SpaceX litmus
            # (test_operator_answer_quality): "a pending is only opened with an ETA".
            # Hermes CIO default expected_seconds is 1800 (gap_resolver hermes vector).
            soft_eta_seconds = 1800
            soft_eta_text = f"≈ {max(1, int(round(soft_eta_seconds / 60.0)))} min"
            opened_pending = False
            if enq and (enq.get("ok") or enq.get("emitted") or enq.get("deduped")):
                _append_jsonl(PENDING_PATH, {
                    "pending_id": pending_id,
                    "status": "open",
                    "ts": _now(),
                    "chat_id": str(chat_id),
                    "message_id": str(message_id),
                    "channel": channel,
                    "operator_text": (text or "")[:1000],
                    "intent": intent,
                    "blocking_gaps": researchish[:10] if researchish else soft[:10],
                    "authority": AUTHORITY,
                    "kind": "soft_research_queue",
                    "eta_seconds": soft_eta_seconds,
                })
                result["pending_id"] = pending_id
                result["eta_seconds"] = soft_eta_seconds
                opened_pending = True
            if opened_pending:
                pending_note = (
                    f"_{note} — {soft_eta_text} until it lands · Pending `{pending_id}`_"
                )
                if f"`{pending_id}`" not in text_out:
                    text_out = _insert_before_authority_tail(text_out, pending_note)
                elif "≈" not in text_out:
                    text_out = _insert_before_authority_tail(
                        text_out,
                        f"_Follow-up ETA {soft_eta_text}_",
                    )
            else:
                text_out = _insert_before_authority_tail(
                    text_out,
                    f"_Note: partial level gaps on {', '.join(soft_syms[:6])} — {note}_",
                )

    result.update({
        "kind": "answered",
        "text": text_out,
        "reply_source": curated.get("source"),
        "model": curated.get("model"),
    })
    _emit_telegram_desk_payload(intent, result)
    return result


#: How long an unfulfilled promise may stay open before it is retracted.
#: `try_fulfill_pending_replies` skips an incomplete pending with a bare
#: `continue`, so a question whose evidence can NEVER arrive was re-checked
#: silently forever. opr_5bc20393b457 ("outlook for SpaceX") sat open 72 minutes
#: with the operator waiting, and would have sat open indefinitely: no symbol
#: resolved (the name index lacked SpaceX; it is SPCX, which the book holds), so the research gap could not close.
PENDING_EXPIRY_HOURS = 2.0


def _pending_expiry_hours(row: dict[str, Any]) -> float:
    """How long this pending may stay open before it is retracted.

    A pending opened with an ETA (the gap resolver queued a slow vector) was
    retracted at 2 h even when the ETA itself was longer, so the operator was
    told "could not answer" before the promised time. It now stays open until
    the ETA plus a grace period (CIO_OPERATOR_PENDING_ETA_GRACE_HOURS, default 1).
    """
    try:
        eta_s = float(row.get("eta_seconds"))
    except (TypeError, ValueError):
        return PENDING_EXPIRY_HOURS
    if eta_s <= 0:
        return PENDING_EXPIRY_HOURS
    try:
        grace_h = float(_env("CIO_OPERATOR_PENDING_ETA_GRACE_HOURS", "1"))
    except ValueError:
        grace_h = 1.0
    return max(PENDING_EXPIRY_HOURS, eta_s / 3600.0 + max(0.0, grace_h))


def _pending_age_hours(row: dict[str, Any]) -> Optional[float]:
    """Hours since a pending was opened, or None when its timestamp is unusable."""
    try:
        ts = datetime.fromisoformat(str(row.get("ts")).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
    except Exception:
        return None


def is_answerable(intent: dict[str, Any]) -> tuple[bool, str]:
    """Can this ask ever be answered from Trade-AI, or is the promise empty?

    A market question about something with no resolvable instrument cannot be
    answered by waiting: no quote, no chain, no analyst coverage and no research
    row will ever arrive for it. Promising "I'll reply when it lands" is then a
    promise about data that cannot land -- which is what happened to the SpaceX
    ask. The name did not resolve -- knowable at the moment of asking. (It was
    SPCX, held; the name index lacked it. Resolution now reads house-held names.)

    Returns (answerable, reason). The reason is operator-facing.
    """
    needs = set(intent.get("needs") or [])
    symbols = [s for s in (intent.get("symbols") or []) if str(s).strip()]
    market_needs = needs & {"analyst_view", "reentry_ready", "reentry_levels", "risk"}
    if market_needs and not symbols:
        # Name what failed to resolve. Never assert WHY (e.g. "private"): the name
        # index only knows the broker instrument feed, and a listed name the feed
        # has not swept is indistinguishable here from a private company.
        names = [str(s.get("matched")) for s in (intent.get("subjects") or [])
                 if isinstance(s, dict) and s.get("kind") == "company" and not s.get("symbol") and s.get("matched")]
        named = (f" ({', '.join(dict.fromkeys(names))} did not resolve to an instrument in the broker feed)"
                 if names else "")
        cands = [str(c) for c in (intent.get("ticker_candidates") or [])][:3]
        hint = (f". If you meant a ticker, write it in capitals ({', '.join(cands)})" if cands else "")
        return False, (
            "no tradable instrument resolved from that question, so there is no "
            "quote, options chain, analyst coverage or research to wait for" + named + hint
        )
    return True, ""


def _pending_reply_provenance(kind: str, row: dict[str, Any], evidence: dict[str, Any],
                              curated: Optional[dict[str, Any]] = None) -> "_ReplyProvenance":
    """Receipt for a follow-up / retraction send. These do not pass through the
    converse core, so they declare what they read here: the pending ledger row
    (and when it was opened) plus whatever evidence the re-check gathered."""
    opened = str(row.get("ts") or "")[:16].replace("T", " ")
    stores = [PENDING_PATH.name + (f" · opened {opened}" if opened else "")]
    stores += [lab for lab in _labels_from_evidence(evidence or {}, curated or {}) if " — " not in lab]
    outside: list[str] = []
    model = role = None
    src = str((curated or {}).get("source") or "")
    if src in ("deepseek_flash", "freeform_flash"):
        model = (curated or {}).get("model") or "deepseek-flash"
        freeform = ((evidence or {}).get("available") or {}).get("freeform_context") is not None
        role = _ROLE_GENERAL_KNOWLEDGE if (freeform or src == "freeform_flash") else _ROLE_WORDING_ONLY
        outside.append(f"{model} — {role}")
    hermes = ((evidence or {}).get("available") or {}).get("hermes_result")
    if isinstance(hermes, dict) and not model:
        # A model is never "outside data" (reply_provenance.origin_line): Hermes
        # read Trade-AI evidence, so it is named on the 🟣 model role, once.
        model = str(hermes.get("model") or "deepseek-flash")
        role = f"Hermes research over Trade-AI evidence; {_ROLE_GENERAL_KNOWLEDGE}"
    return _ReplyProvenance(kind=kind, stores_read=stores, went_outside=outside, model=model, model_role=role)


def _open_for_text(age_h: Optional[float]) -> str:
    if age_h is None:
        return "for an unknown time"
    if age_h < 1:
        return f"{max(1, int(round(age_h * 60)))} minutes"
    return f"{age_h:.1f} hours"


def _asked_at_text(row: dict[str, Any]) -> str:
    """When the question was asked, in the host's local time (date only if not today)."""
    try:
        ts = datetime.fromisoformat(str(row.get("ts")).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        local = ts.astimezone()
        fmt = "%H:%M %Z" if local.date() == datetime.now().astimezone().date() else "%a %b %d %H:%M %Z"
        return local.strftime(fmt)
    except Exception:  # noqa: BLE001
        return ""


def _describe_gap(gap: dict[str, Any]) -> str:
    sym = str(gap.get("symbol") or "").strip()
    what = str(gap.get("reason") or gap.get("field") or "").strip().replace("DATA_UNAVAILABLE", "not available")
    if not what:
        return ""
    return f"{sym}: {what}" if sym and not what.upper().startswith(sym.upper()) else what


def _retry_advice(row: dict[str, Any], intent: dict[str, Any]) -> str:
    """Would asking again work now? Re-resolved with the deterministic subject resolver, no model."""
    text = str(row.get("operator_text") or "")
    before = {str(s).upper() for s in (intent.get("symbols") or []) if str(s).strip()}
    try:
        try:
            from lib.operator_subject_resolver import resolve_subjects  # noqa: PLC0415
        except ImportError:
            from scripts.lib.operator_subject_resolver import resolve_subjects  # noqa: PLC0415
        now_syms = list(dict.fromkeys(
            str(s["symbol"]).upper() for s in resolve_subjects(text) if isinstance(s, dict) and s.get("symbol")
        ))
    except Exception:  # noqa: BLE001
        return "Ask again if you want me to retry."
    new = [s for s in now_syms if s not in before]
    if new:
        return (f"Ask again: this question now resolves to {', '.join(new[:4])}, "
                "so I can answer it from house data.")
    known = list(dict.fromkeys(now_syms + [s for s in before if s not in now_syms]))
    if known:
        # The raw sentence may not contain the ticker ("mcdonalds" is not "MCD").
        # Symbols already on the intent are known. Never tell the operator to name one.
        return (f"Ask again to retry {', '.join(known[:4])}. The ticker is already known. "
                "If the same data is still missing, I will say so straight away "
                "instead of promising a follow-up.")
    return ("Asking again the same way won't help, because no ticker resolves from it. "
            "Name the ticker and I will answer from house data.")


def _closing_message(
    row: dict[str, Any], intent: dict[str, Any], *, age_h: Optional[float], limit_h: float, why: str,
) -> tuple[str, str]:
    """(message, reason) for retracting a pending question.

    2026-09-13: the old text read "the required Trade-AI data did not arrive
    within 2h" for a question that had been open 9.4 hours, named nothing that
    was missing, and said "ask again" whether or not that could work. The
    SpaceX ask was closed that way right after the name index learned SPCX.
    """
    q = " ".join(str(row.get("operator_text") or "").split())
    q = re.sub(r"[*_`\[\]]", " ", q)
    q = q if len(q) <= 160 else q[:157].rstrip() + "…"
    asked = _asked_at_text(row)
    missing = list(dict.fromkeys(
        d for d in (_describe_gap(g) for g in (row.get("blocking_gaps") or []) if isinstance(g, dict)) if d
    ))[:4]
    if why:
        reason = str(why).rstrip(". ")
    elif row.get("eta_seconds"):
        reason = f"the data it needed did not arrive by its ETA plus grace ({round(limit_h, 1):g} hours)"
    else:
        reason = f"the data it needed did not arrive within the {round(limit_h, 1):g}-hour limit"
    lines = [
        f"📭 *Closing* `{row.get('pending_id')}` — I could not answer this.",
        "",
        f"You asked{(' at ' + asked) if asked else ''}: \"{q}\"",
        f"It was open {_open_for_text(age_h)}.",
        f"Why: {reason}.",
    ]
    if missing:
        lines.append("Missing: " + "; ".join(missing) + ".")
    lines += ["", _retry_advice(row, intent), AUTHORITY]
    return "\n".join(lines), reason


def try_fulfill_pending_replies(
    send_fn: SendFn,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    """Re-check open pending operator questions; reply when Trade-AI has facts."""
    rows = _read_jsonl(PENDING_PATH)
    latest: dict[str, dict[str, Any]] = {}
    for r in rows:
        pid = str(r.get("pending_id") or "")
        if pid:
            latest[pid] = r
    open_rows = [r for r in latest.values() if r.get("status") == "open"][-limit:]
    fulfilled = 0
    failed = 0
    expired = 0
    for row in open_rows:
        try:
            intent = row.get("intent") or analyze_operator_intent(row.get("operator_text") or "")
            evidence = gather_tradeai_evidence(intent)
            pending_key = str(row.get("pending_id") or "")
            hermes_result = None
            if not evidence.get("complete"):
                # The research this pending asked for lands in the Hermes result
                # ledger, not as a promoted research row. Join it by pending id.
                hermes_result = hermes_result_for_pending(pending_key)
                if hermes_result:
                    evidence = join_hermes_result(evidence, hermes_result)
                    # The first reply already carried the full dossier; the
                    # follow-up is Hermes' answer, not the same picture again
                    # (with it the HPE follow-up ran 5,316 characters).
                    (evidence.get("available") or {}).pop("subject_dossier_text", None)
            if not evidence.get("complete"):
                # A promise that cannot be kept must be RETRACTED, not abandoned.
                # This used to be a bare `continue`: an unanswerable pending was
                # re-checked silently forever while the operator waited.
                age_h = _pending_age_hours(row)
                answerable, why = is_answerable(intent)
                hermes_failed = hermes_failure_for_pending(pending_key) if answerable else None
                if hermes_failed:
                    symbols = [str(s).upper() for s in (intent.get("symbols") or []) if str(s).strip()]
                    released = house_evidence_after_research_failure(evidence, symbols, hermes_failed)
                    if released is not None and released.get("complete"):
                        evidence = released
                    else:
                        answerable, why = False, plain_research_failure(hermes_failed, symbols)
                if not evidence.get("complete"):
                    limit_h = _pending_expiry_hours(row)
                    if answerable and (age_h is None or age_h < limit_h):
                        continue
                    closing_text, reason = _closing_message(
                        row, intent, age_h=age_h, limit_h=limit_h, why=why,
                    )
                    chat_id = str(row.get("chat_id") or "")
                    if chat_id:
                        body, _prov = _finalize_operator_reply(
                            closing_text,
                            _pending_reply_provenance("pending_expired", row, evidence),
                        )
                        send_fn(chat_id, body, row.get("message_id"))
                    _append_jsonl(PENDING_PATH, {
                        **{k: row.get(k) for k in (
                            "pending_id", "chat_id", "message_id", "channel", "operator_text",
                        )},
                        "status": "expired",
                        "expired_ts": _now(),
                        "expiry_reason": reason,
                        "age_hours": round(age_h, 2) if age_h is not None else None,
                        "authority": AUTHORITY,
                    })
                    expired += 1
                    continue
            curated = _curate_from_evidence(str(row.get("operator_text") or ""), evidence)
            answer_text = curated.get("text") or ""
            note = str((evidence.get("available") or {}).get("research_failure_note") or "").strip()
            if note:
                answer_text = _insert_before_authority_tail(answer_text, note[0].upper() + note[1:] + ".")
            if hermes_result:
                answer_text = _insert_before_authority_tail(answer_text, format_hermes_section(hermes_result))
            landed = "Hermes research landed" if hermes_result else "Trade-AI data landed"
            try:
                from scripts.lib.reply_provenance import LEGEND as _pill_key  # noqa: PLC0415
            except ImportError:  # pragma: no cover -- hub import path
                from lib.reply_provenance import LEGEND as _pill_key  # type: ignore  # noqa: PLC0415
            body, _prov = _finalize_operator_reply(
                f"📬 *Follow-up* `{row.get('pending_id')}` — {landed}\n"
                f"{_pill_key}\n"
                f"You asked{(' at ' + _asked_at_text(row)) if _asked_at_text(row) else ''}: "
                f"\"{_plain(row.get('operator_text'), 160)}\"\n\n"
                + _with_sources_footer(answer_text, evidence, curated),
                _pending_reply_provenance("pending_fulfilled", row, evidence, curated),
            )
            chat_id = str(row.get("chat_id") or "")
            if not chat_id:
                continue
            sent = send_fn(chat_id, body, row.get("message_id"))
            if not sent.get("ok", True) and sent.get("error"):
                failed += 1
                continue
            _append_jsonl(PENDING_PATH, {
                **{k: row.get(k) for k in (
                    "pending_id", "chat_id", "message_id", "channel", "operator_text",
                )},
                "status": "fulfilled",
                "fulfilled_ts": _now(),
                "authority": AUTHORITY,
            })
            fulfilled += 1
        except Exception:
            failed += 1
    return {
        "ok": True,
        "checked": len(open_rows),
        "fulfilled": fulfilled,
        "expired": expired,
        "failed": failed,
        "authority": AUTHORITY,
    }
