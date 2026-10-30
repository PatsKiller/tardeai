# Disk recovery investigation, October 30

Status: IN_PROGRESS — reporting repair; reclaim and activation remain incomplete
Owner: platform / operator
as_of: 2026-10-30
Measured at: 2026-10-30T15:15:02Z unless a different interval is stated
Design: DSN-20261030-disk-recovery

## What happened

The root filesystem grew from about 80% to almost full over five days. The working legacy
release pressure cleaner was retired before the reviewed replacement had an active apply mode.
Growth began before that retirement, so it is a contributor rather than the sole initial cause.

| UTC | Root use, used / (used + available) |
|---|---:|
| October 25, 16:45 | 79.88% |
| October 26, 15:00 | 88.49% |
| October 27, 15:00 | 93.24% |
| October 28, 15:15 | 95.80% |
| October 29, 19:45 | 99.75% |
| October 30, 15:15 | 97.24% |

OBSERVED: the existing pressure-guard receipt history records these measurements. Over the exact
October 28 15:15 to October 30 15:15 window, net usage increased 6.37 GiB despite two manual
reclaims totaling 31.59 GiB. This establishes **at least 37.96 GiB of new allocations**, not total
write traffic. During the same window, 30 prepared release directories account for 31.82 GiB
of directory allocation: 25.38 GiB subsequently removed and 6.43 GiB still present. These figures
are already part of the allocation accounting and must not be added to it again. Release preparation
copies files; repeated preparations of the same commit also consume space.

OBSERVED over a different, longer interval, October 25 08:00 to October 29 19:44: cache usage grew
43.30 GiB and local database-backup usage grew 11.29 GiB. These are not 48-hour category deltas.
Current file birth/modification times do not establish historical net growth. The largest old scratch
families predate the 48-hour window; the 36.38 GiB model blob store predates October entirely.

## Cleanup and monitoring gaps

1. The pressure cleaner last removed a release on October 28 at 06:39 UTC. The release containing
   PR #2259 was first verified at 14:53:43 UTC; the guard reported plan-only at 14:55:43 UTC.
   The retirement obeyed the single-deleter rule but left an operational gap.
2. The active n8n disk monitor runs every 15 minutes. Its `--apply` updates monitoring state and
   queues alerts; it does not reclaim files. The active disk-hygiene lane runs a weekly `--plan`.
   The disabled standing proposal is not an operative cleanup schedule.
3. The old backup cap keeps one top-level full dump by moving older dumps into `archive`.
   That move releases no blocks on the same filesystem. The cap excludes the archive and recovery holds.
4. The disk monitor silently dropped timed-out category measurements and refreshed categories only
   on a threshold-band change. A large unmeasurable cache could disappear from the alert while the
   server stayed critical. Unknown must be reported as unknown, with a timestamp.
5. Two backup-current JSON writers truncated their destination before publication. An ENOSPC failure
   could erase the last good receipt. They must use the existing atomic JSON writer and propagate failure.

The P1 source repair addresses items 3–5 as reporting/durability defects. It does not activate cleanup,
remove any archive, or restore the retired deleter.

## Database retention

OBSERVED from nightly outputs: the main retention step deleted 266,486 rows on October 26. It
skipped October 27–29 because free space was below its safety floor, deleting zero rows on those
runs. The separate document-mention pruner still removed 1,089, 860 and 826 rows respectively.
The recorded primary-database size rose from 16.81 decimal GB on October 27 to 17.36 GB on
October 29, about 0.51 GiB. This does not measure cluster WAL or other databases.

OBSERVED: the October 30 nightly timer fired at 01:15 ET; its service exited 1 before leaving a
new run receipt. The specific startup failure is UNKNOWN. A stale October 29 receipt is not proof
that scheduling stopped. Restore disk headroom before verifying retention again; do not bypass
its disk guard. Ordinary deletion and vacuum generally make database space reusable internally;
a disk-pressure incident is not a reason to start a space-consuming full rewrite
([PostgreSQL vacuum documentation](https://www.postgresql.org/docs/17/routine-vacuuming.html)).

## Reclaim completed and still proposed

OBSERVED: the operator's native October 30 apply reclaimed 16.17 GiB, removing 18 items and
skipping one permission-denied item. The receipt is
`data/runtime/disk_hygiene/disk_hygiene_apply_20261030T140812Z.json` under persistent-state.
An October 29 operator apply had already reclaimed 15.42 GiB. Do not reapply those completed manifests.

The filesystem is about 468 GiB total. At the observation point, reaching 70% needs approximately
120 GiB more reclaimed. Another 50 GiB would leave use around 86%; 500 GiB cannot be reclaimed
from this filesystem. Estimates must distinguish allocated blocks from logical size and shared Git objects.

The private expanded Git inventory, rebuildable-cache proposal and conditional old-dump proposal
are **not an apply-ready manifest**. The live seven-day selector found no additional Git candidates.
A proposed 48-hour selector must preserve clean/pushed/merged checks, claim and open-PR protections,
credential exclusions and complete host-reference checks. An open PR already holds one proposed tree.
Neither its age nor the fact that HEAD is merged proves an entire working directory is expendable.

The archive proposal cannot be treated as approved retention: backup directories are currently
never-touch under §24.12, recovery holds have tripwires, and an encrypted object existing off-box
does not prove restoration coverage. Two retained dumps passed gzip integrity checks; no restore was
performed. The ordinary dump excludes some table data, so complete recovery coverage must be established.

## Decisions and acceptance still required

The following registered P2 tasks remain open:

- **P2-T1:** review a release-only standing rule and its first live apply through the native lane.
  Preserve CURRENT, actual previous release, newest retained releases, all active references and
  complete host process visibility. Coordinate with the release lock. The existing broad A/S/W
  proposal must stay disabled; it is not a shortcut to a conforming release-only rule.
- **P2-T2:** decide backup archive retention and recovery coverage, including any required policy
  amendment. Preserve current dumps, recovery holds and migration snapshots until that decision.
- **P2-T3:** obtain root-only Docker/cluster sizes, verify the next main retention outcome, verify
  real reclaimed blocks and the next cleanup receipt, and measure the sustained growth rate.
- **P2-T4:** replace upload-success masking with uploaded-object evidence. Current upload stamps
  alone are insufficient proof because a failed command can be masked.

No production deletion, rule change, timer edit, service activation, database purge or restore is
performed by P1. Source tests and static proof do not establish a live cleanup repair. The incident
remains open until real headroom, cleanup operation and retention progress are observed.
