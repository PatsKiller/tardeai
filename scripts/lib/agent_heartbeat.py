"""
Agent heartbeat — emit liveness signals that the watchdog monitors.
"""

import os


class AgentHeartbeat:
    HEARTBEAT_INTERVAL_S = 30  # emit every 30s

    def __init__(self, conn, agent_id, pid=None, task=None):
        self.conn = conn
        self.agent_id = agent_id
        self.pid = pid or os.getpid()
        self.task = task

    def register(self):
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO agent_heartbeat (agent_id, pid, status, current_task, started_at, last_seen)
            VALUES (%s, %s, 'ALIVE', %s, now(), now())
            ON CONFLICT (agent_id) DO UPDATE
            SET last_seen = now(), status = 'ALIVE', current_task = %s, pid = %s
        """, (self.agent_id, self.pid, self.task, self.task, self.pid))
        self.conn.commit()
        cur.close()

    def heartbeat(self):
        cur = self.conn.cursor()
        cur.execute("""
            UPDATE agent_heartbeat SET last_seen = now()
            WHERE agent_id = %s
        """, (self.agent_id,))
        self.conn.commit()
        cur.close()

    def mark_done(self, success=True, error=None):
        cur = self.conn.cursor()
        cur.execute("""
            UPDATE agent_heartbeat
            SET status = 'ALIVE', last_seen = now(),
                error_count = CASE WHEN %s THEN error_count + 1 ELSE error_count END,
                last_error = %s
            WHERE agent_id = %s
        """, (not success, error[:500] if error else None, self.agent_id))
        self.conn.commit()
        cur.close()
