# WP-34 item 4: operations configuration and Controls modal proposal

Status: PROPOSED — P3 design only; runtime implementation and authority changes not approved
as_of: 2026-10-24T03:12:54Z
Measured at: source main `8ed8a246486317950df01f2a1846825627f369eb`
Owner: codex-wp34-20261024; Design-Task DSN-20261024-ops-config-modals-P1-T1

Ops Controls already provides a small, typed set of operator actions. The remaining work is
to admit configuration families through their existing owners, add field-level validation,
and prove the effective value in the actual consumer. A saved override or reviewed proposal
must have a distinct status from an applied, verified operational change.

This package delivers a complete tracked-path census, writer/reader and modal-gap mappings,
an offline interactive design, and a registered three-phase proposal. It changes no runtime
settings, flags, policies, credentials, source authority or applier behavior. It takes only
WP-34 item 4. Passkey renaming and sudo-window activation remain operator-only items; neither
was performed. #1976 is CLOSED as integrated; its readiness view is present in main and was
not reopened or rebased.

## Measured scope

| Measurement | Count / result |
|---|---:|
| Tracked paths under `config/` | 1,110 |
| Top-level configuration paths | 248 |
| Populated configuration families | 20 |
| Curated source evidence anchors | 47 |
| Literal filename references / source files containing them | 2,027 / 703 |
| Public Ops Controls setting keys | 4 |
| Keys declared wired / unwired | 2 / 2 |
| Declared change-kind specs / supported / unsupported | 23 / 20 / 3 |
| Actual hand-edited runtime settings, installed parity and accepted editor coverage | NOT_MEASURED |

The 1,110 paths include 651 CI gate definitions, source unit files, schemas, examples,
generated baselines, reference data and financial/credential boundaries. It is a filename
accounting denominator, not 1,110 missing modals or 1,110 production-ready controls. Group
F20 contains metadata/generator assets; F17 contains 149 source unit definitions (the other
`config/systemd/` path is an example environment file). F21 is the reserved unknown-family
fallback and has no paths in this snapshot.

The census reads tracked filenames and searches non-test source for their literal references.
It excludes broker source and credential/secret files. Only the public four-key Controls
catalogue metadata (key/type/bounds/wiring/consumer) was read from configuration content.
Literal references are evidence leads, not runtime reader closure or proof of single-writer
ownership. Dynamic loads, installed copies and family-specific writer ownership require the
P2 attestation before enabling an editor. Missing measurements remain explicit.

## What is already covered

- Jobs supports exact-line cron pause/resume and release STOP/pause/resume/arm. It does not
  provide a general schedule, dependency, delegation-scope or release-policy editor.
- n8n supports live-list membership. That does not edit the run allowlist, source registry,
  workflow, contract or executor policy, or prove that all admission conditions hold.
- Flags has four keys: the two sudo settings have a source reader in
  `ops_controls_sudo.gate`; the two Active Trader thresholds are explicitly `wired:false`.
  The source preview warns that an unwired value is stored but unused.
- Data approvals shows store, writer, reader, freshness and readiness evidence. Its view
  does not provide an arbitrary authority-registry mutation. Work pipeline decisions use
  their existing coordination ledger; the source file catches up in a reviewed commit.
- Grants and passkey lifecycle controls already exist. Release scope/revoke and kill-switch
  clear remain explicitly unsupported Controls kinds; this design does not add them.
- LLM caps already have an operator Telegram callback invoking `llm_cap_admin.set_caps`
  with a database connection. A future Controls adapter should reuse that owner. With a
  connection, it updates the database first and registry second, reporting partial failure;
  without one, the helper changes only the registry. The modal must expose both versions.

The existing catalogue and source-supported kinds are captured in
[inventory.json](packets/ops-config-modals-20261024-wp34/inventory.json). Source support is
not a live authorization: actual policy, operator identity, flags, grants and prerequisites
still decide whether a request may run.

## Common modal and approval flow

```mermaid
flowchart LR
  A[Read original owner and effective revision] --> B[Typed fields from approved catalogue]
  B --> C[Validate and preview exact change]
  C --> D{Existing authority route}
  D --> E[Operator proof and existing runtime writer]
  D --> F[Reviewed source proposal / package]
  E --> G[Durable writer receipt]
  F --> H[CI, coordinator merge and release]
  G --> I[Consumer readback at the expected revision]
  H --> I
```

Every form shows effective state, source revision, original observation time, owner,
permitted fields, consumer wiring, change scope and whether it applies immediately or after
release. Preview binds both the target identity and before-state digest. An expired/stale
preview, unknown key, failed validation, missing owner, refused capability or absent evidence
stops that request. Repeated requests use the same idempotency identity and do not repeat
business effects.

Runtime settings reuse the existing request→preview→operator proof→host applier→original
writer path. Safe/risky direction comes from the server. The current fresh-assertion
exceptions remain, including grants, passkey lifecycle, protected release actions and sudo
settings. The browser receives no host, GitHub, vault or deployment credentials.

Versioned schedules, contracts, policies and routing rules produce a source change proposal
through the existing reviewed workflow. They do not become direct repository file writes
from the web process. A modal does not change review authority, auto-review a health contract,
convert shadow to live, enlarge capability scope or infer a financial/model owner decision.
Financial, broker/order/stop and credential changes remain outside a generic editor.

The result states must distinguish `PROPOSED_SOURCE_CHANGE`, `STORED_NOT_EFFECTIVE`,
`APPLYING`, `PARTIAL`, `REFUSED`, `FAILED` and `EFFECTIVE_VERIFIED`. A receipt alone proves
neither consumer adoption nor business output. The cap adapter must preserve the existing
DB-updated/registry-failed distinction rather than claim an atomic two-store success or
blindly retry. The same principle applies to schedule install versus natural trigger proof.

The common preview contains the exact target/version, before/after fields, affected readers,
required reviewer/authority, validator results, install/reload requirement, readback contract
and any unavailable measurement. Secrets, cookies, tokens and credential material never
appear in input fields, preview, audit text or evidence. No arbitrary path, shell command,
JSON document, model identifier or service name is executable through this design.

## Family mapping

Each populated family's exact paths and their literal source references are in the
[complete census](packets/ops-config-modals-20261024-wp34/config-path-census.json). The
following mappings name the currently proven writer/reader behavior and the proposed
boundary; source-specific ownership still needs attestation where explicitly stated.

### F01 — Operator settings and Controls feature catalogue (1 paths)

Source examples: `config/ops_controls.json`.

**Current writer:** operator_settings is written by ops_controls_core.apply_change through Store.setting_apply; source catalogue/work_pipeline switches remain reviewed repository edits.

**Reader evidence:** ops_controls_sudo.gate reads the two sudo settings; the two Active Trader thresholds are explicitly wired:false in the catalogue.

**Current coverage/gap:** FlagsTab/SettingEditor already offers four keys and set/unset previews. Stored success does not prove effect for unwired keys.

**Proposed modal:** Keep Flags & thresholds; add effective-value, wiring and source-version readback. Catalogue/feature expansion is a separate source-change proposal.

**Authority:** Existing setting kinds only, with existing passkey/phrase and fresh assertion for sudo settings; adding keys or capabilities requires a separately approved source PR.

**Validation:** Catalogue key/type/range/enum, finite numbers, no unknown keys; wiring fixture and real consumer readback required before effective status.

**Preview and verification:** Show default, override, effective consumer value, revision, affected consumer and applies-now/after-release. Unwired is STORED_NOT_EFFECTIVE, never APPLIED_EFFECTIVE.

Evidence: [ops_controls_core.py:532](../../scripts/lib/ops_controls_core.py#L532), [ops_controls_core.py:665](../../scripts/lib/ops_controls_core.py#L665), [ops_controls_sudo.py:76](../../scripts/lib/ops_controls_sudo.py#L76), [OpsControls.tsx:660](../../apps/command-center-v3/src/pages/OpsControls.tsx#L660).

### F02 — Schedules and pipeline definitions (10 paths)

Source examples: `config/hermes_discovery_schedule.json`, `config/lane_registry.json`, `config/lane_stay_on_cron_tokens.json`, `config/n8n_due.json`. All paths are in the census.

**Current writer:** Source registry/schedules are reviewed repository edits; existing crontab pause/resume writes host scheduler through Hosts.crontab_write.

**Reader evidence:** n8n_due.file_sources/load_due_config load scheduling inputs; source references for every grouped path are retained in the census.

**Current coverage/gap:** Jobs lists schedules and pauses/resumes exact cron lines; no arbitrary cadence/dependency/definition editor exists in KINDS.

**Proposed modal:** Schedule & dependency proposal: timezone/DST calendar preview, lane graph, native n8n schedule, exact legacy-trigger disposition.

**Authority:** Propose a reviewed source change; activation remains existing contract/deployment/scheduler admission. Do not add cron to an n8n workflow.

**Validation:** Existing registry/due validators, schedule/timezone/DST and overnight dependency fixtures, one-authority checks; refuse unknown command changes.

**Preview and verification:** Before/after next natural fires, dependency edges, source digest and deployed identity; verify trigger→receipt→output rather than only saved schedule.

Evidence: [n8n_due.py:162](../../scripts/lib/n8n_due.py#L162), [n8n_due.py:364](../../scripts/lib/n8n_due.py#L364), [ops_controls_core.py:356](../../scripts/lib/ops_controls_core.py#L356).

### F03 — n8n execution and admission (5 paths)

Source examples: `config/lane_dispatch_policy_exceptions.json`, `config/n8n_effect_keys.json`, `config/n8n_executor.json`, `config/n8n_fabric_processes.json`. All paths are in the census.

**Current writer:** Reviewed source edits to allowlist/executor definitions; existing live-list add/remove writes only its configured host file and selected service restarts.

**Reader evidence:** n8n_due.file_sources and relay/executor source references consume these definitions; a live-list change is only one admission input.

**Current coverage/gap:** n8n tab supports live-list membership; it is not an editor for commands, capability closure or executor policy.

**Proposed modal:** Lane admission dossier and source proposal, with command closure and contract/deployment evidence attached.

**Authority:** Existing allowlist/capability reviewers and explicit operator admission; no arbitrary argv, code path or service selection in a generic form.

**Validation:** Existing registry/relay/capability gates, disjoint shadow locks, exact source digest, refusal/duplicate-effect fixtures.

**Preview and verification:** Show registry, allowlist, reviewed contract, live-list and installed workflow separately; read back each after an approved change.

Evidence: [n8n_due.py:364](../../scripts/lib/n8n_due.py#L364), [ops_controls_core.py:363](../../scripts/lib/ops_controls_core.py#L363), [ops_controls_core.py:372](../../scripts/lib/ops_controls_core.py#L372).

### F04 — Health contracts, retries and cutover evidence (10 paths)

Source examples: `config/lane_cutover_policy.json`, `config/n8n_health_contracts.json`, `config/n8n_migration_tranches.json`, `config/n8n_momentum_lifecycle_candidate.json`. All paths are in the census.

**Current writer:** Contract/remediation builders can generate proposals; reviewed source commits own operative contracts and retry/cutover policy. Work pipeline records review in an append-only ledger; it does not rewrite the contract file.

**Reader evidence:** n8n_health_contracts.check/validate_contract, n8n_retry_policy.load_policies and n8n_shadow_policy.load_policy.

**Current coverage/gap:** n8n readiness display and pipeline.contract_reviewed exist; no full contract/retry/promotion-policy form exists.

**Proposed modal:** Health contract editor and retry eligibility proposal, with owner review provenance and natural-evidence readiness.

**Authority:** Preserve actual reviewer/owner authority. A proposed edit stays DRAFT; review ledger is separate from operative source and deployment.

**Validation:** Required fields/UNKNOWNs, existing contract/retry checks, sender/learning single-attempt exclusions, exact-head/natural-fire proof.

**Preview and verification:** Diff contract fields and applicable requirements; show reviewed source SHA versus deployed SHA, then consumer health/alert/recovery receipts.

Evidence: [n8n_health_contracts.py:121](../../scripts/lib/n8n_health_contracts.py#L121), [n8n_retry_policy.py:287](../../scripts/lib/n8n_retry_policy.py#L287), [work_pipeline_tier2.py:231](../../scripts/lib/work_pipeline_tier2.py#L231).

### F05 — Release windows, policy and delegation (6 paths)

Source examples: `config/ci_outage_emergency.yaml`, `config/release_pin_daemons.json`, `config/release_train_drain_policy.json`, `config/release_train_n8n.json`. All paths are in the census.

**Current writer:** Versioned policy source; release_control_cli owns host delegation/latches through its existing guarded protocol, not a JSON form.

**Reader evidence:** release_train_window_view.load_config/validate_config and release_train_classify.load_policy.

**Current coverage/gap:** STOP/pause/resume/arm exist. change_scope/revoke are explicitly unsupported in Ops Controls; windows/policy are not editable there.

**Proposed modal:** Release-window calendar proposal and delegation-scope review packet; retain existing STOP/pause and bounded resume/arm.

**Authority:** Coordinator/operator release authority and fresh passkey for protected release acts; capability reservation and exact-head approval remain mandatory.

**Validation:** Window schema/calendar, source classifier, capability proof, revocation epoch and exact-main evidence. No environment-only authority.

**Preview and verification:** Show candidate windows and next fires, scope/revocation delta, exact SHA and current reservation state; re-read actual controller state after apply.

Evidence: [release_train_window_view.py:80](../../scripts/lib/release_train_window_view.py#L80), [release_train_classify.py:86](../../scripts/lib/release_train_classify.py#L86), [ops_controls_core.py:236](../../scripts/lib/ops_controls_core.py#L236).

### F06 — Data authority, domains and capabilities (8 paths)

Source examples: `config/cio_domain_capability_registry.json`, `config/cio_known_dark_classification.json`, `config/cio_surface_classification.json`, `config/contract_manifest.json`. All paths are in the census.

**Current writer:** Reviewed registry source records approvals; Work pipeline stores operator decisions in coordination ledgers pending the source commit.

**Reader evidence:** data_source_authority.registry and existing DataTab readiness/readers/writer findings.

**Current coverage/gap:** Data approvals is a readiness/details view, not a generic authority-registry editor. #1976 is closed/integrated; no rebase is needed.

**Proposed modal:** Domain approval packet with exact store/writer/reader diffs, source checker results and quoted decision.

**Authority:** Existing domain owner/operator approval; no invented sign-off, new writer, data authority or capability scope from a form.

**Validation:** Existing data-source-authority and contract manifest checks; one-writer census, reader closure and dictionary/freshness evidence.

**Preview and verification:** Show proposed versus approved versus effective after release; preserve decision ledger provenance and exact source hashes.

Evidence: [data_source_authority.py:55](../../scripts/lib/data_source_authority.py#L55), [OpsControls.tsx:763](../../apps/command-center-v3/src/pages/OpsControls.tsx#L763), [work_pipeline_tier2.py:338](../../scripts/lib/work_pipeline_tier2.py#L338).

### F07 — LLM process caps, models and routing (16 paths)

Source examples: `config/cio_llm_policy.yaml`, `config/cloud_consensus_policy.json`, `config/coder_backends.json`, `config/inference_layers.yaml`. All paths are in the census.

**Current writer:** The operator Telegram callback invokes llm_cap_admin.set_caps with a DB connection: DB first, then registry, with explicit partial failure. Without conn the helper changes registry only; other routing/model policy is versioned source.

**Reader evidence:** llm_model_registry.load_registry and cio_governed_model_bridge.load_routing_policy_document; per-file references retained.

**Current coverage/gap:** Cap editing already exists in the operator Telegram callback, but is absent from the four-key Ops Controls catalogue. Reuse its cap-admin owner, not a second writer.

**Proposed modal:** Process budget cap modal and routing/model source proposal with source/DB parity panel.

**Authority:** Existing process owner/model-choice approval and cost governance. No API-key fields, provider credentials or universal paid fallback.

**Validation:** Known registered process/model, finite positive bounded caps; existing admin bounds, governed bridge route tests and budget parity.

**Preview and verification:** Show source+DB before/after, daily estimate and affected callers; partial DB_UPDATED_REGISTRY_FAILED stays partial until deliberately reconciled.

Evidence: [run_telegram_callback_poller.py:750](../../scripts/run_telegram_callback_poller.py#L750), [llm_cap_admin.py:96](../../scripts/lib/llm_cap_admin.py#L96), [llm_model_registry.py:61](../../scripts/lib/llm_model_registry.py#L61), [cio_governed_model_bridge.py:505](../../scripts/lib/cio_governed_model_bridge.py#L505).

### F08 — Search providers and public-data routing (6 paths)

Source examples: `config/alpha_vantage_owner.json`, `config/candidate_sources.yaml`, `config/cio_research_source_catalog.json`, `config/provider_cost_call_sites.json`. All paths are in the census.

**Current writer:** Reviewed source definitions; existing source/provider owner retains runtime budget-ledger ownership.

**Reader evidence:** search_routing_policy.load_policy/validate_policy and source authority provider resolution.

**Current coverage/gap:** No matching setting key or Ops Controls path-edit kind.

**Proposed modal:** Provider fallback and budget-share proposal with free-first order and caller-class coverage.

**Authority:** Domain/provider owner sign-off; credentials remain in sanctioned vault lifecycle, never copied into this form.

**Validation:** Existing routing-policy validator and source-authority relationship; provider/caller enumeration and bounded monthly cost.

**Preview and verification:** Show route order, applicable call classes and projected budget share; read back selected route and actual consumer receipt.

Evidence: [search_routing_policy.py:35](../../scripts/lib/search_routing_policy.py#L35), [search_routing_policy.py:61](../../scripts/lib/search_routing_policy.py#L61).

### F09 — Notifications and incident fan-in (9 paths)

Source examples: `config/cio_notification_policy.json`, `config/comms_categories.yaml`, `config/comms_email_mirror.json`, `config/delivery_provenance_quarantine.json`. All paths are in the census.

**Current writer:** Versioned notification/route policy; notifier and gateway own runtime delivery/dedupe stores.

**Reader evidence:** incident_flood_policy.load_policy/apply_fanin_policy and per-file comms references.

**Current coverage/gap:** Ops Controls has no route/category/dedupe policy editor; this is distinct from delivery dashboards.

**Proposed modal:** Alert-routing proposal with synthetic failure→incident→intent→delivery preview and protected P1 path.

**Authority:** Communications owner/operator; comms gateway remains sole sender. Editing policy does not authorize sending a message.

**Validation:** Known destinations/categories, no secret identifiers in preview, P1 bypass and dedupe/recovery notification fixtures.

**Preview and verification:** Show sample synthetic incident, routing/escalation/dedupe outcome and no-send preview; actual approved send/readback is separate evidence.

Evidence: [incident_flood_policy.py:49](../../scripts/lib/incident_flood_policy.py#L49), [incident_flood_policy.py:203](../../scripts/lib/incident_flood_policy.py#L203).

### F10 — Monitoring, bounded recovery and host health (19 paths)

Source examples: `config/active_trader_motion_watchdog.json`, `config/behavioral_detection.json`, `config/cio_health_snapshot_feed.json`, `config/data_plausibility_contracts.json`. All paths are in the census.

**Current writer:** Reviewed recovery/monitor policy; runtime incident/fixer owners retain their existing append-only job and receipt writes.

**Reader evidence:** self_heal_fixer.admit/build_evidence and per-file monitors/health-check references.

**Current coverage/gap:** Health display exists elsewhere; Ops Controls does not offer structured recovery-policy editing.

**Proposed modal:** Monitor/health-contract and bounded-recovery proposal with allowed actions, exclusions, limits and escalation.

**Authority:** Existing recovery owners and grants; LLM diagnosis remains advisory unless an already admitted bounded action is authorized. No arbitrary shell or broker repair.

**Validation:** Finite bounds, allowlisted action IDs, retry/side-effect classification, protected processes and refusal preservation.

**Preview and verification:** Synthetic failure scenarios show diagnosis and permitted action; proof needs failure→incident→notification and output recovery, not empty dead letters.

Evidence: [self_heal_fixer.py:237](../../scripts/lib/self_heal_fixer.py#L237), [self_heal_fixer.py:343](../../scripts/lib/self_heal_fixer.py#L343).

### F11 — Retention, backup and disk hygiene (12 paths)

Source examples: `config/advisory_kb_lessons_retention.json`, `config/backup_coverage_manifest.json`, `config/backup_policy.yaml`, `config/cio_provider_journal_retention.json`. All paths are in the census.

**Current writer:** Versioned policy; registered retention/backup tools operate their own data, not a free-form delete action.

**Reader evidence:** check_retention_policy.validate and db_retention/disk hygiene/backup source references.

**Current coverage/gap:** No typed retention/backup editor in Ops Controls.

**Proposed modal:** Retention-window and backup-coverage proposal showing archive/restore plan and affected stores.

**Authority:** Store owner/operator; financial/audit evidence minimums preserved; destructive changes retain their existing approval/grant boundary.

**Validation:** Existing retention validator/deleter census, finite age/size bounds, writer-safe rotation and restore-fixture proof.

**Preview and verification:** Dry-run counts/bytes and retention windows, preserved audit lineage, backup manifest+restore proof; no deletion while previewing.

Evidence: [check_retention_policy.py:44](../../scripts/check_retention_policy.py#L44), [check_retention_policy.py:174](../../scripts/check_retention_policy.py#L174).

### F12 — Hermes research configuration (32 paths)

Source examples: `config/advice_digest.yaml`, `config/advisory_desk.yaml`, `config/aec_agent_mesh.json`, `config/aec_narrator.yaml`. All paths are in the census.

**Current writer:** Reviewed research source; family-specific automated writers must be attested from the per-file reference census before any editor is enabled.

**Reader evidence:** Research source references in census; api_v2._llm_health reads sanitized research budget policy (read-only).

**Current coverage/gap:** Some research pages expose health, not general configuration editing; no broad Ops Controls kind.

**Proposed modal:** Research agenda, scope and budget proposal; score/model/scope changes require their named owners.

**Authority:** Research owner approval; model/financial influence choices are not inferred from the broad request for modals.

**Validation:** Per-file schema, governed model/source restrictions, market-day schedules and no unintended financial influence.

**Preview and verification:** Show source revision, ownership, affected research lanes and output consumers; effective state only after reviewed release and readback.

Evidence: [api_v2.py:14161](../../scripts/api_v2.py#L14161).

### F13 — Agents and development governance (22 paths)

Source examples: `config/agent_claim_shared_paths.json`, `config/agent_clients.yaml`, `config/agent_discovery_config.json`, `config/agent_maturity_catalog.json`. All paths are in the census.

**Current writer:** Reviewed source/policy packages; existing claim/design/work pipelines own their own runtime ledgers.

**Reader evidence:** Agent runtime/governance source references in census; existing Work board is not an arbitrary policy editor.

**Current coverage/gap:** Claims/design approval controls exist; protected policies/hooks and agent permissions remain separate reviewed changes.

**Proposed modal:** Agent-runtime configuration proposal; protected policy edits produce the existing operator package/PR workflow.

**Authority:** Existing policy authority and per-PR approval; no hook/grant/permission expansion by broad config editing.

**Validation:** Known agent/client/model schema, dependency closure and required policy-specific tests; never grant by environment assertion.

**Preview and verification:** Show scope/permission delta, exact package digest and reviewer requirements; operator owns apply/ratify/merge.

Evidence: [work_pipeline_tier2.py:198](../../scripts/lib/work_pipeline_tier2.py#L198), [ops_controls_core.py:244](../../scripts/lib/ops_controls_core.py#L244).

### F14 — Watch and momentum/scalp configuration (19 paths)

Source examples: `config/calibration_shadow_harness.json`, `config/cio_prospect_watchlist_rules.json`, `config/finviz_momentum_scalp_screen.yaml`, `config/held_position_alerts.json`. All paths are in the census.

**Current writer:** Versioned strategy/alert configuration; two catalogue thresholds are stored but explicitly not wired. Existing execution-engineering ownership remains.

**Reader evidence:** Watch/scalp/screener source references in census; the declared Active Trader threshold consumer is momentum_alerts.py.

**Current coverage/gap:** Two Active Trader threshold forms exist but are not effective. No broad setup/screen/alert-policy editor in Ops Controls.

**Proposed modal:** Advisory screen/alert threshold proposal with five-pillar evidence, catalyst provenance and stage/readiness preview.

**Authority:** Named setup/strategy owner and required execution-engineering grant before touching execution-related consumers; advisory config cannot clear order/2FA boundaries.

**Validation:** Existing setup/evidence tests, finite values, source freshness, catalyst validity and alert/consumer correlation; no label becomes GO by editing the UI.

**Preview and verification:** Show synthetic symbol outcome before/after, source inputs and alert effect; display unwired or stale consumers as not effective.

Evidence: [ops_controls_core.py:532](../../scripts/lib/ops_controls_core.py#L532), [OpsControls.tsx:637](../../apps/command-center-v3/src/pages/OpsControls.tsx#L637).

### F15 — Finviz screens and market calendars (3 paths)

Source examples: `config/finviz_screen_registry.yaml`, `config/macro_calendar_overrides.json`, `config/screener_schedule.yaml`.

**Current writer:** Registry source edits; finviz_screen_compiler.upsert compiles approved screen definitions into its database owner path.

**Reader evidence:** finviz_screen_compiler.load_registry/compile_screen and finviz_registry_reconcile.load_canonical_ids.

**Current coverage/gap:** No canonical screen editor in Ops Controls; database output is derived from source.

**Proposed modal:** Screen definition/compiler preview with source-of-record and compiled-diff panels.

**Authority:** Screen/data owner; invoke existing compiler owner after reviewed source, never directly edit the derived table.

**Validation:** Compiler governance/token validators, allowed screen fields, exchange calendar/timezone and no credential/provider mutation.

**Preview and verification:** Show source→compiled screen/filter diff, affected feeds and expected next refresh; verify DB/compiler/source parity after approval.

Evidence: [finviz_screen_compiler.py:72](../../scripts/finviz_screen_compiler.py#L72), [finviz_screen_compiler.py:122](../../scripts/finviz_screen_compiler.py#L122), [finviz_registry_reconcile.py:105](../../scripts/finviz_registry_reconcile.py#L105).

### F16 — Asset, account display and reference metadata (11 paths)

Source examples: `config/account_display_names.json`, `config/asset_classification_rules.json`, `config/etf_classification_overrides.json`, `config/etf_fund_universe.json`. All paths are in the census.

**Current writer:** Versioned reference source; domain owners must confirm any generator before a write form is admitted.

**Reader evidence:** account_display._load for account names; other per-file references retained in census.

**Current coverage/gap:** Account labels are shared display helpers; no general taxonomy/reference-file mutation kind exists.

**Proposed modal:** Reference-data proposal with names-only account labels, stable identity keys and affected-reader preview.

**Authority:** Domain owner/operator. Names do not change account identity, broker capability, position facts or trading authority.

**Validation:** Schema/identity/parity checks, no account-number display, no many-to-one identity collapse and no invented provider facts.

**Preview and verification:** Show exact field/identity delta and impacted readers; source SHA and consumer readback after release.

Evidence: [account_display.py:32](../../scripts/lib/account_display.py#L32), [account_display.py:52](../../scripts/lib/account_display.py#L52).

### F17 — Host service and timer definitions (149 paths)

Source examples: `config/systemd/agent_runtime/README.md`, `config/systemd/agent_runtime/tradeai-agent-runtime@.service`, `config/systemd/agent_runtime/tradeai-agent-runtime@.timer`, `config/systemd/chatgpt-oauth-proxy.service`. All paths are in the census.

**Current writer:** Reviewed unit definitions plus operator install/enable/restart commands; existing Controls restarts only its configured live-list units.

**Reader evidence:** Systemd host loads installed definitions; installed parity is NOT_MEASURED in this source-only package.

**Current coverage/gap:** No arbitrary systemd unit/timer editor; live-list restart is a narrowly configured existing effect.

**Proposed modal:** Installed-versus-source unit/timer proposal with static service allowlist and exact install packet.

**Authority:** Host operator/service owner; no arbitrary unit name, ExecStart, shell, sudo or broad restart from a form.

**Validation:** systemd verify/fixture checks, source/current closure, explicit unit-name allowlist and singleton schedule authority.

**Preview and verification:** Source+installed digest, next fires and restart impact; installation/enablement has separate operator readback.

Evidence: [ops_controls_core.py:372](../../scripts/lib/ops_controls_core.py#L372).

### F18 — Financial, broker and execution policy boundary (71 paths)

Source examples: `config/TRADE_AI_STRATEGY_PLAYBOOK_v1.0.md`, `config/account_capabilities.json`, `config/atm_config.yaml`, `config/cio_situations.yaml`. All paths are in the census.

**Current writer:** Existing reviewed financial/strategy/account owners; this design neither reads their values nor changes their writers.

**Reader evidence:** Only filename/source-reference metadata is inventoried; broker code was excluded from the source scan.

**Current coverage/gap:** Existing execution desks/approval controls are not authorization for a generic financial-policy editor.

**Proposed modal:** Read-only policy dossier and request for a separately scoped design/grant; no generic apply form.

**Authority:** HELD: explicit financial/strategy/account owner decisions and named execution-engineering authority as applicable.

**Validation:** Owner defines the applicable financial/regression contract; no direct JSON overwrite, order, stop or account-capability change.

**Preview and verification:** Metadata/digest/owner only until separately authorized; evidence cannot be fabricated by a design preview.

Evidence: [ops_controls_core.py:240](../../scripts/lib/ops_controls_core.py#L240).

### F19 — Credentials, authentication and trust anchors (3 paths)

Source examples: `config/cc_auth.yaml`, `config/egress_sanitiser_policy.json`, `config/secret_registry.yaml`.

**Current writer:** Existing vault, passkey and operator authentication lifecycle; secret values were not read.

**Reader evidence:** Only path metadata and public Ops Controls lifecycle source are used.

**Current coverage/gap:** Passkey add/revoke already exists; it does not authorize a secret-value file editor or trust-anchor changes.

**Proposed modal:** Credential-reference/expiry/status dossier with existing vault and passkey lifecycle links; no secret fields.

**Authority:** HELD for new authority: operator only, fresh assertion where already required; never put secrets in previews, docs or audit text.

**Validation:** Reference/type/expiry metadata only; no retrieval, export, browser-cookie read or credential replacement in this design.

**Preview and verification:** Redacted metadata and sanctioned health receipt, never credential material; rotation remains the existing authenticated lifecycle.

Evidence: [ops_controls_core.py:262](../../scripts/lib/ops_controls_core.py#L262), [ops_controls_sudo.py:53](../../scripts/lib/ops_controls_sudo.py#L53).

### F20 — Schemas, CI metadata, examples and generated baselines (698 paths)

Source examples: `config/active_trader.stage0.example.yaml`, `config/active_trader_compliance_fixtures.example.json`, `config/active_trader_flags.example.json`, `config/active_trader_near_ready_fixtures.example.json`. All paths are in the census.

**Current writer:** Registered generator/developer review, not an operational runtime form. A crontab backup is evidence, not a trigger to restore wholesale.

**Reader evidence:** CI/schema/tooling consumes these; many readers use directory enumeration rather than filename literals.

**Current coverage/gap:** No operator configuration gap is inferred just because a build artifact lacks a modal.

**Proposed modal:** Read-only catalogue with generator/validator links and source-change request when appropriate.

**Authority:** Existing developer/policy authority; do not widen baselines or schemas through generic runtime controls.

**Validation:** Canonical generator/schema checks and source review; generated output follows its owner rather than becoming a second writer.

**Preview and verification:** Show generator identity and source digest; do not treat generated metadata as current runtime health.

Evidence: [ops_controls_core.py:244](../../scripts/lib/ops_controls_core.py#L244).

## Concrete mockups and verification

Open the [offline interactive modal design](packets/ops-config-modals-20261024-wp34/modal-mockup.html).
It contains typed examples for the threshold, native schedule/calendar, DRAFT health
contract, LLM process caps and retention cases. Other families request owner/schema
attestation; financial, authentication and generated metadata dossiers have no editable
value fields. All values are labelled synthetic. Apply is disabled throughout, and the
prototype contains no network, credential or runtime mutation implementation.

- [Budget modal — desktop](packets/ops-config-modals-20261024-wp34/mockup-budget-desktop.png)
- [Native schedule modal — phone](packets/ops-config-modals-20261024-wp34/mockup-schedule-mobile.png)

The static validator verifies all 1,110 paths exactly once, family membership, 47 curated
source anchors, 2,027 literal-reference anchors, the public catalogue and registered
PROPOSED phases. The offline browser proof checks invalid threshold/cap values, preserved
DRAFT status, required DB/registry readback, native schedule proposal, no phone page
horizontal scroll, protected read-only dossiers, disabled Apply, no browser errors and zero
network requests. It uses a local file, not the live server.

To reproduce the static proof:

```bash
cd /home/johnclaw/wt-codex-wp34-20261024
/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python docs/ops/packets/ops-config-modals-20261024-wp34/validate_inventory.py
```

The packet's VERIFICATION.json pins source/base identities and proof hashes. It does not
claim live configuration census, current consumer readback, accepted financial policy,
credentials, deployed forms or approval of any implementation phase.

## Proposed phases and remaining decisions

The registered design is
[DSN-20261024-ops-config-modals](../designs/DSN-20261024-ops-config-modals.md):

1. **P1 — this proposal:** source inventory, mapping, concrete mockups and evidence.
2. **P2 — operator selects the first family:** attest each field's owner, original writer,
   public reader, schema/bounds, reload mechanism and effective readback. Resolve dynamic
   loaders and generated files explicitly. Unsupported/unowned fields stay read-only.
3. **P3 — separately approved implementation:** register exact source tasks/file/grant scope,
   implement one adapter, test refusal/stale/duplicate/partial outcomes and consumer adoption,
   then coordinator CI/merge/release and authorized operational verification.

No implementation phase is approved by this proposal. The operator can review the mockup
and select a first family through the existing design-approval process. This avoids a new
writer, an inert override presented as effective, and a broad file editor that bypasses the
project's existing source, financial, credential or review authority.

Publication remains queued as the single WP-34 PUSH_NEEDED command in PROGRESS_LOG.md.
The worker retains the claim and does not push, merge, release, approve or apply changes.
