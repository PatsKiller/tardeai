#!/usr/bin/env python3
"""Runtime mode + migration-capability gate for Telegram notification normalization.

Single source of truth for "is the normalized pipeline allowed to change behaviour".
Everything that touches delivery must ask here first.

Modes
-----
OFF     Pre-normalization behaviour, byte-for-byte. Legacy router + legacy sender.
        Must not require any new table. This is the default.
SHADOW  Evaluate and persist normalized decisions when the migration is present, but
        delivery is unchanged and the new transport is never used for sending.
        Shadow persistence failures are non-fatal — legacy delivery still happens.
ACTIVE  Normalized outbox and logical destinations own delivery.

Resolution order (first hit wins):
    1. TELEGRAM_NORMALIZATION_MODE env var
    2. config/operator_alert_policy.yaml -> telegram_normalization.runtime_mode
    3. legacy boolean telegram_normalization.runtime_enabled (true -> ACTIVE)
    4. OFF

Fail-closed: any unreadable config, unparseable YAML, or unrecognised value resolves
to OFF and is reported through `mode_diagnostics()` rather than raised. A misconfigured
file must never escalate delivery authority.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

MODE_OFF = "OFF"
MODE_SHADOW = "SHADOW"
MODE_ACTIVE = "ACTIVE"
VALID_MODES = (MODE_OFF, MODE_SHADOW, MODE_ACTIVE)

ENV_VAR = "TELEGRAM_NORMALIZATION_MODE"
_REPO = Path(__file__).resolve().parent.parent
POLICY_PATH = _REPO / "config" / "operator_alert_policy.yaml"

# Every table the normalized pipeline writes. ACTIVE requires all of them.
REQUIRED_TABLES = (
    "alert_notification_events",
    "alert_notification_deliveries",
    "alert_digest_queue",
    "operator_alert_preferences",
    "operator_alert_preference_audit",
)

_lock = threading.Lock()
_cache: dict[str, Any] = {"mode": None, "why": None, "tables": None}


class MigrationUnavailable(RuntimeError):
    """ACTIVE mode requested but the outbox migration has not been applied.

    Raised instead of returning a bare False so an operator sees why an alert could
    not be normalized, rather than the alert vanishing.
    """


def _read_policy() -> tuple[dict, str | None]:
    """(telegram_normalization block, error). Never raises."""
    try:
        import yaml
    except Exception as e:                                    # pragma: no cover
        return {}, f"pyyaml_unavailable:{type(e).__name__}"
    try:
        if not POLICY_PATH.is_file():
            return {}, "policy_file_missing"
        data = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8")) or {}
    except Exception as e:
        return {}, f"policy_unreadable:{type(e).__name__}"
    block = data.get("telegram_normalization")
    if not isinstance(block, dict):
        return {}, "telegram_normalization_block_missing"
    return block, None


def resolve_mode(*, refresh: bool = False) -> tuple[str, str]:
    """(mode, reason). Cached; pass refresh=True after changing config."""
    with _lock:
        if not refresh and _cache["mode"] is not None:
            return _cache["mode"], _cache["why"]

        mode, why = MODE_OFF, "default_off"
        raw_env = (os.getenv(ENV_VAR) or "").strip().upper()
        if raw_env:
            if raw_env in VALID_MODES:
                mode, why = raw_env, f"env:{ENV_VAR}"
            else:
                mode, why = MODE_OFF, f"env_invalid_value:{raw_env[:24]}"
        else:
            block, err = _read_policy()
            if err:
                mode, why = MODE_OFF, err
            else:
                raw = block.get("runtime_mode")
                if raw is not None:
                    # YAML 1.1 coerces bare OFF/ON/NO/YES to booleans, so an unquoted
                    # `runtime_mode: OFF` arrives here as False. Map booleans back to a
                    # mode name instead of reporting a bogus "invalid value: FALSE";
                    # True is intentionally NOT ACTIVE — enabling delivery must be a
                    # spelled-out word, never a truthy accident.
                    if isinstance(raw, bool):
                        mode = MODE_OFF if raw is False else MODE_SHADOW
                        why = f"policy:runtime_mode_yaml_bool_{str(raw).lower()}"
                    else:
                        candidate = str(raw).strip().upper()
                        if candidate in VALID_MODES:
                            mode, why = candidate, "policy:runtime_mode"
                        else:
                            mode, why = MODE_OFF, f"policy_invalid_value:{candidate[:24]}"
                elif block.get("runtime_enabled") is True:
                    # Legacy boolean kept working, but it can only reach SHADOW —
                    # turning ACTIVE on must be an explicit, named decision.
                    mode, why = MODE_SHADOW, "policy:legacy_runtime_enabled_true"
                else:
                    mode, why = MODE_OFF, "policy:runtime_mode_absent"

        _cache["mode"], _cache["why"] = mode, why
        return mode, why


def get_mode(*, refresh: bool = False) -> str:
    return resolve_mode(refresh=refresh)[0]


def is_off() -> bool:
    return get_mode() == MODE_OFF


def is_shadow() -> bool:
    return get_mode() == MODE_SHADOW


def is_active() -> bool:
    return get_mode() == MODE_ACTIVE


def tables_available(conn=None, *, refresh: bool = False) -> bool:
    """True when every REQUIRED_TABLES relation exists.

    Uses to_regclass, which answers precisely and cheaply. Deliberately narrow: a
    connection failure is reported as "unavailable" for capability purposes but is
    NOT conflated with a query error inside a delivery path — callers that need the
    distinction use missing_tables().
    """
    return not missing_tables(conn, refresh=refresh)


def missing_tables(conn=None, *, refresh: bool = False) -> list[str]:
    """Names of required tables that do not exist. Empty list == fully migrated."""
    with _lock:
        if not refresh and _cache["tables"] is not None:
            return list(_cache["tables"])
    missing: list[str] = []
    own = False
    try:
        if conn is None:
            import sys
            sys.path.insert(0, str(_REPO / "scripts"))
            from db_adapter import _get_conn
            conn = _get_conn()
            own = True
        if conn is None:
            missing = list(REQUIRED_TABLES)
        else:
            with conn.cursor() as cur:
                for t in REQUIRED_TABLES:
                    cur.execute("SELECT to_regclass(%s)", (f"public.{t}",))
                    row = cur.fetchone()
                    if not row or row[0] is None:
                        missing.append(t)
    except Exception:
        # Cannot determine -> treat as not migrated. Callers in OFF/SHADOW keep
        # legacy delivery; ACTIVE raises MigrationUnavailable rather than dropping.
        missing = list(REQUIRED_TABLES)
    finally:
        if own and conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
    with _lock:
        _cache["tables"] = list(missing)
    return list(missing)


def require_active_capability(conn=None) -> None:
    """Raise MigrationUnavailable if ACTIVE is selected without the migration."""
    if get_mode() != MODE_ACTIVE:
        return
    missing = missing_tables(conn)
    if missing:
        raise MigrationUnavailable(
            "telegram normalization is ACTIVE but these tables are missing: "
            + ", ".join(missing)
            + ". Apply migrations/2026_07_28_alert_notification_outbox.sql or set "
            f"{ENV_VAR}=OFF."
        )


def can_persist_shadow(conn=None) -> bool:
    """SHADOW persists only when the migration is present; absence is not an error."""
    return get_mode() in (MODE_SHADOW, MODE_ACTIVE) and not missing_tables(conn)


def mode_diagnostics(conn=None) -> dict[str, Any]:
    mode, why = resolve_mode()
    missing = missing_tables(conn)
    return {
        "mode": mode,
        "reason": why,
        "default": MODE_OFF,
        "env_var": ENV_VAR,
        "policy_path": str(POLICY_PATH),
        "tables_required": list(REQUIRED_TABLES),
        "tables_missing": missing,
        "migration_applied": not missing,
        "delivery_owner": {
            MODE_OFF: "legacy_router_and_legacy_sender",
            MODE_SHADOW: "legacy_router_and_legacy_sender (normalized decisions persisted only)",
            MODE_ACTIVE: "normalized_outbox",
        }[mode],
    }


def reset_cache() -> None:
    """Tests only."""
    with _lock:
        _cache["mode"] = _cache["why"] = _cache["tables"] = None


if __name__ == "__main__":
    import json
    print(json.dumps(mode_diagnostics(), indent=2, default=str))
