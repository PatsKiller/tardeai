# Runtime reconciliation: operator change packets

Status: DRAFT_FOR_OPERATOR_REVIEW
as_of: 2026-10-12T03:05:00Z
Measured at: source 40208881dd34495b840bcbd4e373f593d06a659f; CURRENT 37752b193-main-exact-phase2-20261011-201624
Evidence: sanitized read-only observations in runtime_observations.json; no runtime changes executed
Owner: existing platform / CIO owners as declared; owner acceptance NOT_MEASURED
Consumer: migration integrator and operator; no automated action consumer

These packets preserve AGENTS.md §0, §17, §23.10 P13, §23.19 and §24.7. They authorize no role, password, service, scheduler, model, retention or provider change. A release grant for main does not authorize these operations. No secret file, model endpoint, business canary or production write was used to prepare them.

## n8n database role: restore under a dedicated application owner

The successful read-only preflight found `n8n` has SUPERUSER, CREATEROLE and CREATEDB, and `n8n_app` does not exist. Database `n8n` is owned by `n8n`; `public` is owned by `pg_database_owner`; its 157 tables, 25 sequences and 374 indexes are owned by `n8n`. Extensions `plpgsql` and `uuid-ossp` are also owned by `n8n`; no role memberships were returned. The app's migration DDL needs ownership of its objects, so GRANTing table DML alone would not establish a usable replacement role.

The established proposal in `docs/implementation/n8n-parallel/proposals/n8n-lab-hardening-compose-diff-20261008.md` §3 couples `n8n_app` with the PG17 recreate. Preserve that decision boundary. Operator review must choose the established PG17 restore or explicitly approve a separate PG16 role-only change. This packet recommends the established restore path, with retained old volume and compose rollback. No in-place demotion of the only known administrative role is proposed.

Before the change window, require all of the following:

1. An operator decision names the database, source/release SHA, exact services, continuity window, target PostgreSQL image and `n8n_app` role. The approved service/config/scheduler scopes must name all affected workflow authorities. Record active workflow IDs and lane-specific fallback triggers without exporting workflow payloads or credentials.
2. Prove a single scheduler authority for the four historically cut-over lanes during n8n downtime. The 413 legacy cron jobs remain authoritative for their lanes; candidate dispatch must stop before any lane fallback is restored. Preserve queued durable requests; do not clear the ledger or release dead letters.
3. Take a fresh sanctioned database backup and retain the original volume and compose artifact in the operator-controlled backup location. Record dump SHA, size, source server version, 157 expected table-data entries, workflow counts/IDs, migration head and public-object ownership. Backups contain sensitive database content; keep them outside documentation, Git and Drive uploads.
4. Operator verifies encryption-key escrow and recovery through the sanctioned secret system without exposing the value or asking an agent to read `.env`. The key is absent from the database dump. Missing escrow proof stops the change.
5. Restore the fresh dump in an isolated scratch database using the exact target PostgreSQL version and intended app role. Compare per-table counts and migration/schema fingerprints, confirm extension availability, and prove n8n starts and performs its migration DDL as `n8n_app` without SUPERUSER/CREATEROLE/CREATEDB or membership in a privileged role. The existing drill restored 157/157 tables and 43 workflows, but it does not prove restore/migrations under this new role.

The measured 2026-10-11 backup has 867,376 bytes, SHA256 `0a88ea0e8b7e7f223cce54fab1e894ab39c0ea696bc9db40cb34a4e6fc5b290f`, and 157 table-data entries. Its hash was independently recomputed. The 2026-10-11T07:00:12Z drill reports restore rc 0, 157/157 tables, 43 restored workflows and equal counts. It is useful recovery evidence; it is not a fresh pre-change backup or an `n8n_app` migration rehearsal.

Proposed operator SQL for the isolated target only, after backup and scopes are approved:

```sql
-- Review input only. Password provisioning is a separate sanctioned operator action.
CREATE ROLE n8n_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOREPLICATION NOBYPASSRLS;
-- Create the isolated target DB with n8n_app as owner through the administrative session.
-- Preinstall required extensions administratively if the chosen provider requires it.
-- Restore n8n tables/sequences/views as the application owner:
-- pg_restore --no-owner --no-acl --role=n8n_app --dbname=<isolated_target> <fresh_dump>
-- Do not use REASSIGN OWNED across the administrative cluster.
```

The administrative operator provisions the new password through sanctioned secret rendering and changes only the app connection's role selector. Do not change `POSTGRES_USER` on an existing volume and assume it changes role flags. Keep the administrative role outside the n8n application connection. If the operator instead approves object transfer in the existing DB, produce a database-scoped list of exact `ALTER ... OWNER TO n8n_app` statements from the inspected catalogs, excluding system objects and extension-owned objects; test that list in the isolated restore first. This alternate list is not generated or executed here.

After the approved switch, require:

- Metadata-only connection check reports `current_user=n8n_app`, all five dangerous role flags false, and no privileged parent role. Application objects and database ownership agree with the isolated rehearsal.
- n8n health and readiness pass, migration head and schema/count fingerprints agree, all previously active workflow IDs retain their approved state, and the sanctioned relay path produces durable host receipts. Neither green workflow state nor exit 0 establishes business output.
- Two natural shadow fires, required canaries, failure notification/recovery and output/consumer proof remain separate lane gates. This role change supplies none of those approvals.

Rollback first stops candidate scheduling. Operator restores the archived connection/compose selector and retained old volume for the named release, then verifies workflow state, one scheduler authority and durable output recovery per affected lane. No wholesale crontab restore, role drop, dump deletion or key rotation belongs to this rollback. Do not purge the target or old volume; retain both with their hashes and timestamps.

## Hermes CIO worker: current idle success, historical failures retained

Fresh service metadata reports inactive/dead, `Result=success`, `ExecMainStatus=0`, last fire 2026-10-11 22:45:26–22:45:27 ET. Its timer is enabled and waiting on the existing 15-minute calendar. The projection resolves to persistent state and has 1,938 historical requests: 1,161 completed, 776 failed and one cancelled, with zero queued/started/running rows at 02:57:49Z. This corrects the earlier failed-unit snapshot. No restart was performed.

Sanitized recent log summaries contain `HermesWorkerError` and language-related refusal categories. The journal records a prior failed process near 21:48 ET. Exact failed-item → unit-run correlation and successful reprocessing are NOT_MEASURED. Do not treat a later empty-work exit 0 as recovery of the historical failed population. Do not repeat the refused item, weaken execution-language guards, select another provider or set a different backend to obtain green.

Current scoped recommendation: retain the timer and inspect the next natural metadata/queue summary. There is no evidence justifying a blind restart or queue replay. If failure recurs, prepare a separate incident packet with sanitized exception category, unit invocation/time, claimed/completed/failed counters and affected queue IDs held locally. Correlate its input/guard result and durable research-output/callback receipt without exposing account or prompt contents.

Any implementation correction needs a separate owned source/test scope. Use fixtures and a stub backend, isolated projection/request/result paths, empty dotenv inputs, a raising model/notification/DB barrier and preserved rejection assertions. Do not run the worker CLI against live state to diagnose it. A future service repair needs the appropriate named service/config grant; archive exact unit/drop-ins, quote source tests at exact CURRENT, preserve store destinations and existing backend/caps, then verify the next natural fire. Rollback restores only those archived drop-ins and the prior code selector. Queue replay, failed-row resets, model calls and policy changes are separate owner decisions.

## Ollama retirement: service drift and unmeasured caller closure

The service remains active/running/enabled at `/etc/systemd/system/ollama.service`, PID 5135. The approved read-only reverse-dependency census lists only `graphical.target`; an approved socket census found no established TCP connection on port 11434 at its observation time. Neither proves there are no periodic or future callers. No model call, health-generation probe, stop, disable, package removal or credential read was performed.

`scripts/local_llm.py` is a compatibility facade: its historical imports route through governed cloud generation, `_try_ollama` raises `LocalGenerativeForbidden`, and explicit local generation fails closed. An import named `local_llm` is therefore not evidence of a live Ollama dependency. Shared embedding code still names a candidate loopback embedding endpoint (`scripts/lib/ollama_embedding_policy.py`); supported embedding-runtime selection remains an operator decision. Completion119 holds `rag-indexer` and topic-curation closure on that boundary.

Static candidate direct endpoints and old operational probes exist in source, including `scripts/hermes_backlog_drain.py`, `scripts/phase3_media_prose_router.py`, `scripts/hybrid_rag_context_adapter.py`, `scripts/check_local_llm_health.py`, `scripts/check_llm_fleet_alerts.py`, `scripts/llm_health_gate.py` and `scripts/claude_escalation_handler.py`. Filename/call-site metadata is source-only and does not prove active scheduled invocation. Broker/financial child closure remains outside this packet; do not investigate or alter it without its per-task grant.

Before stop/disable, operator confirms the existing retirement instruction, its exact scope and the owned embedding decision; approves the named system service actions and rollback; and collects a bounded passive caller census over all relevant periodic schedules. Match current cron/timer/parent stages to the candidate source endpoints, inspect authorized connection/process metadata without prompts, and assign each caller a retain/retire/replace/held disposition. Do not call an endpoint to manufacture usage proof. A future monthly caller cannot be cleared by a momentary empty socket census.

The concrete proposed action, once those gates and grants pass, is the administrative equivalent of `systemctl stop ollama.service` then `systemctl disable ollama.service`. Record previous enabled/active state, exact unit/drop-in hashes, dependent-state snapshot and the grant before any action. Afterward verify inactive/disabled, no listening port 11434, no new dependent failure/queue backlog, and intact governed-cloud refusals. Do not remove model files, packages, caches or any output store.

Rollback is separately scoped in that same approval: restore the archived unit/drop-ins and prior enabled flag, and start the service only if the operator authorizes that rollback. Restoring a service does not authorize retired local generation, an embedding model selection or a changed fallback. Collect passive caller/error metadata and prove recovery through each caller's accepted contract. All caller acceptance, stop/disable, and rollback execution remain NOT_MEASURED in this package.
