/** Portfolio v002 — the operator-approved Portfolio (design/pages/portfolio/v002, approved with amendments 2026-11-11).
 *  Reads, one per load, no polling (server memory pressure): /api/v2/portfolio/holdings (rows carry the backend
 *  protection_state, G1) and /api/v2/home/incidents (Alerts row). No /api/v2/overview, no broker read.
 *  The old page stays at /v3/portfolio-classic (UI removal rule). Legacy deep links (?tab, ?drawer, ?sig, ?acct)
 *  are sent there unchanged; ?symbol= opens the position sheet here. */
import { useCallback, useEffect, useMemo, useState, type ComponentProps } from 'react'
import { Navigate, useLocation, useSearchParams } from 'react-router-dom'
import { DiagnosticsDrawer } from '../components/home/v010'
import PortfolioV002View from '../components/portfolio/v002/PortfolioV002View'
import { AuditSheet, PositionSheet, ProtectionWhySheet } from '../components/portfolio/v002/PortfolioSheets'
import {
  API, auditCategories, fmtAge, loadingRead, p0Items, positionsFrom, protectionModel, readOnce, statusRows,
  type HoldingsFilter, type HoldingsWire, type IncidentsWire, type ProtectionModel, type Read, type StatusRow,
} from '../lib/portfolioV002'

type DiagRecord = ComponentProps<typeof DiagnosticsDrawer>['records'][number]

const LEGACY_PARAMS = ['tab', 'drawer', 'drawerTab', 'sig', 'acct']

export function diagRecords(h: Read<HoldingsWire>, prot: ProtectionModel, status: StatusRow[], nowMs: number): DiagRecord[] {
  const st = (s: string): DiagRecord['status'] => (s === 'OK' || s === 'STALE' || s === 'UNKNOWN' || s === 'TIMED OUT' || s === 'WARN' ? s : 'UNKNOWN')
  const holdAge = h.at ? fmtAge(nowMs - Date.parse(h.at)) : '—'
  const recs: DiagRecord[] = [
    { widget: 'Holdings read', source: API.holdings, refreshRate: 'once per page load', age: holdAge, threshold: '30 s timeout',
      status: h.state === 'LOADING' ? 'UNKNOWN' : st(h.state), failureMode: 'TIMED OUT after 30 s; failed read = UNKNOWN, never empty-OK' },
  ]
  for (const b of prot.brokers) {
    recs.push({ widget: `Protection · ${b.broker}`, source: 'holdings protection_state (cio_truth.protection_for)', refreshRate: 'stop read lane',
      age: b.oldest ? fmtAge(nowMs - Date.parse(b.oldest)) : '—', threshold: 'backend demotes stale reads',
      status: b.state === 'OK' ? 'OK' : b.state === 'GAP' ? 'WARN' : b.state === 'WARN' ? 'WARN' : 'UNKNOWN',
      failureMode: `${b.protectedN} of ${b.counted} resting${b.cause ? ` · ${b.cause}` : ''} · UNKNOWN per row, never NO STOP` })
  }
  recs.push({ widget: 'Protection verdict', source: 'computed in page from row verdicts', refreshRate: 'per load', age: holdAge, threshold: '—',
    status: prot.verdict === 'OK' ? 'OK' : prot.verdict === 'GAP' || prot.verdict === 'WARN' ? 'WARN' : 'UNKNOWN',
    failureMode: 'served rollup /api/v2/portfolio/protection (G2) not deployed', needsBackend: true })
  for (const r of status) {
    recs.push({ widget: r.name, source: r.id === 'row-alerts' ? API.incidents : r.id === 'row-risk' ? 'none' : API.holdings,
      refreshRate: 'per load', age: '—', threshold: r.id === 'row-value' ? '60 m' : r.id === 'row-prices' ? '30 m' : r.id === 'row-alerts' ? '15 m' : '—',
      status: r.state === 'LOADING' ? 'UNKNOWN' : st(r.state), failureMode: r.text, needsBackend: r.needsBackend })
  }
  recs.push({ widget: 'Validation gates', source: 'none', refreshRate: '—', age: '—', threshold: '24 h', status: 'NOT AVAILABLE', failureMode: 'never "0 open"', needsBackend: true })
  recs.push({ widget: 'Since your last visit', source: 'none', refreshRate: '—', age: '—', threshold: '—', status: 'NOT AVAILABLE', failureMode: 'portfolio.last_seen (G13)', needsBackend: true })
  recs.push({ widget: 'Audit state lifecycle', source: 'none', refreshRate: '—', age: '—', threshold: '15 m', status: 'NOT AVAILABLE', failureMode: 'change store (LQ-2143)', needsBackend: true })
  recs.push({ widget: 'Fidelity GTC stop sync', source: 'retired (account closed)', refreshRate: '—', age: '—', threshold: '—', status: 'NOT AVAILABLE', failureMode: 'Retired for one release, then removed (R5)' })
  return recs
}

export default function PortfolioV002() {
  const [params] = useSearchParams()
  const location = useLocation()
  const legacy = LEGACY_PARAMS.some(k => params.has(k))
  const [holdings, setHoldings] = useState<Read<HoldingsWire>>(loadingRead<HoldingsWire>(API.holdings))
  const [incidents, setIncidents] = useState<Read<IncidentsWire>>(loadingRead<IncidentsWire>(API.incidents))
  const [nowIso, setNowIso] = useState(() => new Date().toISOString())
  const [filter, setFilter] = useState<HoldingsFilter>('all')
  const [account, setAccount] = useState('all')
  const [showAll, setShowAll] = useState(false)
  const [showAllAction, setShowAllAction] = useState(false)
  const [whyOpen, setWhyOpen] = useState(false)
  const [diagOpen, setDiagOpen] = useState(false)
  const [auditOpen, setAuditOpen] = useState(false)
  const [posKey, setPosKey] = useState<string | null>(null)

  useEffect(() => {
    if (legacy) return
    let alive = true
    void readOnce<HoldingsWire>(API.holdings).then(r => { if (alive) { setHoldings(r); setNowIso(new Date().toISOString()) } })
    void readOnce<IncidentsWire>(API.incidents).then(r => { if (alive) { setIncidents(r); setNowIso(new Date().toISOString()) } })
    return () => { alive = false }
  }, [legacy])

  const positions = useMemo(() => (holdings.state === 'OK' ? positionsFrom(holdings.data) : []), [holdings])
  const prot = useMemo(() => protectionModel(holdings, positions), [holdings, positions])
  const p0 = useMemo(() => p0Items(holdings, prot), [holdings, prot])
  const status = useMemo(() => statusRows(holdings, incidents, positions, Date.parse(nowIso)), [holdings, incidents, positions, nowIso])
  const audit = useMemo(() => auditCategories(prot, p0), [prot, p0])

  // ?symbol= deep link (Home, Research Intel) opens that position's sheet once the read lands.
  const wantSymbol = (params.get('symbol') || '').toUpperCase()
  useEffect(() => {
    if (!wantSymbol || positions.length === 0) return
    const hit = positions.find(p => p.symbol === wantSymbol)
    if (hit) setPosKey(hit.key)
  }, [wantSymbol, positions])

  const anyOpen = whyOpen || diagOpen || auditOpen || posKey != null
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

  if (legacy) return <Navigate to={`/portfolio-classic${location.search}`} replace />

  const pos = posKey ? positions.find(p => p.key === posKey) ?? null : null
  return (
    <>
      <PortfolioV002View holdings={holdings} positions={positions} prot={prot} p0={p0} status={status} nowIso={nowIso}
        filter={filter} account={account} showAll={showAll} showAllAction={showAllAction}
        onFilter={f => { setFilter(f); window.setTimeout(() => document.getElementById('card-holdings')?.scrollIntoView({ block: 'start' }), 0) }}
        onAccount={setAccount} onShowAll={() => setShowAll(true)} onShowAllAction={() => setShowAllAction(true)}
        onOpenWhy={() => setWhyOpen(true)} onOpenDiag={() => setDiagOpen(true)} onOpenAudit={() => setAuditOpen(true)}
        onOpenPosition={setPosKey} />
      <ProtectionWhySheet open={whyOpen} onClose={() => setWhyOpen(false)} prot={prot} nowIso={nowIso} onGoTo={goTo} />
      <PositionSheet pos={pos} onClose={() => setPosKey(null)} holdings={holdings.data} nowIso={nowIso} />
      <AuditSheet open={auditOpen} onClose={() => setAuditOpen(false)} categories={audit} readOk={holdings.state === 'OK'} />
      <DiagnosticsDrawer open={diagOpen} onClose={() => setDiagOpen(false)} records={diagRecords(holdings, prot, status, Date.parse(nowIso))}
        fetchedAt={holdings.at || undefined} />
    </>
  )
}
