/** Combined Home (operator order 2026-11-13): the complete classic Home first, then the operational Home section
 *  appended beneath it, in the same vertical order on phones, tablets and desktop.
 *
 *  - One application shell: this is a route element inside App's Shell (one header, one NavRail, one scroll owner —
 *    `main.app-main`). Nothing here sets its own height or overflow.
 *  - The classic part is HomeHub itself, unchanged: every card, drawer, sheet, deep link and `?view=classic` keep working.
 *  - The operational part draws the v010 view (HomeV010View, WhySheet, DiagnosticsDrawer) from the v010 model, with
 *    the A01–A04 reconciliation in lib/homeCombined.ts applied before drawing.
 *  - No duplicate load: the operational reads go through lib/sharedRead (readShared). A path a classic or shell hook
 *    already polls (since-close, approvals/summary) is answered from that hook's body or joins its in-flight GET; the
 *    other reads (incidents, last-seen, status, priorities) are one GET per load, no polling, as on /v3 v010 before.
 *  - One published version: after its first read the section stays subscribed (passively, no timer) to every path it
 *    drew, so whenever a classic or shell hook polls one of those paths the section redraws from the same body. A
 *    version the section drew that differs from the one the page holds is shown as a DEFECT (ProductClocks).
 *  The routes /home-classic and the v010 page component stay as they were (classic link kept until validated). */
import { useCallback, useEffect, useMemo, useState } from 'react'
import HomeHub from './HomeHub'
import type { DrillContext } from '../components/DetailDrawer'
import { DiagnosticsDrawer, HomeV010View, WhySheet } from '../components/home/v010'
import {
  API, buildModel, diagFallback, diagFromWire, loadingRead,
  type ApprovalsWire, type DiagRecordModel, type HomeStatusWire, type HomeV010Inputs, type IncidentsWire, type LastSeenWire, type Read,
} from '../lib/homeV010'
import type { SinceCloseWire } from '../lib/sinceClose'
import { PRIORITIES_API, prioritiesView, recordVisit, type PrioritiesWire } from '../lib/homePriorities'
import { readFromBody, readShared } from '../lib/sharedRead'
import { COMBINED_SECTION_ID, COMBINED_SECTION_TITLE, reconcileModel } from '../lib/homeCombined'
import { listLastGood, subscribeAnyBody, subscribeBody } from '../hooks/useApi'
import { PRODUCTS_HOME_API, clockAt, productClock, productsFromBundle, versionMismatch, type ProductClock } from '../lib/productEnvelope'
import { etTime } from '../lib/homeV010'

const LAST_GOOD_KEY = 'cc.home.v010.lastGood'
function loadLastGood(): Record<string, string | null> {
  try { return JSON.parse(window.localStorage.getItem(LAST_GOOD_KEY) || '{}') || {} } catch { return {} }
}
function saveLastGood(v: Record<string, string | null>) {
  try { window.localStorage.setItem(LAST_GOOD_KEY, JSON.stringify(v)) } catch { /* per-viewer convenience only */ }
}

/** The reads the operational section makes, in order. Exported for the endpoint inventory test. */
export const OPERATIONAL_READS: ReadonlyArray<readonly [keyof HomeV010Inputs, string]> = [
  ['incidents', API.incidents], ['sinceClose', API.sinceClose], ['approvals', API.approvals], ['lastSeen', API.lastSeen], ['status', API.status],
]

export function HomeOperationalSection() {
  const [inp, setInp] = useState<HomeV010Inputs>({
    sinceClose: loadingRead<SinceCloseWire>(API.sinceClose),
    approvals: loadingRead<ApprovalsWire>(API.approvals),
    incidents: loadingRead<IncidentsWire>(API.incidents),
    lastSeen: loadingRead<LastSeenWire>(API.lastSeen),
    status: loadingRead<HomeStatusWire>(API.status),
  })
  const [prio, setPrio] = useState<Read<PrioritiesWire>>(() => loadingRead<PrioritiesWire>(PRIORITIES_API))
  const [products, setProducts] = useState<Read<unknown>>(() => loadingRead<unknown>(PRODUCTS_HOME_API))
  const [lastGood] = useState(loadLastGood)
  const [nowIso, setNowIso] = useState(() => new Date().toISOString())
  const [whyOpen, setWhyOpen] = useState(false)
  const [diagOpen, setDiagOpen] = useState(false)
  const [diag, setDiag] = useState<{ records: DiagRecordModel[] | null; fetchedAt?: string; error?: string } | null>(null)

  useEffect(() => {
    let alive = true
    for (const [k, src] of OPERATIONAL_READS) {
      void readShared<unknown>(src).then(r => {
        if (!alive) return
        setInp(prev => ({ ...prev, [k]: r } as HomeV010Inputs))
        setNowIso(new Date().toISOString())
        if (r.state === 'OK' && r.at) { const lg = loadLastGood(); lg[src] = r.at; saveLastGood(lg) }
        // Record this visit only after the previous one was read, once per load (separate POST; GET stays read-only).
        if (k === 'lastSeen' && r.state === 'OK') void recordVisit(window.innerWidth)
      })
    }
    void readShared<PrioritiesWire>(PRIORITIES_API).then(r => { if (alive) setPrio(r) })
    // Stored products (DSN-20261112 §6.1). Until wt/home-products-lead serves the route this is UNKNOWN with its HTTP reason.
    void readShared<unknown>(PRODUCTS_HOME_API).then(r => { if (alive) setProducts(r) })
    // Version lock: any later body for these paths (a classic/shell poll, the visible-again read) redraws this section.
    const offs = OPERATIONAL_READS.map(([k, src]) => subscribeBody(src, (json, at) => {
      if (!alive) return
      setInp(prev => ({ ...prev, [k]: readFromBody(src, json, new Date(at).toISOString()) } as HomeV010Inputs))
      setNowIso(new Date().toISOString())
    }))
    offs.push(subscribeBody(PRODUCTS_HOME_API, (json, at) => { if (alive) setProducts(readFromBody<unknown>(PRODUCTS_HOME_API, json, new Date(at).toISOString())) }))
    offs.push(subscribeBody(PRIORITIES_API, (json, at) => { if (alive) setPrio(readFromBody<PrioritiesWire>(PRIORITIES_API, json, new Date(at).toISOString())) }))
    return () => { alive = false; offs.forEach(off => off()) }
  }, [])

  // Clock only, no network: a served YES older than YES_MAX_AGE_MS is demoted by the model.
  useEffect(() => {
    const t = window.setInterval(() => setNowIso(new Date().toISOString()), 30_000)
    return () => window.clearInterval(t)
  }, [])

  const base = useMemo(() => buildModel(inp, Date.parse(nowIso), lastGood), [inp, nowIso, lastGood])
  const model = useMemo(() => reconcileModel(base, inp, Date.parse(nowIso)).model, [base, inp, nowIso])
  const priorities = useMemo(() => prioritiesView(prio), [prio])

  const openDiag = useCallback(() => {
    setDiagOpen(true)
    if (diag) return
    void readShared<unknown>(API.diagnostics).then(r => {
      const rows = r.state === 'OK' ? diagFromWire(r.data) : null
      setDiag({ records: rows, fetchedAt: r.at || undefined,
        error: rows ? undefined : `${API.diagnostics}: ${r.state === 'OK' ? 'no rows' : `${r.state}${r.error ? ` (${r.error})` : ''}`} — records below are built from this page's own reads` })
    })
  }, [diag])

  const goTo = useCallback((id: string) => {
    setWhyOpen(false)
    window.setTimeout(() => document.getElementById(id)?.scrollIntoView({ block: 'start', behavior: 'smooth' }), 0)
  }, [])

  const records = diag?.records ?? diagFallback(model, inp)
  return (
    <>
      <HomeV010View model={model} priorities={priorities} nowIso={nowIso} onOpenWhy={() => setWhyOpen(true)} onOpenDiag={openDiag} />
      <WhySheet open={whyOpen} onClose={() => setWhyOpen(false)} verdict={model.tradeReady}
        blockers={model.why.blockers} inputs={model.why.inputs} onGoTo={goTo} />
      <DiagnosticsDrawer open={diagOpen} onClose={() => setDiagOpen(false)} records={records}
        fetchedAt={diag?.fetchedAt} error={diag ? diag.error : 'reading /api/v2/home/diagnostics…'} />
      <ProductClocks consumed={consumedClocks(inp, prio, products)} nowMs={Date.parse(nowIso)} />
    </>
  )
}

/** The product clock of every body the operational section drew (or why it has none). */
export function consumedClocks(inp: HomeV010Inputs, prio: Read<PrioritiesWire>, products?: Read<unknown>): Record<string, { clock: ProductClock; read: string }> {
  const out: Record<string, { clock: ProductClock; read: string }> = {}
  const add = (src: string, r: Read<unknown>) => {
    if (r.state === 'LOADING') return
    const clock = r.state === 'OK' ? productClock(r.data)
      : productClock(null, /HTTP (\d+)/.test(r.error || '') ? Number(/HTTP (\d+)/.exec(r.error || '')![1]) : 0)
    out[src] = { clock: r.state === 'OK' ? clock : { ...clock, reason: `${r.state === 'TIMED OUT' ? 'timed out' : 'could not read'}${r.error ? ` (${r.error})` : ''}`
      + (src === PRODUCTS_HOME_API ? ' — stored-products route not served yet (wt/home-products-lead)' : '') }, read: r.at || '' }
  }
  for (const [k, src] of OPERATIONAL_READS) add(src, inp[k] as Read<unknown>)
  add(PRIORITIES_API, prio as Read<unknown>)
  if (products && products.state !== 'LOADING') {
    if (products.state !== 'OK') add(PRODUCTS_HOME_API, products)
    else for (const p of productsFromBundle(products.data)) out[`${PRODUCTS_HOME_API}#${p.id}`] = { clock: p.clock, read: products.at || '' }
  }
  return out
}

const OPERATIONAL_PATHS: ReadonlySet<string> = new Set([...OPERATIONAL_READS.map(([, s]) => s), PRIORITIES_API, PRODUCTS_HOME_API])

/** Source time, build time and freshness of every endpoint this page drew, both sections. A route that is not a stored
 *  product says so; a product that is missing / building / unreadable is UNKNOWN with its reason; a version the
 *  operational section drew that differs from the one the page holds is a DEFECT. */
export function ProductClocks({ consumed, held, nowMs }: { consumed: Record<string, { clock: ProductClock; read: string }>; held?: Array<[string, { json: unknown; at: number }]>; nowMs?: number }) {
  const [, bump] = useState(0)
  useEffect(() => subscribeAnyBody(() => bump(n => n + 1)), [])
  const rows = new Map<string, { clock: ProductClock; usedBy: string; defect: string | null }>()
  const now = nowMs ?? Date.now()
  for (const [path, body] of (held ?? listLastGood())) {
    if (path === PRODUCTS_HOME_API) continue // drawn per product below
    const clock = clockAt(productClock(body.json), now)
    const mine = consumed[path]
    rows.set(path, { clock, usedBy: OPERATIONAL_PATHS.has(path) ? 'classic / shell + operational' : 'classic / shell',
      defect: mine ? versionMismatch(path, mine.clock, clock) : null })
  }
  for (const [path, mine] of Object.entries(consumed)) {
    if (!rows.has(path)) rows.set(path, { clock: clockAt(mine.clock, now), usedBy: 'operational', defect: null })
  }
  const list = [...rows.entries()].sort(([a], [b]) => a.localeCompare(b))
  const defects = list.filter(([, r]) => r.defect).length
  const t = (iso: string | null) => (iso ? etTime(iso, true) : '—')
  return (
    <details data-testid="home-product-clocks" style={{ marginTop: 16, fontSize: 12, color: 'var(--text1)' }}>
      <summary style={{ cursor: 'pointer', color: 'var(--text0)', fontWeight: 600 }}>
        Product clocks · {list.length} endpoints{defects ? ` · ${defects} version DEFECT${defects > 1 ? 'S' : ''}` : ''}
      </summary>
      <p style={{ margin: '6px 0', color: 'var(--text2)' }}>
        Source time (as of) and build time are separate clocks. &quot;Not a product&quot; means the route is still computed per request.
      </p>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 560 }}>
          <thead><tr style={{ textAlign: 'left', color: 'var(--text2)' }}>
            <th>Endpoint</th><th>Used by</th><th>Product</th><th>Source as of</th><th>Built</th><th>Fresh / expiry</th><th>Version</th>
          </tr></thead>
          <tbody>
            {list.map(([path, r]) => (
              <tr key={path} data-path={path} data-status={r.clock.status} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                <td style={{ fontFamily: 'var(--font-mono, monospace)', wordBreak: 'break-all' }}>{path}</td>
                <td>{r.usedBy}</td>
                <td style={{ color: r.clock.verdict === 'OK' ? 'var(--green)' : r.clock.verdict === 'STALE' ? 'var(--amber)' : 'var(--text1)' }}>
                  {r.clock.status === 'NOT A PRODUCT' ? 'NOT A PRODUCT · UNKNOWN' : r.clock.status}{r.clock.reason ? ` — ${r.clock.reason}` : ''}
                  {r.defect ? <div role="alert" style={{ color: 'var(--red)' }}>{r.defect}</div> : null}
                </td>
                <td>{t(r.clock.asOf)}</td>
                <td>{t(r.clock.builtAt)}</td>
                <td>{r.clock.staleAfterS != null ? `stale after ${r.clock.staleAfterS}s` : '—'}{r.clock.hardExpiryS != null ? ` · expires ${r.clock.hardExpiryS}s` : ''}{r.clock.nextRefreshAt ? ` · next ${t(r.clock.nextRefreshAt)}` : ''}</td>
                <td>{r.clock.version ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  )
}

interface Props { onDrill: (ctx: DrillContext) => void }

export default function HomeCombined({ onDrill }: Props) {
  return (
    <div data-testid="home-combined" data-order="classic-then-operational">
      <div data-testid="home-combined-classic" data-part="classic">
        <HomeHub onDrill={onDrill} />
      </div>
      <section id={COMBINED_SECTION_ID} data-testid="home-combined-operational" data-part="operational" aria-labelledby={`${COMBINED_SECTION_ID}-h`}
        style={{ maxWidth: 1392, margin: '24px auto 0', paddingTop: 16, borderTop: '1px solid var(--border)' }}>
        <h2 id={`${COMBINED_SECTION_ID}-h`} style={{ fontSize: 16, fontWeight: 700, margin: '0 0 4px', color: 'var(--text0)' }}>{COMBINED_SECTION_TITLE}</h2>
        <p style={{ fontSize: 12, margin: '0 0 12px', color: 'var(--text2)' }}>
          Appended below the complete Home above. Each value names its source and clock; a missing proof is UNKNOWN, never an all-clear.
        </p>
        <HomeOperationalSection />
      </section>
    </div>
  )
}
