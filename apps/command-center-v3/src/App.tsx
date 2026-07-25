import { useCallback, useEffect, useRef, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useParams, useSearchParams } from 'react-router-dom'
import { useConnectionHealth, signalApiRecover, retryApiConnection } from './hooks/useApi'
import MetricStrip from './components/MetricStrip'
import NavRail from './components/NavRail'
import DetailDrawer, { type DrillContext } from './components/DetailDrawer'
import SharedIntelligenceBridge from './components/SharedIntelligenceBridge'
import StrategyHub from './pages/StrategyHub'
import RiskHub from './pages/RiskHub'
import HomeHub from './pages/HomeHub'
import PortfolioHub from './pages/PortfolioHub'
import ReEntryPage from './pages/ReEntryPage'
import TradingHub from './pages/TradingHub'
import AgentsHub from './pages/AgentsHub'
import IntelligenceHub from './pages/IntelligenceHub'
import HermesHub from './pages/HermesHub'
import RetirementHub from './pages/RetirementHub'
import JournalHub from './pages/JournalHub'
import WatchHub from './pages/WatchHub'
import DefenseHub from './pages/DefenseHub'
import ReportsHub from './pages/ReportsHub'
import SystemHub from './pages/SystemHub'
import RotationIntelligence from './pages/RotationIntelligence'
import RecommendationIntelligence from './pages/RecommendationIntelligence'
import ResearchIntelligenceHub from './pages/ResearchIntelligenceHub'
import RedeployDeskIntegrated from './pages/RedeployDeskIntegrated'
import HealthHub from './pages/HealthHub'
import ConsumptionHub from './pages/ConsumptionHub'


declare const __ANALYST_UI_VERSION__: string
declare const __BUILD_DATE__: string
const BUILD_MARKER_FALLBACK = `cc-v3 ${__ANALYST_UI_VERSION__} · built ${__BUILD_DATE__}`
const GLOBAL_REVIEW_CONTRACT = 'command-center-global-review-v1'

function BuildMarker() {
  const [label, setLabel] = useState(BUILD_MARKER_FALLBACK)
  useEffect(() => {
    fetch('/v3/build-meta.json', { cache: 'no-store' })
      .then(r => r.json())
      .then(m => {
        const v = m?.ui_version || __ANALYST_UI_VERSION__
        const d = (m?.built_at || '').slice(0, 10) || __BUILD_DATE__
        setLabel(`cc-v3 ${v} · built ${d}`)
      })
      .catch(() => { /* keep fallback */ })
  }, [])
  return <span>Build: {label}</span>
}

function ReconnectingBar() {
  const { degraded, failing } = useConnectionHealth()

  useEffect(() => {
    if (!degraded) return
    let cancelled = false
    let okStreak = 0
    const probe = async () => {
      const controller = new AbortController()
      const timer = setTimeout(() => controller.abort(), 5000)
      try {
        const r = await fetch('/api/health', { cache: 'no-store', signal: controller.signal })
        clearTimeout(timer)
        if (cancelled) return
        if (r.ok) {
          okStreak += 1
          if (okStreak >= 2) signalApiRecover()
        } else {
          okStreak = 0
        }
      } catch {
        clearTimeout(timer)
        if (!cancelled) okStreak = 0
      }
    }
    probe()
    const id = window.setInterval(probe, 3000)
    return () => { cancelled = true; window.clearInterval(id) }
  }, [degraded])

  if (!degraded) return null
  return (
    <div style={{
      background: 'rgba(245,158,11,0.10)', color: '#f5c76a', borderBottom: '1px solid rgba(245,158,11,0.28)',
      fontSize: 10.5, fontWeight: 650, textAlign: 'center', padding: '2px 8px', letterSpacing: .2,
    }}>
      showing last-good data · live refresh paused (server busy{failing > 1 ? ` · ${failing} feeds` : ''}) · retrying with backoff
      {' · '}
      <button
        type="button"
        onClick={() => { void retryApiConnection() }}
        style={{ background: 'transparent', border: 'none', color: '#f5c76a', fontWeight: 750, fontSize: 10.5, cursor: 'pointer', textDecoration: 'underline', padding: 0 }}
      >
        retry now
      </button>
    </div>
  )
}

function GoOrderDeepLink() {
  const { intentId } = useParams()
  const id = (intentId || '').trim()
  useEffect(() => {
    if (!id) return
    try { sessionStorage.setItem('cc_deep_intent', id) } catch { /* private mode */ }
    const target = `/v3/trading?tab=${encodeURIComponent('Broker Orders')}&intent=${encodeURIComponent(id)}`
    const t = window.setTimeout(() => {
      if (!window.location.search.includes('intent=')) {
        window.location.replace(target)
      }
    }, 400)
    return () => window.clearTimeout(t)
  }, [id])
  if (!id) return <Navigate to="/trading?tab=Broker%20Orders" replace />
  return <Navigate to={`/trading?tab=${encodeURIComponent('Broker Orders')}&intent=${encodeURIComponent(id)}`} replace />
}

function GoProposalDeepLink() {
  const { proposalId } = useParams()
  const [sp] = useSearchParams()
  const sym = sp.get('symbol')
  const id = (proposalId || '').trim()
  useEffect(() => {
    if (!id) return
    try { sessionStorage.setItem('cc_deep_proposal', id) } catch { /* private mode */ }
  }, [id])
  if (!id) return <Navigate to="/trading?tab=Proposals" replace />
  const q = sym
    ? `/trading?tab=Proposals&proposal=${encodeURIComponent(id)}&symbol=${encodeURIComponent(sym)}`
    : `/trading?tab=Proposals&proposal=${encodeURIComponent(id)}`
  return <Navigate to={q} replace />
}

function normalizeSymbol(value?: string | null): string {
  const symbol = String(value || '').trim().toUpperCase()
  return /^[A-Z0-9.-]{1,10}$/.test(symbol) ? symbol : ''
}

function drillSymbol(ctx: DrillContext | null): string {
  if (!ctx) return ''
  const row = ctx.rows?.[0] ?? {}
  const candidate = row.symbol || ctx.subjectKey || String(ctx.title || '').match(/^[A-Z0-9.-]{1,10}\b/)?.[0]
  return normalizeSymbol(candidate)
}

function Shell() {
  const [drill, setDrill] = useState<DrillContext | null>(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const reviewWasRequested = useRef(false)
  const requestedSymbol = normalizeSymbol(searchParams.get('symbol'))
  const reviewRequested = searchParams.get('review') === '1' || searchParams.get('modal') === 'review'
  const activeDrillSymbol = drillSymbol(drill)

  const openDrill = useCallback((ctx: DrillContext) => {
    setDrill(ctx)
    const symbol = drillSymbol(ctx)
    if (!symbol) return
    const next = new URLSearchParams(searchParams)
    next.set('symbol', symbol)
    next.set('review', '1')
    next.set('modal', 'review')
    setSearchParams(next)
  }, [searchParams, setSearchParams])

  const closeDrill = useCallback(() => {
    setDrill(null)
    if (!reviewRequested && !searchParams.has('modal')) return
    const next = new URLSearchParams(searchParams)
    next.delete('review')
    next.delete('modal')
    next.delete('symbol')
    setSearchParams(next, { replace: true })
  }, [reviewRequested, searchParams, setSearchParams])

  useEffect(() => {
    if (reviewRequested) {
      reviewWasRequested.current = true
      return
    }
    if (reviewWasRequested.current) {
      reviewWasRequested.current = false
      setDrill(null)
    }
  }, [reviewRequested])

  useEffect(() => {
    if (!reviewRequested || !requestedSymbol || activeDrillSymbol === requestedSymbol) return
    let cancelled = false
    const load = async () => {
      let row: Record<string, any> = { symbol: requestedSymbol }
      try {
        const response = await fetch(`/api/v2/watchlist/items?symbol=${encodeURIComponent(requestedSymbol)}`, { cache: 'no-store' })
        const payload = await response.json().catch(() => ({}))
        const inner = payload?.data ?? payload
        row = inner?.items?.[0] ?? row
      } catch { /* the modal still opens with symbol-level evidence */ }
      if (cancelled) return
      setDrill({
        title: `${requestedSymbol} operator review`,
        subtitle: 'URL-addressable decision, provenance and evidence review',
        endpoint: `/api/v2/watch/provenance/${requestedSymbol}`,
        rows: [row],
        links: [
          { label: 'Watchlist', href: `/v3/watch?tab=watchlist&symbol=${encodeURIComponent(requestedSymbol)}`, note: 'Return to the Watchlist workspace' },
          { label: 'Rotation review', href: `/v3/rotation?question=${encodeURIComponent(`Review whether ${requestedSymbol} exposure should change`)}`, note: 'Advisory review only' },
        ],
        subjectType: 'symbol',
        subjectKey: requestedSymbol,
      })
    }
    void load()
    return () => { cancelled = true }
  }, [activeDrillSymbol, requestedSymbol, reviewRequested])

  useEffect(() => {
    if (!drill) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeDrill()
    }
    window.addEventListener('keydown', handleKey)
    return () => {
      window.removeEventListener('keydown', handleKey)
      document.body.style.overflow = previousOverflow
    }
  }, [closeDrill, drill])

  return (
    <div className="app-shell cc-terminal-ui" data-review-contract={GLOBAL_REVIEW_CONTRACT} style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--bg0)', color: 'var(--text0)' }}>
      <ReconnectingBar />
      <MetricStrip onDrill={openDrill} />
      <div className="app-body" style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'hidden' }}>
        <NavRail />
        <main className="app-main" style={{ flex: 1, minWidth: 0, minHeight: 0, overflowY: 'auto', padding: '16px 24px' }}>
          <SharedIntelligenceBridge />
          <Routes>
            <Route index element={<HomeHub onDrill={openDrill} />} />
            <Route path="portfolio" element={<PortfolioHub onDrill={openDrill} />} />
            <Route path="portfolio/re-entry" element={<ReEntryPage />} />
            <Route path="risk" element={<RiskHub onDrill={openDrill} />} />
            <Route path="trading" element={<TradingHub onDrill={openDrill} />} />
            <Route path="go/order/:intentId" element={<GoOrderDeepLink />} />
            <Route path="go/proposal/:proposalId" element={<GoProposalDeepLink />} />
            <Route path="manual-execution" element={<Navigate to="/trading?tab=Entry+Desk" replace />} />
            <Route path="strategy" element={<StrategyHub onDrill={openDrill} />} />
            <Route path="agents" element={<AgentsHub onDrill={openDrill} />} />
            <Route path="intelligence" element={<IntelligenceHub onDrill={openDrill} />} />
            <Route path="research-intelligence" element={<ResearchIntelligenceHub onDrill={openDrill} />} />
            <Route path="research" element={<Navigate to="/research-intelligence" replace />} />
            <Route path="hermes" element={<HermesHub onDrill={openDrill} />} />
            <Route path="retirement" element={<RetirementHub onDrill={openDrill} />} />
            <Route path="journal" element={<JournalHub onDrill={openDrill} />} />
            <Route path="trade-in-view" element={<Navigate to="/journal" replace />} />
            <Route path="watch" element={<WatchHub onDrill={openDrill} />} />
            <Route path="defense" element={<DefenseHub />} />
            <Route path="watchlist" element={<Navigate to="/watch?tab=watchlist" replace />} />
            <Route path="watchpool" element={<Navigate to="/watch?tab=watchpool" replace />} />
            <Route path="sectors" element={<Navigate to="/watch?tab=sectors" replace />} />
            <Route path="pullback-macd" element={<Navigate to="/watch?tab=pullback-macd" replace />} />
            <Route path="reports" element={<ReportsHub onDrill={openDrill} />} />
            <Route path="rotation" element={<RotationIntelligence />} />
            <Route path="redeploy" element={<RedeployDeskIntegrated />} />
            <Route path="advisor-changes" element={<Navigate to="/rotation?tab=advisor-guide" replace />} />
            <Route path="rec-intel" element={<RecommendationIntelligence />} />
            <Route path="health" element={<HealthHub onDrill={openDrill} />} />
            <Route path="consumption" element={<ConsumptionHub />} />
            <Route path="system" element={<SystemHub onDrill={openDrill} />} />
          </Routes>
          <div style={{ marginTop: 18, paddingTop: 8, borderTop: '1px solid rgba(148,163,184,.16)', fontSize: 11, color: 'var(--text3)' }}>
            <BuildMarker />
          </div>
        </main>
      </div>
      {drill && (
        <div role="dialog" aria-modal="true" aria-label={drill.title} data-command-center-modal="review">
          <DetailDrawer ctx={drill} onClose={closeDrill} />
        </div>
      )}
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter basename="/v3">
      <Routes>
        <Route path="/*" element={<Shell />} />
      </Routes>
    </BrowserRouter>
  )
}
