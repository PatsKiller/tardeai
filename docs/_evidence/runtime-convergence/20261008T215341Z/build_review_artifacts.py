#!/usr/bin/env python3
"""Manual reviewer: derive report matrices from saved redacted observations only."""

import json
from collections import Counter
from pathlib import Path

P = Path(__file__).resolve().parent
ROOT = P.parents[3]


def read(n):
    return json.loads((P / n).read_text())


def write(n, r):
    (P / n).write_text(json.dumps(r, indent=2, default=str) + "\n")


def md(n, s):
    (P / n).write_text(s.strip() + "\n")


registry = json.loads((ROOT / "config/lane_registry.json").read_text())
inv = read("01-scheduler-lane-inventory.json")
projection = read("14-scheduler-operations-snapshot.json")
n8n = read("06-n8n-db.json")
data = n8n["results"]
runs = read("08-host-run-ledger.json")
active = Counter(x["scheduler"]["kind"] for x in registry["lanes"] if x["state"] == "ACTIVE")
unit_census = Counter(
    (v["properties"].get("ActiveState"), v["properties"].get("UnitFileState"))
    for v in read("04-systemd-units.json")["units"].values()
)
workflows = data["workflow_metadata"]["data"]
nodes = {r["workflow_id"]: r["nodes"] for r in data["workflow_nodes"]["data"]}
n1 = []
for w in workflows:
    if not w["active"]:
        continue
    wr = [r for r in runs["runs"] if str(w["id"]) in r.get("requested_by", "")]
    last = sorted(wr, key=lambda r: r["requested_at"], reverse=True)[:5]
    lane = (
        last[0]["lane_id"]
        if last
        else next((x["lane_id"] for x in registry["lanes"] if x["lane_id"] in w["name"].lower()), None)
    )
    receipts = [
        {
            "run_id": r["run_id"],
            "mode": r["mode"],
            "requested_at": r["requested_at"],
            "state": r["state"],
            "exit_code": r["exit_code"],
            "receipt": r["receipt"],
        }
        for r in last
    ]
    n1.append(
        {
            "workflow_id": w["id"],
            "name": w["name"],
            "active": True,
            "mode": "shadow" if "shadow" in w["name"].lower() else "live",
            "schedule": [n["schedule"] for n in nodes[w["id"]] if n.get("schedule")],
            "relay_credential_attached": any("httpHeaderAuth" in (n.get("credentials") or {}) for n in nodes[w["id"]]),
            "last_5_retained_executions": [e for e in data["last_executions"]["data"] if e["workflowId"] == w["id"]],
            "last_5_host_receipts": receipts,
            "lane_id": lane,
            "shadow_acceptance": "BLOCKED",
            "cutover_readiness": "NO_GO",
            "reason": "Current branch fixes are not deployed. Relay/executor run older releases. Retention does not preserve complete n8n green execution history; weekly workflows have no observed host receipts. Two natural fires after all fixes and live canary/rollback proof are not established.",
            "evidence_class": "OBSERVED_N8N",
            "receipt_evidence_class": "OBSERVED_DB",
        }
    )
write("09-10-n1-acceptance-matrix.json", {"as_of": n8n["as_of"], "rows": n1, "manual_fires_performed": False})
write(
    "13-registry-proof-gaps.json",
    {
        "schema": "RegistryProofGaps@v1",
        "as_of": inv["as_of"],
        "unregistered_rows": [r["lane_id"] for r in inv["rows"] if not r["declared_in_lane_registry"]],
        "active_gaps": [
            {
                "lane_id": r["lane_id"],
                "missing": [
                    k
                    for k in ("owner", "business_domain", "receipt", "consumer", "writer_tables_files")
                    if r[k] is None
                ],
                "health": r["health_verdict"],
            }
            for r in inv["rows"]
            if r["declared_state"] == "ACTIVE"
        ],
        "note": "Unknown owners/consumers are not invented. Existing registry intent is retained except operator-stated Ollama retirement. Missing rows need contract/owner decisions before authoritative scheduler cutover.",
    },
)
queries = read("17-19-database-load.json")["queries"]
contracts = {
    "watchlist_agent_jobs": (
        "scripts/lib/agent_job_queue.py",
        "scripts/process_watchlist_agent_jobs.py",
        "SELECT queued then UPDATE processing; external family locking required; not atomic SKIP LOCKED",
        "20m source reaper; separate reset_stuck_agent_jobs.py 30m",
        "bounded model governance; retry queue exists",
    ),
    "deep_overnight_llm_queue": (
        "scripts/build_deep_overnight_llm_queue.py",
        "scripts/run_deep_overnight_llm_queue.py",
        "SELECT pending then UPDATE by id; needs scheduler/lock exclusivity",
        "30m source running reaper",
        "pending backlog retained; do not replay under this audit",
    ),
    "communication_outbox": (
        "scripts/lib/comms",
        "host communication dispatcher",
        "delivery claim contract not measured in this audit",
        "NOT_MEASURED",
        "UNKNOWN sends are not proven SENT; no live sends performed",
    ),
    "agent_event_queue": (
        "CIO producers",
        "CIO event/reactive workers",
        "NOT_MEASURED",
        "NOT_MEASURED",
        "stale processing rows require exact producer/consumer attribution",
    ),
}
queues = []
for key, value in queries.items():
    if not key.startswith("queue:"):
        continue
    table = key[6:]
    c = contracts.get(
        table.split(".")[-1], ("NOT_MEASURED", "NOT_MEASURED", "NOT_MEASURED", "NOT_MEASURED", "NOT_MEASURED")
    )
    queues.append(
        {
            "table": table,
            "observed_states": value.get("rows"),
            "query": value.get("query"),
            "producer": c[0],
            "consumer": c[1],
            "claim": c[2],
            "reclaimer": c[3],
            "retry": c[4],
            "dead_letter": None,
            "parallelism": None,
            "lock": None,
            "scheduler": None,
            "output_receipt": None,
            "evidence_class": "OBSERVED_DB",
            "contract_evidence_class": "SOURCE_ONLY" if table.split(".")[-1] in contracts else "NOT_MEASURED",
            "growth_rate": "NOT_MEASURED: one census cannot establish inflow/outflow slope",
        }
    )
queues.extend(
    [
        {
            "table": "n8n runs SQLite",
            "producer": "coordination gateway",
            "consumer": "n8n_run_executor.py",
            "observed_nonterminal": runs["queues"],
            "claim": "BEGIN IMMEDIATE; conditional REQUESTED -> RUNNING",
            "reclaimer": "crash recovery contract requires observation; source tests cover durable claiming",
            "output_receipt": "RunReceipt@v1",
            "evidence_class": "OBSERVED_DB",
        },
        {
            "table": "Hermes research JSONL",
            "producer": "scripts/lib/hermes_research_queue.py",
            "consumer": "scripts/hermes_coordinator.py",
            "claim": "fingerprint dedupe source; current worker lease proof not measured",
            "reclaimer": "NOT_MEASURED",
            "evidence_class": "SOURCE_ONLY",
        },
        {
            "table": "CIO handoff JSONL",
            "producer": "scripts/lib/cio_agent_handoff_queue.py",
            "consumer": "CIO worker",
            "claim": "hash-chain/flock/claim token/lease source",
            "retry": "1/5/15/60m source backoff",
            "queue_length": None,
            "evidence_class": "SOURCE_ONLY",
        },
        {
            "table": "Hermes challenge JSONL",
            "producer": "scripts/lib/cio_hermes_challenge_queue.py",
            "consumer": "Hermes challenger",
            "claim": "claim TTL with flock/fsync event log source; race across read/append requires separate concurrency review",
            "queue_length": None,
            "evidence_class": "SOURCE_ONLY",
        },
        {
            "table": "approval queue",
            "producer": "proposal lifecycle",
            "consumer": "operator authority",
            "claim": "never auto approve or drain",
            "queue_length": None,
            "evidence_class": "NOT_MEASURED",
        },
        {
            "table": "CIO wake",
            "producer": "persistent_agent_wake",
            "consumer": "CIO event loop",
            "claim": "live backlog/lease throughput not measured",
            "queue_length": None,
            "evidence_class": "NOT_MEASURED",
        },
    ]
)
write(
    "17-queue-worker-matrix.json",
    {"as_of": read("17-19-database-load.json")["as_of"], "rows": queues, "live_mutations_performed": False},
)
traces = read("04-dev-tree-leakage-matrix.json")["traces"]
reviewed = []
for t in traces:
    if t["verdict"] != "DEV_TREE_SOURCE_HOP":
        continue
    u = t["unit"]
    if u.startswith("portfolio-") or u.startswith("tradeai-portfolio-"):
        finding = "RELEASE_CONTROLLER_TO_DEV_LAUNCHER"
        action = "NEEDS_DESIGN: launcher code-root fix separate from state/send semantics; inspect six linux_launchers listed in traces"
    elif u in (
        "tradeai-governance-facts.service",
        "tradeai-maturity-board.service",
        "tradeai-a1a-check.service",
    ) or "run_scheduled_" in str(t["trace"]):
        finding = "DEV_PROJ_ASSIGNMENT"
        action = "FIX_NOW_SOURCE: three scheduled governance wrappers derive release root from BASH_SOURCE"
    elif u == "tradeai-continuous.service":
        finding = "SHARED_VENV_REFERENCE"
        action = "RETAIN_WITH_REASON: interpreter environment is shared; this literal alone is not a dev-tree code hop"
    elif "tradeai-flash-" in u:
        finding = "DEV_WORKTREE_UNIT_AND_STATE_REFERENCE"
        action = "NEEDS_OPERATOR_GRANT / NEEDS_DESIGN: unit definitions and state root require explicit rebind; no live child PID proof"
    elif "maintenance-" in u:
        finding = "RETENTION_CHILD_PATH_CANDIDATE"
        action = "NEEDS_DESIGN: docs_retention child literal plus shared interpreter references; do not rewrite destructive retention blindly"
    else:
        finding = "DEV_STATE_READ_OR_METADATA_CANDIDATE"
        action = "NEEDS_DESIGN: classify read path vs executable; literal regex match does not prove execution"
    reviewed.append(
        {
            "unit": u,
            "candidate": finding,
            "source_trace": t["trace"],
            "actual_process_cwd": t["actual_process_cwd"],
            "action": action,
            "evidence_class": "SOURCE_ONLY",
            "runtime_execution_proof": "NOT_MEASURED",
        }
    )
write(
    "04-reviewed-path-findings.json",
    {
        "rows": reviewed,
        "note": "Raw trace is conservative literal traversal, with candidates and shared-venv false positives. Do not equate its 24 candidates with 24 observed dev-tree executions.",
    },
)
md(
    "11-n2-dependency-design.md",
    r"""
# N2 receipt dependency review — source only, NO_GO

Observed GitHub PR #1537 head `66adc9285a581703d04c863b90ea36ee0964810f` is reviewed, not merged or deployed. [PR](https://github.com/PatsKiller/tardeai/pull/1537). The exact JS extracted from the workflow generator accepted a shadow predecessor for live, `RUN_DONE` with exit 1, and a future same-day finish. Failed and missing predecessors were denied. Evidence: `11-dag-negative-review.json` (TEST_ONLY); `git show origin/audit-pr-1537:scripts/generate_n8n_dag_workflows.py` (SOURCE_ONLY). Relay metadata drops receipt/exit from the gating response. The latest row of any mode can mask the correct predecessor.

Use a versioned dependency contract carrying predecessor lane, required mode, business timezone/calendar, a declared business-date rule and maximum age. Capture the original scheduled event time and business date once. Retries must not recompute the business day from their current clock. Select the predecessor receipt for that business date and mode; validate matching run/lane identity, durable terminal `RUN_DONE`, exit 0, finished <= request time, no timed out/lock skipped flags and the required output proof. A predecessor's mere scheduler fire or exit does not satisfy the dependency.

For overnight stages, a generic session rule maps the scheduled event into its prior trading-session business date. Derive it from a governed calendar/timezone, including holidays. Avoid lane-specific date strings. DST fall-back occurrences have distinct scheduled event IDs but one business-process idempotency key; spring-forward absence becomes a missed trigger, not a fabricated receipt. Receipt selection must not accept a future row or another session's success. Missing, failed, skipped-lock and stale predecessors each return typed WAIT/BLOCKED reasons. Persist bounded retry attempt/deadline state; a Wait node's current item count is not a durable attempt counter.

Required negative matrix before N2: same-day shadow/live separation; overnight prior-session matching; holiday/weekend and both DST transitions; failed/timeout/skipped-lock; absent/malformed receipt; stale/future receipt; wrong lane/run ID; duplicate trigger/retry; late completion after deadline; resumed retry crossing midnight; dual requester idempotency. Test the actual generated Code and relay response together, then fixture a full schedule-event -> host request -> receipt chain. N1 stability and two natural shadow fires after exact-CURRENT fixes are prerequisites. No N2 cutover is authorized here.
""",
)
md(
    "12-consolidation-review.md",
    r"""
# Cron consolidation re-measurement

Evidence: `03-cron-remeasurement.json` (OBSERVED_HOST expressions, SOURCE_ONLY fire estimate); `02-duplicates-conflicts.json`; `03-runtime-distributions.json`; current `docs/implementation/n8n-parallel/13-cron-consolidation-20261007.md` (SOURCE_ONLY). The 487/450 historical counts are STALE_HISTORICAL; the observed count is 441. Existing portfolio/platform ordered pipelines are already declared and observed as timers; do not subtract historical proposed savings from today's count.

| Candidate | Before | Proposed after | Isolation/window/runtime | Rollback / classification |
| --- | --- | --- | --- | --- |
| Same quote lock: `45 7,10,12,13,16 * * 1-5` and `*/5 9-15 * * 1-5` | 5 + 84 = 89 weekday schedule fires | NOT_MEASURED until flags/output contract establish one process or two distinct consumers | Same-minute collisions at 10:45/12:45/13:45; lock skips are lost work unless explicitly contractual. Keep step outputs and failure receipts separate. Chain maximum unknown. | Exact affected lines only, retain old line comments and registry rows; NEEDS_DESIGN then operator cron grant |
| `mkt_quotes_intraday` cadence vs observed runtime | Current `*/15 9-16 * * 1-5`: 32 weekday fires (160 over five weekdays); observed p95 2652s and 18 skips / 31 requests in 24h component telemetry | No cadence installed; propose interval >= observed p95 plus margin only after freshness SLA/market-window review | Current p95 ~44.2m; changing cadence changes freshness. Full process p95 and sample coverage need validation. Maximum timeout remains lane contract. | Per-line rollback; NEEDS_DESIGN; no automatic missed-work replay |
| Active-trader session reviews 12:05 and 16:10 weekdays | 2 weekday fires, one exact command | 2 weekday fires retained | Distinct session windows, no scheduled collision; shared lock is not the justification. | RETAIN_WITH_REASON |
| Broker/ATM, watchdogs, DB watchdogs, reapers, cleanup, paper/live | Current observed schedules | Unchanged | Independent recovery/failure isolation retained, including observed ATM skip rate requiring investigation. | RETAIN_WITH_REASON, no chain consolidation |
| Existing nightly/weekly/monthly maintenance pipeline | Current observed timers, not historical 11+3+2 cron lines | Unchanged pending individual receipt coverage | Each step must retain lock, timeout, cost cap, gate, receipt and error status. Inspect destructive retention and backup steps individually. Maximum chain runtime not measured. | Existing timer rollback per unit; no wholesale crontab restore |

No new consolidation is installed. Before any proposal is approved, fill its exact before/after fires per local calendar day, maximum chain runtime from step timeouts and runtime baseline, schedule window, consumer freshness budget and independent recovery path. Unknown values prevent GO; minimum line count is not an objective.
""",
)
md(
    "18-19-model-and-vector-review.md",
    r"""
# Model routing and embedding load — separate governed decisions

The operator states Ollama is retired. OBSERVED_HOST `04-ollama-retired-host.txt` shows the system service enabled and running. The source registry now records RETIRED intent and Scheduler Operations reports the mismatch. No service has been stopped or enabled by this task. Residual embedding paths such as `scripts/hermes_embedding_worker.py` and coordinator steps still need a retirement/replacement contract. Chat OAuth/DeepSeek completions cannot substitute for embedding vectors.

The note “uae oauth th deepseek” is provisionally interpreted as OAuth first, governed DeepSeek fallback. A clarification was requested; no exact process-family response arrived during this audit. `config/llm_process_registry.json` already distinguishes OAuth, DeepSeek-only, author/critic and no-fallback processes. Reordering them globally would violate those contracts and existing cost/provenance rules. Prepare a process-scoped change separately after the intended scope is confirmed, retaining registry caps, off-peak policy, author/critic separation and truthful provider attribution. Routing and secret access stay on the host. n8n names a governed host process, never a provider/model or key.

SOURCE_ONLY current `config/llm_model_registry.json` binds `deepseek_pro` to `deepseek-flash` with display name “DeepSeek V4.1 Flash (Pro tier retired)”; `llm_model_registry.py` rejects obsolete exact model IDs. This is an explicitly labelled retired tier alias, not proof of a current paid Pro model. No live provider probe or paid model call was made. Live identity/routing is NOT_MEASURED beyond source and existing receipts; no key migration.

OBSERVED_DB `17-19-database-load.json`: TradeAI Postgres 17.11, ~24.69GB database; pgvector 0.8.6 installed. `content_embeddings` contains 1,322,836 rows, 12,370,075,648 total bytes and 17,242 writes in the preceding 24h. Its embedding column is JSONB; it has no native vector column or vector index. A distinct `intelligence.embedding.vec` vector column exists. Source reader paths and population/quality between those stores require a complete semantic census. The measured newest-200 candidate query is a single EXPLAIN ANALYZE sample, not retrieval p95.

A separate migration recommendation: inventory embedding model/dimensions and reader compatibility; choose a replacement embedding authority for retired Ollama; measure vector population/NULL/invalid fractions without returning raw vectors; shadow-query a sample in an isolated schema; estimate headroom for vector backfill and HNSW/IVFFlat build; compare quality and p50/p95 over a representative workload; only then request exact-SHA/schema/volume/backfill operator approval. Preserve JSONB until reader parity and rollback are proven. Do not add a million-row DB migration to scheduler remediation. Existing `15-pgvector-migration-decision-20261008.md` is source guidance, not live migration proof.
""",
)
md(
    "20-operator-change-packet.md",
    r"""
# Operator-only runtime packet — prepared, NOT APPLIED

Read `AGENTS.md` §9.3: “Installing, editing or removing a scheduler entry is operator-only. Propose.” §17 and §22 require deployment authorization tied to exact SHA. This task explicitly forbids deployment/cutover without a separate grant. Source commits and PR approval do not activate any of the commands below. Re-measure CURRENT, service PIDs, file hashes and container digest at grant time. Grants must name exact scope, host, SHA and expiry; separate grants for units, cron, compose/security and deployment. No broker/2FA/send/risk-policy authority is included.

## A. Missing n8n unit definitions and old execution roots — P1

Observed relay/executor have LoadState=not-found and point to retained older code while installed symlinks point to a release removed by retention. Gateway is CURRENT. Source deploy now includes all three processes and fails if restart/root verification fails. Source relay/executor unit comments prescribe stable regular files.

Proposed unit-only grant, after the approved exact-main release exists: validate its `GIT_SHA` and both unit contents; archive existing symlink paths with `cp -a` in a private operator recovery directory; replace just `~/.config/systemd/user/tradeai-n8n-run-relay.service` and `tradeai-n8n-run-executor.service` with regular copies of the approved release's corresponding `config/systemd/user/` files, mode 0644; `systemctl --user daemon-reload`; `systemctl --user restart tradeai-n8n-run-relay.service tradeai-n8n-run-executor.service`. Verify each `LoadState=loaded`, nonempty FragmentPath, Restart=on-failure, configured cgroup bounds, MainPID cwd exact approved release and loopback/bridge binds. Verify gateway independently. No workflow/cron changes in this grant.

Concrete reviewed command structure, variables deliberately supplied by the operator's grant rather than inferred:

```bash
# Operator runs only after approval. Validate approved_release SHA before this block.
# approved_release must be the immutable deployed main release, not this worktree.
for unit in tradeai-n8n-run-relay.service tradeai-n8n-run-executor.service; do
  cp -a "$HOME/.config/systemd/user/$unit" "$approved_recovery_dir/$unit"
  unlink "$HOME/.config/systemd/user/$unit" # only if it is the measured dangling symlink
  install -m 0644 "$approved_release/config/systemd/user/$unit" "$HOME/.config/systemd/user/$unit"
done
systemctl --user daemon-reload
systemctl --user restart tradeai-n8n-run-relay.service tradeai-n8n-run-executor.service
systemctl --user show tradeai-n8n-run-relay.service tradeai-n8n-run-executor.service \
  --property=LoadState,FragmentPath,ActiveState,MainPID,Restart,MemoryMax,CPUQuotaPerSecUSec
```

Rollback must restore a valid previously pinned release's regular unit contents and executor root, reload/restart and verify receipts. Restoring a dangling symlink is not recovery. Record queued run IDs before restart; verify no double claim/side effect. Do not dump Environment values. Exact deployment grant remains separate.

## B. Ollama retirement mismatch — P1

Operator intent is RETIRED; measured `ollama.service` is enabled/running. First classify residual embedding consumers and choose their retired/paused/replacement states. Proposed explicit system-service grant: `sudo systemctl disable --now ollama.service`; verify `systemctl show ollama.service --property=ActiveState,UnitFileState,MainPID`; verify no Ollama listener/consumer retry storm. Do not auto-enable during rollback: retirement remains authoritative, and recovery/replacement needs an explicit operator decision. No chat model or embedding key is moved to n8n.

## C. n8n security/recovery — P1/P2

Owner MFA=false and n8n DB role is superuser. The owner must enable MFA and escrow recovery codes manually; this agent does not mutate 2FA. Preserve the existing encryption key; verify an operator-managed escrow/recovery procedure without printing or rotating it. Backup dump alone cannot recover encrypted credentials without that key.

Use an isolated Postgres 17 target/volume and a non-superuser application role; dump from current 16, restore privately, correct application object ownership/grants, validate workflow metadata/credentials decryptability, read-only security audit and relay auth. Do not grant CREATEDB/CREATEROLE/REPLICATION/BYPASSRLS. Prove rollback to untouched source volume and container digest, then request a separate compose cutover grant. Never edit the existing role blindly during active executions.

Current UI is loopback-only. Current TCP samples reach bridge relay 18092 and fail on sampled TradeAI/DOF/DB/gateway/Ollama ports. Firewall rule inspection is BLOCKED by sudo authorization, so request read-only privileged rules first. Review exact current Docker network/subnet/rule IDs before a scoped firewall grant; allow n8n subnet only relay host ingress plus its own DB network requirement. Rollback only the rules installed by that packet, never a global firewall reset.

Set `N8N_PUBLIC_API_DISABLED=true` in the measured compose service if no operator consumer requires it (0 API keys observed, audit says enabled). Preserve loopback publishing, environment blocking, node excludes and disabled community packages. Add an HTTP healthcheck using the version-supported health endpoint; independently preserve watchdog/backup/recovery paths. Success payload retention remains none; propose minimal status+execution-id acceptance observations instead of saving payloads. Keep errors bounded and prune 168h. Set explicit log/metrics/runner settings only after reviewing actual requirements.

Nightly backup and weekly restore drill have observed receipts. Add a read-only security-audit schedule only under a scheduler grant with a lane row, bounded timeout, redacted artifact, consumer and failure receipt. Do not enable Redis/queue mode: measured load provides no demonstrated throughput need.

## D. Scheduler/registry remediation — P1/P2

395 observed entries are unmatched by the source registry's exact mapping. This count includes wrappers/stages and enabled/disabled OpenClaw/workflows; it is not 395 distinct business processes. Review `13-registry-proof-gaps.json` and exact observations. Resolve owners, domain, consumer, receipts, output freshness and allowed exceptions before installing rows or schedules. Old n8n monitor intent ACTIVE conflicts with observed workflow inactive; explicit NO_SIGNAL reason is source-only, no activation is proposed.

For the quote-lock same-minute collision, obtain distinct process/consumer contracts before selecting one scheduler; for runtime/cadence mismatches, derive SLA and exact proposed expression from baseline. Submit one per-line packet with before/after fires, receipts, effective completion target, registry change and exact rollback. Retain independent financial/safety/watchdog/reaper lanes.

## E. N1 acceptance and cutover — NO_GO

After exact-main approved deployment and stable unit recovery, require two natural shadow fires per lane after all fixes. Record n8n execution state/id, accepted unique run_id, durable REQUESTED/claim/DONE exit0, original lock, before/after dry-run output semantics, correct SHA, no traceback/dropped request/unexpected skip. Keep legacy schedule during live canary and prove output/rollback/schedule fidelity. Weekly manual canary may be labelled MANUAL_CANARY only if the policy permits it; it never satisfies a NATURAL shadow requirement. No manual firing was performed here. Current lane matrix is uniformly NO_GO. N2 waits for N1 stability.
""",
)
cron = read("03-cron-remeasurement.json")
db = read("17-19-database-load.json")
oc = read("05-openclaw.json")
report = f"""
# TradeAI runtime convergence due diligence — 2026-10-08

Source audit and additive implementation are ready for review. Production convergence and full platform source acceptance are BLOCKED by incomplete registry/process contracts and natural acceptance proof. No deploy, scheduler installation, workflow activation, cutover, broker/order/stop/risk/send/2FA mutation or policy ratification was performed. Ollama retirement is recorded as operator intent; its running system service is drift.

Evidence is a bounded observation window, not permanently current. Each JSON includes its timestamp/command/query. `00-current-baseline.md` is the Phase 0 artifact; subsequent re-measurements are explicitly later. Schemas distinguish OBSERVED_CURRENT, OBSERVED_HOST, OBSERVED_N8N, OBSERVED_DB, OBSERVED_GITHUB, SOURCE_ONLY, TEST_ONLY, STALE_HISTORICAL, NOT_MEASURED and BLOCKED. Inventory nulls are unknown, not zeros or proof. No secret values are included.

## 1. Exact source/main/CURRENT identity

At baseline/re-measurement, origin/main, initial HEAD and merge-base were `eec946b2cebaa1378dab285c506c789f6dff1fb4`. CURRENT is `/home/johnclaw/trade-ai-releases/portfolio-server/eec946b2c-main-exact-phase2-20261008-165420`, same source SHA. Portfolio-server PID 302872 cwd is that release. Served Command Center SHA is the same, built_at `2026-10-08T20:55:11.633Z`. `/api/health` returned HTTP 200/ok; this is API liveness, not broker or database acceptance. Evidence `00-identity.json`, `00-host.json`; command `python3 collect_baseline.py`. Worktree is `codex/runtime-n8n-convergence-20261008`, isolated from the initially clean primary checkout. Final PR head/source identity is reported separately; it is not deployed CURRENT.

The current AGENTS §23 heading/version history says ACTIVE/ratified while its body still says PROPOSED. This textual contradiction is SOURCE_ONLY and has not been automatically ratified or rewritten. The explicit restrictions and operator-only scheduler/deploy boundaries govern this work.

## 2. Scheduler census

`01-scheduler-lane-inventory.json` contains **{len(inv["rows"])} normalized rows**, including declared lanes and unmatched observations. Observed cron, user/system units, n8n and OpenClaw metadata are combined with registry intent. Event/CIO/Hermes/queue/polling/browser child execution and durable output coverage are incomplete and are explicitly NOT_MEASURED. The inventory's row count is not a business-process count. Command `scripts/report_scheduler_inventory.py --evidence docs/_evidence/runtime-convergence/20261008T215341Z`. Every requested field exists, unknown values stay null; writer/cost/send/broker flags inferred from an allowlist are SOURCE_ONLY, not live authority proof. No ACTIVE lane has a fully established scheduler -> executor -> receipt -> output -> consumer chain in this combined saved snapshot; API-only health is not substituted.

## 3. Active lanes by scheduler

Source registry has {len(registry["lanes"])} lanes, **{sum(active.values())} ACTIVE**: {dict(active)}. These are intent counts (SOURCE_ONLY). OBSERVED activation and drift are separate per-row fields. Source changed two no-signal monitor reasons and added the operator-retired system Ollama row; no host lane was activated. `13-registry-proof-gaps.json` lists missing contracts. Unmatched observations: **{len([r for r in inv["rows"] if not r["declared_in_lane_registry"]])}**, often wrappers/stages; do not create invented owners or declare them healthy.

## 4. Cron count and fire volume

OBSERVED_HOST: {cron["counts"]}. Next seven local calendar days Oct 9–15 produce a SOURCE_ONLY estimate of **{cron["estimated_fires_7d"]} schedule fires**, {cron["estimated_weekday_fires_5d"]} across five weekdays and {cron["estimated_weekend_fires_2d"]} across two weekend days, before market gates/locks/failures. @reboot is unestimated; this interval has no DST transition. Cadence histogram, hourly heatmap, top 30 jobs and minute collisions are in `03-cron-remeasurement.json`. The 487/450 old counts are STALE_HISTORICAL. Logs support only partial runtime distributions, `03-runtime-distributions.json`; not every scheduler fire has a receipt.

## 5. Systemd census

Detailed read-only baseline captured 214 relevant user units; the later discovery retained 223 user/system records with PARTIAL discovery coverage. State/resource/fragment/ExecStart/EnvironmentFile path/timer/result/root fields are in `04-systemd-units.json` and `01-live-scheduler-observations.json`. Baseline unit state pairs: {dict(unit_census)}. Gateway runs CURRENT. Relay and executor run older `3549125b7` release, with missing loaded unit definitions/dangling links to a removed `72b0ce6be` release. `04-unit-links.json`, `04-process-roots.json` prove this; older receipts confirm it. Active failed/activating units and old frozen daemons remain visible. System Ollama is enabled/running despite RETIRED intent (`04-ollama-retired-host.txt`). No restart occurred.

## 6. OpenClaw scheduler census

OBSERVED_HOST `05-openclaw.json`: 13 jobs, 9 enabled and 4 disabled; 7 enabled announce/Telegram jobs. Job IDs, agent IDs, expressions and scheduler state are measured; payloads/tokens/destinations are excluded. The gateway and external ops process are observed in `04-process-roots.json`; ops uses no-apply/Telegram flags. Agent/job metadata is not durable host run proof. Duplicate sends, per-run attribution, browser/memory child writers outside STATE_ROOT and external skill receipt paths remain NOT_MEASURED. Unified API exposes these entries as unowned/NO_SIGNAL rather than claiming healthy delivery. No OpenClaw jobs were migrated or sent.

## 7. n8n runtime census

OBSERVED_N8N/HOST: Community 2.43.0; image digest/ID and compose path in `06-n8n-container.json`. Container running since `2026-10-08T19:58:56.591617215Z`, restart count 0, no Docker healthcheck; publish 127.0.0.1:5678 only, `m8m-n8n_lab` network. DB Postgres 16.15, about 19.65MB at census. **12 workflows / 8 active / 4 inactive**, one scoped relay header credential (TYPE/name only), 0 API keys, 0 webhooks, 0 community packages/nodes. Retained executions at 22:49 census: 419 success, 17 error, 4 running, grouped mode/status and latest-five metadata in `06-n8n-db.json`; success-none retention means this is not an expected-fire completion ratio. Task-runner process observed; no Redis container observed. Queue mode not justified by current ledger load. Explicit runner/log/metrics mode and restart history beyond the captured container epoch are NOT_MEASURED.

## 8. n8n security/hardening assessment

P1: owner MFA false, application DB role superuser with create/replication/bypass privileges. API is enabled despite no keys; operator decision needed to disable it. Positive observed controls: loopback UI, scoped relay credential, environment access blocked, command/SSH/email/FTP/local-file nodes excluded, community disabled, success payloads none, error all with 168h pruning, encryption key configured. Escrow/recovery verification is NOT_MEASURED. Sampled container TCP reaches relay only; configuration firewall proof is BLOCKED by sudo authorization (`07-network-probes.json`). Real read-only n8n security audit ran successfully and is redacted in `07-n8n-security-audit.md`; CLI bootstrap acquires its migration lock, so do not claim an entirely side-effect-free bootstrap.

Latest observed dump `20261008T051506Z`, 626,423 bytes, backup receipt ok; latest restore-drill receipt Oct 7 14:40Z ok (`06-backups-current.json`). Nightly/weekly timer intent and pipeline step source exist; independent failure receipt/watchdog recovery must remain outside n8n authority. [n8n security audit documentation](https://docs.n8n.io/hosting/securing/security-audit/), [database guidance](https://docs.n8n.io/deploy/host-n8n/configure-n8n/choose-n8ns-database.md) supports a separate Postgres 17 plan/non-superuser role; [public API control](https://docs.n8n.io/deploy/host-n8n/configure-n8n/security/disable-the-public-api.md). [Community features](https://docs.n8n.io/deploy/host-n8n/community-edition-features.md): no observed requirement for paid RBAC/projects/SSO/external secrets/environments/Git/log streaming/multi-main. No Redis/queue upgrade is recommended without load evidence.

## 9. N1 shadow result

**BLOCKED, all current active workflow rows NO_GO**. `09-10-n1-acceptance-matrix.json` lists IDs/activation/shadow-live/schedules/relay attachment/latest retained executions/host receipts/output before-after evidence. {len(runs["runs"])} host requests at 22:49 are durable, mostly successful shadow receipts; one watchdog lock skip is retained as lost work. Executor code SHAs are older; branch fixes are not CURRENT. Complete green n8n + host proof for two natural fires after all current fixes is absent, including weekly no-fire lanes. No manual acceptance firing occurred. Snapshot live receipts alone do not prove valid canary conditions, legacy-active status and rollback. No lane is cut over.

## 10. N2 readiness

NO_GO. PR #1537 reviewed at exact head `66adc9285a581703d04c863b90ea36ee0964810f`, not applied. Extracted actual gate JS accepts shadow/live mismatch, exit1 and future finish. `11-dag-negative-review.json` and `11-n2-dependency-design.md` describe receipt identity/mode/exit/business-day/overnight/DST/staleness/idempotency/retry requirements. Receipt is dependency proof; schedule remains a trigger. No n8n provider/broker authority is introduced.

## 11. Duplicate scheduler matrix

`02-duplicates-conflicts.json`: 17 command/shared-lock candidate groups; 16 shared locks and one repeated exact command. Separate 12:05/16:10 session reviews are benign windows. Quote-refresh shared lock collides at 10:45/12:45/13:45 weekdays; NEEDS_DESIGN, not proof of identical business work. Four active shared-output groups require writer synchronization proof. Source registry drift/unowned entries are explicit. Shadow/live overlap is not automatically a duplicate side effect; receipts and mutation contracts decide it. Locks do not legitimize multiple schedulers. P0 financial/safety duplicates remain NOT_MEASURED, so no financial scheduler mutation is proposed.

## 12. Dev-tree leakage matrix

`04-dev-tree-leakage-matrix.json` literal recursive traces and `04-reviewed-path-findings.json` separate executable hops, state-read candidates and deliberate shared venv. 24 literal candidates are not 24 proven executions. Genuine source defects include three governance PROJ assignments (fixed) and portfolio controllers leading to six dev-root launchers (exact remaining remediation, preserve output/send semantics). Flash unit definitions reference another worktree; maintenance retention child and CIO read paths need review. Actual running process roots are `04-process-roots.json`; short-lived child execution is not inferred from a top-level CURRENT WorkingDirectory.

## 13. Queue/worker matrix

`17-queue-worker-matrix.json` joins 36 observed DB queue/proposal tables with selected source producer/consumer/claim/retry/reclaimer contracts and file-queue exceptions. One census cannot prove permanently growing queues or inflow capacity. Notable observed backlog: deep overnight pending 1,928 since May with stale done history; watch decision refresh queued 925 and running 4 since Oct 5; agent events processing 4 with old claims; watchlist jobs queued 4 with completed activity Oct 8. Do not replay paid or broker-affecting old work automatically. Watchlist/deep-overnight SELECT-then-UPDATE claim paths depend on original exclusivity; source reapers exist, but duplicate-claim and current reclaimer effectiveness require observation. SQLite n8n nonterminal queue empty at capture. Hermes/CIO file queues' live counts are NOT_MEASURED, source lease/dedupe contracts are not promoted to LIVE.

## 14. Command Center coverage

SOURCE_ONLY additive `/api/v2/scheduler-operations` is GET-only, `SchedulerOperations@v1`, READ_ONLY_ADVISORY. `/v3/coordination` defaults to Automation / Scheduler Operations with requested columns/filters, stale/error handling, nullable unknowns, receipt/output timeline and candidate SLO breaches. Existing event/migration views remain available. No model/provider keys or n8n payloads are exposed. LIVE requires matching durable host receipt and fresh output, not n8n green. Missing ownership/output/receipts remains visible, not filled with fake zeros. Four fixture Playwright tests passed, covering known problem filter/drilldown, stale 200, failed endpoint and 390px overflow; build passed (`15-*` artifacts). After exact-main deployment, LIVE no-interception API/host row agreement and console check remain BLOCKED by deployment grant; fixture success is TEST_ONLY.

## 15. SLO baseline

`16-slo-baseline.json` measures separate dry/live observed request cohorts, failure/skip ratios, runtime and queue p50/p95. Expected fires/missed/duplicate-run counts are null without complete retention/trigger identity. `03-runtime-distributions.json`: quotes 18 lock skips / 31 observed requests (~58.1%), p95 2,652s; ATM 44 skips / 462 requests (~9.5%), p95 ~7s. These breach requested investigation thresholds; independent safety lane retained. Candidate critical 99% completion/<1% unexpected skip/2x cadence freshness are proposals, not globally ratified SLOs. UI can show measured candidate breaches while unmeasured coverage remains NOT_MEASURED. Market/off-hour exceptions require process-specific calendar contracts.

## 16. Fixes implemented

FIX_NOW_SOURCE/P1: rebind relay/executor in exact-main deploy source; fail on restart/root mismatch; document stable unit installation; release-relative root in three governance wrappers. P1/P2: read-only scheduler projection with partial discovery recovery, state drift, matching receipt validation, shadow separation, stale output/failure preservation, no-write ledger reader, nullable counters; additive operator table and fixture CI. P2: source Ollama retired intent/monitor NO_SIGNAL reasons. Burst fixture expanded to 1/5/16/32/64; source already has backlog64, so no server rewrite. P3: fix a pre-existing test's digit-substring/mtime false failure using structured withheld-value assertions and deterministic metadata collision; financial truth assertions retained. Each defect has negative regression evidence. No runtime remediation was applied.

## 17. Operator-only changes proposed

`20-operator-change-packet.md`: scoped stable unit install/restart and approved exact release; retire running Ollama after residual-consumer decision; owner-only MFA; API disable/healthcheck; isolated Postgres17/non-superuser migration; key escrow verification; privileged read-only firewall proof before rule changes; exact per-line collision/cadence/registry packets; natural N1/canary/rollback window. NEEDS_DESIGN: 395 unmatched row contracts, portfolio/dev-root child semantics, queue double claims, OAuth process scope, embedding replacement/vector migration. RETAIN_WITH_REASON: independent broker/safety/recovery and deliberate shared interpreter. No policy ratification or automatic source activation.

## 18. Rollback plan

Source rollback is git revert of problem-specific commits and operator deployment of the prior approved immutable main release. Stable unit recovery must restore valid regular definitions/root, not missing symlinks. Any future lane cutover rolls back only its exact retired cron line/timer and workflow, preserving unrelated scheduler changes. Keep old DB volume/digest during proposed migration; key escrow independent. This task changed no live scheduler ownership, so no host rollback is currently necessary. Ollama retirement must not be silently reversed.

## 19. Remaining risks

Runtime executor/relay are not exact-CURRENT; missing unit fragments jeopardize restart recovery. Registry and consumer/output chains incomplete. Financial duplicate-writer inventory, all child execution roots, browser/external skill receipts, queue throughput/reclaimer behavior, full firewall policy, metrics/log configuration, embedding/native-vector population and natural success retention are NOT_MEASURED/BLOCKED. N1/N2 remain NO_GO. Source/fixture evidence cannot establish live authority or production convergence. Canonical local acceptance/remote CI exact results are recorded separately; a failed gate is never weakened to pass.

## 20. Recommended next 30 days

Days 1–3: review/approve exact source and narrowly scoped runtime recovery packet; resolve retired Ollama residual consumers; owner enables MFA; verify escrow and firewall rules. Days 4–10: observe two natural shadow fires per lane after all exact-CURRENT fixes, minimal execution-status evidence, proper live canary and per-lane rollback, with independent legacy/recovery during canary. Weekly natural shadow windows may require longer. Days 11–20: assign unmatched process owners, writer/consumer contracts and durable receipts, baseline expected-fire/skip/output SLOs, correct queue exclusivity/reclaimers and dev-root children. Days 21–30: consider only evidence-ready lane cutovers, then generic N2 dependency gating; separately decide Postgres17/n8n role and RAG migration. No target date overrides a NO_GO gate.

PLATFORM_RUNTIME_SOURCE_ACCEPTANCE_BLOCKED
"""
md("20-final-report.md", report)
print(
    json.dumps(
        {
            "inventory_rows": len(inv["rows"]),
            "active_intent": dict(active),
            "n1_rows": len(n1),
            "queue_rows": len(queues),
            "reviewed_path_candidates": len(reviewed),
        }
    )
)
