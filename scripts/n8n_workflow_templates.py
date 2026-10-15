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
    python3 scripts/n8n_workflow_templates.py build-generic [--out DIR] [--check]   # six generic workflows

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


# ---------------------------------------------------------------------------
# Generic, registry-driven workflows (N8N Maturity design 02 §4, §6–§11).
#
# Six workflows replace one-workflow-per-lane: they ask the gateway what is due
# (GET /due) and echo each due item to POST /run. They carry no registry lane id,
# no command, no path and no cron line other than their own Schedule Trigger.
# The only lane ids allowed are the system filters in SYSTEM_FILTER_LANES.
# All six are generated inactive; activation is one config-write grant (AGENTS 4.1.0).
# ---------------------------------------------------------------------------
GENERIC_DEFAULT_OUT = ROOT / "docs" / "implementation" / "n8n-maturity" / "workflows"
GENERIC_SCHEMA = "N8nGenericWorkflowSet@v1"
# The bridge IP, never a hostname (EAI_AGAIN lesson, design 02 §4 node 2).
GENERIC_RELAY_URL = "http://172.19.0.1:18092"
DUE_SCHEMA = "DueResponse@v1"
DUE_LIMIT = 40
GENERIC_BATCH_SIZE = 5
GENERIC_BATCH_WAIT_S = 1
HEARTBEAT_LANE = "heartbeat-watch"
HEARTBEAT_SETTLE_WAIT_S = 60
HEARTBEAT_MAX_AGE_S = 600
WORKFLOW_ERROR_LANE = "n8n-workflow-error"
ERROR_MESSAGE_MAX = 160
# 2026-10-10 (W0 relay fix): the incident router's /due lane filter names REGISTRY lane ids. Design 02 §8 wrote
# `incident-fanin,incident-notify`; the registry rows are `n8n-incident-fanin` (scripts/n8n_incident_fanin.py;
# `incident-fanin` is its gateway EVENT lane, not a registry row) and `incident-notifier` (scripts/
# incident_notifier.py, B2's notifier). The gateway refuses a filter naming a non-row (`bad_lane_filter`, design
# 02 §11), which is how every incident-router tick failed at W0 (n8n executions 1981, 1989, 1995, 1999, 2002).
INCIDENT_FILTER_LANES = ("n8n-incident-fanin", "incident-notifier")
# The only lane ids any generic workflow may spell (design 02 §7, §8, §10). Everything
# else comes from the gateway at run time.
SYSTEM_FILTER_LANES = frozenset(
    {
        HEARTBEAT_LANE,
        *INCIDENT_FILTER_LANES,
        "approval-escalate",
        WORKFLOW_ERROR_LANE,
    }
)
# The /run body: exactly these keys (three echoed from the due item, two from n8n).
RUN_BODY_KEYS = ("lane_id", "mode", "idempotency_key", "workflow_id", "execution_id")
EVENT_BODY_KEYS = ("lane_id", "workflow_id", "execution_id", "node", "message")
# A separate allowlist for build_generic only. ALLOWED_NODE_TYPES (per-lane) is not widened.
GENERIC_ALLOWED_NODE_TYPES = frozenset(
    {
        "n8n-nodes-base.scheduleTrigger",
        "n8n-nodes-base.webhook",
        "n8n-nodes-base.errorTrigger",
        "n8n-nodes-base.set",
        "n8n-nodes-base.httpRequest",
        "n8n-nodes-base.code",
        "n8n-nodes-base.if",
        "n8n-nodes-base.splitInBatches",
        "n8n-nodes-base.wait",
        "n8n-nodes-base.stopAndError",
    }
)
# Never in a generic workflow, whatever the allowlist says (tests assert both).
GENERIC_FORBIDDEN_NODE_TYPES = frozenset(
    {
        "n8n-nodes-base.executeCommand",
        "n8n-nodes-base.ssh",
        "n8n-nodes-base.postgres",
        "n8n-nodes-base.mySql",
        "n8n-nodes-base.microsoftSql",
        "n8n-nodes-base.mongoDb",
        "n8n-nodes-base.redis",
        "n8n-nodes-base.telegram",
        "n8n-nodes-base.emailSend",
        "n8n-nodes-base.gmail",
        "n8n-nodes-base.function",
        "n8n-nodes-base.functionItem",
        "n8n-nodes-base.executeWorkflow",
        "@n8n/n8n-nodes-langchain.agent",
        "@n8n/n8n-nodes-langchain.openAi",
        "@n8n/n8n-nodes-langchain.lmChatOpenAi",
    }
)
INCIDENT_ROUTER_ID = "tradeai-incident-router"

GN_SCHED = "Schedule"
GN_WEBHOOK = "Nudge webhook"
GN_ERROR = "Error Trigger"
GN_SHAPE = "Shape error event"
GN_SET = "Relay"
GN_ROUTE = "Is error event"
GN_EVENT = "POST relay /event"
GN_DUE = "GET relay /due"
GN_VALIDATE = "Validate due"
GN_BATCH = "Batch 5"
GN_RUN = "POST relay /run"
GN_PACE = "Wait 1s"
GN_ASSERT = "Assert"
GN_IF = "Any refused"
GN_STOP = "Stop And Error"
GN_SETTLE = "Wait 60s"
GN_LAST = "GET heartbeat last"
GN_FRESH = "Assert heartbeat fresh"

# kind -> (workflow id, cron, due query, lane filter, executionTimeout s, extra trigger)
GENERIC_KINDS: dict[str, dict] = {
    "dispatcher": {
        "id": "tradeai-dispatcher",
        "cron": "* * * * *",
        "source": "schedule",
        "lanes": [],
        "timeout_s": 50,
    },
    "event-router": {
        "id": "tradeai-event-router",
        "cron": "* * * * *",
        "source": "event",
        "lanes": [],
        "timeout_s": 50,
        "webhook": True,
    },
    "heartbeat-watcher": {
        "id": "tradeai-heartbeat-watcher",
        "cron": "*/5 * * * *",
        "source": "schedule",
        "lanes": [HEARTBEAT_LANE],
        "timeout_s": 150,
        "heartbeat": True,
    },
    "incident-router": {
        "id": INCIDENT_ROUTER_ID,
        "cron": "* * * * *",
        "source": "schedule",
        "lanes": list(INCIDENT_FILTER_LANES),
        "timeout_s": 50,
        "error_trigger": True,
    },
    "digest-scheduler": {
        "id": "tradeai-digest-scheduler",
        "cron": "*/5 * * * *",
        "source": "digest",
        "lanes": [],
        "timeout_s": 50,
    },
    "approval-router": {
        "id": "tradeai-approval-router",
        "cron": "*/5 * * * *",
        "source": "schedule",
        "lanes": ["approval-escalate"],
        "timeout_s": 50,
    },
}


def _g_node_id(kind: str, node: str) -> str:
    return str(uuid.uuid5(_UUID_NS, f"generic:{kind}:{node}"))


def _relay_expr() -> str:
    return "$('" + GN_SET + "').first().json." + RELAY_URL_VAR


def _relay_credentials() -> dict:
    return {"httpHeaderAuth": {"id": CREDENTIAL_NAME, "name": CREDENTIAL_NAME}}


def _due_query(spec: dict) -> str:
    query = f"source={spec['source']}&limit={DUE_LIMIT}"
    if spec["lanes"]:
        query += "&lane=" + ",".join(spec["lanes"])
    return "/due?" + query


def _validate_due_js(spec: dict) -> str:
    return "\n".join(
        [
            "// Generated by scripts/n8n_workflow_templates.py build-generic — do not edit in n8n.",
            f"const SCHEMA = {json.dumps(DUE_SCHEMA)};",
            f"const SOURCE = {json.dumps(spec['source'])};",
            f"const LIMIT = {DUE_LIMIT};",
            f"const LANE_FILTER = {json.dumps(spec['lanes'])};",
            "const LANE_RE = /^[a-z0-9][a-z0-9._-]{1,63}$/;",
            "const KEY_RE = /^[A-Za-z0-9._:-]{16,128}$/;",
            "const due = $input.first().json;",
            "if (!due || due.schema !== SCHEMA) throw new Error('due: schema is not ' + SCHEMA);",
            "if (due.ok !== true) throw new Error('due: ok is not true (' + String(due.refused) + ')');",
            "if (due.source !== SOURCE) throw new Error('due: source is not ' + SOURCE);",
            "const items = Array.isArray(due.items) ? due.items : null;",
            "if (items === null) throw new Error('due: items is not a list');",
            "if (items.length > LIMIT) throw new Error('due: ' + items.length + ' items over limit ' + LIMIT);",
            "const out = [];",
            "for (const it of items) {",
            "  const lane = it && it.lane_id;",
            "  if (typeof lane !== 'string' || !LANE_RE.test(lane)) throw new Error('due: bad lane_id');",
            "  if (LANE_FILTER.length && !LANE_FILTER.includes(lane)) throw new Error('due: lane outside filter: ' + lane);",
            "  if (it.mode !== 'dry_run' && it.mode !== 'live') throw new Error('due: bad mode for ' + lane);",
            "  if (typeof it.idempotency_key !== 'string' || !KEY_RE.test(it.idempotency_key)) {",
            "    throw new Error('due: bad idempotency_key for ' + lane);",
            "  }",
            "  // Only these three fields leave this node; the /run body cannot carry anything else.",
            "  out.push({ json: { lane_id: lane, mode: it.mode, idempotency_key: it.idempotency_key } });",
            "}",
            "return out;",
            "",
        ]
    )


def _assert_runs_js() -> str:
    return "\n".join(
        [
            "// Generated by scripts/n8n_workflow_templates.py build-generic — do not edit in n8n.",
            "// Batch-done output is every /run response in request order; pair it with the due items.",
            f"const due = $('{GN_VALIDATE}').all().map((i) => i.json);",
            "const res = $input.all().map((i) => i.json);",
            "let posted = 0;",
            "let duplicate = 0;",
            "const refused = [];",
            "const unreachable = [];",
            "for (let i = 0; i < due.length; i++) {",
            "  const lane = due[i].lane_id;",
            "  const r = res[i];",
            "  if (!r || r.error || typeof r.statusCode !== 'number') {",
            "    unreachable.push({ lane_id: lane, reason: 'no response' });",
            "    continue;",
            "  }",
            "  const body = (r.body && typeof r.body === 'object') ? r.body : {};",
            "  if (r.statusCode === 200 && body.duplicate === true) { duplicate++; continue; }",
            "  if (r.statusCode === 200 && body.state === 'REQUESTED') { posted++; continue; }",
            "  const why = String(body.refused || body.error || body.state || ('HTTP ' + r.statusCode)).slice(0, 80);",
            "  refused.push({ lane_id: lane, reason: why });",
            "}",
            "if (res.length > due.length) refused.push({ lane_id: '-', reason: 'extra responses' });",
            "return [{ json: { posted, duplicate, refused, unreachable } }];",
            "",
        ]
    )


def _shape_error_js() -> str:
    return "\n".join(
        [
            "// Generated by scripts/n8n_workflow_templates.py build-generic — do not edit in n8n.",
            "// Error Trigger payload -> the five fields the relay /event accepts. Nothing else leaves.",
            "const e = $input.first().json || {};",
            "const exec = e.execution || {};",
            "const wf = e.workflow || {};",
            "const err = exec.error || {};",
            "return [{ json: {",
            f"  event_lane: {json.dumps(WORKFLOW_ERROR_LANE)},",
            "  workflow_id: String(wf.id ?? ''),",
            "  execution_id: String(exec.id ?? ''),",
            "  node: String(exec.lastNodeExecuted ?? (err.node && err.node.name) ?? ''),",
            f"  message: String(err.message ?? '').slice(0, {ERROR_MESSAGE_MAX}),",
            "} }];",
            "",
        ]
    )


def _heartbeat_fresh_js() -> str:
    """Freshness of the watch lane itself, alarmed ONLY once heartbeat-watch is n8n-dispatched.

    2026-10-09 (B5 follow-up): at W0 every registry row is ``dispatch.mode: off``, so no live RUN_DONE can exist
    and an unconditional check was a P1 every 5 min. Dispatch state is read from this tick's ``/due`` reply (the
    lane-filtered DueResponse@v1): a row with mode off is never evaluated, so it leaves no item, held slot, count
    or error. Any trace = dispatched. An ``errors[]`` entry for the lane is a broken dispatch block: alarm.
    Seen only in dry_run: skip (a live row cannot exist). Mode unknown (only counts, e.g. the slot is DONE) and no
    live run ever: skip, the lane has never been live. Otherwise a live RUN_DONE must be <= MAX_AGE_S old.
    Age is elapsed real seconds (DST-safe by construction)."""
    return "\n".join(
        [
            "// Generated by scripts/n8n_workflow_templates.py build-generic — do not edit in n8n.",
            f"const MAX_AGE_S = {HEARTBEAT_MAX_AGE_S};",
            f"const LANE = {json.dumps(HEARTBEAT_LANE)};",
            f"const due = $('{GN_DUE}').first().json;",
            "if (!due || due.ok !== true) throw new Error('heartbeat-watch: /due unreadable; dispatch state unknown');",
            "const mine = (xs) => (Array.isArray(xs) ? xs : []).filter((x) => x && x.lane_id === LANE);",
            "const errs = mine(due.errors);",
            "if (errs.length) throw new Error('heartbeat-watch: dispatch block error ' + String(errs[0].code));",
            "const traced = mine(due.items).concat(mine(due.held));",
            "const counts = (due.counts && typeof due.counts === 'object') ? due.counts : {};",
            "const counted = Object.values(counts).reduce((a, n) => a + (Number(n) || 0), 0);",
            "if (!traced.length && counted === 0) {",
            "  return [{ json: { heartbeat_ok: true, skipped: 'not_dispatched' } }];",
            "}",
            "const modes = new Set(traced.map((x) => x.mode));",
            "if (modes.size && !modes.has('live')) {",
            "  return [{ json: { heartbeat_ok: true, skipped: 'dispatched_dry_run' } }];",
            "}",
            "const r = $input.first().json;",
            "const body = (r.body && typeof r.body === 'object') ? r.body : {};",
            "const last = (body.last && typeof body.last === 'object') ? body.last : null;",
            "if (!modes.size && !last) {",
            "  return [{ json: { heartbeat_ok: true, skipped: 'mode_unknown_never_live' } }];",
            "}",
            "const finished = last && last.finished_at ? Date.parse(String(last.finished_at)) : NaN;",
            "const age = Number.isNaN(finished) ? null : Math.round((Date.now() - finished) / 1000);",
            "const ok = r.statusCode === 200 && !!last && last.state === 'RUN_DONE' && age !== null && age <= MAX_AGE_S;",
            "if (!ok) {",
            "  throw new Error('heartbeat-watch: no live RUN_DONE within ' + MAX_AGE_S + ' s (state ' +",
            "    String(last ? last.state : 'none') + ', age ' + String(age) + ')');",
            "}",
            "return [{ json: { heartbeat_ok: true, age_s: age } }];",
            "",
        ]
    )


def _g_http(kind: str, name: str, *, method: str, path_expr: str, position: list[int], **extra) -> dict:
    params: dict = {
        "method": method,
        "url": "={{ " + _relay_expr() + " }}" + path_expr,
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "options": {"timeout": HTTP_TIMEOUT_MS},
    }
    if extra.get("json_body"):
        params.update({"sendBody": True, "specifyBody": "json", "jsonBody": extra["json_body"]})
    if extra.get("full_response"):
        params["options"]["response"] = {"response": {"fullResponse": True, "neverError": True}}
    node = {
        "id": _g_node_id(kind, name),
        "name": name,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": position,
        "credentials": _relay_credentials(),
        "parameters": params,
        "retryOnFail": True,
        "maxTries": 2,
        "waitBetweenTries": extra.get("wait_ms", 3000),
    }
    if extra.get("on_error"):
        node["onError"] = extra["on_error"]
    return node


def _g_code(kind: str, name: str, js: str, position: list[int]) -> dict:
    return {
        "id": _g_node_id(kind, name),
        "name": name,
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": position,
        "parameters": {"language": "javaScript", "mode": "runOnceForAllItems", "jsCode": js},
    }


def _g_wait(kind: str, name: str, seconds: int, position: list[int]) -> dict:
    return {
        "id": _g_node_id(kind, name),
        "name": name,
        "type": "n8n-nodes-base.wait",
        "typeVersion": 1.1,
        "position": position,
        "webhookId": _g_node_id(kind, name + ":webhook"),
        "parameters": {"amount": seconds, "unit": "seconds"},
    }


def _g_if(kind: str, name: str, left: str, position: list[int]) -> dict:
    return {
        "id": _g_node_id(kind, name),
        "name": name,
        "type": "n8n-nodes-base.if",
        "typeVersion": 2.2,
        "position": position,
        "parameters": {
            "conditions": {
                "combinator": "and",
                "conditions": [
                    {
                        "id": _g_node_id(kind, name + ":cond"),
                        "leftValue": left,
                        "operator": {"type": "boolean", "operation": "true", "singleValue": True},
                        "rightValue": True,
                    }
                ],
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
            }
        },
    }


def _g_main(conns: dict, src: str, *outputs: list[str]) -> None:
    conns[src] = {"main": [[{"node": dst, "type": "main", "index": 0} for dst in out] for out in outputs]}


def build_generic(kind: str) -> dict:
    """One of the six registry-driven workflows (design 02 §11), always inactive."""
    if kind not in GENERIC_KINDS:
        raise ValueError(f"unknown generic kind {kind!r}; choose from {sorted(GENERIC_KINDS)}")
    spec = GENERIC_KINDS[kind]
    wid = spec["id"]
    nodes: list[dict] = []
    conns: dict = {}
    run_body = (
        "={{ JSON.stringify({ lane_id: $json.lane_id, mode: $json.mode, idempotency_key: $json.idempotency_key, "
        "workflow_id: String($workflow.id), execution_id: String($execution.id) }) }}"
    )

    nodes.append(
        {
            "id": _g_node_id(kind, GN_SCHED),
            "name": GN_SCHED,
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.2,
            "position": [0, 300],
            "parameters": {"rule": {"interval": [{"field": "cronExpression", "expression": spec["cron"]}]}},
        }
    )
    nodes.append(
        {
            "id": _g_node_id(kind, GN_SET),
            "name": GN_SET,
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.4,
            "position": [480, 300],
            "parameters": {
                "assignments": {
                    "assignments": [
                        {
                            "id": _g_node_id(kind, GN_SET + ":url"),
                            "name": RELAY_URL_VAR,
                            "type": "string",
                            "value": GENERIC_RELAY_URL,
                        }
                    ]
                },
                # The incident router passes the shaped error event through this node.
                "includeOtherFields": bool(spec.get("error_trigger")),
                "options": {},
            },
        }
    )
    _g_main(conns, GN_SCHED, [GN_SET])

    if spec.get("webhook"):
        nodes.append(
            {
                "id": _g_node_id(kind, GN_WEBHOOK),
                "name": GN_WEBHOOK,
                "type": "n8n-nodes-base.webhook",
                "typeVersion": 2,
                "position": [0, 120],
                "webhookId": _g_node_id(kind, GN_WEBHOOK + ":webhook"),
                "credentials": _relay_credentials(),
                # The nudge only wakes the router; its body is never read (design 02 §6).
                "parameters": {
                    "httpMethod": "POST",
                    "path": "tradeai-nudge",
                    "authentication": "headerAuth",
                    "responseMode": "onReceived",
                    "options": {},
                },
            }
        )
        _g_main(conns, GN_WEBHOOK, [GN_SET])

    due_from = GN_SET
    if spec.get("error_trigger"):
        nodes.append(
            {
                "id": _g_node_id(kind, GN_ERROR),
                "name": GN_ERROR,
                "type": "n8n-nodes-base.errorTrigger",
                "typeVersion": 1,
                "position": [0, 120],
                "parameters": {},
            }
        )
        nodes.append(_g_code(kind, GN_SHAPE, _shape_error_js(), [240, 120]))
        nodes.append(
            _g_if(kind, GN_ROUTE, "={{ $json.event_lane === " + json.dumps(WORKFLOW_ERROR_LANE) + " }}", [720, 300])
        )
        event_body = (
            "={{ JSON.stringify({ lane_id: $json.event_lane, workflow_id: $json.workflow_id, "
            "execution_id: $json.execution_id, node: $json.node, message: $json.message }) }}"
        )
        nodes.append(
            _g_http(kind, GN_EVENT, method="POST", path_expr="/event", position=[960, 120], json_body=event_body)
        )
        _g_main(conns, GN_ERROR, [GN_SHAPE])
        _g_main(conns, GN_SHAPE, [GN_SET])
        _g_main(conns, GN_SET, [GN_ROUTE])
        _g_main(conns, GN_ROUTE, [GN_EVENT], [GN_DUE])
        due_from = GN_ROUTE

    x0 = 960 if spec.get("error_trigger") else 720
    nodes.append(_g_http(kind, GN_DUE, method="GET", path_expr=_due_query(spec), position=[x0, 300]))
    nodes.append(_g_code(kind, GN_VALIDATE, _validate_due_js(spec), [x0 + 240, 300]))
    nodes.append(
        {
            "id": _g_node_id(kind, GN_BATCH),
            "name": GN_BATCH,
            "type": "n8n-nodes-base.splitInBatches",
            "typeVersion": 3,
            "position": [x0 + 480, 300],
            "parameters": {"batchSize": GENERIC_BATCH_SIZE, "options": {}},
        }
    )
    nodes.append(
        _g_http(
            kind,
            GN_RUN,
            method="POST",
            path_expr="/run",
            position=[x0 + 720, 420],
            json_body=run_body,
            full_response=True,
            wait_ms=2000,
            on_error="continueRegularOutput",
        )
    )
    nodes.append(_g_wait(kind, GN_PACE, GENERIC_BATCH_WAIT_S, [x0 + 960, 420]))
    nodes.append(_g_code(kind, GN_ASSERT, _assert_runs_js(), [x0 + 720, 180]))
    nodes.append(_g_if(kind, GN_IF, "={{ ($json.refused.length + $json.unreachable.length) > 0 }}", [x0 + 960, 180]))
    nodes.append(
        {
            "id": _g_node_id(kind, GN_STOP),
            "name": GN_STOP,
            "type": "n8n-nodes-base.stopAndError",
            "typeVersion": 1,
            "position": [x0 + 1200, 120],
            "parameters": {
                "errorType": "errorMessage",
                # Lane ids and reasons only.
                "errorMessage": "={{ "
                + json.dumps(wid + ": ")
                + " + $json.refused.concat($json.unreachable).map((r) => r.lane_id + '=' + r.reason).join('; ') }}",
            },
        }
    )
    if due_from == GN_SET:
        if spec.get("heartbeat"):
            _g_main(conns, GN_SET, [GN_DUE, GN_SETTLE])
        else:
            _g_main(conns, GN_SET, [GN_DUE])
    _g_main(conns, GN_DUE, [GN_VALIDATE])
    _g_main(conns, GN_VALIDATE, [GN_BATCH])
    # SplitInBatches v3: output 0 = done, output 1 = loop.
    _g_main(conns, GN_BATCH, [GN_ASSERT], [GN_RUN])
    _g_main(conns, GN_RUN, [GN_PACE])
    _g_main(conns, GN_PACE, [GN_BATCH])
    _g_main(conns, GN_ASSERT, [GN_IF])
    _g_main(conns, GN_IF, [GN_STOP], [])

    if spec.get("heartbeat"):
        # Runs every tick, due or not: the watcher must see a stale watch lane even when /due is empty.
        nodes.append(_g_wait(kind, GN_SETTLE, HEARTBEAT_SETTLE_WAIT_S, [720, 560]))
        nodes.append(
            _g_http(
                kind,
                GN_LAST,
                method="GET",
                path_expr=f"/runs/{HEARTBEAT_LANE}/last?mode=live",
                position=[960, 560],
                full_response=True,
            )
        )
        nodes.append(_g_code(kind, GN_FRESH, _heartbeat_fresh_js(), [1200, 560]))
        _g_main(conns, GN_SETTLE, [GN_LAST])
        _g_main(conns, GN_LAST, [GN_FRESH])

    settings: dict = {
        "executionOrder": "v1",
        "timezone": TIMEZONE,
        "executionTimeout": spec["timeout_s"],
        "saveDataErrorExecution": "all",
        # Open item F4 / P19: manual (editor) executions are not saved; the instance already sets
        # EXECUTIONS_DATA_SAVE_MANUAL_EXECUTIONS=false and a workflow setting of true would override it.
        "saveManualExecutions": False,
    }
    if wid != INCIDENT_ROUTER_ID:
        settings["errorWorkflow"] = INCIDENT_ROUTER_ID
    nodes.sort(key=lambda n: n["name"])
    return {
        "id": wid,
        "name": wid,
        "active": False,
        "nodes": nodes,
        "connections": conns,
        "settings": settings,
        "meta": {
            "generator": "scripts/n8n_workflow_templates.py build-generic",
            "kind": kind,
            "design": "docs/implementation/n8n-maturity/02-six-workflow-architecture.md §11",
        },
    }


def generic_relay_calls(kind: str) -> list[str]:
    spec = GENERIC_KINDS[kind]
    calls = ["GET " + _due_query(spec), "POST /run"]
    if spec.get("heartbeat"):
        calls.append(f"GET /runs/{HEARTBEAT_LANE}/last?mode=live")
    if spec.get("error_trigger"):
        calls.append("POST /event")
    return calls


def generic_triggers(kind: str) -> list[str]:
    spec = GENERIC_KINDS[kind]
    triggers = ["schedule " + spec["cron"]]
    if spec.get("webhook"):
        triggers.append("webhook POST tradeai-nudge")
    if spec.get("error_trigger"):
        triggers.append("error trigger")
    return triggers


def render_generic() -> dict[str, str]:
    """Map of file name -> text for the six workflows plus INDEX.json (no timestamp; byte-stable)."""
    files: dict[str, str] = {}
    rows = []
    for kind in GENERIC_KINDS:
        wf = build_generic(kind)
        text = _dump(wf)
        fname = f"{wf['id']}.json"
        files[fname] = text
        rows.append(
            {
                "kind": kind,
                "id": wf["id"],
                "file": fname,
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "triggers": generic_triggers(kind),
                "relay_calls": generic_relay_calls(kind),
                "error_workflow": wf["settings"].get("errorWorkflow"),
                "active": False,
            }
        )
    files["INDEX.json"] = _dump(
        {
            "schema": GENERIC_SCHEMA,
            "generator": "scripts/n8n_workflow_templates.py build-generic",
            "relay_url": GENERIC_RELAY_URL,
            "credential_name": CREDENTIAL_NAME,
            "system_filter_lanes": sorted(SYSTEM_FILTER_LANES),
            "node_types": sorted(GENERIC_ALLOWED_NODE_TYPES),
            "workflows": rows,
        }
    )
    return files


def generic_main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="n8n_workflow_templates.py build-generic", description="six generic workflows")
    ap.add_argument("--out", default=str(GENERIC_DEFAULT_OUT))
    ap.add_argument("--check", action="store_true", help="fail if regenerating would change any byte")
    a = ap.parse_args(argv)
    out = Path(a.out)
    files = render_generic()
    if a.check:
        diffs = []
        for rel, text in sorted(files.items()):
            path = out / rel
            if not path.exists():
                diffs.append(f"missing: {rel}")
            elif path.read_bytes() != text.encode("utf-8"):
                diffs.append(f"stale: {rel}")
        print(json.dumps({"mode": "check-generic", "files": len(files), "diffs": diffs, "out": str(out)}))
        return 1 if diffs else 0
    changed = []
    out.mkdir(parents=True, exist_ok=True)
    for rel, text in sorted(files.items()):
        path = out / rel
        data = text.encode("utf-8")
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)
            changed.append(rel)
    print(json.dumps({"mode": "write-generic", "files": len(files), "changed": changed, "out": str(out)}))
    return 0


# ── n8n fabric Phase 1 (2026-10-14; AGENTS.md §23.23, 10.0.0 PROPOSED; REFACTOR_PLAN B5/B6 + addendum item 3) ────
# `build-fabric` generates the fabric primitives into workflows/fabric/, separate from the six generic workflows (whose
# bytes are unchanged, so nothing live drifts): the Run Lane sub-workflow, the fabric error workflow and an inactive
# probe that calls Run Lane once in dry_run. Every fabric workflow carries settings.errorWorkflow (the error workflow
# names itself; n8n skips an error workflow's own failure when errorWorkflow == its id), saves successful executions,
# and is checked against FABRIC_ALLOWED_NODE_TYPES. INDEX.json is the trusted-deployer manifest: per workflow the file
# sha256 and the GRAPH hash (behavioural fields only, so an n8n export of the same graph verifies), plus one POLICY
# hash over the node allowlist, the required settings, the relay routes and the intent route table.
#
#     python3 scripts/n8n_workflow_templates.py build-fabric [--out DIR] [--check]
#     python3 scripts/n8n_workflow_templates.py build-fabric --verify EXPORTED.json [...]   # trusted deployer

FABRIC_DEFAULT_OUT = GENERIC_DEFAULT_OUT / "fabric"
FABRIC_SCHEMA = "N8nFabricManifest@v1"
FABRIC_GENERATOR = "scripts/n8n_workflow_templates.py build-fabric"
RUN_LANE_ID = "tradeai-fabric-run-lane"
FABRIC_ERROR_ID = "tradeai-fabric-error"
FABRIC_PROBE_ID = "tradeai-fabric-run-lane-probe"
#: REFACTOR_PLAN addendum item 9: Error Trigger acceptance needs an AUTOMATIC failure (an editor run does not fire
#: it). This workflow fails on purpose at every scheduled fire; the packet publishes it for one fire, then unpublishes.
FABRIC_ERROR_PROBE_ID = "tradeai-fabric-error-probe"
#: The probe's lane: in config/n8n_run_allowlist.json; its dry_run writes only a shadow crontab copy (30 s timeout).
FABRIC_PROBE_LANE = "crontab-snapshot-for-health-agent"
#: §23.23 node enablement, this PR's share: Execute Workflow + Trigger, Wait, Switch, If, Merge, Error Trigger.
#: Form / webhook-resume (approvals) and the AI Agent node are later PRs, one each.
FABRIC_RELAXED_NODE_TYPES = frozenset(
    {
        "n8n-nodes-base.executeWorkflow",
        "n8n-nodes-base.executeWorkflowTrigger",
        "n8n-nodes-base.wait",
        "n8n-nodes-base.switch",
        "n8n-nodes-base.if",
        "n8n-nodes-base.merge",
        "n8n-nodes-base.errorTrigger",
        # The Run Lane probe's start node (2026-10-15). A Manual Trigger runs ONLY on an explicit execution (the
        # `n8n execute --id` CLI or the editor's Execute button); it never fires on its own, and a workflow whose only
        # trigger is manual has nothing a publish could schedule. Nothing timed or external can start from it.
        "n8n-nodes-base.manualTrigger",
    }
)
FABRIC_ALLOWED_NODE_TYPES = GENERIC_ALLOWED_NODE_TYPES | FABRIC_RELAXED_NODE_TYPES
#: Never in a fabric workflow. Also refused: any type outside the `n8n-nodes-base.` package (community nodes and every
#: @n8n/n8n-nodes-langchain AI / agent / tool / vector-store node; AI comes in a later PR behind the bridge).
FABRIC_FORBIDDEN_NODE_TYPES = (GENERIC_FORBIDDEN_NODE_TYPES - {"n8n-nodes-base.executeWorkflow"}) | frozenset(
    {
        "n8n-nodes-base.executeCommand",
        "n8n-nodes-base.executeCommandTool",
        "n8n-nodes-base.ssh",
        "n8n-nodes-base.ftp",
        "n8n-nodes-base.localFileTrigger",
        "n8n-nodes-base.readWriteFile",
        "n8n-nodes-base.readBinaryFile",
        "n8n-nodes-base.readBinaryFiles",
        "n8n-nodes-base.writeBinaryFile",
        "n8n-nodes-base.telegram",
        "n8n-nodes-base.telegramTrigger",
        "n8n-nodes-base.slack",
        "n8n-nodes-base.slackTrigger",
        "n8n-nodes-base.discord",
        "n8n-nodes-base.mattermost",
        "n8n-nodes-base.microsoftTeams",
        "n8n-nodes-base.twilio",
        "n8n-nodes-base.whatsApp",
        "n8n-nodes-base.emailSend",
        "n8n-nodes-base.emailReadImap",
        "n8n-nodes-base.gmail",
        "n8n-nodes-base.sendGrid",
        "n8n-nodes-base.mailgun",
        "n8n-nodes-base.pushover",
        "n8n-nodes-base.form",
        "n8n-nodes-base.formTrigger",
        "n8n-nodes-base.respondToWebhook",
        "n8n-nodes-base.postgres",
        "n8n-nodes-base.mySql",
        "n8n-nodes-base.redis",
        "n8n-nodes-base.function",
        "n8n-nodes-base.functionItem",
    }
)
FABRIC_NODE_PACKAGE = "n8n-nodes-base."
#: Retention is the instance's: EXECUTIONS_DATA_PRUNE=true, EXECUTIONS_DATA_MAX_AGE=168 (h) (N8N_CONFIGURATION.md
#: §1); successes are saved per workflow so the run_id custom data is visible (§23.23 governance (3)).
FABRIC_REQUIRED_SETTINGS = {
    "executionOrder": "v1",
    "timezone": TIMEZONE,
    "saveDataSuccessExecution": "all",
    "saveDataErrorExecution": "all",
    "saveManualExecutions": False,
}
FABRIC_CREDENTIAL_TYPES = frozenset({"httpHeaderAuth"})
#: Run Lane bounds. n8n caps a workflow at EXECUTIONS_TIMEOUT_MAX (default 3600 s), so the worst case
#: (attempts x outcome timeout + backoffs) stays under RUN_LANE_EXECUTION_TIMEOUT_S.
RUN_LANE_EXECUTION_TIMEOUT_S = 3600
RUN_LANE_MAX_ATTEMPTS = 3
RUN_LANE_OUTCOME_TIMEOUT_DEFAULT_S = 900
RUN_LANE_OUTCOME_TIMEOUT_MAX_S = 1000
RUN_LANE_POLL_FIRST_S = 5
RUN_LANE_POLL_MAX_S = 60
RUN_LANE_RETRY_BACKOFF_BASE_S = 30
RUN_LANE_RETRY_BACKOFF_MAX_S = 120
RUN_LANE_TERMINAL = ("success", "failed", "refused_policy", "skipped_lock")
FABRIC_ERROR_TIMEOUT_S = 60
FABRIC_PROBE_TIMEOUT_S = 300
#: Relay calls each fabric workflow makes (checked against scripts/n8n_run_relay.py ROUTES by the tests).
FABRIC_RELAY_CALLS = {
    RUN_LANE_ID: ["POST /run", "GET /run_outcome"],
    FABRIC_ERROR_ID: ["POST /intent"],
    FABRIC_PROBE_ID: [],
    FABRIC_ERROR_PROBE_ID: [],
}
#: Node fields that change behaviour; the graph hash covers exactly these (plus connections and settings), so a
#: re-export from n8n (which adds position, webhookId, notes, versionId, ...) of the same graph verifies.
GRAPH_NODE_FIELDS = (
    "name",
    "type",
    "typeVersion",
    "parameters",
    "credentials",
    "disabled",
    "onError",
    "retryOnFail",
    "maxTries",
    "waitBetweenTries",
    "alwaysOutputData",
    "executeOnce",
)
GRAPH_SETTINGS_FIELDS = (
    "executionOrder",
    "timezone",
    "executionTimeout",
    "saveDataSuccessExecution",
    "saveDataErrorExecution",
    "saveManualExecutions",
    "errorWorkflow",
    "callerPolicy",
)

RL_INPUT = "Run Lane input"
RL_SET = "Relay"
RL_INIT = "Init"
RL_PREP = "Prepare attempt"
RL_POST = "POST relay /run"
RL_CLASSIFY = "Classify request"
RL_REQUESTED = "Requested?"
RL_WAIT = "Wait poll"
RL_GET = "GET relay /run_outcome"
RL_EVAL = "Evaluate outcome"
RL_PENDING = "Still pending?"
RL_SWITCH = "Route status"
RL_BUDGET = "Retry budget?"
RL_BACKOFF = "Wait backoff"
RL_NEXT = "Next attempt"
RL_RESULT = "Result"
FE_TRIGGER = "Error Trigger"
FE_SHAPE = "Shape intent"
FE_SET = "Relay"
FE_POST = "POST relay /intent"
FE_ASSERT = "Assert intent"
#: The probe's start node. `n8n execute --id` needs a Manual Trigger (or Execute Workflow Trigger) to start from; a
#: Schedule Trigger is not a CLI start node ("Missing node to start execution", operator live run 2026-10-15).
FP_MANUAL = "Manual run"
FP_INPUT = "Probe input"
FP_CALL = "Call Run Lane"
FP_ASSERT = "Assert probe result"


def _f_node_id(wid: str, node: str) -> str:
    return str(uuid.uuid5(_UUID_NS, f"fabric:{wid}:{node}"))


def _f_code(wid: str, name: str, js: str, position: list[int]) -> dict:
    node = _g_code(wid, name, js, position)
    node["id"] = _f_node_id(wid, name)
    return node


def _f_http(
    wid: str,
    name: str,
    *,
    method: str,
    path_expr: str,
    position: list[int],
    json_body: str | None = None,
    relay_node: str = RL_SET,
) -> dict:
    """Relay HTTP node: full response + neverError, so a refusal (403) or an unreachable relay reaches the next Code
    node as data; transport retries (2 tries) are the node's, lane retries are Run Lane's."""
    params: dict = {
        "method": method,
        "url": "={{ $('" + relay_node + "').first().json." + RELAY_URL_VAR + " }}" + path_expr,
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "options": {"timeout": HTTP_TIMEOUT_MS, "response": {"response": {"fullResponse": True, "neverError": True}}},
    }
    if json_body is not None:
        params.update({"sendBody": True, "specifyBody": "json", "jsonBody": json_body})
    return {
        "id": _f_node_id(wid, name),
        "name": name,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": position,
        "credentials": _relay_credentials(),
        "parameters": params,
        "retryOnFail": True,
        "maxTries": 2,
        "waitBetweenTries": 2000,
        "onError": "continueRegularOutput",
    }


def _f_set_relay(wid: str, name: str, position: list[int]) -> dict:
    return {
        "id": _f_node_id(wid, name),
        "name": name,
        "type": "n8n-nodes-base.set",
        "typeVersion": 3.4,
        "position": position,
        "parameters": {
            "assignments": {
                "assignments": [
                    {
                        "id": _f_node_id(wid, name + ":url"),
                        "name": RELAY_URL_VAR,
                        "type": "string",
                        "value": GENERIC_RELAY_URL,
                    }
                ]
            },
            "includeOtherFields": True,
            "options": {},
        },
    }


def _f_wait(wid: str, name: str, amount_expr: str, position: list[int]) -> dict:
    return {
        "id": _f_node_id(wid, name),
        "name": name,
        "type": "n8n-nodes-base.wait",
        "typeVersion": 1.1,
        "position": position,
        "webhookId": _f_node_id(wid, name + ":webhook"),
        "parameters": {"amount": amount_expr, "unit": "seconds"},
    }


def _f_if(wid: str, name: str, left: str, position: list[int]) -> dict:
    node = _g_if(wid, name, left, position)
    node["id"] = _f_node_id(wid, name)
    node["parameters"]["conditions"]["conditions"][0]["id"] = _f_node_id(wid, name + ":cond")
    return node


def _f_switch(wid: str, name: str, field_expr: str, values: tuple[str, ...], position: list[int]) -> dict:
    """Switch v3.2: one renamed output per value (in order), plus the fallback output last."""
    rules = []
    for v in values:
        rules.append(
            {
                "conditions": {
                    "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
                    "conditions": [
                        {
                            "id": _f_node_id(wid, f"{name}:{v}"),
                            "leftValue": field_expr,
                            "rightValue": v,
                            "operator": {"type": "string", "operation": "equals"},
                        }
                    ],
                    "combinator": "and",
                },
                "renameOutput": True,
                "outputKey": v,
            }
        )
    return {
        "id": _f_node_id(wid, name),
        "name": name,
        "type": "n8n-nodes-base.switch",
        "typeVersion": 3.2,
        "position": position,
        "parameters": {"rules": {"values": rules}, "options": {"fallbackOutput": "extra"}},
    }


def _run_lane_init_js() -> str:
    return "\n".join(
        [
            "// Generated by scripts/n8n_workflow_templates.py build-fabric — do not edit in n8n.",
            "// Validates the caller's inputs. A bad input is a caller bug: it throws (-> error workflow).",
            "const LANE_RE = /^[a-z0-9][a-z0-9._-]{1,63}$/;",
            "const KEY_RE = /^[A-Za-z0-9._:-]{16,125}$/;",
            f"const MAX_ATTEMPTS = {RUN_LANE_MAX_ATTEMPTS};",
            f"const TIMEOUT_DEFAULT_S = {RUN_LANE_OUTCOME_TIMEOUT_DEFAULT_S};",
            f"const TIMEOUT_MAX_S = {RUN_LANE_OUTCOME_TIMEOUT_MAX_S};",
            "const i = $input.first().json || {};",
            "const lane = i.lane_id;",
            "if (typeof lane !== 'string' || !LANE_RE.test(lane)) throw new Error('run-lane: bad lane_id');",
            "if (i.mode !== 'dry_run' && i.mode !== 'live') throw new Error('run-lane: bad mode for ' + lane);",
            "const key = i.idempotency_key;",
            "if (typeof key !== 'string' || !KEY_RE.test(key)) throw new Error('run-lane: bad idempotency_key for ' + lane);",
            "// Attempt n > 1 re-requests <base>:a<n>; the gateway validates it (a d: key must be RETRY_DUE).",
            "const base = key.replace(/:a[2-9]$/, '');",
            "const maxA = Math.max(1, Math.min(MAX_ATTEMPTS, Math.floor(Number(i.max_attempts) || 1)));",
            "const tmo = Math.max(60, Math.min(TIMEOUT_MAX_S, Math.floor(Number(i.outcome_timeout_s) || TIMEOUT_DEFAULT_S)));",
            "const proc = (typeof i.process_id === 'string' && LANE_RE.test(i.process_id)) ? i.process_id : '';",
            "$execution.customData.set('lane_id', lane);",
            "if (proc) $execution.customData.set('process_id', proc);",
            "const first = /:a([2-9])$/.exec(key);",
            "return [{ json: { lane_id: lane, mode: i.mode, base_key: base, attempt: 1,",
            "  key_attempt: first ? Number(first[1]) : 1, max_attempts: maxA, outcome_timeout_s: tmo,",
            "  process_id: proc, history: [] } }];",
            "",
        ]
    )


def _run_lane_prepare_js() -> str:
    return "\n".join(
        [
            "// Generated by scripts/n8n_workflow_templates.py build-fabric — do not edit in n8n.",
            f"const POLL_FIRST_S = {RUN_LANE_POLL_FIRST_S};",
            "// key_attempt moves only after a run was actually requested; a transport failure re-sends the same key",
            "// (the gateway returns the existing row as duplicate, so nothing runs twice).",
            "const s = $input.first().json;",
            "const key = s.key_attempt > 1 ? s.base_key + ':a' + s.key_attempt : s.base_key;",
            "return [{ json: { ...s, idempotency_key: key, run_id: key, phase: 'request', requested: false,",
            "  status: null, reason: null, retryable: false, polls: 0, waited_s: 0, wait_s: POLL_FIRST_S } }];",
            "",
        ]
    )


def _run_lane_classify_js() -> str:
    return "\n".join(
        [
            "// Generated by scripts/n8n_workflow_templates.py build-fabric — do not edit in n8n.",
            "// The /run reply -> poll, or a terminal status as DATA. A policy refusal (403) is refused_policy, never",
            "// an n8n error. Relay auth or a malformed request is a configuration bug: it throws.",
            f"const s = $('{RL_PREP}').last().json;",
            "const r = $input.first().json || {};",
            "const body = (r.body && typeof r.body === 'object') ? r.body : {};",
            "const out = { ...s };",
            "const code = r.statusCode;",
            "if (typeof code !== 'number' || r.error) {",
            "  Object.assign(out, { phase: 'done', status: 'failed', reason: 'relay_unreachable', retryable: true });",
            "} else if (code === 200 && (body.state === 'REQUESTED' || body.duplicate === true)) {",
            "  out.phase = 'poll';",
            "  out.requested = true;",
            "  if (typeof body.run_id === 'string' && body.run_id) out.run_id = body.run_id;",
            "} else if (code === 502 || code === 503) {",
            "  const why = String(body.reason || ('HTTP ' + code)).slice(0, 80);",
            "  Object.assign(out, { phase: 'done', status: 'failed', reason: why, retryable: true });",
            "} else if (code === 403 && s.attempt > 1) {",
            "  // The host refused the retry key (e.g. a d: slot not RETRY_DUE under the lane's host retry policy):",
            "  // the run already FAILED, so it stays failed and the budget ends here.",
            "  const why = String(body.reason || body.state || 'refused').slice(0, 72);",
            "  Object.assign(out, { phase: 'done', status: 'failed', reason: 'retry_refused:' + why, retryable: false });",
            "} else if (code === 403) {",
            "  const why = String(body.reason || body.state || 'refused').slice(0, 80);",
            "  Object.assign(out, { phase: 'done', status: 'refused_policy', reason: why, retryable: false });",
            "} else {",
            "  throw new Error('run-lane: relay /run HTTP ' + code + ' ' + String(body.reason || '').slice(0, 60));",
            "}",
            "$execution.customData.set('run_id', String(out.run_id));",
            "return [{ json: out }];",
            "",
        ]
    )


def _run_lane_evaluate_js() -> str:
    return "\n".join(
        [
            "// Generated by scripts/n8n_workflow_templates.py build-fabric — do not edit in n8n.",
            "// One RunOutcome@v1 poll. Terminal -> status; pending/unknown/unreachable -> poll again with bounded",
            "// exponential backoff until outcome_timeout_s, then failed/outcome_timeout (RUN_LOST: never retried).",
            f"const TERMINAL = {json.dumps(list(RUN_LANE_TERMINAL))};",
            f"const POLL_MAX_S = {RUN_LANE_POLL_MAX_S};",
            f"const s = $('{RL_WAIT}').last().json;",
            "const r = $input.first().json || {};",
            "const body = (r.body && typeof r.body === 'object') ? r.body : {};",
            "const out = { ...s, polls: s.polls + 1, waited_s: s.waited_s + s.wait_s };",
            "const ok = r.statusCode === 200 && body.schema === 'RunOutcome@v1' && body.state === 'OK';",
            "if (ok && TERMINAL.includes(body.status)) {",
            "  Object.assign(out, { phase: 'done', status: body.status, exit_code: body.exit_code ?? null,",
            "    receipt_path: body.receipt_path ?? null, effect_key: body.effect_key ?? null,",
            "    duration_s: body.duration_s ?? null, reason: body.reason ?? null,",
            "    retryable: body.status === 'failed' && !String(body.reason || '').startsWith('effect:') });",
            "} else if (out.waited_s >= s.outcome_timeout_s) {",
            "  Object.assign(out, { phase: 'done', status: 'failed', reason: 'outcome_timeout', retryable: false });",
            "} else {",
            "  out.phase = 'poll';",
            "  out.last_seen = ok ? String(body.status) : ('HTTP ' + String(r.statusCode));",
            "  out.wait_s = Math.min(POLL_MAX_S, s.wait_s * 2, Math.max(1, s.outcome_timeout_s - out.waited_s));",
            "}",
            "return [{ json: out }];",
            "",
        ]
    )


def _run_lane_next_js() -> str:
    return "\n".join(
        [
            "// Generated by scripts/n8n_workflow_templates.py build-fabric — do not edit in n8n.",
            "const s = $input.first().json;",
            "const history = (s.history || []).concat([{ attempt: s.attempt, run_id: s.run_id, status: s.status,",
            "  reason: s.reason }]);",
            "return [{ json: { lane_id: s.lane_id, mode: s.mode, base_key: s.base_key, attempt: s.attempt + 1,",
            "  key_attempt: s.requested ? s.key_attempt + 1 : s.key_attempt, max_attempts: s.max_attempts,",
            "  outcome_timeout_s: s.outcome_timeout_s, process_id: s.process_id, history } }];",
            "",
        ]
    )


def _run_lane_result_js() -> str:
    return "\n".join(
        [
            "// Generated by scripts/n8n_workflow_templates.py build-fabric — do not edit in n8n.",
            "// RunLaneResult@v1: the structured result the calling workflow branches on. A failed run with no budget",
            "// left is dead_letter: true; its dead-letter ROW stays in the host ledger (scripts/n8n_dlq.py).",
            f"const TERMINAL = {json.dumps(list(RUN_LANE_TERMINAL))};",
            "const s = $input.first().json;",
            "const status = TERMINAL.includes(s.status) ? s.status : 'failed';",
            "const history = (s.history || []).concat([{ attempt: s.attempt, run_id: s.run_id, status,",
            "  reason: s.reason ?? null }]);",
            "return [{ json: {",
            "  schema: 'RunLaneResult@v1', lane_id: s.lane_id, mode: s.mode, process_id: s.process_id || null,",
            "  run_id: s.run_id, status, reason: TERMINAL.includes(s.status) ? (s.reason ?? null) : 'unrouted_status',",
            "  attempts: s.attempt, max_attempts: s.max_attempts, exit_code: s.exit_code ?? null,",
            "  receipt_path: s.receipt_path ?? null, effect_key: s.effect_key ?? null, duration_s: s.duration_s ?? null,",
            "  dead_letter: status === 'failed', history,",
            "} }];",
            "",
        ]
    )


def _fabric_settings(wid: str, timeout_s: int, *, caller_policy: str | None = None) -> dict:
    settings: dict = dict(FABRIC_REQUIRED_SETTINGS)
    settings["executionTimeout"] = timeout_s
    settings["errorWorkflow"] = FABRIC_ERROR_ID  # the error workflow names itself (n8n skips self-recursion)
    if caller_policy is not None:
        settings["callerPolicy"] = caller_policy
    return settings


def _fabric_doc(wid: str, kind: str, nodes: list[dict], conns: dict, settings: dict) -> dict:
    nodes.sort(key=lambda n: n["name"])
    wf = {
        "id": wid,
        "name": wid,
        "active": False,
        "nodes": nodes,
        "connections": conns,
        "settings": settings,
        "meta": {
            "generator": FABRIC_GENERATOR,
            "kind": kind,
            "design": "AGENTS.md §23.23 (10.0.0 PROPOSED); arch-review-20261014 REFACTOR_PLAN B4-B6",
        },
    }
    wf["meta"]["graph_sha256"] = graph_hash(wf)
    wf["meta"]["policy_sha256"] = policy_hash()
    return wf


def build_run_lane() -> dict:
    """The Run Lane sub-workflow: request -> poll outcome (bounded backoff) -> Switch on status -> retry budget ->
    RunLaneResult@v1. Retries are owned here; refusals are data; nothing here sends or holds a secret."""
    wid = RUN_LANE_ID
    inputs = [
        {"name": "lane_id", "type": "string"},
        {"name": "mode", "type": "string"},
        {"name": "idempotency_key", "type": "string"},
        {"name": "max_attempts", "type": "number"},
        {"name": "outcome_timeout_s", "type": "number"},
        {"name": "process_id", "type": "string"},
    ]
    run_body = (
        "={{ JSON.stringify({ lane_id: $json.lane_id, mode: $json.mode, idempotency_key: $json.idempotency_key, "
        "workflow_id: String($workflow.id), execution_id: String($execution.id) }) }}"
    )
    nodes = [
        {
            "id": _f_node_id(wid, RL_INPUT),
            "name": RL_INPUT,
            "type": "n8n-nodes-base.executeWorkflowTrigger",
            "typeVersion": 1.1,
            "position": [0, 300],
            "parameters": {"inputSource": "workflowInputs", "workflowInputs": {"values": inputs}},
        },
        _f_set_relay(wid, RL_SET, [240, 300]),
        _f_code(wid, RL_INIT, _run_lane_init_js(), [480, 300]),
        _f_code(wid, RL_PREP, _run_lane_prepare_js(), [720, 300]),
        _f_http(wid, RL_POST, method="POST", path_expr="/run", position=[960, 300], json_body=run_body),
        _f_code(wid, RL_CLASSIFY, _run_lane_classify_js(), [1200, 300]),
        _f_if(wid, RL_REQUESTED, "={{ $json.phase === 'poll' }}", [1440, 300]),
        _f_wait(wid, RL_WAIT, "={{ $json.wait_s }}", [1680, 180]),
        _f_http(
            wid,
            RL_GET,
            method="GET",
            path_expr="/run_outcome?run_id={{ encodeURIComponent($json.run_id) }}",
            position=[1920, 180],
        ),
        _f_code(wid, RL_EVAL, _run_lane_evaluate_js(), [2160, 180]),
        _f_if(wid, RL_PENDING, "={{ $json.phase === 'poll' }}", [2400, 180]),
        _f_switch(wid, RL_SWITCH, "={{ $json.status }}", RUN_LANE_TERMINAL, [2640, 420]),
        _f_if(wid, RL_BUDGET, "={{ $json.retryable === true && $json.attempt < $json.max_attempts }}", [2880, 420]),
        _f_wait(
            wid,
            RL_BACKOFF,
            "={{ Math.min("
            + str(RUN_LANE_RETRY_BACKOFF_MAX_S)
            + ", "
            + str(RUN_LANE_RETRY_BACKOFF_BASE_S)
            + " * Math.pow(2, $json.attempt - 1)) }}",
            [3120, 300],
        ),
        _f_code(wid, RL_NEXT, _run_lane_next_js(), [3360, 300]),
        _f_code(wid, RL_RESULT, _run_lane_result_js(), [3360, 600]),
    ]
    conns: dict = {}
    _g_main(conns, RL_INPUT, [RL_SET])
    _g_main(conns, RL_SET, [RL_INIT])
    _g_main(conns, RL_INIT, [RL_PREP])
    _g_main(conns, RL_PREP, [RL_POST])
    _g_main(conns, RL_POST, [RL_CLASSIFY])
    _g_main(conns, RL_CLASSIFY, [RL_REQUESTED])
    _g_main(conns, RL_REQUESTED, [RL_WAIT], [RL_SWITCH])
    _g_main(conns, RL_WAIT, [RL_GET])
    _g_main(conns, RL_GET, [RL_EVAL])
    _g_main(conns, RL_EVAL, [RL_PENDING])
    _g_main(conns, RL_PENDING, [RL_WAIT], [RL_SWITCH])
    # Switch outputs in RUN_LANE_TERMINAL order, then the fallback (an unrouted status -> Result as failed).
    _g_main(conns, RL_SWITCH, [RL_RESULT], [RL_BUDGET], [RL_RESULT], [RL_RESULT], [RL_RESULT])
    _g_main(conns, RL_BUDGET, [RL_BACKOFF], [RL_RESULT])
    _g_main(conns, RL_BACKOFF, [RL_NEXT])
    _g_main(conns, RL_NEXT, [RL_PREP])
    settings = _fabric_settings(wid, RUN_LANE_EXECUTION_TIMEOUT_S, caller_policy="workflowsFromSameOwner")
    return _fabric_doc(wid, "run-lane", nodes, conns, settings)


def _fabric_shape_intent_js() -> str:
    return "\n".join(
        [
            "// Generated by scripts/n8n_workflow_templates.py build-fabric — do not edit in n8n.",
            "// Error Trigger payload -> one send-INTENT. n8n holds no bot token: the host dedupes, caps, routes by the",
            "// alert taxonomy (config/n8n_comms_intent_routes.json) and the comms gateway alone sends.",
            "const e = $input.first().json || {};",
            "const exec = e.execution || {};",
            "const wf = e.workflow || {};",
            "const err = exec.error || (e.trigger && e.trigger.error) || {};",
            "const WF_RE = /^[A-Za-z0-9._-]{1,64}$/;",
            "const EX_RE = /^[A-Za-z0-9_-]{1,40}$/;",
            "const wid = WF_RE.test(String(wf.id ?? '')) ? String(wf.id) : 'unknown';",
            "const xid = EX_RE.test(String(exec.id ?? '')) ? String(exec.id) : 'none';",
            "const node = String(exec.lastNodeExecuted ?? (err.node && err.node.name) ?? '').slice(0, 64);",
            "return [{ json: {",
            "  domain: 'fabric', kind: 'workflow_error',",
            "  subject: ('workflow ' + String(wf.name ?? wid) + ' failed at ' + (node || 'trigger')).slice(0, 120),",
            "  summary: String(err.message ?? '').slice(0, 300),",
            "  workflow_id: wid, execution_id: xid, node,",
            "} }];",
            "",
        ]
    )


def _fabric_assert_intent_js() -> str:
    return "\n".join(
        [
            "// Generated by scripts/n8n_workflow_templates.py build-fabric — do not edit in n8n.",
            "// An intent the host did not accept is this execution's error (saved; n8n does not re-enter an error",
            "// workflow from its own failure). The host-side P1 path never depends on this (§24.1).",
            "const r = $input.first().json || {};",
            "const body = (r.body && typeof r.body === 'object') ? r.body : {};",
            "if (r.statusCode === 200 && body.state === 'ACCEPTED') {",
            "  return [{ json: { intent_id: body.intent_id, tier: body.tier, duplicate: body.duplicate === true } }];",
            "}",
            "throw new Error('fabric-error: intent not accepted: ' + String(body.reason || ('HTTP ' + r.statusCode)).slice(0, 80));",
            "",
        ]
    )


def build_fabric_error() -> dict:
    wid = FABRIC_ERROR_ID
    intent_body = (
        "={{ JSON.stringify({ domain: $json.domain, kind: $json.kind, subject: $json.subject, summary: $json.summary, "
        "workflow_id: $json.workflow_id, execution_id: $json.execution_id, node: $json.node }) }}"
    )
    nodes = [
        {
            "id": _f_node_id(wid, FE_TRIGGER),
            "name": FE_TRIGGER,
            "type": "n8n-nodes-base.errorTrigger",
            "typeVersion": 1,
            "position": [0, 300],
            "parameters": {},
        },
        _f_code(wid, FE_SHAPE, _fabric_shape_intent_js(), [240, 300]),
        _f_set_relay(wid, FE_SET, [480, 300]),
        _f_http(
            wid,
            FE_POST,
            method="POST",
            path_expr="/intent",
            position=[720, 300],
            json_body=intent_body,
            relay_node=FE_SET,
        ),
        _f_code(wid, FE_ASSERT, _fabric_assert_intent_js(), [960, 300]),
    ]
    conns: dict = {}
    _g_main(conns, FE_TRIGGER, [FE_SHAPE])
    _g_main(conns, FE_SHAPE, [FE_SET])
    _g_main(conns, FE_SET, [FE_POST])
    _g_main(conns, FE_POST, [FE_ASSERT])
    return _fabric_doc(wid, "error", nodes, conns, _fabric_settings(wid, FABRIC_ERROR_TIMEOUT_S))


def _fabric_probe_assert_js() -> str:
    return "\n".join(
        [
            "// Generated by scripts/n8n_workflow_templates.py build-fabric — do not edit in n8n.",
            "// Dry-run proof: Run Lane returned a RunLaneResult@v1 with a terminal status (any of the four).",
            f"const TERMINAL = {json.dumps(list(RUN_LANE_TERMINAL))};",
            "const r = $input.first().json || {};",
            "if (r.schema !== 'RunLaneResult@v1' || !TERMINAL.includes(r.status)) {",
            "  throw new Error('fabric-probe: unexpected Run Lane result ' + String(r.status));",
            "}",
            "return [{ json: { probe_ok: true, status: r.status, run_id: r.run_id, attempts: r.attempts } }];",
            "",
        ]
    )


def build_fabric_probe() -> dict:
    """Inactive; for the operator's one-off dry-run proof (`n8n execute --id`). It starts from a Manual Trigger only
    (no schedule: it can never fire on its own) and calls Run Lane once, in dry_run, for FABRIC_PROBE_LANE."""
    wid = FABRIC_PROBE_ID
    key_expr = "={{ 'fabric-probe-' + String($execution.id) + '-' + $now.toFormat('yyyyLLddHHmmss') }}"
    nodes = [
        {
            "id": _f_node_id(wid, FP_MANUAL),
            "name": FP_MANUAL,
            "type": "n8n-nodes-base.manualTrigger",
            "typeVersion": 1,
            "position": [0, 300],
            "parameters": {},
        },
        {
            "id": _f_node_id(wid, FP_INPUT),
            "name": FP_INPUT,
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.4,
            "position": [240, 300],
            "parameters": {
                "assignments": {
                    "assignments": [
                        {
                            "id": _f_node_id(wid, "lane"),
                            "name": "lane_id",
                            "type": "string",
                            "value": FABRIC_PROBE_LANE,
                        },
                        {"id": _f_node_id(wid, "mode"), "name": "mode", "type": "string", "value": "dry_run"},
                        {"id": _f_node_id(wid, "key"), "name": "idempotency_key", "type": "string", "value": key_expr},
                        {"id": _f_node_id(wid, "max"), "name": "max_attempts", "type": "number", "value": 1},
                        {"id": _f_node_id(wid, "tmo"), "name": "outcome_timeout_s", "type": "number", "value": 120},
                    ]
                },
                "options": {},
            },
        },
        {
            "id": _f_node_id(wid, FP_CALL),
            "name": FP_CALL,
            "type": "n8n-nodes-base.executeWorkflow",
            "typeVersion": 1.2,
            "position": [480, 300],
            "parameters": {
                "source": "database",
                "workflowId": {"__rl": True, "value": RUN_LANE_ID, "mode": "id"},
                "workflowInputs": {
                    "mappingMode": "defineBelow",
                    "value": {
                        "lane_id": "={{ $json.lane_id }}",
                        "mode": "={{ $json.mode }}",
                        "idempotency_key": "={{ $json.idempotency_key }}",
                        "max_attempts": "={{ $json.max_attempts }}",
                        "outcome_timeout_s": "={{ $json.outcome_timeout_s }}",
                        "process_id": "",
                    },
                    "matchingColumns": [],
                    "schema": [],
                },
                "options": {"waitForSubWorkflow": True},
            },
        },
        _f_code(wid, FP_ASSERT, _fabric_probe_assert_js(), [720, 300]),
    ]
    conns: dict = {}
    _g_main(conns, FP_MANUAL, [FP_INPUT])
    _g_main(conns, FP_INPUT, [FP_CALL])
    _g_main(conns, FP_CALL, [FP_ASSERT])
    return _fabric_doc(wid, "probe", nodes, conns, _fabric_settings(wid, FABRIC_PROBE_TIMEOUT_S))


FEP_SCHED = "Schedule"
FEP_FAIL = "Fail on purpose"


def build_fabric_error_probe() -> dict:
    """Inactive. Every fire throws, so the fabric error workflow runs from an AUTOMATIC failure (addendum item 9).
    The packet publishes it for exactly one fire and unpublishes it; the resulting intent is a DIGEST row, queued."""
    wid = FABRIC_ERROR_PROBE_ID
    js = "\n".join(
        [
            "// Generated by scripts/n8n_workflow_templates.py build-fabric — do not edit in n8n.",
            "// Deliberate failure for the Error Trigger acceptance proof (packet n8n-fabric-phase1-20261014).",
            "throw new Error('fabric-error-probe: deliberate failure (acceptance proof)');",
            "",
        ]
    )
    nodes = [
        {
            "id": _f_node_id(wid, FEP_SCHED),
            "name": FEP_SCHED,
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.2,
            "position": [0, 300],
            "parameters": {"rule": {"interval": [{"field": "cronExpression", "expression": "* * * * *"}]}},
        },
        _f_code(wid, FEP_FAIL, js, [240, 300]),
    ]
    conns: dict = {}
    _g_main(conns, FEP_SCHED, [FEP_FAIL])
    return _fabric_doc(wid, "error-probe", nodes, conns, _fabric_settings(wid, FABRIC_ERROR_TIMEOUT_S))


# ── n8n fabric process workflows (2026-10-15; AGENTS.md §23.23 10.0.0 ACTIVE: n8n owns FLOW) ───────────────────────
# One workflow per business process in config/n8n_fabric_processes.json. The first is hermes-learning (learn -> tune,
# the 7 steps of config/pipelines/hermes_learning.json). Shape: a Schedule Trigger per stage at the manifest's
# proposed_schedule (identical to the runner's cron slot; the workflow is generated INACTIVE so nothing fires) plus a
# Manual Trigger for proofs (runs every stage in order) -> Process context (slot, mode) -> Route stage (Switch) -> per
# step: Gate (dependencies all `success`? not BLOCKED?) -> Run? (If) -> Run <step> (Execute Workflow -> the PUBLISHED
# Run Lane sub-workflow, which owns retries) -> Result <step> (FabricStepResult@v1). Independent steps sit on separate
# branches joined by Merge; n8n's v1 execution order runs branches one after another, so "parallel" means "a failure
# in one branch never stops a sibling", not concurrency. A step whose dependency did not end `success` is
# skipped_upstream: a failed step stops everything downstream of it and the Process result names it. The process
# calls no relay route itself: every host call goes through Run Lane.

PROCESS_SPEC_REL = Path("config") / "n8n_fabric_processes.json"
PROCESS_SPEC_SCHEMA = "N8nFabricProcesses@v1"
PROCESS_KIND = "process"
PROCESS_STEP_RESULT_SCHEMA = "FabricStepResult@v1"
PROCESS_RESULT_SCHEMA = "FabricProcessResult@v1"
#: n8n's EXECUTIONS_TIMEOUT_MAX default; a process must finish its worst case (every runnable step using its whole Run
#: Lane budget, every stage: the manual run) inside it, or the generator refuses the spec.
PROCESS_EXECUTION_TIMEOUT_S = 3600
#: outcome_timeout_s handed to Run Lane = the step's executor timeout + this margin (queueing, receipt write).
PROCESS_OUTCOME_MARGIN_S = 120
PROCESS_MODES = ("dry_run", "live")
#: Step statuses a Result node can carry: Run Lane's four terminal statuses plus the two the process decides itself.
PROCESS_STEP_STATUSES = RUN_LANE_TERMINAL + ("blocked", "skipped_upstream")
#: Statuses that make the whole execution an error (-> errorWorkflow tradeai-fabric-error -> host intent).
PROCESS_FAILING_STATUSES = ("failed", "refused_policy", "not_run")
#: Idempotency key a process step requests: p:<lane>:<mode>:<slot>. Not a server-minted d:/e:/g: key, so the gateway
#: accepts it as a caller key today and the executor's effect gate refuses it for a LIVE run (effect_slot_unknown)
#: until the gateway validates p: keys against this spec (cutover prerequisite, packet README).
PROCESS_KEY_PREFIX = "p"
_PROCESS_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
_STEP_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
PN_MANUAL = "Manual run"
PN_CTX = "Process context"
PN_ROUTE = "Route stage"
PN_RESULT = "Process result"
PN_ASSERT = "Assert process"


def load_process_specs(path: Path | None = None) -> dict:
    doc = json.loads((path or (ROOT / PROCESS_SPEC_REL)).read_text(encoding="utf-8"))
    if doc.get("schema") != PROCESS_SPEC_SCHEMA or not isinstance(doc.get("processes"), dict):
        raise ValueError(f"{PROCESS_SPEC_REL}: not a {PROCESS_SPEC_SCHEMA} document")
    return doc["processes"]


def schedule_hhmm(expr: str) -> str:
    """'50 10 * * *' -> '1050'. A process stage slot is one minute a day (the runner's cron slot)."""
    parts = str(expr or "").split()
    if len(parts) != 5 or parts[2:] != ["*", "*", "*"] or not (parts[0].isdigit() and parts[1].isdigit()):
        raise ValueError(f"stage schedule {expr!r} is not a single daily minute 'M H * * *'")
    m, h = int(parts[0]), int(parts[1])
    if not (0 <= m <= 59 and 0 <= h <= 23):
        raise ValueError(f"stage schedule {expr!r} out of range")
    return f"{h:02d}{m:02d}"


def timeout_seconds_of(value) -> int:
    s = str(value).strip()
    unit = s[-1] if s and s[-1] in "smh" else ""
    num = s[:-1] if unit else s
    if not num.isdigit():
        raise ValueError(f"bad timeout {value!r}")
    return int(num) * {"": 1, "s": 1, "m": 60, "h": 3600}[unit]


def run_lane_worst_case_s(max_attempts: int, outcome_timeout_s: int) -> int:
    """Run Lane's longest wall time for one call: every attempt waits its whole outcome timeout, plus the backoffs
    between attempts (Run Lane: min(MAX, BASE * 2^(attempt-1)))."""
    backoff = sum(
        min(RUN_LANE_RETRY_BACKOFF_MAX_S, RUN_LANE_RETRY_BACKOFF_BASE_S * 2 ** (a - 1)) for a in range(1, max_attempts)
    )
    return max_attempts * outcome_timeout_s + backoff


def process_plan(process_id: str, spec: dict, manifest: dict) -> dict:
    """Validated plan: stages in manifest order, each with its steps (manifest order), schedules, Run Lane budgets.
    Raises ValueError on any inconsistency between the spec and the manifest (the generator refuses to render)."""
    if not _PROCESS_ID_RE.fullmatch(process_id):
        raise ValueError(f"bad process id {process_id!r}")
    if spec.get("mode") not in PROCESS_MODES:
        raise ValueError(f"{process_id}: mode must be one of {PROCESS_MODES}")
    stages_doc = manifest.get("stages") or {}
    steps_spec = spec.get("steps") or {}
    default_attempts = int(spec.get("default_max_attempts") or 1)
    manifest_ids = [str(st["id"]) for s in stages_doc.values() for st in s.get("steps") or []]
    if sorted(manifest_ids) != sorted(steps_spec):
        raise ValueError(f"{process_id}: spec steps {sorted(steps_spec)} != manifest steps {sorted(manifest_ids)}")
    lanes = [str(v.get("lane_id")) for v in steps_spec.values()]
    if len(set(lanes)) != len(lanes) or not all(_PROCESS_ID_RE.fullmatch(lane) for lane in lanes):
        raise ValueError(f"{process_id}: step lane ids must be unique lane ids")
    stages = []
    for stage, sdoc in stages_doc.items():
        order = [str(st["id"]) for st in sdoc.get("steps") or []]
        if not order:
            raise ValueError(f"{process_id}: stage {stage} has no steps")
        steps = []
        for i, st in enumerate(sdoc["steps"]):
            sid = str(st["id"])
            ss = steps_spec[sid]
            if not _STEP_ID_RE.fullmatch(sid):
                raise ValueError(f"{process_id}: bad step id {sid!r}")
            deps = list(ss.get("depends_on") or [])
            for d in deps:
                if d not in order[:i]:
                    raise ValueError(f"{process_id}: step {sid} depends on {d!r}, not an earlier step of stage {stage}")
            blocked = ss.get("blocked")
            if blocked is not None and (not isinstance(blocked, str) or not blocked.strip()):
                raise ValueError(f"{process_id}: step {sid} blocked must be null or a reason")
            attempts = max(1, min(RUN_LANE_MAX_ATTEMPTS, int(ss.get("max_attempts") or default_attempts)))
            tmo = min(RUN_LANE_OUTCOME_TIMEOUT_MAX_S, timeout_seconds_of(st["timeout"]) + PROCESS_OUTCOME_MARGIN_S)
            # Optional per-step cap on how long Run Lane waits (2026-10-15): only ever LOWERS the derived wait, so a
            # spec can fit the manual all-stages run into the execution timeout. The executor's own timeout (the
            # allowlist timeout_s = the manifest step timeout) is unchanged; a step that outlives the wait ends
            # failed/outcome_timeout in Run Lane (the process fails), never success.
            cap = ss.get("outcome_timeout_s")
            if cap is not None:
                if isinstance(cap, bool) or not isinstance(cap, int) or not PROCESS_OUTCOME_MARGIN_S <= cap <= tmo:
                    raise ValueError(
                        f"{process_id}: step {sid} outcome_timeout_s must be an int in"
                        f" [{PROCESS_OUTCOME_MARGIN_S}, {tmo}] (it can only lower the derived wait)"
                    )
                tmo = cap
            steps.append(
                {
                    "id": sid,
                    "lane_id": ss["lane_id"],
                    "stage": stage,
                    "depends_on": deps,
                    "blocked": blocked,
                    "max_attempts": attempts,
                    "outcome_timeout_s": tmo,
                    "worst_case_s": 0 if blocked else run_lane_worst_case_s(attempts, tmo),
                }
            )
        dependents = {s["id"]: [t["id"] for t in steps if s["id"] in t["depends_on"]] for s in steps}
        stages.append(
            {
                "stage": stage,
                "schedule": sdoc.get("proposed_schedule"),
                "slot_hhmm": schedule_hhmm(sdoc.get("proposed_schedule")),
                "steps": steps,
                "entry": [s["id"] for s in steps if not s["depends_on"]],
                "terminals": [s["id"] for s in steps if not dependents[s["id"]]],
                "dependents": dependents,
                "worst_case_s": sum(s["worst_case_s"] for s in steps),
            }
        )
    total = sum(s["worst_case_s"] for s in stages)
    if total > PROCESS_EXECUTION_TIMEOUT_S:
        raise ValueError(
            f"{process_id}: worst case {total} s (every runnable step of every stage: the manual run) exceeds the"
            f" execution timeout {PROCESS_EXECUTION_TIMEOUT_S} s; lower max_attempts or split the process"
        )
    return {
        "process_id": process_id,
        "workflow_id": spec["workflow_id"],
        "mode": spec["mode"],
        "stages": stages,
        "worst_case_s": total,
    }


def _js_header() -> list[str]:
    return ["// Generated by scripts/n8n_workflow_templates.py build-fabric — do not edit in n8n."]


def _js_res_helper() -> list[str]:
    return [
        "// A node that did not run in this execution throws on $(name).first(): that is 'not_run', never success.",
        "function res(name) { try { return $(name).first().json; } catch (e) { return null; } }",
    ]


def _process_plan_js(trigger: str, stage: str) -> str:
    return "\n".join(
        _js_header() + [f"return [{{ json: {{ trigger: {json.dumps(trigger)}, stage: {json.dumps(stage)} }} }}];", ""]
    )


def _process_context_js(plan: dict) -> str:
    slots = {s["stage"]: s["slot_hhmm"] for s in plan["stages"]}
    return "\n".join(
        _js_header()
        + [
            "// One process run: which stage(s), the mode the host is asked for, and the business slot. A scheduled",
            "// stage's slot is today's date + the stage's cron minute (the cron runner's effect-key slot is the same",
            "// string: scripts/pipelines/pipeline_manifest.py --effect-slot); a manual proof run uses its own minute",
            "// so it never reuses a scheduled slot's idempotency keys.",
            f"const PROCESS_ID = {json.dumps(plan['process_id'])};",
            f"const MODE = {json.dumps(plan['mode'])};",
            f"const SLOTS = {json.dumps(slots, sort_keys=True)};",
            f"const TZ = {json.dumps(TIMEZONE)};",
            "const p = $input.first().json || {};",
            "const stages = Object.keys(SLOTS).concat(['all']);",
            "if (!stages.includes(p.stage)) throw new Error('process ' + PROCESS_ID + ': bad stage ' + String(p.stage));",
            "if (p.trigger !== 'schedule' && p.trigger !== 'manual') throw new Error('process ' + PROCESS_ID + ': bad trigger');",
            "if (p.trigger === 'schedule' && p.stage === 'all') throw new Error('process ' + PROCESS_ID + ': schedule runs one stage');",
            "const now = $now.setZone(TZ);",
            "const slot = p.trigger === 'schedule' ? now.toFormat('yyyyLLdd') + 'T' + SLOTS[p.stage]"
            " : now.toFormat(\"yyyyLLdd'T'HHmm\");",
            "$execution.customData.set('process_id', PROCESS_ID);",
            "$execution.customData.set('stage', p.stage);",
            "$execution.customData.set('slot', slot);",
            "$execution.customData.set('mode', MODE);",
            "return [{ json: { process_id: PROCESS_ID, stage: p.stage, trigger: p.trigger, mode: MODE, slot } }];",
            "",
        ]
    )


def _process_gate_js(step: dict) -> str:
    dep_nodes = {d: f"Result {d}" for d in step["depends_on"]}
    spec = {
        "step_id": step["id"],
        "lane_id": step["lane_id"],
        "stage": step["stage"],
        "depends_on": step["depends_on"],
        "blocked": step["blocked"],
        "max_attempts": step["max_attempts"],
        "outcome_timeout_s": step["outcome_timeout_s"],
    }
    return "\n".join(
        _js_header()
        + [
            "// Run this step only when it is not BLOCKED and every dependency ended `success`. Otherwise the step is",
            "// recorded (blocked / skipped_upstream) without a host call, and its own dependents skip in turn.",
            f"const STEP = {json.dumps(spec, sort_keys=True, ensure_ascii=False)};",
            f"const DEP_NODES = {json.dumps(dep_nodes, sort_keys=True)};",
            f"const KEY_PREFIX = {json.dumps(PROCESS_KEY_PREFIX)};",
        ]
        + _js_res_helper()
        + [
            f"const ctx = $('{PN_CTX}').first().json;",
            "const base = { step_id: STEP.step_id, lane_id: STEP.lane_id, stage: STEP.stage, depends_on: STEP.depends_on };",
            "if (STEP.blocked) return [{ json: { ...base, run: false, skip: 'blocked', reason: STEP.blocked } }];",
            "const notOk = [];",
            "for (const d of STEP.depends_on) {",
            "  const r = res(DEP_NODES[d]);",
            "  if (!r || r.status !== 'success') notOk.push(d + ':' + (r ? String(r.status) : 'not_run'));",
            "}",
            "if (notOk.length) return [{ json: { ...base, run: false, skip: 'skipped_upstream', reason: notOk.join(',') } }];",
            "const key = [KEY_PREFIX, STEP.lane_id, ctx.mode, ctx.slot].join(':');",
            "return [{ json: { ...base, run: true, mode: ctx.mode, idempotency_key: key, max_attempts: STEP.max_attempts,",
            "  outcome_timeout_s: STEP.outcome_timeout_s, process_id: ctx.process_id } }];",
            "",
        ]
    )


def _process_result_step_js(step: dict) -> str:
    return "\n".join(
        _js_header()
        + [
            "// FabricStepResult@v1: the Run Lane result of this step, or the Gate's skip as data.",
            f"const SCHEMA = {json.dumps(PROCESS_STEP_RESULT_SCHEMA)};",
            f"const g = $('Gate {step['id']}').first().json;",
            "const r = $input.first().json || {};",
            "const base = { schema: SCHEMA, step_id: g.step_id, lane_id: g.lane_id, stage: g.stage };",
            "if (g.run !== true) {",
            "  return [{ json: { ...base, status: g.skip, run_id: null, attempts: 0, reason: g.reason ?? null } }];",
            "}",
            "if (r.schema !== 'RunLaneResult@v1') {",
            "  return [{ json: { ...base, status: 'failed', run_id: null, attempts: 0, reason: 'no_run_lane_result' } }];",
            "}",
            "return [{ json: { ...base, status: r.status, run_id: r.run_id, attempts: r.attempts, reason: r.reason ?? null,",
            "  exit_code: r.exit_code ?? null, duration_s: r.duration_s ?? null, dead_letter: r.dead_letter === true,",
            "  effect_key: r.effect_key ?? null, receipt_path: r.receipt_path ?? null } }];",
            "",
        ]
    )


def _process_stage_done_js(stage: str) -> str:
    return "\n".join(
        _js_header()
        + [
            "// One item per stage, whatever number of branches joined here.",
            f"return [{{ json: {{ stage_done: {json.dumps(stage)}, branches: $input.all().length }} }}];",
            "",
        ]
    )


def _process_result_js(plan: dict) -> str:
    steps = [{"step_id": s["id"], "stage": s["stage"]} for st in plan["stages"] for s in st["steps"]]
    return "\n".join(
        _js_header()
        + [
            "// FabricProcessResult@v1: every step of the stage(s) this run covered, in manifest order, with its run_id",
            "// and status. A failed / refused / missing step makes the run `failed` (Assert process then throws, so the",
            "// execution is an error and tradeai-fabric-error raises a host intent); blocked or skipped only is `partial`.",
            f"const SCHEMA = {json.dumps(PROCESS_RESULT_SCHEMA)};",
            f"const STEPS = {json.dumps(steps)};",
            f"const FAILING = {json.dumps(list(PROCESS_FAILING_STATUSES))};",
        ]
        + _js_res_helper()
        + [
            f"const ctx = $('{PN_CTX}').first().json;",
            "const steps = [];",
            "for (const s of STEPS) {",
            "  if (ctx.stage !== 'all' && s.stage !== ctx.stage) continue;",
            "  const r = res('Result ' + s.step_id);",
            "  steps.push(r || { step_id: s.step_id, stage: s.stage, status: 'not_run', run_id: null, attempts: 0,",
            "    reason: 'result_node_not_executed' });",
            "}",
            "const failed = steps.filter((s) => FAILING.includes(s.status)).map((s) => s.step_id);",
            "const overall = failed.length ? 'failed' : (steps.every((s) => s.status === 'success') ? 'ok' : 'partial');",
            "const counts = {};",
            "for (const s of steps) counts[s.status] = (counts[s.status] || 0) + 1;",
            "$execution.customData.set('overall', overall);",
            "if (failed.length) $execution.customData.set('failed_steps', failed.join(',').slice(0, 250));",
            "return [{ json: { schema: SCHEMA, process_id: ctx.process_id, stage: ctx.stage, trigger: ctx.trigger,",
            "  mode: ctx.mode, slot: ctx.slot, overall, failed_steps: failed, first_failed_step: failed[0] || null,",
            "  counts, steps } }];",
            "",
        ]
    )


def _process_assert_js() -> str:
    return "\n".join(
        _js_header()
        + [
            "// A failed run is this execution's error: saved, and the error workflow raises a host intent.",
            "const r = $input.first().json || {};",
            "if (r.overall === 'failed') {",
            "  throw new Error('process ' + r.process_id + ' slot ' + r.slot + ': failed step(s) ' + r.failed_steps.join(','));",
            "}",
            "return [{ json: r }];",
            "",
        ]
    )


def _p_conn(conns: dict, src: str, outputs: list[list[tuple[str, int]]]) -> None:
    conns[src] = {"main": [[{"node": n, "type": "main", "index": i} for n, i in out] for out in outputs]}


def _p_merge(wid: str, name: str, inputs: int, position: list[int]) -> dict:
    return {
        "id": _f_node_id(wid, name),
        "name": name,
        "type": "n8n-nodes-base.merge",
        "typeVersion": 3.1,
        "position": position,
        "parameters": {"numberInputs": inputs},
    }


def _p_run(wid: str, name: str, position: list[int]) -> dict:
    return {
        "id": _f_node_id(wid, name),
        "name": name,
        "type": "n8n-nodes-base.executeWorkflow",
        "typeVersion": 1.2,
        "position": position,
        "parameters": {
            "source": "database",
            "workflowId": {"__rl": True, "value": RUN_LANE_ID, "mode": "id"},
            "workflowInputs": {
                "mappingMode": "defineBelow",
                "value": {
                    "lane_id": "={{ $json.lane_id }}",
                    "mode": "={{ $json.mode }}",
                    "idempotency_key": "={{ $json.idempotency_key }}",
                    "max_attempts": "={{ $json.max_attempts }}",
                    "outcome_timeout_s": "={{ $json.outcome_timeout_s }}",
                    "process_id": "={{ $json.process_id }}",
                },
                "matchingColumns": [],
                "schema": [],
            },
            "options": {"waitForSubWorkflow": True},
        },
    }


def build_process(process_id: str, spec: dict, manifest: dict) -> dict:
    """The process workflow for one config/n8n_fabric_processes.json entry (inactive; see the section comment)."""
    plan = process_plan(process_id, spec, manifest)
    wid = plan["workflow_id"]
    nodes: list[dict] = [
        {
            "id": _f_node_id(wid, PN_MANUAL),
            "name": PN_MANUAL,
            "type": "n8n-nodes-base.manualTrigger",
            "typeVersion": 1,
            "position": [0, 0],
            "parameters": {},
        },
        _f_code(wid, "Plan manual", _process_plan_js("manual", "all"), [240, 0]),
    ]
    conns: dict = {}
    _p_conn(conns, PN_MANUAL, [[("Plan manual", 0)]])
    for k, st in enumerate(plan["stages"], 1):
        sched, pl = f"Schedule {st['stage']}", f"Plan {st['stage']}"
        nodes.append(
            {
                "id": _f_node_id(wid, sched),
                "name": sched,
                "type": "n8n-nodes-base.scheduleTrigger",
                "typeVersion": 1.2,
                "position": [0, 240 * k],
                "parameters": {"rule": {"interval": [{"field": "cronExpression", "expression": st["schedule"]}]}},
            }
        )
        nodes.append(_f_code(wid, pl, _process_plan_js("schedule", st["stage"]), [240, 240 * k]))
        _p_conn(conns, sched, [[(pl, 0)]])
    for pl in ["Plan manual"] + [f"Plan {st['stage']}" for st in plan["stages"]]:
        _p_conn(conns, pl, [[(PN_CTX, 0)]])
    nodes.append(_f_code(wid, PN_CTX, _process_context_js(plan), [480, 240]))
    stage_names = tuple(st["stage"] for st in plan["stages"]) + ("all",)
    nodes.append(_f_switch(wid, PN_ROUTE, "={{ $json.stage }}", stage_names, [720, 240]))
    _p_conn(conns, PN_CTX, [[(PN_ROUTE, 0)]])

    def entry(st: dict) -> list[tuple[str, int]]:
        return [(f"Gate {sid}", 0) for sid in st["entry"]]

    # Switch outputs in stage order, then 'all' (starts at the first stage), then the unused fallback.
    _p_conn(conns, PN_ROUTE, [entry(st) for st in plan["stages"]] + [entry(plan["stages"][0]), []])
    x0 = 960
    for k, st in enumerate(plan["stages"]):
        by_id = {s["id"]: s for s in st["steps"]}
        depth: dict[str, int] = {}
        rows: dict[int, int] = {}
        for s in st["steps"]:
            sid = s["id"]
            depth[sid] = 1 + max((depth[d] for d in s["depends_on"]), default=-1)
            row = rows.get(depth[sid], 0)
            rows[depth[sid]] = row + 1
            x, y = x0 + depth[sid] * 1200, 240 * (row + 3 * k)
            gate, ask, run, res = f"Gate {sid}", f"Run? {sid}", f"Run {sid}", f"Result {sid}"
            if len(s["depends_on"]) > 1:
                nodes.append(_p_merge(wid, f"Join {sid}", len(s["depends_on"]), [x - 240, y]))
                _p_conn(conns, f"Join {sid}", [[(gate, 0)]])
            nodes.append(_f_code(wid, gate, _process_gate_js(s), [x, y]))
            nodes.append(_f_if(wid, ask, "={{ $json.run === true }}", [x + 240, y]))
            nodes.append(_p_run(wid, run, [x + 480, y - 80]))
            nodes.append(_f_code(wid, res, _process_result_step_js(s), [x + 720, y]))
            _p_conn(conns, gate, [[(ask, 0)]])
            _p_conn(conns, ask, [[(run, 0)], [(res, 0)]])
            _p_conn(conns, run, [[(res, 0)]])
        done, stage_join = f"Done {st['stage']}", f"Join {st['stage']}"
        for s in st["steps"]:
            outs: list[tuple[str, int]] = []
            for dep_sid in st["dependents"][s["id"]]:
                dep = by_id[dep_sid]
                if len(dep["depends_on"]) > 1:
                    outs.append((f"Join {dep_sid}", dep["depends_on"].index(s["id"])))
                else:
                    outs.append((f"Gate {dep_sid}", 0))
            if s["id"] in st["terminals"]:
                if len(st["terminals"]) > 1:
                    outs.append((stage_join, st["terminals"].index(s["id"])))
                else:
                    outs.append((done, 0))
            _p_conn(conns, f"Result {s['id']}", [outs])
        xe = x0 + (max(depth.values()) + 1) * 1200
        if len(st["terminals"]) > 1:
            nodes.append(_p_merge(wid, stage_join, len(st["terminals"]), [xe, 240 * 3 * k]))
            _p_conn(conns, stage_join, [[(done, 0)]])
        nodes.append(_f_code(wid, done, _process_stage_done_js(st["stage"]), [xe + 240, 240 * 3 * k]))
        if k + 1 < len(plan["stages"]):
            nxt = plan["stages"][k + 1]
            then = f"Then {nxt['stage']}?"
            nodes.append(
                _f_if(wid, then, "={{ $('" + PN_CTX + "').first().json.stage === 'all' }}", [xe + 480, 240 * 3 * k])
            )
            _p_conn(conns, done, [[(then, 0)]])
            _p_conn(conns, then, [entry(nxt), [(PN_RESULT, 0)]])
            x0 = xe + 720
        else:
            _p_conn(conns, done, [[(PN_RESULT, 0)]])
            x0 = xe + 480
    nodes.append(_f_code(wid, PN_RESULT, _process_result_js(plan), [x0, 240]))
    nodes.append(_f_code(wid, PN_ASSERT, _process_assert_js(), [x0 + 240, 240]))
    _p_conn(conns, PN_RESULT, [[(PN_ASSERT, 0)]])
    wf = _fabric_doc(wid, PROCESS_KIND, nodes, conns, _fabric_settings(wid, PROCESS_EXECUTION_TIMEOUT_S))
    return wf


def process_workflow_plans() -> dict[str, dict]:
    """workflow id -> validated plan for every process in config/n8n_fabric_processes.json."""
    out = {}
    for pid, spec in load_process_specs().items():
        manifest = json.loads((ROOT / spec["manifest"]).read_text(encoding="utf-8"))
        out[spec["workflow_id"]] = process_plan(pid, spec, manifest)
    return out


def process_builders() -> dict:
    """workflow id -> zero-argument builder for every process in config/n8n_fabric_processes.json."""
    out = {}
    for pid, spec in load_process_specs().items():
        manifest = json.loads((ROOT / spec["manifest"]).read_text(encoding="utf-8"))
        out[spec["workflow_id"]] = lambda p=pid, s=spec, m=manifest: build_process(p, s, m)
    return out


def process_problems(wf: dict) -> list[str]:
    """Process-workflow invariants on top of validate_fabric_workflow: no HTTP node (every host call goes through Run
    Lane), every Execute Workflow node calls Run Lane by id and waits for it, and no trigger other than Manual and
    Schedule (no webhook, no Execute Workflow Trigger, no Error Trigger)."""
    problems = []
    for n in wf.get("nodes") or []:
        t = n.get("type")
        if t == "n8n-nodes-base.httpRequest":
            problems.append(f"process_http_node:{n.get('name')}")
        elif t == "n8n-nodes-base.executeWorkflow":
            p = n.get("parameters") or {}
            if (p.get("workflowId") or {}).get("value") != RUN_LANE_ID or not (p.get("options") or {}).get(
                "waitForSubWorkflow"
            ):
                problems.append(f"process_call_not_run_lane:{n.get('name')}")
        elif t in ("n8n-nodes-base.webhook", "n8n-nodes-base.executeWorkflowTrigger", "n8n-nodes-base.errorTrigger"):
            problems.append(f"process_trigger_refused:{n.get('name')}")
    return problems


FABRIC_BUILDERS = {
    RUN_LANE_ID: build_run_lane,
    FABRIC_ERROR_ID: build_fabric_error,
    FABRIC_PROBE_ID: build_fabric_probe,
    FABRIC_ERROR_PROBE_ID: build_fabric_error_probe,
}


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def graph_view(wf: dict) -> dict:
    """The behavioural graph: GRAPH_NODE_FIELDS of each node (absent/None/False-default dropped), connections, the
    GRAPH_SETTINGS_FIELDS of settings, id and name. Position, webhookId, node ids, meta and active are not graph."""
    nodes = []
    for n in wf.get("nodes") or []:
        view = {}
        for k in GRAPH_NODE_FIELDS:
            v = n.get(k)
            if v is None or (k == "disabled" and v is False):
                continue
            view[k] = v
        nodes.append(view)
    nodes.sort(key=lambda n: str(n.get("name")))
    settings = wf.get("settings") or {}
    return {
        "id": wf.get("id"),
        "name": wf.get("name"),
        "nodes": nodes,
        "connections": wf.get("connections") or {},
        "settings": {k: settings[k] for k in GRAPH_SETTINGS_FIELDS if k in settings},
    }


def graph_hash(wf: dict) -> str:
    return hashlib.sha256(_canon(graph_view(wf)).encode("utf-8")).hexdigest()


def fabric_policy() -> dict:
    """What a fabric workflow is allowed to be. Its sha256 is the POLICY hash the trusted deployer checks."""
    routes_path = ROOT / "config" / "n8n_comms_intent_routes.json"
    try:
        routes_sha = hashlib.sha256(routes_path.read_bytes()).hexdigest()
    except OSError:
        routes_sha = None
    return {
        "allowed_node_types": sorted(FABRIC_ALLOWED_NODE_TYPES),
        "forbidden_node_types": sorted(FABRIC_FORBIDDEN_NODE_TYPES),
        "node_package": FABRIC_NODE_PACKAGE,
        "required_settings": FABRIC_REQUIRED_SETTINGS,
        "error_workflow": FABRIC_ERROR_ID,
        "credential": {"name": CREDENTIAL_NAME, "types": sorted(FABRIC_CREDENTIAL_TYPES)},
        "relay_url": GENERIC_RELAY_URL,
        "relay_calls": FABRIC_RELAY_CALLS,
        "intent_routes_sha256": routes_sha,
        "run_lane": {
            "max_attempts": RUN_LANE_MAX_ATTEMPTS,
            "outcome_timeout_max_s": RUN_LANE_OUTCOME_TIMEOUT_MAX_S,
            "execution_timeout_s": RUN_LANE_EXECUTION_TIMEOUT_S,
            "terminal": list(RUN_LANE_TERMINAL),
        },
    }


def policy_hash() -> str:
    return hashlib.sha256(_canon(fabric_policy()).encode("utf-8")).hexdigest()


def validate_fabric_workflow(wf: dict, known_ids: set[str] | frozenset[str]) -> list[str]:
    """Problems that refuse a fabric workflow (generator invariant, CI and the trusted deployer). [] = fit."""
    problems: list[str] = []
    if wf.get("active") is not False:
        problems.append("active_not_false")
    for n in wf.get("nodes") or []:
        t = str(n.get("type"))
        if not t.startswith(FABRIC_NODE_PACKAGE):
            problems.append(f"node_package_refused:{t}")
        elif t in FABRIC_FORBIDDEN_NODE_TYPES:
            problems.append(f"node_forbidden:{t}")
        elif t not in FABRIC_ALLOWED_NODE_TYPES:
            problems.append(f"node_not_allowed:{t}")
        for ctype, cred in (n.get("credentials") or {}).items():
            if (
                ctype not in FABRIC_CREDENTIAL_TYPES
                or not isinstance(cred, dict)
                or cred.get("name") != CREDENTIAL_NAME
            ):
                problems.append(f"credential_refused:{n.get('name')}:{ctype}")
    settings = wf.get("settings") or {}
    ew = settings.get("errorWorkflow")
    if not ew:
        problems.append("error_workflow_missing")
    elif ew not in known_ids:
        problems.append(f"error_workflow_unknown:{ew}")
    for k, v in FABRIC_REQUIRED_SETTINGS.items():
        if settings.get(k) != v:
            problems.append(f"setting:{k}")
    if not isinstance(settings.get("executionTimeout"), int) or settings["executionTimeout"] < 1:
        problems.append("setting:executionTimeout")
    meta = wf.get("meta") or {}
    if meta.get("graph_sha256") != graph_hash(wf):
        problems.append("graph_hash_mismatch")
    return problems


def render_fabric() -> dict[str, str]:
    """file name -> text for the fabric workflows plus INDEX.json (the trusted-deployer manifest; byte-stable)."""
    procs = process_builders()
    wfs = [builder() for builder in FABRIC_BUILDERS.values()] + [builder() for builder in procs.values()]
    known = {wf["id"] for wf in wfs}
    files: dict[str, str] = {}
    rows = []
    for wf in wfs:
        problems = validate_fabric_workflow(wf, known)
        if wf["id"] in procs:
            problems += process_problems(wf)
        if problems:
            raise ValueError(f"fabric workflow {wf['id']} refused by its own generator: {problems}")
        text = _dump(wf)
        fname = f"{wf['id']}.json"
        files[fname] = text
        rows.append(
            {
                "id": wf["id"],
                "kind": wf["meta"]["kind"],
                "file": fname,
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "graph_sha256": wf["meta"]["graph_sha256"],
                "node_types": sorted({n["type"] for n in wf["nodes"]}),
                "error_workflow": wf["settings"]["errorWorkflow"],
                # A process workflow makes no relay call of its own (process_problems): Run Lane makes them.
                "relay_calls": FABRIC_RELAY_CALLS.get(wf["id"], []),
                "active": False,
            }
        )
    files["INDEX.json"] = _dump(
        {
            "schema": FABRIC_SCHEMA,
            "generator": FABRIC_GENERATOR,
            "authority": "READ_ONLY_ADVISORY",
            "policy": fabric_policy(),
            "policy_sha256": policy_hash(),
            "workflows": rows,
        }
    )
    return files


def verify_fabric(paths: list[Path], manifest_path: Path) -> dict:
    """Trusted-deployer check of workflow JSON (an n8n export or a staged import file) against the committed
    manifest: graph hash equal, policy hash equal to the generator's, and validate_fabric_workflow clean. Exports
    may hold one workflow or a list."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {row["id"]: row for row in manifest.get("workflows") or []}
    known = set(expected)
    out: dict = {
        "policy_sha256_manifest": manifest.get("policy_sha256"),
        "policy_sha256_code": policy_hash(),
        "workflows": [],
        "ok": True,
    }
    if manifest.get("policy_sha256") != policy_hash():
        out["ok"] = False
        out["policy_mismatch"] = True
    for p in paths:
        doc = json.loads(Path(p).read_text(encoding="utf-8"))
        for wf in doc if isinstance(doc, list) else [doc]:
            wid = str(wf.get("id"))
            row = expected.get(wid)
            got = graph_hash(wf)
            # An export carries its own meta (or none): re-stamp so validate checks the graph, not the stamp.
            stamped = dict(wf)
            stamped["meta"] = dict(wf.get("meta") or {}, graph_sha256=got)
            problems = validate_fabric_workflow(stamped, known)
            if row is not None and row.get("kind") == PROCESS_KIND:
                problems += process_problems(wf)
            # A live export is active once published; activation state is the grant's business, not the graph's.
            problems = [x for x in problems if x != "active_not_false"]
            if row is None:
                problems.append("not_in_manifest")
            elif row["graph_sha256"] != got:
                problems.append("graph_hash_mismatch")
            extra = sorted(set((wf.get("settings") or {})) - set(GRAPH_SETTINGS_FIELDS))
            entry = {"id": wid, "file": str(p), "graph_sha256": got, "problems": problems, "extra_settings": extra}
            out["workflows"].append(entry)
            if problems:
                out["ok"] = False
    return out


def fabric_main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="n8n_workflow_templates.py build-fabric", description="n8n fabric primitives")
    ap.add_argument("--out", default=str(FABRIC_DEFAULT_OUT))
    ap.add_argument("--check", action="store_true", help="fail if regenerating would change any byte")
    ap.add_argument("--verify", nargs="+", default=None, help="workflow JSON files to verify against the manifest")
    a = ap.parse_args(argv)
    out = Path(a.out)
    if a.verify:
        result = verify_fabric([Path(p) for p in a.verify], out / "INDEX.json")
        print(json.dumps(result, sort_keys=True))
        return 0 if result["ok"] else 1
    files = render_fabric()
    if a.check:
        diffs = []
        for rel, text in sorted(files.items()):
            path = out / rel
            if not path.exists():
                diffs.append(f"missing: {rel}")
            elif path.read_bytes() != text.encode("utf-8"):
                diffs.append(f"stale: {rel}")
        print(json.dumps({"mode": "check-fabric", "files": len(files), "diffs": diffs, "out": str(out)}))
        return 1 if diffs else 0
    changed = []
    out.mkdir(parents=True, exist_ok=True)
    for rel, text in sorted(files.items()):
        path = out / rel
        data = text.encode("utf-8")
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)
            changed.append(rel)
    print(json.dumps({"mode": "write-fabric", "files": len(files), "changed": changed, "out": str(out)}))
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "build-generic":
        return generic_main(list(argv[1:]))
    if argv and argv[0] == "build-fabric":
        return fabric_main(list(argv[1:]))
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
