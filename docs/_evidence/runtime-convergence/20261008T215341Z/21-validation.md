# Source validation — 2026-10-08

TEST_ONLY unless explicitly marked OBSERVED_HOST/DB. No tests against live broker/order/send authority.

| Verification | Result | Evidence / command |
| --- | --- | --- |
| Canonical local acceptance | PASS, ready_to_request_sync=true | `CIO_FAST_JOBS=4 bash scripts/ai_local_acceptance.sh`; actual runner default jobs=8; `21-canonical-acceptance.log` |
| Release equivalent source checks | 17/17 PASS | canonical log, `run_release_ci_equivalent.py --source-only` |
| CIO hardening fast profile | ALL GATES PASS; 336 parallel units + 20 serial gates | canonical log; lane registry, drift, relay, gateway, executor, ledger concurrency, templates, cutover/rollback, Command Center, governance families registered |
| New scheduler / release-rebind / launcher tests | 41 PASS on final source | canonical `scheduler_operations` gate |
| Fixture gateway/relay bursts | 10 PASS; 1,5,16,32,64 connections | `08-fixture-bursts.log`; max64 request latency below 0.062s; no drops/handler errors; source backlog already64 |
| Broad targeted n8n/lane regressions | 313 PASS | `21-targeted-regression.log`; followed by canonical full gates |
| Frontend TypeScript/build | PASS | `15-frontend-build.log`; canonical type check |
| Playwright fixtures final | 4 PASS; rows/filter/timeline/console/stale/unavailable/mobile390 | `15-playwright-final.log`; Chromium permitted outside sandbox; no production acceptance inferred |
| Dark contract / test coverage / host path / authority / line endings / adversarial | PASS | canonical log; no gate weakened, no new unexplained dark contract or undeclared test |
| Changed-file pinned Ruff (check + format) | PASS, 15 Python files formatted; AST equivalent | `21-changed-quality.log`, `21-formatting-proof.json`; no rule/ignore widened |
| Focused final regressions | 70 PASS | `21-focused-final.log`; includes all 41 scheduler/root checks and financial truth withholding |
| Source secret scan and diff whitespace | PASS | `scripts/check_no_secrets.py`, `git diff --check --cached`; logs whitespace normalized only |
| Host security audit | OBSERVED_N8N, CLI exit0 | `07-n8n-security-audit.md`; metadata-only/redacted; CLI bootstrap migration-lock caveat |
| LIVE browser after deployment | BLOCKED | No deployment grant; this branch is not CURRENT; requires API without interception |
| Remote exact-head CI | NOT_MEASURED at evidence commit | PR/final response records `gh pr checks` results at final head |

Negative evidence: release-root wrappers failed before replacing hardcoded PROJ; rebind tests failed without relay/executor and on ignored restart failure; receipt validation rejects mismatched/future/exit1/shadow rows; DB signals previously mislabelled HOST now retain DB evidence. `21-negative-before-fixes.log` proves the mismatched receipt and deterministic timestamp-digit collision defects. Structured price/holdings/cash assertions retain financial truth protection while allowing digits in source mtime metadata. Projection tests also reject expired scheduler observations, stale output behind exit0, no receipt, failed timer child, missing definition, duplicate locked schedule, and absent ledger creation. One absent systemd unit cannot hide peers.

The initial `21-cio-hardening.log` has sandbox socket/multiprocessing failures and the old timestamp-digit test flake. The permitted canonical rerun resolves them; compare the final log rather than declaring the initial failure green. Source acceptance gates are green, while full program source acceptance remains BLOCKED by registry contracts and runtime evidence requirements. No production convergence claim.
