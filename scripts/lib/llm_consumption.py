"""LLM consumption tracking + per-process Automated/Manual gating for OAuth lanes (Grok, ChatGPT) and
metered API lanes (DeepSeek Flash, DeepSeek V4).

OAuth free lanes: fail-open on logging failure (call may still proceed).
Metered DeepSeek paid calls: fail-closed when cost persistence is unavailable.
Manual mode blocks automatic calls and returns ManualRequired for the UI.
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
            allowed_lanes TEXT[] DEFAULT ARRAY['grok','chatgpt','deepseek-flash','deepseek-v4-flash','deepseek-v4-pro','fast','pro','pro_think'],
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
    # Additive migrations for paid-token accounting (safe on existing DBs)
    for stmt in (
        "ALTER TABLE llm_consumption_log ADD COLUMN IF NOT EXISTS relative_units NUMERIC(12,6) DEFAULT 0",
        "ALTER TABLE llm_consumption_log ADD COLUMN IF NOT EXISTS cost_basis TEXT",
        "ALTER TABLE llm_consumption_log ADD COLUMN IF NOT EXISTS pricing_effective_at TEXT",
        "ALTER TABLE llm_consumption_log ADD COLUMN IF NOT EXISTS reasoning_tokens INT",
        "ALTER TABLE llm_consumption_log ADD COLUMN IF NOT EXISTS cache_hit_tokens INT",
        "ALTER TABLE llm_consumption_log ADD COLUMN IF NOT EXISTS cache_miss_tokens INT",
        "ALTER TABLE llm_consumption_log ADD COLUMN IF NOT EXISTS requested_policy TEXT",
        "ALTER TABLE llm_consumption_log ADD COLUMN IF NOT EXISTS executed_policy TEXT",
        "ALTER TABLE llm_consumption_log ADD COLUMN IF NOT EXISTS requested_model_id TEXT",
        "ALTER TABLE llm_consumption_log ADD COLUMN IF NOT EXISTS returned_model TEXT",
        "ALTER TABLE llm_consumption_log ADD COLUMN IF NOT EXISTS thinking TEXT",
        "ALTER TABLE llm_consumption_log ADD COLUMN IF NOT EXISTS reasoning_effort TEXT",
        "ALTER TABLE llm_consumption_log ADD COLUMN IF NOT EXISTS provider_request_id TEXT",
        "ALTER TABLE llm_process_config ADD COLUMN IF NOT EXISTS daily_cost_cap_usd NUMERIC(12,4)",
    ):
        try:
            cur.execute(stmt)
        except Exception:
            try:
                _conn().rollback()
            except Exception:
                pass
            cur = _conn().cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS llm_cost_reservations (
                id BIGSERIAL PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                process_id TEXT NOT NULL,
                projected_usd NUMERIC(12,6) NOT NULL DEFAULT 0,
                actual_usd NUMERIC(12,6),
                status TEXT NOT NULL DEFAULT 'reserved',
                model_id TEXT,
                request_key TEXT,
                metadata_json JSONB
            )""")
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_llm_cost_reservations_process
                ON llm_cost_reservations (process_id, created_at DESC)""")
    except Exception:
        try:
            _conn().rollback()
        except Exception:
            pass
        cur = _conn().cursor()
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
        daily_cap = p.get("daily_soft_cap")
        if "default_mode" in p:
            cur.execute("""
                INSERT INTO llm_process_config (process_id, process_name, category, mode, daily_soft_cap, notes, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (process_id) DO UPDATE SET
                  process_name = EXCLUDED.process_name,
                  category = EXCLUDED.category,
                  mode = EXCLUDED.mode,
                  daily_soft_cap = COALESCE(EXCLUDED.daily_soft_cap, llm_process_config.daily_soft_cap),
                  notes = EXCLUDED.notes,
                  updated_at = NOW()
            """, (pid, p.get("name") or pid, p.get("category"), mode, daily_cap, p.get("description")))
        else:
            cur.execute("""
                INSERT INTO llm_process_config (process_id, process_name, category, mode, daily_soft_cap, notes)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (process_id) DO NOTHING
            """, (pid, p.get("name") or pid, p.get("category"), mode, daily_cap, p.get("description")))
    _conn().commit()


def summarize_prompt(prompt: str, max_len: int = 160) -> str:
    s = re.sub(r"\s+", " ", str(prompt or "")).strip()
    return (s[: max_len - 1] + "…") if len(s) > max_len else s


def is_process_registered(process_id: str) -> bool:
    """True only if process_id appears in llm_process_registry.json."""
    pid = str(process_id or "").strip()
    if not pid:
        return False
    for p in (_load_registry().get("processes") or []):
        if p.get("id") == pid:
            return True
    return False


def _registry_process(process_id: str) -> dict | None:
    pid = str(process_id or "").strip()
    for p in (_load_registry().get("processes") or []):
        if p.get("id") == pid:
            return p
    return None


def _allowed_lanes_from_registry(p: dict) -> list[str]:
    """Explicit allowlist only — never grant the global DEFAULT set to unknown processes.

    Known processes: use allowed_lanes if present; else derive from lane_policy +
    deepseek_allowed_policies only.
    """
    if p.get("allowed_lanes"):
        return [str(x).lower() for x in p["allowed_lanes"]]
    lanes: list[str] = []
    pol = str(p.get("lane_policy") or "either")
    if pol in ("grok_only", "either", "both_preferred", "ensemble"):
        lanes.append("grok")
    if pol in ("chatgpt_only", "either", "both_preferred", "ensemble"):
        lanes.append("chatgpt")
    if pol == "deepseek_only":
        pass
    for ds in p.get("deepseek_allowed_policies") or []:
        u = str(ds).upper()
        lanes.append(str(ds).lower())
        if u == "FAST":
            lanes.extend(["fast", "deepseek-flash", "deepseek-v4-flash"])
        elif u == "FAST_THINK":
            lanes.extend(["fast_think", "deepseek-flash", "deepseek-v4-flash"])
        elif u == "PRO":
            lanes.extend(["pro", "deepseek-v4-pro"])
        elif u == "PRO_THINK":
            lanes.extend(["pro_think", "deepseek-v4-pro"])
        elif u == "PRO_MAX":
            lanes.extend(["pro_max", "deepseek-v4-pro"])
    # de-dupe preserve order
    out: list[str] = []
    for x in lanes:
        if x not in out:
            out.append(x)
    return out


def get_process_config(process_id: str) -> dict:
    pid = str(process_id or "").strip() or "unregistered"
    reg_p = _registry_process(pid)
    if reg_p is None:
        # Fail closed for unknown processes — empty allowlist
        return {
            "process_id": pid,
            "process_name": pid,
            "category": "Unknown",
            "mode": "manual",
            "allowed_lanes": [],
            "deepseek_allowed_policies": [],
            "registered": False,
            "max_input_tokens": None,
            "max_output_tokens": None,
            "daily_soft_cap": None,
            "daily_cost_cap_usd": None,
        }

    allowed = _allowed_lanes_from_registry(reg_p)
    ds_pols = [str(x).upper() for x in (reg_p.get("deepseek_allowed_policies") or [])]
    base = {
        "process_id": pid,
        "process_name": reg_p.get("name") or pid,
        "category": reg_p.get("category"),
        "mode": reg_p.get("default_mode") or _load_registry().get("default_mode") or "manual",
        "allowed_lanes": allowed,
        "deepseek_allowed_policies": ds_pols,
        "daily_soft_cap": reg_p.get("daily_soft_cap"),
        "daily_cost_cap_usd": reg_p.get("daily_cost_cap_usd"),
        "notes": reg_p.get("description"),
        "registered": True,
        "max_input_tokens": reg_p.get("max_input_tokens"),
        "max_output_tokens": reg_p.get("max_output_tokens"),
        "tools_allowed": bool(reg_p.get("tools_allowed", False)),
        "fallback_allowed": bool(reg_p.get("fallback_allowed", False)),
        "advisory_only": bool(reg_p.get("advisory_only", True)),
    }
    # DB mode override when present
    try:
        ensure_schema()
        cur = _conn().cursor()
        cur.execute(
            "SELECT mode, allowed_lanes, daily_soft_cap, daily_cost_cap_usd FROM llm_process_config WHERE process_id=%s",
            (pid,),
        )
        r = cur.fetchone()
        if r:
            if r[0]:
                base["mode"] = r[0]
            # Do not expand allowlist from DB beyond registry for fail-closed
            if r[2] is not None:
                base["daily_soft_cap"] = r[2]
            if r[3] is not None:
                base["daily_cost_cap_usd"] = float(r[3])
    except Exception:
        try:
            _conn().rollback()
        except Exception:
            pass
    return base


DEFAULT_ALLOWED_LANES = [
    "grok", "chatgpt", "local",
    "deepseek-flash", "deepseek-v4-flash", "deepseek-v4-pro",
    "fast", "fast_think", "pro", "pro_think", "pro_max",
]


def sync_process_policies_from_registry(*, force_expand_deepseek: bool = True) -> dict:
    """Non-destructive: create missing process rows and expand allowed_lanes for DeepSeek."""
    ensure_schema()
    reg = _load_registry()
    cur = _conn().cursor()
    created = updated = 0
    for p in reg.get("processes") or []:
        pid = str(p.get("id") or "").strip()
        if not pid:
            continue
        allowed = list(DEFAULT_ALLOWED_LANES)
        for pol in (p.get("deepseek_allowed_policies") or []):
            pl = str(pol).lower()
            if pl not in allowed:
                allowed.append(pl)
        if p.get("deepseek_default_policy"):
            pl = str(p["deepseek_default_policy"]).lower()
            if pl not in allowed:
                allowed.append(pl)
        cost_cap = p.get("daily_cost_cap_usd")
        cur.execute("SELECT allowed_lanes, mode FROM llm_process_config WHERE process_id=%s", (pid,))
        row = cur.fetchone()
        if row is None:
            cur.execute(
                """INSERT INTO llm_process_config
                   (process_id, process_name, category, mode, allowed_lanes, daily_soft_cap, daily_cost_cap_usd, notes, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW())""",
                (pid, p.get("name") or pid, p.get("category"),
                 p.get("default_mode") or reg.get("default_mode") or "manual",
                 allowed, p.get("daily_soft_cap"), cost_cap, p.get("description")),
            )
            created += 1
            continue
        old = [x for x in (row[0] or []) if x != "deepseek-v4"]
        if force_expand_deepseek:
            for lane in allowed:
                if lane not in old:
                    old.append(lane)
        cur.execute(
            """UPDATE llm_process_config SET process_name=%s, category=%s, notes=%s,
               allowed_lanes=%s,
               daily_soft_cap=COALESCE(%s, daily_soft_cap),
               daily_cost_cap_usd=COALESCE(%s, daily_cost_cap_usd),
               updated_at=NOW() WHERE process_id=%s""",
            (p.get("name") or pid, p.get("category"), p.get("description"),
             old, p.get("daily_soft_cap"), cost_cap, pid),
        )
        updated += 1
    _conn().commit()
    return {"ok": True, "created": created, "updated": updated}


def usd_spent_today(process_id: str | None = None) -> float:
    """Observability-only: sum from consumption logs (NOT used for paid cap authority)."""
    ensure_schema()
    cur = _conn().cursor()
    if process_id:
        cur.execute(
            "SELECT COALESCE(SUM(estimated_cost_usd),0) FROM llm_consumption_log "
            "WHERE process_id=%s AND created_at >= CURRENT_DATE "
            "AND COALESCE(cost_basis,'') NOT IN ('relative_units','relative_units_not_usd','')",
            (str(process_id),),
        )
    else:
        cur.execute(
            "SELECT COALESCE(SUM(estimated_cost_usd),0) FROM llm_consumption_log "
            "WHERE created_at >= CURRENT_DATE "
            "AND cost_basis IS NOT NULL AND cost_basis NOT IN ('relative_units','relative_units_not_usd')"
        )
    return float(cur.fetchone()[0] or 0)


# Fixed advisory lock namespace for paid cost ledger (global + per-process keys).
_LEDGER_LOCK_NS = 0x7EAD11C0


def _ledger_lock_keys(process_id: str) -> tuple[int, int]:
    import zlib
    proc_key = zlib.crc32(str(process_id or "").encode("utf-8")) & 0x7FFFFFFF
    return _LEDGER_LOCK_NS, proc_key


def ledger_paid_usd_today(process_id: str | None = None, *, cur=None) -> float:
    """Authoritative paid-cost total for today from the reservation ledger.

    Policy:
      - reserved: count projected_usd (open holds)
      - settled: count actual_usd if set, else projected_usd (conservative)
      - released: count 0 (pre-provider failures do not consume budget)

    Consumption logs are NOT included (avoid double counting).
    """
    own = cur is None
    if own:
        ensure_schema()
        cur = _conn().cursor()
    try:
        if process_id:
            cur.execute(
                """
                SELECT COALESCE(SUM(
                    CASE
                      WHEN status = 'reserved' THEN projected_usd
                      WHEN status = 'settled' THEN COALESCE(actual_usd, projected_usd)
                      ELSE 0
                    END
                ), 0)
                FROM llm_cost_reservations
                WHERE process_id=%s AND created_at >= CURRENT_DATE
                """,
                (str(process_id),),
            )
        else:
            cur.execute(
                """
                SELECT COALESCE(SUM(
                    CASE
                      WHEN status = 'reserved' THEN projected_usd
                      WHEN status = 'settled' THEN COALESCE(actual_usd, projected_usd)
                      ELSE 0
                    END
                ), 0)
                FROM llm_cost_reservations
                WHERE created_at >= CURRENT_DATE
                """
            )
        return float(cur.fetchone()[0] or 0)
    finally:
        if own:
            pass


def ledger_request_count_today(process_id: str, *, cur=None) -> int:
    """Count reserved+settled reservation rows today (request-per-day authority)."""
    own = cur is None
    if own:
        ensure_schema()
        cur = _conn().cursor()
    cur.execute(
        """
        SELECT COUNT(*) FROM llm_cost_reservations
        WHERE process_id=%s AND created_at >= CURRENT_DATE
          AND status IN ('reserved', 'settled')
        """,
        (str(process_id),),
    )
    return int(cur.fetchone()[0] or 0)


def recover_stale_reservations(*, max_age_minutes: int = 30, cur=None) -> int:
    """Conservative recovery: reserved rows older than max_age are settled at projected_usd.

    Documents hang/timeout recovery so open holds cannot pin budget forever while still
    charging conservatively for possibly billable attempts.
    """
    own = cur is None
    if own:
        ensure_schema()
        cur = _conn().cursor()
    cur.execute(
        """
        UPDATE llm_cost_reservations
        SET status='settled',
            actual_usd=COALESCE(actual_usd, projected_usd)
        WHERE status='reserved'
          AND created_at < NOW() - (%s * INTERVAL '1 minute')
        """,
        (int(max_age_minutes),),
    )
    n = cur.rowcount or 0
    if own:
        _conn().commit()
    return int(n)


def reserved_usd_open(process_id: str | None = None) -> float:
    """Open holds only (projected). Prefer ledger_paid_usd_today for cap checks."""
    try:
        ensure_schema()
        cur = _conn().cursor()
        if process_id:
            cur.execute(
                "SELECT COALESCE(SUM(projected_usd),0) FROM llm_cost_reservations "
                "WHERE process_id=%s AND status='reserved' AND created_at >= CURRENT_DATE",
                (str(process_id),),
            )
        else:
            cur.execute(
                "SELECT COALESCE(SUM(projected_usd),0) FROM llm_cost_reservations "
                "WHERE status='reserved' AND created_at >= CURRENT_DATE"
            )
        return float(cur.fetchone()[0] or 0)
    except Exception:
        try:
            _conn().rollback()
        except Exception:
            pass
        return 0.0


def check_cost_cap(
    process_id: str,
    *,
    projected_usd: float = 0.0,
    global_cap: float | None = None,
    cur=None,
) -> dict:
    """Cap check using reservation ledger as the paid authority (not consumption logs)."""
    cfg = get_process_config(process_id)
    if cfg.get("daily_cost_cap_usd") is None:
        for p in (_load_registry().get("processes") or []):
            if p.get("id") == process_id and p.get("daily_cost_cap_usd") is not None:
                cfg["daily_cost_cap_usd"] = p.get("daily_cost_cap_usd")
                break
    proc_cap = cfg.get("daily_cost_cap_usd")
    spent = ledger_paid_usd_today(process_id, cur=cur)
    if proc_cap is not None and (spent + float(projected_usd or 0)) > float(proc_cap):
        return {"allow": False, "reason": "COST_CAP_EXCEEDED", "scope": "process",
                "spent_usd": spent, "cap_usd": float(proc_cap)}
    if global_cap is not None:
        g = ledger_paid_usd_today(None, cur=cur)
        if (g + float(projected_usd or 0)) > float(global_cap):
            return {"allow": False, "reason": "COST_CAP_EXCEEDED", "scope": "global",
                    "spent_usd": g, "cap_usd": float(global_cap)}
    return {"allow": True, "spent_process_usd": spent}


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


def calls_today(process_id: str) -> int:
    """Successful + failed OAuth lane calls logged today for a process."""
    try:
        ensure_schema()
        cur = _conn().cursor()
        cur.execute(
            "SELECT COUNT(*) FROM llm_consumption_log "
            "WHERE process_id=%s AND created_at >= CURRENT_DATE",
            (str(process_id or "").strip() or "unregistered",),
        )
        return int(cur.fetchone()[0] or 0)
    except Exception:
        try:
            _conn().rollback()
        except Exception:
            pass
        return 0


def over_daily_cap(process_id: str, *, extra: int = 0) -> bool:
    """True when today's logged calls (+ optional extra) meet or exceed daily_soft_cap."""
    cfg = get_process_config(process_id)
    cap = cfg.get("daily_soft_cap")
    if cap is None:
        return False
    try:
        cap_n = int(cap)
    except (TypeError, ValueError):
        return False
    if cap_n <= 0:
        return False
    return calls_today(process_id) + max(0, int(extra or 0)) >= cap_n


def should_call(process_id: str, lane: str, *, manual_trigger: bool = False) -> dict:
    """Decision only — does not call the model. Unknown processes: deny."""
    cfg = get_process_config(process_id)
    lane = (lane or "").strip().lower()
    if not cfg.get("registered"):
        return {
            "allow": False, "reason": "PROCESS_NOT_REGISTERED",
            "mode": cfg.get("mode"), "process_id": process_id,
        }
    if lane in ("deepseek-v4", "deepseek_v4"):
        return {"allow": False, "reason": "AMBIGUOUS_LEGACY_LANE", "mode": cfg.get("mode"),
                "process_id": process_id}
    allowed_list = list(cfg.get("allowed_lanes") or [])
    allowed = lane in allowed_list or lane.upper() in {x.upper() for x in allowed_list}
    if not allowed:
        return {
            "allow": False,
            "reason": "POLICY_NOT_ALLOWED",
            "mode": cfg.get("mode"),
            "process_id": process_id,
        }
    if cfg.get("mode") == "manual" and not manual_trigger:
        return {"allow": False, "reason": "manual_mode", "mode": "manual", "process_id": process_id}
    return {"allow": True, "mode": cfg.get("mode"), "process_id": process_id}


def cost_persistence_available() -> bool:
    """True when consumption DB can be used for paid accounting."""
    try:
        ensure_schema()
        cur = _conn().cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        return True
    except Exception:
        try:
            _conn().rollback()
        except Exception:
            pass
        return False


def reserve_projected_cost(
    process_id: str,
    projected_usd: float,
    *,
    model_id: str | None = None,
    metadata: dict | None = None,
    process_config: dict | None = None,
    global_cap: float | None = None,
) -> int:
    """Atomically reserve projected USD + one request slot under a transaction lock.

    process_config MUST be resolved and validated *before* this call (immutable snapshot).
    This function must not call get_process_config (which may rollback) after locks.

    Single transaction:
      1) pg_advisory_xact_lock (global namespace + process key)
      2) recover stale reserved rows (conservative settle)
      3) read ledger paid spend + request counts (using cur only)
      4) enforce process/global USD caps and request-per-day cap
      5) INSERT reservation status=reserved
      6) COMMIT

    Any error after lock acquisition rolls back the entire operation.
    """
    if not cost_persistence_available():
        raise RuntimeError("COST_PERSISTENCE_UNAVAILABLE: paid execution blocked")
    if process_config is None:
        raise RuntimeError("COST_CONFIGURATION_INVALID: process_config required before reservation")
    cfg = process_config
    # Explicit caps required — never treat missing as unlimited
    try:
        proc_cap = float(cfg["daily_cost_cap_usd"])
        soft_n = int(cfg["daily_soft_cap"])
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("COST_CONFIGURATION_INVALID: process caps missing or malformed")
    if proc_cap <= 0 or soft_n <= 0:
        raise RuntimeError("COST_CONFIGURATION_INVALID: process caps must be positive")

    ensure_schema()
    proj = float(projected_usd or 0)
    if proj < 0:
        proj = 0.0

    conn = _conn()
    cur = conn.cursor()
    try:
        ns, pkey = _ledger_lock_keys(process_id)
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (ns,))
        cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (ns, pkey))

        recover_stale_reservations(max_age_minutes=30, cur=cur)

        spent_p = ledger_paid_usd_today(process_id, cur=cur)
        if (spent_p + proj) > proc_cap:
            raise RuntimeError("COST_CAP_EXCEEDED: process cap")

        if global_cap is not None:
            gcap = float(global_cap)
            if gcap <= 0:
                raise RuntimeError("COST_CONFIGURATION_INVALID: global cap malformed")
            spent_g = ledger_paid_usd_today(None, cur=cur)
            if (spent_g + proj) > gcap:
                raise RuntimeError("COST_CAP_EXCEEDED: global cap")

        nreq = ledger_request_count_today(process_id, cur=cur)
        if nreq + 1 > soft_n:
            raise RuntimeError("COST_CAP_EXCEEDED: daily request cap")

        cur.execute(
            """INSERT INTO llm_cost_reservations
               (process_id, projected_usd, status, model_id, metadata_json)
               VALUES (%s,%s,'reserved',%s,%s) RETURNING id""",
            (
                str(process_id),
                proj,
                model_id,
                json.dumps(metadata or {}, default=str)[:2000],
            ),
        )
        rid = int(cur.fetchone()[0])
        conn.commit()
        return rid
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise


def settle_reservation(
    reservation_id: int | None,
    actual_usd: float | None,
    *,
    ok: bool,
    billable_attempt: bool = False,
    projected_fallback: float | None = None,
) -> None:
    """Settle or release a reservation.

    Policy:
      - success: status=settled, actual=actual_usd or projected (conservative if missing)
      - failure before provider send: status=released, actual=0 (no budget consumed)
      - failure after provider send / ambiguous: status=settled, actual=actual or projected
    """
    if not reservation_id:
        return
    try:
        ensure_schema()
        cur = _conn().cursor()
        cur.execute(
            "SELECT projected_usd, status FROM llm_cost_reservations WHERE id=%s FOR UPDATE",
            (int(reservation_id),),
        )
        row = cur.fetchone()
        if not row:
            _conn().commit()
            return
        projected = float(row[0] or 0)
        if ok:
            status = "settled"
            actual = float(actual_usd) if actual_usd is not None else projected
        elif billable_attempt:
            # Conservative: possibly billable provider attempt
            status = "settled"
            if actual_usd is not None:
                actual = float(actual_usd)
            elif projected_fallback is not None:
                actual = float(projected_fallback)
            else:
                actual = projected
        else:
            status = "released"
            actual = 0.0
        cur.execute(
            """UPDATE llm_cost_reservations
               SET actual_usd=%s, status=%s WHERE id=%s""",
            (actual, status, int(reservation_id)),
        )
        _conn().commit()
    except Exception:
        try:
            _conn().rollback()
        except Exception:
            pass


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
    relative_units: float | None = None,
    estimated_cost_usd: float | None = None,
    cost_basis: str | None = None,
    pricing_effective_at: str | None = None,
    reasoning_tokens: int | None = None,
    cache_hit_tokens: int | None = None,
    cache_miss_tokens: int | None = None,
    requested_policy: str | None = None,
    executed_policy: str | None = None,
    requested_model_id: str | None = None,
    returned_model: str | None = None,
    thinking: str | None = None,
    reasoning_effort: str | None = None,
    provider_request_id: str | None = None,
) -> int | None:
    """Persist consumption. relative_units is char-based; estimated_cost_usd is paid-token only."""
    try:
        ensure_schema()
        cfg = get_process_config(process_id)
        pc = len(prompt or "")
        rc = len(response or "")
        rel = relative_units if relative_units is not None else round((pc + rc) / 1000.0, 3)
        # Never store char-relative units in estimated_cost_usd
        cost = float(estimated_cost_usd) if estimated_cost_usd is not None else 0.0
        basis = cost_basis or ("provider_usage_x_registry_snapshot" if estimated_cost_usd is not None else "oauth_free_or_unset")
        meta = dict(metadata or {})
        cur = _conn().cursor()
        cur.execute("""
            INSERT INTO llm_consumption_log
              (model_lane, model_name, process_id, process_name, task_summary, trigger_mode,
               prompt_chars, response_chars, tokens_in, tokens_out, estimated_cost_usd,
               relative_units, reasoning_tokens, cache_hit_tokens, cache_miss_tokens,
               cost_basis, pricing_effective_at, requested_policy, executed_policy,
               requested_model_id, returned_model, thinking, reasoning_effort, provider_request_id,
               success, error_message, duration_ms, metadata_json)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (
            lane, model_name or returned_model or requested_model_id, process_id,
            cfg.get("process_name") or process_id,
            summarize_prompt(task_summary or prompt or ""),
            trigger_mode, pc, rc, tokens_in, tokens_out, cost,
            rel, reasoning_tokens, cache_hit_tokens, cache_miss_tokens,
            basis, pricing_effective_at, requested_policy, executed_policy,
            requested_model_id, returned_model, thinking, reasoning_effort, provider_request_id,
            success, (error_message or "")[:400] if error_message else None,
            duration_ms, json.dumps(meta, default=str)[:4000] if meta else None,
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
    operator_confirmed: bool = False,
    response_json: bool = False,
    output_schema_id: str | None = None,
    max_tokens: int = 2048,
    policy: str | None = None,
    return_provenance: bool = False,
):
    """Check process mode + cost caps; call llm_lane with DeepSeek kwargs; log full provenance.

    When return_provenance=True, returns (text, provenance_dict) instead of text alone.
    """
    import os
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from lib.oauth_lane_status import lane_available

    lane = (lane or "grok").lower()
    process_id = str(process_id or "unregistered")
    meta = dict(metadata or {})
    if operator_confirmed:
        meta["operator_cost_confirmed"] = True
    if policy:
        meta["requested_policy"] = policy
        # Keep exact policy for DeepSeek; llm_lane accepts logical policy names as lanes
        lane = policy.lower() if policy.lower() in (
            "fast", "fast_think", "pro", "pro_think", "pro_max"
        ) else lane

    decision = should_call(process_id, lane, manual_trigger=manual_trigger)
    if not decision.get("allow"):
        if decision.get("reason") == "manual_mode":
            raise ManualRequired(process_id, lane, task_summary or summarize_prompt(prompt), prompt[:500])
        raise RuntimeError(decision.get("reason") or "call not allowed")

    is_deepseek_lane = lane.startswith("deepseek") or lane in (
        "fast", "fast_think", "pro", "pro_think", "pro_max",
    )
    reservation_id = None
    projected = 0.0
    cfg = get_process_config(process_id)
    effective_out = int(max_tokens or 2048)
    effective_in = None
    model_id = model

    if is_deepseek_lane:
        if not cost_persistence_available():
            raise RuntimeError("COST_PERSISTENCE_UNAVAILABLE: paid execution blocked")
        from lib.consumption_run_manual import (
            projected_max_cost_usd, POLICY_TO_MODEL, validate_paid_cap_config,
        )
        # Resolve immutable config + caps BEFORE any reservation transaction/locks
        model_id = model or POLICY_TO_MODEL.get((policy or lane).upper() if policy else "", None)
        if not model_id:
            model_id = "deepseek-v4-pro" if "pro" in lane else "deepseek-v4-flash"

        # Smoke path: require process caps. Non-smoke paid routes also require global cap.
        from lib.consumption_run_manual import SMOKE_PROCESS_ID
        require_global = process_id != SMOKE_PROCESS_ID
        validate_paid_cap_config(cfg, require_global=require_global)

        proc_out = cfg.get("max_output_tokens")
        proc_in = cfg.get("max_input_tokens")
        req_out = int(max_tokens or (proc_out or 2048))
        if proc_out is not None:
            effective_out = min(req_out, int(proc_out))
        else:
            effective_out = req_out
        effective_out = max(1, int(effective_out))

        if proc_in is not None:
            effective_in = int(proc_in)
            est_in = max(1, (len(prompt or "") + 3) // 4)
            if est_in > effective_in:
                raise RuntimeError(
                    f"INPUT_LIMIT_EXCEEDED: prompt ~{est_in} tokens exceeds process max_input_tokens={effective_in}"
                )
        else:
            effective_in = max(1, (len(prompt or "") + 3) // 4)

        projected = projected_max_cost_usd(
            model_id=model_id,
            max_input_tokens=int(effective_in),
            max_output_tokens=int(effective_out),
        )
        gcap_raw = os.environ.get("LLM_GLOBAL_DAILY_USD_CAP")
        try:
            gcap = float(gcap_raw) if gcap_raw not in (None, "") else None
        except (TypeError, ValueError):
            gcap = None
        if require_global and (gcap is None or gcap <= 0):
            raise RuntimeError("COST_CONFIGURATION_INVALID: global daily USD cap required")

        reservation_id = reserve_projected_cost(
            process_id, projected, model_id=model_id,
            process_config=cfg,
            # Smoke may omit global when env unset (gcap=None); non-smoke required gcap above.
            global_cap=gcap,
            metadata={
                "lane": lane, "policy": policy,
                "effective_max_tokens": effective_out,
                "effective_max_input_tokens": effective_in,
            },
        )
    else:
        gcap_raw = os.environ.get("LLM_GLOBAL_DAILY_USD_CAP")
        gcap = float(gcap_raw) if gcap_raw not in (None, "") else None
        cap = check_cost_cap(process_id, projected_usd=0.0, global_cap=gcap)
        if not cap.get("allow"):
            raise RuntimeError(f"COST_CAP_EXCEEDED: {cap}")

    if lane in ("grok", "chatgpt") and not lane_available(lane):
        raise RuntimeError(f"{lane} OAuth lane unavailable — check grok-oauth-proxy / chatgpt-oauth-proxy")
    import llm_lane
    trigger = "manual" if manual_trigger else ("automated" if decision.get("mode") == "automated" else "manual")
    t0 = time.time()
    err = None
    text = ""
    ok = True
    prov: dict = {}
    # Billable only if DeepSeek client reports request_sent / possibly_billable
    billable_attempt = False
    try:
        result = llm_lane.generate(
            prompt, lane=lane, timeout=timeout, model=model, _skip_consumption=True,
            operator_confirmed=operator_confirmed or bool(meta.get("operator_cost_confirmed")),
            response_json=response_json or bool(output_schema_id),
            metadata=meta, return_provenance=True,
            max_tokens=effective_out,
        )
        if isinstance(result, tuple):
            text, prov = result[0], (result[1] or {})
        else:
            text = result
        tradeai_ok = (prov.get("_tradeai") or {}) if isinstance(prov, dict) else {}
        # Success implies the network request completed
        billable_attempt = bool(
            tradeai_ok.get("request_sent")
            or tradeai_ok.get("possibly_billable")
            or (is_deepseek_lane and ok)
        )
    except Exception as e:
        ok = False
        err = str(e)[:300]
        # AUTH/policy before send → request_sent False → release
        # timeout/network after send → possibly_billable True → settle projected
        billable_attempt = bool(
            getattr(e, "possibly_billable", False) or getattr(e, "request_sent", False)
        )
        if getattr(e, "estimated_cost_usd", None) is not None:
            # stash for settle below via local
            meta["_exc_estimated_cost_usd"] = e.estimated_cost_usd
        raise
    finally:
        usage = prov.get("usage") or {}
        tradeai = prov.get("_tradeai") or prov
        is_deepseek = bool(tradeai.get("requested_model_id") or tradeai.get("returned_model")
                           or is_deepseek_lane)
        actual_cost = tradeai.get("estimated_cost_usd") if is_deepseek else None
        if actual_cost is None and meta.get("_exc_estimated_cost_usd") is not None:
            actual_cost = meta.get("_exc_estimated_cost_usd")
        if is_deepseek_lane and reservation_id is not None:
            settle_cost = float(actual_cost) if actual_cost is not None else None
            settle_reservation(
                reservation_id,
                settle_cost,
                ok=ok,
                billable_attempt=billable_attempt,
                projected_fallback=projected,
            )
        try:
            log_call(
                lane=lane, process_id=process_id,
                task_summary=task_summary or summarize_prompt(prompt),
                trigger_mode=trigger, success=ok,
                model_name=tradeai.get("returned_model") or tradeai.get("requested_model_id") or model,
                prompt=prompt, response=text if ok else None,
                tokens_in=usage.get("prompt_tokens"),
                tokens_out=usage.get("completion_tokens"),
                duration_ms=int((time.time() - t0) * 1000),
                error_message=err,
                metadata={
                    **meta,
                    **{k: v for k, v in tradeai.items() if k != "usage"},
                    "effective_max_tokens": effective_out,
                    "reservation_id": reservation_id,
                },
                estimated_cost_usd=actual_cost if is_deepseek else None,
                cost_basis=tradeai.get("cost_basis") if is_deepseek else "oauth_free_or_unset",
                pricing_effective_at=tradeai.get("pricing_effective_at"),
                reasoning_tokens=usage.get("reasoning_tokens"),
                cache_hit_tokens=usage.get("prompt_cache_hit_tokens"),
                cache_miss_tokens=usage.get("prompt_cache_miss_tokens"),
                requested_policy=tradeai.get("requested_policy") or policy,
                executed_policy=tradeai.get("executed_policy"),
                requested_model_id=tradeai.get("requested_model_id"),
                returned_model=tradeai.get("returned_model"),
                thinking=tradeai.get("thinking"),
                reasoning_effort=tradeai.get("reasoning_effort"),
                provider_request_id=tradeai.get("request_id"),
            )
        except Exception:
            # Observability only for paid; ledger already settled/released
            pass
    if return_provenance:
        tradeai = prov.get("_tradeai") or {}
        return text, {
            "usage": prov.get("usage") or {},
            "requested_policy": tradeai.get("requested_policy") or policy,
            "executed_policy": tradeai.get("executed_policy"),
            "requested_model_id": tradeai.get("requested_model_id"),
            "returned_model": tradeai.get("returned_model"),
            "thinking": tradeai.get("thinking"),
            "reasoning_effort": tradeai.get("reasoning_effort"),
            "request_id": tradeai.get("request_id") or tradeai.get("client_request_id"),
            "estimated_cost_usd": tradeai.get("estimated_cost_usd"),
            "latency_ms": tradeai.get("latency_ms"),
            "fallback_used": tradeai.get("fallback_used", False),
            "effective_max_tokens": effective_out,
        }
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


def registry_lane_map() -> dict:
    """Process_id → lane_policy plus human labels (for UI fallback when API cache is stale)."""
    reg = _load_registry()
    return {
        "processes": {
            str(p.get("id")): p.get("lane_policy") or "either"
            for p in (reg.get("processes") or []) if p.get("id")
        },
        "policy_labels": dict(reg.get("lane_policies") or {}),
    }


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