# n8n upgrade runbook (program 0.1h)

Rules: AGENTS.md section 23.26 (recreate `m8m-n8n` only; never drop the database or the volume). The live pin is
`config/n8n_version_pin.json` (n8n image and Postgres image; never `latest`).

## Who
An upgrade is an operator decision (AGENTS.md section 17). An agent prepares the rehearsal and the PR; it does not
recreate the live container.

## Steps
1. **Fresh bundle.** `python3 scripts/n8n_backup.py --apply` (host copy plus verified Drive copy). Record the bundle name.
2. **Rehearse on the restored copy.**
   `python3 scripts/n8n_upgrade_rehearsal.py --apply --target --image n8nio/n8n:<new>`
   It restores the newest bundle (database and volume) into an isolated copy (internal docker network, own throwaway
   Postgres, workflows inactive), boots the target image, and checks: boots, no migration error, workflow count equals
   the manifest, the restored volume's key decrypts a restored credential, everything cleaned up. State must be PASSED.
   Receipt: `backups/n8n/n8n_upgrade_rehearsal_last.json` (seconds recorded: the rehearsal time is the expected
   downtime floor). Run it once with no arguments first to prove the harness on the current pin.
3. **Read the release notes** for breaking changes between the pin and the target; list any node or setting change
   next to the PR.
4. **PR.** Change the image tag in `docker-compose.n8n.yml` and `config/n8n_version_pin.json` together, attach the
   rehearsal receipt. The pin test fails if they disagree.
5. **Apply (operator window, markets closed).** `docker compose -f docker-compose.n8n.yml up -d m8m-n8n` recreates only
   the app container. Never `down`, never `-v`, never touch `m8m-n8n-db` or the `n8n-data` volume.
6. **Verify.** `/healthz` answers; the workflow count equals the pre-upgrade count; the next scheduled executions
   succeed (execution records, 0.1f); `scripts/n8n_bundle_restore_drill.py --apply` PASSES on a post-upgrade bundle.
7. **Roll back** if any check fails: set the previous tag in the compose file and this pin, recreate `m8m-n8n`, and if
   the database schema was migrated forward restore the pre-upgrade bundle (`scripts/n8n_lab_restore_drill.sh` shows
   the restore commands; restore into the live database only on the operator's word).

## Postgres
A Postgres major-version change is a dump-and-restore, not a tag edit; rehearse it the same way with a new
`postgres_image` and treat it as its own operator decision.
