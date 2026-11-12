/** Home v010 — the operator-approved Home (design/pages/home/v010, approved 2026-11-11 22:44 ET).
 *  One read per endpoint per load, no polling (server memory pressure); diagnostics only when the drawer opens.
 *  No broker-backed read, no /api/v2/overview. The old Home stays at /v3/home-classic. */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { DiagnosticsDrawer, HomeV010View, WhySheet } from '../components/home/v010'
import {
  API, buildModel, diagFallback, diagFromWire, loadingRead, readOnce,
  type ApprovalsWire, type DiagRecordModel, type HomeStatusWire, type HomeV010Inputs, type IncidentsWire, type LastSeenWire,
} from '../lib/homeV010'
import type { SinceCloseWire } from '../lib/sinceClose'

const LAST_GOOD_KEY = 'cc.home.v010.lastGood'
function loadLastGood(): Record<string, string | null> {
  try { return JSON.parse(window.localStorage.getItem(LAST_GOOD_KEY) || '{}') || {} } catch { return {} }
}
function saveLastGood(v: Record<string, string | null>) {
  try { window.localStorage.setItem(LAST_GOOD_KEY, JSON.stringify(v)) } catch { /* per-viewer convenience only */ }
}

export default function HomeV010() {
  const [inp, setInp] = useState<HomeV010Inputs>({
    sinceClose: loadingRead<SinceCloseWire>(API.sinceClose),
    approvals: loadingRead<ApprovalsWire>(API.approvals),
    incidents: loadingRead<IncidentsWire>(API.incidents),
    lastSeen: loadingRead<LastSeenWire>(API.lastSeen),
    status: loadingRead<HomeStatusWire>(API.status),
  })
  const [lastGood] = useState(loadLastGood)
  const [nowIso, setNowIso] = useState(() => new Date().toISOString())
  const [whyOpen, setWhyOpen] = useState(false)
  const [diagOpen, setDiagOpen] = useState(false)
  const [diag, setDiag] = useState<{ records: DiagRecordModel[] | null; fetchedAt?: string; error?: string } | null>(null)

  useEffect(() => {
    let alive = true
    const keys: Array<[keyof HomeV010Inputs, string]> = [['incidents', API.incidents], ['sinceClose', API.sinceClose], ['approvals', API.approvals], ['lastSeen', API.lastSeen], ['status', API.status]]
    for (const [k, src] of keys) {
      void readOnce<unknown>(src).then(r => {
        if (!alive) return
        setInp(prev => ({ ...prev, [k]: r } as HomeV010Inputs))
        setNowIso(new Date().toISOString())
        if (r.state === 'OK' && r.at) { const lg = loadLastGood(); lg[src] = r.at; saveLastGood(lg) }
      })
    }
    return () => { alive = false }
  }, [])

  // Clock only, no network: a tab left open must demote a served YES older than YES_MAX_AGE_MS (REVIEW-2446 F-1).
  useEffect(() => {
    const t = window.setInterval(() => setNowIso(new Date().toISOString()), 30_000)
    return () => window.clearInterval(t)
  }, [])

  const model = useMemo(() => buildModel(inp, Date.parse(nowIso), lastGood), [inp, nowIso, lastGood])

  // Scroll lock, focus trap and Escape live in the sheets themselves (useSheetA11y in WhySheet).

  const openDiag = useCallback(() => {
    setDiagOpen(true)
    if (diag) return
    void readOnce<unknown>(API.diagnostics).then(r => {
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
      <HomeV010View model={model} nowIso={nowIso} onOpenWhy={() => setWhyOpen(true)} onOpenDiag={openDiag} />
      <WhySheet open={whyOpen} onClose={() => setWhyOpen(false)} verdict={model.tradeReady}
        blockers={model.why.blockers} inputs={model.why.inputs} onGoTo={goTo} />
      <DiagnosticsDrawer open={diagOpen} onClose={() => setDiagOpen(false)} records={records}
        fetchedAt={diag?.fetchedAt} error={diag ? diag.error : 'reading /api/v2/home/diagnostics…'} />
    </>
  )
}
