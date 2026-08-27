# CIO Notification Replay Acceptance

Authority: `READ_ONLY_ADVISORY`. This documents the deterministic replay that
proves the Aug-17 spam shape does not reproduce under the notification gate.

## Fixture

`scripts/lib/cio_notification_replay.py::build_aug17_replay()` builds a
deterministic, credential-free replay of the Aug 17, 2026 operator history. It
contains every required family:

- cash small-drift cycles (HOLD_CASH, `deploy_now=0`)
- re-entry READY/NEAR churn (WAIT, no governed RE_ENTER)
- SCHD blocked TRIM repeats (`DATA_CONFLICT`)
- operator REJECT on SCHD
- a deferred review
- a genuine governed RE_ENTER transition
- a genuine ACT_NOW transition
- a genuine changed-since-REJECT reopen

Total raw decisions: 59 (1 baseline REJECT + 18 cycles × 3 families + 4
transition/defer decisions). Historically this shape emitted ~54 operator pages.

## Expected result

| Metric | Target | Observed |
|---|---|---|
| raw scanner evaluations | high (unchanged) | 59 |
| immediate notifications | ≤ 5 | 2 |
| duplicate semantic notifications | 0 | 0 |
| unchanged post-REJECT repeats | 0 | 0 |
| reopens | ≥ 1 | 1 |
| digest notifications | — | 4 |
| suppressed | — | 53 |
| mid-sentence truncations | 0 | 0 |
| machine-gibberish headline violations | 0 | 0 |

The 09:44–12:34 unchanged loop produces **zero** repeated immediate pages after
the first material state publication.

## Run

```bash
python3 scripts/cio_notification_replay.py --state /tmp/cio_replay
```

Test coverage: `tests/test_cio_notification_signal.py`
(`test_aug17_replay_does_not_reproduce_54_notifications`,
`test_aug17_zero_repeat_after_first_material`,
`test_replay_fixture_module_acceptance`).

## Stronger invariant

Raw evidence churn never creates a fresh page. A new `decision_id` or a new
`decision_evidence_digest` alone cannot force a notification — only a semantic
material-generation change can. The gate reports raw evaluations, suppressed
events, digest events, and immediate notifications separately.
