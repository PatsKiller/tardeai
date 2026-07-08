"""LLM consumption tracking + per-process Automated/Manual gating for FREE OAuth lanes (Grok, ChatGPT).

Fail-open: if logging or config DB fails, model calls still proceed. Manual mode blocks automatic
calls and returns a structured ManualRequired response for the UI.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
REGISTRY_PATH = ROOT / "config" / "llm_process_registry.json"

_SCHEMA_OK = False
_REGISTRY: dict | None = None


class ManualRequired(Exception):
    """Raised when a process is in manual mode and caller did not force/trigger manually."""

    def __init__(self, process_id: str, lane: str, task_summary: str, prompt_preview: str = ""):
        self.process_id = process_id
        self.lane = lane
        self.task_summary = task_summary
        self.prompt_preview = prompt_preview[:500]
        super().__init__(f"manual approval required for {process_id} ({lane})")


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def ensure_schema() -> None:
    global _SCHEMA_OK
    if _SCHEMA_OK:
        return
    cur = _conn().cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS llm_consumption_log (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            model_lane TEXT NOT NULL,
            model_name TEXT,
            process_id TEXT NOT NULL,
            process_name TEXT,
            task_summary TEXT,
            trigger_mode TEXT NOT NULL DEFAULT 'automated',
            prompt_chars INT,
            response_chars INT,
            tokens_in INT,
            tokens_out INT,
            estimated_cost_usd NUMERIC(12,6) DEFAULT 0,
            success BOOLEAN NOT NULL DEFAULT TRUE,
            error_message TEXT,
            duration_ms INT,
            metadata_json JSONB
        )""")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS llm_process_config (
            process_id TEXT PRIMARY KEY,
            process_name TEXT NOT NULL,
            category TEXT,
            mode TEXT NOT NULL DEFAULT 'manual',
            allowed_lanes TEXT[] DEFAULT ARRAY['grok','chatgpt'],
            daily_soft_cap INT,
            notes TEXT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_llm_consumption_log_created
            ON llm_consumption_log (created_at DESC)""")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_llm_consumption_log_process
            ON llm_consumption_log (process_id, created_at DESC)""")
    _conn().commit()
    _seed_registry()
    _SCHEMA_OK = True


def _load_registry() -> dict:
    global _REGISTRY
    if _REGISTRY is not None:
        return _REGISTRY
    try:
        _REGISTRY = json.loads(REGISTRY_PATH.read_text())
    except Exception:
        _REGISTRY = {"processes": [], "default_mode": "manual"}
    return _REGISTRY


def _seed_registry() -> None:
    reg = _load_registry()
    default = reg.get("default_mode") or "manual"
    cur = _conn().cursor()
    for p in reg.get("processes") or []:
        pid = str(p.get("id") or "").strip()
        if not pid:
            continue
        mode = p.get("default_mode") or default
        # Processes with an explicit default_mode in the registry are bootstrap-synced so
        # operator-approved defaults (e.g. cloud_review=automated) apply on deploy.
        if "default_mode" in p:
            cur.execute("""
                INSERT INTO llm_process_config (process_id, process_name, category, mode, notes, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (process_id) DO UPDATE SET
                  process_name = EXCLUDED.process_name,
                  category = EXCLUDED.category,
                  mode = EXCLUDED.mode,
                  notes = EXCLUDED.notes,
                  updated_at = NOW()
            """, (pid, p.get("name") or pid, p.get("category"), mode, p.get("description")))
        else:
            cur.execute("""
                INSERT INTO llm_process_config (process_id, process_name, category, mode, notes)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (process_id) DO NOTHING
            """, (pid, p.get("name") or pid, p.get("category"), mode, p.get("description")))
    _conn().commit()


def summarize_prompt(prompt: str, max_len: int = 160) -> str:
    s = re.sub(r"\s+", " ", str(prompt or "")).strip()
    return (s[: max_len - 1] + "…") if len(s) > max_len else s


def get_process_config(process_id: str) -> dict:
    ensure_schema()
    pid = str(process_id or "unregistered").strip() or "unregistered"
    row = None
    try:
        cur = _conn().cursor()
        cur.execute("SELECT process_id, process_name, category, mode, allowed_lanes, daily_soft_cap, notes, updated_at "
                    "FROM llm_process_config WHERE process_id=%s", (pid,))
        r = cur.fetchone()
        if r:
            row = {
                "process_id": r[0], "process_name": r[1], "category": r[2], "mode": r[3],
                "allowed_lanes": list(r[4] or []), "daily_soft_cap": r[5], "notes": r[6],
                "updated_at": str(r[7]) if r[7] else None,
            }
    except Exception:
        try:
            _conn().rollback()
        except Exception:
            pass
    if row:
        return row
    reg = _load_registry()
    for p in reg.get("processes") or []:
        if p.get("id") == pid:
            return {
                "process_id": pid, "process_name": p.get("name") or pid,
                "category": p.get("category"), "mode": p.get("default_mode") or reg.get("default_mode") or "manual",
                "allowed_lanes": ["grok", "chatgpt"], "daily_soft_cap": None, "notes": p.get("description"),
            }
    return {
        "process_id": pid, "process_name": pid, "category": "Unknown",
        "mode": reg.get("default_mode") or "manual", "allowed_lanes": ["grok", "chatgpt"],
    }


def set_process_mode(process_id: str, mode: str) -> dict:
    ensure_schema()
    mode = (mode or "").strip().lower()
    if mode not in ("automated", "manual"):
        return {"ok": False, "error": "mode must be automated or manual"}
    cfg = get_process_config(process_id)
    cur = _conn().cursor()
    cur.execute("""
        INSERT INTO llm_process_config (process_id, process_name, category, mode, notes, updated_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
        ON CONFLICT (process_id) DO UPDATE SET mode=EXCLUDED.mode, updated_at=NOW()
    """, (process_id, cfg.get("process_name") or process_id, cfg.get("category"), mode, cfg.get("notes")))
    _conn().commit()
    return {"ok": True, "process_id": process_id, "mode": mode}


def should_call(process_id: str, lane: str, *, manual_trigger: bool = False) -> dict:
    """Decision only — does not call the model."""
    cfg = get_process_config(process_id)
    lane = (lane or "").strip().lower()
    allowed = lane in (cfg.get("allowed_lanes") or ["grok", "chatgpt"])
    if not allowed:
        return {"allow": False, "reason": f"lane {lane} not allowed for {process_id}", "mode": cfg.get("mode")}
    if cfg.get("mode") == "manual" and not manual_trigger:
        return {"allow": False, "reason": "manual_mode", "mode": "manual", "process_id": process_id}
    return {"allow": True, "mode": cfg.get("mode"), "process_id": process_id}


def log_call(
    *,
    lane: str,
    process_id: str,
    task_summary: str,
    trigger_mode: str,
    success: bool,
    model_name: str | None = None,
    prompt: str | None = None,
    response: str | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    duration_ms: int | None = None,
    error_message: str | None = None,
    metadata: dict | None = None,
) -> int | None:
    """Persist a consumption log row. Returns log id or None on failure."""
    try:
        ensure_schema()
        cfg = get_process_config(process_id)
        pc = len(prompt or "")
        rc = len(response or "")
        # Free tier: relative units — 1 unit ≈ 1k chars combined
        rel_units = round((pc + rc) / 1000.0, 3)
        cur = _conn().cursor()
        cur.execute("""
            INSERT INTO llm_consumption_log
              (model_lane, model_name, process_id, process_name, task_summary, trigger_mode,
               prompt_chars, response_chars, tokens_in, tokens_out, estimated_cost_usd,
               success, error_message, duration_ms, metadata_json)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (
            lane, model_name, process_id, cfg.get("process_name") or process_id,
            summarize_prompt(task_summary or prompt or ""),
            trigger_mode, pc, rc, tokens_in, tokens_out, rel_units,
            success, (error_message or "")[:400] if error_message else None,
            duration_ms, json.dumps(metadata or {}, default=str)[:4000] if metadata else None,
        ))
        lid = cur.fetchone()[0]
        _conn().commit()
        return int(lid)
    except Exception:
        try:
            _conn().rollback()
        except Exception:
            pass
        return None


def gate_and_generate(
    prompt: str,
    *,
    lane: str = "grok",
    process_id: str = "unregistered",
    task_summary: str | None = None,
    manual_trigger: bool = False,
    timeout: int = 90,
    model: str | None = None,
    metadata: dict | None = None,
) -> str:
    """Check process mode, call llm_lane.generate, log result. Raises ManualRequired when blocked."""
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from lib.oauth_lane_status import lane_available

    lane = (lane or "grok").lower()
    process_id = str(process_id or "unregistered")
    decision = should_call(process_id, lane, manual_trigger=manual_trigger)
    if not decision.get("allow"):
        if decision.get("reason") == "manual_mode":
            raise ManualRequired(process_id, lane, task_summary or summarize_prompt(prompt), prompt[:500])
        raise RuntimeError(decision.get("reason") or "call not allowed")
    if lane in ("grok", "chatgpt") and not lane_available(lane):
        raise RuntimeError(f"{lane} OAuth lane unavailable — check grok-oauth-proxy / chatgpt-oauth-proxy")
    import llm_lane
    trigger = "manual" if manual_trigger else ("automated" if decision.get("mode") == "automated" else "manual")
    t0 = time.time()
    err = None
    text = ""
    ok = True
    try:
        text = llm_lane.generate(prompt, lane=lane, timeout=timeout, model=model, _skip_consumption=True)
    except Exception as e:
        ok = False
        err = str(e)[:300]
        raise
    finally:
        log_call(
            lane=lane, process_id=process_id,
            task_summary=task_summary or summarize_prompt(prompt),
            trigger_mode=trigger, success=ok, model_name=model,
            prompt=prompt, response=text if ok else None,
            duration_ms=int((time.time() - t0) * 1000),
            error_message=err, metadata=metadata,
        )
    return text


def overview(*, days: int = 30) -> dict:
    ensure_schema()
    cur = _conn().cursor()
    periods = {
        "today": "created_at >= CURRENT_DATE",
        "week": "created_at >= NOW() - INTERVAL '7 days'",
        "month": f"created_at >= NOW() - INTERVAL '{int(days)} days'",
    }
    by_lane: dict[str, dict] = {}
    for label, where in periods.items():
        cur.execute(f"""
            SELECT model_lane,
                   COUNT(*) AS calls,
                   COALESCE(SUM(prompt_chars + response_chars), 0) AS chars,
                   COALESCE(SUM(estimated_cost_usd), 0) AS rel_units,
                   COUNT(*) FILTER (WHERE NOT success) AS failures
            FROM llm_consumption_log WHERE {where}
            GROUP BY model_lane
        """)
        for lane, calls, chars, units, fails in cur.fetchall():
            by_lane.setdefault(lane, {})[label] = {
                "calls": int(calls), "chars": int(chars), "relative_units": float(units or 0),
                "failures": int(fails),
            }
    cur.execute("""
        SELECT process_id, process_name, COUNT(*) AS calls,
               COALESCE(SUM(estimated_cost_usd), 0) AS rel_units,
               MAX(created_at) AS last_used
        FROM llm_consumption_log
        WHERE created_at >= NOW() - INTERVAL '30 days'
        GROUP BY process_id, process_name
        ORDER BY rel_units DESC NULLS LAST
        LIMIT 12
    """)
    top = [{"process_id": r[0], "process_name": r[1], "calls": int(r[2]),
            "relative_units": float(r[3] or 0), "last_used": str(r[4]) if r[4] else None}
           for r in cur.fetchall()]
    return {"by_lane": by_lane, "top_processes": top, "generated_at": datetime.now(timezone.utc).isoformat()}


def list_processes() -> list[dict]:
    ensure_schema()
    reg = {p["id"]: p for p in (_load_registry().get("processes") or []) if p.get("id")}
    policies = (_load_registry().get("lane_policies") or {})
    cur = _conn().cursor()
    cur.execute("SELECT process_id, process_name, category, mode, allowed_lanes, updated_at FROM llm_process_config ORDER BY category, process_name")
    rows = []
    seen = set()
    for r in cur.fetchall():
        pid = r[0]
        seen.add(pid)
        stats = _process_stats(pid)
        meta = reg.get(pid) or {}
        lp = meta.get("lane_policy") or "either"
        rows.append({
            "process_id": pid, "process_name": r[1], "category": r[2], "mode": r[3],
            "allowed_lanes": list(r[4] or []), "updated_at": str(r[5]) if r[5] else None,
            "description": meta.get("description"),
            "lane_policy": lp,
            "lane_policy_label": policies.get(lp) or lp,
            **stats,
        })
    for pid, p in reg.items():
        if pid not in seen:
            cfg = get_process_config(pid)
            lp = p.get("lane_policy") or "either"
            rows.append({**cfg, "description": p.get("description"),
                         "lane_policy": lp, "lane_policy_label": policies.get(lp) or lp,
                         **_process_stats(pid)})
    rows.sort(key=lambda x: (x.get("category") or "", x.get("process_name") or ""))
    return rows


def _process_stats(process_id: str) -> dict:
    try:
        cur = _conn().cursor()
        cur.execute("""
            SELECT COUNT(*), COALESCE(SUM(estimated_cost_usd),0), MAX(created_at),
                   COUNT(*) FILTER (WHERE created_at >= CURRENT_DATE)
            FROM llm_consumption_log WHERE process_id=%s AND created_at >= NOW() - INTERVAL '30 days'
        """, (process_id,))
        r = cur.fetchone()
        return {
            "calls_30d": int(r[0] or 0), "relative_units_30d": float(r[1] or 0),
            "last_used": str(r[2]) if r[2] else None, "calls_today": int(r[3] or 0),
        }
    except Exception:
        return {"calls_30d": 0, "relative_units_30d": 0, "last_used": None, "calls_today": 0}


def recent_logs(*, limit: int = 50, process_id: str | None = None) -> list[dict]:
    ensure_schema()
    cur = _conn().cursor()
    if process_id:
        cur.execute("""
            SELECT id, created_at, model_lane, model_name, process_id, process_name, task_summary,
                   trigger_mode, prompt_chars, response_chars, estimated_cost_usd, success, duration_ms
            FROM llm_consumption_log WHERE process_id=%s
            ORDER BY created_at DESC LIMIT %s
        """, (process_id, limit))
    else:
        cur.execute("""
            SELECT id, created_at, model_lane, model_name, process_id, process_name, task_summary,
                   trigger_mode, prompt_chars, response_chars, estimated_cost_usd, success, duration_ms
            FROM llm_consumption_log ORDER BY created_at DESC LIMIT %s
        """, (limit,))
    cols = ["id", "created_at", "model_lane", "model_name", "process_id", "process_name", "task_summary",
            "trigger_mode", "prompt_chars", "response_chars", "relative_units", "success", "duration_ms"]
    return [dict(zip(cols, (str(v) if k == "created_at" and v else v for k, v in zip(cols, row))))
            for row in cur.fetchall()]


def insights() -> list[dict]:
    """Advisory suggestions for high consumers on automated mode."""
    out = []
    for p in list_processes():
        if p.get("mode") != "automated":
            continue
        u = float(p.get("relative_units_30d") or 0)
        if u >= 5.0 or int(p.get("calls_today") or 0) >= 20:
            out.append({
                "type": "high_consumer",
                "process_id": p["process_id"],
                "message": f"{p.get('process_name')} is Automated with {p.get('calls_30d')} calls / "
                           f"{u:.1f} relative units (30d) — consider Manual mode.",
                "severity": "warning",
            })
    return out