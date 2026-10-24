# WP-33 item 5: exact-head PR stack triage

Status: REVIEW — six proven source duplicates closed; nine PRs retained; delivery publication pending
as_of: 2026-10-24T03:41:43Z
Measured at: main `325ff34f2b3b272090b78d5210a2847c8c30bd2a`; policy 20.1.0 ACTIVE; task `DSN-20261023-handoff-v3-P7-T335`

The audit closed **#1599, #1628 and #1804–#1807** after proving their accepted replacement changes are on main. Nine listed PRs remain open. Three others, #1879–#1881, were already closed by WP-03 and remain closed. This eighteen-PR denominator measures source housekeeping, not migrated lanes or production readiness.

No broker/order/stop source, grant authority, protected file, registry, allowlist, contract, schedule or runtime was changed. No PR was merged, no branch deleted and no release run. The audit did not query a live database, read credentials, run broker capability audits or consume grants.

## Disposition matrix

Full heads, file comparisons, checks and close readbacks are in the [evidence packet](packets/open-stack-triage-20261023/README.md).

| PR | Exact head prefix | Final disposition | Evidence / next action |
|---|---|---|---|
| [#1599](https://github.com/PatsKiller/tardeai/pull/1599) | `43422f605` | CLOSED, superseded | Integrated replacement `9bb8c147d`; strict unit delivered as an operator packet. Installation is separate and unmeasured. |
| [#1628](https://github.com/PatsKiller/tardeai/pull/1628) | `8e505c972` | CLOSED, superseded | Production deltas match `aa0b9b8d9`; original tests preserved. No grant operation. |
| [#1795](https://github.com/PatsKiller/tardeai/pull/1795) | `3a7fc9b0f` | OPEN, preserve B1 | Seven staged read/sync lanes; split exact closed-read candidates from excluded/nonmatching entries before a granted update. |
| [#1796](https://github.com/PatsKiller/tardeai/pull/1796) | `eedeeaaa2` | OPEN, preserve B2 | Seven stop/protection entries; stop writers remain excluded. The read-only stop-health script is only a name-level candidate. |
| [#1798](https://github.com/PatsKiller/tardeai/pull/1798) | `4a8c9845f` | OPEN, preserve B3 | Seven advisory/protection/wrapper entries; classify each under current authority with the owner before updating. |
| [#1799](https://github.com/PatsKiller/tardeai/pull/1799) | `779655353` | OPEN, preserve B4 | Seven paper/order-path entries; the read carve-out does not admit them. Preserve inert staging. |
| [#1801](https://github.com/PatsKiller/tardeai/pull/1801) | `b4513ccb0` | OPEN, preserve B5 | Seven options/market-data/daemon entries; daemon/wrapper and exact read-form boundaries need separate review. |
| [#1802](https://github.com/PatsKiller/tardeai/pull/1802) | `624c35ee1` | OPEN, preserve B6 | Six orchestrator/launcher entries; wrappers and proposal writers cannot be admitted as the closed read set. |
| [#1804](https://github.com/PatsKiller/tardeai/pull/1804) | `dde77d2b2` | CLOSED, superseded | First batch integrated as `ab741b0de` plus caller-token fix `7631eed0a`; key-based allowlist equivalence proven. |
| [#1805](https://github.com/PatsKiller/tardeai/pull/1805) | `eb64c276b` | CLOSED, superseded | Patch-equivalent accepted replacement `bb30d98d6`; seven incremental process records equal main. |
| [#1806](https://github.com/PatsKiller/tardeai/pull/1806) | `836e356cf` | CLOSED, superseded | Patch-equivalent replacement `146c5eb6b`; three incremental process records equal main. |
| [#1807](https://github.com/PatsKiller/tardeai/pull/1807) | `cb6dd1064` | CLOSED, superseded | Patch-equivalent replacement `de6dc89fb`; six incremental process records equal main. |
| [#1940](https://github.com/PatsKiller/tardeai/pull/1940) | `af24cde78` | OPEN, red / held | Recover failing gate details, then update under released config ownership; preserve three shadow and two inert/staged intents. |
| [#1350](https://github.com/PatsKiller/tardeai/pull/1350) | `ff911a4c3` | OPEN, historical repackage review | Unique September 28 audit document is not present by exact blob elsewhere on main; no supersession proof. |
| [#1351](https://github.com/PatsKiller/tardeai/pull/1351) | `a9fc1d042` | OPEN, historical repackage review | Unique follow-up document plus differing release-pin checker/test/runner changes; preserve until separately compared. |
| [#1879](https://github.com/PatsKiller/tardeai/pull/1879) | `acffb663b` | Already CLOSED | Head is a main ancestor; WP-03 previously recorded served ancestry. No repeated closure. |
| [#1880](https://github.com/PatsKiller/tardeai/pull/1880) | `3a794eb02` | Already CLOSED | Same source-ancestry verification; existing WP-03 disposition preserved. |
| [#1881](https://github.com/PatsKiller/tardeai/pull/1881) | `a6ed3ca5b` | Already CLOSED | Same source-ancestry verification; existing WP-03 disposition preserved. |

Fresh checks found **all nine retained PRs CONFLICTING/DIRTY**. Initial GitHub mergeability was UNKNOWN; the later observation is preserved alongside it. F09 and the six closed duplicates had all four required checks green on their historical exact heads. #1940 fails `cio-hardening` and `ci-gate`; #1350/#1351 do not report the now-required `ci-gate`.

## Supersession proof

The open original heads were not main ancestors and their whole changed files differ from current main. Those coarse checks alone did not justify closure. Accepted replacement commit ancestry and exact delta/state comparisons supplied the missing evidence:

- Main's `9decbb6e2` integration explicitly includes #1628, #1599 and #1804–#1807. All seven relevant replacement commits are main ancestors.
- LLM batch 1: all twenty-two matching source/test/process/routing deltas have equal stable zero-context patch IDs. The remaining allowlist delta comprises both planner records and the RI blocked reason; all three exactly equal current main. The caller max_tokens correction and batches 2–4 are patch-equivalent. All twenty-five incremental process rows exactly equal main. Existing downstream activation/seed work is not certified by source closure.
- #1628: all three production-file deltas match the accepted replacement. All twenty-three original test functions remain AST-identical on current main. The sole integration harness adjustment points `release_venv.sh` at the repository copy from the temporary fixture. No grant-binding rule was edited during this audit.
- #1599: all five helper functions at the original exact head remain AST-identical on main. The secret-name classifier and renderer also match by whole blob. Integration adds current nonsecret relay config names and preserves the current live-list environment file; the strict systemd artifact is intentionally an operator packet, with adjusted inventory/unit tests. Its source implementation is integrated; host installation remains NOT_MEASURED.

Before each closure, the audit rechecked OPEN state and the exact captured head, added its source-specific reason, closed without deleting the branch and verified CLOSED state with the same head. The six post-close receipts are committed in the packet.

## F09: precise remaining work

The six cumulative PRs contain **41 incremental staged lane records**: 7 + 7 + 7 + 7 + 7 + 6. None of those staged records exists on current main. Their historical policy text says 12.0.0 is PROPOSED; current policy is 20.1.0 ACTIVE and the 19.0.0 read carve-out is ACTIVE. That removes neither exact-argv nor capability/runtime conditions.

Only five proposed script names occur in the closed read set: four B1 names (Alpaca live read, moomoo live read, SnapTrade sync, positions sync) and B2's read-only stop-health reporter. This preliminary name comparison is not admission. The proposed dry-run forms, static closure, trading locks and Schwab read-only mode were not evaluated, and no broker source or runtime reader was executed.

Owner/coordinator next actions:

1. Separate the closed-read candidates from stop/order/paper/wrapper/daemon entries and from advisory entries needing their own class review. Keep the non-admitted staging inert; do not bulk-enable F09 under the read exception.
2. Obtain a fresh per-task execution-engineering grant naming any broker-adjacent source to update/test. The old PR bodies' October 15 grant descriptions are historical provenance, not this worker's authority.
3. Wait for WP-21's retained ownership of the registry, allowlist, contracts, capability baseline and related tests. Coordinate one config integration at a time; no hand-union across active claims.
4. Update from current main by merging it into the selected branch, preserving newer source/config and review provenance. F09 is 923 main-side commits behind the measured base; historical green CI does not validate that integration. Use isolated fixtures and current gates after the authorized update.
5. Apply existing contract/admission/cutover requirements per accepted lane. No host schedule, live list or workflow is changed by this triage.

## #1940 and historical audits

#1940's three proposed native shadow monitors and their contracts are absent from main. Its options quote-refresh intent is inert; Schwab position sync remains staged/cron. All five branch contracts say REVIEWED, which is not an activation decision. The quote-refresh command still needs a current read-capability/admission review. Its registry/allowlist/contracts and some tests overlap retained WP-21 ownership.

Required failures are linked to [hardening run 39846073572](https://github.com/PatsKiller/tardeai/actions/runs/39846073572) and [sharded run 39846073599](https://github.com/PatsKiller/tardeai/actions/runs/39846073599). Requested failed-log reads returned empty output, so the actual failing test cause remains NOT_MEASURED. Next: recover retained job detail or reproduce with sanctioned isolated fixtures once source/claim boundaries permit; fix the named failure on current main, then revalidate exact-head CI. No failure cause was invented and no failing gate was weakened.

#1350/#1351 are 2,410 main-side commits behind this snapshot. Their unique historical document blobs were not found elsewhere on main, so age/conflict is insufficient evidence to discard them. The author/coordinator should repackage the September 28 observations as dated historical evidence on a fresh base, regenerate INDEX, and separately review #1351's checker delta against today's checker. Do not carry its old CI-runner changes wholesale. Both need the current fourth required check.

## Ownership, verification and limits

Live retained WP-21 claim `20261024T021437Z-codex-8df6cf34` owns `config/lane_registry.json`, `config/n8n_run_allowlist.json`, `config/n8n_health_contracts.json`, the capability baseline and related tests. WP-33 item 4 also owns its lane-monitor source/test paths. These were read for metadata only; no claim was overridden and no source/config integration was attempted.

Verification used exact Git object/mode comparisons, main ancestry, stable delta IDs, AST structure comparisons, key-based JSON equality, fresh GitHub state/check readbacks, and artifact/schema/checksum validation. No new application test was needed for this review-only change. CI status remains bound to each captured PR head. Runtime health, workflow installation, persistent process seed, contract approval acceptance and deployment are outside the measured evidence.

Remaining work is now explicit: nine preserved PRs with the actions above, operator-only relay unit installation/process seed acceptance still separate, and publication of this report. No fresh broker, database, credential, host or release action is authorized by these receipts.

Evidence manifest SHA-256: `596528441a7dae055594c81c6bb0fb40ca07673d58f3e739f022330fa74ac5ab`.
