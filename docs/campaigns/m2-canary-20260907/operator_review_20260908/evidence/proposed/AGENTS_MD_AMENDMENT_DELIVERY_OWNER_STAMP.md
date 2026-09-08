# PROPOSED amendment to AGENTS.md — delivery_owner stamp on settle

**Status:** PROPOSED (not applied)  
**Effective-Date:** PENDING operator approval  
**Campaign:** m2-canary-20260907  
**Does not edit repo AGENTS.md in this change set.**

## Proposed addition (comms / delivery settlement)

> **`settle_delivery` must persist ownership into delivery coordinates.**  
> When settling a gateway (or owned) delivery, merge `delivery_owner` and  
> `gateway_mode` into `communication_deliveries.provider_coordinates` (JSON),  
> not only into ephemeral settle metadata or log lines. Soak and canary  
> collectors that gate on `delivery_owner=gateway` (plus PMID / SENT|SETTLED)  
> query `provider_coordinates`; omitting the stamp causes  
> `gateway_canary_delivery` **false negatives** even when Telegram delivery  
> succeeded. Landed in code via **PR #926** (`340aaf831…`); keep this rule  
> in AGENTS.md so future settle paths do not regress.

## Rationale

Stage-3 soak for m2-canary-20260907 failed closed on `gateway_canary_delivery`  
while controlled SETTLED proofs existed: settle wrote owner in-process but did  
not merge into `provider_coordinates`. PR #926 fixes the writer; live re-proof  
SETTLED pmid 51022 after promote. Without an AGENTS.md rule, a later refactor  
can drop the stamp and reintroduce silent soak failures.

## Approval

Operator must approve and merge into AGENTS.md (Policy-Version bump) before  
this text becomes ACTIVE. Until then, campaign evidence  
(`evidence/gateway_soak_gap_20260908/`, PR #926) governs ops.
