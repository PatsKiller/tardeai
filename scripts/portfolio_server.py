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
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
HOLDINGS_PATH = STATE_DIR / "holdings.json"


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
