# 12 · Installation and Permission Inventory — pre-execution gates

```
Status:      PROPOSED
as_of:       2026-09-27T18:00:00-04:00
Measured at: 8f2a178d5 (origin/main) / served 8f2a178d5-main-exact-phase2-20260927-171004.
             Host facts tagged [VERIFIED] were read on 2026-09-27 by read-only commands quoted in 00 §0.3.
Authority:   READ_ONLY_ADVISORY. Nothing is installed, upgraded, replaced or removed by this document.
Package:     cognitive_transformation_20260927 — read 00 first.
Answers:     operator brief §11 (pre-execution permission gates: software, infrastructure, access;
             why / risk / impact / rollback for every item).
```

## 0. The design principle that keeps this list short

No new stores, no new frameworks, no new products. The platform already has Postgres 17 with pgvector,
JSONL append-only stores with hash chains, systemd/cron, a health agent, a watchdog, a Command Center,
a governed model bridge, an Ollama host, Telegram bots with inline keyboards, and Bitwarden Secrets
Manager. Everything in 01–08 is wiring over those. The inventory therefore has **two** software items
and **zero** new services from outside the repository.

## 1. Software — install / upgrade / replace / remove

| # | Item | Action | Why | Risk | Impact | Rollback |
|---|---|---|---|---|---|---|
| SW-1 | Ollama model `nomic-embed-text` (768-d, local) | **install** (model pull; Ollama already runs on the host per the local-LLM policy `[DOC-CLAIM: memory]`) | retrieval step 7 (03); embeddings never leave the box (§2A) | low: disk (~300 MB), CPU/GPU time during projection | enables semantic lookup; absent → step 7 returns MISS, the rest of the ladder works | `ollama rm nomic-embed-text`; `intelligence.embedding` table left empty |
| SW-2 | Python `pgvector` helper package | **install only if needed** — first verify raw SQL through `psycopg2` suffices (`'[…]'::vector`); the design prefers no new dependency | vector column literals | very low | none if raw SQL works | `pip uninstall pgvector` in the dev venv; requirements diff reverted |
| SW-3 | Packages present and reused, no action: `psycopg2-binary`, `pydantic 2.12`, `python-docx 1.2.0` (venv), `anthropic 0.87`, `openai 2.30` `[VERIFIED: venv listing 2026-09-27]` | — | — | — | — | — |
| SW-4 | `local_llm` shim (`local_llm_compat`, 21–22 importers) | **decision** (revive at the registered $0.25/150/day or remove the shim) | returns `""` on refusal — a silent failure pattern (06 §8) | medium if removed abruptly: 22 importers | operator spend decision (11 O-5) | registry row toggled |
| SW-5 | Explicitly **not** installed: Neo4j/any graph DB, Redis, Kafka/RabbitMQ, Celery, Prometheus, Grafana, OpenTelemetry, SQLAlchemy, LangChain-style frameworks | none | 07/06/02 show Postgres suffices; every new product is a new silo and a new operator burden | — | — | — |
| SW-6 | Agents/services **from the repo** (new lanes, not new software): conformance audit, memory compliance audit, breach detector, GIR projector, approval reminder, checkpoint rotation | **add as lanes** (11 O-2) | the five pillars need six scheduled jobs | low; each has an SLA row and an L1 action | +6 lanes to a registry of 147 declared | disable lane; unit removed via the install script |
| SW-7 | Retired: 5 no-op Wave-3 timers, `tradeai-iris-taxonomy.timer` (already disabled), duplicate crons (W0-7 done), the three overlapping material-change detectors (keep the DB one), two of the four health agents (fold into 06 L3) | **remove from schedule; archive with tripwire** (§0 rule 6) | duplication (09-27 §10) | low–medium: a consumer may depend on a retired writer — DSA check first | fewer double runs | re-enable unit; archive manifest |

## 2. Infrastructure — modifications

| # | Item | Modification | Why | Risk | Impact | Rollback |
|---|---|---|---|---|---|---|
| IN-1 | **Production Postgres 17.11** (`127.0.0.1:5432`, db `trade_ai`, 766 tables; extensions btree_gist, pgcrypto, uuid-ossp, **vector 0.8.6** `[VERIFIED: read-only SELECT on pg_extension, 2026-09-27]`) | new schema `intelligence` with 8 tables + indexes (02 §5, 06 §3–4, 13); one reviewed migration | GIR read model, edges, research index, embeddings, supervisor, approval ledger | medium: projector load on first build (run off-peak, batched); disk growth (est. < 2 GB first year) | new tables only; no existing table altered | reviewed `DROP SCHEMA intelligence` script, **never automatic** (memory 09-19: destructive on re-run) |
| IN-2 | **M2 shadow** (docker `tradeai-m2-shadow-v2`, pgvector/pg16, :55432) → production | `memory_prod_cutover.apply` (exists `[CODE]`) after roles (AC-2) | history/bitemporal on prod | medium: cutover script is destructive on re-run per memory; dry-run first | M2 facts queryable from prod; shadow kept as replica until W3 | keep shadow; point `M2_AGENT_DSN` back |
| IN-3 | **Lab Postgres** (:5433, `~/tradeai-lab/pg17`) | none, except as the rollback-test target for IN-1 migrations | migrations are tested where they can be dropped | low | — | — |
| IN-4 | **Storage** | rotation for `agent_checkpoints/*.jsonl`, `research_contradiction_candidates.jsonl` (118 MB), advisory KB (245 MB) via `rotate_append_only_store.py` scheduled (SW-6) | growth; no deletion | low | archive dirs with tripwire | stop the lane |
| IN-5 | **Queues** | no new queue system; existing Postgres queues (22 `*_queue` tables `[VERIFIED: survey]`) and JSONL queues migrate to the worker contract in place (W4) | one claim primitive | medium per migration (each is its own PR with dry-run) | fewer queue styles | per-lane revert |
| IN-6 | **Messaging** | none new; the CIO event bus gains `memory.delta`, `breach.*`, `approval.*` event types (today 15) | fan-out, supervision, approvals | low | consumers opt in | remove consumer |
| IN-7 | **Graph systems** | none; `intelligence.gir_edge` in Postgres | 07 | — | — | — |
| IN-8 | **Observability** | none new; Command Center panels (supervisor, governance, memory compliance) over `supervisor.*` and `data/governance/*.json`; Cockpit stays on :9090 | 06 §7 | low | new API routes (counted in `route_access_counts`) | remove panels |
| IN-9 | **systemd user units** (host 259 vs repo 117 `[VERIFIED: survey]`) | +2–4 units for SW-6 lanes, via `install_cio_operator_runtime.sh`; nothing hand-installed | §10 | low | drift baseline shrinks, not grows | uninstall via script |
| IN-10 | **Telegram** | no new bot; the main bot's single `getUpdates` poller handles package callbacks (13); no second consumer (HTTP 409) | single approval queue | low | one more callback prefix (`pkg:`) | remove handler |
| IN-11 | **Ollama host** | model pull (SW-1) | embeddings | low | disk | remove model |

## 3. Access requirements — permissions, credentials, API access

| # | Requirement | Who grants | Why | Risk | Rollback |
|---|---|---|---|---|---|
| AC-1 | `sudo` for `CREATE SCHEMA`/`CREATE ROLE` on prod Postgres (the app role cannot) | operator (superuser session) | IN-1, IN-2 | one-time, reviewed SQL | `DROP ROLE` in the same review |
| AC-2 | New roles: `intelligence_reader` (silos via façade), `intelligence_writer` (projector, façade commit, supervisor), with RLS tenant policy like `memory_r10_m2` | operator | least privilege | credentials → Bitwarden SM (`bws`), rendered by the existing read-only render token flow; **never** into `agent-operator.env` | revoke role |
| AC-3 | Rotate existing plaintext DSNs (`~/.config/tradeai/agent-operator.env`) — 09-27 top-risk 3 | operator (BWS edit first; then render + `ALTER ROLE`; prod `trade_ai_shadow_ro` via `~/ops-rotation/rotate_trade_ai_shadow_ro.sh` `[DOC-CLAIM: memory 09-27]`) | credentials at rest | crons sourcing the env break if rotation and render are not atomic — do it in the maintenance window with the supervisor watching | previous secret version in BWS |
| AC-4 | `sudoers` allowlist for supervisor L1 restarts (specific `systemctl` verbs on named units; the health agent runs under `NoNewPrivileges` and cannot start Postgres `[DOC-CLAIM: AGENTS 1.2.2]`) | operator | 06 L1 | scope creep — the list is enumerated and diffed in the security review | remove lines |
| AC-5 | Telegram: no new tokens; verify `from_id` against an operator allowlist in `guard_remote_approval` | operator (allowlist value) | 13 | none | config revert |
| AC-6 | Git/GitHub: push via `TRADEAI_REMOTE_PUSH_AUTHORIZED=1` under per-package grants; merges by the operator (0 required reviews today; CODEOWNERS advisory) | operator | AI_WORK_POLICY | budget 1 push per tranche | — |
| AC-7 | Cloud/API: **none new**. No new LLM provider, no new data vendor; OAuth lanes and DeepSeek as today; Brave/SearXNG as today | — | 03 reuses what is fetched | — | — |
| AC-8 | Drive: existing `gog` sync of `docs/` and the approval artifacts; no new scopes; **mail** scope already used for the 09-26/09-27 deliveries under operator instruction | operator | 11 §3 | `gog drive upload --dry-run` uploads anyway (AGENTS §7) — search first, upload once | — |
| AC-9 | Database read access for the audit lanes: read-only role on prod (existing `trade_ai_shadow_ro` after rotation) | operator | 05/06 | — | — |

## 4. What this inventory guarantees

- **No hidden dependencies:** every module the designs import exists in the repo today (01–08 cite
  them by path); the only external artifacts are SW-1 and, conditionally, SW-2.
- **No surprise installations:** SW-6 lanes and IN-9 units go through the install script and the lane
  registry gate (`check_lane_registry.py --fail-on-new` fails CI on an undeclared job `[CODE]`).
- **No silent architectural changes:** contract hashes (05 §5) and the docs drift check make a change
  to any of the five standard interfaces visible at prepare time.
- **Explicit operator approval before execution:** every row above maps to an item in 11 and to a line
  in the consolidated Telegram package (13). The first package (Wave 1) will carry: O-1, O-2 (4 lanes),
  O-3 (façade, projector, supervisor, ledger), S-1..S-4, I-1, I-3, I-4, P-1 (deferred to W4 if the
  operator prefers), B-4 — about 14 items, one message.
