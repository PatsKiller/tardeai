"""Classifier Health Check — daily monitoring for strategy-per-ticker inflation."""
import os, json, psycopg2
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
for line in (PROJECT_ROOT / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

THRESHOLD = 3

def check():
    conn = psycopg2.connect(host=os.environ.get("DB_HOST", "localhost"),
                            dbname=os.environ.get("DB_NAME", "trade_ai"),
                            user=os.environ.get("DB_USER", "trade_ai"),
                            password=os.environ.get("DB_PASSWORD", ""))
    cur = conn.cursor()
    cur.execute("""SELECT symbol, COUNT(DISTINCT strategy_id) AS sc,
                          ARRAY_AGG(DISTINCT strategy_id) AS strategies
                   FROM strategy_signals WHERE fired_at > NOW() - INTERVAL '1 day'
                   GROUP BY symbol HAVING COUNT(DISTINCT strategy_id) > %s
                   ORDER BY sc DESC LIMIT 10""", (THRESHOLD,))
    violations = cur.fetchall()
    cur.execute("""SELECT COALESCE(MAX(sc), 0) FROM (
                     SELECT COUNT(DISTINCT strategy_id) AS sc
                     FROM strategy_signals WHERE fired_at > NOW() - INTERVAL '1 day'
                     GROUP BY symbol) x""")
    max_strats = cur.fetchone()[0]
    conn.close()
    return {"checked_at": datetime.utcnow().isoformat() + "Z", "threshold": THRESHOLD,
            "violation_count": len(violations), "max_strategies_per_ticker_1d": max_strats,
            "regression_detected": max_strats > THRESHOLD,
            "top_violators": [{"symbol": v[0], "count": v[1], "strategies": list(v[2])} for v in violations[:5]]}

if __name__ == "__main__":
    result = check()
    print(json.dumps(result, indent=2))
    os.makedirs("data/monitoring", exist_ok=True)
    with open("data/monitoring/classifier_health.json", "w") as f:
        json.dump(result, f, indent=2)
    if result["regression_detected"]:
        print("\n!!! CLASSIFIER REGRESSION DETECTED !!!"); exit(1)
    print("\nClassifier health: OK")
