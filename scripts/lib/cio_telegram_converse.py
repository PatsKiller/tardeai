"""CIO Telegram converse — free-text + reply continuity → OPERATOR_MESSAGE → wake → reply.

READ_ONLY_ADVISORY forever. No broker/order/stop/2FA.

Env:
  TELEGRAM_CIO_BOT_TOKEN       — dedicated bot (required for live)
  TELEGRAM_CIO_CHAT_IDS        — comma allowlist (or TELEGRAM_CIO_ALLOWLIST)
  CIO_TELEGRAM_CONVERSE=0|1    — master switch (default 1 if allowlist set)
  CIO_TELEGRAM_WAKES_PER_HOUR  — rate limit (default 20)
  COMMAND_CENTER_BASE_URL      — optional deep links
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DEDUP = PROJECT_ROOT / "data" / "cio" / "cio_telegram_msg_dedup.jsonl"
DEFAULT_MSG_MAP = PROJECT_ROOT / "data" / "cio" / "cio_telegram_plan_messages.jsonl"
DEFAULT_RATE = PROJECT_ROOT / "data" / "cio" / "cio_telegram_rate.jsonl"
DEFAULT_OFFSET = PROJECT_ROOT / "data" / "cio" / ".cio_telegram_offset"

FOOTER_RE = re.compile(
    r"(?:plan_id|plan)\s*[:=]\s*`?(plan_[a-z0-9_\-]+)`?"
    r"|(?:action_id|action)\s*[:=]\s*`?([a-z0-9_\-]+)`?"
    r"|(?:goal_id|goal)\s*[:=]\s*`?(goal_[a-z0-9_\-]+)`?",
    re.I,
)
SYMBOL_RE = re.compile(r"\b([A-Z]{1,5})\b")
ACK_RE = re.compile(r"^\s*(ack|acknowledge)\s*(plan_[a-z0-9_\-]+|plan-[a-z0-9_\-]+)?\s*$", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env(k: str, default: str = "") -> str:
    return os.environ.get(k, default).strip()


def converse_enabled() -> bool:
    raw = _env("CIO_TELEGRAM_CONVERSE", "")
    if raw:
        return raw.lower() not in ("0", "false", "off", "no")
    # default on only when allowlist configured
    return bool(allowlist_chat_ids())


def cio_bot_token() -> str:
    return _env("TELEGRAM_CIO_BOT_TOKEN")


def allowlist_chat_ids() -> set[str]:
    raw = _env("TELEGRAM_CIO_CHAT_IDS") or _env("TELEGRAM_CIO_ALLOWLIST") or _env("TELEGRAM_CHAT_ID")
    return {c.strip() for c in raw.split(",") if c.strip()}


def wakes_per_hour() -> int:
    try:
        return max(1, int(_env("CIO_TELEGRAM_WAKES_PER_HOUR", "20")))
    except ValueError:
        return 20


def cc_base() -> str:
    return _env("COMMAND_CENTER_BASE_URL") or _env("TRADEAI_CC_BASE_URL") or ""


# ── Dedup / rate / message map ──────────────────────────────────────────────


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(path.suffix + ".lock")
    with open(lock, "a") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            with open(path, "a") as fh:
                fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
                fh.flush()
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def message_seen(message_id: str | int, *, path: Path = DEFAULT_DEDUP) -> bool:
    mid = str(message_id)
    if not path.exists():
        return False
    try:
        for line in path.read_text().splitlines()[-5000:]:
            try:
                if json.loads(line).get("message_id") == mid:
                    return True
            except json.JSONDecodeError:
                continue
    except Exception:
        return False
    return False


def mark_message_seen(message_id: str | int, chat_id: str, *, path: Path = DEFAULT_DEDUP) -> None:
    _append_jsonl(path, {
        "message_id": str(message_id),
        "chat_id": str(chat_id),
        "ts": _now(),
    })


def record_plan_message(
    plan_id: str,
    telegram_message_id: str | int,
    chat_id: str,
    *,
    path: Path = DEFAULT_MSG_MAP,
) -> None:
    _append_jsonl(path, {
        "plan_id": plan_id,
        "telegram_message_id": str(telegram_message_id),
        "chat_id": str(chat_id),
        "ts": _now(),
    })


def plan_id_for_reply_message(
    reply_to_message_id: str | int | None,
    *,
    path: Path = DEFAULT_MSG_MAP,
) -> Optional[str]:
    if not reply_to_message_id or not path.exists():
        return None
    rid = str(reply_to_message_id)
    try:
        for line in reversed(path.read_text().splitlines()):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(row.get("telegram_message_id")) == rid:
                return row.get("plan_id")
    except Exception:
        return None
    return None


def rate_limit_ok(chat_id: str, *, path: Path = DEFAULT_RATE, limit: Optional[int] = None) -> bool:
    lim = limit if limit is not None else wakes_per_hour()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    n = 0
    if path.exists():
        try:
            for line in path.read_text().splitlines()[-2000:]:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if str(row.get("chat_id")) != str(chat_id):
                    continue
                ts = row.get("ts")
                if not ts:
                    continue
                try:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt >= cutoff:
                        n += 1
                except Exception:
                    continue
        except Exception:
            return True
    return n < lim


def mark_wake_rate(chat_id: str, *, path: Path = DEFAULT_RATE) -> None:
    _append_jsonl(path, {"chat_id": str(chat_id), "ts": _now()})


# ── Parse ───────────────────────────────────────────────────────────────────


def parse_ids_from_text(text: str) -> dict[str, Optional[str]]:
    out = {"plan_id": None, "action_id": None, "goal_id": None}
    for m in FOOTER_RE.finditer(text or ""):
        if m.group(1):
            out["plan_id"] = m.group(1)
        if m.group(2):
            out["action_id"] = m.group(2)
        if m.group(3):
            out["goal_id"] = m.group(3)
    # re: PLAN-… patterns
    m = re.search(r"re:\s*(plan_[a-z0-9_\-]+)", text or "", re.I)
    if m:
        out["plan_id"] = m.group(1)
    m = re.search(r"\bgoal\s+(goal_[a-z0-9_\-]+)", text or "", re.I)
    if m:
        out["goal_id"] = m.group(1)
    return out


def extract_symbols(text: str) -> list[str]:
    # avoid common English words
    stop = {
        "I", "A", "THE", "AND", "OR", "FOR", "TO", "OF", "IN", "ON", "IS", "IT",
        "BE", "AT", "AS", "AN", "IF", "MY", "WE", "DO", "SO", "NO", "YES", "OK",
        "CEO", "CFO", "ETF", "USD", "ALL", "NOW", "BUY", "SELL", "HOLD", "TRIM",
        "ACK", "PLAN", "GOAL", "CIO", "WHAT", "HOW", "WHY", "CAN", "YOU", "ME",
    }
    found = []
    for m in SYMBOL_RE.finditer(text or ""):
        s = m.group(1)
        if s in stop or len(s) < 2:
            continue
        if s not in found:
            found.append(s)
    return found[:8]


def parse_reply_footer(bot_text: str) -> dict[str, Optional[str]]:
    return parse_ids_from_text(bot_text or "")


# ── Structured reply formatter ──────────────────────────────────────────────


def format_structured_reply(
    *,
    summary: str,
    evidence_refs: Optional[list[dict[str, Any]]] = None,
    options: Optional[list[dict[str, Any]]] = None,
    recommendation: str = "",
    risks: Optional[list[str]] = None,
    plan_id: Optional[str] = None,
    goal_id: Optional[str] = None,
    revisit_at: Optional[str] = None,
    llm_deferred: bool = False,
    deep_links: Optional[list[str]] = None,
) -> str:
    lines: list[str] = []
    lines.append("🧠 *CIO advisory* · READ_ONLY")
    if llm_deferred:
        lines.append("_(LLM deferred — template reply)_")
    lines.append("")
    lines.append("*Summary*")
    lines.append(summary.strip() or "(no summary)")
    if evidence_refs:
        lines.append("")
        lines.append("*Evidence*")
        for r in evidence_refs[:8]:
            dom = r.get("domain") or "?"
            as_of = r.get("as_of") or "DATA_UNAVAILABLE"
            fields = ",".join(r.get("fields_used") or [])[:40]
            lines.append(f"• `{dom}` as_of={as_of}" + (f" ({fields})" if fields else ""))
    if options:
        lines.append("")
        lines.append("*Options*")
        for o in options[:6]:
            lab = o.get("label") or o.get("id") or "?"
            lines.append(f"• {lab}")
    if recommendation:
        lines.append("")
        lines.append("*Recommendation*")
        lines.append(recommendation.strip())
    if risks:
        lines.append("")
        lines.append("*Risks*")
        for rk in risks[:5]:
            lines.append(f"• {rk}")
    lines.append("")
    meta = []
    if plan_id:
        meta.append(f"plan_id: `{plan_id}`")
    if goal_id:
        meta.append(f"goal_id: `{goal_id}`")
    if revisit_at:
        meta.append(f"revisit_at: `{revisit_at}`")
    if meta:
        lines.append(" · ".join(meta))
    base = cc_base().rstrip("/")
    if deep_links and base:
        links = " ".join(f"{base}{p}" if p.startswith("/") else p for p in deep_links[:4])
        lines.append(f"CC: {links}")
    lines.append("")
    lines.append("_Reply to this message to continue · `/cio ack " + (plan_id or "<id>") + "` or reply `ack`_")
    lines.append("_No orders/stops from chat. READ_ONLY_ADVISORY._")
    return "\n".join(lines)


# ── Context assembly ────────────────────────────────────────────────────────


def assemble_context(
    text: str,
    *,
    plan_id: Optional[str] = None,
    action_id: Optional[str] = None,
    goal_id: Optional[str] = None,
) -> dict[str, Any]:
    symbols = extract_symbols(text)
    ctx: dict[str, Any] = {
        "authority": "READ_ONLY_ADVISORY",
        "symbols": symbols,
        "plan": None,
        "goal": None,
        "open_plans": [],
        "open_goals": [],
        "evidence_refs": [],
        "data_notes": [],
    }
    try:
        from scripts.lib.cio_plans import CIOPlanStore
        store = CIOPlanStore()
        if plan_id:
            ctx["plan"] = store.get_plan(plan_id)
        for s in symbols:
            ctx["open_plans"].extend(store.list_open_plans(symbol=s, limit=3))
        if not symbols:
            ctx["open_plans"] = store.list_open_plans(limit=5)
    except Exception as exc:
        ctx["data_notes"].append(f"plans:DATA_UNAVAILABLE:{type(exc).__name__}")

    try:
        from scripts.lib.cio_goals import CIOGoalStore
        gs = CIOGoalStore()
        if goal_id:
            ctx["goal"] = gs.get_goal(goal_id)
        ctx["open_goals"] = gs.list_open_goals(owner_agent="alex", limit=5)
        if ctx.get("goal") and ctx["goal"].get("thesis_summary"):
            ctx["evidence_refs"].append({
                "domain": "cio_goals",
                "as_of": ctx["goal"].get("updated_ts") or "DATA_UNAVAILABLE",
                "fields_used": ["thesis_summary"],
            })
    except Exception as exc:
        ctx["data_notes"].append(f"goals:DATA_UNAVAILABLE:{type(exc).__name__}")

    # Lightweight holdings facts for mentioned symbols (fail-soft)
    try:
        holdings_path = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
        if holdings_path.exists() and symbols:
            data = json.loads(holdings_path.read_text())
            as_of = data.get("as_of") or data.get("generated_at") or "DATA_UNAVAILABLE"
            for h in data.get("holdings") or []:
                sym = str(h.get("symbol") or "").upper()
                if sym not in symbols:
                    continue
                ctx["evidence_refs"].append({
                    "domain": "holdings",
                    "as_of": str(as_of),
                    "fields_used": ["symbol", "market_value", "cost_basis"],
                    "symbol": sym,
                    "market_value": h.get("market_value"),
                    "cost_basis": h.get("cost_basis") or h.get("avg_cost"),
                })
    except Exception as exc:
        ctx["data_notes"].append(f"holdings:DATA_UNAVAILABLE:{type(exc).__name__}")

    if action_id:
        ctx["action_id"] = action_id
    return ctx


def build_template_advisory(text: str, ctx: dict[str, Any]) -> dict[str, Any]:
    """Deterministic reply when LLM is blocked or disabled."""
    symbols = ctx.get("symbols") or []
    plan = ctx.get("plan") or {}
    parts = [f"Operator: {text[:400]}"]
    if symbols:
        parts.append(f"Symbols mentioned: {', '.join(symbols)}.")
    if plan:
        parts.append(f"Continuing plan {plan.get('plan_id')} ({plan.get('situation_type')}).")
        if plan.get("recommendation"):
            parts.append(f"Prior recommendation: {plan.get('recommendation')[:200]}")
    facts = []
    for r in ctx.get("evidence_refs") or []:
        if r.get("symbol") and r.get("market_value") is not None:
            facts.append(f"{r['symbol']} market_value={r['market_value']} (as_of={r.get('as_of')})")
        elif r.get("domain"):
            facts.append(f"{r['domain']} as_of={r.get('as_of')}")
    if facts:
        parts.append("Facts from context: " + "; ".join(facts[:5]))
    if ctx.get("data_notes"):
        parts.append("Data notes: " + "; ".join(ctx["data_notes"][:3]))
    parts.append("This is READ_ONLY_ADVISORY. No orders or stops will be placed from chat.")

    options = [
        {"id": "ack", "label": "Acknowledge and monitor", "pros": "No change", "cons": "May delay action"},
        {"id": "deepen", "label": "Request deeper desk review", "pros": "More evidence", "cons": "Takes time"},
        {"id": "link_goal", "label": "Link to open goal", "pros": "Continuity", "cons": "Needs goal id"},
    ]
    if plan and plan.get("options"):
        options = plan["options"][:4]

    rec = plan.get("recommendation") if plan else (
        "Review facts above; reply to continue this thread or use /cio portfolio|actions for status."
    )
    risks = list(plan.get("risks") or ["Context incomplete if domains unavailable", "No auto-execution"])
    revisit = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()

    return {
        "summary": " ".join(parts)[:900],
        "evidence_refs": ctx.get("evidence_refs") or [],
        "options": options,
        "recommendation": rec,
        "risks": risks,
        "revisit_at": revisit,
        "llm_deferred": True,
        "owner_agent": "alex",
        "deep_links": ["/v3/", "/v3/advisory", "/v3/risk"],
    }


# ── Bus + wake ──────────────────────────────────────────────────────────────


def emit_operator_message(payload: dict[str, Any]) -> Optional[str]:
    try:
        from scripts.lib.cio_event_bus import CIOEventBus
        bus = CIOEventBus()
        evt = bus.emit("operator.message", payload, source="cio_telegram_bot", priority="HIGH")
        return getattr(evt, "event_id", None) or (evt.get("event_id") if isinstance(evt, dict) else None)
    except Exception:
        return None


def enqueue_operator_wake(
    *,
    chat_id: str,
    message_id: str,
    text: str,
    plan_id: Optional[str],
    goal_id: Optional[str],
    action_id: Optional[str],
    event_id: Optional[str],
    target_agent: str = "alex",
) -> Optional[str]:
    try:
        from scripts.lib.cio_wake_jobs import CIOWakeJobStore
        store = CIOWakeJobStore()
        hour = datetime.now(timezone.utc).strftime("%Y%m%d%H")
        wake_job_id = f"wake_op_{target_agent}_{message_id}_{hour}"
        store.enqueue(
            {
                "wake_job_id": wake_job_id,
                "trigger_type": "OPERATOR_MESSAGE",
                "trigger_ref": str(message_id),
                "trigger_hash": hashlib.sha256(f"{chat_id}:{message_id}".encode()).hexdigest()[:16],
                "reason_codes": ["OPERATOR_MESSAGE"],
                "required_domains": ["portfolio"],
                "wake_intent": "NEW_RUN",
                "idempotency_key": wake_job_id,
                "context": {
                    "target_agent": target_agent,
                    "chat_id": str(chat_id),
                    "message_id": str(message_id),
                    "text": text[:2000],
                    "plan_id": plan_id,
                    "goal_id": goal_id,
                    "action_id": action_id,
                    "event_id": event_id,
                    "authority": "READ_ONLY_ADVISORY",
                },
            },
            actor_id="cio_telegram_bot",
            actor_type="system",
            authority="READ_ONLY_ADVISORY",
        )
        return wake_job_id
    except Exception:
        return None


def ensure_converse_plan(
    advisory: dict[str, Any],
    *,
    plan_id: Optional[str],
    symbols: list[str],
    text: str,
) -> str:
    from scripts.lib.cio_plans import CIOPlanStore
    store = CIOPlanStore()
    if plan_id:
        existing = store.get_plan(plan_id)
        if existing:
            store.update_plan(
                plan_id,
                summary=advisory.get("summary") or existing.get("summary"),
                recommendation=advisory.get("recommendation") or existing.get("recommendation"),
                options=advisory.get("options") or existing.get("options"),
                risks=advisory.get("risks") or existing.get("risks"),
                evidence_refs=advisory.get("evidence_refs") or existing.get("evidence_refs"),
                status="proposed",
                actor_id="cio_telegram_bot",
            )
            return plan_id
    plan = store.create_plan(
        situation_type="S0_OPERATOR_CONVERSE",
        symbols=symbols,
        title=f"Operator converse: {(text or '')[:60]}",
        summary=advisory.get("summary") or "",
        options=advisory.get("options") or [{"id": "ack", "label": "Acknowledge", "pros": "", "cons": ""}],
        recommendation=advisory.get("recommendation") or "Review and reply.",
        risks=advisory.get("risks") or [],
        evidence_refs=advisory.get("evidence_refs") or [],
        revisit_at=advisory.get("revisit_at") or (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        owner_agent=advisory.get("owner_agent") or "alex",
        cc_deep_links=advisory.get("deep_links") or ["/v3/"],
        status="proposed",
        detector_version="cio-telegram-converse-v1",
        actor_id="cio_telegram_bot",
    )
    return plan["plan_id"]


# ── Slash commands ──────────────────────────────────────────────────────────


def _import_cio_commands():
    try:
        from scripts import cio_commands as cc  # type: ignore
        return cc
    except Exception:
        import cio_commands as cc  # type: ignore
        return cc


def handle_cio_slash(text: str) -> str:
    """Run deterministic /cio commands without LLM."""
    raw = (text or "").strip()
    lower = raw.lower()
    cc = _import_cio_commands()
    if lower in ("/cio", "cio", "/cio help", "cio help"):
        return cc.HELP

    parts = raw.split()
    # normalize /cio X → argv style
    if parts and parts[0].lower() in ("/cio", "cio"):
        parts = parts[1:]
    if not parts:
        return cc.COMMANDS["status"]() if "status" in cc.COMMANDS else cc.HELP

    sub = parts[0].lower()
    # inject argv for cmd_* that read sys.argv
    import sys
    old = sys.argv[:]
    try:
        if sub == "plans":
            return cc.cmd_plans() if hasattr(cc, "cmd_plans") else cmd_plans()
        if sub == "plan" and len(parts) >= 2:
            sys.argv = ["cio_commands.py", "plan", parts[1]]
            if hasattr(cc, "cmd_plan"):
                return cc.cmd_plan()
            return cmd_plan_detail(parts[1])
        if sub in ("ack", "rate", "defer", "done", "reject"):
            sys.argv = ["cio_commands.py", sub] + parts[1:]
            fn = {
                "ack": cc.cmd_ack,
                "rate": cc.cmd_rate,
                "defer": cc.cmd_defer,
                "done": cc.cmd_done,
                "reject": cc.cmd_reject,
            }[sub]
            return fn()
        if sub in ("status", "actions", "portfolio", "hermes", "risk"):
            if sub in cc.COMMANDS:
                return cc.COMMANDS[sub]()
        return f"Unknown /cio command: {sub}\nUse /cio help"
    finally:
        sys.argv = old


def cmd_plans() -> str:
    from scripts.lib.cio_plans import CIOPlanStore
    rows = CIOPlanStore().list_open_plans(limit=15)
    if not rows:
        return "No open plans."
    lines = ["📋 *Open plans*"]
    for p in rows:
        lines.append(
            f"• `{p.get('plan_id')}` {p.get('situation_type')} "
            f"{','.join(p.get('symbols') or [])} — {p.get('status')}"
        )
    return "\n".join(lines)


def cmd_plan_detail(plan_id: str) -> str:
    from scripts.lib.cio_plans import CIOPlanStore
    p = CIOPlanStore().get_plan(plan_id)
    if not p:
        return f"Plan not found: {plan_id}"
    return format_structured_reply(
        summary=p.get("summary") or p.get("title") or "",
        evidence_refs=p.get("evidence_refs"),
        options=p.get("options"),
        recommendation=p.get("recommendation") or "",
        risks=p.get("risks"),
        plan_id=p.get("plan_id"),
        revisit_at=p.get("revisit_at"),
        llm_deferred=False,
        deep_links=p.get("cc_deep_links"),
    )


# ── Egress ──────────────────────────────────────────────────────────────────


def send_cio_message(chat_id: str, text: str, *, reply_to: Optional[str] = None) -> dict[str, Any]:
    """Single governed sender for CIO bot (uses TELEGRAM_CIO_BOT_TOKEN only)."""
    token = cio_bot_token()
    if not token:
        return {"ok": False, "error": "TELEGRAM_CIO_BOT_TOKEN unset"}
    try:
        from telegram_transport import send_message, smart_split, MAX_MSG_LEN
        chunks = smart_split(text, MAX_MSG_LEN)
        last: dict[str, Any] = {}
        for chunk in chunks:
            last = send_message(token=token, chat_id=str(chat_id), text=chunk)
        # extract message_id if present
        mid = None
        try:
            mid = (last.get("response") or {}).get("result", {}).get("message_id")
        except Exception:
            mid = None
        return {"ok": bool(last.get("ok")), "message_id": mid, "raw": last}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ── Main update processor ───────────────────────────────────────────────────


def process_telegram_message(
    msg: dict[str, Any],
    *,
    dedup_path: Path = DEFAULT_DEDUP,
    msg_map_path: Path = DEFAULT_MSG_MAP,
    rate_path: Path = DEFAULT_RATE,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Process one Telegram message dict. Fail-closed for non-allowlisted."""
    out: dict[str, Any] = {
        "handled": False,
        "authority": "READ_ONLY_ADVISORY",
        "reason": "",
    }
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    message_id = msg.get("message_id")
    text = (msg.get("text") or "").strip()
    from_user = msg.get("from") or {}

    if not text or not chat_id or message_id is None:
        out["reason"] = "empty"
        return out

    allowed = allowlist_chat_ids()
    if not allowed or chat_id not in allowed:
        out["reason"] = "not_allowlisted"
        return out

    if not converse_enabled() and not text.lower().startswith("/cio"):
        out["reason"] = "converse_disabled"
        return out

    if message_seen(message_id, path=dedup_path):
        out["reason"] = "duplicate_message_id"
        return out

    # mark seen early for idempotency
    if not dry_run:
        mark_message_seen(message_id, chat_id, path=dedup_path)

    # slash commands (deterministic)
    if text.lower().startswith("/cio") or text.lower().split()[0] in ("/cio",):
        reply = handle_cio_slash(text)
        if not dry_run:
            send_cio_message(chat_id, reply)
        out.update({"handled": True, "kind": "slash", "reply_preview": reply[:200]})
        return out

    # ack shortcut
    m_ack = ACK_RE.match(text)
    if m_ack:
        pid = m_ack.group(2)
        if not pid:
            # reply-to plan
            reply_to = msg.get("reply_to_message") or {}
            pid = plan_id_for_reply_message(reply_to.get("message_id"), path=msg_map_path)
            if not pid and reply_to.get("text"):
                pid = parse_reply_footer(reply_to.get("text") or "").get("plan_id")
        if pid:
            reply = handle_cio_slash(f"/cio ack {pid}")
            if not dry_run:
                send_cio_message(chat_id, reply)
            out.update({"handled": True, "kind": "ack", "plan_id": pid})
            return out

    # free-text converse
    if not rate_limit_ok(chat_id, path=rate_path):
        if not dry_run:
            send_cio_message(chat_id, "Rate limit: too many converse wakes this hour. Try /cio status.")
        out["reason"] = "rate_limited"
        out["handled"] = True
        return out

    # attach ids from reply_to or text
    plan_id = goal_id = action_id = None
    reply_to = msg.get("reply_to_message") or {}
    if reply_to:
        plan_id = plan_id_for_reply_message(reply_to.get("message_id"), path=msg_map_path)
        footer = parse_reply_footer(reply_to.get("text") or "")
        plan_id = plan_id or footer.get("plan_id")
        goal_id = footer.get("goal_id")
        action_id = footer.get("action_id")
    parsed = parse_ids_from_text(text)
    plan_id = plan_id or parsed.get("plan_id")
    goal_id = goal_id or parsed.get("goal_id")
    action_id = action_id or parsed.get("action_id")

    payload = {
        "text": text[:4000],
        "chat_id": chat_id,
        "message_id": str(message_id),
        "reply_to_message_id": str(reply_to.get("message_id") or "") or None,
        "ts": _now(),
        "user_id": str(from_user.get("id") or ""),
        "username": from_user.get("username") or from_user.get("first_name") or "",
        "plan_id": plan_id,
        "goal_id": goal_id,
        "action_id": action_id,
        "authority": "READ_ONLY_ADVISORY",
    }

    event_id = None if dry_run else emit_operator_message(payload)
    wake_id = None if dry_run else enqueue_operator_wake(
        chat_id=chat_id,
        message_id=str(message_id),
        text=text,
        plan_id=plan_id,
        goal_id=goal_id,
        action_id=action_id,
        event_id=event_id,
        target_agent="alex",
    )
    if not dry_run:
        mark_wake_rate(chat_id, path=rate_path)

    ctx = assemble_context(text, plan_id=plan_id, action_id=action_id, goal_id=goal_id)
    advisory = build_template_advisory(text, ctx)
    new_plan_id = plan_id
    if not dry_run:
        new_plan_id = ensure_converse_plan(
            advisory, plan_id=plan_id, symbols=ctx.get("symbols") or [], text=text,
        )
    reply = format_structured_reply(
        summary=advisory["summary"],
        evidence_refs=advisory.get("evidence_refs"),
        options=advisory.get("options"),
        recommendation=advisory.get("recommendation") or "",
        risks=advisory.get("risks"),
        plan_id=new_plan_id,
        goal_id=goal_id,
        revisit_at=advisory.get("revisit_at"),
        llm_deferred=bool(advisory.get("llm_deferred")),
        deep_links=advisory.get("deep_links"),
    )

    sent_mid = None
    if not dry_run:
        sent = send_cio_message(chat_id, reply)
        sent_mid = sent.get("message_id")
        if sent_mid and new_plan_id:
            record_plan_message(new_plan_id, sent_mid, chat_id, path=msg_map_path)

    out.update({
        "handled": True,
        "kind": "converse",
        "event_id": event_id,
        "wake_job_id": wake_id,
        "plan_id": new_plan_id,
        "attached_plan_id": plan_id,
        "telegram_out_message_id": sent_mid,
        "reply_preview": reply[:240],
        "llm_deferred": True,
    })
    return out
