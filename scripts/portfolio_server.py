"""
portfolio_server.py — v2.0 (April 10, 2026)

Endpoints:
  GET  /                            → redirect to command center
  GET  /data/portfolios/state/*     → serve state JSON files
  GET  /reports/*                   → serve HTML reports
  GET  /assets/*                    → serve YAML/config files
  GET  /scripts/*                   → serve Python scripts (for MCP inspection)
  POST /api/import                  → import parsed positions data → holdings.json
  POST /api/import-transactions     → append new transactions → trade_journal.json
  POST /api/run-portfolio           → trigger linux_launchers/run_portfolio.sh
  POST /api/run-trade-ai            → trigger linux_launchers/run_continuous.sh
  POST /api/run-pipeline            → whitelisted pipeline trigger (daily/weekly/monthly_lite/price_cache)
  POST /api/yaml-apply              → apply YAML advisor suggestions
  GET  /api/health                  → server health check

IMPORT CONTRACT (/api/import):
  Body: {
    account_key:  str,          # e.g. "fidelity_401k"
    as_of:        str,          # ISO date e.g. "2026-04-08"
    holdings:     List[Dict],   # parsed holdings
    total_value:  float,
    source:       str           # "schwab_csv" | "fidelity_pdf"
  }
  Returns: {ok, holdings_written, total_value, portfolio_total, as_of}
  Errors:  400 (missing fields), 409 (data older than current), 500 (write error)

  After a successful import, sets a "pending_pipeline_run" flag in holdings.json.
  The Command Center reads this flag and shows a yellow banner:
  "Holdings updated — pipeline not yet run · Run Now"
"""

import http.server
import socketserver
import json
import os
import subprocess
import sys
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs

PORT = 7777
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
PROCESS_STARTED_AT = datetime.now().astimezone().isoformat(timespec="seconds")


def _read_pin_sha(root: Path) -> str:
    for name in ("SOURCE_COMMIT", "BUILD_SHA", "GIT_SHA"):
        p = root / name
        try:
            sha = p.read_text(encoding="utf-8").strip().split()[0]
        except OSError:
            continue
        if sha:
            return sha
    return ""


LOADED_PIN_SHA = _read_pin_sha(PROJECT_ROOT)


def _boot_stamp_path() -> Path:
    override = os.getenv("PORTFOLIO_SERVER_BOOT_STAMP_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "state" / "tradeai" / "portfolio_server_boot.json"


def _data_as_of(data: dict) -> str | None:
    for candidate in (
        data.get("data_as_of"),
        data.get("source_as_of"),
        data.get("as_of"),
        (data.get("data") or {}).get("data_as_of") if isinstance(data.get("data"), dict) else None,
        (data.get("data") or {}).get("as_of") if isinstance(data.get("data"), dict) else None,
    ):
        if candidate:
            return str(candidate)
    return None


def _age_seconds(as_of: str | None) -> float | None:
    if not as_of:
        return None
    try:
        parsed = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return round(max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds()), 3)
    except (TypeError, ValueError):
        return None

# Make the repo ROOT importable so `from scripts.lib.X` resolves alongside the
# existing `from lib.X` convention (scripts/ and scripts/lib are also on sys.path).
# The CIO subsystem (Phases 0-10) uses the `scripts.`-prefixed form; without the
# root on sys.path the web server raises "No module named 'scripts'".
import sys as _sys_root  # noqa: E402
if str(PROJECT_ROOT) not in _sys_root.path:
    _sys_root.path.insert(0, str(PROJECT_ROOT))

# CC v3 stale-bundle check. The injected inline script and /v3/cc-boot.js BOTH compare
# this against sessionStorage['cc_v3_build'] and reload when it differs. They must
# therefore resolve to the SAME string — one shared fallback, never two literals.
#
# They used to hardcode different defaults ('1.5' inline, '1.6' in cc-boot). That is
# inert while build-meta.json carries a ui_version, but the 2026-07-28 rebuild emitted
# a build-meta.json WITHOUT that key, so each path fell back to its own literal and the
# two scripts disagreed permanently: inline set the key to 1.5 and reloaded, cc-boot saw
# 1.5 != 1.6, set 1.6 and reloaded, forever. /v3 became an infinite reload loop — a
# blank page with a _cc_reload timestamp spinning in the URL. sessionStorage only
# prevents a loop when both readers agree on the expected value.
CC_V3_UI_VERSION_FALLBACK = "1.6"


def _cc_v3_ui_version() -> str:
    """Single source of truth for the SPA bundle version both boot paths compare."""
    meta = PROJECT_ROOT / "apps" / "command-center-v3" / "dist" / "build-meta.json"
    try:
        import json as _json
        return str(_json.loads(meta.read_text()).get("ui_version") or CC_V3_UI_VERSION_FALLBACK)
    except Exception:
        return CC_V3_UI_VERSION_FALLBACK

# v3.1 (WS-F): load env BEFORE class definitions so operational knobs like
# DASHBOARD_MAX_CONCURRENCY / DASHBOARD_SEM_TIMEOUT_SEC are actually reachable
# (the semaphore is sized at class-creation time; api_v2's load_dotenv runs too
# late for it). Never overrides values already set by systemd.
# S4: tmpfs SM render first, then disk .env fallback.
try:
    import sys as _sys_eb
    _lib = str(PROJECT_ROOT / "scripts" / "lib")
    if _lib not in _sys_eb.path:
        _sys_eb.path.insert(0, _lib)
    from env_bootstrap import load_env
    load_env()
except Exception:
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
    except Exception:
        pass

# ── api_v2 hot-reload guard ──────────────────────────────────────────────────
# Reload api_v2 ONLY when its source file actually changes — not on every request.
# Reloading the large api_v2 module on every /api/v2/ request, on a threaded server
# under the dashboard's concurrent polling, previously deadlocked the whole server
# (process alive but serving nothing). mtime-gated + lock-guarded: at most one thread
# reloads, and only when the file changed. Preserves hot-reload-on-edit for dev.
_api_v2_lock = threading.Lock()
_api_v2_mtime = [0.0]
_api_rp_mtime = [0.0]

def _get_api_v2():
    import importlib, sys, api_v2 as _mod
    try:
        _m = os.path.getmtime(_mod.__file__)
    except Exception:
        _m = 0.0
    try:
        import reports_portal as _rp
        _rm = os.path.getmtime(_rp.__file__)
    except Exception:
        _rm = 0.0
    if _m != _api_v2_mtime[0] or _rm != _api_rp_mtime[0]:
        # NON-BLOCKING acquire (2026-07-01): only the ONE thread that wins the lock reloads; every other
        # request thread serves the current module immediately instead of blocking here. Reloading the
        # ~28k-line api_v2 is slow, and _api_v2_mtime[0] isn't updated until it finishes — so a blocking
        # `with _api_v2_lock` queued EVERY concurrent request behind that one slow reload (a git pull under
        # load → 200+ threads stuck, CLOSE-WAIT pileup, dashboard wedged). Serving briefly-stale code for
        # the sub-second reload window is strictly better than wedging a live trading dashboard.
        if _api_v2_lock.acquire(blocking=False):
            try:
                if _m != _api_v2_mtime[0] or _rm != _api_rp_mtime[0]:
                    if _rm != _api_rp_mtime[0]:
                        if "reports_portal" in sys.modules:
                            importlib.reload(sys.modules["reports_portal"])
                        _api_rp_mtime[0] = _rm
                    if _m != _api_v2_mtime[0]:
                        importlib.reload(_mod)
                        _api_v2_mtime[0] = _m
                    # Pilot submit stack (intent router + transport) is NOT inside api_v2 — reload it
                    # whenever api_v2 reloads so long-lived servers pick up stop-replace fixes.
                    for _pilot_mod in (
                        "brokers.intent_submit_router",
                        "schwab_transport",
                        "brokers.protective_stop_pilot",
                        # Decision-authority modules that api_v2 calls into — reload
                        # them WITH api_v2 so a signature change (e.g. the
                        # current_snapshot param on evaluate_action) is picked up
                        # rather than silently swallowed by the handler's try/except.
                        "decision_action_policy",
                        "packet_invalidation",
                        "decision_packet",
                        "shadow_decision_service",
                    ):
                        if _pilot_mod in sys.modules:
                            importlib.reload(sys.modules[_pilot_mod])
            finally:
                _api_v2_lock.release()
        # else: another thread is mid-reload → return the current module now, pick up the new one next request
    return _mod

# Phase P1: Load .env into os.environ so db_adapter sees DB_* keys when run as systemd service
_env_file = PROJECT_ROOT / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
HOLDINGS_PATH = STATE_DIR / "holdings.json"
PERSONAL_PATH = STATE_DIR / "personal_situation.json"
PERSONAL_BACKUP_DIR = PROJECT_ROOT / "file_backups"


# ── Personal Situation helpers ────────────────────────────────────────────────

def _compute_derived_fields(data: dict) -> dict:
    """Populate computed_from fields with their derived values.
    Mutates a copy of the data and returns it. Never modifies the source file."""
    import copy
    data = copy.deepcopy(data)
    fields = data.get("fields", {})

    def get_val(field_name):
        f = fields.get(field_name, {})
        return f.get("current")

    # age: years from dob to today
    if "age" in fields:
        dob_str = get_val("dob")
        if dob_str:
            try:
                dob = date.fromisoformat(dob_str)
                today = date.today()
                age = (today - dob).days / 365.25
                fields["age"]["current"] = round(age, 1)
                fields["age"]["last_updated"] = today.isoformat()
            except (ValueError, TypeError):
                fields["age"]["current"] = None

    # ssdi_monthly_computed: ssdi_annual / 12
    if "ssdi_monthly_computed" in fields:
        ssdi = get_val("ssdi_annual")
        if ssdi is not None:
            fields["ssdi_monthly_computed"]["current"] = round(ssdi / 12, 2)
            fields["ssdi_monthly_computed"]["last_updated"] = date.today().isoformat()

    # golden_window_open: dob + disability_end_age years
    if "golden_window_open" in fields:
        dob_str = get_val("dob")
        end_age = get_val("disability_end_age")
        if dob_str and end_age is not None:
            try:
                dob = date.fromisoformat(dob_str)
                days = int(float(end_age) * 365.25)
                open_date = date.fromordinal(dob.toordinal() + days)
                fields["golden_window_open"]["current"] = open_date.isoformat()
                fields["golden_window_open"]["last_updated"] = date.today().isoformat()
            except (ValueError, TypeError):
                fields["golden_window_open"]["current"] = None

    # golden_window_close: dob + rmd_age years
    if "golden_window_close" in fields:
        dob_str = get_val("dob")
        rmd = get_val("rmd_age")
        if dob_str and rmd is not None:
            try:
                dob = date.fromisoformat(dob_str)
                days = int(float(rmd) * 365.25)
                close_date = date.fromordinal(dob.toordinal() + days)
                fields["golden_window_close"]["current"] = close_date.isoformat()
                fields["golden_window_close"]["last_updated"] = date.today().isoformat()
            except (ValueError, TypeError):
                fields["golden_window_close"]["current"] = None

    # roth_conversion_remaining_2026
    if "roth_conversion_remaining_2026" in fields:
        ceiling = get_val("next_bracket_ceiling") or 0
        ssdi = get_val("ssdi_annual") or 0
        sch_c = get_val("schedule_c_gross") or 0
        fed_ded = get_val("federal_itemized") or 0
        se_ded = get_val("se_tax_deduction") or 0
        ytd = get_val("roth_conversion_ytd_2026") or 0
        taxable_ssdi = ssdi * 0.85
        taxable_income = taxable_ssdi + sch_c - fed_ded - se_ded
        remaining = max(0, ceiling - taxable_income - ytd)
        fields["roth_conversion_remaining_2026"]["current"] = round(remaining, 2)
        fields["roth_conversion_remaining_2026"]["last_updated"] = date.today().isoformat()

    return data


def _validate_field_update(field_name: str, new_value, field_def: dict) -> tuple:
    """Validate a proposed field update. Returns (is_valid, coerced_value_or_error)."""
    if not field_def.get("editable", True):
        return False, f"{field_name} is computed, not editable"

    dtype = field_def.get("data_type")
    try:
        if dtype in ("currency", "integer"):
            return True, int(float(new_value))
        elif dtype == "percentage":
            return True, float(new_value)
        elif dtype == "date":
            date.fromisoformat(str(new_value))
            return True, str(new_value)
        elif dtype == "enum":
            options = field_def.get("options", [])
            if str(new_value) not in options:
                return False, f"must be one of {options}"
            return True, str(new_value)
        elif dtype == "boolean":
            s = str(new_value).lower().strip()
            if s in ("true", "1", "yes", "y"):
                return True, True
            if s in ("false", "0", "no", "n"):
                return True, False
            return False, "must be boolean"
        elif dtype == "string":
            return True, str(new_value)
        else:
            return False, f"unknown data_type {dtype}"
    except (ValueError, TypeError) as e:
        return False, f"invalid value for {dtype}: {e}"


def _reconstruct_personal_as_of(target_date: str) -> dict:
    """Phase 8D-1: Reconstruct personal_situation state as of target_date.

    Walks personal_history (via personal_timeline view) backwards. For each
    editable field, finds the most recent entry with effective_date <= target_date.
    Falls back to current JSON value if it predates target_date.

    Re-runs _compute_derived_fields against reconstructed state so computed
    fields (age, golden_window_*, ssdi_monthly_computed, roth_remaining)
    reflect the target_date context.

    Returns: {ok, data, as_of, fields_changed, fields_no_data} on success
             {ok: False, error: str} on failure
    """
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    try:
        from db_adapter import USE_DB, get_personal_snapshot_at_date
    except Exception as e:
        return {"ok": False, "error": f"db_adapter import failed: {e}"}

    if not PERSONAL_PATH.exists():
        return {"ok": False, "error": "personal_situation.json not found"}

    if not USE_DB:
        return {"ok": False, "error": "Postgres unavailable - reconstruction requires DB"}

    base_data = json.loads(PERSONAL_PATH.read_text(encoding="utf-8"))
    fields = base_data.get("fields", {})

    rows = get_personal_snapshot_at_date(target_date)

    if rows is None:
        return {"ok": False, "error": "Postgres query failed"}

    historical = {r["field_name"]: r for r in (rows or [])}

    # Reconstruct field-by-field
    import copy
    reconstructed_fields = {}
    fields_changed = 0
    fields_no_data = 0

    for field_name, field_def in fields.items():
        if not isinstance(field_def, dict):
            reconstructed_fields[field_name] = field_def
            continue

        new_field = copy.deepcopy(field_def)

        # Computed fields will be overwritten by _compute_derived_fields - skip for now
        if not field_def.get("editable", True):
            reconstructed_fields[field_name] = new_field
            continue

        if field_name in historical:
            hist = historical[field_name]
            hist_value = hist["value"]  # JSONB - already deserialized by psycopg2
            current_value = field_def.get("current")

            if hist_value != current_value:
                new_field["current"] = hist_value
                eff_date = hist["effective_date"]
                new_field["last_updated"] = eff_date.isoformat() if hasattr(eff_date, "isoformat") else str(eff_date)
                new_field["_reconstructed"] = True
                new_field["_reconstructed_from"] = "history"
                new_field["_reconstructed_source"] = hist.get("source", "unknown")
                fields_changed += 1
            else:
                new_field["_reconstructed"] = False
        else:
            current_last_updated = field_def.get("last_updated", "")
            if current_last_updated and current_last_updated <= target_date:
                # Current value predates target - it WAS active at target_date
                new_field["_reconstructed"] = False
            else:
                # Field had no value at target_date
                new_field["current"] = None
                new_field["last_updated"] = None
                new_field["_reconstructed"] = True
                new_field["_reconstructed_from"] = "not_yet_set"
                fields_no_data += 1

        reconstructed_fields[field_name] = new_field

    result_data = {
        "schema_version": base_data.get("schema_version", 1),
        "owner": base_data.get("owner", "John W. Whiting"),
        "fields": reconstructed_fields,
        "_as_of": target_date,
        "_reconstructed_at": datetime.now().isoformat(),
        "_fields_changed": fields_changed,
        "_fields_no_data": fields_no_data,
    }

    # Re-run computed fields against reconstructed state
    result_data = _compute_derived_fields(result_data)

    return {
        "ok": True,
        "data": result_data,
        "as_of": target_date,
        "fields_changed": fields_changed,
        "fields_no_data": fields_no_data,
    }


def _handle_personal_as_of(handler, target_date: str):
    """GET /api/personal/as_of/<YYYY-MM-DD> - Phase 8D-1 reconstruction endpoint."""
    # Validate date format
    try:
        from datetime import date as _date
        _date.fromisoformat(target_date)
    except (ValueError, TypeError):
        json_response(handler, 400, {
            "ok": False,
            "error": f"Invalid date format: {target_date}. Use YYYY-MM-DD."
        })
        return

    result = _reconstruct_personal_as_of(target_date)
    code = 200 if result.get("ok") else 500
    json_response(handler, code, result)


def _handle_personal_history(handler, field_name: str):
    """GET /api/personal/history/<field_name> - Phase 8D-2 field timeline endpoint."""
    if not field_name:
        json_response(handler, 400, {"ok": False, "error": "field_name is required"})
        return

    # Validate field exists in JSON schema
    if not PERSONAL_PATH.exists():
        json_response(handler, 404, {"ok": False, "error": "personal_situation.json not found"})
        return

    try:
        ps_data = json.loads(PERSONAL_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        json_response(handler, 500, {"ok": False, "error": f"JSON parse error: {e}"})
        return

    fields = ps_data.get("fields", {})
    if field_name not in fields:
        json_response(handler, 404, {"ok": False, "error": f"field '{field_name}' not found"})
        return

    field_def = fields[field_name]
    metadata = {
        "field": field_name,
        "data_type": field_def.get("data_type"),
        "category": field_def.get("category"),
        "description": field_def.get("description"),
        "editable": field_def.get("editable", True),
        "current_value": field_def.get("current"),
        "last_updated": field_def.get("last_updated"),
    }

    # Query Postgres for history
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    try:
        from db_adapter import USE_DB, get_personal_field_history
    except Exception as e:
        json_response(handler, 500, {"ok": False, "error": f"db_adapter import failed: {e}"})
        return

    if not USE_DB:
        json_response(handler, 200, {
            "ok": True, **metadata,
            "history": [], "row_count": 0,
            "note": "Postgres unavailable — no history data"
        })
        return

    rows = get_personal_field_history(field_name)

    if rows is None:
        json_response(handler, 500, {"ok": False, "error": "Postgres query failed"})
        return

    # Serialize dates/timestamps
    history = []
    for row in rows:
        eff = row.get("effective_date")
        rec = row.get("recorded_at")
        history.append({
            "value": row.get("value"),
            "effective_date": eff.isoformat() if hasattr(eff, "isoformat") else str(eff) if eff else None,
            "recorded_at": rec.isoformat() if hasattr(rec, "isoformat") else str(rec) if rec else None,
            "note": row.get("note", ""),
            "source": row.get("source", ""),
        })

    # Summary stats
    first_change = history[0]["recorded_at"] if history else None
    latest_change = history[-1]["recorded_at"] if history else None

    json_response(handler, 200, {
        "ok": True, **metadata,
        "history": history,
        "row_count": len(history),
        "first_change": first_change,
        "latest_change": latest_change,
    })


def _handle_personal_read(handler):
    """GET /api/personal/read — return personal situation with computed fields."""
    try:
        if not PERSONAL_PATH.exists():
            json_response(handler, 404, {"ok": False, "error": "personal_situation.json not found"})
            return
        raw = json.loads(PERSONAL_PATH.read_text(encoding="utf-8"))
        populated = _compute_derived_fields(raw)
        json_response(handler, 200, {"ok": True, "data": populated})
    except Exception as e:
        json_response(handler, 500, {"ok": False, "error": str(e)})


def _handle_personal_write(handler, raw_body: bytes):
    """POST /api/personal/write — validate, append history, write."""
    try:
        body = json.loads(raw_body.decode("utf-8", errors="replace")) if raw_body else {}
        updates = body.get("updates", {})
        note = body.get("note", "")

        if not updates:
            json_response(handler, 400, {"ok": False, "error": "no updates in body"})
            return
        if not PERSONAL_PATH.exists():
            json_response(handler, 404, {"ok": False, "error": "personal_situation.json not found"})
            return

        data = json.loads(PERSONAL_PATH.read_text(encoding="utf-8"))
        fields = data.get("fields", {})

        # Validate all updates BEFORE writing any
        errors = []
        coerced = {}
        for field_name, new_value in updates.items():
            if field_name not in fields:
                errors.append(f"{field_name}: unknown field")
                continue
            ok, result = _validate_field_update(field_name, new_value, fields[field_name])
            if not ok:
                errors.append(f"{field_name}: {result}")
            else:
                coerced[field_name] = result

        if errors:
            json_response(handler, 400, {"ok": False, "errors": errors})
            return

        # Backup current file
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = PERSONAL_BACKUP_DIR / f"personal_{ts}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / "personal_situation.json"
        backup_path.write_bytes(PERSONAL_PATH.read_bytes())

        # Apply updates with history append
        today = date.today().isoformat()
        changes = []
        for field_name, new_value in coerced.items():
            f = fields[field_name]
            old_value = f.get("current")
            if old_value != new_value:
                f.setdefault("history", []).append({
                    "value": old_value,
                    "date": f.get("last_updated", today),
                    "note": note or f"superseded by edit on {today}"
                })
                f["current"] = new_value
                f["last_updated"] = today
                changes.append({"field": field_name, "from": old_value, "to": new_value})

        data["generated_at"] = datetime.now().isoformat()
        PERSONAL_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

        # Phase P1: Dual-write changes to personal_history table (non-blocking)
        try:
            sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from db_adapter import USE_DB, save_personal_history_entry
            if USE_DB:
                for change in changes:
                    fn = change["field"]
                    f_def = fields.get(fn, {})
                    save_personal_history_entry(
                        field_name=fn,
                        value=json.dumps(change["to"]),
                        data_type=f_def.get("data_type", "unknown"),
                        category=f_def.get("category", "unknown"),
                        effective_date=today,
                        note=note or f"set via modal on {today}",
                        source="modal_edit",
                    )
        except Exception as db_err:
            print(f"  [personal] Postgres dual-write failed (JSON saved OK): {db_err}")

        # Invalidate AI caches that depend on personal situation (Phase 4)
        try:
            _sd = PROJECT_ROOT / "data" / "portfolios" / "state"
            for _stale in ["ai_roth_conversion.json", "ai_analysis_cache.json"]:
                _sf = _sd / _stale
                if _sf.exists():
                    _sf.unlink()
            print(f"  [personal] Invalidated AI caches (Roth + analysis)")
        except Exception:
            pass

        json_response(handler, 200, {
            "ok": True, "changes": changes,
            "backup": str(backup_path), "changed_count": len(changes)
        })
    except Exception as e:
        json_response(handler, 500, {"ok": False, "error": str(e)})


# ── Helpers ───────────────────────────────────────────────────────────────────

def read_holdings() -> dict:
    if HOLDINGS_PATH.exists():
        try:
            data = json.loads(HOLDINGS_PATH.read_text(encoding="utf-8"))
            try:
                import sys as _sys
                if str(PROJECT_ROOT / "scripts") not in _sys.path:
                    _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
                from phase2_snapshot_lock import lock_portfolio_totals
                data = lock_portfolio_totals(data, project_root=PROJECT_ROOT)
            except Exception as _e:
                print(f"[server] WARNING snapshot lock failed: {_e}")
            return data
        except Exception:
            pass
    return {"holdings": [], "account_summaries": {}, "portfolio_totals": {}}


def write_holdings(data: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    # MANDATORY wipe-guard: never zero/overwrite a good holdings snapshot with a bad payload.
    from holdings_guard import protected_holdings_write
    protected_holdings_write(data, source="portfolio_server.write_holdings", target_path=str(HOLDINGS_PATH))
    # ROOT: sold positions must not keep source='portfolio' rows (HELD badge on watchlist).
    try:
        from sync_portfolio_watchlist_membership import sync_portfolio_watchlist_membership
        sync_portfolio_watchlist_membership(data)
    except Exception as _e:
        print(f"  [write_holdings] portfolio watchlist membership sync failed: {_e}")


def _nan_safe(obj):
    """Recursively convert float NaN/Inf -> None so output is valid JSON (browsers reject NaN)."""
    import math
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _nan_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_nan_safe(v) for v in obj]
    return obj


# Process-level body cache for ETag-bearing responses (trade-ai ~1.7MB etc.).
# Keyed by ETag → {raw, gz}. Avoids re-json.dumps + re-gzip on every concurrent poll
# when the browser hasn't sent If-None-Match yet (or first load of a new tab).
_JSON_BODY_CACHE = {}
_JSON_BODY_CACHE_LOCK = threading.Lock()
_JSON_BODY_CACHE_MAX = 8


def _stamp_serving(handler, data):
    """Class guard: every /api/v3 JSON names the process, the loaded pin, and disk pin.

    Stops a 2-day in-memory overlay being served as current with no indicator.
    """
    if not isinstance(data, dict):
        return data
    path = str(getattr(handler, "path", "") or "")
    if "?" in path:
        path = path.split("?", 1)[0]
    if not path.startswith("/api/v3/"):
        return data
    if isinstance(data.get("_serving"), dict):
        return data
    disk = _read_pin_sha(Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT")
    data_as_of = _data_as_of(data)
    data["_serving"] = {
        "schema": "ServingFreshness@v1",
        "authority": "READ_ONLY_ADVISORY",
        "process_started_at": PROCESS_STARTED_AT,
        "source_pin": disk or None,
        "loaded_pin": LOADED_PIN_SHA or None,
        "loaded_pin_sha": LOADED_PIN_SHA or None,
        "current_pin_sha": disk or None,
        "data_as_of": data_as_of,
        "cache_age": _age_seconds(data_as_of),
        "pin_match": bool(LOADED_PIN_SHA) and LOADED_PIN_SHA == disk,
    }
    return data


def json_response(handler, status: int, data: dict) -> None:
    # Phase 203 fix: never emit bare NaN/Infinity — Python json allows them by default but they are
    # INVALID JSON and browser JSON.parse() rejects the whole payload (was blanking the v3 scanner).
    # Fast path uses allow_nan=False (raises on NaN); only sanitize recursively when NaN is present.
    # RI v3.1 (WS-A): routes may attach "__etag__" (top level or inside data["data"]). If the client
    # sent a matching If-None-Match we answer 304 BEFORE any json.dumps/gzip — that serialize+compress
    # of MB-scale payloads on every poll was the real CPU cost behind the server_busy storms.
    data = _stamp_serving(handler, data)
    etag = None
    if isinstance(data, dict):
        if "__etag__" in data:
            etag = data.pop("__etag__")
        elif isinstance(data.get("data"), dict) and "__etag__" in data["data"]:
            etag = data["data"].pop("__etag__")
    serving = data.get("_serving") if isinstance(data, dict) else None
    cache_key = etag
    if etag and isinstance(serving, dict):
        # A pin change must never reuse a body serialized under the old pin.
        # Age is intentionally bucketed so the large-body cache remains useful.
        age_bucket = int(float(serving.get("cache_age") or 0) // 60)
        cache_key = f"{etag}|{serving.get('source_pin')}|{age_bucket}"
    if etag and status == 200:
        try:
            inm = (handler.headers.get("If-None-Match") or "") if getattr(handler, "headers", None) else ""
        except Exception:
            inm = ""
        if inm.strip() == etag:
            handler.send_response(304)
            handler.send_header("ETag", etag)
            handler.send_header("Access-Control-Allow-Origin", "*")
            handler.send_header("Connection", "close")
            handler.end_headers()
            return
    want_gzip = False
    try:
        ae = (handler.headers.get("Accept-Encoding") or "") if getattr(handler, "headers", None) else ""
        want_gzip = "gzip" in ae.lower()
    except Exception:
        want_gzip = False

    body = None
    use_gzip = False
    # Reuse pre-serialized body when ETag is known (trade-ai multi-MB path).
    if etag and status == 200:
        with _JSON_BODY_CACHE_LOCK:
            cached = _JSON_BODY_CACHE.get(cache_key)
        if cached:
            if want_gzip and cached.get("gz") is not None:
                body, use_gzip = cached["gz"], True
            elif cached.get("raw") is not None:
                body, use_gzip = cached["raw"], False

    if body is None:
        try:
            raw_body = json.dumps(data, default=str, allow_nan=False).encode("utf-8")
        except ValueError:
            raw_body = json.dumps(_nan_safe(data), default=str, allow_nan=False).encode("utf-8")
        # Gzip large JSON over the wire (RI/trade-ai are multi-MB; Tailscale + concurrent polls was
        # saturating request threads and wedging "Reconnecting…" — 2026-07-16).
        # compresslevel 1: CPU-cheap; concurrent gzip of multi-MB JSON at level 4
        # was saturating the request semaphore (server_busy 503 storms).
        gz_body = None
        if len(raw_body) >= 4096:
            try:
                import gzip
                gz_body = gzip.compress(raw_body, compresslevel=1)
            except Exception:
                gz_body = None
        if etag and status == 200:
            with _JSON_BODY_CACHE_LOCK:
                if cache_key not in _JSON_BODY_CACHE and len(_JSON_BODY_CACHE) >= _JSON_BODY_CACHE_MAX:
                    # drop an arbitrary oldest-ish entry
                    try:
                        _JSON_BODY_CACHE.pop(next(iter(_JSON_BODY_CACHE)))
                    except Exception:
                        _JSON_BODY_CACHE.clear()
                _JSON_BODY_CACHE[cache_key] = {"raw": raw_body, "gz": gz_body}
        if want_gzip and gz_body is not None:
            body, use_gzip = gz_body, True
        else:
            body, use_gzip = raw_body, False

    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    if etag and status == 200:
        handler.send_header("ETag", etag)
    if use_gzip:
        handler.send_header("Content-Encoding", "gzip")
        handler.send_header("Vary", "Accept-Encoding")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Connection", "close")
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
        pass  # client gone — do not escalate to 500 handler


_AGENT_RUNTIME_READ_PREFIX = "/api/v3/agent-runtime"
_AGENT_MATURITY_READ_PREFIX = "/api/v3/agent-maturity"
_ACTIVE_TRADER_READ_PREFIX = "/api/v3/active-trader"


def _is_agent_runtime_read_path(path: str) -> bool:
    return (
        path == _AGENT_RUNTIME_READ_PREFIX
        or path.startswith(_AGENT_RUNTIME_READ_PREFIX + "/")
        or path == _AGENT_MATURITY_READ_PREFIX
        or path.startswith(_AGENT_MATURITY_READ_PREFIX + "/")
    )


def _is_active_trader_read_path(path: str) -> bool:
    return path == _ACTIVE_TRADER_READ_PREFIX or path.startswith(_ACTIVE_TRADER_READ_PREFIX + "/")


def _agent_runtime_read_handle(method: str, path: str, raw_query):
    """Delegate to the read-only agent-runtime boot module.

    Returns ``(status, body)`` for any agent-runtime read path, or None otherwise.
    Fails closed to an honest zero-authority 503 so a misconfigured reader can
    never crash the server or leak internals.
    """
    try:
        _scripts_dir = str(PROJECT_ROOT / "scripts")
        if _scripts_dir not in sys.path:
            sys.path.insert(0, _scripts_dir)
        import agent_runtime_read_boot as _ar_boot
        query = {}
        if raw_query:
            query = {k: (v[0] if isinstance(v, list) and len(v) == 1 else v) for k, v in raw_query.items()}
        # agent-maturity first paint must not wait on a hung Postgres connect.
        if str(path or "").startswith("/api/v3/agent-maturity"):
            from lib.cc_request_bound import run_bounded
            try:
                return run_bounded(_ar_boot.handle, method, path, query, timeout_s=3.0)
            except TimeoutError:
                # Live connect/read hung. Repo evidence is ~20ms — serve that
                # instead of an empty 503 so the maturity board still paints.
                try:
                    from agent_runtime.read_http import _dispatch_maturity
                    status, body = _dispatch_maturity(method, path, None)
                    if isinstance(body, dict):
                        body = dict(body)
                        body["degraded"] = True
                        body["detail"] = "live maturity reader exceeded 3s bound; repository evidence only"
                    return status, body
                except Exception:
                    return 503, {
                        "contract": "agent-maturity-read-api-v1",
                        "read_only": True,
                        "kind": "timeout",
                        "data": None,
                        "authority": {
                            "mutation": False, "provider_call": False, "service_control": False,
                            "schedule_change": False, "financial_action": False,
                        },
                        "detail": "agent-maturity exceeded 3s connect/read bound",
                    }
        return _ar_boot.handle(method, path, query)
    except Exception:
        # Honest zero-authority 503; never surface an exception to the client.
        return 503, {
            "contract": "agent-runtime-command-center-read-api-v1",
            "read_only": True,
            "kind": "not_connected",
            "data": None,
            "authority": {
                "mutation": False, "provider_call": False, "service_control": False,
                "schedule_change": False, "financial_action": False,
            },
            "detail": "agent-runtime read API is unavailable",
        }


def _active_trader_read_handle(method: str, path: str, raw_query):
    """Delegate to Active Trader Stage 0 read-only boot (no live orders / canary).

    Always returns a Stage 0 envelope with write:false and canary:false.
    """
    try:
        _scripts_dir = str(PROJECT_ROOT / "scripts")
        if _scripts_dir not in sys.path:
            sys.path.insert(0, _scripts_dir)
        import active_trader_read_boot as _at_boot
        query = {}
        if raw_query:
            query = {k: (v[0] if isinstance(v, list) and len(v) == 1 else v) for k, v in raw_query.items()}
        result = _at_boot.handle(method, path, query)
        if result is not None:
            return result
        return 404, {
            "contract": "active-trader-stage0-read-api-v1",
            "stage": 0,
            "write": False,
            "canary": False,
            "read_only": True,
            "detail": "not found",
        }
    except Exception:
        return 503, {
            "contract": "active-trader-stage0-read-api-v1",
            "stage": 0,
            "write": False,
            "canary": False,
            "read_only": True,
            "kind": "unavailable",
            "detail": "active-trader Stage 0 read API is unavailable",
        }


def _is_active_trader_session_path(path: str) -> bool:
    try:
        _scripts_dir = str(PROJECT_ROOT / "scripts")
        if _scripts_dir not in sys.path:
            sys.path.insert(0, _scripts_dir)
        import active_trader.session_http as _sh
        return _sh.is_session_path(path)
    except Exception:
        p = (path or "").rstrip("/")
        return p.startswith("/api/v3/active-trader/session-drafts") or p.startswith("/api/v3/active-trader/sessions")


def _active_trader_session_handle(method, path, query, body):
    """Delegate to the ActiveTrader SESSION CONTROL plane (POST-capable, simulation-only, live disabled).

    Writes SESSION-authorization state only — no live adapter, no real 2FA/credential, no real order.
    """
    try:
        _scripts_dir = str(PROJECT_ROOT / "scripts")
        if _scripts_dir not in sys.path:
            sys.path.insert(0, _scripts_dir)
        import active_trader_session_boot as _sb
        q = {}
        if query:
            q = {k: (v[0] if isinstance(v, list) and len(v) == 1 else v) for k, v in query.items()}
        return _sb.handle(method, path, q, body)
    except Exception:
        return 503, {"contract": "active-trader-p3-session-control-v1", "kind": "unavailable",
                     "read_only": False, "write": False, "live": False,
                     "detail": "session control plane unavailable"}


def _send_agent_runtime_json(handler, status: int, data: dict) -> None:
    """Dedicated emitter for the agent-runtime read surface.

    Same-origin only: it deliberately does NOT send a permissive
    Access-Control-Allow-Origin header (unlike json_response), and marks the
    payload no-store so read snapshots are never cached.
    """
    body = json.dumps(data, default=str, allow_nan=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Connection", "close")
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
        pass


def _content_type_for_path(path: Path) -> str:
    """MIME type for static downloads — PDF/DOCX must not default to text/html."""
    import mimetypes
    ext = path.suffix.lower()
    explicit = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
        ".json": "application/json",
        ".js": "application/javascript",
        ".css": "text/css",
        ".html": "text/html; charset=utf-8",
        ".htm": "text/html; charset=utf-8",
        ".yaml": "text/plain; charset=utf-8",
        ".yml": "text/plain; charset=utf-8",
        ".py": "text/plain; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
        ".csv": "text/csv; charset=utf-8",
        ".log": "text/plain; charset=utf-8",
    }
    if ext in explicit:
        return explicit[ext]
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def serve_file(handler, path: Path) -> None:
    if not path.exists() or not path.is_file():
        handler.send_error(404, f"Not found: {path.name}")
        return
    ctype = _content_type_for_path(path)
    data = path.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    ext = path.suffix.lower()
    if ext == ".pdf":
        handler.send_header("Content-Disposition", f'inline; filename="{path.name}"')
    elif ext in (".docx", ".doc", ".xlsx", ".pptx"):
        handler.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
    # Cache: HTML pages no-cache, hashed assets cache forever
    if ext == ".html":
        handler.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
    elif ext in (".js", ".css") and "-" in path.stem:
        handler.send_header("Cache-Control", "public, max-age=31536000, immutable")
    else:
        handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    handler.wfile.write(data)


# ── Import handler ────────────────────────────────────────────────────────────

def _parse_csv_to_import(body: dict) -> dict:
    """Parse raw Schwab/Fidelity CSV text into the structured format handle_import() expects.

    Schwab CSVs have metadata lines before the header:
      "Positions for Rollover IRA ...as of 04/30/2026..."
      ""
      "Symbol","Description","Quantity","Price",...

    The parser finds the header row by looking for a line containing 'symbol'.
    """
    import re
    from datetime import date as _date

    csv_text = body.get("csv_text", "")
    import_type = body.get("import_type", "schwab_positions")
    filename = body.get("filename", "")

    # Determine account from filename or import_type
    fname_lower = filename.lower()
    if "rollover" in fname_lower or "roll" in fname_lower:
        account_key = "schwab_rollover_ira"
    elif "roth" in fname_lower:
        account_key = "schwab_roth"
    elif "individual" in fname_lower or "taxable" in fname_lower or "brokerage" in fname_lower:
        account_key = "schwab_taxable"
    elif "fidelity" in fname_lower or "401" in fname_lower or import_type == "fidelity_positions":
        account_key = "fidelity_rollover_ira"
    else:
        account_key = "schwab_rollover_ira"

    # ── CSV line tokenizer (handles quoted fields with embedded commas) ──
    def parse_csv_line(line):
        cells = []
        cur = ""
        in_q = False
        for ch in line:
            if ch == '"':
                in_q = not in_q
            elif ch == ',' and not in_q:
                cells.append(cur.strip())
                cur = ""
            else:
                cur += ch
        cells.append(cur.strip())
        return cells

    lines = csv_text.replace("\ufeff", "").split("\n")
    lines = [l.rstrip("\r") for l in lines if l.strip()]

    # Extract as_of date from header metadata (e.g., "...as of 04/30/2026...")
    as_of = str(_date.today())
    for l in lines[:5]:
        m = re.search(r'(\d{2})/(\d{2})/(\d{4})', l)
        if m:
            as_of = f"{m.group(3)}-{m.group(1)}-{m.group(2)}"
            break

    # Find header row — must contain "symbol" somewhere
    header_idx = -1
    for i, l in enumerate(lines):
        low = l.replace('"', '').lower()
        if ('symbol' in low or 'ticker' in low) and ('quantity' in low or 'shares' in low or 'description' in low):
            header_idx = i
            break

    if header_idx < 0:
        raise ValueError("Could not find header row. Expected columns: Symbol, Quantity, Price, Market Value")

    headers = [h.lower().strip() for h in parse_csv_line(lines[header_idx])]
    # Schwab uses verbose headers like "Qty (Quantity)", "Mkt Val (Market Value)", "Gain $ (Gain/Loss $)"
    sym_idx = next((i for i, h in enumerate(headers) if h == 'symbol'), -1)
    qty_idx = next((i for i, h in enumerate(headers) if 'quantity' in h or 'qty' in h), -1)
    price_idx = next((i for i, h in enumerate(headers) if h == 'price' or h == 'last price'), -1)
    mv_idx = next((i for i, h in enumerate(headers) if 'market value' in h or 'mkt val' in h or 'current value' in h), -1)
    name_idx = next((i for i, h in enumerate(headers) if h == 'description' or h == 'name'), -1)
    cb_idx = next((i for i, h in enumerate(headers) if 'cost basis' in h), -1)
    gl_idx = next((i for i, h in enumerate(headers) if 'gain' in h and '$' in h), -1)

    if sym_idx < 0:
        raise ValueError(f"No 'Symbol' column found. Headers: {headers}")

    print(f"  [csv-parse] Header at line {header_idx}: {headers[:8]}...")

    def parse_num(s):
        if not s or s in ('--', 'N/A', 'n/a', '', 'Incomplete'):
            return 0.0
        cleaned = re.sub(r'[$,%]', '', s).replace(',', '').strip()
        if not cleaned or not re.match(r'^-?[\d.]+$', cleaned):
            return 0.0
        return float(cleaned)

    _CASH_SYMS = {"CASH", "CASH & CASH INVESTMENTS", "CASH & CASH EQUIVALENTS",
                  "SNAXX", "SWVXX", "VMFXX", "FDRXX", "SPRXX", "MMKT", "SPAXX", "FZFXX"}

    holdings = []
    total_value = 0.0

    for i in range(header_idx + 1, len(lines)):
        row = parse_csv_line(lines[i])
        if len(row) <= sym_idx:
            continue
        sym = row[sym_idx].upper().strip()
        if not sym or sym == 'SYMBOL' or sym == 'ACCOUNT TOTAL' or sym == 'POSITIONS TOTAL' or len(sym) > 20:
            continue
        # Skip CUSIP numbers (all digits) — not a ticker
        if sym.isdigit():
            continue

        shares = parse_num(row[qty_idx]) if qty_idx >= 0 and qty_idx < len(row) else 0
        price = parse_num(row[price_idx]) if price_idx >= 0 and price_idx < len(row) else 0
        mv = parse_num(row[mv_idx]) if mv_idx >= 0 and mv_idx < len(row) else 0
        name = row[name_idx].strip() if name_idx >= 0 and name_idx < len(row) else ""
        cb = parse_num(row[cb_idx]) if cb_idx >= 0 and cb_idx < len(row) else 0
        gl = parse_num(row[gl_idx]) if gl_idx >= 0 and gl_idx < len(row) else 0

        is_cash = sym in _CASH_SYMS or 'CASH' in sym

        if is_cash:
            # Cash line: market_value is the cash amount
            if mv <= 0:
                mv = parse_num(row[price_idx]) if price_idx >= 0 and price_idx < len(row) else 0
            if mv > 0:
                holdings.append({
                    "symbol": "CASH", "name": "Cash & Cash Investments",
                    "company": "Cash & Cash Investments",
                    "shares": mv, "price": 1.0, "market_value": mv,
                    "day_change": 0.0, "day_change_pct": 0.0,
                    "cost_basis": mv, "gain_loss": 0.0,
                    "account": account_key, "is_cash": True,
                })
                total_value += mv
            continue

        if mv == 0 and shares > 0 and price > 0:
            mv = round(shares * price, 2)

        holdings.append({
            "symbol": sym, "name": name, "company": name,
            "shares": shares, "price": price, "market_value": mv,
            "day_change": 0.0, "day_change_pct": 0.0,
            "cost_basis": cb, "gain_loss": gl,
            "account": account_key, "is_cash": False,
        })
        total_value += mv

    if not holdings:
        raise ValueError("No valid positions found in CSV")

    print(f"  [csv-parse] Parsed {len(holdings)} positions, total ${total_value:,.2f}, account={account_key}")

    return {
        "account_key": account_key,
        "as_of": as_of,
        "holdings": holdings,
        "total_value": round(total_value, 2),
        "source": f"csv_import_{import_type}",
        "import_type": import_type,
        "filename": filename,
    }


def _parse_txn_csv(body: dict) -> dict:
    """Parse raw Schwab Transactions CSV into structured format for handle_import_transactions().

    Schwab transaction CSV headers:
      "Date","Action","Symbol","Description","Quantity","Price","Fees & Comm","Amount"
    """
    import re

    csv_text = body.get("csv_text", "")
    filename = body.get("filename", "")

    # Determine account from filename
    fname_lower = filename.lower()
    if "rollover" in fname_lower:
        acct_key = "schwab_rollover_ira"
    elif "roth" in fname_lower:
        acct_key = "schwab_roth"
    elif "individual" in fname_lower or "taxable" in fname_lower or "brokerage" in fname_lower:
        acct_key = "schwab_taxable"
    else:
        acct_key = "schwab_rollover_ira"

    def parse_csv_line(line):
        cells = []
        cur = ""
        in_q = False
        for ch in line:
            if ch == '"':
                in_q = not in_q
            elif ch == ',' and not in_q:
                cells.append(cur.strip())
                cur = ""
            else:
                cur += ch
        cells.append(cur.strip())
        return cells

    lines = csv_text.replace("\ufeff", "").split("\n")
    lines = [l.rstrip("\r") for l in lines if l.strip()]

    # Find header row
    header_idx = -1
    for i, l in enumerate(lines):
        low = l.replace('"', '').lower()
        if 'date' in low and ('action' in low or 'symbol' in low):
            header_idx = i
            break

    if header_idx < 0:
        raise ValueError("Could not find transaction header row. Expected: Date, Action, Symbol columns.")

    headers = [h.lower().strip() for h in parse_csv_line(lines[header_idx])]
    date_idx = next((i for i, h in enumerate(headers) if h == 'date' or 'trade date' in h), -1)
    action_idx = next((i for i, h in enumerate(headers) if h == 'action' or h == 'type' or 'transaction' in h), -1)
    sym_idx = next((i for i, h in enumerate(headers) if h == 'symbol' or h == 'ticker'), -1)
    qty_idx = next((i for i, h in enumerate(headers) if 'quantity' in h or 'qty' in h or 'shares' in h), -1)
    price_idx = next((i for i, h in enumerate(headers) if h == 'price' or 'exec price' in h), -1)
    amt_idx = next((i for i, h in enumerate(headers) if 'amount' in h or 'total' in h or 'net' in h), -1)
    desc_idx = next((i for i, h in enumerate(headers) if 'description' in h or 'desc' in h), -1)

    def parse_num(s):
        if not s or s in ('--', 'N/A', ''):
            return 0.0
        cleaned = re.sub(r'[$,+]', '', s).strip()
        if not cleaned or not re.match(r'^-?[\d.]+$', cleaned):
            return 0.0
        return float(cleaned)

    txns = []
    for i in range(header_idx + 1, len(lines)):
        row = parse_csv_line(lines[i])
        if date_idx < 0 or date_idx >= len(row):
            continue
        date_raw = row[date_idx].strip()
        if not date_raw or not re.search(r'\d', date_raw):
            continue

        # Normalize date MM/DD/YYYY → YYYY-MM-DD
        dm = re.match(r'(\d{1,2})/(\d{1,2})/(\d{4})', date_raw)
        trade_date = f"{dm.group(3)}-{dm.group(1).zfill(2)}-{dm.group(2).zfill(2)}" if dm else date_raw

        action = row[action_idx].strip() if action_idx >= 0 and action_idx < len(row) else ""
        symbol = (row[sym_idx].upper().strip() if sym_idx >= 0 and sym_idx < len(row) else "").strip()
        qty = parse_num(row[qty_idx]) if qty_idx >= 0 and qty_idx < len(row) else 0
        price = parse_num(row[price_idx]) if price_idx >= 0 and price_idx < len(row) else 0
        amount = parse_num(row[amt_idx]) if amt_idx >= 0 and amt_idx < len(row) else 0
        desc = row[desc_idx].strip()[:60] if desc_idx >= 0 and desc_idx < len(row) else action

        if not trade_date or not action:
            continue

        txns.append({
            "date": trade_date,
            "action": action,
            "symbol": symbol or "—",
            "quantity": abs(qty),
            "price": price,
            "amount": amount,
            "description": desc,
            "account": acct_key,
        })

    if not txns:
        raise ValueError("No valid transactions found in CSV")

    print(f"  [txn-parse] Parsed {len(txns)} transactions, account={acct_key}")
    return {"transactions": txns, "import_type": "schwab_transactions", "filename": filename}


def handle_import(body: dict) -> tuple:
    """
    Write imported positions to holdings.json.

    Rules:
    1. account_key, as_of, holdings, total_value are required
    2. as_of must not be older than current data for this account
    3. Holdings for the account are completely replaced
    4. Account summary is updated
    5. Portfolio total is recomputed
    6. pending_pipeline_run flag is set to True
    7. Returns (status_code, response_dict)
    """
    # Validate required fields
    required = ["account_key", "as_of", "holdings", "total_value"]
    missing = [f for f in required if f not in body]
    if missing:
        return 400, {"error": f"Missing required fields: {missing}"}

    account_key = body["account_key"]
    new_as_of = body["as_of"]
    new_holdings = body["holdings"]
    new_total = float(body["total_value"])
    source = body.get("source", "import")

    # Backup before import
    try:
        import shutil
        _bak_dir = PROJECT_ROOT / "file_backups" / f"holdings_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        _bak_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(HOLDINGS_PATH, _bak_dir / "holdings.json")
    except Exception:
        pass

    # Load current state
    current = read_holdings()

    # Check referential integrity: don't import older data
    current_as_of = (current.get("account_summaries", {})
                     .get(account_key, {}).get("as_of"))
    if current_as_of and new_as_of < current_as_of:
        return 409, {
            "error": f"Import date {new_as_of} is older than current "
                     f"data {current_as_of} for {account_key}. "
                     "Download a more recent statement."
        }

    # Replace all holdings for this account
    existing_other = [
        h for h in current.get("holdings", [])
        if h.get("account") != account_key
    ]
    # Ensure account key is set on all incoming holdings
    # Mark cash/money-market positions so repricers never treat them as stocks
    _CASH_SYMS = {"CASH", "CASH & CASH INVESTMENTS", "MMKT", "SNAXX", "SWVXX", "VMFXX", "SPRXX", "FDRXX"}
    for h in new_holdings:
        h["account"] = account_key
        sym = (h.get("symbol") or "").upper().strip()
        if sym in _CASH_SYMS or h.get("is_cash"):
            h["is_cash"] = True
            h["price"] = 1
            h["market_value"] = round(float(h.get("shares") or h.get("market_value") or 0), 2)
            h["day_change"] = 0.0
            h["day_change_pct"] = 0.0

    current["holdings"] = existing_other + new_holdings

    # Update account summary
    if "account_summaries" not in current:
        current["account_summaries"] = {}
    if account_key not in current["account_summaries"]:
        current["account_summaries"][account_key] = {}

    current["account_summaries"][account_key].update({
        "total_value": new_total,
        "reported_total_value": new_total,
        "reported_total_as_of": new_as_of,
        "holdings_count": len(new_holdings),
        "as_of": new_as_of,
        "last_import": datetime.now().isoformat(),
        "source": source,
    })

    # Recompute portfolio total
    portfolio_total = round(
        sum(v.get("total_value", 0)
            for v in current["account_summaries"].values()), 2
    )
    if "portfolio_totals" not in current:
        current["portfolio_totals"] = {}
    current["portfolio_totals"]["total_value"] = portfolio_total
    current["portfolio_totals"]["as_of"] = new_as_of

    # Set pending_pipeline_run flag — tells Command Center to show banner
    current["pending_pipeline_run"] = True
    current["pending_pipeline_run_since"] = datetime.now().isoformat()
    current["pending_pipeline_run_account"] = account_key

    # Write back
    try:
        write_holdings(current)
    except Exception as e:
        return 500, {"error": f"Failed to write holdings.json: {e}"}

    print(f"  [import] {account_key}: {len(new_holdings)} holdings | "
          f"${new_total:,.2f} | as_of={new_as_of}")
    print(f"  [import] Portfolio total: ${portfolio_total:,.2f}")

    return 200, {
        "ok": True,
        "account_key": account_key,
        "holdings_written": len(new_holdings),
        "total_value": new_total,
        "portfolio_total": portfolio_total,
        "as_of": new_as_of,
        "pending_pipeline_run": True,
    }


def handle_import_transactions(body: dict) -> tuple:
    """
    Append new transactions to trade_journal in holdings.json.
    Deduplicates by: date|action|symbol|abs(quantity).
    """
    if "transactions" not in body:
        return 400, {"error": "Missing 'transactions' field"}

    current = read_holdings()
    existing_journal = current.get("trade_journal", [])

    # Build dedup set from existing
    def dedup_key(t):
        qty = abs(float(t.get("quantity", 0) or 0))
        return (f"{t.get('date','')}|{t.get('action','')}|"
                f"{t.get('symbol','')}|{qty:.3f}|{t.get('account','')}")

    existing_keys = {dedup_key(t) for t in existing_journal}

    new_txns = body["transactions"]
    added = []
    skipped = 0

    for txn in new_txns:
        k = dedup_key(txn)
        if k not in existing_keys:
            existing_journal.append(txn)
            existing_keys.add(k)
            added.append(txn)
        else:
            skipped += 1

    # Sort by date descending
    existing_journal.sort(
        key=lambda t: t.get("date", ""), reverse=True)

    current["trade_journal"] = existing_journal

    try:
        write_holdings(current)
    except Exception as e:
        return 500, {"error": f"Failed to write holdings.json: {e}"}

    print(f"  [import-txn] Added {len(added)}, skipped {skipped} duplicates")

    return 200, {
        "ok": True,
        "transactions_written": len(added),
        "duplicates_skipped": skipped,
        "total_in_journal": len(existing_journal),
    }


def handle_clear_pending(body: dict) -> tuple:
    """Clear the pending_pipeline_run flag after pipeline completes."""
    current = read_holdings()
    current["pending_pipeline_run"] = False
    current.pop("pending_pipeline_run_since", None)
    current.pop("pending_pipeline_run_account", None)
    try:
        write_holdings(current)
    except Exception as e:
        return 500, {"error": str(e)}
    return 200, {"ok": True}


# ── HTTP Handler ──────────────────────────────────────────────────────────────

# ── API Authentication ───────────────────────────────────────────────────────
# Set API_AUTH_TOKEN in .env to enable. If not set, auth is disabled (open access).
# When enabled, all /api/* requests require: Authorization: Bearer <token>
# Static files (/v2/, /data/, /reports/) are exempt — no auth needed for frontend.
API_AUTH_TOKEN = os.environ.get("API_AUTH_TOKEN", "").strip()
API_AUTH_ENABLED = bool(API_AUTH_TOKEN)
# Paths exempt from auth (frontend, static files, health check)
AUTH_EXEMPT_PREFIXES = ("/v2/", "/v3/", "/v3-next/", "/data/", "/archive/", "/reports/", "/assets/", "/api/health")


# ── Engine Room v1 (WS-1, Path B): in-process topology relief ──────────────────
# Root cause of the server-busy storms: threads keep computing + serializing MB
# payloads for clients that already disconnected (cache-busted poll storms, dead
# Tailscale peers), holding semaphore slots while sockets sit in CLOSE-WAIT.
# Path A (gunicorn gthread cutover) is INFEASIBLE — this is a raw http.server
# handler, not a WSGI app. Path B: detect the disconnect and stop paying for it.
import socket as _socket
import time as _wd_time

_INFLIGHT: dict = {}  # thread ident -> (path, started_at, connection)
_INFLIGHT_LOCK = threading.Lock()
_WATCHDOG_ABANDON_SEC = float(os.getenv("DASHBOARD_WATCHDOG_ABANDON_SEC", "25"))


def _peer_closed(conn) -> bool:
    """True when the client has closed its end (socket EOF ⇒ our side is CLOSE-WAIT).
    Zero-timeout select first: recv on a timeout-mode socket would block in select
    for the full socket timeout when no bytes are pending."""
    try:
        import select as _select
        readable, _, _ = _select.select([conn], [], [], 0)
        if not readable:
            return False  # nothing pending ⇒ peer alive
        return conn.recv(1, _socket.MSG_PEEK) == b""
    except Exception:
        return True   # errored socket: treat as gone


def _compute_watchdog() -> None:
    """Every 5s: any request computing past the abandon threshold whose client is
    gone gets its socket shut down, so the thread dies on its next write instead of
    finishing a response nobody will read. Never touches a connected client."""
    while True:
        _wd_time.sleep(5)
        now = _wd_time.time()
        with _INFLIGHT_LOCK:
            snapshot = list(_INFLIGHT.items())
        for tid, (path, t0, conn) in snapshot:
            age = now - t0
            if age < _WATCHDOG_ABANDON_SEC:
                continue
            try:
                if _peer_closed(conn):
                    conn.shutdown(_socket.SHUT_RDWR)
                    print(f"  [watchdog] reaped abandoned compute: {path} after {age:.0f}s")
            except Exception:
                pass


class PortfolioHandler(http.server.BaseHTTPRequestHandler):

    def finish(self):
        # Multi-threaded server (2026-06-29): close this request thread's DB connection so the server
        # never accumulates one open connection per request thread. Crons are unaffected (single thread).
        try:
            from db_adapter import close_thread_conn
            close_thread_conn()
        except Exception:
            pass
        try:
            super().finish()
        except Exception:
            pass

    def log_message(self, fmt, *args):
        # Suppress noisy GET logs for static files, keep API logs
        path = args[0] if args else ""
        if "/api/" in str(path):
            print(f"  [server] {fmt % args}")

    def _check_auth(self) -> bool:
        """Validate API authentication. Returns True if authorized."""
        if not API_AUTH_ENABLED:
            return True
        parsed = urlparse(self.path)
        path = parsed.path
        # Exempt static/frontend paths
        for prefix in AUTH_EXEMPT_PREFIXES:
            if path.startswith(prefix):
                return True
        # Only check auth for /api/ paths
        if not path.startswith("/api/"):
            return True
        # Check Authorization header
        auth_header = self.headers.get("Authorization", "")
        if auth_header == f"Bearer {API_AUTH_TOKEN}":
            return True
        # Check query param fallback (for browser testing)
        query = parse_qs(urlparse(self.path).query)
        if query.get("token", [None])[0] == API_AUTH_TOKEN:
            return True
        return False

    def _send_auth_error(self):
        """Send 401 Unauthorized response."""
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": False, "error": "Unauthorized. Set Authorization: Bearer <token> header."}).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def _reject_non_get_agent_runtime(self):
        """Non-GET methods on the read-only agent-runtime surface -> 405 (never a mutation)."""
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if _is_agent_runtime_read_path(path):
            _ar = _agent_runtime_read_handle(self.command, path, None)
            if _ar is not None:
                _send_agent_runtime_json(self, _ar[0], _ar[1])
                return True
        return False

    def _reject_non_get_active_trader(self):
        """Non-GET methods on Active Trader Stage 0 surface -> 405 (write:false)."""
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if _is_active_trader_read_path(path):
            _at = _active_trader_read_handle(self.command, path, None)
            if _at is not None:
                _send_agent_runtime_json(self, _at[0], _at[1])
                return True
        return False

    def do_PUT(self):
        if self._reject_non_get_agent_runtime():
            return
        if self._reject_non_get_active_trader():
            return
        self.send_error(405, "Method Not Allowed")

    def do_PATCH(self):
        if self._reject_non_get_agent_runtime():
            return
        if self._reject_non_get_active_trader():
            return
        self.send_error(405, "Method Not Allowed")

    def do_DELETE(self):
        if self._reject_non_get_agent_runtime():
            return
        if self._reject_non_get_active_trader():
            return
        self.send_error(405, "Method Not Allowed")

    def do_GET(self):
        # WS-1 Path B: don't start compute for a client that already hung up
        # (poll storms abort + retry; the aborted request must cost ~0)
        if _peer_closed(self.connection):
            self.close_connection = True
            return
        tid = threading.get_ident()
        with _INFLIGHT_LOCK:
            _INFLIGHT[tid] = (self.path, _wd_time.time(), self.connection)
        try:
            return self._do_GET_inner()
        finally:
            with _INFLIGHT_LOCK:
                _INFLIGHT.pop(tid, None)

    def _do_GET_inner(self):
        if not self._check_auth():
            self._send_auth_error()
            return

        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        # Read-only agent-runtime Command Center surface (GET only).
        # DEFAULT DISABLED behind AGENT_RUNTIME_READ_API; returns the honest
        # zero-authority 503 envelope whenever the reader is not connected.
        if _is_agent_runtime_read_path(path):
            _ar = _agent_runtime_read_handle("GET", path, parse_qs(parsed.query))
            if _ar is not None:
                _send_agent_runtime_json(self, _ar[0], _ar[1])
                return

        # Active Trader SESSION CONTROL reads (GET session/journal) — checked before the read plane.
        if _is_active_trader_session_path(path.rstrip("/") or "/"):
            _st = _active_trader_session_handle("GET", path, parse_qs(parsed.query), None)
            _send_agent_runtime_json(self, _st[0], _st[1])
            return

        # Active Trader Stage 0 — GET health/status/sessions only (write:false, canary:false).
        if _is_active_trader_read_path(path):
            _at = _active_trader_read_handle("GET", path, parse_qs(parsed.query))
            if _at is not None:
                _send_agent_runtime_json(self, _at[0], _at[1])
                return

        # v2/v3 API dispatch
        # R21 control-plane is an additive, GET-only projection surface.  Keep
        # it ahead of the legacy API router so unknown/invalid control-plane
        # requests receive typed degradation envelopes.
        if path.startswith("/api/v3/control-plane"):
            try:
                from control_plane_api import handle as _control_plane_handle
                _cp = _control_plane_handle(path, method=self.command, query=parse_qs(parsed.query))
                if _cp is not None:
                    json_response(self, _cp[0], _cp[1])
                    return
            except Exception as _cpe:
                json_response(self, 500, {"ok": False, "error": "control-plane projection failed"})
                return

        # /api/v3/ added 2026-07-29: the Telegram-normalization work registered
        # /api/v3/alerts/{active,settings,settings/preview} in api_v2.ROUTES, but this
        # dispatcher only ever matched /api/v2/, so all three 404'd over HTTP while
        # working fine when handle() was called in-process. They had never been
        # exercised — the migration behind them was unapplied until today.
        # api_v2.handle() routes on the FULL path, so one prefix match serves both.
        if path.startswith(("/api/v2/", "/api/v3/")):
            try:
                import time as _time
                _v2_t0 = _time.perf_counter()
                _api_v2_mod = _get_api_v2()
                _v2_handle = _api_v2_mod.handle
                _v2_query = dict(parse_qs(parsed.query)) if parsed.query else {}
                _v2_query = {k: v[0] if isinstance(v, list) and len(v) == 1 else v for k, v in _v2_query.items()}
                _v2_result = _v2_handle(path, method="GET", query=_v2_query)
                if _v2_result is not None:
                    _v2_status, _v2_body = _v2_result
                    if path.startswith("/api/v2/hermes"):
                        try:
                            sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))
                            from lib.hermes_logging.request_logger import log_hermes_request
                            log_hermes_request(
                                path,
                                method="GET",
                                duration_ms=int((_time.perf_counter() - _v2_t0) * 1000),
                                status_code=_v2_status,
                            )
                        except Exception:
                            pass
                    json_response(self, _v2_status, _v2_body)
                    return
            except Exception as _v2e:
                json_response(self, 500, {"ok": False, "error": str(_v2e)})
                return

        # Root redirect → /v3/ (v3 is canonical as of 2026-06-02)
        if path == "/" or path == "":
            self.send_response(302)
            self.send_header("Location", "/v3/")
            self.end_headers()
            return

        # Bare SPA routes (old bookmarks / shared links missing the /v3 base) → /v3/<route>.
        # /redeploy links were generated without the base until 2026-07-14; keep them working.
        if path == "/redeploy":
            q = self.path.split("?", 1)
            self.send_response(302)
            self.send_header("Location", "/v3/redeploy" + (f"?{q[1]}" if len(q) > 1 else ""))
            self.end_headers()
            return

        # Command Center v2 — serve built app at /v2/
        if path == "/v2" or path.startswith("/v2/"):
            _v2_dist = PROJECT_ROOT / "apps" / "command-center-v2" / "dist"
            _v2_sub = path[3:] or "/index.html"  # strip /v2 prefix
            if _v2_sub == "":
                _v2_sub = "/index.html"
            _v2_file = _v2_dist / _v2_sub.lstrip("/")
            # SPA fallback: serve index.html for non-asset paths
            if not _v2_file.exists() and not any(_v2_sub.endswith(ext) for ext in (".js", ".css", ".svg", ".png", ".ico", ".woff", ".woff2")):
                _v2_file = _v2_dist / "index.html"
            if _v2_file.exists():
                _ct = "text/html"
                if _v2_sub.endswith(".js"): _ct = "application/javascript"
                elif _v2_sub.endswith(".css"): _ct = "text/css"
                elif _v2_sub.endswith(".svg"): _ct = "image/svg+xml"
                elif _v2_sub.endswith(".png"): _ct = "image/png"
                elif _v2_sub.endswith(".ico"): _ct = "image/x-icon"
                self.send_response(200)
                self.send_header("Content-Type", _ct)
                # Force no-cache on all assets to prevent stale chunk issues after builds
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                _body = _v2_file.read_bytes()
                # Inject frozen banner into v2 HTML pages
                if _ct == "text/html":
                    _banner = b'<div style="position:fixed;top:0;left:0;right:0;z-index:9999;background:#1e293b;border-bottom:2px solid #f59e0b;padding:6px 16px;font-family:sans-serif;font-size:12px;color:#f59e0b;text-align:center">v2 is frozen &mdash; <a href="/v3/" style="color:#60a5fa;text-decoration:underline">v3 is now canonical</a></div>'
                    _body = _body.replace(b'<body>', b'<body>' + _banner, 1)
                self.send_header("Content-Length", str(len(_body)))
                self.end_headers()
                self.wfile.write(_body)
            else:
                self.send_response(404)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Not found")
            return

        # Command Center v3 — live boot script (always fresh; busts stale SPA bundles)
        if path == "/v3/cc-boot.js":
            _build_ver = _cc_v3_ui_version()   # shared with the inline injection below
            _js = (
                "(function(){fetch('/v3/build-meta.json',{cache:'no-store'})"
                ".then(function(r){return r.json();})"
                ".then(function(m){var v=m.ui_version||'%s',k='cc_v3_build';"
                "try{if(sessionStorage.getItem(k)!==v){sessionStorage.setItem(k,v);"
                # strip any STALE _cc_reload before adding a fresh one, so a new version always forces a
                # fresh-URL reload (the old code skipped the reload whenever _cc_reload was already present,
                # pinning the browser to a cached bundle). sessionStorage above prevents an infinite loop.
                "var s=location.search.replace(/[?&]_cc_reload=\\d+/,'');if(s.charAt(0)==='&')s='?'+s.slice(1);"
                "var q=s?'&':'?';"
                "location.replace(location.pathname+s+q+'_cc_reload='+Date.now());}"
                "}catch(e){}}).catch(function(){});})();" % _build_ver
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Content-Length", str(len(_js)))
            self.end_headers()
            self.wfile.write(_js)
            return

        # Active Trader Next — read-only static bundle at /v3-next/ (additive
        # sibling of /v3). Served from a dedicated static root OUTSIDE the repo so the
        # published bundle is pinned to the deployed build, not a moving worktree.
        # /v3 matching below is untouched: "/v3-next/...".startswith("/v3/") is
        # False, so neither route can swallow the other.
        if path == "/v3-next" or path.startswith("/v3-next/"):
            _vn_dist = Path("/home/johnclaw/deploy/v3-next/current")
            _vn_sub = path[len("/v3-next"):] or "/index.html"
            if _vn_sub == "/" or ".." in _vn_sub:
                _vn_sub = "/index.html"
            _vn_file = _vn_dist / _vn_sub.lstrip("/")
            if not _vn_file.is_file() and not any(_vn_sub.endswith(ext) for ext in (
                    ".js", ".css", ".svg", ".png", ".ico", ".woff", ".woff2", ".json")):
                _vn_file = _vn_dist / "index.html"  # SPA fallback
            if _vn_file.is_file():
                _ct = "text/html"
                if _vn_sub.endswith(".js"): _ct = "application/javascript"
                elif _vn_sub.endswith(".css"): _ct = "text/css"
                elif _vn_sub.endswith(".svg"): _ct = "image/svg+xml"
                elif _vn_sub.endswith(".png"): _ct = "image/png"
                elif _vn_sub.endswith(".json"): _ct = "application/json"
                elif _vn_sub.endswith(".ico"): _ct = "image/x-icon"
                _vn_body = _vn_file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", _ct)
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Content-Length", str(len(_vn_body)))
                self.end_headers()
                self.wfile.write(_vn_body)
            else:
                self.send_response(404)
                self.end_headers()
            return

        # Signed CIO action links — must run BEFORE the SPA catch-all.
        if path.startswith("/v3/go/cio/"):
            try:
                from scripts.lib.cio_go_handler import handle_cio_go
                qs = parse_qs(urlparse(self.path).query)
                body = None
                if self.command == "POST":
                    ln = int(self.headers.get("Content-Length") or 0)
                    raw = self.rfile.read(ln) if ln else b""
                    ctype = (self.headers.get("Content-Type") or "")
                    if "json" in ctype:
                        body = json.loads(raw.decode() or "{}")
                    else:
                        body = {k: v[0] if v else "" for k, v in parse_qs(raw.decode()).items()}
                status, ctype, payload = handle_cio_go(self.command, path, qs, body)
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except Exception as exc:
                msg = f"cio go handler failed: {type(exc).__name__}".encode()
                self.send_response(500)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)
            return

        # Command Center v3 — serve built app at /v3/
        if path == "/v3" or path.startswith("/v3/"):
            _v3_dist = PROJECT_ROOT / "apps" / "command-center-v3" / "dist"
            _v3_sub = path[3:] or "/index.html"
            if _v3_sub == "":
                _v3_sub = "/index.html"
            _v3_file = _v3_dist / _v3_sub.lstrip("/")
            if not _v3_file.exists() and not any(_v3_sub.endswith(ext) for ext in (".js", ".css", ".svg", ".png", ".ico", ".woff", ".woff2")):
                _v3_file = _v3_dist / "index.html"
            if _v3_file.exists():
                _ct = "text/html"
                if _v3_sub.endswith(".js"): _ct = "application/javascript"
                elif _v3_sub.endswith(".css"): _ct = "text/css"
                elif _v3_sub.endswith(".svg"): _ct = "image/svg+xml"
                elif _v3_sub.endswith(".png"): _ct = "image/png"
                elif _v3_sub.endswith(".ico"): _ct = "image/x-icon"
                self.send_response(200)
                self.send_header("Content-Type", _ct)
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                _body = _v3_file.read_bytes()
                # SPA routes (/v3/journal, etc.) fall back to index.html — still inject boot + cache bust.
                if _v3_file.name == "index.html":
                    _build_ver = _cc_v3_ui_version()   # MUST match /v3/cc-boot.js exactly
                    _inject = (
                        "<script>(function(){var v='%s',k='cc_v3_build';"
                        "try{if(sessionStorage.getItem(k)!==v){sessionStorage.setItem(k,v);"
                        # strip any stale _cc_reload, then reload with a fresh one — a new version always
                        # busts the cached bundle (see cc-boot.js above for the full rationale).
                        "var s=location.search.replace(/[?&]_cc_reload=\\d+/,'');if(s.charAt(0)==='&')s='?'+s.slice(1);"
                        "var q=s?'&':'?';"
                        "location.replace(location.pathname+s+q+'_cc_reload='+Date.now());}"
                        "}catch(e){}})();</script>" % _build_ver
                    ).encode()
                    _boot = b'<script src="/v3/cc-boot.js"></script>'
                    if _boot not in _body and b"</head>" in _body:
                        _body = _body.replace(b"</head>", _boot + b"</head>", 1)
                    # Inject the version check BEFORE the module script, not at
                    # </head>.
                    #
                    # Appended at </head> it landed *after* <script type="module">,
                    # so Chrome's preload scanner had already begun fetching the
                    # 4.4 MB bundle by the time this ran; on the first load of a
                    # browser session it then calls location.replace() and cancels
                    # that fetch. Every route showed net::ERR_ABORTED on a URL that
                    # serves 200 when requested directly. Deciding to redirect
                    # before the fetch starts costs nothing and wastes nothing.
                    _mod = _body.find(b'<script type="module"')
                    if _mod != -1:
                        _body = _body[:_mod] + _inject + _body[_mod:]
                    elif b"</head>" in _body:
                        _body = _body.replace(b"</head>", _inject + b"</head>", 1)
                self.send_header("Content-Length", str(len(_body)))
                self.end_headers()
                self.wfile.write(_body)
            else:
                self.send_response(404)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Not found")
            return

        # Root redirect
        if path == "/":
            self.send_response(302)
            self.send_header("Location", "/reports/command_center.html")
            self.end_headers()
            return

        # Agent monitor dashboard
        if path == "/agent-monitor":
            _am = PROJECT_ROOT / "reports" / "agent_monitor.html"
            if _am.exists():
                serve_file(self, _am)
            else:
                self.send_error(404, "agent_monitor.html not found")
            return

        # Agent orchestration dashboard
        if path == "/agent-orchestration":
            _ao = PROJECT_ROOT / "reports" / "agent_orchestration.html"
            if _ao.exists():
                serve_file(self, _ao)
            else:
                self.send_error(404, "agent_orchestration.html not found")
            return

        # API health check
        if path == "/api/health":
            json_response(self, 200, {
                "ok": True,
                "version": "2.0",
                "port": PORT,
                "holdings_exists": HOLDINGS_PATH.exists(),
            })
            return

        # Freshness manifest (Phase 0)
        if path == "/api/freshness":
            _fp = PROJECT_ROOT / "data" / "portfolios" / "state" / "_freshness.json"
            if _fp.exists():
                try:
                    _fm = json.loads(_fp.read_text())
                    from datetime import datetime as _dt
                    _completed = _dt.fromisoformat(_fm.get("completed_at", "2000-01-01"))
                    _age_hours = round((_dt.now() - _completed).total_seconds() / 3600, 1)
                    _status = "fresh" if _age_hours <= 26 else "stale"
                    json_response(self, 200, {
                        **_fm,
                        "age_hours": _age_hours,
                        "status": _status,
                        "message": f"Pipeline ran {_age_hours:.1f}h ago" if _status == "fresh" else f"Data is {_age_hours:.0f}h stale — pipeline may not have run",
                    })
                except Exception as _e:
                    json_response(self, 500, {"status": "error", "message": str(_e)})
            else:
                json_response(self, 200, {
                    "status": "unknown",
                    "age_hours": None,
                    "message": "No freshness manifest found — pipeline has not written _freshness.json yet",
                })
            return

        # Database health (Phase P5-3)
        if path == "/api/db/health":
            try:
                from db_adapter import USE_DB, db_status, get_db_table_stats
                if not USE_DB:
                    json_response(self, 200, {"ok": False, "status": "disabled", "message": "USE_DB is False"})
                    return
                rows = get_db_table_stats()
                if not rows:
                    json_response(self, 503, {"ok": False, "status": "connection_failed", "message": "DB connection failed"})
                    return
                from datetime import datetime as _dt
                json_response(self, 200, {
                    "ok": True,
                    "status": db_status(),
                    "checked_at": _dt.now().isoformat(),
                    "tables": [dict(r) for r in rows],
                })
            except Exception as _e:
                json_response(self, 500, {"ok": False, "status": "error", "message": str(_e)})
            return

        # Notifications read (GET) — recent notification_log entries
        if path == "/api/notifications/recent":
            try:
                from db_adapter import USE_DB, get_recent_notifications
                _rows = []
                if USE_DB:
                    _rows = get_recent_notifications(20)
                    for _r in _rows:
                        for _k, _v in _r.items():
                            if hasattr(_v, 'isoformat'):
                                _r[_k] = _v.isoformat()
                json_response(self, 200, {"ok": True, "notifications": _rows})
            except Exception as _e:
                json_response(self, 500, {"ok": False, "error": str(_e)})
            return

        # Report catalog (GET) — filesystem scan of all report outputs
        if path in ("/api/reports/catalog", "/api/v2/reports/catalog"):
            try:
                import os as _os
                _cat = {"live": [], "trade_ai_daily": [], "portfolio_daily": [], "weekly": [], "monthly": [], "docx": []}
                _r = PROJECT_ROOT / "reports"
                _pf = PROJECT_ROOT / "data" / "portfolios" / "reports"
                # Live dashboards
                # SECURITY 2026-08-31: portfolio_live.html withheld from the catalogue.
                # Historic copies embed a live Anthropic key in client-side JS (201 of 228
                # generated pages measured). The generator no longer embeds one, but the old
                # files still exist and this route is served-if-present. Restore this entry
                # once the historic copies are removed -- that deletion is operator-only.
                for _f in ["command_center.html", "dashboard_live.html", "strategy_center.html", "reports_hub.html"]:
                    _fp = _r / _f
                    if _fp.exists():
                        _cat["live"].append({"name": _f, "path": f"/reports/{_f}", "size_kb": round(_fp.stat().st_size / 1024, 1),
                            "modified": datetime.fromtimestamp(_os.path.getmtime(_fp)).isoformat(timespec="seconds")})
                # Trade AI daily
                for _fp in sorted(_r.glob("2026-*/*/dashboard_*.html"), reverse=True)[:20]:
                    _rel = str(_fp.relative_to(PROJECT_ROOT))
                    _cat["trade_ai_daily"].append({"name": _fp.name, "path": f"/{_rel}", "date": _fp.parent.parent.name,
                        "time": _fp.parent.name, "size_kb": round(_fp.stat().st_size / 1024, 1)})
                # Portfolio daily
                for _fp in sorted(_pf.glob("portfolio_dashboard_*.html"), reverse=True)[:20]:
                    _rel = str(_fp.relative_to(PROJECT_ROOT))
                    _cat["portfolio_daily"].append({"name": _fp.name, "path": f"/{_rel}",
                        "size_kb": round(_fp.stat().st_size / 1024, 1)})
                # Weekly
                _wk = _pf / "weekly"
                if _wk.exists():
                    for _fp in sorted(_wk.glob("*.html"), reverse=True)[:10]:
                        _cat["weekly"].append({"name": _fp.name, "path": f"/{_fp.relative_to(PROJECT_ROOT)}", "type": "html",
                            "size_kb": round(_fp.stat().st_size / 1024, 1)})
                    for _fp in sorted(_wk.glob("*.docx"), reverse=True)[:10]:
                        _cat["weekly"].append({"name": _fp.name, "path": f"/{_fp.relative_to(PROJECT_ROOT)}", "type": "docx",
                            "size_kb": round(_fp.stat().st_size / 1024, 1)})
                # Monthly
                _mo = _pf / "monthly"
                if _mo.exists():
                    for _fp in sorted(_mo.glob("*.html"), reverse=True)[:10]:
                        _cat["monthly"].append({"name": _fp.name, "path": f"/{_fp.relative_to(PROJECT_ROOT)}", "type": "html",
                            "size_kb": round(_fp.stat().st_size / 1024, 1)})
                    for _fp in sorted(_mo.glob("*.docx"), reverse=True)[:10]:
                        _cat["monthly"].append({"name": _fp.name, "path": f"/{_fp.relative_to(PROJECT_ROOT)}", "type": "docx",
                            "size_kb": round(_fp.stat().st_size / 1024, 1)})
                # DOCX files (briefs + Trade AI)
                for _fp in sorted(_pf.glob("portfolio_brief_*.docx"), reverse=True)[:10]:
                    _cat["docx"].append({"name": _fp.name, "path": f"/{_fp.relative_to(PROJECT_ROOT)}", "category": "portfolio_brief",
                        "size_kb": round(_fp.stat().st_size / 1024, 1)})
                for _fp in sorted(_r.glob("2026-*/*/*.docx"), reverse=True)[:10]:
                    _cat["docx"].append({"name": _fp.name, "path": f"/{_fp.relative_to(PROJECT_ROOT)}", "category": "trade_ai",
                        "size_kb": round(_fp.stat().st_size / 1024, 1)})
                json_response(self, 200, {"ok": True, "catalog": _cat})
            except Exception as _e:
                json_response(self, 500, {"ok": False, "error": str(_e)})
            return

        # Action queue read (GET) — pending approval items
        if path == "/api/approvals/pending":
            try:
                from db_adapter import USE_DB, get_pending_action_queue
                from decimal import Decimal
                _rows = []
                if USE_DB:
                    _rows = get_pending_action_queue()
                    for _r in _rows:
                        for _k, _v in _r.items():
                            if hasattr(_v, 'isoformat'):
                                _r[_k] = _v.isoformat()
                            elif isinstance(_v, Decimal):
                                _r[_k] = float(_v)
                json_response(self, 200, {"ok": True, "pending": _rows})
            except Exception as _e:
                json_response(self, 500, {"ok": False, "error": str(_e)})
            return

        # Watchlist read (GET)
        if path == "/api/watchlist/read":
            try:
                _wl_path = PROJECT_ROOT / "data" / "portfolios" / "state" / "watchlist.json"
                _wl = json.loads(_wl_path.read_text()) if _wl_path.exists() else {}
                # Load analyst_curated and ai_generated from Postgres
                _analyst_items = []
                _ai_items = []
                try:
                    from db_adapter import load_watchlist_items
                    for _st, _target in [("analyst_curated", "_analyst_items"), ("ai_generated", "_ai_items")]:
                        _raw = load_watchlist_items(source_type=_st, status="active")
                        for _r in _raw:
                            for _k, _v in _r.items():
                                if hasattr(_v, 'isoformat'):
                                    _r[_k] = _v.isoformat()
                        if _st == "analyst_curated":
                            _analyst_items = _raw
                        else:
                            _ai_items = _raw
                except Exception:
                    pass
                json_response(self, 200, {"ok": True, "items": _wl, "analyst_curated": _analyst_items, "ai_generated": _ai_items})
            except Exception as _e:
                json_response(self, 500, {"ok": False, "error": str(_e)})
            return

        # Personal Situation read (GET)
        if path.startswith("/api/personal/as_of/"):
            _date_str = path[len("/api/personal/as_of/"):].strip("/")
            _handle_personal_as_of(self, _date_str)
            return

        if path.startswith("/api/personal/history/"):
            _field_name = path[len("/api/personal/history/"):].strip("/")
            _handle_personal_history(self, _field_name)
            return

        if path == "/api/personal/read":
            _handle_personal_read(self)
            return

        # ENV read (GET)
        if path == "/api/env/read":
            import json as _ej
            _env = PROJECT_ROOT / ".env"
            _SENS = {"ANTHROPIC_API_KEY","FINVIZ_API_TOKEN","FINVIZ_COOKIE","TELEGRAM_BOT_TOKEN","NEWSAPI_KEY"}
            _SHOW = {"FINVIZ_COOKIE","FINVIZ_API_TOKEN","TELEGRAM_CHAT_ID","ENABLE_TELEGRAM","TELEGRAM_BOT_TOKEN","BRAVE_SEARCH_API_KEY","OPENAI_API_KEY","ANTHROPIC_API_KEY","CLAUDE_CHEAP_MODEL","CLAUDE_ESCALATION_MODEL","GEMINI_API_KEY","FINNHUB_API_KEY","NEWSAPI_KEY","POLYGON_API_KEY","FMP_API_KEY","ALPHA_VANTAGE_API_KEY","YOUTUBE_API_KEY","YOUTUBE_COOKIE","FRED_API_KEY","TIMEZONE","ENABLE_EMAIL","ENABLE_WHATSAPP","ENABLE_SLACK","FINVIZ_NEWS_ENABLED","YAHOO_NEWS_ENABLED","ERROR_NOTIFY_TELEGRAM","GENERATE_PDF","GENERATE_DOCX","GENERATE_TOS"}
            _flds = []
            if _env.exists():
                for _ln in _env.read_text(encoding="utf-8").splitlines():
                    _ln = _ln.strip()
                    if not _ln or _ln.startswith("#") or "=" not in _ln: continue
                    _k, _, _v = _ln.partition("=")
                    _k = _k.strip(); _v = _v.strip()
                    _m = _v[:4] + "****" + _v[-4:] if len(_v) > 10 else "****"
                    _flds.append({"key": _k, "value": _v if _k in _SHOW else "", "masked": _m, "sensitive": _k in _SENS})
            # Inject YouTube cookie status as virtual field
            _yt_ck = PROJECT_ROOT / "config" / "youtube_cookies.txt"
            if _yt_ck.exists():
                _yt_lines = [l for l in _yt_ck.read_text().splitlines() if l.strip() and not l.startswith("#")]
                _yt_auth = [l for l in _yt_lines if "SID" in l.split("\t")[-2] or "LOGIN" in l.split("\t")[-2]] if _yt_lines else []
                _yt_val = f"LOADED ({len(_yt_lines)} cookies, {len(_yt_auth)} auth)"
            else:
                _yt_val = "MISSING — bash scripts/setup_youtube_cookies.sh"
            _flds.append({"key": "YOUTUBE_COOKIE", "value": _yt_val, "masked": _yt_val, "sensitive": False})
            json_response(self, 200, {"ok": True, "fields": _flds})
            return

        # Static file serving
        # Map URL paths to filesystem paths
        file_map = [
            ("/data/portfolios/state/", PROJECT_ROOT / "data" / "portfolios" / "state"),
            ("/data/portfolios/charts/", PROJECT_ROOT / "data" / "portfolios" / "charts"),
            ("/data/portfolios/reports/", PROJECT_ROOT / "data" / "portfolios" / "reports"),
            ("/archive/", PROJECT_ROOT / "archive"),
            ("/reports/", PROJECT_ROOT / "reports"),
            ("/config/", PROJECT_ROOT / "config"),
            ("/assets/", PROJECT_ROOT / "assets"),
            ("/scripts/", PROJECT_ROOT / "scripts"),
            ("/logs/", PROJECT_ROOT / "logs"),
        ]

        for prefix, base_dir in file_map:
            if path.startswith(prefix):
                rel = path[len(prefix):]
                file_path = base_dir / rel
                serve_file(self, file_path)
                return

        self.send_error(404, f"Not found: {path}")

    def do_POST(self):
        tid = threading.get_ident()
        with _INFLIGHT_LOCK:
            _INFLIGHT[tid] = (self.path, _wd_time.time(), self.connection)
        try:
            return self._do_POST_inner()
        finally:
            with _INFLIGHT_LOCK:
                _INFLIGHT.pop(tid, None)

    def _do_POST_inner(self):
        if not self._check_auth():
            self._send_auth_error()
            return

        parsed = urlparse(self.path)
        path = parsed.path

        # CONTROL_PLANE_API_V1_BASELINE is GET-only. Intercept before v2 POST dispatch
        # so /api/v3/control-plane/* cannot mutate through the generic router.
        if path.startswith("/api/v3/control-plane"):
            try:
                from control_plane_api import handle as _control_plane_handle
                _cp = _control_plane_handle(path, method="POST", query=parse_qs(parsed.query))
                if _cp is not None:
                    json_response(self, _cp[0], _cp[1])
                    return
            except Exception:
                json_response(self, 500, {"ok": False, "error": "control-plane projection failed"})
                return

        # Signed CIO action links from main. Distinct path from control-plane.
        if path.startswith("/v3/go/cio/"):
            try:
                from scripts.lib.cio_go_handler import handle_cio_go
                qs = parse_qs(parsed.query)
                ln = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(ln) if ln else b""
                ctype = (self.headers.get("Content-Type") or "")
                if "json" in ctype:
                    body = json.loads(raw.decode() or "{}")
                else:
                    body = {k: v[0] if v else "" for k, v in parse_qs(raw.decode()).items()}
                status, ctype, payload = handle_cio_go("POST", path, qs, body)
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except Exception as exc:
                msg = f"cio go handler failed: {type(exc).__name__}".encode()
                self.send_response(500)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)
            return

        # Agent-runtime read surface is GET-only: any POST here is 405, never a write.
        _ar_path = path.rstrip("/") or "/"
        if _is_agent_runtime_read_path(_ar_path):
            _ar = _agent_runtime_read_handle("POST", _ar_path, None)
            if _ar is not None:
                _send_agent_runtime_json(self, _ar[0], _ar[1])
                return

        # Active Trader SESSION CONTROL plane — SEPARATE POST-capable service (simulation-only, live
        # disabled). Checked BEFORE the GET-only read plane so its POSTs are not 405'd. Writes SESSION
        # state only; no live adapter, no real 2FA/credential, no real order.
        if _is_active_trader_session_path(_ar_path):
            _slen = int(self.headers.get("Content-Length", 0))
            _sraw = self.rfile.read(_slen) if _slen > 0 else b"{}"
            try:
                _sbody = json.loads(_sraw or b"{}")
            except Exception:
                _sbody = {}
            _st = _active_trader_session_handle("POST", _ar_path, parse_qs(parsed.query), _sbody)
            _send_agent_runtime_json(self, _st[0], _st[1])
            return

        # Active Trader Stage 0 READ surface is GET-only: POST is 405, never enables canary/orders.
        if _is_active_trader_read_path(_ar_path):
            _at = _active_trader_read_handle("POST", _ar_path, None)
            if _at is not None:
                _send_agent_runtime_json(self, _at[0], _at[1])
                return

        # Read body
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            body = json.loads(raw)
        except Exception:
            json_response(self, 400, {"error": "Invalid JSON body"})
            return

        # v2/v3 API POST dispatch — see the GET dispatch note above.
        # POST /api/v3/alerts/settings and /api/v3/alerts/test-send live in
        # api_v2.handle()'s POST branch and were unreachable for the same reason.
        if path.startswith(("/api/v2/", "/api/v3/")):
            try:
                import time as _time
                _v2_t0 = _time.perf_counter()
                _api_v2_mod = _get_api_v2()
                _v2_handle = _api_v2_mod.handle
                _v2_result = _v2_handle(path, method="POST", body=body)
                if _v2_result is not None:
                    _v2_status, _v2_body = _v2_result
                    if path.startswith("/api/v2/hermes"):
                        try:
                            sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))
                            from lib.hermes_logging.request_logger import log_hermes_request
                            log_hermes_request(
                                path,
                                method="POST",
                                duration_ms=int((_time.perf_counter() - _v2_t0) * 1000),
                                status_code=_v2_status,
                            )
                        except Exception:
                            pass
                    json_response(self, _v2_status, _v2_body)
                    return
            except Exception as _v2e:
                json_response(self, 500, {"ok": False, "error": str(_v2e)})
                return

        if path == "/api/import":
            print(f"  [import] POST /api/import received — body keys: {list(body.keys())[:10]}, size: {len(raw)} bytes")
            try:
                # Log import attempt to file
                import datetime as _imp_dt
                _imp_log = PROJECT_ROOT / "logs" / "import_audit.log"
                _imp_log.parent.mkdir(parents=True, exist_ok=True)
                with open(_imp_log, "a") as _ilf:
                    _ilf.write(f"[{_imp_dt.datetime.now().isoformat()}] /api/import — keys={list(body.keys())[:10]} size={len(raw)}B\n")
                    if "positions" in body:
                        _ilf.write(f"  positions count: {len(body['positions'])}\n")
                        for _p in body['positions'][:3]:
                            _ilf.write(f"  sample: {_p.get('symbol','')} {_p.get('shares','')} {_p.get('account','')}\n")
                    if "accounts" in body:
                        _ilf.write(f"  accounts: {list(body['accounts'].keys()) if isinstance(body['accounts'], dict) else body['accounts']}\n")
            except Exception:
                pass
            # Capture before-state for reconciliation
            _before_total = 0
            _before_positions = 0
            try:
                _hb = json.loads(HOLDINGS_PATH.read_text(encoding="utf-8")) if HOLDINGS_PATH.exists() else {}
                _acct_key = body.get("account_key", "")
                for _hp in _hb.get("holdings", []):
                    if _hp.get("account") == _acct_key:
                        _before_positions += 1
                        _before_total += _hp.get("market_value", 0)
            except Exception:
                pass

            # If raw CSV was sent from ImportModal, parse it into the expected format
            if "csv_text" in body and "account_key" not in body:
                # Log raw CSV for debugging
                try:
                    _csv_debug = PROJECT_ROOT / "logs" / "last_csv_upload.txt"
                    _csv_debug.write_text(body.get("csv_text", "")[:5000])
                    print(f"  [import] Raw CSV saved to logs/last_csv_upload.txt ({len(body.get('csv_text',''))} chars)")
                except Exception:
                    pass
                try:
                    body = _parse_csv_to_import(body)
                    print(f"  [import] Parsed CSV → account={body.get('account_key')} holdings={len(body.get('holdings',[]))}")
                except Exception as _csv_err:
                    import traceback
                    traceback.print_exc()
                    json_response(self, 400, {"error": f"CSV parse failed: {_csv_err}"})
                    return

            status, result = handle_import(body)
            print(f"  [import] Result: status={status}, ok={result.get('ok','?')}")

            # Capture after-state
            _after_total = 0
            _after_positions = 0
            try:
                _ha = json.loads(HOLDINGS_PATH.read_text(encoding="utf-8")) if HOLDINGS_PATH.exists() else {}
                for _hp in _ha.get("holdings", []):
                    if _hp.get("account") == body.get("account_key", ""):
                        _after_positions += 1
                        _after_total += _hp.get("market_value", 0)
            except Exception:
                pass

            # Write structured audit entry with reconciliation
            try:
                import datetime as _sa_dt
                _sa_log = PROJECT_ROOT / "logs" / "import_audit_structured.jsonl"
                _sa_entry = json.dumps({
                    "timestamp": _sa_dt.datetime.now().isoformat(),
                    "type": "positions", "import_type": body.get("import_type", "unknown"),
                    "filename": body.get("filename", ""),
                    "account": body.get("account_key") or body.get("display_name", ""),
                    "rows_received": len(body.get("positions", body.get("holdings", []))),
                    "rows_accepted": result.get("positions_written") or result.get("count") or len(body.get("holdings", [])),
                    "rows_rejected": 0,
                    "status": "success" if result.get("ok") else "error",
                    "message": result.get("message", result.get("error", "")),
                    "size_bytes": len(raw),
                    "before": {"positions": _before_positions, "total_value": round(_before_total, 2)},
                    "after": {"positions": _after_positions, "total_value": round(_after_total, 2)},
                    "delta_value": round(_after_total - _before_total, 2),
                })
                with open(_sa_log, "a") as _sf:
                    _sf.write(_sa_entry + "\n")
            except Exception:
                pass
            json_response(self, status, result)

        elif path == "/api/import-transactions":
            print(f"  [import-txn] POST /api/import-transactions received — body keys: {list(body.keys())[:10]}, size: {len(raw)} bytes")

            # If raw CSV was sent, parse it
            if "csv_text" in body and "transactions" not in body:
                try:
                    body = _parse_txn_csv(body)
                    print(f"  [import-txn] Parsed CSV → {len(body.get('transactions',[]))} transactions")
                except Exception as _e:
                    import traceback
                    traceback.print_exc()
                    json_response(self, 400, {"error": f"Transaction CSV parse failed: {_e}"})
                    return

            try:
                import datetime as _imp_dt
                _imp_log = PROJECT_ROOT / "logs" / "import_audit.log"
                _imp_log.parent.mkdir(parents=True, exist_ok=True)
                with open(_imp_log, "a") as _ilf:
                    _ilf.write(f"[{_imp_dt.datetime.now().isoformat()}] /api/import-transactions — keys={list(body.keys())[:10]} size={len(raw)}B\n")
                    txns = body.get("transactions", [])
                    _ilf.write(f"  transactions count: {len(txns)}\n")
                    for _t in txns[:3]:
                        _ilf.write(f"  sample: {_t.get('date','')} {_t.get('action','')} {_t.get('symbol','')} {_t.get('quantity','')}\n")
            except Exception:
                pass
            status, result = handle_import_transactions(body)
            print(f"  [import-txn] Result: status={status}, ok={result.get('ok','?')}")
            json_response(self, status, result)

        elif path == "/api/clear-pending":
            status, result = handle_clear_pending(body)
            json_response(self, status, result)

        elif path == "/api/run-portfolio":
            sh = PROJECT_ROOT / "linux_launchers" / "run_portfolio.sh"
            if not sh.exists():
                json_response(self, 404, {"error": "run_portfolio.sh not found"})
                return
            def _run_daily(script=sh):
                import datetime
                log_dir = PROJECT_ROOT / "logs" / "ui_runs"
                log_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                log_file = log_dir / f"run_portfolio-{stamp}.log"
                with open(log_file, "ab") as fh:
                    subprocess.run(["bash", str(script)], cwd=str(PROJECT_ROOT), stdout=fh, stderr=subprocess.STDOUT)
            threading.Thread(target=_run_daily, daemon=True).start()
            json_response(self, 202, {"ok": True, "message": "run_portfolio.sh triggered"})

        elif path == "/api/run-trade-ai":
            sh = PROJECT_ROOT / "linux_launchers" / "run_continuous.sh"
            if not sh.exists():
                json_response(self, 404, {"error": "run_continuous.sh not found"})
                return
            def _run_trade_ai(script=sh):
                import datetime
                log_dir = PROJECT_ROOT / "logs" / "ui_runs"
                log_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                log_file = log_dir / f"run_continuous-{stamp}.log"
                with open(log_file, "ab") as fh:
                    subprocess.run(["bash", str(script)], cwd=str(PROJECT_ROOT), stdout=fh, stderr=subprocess.STDOUT)
            threading.Thread(target=_run_trade_ai, daemon=True).start()
            json_response(self, 202, {"ok": True, "message": "Trade AI continuous scan triggered"})


        elif path == "/api/run-recovery-review":
            def _run_recovery():
                try:
                    from recovery_watch_daily import main as recovery_main
                    result = recovery_main()
                    print(f"  [recovery] Review complete: {result}")
                except Exception as e:
                    print(f"  [recovery] Review failed: {e}")
            threading.Thread(target=_run_recovery, daemon=True).start()
            json_response(self, 202, {"ok": True, "message": "Recovery watch daily review triggered"})

        elif path == "/api/run-aegis":
            def _run_aegis():
                try:
                    from aegis_overnight import main as overnight_main
                    result = overnight_main()
                    print(f"  [aegis] Overnight orchestrator complete: {result}")
                except Exception as e:
                    print(f"  [aegis] Overnight orchestrator failed: {e}")
            threading.Thread(target=_run_aegis, daemon=True).start()
            json_response(self, 202, {"ok": True, "message": "Aegis overnight orchestrator triggered (collection → synthesis → refinement)"})

        elif path == "/api/run-reprice":
            sh = PROJECT_ROOT / "linux_launchers" / "run_reprice_only.sh"
            if not sh.exists():
                json_response(self, 404, {"error": "run_reprice_only.sh not found"})
                return
            def _run_reprice(script=sh):
                import datetime
                log_dir = PROJECT_ROOT / "logs" / "ui_runs"
                log_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                log_file = log_dir / f"reprice-{stamp}.log"
                with open(log_file, "ab") as fh:
                    subprocess.run(["bash", str(script)], cwd=str(PROJECT_ROOT), stdout=fh, stderr=subprocess.STDOUT)
            threading.Thread(target=_run_reprice, daemon=True).start()
            json_response(self, 202, {"ok": True, "message": "repricing refresh started"})

        elif path == "/api/run-pipeline":
            ALLOWED_PIPELINES = {
                "daily": "linux_launchers/run_portfolio.sh",
                "weekly": "linux_launchers/run_portfolio_weekly.sh",
                "monthly": "linux_launchers/run_portfolio_monthly_lite.sh",
                "price_cache": "linux_launchers/run_price_cache.sh",
            }
            pipeline_id = body.get("pipeline", "")
            if pipeline_id not in ALLOWED_PIPELINES:
                json_response(self, 400, {"error": f"Unknown pipeline: {pipeline_id}"})
                return
            sh = PROJECT_ROOT / ALLOWED_PIPELINES[pipeline_id]
            if not sh.exists():
                json_response(self, 404, {"error": f"{sh.name} not found"})
                return
            def _run_sh(script=sh, pipeline_name=pipeline_id):
                import datetime
                log_dir = PROJECT_ROOT / "logs" / "ui_runs"
                log_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                log_file = log_dir / f"{pipeline_name}-{stamp}.log"
                with open(log_file, "ab") as fh:
                    subprocess.run(["bash", str(script)], cwd=str(PROJECT_ROOT), stdout=fh, stderr=subprocess.STDOUT)
            threading.Thread(target=_run_sh, daemon=True).start()
            json_response(self, 202, {"ok": True, "message": f"{sh.name} started", "pipeline": pipeline_id})

        elif path == "/api/env/read":
            import json as _ej
            _env = PROJECT_ROOT / ".env"
            _SENS = {"ANTHROPIC_API_KEY","FINVIZ_API_TOKEN","FINVIZ_COOKIE","TELEGRAM_BOT_TOKEN","NEWSAPI_KEY"}
            _SHOW = {"FINVIZ_COOKIE","FINVIZ_API_TOKEN","TELEGRAM_CHAT_ID","ENABLE_TELEGRAM","TELEGRAM_BOT_TOKEN","BRAVE_SEARCH_API_KEY","OPENAI_API_KEY","ANTHROPIC_API_KEY","CLAUDE_CHEAP_MODEL","CLAUDE_ESCALATION_MODEL","GEMINI_API_KEY","FINNHUB_API_KEY","NEWSAPI_KEY","POLYGON_API_KEY","FMP_API_KEY","ALPHA_VANTAGE_API_KEY","YOUTUBE_API_KEY","YOUTUBE_COOKIE","FRED_API_KEY","TIMEZONE","ENABLE_EMAIL","ENABLE_WHATSAPP","ENABLE_SLACK","FINVIZ_NEWS_ENABLED","YAHOO_NEWS_ENABLED","ERROR_NOTIFY_TELEGRAM","GENERATE_PDF","GENERATE_DOCX","GENERATE_TOS"}
            _flds = []
            if _env.exists():
                for _ln in _env.read_text(encoding="utf-8").splitlines():
                    _ln = _ln.strip()
                    if not _ln or _ln.startswith("#") or "=" not in _ln: continue
                    _k, _, _v = _ln.partition("=")
                    _k = _k.strip(); _v = _v.strip()
                    _m = _v[:4] + "****" + _v[-4:] if len(_v) > 10 else "****"
                    _flds.append({"key": _k, "value": _v if _k in _SHOW else "", "masked": _m, "sensitive": _k in _SENS})
            json_response(self, 200, {"ok": True, "fields": _flds})
            return

        elif path == "/api/personal/write":
            _handle_personal_write(self, raw)
            return

        elif path == "/api/watchlist/write":
            try:
                body = json.loads(raw.decode("utf-8"))
                action = body.get("action", "add")  # 'add' or 'remove'
                symbol = body.get("symbol", "").upper().strip()
                source_type = body.get("source_type", "user")  # 'user' or 'analyst_curated'
                if source_type not in ("user", "analyst_curated"):
                    source_type = "user"
                if not symbol:
                    json_response(self, 400, {"ok": False, "error": "symbol required"})
                    return
                _wl_path = PROJECT_ROOT / "data" / "portfolios" / "state" / "watchlist.json"
                _wl = json.loads(_wl_path.read_text()) if _wl_path.exists() else {}
                if action == "remove":
                    # Only touch watchlist.json for user entries
                    if source_type == "user":
                        _wl.pop(symbol, None)
                        _wl_path.write_text(json.dumps(_wl, indent=2))
                    try:
                        from db_adapter import remove_watchlist_item
                        remove_watchlist_item(symbol, source_type)
                    except Exception:
                        pass
                    json_response(self, 200, {"ok": True, "action": "removed", "symbol": symbol, "source_type": source_type})
                else:
                    from datetime import date as _d
                    _added = body.get("added") or _d.today().isoformat()
                    _entry = {
                        "thesis": body.get("thesis", ""),
                        "target_intent": body.get("target_intent", ""),
                        "added": _added,
                        "notes": body.get("notes", ""),
                        "watching_since": "",
                    }
                    # Only write to watchlist.json for user entries (preserve compatibility)
                    if source_type == "user":
                        _wl[symbol] = _entry
                        _wl_path.write_text(json.dumps(_wl, indent=2))
                    # Postgres write for all source types
                    try:
                        from db_adapter import save_watchlist_item
                        _added_by = body.get("added_by", source_type.replace("_", " "))
                        _data = {}
                        if body.get("analyst_source"):
                            _data["analyst_source"] = body["analyst_source"]
                        if body.get("curation_note"):
                            _data["curation_note"] = body["curation_note"]
                        save_watchlist_item({
                            "symbol": symbol,
                            "source_type": source_type,
                            "thesis": _entry["thesis"],
                            "target_intent": _entry["target_intent"],
                            "added_date": _added,
                            "added_by": _added_by,
                            "status": "active",
                            "notes": _entry["notes"],
                            "data": _data,
                        })
                    except Exception as _dbe:
                        print(f"  [watchlist] Postgres write failed: {_dbe}")
                    json_response(self, 200, {"ok": True, "action": "added", "symbol": symbol, "source_type": source_type, "entry": _entry})
            except Exception as _e:
                json_response(self, 500, {"ok": False, "error": str(_e)})
            return

        elif path == "/api/env/write":
            # S5 2026-07-21: retired. Use POST /api/v2/admin/secrets (Bitwarden SM + render).
            json_response(self, 410, {
                "ok": False,
                "error": "gone",
                "message": "/api/env/write is retired. Use System → Admin → API Keys & Secrets "
                           "(POST /api/v2/admin/secrets) which writes Bitwarden SM and re-renders tmpfs.",
            })
            return

        elif path == "/api/yaml-apply":
            # Apply YAML advisor suggestions
            suggestion_ids = body.get("suggestion_ids", [])
            writer = PROJECT_ROOT / "scripts" / "portfolio_yaml_writer.py"
            if not writer.exists():
                json_response(self, 404, {"error": "portfolio_yaml_writer.py not found"})
                return
            ids_str = " ".join(suggestion_ids)
            cmd = (f'"{sys.executable}" "{writer}" --apply {ids_str} '
                   f'--project-root "{PROJECT_ROOT}"')
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                cwd=str(PROJECT_ROOT))
            json_response(self, 200, {
                "ok": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
            })

        else:
            json_response(self, 404, {"error": f"Unknown endpoint: {path}"})


# ── Entry point ───────────────────────────────────────────────────────────────

def _peek_http_path(request) -> str:
    """Best-effort request path from MSG_PEEK so health can bypass the concurrency semaphore."""
    import socket
    try:
        raw = request.recv(2048, socket.MSG_PEEK)
        if not raw:
            return ""
        line = raw.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")
        parts = line.split()
        if len(parts) >= 2:
            # GET /api/health?x=1 HTTP/1.1
            return parts[1].split("?", 1)[0]
    except Exception:
        pass
    return ""


def _sem_exempt_path(path: str) -> bool:
    """Always serve these without waiting on the global request semaphore.

    Home MetricStrip + SPA shell must stay responsive even when heavy endpoints
    (RI, proposals, risk) are saturating the concurrency pool.
    """
    p = (path or "").rstrip("/") or "/"
    if p in (
        "/api/health",
        "/api/v2/health",
        "/api/v2/overview",
        "/api/v2/trade-ai",
        "/api/v2/trade-ai/summary",
        "/api/v2/trade-ai/scanner",
        "/api/v2/risk-regime/latest",
        "/api/v2/live-trading-gate",
        "/api/v2/paper-trade-readiness",
        "/api/v3/agent-maturity",
    ):
        return True
    if p.startswith("/api/v3/agent-maturity/"):
        return True
    # Static SPA/assets — cheap, high volume
    if p.startswith("/v3/") or p.startswith("/v2/") or p.startswith("/assets/"):
        return True
    if p in ("/", "/v3", "/v2"):
        return True
    return False


class ReusableHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Threaded HTTPServer with SO_REUSEADDR.

    2026-06-29: made MULTI-THREADED (was deliberately single-threaded) so one slow endpoint no longer
    blocks every other request — the 2026-06-25/29 "Reconnecting"/ERR_CONNECTION_RESET hangs were the
    single thread stuck on a heavy endpoint while /api/health and the dashboard's parallel polls queued
    behind it. Thread-safety: db_adapter now hands each thread its OWN connection (closed in
    PortfolioHandler.finish), so concurrent requests never share cursor/transaction state.

    Concurrency is BOUNDED by a semaphore (DASHBOARD_MAX_CONCURRENCY, default 32). Excess waits at most
    SEM_ACQUIRE_TIMEOUT_SEC then gets 503. Health + static assets bypass the semaphore so the
    reconnect banner can always clear (2026-07-16 server_busy storm).
    """
    allow_reuse_address = True
    # SO_REUSEPORT allowed a second portfolio_server to bind :7777 alongside the first (orphan twins).
    allow_reuse_port = False
    request_queue_size = 128
    daemon_threads = True
    _sem = threading.BoundedSemaphore(int(os.getenv("DASHBOARD_MAX_CONCURRENCY", "48")))
    _sem_timeout = float(os.getenv("DASHBOARD_SEM_TIMEOUT_SEC", "5.0"))

    def process_request_thread(self, request, client_address):
        # Bound hung client I/O so dead Tailscale peers release slots
        try:
            request.settimeout(float(os.getenv("DASHBOARD_REQUEST_TIMEOUT_SEC", "30")))
        except Exception:
            pass
        path = _peek_http_path(request)
        if _sem_exempt_path(path):
            try:
                super().process_request_thread(request, client_address)
            except Exception:
                try:
                    request.close()
                except Exception:
                    pass
            return
        acquired = False
        try:
            acquired = self._sem.acquire(timeout=self._sem_timeout)
            if not acquired:
                # Fail fast — browser useApi will retry; better than wedging 300 CLOSE-WAIT threads
                try:
                    body = b'{"ok":false,"error":"server_busy","retry_after_sec":2}'
                    resp = (
                        b"HTTP/1.1 503 Service Unavailable\r\n"
                        b"Content-Type: application/json\r\n"
                        b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                        b"Connection: close\r\n"
                        b"Retry-After: 2\r\n"
                        b"Access-Control-Allow-Origin: *\r\n"
                        b"\r\n" + body
                    )
                    request.sendall(resp)
                except Exception:
                    pass
                try:
                    request.close()
                except Exception:
                    pass
                return
            super().process_request_thread(request, client_address)
        finally:
            if acquired:
                try:
                    self._sem.release()
                except Exception:
                    pass


if __name__ == "__main__":
    # Do NOT fuser-kill :7777 here — overlapping systemd restarts + port-guard SIGTERM caused
    # adopt churn (orphan PPID=1 while systemctl shows inactive). Watchdog clears unhealthy orphans;
    # manual recovery: systemctl --user stop portfolio-server && kill stray pid && systemctl start.
    try:
        server = ReusableHTTPServer(("", PORT), PortfolioHandler)
    except OSError as e:
        print(f"[fatal] Cannot bind port {PORT}: {e}")
        print("Another portfolio_server may already be listening. Check: ss -tlnp | grep 7777")
        sys.exit(1)
    try:
        _boot = _boot_stamp_path()
        _boot.parent.mkdir(parents=True, exist_ok=True)
        _disk = _read_pin_sha(Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT")
        _boot.write_text(json.dumps({
            "schema": "PortfolioServerBoot@v1",
            "authority": "READ_ONLY_ADVISORY",
            "process_started_at": PROCESS_STARTED_AT,
            "loaded_pin_sha": LOADED_PIN_SHA,
            "current_pin_sha": _disk,
            "pid": os.getpid(),
            "port": PORT,
        }, indent=2) + "\n", encoding="utf-8")
    except OSError as _be:
        print(f"[warn] could not write boot stamp: {_be}")
    threading.Thread(target=_compute_watchdog, daemon=True,
                     name="engine-room-compute-watchdog").start()
    # ── Startup data freshness check ──────────────────────────────────────
    # Defense-in-depth: verify holdings.json is from a recent session BEFORE
    # the server starts serving stale data. The deploy script symlinks the
    # release data/ dir to the canonical pipeline output, but if that breaks
    # (e.g. a manual rsync that copied files instead of symlinking, or a
    # filesystem restore), we want a loud warning at startup — not a silent
    # stale-header discovery three days later.
    try:
        from datetime import datetime as _dt, timezone as _tz
        _h = json.loads(HOLDINGS_PATH.read_text(encoding="utf-8"))
        _lr = _h.get("last_repriced") or _h.get("as_of") or ""
        _age_hours = None
        for _fmt in ("%Y-%m-%d %H:%M:%S ET", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                _aged = _dt.strptime(str(_lr).strip().split(".")[0][:19], _fmt)
                _age_hours = round((_dt.now(_tz.utc) - _aged.replace(tzinfo=_tz.utc)).total_seconds() / 3600, 1)
                break
            except (ValueError, IndexError):
                continue
        if _age_hours is not None:
            if _age_hours > 168:  # >7 days
                print(f"[CRITICAL] holdings.json last_repriced={_lr} — data is "
                      f"{_age_hours:.0f}h old ({_age_hours/24:.0f}d)! "
                      f"Portfolio header will show STALE values.")
                print(f"[CRITICAL] Check: ls -la {HOLDINGS_PATH} — is it a symlink to the canonical pipeline output?")
            elif _age_hours > 26:  # >1 day
                print(f"[WARN] holdings.json last_repriced={_lr} — data is "
                      f"{_age_hours:.0f}h old. Check pipeline health or deploy symlinks.")
        else:
            print(f"[WARN] Could not parse last_repriced from holdings.json: {str(_lr)[:80]}")
    except Exception as _fe:
        print(f"[WARN] Startup freshness check failed: {_fe} (continuing)")
    # ──────────────────────────────────────────────────────────────────────
    print(f"Portfolio server → http://localhost:{PORT}")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Holdings: {HOLDINGS_PATH}")
    print("Endpoints: /api/import  /api/import-transactions  "
          "/api/run-portfolio  /api/run-trade-ai  /api/run-pipeline  /api/health")
    print("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
