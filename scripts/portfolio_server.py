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
import json
import os
import subprocess
import sys
import threading
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

PORT = 7777
PROJECT_ROOT = Path(__file__).parent.parent.resolve()

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
        from db_adapter import USE_DB, _execute
    except Exception as e:
        return {"ok": False, "error": f"db_adapter import failed: {e}"}

    if not PERSONAL_PATH.exists():
        return {"ok": False, "error": "personal_situation.json not found"}

    if not USE_DB:
        return {"ok": False, "error": "Postgres unavailable - reconstruction requires DB"}

    base_data = json.loads(PERSONAL_PATH.read_text(encoding="utf-8"))
    fields = base_data.get("fields", {})

    # SELECT DISTINCT ON gives us the latest matching row per field
    rows = _execute(
        """SELECT DISTINCT ON (field_name)
               field_name, value, effective_date, recorded_at, note, source
           FROM personal_history
           WHERE effective_date <= %s
           ORDER BY field_name, effective_date DESC, recorded_at DESC""",
        (target_date,),
        fetch="all"
    )

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
        from db_adapter import USE_DB, _execute
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

    rows = _execute(
        """SELECT value, effective_date, recorded_at, note, source
           FROM personal_history
           WHERE field_name = %s
           ORDER BY recorded_at ASC""",
        (field_name,),
        fetch="all"
    )

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
            from db_adapter import USE_DB, _execute
            if USE_DB:
                for change in changes:
                    fn = change["field"]
                    f_def = fields.get(fn, {})
                    _execute(
                        """INSERT INTO personal_history 
                           (field_name, value, data_type, category, effective_date, note, source)
                           VALUES (%s, %s, %s, %s, %s, %s, 'modal_edit')""",
                        (fn, json.dumps(change["to"]), 
                         f_def.get("data_type", "unknown"),
                         f_def.get("category", "unknown"),
                         today,
                         note or f"set via modal on {today}")
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
    HOLDINGS_PATH.write_text(
        json.dumps(data, indent=2, default=str), encoding="utf-8"
    )


def json_response(handler, status: int, data: dict) -> None:
    body = json.dumps(data).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def serve_file(handler, path: Path) -> None:
    if not path.exists():
        handler.send_error(404, f"Not found: {path.name}")
        return
    ctype = "text/html"
    if path.suffix == ".json":
        ctype = "application/json"
    elif path.suffix in (".yaml", ".yml"):
        ctype = "text/plain"
    elif path.suffix == ".js":
        ctype = "application/javascript"
    elif path.suffix == ".css":
        ctype = "text/css"
    elif path.suffix == ".py":
        ctype = "text/plain"
    data = path.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    handler.wfile.write(data)


# ── Import handler ────────────────────────────────────────────────────────────

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
    for h in new_holdings:
        h["account"] = account_key

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

class PortfolioHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        # Suppress noisy GET logs for static files, keep API logs
        path = args[0] if args else ""
        if "/api/" in str(path):
            print(f"  [server] {fmt % args}")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        # Root redirect
        if path == "/":
            self.send_response(302)
            self.send_header("Location", "/reports/command_center.html")
            self.end_headers()
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
                from db_adapter import _execute, USE_DB, db_status
                if not USE_DB:
                    json_response(self, 200, {"ok": False, "status": "disabled", "message": "USE_DB is False"})
                    return
                rows = _execute("""
                    SELECT s.relname AS name,
                           s.n_live_tup AS live_rows,
                           s.n_dead_tup AS dead_rows,
                           pg_size_pretty(pg_total_relation_size(s.schemaname||'.'||s.relname)) AS size,
                           s.last_autovacuum::text,
                           s.last_autoanalyze::text
                    FROM pg_stat_user_tables s
                    ORDER BY pg_total_relation_size(s.schemaname||'.'||s.relname) DESC
                """, fetch="all")
                if rows is None:
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

        # Watchlist read (GET)
        if path == "/api/watchlist/read":
            try:
                _wl_path = PROJECT_ROOT / "data" / "portfolios" / "state" / "watchlist.json"
                _wl = json.loads(_wl_path.read_text()) if _wl_path.exists() else {}
                # Also load analyst_curated from Postgres
                _analyst_items = []
                try:
                    from db_adapter import load_watchlist_items
                    _raw = load_watchlist_items(source_type="analyst_curated", status="active")
                    # Convert date objects to strings for JSON serialization
                    for _r in _raw:
                        for _k, _v in _r.items():
                            if hasattr(_v, 'isoformat'):
                                _r[_k] = _v.isoformat()
                    _analyst_items = _raw
                except Exception:
                    pass
                json_response(self, 200, {"ok": True, "items": _wl, "analyst_curated": _analyst_items})
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
            _SHOW = {"FINVIZ_COOKIE","FINVIZ_API_TOKEN","TELEGRAM_CHAT_ID","ENABLE_TELEGRAM","TELEGRAM_BOT_TOKEN","BRAVE_SEARCH_API_KEY","OPENAI_API_KEY","ANTHROPIC_API_KEY","CLAUDE_CHEAP_MODEL","CLAUDE_ESCALATION_MODEL","GEMINI_API_KEY","FINNHUB_API_KEY","NEWSAPI_KEY","POLYGON_API_KEY","FMP_API_KEY","ALPHA_VANTAGE_API_KEY","TIMEZONE","ENABLE_EMAIL","ENABLE_WHATSAPP","ENABLE_SLACK","FINVIZ_NEWS_ENABLED","YAHOO_NEWS_ENABLED","ERROR_NOTIFY_TELEGRAM","GENERATE_PDF","GENERATE_DOCX","GENERATE_TOS"}
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

        # Static file serving
        # Map URL paths to filesystem paths
        file_map = [
            ("/data/portfolios/state/", PROJECT_ROOT / "data" / "portfolios" / "state"),
            ("/data/portfolios/charts/", PROJECT_ROOT / "data" / "portfolios" / "charts"),
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
        parsed = urlparse(self.path)
        path = parsed.path

        # Read body
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            body = json.loads(raw)
        except Exception:
            json_response(self, 400, {"error": "Invalid JSON body"})
            return

        if path == "/api/import":
            status, result = handle_import(body)
            json_response(self, status, result)

        elif path == "/api/import-transactions":
            status, result = handle_import_transactions(body)
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
            _SHOW = {"FINVIZ_COOKIE","FINVIZ_API_TOKEN","TELEGRAM_CHAT_ID","ENABLE_TELEGRAM","TELEGRAM_BOT_TOKEN","BRAVE_SEARCH_API_KEY","OPENAI_API_KEY","ANTHROPIC_API_KEY","CLAUDE_CHEAP_MODEL","CLAUDE_ESCALATION_MODEL","GEMINI_API_KEY","FINNHUB_API_KEY","NEWSAPI_KEY","POLYGON_API_KEY","FMP_API_KEY","ALPHA_VANTAGE_API_KEY","TIMEZONE","ENABLE_EMAIL","ENABLE_WHATSAPP","ENABLE_SLACK","FINVIZ_NEWS_ENABLED","YAHOO_NEWS_ENABLED","ERROR_NOTIFY_TELEGRAM","GENERATE_PDF","GENERATE_DOCX","GENERATE_TOS"}
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
            import json as _ej, time as _et
            _bstr = raw.decode("utf-8", errors="replace")
            try:
                _upd = _ej.loads(_bstr).get("updates", {})
            except Exception:
                json_response(self, 400, {"error": "Invalid JSON"}); return
            _env = PROJECT_ROOT / ".env"
            if not _env.exists():
                json_response(self, 404, {"error": ".env not found"}); return
            _ts2 = _et.strftime("%Y%m%d-%H%M%S")
            _bd = PROJECT_ROOT / "file_backups" / ("env_" + _ts2)
            _bd.mkdir(parents=True, exist_ok=True)
            _bk = _bd / (".env.bak-" + _ts2)
            _bk.write_bytes(_env.read_bytes())
            _el = _env.read_text(encoding="utf-8").splitlines()
            _dk = set(); _nl = []
            for _ln2 in _el:
                _s2 = _ln2.strip()
                _k2 = _s2.split("=",1)[0].strip() if (_s2 and not _s2.startswith("#") and "=" in _s2) else None
                if _k2 and _k2 in _upd:
                    _nl.append(_k2 + "=" + _upd[_k2]); _dk.add(_k2)
                else:
                    _nl.append(_ln2)
            for _k3, _v3 in _upd.items():
                if _k3 not in _dk: _nl.append(_k3 + "=" + _v3)
            _env.write_text(chr(10).join(_nl) + chr(10), encoding="utf-8")
            json_response(self, 200, {"ok": True, "backup": str(_bk), "updated": list(_dk)})
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

if __name__ == "__main__":
    server = http.server.HTTPServer(("", PORT), PortfolioHandler)
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
