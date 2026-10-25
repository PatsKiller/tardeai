# WP-33 item2: residual sync-social cron retirement packet

Status: DRAFT — OPERATOR-ONLY proposal; offline fixtures verified, host unchanged
as_of: 2026-10-24T03:56:49Z
Design-Task: DSN-20261023-handoff-v3-P7-T332

This packet comments **one exact residual unflocked cron line**, preserving its text and every unrelated byte. It changes no workflow, registry, contract, dispatcher admission, effect key, lock, service, credentials or producer code. The author has not read or changed the current host crontab. The historical line number 1077 is context, not a selector.

## Why the older packet is insufficient

[The October 23 census](../../N8N_CUTOVER_EFFECT_CLAIM_WRAPPER_20261023.md) recorded this residual line after the older flocked line at 875 was already commented:

```text
30 11,15 * * 1-5 cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT && /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/sync_social_to_intelligence.py --apply >> logs/sync_social_to_intelligence.log 2>&1
```

The older `incident-spcx-resume-20261022/double-run-operator.sh` targets a different line with literal `$PROJ`, `$PY` and `flock -n /tmp/sync_social_to_intelligence.lock`. It cannot retire the absolute-CURRENT unflocked residual. This packet never broadens the match to either that older line or similar variants. `target.json` contains the reviewed exact target and dated packet marker. Its target-line SHA-256 is `6005200955aa59b87e4fc68b3e83ef88def4bf001938e40b5393f6e4e972ff4e`.

## Offline author proof

`retire_packet.py plan` reads only a supplied file. It does not invoke any command or scheduler. A pinned-clock synthetic snapshot over 200 KB puts the target at line 1077 and the already-commented old flocked line at 875. The captured result was:

```text
OFFLINE_ONLY PLAN_READY 1 1077 NOT_MEASURED
```

Those fields are status, changed-line count, fixture line number and n8n acceptance. The candidate differs only by this prefix:

```text
# RETIRED WP33-20261024 sync-social-to-intelligence residual (operator packet; n8n owns)
```

One ASCII space separates that marker from the original line. The date identifies the reviewed packet, not a claim that retirement occurred on that date. An actual operator apply records its own verification time in a separate receipt. The full fixture plan and digest manifest are linked in the [delivery report](../../WP33_ITEM2_SYNC_SOCIAL_CRON_PACKET_20261024.md).

Missing, altered, duplicate, mixed active/retired or ambiguously commented targets refuse. An exactly already-retired target is an explicit no-op. LF/CRLF and missing final newline are preserved. The private plan directory keeps the original snapshot, candidate, plan receipt and a zero-context target-only diff. Modes are 700 for the new directory and 600 for its files; existing output directories/files are never overwritten.

## Exact operator commands

The cron freeze and operator decision still apply. **Even `--preview` below reads the host scheduler and needs the grant.** The author ran this wrapper only against a fake `crontab` in tests.

Before changing the trigger, the operator checks the current n8n owner/contract and a recent matching run/output receipt. The historical census alone is not fresh acceptance. If the exact line has drifted or n8n ownership is uncertain, stop for reconciliation; do not loosen matching or retire a different line.

Issue the scoped four-hour grant in the canonical checkout:

```sh
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
bin/guard grant cron --for 4h --uses 10 --replace --reason "WP-33 item2 operator-only preview/readback and one exact residual sync-social comment; no other scheduler changes"
```

After the coordinator merges and publishes this packet, use the served copy:

```sh
P=/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/docs/ops/packets/sync-social-residual-cron-20261024
bash "$P/operator.sh" --preview
```

Read the target-only diff and the `PRIVATE_EVIDENCE` path. It must show exactly one prefix addition, or an explicit already-retired no-op. `PLAN_READY` is a proposed cron edit, not n8n acceptance. Then, in the same serialized operator change window:

```sh
bash "$P/operator.sh" --apply
```

Type `ACK-RETIRE-SYNC-SOCIAL-RESIDUAL` when asked. This command captures a **fresh** snapshot, prints its exact proposal, verifies the candidate, checks the snapshot again immediately before installation, and captures the installed state for exact byte comparison. It refuses changed pre-install state, failed reads, candidate or receipt scope/hash drift and mismatched readback. It never reads credentials or queries a database. A completed installation creates `installed-verification.json`; archive/link that receipt and the grant/operator decision in the progress log and tracker.

The crontab API installs a whole candidate file. The packet proves that its candidate contains precisely the one approved prefix addition. It never replays an old full backup or changes any other line. `crontab` provides no atomic compare-and-swap: another writer between the final recheck and install remains a race, so the operator must serialize scheduler writes. Post-install comparison detects readback drift; it does not justify a claim of atomicity.

There is **no automatic restore** and no full-backup replay command. On a mismatch retain the evidence and stop. Any later reversal requires a newly reviewed, one-line operator change against a fresh snapshot; do not restore the entire crontab from this packet's backup.

## What remains unverified

The author's current host census, actual retirement, n8n execution, business-output correctness, same-slot duplicate effects and notification delivery are all **NOT_MEASURED**. `installed-verification.json` would prove only the observed cron comment/readback, not those business claims. No natural fire was triggered or observed by this work.

The source tests are registered in `sync_social_residual_cron_packet_20261024`. They exercise the real Python transform and shell wrapper using isolated fake `crontab`, hostname and user commands. They never invoke the real scheduler. The delivery report records the 140 passing new/compatibility checks and exact source base.
