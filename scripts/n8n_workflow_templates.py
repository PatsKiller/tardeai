#!/usr/bin/env python3
"""n8n_workflow_templates.py — generate the scheduler-of-record workflows for the N1–N6 lanes.

One template, two workflows per lane:

    <lane_id>-shadow   mode=dry_run   (imported inactive; activated first, cron line still live)
    <lane_id>          mode=live      (imported inactive; activated at canary, cron retired at cutover)

Node chain (fixed; a test pins the node-type set):

    Schedule Trigger  →  Set "Relay constants"  →  HTTP Request v4.2  →  Code "Assert REQUESTED"
    (cron expression,     (TRADEAI_N8N_RUN_URL,     POST {url}/run,        status 200 and
     America/New_York)     placeholder host)        Header Auth credential  state REQUESTED
                                                    `tradeai-run-relay`,    or duplicate:true,
                                                    10 s, fullResponse)     else throw(lane id)

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
TRANCHES = ("N1", "N2", "N3", "N4", "N5", "N6")
# Tranches committed under generated/ directly; the rest land under generated/pending/.
COMMITTED_TRANCHES = ("N1",)

# The only node types a generated workflow may contain. tests pin this set.
ALLOWED_NODE_TYPES = frozenset(
    {
        "n8n-nodes-base.scheduleTrigger",
        "n8n-nodes-base.set",
        "n8n-nodes-base.httpRequest",
        "n8n-nodes-base.code",
    }
)

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
    },
    {
        "lane_id": "after-close-pipeline-planning",
        "tranche": "N2",
        "cron": ["35 17 * * 1-5"],
        "fidelity": "EXACT",
        "source": "crontab: 35 17 * * 1-5 run_after_close_pipeline.sh --stage planning (registry kind cron)",
        "pipeline": "after_close",
        "stage_order": 3,
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


def build_workflow(lane: dict, mode: str, relay_url: str = RELAY_URL_PLACEHOLDER) -> dict:
    """One n8n workflow (import shape for n8n 2.43.0) for a lane in a run mode."""
    assert mode in ("dry_run", "live"), mode
    lane_id = lane["lane_id"]
    name = f"{lane_id}-shadow" if mode == "dry_run" else lane_id
    body = {"lane_id": lane_id, "mode": mode, "requested_by": name}
    n_sched, n_set, n_http, n_code = "Schedule", "Relay constants", "POST relay /run", "Assert REQUESTED"
    nodes = [
        {
            "id": _node_id(name, "schedule"),
            "name": n_sched,
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.2,
            "position": [240, 300],
            "parameters": {
                "rule": {"interval": [{"field": "cronExpression", "expression": c} for c in lane["cron"]]},
            },
        },
        {
            "id": _node_id(name, "set"),
            "name": n_set,
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
        },
        {
            "id": _node_id(name, "http"),
            "name": n_http,
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [720, 300],
            "onError": "stopWorkflow",
            "credentials": {"httpHeaderAuth": {"id": CREDENTIAL_NAME, "name": CREDENTIAL_NAME}},
            "parameters": {
                "method": "POST",
                "url": "={{ $json." + RELAY_URL_VAR + " }}/run",
                "authentication": "genericCredentialType",
                "genericAuthType": "httpHeaderAuth",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": json.dumps(body, sort_keys=True),
                "options": {
                    "timeout": HTTP_TIMEOUT_MS,
                    # neverError: the Code node is the single assertion point, so a 4xx/5xx
                    # fails the workflow with the lane id in the message, not a generic HTTP error.
                    "response": {"response": {"fullResponse": True, "neverError": True}},
                },
            },
        },
        {
            "id": _node_id(name, "code"),
            "name": n_code,
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [960, 300],
            "onError": "stopWorkflow",
            "parameters": {"language": "javaScript", "mode": "runOnceForAllItems", "jsCode": _assert_js(lane_id, mode)},
        },
    ]
    connections = {
        n_sched: {"main": [[{"node": n_set, "type": "main", "index": 0}]]},
        n_set: {"main": [[{"node": n_http, "type": "main", "index": 0}]]},
        n_http: {"main": [[{"node": n_code, "type": "main", "index": 0}]]},
    }
    return {
        "id": _wf_id(name),
        "name": name,
        "active": False,
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1", "timezone": TIMEZONE, "saveManualExecutions": True},
        "meta": {
            "generator": "scripts/n8n_workflow_templates.py",
            "lane_id": lane_id,
            "mode": mode,
            "tranche": lane["tranche"],
            "schedule_source": lane["source"],
            "schedule_fidelity": lane["fidelity"],
        },
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
        for key in ("note", "pipeline", "stage_order"):
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
