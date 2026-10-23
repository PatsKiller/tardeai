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
