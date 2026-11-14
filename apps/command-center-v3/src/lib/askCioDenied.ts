/**
 * Ask the CIO / My questions — what a REFUSED read means (campaign Home item 6).
 *
 * `useApi` already treats 401/403 as terminal: the polling interval stops and no backoff ladder runs. What it did not
 * do is tell the surface WHICH refusal it was — it handed back one generic sentence — and My questions had no way to
 * recover once the session became authorised, because a terminal outcome stands until an explicit refetch.
 *
 * This module turns the hook's answer into one typed refusal: the server's own code (never invented — `parseErrorBody`
 * only yields a code when the body carried one), the server's own detail sentence when it sent one, and the two
 * recovery facts the page needs. `useApi`'s 401/403 are the only states that are denials; everything else, including
 * an error that happens to carry a code, stays an ordinary error.
 *
 * Pure. No React, no network, no formatting of clock values (the component renders instants and ages).
 */

export interface AskDenialInput {
  /** `useApi`'s authorization answer for the read. */
  authState?: 'OK' | 'UNAUTHORIZED' | 'FORBIDDEN' | null
  /** The server's typed code, from `useApi`'s `errorCode` (already shape-validated, re-checked here). */
  errorCode?: string | null
  /** The server's own detail sentence, from `useApi`'s `errorDetail`. */
  errorDetail?: string | null
  /** `useApi`'s transport message — the fallback when the body carried no detail. */
  error?: string | null
}

export interface AskDenialView {
  denied: boolean
  /** The HTTP status the denial came from (401/403), or null when the read was not denied. */
  httpStatus: 401 | 403 | null
  /** The server's typed code, only when the response actually carried one. */
  code: string | null
  title: string
  detail: string
  /** What the page does about it. Recovery is an operator action, never a poll. */
  recovery: string
  retryLabel: string
}

/** Sentences for codes this surface knows. An unknown code is still shown — by its code, not by silence. */
export const ASK_REFUSAL_TEXT: Record<string, string> = {
  AGENT_CALLER_REFUSED: 'Ask the CIO answers only the operator’s tailnet identity — agents, n8n and the service token are refused.',
  CSRF_REFUSED: 'The request was not accepted as same-origin.',
  AUTH_CONFIG_UNAVAILABLE: 'The auth configuration could not be read, so no caller can be admitted.',
}

const CODE = /^[A-Z][A-Z0-9_]{2,63}$/

function clean(value: string | null | undefined): string {
  return typeof value === 'string' ? value.trim() : ''
}

function codeOrNull(value: string | null | undefined): string | null {
  const code = clean(value)
  return CODE.test(code) ? code : null
}

const NOT_DENIED: AskDenialView = { denied: false, httpStatus: null, code: null, title: '', detail: '', recovery: '', retryLabel: '' }

export function askDenialView(input: AskDenialInput | null | undefined): AskDenialView {
  const auth = input?.authState ?? null
  if (auth !== 'FORBIDDEN' && auth !== 'UNAUTHORIZED') return { ...NOT_DENIED }

  const code = codeOrNull(input?.errorCode)
  const detail = clean(input?.errorDetail) || (code ? ASK_REFUSAL_TEXT[code] : '') || clean(input?.error)
  const httpStatus = auth === 'FORBIDDEN' ? 403 : 401

  if (auth === 'FORBIDDEN') {
    return {
      denied: true,
      httpStatus,
      code,
      title: 'Refused — this surface answers only the operator',
      detail: detail || 'the server refused this read',
      recovery: 'Polling stopped. It asks once more when you return to this tab.',
      retryLabel: 'Try again',
    }
  }
  return {
    denied: true,
    httpStatus,
    code,
    title: 'Sign-in required',
    detail: detail || 'the server did not accept this session',
    recovery: 'Polling stopped. Sign in, then press Try again or return to this tab.',
    retryLabel: 'Try again',
  }
}

/** The line the panel prints for the refusal identity: the server's code when it sent one, else the HTTP status. */
export function refusalLabel(view: AskDenialView): string {
  return view.code ?? (view.httpStatus ? `HTTP ${view.httpStatus}` : 'not measured')
}
