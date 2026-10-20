# DRAFT: AGENTS.md PATCH for the motion marker path (not applied)

```
Status:      DRAFT (not applied; needs the operator's per-PR word to merge an AGENTS.md change)
as_of:       2026-10-19
```

**Status: DRAFT. Not applied to AGENTS.md.** This is a PATCH-level editorial correction under §20, outside §0, §2 and
§17. It rides `APPROVE_AGENTS_POLICY_1_2_0` and becomes ACTIVE on merge, but merging any `AGENTS.md` change needs the
operator's per-PR word (§23.13 excludes it from the standing merge approval). Apply it only **after** the operator
installs the fixed unit (`cutover.sh install --apply`). Until then, the item-4 measurement ("the motion unit's flag is
…") stays literally true of the installed unit.

## Proposed edits

1. **§24.10, item 4**, the last sentence. Here `<misspelt>` means `/etc/tardeai`:

   - from: ``measured 2026-10-10, the motion unit's flag is `<misspelt>/enable-active-trader-motion`.``
   - to: ``measured 2026-10-10, the motion unit's flag was `<misspelt>/enable-active-trader-motion`, a misspelt
     directory that never existed; from 2026-10-19 it is `/etc/tradeai/enable-active-trader-motion` (root-owned,
     operator-created; `docs/ops/packets/active-trader-motion-n8n-20261019/`).``

2. **§24.10, Cause note.** This is unchanged: it is history, and it quotes the unit as it was on 2026-10-10.

3. **Header and changelog.** Set `Policy-Version` to `14.0.1` and add a changelog row: "PATCH: §24.10 item 4 records
   the corrected motion marker path (`/etc/tradeai`); stale measurement only, no change to required behaviour; §0,
   §2, §2A, §7A, §17 and §23.14 byte-identical."

4. **Tests.** In `tests/test_agents_policy_5_0_0_execution_ops.py::test_24_10_permitted_actions_are_the_operator_list_and_nothing_else`,
   add `"/etc/tradeai/enable-active-trader-motion"` to the pinned fragments and keep the old literal. Any test that
   pins `Policy-Version: 14.0.0` moves to 14.0.1.

## Why it is not applied in this PR

- The brief says to draft rather than apply when an operator token is needed. A PATCH to AGENTS.md cannot merge
  without the operator's per-PR word.
- The measured statement is still true until the operator installs the fixed unit.
- A version bump touches every test that pins the version. That belongs in a docs-only PR the operator can approve
  on its own.
