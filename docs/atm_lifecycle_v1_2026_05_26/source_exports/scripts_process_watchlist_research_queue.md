# Source Export: scripts/process_watchlist_research_queue.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/process_watchlist_research_queue.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `f468c5ede734f739dc46cbcdfeba0abfe786aaff898830f46eff1a347586b867` |
| **File Size** | 6469 bytes |

## Full Source

```py
#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

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
    with (LOGS / "watchlist_research_queue.log").open("a") as f:
        f.write(json.dumps({"time": now(), **obj}) + "\n")

def db_env():
    d = {}
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.startswith("DB_"):
                    d[k] = v
    return d

def psql(sql):
    d = db_env()
    if not d:
        return
    env = os.environ.copy()
    env["PGPASSWORD"] = d["DB_PASSWORD"]
    subprocess.run(
        ["psql", "-h", d["DB_HOST"], "-p", d["DB_PORT"], "-U", d["DB_USER"], "-d", d["DB_NAME"], "-c", sql],
        text=True, capture_output=True, env=env, cwd=ROOT
    )

def q(v):
    if v is None:
        return "NULL"
    return "'" + str(v).replace("'", "''") + "'"

def db_queue(item):
    payload = json.dumps(item).replace("'", "''")
    sql = f"""
    INSERT INTO watchlist_research_queue(id, symbol, agent, request_type, note, status, payload, created_at, updated_at)
    VALUES ({q(item['id'])},{q(item['symbol'])},{q(item['agent'])},{q(item['request_type'])},{q(item.get('note'))},{q(item['status'])},'{payload}'::jsonb,{q(item['created_at'])},{q(item['updated_at'])})
    ON CONFLICT (id) DO UPDATE SET status=EXCLUDED.status,payload=EXCLUDED.payload,updated_at=EXCLUDED.updated_at;
    """
    psql(sql)

def db_result(result):
    route = json.dumps(result.get("route", {})).replace("'", "''")
    blob = json.dumps(result).replace("'", "''")
    sql = f"""
    INSERT INTO watchlist_research_results(id, queue_id, symbol, agent, request_type, status, summary, route, result, created_at, completed_at)
    VALUES ({q(result['id'])},{q(result.get('queue_id') or result['id'])},{q(result['symbol'])},{q(result.get('agent'))},{q(result.get('request_type'))},{q(result.get('status'))},{q(result.get('summary'))},'{route}'::jsonb,'{blob}'::jsonb,{q(result.get('created_at'))},{q(result.get('completed_at'))})
    ON CONFLICT (id) DO UPDATE SET status=EXCLUDED.status,summary=EXCLUDED.summary,route=EXCLUDED.route,result=EXCLUDED.result,completed_at=EXCLUDED.completed_at;
    """
    psql(sql)

def db_event(event_type, payload):
    blob = json.dumps(payload).replace("'", "''")
    sql = f"""
    INSERT INTO watchlist_research_events(event_type, symbol, agent, request_type, status, message, payload)
    VALUES ({q(event_type)},{q(payload.get('symbol'))},{q(payload.get('agent'))},{q(payload.get('request_type'))},{q(payload.get('status'))},{q(payload.get('message'))},'{blob}'::jsonb);
    """
    psql(sql)

def run_router(symbol, agent, request_type, note):
    msg = f"{agent} research request for {symbol}. Type: {request_type}. {note}".strip()
    proc = subprocess.run(
        ["python3", "scripts/agent_router_controlled.py", "--message", msg, "--save"],
        cwd=ROOT, text=True, capture_output=True
    )
    try:
        return json.loads(proc.stdout)
    except Exception:
        return {"stdout": proc.stdout, "stderr": proc.stderr, "returncode": proc.returncode}

def result_for(item, route):
    summary = f"{item['symbol']}: routed to {route.get('to_agent')} for {item.get('request_type')} confidence={route.get('confidence')} reliability={route.get('reliability_controls',{}).get('mode')}"
    return {
        "id": item["id"],
        "queue_id": item["id"],
        "symbol": item["symbol"],
        "agent": item.get("agent"),
        "request_type": item.get("request_type"),
        "status": "completed",
        "summary": summary,
        "route": route,
        "created_at": item.get("created_at"),
        "completed_at": now(),
        "recommended_next_action": "Iterate: review agent output, then request deeper Maria/Steph/Risk analysis if needed."
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    queue = load_json(QUEUE, {"updated_at": now(), "items": []})
    results = load_json(RESULTS, {"updated_at": now(), "results": []})
    events = load_json(EVENTS, {"updated_at": now(), "events": []})

    processed = []
    for item in queue.get("items", []):
        if len(processed) >= args.limit:
            break
        if item.get("status") != "queued":
            continue

        item["status"] = "processing"
        item["updated_at"] = now()
        db_queue(item)
        db_event("processing", {**item, "message": "processing started"})

        route = run_router(item["symbol"], item.get("agent", "full_chain"), item.get("request_type", "research"), item.get("note", ""))
        result = result_for(item, route)

        item["status"] = "completed"
        item["updated_at"] = now()
        item["result_id"] = result["id"]

        results.setdefault("results", []).append(result)
        events.setdefault("events", []).append({"time": now(), "event": "completed", "symbol": item["symbol"], "item": item, "result": result})

        db_queue(item)
        db_result(result)
        db_event("completed", {**item, "message": result["summary"]})

        processed.append(result)

    queue["updated_at"] = now()
    results["updated_at"] = now()
    events["updated_at"] = now()
    save_json(QUEUE, queue)
    save_json(RESULTS, results)
    save_json(EVENTS, events)
    log_line({"event": "processed", "count": len(processed)})

    out = {"ok": True, "processed": len(processed), "results_file": str(RESULTS)}
    print(json.dumps(out, indent=2) if args.json else out)

if __name__ == "__main__":
    main()
```
