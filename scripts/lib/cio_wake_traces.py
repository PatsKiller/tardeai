"""CIO lightweight wake traces — append-only JSONL (Phase P5).

READ_ONLY_ADVISORY. Fail-soft: never raise into wake/enrich/converse flow.
Answers: why did it wake / what did the LLM path do / did it finish.

File: data/cio/cio_wake_traces.jsonl
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TRACE_PATH = PROJECT_ROOT / "data" / "cio" / "cio_wake_traces.jsonl"

# Canonical enums (soft — unknown strings still accepted)
SOURCES = frozenset({
    "situation.raised",
    "OPERATOR_MESSAGE",
    "GOAL_DUE",
    "EVENT_BUS",
    "heartbeat",
    "other",
})
LLM_STATES = frozenset({
    "invoked",
    "blocked_cap",
    "blocked_provider",
    "blocked_disabled",
    "template",
    "forced_template",
    "skipped_non_material",
    "skipped_dedup",
    "pending",
})
OUTCOMES = frozenset({"ok", "error", "deferred", "open"})

# Fields kept on merged projection
_MERGE_KEYS = (
    "trace_id",
    "wake_id",
    "ts",
    "ts_open",
    "ts_close",
    "source",
    "situation_type",
    "agent_id",
    "plan_id",
    "thesis_version",
    "llm",
    "model_id",
    "duration_ms",
    "outcome",
    "error_class",
    "flags",
    "phase",
    "t0_ms",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ms() -> int:
    return int(time.time() * 1000)


def flags_snapshot() -> dict[str, bool]:
    """Current enrich/notify flags (env + soft defaults)."""
    enrich_raw = os.environ.get("CIO_LLM_ENRICH", "1").strip().lower()
    enrich_on = enrich_raw not in ("0", "false", "off", "no")
    # Accept singular or plural notify env (OR); default off when both unset.
    notify_on = False
    for key in ("CIO_SITUATION_NOTIFY", "CIO_SITUATIONS_NOTIFY"):
        if os.environ.get(key, "").strip().lower() in ("1", "true", "on", "yes"):
            notify_on = True
            break
    return {"enrich_on": enrich_on, "notify_on": notify_on}


def map_source(
    trigger_type: str = "",
    reason_codes: Optional[Iterable[str]] = None,
    event_type: str = "",
    situation_type: str = "",
    source: str = "",
) -> str:
    """Map wake/enrich inputs → canonical trace source."""
    if source and source in SOURCES:
        return source
    s = (source or "").strip()
    st = (situation_type or "").strip()
    tt = (trigger_type or "").strip()
    et = (event_type or "").strip()
    reasons = {str(r) for r in (reason_codes or [])}

    if s == "OPERATOR_MESSAGE" or tt == "OPERATOR_MESSAGE" or "OPERATOR_MESSAGE" in reasons:
        return "OPERATOR_MESSAGE"
    if st.startswith("S") and "_" in st:
        return "situation.raised"
    if s.startswith("S") and "_" in s:
        return "situation.raised"
    if s == "situation.raised" or et == "situation.raised":
        return "situation.raised"
    if tt in ("GOAL_DUE", "GOAL_EVENT_LINKED") or any(r.startswith("GOAL_") for r in reasons):
        return "GOAL_DUE"
    if tt == "EVENT_BUS" or "EVENT_BUS" in reasons:
        return "EVENT_BUS"
    if s == "heartbeat" or et.startswith("system.heartbeat") or "heartbeat" in (s + " " + et).lower():
        return "heartbeat"
    return "other"


def _normalize_llm(llm: Optional[str], narrative_source: Optional[str] = None) -> Optional[str]:
    if not llm:
        if narrative_source == "template":
            return "template"
        if narrative_source == "llm":
            return "invoked"
        return None
    # Map enrich_plan status to schema-friendly values
    if llm == "forced_template":
        return "template"
    if llm == "blocked_disabled":
        return "blocked_provider"
    return llm


def _short_error(err: Any, max_len: int = 80) -> Optional[str]:
    if err is None or err == "":
        return None
    s = str(err).replace("\n", " ").strip()
    # Prefer class-like prefixes
    if ":" in s and len(s.split(":", 1)[0]) < 40:
        head = s.split(":", 1)[0].strip()
        if head and " " not in head:
            return head[:max_len]
    return s[:max_len]


def _append_row(row: dict[str, Any], path: Path) -> bool:
    """Append one JSONL row. Returns True on success. Never raises."""
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Drop Nones for compactness; keep explicit booleans/flags
        clean = {k: v for k, v in row.items() if v is not None}
        line = json.dumps(clean, sort_keys=True, separators=(",", ":"), default=str) + "\n"
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
        return True
    except Exception:
        return False


def _trace_id_for(wake_id: str, explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit
    # Stable-ish id per wake for operator correlation
    if wake_id:
        return f"tr_{wake_id}"[:96]
    return f"tr_{uuid.uuid4().hex[:16]}"


def open_trace(
    *,
    wake_id: str,
    source: str = "other",
    situation_type: Optional[str] = None,
    agent_id: Optional[str] = None,
    plan_id: Optional[str] = None,
    thesis_version: Optional[str] = None,
    trace_id: Optional[str] = None,
    path: Path | str | None = None,
    extra: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Open a wake trace (phase=open, outcome=open). Fail-soft; returns trace_id or None."""
    try:
        p = Path(path) if path else DEFAULT_TRACE_PATH
        tid = _trace_id_for(wake_id, trace_id)
        t0 = _now_ms()
        row: dict[str, Any] = {
            "phase": "open",
            "trace_id": tid,
            "wake_id": wake_id or tid,
            "ts": _now_iso(),
            "ts_open": _now_iso(),
            "source": map_source(source=source, situation_type=situation_type or ""),
            "situation_type": situation_type,
            "agent_id": agent_id or "alex",
            "plan_id": plan_id,
            "thesis_version": thesis_version,
            "llm": "pending",
            "model_id": None,
            "duration_ms": None,
            "outcome": "open",
            "error_class": None,
            "flags": flags_snapshot(),
            "t0_ms": t0,
        }
        if extra:
            for k, v in extra.items():
                if k not in row and v is not None:
                    row[k] = v
        if not _append_row(row, p):
            return None
        return tid
    except Exception:
        return None


def update_trace(
    wake_id: str = "",
    *,
    trace_id: Optional[str] = None,
    llm: Optional[str] = None,
    model_id: Optional[str] = None,
    plan_id: Optional[str] = None,
    situation_type: Optional[str] = None,
    agent_id: Optional[str] = None,
    thesis_version: Optional[str] = None,
    source: Optional[str] = None,
    narrative_source: Optional[str] = None,
    error_class: Optional[str] = None,
    path: Path | str | None = None,
    extra: Optional[dict[str, Any]] = None,
) -> bool:
    """Append a phase=update row (merge-on-read). Fail-soft."""
    try:
        p = Path(path) if path else DEFAULT_TRACE_PATH
        wid = wake_id or (trace_id or "")
        if not wid and not trace_id:
            return False
        tid = _trace_id_for(wid, trace_id)
        row: dict[str, Any] = {
            "phase": "update",
            "trace_id": tid,
            "wake_id": wid or tid,
            "ts": _now_iso(),
            "llm": _normalize_llm(llm, narrative_source),
            "model_id": model_id,
            "plan_id": plan_id,
            "situation_type": situation_type,
            "agent_id": agent_id,
            "thesis_version": thesis_version,
            "source": map_source(source=source or "", situation_type=situation_type or "") if source or situation_type else None,
            "error_class": _short_error(error_class) if error_class else None,
            "flags": flags_snapshot(),
        }
        if extra:
            for k, v in extra.items():
                if v is not None:
                    row[k] = v
        return _append_row(row, p)
    except Exception:
        return False


def close_trace(
    wake_id: str = "",
    *,
    trace_id: Optional[str] = None,
    outcome: str = "ok",
    llm: Optional[str] = None,
    model_id: Optional[str] = None,
    plan_id: Optional[str] = None,
    situation_type: Optional[str] = None,
    agent_id: Optional[str] = None,
    thesis_version: Optional[str] = None,
    source: Optional[str] = None,
    narrative_source: Optional[str] = None,
    error_class: Optional[str] = None,
    duration_ms: Optional[int] = None,
    t0_ms: Optional[int] = None,
    path: Path | str | None = None,
    extra: Optional[dict[str, Any]] = None,
) -> bool:
    """Append phase=close row. Fail-soft."""
    try:
        p = Path(path) if path else DEFAULT_TRACE_PATH
        wid = wake_id or (trace_id or "")
        if not wid and not trace_id:
            return False
        tid = _trace_id_for(wid, trace_id)
        if duration_ms is None and t0_ms is not None:
            try:
                duration_ms = max(0, _now_ms() - int(t0_ms))
            except Exception:
                duration_ms = None
        oc = outcome if outcome in OUTCOMES else "ok"
        row: dict[str, Any] = {
            "phase": "close",
            "trace_id": tid,
            "wake_id": wid or tid,
            "ts": _now_iso(),
            "ts_close": _now_iso(),
            "outcome": oc,
            "llm": _normalize_llm(llm, narrative_source),
            "model_id": model_id,
            "plan_id": plan_id,
            "situation_type": situation_type,
            "agent_id": agent_id,
            "thesis_version": thesis_version,
            "source": map_source(source=source or "", situation_type=situation_type or "") if source or situation_type else None,
            "error_class": _short_error(error_class) if error_class else None,
            "duration_ms": duration_ms,
            "flags": flags_snapshot(),
        }
        if extra:
            for k, v in extra.items():
                if v is not None:
                    row[k] = v
        return _append_row(row, p)
    except Exception:
        return False


def emit_closed_trace(
    *,
    wake_id: str,
    source: str,
    llm: str,
    outcome: str = "ok",
    situation_type: Optional[str] = None,
    agent_id: Optional[str] = None,
    plan_id: Optional[str] = None,
    thesis_version: Optional[str] = None,
    model_id: Optional[str] = None,
    duration_ms: Optional[int] = None,
    error_class: Optional[str] = None,
    path: Path | str | None = None,
    extra: Optional[dict[str, Any]] = None,
) -> bool:
    """One-shot open+close style closed record (for heartbeat no-ops, etc.)."""
    try:
        p = Path(path) if path else DEFAULT_TRACE_PATH
        tid = _trace_id_for(wake_id)
        ts = _now_iso()
        row: dict[str, Any] = {
            "phase": "close",
            "trace_id": tid,
            "wake_id": wake_id or tid,
            "ts": ts,
            "ts_open": ts,
            "ts_close": ts,
            "source": map_source(source=source, situation_type=situation_type or ""),
            "situation_type": situation_type,
            "agent_id": agent_id or "alex",
            "plan_id": plan_id,
            "thesis_version": thesis_version,
            "llm": _normalize_llm(llm),
            "model_id": model_id,
            "duration_ms": duration_ms if duration_ms is not None else 0,
            "outcome": outcome if outcome in OUTCOMES else "ok",
            "error_class": _short_error(error_class) if error_class else None,
            "flags": flags_snapshot(),
        }
        if extra:
            for k, v in extra.items():
                if v is not None:
                    row[k] = v
        return _append_row(row, p)
    except Exception:
        return False


def _read_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        return rows
    return rows


def _merge_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Last-write-wins merge; preserve first ts_open/t0_ms."""
    out: dict[str, Any] = {}
    for r in rows:
        if not out:
            out = {k: r.get(k) for k in r}
            continue
        for k, v in r.items():
            if k in ("ts_open", "t0_ms") and out.get(k) is not None:
                continue
            if v is None:
                continue
            out[k] = v
        # always advance last ts
        if r.get("ts"):
            out["ts"] = r["ts"]
    # duration from t0 if still open-ish missing
    if out.get("duration_ms") is None and out.get("t0_ms") and out.get("phase") == "close":
        try:
            # use ts_close if parseable; else leave
            pass
        except Exception:
            pass
    if out.get("duration_ms") is None and out.get("t0_ms") is not None and out.get("outcome") not in (None, "open"):
        try:
            # approximate from wall clock only if closed without duration
            out["duration_ms"] = max(0, _now_ms() - int(out["t0_ms"]))
        except Exception:
            pass
    return out


def list_traces(
    *,
    limit: int = 20,
    plan_id: Optional[str] = None,
    llm: Optional[str] = None,
    wake_id: Optional[str] = None,
    source: Optional[str] = None,
    outcome: Optional[str] = None,
    path: Path | str | None = None,
    closed_only: bool = False,
) -> list[dict[str, Any]]:
    """List recent traces (merged by wake_id). Newest first. Deterministic, zero LLM."""
    try:
        p = Path(path) if path else DEFAULT_TRACE_PATH
        raw = _read_rows(p)
        by_wake: dict[str, list[dict[str, Any]]] = {}
        order: list[str] = []
        for r in raw:
            key = str(r.get("wake_id") or r.get("trace_id") or "")
            if not key:
                continue
            if key not in by_wake:
                by_wake[key] = []
                order.append(key)
            by_wake[key].append(r)
        merged = [_merge_rows(by_wake[k]) for k in order]
        # filter
        out: list[dict[str, Any]] = []
        for m in merged:
            if plan_id and str(m.get("plan_id") or "") != str(plan_id):
                continue
            if llm and str(m.get("llm") or "") != str(llm):
                continue
            if wake_id and str(m.get("wake_id") or "") != str(wake_id):
                continue
            if source and str(m.get("source") or "") != str(source):
                continue
            if outcome and str(m.get("outcome") or "") != str(outcome):
                continue
            if closed_only and m.get("outcome") in (None, "open"):
                continue
            out.append(m)
        # newest last write first
        out.reverse()
        lim = max(1, min(int(limit or 20), 200))
        return out[:lim]
    except Exception:
        return []


def format_traces(
    rows: list[dict[str, Any]],
    *,
    max_chars: int = 3500,
) -> str:
    """Compact operator text for /cio traces (cap length)."""
    if not rows:
        return "No wake traces."
    lines = [f"🔍 CIO wake traces (last {len(rows)}, READ_ONLY):"]
    for m in rows:
        ts = str(m.get("ts") or "")[:19]
        llm = m.get("llm") or "-"
        oc = m.get("outcome") or "-"
        src = m.get("source") or "-"
        wid = m.get("wake_id") or "-"
        pid = m.get("plan_id") or "-"
        st = m.get("situation_type") or "-"
        err = m.get("error_class")
        dur = m.get("duration_ms")
        dur_s = f"{dur}ms" if dur is not None else "-"
        line = (
            f"• {ts}  {src}  llm={llm}  out={oc}  {dur_s}\n"
            f"  wake={wid}  plan={pid}  sit={st}"
        )
        if err:
            line += f"  err={err}"
        if m.get("model_id"):
            line += f"  model={m.get('model_id')}"
        lines.append(line)
    text = "\n".join(lines)
    if len(text) > max_chars:
        return text[: max_chars - 20] + "\n…(truncated)"
    return text


def cmd_traces_text(
    n: int = 10,
    *,
    plan_id: Optional[str] = None,
    llm: Optional[str] = None,
    path: Path | str | None = None,
) -> str:
    rows = list_traces(limit=n, plan_id=plan_id, llm=llm, path=path)
    return format_traces(rows)


# ── Fail-soft wrappers for call sites ───────────────────────────────────────


def safe_open_from_wake_payload(payload: dict[str, Any], *, path: Path | str | None = None) -> None:
    """Called after wake enqueue. Never raises."""
    try:
        ctx = payload.get("context") or {}
        reasons = payload.get("reason_codes") or []
        tt = str(payload.get("trigger_type") or "")
        src = map_source(
            trigger_type=tt,
            reason_codes=reasons,
            event_type=str(ctx.get("event_type") or ""),
            situation_type=str(ctx.get("situation_type") or ""),
        )
        open_trace(
            wake_id=str(payload.get("wake_job_id") or ""),
            source=src,
            situation_type=ctx.get("situation_type"),
            agent_id=str(ctx.get("target_agent") or ctx.get("agent_id") or "alex"),
            plan_id=ctx.get("plan_id"),
            thesis_version=ctx.get("thesis_version"),
            path=path,
        )
    except Exception:
        pass


def safe_update_from_enrich(
    *,
    wake_id: str,
    plan: Optional[dict[str, Any]] = None,
    llm: Optional[str] = None,
    model_id: Optional[str] = None,
    source: str = "",
    narrative_source: Optional[str] = None,
    llm_error: Optional[str] = None,
    path: Path | str | None = None,
) -> None:
    try:
        plan = plan or {}
        update_trace(
            wake_id=wake_id or str(plan.get("plan_id") or ""),
            llm=llm,
            model_id=model_id or plan.get("llm_model"),
            plan_id=plan.get("plan_id"),
            situation_type=plan.get("situation_type"),
            agent_id=plan.get("owner_agent") or "alex",
            thesis_version=plan.get("thesis_version"),
            source=source or plan.get("situation_type") or "",
            narrative_source=narrative_source or plan.get("narrative_source"),
            error_class=llm_error,
            path=path,
        )
    except Exception:
        pass


def safe_close_from_enrich(
    *,
    wake_id: str,
    plan: Optional[dict[str, Any]] = None,
    llm: Optional[str] = None,
    model_id: Optional[str] = None,
    source: str = "",
    narrative_source: Optional[str] = None,
    llm_error: Optional[str] = None,
    outcome: str = "ok",
    duration_ms: Optional[int] = None,
    path: Path | str | None = None,
) -> None:
    try:
        plan = plan or {}
        # Cap path / template → deferred when LLM did not run successfully
        oc = outcome
        if oc == "ok" and llm in ("blocked_cap", "template", "blocked_provider", "blocked_disabled", "forced_template"):
            if narrative_source == "template" or llm in ("blocked_cap", "template", "forced_template"):
                oc = "deferred" if llm == "blocked_cap" else "ok"
        close_trace(
            wake_id=wake_id or str(plan.get("plan_id") or ""),
            outcome=oc,
            llm=llm,
            model_id=model_id or plan.get("llm_model"),
            plan_id=plan.get("plan_id"),
            situation_type=plan.get("situation_type"),
            agent_id=plan.get("owner_agent") or "alex",
            thesis_version=plan.get("thesis_version"),
            source=source or plan.get("situation_type") or "",
            narrative_source=narrative_source or plan.get("narrative_source"),
            error_class=llm_error,
            duration_ms=duration_ms,
            path=path,
        )
    except Exception:
        pass
