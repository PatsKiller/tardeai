/** Portfolio v002 — the operator-approved Portfolio (design/pages/portfolio/v002, approved with amendments 2026-11-11).
 *  Reads, one per load, no polling (server memory pressure): /api/v2/portfolio/holdings (rows carry the backend
 *  protection_state, G1; and the PortfolioMeasures@v1 block when the writer has materialized it),
 *  /api/v2/home/incidents (system rows), and /api/v2/ui/prefs/get?key=portfolio.last_seen (the visit anchor, LQ-2467).
 *  No /api/v2/overview, no broker read. After the reads settle the page stamps its visit once (server-stamped POST).
 *  The old page stays at /v3/portfolio-classic (UI removal rule). Legacy deep links (?tab, ?drawer, ?sig, ?acct)
 *  are sent there unchanged; ?symbol= opens the position sheet here. */
import { useCallback, useEffect, useMemo, useState, type ComponentProps } from 'react'
import { Navigate, useLocation, useSearchParams } from 'react-router-dom'
import { DiagnosticsDrawer } from '../components/home/v010'
import { legacyPortfolioRedirect } from '../lib/portfolioDeepLink'
import PortfolioV002View, { HOLDINGS_PAGE } from '../components/portfolio/v002/PortfolioV002View'
import {
  AuditSheet, GateEvidenceSheet, MeasuresSheet, PositionSheet, ProtectionWhySheet, RiskSheet, SinceLastVisitSheet, SyncToolsSheet,
} from '../components/portfolio/v002/PortfolioSheets'
import {
  API, auditCategories, changesModel, filterPositions, fmtAge, gateStore, holdingsCsv, loadingRead, measuresModel, p0Items,
  positionsFrom, protectionModel, readOnce, recordPortfolioVisit, sinceVisitModel, snapshotFacts, statusRows,
  type HoldingsFilter, type HoldingsWire, type IncidentsWire, type LastSeenWire, type MeasureKey, type MeasuresModel,
  type PortfolioChangesWire, type PortfolioGatesWire, type ProtectionModel, type Read, type SinceVisitModel, type StatusRow,
  type VisitRecord,
} from '../lib/portfolioV002'

type DiagRecord = ComponentProps<typeof DiagnosticsDrawer>['records'][number]

// OBS-P2a/P2b: the classic-only query params are a tested contract (lib/portfolioDeepLink), not a page-local list.

export function diagRecords(h: Read<HoldingsWire>, prot: ProtectionModel, status: StatusRow[], measures: MeasuresModel,
  since: SinceVisitModel, visit: VisitRecord, nowMs: number, gates?: Read<PortfolioGatesWire>,
  changes?: Read<PortfolioChangesWire>): DiagRecord[] {
  const st = (s: string): DiagRecord['status'] => (s === 'OK' || s === 'STALE' || s === 'UNKNOWN' || s === 'TIMED OUT' || s === 'WARN' ? s : 'UNKNOWN')
  const holdAge = h.at ? fmtAge(nowMs - Date.parse(h.at)) : '—'
  const recs: DiagRecord[] = [
    { widget: 'Holdings read', source: API.holdings, refreshRate: 'once per page load', age: holdAge, threshold: '30 s timeout',
      status: h.state === 'LOADING' ? 'UNKNOWN' : st(h.state), failureMode: 'TIMED OUT after 30 s; failed read = UNKNOWN, never empty-OK' },
  ]
  if (gates) {
    // PR-004: named as its own read, so the source-clock table shows the gate store beside holdings/incidents/visit.
    recs.push({ widget: 'Gate store read', source: API.gates, refreshRate: 'once per page load', age: gates.at ? fmtAge(nowMs - Date.parse(gates.at)) : '—',
      threshold: '900 s on the open-gate clock',
      status: gates.state === 'LOADING' ? 'UNKNOWN' : st(gates.state),
      failureMode: gates.state === 'OK' ? 'the projection answers or says why it cannot' : (gates.error || 'no answer: no gate verdict is shown') })
  }
  for (const b of prot.brokers) {
    recs.push({ widget: `Protection · ${b.broker}`, source: 'holdings protection_state (cio_truth.protection_for)', refreshRate: 'stop read lane',
      age: b.oldest ? fmtAge(nowMs - Date.parse(b.oldest)) : '—', threshold: 'backend demotes stale reads',
      status: b.state === 'OK' ? 'OK' : b.state === 'GAP' ? 'WARN' : b.state === 'WARN' ? 'WARN' : 'UNKNOWN',
      failureMode: `${b.protectedN} of ${b.counted} resting${b.cause ? ` · ${b.cause}` : ''} · UNKNOWN per row, never NO STOP` })
  }
  recs.push({ widget: 'Protection verdict', source: 'computed in page from row verdicts', refreshRate: 'per load', age: holdAge, threshold: '—',
    status: prot.verdict === 'OK' ? 'OK' : prot.verdict === 'GAP' || prot.verdict === 'WARN' ? 'WARN' : 'UNKNOWN',
    failureMode: 'served rollup /api/v2/portfolio/protection (G2) not deployed', needsBackend: true })
  recs.push({ widget: 'The four measures', source: 'holdings measures (PortfolioMeasures@v1)',
    refreshRate: 'written by the portfolio writer', age: measures.asOf ? fmtAge(nowMs - Date.parse(measures.asOf)) : '—',
    threshold: 'materialized by the writer; GET never computes',
    status: measures.state === 'PRESENT' ? (measures.dayUnverified ? 'WARN' : 'OK') : measures.state === 'LOADING' ? 'UNKNOWN' : 'UNKNOWN',
    failureMode: measures.state === 'PRESENT' ? `verified daily P&L ${measures.dayUnverified ? 'UNKNOWN by contract' : 'VERIFIED'}` : (measures.reason || 'no measures block'),
    needsBackend: measures.state !== 'PRESENT' })
  for (const r of status) {
    recs.push({ widget: r.name, source: r.id === 'row-alerts' ? API.incidents : r.id === 'row-risk' ? 'none' : API.holdings,
      refreshRate: 'per load', age: '—', threshold: r.id === 'row-value' ? '60 m' : r.id === 'row-prices' ? '30 m' : r.id === 'row-alerts' ? '15 m' : '—',
      status: r.state === 'LOADING' ? 'UNKNOWN' : st(r.state), failureMode: r.text, needsBackend: r.needsBackend })
  }
  recs.push({ widget: 'Portfolio last seen', source: API.lastSeen, refreshRate: 'once per page load (POST stamps the visit)',
    age: since.seenAt ? fmtAge(nowMs - Date.parse(since.seenAt)) : '—', threshold: 'window: ' + since.windowBasis,
    status: since.status === 'LOADING' ? 'UNKNOWN' : since.status === 'RECORDED' ? 'OK' : 'UNKNOWN',
    failureMode: `visit ${visit}; ${since.reason || since.windowText}` })
  // PR-004: the served portfolio gate projection. An unanswered read is UNAVAILABLE — never a gate verdict, and never "0 open".
  const gs = gates ? gateStore(gates, nowMs) : null
  recs.push({ widget: 'Validation gates · served projection', source: API.gates, refreshRate: 'once per page load',
    age: gs && gs.state !== 'UNAVAILABLE' ? gs.snapshotLine : '—', threshold: '900 s on the open-gate clock',
    status: gs == null ? 'UNKNOWN' : gs.state === 'UNAVAILABLE' ? 'UNKNOWN' : st(gs.state),
    failureMode: gs == null ? 'no gate read on this page' : gs.headline, needsBackend: gs == null || gs.state === 'UNAVAILABLE' })
  // PR-005: the served change list. The cursor is the SERVER-stamped visit read before this load stamps its own.
  const cm = changes ? changesModel(changes, since) : null
  recs.push({ widget: 'Since your last visit · change list', source: API.changes, refreshRate: 'once per page load',
    age: changes?.at ? fmtAge(nowMs - Date.parse(changes.at)) : '—', threshold: 'window: ' + since.windowBasis,
    status: cm == null ? 'UNKNOWN' : cm.state === 'UNAVAILABLE' ? 'UNKNOWN' : 'OK',
    failureMode: cm == null ? 'no change read on this page' : cm.headline, needsBackend: cm == null || cm.state === 'UNAVAILABLE' })
  recs.push({ widget: 'Audit state lifecycle', source: 'none', refreshRate: '—', age: '—', threshold: '15 m', status: 'NOT AVAILABLE', failureMode: 'change store (LQ-2143)', needsBackend: true })
  recs.push({ widget: 'Risk score', source: 'none', refreshRate: '—', age: '—', threshold: '—', status: 'NOT AVAILABLE', failureMode: 'pending decision: no approved definition (G7)', needsBackend: true })
  recs.push({ widget: 'Fidelity GTC stop sync', source: 'retired (account closed)', refreshRate: '—', age: '—', threshold: '—', status: 'NOT AVAILABLE', failureMode: 'Retired for one release, then removed (R5)' })
  return recs
}

export default function PortfolioV002() {
  const [params] = useSearchParams()
  const location = useLocation()
  const legacyTo = legacyPortfolioRedirect(location.search)
  const [holdings, setHoldings] = useState<Read<HoldingsWire>>(loadingRead<HoldingsWire>(API.holdings))
  const [incidents, setIncidents] = useState<Read<IncidentsWire>>(loadingRead<IncidentsWire>(API.incidents))
  const [lastSeen, setLastSeen] = useState<Read<LastSeenWire>>(loadingRead<LastSeenWire>(API.lastSeen))
  // PR-004: the portfolio-scoped gate store. Read once per load; a 404 (route not yet wired) is an honest UNAVAILABLE.
  const [gates, setGates] = useState<Read<PortfolioGatesWire>>(loadingRead<PortfolioGatesWire>(API.gates))
  // PR-005: the change list, read AFTER the visit cursor lands so the window is the server-stamped one (LQ-2467).
  const [changes, setChanges] = useState<Read<PortfolioChangesWire>>(loadingRead<PortfolioChangesWire>(API.changes))
  const [visitRecord, setVisitRecord] = useState<VisitRecord>('PENDING')
  const [nowIso, setNowIso] = useState(() => new Date().toISOString())
  const [filter, setFilter] = useState<HoldingsFilter>('all')
  const [account, setAccount] = useState('all')
  const [shownCount, setShownCount] = useState(HOLDINGS_PAGE)
  const [showAllAction, setShowAllAction] = useState(false)
  const [whyOpen, setWhyOpen] = useState(false)
  const [diagOpen, setDiagOpen] = useState(false)
  const [auditOpen, setAuditOpen] = useState(false)
  const [gatesOpen, setGatesOpen] = useState(false)
  const [sinceOpen, setSinceOpen] = useState(false)
  const [syncOpen, setSyncOpen] = useState(false)
  const [riskOpen, setRiskOpen] = useState(false)
  const [measuresOpen, setMeasuresOpen] = useState(false)
  const [measureFocus, setMeasureFocus] = useState<MeasureKey | null>(null)
  const [posKey, setPosKey] = useState<string | null>(null)

  useEffect(() => {
    if (legacyTo) return
    let alive = true
    const reads = Promise.all([
      readOnce<HoldingsWire>(API.holdings).then(r => { if (alive) setHoldings(r) }),
      readOnce<IncidentsWire>(API.incidents).then(r => { if (alive) setIncidents(r) }),
      readOnce<LastSeenWire>(API.lastSeen).then(async r => {
        if (!alive) return
        setLastSeen(r)
        // PR-005: the cursor is the value the SERVER returned, read before this visit stamps (LQ-2467). A local clock
        // is never sent. No recorded visit -> no cursor -> the server windows 24 h and says so in `window.basis`.
        const seen = r.state === 'OK' ? r.data?.read?.seen_at : null
        const url = seen ? `${API.changes}?since=${encodeURIComponent(seen)}` : API.changes
        const c = await readOnce<PortfolioChangesWire>(url)
        if (alive) setChanges(c)
      }),
      readOnce<PortfolioGatesWire>(API.gates).then(r => { if (alive) setGates(r) }),
    ])
    // One visit stamp per load, after every read has settled, server-stamped (LQ-2467). Not part of the reads.
    void reads.then(() => {
      if (!alive) return
      setNowIso(new Date().toISOString())
      void recordPortfolioVisit(window.innerWidth).then(s => { if (alive) setVisitRecord(s) })
    })
    return () => { alive = false }
  }, [legacyTo])

  const positions = useMemo(() => (holdings.state === 'OK' ? positionsFrom(holdings.data) : []), [holdings])
  const prot = useMemo(() => protectionModel(holdings, positions), [holdings, positions])
  const p0 = useMemo(() => p0Items(holdings, prot), [holdings, prot])
  const status = useMemo(() => statusRows(holdings, incidents, positions, Date.parse(nowIso)), [holdings, incidents, positions, nowIso])
  const audit = useMemo(() => auditCategories(prot, p0), [prot, p0])
  const measures = useMemo(() => measuresModel(holdings), [holdings])
  const sinceVisit = useMemo(() => sinceVisitModel(lastSeen), [lastSeen])

  // ?symbol= deep link (Home, Research Intel) opens that position's sheet once the read lands.
  const wantSymbol = (params.get('symbol') || '').toUpperCase()
  useEffect(() => {
    if (!wantSymbol || positions.length === 0) return
    const hit = positions.find(p => p.symbol === wantSymbol)
    if (hit) setPosKey(hit.key)
  }, [wantSymbol, positions])

  const anyOpen = whyOpen || diagOpen || auditOpen || gatesOpen || sinceOpen || syncOpen || riskOpen || measuresOpen || posKey != null
  useEffect(() => {
    if (!anyOpen) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = prev }
  }, [anyOpen])

  const goTo = useCallback((id: string) => {
    setWhyOpen(false)
    window.setTimeout(() => document.getElementById(id)?.scrollIntoView({ block: 'start', behavior: 'smooth' }), 0)
  }, [])

  const exportCsv = useCallback(() => {
    const rows = filterPositions(positions, filter, account)
    if (rows.length === 0) return
    // OBS-P1: the CSV carries the SAME snapshot identity the header line and the rows were drawn from — one read, one
    // id, so an exported file cannot describe a different book than the page it came from.
    const snap = snapshotFacts(holdings.state === 'OK' ? holdings.data : null, positions.map(p => ({ account_id: p.accountKey })), account)
    const blob = new Blob([holdingsCsv(rows, snap)], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `portfolio-holdings-${new Date().toISOString().slice(0, 10)}.csv`
    document.body.appendChild(a)
    a.click()
    a.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 0)
  }, [positions, filter, account, holdings])

  if (legacyTo) return <Navigate to={legacyTo} replace />

  const pos = posKey ? positions.find(p => p.key === posKey) ?? null : null
  return (
    <>
      <PortfolioV002View holdings={holdings} positions={positions} prot={prot} p0={p0} status={status}
        measures={measures} sinceVisit={sinceVisit} visitRecord={visitRecord} nowIso={nowIso}
        filter={filter} account={account} shownCount={shownCount} showAllAction={showAllAction}
        onFilter={f => { setFilter(f); setShownCount(HOLDINGS_PAGE); window.setTimeout(() => document.getElementById('card-holdings')?.scrollIntoView({ block: 'start' }), 0) }}
        onAccount={a => { setAccount(a); setShownCount(HOLDINGS_PAGE) }}
        onShowMore={() => setShownCount(n => n + HOLDINGS_PAGE)} onShowAllAction={() => setShowAllAction(true)}
        onOpenWhy={() => setWhyOpen(true)} onOpenDiag={() => setDiagOpen(true)} onOpenAudit={() => setAuditOpen(true)}
        onOpenPosition={setPosKey}
        onOpenMeasures={() => { setMeasureFocus(null); setMeasuresOpen(true) }}
        onOpenMeasure={k => { setMeasureFocus(k); setMeasuresOpen(true) }}
        onOpenGates={() => setGatesOpen(true)}
        onOpenSince={() => setSinceOpen(true)} onOpenSync={() => setSyncOpen(true)} onOpenRisk={() => setRiskOpen(true)}
        onExportCsv={exportCsv} />
      <ProtectionWhySheet open={whyOpen} onClose={() => setWhyOpen(false)} prot={prot} positions={positions} nowIso={nowIso} onGoTo={goTo} />
      <PositionSheet pos={pos} onClose={() => setPosKey(null)} holdings={holdings.data} nowIso={nowIso} />
      <MeasuresSheet open={measuresOpen} onClose={() => setMeasuresOpen(false)} measures={measures} nowIso={nowIso} focus={measureFocus} />
      <GateEvidenceSheet open={gatesOpen} onClose={() => setGatesOpen(false)} prot={prot} measures={measures} positions={positions}
        holdings={holdings.data} gatesRead={gates} nowMs={Date.parse(nowIso)} />
      <SinceLastVisitSheet open={sinceOpen} onClose={() => setSinceOpen(false)} since={sinceVisit} visitRecord={visitRecord}
        changesRead={changes} />
      <SyncToolsSheet open={syncOpen} onClose={() => setSyncOpen(false)} holdings={holdings.data} nowIso={nowIso}
        onExportCsv={exportCsv} canExport={filterPositions(positions, filter, account).length > 0} />
      <RiskSheet open={riskOpen} onClose={() => setRiskOpen(false)} />
      <AuditSheet open={auditOpen} onClose={() => setAuditOpen(false)} categories={audit} readOk={holdings.state === 'OK'} />
      <DiagnosticsDrawer open={diagOpen} onClose={() => setDiagOpen(false)}
        records={diagRecords(holdings, prot, status, measures, sinceVisit, visitRecord, Date.parse(nowIso), gates, changes)}
        fetchedAt={holdings.at || undefined} />
    </>
  )
}
