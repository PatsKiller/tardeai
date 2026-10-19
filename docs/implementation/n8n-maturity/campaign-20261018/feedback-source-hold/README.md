# Preserve the held Hermes feedback stage

Status: DRAFT
as_of: 2026-10-19T00:00:36.644623+00:00
Measured at: source 969e9820c3f85f61a63dc394c01f69492ff82f98; native 37ed9b107f41beb2dedada2c61acb309b1b58fcd passed; fresh-main integration 50f7f5a2887f24b51b0a3100914709344921dd9d pending native; production a2aef7b4d2de17e737526337a2ffc37848deda4f

The sixth Hermes learning stage has no qualifying live output or downstream
consumption proof. This change restores its source configuration to shadow with
`live_arg: null`, matching the active hold. The registered queue-only adapter
remains available for a later reviewed cutover; its existence is not activation.
All other lane rows and top-level configuration metadata remain unchanged.

The original actual admission-to-executor test fails twice on 7af14c7782cf7ab0cba261cc25e6789fe810b092
and passes unchanged on 969e9820c3f85f61a63dc394c01f69492ff82f98. The requested live run is
clamped to dry mode, spawns only the dry command and creates no effect claim.
Author validation passed 161 tests; independent validation passed 114 tests.
Three older tests assumed every runnable stage was enabled. Their original
failures are retained, followed by precise feedback-held assertions while all
five other stages keep their enabled expectations. The new behavioral suite is
registered in the canonical CIO CI runner.

Production was restored to a2aef7b4d2de17e737526337a2ffc37848deda4f after PR #1854's release
failed its config acceptance check. The upstream config delta came from PR
#1849, not #1850. The prepared 7af artifact stays rejected and immutable; this
source change requires reviewed CI, merge and a fresh canonical preparation.
No workflow, scheduler, runtime live list or owner was changed here.

The separate 7af claim-to-spawn fencing defect remains open; the retained failing
reproduction is not closed by this config hold. The sixth stage remains held
for output, input lineage, downstream consumption and transactional cutover
proof. No live learning or notification was repeated for evidence.

XML artifacts use deterministic gzip to preserve their original bytes, including
historical assertion failures, without adding trailing whitespace to Git. The
manifest records compressed and original digests and original byte lengths.
Native acceptance and exact-head hosted CI are separate requirements recorded
in the PR; these documents do not claim deployment or business recovery.

The complete native acceptance at 1a00 failed five existing inventory assertions
that still classified feedback as enabled. The original full failed log is
retained. The shared Hermes fixture now declares four live learn stages plus
tune, with feedback held; four inventory assertions use that one fixture.
The dispatcher expectation separately tests the held dry shape and preserves
the retained future notify-argv refusal. No production source or policy was
changed by this requirement migration. The focused requirement-migration run passes 168 tests. Candidate-focused and full native
results remain separate; the failed run is never reported as green.

The separate complete native run at 37ed9b107f41beb2dedada2c61acb309b1b58fcd
passed all required local gates (session58555, exit0). Its raw log is retained
losslessly alongside the failed 1a run. A normal merge now imports reviewed
main b52a1f2fa2f929e9b72d9133b98cf2610ffb9264. Feedback configurations and tests
remain byte-identical to the tested37 candidate; full native acceptance of this
new dependency combination remains a separate pending requirement.
