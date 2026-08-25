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
})
_RUNTIME_NEEDS = frozenset({"runtime_llm", "runtime_status"})
_META_HEURISTIC = re.compile(
    r"(?is)\b("
    r"llm|model|deepseek|flash|pro\b|"
    r"which\s+(?:ai|model|llm)|"
    r"what\s+(?:\w+\s+){0,4}(?:using|model|llm)|"
    r"how\s+(?:do\s+)?you\s+work|"
    r"read[_\s-]?only|authority|"
    r"bot\s+status|what\s+version|which\s+version"
    r")\b"
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
        "model_flash": "deepseek-v4-flash",
        "model_pro": "deepseek-v4-pro",
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
        facts["model_flash"] = "deepseek-v4-flash"
        facts["model_pro"] = "deepseek-v4-pro"
        facts["operator_intent_uses"] = "deepseek-v4-flash (use_pro=False)"
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


def analyze_operator_intent(text: str) -> dict[str, Any]:
    """DeepSeek Flash → structured intent. Numbers never come from this step."""
    out: dict[str, Any] = {
        "ok": False,
        "source": "heuristic",
        "model": None,
        "intent": "freeform",
        "symbols": [],
        "needs": [],
        "error": None,
    }
    t = (text or "").strip()
    if not t:
        out["intent"] = "unclear"
        out["error"] = "empty"
        return out

    needs: list[str] = []

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
        syms = sorted(set(re.findall(r"\b([A-Z]{1,5})\b", t)))
        stop = {
            "I", "A", "THE", "AND", "OR", "TO", "FOR", "ON", "IN", "OF", "IS", "IT",
            "WHAT", "CAN", "NOW", "ETC", "DAY", "SMA", "RSI", "CIO", "READ", "ONLY",
            "USD", "READY", "NEAR", "ZONE", "STOP", "ALEX", "LLM", "YOU", "HOW",
            "WHICH", "USING", "MODEL", "FLASH", "PRO", "AI", "WHY",
        }
        out["symbols"] = [s for s in syms if s not in stop][:12]
        return out

    # P0: meta_system BEFORE desk defaults — never fall through to re-entry dump
    if _looks_like_meta_system(t):
        out["intent"] = "meta_system"
        if re.search(r"(?is)\b(llm|model|deepseek|flash|pro|ai)\b", t):
            needs.append("runtime_llm")
        needs.append("runtime_status")
        out["needs"] = list(dict.fromkeys(needs))
    else:
        if re.search(
            r"(?is)\bre[\s\-]?(?:entr|enter)|rentr|ready\s+to\s+(?:buy|purchase|review)|buy\s+back",
            t,
        ):
            needs.append("reentry_ready")
            out["intent"] = "reentry"
        if re.search(
            r"(?is)\b(support|resistance|s/?r|50[\s\-]?day|sma\s*50|sma50|sma\s*20|levels?|stop)\b",
            t,
        ):
            needs.append("reentry_levels")
            if out["intent"] in ("unclear", "general"):
                out["intent"] = "reentry"
        if re.search(r"(?is)\b(cash|buying\s+power)\b", t):
            needs.append("cash")
            if out["intent"] in ("unclear", "freeform"):
                out["intent"] = "cash"
        if re.search(r"(?is)\b(portfolio|holdings|book)\b", t):
            needs.append("portfolio")
            if out["intent"] in ("unclear", "freeform"):
                out["intent"] = "portfolio"
        if re.search(r"(?is)\b(risk|heat|drawdown)\b", t):
            needs.append("risk")
            if out["intent"] in ("unclear", "freeform"):
                out["intent"] = "risk"
        if re.search(
            r"(?is)\b(research|hermes|thesis|why\s+(?:own|hold|watch)|deep\s+dive)\b",
            t,
        ):
            needs.append("research")
            if out["intent"] in ("unclear", "freeform"):
                out["intent"] = "research"

        # Explainer/comparison language → freeform (soft desk hints OK, no reentry)
        if _looks_like_freeform(t) and out["intent"] not in ("reentry", "meta_system"):
            soft = [n for n in needs if n in ("portfolio", "cash", "risk", "research")]
            out["intent"] = "freeform"
            out["needs"] = soft
        # P0: NO default reentry_ready/portfolio — unmatched → freeform agent
        elif not needs:
            out["intent"] = "freeform"
            out["needs"] = []
        else:
            out["needs"] = list(dict.fromkeys(needs))

    syms = sorted(set(re.findall(r"\b([A-Z]{1,5})\b", t)))
    stop = {
        "I", "A", "THE", "AND", "OR", "TO", "FOR", "ON", "IN", "OF", "IS", "IT",
        "WHAT", "CAN", "NOW", "ETC", "DAY", "SMA", "RSI", "CIO", "READ", "ONLY",
        "USD", "READY", "NEAR", "ZONE", "STOP", "ALEX", "LLM", "YOU", "HOW",
        "WHICH", "USING", "MODEL", "FLASH", "PRO", "AI",
    }
    out["symbols"] = [s for s in syms if s not in stop][:12]

    # Flash refine (intent only) — may not override clear heuristic meta_system
    heuristic_intent = out["intent"]
    heuristic_needs = list(out["needs"])

    if _env("CIO_OPERATOR_INTENT_FLASH", "1").lower() not in ("0", "false", "off", "no"):
        try:
            from scripts.lib.cio_plan_enrichment import call_governed_llm, load_llm_policy

            system = (
                "You classify CIO Telegram operator questions. "
                "Return ONE JSON object only with keys: "
                "intent (meta_system|reentry|portfolio|cash|risk|research|desk_question|"
                "freeform|unclear|other), "
                "symbols (list of tickers), "
                "needs (subset of: runtime_llm, runtime_status, reentry_ready, reentry_levels, "
                "cash, portfolio, risk, research). "
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
                        "reentry", "portfolio", "cash", "risk", "research",
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
                        "meta_system", "reentry", "portfolio", "cash", "risk", "research",
                    ):
                        out["intent"] = "freeform"
                        out["needs"] = [
                            n for n in (out["needs"] or [])
                            if n in ("portfolio", "cash", "risk", "research")
                        ]

                    if isinstance(parsed.get("symbols"), list):
                        out["symbols"] = [
                            str(s).upper() for s in parsed["symbols"] if str(s).isalpha()
                        ][:12]
                    out["ok"] = True
                    out["source"] = "deepseek_flash"
                    out["model"] = llm.get("model") or "deepseek-v4-flash"
                    # Final guard: meta heuristic always blocks desk needs
                    if _looks_like_meta_system(t):
                        out["intent"] = "meta_system"
                        out["needs"] = [
                            n for n in (out["needs"] or []) if n in _RUNTIME_NEEDS
                        ] or ["runtime_llm", "runtime_status"]
                    return out
            out["error"] = str(llm.get("error") or "intent_flash_failed")
        except Exception as exc:
            out["error"] = f"intent:{type(exc).__name__}:{exc}"

    out["ok"] = True  # heuristic is acceptable
    return out


def _domain_payload(snap: dict[str, Any], name: str) -> dict[str, Any]:
    domains = snap.get("domains") or {}
    d = domains.get(name) or {}
    if isinstance(d, dict) and "data" in d and d.get("data") is not None:
        return d.get("data") if isinstance(d.get("data"), dict) else {"value": d.get("data")}
    return d if isinstance(d, dict) else {}


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

    port = _domain_payload(snap, "portfolio")
    if port and port.get("total_value") is not None:
        facts["portfolio"] = {
            "total_value": port.get("total_value"),
            "holdings_count": port.get("holdings_count"),
            "day_change_pct": port.get("day_change_pct"),
            "as_of": port.get("as_of"),
        }
    else:
        soft_gaps.append({
            "domain": "portfolio", "symbol": None, "field": "totals",
            "reason": "portfolio totals DATA_UNAVAILABLE", "gap_type": "soft",
        })

    cash = _domain_payload(snap, "cash_buying_power")
    if cash:
        nested = cash.get("data") if isinstance(cash.get("data"), dict) else {}
        facts["cash"] = {
            "cash_pct": cash.get("cash_pct", nested.get("cash_pct")),
            "buying_power": cash.get("buying_power") or cash.get("cash") or nested.get("buying_power"),
            "quality_state": cash.get("quality_state") or cash.get("state"),
        }
    else:
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

    hermes = _domain_payload(snap, "hermes_research")
    if hermes and hermes.get("state") not in (None, "DATA_UNAVAILABLE"):
        facts["hermes"] = {
            "promoted_research_count": hermes.get("promoted_research_count"),
            "staged_research_count": hermes.get("staged_research_count"),
            "latest_topics": hermes.get("latest_topics"),
        }

    available["freeform_context"] = facts
    available["soft_gaps"] = soft_gaps
    return {
        "ok": True,
        "authority": AUTHORITY,
        "available": available,
        "gaps": soft_gaps,
        "blocking_gaps": [],  # freeform answers immediately
        "sources": sources,
        "complete": True,
    }


def _format_freeform_failsoft(context: dict[str, Any], soft_gaps: list[dict[str, Any]]) -> str:
    """Deterministic freeform reply when Flash is off or fails."""
    lines = ["🧠 *Alex · freeform (Trade-AI grounded)*"]
    port = context.get("portfolio") or {}
    if port:
        lines.append(
            f"• Book: value={port.get('total_value')} holdings={port.get('holdings_count')} "
            f"day%={port.get('day_change_pct')}"
        )
    cash = context.get("cash") or {}
    if cash and (cash.get("cash_pct") is not None or cash.get("buying_power") is not None):
        lines.append(
            f"• Cash: pct={cash.get('cash_pct')} bp={cash.get('buying_power')} "
            f"q={cash.get('quality_state')}"
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
    for sym, th in (context.get("theses") or {}).items():
        summary = th.get("thesis_summary") or th.get("why_owned_or_watched") or th.get("thesis_state")
        lines.append(f"• Thesis `{sym}`: {summary}")
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


def _validate_freeform_reply(text: str, context: dict[str, Any]) -> Optional[str]:
    """Reject Flash replies that invent READY/NEAR dumps not present in facts."""
    if not text:
        return "empty"
    low = text.lower()
    if "defensive_observe" in low and "acknowledge and monitor" in low:
        return "s0_wallpaper"
    # READY TO REVIEW dump only OK if context somehow included it (freeform never does)
    if "ready to review" in low or re.search(r"\bNEAR ENTRY\b", text):
        return "invented_reentry_dump"
    return None


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

        facts_json = json.dumps(context, default=str)[:6000]
        gaps_json = json.dumps(soft_gaps[:12], default=str)[:2000]
        system = (
            "You are Alex, Trade-AI CIO assistant on Telegram. READ_ONLY_ADVISORY — "
            "no orders/stops. Answer the operator in a helpful free-form style.\n"
            "Rules:\n"
            "1) You MAY reason generally (strategy, comparisons, explainers).\n"
            "2) Prices, weights, READY/NEAR lists, R:R, cash, heat, quantities — "
            "ONLY from TRADE_AI_FACTS. If missing, say DATA_UNAVAILABLE.\n"
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
            "model": llm.get("model") or "deepseek-v4-flash",
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
    if want_reentry:
        from scripts.lib.cio_telegram_converse import (
            format_reentry_purchase_reply,
            load_reentry_desk_rows,
            _row_levels,
        )

        rows, as_of, path = load_reentry_desk_rows()
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
        # Prefer snapshot; fall back to holdings helper
        book_bits: list[str] = []
        cash_dom = _domain_payload(snap, "cash_buying_power")
        port_dom = _domain_payload(snap, "portfolio")
        hold_dom = _domain_payload(snap, "holdings_detail")
        if cash_dom:
            q = cash_dom.get("quality_state") or cash_dom.get("state")
            nested = cash_dom.get("data") if isinstance(cash_dom.get("data"), dict) else {}
            pct = cash_dom.get("cash_pct")
            if pct is None:
                pct = nested.get("cash_pct")
            bp = cash_dom.get("buying_power") or cash_dom.get("cash") or nested.get("buying_power")
            # PARTIAL cash is OK (soft) — still surface facts when present
            if pct is not None or bp is not None:
                book_bits.append(f"cash_pct={pct} buying_power={bp} quality={q}")
            elif q == "DATA_UNAVAILABLE":
                gaps.append({
                    "domain": "cash_buying_power",
                    "symbol": None,
                    "field": "cash",
                    "reason": "cash domain unavailable",
                    "gap_type": "missing_market_data",
                })
        if port_dom:
            book_bits.append(
                f"portfolio_value={port_dom.get('total_value')} "
                f"holdings={port_dom.get('holdings_count')}"
            )
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
        hermes = _domain_payload(snap, "hermes_research")
        if hermes and hermes.get("state") not in (None, "DATA_UNAVAILABLE"):
            available["hermes_research"] = {
                "promoted_research_count": hermes.get("promoted_research_count"),
                "staged_research_count": hermes.get("staged_research_count"),
                "latest_topics": hermes.get("latest_topics"),
                "model_provider": hermes.get("model_provider"),
            }
        else:
            gaps.append({
                "domain": "hermes_research",
                "symbol": symbols[0] if symbols else None,
                "field": "research",
                "reason": "hermes_research unavailable or empty",
                "gap_type": "missing_research",
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

    return {
        "ok": True,
        "authority": AUTHORITY,
        "available": available,
        "gaps": gaps,
        "blocking_gaps": blocking,
        "sources": sources,
        "complete": not blocking and bool(available),
    }


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
    if hermes:
        extras.append(
            f"Hermes: promoted={hermes.get('promoted_research_count')} "
            f"staged={hermes.get('staged_research_count')} "
            f"topics={hermes.get('latest_topics')}"
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

    if card and _reentry_flash_enabled():
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
    evidence = gather_tradeai_evidence(intent)
    pending_id = f"opr_{uuid.uuid4().hex[:12]}"

    result: dict[str, Any] = {
        "authority": AUTHORITY,
        "intent": intent,
        "evidence_complete": evidence.get("complete"),
        "gaps": evidence.get("gaps") or [],
        "blocking_gaps": evidence.get("blocking_gaps") or [],
        "sources": evidence.get("sources") or [],
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
        if any(g.get("domain") == "hermes_research" for g in blocking):
            _enqueue_hermes_research(
                symbols=[str(s).upper() for s in (intent.get("symbols") or [])],
                chat_id=str(chat_id),
                pending_id=pending_id,
                operator_text=text or "",
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
        })
        result.update({
            "kind": "deferred",
            "pending_id": pending_id,
            "text": (
                "🧠 *Alex · Trade-AI pull queued*\n"
                f"I analyzed your ask (`{intent.get('intent')}`). "
                "Required facts are not fully in Trade-AI yet:\n"
                + "\n".join(f"• `{b}`" for b in gap_bits)
                + "\n\nQueued into the controlled gap pipeline. "
                f"I'll reply here when it lands.\n"
                f"Pending: `{pending_id}`\n"
                "No orders/stops · READ_ONLY_ADVISORY"
            ),
            "reply_source": "deferred_gap",
        })
        _emit_telegram_desk_payload(intent, result)
        return result

    curated = _curate_from_evidence(text, evidence)
    soft = [g for g in (evidence.get("gaps") or []) if g not in blocking]
    text_out = curated.get("text") or ""
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
    for row in open_rows:
        try:
            intent = row.get("intent") or analyze_operator_intent(row.get("operator_text") or "")
            evidence = gather_tradeai_evidence(intent)
            if not evidence.get("complete"):
                continue
            curated = _curate_from_evidence(str(row.get("operator_text") or ""), evidence)
            body = (
                f"📬 *Follow-up* `{row.get('pending_id')}` — Trade-AI data landed\n\n"
                + (curated.get("text") or "")
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
        "failed": failed,
        "authority": AUTHORITY,
    }
