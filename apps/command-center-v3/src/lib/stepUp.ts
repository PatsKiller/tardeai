/**
 * TOTP step-up client helpers (cc_auth, 2026-10-16). Pure logic, no React.
 *
 * A step-up route answers 403 {auth: 'step_up', step_up_action, step_up: {available, endpoint}} when TOTP
 * step-up is active and this browser's tailnet login holds no unlock for that action class. When TOTP is
 * disabled the body has NO `step_up` key and the page must show the refusal as before (no code prompt).
 */

export const STEP_UP_ENDPOINT = '/api/v2/auth/step-up'

export type StepUpChallenge = { action: string; endpoint: string }

export type StepUpResult = {
  ok: boolean
  error?: string
  unlocked_until?: number
  locked_until?: number
  attempts_left?: number
}

/** The challenge to prompt for, or null when this response is not an answerable step-up refusal. */
export function stepUpChallenge(status: number, body: unknown): StepUpChallenge | null {
  if (status !== 403 || !body || typeof body !== 'object') return null
  const b = body as Record<string, any>
  if (b.auth !== 'step_up' || !b.step_up || b.step_up.available !== true) return null
  const action = typeof b.step_up_action === 'string' ? b.step_up_action : ''
  if (!action) return null
  // The code only ever goes to the fixed same-origin endpoint, whatever the body names.
  return { action, endpoint: STEP_UP_ENDPOINT }
}

/** Keep digits only, at most 6. */
export function sanitizeCode(raw: string): string {
  return String(raw || '').replace(/\D/g, '').slice(0, 6)
}

export function codeComplete(code: string): boolean {
  return /^\d{6}$/.test(code)
}

/** POST the code. Never retried automatically: a wrong code counts toward the server lockout. */
export async function submitStepUp(
  challenge: StepUpChallenge,
  code: string,
  fetchImpl: typeof fetch = fetch,
): Promise<StepUpResult> {
  if (!codeComplete(code)) return { ok: false, error: 'Enter the 6-digit code from your authenticator' }
  try {
    const r = await fetchImpl(challenge.endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
      body: JSON.stringify({ action: challenge.action, code }),
    })
    let j: any = null
    try { j = await r.json() } catch { j = null }
    if (r.ok && j?.ok === true) return { ok: true, unlocked_until: j.unlocked_until }
    return {
      ok: false,
      error: j?.error || `HTTP ${r.status}`,
      locked_until: j?.locked_until,
      attempts_left: j?.attempts_left,
    }
  } catch (e: any) {
    return { ok: false, error: e?.message || 'step-up request failed' }
  }
}
