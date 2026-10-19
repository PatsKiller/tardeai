# Require successful mandatory SOP commands and exact-head release checks

Status: DRAFT
as_of: 2026-10-18T23:47:00.198771+00:00
Measured at: source 226583b361e65a2aba86eba2f8783a882096dc1a; baseline 7af14c7782cf7ab0cba261cc25e6789fe810b092; observed production a2aef7b4d2de17e737526337a2ffc37848deda4f

The real SOP emitter previously returned success after recording a failed
mandatory command. The shared validator now requires each of its five existing
mandatory commands exactly once, with known integer zero expectation and exit,
and without a skip. Diagnostic records remain available after refusal. No new
verdict engine, approval, guard bypass, or authority is introduced.

The frozen behavioral suite reports 22 expected baseline AssertionErrors and
one valid control, followed by all 23 passing unchanged. Author regressions
pass 57 tests; independent source validation passes 74. Actual complete v1
producer/consumer pairs remain compatible in both directions. Historical
incomplete v1 records remain diagnostic and cannot qualify as mandatory proof.
The original sandbox failure and distinct later host success remain separate.
An independent run with missing Ruff on PATH is also retained as setup failure,
followed by the correctly configured independent run; it is not red-first proof.

The release-readiness workflow also executed the synthetic merge preview on PR
runs. Its checkout now selects the exact PR head while preserving push and
manual event identity. One meaningful selector assertion fails on the baseline,
three non-PR controls pass, and the identical four cases pass after correction.
PR1855 used a separately logged exact-head manual dispatch before its merge;
this change makes subsequent PR checks select that identity directly.

The new regression suites must run in the existing canonical CIO gate. Source
validation, native acceptance, hosted exact-head CI, deployment and recovered
business output are separate states. This packet claims local implementation
and source review only. Every fake-command attestation in the tests is explicitly
not operational proof. Production remains on the restored release.

Artifacts are losslessly compressed where needed. The manifest records both
stored and original digests; historical failed observations are not rewritten.
