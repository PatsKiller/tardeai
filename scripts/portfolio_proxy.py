"""portfolio_proxy.py — Local API proxy for Portfolio Intelligence dashboard.
Runs on http://localhost:7778 alongside the file server.
Forwards Claude API calls from the browser (bypasses CORS restriction).
Start with: python scripts/portfolio_proxy.py --root .
"""
from __future__ import annotations
import argparse, json, os, sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

def get_api_key(project_root: Path) -> str:
    # 1. Env var
    key = os.getenv("ANTHROPIC_API_KEY","").strip()
    if key: return key
    # 2. .env file
    env_file = project_root / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY"):
                key = line.split("=",1)[-1].strip().strip("\"'")
                if key: return key
    return ""

PROJECT_ROOT = Path(".")
API_KEY = ""

class ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress access logs

    def do_OPTIONS(self):
        self._cors_headers()
        self.send_response(200)
        self.end_headers()

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, x-api-key, anthropic-version")

    def do_POST(self):
        if self.path == "/api/claude":
            self._handle_claude()
        elif self.path == "/api/stop":
            self._handle_stop()
        elif self.path == "/api/intent":
            self._handle_intent()
        elif self.path in ("/api/note", "/api/trade_notes"):
            self._handle_trade_notes()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_stop(self):
        """Handle stop-loss set/remove from dashboard."""
        try:
            length  = int(self.headers.get("Content-Length", 0))
            body    = json.loads(self.rfile.read(length))
            action  = body.get("action","")
            symbol  = body.get("symbol","").upper().strip()
            state_dir = PROJECT_ROOT / "data" / "portfolios" / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            stops_file = state_dir / "stops.json"
            stops = json.loads(stops_file.read_text()) if stops_file.exists() else {}

            if action == "set" and symbol:
                stops[symbol] = {
                    "stop":      round(float(body.get("stop",0)), 4),
                    "trail_pct": round(float(body.get("trail_pct",0)), 2),
                    "notes":     str(body.get("notes","")),
                    "set_date":  __import__("datetime").datetime.now().strftime("%Y-%m-%d"),
                    "account":   "all",
                }
                stops_file.write_text(json.dumps(stops, indent=2))
                result = {"ok": True, "message": f"Stop set for {symbol} @ ${stops[symbol]['stop']:.2f}. Re-run portfolio.bat to refresh."}
            elif action == "remove" and symbol:
                stops.pop(symbol, None)
                stops_file.write_text(json.dumps(stops, indent=2))
                result = {"ok": True, "message": f"Stop removed for {symbol}. Re-run portfolio.bat to refresh."}
            else:
                result = {"ok": False, "message": "Unknown action"}

            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        except Exception as e:
            self.send_response(500)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())


    def _handle_intent(self):
        """Save position intent to portfolio_intent.yaml."""
        try:
            import yaml
            length = int(self.headers.get("Content-Length", 0))
            body   = json.loads(self.rfile.read(length))
            action = body.get("action","")
            intent_file = PROJECT_ROOT / "assets" / "portfolio_intent.yaml"
            
            # Load current config
            cfg = yaml.safe_load(intent_file.read_text()) if intent_file.exists() else {}
            if not cfg: cfg = {}
            
            skip = {"covered_call_settings","stop_settings","benchmark","fidelity_funds"}
            # Rebuild intent map
            intent_map = {}
            for cat, tickers in cfg.items():
                if cat in skip or not isinstance(tickers, list): continue
                for t in tickers:
                    intent_map[str(t).upper()] = cat

            if action == "set":
                sym    = str(body.get("symbol","")).upper()
                intent = str(body.get("intent","unclassified"))
                if sym:
                    # Remove from all existing categories
                    for cat in list(cfg.keys()):
                        if cat in skip or not isinstance(cfg.get(cat), list): continue
                        if sym in cfg[cat]: cfg[cat].remove(sym)
                    # Add to new category
                    if intent not in cfg: cfg[intent] = []
                    if sym not in cfg[intent]: cfg[intent].append(sym)
                    result = {"ok": True, "symbol": sym, "intent": intent}

            elif action == "batch":
                intents = body.get("intents", {})
                for sym, intent in intents.items():
                    sym = sym.upper()
                    for cat in list(cfg.keys()):
                        if cat in skip or not isinstance(cfg.get(cat), list): continue
                        if sym in cfg[cat]: cfg[cat].remove(sym)
                    if intent not in cfg: cfg[intent] = []
                    if sym not in cfg[intent]: cfg[intent].append(sym)
                result = {"ok": True, "count": len(intents)}

            else:
                result = {"ok": False, "error": "Unknown action"}

            # Save
            intent_file.parent.mkdir(parents=True, exist_ok=True)
            intent_file.write_text(yaml.dump(cfg, default_flow_style=False, allow_unicode=True))

            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type","application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        except Exception as e:
            self.send_response(500)
            self._cors_headers()
            self.send_header("Content-Type","application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok":False,"error":str(e)}).encode())

    def _handle_trade_notes(self):
        """Handle trade notes save/load from dashboard drawer."""
        try:
            length    = int(self.headers.get("Content-Length", 0))
            body      = json.loads(self.rfile.read(length))
            action    = body.get("action","")
            state_dir = PROJECT_ROOT / "data" / "portfolios" / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            notes_file = state_dir / "trade_notes.json"
            notes = json.loads(notes_file.read_text()) if notes_file.exists() else {}

            if action == "set":
                key = body.get("trade_key","")
                if key:
                    notes[key] = {
                        "notes":     str(body.get("notes","")),
                        "rating":    int(body.get("rating",0)),
                        "setup":     str(body.get("setup","")),
                        "execution": str(body.get("execution","")),
                        "saved_at":  __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
                    }
                    notes_file.write_text(json.dumps(notes, indent=2))
                    result = {"ok": True, "message": f"Note saved for {key}"}
                else:
                    result = {"ok": False, "message": "No trade_key"}
            elif action == "get":
                key = body.get("trade_key","")
                result = {"ok": True, "note": notes.get(key, {})}
            else:
                result = {"ok": False, "message": "Unknown action"}

            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type","application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        except Exception as e:
            self.send_response(500)
            self._cors_headers()
            self.send_header("Content-Type","application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def _handle_claude(self):
        try:
            length  = int(self.headers.get("Content-Length", 0))
            body    = self.rfile.read(length)
            payload = json.loads(body)

            req = Request(
                "https://api.anthropic.com/v1/messages",
                data=json.dumps(payload).encode(),
                headers={
                    "Content-Type":      "application/json",
                    "x-api-key":         API_KEY,
                    "anthropic-version": "2023-06-01",
                },
                method="POST",
            )
            with urlopen(req, timeout=90) as resp:
                result = resp.read()

            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(result)

        except HTTPError as e:
            err_body = e.read()
            self.send_response(e.code)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(err_body)
        except Exception as e:
            self.send_response(500)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".", help="Project root (for .env)")
    p.add_argument("--port", type=int, default=7778)
    args = p.parse_args()

    PROJECT_ROOT = Path(args.root)
    API_KEY = get_api_key(PROJECT_ROOT)
    if not API_KEY:
        print("WARNING: ANTHROPIC_API_KEY not found — AI buttons will fail")
    else:
        print(f"  [proxy] API key loaded ✅")

    server = HTTPServer(("localhost", args.port), ProxyHandler)
    print(f"  [proxy] Running on http://localhost:{args.port}")
    print(f"  [proxy] Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
