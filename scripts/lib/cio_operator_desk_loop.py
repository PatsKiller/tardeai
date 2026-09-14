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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PENDING_PATH = PROJECT_ROOT / "data" / "cio" / "cio_operator_pending_replies.jsonl"
AUTHORITY = "READ_ONLY_ADVISORY"

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

        # Explainer/comparison language → freeform (soft desk hints OK, no reentry)
        if _looks_like_freeform(scan) and out["intent"] not in ("reentry", "meta_system"):
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

            llm = call_governed_llm(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": t[:800]},
                ],
                load_llm_policy(),
                use_pro=False,
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
            "sector rotation lore) must be prefixed 'General market history (model knowledge, not "
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
            "3) Never invent holdings or re-entry candidate dumps.\n"
            "4) Mention SOFT_GAPS briefly when relevant.\n"
            "5) Keep reply under ~900 chars; Telegram markdown ok (*bold*, `code`).\n"
            "6) End with READ_ONLY_ADVISORY."
        )
        user = (
            f"OPERATOR_ASK:\n{(operator_text or '')[:800]}\n\n"
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


def gather_tradeai_evidence(intent: dict[str, Any]) -> dict[str, Any]:
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
        items = subject_research(symbols)
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


def _register_gaps(gaps: list[dict[str, Any]], *, chat_id: str, pending_id: str) -> dict[str, Any]:
    """Best-effort enqueue into data_gap_registry / advisory ledger."""
    registered = 0
    try:
        from scripts.lib.advisory_gap_requeue import register_advisory_gaps

        rows = []
        for g in gaps:
            sym = g.get("symbol") or "BOOK"
            rows.append({
                "symbol": sym,
                "quality": "DATA_UNAVAILABLE",
                "gaps": [g.get("field") or g.get("reason") or "missing"],
                "setup": "WAIT_DATA",
                "reentry_state": None,
            })
        res = register_advisory_gaps(rows, max_register=20)
        registered = int(res.get("registered") or 0)
    except Exception as exc:
        return {"registered": 0, "error": f"{type(exc).__name__}:{exc}"}
    _append_jsonl(
        PROJECT_ROOT / "data" / "cio" / "cio_operator_gap_requests.jsonl",
        {
            "ts": _now(),
            "pending_id": pending_id,
            "chat_id": chat_id,
            "gaps": gaps,
            "registered": registered,
            "authority": AUTHORITY,
        },
    )
    return {"registered": registered}


def subject_research(symbols: list[str], *, limit: int = 6) -> list[dict[str, Any]]:
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
            """SELECT symbol, research_type, topic,
                      COALESCE(summary, thesis, ''), confidence_score,
                      created_at
                 FROM hermes_research_intelligence
                WHERE upper(symbol) = ANY(%s) AND status = 'promoted'
                ORDER BY created_at DESC
                LIMIT %s""",
            (syms, int(limit)),
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
        return out
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
        )
        out["ok"] = bool((emit or {}).get("ok", True)) if isinstance(emit, dict) else True
        out["emitted"] = 0 if isinstance(emit, dict) and emit.get("skipped") else 1
        out["plan_id"] = plan_id
        out["emit"] = emit if isinstance(emit, dict) else {"raw": str(emit)[:200]}
        _append_jsonl(
            PROJECT_ROOT / "data" / "cio" / "cio_operator_gap_requests.jsonl",
            {
                "ts": _now(),
                "pending_id": pending_id,
                "chat_id": chat_id,
                "kind": "hermes_operator_forced",
                "plan_id": plan_id,
                "symbols": symbols,
                "authority": AUTHORITY,
            },
        )
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}:{exc}"
    return out



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


def _curate_from_evidence(operator_text: str, evidence: dict[str, Any]) -> dict[str, Any]:
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
            "text": (
                "Trade-AI has no vetted facts for that yet. "
                "Queued a pull — I'll reply when it lands.\n"
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


def handle_operator_desk_question(
    text: str,
    *,
    chat_id: str = "",
    message_id: str = "",
    channel: str = "telegram",
) -> dict[str, Any]:
    """Full loop: analyze → Trade-AI pull → answer or defer with pending reply."""
    intent = analyze_operator_intent(text)
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
        _register_gaps(blocking, chat_id=str(chat_id), pending_id=pending_id)
        # Hermes when research is the blocker
        # Do not promise a reply about something that can never be answered.
        # "What's the outlook for SpaceX, what are options closing, what are
        # analysts expecting" got a queue ticket and 72 minutes of silence
        # because SpaceX is private: no symbol resolved, so the research gap
        # could not close and the pending could not complete. Say so now.
        _answerable, _why = is_answerable(intent)
        if not _answerable:
            result.update({
                "kind": "unanswerable",
                "pending_id": None,
                "reply_preview": (
                    f"I can't answer that from Trade-AI: {_why}.\n\n"
                    "If it is a private company, there is no market data, options "
                    "chain or analyst coverage for it here.\n"
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
            if resolver_summary is None and any(g.get("domain") == "hermes_research" for g in blocking):
                # Pre-Phase-7 path (resolver disabled): Hermes when research blocks.
                _enqueue_hermes_research(
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
            _append_jsonl(PENDING_PATH, {
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
                **({"eta_seconds": eta_seconds, "resolver": resolver_summary.get("receipt")}
                   if resolver_summary is not None else {}),
            })
            queued_line = (
                f"Queued into the controlled gap pipeline — {eta_text} until it lands. "
                if eta_text else
                "Queued into the controlled gap pipeline. "
            )
            result.update({
                "kind": "deferred",
                "pending_id": pending_id,
                "eta_seconds": eta_seconds,
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
            if g.get("gap_type") == "research" and g.get("symbol")
        ]
        if queue_on and research_gaps:
            _register_gaps(research_gaps[:10], chat_id=str(chat_id), pending_id=pending_id)
            syms = sorted({str(g.get("symbol")) for g in research_gaps if g.get("symbol")})
            _enqueue_hermes_research(
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
            if f"`{pending_id}`" not in text_out:
                text_out = (
                    text_out.rstrip()
                    + f"\n_Queued Trade-AI research for {', '.join(syms[:6])} · "
                    f"Pending `{pending_id}`_"
                )
            result["pending_id"] = pending_id
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
            text_out = (
                text_out.rstrip()
                + f"\n_Note: partial level gaps on {', '.join(soft_syms[:6])} — "
                "queued for Trade-AI refresh._"
            )
            _register_gaps(soft[:10], chat_id=str(chat_id), pending_id=pending_id)

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
#: with the operator waiting, and would have sat open indefinitely: SpaceX is
#: private, so no symbol resolved, so the research gap could not close.
PENDING_EXPIRY_HOURS = 2.0


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
    ask. SpaceX is private; that was knowable at the moment of asking.

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
    return _ReplyProvenance(kind=kind, stores_read=stores, went_outside=outside, model=model, model_role=role)


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
            if not evidence.get("complete"):
                # A promise that cannot be kept must be RETRACTED, not abandoned.
                # This used to be a bare `continue`: an unanswerable pending was
                # re-checked silently forever while the operator waited.
                age_h = _pending_age_hours(row)
                answerable, why = is_answerable(intent)
                if answerable and (age_h is None or age_h < PENDING_EXPIRY_HOURS):
                    continue
                reason = why or (
                    f"the required Trade-AI data did not arrive within "
                    f"{PENDING_EXPIRY_HOURS:g}h"
                )
                chat_id = str(row.get("chat_id") or "")
                if chat_id:
                    body, _prov = _finalize_operator_reply(
                        f"📭 *Closing* `{row.get('pending_id')}` — I could not answer this.\n\n"
                        f"{reason}.\n\nAsk again if you want me to retry.\n"
                        f"{AUTHORITY}",
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
            body, _prov = _finalize_operator_reply(
                f"📬 *Follow-up* `{row.get('pending_id')}` — Trade-AI data landed\n\n"
                + _with_sources_footer(curated.get("text") or "", evidence, curated),
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
