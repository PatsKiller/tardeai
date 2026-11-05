# CI load reduction (DSN-20261031-ci-load-reduction, D50 item 7)

Why: on 2026-10-31 GitHub Actions started **5,369 runs**. Mergify's blanket "keep PRs up to date" rule pushed
catch-up commits to every open PR after each merge (**2,913 runs, 54%**); agents opening ready PRs and pushing
several times each accounted for 1,775 (33%). One PR push cost 9–10 workflows, about 36 jobs and about 110
runner-minutes, of which two near-identical 12-job sharded suites were about 97. **269 of 444 full-suite PR runs
were cancelled by a newer push** — they spent their minutes to be thrown away. Main's 12-second gating job then
waited 48–104 minutes for a runner and merges stalled.

Three levers, now implemented in `cio-full-suite-sharded.yml`; one prepared switch, deliberately off.

## 1. Concurrent pushes to one head cancel each other

The workflow's `concurrency:` group is keyed on the ref for pull requests, so a newer push cancels the run it
supersedes. Push-to-main and the nightly keep their own groups and never cancel each other: a merge batch is
several pushes and the deploy poller must see every main run finish.

## 2. A merge-of-main-only push does not re-run the full suite

`preflight` compares the head's **branch diff against `origin/main`** with its first parent's. If they are
identical, the merge brought only main in and the suite has nothing new to say; the shard jobs are skipped and
both aggregators (`ci-gate`, `cio-hardening`) still report, with a step that states in the run log that this run
attests a **skip**, not a suite result.

The rule fails **open**: a non-merge head, a hand-resolved merge that also changes branch files, an unreadable
head, or an unresolvable `origin/main` all RUN the suite. A skipped suite that should have run is a green on
untested code, and that is the one outcome this must never produce. The decision lives in
`scripts/lib/ci_suite_preflight.py` with its own tests, rather than inline YAML, so it can be tested and mutated.

## 3. The full suite runs once per bundle

Bundles arrive as one push to one head (the deputy merges approved heads into a single branch), and lever 1
already collapses the intermediate pushes. Nothing extra is needed, and nothing re-runs per PR inside a bundle.

## 4. Prepared, NOT enabled: a faster hosted runner

Every job in the file now reads its runner from one variable:

```yaml
runs-on: ${{ vars.CI_RUNNER || 'ubuntu-latest' }}
```

Setting the repository variable `CI_RUNNER` (Settings → Variables) to a larger hosted label — e.g.
`ubuntu-latest-8-cores` or `ubuntu-24.04-arm` — switches every job at once. Nothing else changes; unset, the
workflow is exactly as it was. **Do not enable it until the operator picks a provider and the spend is agreed.**

## What a self-hosted runner would need after the repository goes private

- **Registration** with a repo- or organisation-scoped token, `--labels self-hosted,linux,x64,tradeai-ci`, and
  `--no-default-labels` so a stray `runs-on: ubuntu-latest` cannot silently land there.
- **Isolation**: the shards run pytest against fixtures but the Postgres shard starts a service container and the
  frontend jobs run `npm ci` — the runner needs Docker (or a pre-provisioned Postgres) and about 20 GB of free
  disk per concurrent job.
- **No secrets on the box**: `ci-gate`/`cio-hardening` read only the repo; the promote path reads its attestation
  from an artifact. Keep the deploy token off the runner entirely, or the runner becomes an operator.
- **One runner per job slot**, `--ephemeral` so a polluted workspace cannot carry into the next run, and
  `actions/checkout` with `persist-credentials: false`.
- **A documented kill switch**: removing the `CI_RUNNER` variable puts every job back on GitHub-hosted runners in
  one edit.
