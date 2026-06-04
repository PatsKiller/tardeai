// adminWrite.ts — client for the guarded admin write surface (Tier-2/3).
// Two-step by contract: preview() returns the exact old->new diff (no mutation); confirm() applies.
// Operator identity + access token are stored locally (air-gapped LAN; the network is the perimeter).

export interface AdminPreview {
  ok: boolean
  needs_confirm?: boolean
  preview?: { action: string; target: string; old_value: any; new_value: any }
  error?: string
}
export interface AdminResult {
  ok: boolean
  result?: 'applied' | 'failed' | 'rejected'
  audit_id?: number
  old_value?: any
  new_value?: any
  error?: string
  detail?: string
}

export function getOperator(): string {
  return localStorage.getItem('admin_operator') || 'operator'
}
export function setOperator(v: string) { localStorage.setItem('admin_operator', v) }
export function getToken(): string { return localStorage.getItem('admin_write_token') || '' }
export function setToken(v: string) { localStorage.setItem('admin_write_token', v) }

async function post(path: string, body: any): Promise<any> {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...body, operator: getOperator(), token: getToken() }),
  })
  // POST handlers return the raw guard dict (not the GET {ok,data} wrapper)
  return r.json()
}

/** STEP 1 of the two-step: ask the server for the exact change. Never mutates. */
export function preview(path: string, body: any): Promise<AdminPreview> {
  return post(path, { ...body, confirm: false })
}

/** STEP 2: apply the change (only call after the operator confirms the previewed diff). */
export function confirm(path: string, body: any): Promise<AdminResult> {
  return post(path, { ...body, confirm: true })
}
