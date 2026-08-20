"""CIO operator desk loop — DeepSeek analyzes; Trade-AI supplies truth.

Contract (READ_ONLY_ADVISORY):
  1. Flash analyzes what the operator is asking (intent JSON only).
  2. Evidence is pulled only from controlled Trade-AI artifacts
     (re-entry desk, holdings / Data Broker paths) — never invented by the model.
  3. If required evidence is missing → register a gap, ack the operator
     ("pulling into Trade-AI — will reply when it lands"), and ledger a pending reply.
  4. When evidence arrives → fulfill pending and Telegram-reply with vetted facts.
  5. Flash may only rewrite wording of vetted facts for Telegram clarity.

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


def analyze_operator_intent(text: str) -> dict[str, Any]:
    """DeepSeek Flash → structured intent. Numbers never come from this step."""
    out: dict[str, Any] = {
        "ok": False,
        "source": "heuristic",
        "model": None,
        "intent": "general",
        "symbols": [],
        "needs": [],
        "error": None,
    }
    t = (text or "").strip()
    if not t:
        out["error"] = "empty"
        return out

    # Heuristic baseline (always available if Flash fails)
    needs: list[str] = []
    low = t.lower()
    if re.search(r"(?is)\bre[\s\-]?(?:entr|enter)|rentr|ready\s+to\s+(?:buy|purchase|review)|buy\s+back", t):
        needs.append("reentry_ready")
        out["intent"] = "reentry"
    if re.search(r"(?is)\b(support|resistance|s/?r|50[\s\-]?day|sma\s*50|sma50|sma\s*20|levels?|stop)\b", t):
        needs.append("reentry_levels")
        if out["intent"] == "general":
            out["intent"] = "reentry"
    if re.search(r"(?is)\b(cash|buying\s+power)\b", t):
        needs.append("cash")
    if re.search(r"(?is)\b(portfolio|holdings|book)\b", t):
        needs.append("portfolio")
    if re.search(r"(?is)\b(risk|heat|drawdown)\b", t):
        needs.append("risk")
    if not needs:
        needs = ["reentry_ready", "portfolio"]  # safe default context for desk Qs
        out["intent"] = "desk_question"

    syms = sorted(set(re.findall(r"\b([A-Z]{1,5})\b", t)))
    # Drop common English false positives
    stop = {
        "I", "A", "THE", "AND", "OR", "TO", "FOR", "ON", "IN", "OF", "IS", "IT",
        "WHAT", "CAN", "NOW", "ETC", "DAY", "SMA", "RSI", "CIO", "READ", "ONLY",
        "USD", "READY", "NEAR", "ZONE", "STOP", "ALEX",
    }
    out["symbols"] = [s for s in syms if s not in stop][:12]
    out["needs"] = needs

    # Flash refine (intent only)
    if _env("CIO_OPERATOR_INTENT_FLASH", "1").lower() not in ("0", "false", "off", "no"):
        try:
            from scripts.lib.cio_plan_enrichment import call_governed_llm, load_llm_policy
            system = (
                "You classify CIO Telegram operator questions. "
                "Return ONE JSON object only with keys: "
                "intent (reentry|portfolio|cash|risk|desk_question|other), "
                "symbols (list of tickers), "
                "needs (subset of: reentry_ready, reentry_levels, cash, portfolio, risk). "
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
                    if parsed.get("intent"):
                        out["intent"] = str(parsed["intent"])[:40]
                    if isinstance(parsed.get("symbols"), list):
                        out["symbols"] = [
                            str(s).upper() for s in parsed["symbols"] if str(s).isalpha()
                        ][:12]
                    if isinstance(parsed.get("needs"), list):
                        allowed = {
                            "reentry_ready", "reentry_levels", "cash", "portfolio", "risk",
                        }
                        flash_needs = [
                            str(n) for n in parsed["needs"] if str(n) in allowed
                        ]
                        if flash_needs:
                            out["needs"] = flash_needs
                    out["ok"] = True
                    out["source"] = "deepseek_flash"
                    out["model"] = llm.get("model") or "deepseek-v4-flash"
                    return out
            out["error"] = str(llm.get("error") or "intent_flash_failed")
        except Exception as exc:
            out["error"] = f"intent:{type(exc).__name__}:{exc}"

    out["ok"] = True  # heuristic is acceptable
    return out


def gather_tradeai_evidence(intent: dict[str, Any]) -> dict[str, Any]:
    """Pull vetted Trade-AI evidence only. Report gaps — never invent fills."""
    from scripts.lib.cio_telegram_converse import (
        format_reentry_purchase_reply,
        load_reentry_desk_rows,
        _portfolio_cash_fact_lines,
        _row_levels,
    )

    needs = list(intent.get("needs") or [])
    symbols = [str(s).upper() for s in (intent.get("symbols") or [])]
    available: dict[str, Any] = {}
    gaps: list[dict[str, Any]] = []
    sources: list[str] = []

    rows, as_of, path = load_reentry_desk_rows()
    if path:
        sources.append(str(path))
    if "reentry_ready" in needs or "reentry_levels" in needs or intent.get("intent") == "reentry":
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
            # Per-symbol level gaps
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
                    if symbols:  # only gap if operator named it
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

    if "cash" in needs or "portfolio" in needs:
        book = _portfolio_cash_fact_lines()
        if book:
            available["book"] = "; ".join(book)
            sources.append("holdings.json")
        else:
            gaps.append({
                "domain": "portfolio",
                "symbol": None,
                "field": "holdings",
                "reason": "holdings.json unavailable",
                "gap_type": "missing_market_data",
            })

    # Material gaps = block immediate complete answer only when core need unsatisfied
    blocking = []
    if ("reentry_ready" in needs or intent.get("intent") == "reentry") and not available.get("reentry_card"):
        blocking = [g for g in gaps if g.get("domain") == "reentry_decision_desk"]
    # Named symbol totally missing from desk while asking reentry
    if symbols and ("reentry_ready" in needs or "reentry_levels" in needs):
        blocking.extend(
            g for g in gaps
            if g.get("symbol") in symbols and g.get("field") == "row"
        )

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
        # Shape minimal rows for requeue helper
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


def _curate_from_evidence(operator_text: str, evidence: dict[str, Any]) -> dict[str, Any]:
    """Flash rewrites vetted facts only — fail-soft to raw card."""
    from scripts.lib.cio_telegram_converse import (
        curate_reentry_reply_with_flash,
        _reentry_flash_enabled,
    )

    card = (evidence.get("available") or {}).get("reentry_card") or ""
    book = (evidence.get("available") or {}).get("book") or ""
    facts = card
    if book:
        facts = f"Book: {book}\n\n{card}"

    if not facts.strip():
        return {
            "ok": False,
            "text": (
                "Trade-AI has no vetted facts for that yet. "
                "Queued a pull — I'll reply when it lands.\n"
                "READ_ONLY_ADVISORY"
            ),
            "source": "empty_evidence",
        }

    # Prefer Flash Q&A over polish-only when general path
    try:
        from scripts.lib.cio_telegram_converse import answer_operator_free_text_with_flash
        # Reuse Flash answerer but it gathers again — call curate path directly
        pass
    except Exception:
        pass

    ready = []
    near = []
    # Extract tickers from card for validation
    ready = re.findall(r"\*([A-Z]{1,5})\*", card)
    near = re.findall(r"`([A-Z]{1,5})`", card)

    if _reentry_flash_enabled():
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

    return {
        "ok": True,
        "text": facts if facts.endswith("READ_ONLY_ADVISORY") else facts + "\nREAD_ONLY_ADVISORY",
        "source": "tradeai_deterministic",
        "model": None,
    }


def handle_operator_desk_question(
    text: str,
    *,
    chat_id: str = "",
    message_id: str = "",
    channel: str = "telegram",
) -> dict[str, Any]:
    """Full loop: analyze → Trade-AI pull → answer or defer with pending reply."""
    intent = analyze_operator_intent(text)
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
                + f"\n\nQueued into the controlled gap pipeline. "
                f"I'll reply here when it lands.\n"
                f"Pending: `{pending_id}`\n"
                "No orders/stops · READ_ONLY_ADVISORY"
            ),
            "reply_source": "deferred_gap",
        })
        return result

    curated = _curate_from_evidence(text, evidence)
    # Soft gaps (non-blocking) — mention briefly
    soft = [g for g in (evidence.get("gaps") or []) if g not in blocking]
    text_out = curated.get("text") or ""
    if soft and "DATA_UNAVAILABLE" not in text_out:
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
    return result


def try_fulfill_pending_replies(
    send_fn: SendFn,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    """Re-check open pending operator questions; reply when Trade-AI has facts."""
    rows = _read_jsonl(PENDING_PATH)
    # Latest status wins per pending_id
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
