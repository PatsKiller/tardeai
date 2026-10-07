# Scheduler truth

Dated 2026-10-07. Registry edits in this branch are WIRED_UNPROVEN until a served release and a natural fire. No timer was disabled. No crontab line was edited. `scripts/check_lane_registry.py` against the live host export reported 173 declared lanes, 134 ACTIVE, 0 structural errors, and 0 undeclared jobs. Three older lanes still have reason confidence UNKNOWN (`deep-overnight-llm`, `overnight-batch`, `cio-decision-engine`). Those rows were not edited to make the gate green.

## Classifier

`scripts/lib/n8n_lane_host_conflict.py` is the classifier.

- A non-recurring timer with SubState `elapsed`, an empty next elapse, and registry state RETIRED returns `CLASSIFIER_FALSE_POSITIVE_CLOSED`.
- A recurring enabled timer that still has a next elapse and is declared RETIRED returns `ENABLED_WHILE_DECLARED_RETIRED`.
- The same shape declared NEVER_SCHEDULED returns `ENABLED_WHILE_DECLARED_NEVER_SCHEDULED`.
- A present crontab command declared NEVER_SCHEDULED returns `CRON_PRESENT_WHILE_DECLARED_NEVER_SCHEDULED`.

Fixtures cover `at-observation-01`, its closeout, the recurring contradiction shape, and the maturity cron shape. The two one-shot unit files were not changed and were not disabled.

`scripts/lib/effective_truth.py` still lists enabled timers whose realtime next elapse is empty. That list is a different question. A monotonic timer such as `tradeai-gir-projector.timer` publishes `NextElapseUSecMonotonic` and an empty realtime field while SubState is `waiting`. The new classifier does not treat that shape as a spent one-shot.

## Contradiction adjudicator — conflict, not a silent flip

Observed 2026-10-07T01:46:08Z:

- Unit `tradeai-contradiction-adjudicator.timer`, enabled, waiting, next 2026-10-07 19:30 ET, last 2026-10-06 19:30 ET.
- Service command, from the repo unit and the earlier unit read: `scripts/contradiction_adjudicator.py --apply --max-pairs 20`, working directory CURRENT.
- Latest run file `data/runtime/contradiction_adjudicator_latest.json` records schema `AdjudicationRun@v1`, mode `apply`, written 20, as_of 2026-10-06T23:30:00Z. Verdict text was not read.
- `data/cio/contradiction_verdicts.jsonl` exists (206,289 bytes, same mtime as that run file).
- `scripts/gir_projector.py` is the in-repo reader of that jsonl. `tradeai-gir-projector.timer` is enabled and waiting. Its last trigger was 2026-10-06 21:24 ET, after the verdict file mtime. Whether those 20 rows were applied is NOT_MEASURED. The projector's empty realtime next elapse is the monotonic-timer case, not a spent one-shot.

The code path for `--apply` calls the paid judge and appends verdicts. Each written row template sets `financial_action` false and `memory_behavior_influence` 0. This session did not call the model and did not confirm a current owner sign-off.

Resolution ready for review, not applied: keep the registry row NEVER_SCHEDULED until an owner accepts the live `--apply` writer. Do not stop the timer to make the row look true. The next natural window, if the timer remains, is 2026-10-07 19:30 ET. Do not force it.

Proposed operator choices:

1. Accept the live timer as the canonical writer and change the row to ACTIVE with the existing output path `data/runtime/contradiction_adjudicator_latest.json`, owner `cio`, and a reason that cites the 2026-10-06 19:30 ET fire. Then watch the following natural fire.
2. Leave the row NEVER_SCHEDULED and issue a scheduler grant that disables the timer. That is a production scheduler change and was not done.

## Maturity remeasure — proposed ACTIVE row, not applied

The crontab line is the writer. `scripts/maturity_remeasure.py` scores nine domains from receipts. Absent proofs score 1. `score()` does not read an `overall` headline; a fixture with `overall: 4.7` and empty proofs still scores 1 in every domain. The live file's headline was not used.

The file under persistent-state has schema `MaturityScore@v1`, scorer `maturity-remeasure`, as_of 2026-10-05T10:40:01Z, window 168 hours, nine domains. It is absent under `CURRENT/data/governance` because that directory is not the persistent-state symlink (`data/runtime` is the symlink; `data/governance` on CURRENT is not that file). A code search found the writer and its tests. It did not find a separate runtime reader of `data/governance/maturity_latest.json`. `source_maturity_latest.json` is a different file.

`SCHEDULED_ENTRYPOINT` in the script still says the cron is not installed. `check_dark_contracts.py` treats that phrase as not installed. Changing the string changes the gate, so it was not changed in this pass.

Proposed row, not written into `config/lane_registry.json`:

- lane_id `maturity-remeasure`
- state ACTIVE
- owner `platform`
- scheduler cron `40 6 * * 1`, match `maturity_remeasure.py`
- output_signal `data/governance/maturity_latest.json` on the persistent-state root
- state_reason: the Monday 06:40 ET writer is already on the user crontab; the NEVER_SCHEDULED evidence is stale

The next legitimate natural fire is Monday 2026-10-12 06:40 ET. Do not run `--write` to create a proof. A pause would remove a writer whose consumer in this tree is the closeout file, and that pause was not requested as a live change.

## Alignment rule

A lane is aligned only when schedule, state, command, release path, output, and consumer agree. These two rows do not. The classifier correction is local until this commit is served.
