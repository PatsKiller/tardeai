// Ops → Controls · Jobs readability: classification (live crontab × registry → plain status / mismatch) and the
// cron humanizer. Runs in the CC-v3 build:  node --experimental-strip-types src/lib/opsControlsJobs.test.ts
import {
  classifyJob, expandField, extractCronExpr, filterCounts, humanizeCron, matchesFilter, matchesQuery, parsePausedLine,
  startsWithCron, type JobRowX,
} from './opsControlsJobs.ts'
// No node:assert: CI's tsc has no @types/node (same local-assert pattern as opsControls.test.ts).
declare const process: { exit(code?: number): never }
function fail(m: string): never { console.log(`  [FAIL] ${m}`); process.exit(1) }
const eq = (a: unknown, b: unknown, m = '') => {
  const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) fail(`${m} expected ${y} got ${x}`)
}
const ok = (c: unknown, m: string) => { if (!c) fail(m) }
let n = 0
function t(name: string, fn: () => void) { fn(); n++; console.log(`  [PASS] ${name}`) }

const SHA = 'a'.repeat(64)
const row = (p: Partial<JobRowX>): JobRowX => ({
  lane_id: 'lane-x', cron_state: 'ACTIVE', line_sha256: SHA, display: '7,22,37,52 9-16 * * 1-5 cd $PROJ && $PY x.py',
  registry_state: 'ACTIVE', scheduler_kind: 'cron', schedule: '7,22,37,52 9-16 * * 1-5', ...p,
})
const SPCX = '# PAUSED 2026-10-14 schwab-app-deactivated (incident SPCX) 31 9 * * 1-5 cd $PROJ && flock -n /tmp/s.lock x'
const PAGE = `# PAUSED 2026-10-20 ops-controls:0123456789abcdef 5 8 * * 1-5 cd $PROJ && $PY y.py`

// ── cron humanizer ────────────────────────────────────────────────────────────────────────────────────────────────
t('humanize: the operator example — weekdays every 15 min in market hours', () => {
  eq(humanizeCron('7,22,37,52 9-16 * * 1-5'), 'weekdays 09:07–16:52 every 15 min')
  eq(humanizeCron('*/15 9-16 * * 1-5'), 'weekdays 09:00–16:45 every 15 min')
  eq(humanizeCron('7-59/20 9-16 * * 1-5'), 'weekdays 09:07–16:47 every 20 min')
})
t('humanize: single times, lists and hourly windows', () => {
  eq(humanizeCron('0 20 * * 6'), 'Saturdays at 20:00')
  eq(humanizeCron('30 8,20 * * *'), 'every day at 08:30, 20:30')
  eq(humanizeCron('0 10-16 * * 1-5'), 'weekdays hourly 10:00–16:00')
  eq(humanizeCron('45 19 * * *'), 'every day at 19:45')
  eq(humanizeCron('0 9-18/3 * * 1-5'), 'weekdays at 09:00, 12:00, 15:00, 18:00')
  eq(humanizeCron('15 */2 * * *'), 'every 2 h at :15 (00:15–22:15)')
})
t('humanize: all-day cadences, days of month, names, keywords', () => {
  eq(humanizeCron('*/5 * * * *'), 'every 5 min')
  eq(humanizeCron('20 * * * *'), 'every hour at :20')
  eq(humanizeCron('7,37 * * * *'), 'every 30 min (from :07)')
  eq(humanizeCron('* * * * *'), 'every minute')
  eq(humanizeCron('0 9 1 * *'), 'on day 1 of the month at 09:00')
  eq(humanizeCron('5 16 * * MON,WED,FRI'), 'Mon, Wed, Fri at 16:05')
  eq(humanizeCron('0 8 * * 0'), 'Sundays at 08:00')
  eq(humanizeCron('0 8 * * 0,6'), 'weekends at 08:00')
  eq(humanizeCron('0 8 * * 1-4'), 'Mon–Thu at 08:00')
  eq(humanizeCron('@reboot'), 'once at host boot')
})
t('humanize: refuses what it cannot read (never guesses)', () => {
  eq(humanizeCron(null), null)
  eq(humanizeCron(''), null)
  eq(humanizeCron('(incident SPCX) 31 9 *'), null)
  eq(humanizeCron('61 9 * * *'), null)
  eq(humanizeCron('@sometimes'), null)
  eq(expandField('5-2', 0, 59), null)
  eq(expandField('*/0', 0, 59), null)
})
t('extractCronExpr skips a multi-word paused note; startsWithCron rejects it', () => {
  eq(extractCronExpr(SPCX), '31 9 * * 1-5')
  eq(extractCronExpr('7,22,37,52 9-16 * * 1-5 cd $PROJ'), '7,22,37,52 9-16 * * 1-5')
  eq(extractCronExpr('@reboot sleep 60 && cd x'), '@reboot')
  eq(extractCronExpr('cd set run now please ok'), null)
  ok(startsWithCron('31 9 * * 1-5 cd x'), 'cron line starts with cron')
  ok(!startsWithCron('(incident SPCX) 31 9 * * 1-5 cd x'), 'parenthetical is not cron')
})

// ── paused-line parsing ───────────────────────────────────────────────────────────────────────────────────────────
t('parsePausedLine: SPCX convention keeps the incident in the reason and is not page-resumable', () => {
  const p = parsePausedLine(SPCX)!
  eq([p.date, p.note, p.reason, p.resumable], ['2026-10-14', 'schwab-app-deactivated', 'schwab-app-deactivated (incident SPCX)', false])
  const q = parsePausedLine(PAGE)!
  eq([q.reason, q.resumable], ['paused from this page (01234567)', true])
  eq(parsePausedLine('# PAUSED_MASTER_REWRITE 5 * * * * x'), null)
})

// ── classification: live crontab × registry ───────────────────────────────────────────────────────────────────────
t('agree: ACTIVE+ACTIVE running, PAUSED+PAUSED paused, ABSENT+RETIRED retired and quiet', () => {
  const a = classifyJob(row({}))
  eq([a.category, a.label, a.mismatch, a.action, a.scheduleText], ['running', 'Running', null, 'pause', 'weekdays 09:07–16:52 every 15 min'])
  const p = classifyJob(row({ cron_state: 'PAUSED', registry_state: 'PAUSED', display: SPCX, paused_on: '2026-10-14', paused_note: 'schwab-app-deactivated' }))
  eq([p.category, p.label, p.mismatch], ['paused', 'Paused since 2026-10-14 (schwab-app-deactivated (incident SPCX))', null])
  eq(p.action, null, 'SPCX paused line: no page Resume')
  ok(/host terminal/.test(p.actionNote || ''), 'host-terminal note')
  eq(p.cronExpr, '31 9 * * 1-5')
  const r = classifyJob(row({ cron_state: 'ABSENT', registry_state: 'RETIRED', display: null, line_sha256: null, schedule: '0 3 * * *' }))
  eq([r.category, r.label, r.mismatch, r.quiet, r.scheduleText], ['retired', 'Retired (off on purpose)', null, true, 'every day at 03:00'])
  const nv = classifyJob(row({ cron_state: 'ABSENT', registry_state: 'NEVER_SCHEDULED', display: null, line_sha256: null }))
  eq([nv.category, nv.quiet, nv.mismatch], ['retired', true, null])
})
t('mismatch: ACTIVE + registry RETIRED / PAUSED / NEVER_SCHEDULED', () => {
  const v = classifyJob(row({ registry_state: 'RETIRED' }))
  eq([v.category, v.tone, v.mismatch, v.label], ['running', 'danger', 'Cron runs it, but the registry says it is retired', 'Running — but registry says it is retired'])
  ok(classifyJob(row({ registry_state: 'PAUSED' })).mismatch, 'ACTIVE+PAUSED flagged')
  ok(classifyJob(row({ registry_state: 'NEVER_SCHEDULED' })).mismatch, 'ACTIVE+NEVER_SCHEDULED flagged')
})
t('mismatch: ABSENT + registry ACTIVE, unless n8n runs it live', () => {
  const off = classifyJob(row({ cron_state: 'ABSENT', display: null, line_sha256: null }))
  eq([off.category, off.label], ['off', 'Off — but registry says it should run'])
  ok(off.mismatch, 'ABSENT+ACTIVE flagged')
  const n8n = classifyJob(row({ cron_state: 'ABSENT', display: null, line_sha256: null, dispatch_mode: 'live' }))
  eq([n8n.category, n8n.label, n8n.mismatch], ['running', 'Runs on n8n (no crontab line)', null])
  eq(classifyJob(row({ cron_state: 'ABSENT', display: null, line_sha256: null, dispatch_mode: 'dry_run' })).mismatch !== null, true)
})
t('mismatch: PAUSED + registry ACTIVE; page-paused line is resumable', () => {
  const v = classifyJob(row({ cron_state: 'PAUSED', display: PAGE, paused_on: '2026-10-20', paused_note: 'ops-controls:0123456789abcdef' }))
  eq([v.category, v.action], ['paused', 'resume'])
  eq(v.mismatch, 'Commented out in the crontab, but the registry says it should run')
})
t('no mismatch: ABSENT + registry PAUSED; PAUSED + RETIRED is retired', () => {
  const v = classifyJob(row({ cron_state: 'ABSENT', registry_state: 'PAUSED', display: null, line_sha256: null }))
  eq([v.category, v.mismatch, v.action], ['paused', null, null])
  const w = classifyJob(row({ cron_state: 'PAUSED', registry_state: 'RETIRED', display: SPCX }))
  eq([w.category, w.mismatch], ['retired', null])
})
t('AMBIGUOUS: uses match_counts when present, never acts, still flags a disagreement', () => {
  const a = classifyJob(row({ cron_state: 'AMBIGUOUS', line_sha256: null, display: null, match_counts: { active: 2, paused: 0 } }))
  eq([a.category, a.label, a.action, a.mismatch], ['running', 'Running · 2 matching cron lines', null, null])
  ok(/host terminal/.test(a.actionNote || ''), 'ambiguous → host terminal')
  const p = classifyJob(row({ cron_state: 'AMBIGUOUS', registry_state: 'PAUSED', line_sha256: null, display: null, match_counts: { active: 0, paused: 2 } }))
  eq([p.category, p.mismatch], ['paused', null])
  const r = classifyJob(row({ cron_state: 'AMBIGUOUS', registry_state: 'RETIRED', line_sha256: null, display: null, match_counts: { active: 3, paused: 0 } }))
  ok(r.mismatch, 'ambiguous running + retired flagged')
  const old = classifyJob(row({ cron_state: 'AMBIGUOUS', line_sha256: null, display: null }))
  eq([old.category, old.mismatch], ['unclear', null])
})
t('registry expression with several schedules is humanized part by part', () => {
  const v = classifyJob(row({ cron_state: 'ABSENT', display: null, line_sha256: null, schedule: '0 4-9 * * 1-5 + 30 4-15 * * 1-5' }))
  eq([v.cronExpr, v.scheduleText], ['0 4-9 * * 1-5 + 30 4-15 * * 1-5', 'weekdays hourly 04:00–09:00; weekdays hourly 04:30–15:30'])
  const w = classifyJob(row({ cron_state: 'ABSENT', display: null, line_sha256: null, schedule: 'dispatcher' }))
  eq([w.cronExpr, w.scheduleText], [null, null])
})
t('filters, counts and search', () => {
  const rows = [
    row({ lane_id: 'alpha' }),
    row({ lane_id: 'beta', registry_state: 'RETIRED', broker_class: true }),
    row({ lane_id: 'gamma', cron_state: 'PAUSED', registry_state: 'PAUSED', display: SPCX, broker_class: true }),
    row({ lane_id: 'delta', cron_state: 'ABSENT', registry_state: 'RETIRED', display: null, line_sha256: null }),
  ]
  eq(filterCounts(rows), { all: 4, attention: 1, running: 2, paused: 1, retired: 1, broker: 2 })
  ok(matchesFilter(rows[1], classifyJob(rows[1]), 'attention'), 'beta needs attention')
  ok(matchesQuery(rows[0], 'ALP') && !matchesQuery(rows[0], 'zzz') && matchesQuery(rows[0], '  '), 'search by name')
})

console.log(`opsControlsJobs: ${n} passed`)
