"""
Health Learning Engine — makes the health inspector self-learning over time.

Three learning dimensions:
1. THRESHOLD SELF-TUNING: Adjusts freshness thresholds based on actual pipeline cadence
2. REMEDIATION PRIORITY: Learns which fixes work best for which failure patterns
3. PATTERN DISCOVERY: Detects new staleness patterns not in the runbook
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from collections import defaultdict

TRADEAI_ROOT = "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
sys.path.insert(0, os.path.join(TRADEAI_ROOT, "scripts"))


class HealthLearningEngine:
    def __init__(self, conn, llm_call_fn=None):
        """
        conn: psycopg2 connection
        llm_call_fn: function(prompt) -> str for LLM analysis
        """
        self.conn = conn
        self.llm_call = llm_call_fn

    # ── THRESHOLD SELF-TUNING ──

    def analyze_pipeline_cadence(self, producer_name, lookback_days=30):
        """Calculate actual production cadence and recommend threshold."""
        cur = self.conn.cursor()
        cur.execute(
            """
            WITH gaps AS (
                SELECT
                    EXTRACT(EPOCH FROM (lead(created_at) OVER w - created_at))/3600 as gap_h
                FROM hermes_research_intelligence
                WHERE (topic ILIKE %s OR summary ILIKE %s)
                  AND created_at > now() - interval '%s days'
                WINDOW w AS (ORDER BY created_at)
            )
            SELECT
                AVG(gap_h) as avg_gap_h,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY gap_h) as p95_gap_h,
                COUNT(*) as sample_count
            FROM gaps
            WHERE gap_h IS NOT NULL
        """,
            (f"%{producer_name}%", f"%{producer_name}%", lookback_days),
        )
        row = cur.fetchone()
        cur.close()

        if row and row[0]:
            return {
                "producer": producer_name,
                "avg_gap_h": round(row[0], 1),
                "p95_gap_h": round(row[1], 1) if row[1] else None,
                "sample_count": row[2],
                "recommended_threshold_h": round(
                    max(row[1] * 1.5, row[0] * 3, 2), 1
                )
                if row[1]
                else None,
                "confidence": min(row[2] / 10, 1.0),
            }
        return None

    def stage_threshold_adjustment(
        self, producer_name, old_threshold_h, new_threshold_h, confidence
    ):
        """Stage a threshold adjustment finding."""
        cur = self.conn.cursor()
        confidence_pct = int(confidence * 100)
        summary = (
            f"Threshold adjusted: {producer_name} {old_threshold_h}h -> {new_threshold_h}h "
            f"(confidence: {confidence_pct}%)"
        )
        cur.execute(
            """
            INSERT INTO hermes_research_intelligence
                (source, hermes_agent_name, research_type, topic, summary, thesis,
                 confidence_score, status, tags, threshold_adjusted,
                 freshness_date, model_used, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, true, CURRENT_DATE, %s, NOW(), NOW())
        """,
            (
                "hermes",
                "hermes_health_inspector",
                "threshold_tuning",
                "threshold_tuning",
                summary,
                summary,
                confidence,
                "staged",
                '{"health_inspection","threshold_tuning","P3"}',
                "learning_engine",
            ),
        )
        self.conn.commit()
        cur.close()
        return new_threshold_h

    # ── REMEDIATION PRIORITY LEARNING ──

    def learn_remediation_effectiveness(self, lookback_days=30):
        """Calculate success rate for each remediation type."""
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT
                research_type,
                hermes_agent_name,
                COUNT(*) as total_attempts,
                SUM(CASE WHEN remediation_success = true THEN 1 ELSE 0 END) as successes,
                AVG(CASE WHEN remediation_duration_ms IS NOT NULL THEN remediation_duration_ms END) as avg_duration_ms
            FROM hermes_research_intelligence
            WHERE remediation_success IS NOT NULL
              AND created_at > now() - interval '%s days'
            GROUP BY research_type, hermes_agent_name
            ORDER BY total_attempts DESC
        """,
            (lookback_days,),
        )
        rows = cur.fetchall()
        cur.close()

        priorities = {}
        for row in rows:
            key = f"{row[1]}::{row[0]}"
            total = row[2]
            successes = row[3] or 0
            rate = successes / total if total > 0 else 0
            priorities[key] = {
                "success_rate": round(rate, 3),
                "total_attempts": total,
                "avg_duration_ms": round(row[4]) if row[4] else None,
                "priority_rank": round(
                    rate * (1 - 1 / (total + 1)), 3
                ),
            }

        sorted_priorities = dict(
            sorted(
                priorities.items(),
                key=lambda x: x[1]["priority_rank"],
                reverse=True,
            )
        )
        return sorted_priorities

    def get_remediation_order(self, failure_type):
        """Get the learned remediation order for a failure type."""
        priorities = self.learn_remediation_effectiveness()
        matching = {
            k: v for k, v in priorities.items() if failure_type in k
        }
        return dict(
            sorted(matching.items(), key=lambda x: x[1]["priority_rank"], reverse=True)
        )

    # ── PATTERN DISCOVERY ──

    def discover_new_patterns(self, use_llm=True):
        """Find correlated failures that co-occur — may indicate new pattern types."""
        cur = self.conn.cursor()
        cur.execute(
            """
            WITH paired AS (
                SELECT
                    a.topic as topic_a,
                    b.topic as topic_b,
                    a.created_at as time_a,
                    b.created_at as time_b
                FROM hermes_research_intelligence a
                JOIN hermes_research_intelligence b
                    ON a.id < b.id
                    AND ABS(EXTRACT(EPOCH FROM (a.created_at - b.created_at))) < 3600
                WHERE a.created_at > now() - interval '14 days'
                  AND b.created_at > now() - interval '14 days'
                  AND a.tags && ARRAY['P0','P1']
                  AND b.tags && ARRAY['P0','P1']
            )
            SELECT topic_a, topic_b, COUNT(*) as co_occurrences
            FROM paired
            GROUP BY topic_a, topic_b
            HAVING COUNT(*) >= 2
            ORDER BY co_occurrences DESC
            LIMIT 20
        """
        )
        rows = cur.fetchall()
        cur.close()

        patterns = []
        for row in rows:
            patterns.append(
                {
                    "topic_a": row[0],
                    "topic_b": row[1],
                    "co_occurrences": row[2],
                    "pattern_type": "CORRELATED_FAILURE",
                }
            )

        if use_llm and self.llm_call and patterns:
            llm_analysis = self._llm_analyze_patterns(patterns)
            if llm_analysis:
                patterns.append(
                    {"llm_analysis": llm_analysis, "pattern_type": "LLM_DISCOVERED"}
                )

        return patterns

    def _llm_analyze_patterns(self, co_occurrence_data):
        """Use Claude/DeepSeek to analyze co-occurrence patterns."""
        prompt = f"""You are a systems health analyst. Analyze these co-occurring failure patterns from a trading pipeline.

Co-occurrence data:
{json.dumps(co_occurrence_data, indent=2)}

For each pair that co-occurs >=2 times, determine:
1. Is there a causal relationship (does A breaking cause B to break)?
2. What is the root cause hypothesis?
3. Should this be a new runbook entry? If so, suggest severity, diagnostics, and remediation.

Respond in JSON:
{{"discovered_patterns": [{{"name": "pattern_name", "producers": ["a","b"], "causal": true/false, "root_cause_hypothesis": "...", "severity": "P0|P1|P2|P3", "suggested_diagnostics": ["..."], "suggested_remediation": "...", "confidence": 0.0-1.0}}], "summary": "..."}}
"""
        try:
            result = self.llm_call(prompt)
            return json.loads(result) if isinstance(result, str) else result
        except Exception:
            return {"error": "LLM analysis failed", "patterns": co_occurrence_data}

    # ── DISCOVERY STAGING ──

    def stage_discovered_pattern(self, pattern):
        """Stage a newly discovered pattern."""
        cur = self.conn.cursor()
        name = pattern.get("name", "unknown")
        hypothesis = pattern.get(
            "root_cause_hypothesis", f"New pattern: {name}"
        )
        sev = pattern.get("severity", "P3")
        conf = pattern.get("confidence", 0.5)
        cur.execute(
            """
            INSERT INTO hermes_research_intelligence
                (source, hermes_agent_name, research_type, topic, summary, thesis,
                 confidence_score, status, tags, new_pattern_discovered,
                 pattern_signature, freshness_date, model_used, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, true, %s, CURRENT_DATE, %s, NOW(), NOW())
        """,
            (
                "hermes",
                "hermes_health_inspector",
                "pattern_discovery",
                "pattern_discovery",
                hypothesis[:200],
                hypothesis[:500],
                conf,
                "staged",
                '{"health_inspection","pattern_discovery","' + sev + '"}',
                name,
                "learning_engine",
            ),
        )
        self.conn.commit()
        cur.close()

    # ── FULL LEARNING CYCLE ──

    def run_learning_cycle(self, producers_config, cycle_number):
        """
        Full self-learning pass.
        producers_config: dict of {producer_name: {max_age_h, ...}}
        cycle_number: incrementing cycle counter
        """
        results = {
            "cycle": cycle_number,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "threshold_adjustments": [],
            "remediation_priorities": {},
            "discovered_patterns": [],
            "new_runbook_entries": [],
        }

        # 1. THRESHOLD SELF-TUNING
        for producer_name, config in producers_config.items():
            cadence = self.analyze_pipeline_cadence(producer_name)
            if (
                cadence
                and cadence["recommended_threshold_h"]
                and cadence["confidence"] > 0.3
            ):
                old_h = config.get("max_age_h", 24)
                if (
                    abs(cadence["recommended_threshold_h"] - old_h) / old_h
                    > 0.2
                ):
                    new_h = self.stage_threshold_adjustment(
                        producer_name,
                        old_h,
                        cadence["recommended_threshold_h"],
                        cadence["confidence"],
                    )
                    results["threshold_adjustments"].append(
                        {
                            "producer": producer_name,
                            "old_h": old_h,
                            "new_h": new_h,
                            "confidence": cadence["confidence"],
                        }
                    )

        # 2. REMEDIATION PRIORITY LEARNING
        results["remediation_priorities"] = (
            self.learn_remediation_effectiveness()
        )

        # 3. PATTERN DISCOVERY
        discovered = self.discover_new_patterns(use_llm=True)
        for pattern in discovered:
            if "llm_analysis" not in str(pattern):
                self.stage_discovered_pattern(pattern)
        results["discovered_patterns"] = discovered

        # Update learning cycle counter for rows in this cycle
        cur = self.conn.cursor()
        cur.execute(
            """
            UPDATE hermes_research_intelligence
            SET learning_cycle = %s
            WHERE learning_cycle = 0 AND created_at > now() - interval '1 hour'
        """,
            (cycle_number,),
        )
        self.conn.commit()
        cur.close()

        return results
