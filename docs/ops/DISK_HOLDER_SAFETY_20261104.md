# Disk hygiene — why rule R reports releases instead of deleting them (2026-11-04)

**Decision (a), lead ruling 2026-11-04, taken after codex's R3a/R3b block on `302b34483`:** the scheduled lane never
removes a release directory, through any path, under any mode, with any file present. It reports the reclaimable set,
with bytes. There is NO one-shot exception: a value object can bind to a target's metadata, but it cannot distinguish
agent intent from operator approval, because the process that can read the target can also write the approval. A
constrained namespace is not an authority boundary.

This document records the argument, the mechanism that replaced the fence's claim, and the residual that no code in
this repository can close.

---

## 1. The two counterexamples that forced the decision

Both were reproduced by codex at `302b34483` against the real source, with synthetic children under an owned root.

**R3a — holder existence was conflated with holder naming.** `proc_holder_units` collected cgroup names ending
`.service`. A process holding the release from a valid `session-77.scope` produced `units=(), complete=True` — the
scan's own word for "nobody is there" — and `rmtree` deleted the directory. The kernel had moved that process's cwd
to the fenced name, so the post-rename scan *did* look at the right path; it simply had nothing to collect.

**R3b — a retained directory descriptor bypasses any pathname fence.** A native child opened a descriptor to the
release through the original name, stayed outside the path during both scans (so both returned
`complete=True, units=()`), then `fchdir`-ed through that descriptor at the `rmtree` boundary. `/proc/<child>/cwd`
pointed inside the fenced directory immediately before it was deleted. The fence stops *lookups* by name; it cannot
stop a reference that was taken before the name changed.

## 2. Why the fence cannot be repaired into a proof

POSIX has no "unlink only if nothing holds this" primitive. `rmdir`/`unlinkat` succeed on a directory that is a
process's cwd or the target of an open descriptor. Every check available to us is a **scan** — a snapshot — and the
distance between the last scan and the unlink is unbounded. QUIESCENCE CANNOT BE ENFORCED here for two concrete
reasons:

1. **The holders are not ours to stop.** Agents, shells and helpers run as the same uid. Freezing or signalling them
   is neither authorised (AGENTS.md §24.10 is markets-closed *ops units* only) nor safe.
2. **A cooperating restarter is not a quiescence proof.** Restarting a `systemctl --user` unit clears one named
   holder; it says nothing about the thousands of same-uid processes that could open a descriptor in the next
   microsecond.

So option (b) in the lead's note — "deletion requires an enforceable quiescence window" — has no implementation on
this host. The honest disposition is (a): refuse, and report.

## 3. What the code does now

* `proc_holder_units` returns `HolderScan(units, complete, holders, unattributed)`:
  * `holders` counts processes whose **cwd or any descriptor** is inside the path — existence is tracked
    independently of naming (R3a);
  * descriptors are read, with the kernel's ` (deleted)` suffix stripped (R3b);
  * `unattributed` names holders for which no restartable `.service` unit exists — always a refusal;
  * `complete=False` for any same-uid process we could not look at.
* `remove_item` refuses when `holders` is non-zero — not only when `units` is non-empty — both after a restart and
  after the fence rename.
* `_release_rows` marks every release row `candidate=False` with
  `release_delete_refused:no_enforceable_quiescence_primitive`; it never orders a restart when it is not removing. The
  bytes stay in the manifest's `excluded` set, so the operator digest still shows what the lane would free.
* The LEGACY `plan()` path runs the same refusal (`refuse_release_removals`), because it used to select releases
  itself — the default report path being safe said nothing about the old entrypoint (codex 2026-11-04).
* `remove_item` refuses EVERY release, unconditionally: `kind == "release_dir"`, `rule == "R"`, a path inside a
  configured release root — under any other `kind` — and, fail-closed, any directory removal when the release
  namespace was never loaded (`_RELEASE_ROOTS` empty). There is no arming argument and no callable deletion helper.

The scan is still worth having: it names the component that resolves a superseded release (the 12-hour
`tradeai-ops-agent` resurrection), and it refuses the deletion boundary if the operator ever arms it.

## 4. What remains unproven, stated plainly

A process that opens a descriptor **after** the last scan and `fchdir`s before the unlink is invisible to any
external check. This is why the scheduled lane does not delete: the residual is a race, not a bug, and a lane that
cannot state the invariant should not perform the operation. `auto_delete=true` therefore buys back the fence and the
full scan, not a proof; an operator who arms it is accepting that residual.

## 5. Operator-facing consequences (needs a ruling, not an implementation)

The operator's 2026-11-04 instruction "remove the superseded ones on every release" is **now report-only**. That is
a capability change, made because the finding wins (AGENTS.md §0 rule 10). Reclaimable bytes appear on every run; the
deletion itself needs either:

1. an explicit repeat of the instruction with this document's residual accepted, or
2. a mechanism that can prove the invariant (a helper that owns the directory from creation, so no uncooperative
   descriptor can exist — not available for releases that already exist).

Until one of those arrives, the growth-rate guard is the useful signal: superseded releases accumulate and the
digest names them.
