# C1 company-facts population operator packet

**Status:** PROPOSED; workflow inactive, registry NEVER_SCHEDULED; no live backfill or migration performed.
**Owner:** CIO/operator. Source task DSN-20261024-c1-company-populate-P1-T1.

The worker prepared source only. Apply this packet after coordinator merge/release. The single writer is the existing
InstrumentRecord facade, keyed by confirmed security_guid. It does not create a stance, conviction, prospect stage,
order, promotion, identity or second store. Missing issuer is explicit and permitted only for fact-only rows.

1. Review `migrations/2026_10_24_cio_company_facts_only.sql` and its SHA in `PACKAGE_HASHES.json`. It extends the existing
   table, keeping strict judged-prospect requirements. If PG dual-write is already enabled, this capability is required
   before any fact-only canonical append. The CLI refuses missing capability. This packet never toggles that flag.
2. Grant `state-write` for canonical InstrumentRecord append and the two latest receipt/report files. If existing PG
   dual-write is enabled, grant `db-write` for the named migration and same-table facts/events. These scopes grant no
   broker, order, credential, provider, model or scheduler operation. The operator reviews the exact SQL file before
   running it using the existing sanctioned DB administrator runner; no connection secret is included in this packet.
3. From the accepted CURRENT, inspect the dry-run, then perform the one-time backfill below. `--with-db` collects fresh
   SELECT-only membership/profile inputs in read-only transactions and stored holdings; it never calls a broker/provider.
   Do not feed the old proof capture to the live backfill.

```bash
cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/cio_company_facts_populate.py --dry-run --with-db --state-root /home/johnclaw/trade-ai-releases/persistent-state
/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/cio_company_facts_populate.py --apply --with-db --state-root /home/johnclaw/trade-ai-releases/persistent-state
```

Optional grant commands for the **operator** after reviewing scope (not run by worker):

```bash
bin/guard grant state-write --for 4h --uses 4 --reason "C1 company-facts backfill: existing GUID InstrumentRecord facts plus latest report/receipt only; no judgments or promotion"
bin/guard grant db-write --for 4h --uses 4 --reason "C1 reviewed fact-only migration SHA from PACKAGE_HASHES.json and existing gated cio_prospect/cio_prospect_events dual-write only"
```

4. Require exit0 plus `produced_count>0`, judgment_writes=0, prospect_promotions=0; inspect **every** gap and quality_status.
   The copy result is not a live acceptance count. Flag-off reports `NOT_REQUESTED_FLAG_OFF`; it never claims PG current.
   Requested PG failure remains a failed/partial run, even if JSONL appended. Repeating unchanged facts verifies PG equality;
   divergence is owner-held and is not silently repaired. Read FATN/ANET and a gap through the existing Watch broker and
   CIO/Ask consumers under sanctioned readback; compare GUID, original clocks and source refs, not cache build time.
5. Review `HEALTH_CONTRACT_DRAFT.json` with an actual reviewer/date/provenance; proposed weekdays06:35 and15:35 ET,
   one attempt, class learn, shared lane lock600s. 15:35 follows the nominal final15:25 Hermes trigger, but **completion
   ordering is not proven**. Decide whether the owner's contract needs causal completion gating instead. Maximum scheduled
   weekend gap is63h; provisional72/96h freshness bounds avoid false weekend failure, but do not prove weekday expected-fire
   coverage. Per-slot/calendar monitoring, alert delivery and observed baselines remain NOT_MEASURED until accepted.
6. Under exact `config-write`/`service` authority and native workflow activation authority, integrate the reviewed contract,
   `ALLOWLIST_PROPOSAL.json` and `REGISTRY_ACTIVATION_PROPOSAL.json` by keyed union into current operative configuration.
   Preserve all unrelated entries. Add only this lane to existing relay live admission if authorized; no policy widening.
   The proposed contract is not grandfathered. The source registry row is kind none until this is accepted.
7. Run existing import/framework activation checks with current sanctioned platform/runtime evidence. They must reject
   incomplete admission/evidence; do not weaken them. Import `workflow.json` **inactive** with the established n8n operator
   import procedure. Activation is a separate exact-workflow grant. Record the workflow ID/version, contract digest,
   accepted CURRENT SHA, admission receipts and actual activation time. There is **no legacy host schedule to retire**;
   do not add or edit crontab/systemd. Both proposed triggers are n8n-native Schedule Trigger nodes.
8. Run the exact accepted workflow form in its authorized window; correlate n8n execution → requested/started/finished host
   receipts → same-GUID facts → consumer readback → failure/quality notification proof. Do not call this proven from the
   source fixture. Stop only this workflow if its accepted runtime contract fails; preserve all canonical history.

The generated workflow uses existing RunLane and fabric-error subworkflows. It adds no retry loop, sender, arbitrary shell
or LLM. Latest report/receipt overwrite their own bounded files; the existing canonical JSONL/event history is retained.
`data_retention_policy.json` declares the existing CIO current/events tables KEEP_FOREVER; it authorizes no deletion.
