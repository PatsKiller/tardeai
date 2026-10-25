// Ops → Controls · Toggles tab (feat/ops-controls-toggles-20261025).
// Operator 2026-10-25 (verbatim): "this should have just been a toggle to turn on/off on the control ops."
// This module turns GET /state (the env-backed settings rows, the n8n live list and the toggles section) into the
// rows the Toggles tab draws: what each switch is right now, where that value comes from (operator setting, the
// server's environment, or the default), who changed it last and when, and whether a test text could reach the
// operator today. Pure: no React, no DOM, no fetch. The server decides every value; nothing here re-derives one.
// Every change still goes through the server's flow (preview → passkey + typed phrase → host applier).
import type { N8nRow, OpsControlsState, OpsRequest, SettingRow, TestSendResult } from './opsControls'

export const SMS_ENABLED_KEY = 'comms.sms.enabled'
export const SMS_EMAIL_KEY = 'comms.sms.operator_email'
export const GATEWAY_MODE_KEY = 'comms.gateway_mode'
export const DELIVERING_MODES = ['CANARY', 'ACTIVE'] as const

export function settingRow(state: OpsControlsState | null | undefined, key: string): SettingRow | null {
  return (state?.settings?.rows || []).find(r => r.key === key) || null
}

/** Mirror of the server's sms_gateway_email validator (the server is the authority; this only gates the button). */
export function validateSmsEmail(raw: string, allowed: readonly string[] | null | undefined):
  { ok: true; value: string } | { ok: false; error: string } {
  const v = String(raw || '').trim().toLowerCase()
  const m = /^(\d{10})@([a-z0-9-]+(\.[a-z0-9-]+)+)$/.exec(v)
  if (!m) return { ok: false, error: 'Use 10 digits, then @ and your carrier’s text gateway, e.g. 5551234567@msg.fi.google.com' }
  const list = (allowed || []).map(d => d.toLowerCase())
  if (!list.includes(m[2])) return { ok: false, error: `${m[2]} is not a known carrier gateway (${list.slice(0, 4).join(', ')}…)` }
  return { ok: true, value: v }
}

export function maskPhone(v: string | null | undefined): string {
  const s = String(v ?? '')
  if (!s.includes('@')) return s
  const [local, dom] = s.split('@', 2)
  if (local.includes('•')) return s
  return '•'.repeat(Math.max(0, local.length - 4)) + local.slice(-4) + '@' + dom
}

export type Source = 'operator_setting' | 'environment' | 'default' | 'unknown'
export const SOURCE_TEXT: Record<Source, string> = {
  operator_setting: 'Set here',
  environment: 'From the server .env',
  default: 'Default',
  unknown: 'Unknown (older server)',
}

/** The value a consumer sees right now and where it comes from. Missing effective block = unknown, never a guess. */
export function effectiveOf(row: SettingRow | null): { value: unknown; source: Source } {
  if (!row) return { value: null, source: 'unknown' }
  if (row.effective) return { value: row.effective.value, source: row.effective.source }
  if (row.overridden) return { value: row.current, source: 'operator_setting' }
  return { value: null, source: 'unknown' }
}

export function isOn(v: unknown): boolean | null {
  if (v === true || v === 'true') return true
  if (v === false || v === 'false' || v === '' ) return false
  return null
}

export function changedText(row: SettingRow | null, fmt: (iso: string) => string): string {
  if (!row?.updated_at) return row?.overridden === false ? 'Never changed here' : '—'
  return `${fmt(row.updated_at)} · ${(row.updated_by || '—').replace(/^tailnet:/, '')}`
}

/** Whether a real failure text could reach the operator now, and the plain reasons it could not. */
export function smsReadiness(state: OpsControlsState | null | undefined): { ready: boolean; reasons: string[] } {
  const reasons: string[] = []
  const on = isOn(effectiveOf(settingRow(state, SMS_ENABLED_KEY)).value)
  const addr = effectiveOf(settingRow(state, SMS_EMAIL_KEY)).value
  const mode = String(effectiveOf(settingRow(state, GATEWAY_MODE_KEY)).value ?? '')
  if (on !== true) reasons.push('Text alerts are off')
  if (!addr) reasons.push('No text address is set')
  if (!(DELIVERING_MODES as readonly string[]).includes(mode)) reasons.push(`Gateway mode is ${mode || 'unknown'}: texts and emails are recorded, not sent`)
  if (state?.toggles?.channels && state.toggles.channels.sms === false) reasons.push('This release has no SMS channel yet (PR 2105)')
  return { ready: reasons.length === 0, reasons }
}

export type LaneToggle = { lane_id: string; live: boolean | null; stage: string | null; registry_state: string | null; last: { at: string; by: string } | null }

/** The last APPLIED live-list change for one lane, from the recent requests the state carries. */
export function laneLastChange(requests: OpsRequest[] | null | undefined, lane: string): { at: string; by: string } | null {
  const hits = (requests || []).filter(r => r.status === 'APPLIED' && (r.kind === 'n8n_live_list.add' || r.kind === 'n8n_live_list.remove')
    && String(r.params?.lane_id ?? '') === lane && (r.applied_at || r.status_at))
  hits.sort((a, b) => String(b.applied_at || b.status_at).localeCompare(String(a.applied_at || a.status_at)))
  const h = hits[0]
  return h ? { at: String(h.applied_at || h.status_at), by: String(h.actor || '—').replace(/^tailnet:/, '') } : null
}

/** One switch per n8n lane: live (on the relay live list) or dry. Live first, then by lane id. */
export function laneToggles(state: OpsControlsState | null | undefined, query = ''): LaneToggle[] {
  const q = query.trim().toLowerCase()
  const rows: N8nRow[] = state?.n8n?.rows || []
  return rows
    .filter(r => !q || r.lane_id.toLowerCase().includes(q))
    .map(r => ({
      lane_id: r.lane_id, live: typeof r.on_live_list === 'boolean' ? r.on_live_list : null,
      stage: (r.stage as string) || null, registry_state: ((r as { registry_state?: string }).registry_state) || null,
      last: laneLastChange(state?.requests, r.lane_id),
    }))
    .sort((a, b) => (a.live === b.live ? a.lane_id.localeCompare(b.lane_id) : a.live ? -1 : 1))
}

export function testSendText(r: TestSendResult | null | undefined): string {
  if (!r) return ''
  if (r.delivered) return `Sent (${r.channel}) at ${r.at}. Check your phone.`
  return `Not sent: ${r.error || 'the gateway did not deliver'}${r.gateway_mode ? ` (gateway mode ${r.gateway_mode})` : ''}.`
}
