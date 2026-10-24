/**
 * scanRunAge.ts — how old is the scanner run on screen, and is that too old for a scalp?
 *
 * Operator, 2026-10-23 08:54: the Opportunities page read "7:00 AM scan" while the
 * operator was looking at it at 08:54, and read as two hours stale. That label was wrong
 * the other way: slot 0700 is RE-RUN through the morning (attempts finished 08:02, 08:21,
 * 08:35 and 08:52 ET), and the page was showing the 08:52 attempt. The slot named the
 * schedule, not the data. Micro-cap scalps cannot tolerate a long gap, so both surfaces
 * (the header SETUPS tile and the Trading → Trade AI run line) now lead with the run's
 * FINISHED time in ET and its AGE.
 *
 * Thresholds, Mon–Fri 06:00–12:00 ET (the scalp window): over 5 min is amber, over 10 min
 * is red. Outside the window the age is shown neutral, because nothing should be
 * refreshing it.
 *
 * Fail closed: a stamp with no timezone (older producers wrote naive datetime.now()) has
 * no computable age. It renders "age unknown" in amber and is never assumed to be UTC or ET.
 *
 * Pure: no React, no fetch, no Date.now(). The caller passes `now`.
 * Runnable test: node --experimental-strip-types src/lib/scanRunAge.test.ts
 */

export type RunAgeTone = 'ok' | 'warn' | 'bad'

export const SCALP_WINDOW_START_MIN = 6 * 60
export const SCALP_WINDOW_END_MIN = 12 * 60
export const AGE_WARN_MIN = 5
export const AGE_BAD_MIN = 10
/** A run that finishes more than this long after its slot label is a re-run of that slot. */
export const RERUN_GRACE_MIN = 30

export interface RunAge {
  /** "08:52 ET", or null when the stamp is missing or unzoned. */
  finishedEt: string | null
  /** Whole minutes since the run finished, or null when not computable. */
  ageMin: number | null
  zoned: boolean
  inScalpWindow: boolean
  tone: RunAgeTone
  /** On the face: "finished 08:52 ET · 4 min ago", "finished 2026-10-23T08:52 unzoned · age unknown", "no finished stamp". */
  label: string
  /** "slot 0700", or "slot 0700 · re-run" when the data is from a later attempt of that slot. */
  slotLabel: string | null
  rerun: boolean
  /** Tooltip sentence that states the thresholds. */
  tip: string
}

const ZONED = /(Z|[+-]\d{2}:?\d{2})$/

function etParts(d: Date): { weekday: string; minutes: number; hhmm: string } {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York', weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(d)
  const get = (t: string) => parts.find(p => p.type === t)?.value ?? ''
  const h = Number(get('hour')) % 24
  const m = Number(get('minute'))
  return { weekday: get('weekday'), minutes: h * 60 + m, hhmm: `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}` }
}

/** Mon–Fri 06:00–12:00 America/New_York. Holidays are not modelled. */
export function inScalpWindow(now: Date): boolean {
  const p = etParts(now)
  if (p.weekday === 'Sat' || p.weekday === 'Sun') return false
  return p.minutes >= SCALP_WINDOW_START_MIN && p.minutes < SCALP_WINDOW_END_MIN
}

export function ageText(min: number): string {
  if (min < 1) return 'just now'
  if (min < 60) return `${min} min ago`
  const h = Math.floor(min / 60)
  const m = min % 60
  return m ? `${h} h ${m} min ago` : `${h} h ago`
}

/**
 * @param finished  the run's completion stamp (latest_run_timestamp / setup_run_summary.run_timestamp)
 * @param slot      the scheduled slot label, e.g. "0700"
 * @param now       the current instant
 */
export function scanRunAge(finished: unknown, slot: unknown, now: Date): RunAge {
  const raw = finished == null || finished === '' ? null : String(finished)
  const slotStr = slot == null || slot === '' ? null : String(slot)
  const window = inScalpWindow(now)
  const tipBase = `Thresholds in the scalp window (Mon–Fri 06:00–12:00 ET): amber over ${AGE_WARN_MIN} min, red over ${AGE_BAD_MIN} min.`
  if (!raw) {
    return { finishedEt: null, ageMin: null, zoned: false, inScalpWindow: window, tone: 'warn', label: 'no finished stamp',
      slotLabel: slotStr ? `slot ${slotStr}` : null, rerun: false, tip: `The run carries no completion stamp, so its age cannot be shown. ${tipBase}` }
  }
  const zoned = ZONED.test(raw)
  const t = new Date(raw)
  if (!zoned || isNaN(t.getTime())) {
    return { finishedEt: null, ageMin: null, zoned: false, inScalpWindow: window, tone: 'warn',
      label: `finished ${raw.slice(0, 16)} unzoned · age unknown`, slotLabel: slotStr ? `slot ${slotStr}` : null, rerun: false,
      tip: `The producer wrote this stamp with no timezone, so its age cannot be computed. It is shown as published. ${tipBase}` }
  }
  const ageMin = Math.max(0, Math.floor((now.getTime() - t.getTime()) / 60_000))
  const fin = etParts(t)
  let tone: RunAgeTone = 'ok'
  if (window) tone = ageMin > AGE_BAD_MIN ? 'bad' : ageMin > AGE_WARN_MIN ? 'warn' : 'ok'
  const m = slotStr?.match(/^(\d{2})(\d{2})$/)
  const slotMin = m ? Number(m[1]) * 60 + Number(m[2]) : null
  const rerun = slotMin != null && fin.minutes - slotMin > RERUN_GRACE_MIN
  return {
    finishedEt: `${fin.hhmm} ET`,
    ageMin,
    zoned: true,
    inScalpWindow: window,
    tone,
    label: `finished ${fin.hhmm} ET · ${ageText(ageMin)}`,
    slotLabel: slotStr ? `slot ${slotStr}${rerun ? ' · re-run' : ''}` : null,
    rerun,
    tip: `Run finished ${fin.hhmm} ET, ${ageText(ageMin)}.`
      + (rerun ? ` Slot ${slotStr} is a schedule label: this data is from a later re-run of that slot, not from ${(slotStr ?? "").slice(0, 2)}:${(slotStr ?? "").slice(2)}.` : '')
      + ` ${tipBase}${window ? '' : ' Outside the window the age is shown neutral.'}`,
  }
}

/** Latest-run decision tally (setup_run_summary) as one phrase. */
export function latestRunPhrase(s: any): string | null {
  if (!s || typeof s !== 'object') return null
  const n = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null)
  const scanned = n(s.scanned_count)
  if (scanned == null) return null
  const parts = [`${n(s.go_count) ?? 0} GO`, `${n(s.wait_count) ?? 0} WAIT`, `${n(s.nogo_count) ?? 0} NOGO`]
  const review = n(s.review_count)
  if (review) parts.push(`${review} review`)
  return `latest run: ${scanned} scanned · ${parts.join(' / ')}`
}

export const LATEST_RUN_TIP = 'Latest run only. The Trading → Trade AI tiles count today\'s whole scanner universe (every row from every run today), so they are larger by design.'

/**
 * The freshest clock the payload serves, and the age read from it.
 *
 * Follow-up 2026-10-23 (cadence PR 1992): the rows the page shows come from the
 * continuous runner's scan cycles (trade_ai_scans), not from the hourly run summary.
 * The 08:18 / 08:32 / 08:50 "0700" attempts were health-agent re-runs, and the run summary is
 * not rewritten by each cycle. So when the API serves `scan_freshness` /
 * `latest_scan_at` (the newest scanned_at among the served rows), that is the age the
 * operator needs. `latest_run_timestamp` is the fallback only when that field is absent.
 * The server's STALE status (over 10 min inside 06:00–12:00 ET) wins: it forces red.
 */
export function payloadRunAge(payload: any, slot: unknown, now: Date): RunAge & { source: 'scan' | 'run' } {
  const sf = payload?.scan_freshness && typeof payload.scan_freshness === 'object' ? payload.scan_freshness : null
  const scanAt = sf?.latest_scan_at ?? payload?.latest_scan_at ?? null
  if (scanAt) {
    const a = scanRunAge(scanAt, slot, now)
    const serverStale = sf?.status === 'STALE'
    const tone: RunAgeTone = serverStale ? 'bad' : a.tone
    return {
      ...a,
      tone,
      label: a.label.replace(/^finished /, 'latest scan '),
      tip: a.tip.replace(/^Run finished /, 'Newest scanned row ')
        + (sf?.status ? ` Server freshness: ${sf.status}${sf.age_sec != null ? ` (${Math.round(Number(sf.age_sec) / 60)} min)` : ''}.` : ''),
      source: 'scan',
    }
  }
  const run = payload?.latest_run_timestamp ?? payload?.setup_run_summary?.run_timestamp
  return { ...scanRunAge(run, slot, now), source: 'run' }
}
