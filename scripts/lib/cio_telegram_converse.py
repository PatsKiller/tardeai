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
    """Command Center origin for deep links (no trailing slash).

    Prefer explicit COMMAND_CENTER_BASE_URL / TRADEAI_CC_BASE_URL, else the same
    Tailscale public base used by all Telegram notifications
    (https://{TAILSCALE_HOSTNAME} via notification_url_builder). Never default
    to LAN-only 192.168.50.16 — phones on the tailnet cannot open those.
    """
    raw = (
        _env("COMMAND_CENTER_BASE_URL")
        or _env("TRADEAI_CC_BASE_URL")
        or _env("CC_BASE_URL")
        or _env("TRADEAI_PUBLIC_CC_URL")
        or _env("NOTIFICATION_PUBLIC_BASE_URL")
    )
    if not raw:
        try:
            from scripts.notification_url_builder import get_public_base_url
            raw = get_public_base_url()
        except Exception:
            try:
                from notification_url_builder import get_public_base_url  # type: ignore
                raw = get_public_base_url()
            except Exception:
                host = (
                    _env("TAILSCALE_HOSTNAME")
                    or "ms01-openclaw.tail163d14.ts.net"
                )
                raw = f"https://{host}"
    return str(raw).rstrip("/")


def active_thesis_version() -> Optional[str]:
    """Current desk thesis pin (desk@vN) or None. Fail-soft."""
    try:
        from scripts.lib.cio_theses import safe_current_pin
        return safe_current_pin("desk")
    except Exception:
        try:
            from lib.cio_theses import safe_current_pin  # type: ignore
            return safe_current_pin("desk")
        except Exception:
            return None


def build_cc_deep_links(
    *,
    situation_type: str = "",
    plan_id: Optional[str] = None,
    goal_id: Optional[str] = None,
    action_id: Optional[str] = None,
    symbols: Optional[list[str]] = None,
    extra: Optional[list[str]] = None,
) -> list[str]:
    """Relative CC paths for a plan/situation (joined with cc_base in formatter)."""
    paths: list[str] = []
    # Situation catalog defaults
    try:
        import yaml
        cfg_path = PROJECT_ROOT / "config" / "cio_situations.yaml"
        if cfg_path.exists() and situation_type:
            cfg = yaml.safe_load(cfg_path.read_text()) or {}
            for p in (cfg.get("cc_deep_links") or {}).get(situation_type) or []:
                if p and p not in paths:
                    paths.append(str(p))
    except Exception:
        pass
    # Always include CIO + advisory desks
    for p in ("/v3/cio", "/v3/advisory"):
        if p not in paths:
            paths.append(p)
    # Plan / goal query hooks (frontends that read ?plan= / ?goal=)
    if plan_id:
        q = f"/v3/cio?plan={plan_id}"
        if q not in paths:
            paths.insert(0, q)
    if goal_id:
        g = f"/v3/cio?goal={goal_id}"
        if g not in paths:
            paths.append(g)
    if action_id:
        a = f"/v3/cio?action={action_id}"
        if a not in paths:
            paths.append(a)
    if symbols:
        sym = str(symbols[0]).upper()
        if sym and len(sym) <= 8:
            w = f"/v3/portfolio?symbol={sym}"
            if w not in paths:
                paths.append(w)
    for p in extra or []:
        if p and p not in paths:
            paths.append(str(p))
    # Cap length for Telegram
    return paths[:6]


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
    channel: str = "telegram",
) -> None:
    mid = str(telegram_message_id)
    row: dict[str, Any] = {
        "plan_id": plan_id,
        "message_id": mid,
        "chat_id": str(chat_id),
        "channel": channel,
        "ts": _now(),
    }
    # back-compat key for Telegram reply lookup
    if channel == "telegram":
        row["telegram_message_id"] = mid
    else:
        row["outbound_message_id"] = mid
    _append_jsonl(path, row)


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
            if (
                str(row.get("telegram_message_id") or "") == rid
                or str(row.get("message_id") or "") == rid
                or str(row.get("outbound_message_id") or "") == rid
            ):
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
    action_id: Optional[str] = None,
    revisit_at: Optional[str] = None,
    thesis_version: Optional[str] = None,
    situation_type: Optional[str] = None,
    llm_deferred: bool = False,
    deep_links: Optional[list[str]] = None,
    symbols: Optional[list[str]] = None,
) -> str:
    """Structured CIO reply: summary/options/rec/risks + thesis pin + CC deep links.

    Thesis pin defaults to active desk@vN when not passed.
    Deep links: absolute URLs when cc_base() is set; always show paths as fallback.
    """
    # Resolve thesis pin (P3)
    pin = thesis_version
    if not pin:
        pin = active_thesis_version()

    # Resolve deep links (P6)
    links = list(deep_links or [])
    if not links or plan_id or goal_id or situation_type:
        auto = build_cc_deep_links(
            situation_type=situation_type or "",
            plan_id=plan_id,
            goal_id=goal_id,
            action_id=action_id,
            symbols=symbols,
            extra=deep_links,
        )
        # prefer auto order (plan-first) then extras
        links = auto

    def _clean(s: str) -> str:
        """Strip internal deferred markers; round long floats for readability."""
        t = (s or "").strip()
        for noise in (
            " [LLM deferred — deterministic view only]",
            " (LLM deferred — deterministic view only)",
            "[LLM deferred — deterministic view only]",
            "(LLM deferred — deterministic view only)",
        ):
            t = t.replace(noise, "")
        # soften long floats like 182.50959999999998
        import re as _re
        def _rnd(m):
            try:
                return f"{float(m.group(0)):.2f}"
            except Exception:
                return m.group(0)
        t = _re.sub(r"\b\d+\.\d{3,}\b", _rnd, t)
        return t.strip()

    lines: list[str] = []
    # Visual hierarchy: badge line
    mode = "📋 template" if llm_deferred else "✨ Alex (LLM)"
    sit_short = (situation_type or "").replace("_", " ")
    header = f"🧠 CIO · READ_ONLY · {mode}"
    if pin:
        header += f" · `{pin}`"
    lines.append(header)
    if situation_type:
        sym_s = ",".join(symbols or [])[:40]
        title = f"📍 {sit_short}"
        if sym_s:
            title += f" · {sym_s}"
        lines.append(title)
    lines.append("────────────────")
    # Thesis drives the rec — surface stance, not just a footer pin
    thesis_stance = ""
    thesis_summary = ""
    try:
        from scripts.lib.cio_theses import CIOThesisStore
        rec = CIOThesisStore().get_by_pin(str(pin)) if pin else None
        if rec:
            thesis_stance = str(rec.get("stance") or "")
            thesis_summary = str(rec.get("summary") or "")[:160]
    except Exception:
        try:
            from lib.cio_theses import CIOThesisStore  # type: ignore
            rec = CIOThesisStore().get_by_pin(str(pin)) if pin else None
            if rec:
                thesis_stance = str(rec.get("stance") or "")
                thesis_summary = str(rec.get("summary") or "")[:160]
        except Exception:
            pass
    if pin and (thesis_stance or thesis_summary):
        lines.append(f"🎯 *Desk thesis* `{pin}`" + (f" · {thesis_stance}" if thesis_stance else ""))
        if thesis_summary:
            lines.append(_clean(thesis_summary))
        lines.append("")
    # Material long-form: pull Thesis alignment / Multi-domain blocks out of summary
    what_body = _clean(summary) or "(no summary)"
    thesis_align_line = ""
    multi_dom_line = ""
    if "Thesis alignment" in what_body:
        parts = what_body.split("Thesis alignment", 1)
        what_body = parts[0].strip()
        rest = parts[1]
        if "Multi-domain" in rest:
            ta_part, md_part = rest.split("Multi-domain", 1)
            thesis_align_line = ("Thesis alignment" + ta_part).strip(" :\n")
            multi_dom_line = ("Multi-domain" + md_part).strip(" :\n")
        else:
            thesis_align_line = ("Thesis alignment" + rest).strip(" :\n")
    elif "Multi-domain" in what_body:
        parts = what_body.split("Multi-domain", 1)
        what_body = parts[0].strip()
        multi_dom_line = ("Multi-domain" + parts[1]).strip(" :\n")
    lines.append("📌 *What*")
    lines.append(what_body or "(no summary)")
    if thesis_align_line:
        lines.append("")
        lines.append("🧭 *Thesis alignment*")
        body = thesis_align_line
        for prefix in ("Thesis alignment", "desk@v",):
            pass
        # Drop leading "Thesis alignment:" / "(desk@vN):" leftovers
        body = body.replace("Thesis alignment", "", 1)
        body = body.lstrip(" :\n(")
        if body.startswith("desk@"):
            # strip "desk@vN):" or "desk@vN:"
            if "):" in body[:20]:
                body = body.split("):", 1)[-1]
            elif ":" in body[:16]:
                body = body.split(":", 1)[-1]
        lines.append(_clean(body))
    if multi_dom_line:
        lines.append("")
        lines.append("🧩 *Multi-domain*")
        lines.append(_clean(multi_dom_line.replace("Multi-domain", "").lstrip(" :")))
    if options:
        lines.append("")
        lines.append("⚖️ *Options*")

        def _opt_clause(s: str, limit: int = 180) -> str:
            """Full clause up to limit; break at word boundary, no mid-word cut."""
            t = _clean(s)
            if len(t) <= limit:
                return t
            cut = t[: limit - 1]
            if " " in cut:
                cut = cut.rsplit(" ", 1)[0]
            return cut.rstrip(" ,;:") + "…"

        for i, o in enumerate(options[:5], 1):
            lab = _clean(str(o.get("label") or o.get("id") or "?"))
            pros = (o.get("pros") or "").strip()
            cons = (o.get("cons") or "").strip()
            # Multi-line so pros/cons are complete (was [:60] inline — awkward truncations)
            lines.append(f"{i}. {lab}")
            if pros:
                lines.append(f"   + {_opt_clause(pros)}")
            if cons:
                lines.append(f"   − {_opt_clause(cons)}")
    if recommendation:
        lines.append("")
        lines.append("✅ *Recommendation*")
        lines.append(_clean(recommendation))
    if risks:
        lines.append("")
        lines.append("⚠️ *Risks*")
        for rk in risks[:4]:
            lines.append(f"• {_clean(str(rk))}")
    # Evidence: compact, last
    if evidence_refs:
        lines.append("")
        lines.append("📎 *Evidence* (Data Broker)")
        for r in evidence_refs[:4]:
            dom = r.get("domain") or "?"
            as_of = str(r.get("as_of") or "")[:10] or "n/a"
            lines.append(f"• {dom} · {as_of}")
    lines.append("────────────────")
    meta = []
    if plan_id:
        meta.append(f"`{plan_id}`")
    if goal_id:
        meta.append(f"goal `{goal_id}`")
    if pin:
        meta.append(f"thesis `{pin}`")
    if revisit_at:
        meta.append(f"revisit {str(revisit_at)[:10]}")
    if meta:
        lines.append(" · ".join(meta))
    base = cc_base()
    if links:
        # One primary deep link + optional second
        primary = links[0]
        p = str(primary)
        if not (p.startswith("http://") or p.startswith("https://")):
            p = f"{base}{p}" if p.startswith("/") else f"{base}/{p}"
        lines.append(f"🔗 {p}")
        if len(links) > 1 and base:
            more = []
            for path in links[1:3]:
                path = str(path)
                if path.startswith("http"):
                    more.append(path.split("/")[-1] or path)
                else:
                    more.append(path)
            if more:
                lines.append("also: " + ", ".join(more))
    lines.append("")
    lines.append(f"Reply to continue · `/cio ack {plan_id or '<id>'}` or `ack`")
    if pin:
        lines.append(f"Thesis: `/cio thesis`")
    lines.append("No orders/stops from chat · READ_ONLY_ADVISORY")
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
        if sub == "traces":
            n = 10
            llm_f = None
            plan_f = None
            for i, tok in enumerate(parts[1:], start=1):
                if tok.isdigit():
                    n = max(1, min(int(tok), 50))
                elif tok.startswith("llm="):
                    llm_f = tok.split("=", 1)[1]
                elif tok.startswith("plan="):
                    plan_f = tok.split("=", 1)[1]
            if hasattr(cc, "cmd_traces"):
                return cc.cmd_traces(n=n, llm=llm_f, plan_id=plan_f)
            try:
                from scripts.lib.cio_wake_traces import cmd_traces_text
                return cmd_traces_text(n, llm=llm_f, plan_id=plan_f)
            except Exception as e:
                return f"traces unavailable: {e}"
        if sub == "thesis":
            import sys
            old = sys.argv[:]
            try:
                sys.argv = ["cio_commands.py", "thesis"] + parts[1:]
                if parts[1:2] and parts[1].lower() in ("history", "list", "versions"):
                    return cc.cmd_thesis_history() if hasattr(cc, "cmd_thesis_history") else "thesis history unavailable"
                return cc.cmd_thesis() if hasattr(cc, "cmd_thesis") else "thesis unavailable"
            finally:
                sys.argv = old
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
    """Process one Telegram message dict. Fail-closed for non-allowlisted.

    Thin adapter over shared multi-channel converse core (P4).
    """
    from scripts.lib.cio_converse_core import process_operator_message

    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    message_id = msg.get("message_id")
    text = (msg.get("text") or "").strip()
    from_user = msg.get("from") or {}
    reply_to = msg.get("reply_to_message") or {}

    def _send(cid: str, body: str, reply_to: Optional[str] = None) -> dict[str, Any]:
        return send_cio_message(cid, body, reply_to=reply_to)

    return process_operator_message(
        channel="telegram",
        chat_id=chat_id,
        message_id=message_id if message_id is not None else "",
        text=text,
        reply_to_message_id=str(reply_to.get("message_id") or "") or None,
        reply_to_text=reply_to.get("text") or None,
        user_id=str(from_user.get("id") or ""),
        username=from_user.get("username") or from_user.get("first_name") or "",
        allowlist=allowlist_chat_ids(),
        converse_on=converse_enabled(),
        dedup_path=dedup_path,
        msg_map_path=msg_map_path,
        rate_path=rate_path,
        dry_run=dry_run,
        send_fn=None if dry_run else _send,
        wakes_limit=wakes_per_hour(),
        actor_id="cio_telegram_bot",
    )
