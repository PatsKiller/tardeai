// Ops → Controls (feat/ops-controls-20261022): the client side of docs/ops/OPS_CONTROLS_API.md.
// Types for GET /state and the request object, the API client (every POST is JSON, same-origin, with an
// idempotency key where the contract asks for one), WebAuthn base64url <-> ArrayBuffer helpers, and the pure
// gates the page uses: canAct (inert unless policy ACTIVE, store OK and the kind supported), isTerminal,
// phraseMatches (a mirror of the server's whitespace-collapsed exact compare), kindFor and validateSetting.
// The server decides every kind's direction; nothing here chooses it. Pure module: no React, no DOM at import.

import type { DataApprovals } from './opsControlsData'

export const OPS_CONTROLS_BASE = '/api/v2/ops/controls'

export type PolicyState = 'ACTIVE' | 'NOT_ACTIVE' | 'UNREADABLE'
export type StoreState = 'OK' | 'NOT_MIGRATED' | 'UNAVAILABLE'
export type ApplierState = 'OK' | 'STALE' | 'ABSENT'
export type SectionState = 'OK' | 'NOT_MIGRATED' | 'UNAVAILABLE'
export type Direction = 'safe' | 'risky'
export type RequestStatus = 'PREVIEWED' | 'AWAITING_STEP_UP' | 'STEP_UP_VERIFIED' | 'APPROVED' | 'APPLYING' | 'APPLIED'
  | 'FAILED' | 'REFUSED' | 'EXPIRED' | 'CANCELLED'

export type KindInfo = {
  kind: string; label: string; direction: Direction; supported: boolean; reason: string | null
  executor: 'applier' | 'cc' | null; tab: string | null
}
export type JobRow = {
  lane_id: string; registry_state?: string; scheduler_kind?: string
  cron_state: 'ACTIVE' | 'PAUSED' | 'ABSENT' | 'AMBIGUOUS'; schedule?: string | null; line_sha256: string | null
  display: string | null; paused_on?: string | null; paused_note?: string | null
  broker_class?: boolean; broker_tokens?: string[]; note?: string | null
}
export type N8nRow = { lane_id: string; stage?: string; mode?: string; on_live_list: boolean; workflow?: string | null }
export type SettingType = 'bool' | 'int' | 'float' | 'string' | 'enum'
export type SettingValue = boolean | number | string
export type SettingRow = {
  key: string; label?: string; type: SettingType; default?: SettingValue | null; current?: SettingValue | null
  overridden?: boolean; min?: number | null; max?: number | null; choices?: string[] | null; wired?: boolean
  consumer?: string | null; updated_at?: string | null; updated_by?: string | null
}
export type SettingHistory = { key: string; old_value: unknown; new_value: unknown; actor?: string; at?: string; request_id?: string }
export type ActiveGrant = { tier: string; uses?: string | number | null; minutes_left?: number | null; grant_id8?: string; grant_id?: string; reason?: string | null }
export type Passkey = { credential_id8: string; credential_id?: string; name: string; created_at?: string | null; last_used_at?: string | null; revoked_at?: string | null }
export type AuditRow = {
  seq: number; at?: string; actor?: string; action?: string; kind?: string | null; request_id?: string | null
  outcome?: string | null; detail?: Record<string, unknown> | null; undo_available?: boolean
}
export type Preview = { summary?: string; before?: string | null; after?: string | null; diff?: string[]; warnings?: string[] }
export type OpsRequest = {
  request_id: string; kind: string; label?: string; direction: Direction; executor?: string
  params?: Record<string, unknown>; phrase?: string | null; preview?: Preview | null; expected_state_digest?: string
  status: RequestStatus; status_at?: string; created_at?: string; approved_at?: string | null; applied_at?: string | null
  actor?: string; result?: { outcome?: string; verify?: unknown; backup_ref?: string; detail?: string } | null
  undo_of?: string | null; undone_by?: string | null
  undo?: { available: boolean; kind?: string | null; direction?: Direction | null; reason?: string | null } | null
}
type Section = { state: SectionState; reason?: string | null }
export type OpsControlsState = {
  ok?: boolean; schema?: string; as_of?: string; operator?: string
  policy: { state: PolicyState; required?: string; detail?: string }
  store: { state: StoreState; missing_tables?: string[]; reason?: string | null }
  applier: { state: ApplierState; heartbeat_at?: string | null; age_s?: number | null; reason?: string | null }
  factors: { webauthn_library: 'available' | 'missing'; hmac_key: 'present' | 'missing'; totp: 'enrolled' | 'not_enrolled'; passkeys_active: number }
  kinds: KindInfo[]
  jobs: Section & { as_of?: string; rows?: JobRow[]; unmatched_active_lines?: number }
  n8n: Section & { live_list_path?: string; live_lanes?: string[]; rows?: N8nRow[] }
  settings: Section & { rows?: SettingRow[]; history?: SettingHistory[] }
  grants: Section & { tiers?: string[]; active?: ActiveGrant[] }
  // per-domain readiness (scripts/lib/data_domain_readiness.py); older servers send rows with domain/title/status only
  data_approvals: Section & Omit<DataApprovals, 'state' | 'reason'>
  release_train: Section & { mode?: string; epoch?: number | null; latch?: string }
  passkeys: Passkey[]
  audit: Section & { rows?: AuditRow[] }
  requests: OpsRequest[]
}

// ── pure gates ─────────────────────────────────────────────────────────────────────────────────────────
export const TERMINAL_STATUSES: readonly RequestStatus[] = ['APPLIED', 'FAILED', 'REFUSED', 'EXPIRED', 'CANCELLED']
export function isTerminal(status: string | null | undefined): boolean {
  return TERMINAL_STATUSES.includes(String(status || '') as RequestStatus)
}

export function kindFor(state: Pick<OpsControlsState, 'kinds'> | null | undefined, kind: string): KindInfo | null {
  return (state?.kinds || []).find(k => k.kind === kind) || null
}

/** Why an action is refused, or null when it may be offered. Fail closed on anything missing. */
export function actBlockReason(state: OpsControlsState | null | undefined, kind: string): string | null {
  if (!state) return 'Controls state unavailable'
  if (state.policy?.state !== 'ACTIVE') return 'Inert: AGENTS.md 19.0.0 is not ACTIVE'
  if (state.store?.state !== 'OK') return `Store ${state.store?.state || 'UNAVAILABLE'}`
  const k = kindFor(state, kind)
  if (!k) return `Unknown change kind ${kind}`
  if (!k.supported) return `Host terminal only: ${k.reason || 'not supported here'}`
  return null
}
export function canAct(state: OpsControlsState | null | undefined, kind: string): boolean {
  return actBlockReason(state, kind) === null
}

/** Mirror of the server: trim, collapse internal whitespace, then exact (case-sensitive) compare. */
export function normalizePhrase(s: string | null | undefined): string {
  return String(s ?? '').trim().replace(/\s+/g, ' ')
}
export function phraseMatches(typed: string | null | undefined, phrase: string | null | undefined): boolean {
  const p = normalizePhrase(phrase)
  return p.length > 0 && normalizePhrase(typed) === p
}

/** Validate a typed setting value against the row's type/min/max/choices. Returns the JSON value to send. */
export function validateSetting(row: Pick<SettingRow, 'type' | 'min' | 'max' | 'choices'>, raw: string):
  { ok: true; value: SettingValue } | { ok: false; error: string } {
  const t = raw.trim()
  const range = (n: number) => {
    if (row.min !== null && row.min !== undefined && n < row.min) return `must be ≥ ${row.min}`
    if (row.max !== null && row.max !== undefined && n > row.max) return `must be ≤ ${row.max}`
    return null
  }
  switch (row.type) {
    case 'bool':
      if (t === 'true') return { ok: true, value: true }
      if (t === 'false') return { ok: true, value: false }
      return { ok: false, error: 'choose true or false' }
    case 'int': {
      if (!/^-?\d+$/.test(t)) return { ok: false, error: 'must be a whole number' }
      const n = Number(t); const e = range(n)
      return e ? { ok: false, error: e } : { ok: true, value: n }
    }
    case 'float': {
      if (!/^-?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(t)) return { ok: false, error: 'must be a number' }
      const n = Number(t); if (!Number.isFinite(n)) return { ok: false, error: 'must be a finite number' }
      const e = range(n)
      return e ? { ok: false, error: e } : { ok: true, value: n }
    }
    case 'enum':
      if (!(row.choices || []).includes(t)) return { ok: false, error: `must be one of ${(row.choices || []).join(', ') || '(no choices)'}` }
      return { ok: true, value: t }
    case 'string':
      if (!t) return { ok: false, error: 'must not be empty' }
      return { ok: true, value: t }
    default:
      return { ok: false, error: `unknown setting type ${String(row.type)}` }
  }
}

// ── base64url <-> ArrayBuffer ─────────────────────────────────────────────────────────────────────────
export function base64urlToBuffer(s: string): ArrayBuffer {
  const b64 = String(s).replace(/-/g, '+').replace(/_/g, '/')
  const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4)
  const bin = atob(padded)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out.buffer
}
export function bufferToBase64url(buf: ArrayBuffer | ArrayBufferView | null | undefined): string {
  if (!buf) return ''
  const bytes = buf instanceof ArrayBuffer ? new Uint8Array(buf) : new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength)
  let bin = ''
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i])
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

type JsonObj = Record<string, any>
/** Servers wrap options differently ({publicKey}, {options}, bare); accept all three. */
export function unwrapOptions(r: JsonObj): JsonObj {
  return (r && (r.publicKey || r.options?.publicKey || r.options)) || r
}
const decodeDescriptors = (list: unknown) => Array.isArray(list)
  ? list.map((c: JsonObj) => ({ ...c, id: base64urlToBuffer(c.id) })) : undefined

export function toPublicKeyRequestOptions(json: JsonObj): PublicKeyCredentialRequestOptions {
  const o = unwrapOptions(json)
  const out: JsonObj = { ...o, challenge: base64urlToBuffer(o.challenge) }
  const allow = decodeDescriptors(o.allowCredentials)
  if (allow) out.allowCredentials = allow
  return out as PublicKeyCredentialRequestOptions
}
export function toPublicKeyCreationOptions(json: JsonObj): PublicKeyCredentialCreationOptions {
  const o = unwrapOptions(json)
  const out: JsonObj = { ...o, challenge: base64urlToBuffer(o.challenge), user: { ...o.user, id: base64urlToBuffer(o.user?.id) } }
  const exclude = decodeDescriptors(o.excludeCredentials)
  if (exclude) out.excludeCredentials = exclude
  return out as PublicKeyCredentialCreationOptions
}

/** PublicKeyCredential → JSON with base64url fields (the shape step-up/verify and register/verify take). */
export function credentialToJSON(cred: any): JsonObj {
  const r = cred?.response || {}
  const response: JsonObj = { clientDataJSON: bufferToBase64url(r.clientDataJSON) }
  if (r.authenticatorData) response.authenticatorData = bufferToBase64url(r.authenticatorData)
  if (r.signature) response.signature = bufferToBase64url(r.signature)
  if (r.userHandle) response.userHandle = bufferToBase64url(r.userHandle)
  if (r.attestationObject) response.attestationObject = bufferToBase64url(r.attestationObject)
  if (typeof r.getTransports === 'function') {
    try { response.transports = r.getTransports() } catch { /* optional */ }
  } else if (Array.isArray(r.transports)) response.transports = r.transports
  let ext: JsonObj = {}
  if (typeof cred?.getClientExtensionResults === 'function') {
    try { ext = cred.getClientExtensionResults() || {} } catch { ext = {} }
  }
  return {
    id: cred?.id, rawId: bufferToBase64url(cred?.rawId), type: cred?.type || 'public-key',
    authenticatorAttachment: cred?.authenticatorAttachment ?? null, response, clientExtensionResults: ext,
  }
}

// ── API client ───────────────────────────────────────────────────────────────────────────────────────
export class OpsApiError extends Error {
  status: number; code: string; detail: string
  constructor(status: number, code: string, detail: string) {
    super(`${code}${detail ? `: ${detail}` : ''}`)
    this.status = status; this.code = code; this.detail = detail
  }
}
export function newIdempotencyKey(): string {
  const c: any = (globalThis as any).crypto
  if (c?.randomUUID) return c.randomUUID()
  return `opsk-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
}

async function call<T>(method: 'GET' | 'POST', path: string, body?: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${OPS_CONTROLS_BASE}${path}`, {
      method, credentials: 'same-origin', cache: 'no-store',
      headers: method === 'POST' ? { 'Content-Type': 'application/json' } : undefined,
      body: method === 'POST' ? JSON.stringify(body ?? {}) : undefined,
    })
  } catch (e) {
    throw new OpsApiError(0, 'NETWORK', e instanceof Error ? e.message : String(e))
  }
  let data: any = null
  try { data = await res.json() } catch { data = null }
  if (!res.ok || (data && data.ok === false)) {
    throw new OpsApiError(res.status, String(data?.error || `HTTP_${res.status}`), String(data?.detail || ''))
  }
  return data as T
}
/** A request may come bare or wrapped as {request}; accept both. */
const req = (r: any): OpsRequest => (r && r.request ? r.request : r)

export const opsApi = {
  statePath: `${OPS_CONTROLS_BASE}/state`,
  createRequest: async (kind: string, params: Record<string, unknown>, oneClick = false) =>
    req(await call('POST', '/requests', { kind, params, idempotency_key: newIdempotencyKey(), ...(oneClick ? { one_click: true } : {}) })),
  getRequest: async (id: string) => req(await call('GET', `/requests/${encodeURIComponent(id)}`)),
  approve: async (id: string, stepUpToken?: string) =>
    req(await call('POST', `/requests/${encodeURIComponent(id)}/approve`, stepUpToken ? { step_up_token: stepUpToken } : {})),
  cancel: async (id: string) => req(await call('POST', `/requests/${encodeURIComponent(id)}/cancel`, {})),
  undo: async (id: string) => req(await call('POST', `/requests/${encodeURIComponent(id)}/undo`, { idempotency_key: newIdempotencyKey() })),
  stepUpOptions: (id: string) => call<JsonObj>('POST', `/requests/${encodeURIComponent(id)}/step-up/options`, {}),
  stepUpVerify: (id: string, credential: JsonObj, phrase: string) =>
    call<{ step_up_token: string; expires_at?: string }>('POST', `/requests/${encodeURIComponent(id)}/step-up/verify`, { credential, phrase }),
  stepUpTotp: (id: string, code: string, phrase: string) =>
    call<{ step_up_token: string; expires_at?: string }>('POST', `/requests/${encodeURIComponent(id)}/step-up/totp`, { code, phrase }),
  registerOptions: (requestId: string) => call<JsonObj>('POST', '/passkeys/register/options', { request_id: requestId }),
  registerVerify: (requestId: string, credential: JsonObj) => call<JsonObj>('POST', '/passkeys/register/verify', { request_id: requestId, credential }),
}

/** Passkey step-up for one request: options → navigator.credentials.get → verify {credential, phrase}. */
export async function passkeyStepUp(requestId: string, phrase: string): Promise<string> {
  const nav: any = (globalThis as any).navigator
  if (!nav?.credentials?.get) throw new OpsApiError(0, 'WEBAUTHN_UNAVAILABLE', 'this browser/context has no WebAuthn (needs HTTPS)')
  const opts = await opsApi.stepUpOptions(requestId)
  const cred = await nav.credentials.get({ publicKey: toPublicKeyRequestOptions(opts) })
  if (!cred) throw new OpsApiError(0, 'WEBAUTHN_CANCELLED', 'no credential returned')
  const r = await opsApi.stepUpVerify(requestId, credentialToJSON(cred), phrase)
  return r.step_up_token
}

/** After the passkey.register request is APPROVED: options → navigator.credentials.create → verify. */
export async function registerPasskey(requestId: string): Promise<JsonObj> {
  const nav: any = (globalThis as any).navigator
  if (!nav?.credentials?.create) throw new OpsApiError(0, 'WEBAUTHN_UNAVAILABLE', 'this browser/context has no WebAuthn (needs HTTPS)')
  const opts = await opsApi.registerOptions(requestId)
  const cred = await nav.credentials.create({ publicKey: toPublicKeyCreationOptions(opts) })
  if (!cred) throw new OpsApiError(0, 'WEBAUTHN_CANCELLED', 'no credential created')
  return opsApi.registerVerify(requestId, credentialToJSON(cred))
}
