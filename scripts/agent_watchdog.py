#!/usr/bin/env python3
"""
Agent Watchdog — detects hung/dead agents and escalates.
Runs every 5 minutes via cron.
"""

import sys
import os
import json
from datetime import datetime

TRADEAI_ROOT = "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
sys.path.insert(0, os.path.join(TRADEAI_ROOT, "scripts"))


def main():
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
    except Exception as e:
        print(f"DB connection failed: {e}")
        sys.exit(1)
    if not conn:
        print("DB connection failed")
        sys.exit(1)

    cur = conn.cursor()

    # Find hung agents (>15 min since last heartbeat, not already marked DEAD)
    cur.execute("""
        SELECT agent_id, status,
               EXTRACT(EPOCH FROM (now() - last_seen))/60 as mins,
               pid, current_task, last_error
        FROM agent_heartbeat
        WHERE last_seen < now() - interval '15 minutes'
          AND status NOT IN ('DEAD', 'RESTARTING')
    """)
    hung = cur.fetchall()

    for agent in hung:
        agent_id = agent[0]
        mins = agent[2]
        pid = agent[3]

        # Mark as HUNG
        cur.execute("""
            UPDATE agent_heartbeat SET status = 'HUNG'
            WHERE agent_id = %s
        """, (agent_id,))
        conn.commit()

        # Check if PID still exists
        if pid:
            try:
                os.kill(pid, 0)  # signal 0 just checks existence
                pid_alive = True
            except (OSError, ProcessLookupError):
                pid_alive = False
        else:
            pid_alive = False

        # Escalation payload
        escalation = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "type": "AGENT_HUNG",
            "agent_id": agent_id,
            "minutes_since_seen": round(mins, 1),
            "pid_alive": pid_alive,
            "pid": pid,
            "current_task": agent[4],
            "severity": "P0" if mins > 30 else "P1",
            "recommended_action": "restart_agent" if mins > 30 else "investigate",
            "last_error": agent[5],
        }

        # Write to escalation queue
        queue_path = os.path.join(TRADEAI_ROOT, "data", "runtime", "staleness_escalation_queue.json")
        os.makedirs(os.path.dirname(queue_path), exist_ok=True)
        try:
            with open(queue_path, "r") as f:
                queue = json.load(f)
        except Exception:
            queue = []
        queue.append(escalation)
        with open(queue_path, "w") as f:
            json.dump(queue, f, indent=2)

        # Also write to main claude escalation queue
        claude_queue_path = os.path.join(TRADEAI_ROOT, "logs", "claude_escalation_queue.json")
        try:
            with open(claude_queue_path, "r") as f:
                cq = json.load(f)
        except Exception:
            cq = []
        cq.append(escalation)
        with open(claude_queue_path, "w") as f:
            json.dump(cq, f, indent=2)

        print(f"ESCALATED: {agent_id} hung for {mins:.0f}min (pid alive: {pid_alive})")

    cur.close()
    conn.close()

    if hung:
        print(f"TOTAL: {len(hung)} agents escalated")
    else:
        print("All agents healthy")


if __name__ == "__main__":
    main()
