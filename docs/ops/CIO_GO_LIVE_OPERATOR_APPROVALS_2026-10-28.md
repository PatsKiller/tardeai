Status: ACTIVE
as_of: 2026-10-28T21:31:00Z
Canonical repo path: docs/ops/CIO_GO_LIVE_OPERATOR_APPROVALS_2026-10-28.md
Authority: §17 operator-only gates — the three "on-switches" that were never flipped
See also: docs/audits/CIO_READINESS_GO_LIVE_AUDIT_2026-10-28.md

# CIO review go-live — the three operator approvals (one page, no jargon)

## In plain English

The CIO review system was built, but three "on-switches" were never turned on. An AI agent is not allowed to
flip them — that is the safety rail working, not the system stalling. This page is the whole list of what needs
**you** (the operator). Everything else is code, already being built by agents.

The three switches, in the order they must happen:

## 1. Create the CIO database table (grant the `cio_prospect` row + apply the migration)

**What it is:** today the CIO's per-symbol decision ("WATCH", conviction, next action) is computed but stored in a
"shadow" file, not the real database. The real table was designed but never created.

**The two acts (both yours):**
- **Grant** the `cio_prospect` registry row in `config/data_source_authority.json` (it is `PROPOSED`, approval
  pending). This is a §17/§7A data-source grant.
- **Apply** `migrations/2026_10_22_cio_prospect.sql` to the production Postgres, off-peak. This is the DDL that
  creates the table.

**Why you, not the agent:** creating the authoritative store and granting the data source is on the operator-only
list (§17). An AI must not unilaterally decide "the CIO's database is now live."

## 2. Turn on saving (set `TRADEAI_CIO_PROSPECT_PG_DUAL_WRITE=1`)

**What it is:** the writer has a safety switch that is OFF by default. With it off, the writer returns before
saving anything — which is why decisions never land anywhere permanent.

**The act (yours):** set `TRADEAI_CIO_PROSPECT_PG_DUAL_WRITE=1` in the host environment for the units that run
`cio_prospect_writer` and the prospect shadow build (a host config change — §17).

**Why you, not the agent:** host environment / config changes are operator-gated. This is the exact switch that
stops an AI from silently enabling a production write path.

## 3. Turn on the conflict rulebook (`config/conflict_rulebook.json`)

**What it is:** the rulebook that decides, when two desks disagree (e.g. `WATCH` vs `ENTRY_NEAR`), which one wins.
It exists but is `"status": "PROPOSED"`, `"live_enabled": false`, `"approval": null` — i.e. draft mode.

**The act (yours):** approve activating it (flip `live_enabled: true`, set `status`, record the approval). The
code that *reads* it and applies it to the Watch page is a separate agent PR.

**Why you, not the agent:** the conflict rulebook is operator-approved policy (§28.10). An AI must not pick, on its
own authority, which of two desks is "right."

---

## What depends on what (so you can see the whole path)

```
[1] grant + migrate  ─┐
[2] dual-write on     ─┴─►  THEN  point Watch at the canonical resolver (agent PR, waits on 1+2)
[3] rulebook on            ─►  wire the conflict engine into Watch (agent PR, waits on 3)
```

## What the agents are doing right now (no approval needed)

- Build `watch_review_status.py` (fixes "review outcome never reaches the row").
- Add the Watch STALE badge (stale reviews stop looking current).

## Honesty

None of the three switches is flipped yet. Until they are, the CIO review system will keep showing the symptoms in
the audit: parallel truths, stale reviews, "conflict ledger not yet produced." The moment you approve these three,
the already-written code can be turned on and the symptoms clear.
