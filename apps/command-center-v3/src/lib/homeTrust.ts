// Home trust helpers (2026-07-26) — honest stale / empty / retired presentation.
// Keeps HomeHub readable; pure functions only.

/** US equity cash session approx (ET). Sunday always closed. */
export function isUsEquitySessionOpen(now = new Date()): boolean {
  // Convert to America/New_York wall clock via toLocaleString parts
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    weekday: 'short',
    hour: 'numeric',
    minute: 'numeric',
    hour12: false,
  }).formatToParts(now)
  const wd = parts.find(p => p.type === 'weekday')?.value
  if (wd === 'Sat' || wd === 'Sun') return false
  const hour = Number(parts.find(p => p.type === 'hour')?.value ?? 0)
  const minute = Number(parts.find(p => p.type === 'minute')?.value ?? 0)
  const mins = hour * 60 + minute
  // 09:30–16:00 ET
  return mins >= 9 * 60 + 30 && mins < 16 * 60
}

/** Days between ISO date (YYYY-MM-DD) and today (ET calendar). */
export function calendarDaysBehind(runDate?: string | null, now = new Date()): number | null {
  if (!runDate) return null
  const m = String(runDate).match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (!m) return null
  const et = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now)
  const [y, mo, d] = et.split('-').map(Number)
  const a = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  const b = Date.UTC(y, mo - 1, d)
  return Math.max(0, Math.round((b - a) / 86_400_000))
}

export type SetupStaleKind = 'fresh' | 'prior_session' | 'weekend' | 'stale' | 'none'

export function classifySetupStale(runDate?: string | null, now = new Date()): {
  kind: SetupStaleKind
  days: number | null
  label: string
} {
  if (!runDate) return { kind: 'none', days: null, label: 'no run yet' }
  const days = calendarDaysBehind(runDate, now)
  if (days == null) return { kind: 'none', days: null, label: 'no run yet' }
  if (days === 0) return { kind: 'fresh', days, label: 'today' }
  const wd = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', weekday: 'short' }).format(now)
  if ((wd === 'Sat' || wd === 'Sun') && days <= 3) {
    return { kind: 'weekend', days, label: `market closed · last RTH scan ${days}d ago` }
  }
  if (days === 1) return { kind: 'prior_session', days, label: 'prior session' }
  return { kind: 'stale', days, label: `stale · ${days}d since last scan` }
}

/** Hermes gateway was intentionally stopped after sidecar→global migration. */
export function hermesGatewayDisplay(gatewayStatus?: string | null, autonomousOn?: boolean, staged?: number): {
  label: string
  color: string
  tip: string
  expectedRetired: boolean
} {
  const g = String(gatewayStatus ?? '').toLowerCase()
  const ok = g === 'ok' || g === 'active' || g === 'running'
  if (ok) {
    return { label: 'online', color: '#22c55e', tip: 'hermes-gateway.service active', expectedRetired: false }
  }
  // inactive / offline / offline / empty → expected retired when research still flows
  const researchAlive = Boolean(autonomousOn) || (Number(staged) || 0) > 0
  if (researchAlive) {
    return {
      label: 'retired (expected)',
      color: 'var(--text3)',
      tip: 'hermes-gateway.service was stopped/disabled after global Hermes install migration — not an outage. Research runs via autonomous loop + staged pipeline.',
      expectedRetired: true,
    }
  }
  return {
    label: 'offline',
    color: '#ef4444',
    tip: 'Gateway offline and no autonomous/staged research signal — check Hermes hub / System health.',
    expectedRetired: false,
  }
}

/** Client-side mirror of scripts/llm_content_quality.py for briefing render. */
export function isUsableBriefingText(raw: unknown): boolean {
  let text = ''
  let x: any = raw
  if (typeof x === 'string') {
    try { x = JSON.parse(x) } catch { /* keep string */ }
  }
  text = String(x?.content ?? x?.summary ?? x?.text ?? x ?? '').trim()
  if (text.length < 80) return false
  if (/(\*\*##\.?\s*){3,}/.test(text)) return false
  if (/(##\s*){4,}/.test(text)) return false
  if (/LLM error|Ollama (unavailable|timeout)|All LLM attempts failed/i.test(text)) return false
  const letters = [...text].filter(c => /[A-Za-z]/.test(c)).length
  const printable = [...text].filter(c => !/\s/.test(c)).length
  if (printable && letters / printable < 0.45) return false
  return true
}

export function briefingProse(raw: unknown): string {
  let x: any = raw
  if (typeof x === 'string') {
    try { x = JSON.parse(x) } catch { return x }
  }
  return String(x?.content ?? x?.summary ?? x?.text ?? x ?? '')
}
