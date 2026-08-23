# Research Data Hygiene Live Findings - 2026-08-23

Authority: `READ_ONLY_ADVISORY`

## Threshold tuning

Read-only query against `hermes_research_intelligence`:

- `8,412` rows from `hermes_health_inspector` with `research_type=threshold_tuning`.
- `7,408` rows have the identical summary `analyst_consensus 48h -> 2h`.
- `0` distinct non-null pattern signatures.
- Observed range: 2026-08-07 through 2026-08-23.

These rows did not mutate the configured 48-hour threshold. They were repeated,
mislabelled proposals produced by a cadence query that could consume the same
research table it polluted.

## Librarian backlog

Read-only query against `hermes_research_intelligence`:

- `2,500` Autonomous Librarian historical rows, not 500 total.
- `2,480` are `rejected`; `30` are `archived`; `0` are open/staged.
- `1,674` are high-priority weak-strategy history and `824` are medium-priority.
- All `2,500` lack `owner_agent`, `backlog_type`, and `research_questions`.
- Only `17` distinct topics exist across the 2,500 rows.

The 500 count is a bounded read surface. Terminal rows must not be presented as
an open operator queue.

## Topics adapter

The API returns `user_topics` and the live DB contains `61` active topics. The
host OpenClaw read-only adapter falls through to `topics`, yielding zero. The
repository frontend already reads `user_topics`; host adapter activation remains
part of the controlled OpenClaw/CURRENT cutover.

## CIO cross-symbol notification churn

Operator receipts show research completions for JEPI, ARKX, and SCHD alternately
notifying FCNTX opportunity rank-20 membership and JTAI reentry membership. The
root cause is global product diffing being attributed to a symbol-scoped research
completion. Correct policy:

- persist the complete global product diff for audit;
- notify only changes for the researched symbol;
- do not page top-20 display-edge opportunity churn outside the top five;
- dedupe on semantic transition plus thesis version, not product timestamp.

## Implemented controls

- Deterministic health fusion; no local generative endpoint.
- Threshold proposal sample floor, self-artifact exclusion, 7-day fingerprint
  dedupe, three-proposal cycle cap, and bounded 0.5x-4x proposal range.
- Open-versus-terminal backlog accounting and deterministic ownership taxonomy.
- Dry-run-by-default historical archive and taxonomy repair tools.
- Stateful RAG-first auto-research context and placeholder-zero input/output gates.
- Symbol-scoped research notification causality and semantic transition dedupe.

No repair utility was run with `--apply`. Financial writes: `0`.

`MATURITY_IMPACT: research_acquisition + notification_signal_noise + gpu_policy_compliance`
