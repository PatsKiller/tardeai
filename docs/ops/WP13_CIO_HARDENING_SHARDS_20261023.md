# WP-13 parallel CIO hardening delivery

Status: DRAFT — local implementation tested; operator publication and remote acceptance pending
as_of: 2026-10-24T02:39:00Z
Measured at: existing `dc96811d46c1` work integrated with `origin/main` `fe826d2ecdb59a19bd7c510c8923c7b743f06eee`
Design-Task: DSN-20261023-handoff-v3-P3-T13

`cio-hardening` currently waits for nearly the full registered suite in one job on large release PRs. This change runs the eight balanced shards, serial shard, PostgreSQL shard and integrity rails in parallel on ready PRs, main pushes and manual dispatches. The existing required check name `cio-hardening` becomes their aggregate. Draft PRs still skip this fleet; #2032's exact draft guard and `ready_for_review` trigger are preserved.

This resumes the existing test/gate/design commit `dc96811d4` and external `handoffs/scratchpad-20261023/workflow.patch`, merging main without rebasing or force-pushing. The single workflow conflict selected the existing sharded candidate. The resulting workflow is byte-identical to the old worktree's in-flight candidate, and all changes outside this work package are inherited main commits. The prior worktree and its uncommitted file remain intact.

## Preserved acceptance checks

- Every test job checks out the exact PR head or pushed SHA, uses the existing shard planner and installs its selected frontend dependencies before executing tests.
- `CI_GATE_NEEDS` and `--verify-shards` reject missing or duplicate registered files, missing shards, unsuccessful/skipped jobs, mismatched tree/plan and failed units. The aggregate executes no tests itself.
- The aggregate uses `always()` on main pushes/dispatches and `!cancelled()` for PRs. Main failure/timeout/cancellation still reaches `main-red-alert`; a superseded PR cannot become green.
- Adversarial, dark-contract, retention, line-ending, test-coverage, host-path, docs-index and release-manifest rails remain in the integrity job, alongside the existing report smokes.
- Required context names, per-SHA main concurrency, superseded-PR cancellation, isolated PostgreSQL service and manual serial reference job remain available. Branch protection is unchanged.

## Local verification

| Test group | Result |
|---|---|
| Fast-shard workflow regression | 36 passed, included below |
| Fast shards + frontend dependencies + gate registry + draft fleet | 159 passed in 53.38 s |
| Shard manifests/tree attestations + SOP attestation | 53 passed in 4.41 s |
| Cancelled/timeout alerts + per-SHA concurrency + outage-release controls | 52 passed in 1.28 s |

The new test is registered in canonical `config/ci_gates/ci_cio_hardening_fast_shards_20261022.json`. The shard plan and retained XML receipts are under `/home/johnclaw/.cache/rtc/codex-wp13-20261023/`. The source-only controls use fixture state and test interdicts; they require no live server, providers, production DB or notifications.

Git whitespace is checked against main for this work package. Main's inherited CRLF workflow files retain their bytes; they are not converted during integration. `docs/INDEX.md` is regenerated for the new report. Operator publication is recorded as exactly one `PUSH_NEEDED` event; no sandbox push was attempted.

## Remote proof still required

The earlier worker measured approximately 37 minutes median for the monolithic main job and 28–38 minutes for large release PRs (examples: runs 39968620315, 39994133076 and 40001978010). Eight to twelve minutes is a target, not an observed result. **New workflow wall time is NOT_MEASURED** until the exact integrated candidate is published and completes on GitHub. Local test duration does not measure runner scheduling, installation or the registered suite.

After the operator publishes the candidate PR and its required checks pass, run this read-only measurement from this branch. It selects a completed pull-request run on the exact local head and calculates first shard start through aggregate completion:

```bash
cd /home/johnclaw/wt-codex-wp13-20261023
python3 - <<'PY'
import datetime as dt
import json
import subprocess as sp

def get(*args):
    return json.loads(sp.check_output(args, text=True))

head = sp.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
runs = get('gh', 'run', 'list', '--repo', 'PatsKiller/tardeai', '--workflow',
           'cio-production-hardening-ci.yml', '--branch',
           'work/DSN-20261023-handoff-v3-P3-T13', '--limit', '30', '--json',
           'databaseId,headSha,status,event')
matches = [r for r in runs if r['headSha'] == head and r['event'] == 'pull_request'
           and r['status'] == 'completed']
assert matches, 'No completed pull-request run on this exact candidate head'
run_id = matches[0]['databaseId']
pages = get('gh', 'api', f'repos/PatsKiller/tardeai/actions/runs/{run_id}/jobs?per_page=100',
            '--paginate', '--slurp')
jobs = [j for p in pages for j in p['jobs']]
parts = [j for j in jobs if j['name'].startswith('hardening shard ')
         or j['name'] == 'hardening integrity rails']
aggregates = [j for j in jobs if j['name'] == 'cio-hardening']
assert len(parts) == 11 and len(aggregates) == 1, 'Missing/duplicate candidate jobs'
assert all(j['conclusion'] == 'success' for j in parts + aggregates), 'Run is not accepted'
parse = lambda s: dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
start = min(parse(j['started_at']) for j in parts)
end = parse(aggregates[0]['completed_at'])
print(json.dumps({'sha': head, 'run_id': run_id, 'first_part_start': start.isoformat(),
                  'aggregate_end': end.isoformat(), 'wall_minutes': (end-start).total_seconds()/60}, indent=2))
PY
```

Append the actual run URL, head and computed wall time to the progress log, then update this report. The coordinator merges/releases after remote acceptance. PR #1943 is superseded by this candidate but must remain open until its successor merges. No claim of remote green or live deployment is made here.

The full registered suite still runs in both `ci-gate` and this workflow, using more concurrent runners. Any later removal of a required PR check or branch-protection change is the operator's separate decision.
