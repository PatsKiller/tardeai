# Relay live-set gate — operator runbook

**Applies to:** `scripts/lib/relay_live_set_gate.py`, `scripts/relay_live_set_gate.py`, the promote step in
`scripts/cio_phase2_exact_main_deploy.sh`, and the deploy poller hold in `scripts/lib/deploy_on_main.py`.

## What holds a promote
A release that would change which lanes the n8n relay runs live is held at promote until you acknowledge that exact
change. The change is named by a `diff_id` (a hash of the build and the lane delta). You get one P1 page per `diff_id`;
if that page is not accepted by Telegram, the next prepare pages again.

While held, the poller does not prepare again. On every tick it re-checks the held release against what CURRENT
serves: if the change is gone the hold clears by itself (`cleared_no_change`); if the change is different the hold
moves to the new `diff_id`, which needs its own acknowledgement. A main merge ends the hold (`superseded`).

## See the change (read-only, no page)
```
python3 <release>/scripts/relay_live_set_gate.py status --release <release>
```

## Acknowledge (operator only)
Issue a `release-write` guard grant whose reason contains `relay-live-set:<diff_id>`:
```
bin/guard grant release-write --for 1h --uses 1 --reason "relay-live-set:<diff_id> reviewed"
```
The poller resumes by itself on its next tick.

**The `--replace` trade-off.** Only one `release-write` grant is active at a time. If one is already active (for
example a release window you opened), the command above refuses unless you add `--replace`, and `--replace` closes
that active grant (status `replaced`). Your acknowledgement is not lost by that: a replaced or expired grant still
counts as the acknowledgement of its `diff_id`, as long as its window reached the moment the hold was recorded. What
you lose is the other grant's remaining release-write authority, which you re-issue if you still need it. Without `--replace`, the
other way is to let the active grant expire (or `guard revoke` it) and then grant.

**What never counts:** a revoked grant (revoking withdraws the acknowledgement), a grant for another `diff_id`, and a
grant whose window ended before the hold was recorded.

## Page markers (host state, never deleted)
`<persistent-state>/data/governance/relay_live_set_paged/`:
`<diff_id>-<event>.sending` (a send in progress), `<diff_id>-<event>.json` (paged, blocks further pages),
`<diff_id>-<event>.send_failed-<utc>.json` (a send that was not accepted; blocks nothing).
