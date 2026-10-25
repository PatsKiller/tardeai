# Anthropic-first local build report

Base: 7a17113afedc552a645493972dee46c0ba51a2dd.
Branch: work/DSN-20261025-anthropic-first-P1-T1.
Status: implementation checkpoint; **not live / no merge / no remote publication**.

The caller inventory was reported before implementation. See ../../ANTHROPIC_FIRST_20261025.md and dry-run-table.md for population, bypasses, measured cost and bounds.

The new canonical CI gate is config/ci_gates/anthropic_first_20261025.json. Final selected CI-parity run at fb2f083e9adff23ef89ee9e3e4b071d4f8d0ccd0: **263 passed**, psycopg2 hidden, existing Pydantic-2 virtualenv. All four new test files are in the canonical CI gate. The 56 new core tests also pass with system Python/hidden psycopg2. No dependency was installed.

Frontend build passed; its source tree is identical to this tested head. Ruff 0.16.2, host-path, coverage and line-ending checks pass (zero new violations). Contract validation and lane-registry schema validation pass. Server caller maps and all nine excluded registry rows are semantically unchanged. See verification.json for exact limits. This was selected CI-parity coverage; the socket-backed test was OS-refused and GitHub CI was not run.

Outstanding acceptance: active-owner monitoring handoffs; source-admission review; operator-permitted 412/390 browser and loopback proof; key delivery; post-release real canaries/readback. Do not label the branch production-ready from unit tests.

The fixture runner uses no server and aborts all network. Its first launch was OS-refused; no screenshot exists. Do not substitute a rendered mockup for browser proof.
