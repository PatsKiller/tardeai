/**
 * Stage 4 patch for OpenClaw dist/store-*.js (2026.6.11 store-DXF66QL3.js shape).
 *
 * Problem: saveCronJobsStore writes SQLite only; jobs.json is a store key, not
 * a flushed file. Maria reminders claimed durable schedules while
 * ~/.openclaw/cron/jobs.json was absent (only .migrated / .bak* remained).
 *
 * Apply under an active `openclaw` grant + write access to the gateway package:
 *
 *   1. Backup the live store file.
 *   2. Merge the two hunks below into saveCronJobsStore + loadCronJobsStoreWithConfigJobs
 *      (or re-run the Trade-AI recover CLI, then restart the gateway).
 *   3. Prefer the Trade-AI helper for operator recovery without package edits:
 *        .venv/bin/python scripts/recover_gateway_cron_jobs_mirror.py --dry-run
 *        .venv/bin/python scripts/recover_gateway_cron_jobs_mirror.py --apply
 *
 * AGENTS.md §0.5: never auto-merge divergent .migrated vs .bak copies.
 */

/* HUNK A — append after replaceCronRows in saveCronJobsStore: */
/*
	try {
		const resolved = path.resolve(storePath);
		await atomicWrite(resolved, JSON.stringify({
			version: store?.version ?? 1,
			jobs: Array.isArray(store?.jobs) ? store.jobs : []
		}, null, 2) + "\n");
	} catch (err) {
		console.error(`[cron-store] jobs.json atomic flush failed: ${err?.message || err}`);
	}
*/

/* HUNK B — when SQLite rows are empty, recover sidecars before returning empty store.
   Prefer Trade-AI scripts/lib/gateway_cron_jobs_mirror.py for the recovery logic;
   call it from a one-shot under grant rather than duplicating merge policy here. */
