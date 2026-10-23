// Ops → Controls pure helpers (docs/ops/OPS_CONTROLS_API.md). Runs in the CC-v3 build:
//   node --experimental-strip-types src/lib/opsControls.test.ts
import {
  actBlockReason, base64urlToBuffer, bufferToBase64url, canAct, credentialToJSON, isTerminal, kindFor, phraseMatches,
  toPublicKeyCreationOptions, toPublicKeyRequestOptions, validateSetting, type OpsControlsState,
} from './opsControls.ts'
// No node:assert: CI's tsc has no @types/node (same local-assert pattern as designTokens.test.ts).
declare const process: { exit(code?: number): never }
const norm = (v: unknown): unknown => v instanceof Uint8Array ? { u8: [...v] } : Array.isArray(v) ? v.map(norm)
  : v && typeof v === 'object' ? Object.fromEntries(Object.keys(v as object).sort().map(k => [k, norm((v as any)[k])])) : v
function fail(m: string): never { console.log(`  [FAIL] ${m}`); process.exit(1) }
const assert = {
  equal: (a: unknown, b: unknown, m = '') => { if (a !== b) fail(`${m} expected ${JSON.stringify(b)} got ${JSON.stringify(a)}`) },
  deepEqual: (a: unknown, b: unknown, m = '') => {
    const x = JSON.stringify(norm(a)), y = JSON.stringify(norm(b)); if (x !== y) fail(`${m} expected ${y} got ${x}`)
  },
  match: (s: string, re: RegExp) => { if (!re.test(s)) fail(`${JSON.stringify(s)} !~ ${re}`) },
  doesNotMatch: (s: string, re: RegExp) => { if (re.test(s)) fail(`${JSON.stringify(s)} =~ ${re}`) },
}

let n = 0
function t(name: string, fn: () => void) { fn(); n++; console.log(`  [PASS] ${name}`) }

const KINDS = [
  { kind: 'crontab.pause', label: 'Pause', direction: 'risky', supported: true, reason: null, executor: 'applier', tab: 'jobs' },
  { kind: 'release_train.stop', label: 'STOP', direction: 'safe', supported: true, reason: null, executor: 'applier', tab: 'jobs' },
  { kind: 'kill_switch.clear', label: 'Clear', direction: 'risky', supported: false, reason: 'broker-execution code', executor: null, tab: 'jobs' },
]
function state(over: Partial<OpsControlsState> = {}): OpsControlsState {
  return {
    policy: { state: 'ACTIVE' }, store: { state: 'OK' }, applier: { state: 'OK' },
    factors: { webauthn_library: 'available', hmac_key: 'present', totp: 'enrolled', passkeys_active: 1 },
    kinds: KINDS as any, jobs: { state: 'OK' }, n8n: { state: 'OK' }, settings: { state: 'OK' }, grants: { state: 'OK' },
    data_approvals: { state: 'OK' }, release_train: { state: 'OK' }, passkeys: [], audit: { state: 'OK' }, requests: [],
    ...over,
  }
}

t('canAct: ACTIVE + store OK + supported kind', () => {
  assert.equal(canAct(state(), 'crontab.pause'), true)
  assert.equal(canAct(state(), 'release_train.stop'), true)
})
t('canAct refuses when policy NOT_ACTIVE (inert)', () => {
  const s = state({ policy: { state: 'NOT_ACTIVE', required: '19.0.0' } })
  assert.equal(canAct(s, 'release_train.stop'), false)
  assert.equal(canAct(s, 'crontab.pause'), false)
  assert.match(actBlockReason(s, 'crontab.pause') || '', /19\.0\.0/)
})
t('canAct refuses UNREADABLE policy, missing state, unmigrated store', () => {
  assert.equal(canAct(state({ policy: { state: 'UNREADABLE' } }), 'crontab.pause'), false)
  assert.equal(canAct(null, 'crontab.pause'), false)
  assert.equal(canAct(state({ store: { state: 'NOT_MIGRATED', missing_tables: ['x'] } }), 'crontab.pause'), false)
  assert.equal(canAct(state({ store: { state: 'UNAVAILABLE' } }), 'crontab.pause'), false)
})
t('canAct refuses unsupported and unknown kinds, with the host-terminal reason', () => {
  assert.equal(canAct(state(), 'kill_switch.clear'), false)
  assert.equal(actBlockReason(state(), 'kill_switch.clear'), 'Host terminal only: broker-execution code')
  assert.equal(canAct(state(), 'no.such.kind'), false)
})
t('kindFor finds by name, null otherwise', () => {
  assert.equal(kindFor(state(), 'crontab.pause')?.direction, 'risky')
  assert.equal(kindFor(state(), 'nope'), null)
  assert.equal(kindFor(null, 'crontab.pause'), null)
})
t('isTerminal', () => {
  for (const s of ['APPLIED', 'FAILED', 'REFUSED', 'EXPIRED', 'CANCELLED']) assert.equal(isTerminal(s), true, s)
  for (const s of ['PREVIEWED', 'AWAITING_STEP_UP', 'STEP_UP_VERIFIED', 'APPROVED', 'APPLYING', '', null, undefined]) assert.equal(isTerminal(s as any), false, String(s))
})
t('phraseMatches: whitespace-collapsed exact compare', () => {
  const p = 'ADD LIVE pr-hygiene-audit 2026-10-22'
  assert.equal(phraseMatches(p, p), true)
  assert.equal(phraseMatches('  ADD   LIVE pr-hygiene-audit\t2026-10-22 ', p), true)
  assert.equal(phraseMatches('add live pr-hygiene-audit 2026-10-22', p), false)
  assert.equal(phraseMatches('ADD LIVE pr-hygiene-audit', p), false)
  assert.equal(phraseMatches('', ''), false)
  assert.equal(phraseMatches('x', null), false)
})
t('base64url round trip (all byte values, every length mod 3)', () => {
  const all = new Uint8Array(256).map((_, i) => i)
  for (const len of [0, 1, 2, 3, 4, 5, 32, 255, 256]) {
    const src = all.slice(0, len)
    const enc = bufferToBase64url(src.buffer)
    assert.doesNotMatch(enc, /[+/=]/)
    assert.deepEqual(new Uint8Array(base64urlToBuffer(enc)), src)
  }
  assert.equal(bufferToBase64url(new Uint8Array([251, 255]).buffer), '-_8')
  assert.deepEqual([...new Uint8Array(base64urlToBuffer('-_8'))], [251, 255])
  const view = new Uint8Array([9, 1, 2, 3, 9]).subarray(1, 4)
  assert.equal(bufferToBase64url(view), bufferToBase64url(new Uint8Array([1, 2, 3]).buffer))
})
t('toPublicKeyRequestOptions decodes challenge and allowCredentials ids (bare or {publicKey})', () => {
  const json = { challenge: 'AQID', rpId: 'x', userVerification: 'required', allowCredentials: [{ type: 'public-key', id: 'BAUG' }] }
  for (const o of [json, { publicKey: json }]) {
    const r: any = toPublicKeyRequestOptions(o)
    assert.deepEqual([...new Uint8Array(r.challenge)], [1, 2, 3])
    assert.deepEqual([...new Uint8Array(r.allowCredentials[0].id)], [4, 5, 6])
    assert.equal(r.userVerification, 'required')
  }
})
t('toPublicKeyCreationOptions decodes challenge, user.id, excludeCredentials ids', () => {
  const r: any = toPublicKeyCreationOptions({ challenge: 'AQID', rp: { name: 'cc' }, user: { id: 'BwgJ', name: 'op', displayName: 'Op' },
    pubKeyCredParams: [{ type: 'public-key', alg: -7 }], excludeCredentials: [{ type: 'public-key', id: 'CgsM' }] })
  assert.deepEqual([...new Uint8Array(r.challenge)], [1, 2, 3])
  assert.deepEqual([...new Uint8Array(r.user.id)], [7, 8, 9])
  assert.equal(r.user.name, 'op')
  assert.deepEqual([...new Uint8Array(r.excludeCredentials[0].id)], [10, 11, 12])
})
t('credentialToJSON encodes every binary field base64url', () => {
  const b = (...x: number[]) => new Uint8Array(x).buffer
  const j = credentialToJSON({ id: 'abc', rawId: b(1, 2, 3), type: 'public-key', authenticatorAttachment: 'platform',
    response: { clientDataJSON: b(4), authenticatorData: b(5), signature: b(6), userHandle: b(7), getTransports: () => ['internal'] },
    getClientExtensionResults: () => ({}) })
  assert.equal(j.rawId, 'AQID')
  assert.deepEqual(j.response, { clientDataJSON: 'BA', authenticatorData: 'BQ', signature: 'Bg', userHandle: 'Bw', transports: ['internal'] })
  const c = credentialToJSON({ id: 'z', rawId: b(1), type: 'public-key', response: { clientDataJSON: b(1), attestationObject: b(2) } })
  assert.equal(c.response.attestationObject, 'Ag')
  assert.equal('signature' in c.response, false)
})
t('validateSetting enforces type, range and choices', () => {
  assert.deepEqual(validateSetting({ type: 'float', min: 0, max: 1 }, '0.43'), { ok: true, value: 0.43 })
  assert.equal(validateSetting({ type: 'float', min: 0, max: 1 }, '1.5').ok, false)
  assert.equal(validateSetting({ type: 'float' }, 'abc').ok, false)
  assert.deepEqual(validateSetting({ type: 'int', min: 1 }, '5'), { ok: true, value: 5 })
  assert.equal(validateSetting({ type: 'int' }, '5.5').ok, false)
  assert.equal(validateSetting({ type: 'int', min: 1 }, '0').ok, false)
  assert.deepEqual(validateSetting({ type: 'bool' }, 'false'), { ok: true, value: false })
  assert.equal(validateSetting({ type: 'bool' }, 'yes').ok, false)
  assert.deepEqual(validateSetting({ type: 'enum', choices: ['a', 'b'] }, 'b'), { ok: true, value: 'b' })
  assert.equal(validateSetting({ type: 'enum', choices: ['a'] }, 'c').ok, false)
  assert.equal(validateSetting({ type: 'string' }, '  ').ok, false)
})

console.log(`opsControls: ${n} passed`)
