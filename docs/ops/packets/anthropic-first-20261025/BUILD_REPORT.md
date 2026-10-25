# Anthropic-first local build report

Base: 7a17113afedc552a645493972dee46c0ba51a2dd.
Branch: work/DSN-20261025-anthropic-first-P1-T1.
Status: implementation checkpoint; **not live / no merge / no remote publication**.

The caller inventory was reported before implementation. See ../../ANTHROPIC_FIRST_20261025.md and dry-run-table.md for population, bypasses, measured cost and bounds.

The new canonical CI gate is config/ci_gates/anthropic_first_20261025.json. Prior integrated run: 115 passed with psycopg2 hidden. Final verification is recorded in verification.json after the checks finish.

Outstanding acceptance: active-owner monitoring handoffs; source-admission review; operator-permitted 412/390 browser and loopback proof; key delivery; post-release real canaries/readback. Do not label the branch production-ready from unit tests.

The fixture runner uses no server and aborts all network. Its first launch was OS-refused; no screenshot exists. Do not substitute a rendered mockup for browser proof.
