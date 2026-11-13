/** Combined Home (operator order 2026-11-13): reconciliation the appended operational section applies to the v010 model.
 *
 *  The v010 model (lib/homeV010.ts buildModel) is unchanged; the combined page passes it through `reconcileModel`
 *  before drawing. Each correction names the accuracy finding it answers (A01–A09 in the 2026-11-13 reference):
 *
 *    A04  Schedulers: the System Status row used a hard-coded UNKNOWN ("no per-lane run source") while the Trading
 *         gates card drew the `schedulers` gate from the same /api/v2/home/status read (lane_health_current). Both now
 *         draw the one projection: same state, source, clock and reason. No gate in the read -> the UNKNOWN row stays.
 *    A03  Stop read vs coverage: the raw stop read (since-close, broker stop clock) and the derived coverage product
 *         (`orders` gate, "Stop coverage (protection)") are separate rows with separate clocks. A fresh raw read never
 *         makes a stale coverage product look current, and a stale coverage product is not a confirmed gap.
 *    A02  P0 population: the header pill counts P0 items from /api/v2/home/incidents; the `p0` gate is the verdict
 *         lane's own read. When the two disagree the gate cannot vouch for "no P0": it is drawn UNKNOWN with both
 *         counts and both sources named, never OK.
 *    Verdict (operator rule): a confirmed blocker stays NO. A NO whose only causes are required inputs that are
 *         stale / unread (no count blocker, no GAP, no WARN row) is shown as UNKNOWN with the specific reason. UNKNOWN
 *         is never upgraded and nothing here can produce YES.
 *    A01  Incident identity: a category the server's class map gave an item is shown only when the item's own typed
 *         fields agree with it (see `incidentCategory`); otherwise the item's alert_type is shown, so a PR merge digest
 *         is never drawn as "Unprotected Position" and a RAW-store health check never as "Orphaned Stop".
 *         The detection time of an incident older than six days carries its date (etTime alone prints a weekday, so a
 *         54-day-old row read "Sun 11:32 AM"), and a row the server flags stale_condition says so.
 *  Pure functions; the page owns fetching. */

import { sinceCloseModel } from './sinceClose.ts'
import { etTime, type GateRow, type HomeStatusWire, type HomeV010Inputs, type HomeV010Model, type IncidentItem, type RowState, type StatusRow } from './homeV010.ts'

export const COMBINED_SECTION_ID = 'home-operational'
export const COMBINED_SECTION_TITLE = 'System, protection & operational readiness'

const UNREADABLE: ReadonlySet<string> = new Set(['STALE', 'UNKNOWN', 'TIMED OUT', 'TIMED_OUT'])
const CONFIRMING: ReadonlySet<string> = new Set(['GAP', 'WARN'])

// ── A01: typed incident identity ───────────────────────────────────────────────────────────────────────────────
/** What the item's own fields must show before a protection category may be drawn. A protection class needs a
 *  position identity (symbol) and an alert_type from the protection family; anything else keeps its own alert_type. */
const PROTECTION_CATEGORIES: Record<string, RegExp> = {
  'Unprotected Position': /unprotect|stop[_ -]?coverage|no[_ -]?stop|missing[_ -]?stop/i,
  'Orphaned Stop': /orphan/i,
}

export interface CategoryView { label: string; mismatch: string | null }

/** The label an incident is drawn under, and why the server's category was not used (null when it was). */
export function incidentCategory(i: Pick<IncidentItem, 'category' | 'alert_type' | 'symbol' | 'cause'>): CategoryView {
  const cat = (i.category || '').trim()
  const type = (i.alert_type || '').trim()
  const rule = PROTECTION_CATEGORIES[cat]
  if (!cat) return { label: type || 'Unclassified incident', mismatch: null }
  if (!rule) return { label: cat, mismatch: null }
  const typed = rule.test(type) || rule.test(i.cause || '')
  if (typed && i.symbol) return { label: cat, mismatch: null }
  const fallback = type ? `Unclassified · ${type}` : 'Unclassified incident'
  return { label: fallback, mismatch: `server category "${cat}" not supported by the item (alert_type ${type || 'missing'}${i.symbol ? '' : ', no symbol'})` }
}

/** "Detected" text with the calendar date whenever the weekday alone would be ambiguous (older than six days). */
export function detectedText(iso: string | null | undefined, nowMs: number): string | null {
  if (!iso) return null
  const t = Date.parse(iso)
  if (!Number.isFinite(t)) return null
  const old = nowMs - t > 6 * 86_400_000
  if (!old) return etTime(iso, true)
  const date = new Date(t).toLocaleDateString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', year: 'numeric' })
  return `${date} ${etTime(iso)} (${Math.floor((nowMs - t) / 86_400_000)} d ago)`
}

// ── verdict ────────────────────────────────────────────────────────────────────────────────────────────────────
interface WireBlocker { category?: string; kind?: string; input?: string; state?: string; cause?: string; count?: number | null }

/** NO -> UNKNOWN only when every served blocker is a row whose input is stale/unread. Returns the new cause or null. */
export function staleOnlyNo(model: HomeV010Model, status: HomeStatusWire | null | undefined): string | null {
  if (model.tradeReady !== 'NO' || !status) return null
  const blockers = (status.blockers || []) as WireBlocker[]
  if (blockers.length === 0) return null
  const proofOnly = blockers.every(b => b.kind === 'row' && UNREADABLE.has(String(b.state || '').replace('_', ' ')))
  if (!proofOnly) return null
  // A gate that itself confirms a gap (GAP / WARN on a required gate) keeps NO.
  if ((model.gates || []).some(g => g.required && CONFIRMING.has(g.state))) return null
  const why = blockers.map(b => `${b.category || b.input || 'input'} ${String(b.state || '').toLowerCase()}${b.cause ? ` (${b.cause})` : ''}`).join('; ')
  return `required proof missing or stale, no confirmed blocker: ${why}`
}

// ── rows ───────────────────────────────────────────────────────────────────────────────────────────────────────
function gateRow(id: string, name: string, g: GateRow): StatusRow {
  const clock = g.asOf ? `as of ${etTime(g.asOf, true)}${g.age ? ` · ${g.age} old` : ''}` : 'no as-of recorded'
  return {
    id, name, state: g.state, value: `${clock} · ${g.source}`,
    ...(g.state !== 'OK' ? { cause: g.reason || g.state.toLowerCase(), source: g.source, owner: 'see source lane' } : {}),
    needsBackend: g.needsBackend,
  }
}

export interface ReconcileNotes { verdictDowngraded: string | null; p0Disagreement: string | null; categoryMismatches: string[] }

export function reconcileModel(model: HomeV010Model, inp: HomeV010Inputs, nowMs: number = Date.now()):
  { model: HomeV010Model; notes: ReconcileNotes } {
  const gates = model.gates ? model.gates.map(g => ({ ...g })) : null
  const find = (id: string) => gates?.find(g => g.id === id) ?? null

  // A02: P0 list vs p0 gate.
  let p0Disagreement: string | null = null
  const p0g = find('p0')
  if (p0g && p0g.state === 'OK') {
    const listed = model.p0.length
    const gateCount = p0g.count ?? 0
    if (listed !== gateCount) {
      p0Disagreement = `populations disagree: the gate read ${gateCount} open P0 (${p0g.source}${p0g.asOf ? `, as of ${etTime(p0g.asOf, true)}` : ''}); `
        + `/api/v2/home/incidents lists ${listed} (${model.p0.map(p => p.id.replace(/^p0-/, '#')).join(', ') || 'none'})`
      p0g.state = 'UNKNOWN'
      p0g.reason = `${p0Disagreement} — the gate cannot vouch for "no P0"`
    }
  }

  // A01: incident labels from typed fields.
  const items = (inp.incidents.state === 'OK' ? inp.incidents.data?.items : null) || []
  const categoryMismatches: string[] = []
  // Keys must be built exactly as buildModel builds them: the index `n` is the position in the P0-filtered list (and, for
  // since rows, in the window-filtered list), not in the full items array — else an item without an incident_id would
  // lend its label / clock to another item.
  const byId = new Map(items.filter(i => i.priority === 'P0').map((i, n) => [`p0-${i.incident_id ?? n}`, i]))
  const p0 = model.p0.map(p => {
    const it = byId.get(p.id)
    if (!it) return p
    const c = incidentCategory(it)
    const det = detectedText(it.first_seen_at, nowMs)
    let detail = p.detail.map(d => (d.startsWith('Detected: ') && det)
      ? `Detected: ${det}${it.failed_checks != null ? ` · ${it.failed_checks} checks` : ''}` : d)
    if (it.stale_condition) detail = [...detail, 'Condition flagged stale by the server (stale_condition)']
    if (!c.mismatch) return { ...p, detail }
    categoryMismatches.push(`#${it.incident_id ?? '?'}: ${c.mismatch}`)
    return { ...p, title: [c.label, it.symbol, it.account_label].filter(Boolean).join(' · '), detail: [...detail, `Label check: ${c.mismatch}`] }
  })
  const ls = inp.lastSeen.state === 'OK' ? inp.lastSeen.data?.read : null
  const windowStart = ls?.status === 'RECORDED' && ls.seen_at ? new Date(ls.seen_at).getTime() : nowMs - 24 * 3600_000
  const inWindow = items.filter(i => { const t = i.first_seen_at ? new Date(i.first_seen_at).getTime() : NaN; return Number.isFinite(t) && t >= windowStart })
  const sinceById = new Map(inWindow.map((i, n) => [`since-${i.incident_id ?? n}`, i]))
  const sinceRows = model.since.rows.map(r => {
    const it = sinceById.get(r.id)
    if (!it) return r
    const c = incidentCategory(it)
    return c.mismatch ? { ...r, text: [c.label, it.symbol].filter(Boolean).join(' · ') } : r
  })

  // A04 + A03: status rows from the canonical gate projection.
  const sched = find('schedulers')
  const cov = find('orders')
  const status: StatusRow[] = []
  for (const r of model.status) {
    if (r.id === 'row-schedulers' && sched) { status.push(gateRow('row-schedulers', 'Schedulers', sched)); continue }
    if (r.id === 'row-alerts' && items[0] && r.cause) {
      const c = incidentCategory(items[0])
      status.push(c.mismatch ? { ...r, cause: c.label } : r); continue
    }
    if (r.id === 'row-orders') {
      status.push({ ...r, name: 'Stop read (raw)' })
      if (cov) {
        const row = gateRow('row-coverage', 'Stop coverage (derived)', cov)
        if (cov.state === 'STALE' || cov.state === 'UNKNOWN' || cov.state === 'TIMED OUT') {
          const raw = r.state === 'OK' ? `the raw stop read is current (${r.value})` : `the raw stop read is ${r.state}`
          row.cause = `coverage product not re-observed${cov.asOf ? ` since ${etTime(cov.asOf, true)}` : ''}; ${raw}. Proof missing, not a confirmed gap`
        }
        status.push(row)
      }
      continue
    }
    status.push(r)
  }

  // Stop advice whose read was not recorded (stop_read.status 'missing'): buildModel draws no stop rows then, and could
  // say "Nothing needs action" while the classic SinceCloseStops lists the same actions under "STOPS READ NOT RECORDED".
  // The two sections must not contradict: the read is surfaced as UNKNOWN and the empty state is withdrawn.
  let unread = model.unread
  let actionEmpty = model.actionEmpty
  const scData = inp.sinceClose.state === 'OK' ? inp.sinceClose.data : null
  if (scData && (scData as { status?: string }).status === 'ok') {
    const sc = sinceCloseModel(scData, nowMs)
    const open = sc?.stops?.actions?.length ?? 0
    if (sc?.stops?.read?.status === 'missing' && open > 0 && !unread.some(u => u.source === inp.sinceClose.source)) {
      unread = [...unread, { source: inp.sinceClose.source, label: `stop advice (${open} action${open === 1 ? '' : 's'}, stop read not recorded)`, state: 'UNKNOWN', lastGood: null }]
      actionEmpty = false
    }
  }

  // Verdict.
  const downgrade = staleOnlyNo(model, inp.status?.state === 'OK' ? inp.status.data : null)
  const tradeReady = downgrade ? 'UNKNOWN' as const : model.tradeReady
  const tradeReadyCause = downgrade ?? model.tradeReadyCause
  const why = {
    blockers: [
      ...(downgrade ? [{ category: 'Server NO shown as UNKNOWN', detail: downgrade }] : []),
      ...(p0Disagreement ? [{ category: 'P0 populations disagree', detail: p0Disagreement, targetId: 'card-gates' }] : []),
      ...model.why.blockers.map(b => (b.targetId === 'row-schedulers' && sched)
        ? { ...b, category: `Schedulers: ${sched.state}`, detail: `Cause: ${sched.reason || sched.state.toLowerCase()} · Source: ${sched.source}`, needsBackend: sched.needsBackend } : b)
        .filter(b => !(sched && sched.state === 'OK' && b.targetId === 'row-schedulers')),
    ],
    inputs: model.why.inputs.map(i => (i.name === 'Schedulers' && sched)
      ? { ...i, state: (sched.state === 'GAP' ? 'GAP' : sched.state) as typeof i.state, ageText: sched.age || undefined, needsBackend: sched.needsBackend } : i),
  }
  return {
    model: { ...model, gates, p0, unread, actionEmpty, tradeReady, tradeReadyCause, status, since: { ...model.since, rows: sinceRows }, why },
    notes: { verdictDowngraded: downgrade, p0Disagreement, categoryMismatches },
  }
}

export type { RowState }
