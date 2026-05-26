# Source Export: scripts/watchlist_research_api.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/watchlist_research_api.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `a411a1cac52306a1af1e9c326752eff2b54bb5d2514ed8cc90ba9a4ddb7652a5` |
| **File Size** | 9852 bytes |

## Full Source

```py
#!/usr/bin/env python3
import json
import os
import subprocess
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data/portfolios/state"
LOGS = ROOT / "logs"
QUEUE = STATE / "watchlist_research_queue.json"
RESULTS = STATE / "watchlist_research_results.json"
EVENTS = STATE / "watchlist_research_events.json"
ENV = ROOT / ".env"

def now():
    return datetime.now(timezone.utc).isoformat()

def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default

def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2))

def log_line(obj):
    LOGS.mkdir(parents=True, exist_ok=True)
    with (LOGS / "watchlist_research_api.log").open("a") as f:
        f.write(json.dumps({"time": now(), **obj}) + "\n")

def load_db_env():
    db = {}
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.startswith("DB_"):
                    db[k] = v
    return db

def db_exec(sql, stdin=None):
    db = load_db_env()
    required = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    if any(k not in db or not db[k] for k in required):
        return {"ok": False, "error": "missing db env"}

    env = os.environ.copy()
    env["PGPASSWORD"] = db["DB_PASSWORD"]
    proc = subprocess.run(
        ["psql", "-h", db["DB_HOST"], "-p", db["DB_PORT"], "-U", db["DB_USER"], "-d", db["DB_NAME"], "-v", "ON_ERROR_STOP=1", "-c", sql],
        text=True,
        input=stdin,
        capture_output=True,
        env=env,
        cwd=ROOT
    )
    if proc.returncode != 0:
        return {"ok": False, "error": proc.stderr.strip(), "stdout": proc.stdout.strip()}
    return {"ok": True, "stdout": proc.stdout.strip()}

def sql_quote(v):
    if v is None:
        return "NULL"
    return "'" + str(v).replace("'", "''") + "'"

def db_event(event_type, payload):
    payload_json = json.dumps(payload).replace("'", "''")
    sql = f"""
    INSERT INTO watchlist_research_events(event_type, symbol, agent, request_type, status, message, payload)
    VALUES (
      {sql_quote(event_type)},
      {sql_quote(payload.get('symbol'))},
      {sql_quote(payload.get('agent'))},
      {sql_quote(payload.get('request_type'))},
      {sql_quote(payload.get('status'))},
      {sql_quote(payload.get('message'))},
      '{payload_json}'::jsonb
    );
    """
    return db_exec(sql)

def db_upsert_queue(item):
    payload_json = json.dumps(item).replace("'", "''")
    sql = f"""
    INSERT INTO watchlist_research_queue(id, symbol, agent, request_type, note, status, payload, created_at, updated_at)
    VALUES (
      {sql_quote(item['id'])},
      {sql_quote(item['symbol'])},
      {sql_quote(item['agent'])},
      {sql_quote(item['request_type'])},
      {sql_quote(item.get('note'))},
      {sql_quote(item['status'])},
      '{payload_json}'::jsonb,
      {sql_quote(item['created_at'])},
      {sql_quote(item['updated_at'])}
    )
    ON CONFLICT (id) DO UPDATE SET
      status = EXCLUDED.status,
      payload = EXCLUDED.payload,
      updated_at = EXCLUDED.updated_at;
    """
    return db_exec(sql)

def db_upsert_result(result):
    route_json = json.dumps(result.get("route", {})).replace("'", "''")
    result_json = json.dumps(result).replace("'", "''")
    sql = f"""
    INSERT INTO watchlist_research_results(id, queue_id, symbol, agent, request_type, status, summary, route, result, created_at, completed_at)
    VALUES (
      {sql_quote(result['id'])},
      {sql_quote(result.get('queue_id') or result.get('id'))},
      {sql_quote(result['symbol'])},
      {sql_quote(result.get('agent'))},
      {sql_quote(result.get('request_type'))},
      {sql_quote(result.get('status'))},
      {sql_quote(result.get('summary'))},
      '{route_json}'::jsonb,
      '{result_json}'::jsonb,
      {sql_quote(result.get('created_at'))},
      {sql_quote(result.get('completed_at'))}
    )
    ON CONFLICT (id) DO UPDATE SET
      status = EXCLUDED.status,
      summary = EXCLUDED.summary,
      route = EXCLUDED.route,
      result = EXCLUDED.result,
      completed_at = EXCLUDED.completed_at;
    """
    return db_exec(sql)

def db_counts():
    sql = """
    SELECT json_build_object(
      'queue', (SELECT COUNT(*) FROM watchlist_research_queue),
      'queued', (SELECT COUNT(*) FROM watchlist_research_queue WHERE status='queued'),
      'completed', (SELECT COUNT(*) FROM watchlist_research_queue WHERE status='completed'),
      'results', (SELECT COUNT(*) FROM watchlist_research_results),
      'events', (SELECT COUNT(*) FROM watchlist_research_events)
    );
    """
    db = load_db_env()
    if not db:
        return {}
    env = os.environ.copy()
    env["PGPASSWORD"] = db["DB_PASSWORD"]
    proc = subprocess.run(
        ["psql", "-h", db["DB_HOST"], "-p", db["DB_PORT"], "-U", db["DB_USER"], "-d", db["DB_NAME"], "-t", "-A", "-c", sql],
        text=True, capture_output=True, env=env, cwd=ROOT
    )
    try:
        return json.loads(proc.stdout.strip())
    except Exception:
        return {"error": proc.stderr.strip(), "raw": proc.stdout.strip()}

def enqueue(payload):
    q = load_json(QUEUE, {"updated_at": now(), "items": []})
    items = q.setdefault("items", [])
    created = []

    for sym in payload.get("symbols", []):
        sym = str(sym).upper().strip()
        if not sym:
            continue
        item = {
            "id": f"{sym}_{payload.get('agent','full_chain')}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
            "symbol": sym,
            "agent": payload.get("agent") or "full_chain",
            "request_type": payload.get("request_type") or "research",
            "note": payload.get("note") or "",
            "status": "queued",
            "created_at": now(),
            "updated_at": now()
        }
        items.append(item)
        created.append(item)
        db_upsert_queue(item)
        db_event("enqueue", {**item, "message": "queued from dashboard"})

    q["updated_at"] = now()
    save_json(QUEUE, q)
    log_line({"event": "enqueue", "created": len(created), "symbols": payload.get("symbols", [])})
    return created

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        data = json.dumps(obj, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self._send(200, {"ok": True})

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self._send(200, {"ok": True, "time": now(), "db": db_counts()})
        elif path == "/queue":
            self._send(200, load_json(QUEUE, {"items": []}))
        elif path == "/results":
            self._send(200, load_json(RESULTS, {"results": []}))
        elif path == "/events":
            self._send(200, load_json(EVENTS, {"events": []}))
        elif path == "/debug":
            self._send(200, {
                "ok": True,
                "time": now(),
                "files": {
                    "queue_exists": QUEUE.exists(),
                    "results_exists": RESULTS.exists(),
                    "events_exists": EVENTS.exists(),
                    "classified_exists": (STATE / "classified_candidates.json").exists(),
                    "watchlist_exists": (STATE / "ai_watchlist.json").exists(),
                    "discovery_exists": (STATE / "discovery_candidates.json").exists()
                },
                "db": db_counts()
            })
        else:
            self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode() if length else "{}"
        try:
            payload = json.loads(raw)
        except Exception:
            self._send(400, {"ok": False, "error": "invalid json"})
            return

        if path == "/enqueue":
            created = enqueue(payload)
            self._send(200, {"ok": True, "created": len(created), "items": created, "db": db_counts()})
        elif path == "/process":
            proc = subprocess.run(
                ["python3", "scripts/process_watchlist_research_queue.py", "--limit", "10", "--json"],
                cwd=ROOT, text=True, capture_output=True
            )
            try:
                body = json.loads(proc.stdout)
            except Exception:
                body = {"stdout": proc.stdout, "stderr": proc.stderr}
            log_line({"event": "process", "returncode": proc.returncode, "body": body})
            self._send(200, {"ok": proc.returncode == 0, "result": body, "db": db_counts()})
        else:
            self._send(404, {"ok": False, "error": "not found"})

def main():
    port = int(os.environ.get("WATCHLIST_RESEARCH_API_PORT", "7788"))
    LOGS.mkdir(parents=True, exist_ok=True)
    log_line({"event": "startup", "port": port})
    print(f"watchlist research api listening on 0.0.0.0:{port}", flush=True)
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()

if __name__ == "__main__":
    main()
```
