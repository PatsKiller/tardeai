/**
 * Operator-facing words for Ops → Controls availability (operator page audit 2026-11-04, FQ-068).
 *
 * The page used to lead with the server's own error — e.g. "forbidden — this operator is not
 * permitted this surface; this will not resolve by waiting" — beside a long diagnostics stack. The
 * operator needs the meaning and the authorized way back; the raw error stays in a technical-detail
 * toggle (nothing is removed — audit brief Rule 2).
 */
export type ControlsUnavailable = { text: string; next: string; raw: string | null }

export function controlsUnavailableExplanation(error: unknown): ControlsUnavailable {
  const raw = typeof error === 'string' && error.trim() ? error.trim() : null
  if (raw && /forbidden|not permitted|not authorised|not authorized/i.test(raw)) {
    return {
      text: 'Controls are limited to the operator; this session is not signed in with that role.',
      next: 'Open this page from the operator’s own Command Center session (the tailnet address), or ask the administrator to grant operator access. Waiting will not change it.',
      raw,
    }
  }
  return {
    text: 'The controls state could not be read, so the page will not show or accept a change.',
    next: 'If it repeats, report it with the technical detail below; nothing here is reported as healthy.',
    raw,
  }
}
