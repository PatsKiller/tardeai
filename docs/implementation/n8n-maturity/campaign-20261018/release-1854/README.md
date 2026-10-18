# PR 1854 release acceptance and rollback

The exact merged release `7af14c7782cf7ab0cba261cc25e6789fe810b092` was promoted and
**rejected at acceptance**, then rolled back to `a2aef7b4d2de17e737526337a2ffc37848deda4f`.
PR 1854 remains merged. Its changes are not currently deployed.

Required exact-head PR checks, independent source review, native local acceptance
and exact merged-SHA push/main CI passed. Canonical prepare created the immutable
artifact. The authentic finite release grants and consumption identities are in
[the acceptance record](acceptance.json) and the evidence directory.

The deployed-to-target comparison found upstream Hermes feedback changes:
`live_arg` becomes `--apply --notify queue` and registry stage becomes `canary`,
while the health-contract stage remains `shadow`. The release mutation manifest
excluded live configuration changes. The integrator missed that upstream delta
before promotion. No matching configuration grant was used. Ownership stayed
with cron; no sixth-stage output or new cutover is claimed.

Canonical rollback restored CURRENT and all eight observed bound services. The
prepared source compensation restored the clean physical checkout by detaching
at the known rollback SHA. It preserved the original branch at its promoted head;
no branch was rewound. Configuration digests, all 37 owner rows and the existing
unknown effect claim match their before-images. The unknown claim was not expired
or erased. Scheduler entries were not changed.

The preserved canonical rollback receipt has a legacy identity contradiction:
although its mode is `rollback` and result is `rollback_ok`, `rolled_back` is
false, and its deployed SHA, release directory and venv path still name the
prepared 7af artifact. The writer reads retained prepare-state variables rather
than the rollback target. The raw receipt is preserved unchanged. CURRENT,
service working directories, clean checkout and the natural a2 run establish
the actual rollback identity; the contradictory header is not acceptance proof.

A natural live fan-in run during the brief promotion produced 139 contracted
items, and its exact run appeared in the authenticated CC readback. That proves
one bounded output path, not release acceptance, incident recovery, sixth-stage
Hermes success or sustained operation. The existing tailnet frontend returned
200; this does not establish user session or MFA claims. No learning or
notification effect was rerun to manufacture evidence.

Before re-promotion, independently review the complete deployed-to-target
configuration delta and freeze its required authority. Preserve the feedback
owner and existing proof holds. Campaign qualifying observation remains zero
hours and provisional operational maturity remains 2.5/5.
