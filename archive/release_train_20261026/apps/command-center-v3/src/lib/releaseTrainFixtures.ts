// Typed fixtures transcribed from docs/ops/RELEASE_TRAIN_API.md (67f83711a) sections 3–7, plus the STOP shapes from
// docs/ops/RELEASE_TRAIN_UI_CONTRACT.md. Used by releaseTrain.test.ts. When the backend lands, diff a captured
// response against these: a moved field fails a named check.
import type {
  ReleaseEventsWire, ReleaseQueueWire, ReleaseTrainDetailWire, ReleaseTrainSummaryWire, StopResultWire, StopStatusWire,
} from './releaseTrain.ts'

export const NOW_ISO = '2026-10-21T21:30:30+00:00'
const AT = '2026-10-21T21:30:00+00:00'
const SHA_A = 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678'
const SHA_B = 'b2c3d4e5f60718293a4b5c6d7e8f9012345678a1'

const ok = <T,>(value: T, source: string, reason: string | null = null, as_of = AT) => ({ value, as_of, freshness: 'OK', source, reason })

export const SUMMARY: ReleaseTrainSummaryWire = {
  schema: 'ReleaseTrainSummary@v1',
  authority: 'READ_ONLY_ADVISORY',
  generated_at: AT,
  status: 'DEGRADED',
  armed: ok(false, 'config/release_train_policy.json', 'phase_1_build_only'),
  standing_policy: ok({ state: 'NOT_CONFIGURED', detail: 'No standing delegation record exists (Phase 2, operator-applied).' }, 'config/release_train_delegation.json'),
  next_window: ok({
    window_id: '2026-10-21T18:00-04:00', local_time: '18:00', timezone: 'America/New_York', starts_at: '2026-10-21T18:00:00-04:00',
    starts_in_seconds: 1800, role: 'canary', enable_order: 1, enabled: false, note: 'First live canary window.',
  }, 'clock'),
  queue_counts: ok({ ready: 2, held: 5, needs_operator: 3, blocked: 1, in_train: 0, other: 0, total: 11 }, 'postgres:release_queue'),
  last_outcome: ok({
    train_id: 'rt-20261021-1800-a1b2c3', window_id: '2026-10-21T18:00-04:00', outcome: 'RELEASED_VERIFIED',
    finished_at: '2026-10-21T22:41:07+00:00', members: [1901, 1903], candidate_sha: SHA_A, main_sha: SHA_A, served_sha: SHA_A,
  }, 'postgres:release_queue_events'),
  stop: ok({ state: 'CLEAR', effective_stop: false, latched_at: null, window_id: null, latch_reason: null, reader: 'file',
    path: '<state root>/data/runtime/release_window/STOP.json', note: 'Release STOP only. The trading kill switch is separate.' }, 'file:release_window/STOP.json'),
  census: ok({
    status: 'COMPLETE', open_prs: 30, bucket_total: 30, invariant: 'open_prs == sum(buckets)', invariant_holds: true, incomplete_reasons: [],
    buckets: [
      { name: 'train_internal', count: 0, prs: [] }, { name: 'queued', count: 0, prs: [] }, { name: 'draft', count: 0, prs: [] },
      { name: 'held', count: 8, prs: [1629] }, { name: 'stacked', count: 3, prs: [1879] }, { name: 'conflicting', count: 13, prs: [1417] },
      { name: 'mergeability_unknown', count: 0, prs: [] }, { name: 'checks_failing', count: 1, prs: [1887] },
      { name: 'checks_pending', count: 0, prs: [] }, { name: 'checks_unknown', count: 0, prs: [] }, { name: 'unqueued_clean', count: 5, prs: [1901] },
    ],
  }, 'receipt:pr-hygiene-audit', null, '2026-10-21T10:30:12+00:00'),
  store: ok({ state: 'NOT_MIGRATED', tables: { release_queue_events: false, release_queue: false } }, 'postgres:to_regclass'),
}

/** Phase 1 reality on this host: store not migrated → queue counts UNAVAILABLE (never 0). */
export const SUMMARY_NOT_MIGRATED: ReleaseTrainSummaryWire = {
  ...SUMMARY,
  queue_counts: { value: null, as_of: null, freshness: 'UNAVAILABLE', source: 'postgres:release_queue', reason: 'not_migrated' },
  last_outcome: { value: null, as_of: null, freshness: 'UNAVAILABLE', source: 'postgres:release_queue_events', reason: 'not_migrated' },
}

export const QUEUE: ReleaseQueueWire = {
  schema: 'ReleaseTrainQueue@v1', generated_at: AT, as_of: AT, freshness: 'OK', source: 'postgres:release_queue', reason: null,
  store_state: 'OK', total: 3,
  rows: [
    { pr_number: 1901, repo: 'PatsKiller/tardeai', title: 'fix(x): broker helper', agent: 'claude:session_01Q', head_sha: SHA_A,
      state: 'held', risk_class: 'held', risk_reasons: [{ rule: 'broker_active_trader', class: 'held', path: 'scripts/active_trader/foo.py', detail: 'Broker / Active Trader code is always held.' }],
      depends_on: [1899], intended_window: '18:00', blocker: 'broker_active_trader',
      next_action: 'Needs an execution-engineering grant and a manual release; the train never carries it.', train_id: null,
      submitted_at: '2026-10-21T19:02:11+00:00', as_of: '2026-10-21T19:02:13+00:00', age_seconds: 8867, last_event_seq: 42, census_bucket: 'queued' },
    { pr_number: 1903, title: 'docs: runbook', agent: 'codex', head_sha: SHA_B, state: 'integrating', risk_class: 'eligible', depends_on: [],
      intended_window: '18:00', blocker: null, next_action: 'qualify', train_id: 'rt-20261021-1800-a1b2c3',
      submitted_at: '2026-10-21T18:00:00+00:00', age_seconds: null, census_bucket: 'queued' },
    { pr_number: 1905, title: null, agent: null, state: 'classified', risk_class: null, depends_on: null, submitted_at: null, age_seconds: null },
  ],
  census: SUMMARY.census,
}

export const QUEUE_NOT_MIGRATED: ReleaseQueueWire = {
  schema: 'ReleaseTrainQueue@v1', generated_at: AT, as_of: null, freshness: 'UNAVAILABLE', reason: 'not_migrated',
  store_state: 'NOT_MIGRATED', total: null, rows: null, census: SUMMARY.census,
}

const ev = (seq: number, train: string, type: string, state: string, at: string, payload: Record<string, unknown> = {}) => ({
  schema: 'TrainEvent@v1', seq, event_id: `rte-${seq}`, event_type: type, subject_kind: 'train', subject_id: `train:${train}`,
  pr_number: null, train_id: train, state_after: state, actor: 'release-controller', occurred_at: at, recorded_at: at, payload,
})

export const EVENTS: ReleaseEventsWire = {
  schema: 'ReleaseTrainEvents@v1', generated_at: AT, as_of: AT, freshness: 'OK', reason: null,
  events: [
    ev(1, 'rt-20261020-0000-aaaa1', 'frozen', 'selected', '2026-10-20T04:00:00+00:00', { window_id: '2026-10-20T00:00-04:00', members: [1, 2, 3] }),
    ev(2, 'rt-20261020-0000-aaaa1', 'outcome', 'merged', '2026-10-20T04:30:00+00:00', { outcome: 'MERGED_NOT_LIVE', candidate_sha: SHA_B }),
    ev(3, 'rt-20261020-1800-bbbb2', 'outcome', 'released', '2026-10-20T22:40:00+00:00', { outcome: 'RELEASED_VERIFIED', served_sha: SHA_A, candidate_sha: SHA_A }),
    ev(4, 'rt-20261021-0000-cccc3', 'outcome', 'observing', '2026-10-21T04:40:00+00:00', { outcome: 'RELEASED_OBSERVING' }),
    ev(5, 'rt-20261021-0600-dddd4', 'outcome', 'rolled_back', '2026-10-21T10:40:00+00:00', { outcome: 'ROLLED_BACK' }),
    ev(6, 'rt-20261021-0800-eeee5', 'outcome', 'rollback_failed', '2026-10-21T12:40:00+00:00', { outcome: 'ROLLBACK_FAILED' }),
    ev(7, 'rt-20261021-1800-a1b2c3', 'frozen', 'integrating', '2026-10-21T22:00:00+00:00', { members: [1903] }),
    { schema: 'TrainEvent@v1', seq: 8, event_type: 'classified', subject_kind: 'pr', subject_id: 'pr:1901', pr_number: 1901, train_id: null, state_after: 'held', occurred_at: AT },
  ],
  next_after_seq: 8,
}

export const DETAIL: ReleaseTrainDetailWire = {
  schema: 'ReleaseTrainDetail@v1', generated_at: AT, as_of: AT, freshness: 'OK', reason: null,
  train: {
    train_id: 'rt-20261021-1800-a1b2c3', window_id: '2026-10-21T18:00-04:00', phase: 'observing', history_class: 'observing',
    members: [{ pr_number: 1903, head_sha: SHA_B, risk_class: 'eligible', order: 2 }, { pr_number: 1901, head_sha: SHA_A, risk_class: 'eligible', order: 1 }],
    base_sha: SHA_B, candidate_sha: SHA_A, main_sha: SHA_A, served_sha: SHA_A, artifact_digest: 'sha256:' + '0'.repeat(64),
    check_manifest: ['cio-hardening', 'agent-governance', 'release-readiness', 'ci-gate'],
    frozen_at: '2026-10-21T20:30:00+00:00', started_at: '2026-10-21T20:30:00+00:00', finished_at: null, elapsed_seconds: 3600,
    rollback_target: '7faa8cddf-main-exact-phase2-20261021-154546', outcome: null, evidence: [],
    events: [
      { seq: 12, event_type: 'promoted', state_after: 'observing', actor: 'release-controller', occurred_at: '2026-10-21T21:10:00+00:00' },
      { seq: 10, event_type: 'frozen', state_after: 'selected', actor: 'release-controller', occurred_at: '2026-10-21T20:30:00+00:00' },
    ],
  },
}

export const STOP_ABSENT: StopStatusWire = {
  schema: 'ReleaseTrainStopStatus@v1', as_of: '2026-10-21T21:30:20Z', latch: { status: 'ABSENT', body: null, path: '/state/STOP.json', mtime: null },
  window_run_lock: 'FREE', phase: 'running', runner_reader: 'main_fail_open', reader_note: null, audit_tail: [],
  resume: { policy: 'host-CLI-only', command: 'python3 scripts/release_window.py clear-stop --reason "<why it is safe to resume>"' },
  separate_from_trading_kill_switch: true,
}

export const STOP_SET: StopStatusWire = {
  ...STOP_ABSENT,
  as_of: '2026-10-21T21:30:25Z',
  latch: { status: 'SET', path: '/state/STOP.json', mtime: '2026-10-21T21:30:21Z',
    body: { latched_at: '2026-10-21T21:30:21Z', actor: 'tailnet:john@jwwhiting.com', reason: 'bad batch', outcome: 'STOP_REQUESTED_OPERATOR', stop_id: 'rts-1' } },
  phase: 'stopped',
}

export const STOP_RESULT_OK: StopResultWire = {
  ok: true, schema: 'ReleaseTrainStopResult@v1', outcome: 'STOP_SET', phase: 'acknowledged', stop_id: 'rts-1',
  actor: 'tailnet:john@jwwhiting.com', reason: 'bad batch', requested_at: '2026-10-21T21:30:21Z', acknowledged_at: '2026-10-21T21:30:21Z',
  latch: STOP_SET.latch, replayed: false,
}

export const STOP_RESULT_REFUSED: StopResultWire = {
  ok: false, schema: 'ReleaseTrainStopResult@v1', outcome: 'REFUSED', refusal: 'CSRF', error: 'csrf: Origin not on allowlist',
}
