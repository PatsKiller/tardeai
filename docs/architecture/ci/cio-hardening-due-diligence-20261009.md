# CIO hardening due diligence — executive summary (2026-10-09)

```
Status:    FINDINGS + RECOMMENDATIONS. Nothing changed. Operator decisions requested in §5.
Evidence:  cio-hardening-timing-evidence-20261009.md (53 CI runs, 10-08 15:07Z → 10-09 13:51Z, every number with its command)
           cio-hardening-design-audit-20261009.md   (full deliverable: architecture, root causes, findings by category,
                                                     quick wins, medium/long term, 2–3 min design, risks; file:line cited)
Tree:      origin/main 3b5c24856
```

## 1. Why it takes ~15 minutes (measured)

| Stage (push to main, median) | Seconds | Why |
|---|---|---|
| Queue before the job starts | 4 (but 422–814 in 4 of 19 merges) | main runs are never cancelled; a merge waits for the previous main run |
| Checkout + Python + install | ~20 | same as the fast workflows; no pip or impact-map cache |
| Parallel test phase | 677 (p90 761) | ~2,550 CPU-s of tests (886 files) on a 4-vCPU runner, 94% busy: throughput-bound, not one slow test |
| …of which one gate `maturity_overnight_20260912` | 779 CPU-s | ~31% of the parallel work |
| Serial tail | 144 | 26 files run one at a time; at least 14 are regex false positives, only 5 touch shared state |
| Duplicate registrations | ~40 | 25 files listed in more than one gate |
| **Job wall** | **904 (p90 ~1,000)** | |
| **Merge → green on main** | **951 median, 1,365 p90, 1,617 max** | the deploy refuses promote until this exact-SHA run is green |

Runner region adds ~1.8× variance (centralus test step 503 s vs 901 s elsewhere; CPU model not logged).

**The structural cause:** the PR run is a *selection* (median 449 s, up to 477 files deferred), so main must run the
whole suite again — even though **24 of 24 merges since 10-08 produced a tree byte-identical to the PR head** that had
just passed. With `strict=true` and no merge queue (not available on a user-owned repo — NOT VERIFIED by API), every
main move also forces PR reruns: today 6 of 20 PR runs (1,917 runner-s) were on merge-of-main heads.

## 2. Justifying the minutes

| Minutes | Necessary for integrity? |
|---|---|
| Running the full suite once per tree | **Yes** — it is the evidence the release gate relies on |
| Running it a second time on an identical tree | **No** — same bytes, same result |
| Running it on one 4-core machine | **No** — it is CPU volume; sharding gives the same evidence in ~1/8 the wall |
| 14+ false-positive serial files | **No** |
| Queueing behind a superseded main run | **No** — prepare only ever promotes the main tip |
| Stale duration hints (one 09-25 measurement, 48 files) | **No** |
| Rebuilding the impact map every PR (~19 s) | **No** |

## 3. Security and integrity gaps found while measuring

1. The secrets scan never runs in CI (local hooks only, bypassable).
2. Broker-write fences (`validate_schwab_write_policy`, `no_broker_write_bypass`) run in release-readiness, which is required for neither merge nor promote.
3. Prepare's frontend build silently falls back to plain `vite build`, skipping the design guards and `tsc` (`cio_phase2_exact_main_deploy.sh:443-448`).
4. Postgres schema/RLS tests skip in required CI (no psycopg2); they only run on the author's host.
5. agent-governance cancels its own main runs: 17 SHAs since 10-01 are unpromotable.
6. The nightly serial full run is red (order dependency in `maturity_overnight`); issue #1251 has 59 comments since 09-26, so it no longer alarms anyone.
7. Python skew: CI 3.13 / agent-governance 3.12 / production venv 3.14.4.

## 4. Recommendations (ranked by impact ÷ effort)

**Quick wins (<24 h, no control weakened — design audit Q1–Q11):** cancel superseded main runs (removes the 7–13 min
queue spikes); agent-governance cancels only on PRs; regenerate duration hints from CI and refresh weekly; dedupe
duplicate gate files; drop the serial false positives; content-keyed impact-map cache; pip cache + shallow checkout;
move the PDF/DOCX smoke to nightly; run the CI check *before* consuming a release grant; make the prepare frontend
build fail closed; add a CI diff secrets scan. Effect: PR ~449 → ~300–340 s; push ~904 → ~760–800 s; merge→promotable
p90 1,365 → ~800–850 s.

**Medium term (1–3 weeks):**
1. **Shard the full suite on every PR** (~8 runners × 4 workers, duration-balanced, plus a Postgres shard) behind one aggregate required check. Full suite ~2.5–3 min wall; nothing deferred. Saves ~550–700 s.
2. **Accept tree-attested PR evidence at promote** (PR ran the full suite, PR tree == merge tree, workflow files identical); keep the main run as an async backstop. Saves ~950 s median from merge to promotable. **Changes the release gate → operator decision.**
3. Hermetic serial tail; profile `test_data_source_authority` (162 s on slow runners) and `maturity_overnight`.
4. Fix the nightly order dependency so #1251 becomes a real alarm again; required release-readiness (broker fences) at merge.

**Long term:** content-addressed test-result cache keyed on input hashes; pinned runner images; a single Python version (3.14) across CI and production.

## 5. The 2–3 minute target — what is achievable

With sharding + tree-attested promote: **PR blocking path ~2.5–3.2 min** (floor set by the slowest single file until
it is profiled), **merge → promotable ≈ PR green (seconds)**. Not achievable without those two: the full suite on one
4-vCPU runner cannot go below ~637–722 s. Auto-rollback on async failures is **not** recommended: a release rollback
does not revert shared data or migrations, so async failures should alarm and the operator decides.

## 6. Decisions for the operator

1. Approve the quick wins Q1–Q11 (no control is weakened; three strengthen controls).
2. Approve sharding the full suite on PRs (runner minutes go up ~8× per PR run; wall time goes down ~4–5×).
3. Approve tree-attested promote (release-gate change).
4. Approve making release-readiness a required check.
