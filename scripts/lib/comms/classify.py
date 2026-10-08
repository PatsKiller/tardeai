"""Communications classification — the decision-support fields for every CommunicationEvent.

Operator 2026-10-07: open Communications and immediately see what needs attention, what is an opportunity
(especially re-entry) and what can be ignored. Every item gets: category (config/comms_categories.yaml, extensible),
priority (critical/high/medium/low), five scores — priority, confidence, risk, reward, time sensitivity — a TTL and
expiry, an actionability flag with a short action, the symbols it is about, and for re-entry items a re-entry
status (opportunity / potential / confirmed / expired / invalidated). Before this, nearly every row was `info` /
`operational_30d` from `telegram_alert.send_telegram` / `ops`, so nothing told the families apart.

Pure functions; the only I/O is reading the YAML (cached by mtime). Rules match the first line (each family has a
distinctive header); a rule's optional `body` regex must also hit somewhere in the body.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "config" / "comms_categories.yaml"
_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_TIER = {"critical": 1.0, "high": 0.75, "medium": 0.45, "low": 0.15}
_cache: dict[str, Any] = {"mtime": None, "cfg": None}

# Symbol tags the alert footer adds ("ALLE:4b54769d"). Words the tagger mistakes for tickers are dropped.
_TAG_RE = re.compile(r"\b([A-Z][A-Z0-9.]{0,5}):[0-9a-f]{8}\b")
_NOT_SYMBOLS = {"CI", "DB", "HST", "OI", "DTE", "B", "S", "PRICE", "PEG", "LIVE", "POP", "FIVE", "RS", "CACC",
                "TSLW", "MAA", "CINT", "RMAX", "DHSB", "AIFA", "HODO", "LQDT", "TROW", "NNE", "XLK",
                # header words that look like tickers
                "SCALP", "ALERT", "ALERTS", "NEW", "GO", "WATCH", "CIO", "BUY", "SELL", "HOLD", "WAIT", "AVOID",
                "NOGO", "ETF", "API", "RSI", "MA", "ET", "EOD", "AM", "PM", "OK", "ATP", "SIEM", "NOTE", "READY",
                "LIVE", "DEGRADED", "STALE", "MISSING", "NEAR", "FAIL", "PASS", "INFO", "AI", "LLM", "UTC", "USD",
                "TRIGGERED", "APPROACHING", "ARMED", "FAILED", "CRITICAL", "HIGH", "LOW", "OPEN", "CLOSED", "NONE",
                "DRY", "RUN", "UNREVIEWED", "ATM", "CASH", "REVIEW", "HUMAN", "TRADE", "AI.", "GTC", "DAY", "IRA", "ROTH", "TAX"}


def load_config(path: Optional[Path] = None) -> dict:
    p = path or CONFIG_PATH
    try:
        m = p.stat().st_mtime
    except OSError:
        m = None
    if path is None and _cache["cfg"] is not None and _cache["mtime"] == m:
        return _cache["cfg"]
    import yaml
    cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    for r in cfg.get("rules") or []:
        r["_re"] = re.compile(str(r["match"]), re.IGNORECASE)
        r["_body"] = re.compile(str(r["body"]), re.IGNORECASE) if r.get("body") else None
    for r in cfg.get("reentry_status") or []:
        r["_re"] = re.compile(str(r["match"]), re.IGNORECASE)
    cfg["_signals"] = {k: re.compile(v, re.IGNORECASE) for k, v in (cfg.get("signals") or {}).items()}
    if path is None:
        _cache.update(mtime=m, cfg=cfg)
    return cfg


def _plain(body: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", body or ""))


def _first_line(body: str) -> str:
    for line in _plain(body).splitlines():
        line = line.strip().strip("*_").strip()
        if line:
            return line
    return ""


# Where a stored body names its symbol: footer tags, Command Center links, `symbol=` params, and the header shapes
# the families use ("ALERT — ALLE", "Signal: VJET", "TRIGGER: *DT*", "OPTIONS INTENT · SPCX").
_LINK_RE = re.compile(r"/watch/intelligence/([A-Z][A-Z0-9.]{0,5})\b|[?&]symbol=([A-Z][A-Z0-9.]{0,5})\b")
_HEAD_RE = re.compile(r"(?:—|–|:|·)\s*\*?\$?([A-Z][A-Z0-9]{0,4}(?:\.[A-Z])?)\*?(?=\s|$|[·*,()]|\s*\()")


def symbols_in(body: str) -> list[str]:
    seen: list[str] = []

    def add(s: str) -> None:
        if s and s not in _NOT_SYMBOLS and s not in seen and len(seen) < 8:
            seen.append(s)

    for a, b in _LINK_RE.findall(body or ""):
        add(a or b)
    for s in _TAG_RE.findall(body or ""):
        add(s)
    lines = [l.strip() for l in _plain(body).splitlines() if l.strip()][:2]
    lead = re.match(r"^[^A-Za-z]*\*?([A-Z]{2,5})\*?\s+[A-Z][a-z]", lines[0]) if lines else None   # "TDG Reentry ..."
    if lead:
        add(lead.group(1))
    for s2 in re.findall(r"\b(?:state|signal|watch|for)\s+\*?([A-Z]{2,5})\b", " ".join(lines)):   # "Entry state PEW"
        add(s2)
    for s in _HEAD_RE.findall(" \n".join(lines)):
        if len(s) >= 2:
            add(s)
    return seen


def headline(body: str) -> str:
    return _first_line(body)[:200]


def topic_key(category: str, body: str) -> str:
    """Same category + same headline shape (numbers ignored) = the same topic, so a newer copy supersedes."""
    import hashlib
    norm = re.sub(r"[0-9][0-9.,:%$+-]*", "#", _first_line(body).lower())
    return hashlib.sha1(f"{category}|{norm}".encode("utf-8")).hexdigest()[:16]


def priority_score(priority: str, time: float, risk: float, reward: float, confidence: float) -> float:
    tier = _TIER.get(priority, 0.15)
    return round(100.0 * (0.35 * time + 0.25 * max(risk, reward) + 0.20 * confidence + 0.20 * tier), 1)


def _clip(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def classify(*, body: str, direction: str = "OUTBOUND", severity: Optional[str] = None,
             message_class: Optional[str] = None, cfg: Optional[dict] = None) -> dict[str, Any]:
    """Every decision-support field for one message (pure)."""
    cfg = cfg or load_config()
    text = _plain(body)
    if str(direction).upper() == "INBOUND":
        spec, rule_id = dict(cfg.get("inbound") or {}), "inbound"
    else:
        head, spec, rule_id = _first_line(body), None, None
        for r in cfg.get("rules") or []:
            if r["_re"].search(head or "") and (r["_body"] is None or r["_body"].search(text)):
                spec, rule_id = r, r["id"]
                break
        if spec is None:
            spec, rule_id = dict(cfg.get("default") or {}), "default"
    prio = str(spec.get("priority") or "low").lower()
    floor = (cfg.get("severity_floor") or {}).get(str(severity or "").lower())
    if floor and _RANK.get(floor, 9) < _RANK.get(prio, 9):
        prio = floor
    cats = cfg.get("categories") or {}
    cat = str(spec.get("category") or "system_alert")
    if cat not in cats:
        cat = str((cfg.get("default") or {}).get("category") or next(iter(cats)))
    conf, risk, reward, tsens = (_clip(spec.get(k, d)) for k, d in
                                 (("confidence", 0.5), ("risk", 0.1), ("reward", 0.0), ("time", 0.2)))
    sig = cfg.get("_signals") or {}
    m = sig.get("confidence") and sig["confidence"].search(text)
    if m:
        v = m.group(1)
        conf = _clip(float(v.rstrip("%")) / 100.0 if v.endswith("%") else float(v))
    m = sig.get("reward_rr") and sig["reward_rr"].search(text)
    if m and reward > 0:
        reward = _clip(max(reward, min(float(m.group(1)), 6.0) / 6.0))
    reentry = None
    if cat == "re_entry":
        for r in cfg.get("reentry_status") or []:
            if r["_re"].search(text):
                reentry = r["status"]
                break
    actionable = bool(spec.get("actionable"))
    if reentry == "invalidated":
        actionable = False
    return {"category": cat, "priority": prio, "confidence": round(conf, 3), "risk_score": round(risk, 3),
            "reward_score": round(reward, 3), "time_sensitivity": round(tsens, 3),
            "priority_score": priority_score(prio, tsens, risk, reward, conf),
            "ttl_hours": float(cats[cat]["ttl_hours"]), "reentry_status": reentry, "actionable": actionable,
            "action": spec.get("action") if actionable else None, "symbols": symbols_in(body), "rule_id": rule_id,
            "topic_key": topic_key(cat, body) if spec.get("supersede_by_topic", True) else None}


def expires_at(created_at: Optional[datetime], ttl_hours: float) -> datetime:
    base = created_at or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return base + timedelta(hours=ttl_hours)


def categories(cfg: Optional[dict] = None) -> list[dict]:
    cfg = cfg or load_config()
    return [{"id": k, "label": v.get("label", k), "ttl_hours": v.get("ttl_hours")}
            for k, v in (cfg.get("categories") or {}).items()]


# Columns from migrations/2026_10_07_communication_classification.sql.
UPDATE_SQL = """
UPDATE communication_events
   SET category = %(category)s, priority = %(priority)s, priority_score = %(priority_score)s,
       confidence = %(confidence)s, risk_score = %(risk_score)s, reward_score = %(reward_score)s,
       time_sensitivity = %(time_sensitivity)s, reentry_status = %(reentry_status)s, actionable = %(actionable)s,
       action_hint = %(action)s, symbols = %(symbols)s, classified_by = %(rule_id)s, topic_key = %(topic_key)s,
       actionable_since = CASE WHEN %(actionable)s THEN COALESCE(actionable_since, created_at) ELSE NULL END,
       expires_at = CASE WHEN legal_hold THEN expires_at ELSE %(expires_at)s END
 WHERE event_id = %(event_id)s
"""

# "Unless reaffirmed by new data": a newer item in the same category supersedes older active ones that share a symbol
# or the same topic (headline shape) — they are hidden; the newest carries the current view. Rules can opt out with
# supersede_by_topic: false (approval requests: each is a distinct decision).
SUPERSEDE_SQL = """
UPDATE communication_events
   SET status = 'superseded', superseded_by = %(event_id)s
 WHERE status IN ('active', 'acknowledged') AND category = %(category)s
   AND event_id <> %(event_id)s AND created_at <= %(created_at)s
   AND ((cardinality(%(symbols)s::text[]) > 0 AND symbols && %(symbols)s::text[])
        OR (%(topic_key)s::text IS NOT NULL AND topic_key = %(topic_key)s::text))
"""


def update_params(event_id: str, c: dict, created_at: Optional[datetime]) -> dict:
    created = created_at or datetime.now(timezone.utc)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return {**c, "event_id": event_id, "created_at": created, "expires_at": expires_at(created, c["ttl_hours"])}
