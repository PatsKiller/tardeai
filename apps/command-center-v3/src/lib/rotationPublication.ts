type Row = Record<string, unknown>
export type RotationAvailability = {
  ready: boolean
  status: 'READY' | 'STALE' | 'UNAVAILABLE'
  reasons: string[]
  sourceAsOf: string | null
  generatedAt: string | null
  validatedAt: string | null
  expiresAtMs: number | null
}

function record(value: unknown): Row | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Row : null
}
function timestamp(value: unknown): string | null {
  return typeof value === 'string' && /(?:Z|[+-]\d\d:\d\d)$/.test(value)
    && Number.isFinite(Date.parse(value)) ? value : null
}

// Display validation of the host's versioned verdict; no financial decisions.
export function rotationAvailability(summary: unknown, error?: unknown, now = Date.now()): RotationAvailability {
  const data = record(summary)
  const proof = record(data?.publication)
  const sourceAsOf = timestamp(proof?.source_as_of)
  const generatedAt = timestamp(proof?.cache_generated_at)
  const checked = timestamp(proof?.checked_at)
  const base = { sourceAsOf, generatedAt, validatedAt: checked,
    expiresAtMs: checked && generatedAt ? Math.min(Date.parse(checked), Date.parse(generatedAt)) + 900_000 : null }
  const unavailable = (reason: string): RotationAvailability => ({ ...base, ready: false, status: 'UNAVAILABLE', reasons: [reason] })
  if (error) return unavailable('request_failed')
  if (proof?.schema !== 'RotationPublication@v1') return unavailable('missing_publication_evidence')
  const reasons = Array.isArray(proof.reasons) && proof.reasons.every(x => typeof x === 'string') ? proof.reasons as string[] : null
  if (!reasons || typeof proof.status !== 'string' || !['READY', 'STALE', 'UNAVAILABLE'].includes(proof.status)) return unavailable('malformed_publication')
  if (proof.status !== 'READY') return { ...base, ready: false, status: proof.status as 'STALE' | 'UNAVAILABLE', reasons }
  const accounts = proof.accounts
  const coverage = record(proof.coverage)
  const positiveInteger = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value > 0
  if (data?.ok !== true || proof.producer_ok !== true || reasons.length || !checked || !sourceAsOf || !generatedAt
    || typeof proof.input_sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(proof.input_sha256)
    || proof.source_as_of_basis !== 'oldest_required_position_or_account_timestamp'
    || !coverage || !positiveInteger(coverage.required_positions) || coverage.dated_positions !== coverage.required_positions
    || !positiveInteger(coverage.accounts) || coverage.dated_accounts !== coverage.accounts
    || !Array.isArray(accounts) || !accounts.length || accounts.some(value => {
      const row = record(value)
      return !row || typeof row.account_key !== 'string' || !row.account_key.trim()
        || row.state !== 'LIVE' || !timestamp(row.source_as_of) || Date.parse(String(row.source_as_of)) > now
    }) || accounts.length !== coverage.accounts) return unavailable('incomplete_publication')
  const age = now - Date.parse(checked)
  const engineAge = now - Date.parse(generatedAt)
  if (!Number.isFinite(now) || age < 0 || engineAge < 0 || Date.parse(sourceAsOf) > now) return unavailable('invalid_publication_clock')
  if (data.stale === true || age > 900_000 || engineAge > 900_000) return { ...base, ready: false, status: 'STALE', reasons: ['publication_expired'] }
  return { ...base, ready: true, status: 'READY', reasons: [] }
}

const REASONS: Record<string, string> = {
  request_failed: 'The latest request failed.', account_stale: 'Account data is stale.',
  account_evidence_stale: 'Account data is stale.', publication_expired: 'The last validation is stale.',
  position_evidence_stale: 'Position evidence is stale.', unsupported_stop_claim: 'The claimed stop evidence is not supported.',
  conflicting_account_state: 'Account status records disagree.',
  missing_publication_evidence: 'Current source verification is unavailable.',
}
export function rotationAvailabilityMessage(value: RotationAvailability): string {
  return [...new Set(value.reasons.map(x => REASONS[x] ?? 'Source verification is incomplete.'))].join(' ')
}

// Short chip labels for the one-line withheld notice (P3, operator-approved 2026-10-23). The sentence
// form above stays in the tooltip; an unknown code is shown as its own words rather than hidden.
const REASON_CHIPS: Record<string, string> = {
  request_failed: 'request failed', account_stale: 'account data stale', account_evidence_stale: 'account data stale',
  position_evidence_stale: 'position evidence stale', publication_expired: 'validation stale',
  unsupported_stop_claim: 'stop claim unsupported', conflicting_account_state: 'account records disagree',
  missing_publication_evidence: 'verification unavailable', missing_input: 'input missing',
  malformed_publication: 'malformed publication', incomplete_publication: 'publication incomplete',
  invalid_publication_clock: 'publication clock invalid',
}
export function rotationReasonChips(value: RotationAvailability): string[] {
  return [...new Set(value.reasons.map(x => REASON_CHIPS[x] ?? x.replace(/_/g, ' ')))]
}

/**
 * What each withheld reason means in operator terms, which evidence has to update, and the one next
 * step that clears it (operator audit 2026-11-04, FQ-062). The chip row alone told the operator that
 * three things were wrong but not what to do; `Refresh Summary` was the only affordance on the page.
 * A reason this table does not know still gets a next step and keeps its raw code in `raw` (shown
 * inside a details toggle by the notice), never as the operator's only explanation.
 */
export type RotationBlocker = { code: string; label: string; what: string; next: string; raw: string }

const REASON_DETAIL: Record<string, { what: string; next: string }> = {
  account_stale: {
    what: 'The account balances this review reads are older than its 15-minute window.',
    next: 'It clears when the next account sync writes a newer balance timestamp; then press Refresh Summary.',
  },
  account_evidence_stale: {
    what: 'The account balances this review reads are older than its 15-minute window.',
    next: 'It clears when the next account sync writes newer balance evidence; then press Refresh Summary.',
  },
  account_unavailable: {
    what: 'The account data this review reads is unavailable, so it cannot tell which holdings are eligible to rotate.',
    next: 'It clears when the account sync returns a balance; then press Refresh Summary. If the source stays down, Risk → Exposure names the failed source.',
  },
  account_evidence_unavailable: {
    what: 'The account data this review reads is unavailable, so it cannot tell which holdings are eligible to rotate.',
    next: 'It clears when the account sync returns balance evidence; then press Refresh Summary. If the source stays down, Risk → Exposure names the failed source.',
  },
  position_unavailable: {
    what: 'The position data this review reads is unavailable, so it cannot judge what a rotation would change.',
    next: 'It clears when the position sync returns; then press Refresh Summary. If the source stays down, Risk → Exposure names the failed source.',
  },
  position_evidence_unavailable: {
    what: 'The position evidence this review reads is unavailable, so it cannot judge what a rotation would change.',
    next: 'It clears when the position sync returns evidence; then press Refresh Summary. If the source stays down, Risk → Exposure names the failed source.',
  },
  position_evidence_stale: {
    what: 'The position quantities this review reads are older than its 15-minute window.',
    next: 'It clears when the next position sync writes newer evidence; then press Refresh Summary.',
  },
  unsupported_stop_claim: {
    what: 'The stop price this review read could not be matched to a recorded stop, so it cannot judge what a rotation would leave unprotected.',
    next: 'It clears when the stop record is refreshed so it covers the position. If it does not, review that position in Risk → Recovery.',
  },
  publication_expired: {
    what: 'The last validation of these sources is older than 15 minutes.',
    next: 'Press Refresh Summary to validate the current sources again.',
  },
  conflicting_account_state: {
    what: 'Two account records disagree about an account this review uses.',
    next: 'It stays withheld until the account sources agree; re-run the account sync, then press Refresh Summary.',
  },
  request_failed: {
    what: 'The latest request for the rotation review failed, so there is no current answer.',
    next: 'Press Refresh Summary. If it fails again, the failure is recorded under Jobs → failures.',
  },
  missing_publication_evidence: {
    what: 'The server did not supply the evidence that says which sources this review used and when they were read.',
    next: 'Press Refresh Summary. If it persists, the review producer is not publishing its evidence; report it with this code.',
  },
  missing_input: {
    what: 'A required source for the review is missing.',
    next: 'Wait for the missing source to update, then press Refresh Summary.',
  },
  malformed_publication: {
    what: 'The review’s evidence record could not be read, so the page cannot vouch for the advice.',
    next: 'Press Refresh Summary. If it persists, report it with this code.',
  },
  incomplete_publication: {
    what: 'The review’s evidence record is missing part of its source coverage, so the page cannot vouch for the advice.',
    next: 'Press Refresh Summary once all accounts and positions have a source timestamp.',
  },
  invalid_publication_clock: {
    what: 'A source timestamp for this review is in the future or otherwise impossible, so freshness cannot be trusted.',
    next: 'Wait for the next sync to write a valid timestamp, then press Refresh Summary.',
  },
}

export function rotationBlockerExplanations(value: RotationAvailability): RotationBlocker[] {
  const seen = new Set<string>()
  return value.reasons.filter(code => {
    if (seen.has(code)) return false
    seen.add(code)
    return true
  }).map(code => {
    const known = REASON_DETAIL[code]
    return {
      code,
      label: REASON_CHIPS[code] ?? code.replace(/_/g, ' '),
      what: known?.what ?? 'This condition is not one the page can explain yet.',
      next: known?.next ?? 'Press Refresh Summary after the sources update. If it persists, report it with the code shown under technical detail.',
      raw: code,
    }
  })
}
