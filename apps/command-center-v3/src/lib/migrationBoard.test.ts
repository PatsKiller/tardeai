import { projectMigrationBoard, signalAgeLabel, lastRunLabel, toneForPhase, toneForRunState } from './migrationBoard.ts'
declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) }
}

const absent = projectMigrationBoard(null)
check('no payload is UNAVAILABLE with a danger tone', absent.status === 'UNAVAILABLE' && absent.statusTone === 'danger' && absent.rows.length === 0)

const none = projectMigrationBoard({ schema: 'N8nMigrationBoard@v1', status: 'NO_BOARD', note: 'not run', lanes: [], summary: {} })
check('a missing board file is NO BOARD (warning), not an error', none.status === 'NO_BOARD' && none.statusLabel === 'NO BOARD' && none.statusTone === 'warning' && none.note === 'not run')
check('phase chips always cover the five phases', none.byPhase.length === 5 && none.byPhase.every(p => p.n === 0))

const ok = projectMigrationBoard({
  schema: 'N8nMigrationBoard@v1', status: 'OK', as_of: '2026-10-08T13:05:00+00:00', lane_count: 3,
  summary: {
    per_tranche: { N1: { lanes: 2, by_phase: { CUT_OVER: 1, SHADOW: 1 }, risks: 0 }, N2: { lanes: 1, by_phase: { CANARY: 1 }, risks: 1 } },
    by_phase: { NOT_STARTED: 0, SHADOW: 1, CANARY: 1, CUT_OVER: 1, ROLLED_BACK: 0 },
    open_risks: [{ lane_id: 'premarket-data-pipeline', tranche: 'N2', flag: 'OUTPUT_SIGNAL_STALE', phase: 'CANARY' }],
    open_risk_count: 1, no_registry_row: 1,
  },
  lanes: [
    { lane_id: 'n8n-lab-watchdog', tranche: 'N1', registry_row: true, scheduler_of_record: 'n8n', phase: 'CUT_OVER',
      last_run: { run_id: 'r1', mode: 'live', state: 'RUN_DONE', exit_code: 0, duration_s: 1.25, finished_at: '2026-10-08T13:00:00+00:00' },
      expected_cadence_hours: 0.1, output_signal_age_h: 0.05, rollback_ready: true, readiness: 'GO', risk_flags: [] },
    { lane_id: 'n8n-monitor-dof', tranche: 'N1', registry_row: false, scheduler_of_record: 'unregistered', phase: 'SHADOW',
      last_run: { mode: 'dry_run', state: 'RUN_DONE', exit_code: 0 }, output_signal_age_h: null, rollback_ready: false, readiness: null, risk_flags: ['NO_REGISTRY_ROW'] },
    { lane_id: 'premarket-data-pipeline', tranche: 'N2', registry_row: true, scheduler_of_record: 'cron', phase: 'CANARY',
      last_run: { mode: 'live', state: 'RUN_FAILED', exit_code: 2, duration_s: 30 }, expected_cadence_hours: 24, output_signal_age_h: 60,
      rollback_ready: false, readiness: 'NO_GO', risk_flags: ['OUTPUT_SIGNAL_STALE'] },
  ],
})
check('OK label carries the lane count; a risk turns the status chip warning', ok.status === 'OK' && ok.statusLabel === 'OK · 3 lanes' && ok.statusTone === 'warning' && ok.asOfLabel === '2026-10-08 13:05')
check('phase tones: CUT_OVER success, CANARY info, SHADOW ai', ok.rows[0].phaseTone === 'success' && ok.rows[2].phaseTone === 'info' && ok.rows[1].phaseTone === 'ai' && toneForPhase('ROLLED_BACK') === 'danger')
check('last run label and tone', ok.rows[0].lastRun === 'live · RUN_DONE · exit 0 · 1.3 s' && ok.rows[0].lastRunTone === 'success' && ok.rows[2].lastRunTone === 'danger' && toneForRunState('RUN_SKIPPED_LOCK') === 'warning')
check('signal age labels and staleness (> 2x cadence)', ok.rows[0].signalAgeLabel === '3 min' && ok.rows[2].signalAgeLabel === '2.5 d' && ok.rows[2].signalStale === true && ok.rows[0].signalStale === false && ok.rows[1].signalAgeLabel === 'unverified')
check('readiness tones', ok.rows[0].readinessTone === 'success' && ok.rows[2].readinessTone === 'danger' && ok.rows[1].readinessTone === 'neutral')
check('rollback and registry flags', ok.rows[0].rollbackReady === true && ok.rows[1].registryRow === false && ok.rows[2].riskLabel === 'OUTPUT_SIGNAL_STALE')
check('tranche chips: a risk is danger, all cut over is success', ok.tranches.map(t => `${t.tranche}:${t.tone}`).join(',') === 'N1:info,N2:danger' && ok.openRiskCount === 1 && ok.noRegistryRow === 1)
check('helpers without a run', lastRunLabel(null) === 'no run' && signalAgeLabel(30) === '30.0 h')

console.log(`migrationBoard: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
