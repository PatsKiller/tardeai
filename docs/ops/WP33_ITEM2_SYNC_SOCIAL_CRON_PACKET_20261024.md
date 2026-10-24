# WP-33 item2: exact residual sync-social operator packet

Status: DRAFT — locally tested operator packet; publication, operator census and apply pending
as_of: 2026-10-24T03:56:49Z
Source base: `ef115e38e5d9b9a52c3b480898afe72b30678121`
Design-Task: DSN-20261023-handoff-v3-P7-T332

The October 23 census recorded an unflocked `sync_social_to_intelligence.py --apply` cron line using absolute CURRENT/interpreter paths, while the older flocked `$PROJ`/`$PY` line was already commented. The existing double-run packet matches only the older line. This delivery prepares a new exact-line operator packet; **no current host scheduler read or change was performed**.

The [packet README](packets/sync-social-residual-cron-20261024/README.md) contains the exact four-hour grant and preview/apply commands. [target.json](packets/sync-social-residual-cron-20261024/target.json) pins the reviewed residual line. `retire_packet.py` builds and verifies a prefix-only candidate from a supplied snapshot. `operator.sh` is operator-only, including preview; its shell behavior was exercised solely with a fake crontab. Neither the packet author nor its tests executed the real `crontab` command.

## Verified source behavior

**27 new tests passed in 2.35 s**, plus **113 existing packet/CI-registry checks passed in 2.53 s**. Canonical gate `sync_social_residual_cron_packet_20261024` was generated with `scripts.lib.ci_gates.render`. Helper/test Ruff, shell syntax, whitespace, claim coverage and generated INDEX checks pass.

The tests establish:

- A synthetic crontab over 200 KB at the historical line numbers changes by exactly one RETIRED prefix; the old flocked line and every other byte remain unchanged.
- LF, CRLF and missing-final-newline inputs retain their endings. Missing, modified, duplicate and mixed active/retired targets refuse; exact prior retirement is a no-op.
- Candidate, receipt scope/hash or readback drift refuses. Private backups and receipts cannot be overwritten. The displayed diff has no unrelated context or environment declarations.
- The real shell preview performs one fake read and zero installs. Confirmed apply performs read→recheck→one install→readback, and stores a verification receipt. Wrong acknowledgement, failed reads and pre-install drift perform zero installs. A corrupt readback fails after the one install and performs no full-backup restoration.

The pinned synthetic CLI dry run returned `OFFLINE_ONLY PLAN_READY 1 1077 NOT_MEASURED`. Its snapshot SHA-256 is `b2964826d90783d4a5c45a8227f7e602eed00825879f10ee868c23241ef6f90b`; candidate SHA-256 is `6229abf4b63fb053873a92f9286cfbcd6133bfe84e8fe70d92745a3e8eb8ae2e`. The supplied fixture clock is `2026-10-24T03:48:19Z`. [verification.json](packets/sync-social-residual-cron-20261024/verification.json) binds the source hashes, plan and test counts. Original XML receipts and the full synthetic snapshot are under `~/.cache/rtc/codex-wp33i2-20261024/`.

## Operator boundary and next proof

Current host line presence and actual n8n owner/output acceptance remain **NOT_MEASURED** by this worker. The operator needs the documented cron grant, a fresh preview, current n8n evidence and the exact typed acknowledgement. The wrapper's possible installed receipt means only that the captured cron comment matched the candidate; it does not prove the replacement ran or duplicate business effects stopped.

No registry, contract, admission, active-workflow, producer, lock, service, broker, order, stop or credential changes are included. No retained WP-21 config/API claim was touched. Source preparation does not authorize a promotion or scheduler operation by an agent. The packet uses a final drift check and exact readback, but the crontab API has no atomic compare-and-swap; the operator must serialize changes.

The worker commits one package and logs one `PUSH_NEEDED` command, retaining its claim. The coordinator/operator publishes it, obtains exact-head required CI, merges/releases, then owns the granted scheduler operation and records the fresh evidence. Runtime completion is not claimed, and no full-crontab restore is supplied.
