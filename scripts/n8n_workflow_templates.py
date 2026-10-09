#!/usr/bin/env python3
"""n8n_workflow_templates.py — generate the scheduler-of-record workflows for the N1–N7 lanes.

One template, two workflows per lane:

    <lane_id>-shadow   mode=dry_run   (imported inactive; activated first, cron line still live)
    <lane_id>          mode=live      (imported inactive; activated at canary, cron retired at cutover)

Node chain for an ungated lane (fixed; a test pins the node-type set):

    Schedule Trigger  →  Set "Relay constants"  →  HTTP Request v4.2  →  Code "Assert REQUESTED"
    (cron expression,     (TRADEAI_N8N_RUN_URL,     POST {url}/run,        status 200 and
     America/New_York)     placeholder host)        Header Auth credential  state REQUESTED
                                                    `tradeai-run-relay`,    or duplicate:true,
                                                    10 s, fullResponse)     else throw(lane id)

A lane with `after` (four N2 edges only) inserts a gate between Set and POST: HTTP GET
{url}/runs/<after>/last, a Code node that requires state RUN_DONE on the same America/New_York
calendar day as the execution, an IF, and on the false branch a Wait of GATE_RETRY_WAIT_S seconds
that retries the GET. After MAX_GATE_RETRIES failed waits the Code node throws with the lane id.
Ungated lanes keep the four-node chain above; their node types and ids do not change.

Why a Set node and not `$env`: the lab compose sets `N8N_BLOCK_ENV_ACCESS_IN_NODE=true`
(`docker-compose.n8n.yml`), so `{{ $env.X }}` throws inside the container. The relay host
and port are pending operator permission, so the generator never bakes an IP: the Set node
carries the placeholder `http://RELAY_HOST:18092` and the operator edits ONE value per
workflow — or re-runs this generator with `--relay-url` once the address is granted.

The workflow only ever asks the relay to *request* a run. It never runs a command, never
sends, never touches a secret other than the one relay bearer; the executor on the host
runs the lane's own runner under the lane's own lock (plan: streamed-humming-wolf, 2026-10-08).

    python3 scripts/n8n_workflow_templates.py --lanes N1 --out docs/implementation/n8n-parallel/workflows/generated
    python3 scripts/n8n_workflow_templates.py --lanes all --check     # CI: committed files == regenerated

Output is deterministic: workflow and node ids derive from sha256/uuid5 of the lane id, keys
are sorted, 2-space indent, trailing newline. `INDEX.json` keeps its `generated_at` while
nothing else changed, so a re-run on an unchanged tree is a no-op.

Schedules were read on 2026-10-08 from `crontab -l`, `systemctl --user cat <timer>` and
`config/lane_registry.json` (`scheduler.expression`); the table below is a static copy so the
generator and the CI check do not depend on the host they run on. Each row names its source.

AUTHORITY: READ_ONLY_ADVISORY. Writes only under --out. Importing into n8n is an operator step.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "docs" / "implementation" / "n8n-parallel" / "workflows" / "generated"
SCHEMA = "N8nWorkflowSet@v1"
NO_CONSUMER_REASON = (
    "Generator run by hand (and by CI in --check mode); the committed workflow JSON under "
    "docs/implementation/n8n-parallel/workflows/generated/ is the consumer. Importing into n8n "
    "is an operator step (docker exec m8m-n8n n8n import:workflow)."
)

TIMEZONE = "America/New_York"
CREDENTIAL_NAME = "tradeai-run-relay"
RELAY_URL_PLACEHOLDER = "http://RELAY_HOST:18092"
RELAY_URL_VAR = "TRADEAI_N8N_RUN_URL"
HTTP_TIMEOUT_MS = 10_000
# Failed predecessor checks wait this long, then GET /runs/<after>/last again.
GATE_RETRY_WAIT_S = 60
# How many of those waits are allowed. The next failure throws. Pinned by the generator test.
MAX_GATE_RETRIES = 5
TRANCHES = ("N1", "N2", "N3", "N4", "N5", "N6", "N7")
# Tranches committed under generated/ directly; the rest land under generated/pending/.
# N7 (ops lanes, 2026-10-09) is committed: every N7 lane has a config/n8n_run_allowlist.json entry.
COMMITTED_TRANCHES = ("N1", "N7")

# Ungated workflows are exactly these four. Gated workflows may also use IF and Wait.
UNGATED_NODE_TYPES = frozenset(
    {
        "n8n-nodes-base.scheduleTrigger",
        "n8n-nodes-base.set",
        "n8n-nodes-base.httpRequest",
        "n8n-nodes-base.code",
    }
)
# The only node types a generated workflow may contain. tests pin this set.
ALLOWED_NODE_TYPES = UNGATED_NODE_TYPES | frozenset(
    {
        "n8n-nodes-base.if",
        "n8n-nodes-base.wait",
    }
)
_AFTER_RE = re.compile(r"^[A-Za-z0-9._-]+$")
N_SCHED = "Schedule"
N_SET = "Relay constants"
N_GET = "GET predecessor last"
N_GATE = "Evaluate predecessor"
N_IF = "Predecessor ready"
N_WAIT = "Wait retry"
N_POST = "POST relay /run"
N_ASSERT = "Assert REQUESTED"

_UUID_NS = uuid.UUID("6f2c0a1e-5c7b-4d3a-9e1f-0a8b7c6d5e4f")

# ---------------------------------------------------------------------------
# Lane table. fidelity: EXACT (cron copied verbatim or a lossless OnCalendar conversion),
# APPROXIMATE (cron cannot express the systemd/OpenClaw rule; note says how), PROPOSED (no
# scheduler entry exists yet; the row quotes the proposed line), ONE_SHOT (an `at` job).
# ---------------------------------------------------------------------------
LANES: list[dict] = [
    # ---- N1 coordination-only ------------------------------------------------------------
    {
        "lane_id": "n8n-pilot-dispatch",
        "tranche": "N1",
        "cron": ["*/15 * * * *"],
        "fidelity": "EXACT",
        "source": "crontab: */15 * * * * scripts/n8n_pilot_dispatch.py --apply (registry kind cron)",
    },
    {
        "lane_id": "n8n-incident-fanin",
        "tranche": "N1",
        "cron": ["*/5 * * * *"],
        "fidelity": "EXACT",
        "source": "crontab: */5 * * * * scripts/n8n_incident_fanin.py --apply (registry kind cron)",
    },
    {
        "lane_id": "n8n-research-intake-consumer",
        "tranche": "N1",
        "cron": ["*/15 * * * *"],
        "fidelity": "EXACT",
        "source": "crontab: */15 * * * * scripts/n8n_research_intake_consumer.py --apply (registry kind cron)",
    },
    {
        "lane_id": "crontab-snapshot-for-health-agent",
        "tranche": "N1",
        "cron": ["*/20 * * * *"],
        "fidelity": "EXACT",
        "source": "crontab: */20 * * * * crontab -l > .../crontab_snapshot.txt (registry kind cron)",
    },
    {
        "lane_id": "n8n-lab-watchdog",
        "tranche": "N1",
        "cron": ["*/5 * * * *"],
        "fidelity": "EXACT",
        "source": "systemd: tradeai-n8n-lab-watchdog.timer OnUnitActiveSec=5min (registry kind systemd)",
    },
    {
        "lane_id": "lane-governance-packet-weekly",
        "tranche": "N1",
        "cron": ["20 6 * * 1"],
        "fidelity": "PROPOSED",
        "source": "registry row NEVER_SCHEDULED; proposed line '20 6 * * 1 report_lane_governance_packet.py --write --period weekly'",
        "note": "No scheduler entry exists yet; n8n would be the first scheduler-of-record. Needs the registry row flipped from NEVER_SCHEDULED.",
    },
    {
        "lane_id": "maturity-remeasure",
        "tranche": "N1",
        "cron": ["40 6 * * 1"],
        "fidelity": "EXACT",
        "source": "crontab: 40 6 * * 1 scripts/maturity_remeasure.py --write (registry kind cron)",
    },
    {
        "lane_id": "n8n-monitor-trade-ai",
        "tranche": "N1",
        "cron": ["*/5 * * * *"],
        "fidelity": "EXACT",
        "source": "n8n workflow s57KBllvqf6Jb5xF 'Every 5 minutes' (workflows/INDEX.json)",
        "note": "An n8n workflow of this NAME already exists (GET build-meta, target lost to loopback binding). Rename or deactivate it before import so the name is not duplicated.",
    },
    {
        "lane_id": "n8n-monitor-dof",
        "tranche": "N1",
        "cron": ["*/5 * * * *"],
        "fidelity": "EXACT",
        "source": "n8n workflow GXwhbRkwsGcYZxgn 'Every 5 minutes' (workflows/INDEX.json)",
        "note": "An n8n workflow of this NAME already exists (GET run-scope). Rename or deactivate it before import.",
    },
    # ---- N2 pipeline orchestration --------------------------------------------------------
    {
        "lane_id": "premarket-data-pipeline",
        "tranche": "N2",
        "cron": ["45 5 * * *"],
        "fidelity": "EXACT",
        "source": "crontab: 45 5 * * * run_premarket_data_pipeline.sh --stage premarket (registry kind cron)",
    },
    {
        "lane_id": "after-close-pipeline-close-capture",
        "tranche": "N2",
        "cron": ["5 16 * * 1-5"],
        "fidelity": "EXACT",
        "source": "crontab: 5 16 * * 1-5 run_after_close_pipeline.sh --stage close-capture (registry kind cron)",
        "pipeline": "after_close",
        "stage_order": 1,
    },
    {
        "lane_id": "after-close-pipeline-broker-truth",
        "tranche": "N2",
        "cron": ["25 17 * * 1-5"],
        "fidelity": "EXACT",
        "source": "crontab: 25 17 * * 1-5 run_after_close_pipeline.sh --stage broker-truth (registry kind cron)",
        "pipeline": "after_close",
        "stage_order": 2,
        "after": "after-close-pipeline-close-capture",
    },
    {
        "lane_id": "after-close-pipeline-planning",
        "tranche": "N2",
        "cron": ["35 17 * * 1-5"],
        "fidelity": "EXACT",
        "source": "crontab: 35 17 * * 1-5 run_after_close_pipeline.sh --stage planning (registry kind cron)",
        "pipeline": "after_close",
        "stage_order": 3,
        "after": "after-close-pipeline-broker-truth",
    },
    {
        "lane_id": "hermes-learning-pipeline-learn",
        "tranche": "N2",
        "cron": ["50 10 * * *"],
        "fidelity": "EXACT",
        "source": "crontab: 50 10 * * * run_hermes_pipeline.sh --stage learn (registry kind cron)",
        "pipeline": "hermes_learning",
        "stage_order": 1,
    },
    {
        "lane_id": "hermes-learning-pipeline-tune",
        "tranche": "N2",
        "cron": ["0 17 * * *"],
        "fidelity": "EXACT",
        "source": "crontab: 0 17 * * * run_hermes_pipeline.sh --stage tune (registry kind cron)",
        "pipeline": "hermes_learning",
        "stage_order": 2,
        "after": "hermes-learning-pipeline-learn",
    },
    {
        "lane_id": "hermes-overnight-pipeline-close",
        "tranche": "N2",
        "cron": ["13 23 * * *"],
        "fidelity": "EXACT",
        "source": "crontab: 13 23 * * * run_hermes_pipeline.sh --manifest hermes_overnight.json --stage close (registry kind cron)",
        "pipeline": "hermes_overnight",
        "stage_order": 1,
    },
    {
        "lane_id": "hermes-overnight-pipeline-night",
        "tranche": "N2",
        "cron": ["20 2 * * *"],
        "fidelity": "EXACT",
        "source": "crontab: 20 2 * * * run_hermes_pipeline.sh --manifest hermes_overnight.json --stage night (registry kind cron)",
        "pipeline": "hermes_overnight",
        "stage_order": 2,
        "after": "hermes-overnight-pipeline-close",
    },
    {
        "lane_id": "platform-maintenance-nightly",
        "tranche": "N2",
        "cron": ["15 1 * * *"],
        "fidelity": "EXACT",
        "source": "systemd: tradeai-platform-maintenance-nightly.timer OnCalendar=*-*-* 01:15:00 (registry kind systemd)",
    },
    {
        "lane_id": "platform-maintenance-weekly",
        "tranche": "N2",
        "cron": ["0 3 * * 0"],
        "fidelity": "EXACT",
        "source": "systemd: tradeai-platform-maintenance-weekly.timer OnCalendar=Sun *-*-* 03:00:00 (registry kind systemd)",
    },
    {
        "lane_id": "platform-maintenance-monthly",
        "tranche": "N2",
        "cron": ["0 6 1 * *"],
        "fidelity": "EXACT",
        "source": "systemd: tradeai-platform-maintenance-monthly.timer OnCalendar=*-*-01 06:00:00 (registry kind systemd)",
    },
    {
        "lane_id": "governance-pipeline",
        "tranche": "N2",
        "cron": ["40 7 * * 1-5", "0 18 * * 0"],
        "fidelity": "EXACT",
        "source": "systemd: tradeai-governance-pipeline.timer OnCalendar=Mon-Fri 07:40 + OnCalendar=Sun 18:00 (registry kind systemd; runs from the dev tree, re-pin pending)",
    },
    {
        "lane_id": "portfolio-daily-cadence",
        "tranche": "N2",
        "cron": ["30 7 * * 1-5"],
        "fidelity": "EXACT",
        "source": "systemd: tradeai-portfolio-daily-cadence.timer OnCalendar=Mon-Fri *-*-* 07:30:00 (registry kind systemd; dev tree, re-pin pending)",
    },
    {
        "lane_id": "portfolio-weekly-cadence",
        "tranche": "N2",
        "cron": ["30 20 * * 0"],
        "fidelity": "EXACT",
        "source": "systemd: tradeai-portfolio-weekly-cadence.timer OnCalendar=Sun *-*-* 20:30:00 (registry kind systemd; dev tree, re-pin pending)",
    },
    {
        "lane_id": "portfolio-monthly-cadence",
        "tranche": "N2",
        "cron": ["35 7 1 * *"],
        "fidelity": "EXACT",
        "source": "systemd: tradeai-portfolio-monthly-cadence.timer OnCalendar=*-*-01 07:35:00 (registry kind systemd; dev tree, re-pin pending)",
    },
    {
        "lane_id": "portfolio-lookthrough-cadence",
        "tranche": "N2",
        "cron": ["30 6 1-7 * 0"],
        "fidelity": "APPROXIMATE",
        "source": "systemd: tradeai-portfolio-lookthrough-cadence.timer OnCalendar=Sun *-*-01..07 06:30:00 (registry kind systemd; dev tree, re-pin pending)",
        "note": "systemd means the FIRST Sunday of the month. Vixie-style cron (and n8n's scheduler) ORs day-of-month with day-of-week, so '30 6 1-7 * 0' also fires on the 1st-7th and on every Sunday. Operator decision: accept the extra fires (the runner is idempotent per its receipt) or keep this one lane on its timer.",
    },
    {
        "lane_id": "portfolio-backup-cadence",
        "tranche": "N2",
        "cron": ["30 2 * * *"],
        "fidelity": "EXACT",
        "source": "systemd: tradeai-portfolio-backup-cadence.timer OnCalendar=*-*-* 02:30:00 (registry kind systemd; dev tree, re-pin pending)",
        "note": "Doc 16 §4.2 lists this lane under both N2 ('portfolio cadences x5') and N5; it is generated once, here. The unique lane count is therefore 70, not 71.",
    },
    # ---- N3 reports and digests ---------------------------------------------------------
    {
        "lane_id": "llm-spend-report-daily",
        "tranche": "N3",
        "cron": ["5 7 * * *"],
        "fidelity": "EXACT",
        "source": "crontab: 5 7 * * * scripts/llm_spend_report.py --period daily --send (registry kind cron)",
    },
    {
        "lane_id": "llm-spend-report-weekly",
        "tranche": "N3",
        "cron": ["10 7 * * 1"],
        "fidelity": "EXACT",
        "source": "crontab: 10 7 * * 1 scripts/llm_spend_report.py --period weekly --send (registry kind cron)",
    },
    {
        "lane_id": "llm-spend-report-monthly",
        "tranche": "N3",
        "cron": ["15 7 1 * *"],
        "fidelity": "EXACT",
        "source": "crontab: 15 7 1 * * scripts/llm_spend_report.py --period monthly --send (registry kind cron)",
    },
    {
        "lane_id": "material-change-digest",
        "tranche": "N3",
        "cron": ["15 16 * * *"],
        "fidelity": "EXACT",
        "source": "crontab: 15 16 * * * scripts/notify_material_change.py --digest --apply (registry kind cron)",
    },
    {
        "lane_id": "alert-daily-digest",
        "tranche": "N3",
        "cron": ["55 17 * * 1-5"],
        "fidelity": "EXACT",
        "source": "crontab: 55 17 * * 1-5 scripts/alert_daily_digest.py (no registry row; needs --receipt)",
    },
    {
        "lane_id": "ops-daily-digest",
        "tranche": "N3",
        "cron": ["0 18 * * *"],
        "fidelity": "EXACT",
        "source": "crontab: 0 18 * * * ~/.openclaw/skills/tradeai-health-inspect/scripts/ops_daily_digest.py (no registry row; needs --receipt)",
    },
    {
        "lane_id": "ops-weekly-learning-report",
        "tranche": "N3",
        "cron": ["30 9 * * 0"],
        "fidelity": "EXACT",
        "source": "crontab: 30 9 * * 0 ~/.openclaw/skills/tradeai-health-inspect/scripts/ops_weekly_learning_report.py (no registry row)",
    },
    {
        "lane_id": "system-rollup-snapshot",
        "tranche": "N3",
        "cron": ["40 20 * * *"],
        "fidelity": "EXACT",
        "source": "crontab: 40 20 * * * scripts/system_rollup_snapshot.py (no registry row)",
    },
    {
        "lane_id": "generate-weekly-docx",
        "tranche": "N3",
        "cron": ["0 21 * * 0"],
        "fidelity": "EXACT",
        "source": "crontab: 0 21 * * 0 scripts/generate_weekly_docx.py (no registry row)",
    },
    {
        "lane_id": "generate-analyst-daily-digest",
        "tranche": "N3",
        "cron": ["30 7 * * 1-5"],
        "fidelity": "EXACT",
        "source": "crontab: 30 7 * * 1-5 scripts/generate_analyst_daily_digest.py --format docx (no registry row)",
    },
    {
        "lane_id": "desk-suggestions-digest",
        "tranche": "N3",
        "cron": ["0 8 * * 1-5"],
        "fidelity": "EXACT",
        "source": "crontab: 0 8 * * 1-5 scripts/desk_suggestions_digest.py (no registry row; needs --receipt)",
    },
    {
        "lane_id": "rotation-rebalance-digest",
        "tranche": "N3",
        "cron": ["0 18 * * 0"],
        "fidelity": "EXACT",
        "source": "crontab: 0 18 * * 0 scripts/rotation_rebalance_digest.py (no registry row)",
    },
    # ---- N4 audits and monitors ---------------------------------------------------------
    {
        "lane_id": "expected-services-audit",
        "tranche": "N4",
        "cron": ["12 * * * *"],
        "fidelity": "EXACT",
        "source": "systemd: tradeai-expected-services.timer OnCalendar=*-*-* *:12:00 RandomizedDelaySec=60 (registry kind systemd)",
    },
    {
        "lane_id": "data-source-health-audit",
        "tranche": "N4",
        "cron": ["27 * * * *"],
        "fidelity": "EXACT",
        "source": "systemd: tradeai-data-source-health.timer OnCalendar=*-*-* *:27:00 RandomizedDelaySec=60 (registry kind systemd)",
    },
    {
        "lane_id": "served-copy-split-audit",
        "tranche": "N4",
        "cron": ["42 * * * *"],
        "fidelity": "EXACT",
        "source": "systemd: tradeai-served-copy-split.timer OnCalendar=*-*-* *:42:00 RandomizedDelaySec=60 (registry kind systemd)",
    },
    {
        "lane_id": "data-plausibility-audit",
        "tranche": "N4",
        "cron": ["20 6 * * *"],
        "fidelity": "EXACT",
        "source": "systemd: tradeai-data-plausibility.timer OnCalendar=*-*-* 06:20:00 RandomizedDelaySec=120 (registry kind systemd)",
    },
    {
        "lane_id": "gap-resolution-audit",
        "tranche": "N4",
        "cron": ["7,37 * * * *"],
        "fidelity": "EXACT",
        "source": "systemd: tradeai-gap-resolution.timer OnCalendar=*-*-* *:07,37:00 RandomizedDelaySec=60 (registry kind systemd)",
    },
    {
        "lane_id": "source-litmus-vs-yahoo",
        "tranche": "N4",
        "cron": ["45 7 * * 2-6"],
        "fidelity": "EXACT",
        "source": "systemd: tradeai-source-litmus.timer OnCalendar=Tue..Sat *-*-* 07:45:00 RandomizedDelaySec=120 (registry kind systemd)",
    },
    {
        "lane_id": "finviz-view-contracts",
        "tranche": "N4",
        "cron": ["5 6 * * 1-5"],
        "fidelity": "EXACT",
        "source": "systemd: tradeai-finviz-view-contracts.timer OnCalendar=Mon..Fri *-*-* 06:05:00 RandomizedDelaySec=120 (registry kind systemd)",
    },
    {
        "lane_id": "operator-answer-quality-audit",
        "tranche": "N4",
        "cron": ["22,52 * * * *"],
        "fidelity": "EXACT",
        "source": "systemd: tradeai-operator-answer-quality.timer OnCalendar=*-*-* *:22,52:00 RandomizedDelaySec=60 (registry kind systemd)",
    },
    {
        "lane_id": "research-lane-health",
        "tranche": "N4",
        "cron": ["*/15 * * * *"],
        "fidelity": "EXACT",
        "source": "systemd: tradeai-research-lane-health.timer OnUnitActiveSec=15min (registry kind systemd)",
    },
    {
        "lane_id": "agent-runtime-health",
        "tranche": "N4",
        "cron": ["*/5 * * * *"],
        "fidelity": "EXACT",
        "source": "systemd: tradeai-agent-runtime-health.timer OnUnitActiveSec=5min (registry kind systemd)",
    },
    {
        "lane_id": "job-coverage-monitor",
        "tranche": "N4",
        "cron": ["30 8,20 * * *"],
        "fidelity": "EXACT",
        "source": "crontab: 30 8,20 * * * scripts/job_coverage_monitor.py (no registry row; needs --receipt)",
    },
    {
        "lane_id": "llm-retry-monitor",
        "tranche": "N4",
        "cron": ["0 7 * * *"],
        "fidelity": "EXACT",
        "source": "crontab: 0 7 * * * scripts/llm_retry_monitor.py (no registry row)",
    },
    {
        "lane_id": "catalyst-calibration-monitor",
        "tranche": "N4",
        "cron": ["40 5 * * *"],
        "fidelity": "EXACT",
        "source": "crontab: 40 5 * * * scripts/catalyst_calibration_monitor.py (no registry row)",
    },
    {
        "lane_id": "source-attribution-monitor",
        "tranche": "N4",
        "cron": ["0 6 * * *"],
        "fidelity": "EXACT",
        "source": "crontab: 0 6 * * * scripts/source_attribution_monitor.py (no registry row)",
    },
    {
        "lane_id": "watch-directives-monitor",
        "tranche": "N4",
        "cron": ["20 6 * * *"],
        "fidelity": "EXACT",
        "source": "crontab: 20 6 * * * scripts/watch_directives_monitor.py (no registry row)",
    },
    {
        "lane_id": "hermes-pipeline-health",
        "tranche": "N4",
        "cron": ["45 7,15 * * *"],
        "fidelity": "EXACT",
        "source": "crontab: 45 7,15 * * * scripts/hermes_pipeline_health.py --send (no registry row)",
    },
    {
        "lane_id": "youtube-cookie-health-check",
        "tranche": "N4",
        "cron": ["45 19 * * *"],
        "fidelity": "EXACT",
        "source": "crontab: 45 19 * * * scripts/youtube_cookie_health_check.py (no registry row; needs --receipt)",
    },
    {
        "lane_id": "finviz-health-check",
        "tranche": "N4",
        "cron": ["25 6-18/3 * * 1-5"],
        "fidelity": "EXACT",
        "source": "crontab: 25 6-18/3 * * 1-5 timeout 2m scripts/finviz_health_check.py (no registry row)",
    },
    {
        "lane_id": "crawl-v3-dashboard",
        "tranche": "N4",
        "cron": ["50 6 * * *"],
        "fidelity": "EXACT",
        "source": "crontab: 50 6 * * * scripts/crawl_v3_dashboard.py --telegram (no registry row)",
    },
    {
        "lane_id": "alert-missing-conditions",
        "tranche": "N4",
        "cron": ["30 7 * * 1-5"],
        "fidelity": "EXACT",
        "source": "crontab: 30 7 * * 1-5 scripts/alert_missing_conditions.py (no registry row)",
    },
    # ---- N5 backups and syncs -----------------------------------------------------------
    {
        "lane_id": "drive-syncs-hourly",
        "tranche": "N5",
        "cron": ["5 * * * *"],
        "fidelity": "EXACT",
        "source": "crontab: 5 * * * * scripts/run_drive_syncs.sh --apply (registry kind cron)",
    },
    {
        "lane_id": "backup-generated-docs",
        "tranche": "N5",
        "cron": ["50 23 * * *"],
        "fidelity": "EXACT",
        "source": "crontab: 50 23 * * * linux_launchers/backup_generated_docs.sh (no registry row)",
    },
    {
        "lane_id": "sync-memory-to-drive",
        "tranche": "N5",
        "cron": ["10 3 * * *"],
        "fidelity": "EXACT",
        "source": "crontab: 10 3 * * * ~/.claude/sync-memory-to-drive.sh (no registry row; outside the repo)",
    },
    {
        "lane_id": "commit-hermes-daily",
        "tranche": "N5",
        "cron": ["13 23 * * *"],
        "fidelity": "EXACT",
        "source": "crontab: 13 23 * * * run_with_deepseek_offpeak.sh --official -- scripts/commit_hermes_daily.sh (no registry row)",
    },
    {
        "lane_id": "n8n-lab-backup",
        "tranche": "N5",
        "cron": ["30 3 * * *"],
        "fidelity": "EXACT",
        "source": "registry row RETIRED 2026-10-07 (was crontab 30 3 * * * scripts/n8n_lab_backup.sh --apply); superseded_by platform-maintenance-nightly",
        "note": "Already a step of platform-maintenance-nightly (N2). Generated for completeness; recommend NOT activating — moving the parent lane moves this one.",
    },
    {
        "lane_id": "n8n-lab-restore-drill",
        "tranche": "N5",
        "cron": ["0 4 * * 0"],
        "fidelity": "EXACT",
        "source": "registry row RETIRED 2026-10-07 (was crontab 0 4 * * 0 scripts/n8n_lab_restore_drill.sh --apply); superseded_by platform-maintenance-weekly",
        "note": "Already a step of platform-maintenance-weekly (N2). Generated for completeness; recommend NOT activating.",
    },
    # ---- N6 other projects --------------------------------------------------------------
    {
        "lane_id": "dof-auction-pipeline",
        "tranche": "N6",
        "cron": ["0 20 * * 6"],
        "fidelity": "EXACT",
        "source": "crontab: 0 20 * * 6 ~/nyc-dof-auction scripts/run_pipeline.py (six stages in one line; no registry row; needs dof_reader + allowlist entry)",
    },
    {
        "lane_id": "dof-rescan-tickets",
        "tranche": "N6",
        "cron": ["0 18 * * *"],
        "fidelity": "EXACT",
        "source": "crontab: 0 18 * * * ~/nyc-dof-auction scripts/rescan_tickets.py (no registry row; needs dof_reader + allowlist entry)",
    },
    {
        "lane_id": "openclaw-claude-plan-reminder-week-before",
        "tranche": "N6",
        "cron": ["0 9 24 * *"],
        "fidelity": "EXACT",
        "source": "OpenClaw cron 676c2212 'Claude plan reminder, about a week before month end' 0 9 24 * * (jobs.json)",
        "note": "Delivery stays in OpenClaw; the allowlist entry must call the OpenClaw reminder path, not a Trade AI sender.",
    },
    {
        "lane_id": "openclaw-claude-plan-reminder-last-day",
        "tranche": "N6",
        "cron": ["0 9 28 * *"],
        "fidelity": "APPROXIMATE",
        "source": "OpenClaw cron 0775cd6b 'Claude plan reminder, last day of month' 0 9 L * * (jobs.json)",
        "note": "Standard 5-field cron has no portable 'L' (last day). Moved to the 28th; operator may prefer to leave this reminder in OpenClaw.",
    },
    {
        "lane_id": "openclaw-supergrok-promo-expiry",
        "tranche": "N6",
        "cron": ["0 10 20 10 *"],
        "fidelity": "ONE_SHOT",
        "source": "OpenClaw at-job 9a26d34d 'SuperGrok promo expiry reminder' at 2026-10-20T14:00:00Z (= 10:00 ET)",
        "note": "One-shot. Deactivate the workflow after it fires or it repeats yearly.",
    },
    {
        "lane_id": "openclaw-sentinelone-earnings-reminder",
        "tranche": "N6",
        "cron": ["0 8 7 12 *"],
        "fidelity": "ONE_SHOT",
        "source": "OpenClaw at-job a9c337e0 'SentinelOne (S) earnings reminder' at 2026-12-07T13:00:00Z (= 08:00 ET)",
        "note": "One-shot. Deactivate the workflow after it fires or it repeats yearly.",
    },
    # ---- N7 ops lanes (operator 2026-10-09 "add the lanes"; lanes/ops-lanes-20261009.md) -------
    # No scheduler entry exists for any of these; n8n is the first scheduler-of-record. Every one has an
    # allowlist entry (--dry-run / --write) and a NEVER_SCHEDULED registry row.
    {
        "lane_id": "storage-watch",
        "tranche": "N7",
        "cron": ["10 6 * * *"],
        "fidelity": "PROPOSED",
        "source": "registry row NEVER_SCHEDULED; proposed line '10 6 * * * scripts/storage_watch.py --write'",
        "note": "New lane: no cron line or unit exists; n8n is the first scheduler. Read-only; receipt data/runtime/storage_watch_last.json.",
    },
    {
        "lane_id": "backup-verify",
        "tranche": "N7",
        "cron": ["40 6 * * *"],
        "fidelity": "PROPOSED",
        "source": "registry row NEVER_SCHEDULED; proposed line '40 6 * * * scripts/backup_verify.py --write'",
        "note": "New daily lane. The no-flag form of the same script stays a step of platform-maintenance-monthly; both share /tmp/backup_verify.lock.",
    },
    {
        "lane_id": "trade-ai-restore-drill",
        "tranche": "N7",
        "cron": ["30 3 * * 0"],
        "fidelity": "PROPOSED",
        "source": "registry row NEVER_SCHEDULED; proposed first Sunday 03:30 = '30 3 * * 0' + --first-week-only on the live arg",
        "note": "Fires every Sunday: the shadow (dry_run) prints the plan each week; live is a no-op unless the day is 1-7. '30 3 1-7 * 0' would OR the day fields and fire on days 1-7 and every Sunday.",
    },
    {
        "lane_id": "n8n-workflow-drift-check",
        "tranche": "N7",
        "cron": ["20 6 * * *"],
        "fidelity": "PROPOSED",
        "source": "registry row NEVER_SCHEDULED (AGENTS.md 3.0.0 §23.10 P18, #1554); proposed '20 6 * * * scripts/check_n8n_workflow_drift.py --write'",
        "note": "Daily cadence per the registry row (expected_cadence_hours 24). Read-only; receipt data/runtime/n8n_workflow_drift_last.json.",
    },
    # Trade-AI scalp scan (operator 2026-10-09 "n8n drives a governed lane"; lanes/scalp-lane-20261009.md).
    # The cron line stays the scheduler of record and fallback. Live allowed by the AGENTS.md 4.0.0 §23.3
    # exception (APPROVE_AGENTS_POLICY_4_0_0, 2026-10-09); still needs the relay live-lane listing + activation grant.
    {
        "lane_id": "trade-ai-scalp-live",
        "tranche": "N7",
        "cron": ["*/5 9-15 * * 1-5"],
        "fidelity": "EXACT",
        "source": "crontab: */5 9-15 * * 1-5 run_trade_ai_scalp_live.py (registry kind cron); the script self-gates 09:30-16:00 ET, so the 09:00-09:25 fires exit with receipt status outside_rth",
        "note": "Same /tmp/tradeai_scalp_live.lock (flock -n) as the cron line, so n8n and cron never overlap. Receipt data/runtime/trade_ai_scalp_live_last.json; the incident fan-in raises trade-ai-scalp-live:STALLED when last_ok_at is older than 12 min in RTH.",
    },
]

# ---------------------------------------------------------------------------
# cron validation (5 fields, Vixie subset; what n8n's scheduleTrigger accepts)
# ---------------------------------------------------------------------------
_FIELD = re.compile(r"^(\*|\d+(-\d+)?)(/\d+)?(,(\*|\d+(-\d+)?)(/\d+)?)*$")
_FIELD_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))


def validate_cron(expr: str) -> list[str]:
    """Return problems with a 5-field cron expression; [] when it is acceptable."""
    problems: list[str] = []
    fields = expr.split()
    if len(fields) != 5:
        return [f"expected 5 fields, got {len(fields)}: {expr!r}"]
    for field, (lo, hi) in zip(fields, _FIELD_RANGES):
        if not _FIELD.match(field):
            problems.append(f"bad field {field!r} in {expr!r}")
            continue
        for part in field.split(","):
            base = part.split("/")[0]
            if base == "*":
                continue
            for n in base.split("-"):
                if not lo <= int(n) <= hi:
                    problems.append(f"{n} out of range {lo}-{hi} in {expr!r}")
    return problems


# ---------------------------------------------------------------------------
# systemd OnCalendar -> cron (the forms used by the estate's timers; tests pin them)
# ---------------------------------------------------------------------------
_DOW = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 0}


def _dow_to_cron(spec: str) -> str:
    parts = []
    for chunk in spec.split(","):
        chunk = chunk.strip().lower()
        sep = ".." if ".." in chunk else ("-" if "-" in chunk else None)
        if sep:
            a, b = chunk.split(sep)
            parts.append(f"{_DOW[a]}-{_DOW[b]}")
        else:
            parts.append(str(_DOW[chunk]))
    return ",".join(parts)


def oncalendar_to_cron(value: str) -> str:
    """Convert a systemd OnCalendar value to a 5-field cron expression.

    Handles the shapes present in the estate's timers: optional weekday list/range
    (`Mon-Fri`, `Tue..Sat`, `Sun`), optional date `*-*-*` / `*-*-DD` / `*-*-A..B`, and a
    time `HH:MM[:SS]` or `*:MM[,MM]:SS`. Anything else raises ValueError.
    """
    tokens = value.strip().split()
    dow, date, time = "*", "*-*-*", None
    for tok in tokens:
        if ":" in tok:
            time = tok
        elif "-" in tok and tok[0] in "*0123456789":
            date = tok
        else:
            dow = _dow_to_cron(tok)
    if time is None:
        raise ValueError(f"OnCalendar without a time part: {value!r}")
    hour, minute = time.split(":")[0], time.split(":")[1]
    cron_hour = "*" if hour == "*" else str(int(hour))
    cron_min = ",".join(str(int(m)) for m in minute.split(","))
    dom_spec = date.split("-")[-1]
    if dom_spec == "*":
        dom = "*"
    elif ".." in dom_spec:
        a, b = dom_spec.split("..")
        dom = f"{int(a)}-{int(b)}"
    else:
        dom = str(int(dom_spec))
    cron = f"{cron_min} {cron_hour} {dom} * {dow}"
    problems = validate_cron(cron)
    if problems:
        raise ValueError("; ".join(problems))
    return cron


# ---------------------------------------------------------------------------
# workflow template
# ---------------------------------------------------------------------------
def _wf_id(name: str) -> str:
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]


def _node_id(name: str, node: str) -> str:
    return str(uuid.uuid5(_UUID_NS, f"{name}:{node}"))


def _assert_js(lane_id: str, mode: str) -> str:
    return (
        f"// Generated by scripts/n8n_workflow_templates.py — do not edit in n8n.\n"
        f"const LANE = {json.dumps(lane_id)};\n"
        f"const MODE = {json.dumps(mode)};\n"
        "const item = $input.first();\n"
        "const status = item.json.statusCode;\n"
        "const body = (item.json.body && typeof item.json.body === 'object') ? item.json.body : {};\n"
        "const detail = JSON.stringify(item.json.body ?? null).slice(0, 300);\n"
        "if (status !== 200) {\n"
        "  throw new Error('[' + LANE + '/' + MODE + '] relay returned HTTP ' + String(status) + ': ' + detail);\n"
        "}\n"
        "const accepted = body.duplicate === true || body.state === 'REQUESTED';\n"
        "if (!accepted) {\n"
        "  throw new Error('[' + LANE + '/' + MODE + '] run not REQUESTED: ' + detail);\n"
        "}\n"
        "return [{ json: { lane_id: LANE, mode: MODE, state: body.state ?? null, duplicate: body.duplicate === true,\n"
        "  run_id: body.run_id ?? null, idempotency_key: body.idempotency_key ?? null, requested_at: body.requested_at ?? null } }];\n"
    )


def _single_minute_of_day(cron_exprs: list) -> int | None:
    """Minute-of-day when every expression is one hour and one minute. Otherwise None."""
    found: list[int] = []
    for expr in cron_exprs or []:
        parts = str(expr).split()
        if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
            return None
        minute, hour = int(parts[0]), int(parts[1])
        if minute > 59 or hour > 23:
            return None
        found.append(hour * 60 + minute)
    if len(set(found)) != 1:
        return None
    return found[0]


def predecessor_crosses_midnight(lane: dict, after: str) -> bool:
    """True when the predecessor's single fire is later in the ET day than this lane's.

    hermes-overnight-pipeline-close is 23:13 and hermes-overnight-pipeline-night is
    02:20, so that evening RUN_DONE belongs to the previous America/New_York date.
    A cron that is not a single hour and minute does not cross.
    """
    pred = next((row for row in LANES if row.get("lane_id") == after), None)
    if pred is None:
        return False
    pred_minute = _single_minute_of_day(pred.get("cron") or [])
    lane_minute = _single_minute_of_day(lane.get("cron") or [])
    if pred_minute is None or lane_minute is None:
        return False
    return pred_minute > lane_minute


def _gate_js(lane_id: str, after: str, mode: str, *, crosses_midnight: bool) -> str:
    """Predecessor check. The ET day is taken at execution time, never baked into the JSON."""
    crosses = "true" if crosses_midnight else "false"
    return "\n".join(
        [
            "// Generated by scripts/n8n_workflow_templates.py — do not edit in n8n.",
            f"const MAX_GATE_RETRIES = {MAX_GATE_RETRIES};",
            f"const LANE = {json.dumps(lane_id)};",
            f"const MODE = {json.dumps(mode)};",
            f"const AFTER = {json.dumps(after)};",
            f"const CROSSES_MIDNIGHT = {crosses};",
            "const TZ = 'America/New_York';",
            "function etDay(value) {",
            "  const d = new Date(value);",
            "  if (Number.isNaN(d.getTime())) return '';",
            "  return new Intl.DateTimeFormat('en-CA', {",
            "    timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit'",
            "  }).format(d);",
            "}",
            "function previousEtDay(value) {",
            "  const day = etDay(value);",
            "  const m = /^(\\d{4})-(\\d{2})-(\\d{2})$/.exec(day);",
            "  if (!m) return '';",
            "  const anchor = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]), 17, 0, 0));",
            "  return etDay(new Date(anchor.getTime() - 86400000).toISOString());",
            "}",
            "const item = $input.first().json;",
            "const status = item.statusCode;",
            "const body = (item.body && typeof item.body === 'object') ? item.body : {};",
            "const last = (body.last && typeof body.last === 'object') ? body.last : null;",
            "const finished = last && last.finished_at ? String(last.finished_at) : '';",
            "const nowIso = new Date().toISOString();",
            "const today = etDay(nowIso);",
            "const finishedDay = finished !== '' ? etDay(finished) : '';",
            "const dayOk = finishedDay !== '' && (finishedDay === today ||",
            "  (CROSSES_MIDNIGHT && finishedDay === previousEtDay(nowIso)));",
            "const ok = status === 200 && !!last && last.state === 'RUN_DONE' && dayOk;",
            "let attempt = 1;",
            "try {",
            '  attempt = $("Wait retry").all().length + 1;',
            "} catch (e) {",
            "  attempt = 1;",
            "}",
            f'const relayUrl = $("Relay constants").first().json.{RELAY_URL_VAR};',
            "if (!ok && attempt > MAX_GATE_RETRIES) {",
            "  const windowText = CROSSES_MIDNIGHT",
            "    ? 'the America/New_York day or the previous evening'",
            "    : 'the America/New_York day';",
            "  throw new Error('[' + LANE + '/' + MODE + '] predecessor ' + AFTER +",
            "    ' not RUN_DONE for ' + windowText + ' after ' + String(attempt) +",
            "    ' attempts (MAX_GATE_RETRIES=' + String(MAX_GATE_RETRIES) + ')');",
            "}",
            "return [{ json: {",
            f"  gate_ok: ok, gate_attempt: attempt, {RELAY_URL_VAR}: relayUrl,",
            "  predecessor_state: last ? (last.state || null) : null,",
            "  predecessor_finished_at: finished || null",
            "} }];",
            "",
        ]
    )


def _schedule_node(name: str, lane: dict) -> dict:
    return {
        "id": _node_id(name, "schedule"),
        "name": N_SCHED,
        "type": "n8n-nodes-base.scheduleTrigger",
        "typeVersion": 1.2,
        "position": [240, 300],
        "parameters": {
            "rule": {"interval": [{"field": "cronExpression", "expression": c} for c in lane["cron"]]},
        },
    }


def _set_node(name: str, relay_url: str) -> dict:
    return {
        "id": _node_id(name, "set"),
        "name": N_SET,
        "type": "n8n-nodes-base.set",
        "typeVersion": 3.4,
        "position": [480, 300],
        "parameters": {
            "assignments": {
                "assignments": [
                    {
                        "id": _node_id(name, "set:url"),
                        "name": RELAY_URL_VAR,
                        "type": "string",
                        "value": relay_url,
                    }
                ]
            },
            "includeOtherFields": False,
            "options": {},
        },
    }


def _post_node(name: str, lane_id: str, mode: str, *, position: list[int]) -> dict:
    # The relay derives the idempotent run id from workflow_id + execution_id
    # and refuses a body without them (relay_bad_run_id). n8n fills both at
    # execution time, so the body is an expression, not a literal.
    json_body = (
        "={{ JSON.stringify({ lane_id: "
        + json.dumps(lane_id)
        + ", mode: "
        + json.dumps(mode)
        + ", requested_by: "
        + json.dumps(name)
        + ", workflow_id: String($workflow.id), execution_id: String($execution.id) }) }}"
    )
    return {
        "id": _node_id(name, "http"),
        "name": N_POST,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": position,
        "onError": "stopWorkflow",
        "credentials": {"httpHeaderAuth": {"id": CREDENTIAL_NAME, "name": CREDENTIAL_NAME}},
        "parameters": {
            "method": "POST",
            "url": "={{ $json." + RELAY_URL_VAR + " }}/run",
            "authentication": "genericCredentialType",
            "genericAuthType": "httpHeaderAuth",
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": json_body,
            "options": {
                "timeout": HTTP_TIMEOUT_MS,
                # neverError: the Code node is the single assertion point, so a 4xx/5xx
                # fails the workflow with the lane id in the message, not a generic HTTP error.
                "response": {"response": {"fullResponse": True, "neverError": True}},
            },
        },
    }


def _assert_node(name: str, lane_id: str, mode: str, *, position: list[int]) -> dict:
    return {
        "id": _node_id(name, "code"),
        "name": N_ASSERT,
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": position,
        "onError": "stopWorkflow",
        "parameters": {"language": "javaScript", "mode": "runOnceForAllItems", "jsCode": _assert_js(lane_id, mode)},
    }


def _link(src: str, dst: str) -> dict:
    return {src: {"main": [[{"node": dst, "type": "main", "index": 0}]]}}


def _plain_chain(lane: dict, mode: str, name: str, relay_url: str) -> tuple[list[dict], dict]:
    lane_id = lane["lane_id"]
    nodes = [
        _schedule_node(name, lane),
        _set_node(name, relay_url),
        _post_node(name, lane_id, mode, position=[720, 300]),
        _assert_node(name, lane_id, mode, position=[960, 300]),
    ]
    connections = {}
    connections.update(_link(N_SCHED, N_SET))
    connections.update(_link(N_SET, N_POST))
    connections.update(_link(N_POST, N_ASSERT))
    return nodes, connections


def _get_last_node(name: str, after: str) -> dict:
    return {
        "id": _node_id(name, "http-get"),
        "name": N_GET,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [720, 300],
        "onError": "stopWorkflow",
        "credentials": {"httpHeaderAuth": {"id": CREDENTIAL_NAME, "name": CREDENTIAL_NAME}},
        "parameters": {
            "method": "GET",
            "url": "={{ $json." + RELAY_URL_VAR + " }}/runs/" + after + "/last",
            "authentication": "genericCredentialType",
            "genericAuthType": "httpHeaderAuth",
            "options": {
                "timeout": HTTP_TIMEOUT_MS,
                "response": {"response": {"fullResponse": True, "neverError": True}},
            },
        },
    }


def _gated_chain(lane: dict, mode: str, name: str, relay_url: str, after: str) -> tuple[list[dict], dict]:
    lane_id = lane["lane_id"]
    nodes = [
        _schedule_node(name, lane),
        _set_node(name, relay_url),
        _get_last_node(name, after),
        {
            "id": _node_id(name, "code-gate"),
            "name": N_GATE,
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [960, 300],
            "onError": "stopWorkflow",
            "parameters": {
                "language": "javaScript",
                "mode": "runOnceForAllItems",
                "jsCode": _gate_js(lane_id, after, mode, crosses_midnight=predecessor_crosses_midnight(lane, after)),
            },
        },
        {
            "id": _node_id(name, "if"),
            "name": N_IF,
            "type": "n8n-nodes-base.if",
            "typeVersion": 2.2,
            "position": [1200, 300],
            "parameters": {
                "conditions": {
                    "combinator": "and",
                    "conditions": [
                        {
                            "id": _node_id(name, "if:gate_ok"),
                            "leftValue": "={{ $json.gate_ok }}",
                            "operator": {"type": "boolean", "operation": "true", "singleValue": True},
                            "rightValue": True,
                        }
                    ],
                    "options": {
                        "caseSensitive": True,
                        "leftValue": "",
                        "typeValidation": "strict",
                        "version": 2,
                    },
                }
            },
        },
        {
            "id": _node_id(name, "wait"),
            "name": N_WAIT,
            "type": "n8n-nodes-base.wait",
            "typeVersion": 1.1,
            "position": [1440, 480],
            "parameters": {"amount": GATE_RETRY_WAIT_S, "unit": "seconds"},
        },
        _post_node(name, lane_id, mode, position=[1440, 180]),
        _assert_node(name, lane_id, mode, position=[1680, 180]),
    ]
    connections = {}
    connections.update(_link(N_SCHED, N_SET))
    connections.update(_link(N_SET, N_GET))
    connections.update(_link(N_GET, N_GATE))
    connections.update(_link(N_GATE, N_IF))
    connections[N_IF] = {
        "main": [
            [{"node": N_POST, "type": "main", "index": 0}],
            [{"node": N_WAIT, "type": "main", "index": 0}],
        ]
    }
    connections.update(_link(N_WAIT, N_GET))
    connections.update(_link(N_POST, N_ASSERT))
    return nodes, connections


def build_workflow(lane: dict, mode: str, relay_url: str = RELAY_URL_PLACEHOLDER) -> dict:
    """One n8n workflow (import shape for n8n 2.43.0) for a lane in a run mode."""
    assert mode in ("dry_run", "live"), mode
    lane_id = lane["lane_id"]
    name = f"{lane_id}-shadow" if mode == "dry_run" else lane_id
    after = lane.get("after")
    if after is not None and (not isinstance(after, str) or not _AFTER_RE.fullmatch(after)):
        raise ValueError(f"bad after on {lane_id}: {after!r}")
    if after:
        nodes, connections = _gated_chain(lane, mode, name, relay_url, after)
    else:
        nodes, connections = _plain_chain(lane, mode, name, relay_url)
    meta = {
        "generator": "scripts/n8n_workflow_templates.py",
        "lane_id": lane_id,
        "mode": mode,
        "tranche": lane["tranche"],
        "schedule_source": lane["source"],
        "schedule_fidelity": lane["fidelity"],
    }
    if after:
        meta["after"] = after
    return {
        "id": _wf_id(name),
        "name": name,
        "active": False,
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1", "timezone": TIMEZONE, "saveManualExecutions": True},
        "meta": meta,
    }


def _dump(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def code_sha() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]


def select_lanes(spec: str) -> list[dict]:
    if spec == "all":
        return list(LANES)
    wanted = {s.strip().upper() for s in spec.split(",") if s.strip()}
    unknown = wanted - set(TRANCHES)
    if unknown:
        raise SystemExit(f"unknown tranche(s): {sorted(unknown)}; choose from {TRANCHES} or all")
    return [lane for lane in LANES if lane["tranche"] in wanted]


def lane_rel_dir(lane: dict) -> str:
    return "" if lane["tranche"] in COMMITTED_TRANCHES else "pending"


def render(lanes: list[dict], relay_url: str = RELAY_URL_PLACEHOLDER) -> dict[str, str]:
    """Map of relative path -> file text for every selected lane (INDEX excluded)."""
    files: dict[str, str] = {}
    for lane in lanes:
        sub = lane_rel_dir(lane)
        for mode in ("dry_run", "live"):
            wf = build_workflow(lane, mode, relay_url)
            rel = f"{sub}/{wf['name']}.json" if sub else f"{wf['name']}.json"
            files[rel] = _dump(wf)
    return files


def build_index(lanes: list[dict], generated_at: str) -> dict:
    rows = []
    for lane in lanes:
        sub = lane_rel_dir(lane)
        pre = f"{sub}/" if sub else ""
        row = {
            "lane_id": lane["lane_id"],
            "tranche": lane["tranche"],
            "schedule": list(lane["cron"]),
            "schedule_source": lane["source"],
            "schedule_fidelity": lane["fidelity"],
            "committed": lane["tranche"] in COMMITTED_TRANCHES,
            "shadow_file": f"{pre}{lane['lane_id']}-shadow.json",
            "live_file": f"{pre}{lane['lane_id']}.json",
            "shadow_workflow_id": _wf_id(f"{lane['lane_id']}-shadow"),
            "live_workflow_id": _wf_id(lane["lane_id"]),
        }
        for key in ("note", "pipeline", "stage_order", "after"):
            if key in lane:
                row[key] = lane[key]
        rows.append(row)
    by_tranche = {t: sum(1 for lane in lanes if lane["tranche"] == t) for t in TRANCHES}
    return {
        "schema": SCHEMA,
        "generated_at": generated_at,
        "code_sha": code_sha(),
        "generator": "scripts/n8n_workflow_templates.py",
        "timezone": TIMEZONE,
        "credential_name": CREDENTIAL_NAME,
        "relay_url_var": RELAY_URL_VAR,
        "relay_url_placeholder": RELAY_URL_PLACEHOLDER,
        "node_types": sorted(ALLOWED_NODE_TYPES),
        "lane_count": len(lanes),
        "lanes_by_tranche": by_tranche,
        "lanes": rows,
    }


def _index_without_timestamp(text: str) -> dict | None:
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return None
    if isinstance(obj, dict):
        obj.pop("generated_at", None)
    return obj


def write(out: Path, lanes: list[dict], relay_url: str) -> list[str]:
    files = render(lanes, relay_url)
    written: list[str] = []
    for rel, text in sorted(files.items()):
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
            written.append(rel)
    index_path = out / "INDEX.json"
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    previous = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    prev_obj = _index_without_timestamp(previous)
    candidate = build_index(lanes, now)
    if prev_obj is not None and prev_obj == _index_without_timestamp(_dump(candidate)):
        return written  # unchanged: keep generated_at so the tree stays diff-free
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(_dump(candidate), encoding="utf-8")
    written.append("INDEX.json")
    return written


def check(out: Path, lanes: list[dict], relay_url: str) -> list[str]:
    """Differences between the committed files and a fresh render; [] means clean."""
    diffs: list[str] = []
    files = render(lanes, relay_url)
    for rel, text in sorted(files.items()):
        path = out / rel
        if not path.exists():
            diffs.append(f"missing: {rel}")
        elif path.read_text(encoding="utf-8") != text:
            diffs.append(f"stale: {rel}")
    index_path = out / "INDEX.json"
    if not index_path.exists():
        diffs.append("missing: INDEX.json")
    else:
        committed = _index_without_timestamp(index_path.read_text(encoding="utf-8"))
        expected = _index_without_timestamp(_dump(build_index(lanes, "")))
        if committed != expected:
            diffs.append("stale: INDEX.json")
    return diffs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lanes", default="all", help="N1|N2|...|N6 (comma list) or all")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument(
        "--relay-url",
        default=RELAY_URL_PLACEHOLDER,
        help="Set-node constant; keep the placeholder in the repo, never an IP",
    )
    ap.add_argument("--check", action="store_true", help="fail if committed files differ from a fresh render")
    a = ap.parse_args(argv)
    lanes = select_lanes(a.lanes)
    for lane in lanes:
        for expr in lane["cron"]:
            problems = validate_cron(expr)
            if problems:
                print(f"invalid cron for {lane['lane_id']}: {problems}", file=sys.stderr)
                return 2
    out = Path(a.out)
    if a.check:
        diffs = check(out, lanes, a.relay_url)
        print(json.dumps({"mode": "check", "lanes": len(lanes), "diffs": diffs, "out": str(out)}))
        return 1 if diffs else 0
    written = write(out, lanes, a.relay_url)
    print(
        json.dumps(
            {"mode": "write", "lanes": len(lanes), "files": 2 * len(lanes) + 1, "changed": written, "out": str(out)}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
