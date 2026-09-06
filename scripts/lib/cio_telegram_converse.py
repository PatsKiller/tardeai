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
DECISION_ID_RE = re.compile(
    r"(?:Decision|decision_id)\s*[:=]\s*`?(dec_[A-Za-z0-9._:-]{8,80})`?"
    r"|\b(dec_[A-Za-z0-9._:-]{8,80})\b",
    re.I,
)
SYMBOL_RE = re.compile(r"\b([A-Z]{1,5})\b")
ACK_RE = re.compile(r"^\s*(ack|acknowledge)\s*(plan_[a-z0-9_\-]+|plan-[a-z0-9_\-]+)?\s*$", re.I)

REENTRY_QUERY_RE = re.compile(
    r"(?is)\b("
    r"re[\s\-]?(?:entr(?:y|ies)|enter(?:ing|ed)?)|"  # reentry, re-enter, reenter…
    r"rentr(?:y|ies|e)|"                             # typo: rentry
    r"ready\s+(?:to\s+)?(?:review|buy|purchase)|"
    r"(?:buy|purchase).{0,40}ready|"
    r"ready.{0,40}(?:buy|purchase)|"
    r"can\s+i\s+(?:re[\s\-]?(?:enter|entry)|buy\s+back)|"
    r"what\s+can\s+i\s+re[\s\-]?(?:enter|entry)"
    r")\b"
)

REENTRY_LEVELS_QUERY_RE = re.compile(
    r"(?is)\b("
    r"support|resistance|s/?r\b|50[\s\-]?day|sma\s*50|sma50|"
    r"sma\s*20|sma20|200[\s\-]?day|levels?|stop"
    r")\b"
)




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
    # Phase 1: never fall back to general TELEGRAM_CHAT_ID (Maria channel).
    raw = _env("TELEGRAM_CIO_CHAT_IDS") or _env("TELEGRAM_CIO_ALLOWLIST")
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
    def _reject_lan(url: str) -> bool:
        u = (url or "").lower()
        return any(
            bad in u
            for bad in (
                "192.168.",
                "127.0.0.1",
                "localhost",
                "0.0.0.0",
                "10.0.",
            )
        )

    candidates = [
        _env("COMMAND_CENTER_BASE_URL"),
        _env("TRADEAI_CC_BASE_URL"),
        _env("CC_BASE_URL"),
        _env("TRADEAI_PUBLIC_CC_URL"),
        _env("NOTIFICATION_PUBLIC_BASE_URL"),
    ]
    raw = ""
    for c in candidates:
        if c and not _reject_lan(c):
            raw = c
            break
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
    if _reject_lan(str(raw)):
        host = _env("TAILSCALE_HOSTNAME") or "ms01-openclaw.tail163d14.ts.net"
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
    out = {"plan_id": None, "action_id": None, "goal_id": None, "decision_id": None}
    for m in FOOTER_RE.finditer(text or ""):
        if m.group(1):
            out["plan_id"] = m.group(1)
        if m.group(2):
            out["action_id"] = m.group(2)
        if m.group(3):
            out["goal_id"] = m.group(3)
    # re: PLAN-… patterns and bare `plan_…` footers
    m = re.search(r"re:\s*(plan_[a-z0-9_\-]+)", text or "", re.I)
    if m:
        out["plan_id"] = m.group(1)
    if not out["plan_id"]:
        m = re.search(r"`?(plan_[a-z0-9_\-]{6,})`?", text or "", re.I)
        if m:
            out["plan_id"] = m.group(1)
    m = re.search(r"\bgoal\s+(goal_[a-z0-9_\-]+)", text or "", re.I)
    if m:
        out["goal_id"] = m.group(1)
    dm = DECISION_ID_RE.search(text or "")
    if dm:
        out["decision_id"] = dm.group(1) or dm.group(2)
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


def load_decision_thread_context(decision_id: str) -> dict[str, Any]:
    """Live catalog + latest operator disposition for a decision-card thread."""
    did = str(decision_id or "").strip()
    ctx: dict[str, Any] = {
        "decision_id": did,
        "symbol": "",
        "stance": "",
        "disposition": None,
        "why_now": "",
        "delta_usd": None,
        "authority": "READ_ONLY_ADVISORY",
    }
    if not did:
        return ctx
    try:
        from scripts.api_v3_cio import load_known_decision_catalog, get_decision_dispositions
        known = (load_known_decision_catalog() or {}).get(did) or {}
        ctx["symbol"] = str(known.get("symbol") or "")
        ctx["stance"] = str(known.get("action") or known.get("stance") or "")
        disp = ((get_decision_dispositions() or {}).get("dispositions") or {}).get(did)
        if isinstance(disp, dict):
            ctx["disposition"] = str(disp.get("disposition") or "")
            ctx["operator_disposition"] = ctx["disposition"]
            ctx["disposition_at"] = disp.get("occurred_at")
            ctx["operator_note"] = str(disp.get("note") or "")
            ctx["decision_input_digest"] = str(disp.get("decision_input_digest") or "")
            ctx["decision_evidence_digest"] = str(disp.get("decision_evidence_digest") or "")
            if str(ctx["disposition"] or "").upper() == "REJECT":
                ctx["operator_challenge_status"] = "OPEN"
                ctx["challenge_review"] = "DATA_UNAVAILABLE"
            else:
                ctx["operator_challenge_status"] = "none"
    except Exception as exc:
        ctx["catalog_error"] = f"{type(exc).__name__}"
    # Prefer capital-plan row facts when the catalog is thin
    try:
        from scripts.lib.cio_office_state import fetch_capital_plan
        plan = fetch_capital_plan()
        for row in plan.get("position_decisions") or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("decision_id") or "") != did:
                continue
            ctx["symbol"] = ctx["symbol"] or str(row.get("symbol") or "")
            ctx["stance"] = ctx["stance"] or str(row.get("stance") or row.get("stance_code") or "")
            ctx["why_now"] = str(row.get("why_now") or "")
            ctx["delta_usd"] = row.get("recommended_delta_usd")
            ctx["weight_pct"] = row.get("current_weight_pct") or row.get("weight_pct")
            ctx["action_label"] = row.get("action_label")
            ctx["act_now"] = row.get("act_now")
            break
    except Exception:
        pass
    return ctx


_REJECT_RE = re.compile(r"\breject(?:ed|ing)?\b", re.I)


def _looks_like_reject(text: str) -> bool:
    return bool(_REJECT_RE.search(text or ""))


def persist_operator_challenge(decision_id: str, note: str, disposition: str) -> dict[str, Any]:
    """Persist the exact operator free-text note as a governed challenge.

    Prefers append_case_event when the case store exposes it; else append_case
    with case_id_for (same decision_id); else record_disposition. Never rewrites
    the note into a canned staple phrase.
    """
    did = str(decision_id or "").strip()
    note_s = str(note or "")
    disp = str(disposition or "").strip()
    challenge = "OPEN" if disp.upper() == "REJECT" else "none"
    out: dict[str, Any] = {
        "ok": False,
        "decision_id": did,
        "note": note_s,
        "disposition": disp,
        "operator_challenge_status": challenge,
        "challenge_review": "DATA_UNAVAILABLE" if challenge == "OPEN" else None,
        "via": None,
    }
    if not did:
        out["reason"] = "missing_decision_id"
        return out
    payload = {
        "decision_id": did,
        "status": "OPERATOR_CHALLENGE" if challenge == "OPEN" else "OPERATOR_NOTE",
        "operator_challenge_status": challenge,
        "challenge_review": "DATA_UNAVAILABLE" if challenge == "OPEN" else None,
        "operator_disposition": {
            "disposition": disp or None,
            "note": note_s,
            "source": "persist_operator_challenge",
        },
    }
    try:
        from scripts.lib.cio_production_case import append_case_event
        rec = append_case_event(did, payload)
        out["ok"] = True
        out["via"] = "append_case_event"
        out["record"] = rec
        return out
    except Exception:
        pass
    try:
        from scripts.lib.cio_production_case import append_case, case_id_for
        rec = append_case({
            "case_id": case_id_for(did, "", ""),
            **payload,
        })
        out["ok"] = True
        out["via"] = "append_case"
        out["record"] = rec
        return out
    except Exception:
        pass
    try:
        from scripts.lib.cio_production_case import record_disposition
        rec = record_disposition(did, payload["operator_disposition"])
        out["ok"] = True
        out["via"] = "record_disposition"
        out["record"] = rec
        return out
    except Exception as exc:
        out["reason"] = f"{type(exc).__name__}"
        return out


def open_thesis_challenge(decision: dict[str, Any], note: str) -> dict[str, Any]:
    """Open a REJECT challenge. Desks are not called here — review is honest."""
    d = dict(decision or {})
    did = str(d.get("decision_id") or "").strip()
    d["operator_challenge_status"] = "OPEN"
    d["challenge_review"] = "DATA_UNAVAILABLE"
    d["operator_disposition"] = d.get("operator_disposition") or "REJECT"
    persisted = persist_operator_challenge(did, note, "REJECT")
    return {
        "ok": bool(persisted.get("ok")),
        "decision_id": did,
        "operator_challenge_status": "OPEN",
        "challenge_review": "DATA_UNAVAILABLE",
        "note": str(note or ""),
        "persist": persisted,
        "decision": d,
    }


def format_decision_thread_reply(
    *,
    decision_id: str,
    operator_text: str,
    thread: Optional[dict[str, Any]] = None,
) -> str:
    """CIO-speak reply that keeps the same decision_id. Not a new S0 plan.

    Uses the actual operator free-text note. Does not invent a staple phrase.
    """
    thread = thread or load_decision_thread_context(decision_id)
    did = thread.get("decision_id") or decision_id
    sym = thread.get("symbol") or "this name"
    stance = (
        thread.get("standing_recommendation")
        or thread.get("stance")
        or thread.get("stance_code")
        or "the standing call"
    )
    stance = str(stance).upper()
    disp = str(
        thread.get("disposition")
        or thread.get("operator_disposition")
        or ""
    ).upper() or "NONE"
    why = (thread.get("why_now") or "").strip()
    label = thread.get("action_label") or ""
    note = (operator_text or "").strip()
    if not note:
        note = str(thread.get("operator_note") or "").strip()
    note_show = note[:400] if note else "(no note)"
    act_now = thread.get("act_now")
    if disp != "REJECT" and _looks_like_reject(note):
        disp = "REJECT"
    lines = [
        "Alex · CIO NOW",
        "",
        "THREAD",
        f"Same decision {did} · {sym} · standing {stance}.",
        f"Latest disposition on record: {disp}.",
        "",
        "I HEARD YOU",
        note_show,
        "",
        "WHAT THAT MEANS",
    ]
    if disp == "REJECT":
        lines.append(
            f"REJECT is recorded. I will not keep asking you to take the {stance} "
            f"on {sym}. The book fact is unchanged: {why or 'see capital plan'}."
        )
        if label:
            lines.append(f"Freshness={label}; ACT_NOW={act_now}.")
        if note:
            lines.append(f"Your counter-thesis is now on the case: {note[:400]}")
        else:
            lines.append("Your counter-thesis is now on the case.")
        lines.append("It does not clear a concentration fire by itself.")
        lines.append("operator_challenge_status=OPEN")
        lines.append("challenge_review=DATA_UNAVAILABLE")
    else:
        lines.append(
            f"Standing call remains {stance} on {sym}. "
            f"{why or 'See capital plan.'}"
        )
    lines.extend([
        "",
        "WHAT I WILL NOT DO",
        "Place, cancel, or change any order or stop. Invent ACT_NOW. Open a new S0 chat plan.",
        "",
        "NEXT",
        "TRIM/HOLD stays the office call until weight or thesis changes. "
        "Reply here to add evidence; I will stay on this decision_id.",
        "",
        f"Decision: {did}",
    ])
    return "\n".join(lines)


def record_decision_thread_note(decision_id: str, note: str, *, disposition: str = "") -> None:
    """Append the exact operator free-text onto the production case. Fail-soft."""
    text = str(note or "")
    disp = str(disposition or "")
    if not disp and _looks_like_reject(text):
        disp = "REJECT"
    try:
        if str(disp).upper() == "REJECT":
            open_thesis_challenge({"decision_id": decision_id}, text)
        else:
            persist_operator_challenge(decision_id, text, disp)
    except Exception:
        pass


# ── Structured reply formatter ──────────────────────────────────────────────


def _age_suffix(raw: str) -> str:
    """' · 18d' — the operator should see evidence age without being told."""
    try:
        from datetime import datetime, timezone
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if not d.tzinfo:
            d = d.replace(tzinfo=timezone.utc)
        n = (datetime.now(timezone.utc) - d).days
        return f" · {n}d" if n >= 2 else ""
    except Exception:
        return ""


def _trim(text: str, limit: int) -> str:
    """Cut at a sentence, else a word — never mid-token.

    `summary[:160]` produced "…escalate material drift, concentration, and deep
    drawdowns to the" in a delivered advisory on 2026-08-30. A hard slice makes
    the desk look broken even when the content is right.
    """
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    window = t[:limit]
    for end in (". ", "; ", " — ", ", "):
        cut = window.rfind(end)
        if cut >= int(limit * 0.5):
            return window[:cut + 1].strip().rstrip(",;")
    cut = window.rfind(" ")
    return (window[:cut] if cut >= int(limit * 0.5) else window).rstrip(" ,;") + "…"


# Detector output, not prose: "reasons=weight_42.1pct; weight=42.1; loss_pct=None".
# It reached the operator verbatim in the *What* block on 2026-08-30.
_DEBUG_KV_RE = re.compile(
    r"^\s*(?:[a-z_]+=[^;\n]*)(?:\s*;\s*[a-z_]+=[^;\n]*)+\s*$", re.I)


def _readable_reasons(text: str) -> str:
    """Turn a k=v debug string into a sentence; leave real prose alone."""
    t = (text or "").strip()
    if not _DEBUG_KV_RE.match(t):
        return t
    parts = []
    for chunk in t.split(";"):
        if "=" not in chunk:
            continue
        k, _, v = chunk.partition("=")
        k = k.strip().replace("_", " "); v = v.strip()
        if not v or v.lower() in ("none", "null", "nan", ""):
            continue                      # "loss_pct=None" says nothing
        parts.append(f"{k} {v}")
    return ("Detector flags: " + ", ".join(parts) + ".") if parts else ""


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
    thesis_alignment: Optional[str] = None,
    multi_domain_summary: Optional[str] = None,
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
            thesis_summary = _trim(str(rec.get("summary") or ""), 160)
    except Exception:
        try:
            from lib.cio_theses import CIOThesisStore  # type: ignore
            rec = CIOThesisStore().get_by_pin(str(pin)) if pin else None
            if rec:
                thesis_stance = str(rec.get("stance") or "")
                thesis_summary = _trim(str(rec.get("summary") or ""), 160)
        except Exception:
            pass
    if pin and (thesis_stance or thesis_summary):
        lines.append(f"🎯 *Desk thesis* `{pin}`" + (f" · {thesis_stance}" if thesis_stance else ""))
        if thesis_summary:
            lines.append(_clean(thesis_summary))
        lines.append("")
    # Prefer structured fields; fall back to embedded summary markers
    what_body = _clean(summary) or "(no summary)"
    thesis_align_line = _clean(thesis_alignment or "")
    multi_dom_line = _clean(multi_domain_summary or "")
    # Always lift an embedded block out of *What*, even when the structured
    # field is populated. The old condition (`not thesis_align_line and ...`)
    # stripped it ONLY when the field was empty, so a plan carrying both
    # rendered the identical paragraph twice — once in *What*, once under 🧭.
    # Observed verbatim in a delivered advisory on 2026-08-30.
    if "Thesis alignment" in what_body:
        parts = what_body.split("Thesis alignment", 1)
        what_body = parts[0].strip()
        rest = parts[1]
        if "Multi-domain" in rest:
            ta_part, md_part = rest.split("Multi-domain", 1)
            thesis_align_line = thesis_align_line or ("Thesis alignment" + ta_part).strip(" :\n")
            multi_dom_line = multi_dom_line or ("Multi-domain" + md_part).strip(" :\n")
        else:
            thesis_align_line = thesis_align_line or ("Thesis alignment" + rest).strip(" :\n")
    elif "Multi-domain" in what_body:
        parts = what_body.split("Multi-domain", 1)
        what_body = parts[0].strip()
        multi_dom_line = multi_dom_line or ("Multi-domain" + parts[1]).strip(" :\n")
    what_body = _readable_reasons(what_body)
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

        def _opt_clause(s: str, limit: int = 240) -> str:
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
            raw = str(r.get("as_of") or "")
            as_of = raw[:10] or "n/a"
            # Age, not just a date. "2026-08-11" reads as fine at a glance;
            # "2026-08-11 · 18d" does not, and the operator is entitled to
            # judge how old the evidence under an advisory actually is.
            lines.append(f"• {dom} · {as_of}{_age_suffix(raw)}")
    lines.append("────────────────")
    meta = []
    if plan_id:
        meta.append(f"`{plan_id}`")
    if goal_id:
        meta.append(f"goal `{goal_id}`")
    if pin:
        meta.append(f"thesis `{pin}`")
    if revisit_at:
        # A revisit date in the past is the norm, not the exception (the
        # horizon is 24h), so it is marked rather than hidden: printing it bare
        # invited the reading that this plan was reviewed on that date.
        _rev = str(revisit_at)[:10]
        _overdue = _age_suffix(str(revisit_at))
        meta.append(f"revisit {_rev}" + (f" (overdue{_overdue})" if _overdue else ""))
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

    # Same-brain ticker cognition as CIO worker / envelope (read-only).
    if symbols:
        try:
            from scripts.lib.cio_persistent_cognition import (
                cognition_for_symbol,
                resolve_cognition_root,
                telegram_fields,
            )

            root = resolve_cognition_root()
            rows = [cognition_for_symbol(root, s) for s in symbols[:8]]
            ctx["ticker_cognition"] = [telegram_fields(r) for r in rows]
            ctx["security_guids"] = [r.get("security_guid") for r in rows]
            ctx["evidence_refs"].append({
                "domain": "persistent_ticker_cognition",
                "as_of": rows[0].get("freshness") if rows else "DATA_UNAVAILABLE",
                "fields_used": ["security_guid", "curation_id", "curation_version", "symbol_thesis_id"],
            })
        except Exception as exc:
            ctx["data_notes"].append(f"cognition:DATA_UNAVAILABLE:{type(exc).__name__}")

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
        if sub == "research":
            # /cio research <plan_id>  — operator-forced Hermes enqueue (bypass TTL)
            if len(parts) < 2:
                return (
                    "Usage: `/cio research <plan_id>`\n"
                    "Forces a Hermes research request (operator_forced; bypasses TTL). "
                    "Confirm accepted; full card after result if material. READ_ONLY."
                )
            return cmd_research(parts[1])
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


def cmd_research(plan_id: str) -> str:
    """Operator-forced Hermes research enqueue for a plan (READ_ONLY)."""
    from scripts.lib.cio_plans import CIOPlanStore
    pid = (plan_id or "").strip()
    p = CIOPlanStore().get_plan(pid)
    if not p:
        return f"Plan not found: `{pid}`"
    try:
        try:
            from lib.hermes_research_loop import emit_research_for_plan
        except Exception:
            from scripts.lib.hermes_research_loop import emit_research_for_plan  # type: ignore
        rr = emit_research_for_plan(
            p,
            reason="operator:/cio research",
            operator_forced=True,
            force_refresh=True,
            actor_id="cio_telegram_operator",
        )
        if not rr.get("ok"):
            return (
                f"Research enqueue failed for `{pid}`: "
                f"{rr.get('error') or rr.get('reason') or 'unknown'}. READ_ONLY."
            )
        rid = rr.get("research_id") or "—"
        reason = rr.get("reason") or "—"
        status = rr.get("status") or "—"
        lines = [
            f"🔬 *Research accepted* · plan `{pid}`",
            f"research_id: `{rid}`",
            f"reason: `{reason}` · status: `{status}`",
        ]
        if rr.get("reused"):
            lines.append("TTL reuse — existing result attached; no new Hermes run.")
        elif rr.get("deduped"):
            lines.append("In-flight de-dupe — joined existing job (no double queue).")
        else:
            lines.append("Queued for Hermes worker. Full card after result if material changes.")
            lines.append("Worker: `PYTHONPATH=scripts python3 -m scripts.hermes_cio_worker --once`")
        lines.append("No orders/stops · READ_ONLY_ADVISORY")
        return "\n".join(lines)
    except Exception as e:
        return f"Research enqueue error: {type(e).__name__}: {e}"


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
        thesis_version=p.get("thesis_version"),
        situation_type=p.get("situation_type"),
        llm_deferred=p.get("narrative_source") == "template",
        deep_links=p.get("cc_deep_links"),
        symbols=p.get("symbols"),
        thesis_alignment=p.get("thesis_alignment"),
        multi_domain_summary=p.get("multi_domain_summary"),
    )


# ── Egress ──────────────────────────────────────────────────────────────────


def send_cio_message(chat_id: str, text: str, *, reply_to: Optional[str] = None) -> dict[str, Any]:
    """CIO converse egress via approved cio_telegram_transport (no raw Bot API).

    chat_id/reply_to retained for call-site compatibility; transport fans out to
    the CIO allowlist after inbound allowlist gating.
    """
    _ = (chat_id, reply_to)
    try:
        from scripts.lib.cio_telegram_transport import send_cio_message as _transport_send
        res = _transport_send(
            text,
            kind="cio_converse",
            require_live_auth=False,
            force=False,
        )
        mids = res.get("message_ids") or []
        out: dict[str, Any] = {
            "ok": bool(res.get("delivered")),
            "message_id": mids[0] if mids else None,
            "raw": res,
        }
        if not out["ok"]:
            out["error"] = res.get("reason") or "send_failed"
        return out
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ── Main update processor ───────────────────────────────────────────────────


def _best_effort_tag_inbound(text: str, *, chat_id: str,
                             message_id: Any = None) -> None:
    """Resolve the question to issuer/subject GUIDs and store it. Never raises.

    Deterministic: ticker or company name, the latter resolved through the broker
    instrument feed that also supplies the CUSIP. No model runs here.
    """
    conn = None
    try:
        import os

        import psycopg2

        from scripts.lib.inbound_identity_tagger import persist, tag_inbound

        tag = tag_inbound(text)
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            dbname=os.environ.get("DB_NAME", "trade_ai"),
            user=os.environ.get("DB_USER", "trade_ai"),
            password=os.environ.get("DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD"),
        )
        persist(tag, conn=conn, question_text=text,
                chat_id=chat_id, message_id=message_id, channel="telegram")
    except Exception as exc:  # noqa: BLE001 — bookkeeping must not break the reply
        # No module logger here; stderr is what the systemd unit captures.
        try:
            import sys as _sys
            print(f"[inbound-tag] failed: {type(exc).__name__}: {exc}", file=_sys.stderr)
        except Exception:
            pass
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


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

    # Tag and persist the question against the identity spine. Until 2026-09-06
    # tagging was DISCOVERY-ONLY: research and news carried issuer_guid, the
    # inbound path carried nothing and stored nothing but the last update_id. So
    # "Alex, what's Walmart's support and resistance?" left no trace an agent
    # could later join to the research that would answer it.
    #
    # Allowlist-gated, because storing arbitrary inbound text is not something to
    # do by accident, and BEST-EFFORT: a tagging failure must never cost the
    # operator their answer. The reply is the product; the tag is bookkeeping.
    if text and chat_id in (allowlist_chat_ids() or set()):
        _best_effort_tag_inbound(text, chat_id=chat_id, message_id=message_id)

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

# ── Re-entry purchase desk answers (Trade-AI truth) ──────────────────────

def looks_like_reentry_purchase_query(text: str) -> bool:
    """True when operator asks which names are re-entry ready to buy/review."""
    t = (text or "").strip()
    if not t or len(t) > 500:
        return False
    # Slash commands are handled elsewhere
    if t.lower().startswith("/cio"):
        return False
    return bool(REENTRY_QUERY_RE.search(t))


def wants_reentry_levels(text: str) -> bool:
    """Operator asked for S/R, SMA50, stops, etc."""
    return bool(REENTRY_LEVELS_QUERY_RE.search(text or ""))


def _row_levels(r: dict[str, Any]) -> dict[str, Any]:
    """Extract desk levels — never invent; missing stays None."""
    resist = r.get("resistance") if isinstance(r.get("resistance"), dict) else {}
    return {
        "stop": r.get("stop"),
        "target": r.get("target"),
        "rsi": r.get("rsi"),
        "sma_20": r.get("sma_20"),
        "sma_50": r.get("sma_50"),
        "sma_200": r.get("sma_200"),
        "resistance_level": resist.get("level"),
        "resistance_state": resist.get("state"),
        "atr": r.get("atr"),
    }


def _fmt_levels_line(it: dict[str, Any]) -> str:
    bits: list[str] = []
    if it.get("stop") is not None:
        bits.append(f"stop {_fmt_money(it['stop'])}")
    if it.get("resistance_level") is not None:
        st = it.get("resistance_state") or ""
        bits.append(
            f"resist {_fmt_money(it['resistance_level'])}"
            + (f" ({st})" if st else "")
        )
    if it.get("sma_50") is not None:
        bits.append(f"SMA50 {_fmt_money(it['sma_50'])}")
    if it.get("sma_20") is not None:
        bits.append(f"SMA20 {_fmt_money(it['sma_20'])}")
    if it.get("sma_200") is not None:
        bits.append(f"SMA200 {_fmt_money(it['sma_200'])}")
    if it.get("rsi") is not None:
        try:
            bits.append(f"RSI {float(it['rsi']):.1f}")
        except (TypeError, ValueError):
            pass
    if it.get("target") is not None:
        bits.append(f"tgt {_fmt_money(it['target'])}")
    return " · ".join(bits)

def _reentry_desk_json_paths() -> list[Path]:
    """Candidate paths for reentry_decision_desk_latest.json (worktree + live)."""
    rel = Path("data") / "runtime" / "reentry_decision_desk_latest.json"
    out: list[Path] = [PROJECT_ROOT / rel]
    data_root = (_env("TRADEAI_DATA_ROOT") or "").strip()
    if data_root:
        out.append(Path(data_root) / "runtime" / "reentry_decision_desk_latest.json")
    src = (_env("TRADEAI_SRC") or "").strip()
    if src:
        out.append(Path(src) / rel)
    # Canonical live tree (release CURRENT often symlinks here)
    out.append(
        Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild") / rel
    )
    # Dedupe while preserving order
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq


def load_reentry_desk_rows() -> tuple[list[dict[str, Any]], Optional[str], Optional[Path]]:
    """Load desk rows from latest artifact. Returns (rows, computed_at, path)."""
    for path in _reentry_desk_json_paths():
        try:
            if not path.is_file():
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                continue
            rows = raw.get("rows") or raw.get("candidates") or []
            if isinstance(raw.get("data"), dict) and not rows:
                rows = raw["data"].get("rows") or []
            if not isinstance(rows, list):
                continue
            as_of = (
                raw.get("computed_at")
                or raw.get("generated_at")
                or raw.get("as_of")
            )
            return rows, (str(as_of) if as_of else None), path
        except Exception:
            continue
    return [], None, None


def _fmt_money(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if x >= 100:
        return f"${x:,.2f}"
    if x >= 1:
        return f"${x:.2f}"
    return f"${x:.4f}".rstrip("0").rstrip(".")


def format_reentry_purchase_reply(
    *,
    desk_rows: Optional[list[dict[str, Any]]] = None,
    computed_at: Optional[str] = None,
    near_limit: int = 8,
    include_levels: bool = True,
    operator_text: str = "",
) -> str:
    """Short actionable Telegram reply for re-entry readiness (READ_ONLY).

    Answers 'what's ready to buy?' with READY TO REVIEW names + zone —
    not the S0 template / thesis wall. Levels (stop/resist/SMA50) from desk only.
    """
    rows = desk_rows
    as_of = computed_at
    if rows is None:
        rows, as_of, _path = load_reentry_desk_rows()

    detail = include_levels or wants_reentry_levels(operator_text)

    ready: list[dict[str, Any]] = []
    near: list[dict[str, Any]] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        intel = r.get("intel") if isinstance(r.get("intel"), dict) else {}
        state = str(intel.get("state") or r.get("status") or "").strip()
        sym = str(r.get("symbol") or r.get("ticker") or "").upper()
        if not sym:
            continue
        item = {
            "symbol": sym,
            "state": state,
            "price": r.get("price"),
            "entry_low": r.get("entry_low"),
            "entry_high": r.get("entry_high"),
            "held": bool(r.get("held")),
            "action": (r.get("advisory") or {}).get("action")
            if isinstance(r.get("advisory"), dict)
            else None,
        }
        item.update(_row_levels(r))
        if state == "READY TO REVIEW":
            ready.append(item)
        elif state == "NEAR ENTRY":
            near.append(item)

    lines: list[str] = [
        "🎯 *Re-entry — purchase candidates*",
        "_Exited names · not current holdings · READ_ONLY_",
    ]
    if as_of:
        lines.append(f"as_of `{str(as_of)[:19]}`")
    lines.append("")

    if not rows:
        lines.append("No re-entry desk artifact found — rebuild desk / check Data Broker.")
        lines.append("")
        lines.append("CC: `/v3/portfolio/re-entry` · `/cio reentry`")
        lines.append("No orders/stops from chat · READ_ONLY_ADVISORY")
        return "\n".join(lines)

    if ready:
        lines.append(f"✅ *READY TO REVIEW* ({len(ready)}) — buy-limit candidates")
        for it in ready:
            zone = ""
            if it.get("entry_low") is not None and it.get("entry_high") is not None:
                zone = f" zone {_fmt_money(it['entry_low'])}–{_fmt_money(it['entry_high'])}"
            px = _fmt_money(it.get("price"))
            held_tag = " · *held*" if it.get("held") else ""
            lines.append(f"• *{it['symbol']}* {px}{zone}{held_tag}")
            if it.get("action"):
                lines.append(f"  _{it['action']}_")
            if detail:
                lvl = _fmt_levels_line(it)
                if lvl:
                    lines.append(f"  {lvl}")
                else:
                    lines.append("  _levels: DATA_UNAVAILABLE on desk row_")
    else:
        lines.append("✅ *READY TO REVIEW* — none right now")

    lines.append("")
    if near:
        if detail:
            # When operator asked for levels, show top NEAR with SMA/stop too
            show_n = min(5, max(1, int(near_limit)))
            lines.append(f"👀 *NEAR ENTRY* ({len(near)}) — top {show_n} w/ levels")
            for it in near[:show_n]:
                zone = ""
                if it.get("entry_low") is not None and it.get("entry_high") is not None:
                    zone = f" zone {_fmt_money(it['entry_low'])}–{_fmt_money(it['entry_high'])}"
                lines.append(f"• `{it['symbol']}` {_fmt_money(it.get('price'))}{zone}")
                lvl = _fmt_levels_line(it)
                if lvl:
                    lines.append(f"  {lvl}")
            extra = len(near) - show_n
            if extra > 0:
                lines.append(f"_+{extra} more NEAR — `/v3/portfolio/re-entry`_")
        else:
            show = near[: max(1, int(near_limit))]
            names = ", ".join(f"`{it['symbol']}`" for it in show)
            extra = len(near) - len(show)
            near_line = f"👀 *NEAR ENTRY* ({len(near)}): {names}"
            if extra > 0:
                near_line += f" +{extra} more"
            lines.append(near_line)
            lines.append("_Near = watch/prepare — not purchase-ready yet_")
    else:
        lines.append("👀 *NEAR ENTRY* — none")

    lines.append("")
    if detail:
        lines.append(
            "_Levels from re-entry desk (stop / resist / SMAs). "
            "No separate ‘support’ field — use stop + entry zone._"
        )
    lines.append(
        "Note: current *holdings* are not re-entry targets; "
        "this book is for names you already exited."
    )
    lines.append("CC: `/v3/portfolio/re-entry` · cmd: `/cio reentry`")
    lines.append("No orders/stops from chat · READ_ONLY_ADVISORY")
    return "\n".join(lines)


def _reentry_flash_enabled() -> bool:
    raw = (_env("CIO_REENTRY_FLASH") or "1").lower()
    return raw not in ("0", "false", "off", "no")


def _validate_flash_reentry_reply(
    curated: str,
    *,
    ready_symbols: list[str],
    near_symbols: list[str],
) -> bool:
    """Fail-closed: Flash may rewrite tone, not drop READY names or claim fills."""
    text = (curated or "").strip()
    if not text or len(text) < 40 or len(text) > 3500:
        return False
    upper = text.upper()
    for sym in ready_symbols:
        if sym.upper() not in upper:
            return False
    banned = (
        "ORDER PLACED",
        "BUYING NOW",
        "SUBMITTED",
        "FILLED",
        "I WILL BUY",
        "EXECUTING",
        "BROKER ORDER",
    )
    if any(b in upper for b in banned):
        return False
    # Soft invent check: reject ONLY if Flash adds many tickers outside ready+near
    allowed = {s.upper() for s in ready_symbols} | {s.upper() for s in near_symbols}
    # Tokens that look like tickers but are English/labels in this card
    stop = {
        "READY", "NEAR", "ENTRY", "REVIEW", "ZONE", "CC", "CIO", "READ", "ONLY",
        "ADVISORY", "HOLDINGS", "LIMIT", "BUY", "WATCH", "THE", "AND", "NOT",
        "YET", "MORE", "AS", "OF", "USD", "UTC", "CMD", "NOTE", "NONE", "THIS",
        "THAT", "FROM", "WITH", "FOR", "DESK", "BOOK", "CASH", "FLASH", "LLM",
        "PRICE", "RANGE", "NAMES", "NAME", "LIST", "NEXT", "STEP", "STEPS",
        "ACTION", "ACTIONS", "CANDIDATE", "CANDIDATES", "EXITED", "CURRENT",
        "TARGET", "TARGETS", "TACTICAL", "PREPARE", "PURCHASE", "REENTRY",
        "HTTP", "HTTPS", "PORTFOLIO", "TELEGRAM", "OPERATOR", "ALEX",
    }
    invented = []
    for tok in re.findall(r"\b([A-Z]{2,5})\b", text):
        if tok in allowed or tok in stop:
            continue
        if tok.isalpha():
            invented.append(tok)
    # Allow a couple of unknown ALLCAPS words (Flash vocabulary); block a pile of new tickers
    if len(set(invented)) > 3:
        return False
    return True


def curate_reentry_reply_with_flash(
    *,
    operator_text: str,
    deterministic_reply: str,
    ready_symbols: list[str],
    near_symbols: list[str],
) -> dict[str, Any]:
    """DeepSeek Flash polish for Telegram — numbers/symbols stay desk-grounded.

    Fail-soft to deterministic_reply on any governance/validation miss.
    """
    out: dict[str, Any] = {
        "ok": False,
        "text": deterministic_reply,
        "source": "deterministic",
        "model": None,
        "error": None,
    }
    if not _reentry_flash_enabled():
        out["error"] = "flash_disabled"
        return out
    if not (deterministic_reply or "").strip():
        out["error"] = "empty_facts"
        return out

    system = (
        "You are Alex, CIO desk Telegram assistant. Authority: READ_ONLY_ADVISORY. "
        "Rewrite the FACTS card into a clear, scannable Telegram message using *bold* "
        "and short bullets. Keep EVERY READY symbol and its price, zone, stop, resist, "
        "SMA20/SMA50/SMA200, RSI, and target exactly as given — do not invent or round away. "
        "You may shorten the NEAR list. Do not invent symbols, prices, zones, or urgency. "
        "Do not place orders or claim execution. End with READ_ONLY_ADVISORY. "
        "No thesis essays. Max ~22 lines."
    )
    user = (
        f"Operator asked: {(operator_text or '')[:300]}\n\n"
        f"FACTS (ground truth — do not change numbers/symbols):\n"
        f"{deterministic_reply}\n\n"
        f"READY symbols that MUST appear: {', '.join(ready_symbols) or '(none)'}\n"
        f"NEAR symbols allowed: {', '.join(near_symbols[:20]) or '(none)'}"
    )
    try:
        from scripts.lib.cio_plan_enrichment import call_governed_llm, load_llm_policy
        policy = load_llm_policy()
        # Force Flash (deepseek-v4-flash) — not Pro — for this short polish
        llm = call_governed_llm(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            policy,
            use_pro=False,
        )
    except Exception as exc:
        out["error"] = f"flash_call:{type(exc).__name__}:{exc}"
        return out

    if not llm.get("ok"):
        out["error"] = str(llm.get("error") or llm.get("governance_code") or "flash_failed")
        out["model"] = llm.get("model")
        return out

    curated = str(llm.get("content") or "").strip()
    # Strip accidental code fences
    if curated.startswith("```"):
        curated = re.sub(r"^```(?:markdown|md|text)?\s*", "", curated)
        curated = re.sub(r"\s*```$", "", curated).strip()
    if "READ_ONLY" not in curated.upper():
        curated = curated.rstrip() + "\nNo orders/stops from chat · READ_ONLY_ADVISORY"

    if not _validate_flash_reentry_reply(
        curated,
        ready_symbols=ready_symbols,
        near_symbols=near_symbols,
    ):
        out["error"] = "flash_validation_rejected"
        out["model"] = llm.get("model")
        return out

    out.update({
        "ok": True,
        "text": curated,
        "source": "deepseek_flash",
        "model": llm.get("model") or "deepseek-v4-flash",
        "error": None,
    })
    return out


def answer_reentry_purchase_query(
    operator_text: str = "",
    *,
    use_flash: bool = True,
) -> dict[str, Any]:
    """Facts-first re-entry answer; optional DeepSeek Flash Telegram polish."""
    rows, as_of, path = load_reentry_desk_rows()
    ready_syms: list[str] = []
    near_syms: list[str] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        intel = r.get("intel") if isinstance(r.get("intel"), dict) else {}
        state = str(intel.get("state") or r.get("status") or "").strip()
        sym = str(r.get("symbol") or "").upper()
        if not sym:
            continue
        if state == "READY TO REVIEW":
            ready_syms.append(sym)
        elif state == "NEAR ENTRY":
            near_syms.append(sym)

    deterministic = format_reentry_purchase_reply(
        desk_rows=rows,
        computed_at=as_of,
        operator_text=operator_text,
        include_levels=True,
    )
    result: dict[str, Any] = {
        "text": deterministic,
        "source": "deterministic",
        "model": None,
        "ready_symbols": ready_syms,
        "near_symbols": near_syms,
        "as_of": as_of,
        "desk_path": str(path) if path else None,
        "flash_error": None,
    }
    if use_flash and _reentry_flash_enabled():
        flash = curate_reentry_reply_with_flash(
            operator_text=operator_text,
            deterministic_reply=deterministic,
            ready_symbols=ready_syms,
            near_symbols=near_syms,
        )
        if flash.get("ok"):
            result["text"] = flash["text"]
            result["source"] = "deepseek_flash"
            result["model"] = flash.get("model")
        else:
            result["flash_error"] = flash.get("error")
    _emit_reentry_reply_payload(ready_syms, near_syms)
    return result


def _emit_reentry_reply_payload(ready_syms: list[str], near_syms: list[str]) -> None:
    """DecisionPayload@v1 for a Telegram re-entry facts reply. Fail-soft."""
    try:
        from scripts.lib.agent_decision_payload import emit_telegram_decision_payload
        emit_telegram_decision_payload(
            symbol=ready_syms[0] if ready_syms else (near_syms[0] if near_syms else None),
            action="READY" if ready_syms else ("NEAR" if near_syms else "WAIT"),
            surface="reentry",
            origin="OPERATOR_ASK",
            extra={"ready_n": len(ready_syms), "near_n": len(near_syms)},
        )
    except Exception:
        pass


def _portfolio_cash_fact_lines() -> list[str]:
    """One-line book facts for Flash context (fail-soft)."""
    lines: list[str] = []
    try:
        holdings_path = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
        # Fall back to canonical live tree
        if not holdings_path.is_file():
            holdings_path = Path(
                "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
                "/data/portfolios/state/holdings.json"
            )
        if not holdings_path.is_file():
            return lines
        data = json.loads(holdings_path.read_text(encoding="utf-8"))
        total = data.get("total_value") or data.get("portfolio_value")
        cash = data.get("cash") or data.get("total_cash")
        as_of = data.get("as_of") or data.get("generated_at")
        if total is not None:
            lines.append(f"portfolio_total≈{_fmt_money(total)}")
        if cash is not None:
            lines.append(f"cash≈{_fmt_money(cash)}")
        if as_of:
            lines.append(f"holdings_as_of={str(as_of)[:19]}")
    except Exception:
        pass
    return lines


