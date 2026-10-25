// Ops → Controls · Toggles tab model. Runs in the CC-v3 build:
//   node --experimental-strip-types src/lib/opsToggles.test.ts
import {
  changedText, effectiveOf, isOn, laneLastChange, laneToggles, maskPhone, settingRow, smsReadiness, testSendText,
  validateSmsEmail,
} from './opsToggles.ts'
import type { OpsControlsState } from './opsControls'
// No node:assert: CI's tsc has no @types/node (same local-assert pattern as opsControlsN8n.test.ts).
declare const process: { exit(code?: number): never }
function fail(m: string): never { console.log(`  [FAIL] ${m}`); process.exit(1) }
const eq = (a: unknown, b: unknown, m = '') => {
  const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) fail(`${m} expected ${y} got ${x}`)
}
const ok = (c: unknown, m: string) => { if (!c) fail(m) }
let n = 0
function t(name: string, fn: () => void) { fn(); n++; console.log(`  [PASS] ${name}`) }

const DOMAINS = ['msg.fi.google.com', 'vtext.com', 'tmomail.net', 'txt.att.net']
const state = (over: Partial<OpsControlsState> = {}): OpsControlsState => ({
  policy: { state: 'ACTIVE' }, store: { state: 'OK' }, applier: { state: 'OK' },
  factors: { webauthn_library: 'available', hmac_key: 'present', totp: 'enrolled', passkeys_active: 1 }, kinds: [],
  jobs: { state: 'OK' }, grants: { state: 'OK' }, data_approvals: { state: 'OK' } as OpsControlsState['data_approvals'],
  release_train: { state: 'OK' }, passkeys: [], audit: { state: 'OK' }, requests: [],
  n8n: { state: 'OK', rows: [
    { lane_id: 'zeta', on_live_list: true }, { lane_id: 'cio-prospect-shadow', on_live_list: false, stage: 'canary' },
    { lane_id: 'alpha', on_live_list: true }, { lane_id: 'conflict-resolver', on_live_list: false },
  ] },
  settings: { state: 'OK', rows: [
    { key: 'comms.sms.enabled', type: 'bool', env_key: 'ENABLE_SMS', effective: { value: 'true', source: 'environment' } },
    { key: 'comms.sms.operator_email', type: 'string', env_key: 'OPERATOR_SMS_EMAIL', overridden: true, current: '••••••4567@vtext.com',
      updated_at: '2026-10-25T18:00:00Z', updated_by: 'tailnet:john@jwwhiting.com', effective: { value: '••••••4567@vtext.com', source: 'operator_setting' } },
    { key: 'comms.gateway_mode', type: 'enum', choices: ['OFF', 'CANARY', 'ACTIVE'], env_key: 'COMMS_GATEWAY_MODE', effective: { value: 'OFF', source: 'default' } },
  ] },
  toggles: { state: 'OK', channels: { sms: true, email: true } },
  ...over,
})

t('sms address validator mirrors the server', () => {
  eq(validateSmsEmail(' 5551234567@VText.com ', DOMAINS), { ok: true, value: '5551234567@vtext.com' })
  ok(!validateSmsEmail('555123456@vtext.com', DOMAINS).ok, '9 digits refused')
  ok(!validateSmsEmail('555-123-4567@vtext.com', DOMAINS).ok, 'dashes refused')
  ok(!validateSmsEmail('5551234567@gmail.com', DOMAINS).ok, 'unknown domain refused')
  ok(!validateSmsEmail('5551234567@vtext.com.evil.io', DOMAINS).ok, 'suffix trick refused')
  ok(!validateSmsEmail('', DOMAINS).ok, 'empty refused')
})

t('maskPhone keeps last 4 and the domain; idempotent', () => {
  eq(maskPhone('5551234567@vtext.com'), '••••••4567@vtext.com')
  eq(maskPhone('••••••4567@vtext.com'), '••••••4567@vtext.com')
})

t('effective value and source come from the server; unknown on an older server', () => {
  const s = state()
  eq(effectiveOf(settingRow(s, 'comms.sms.enabled')), { value: 'true', source: 'environment' })
  eq(effectiveOf(settingRow(s, 'nope')), { value: null, source: 'unknown' })
  eq(effectiveOf({ key: 'x', type: 'bool' }), { value: null, source: 'unknown' })
  eq([isOn('true'), isOn(false), isOn(null)], [true, false, null])
})

t('changedText names who and when, or says never', () => {
  const s = state()
  eq(changedText(settingRow(s, 'comms.sms.operator_email'), iso => iso.slice(0, 10)), '2026-10-25 · john@jwwhiting.com')
  eq(changedText({ key: 'x', type: 'bool', overridden: false }, String), 'Never changed here')
})

t('sms readiness lists every blocker in words', () => {
  const r = smsReadiness(state())
  eq(r.ready, false)
  ok(r.reasons.some(x => x.startsWith('Gateway mode is OFF')), 'mode blocker named')
  const s2 = state()
  s2.settings.rows![2].effective = { value: 'CANARY', source: 'operator_setting' }
  eq(smsReadiness(s2), { ready: true, reasons: [] })
  s2.toggles = { state: 'OK', channels: { sms: false, email: true } }
  ok(smsReadiness(s2).reasons.some(x => x.includes('PR 2105')), 'missing channel named')
})

t('lane toggles: live first, then by id; query filters; last change from applied requests', () => {
  const s = state({ requests: [
    { request_id: 'r1', kind: 'n8n_live_list.add', direction: 'risky', status: 'APPLIED', params: { lane_id: 'alpha' }, applied_at: '2026-10-24T10:00:00Z', actor: 'tailnet:john@jwwhiting.com' },
    { request_id: 'r2', kind: 'n8n_live_list.add', direction: 'risky', status: 'FAILED', params: { lane_id: 'alpha' }, applied_at: '2026-10-25T10:00:00Z' },
  ] })
  eq(laneToggles(s).map(l => l.lane_id), ['alpha', 'zeta', 'cio-prospect-shadow', 'conflict-resolver'])
  eq(laneToggles(s, 'CIO').map(l => l.lane_id), ['cio-prospect-shadow'])
  eq(laneLastChange(s.requests, 'alpha'), { at: '2026-10-24T10:00:00Z', by: 'john@jwwhiting.com' })
  eq(laneLastChange(s.requests, 'zeta'), null)
  const s3 = state(); s3.n8n = { state: 'UNAVAILABLE', rows: [{ lane_id: 'a', on_live_list: null as unknown as boolean }] }
  eq(laneToggles(s3)[0].live, null)
})

t('test send result in words', () => {
  ok(testSendText({ channel: 'sms', test_id: 'x', at: 'now', delivered: true }).startsWith('Sent (sms)'), 'sent')
  eq(testSendText({ channel: 'sms', test_id: 'x', at: 'now', delivered: false, error: 'delivery_blocked_mode', gateway_mode: 'OFF' }),
    'Not sent: delivery_blocked_mode (gateway mode OFF).')
})

console.log(`opsToggles: ${n} passed`)
