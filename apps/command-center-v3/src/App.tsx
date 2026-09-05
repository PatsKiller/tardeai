import { useEffect, useState } from 'react'
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
import ActiveTraderHub from './pages/ActiveTraderHub'
import AgentRuntimeHub from './pages/AgentRuntimeHub'
import IntelligenceHub from './pages/IntelligenceHub'
import HermesHub from './pages/HermesHub'
import RetirementHub from './pages/RetirementHub'
import JournalHub from './pages/JournalHub'
import WatchHub from './pages/WatchHub'
import SymbolIntelligencePage from './pages/SymbolIntelligencePage'
import WatchDiscovery from './pages/WatchDiscovery'
import WatchLegacy from './pages/WatchLegacy'
import DefenseHub from './pages/DefenseHub'
import ReportsHub from './pages/ReportsHub'
import SystemHub from './pages/SystemHub'
import RotationIntelligence from './pages/RotationIntelligence'
import RecommendationIntelligence from './pages/RecommendationIntelligence'
import ResearchIntelligenceHub from './pages/ResearchIntelligenceHub'
import RedeployDeskIntegrated from './pages/RedeployDeskIntegrated'
import HealthHub from './pages/HealthHub'
import CommunicationsHub from './pages/CommunicationsHub'
import ConsumptionHub from './pages/ConsumptionHub'
import SchwabReauthHub from './pages/SchwabReauthHub'
import SchwabReauthBanner from './components/SchwabReauthBanner'
import FinvizCookieBanner from './components/FinvizCookieBanner'
import AdvisoryDeskHub from './pages/AdvisoryDeskHub'
import CioHub from './pages/CioHub'
import {
  ControlPlaneHub,
  ControlPlaneSystemPage,
  AgentOfficePage,
  WorkflowTracePage,
  ResearchAttentionPage,
  DataIntegrityPage,
  IdentityPage,
  NotificationsPage,
  LearningPage,
  MaturityPage,
  AuditPage,
} from './pages/control-plane'
import SurfaceModeBanner from './components/truth/SurfaceModeBanner'
import RouteErrorBoundary from './components/truth/RouteErrorBoundary'


declare const __ANALYST_UI_VERSION__: string
declare const __BUILD_DATE__: string
const BUILD_MARKER_FALLBACK = `cc-v3 ${__ANALYST_UI_VERSION__} · built ${__BUILD_DATE__}`

function BuildMarker() {
  const [label, setLabel] = useState(BUILD_MARKER_FALLBACK)
  useEffect(() => {
    fetch('/v3/build-meta.json', { cache: 'no-store' })
      .then(r => r.json())
      .then(m => {
        const v = m?.ui_version || __ANALYST_UI_VERSION__
        const d = (m?.built_at || '').slice(0, 10) || __BUILD_DATE__
        // Build identity from the served artifact: the commit this bundle was
        // built from, never a fabricated or stale SHA (cc-header-truth-v2 Phase 2 G).
        const sha = m?.git_sha || m?.source_commit || m?.build_sha
        const shaPart = sha ? ` · ${String(sha).slice(0, 12)}` : ''
        setLabel(`cc-v3 ${v} · built ${d}${shaPart}`)
      })
      .catch(() => { /* keep fallback — build-time defines of the served bundle */ })
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

function Shell() {
  const [drill, setDrill] = useState<DrillContext | null>(null)
  return (
    <div className="app-shell cc-terminal-ui" style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--bg0)', color: 'var(--text0)' }}>
      <SchwabReauthBanner />
      <FinvizCookieBanner />
      <ReconnectingBar />
      <MetricStrip onDrill={setDrill} />
      <div className="app-body" style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'hidden' }}>
        <NavRail />
        <main className="app-main" style={{ flex: 1, minWidth: 0, minHeight: 0, overflowY: 'auto', padding: '16px 24px' }}>
          <SharedIntelligenceBridge />
          <Routes>
            <Route index element={<RouteErrorBoundary route="/v3/"><HomeHub onDrill={setDrill} /></RouteErrorBoundary>} />
            <Route path="portfolio" element={<RouteErrorBoundary route="/v3/portfolio"><PortfolioHub onDrill={setDrill} /></RouteErrorBoundary>} />
            <Route path="portfolio/re-entry" element={<RouteErrorBoundary route="/v3/portfolio/re-entry"><ReEntryPage /></RouteErrorBoundary>} />
            <Route path="risk" element={<RouteErrorBoundary route="/v3/risk"><RiskHub onDrill={setDrill} /></RouteErrorBoundary>} />
            <Route path="trading" element={<RouteErrorBoundary route="/v3/trading"><TradingHub onDrill={setDrill} /></RouteErrorBoundary>} />
            <Route path="active-trader" element={<RouteErrorBoundary route="/v3/active-trader"><ActiveTraderHub /></RouteErrorBoundary>} />
            <Route path="trading/active-trader" element={<RouteErrorBoundary route="/v3/trading/active-trader"><Navigate to="/active-trader" replace /></RouteErrorBoundary>} />
            <Route path="go/order/:intentId" element={<RouteErrorBoundary route="/v3/go/order/:intentId"><GoOrderDeepLink /></RouteErrorBoundary>} />
            <Route path="go/proposal/:proposalId" element={<RouteErrorBoundary route="/v3/go/proposal/:proposalId"><GoProposalDeepLink /></RouteErrorBoundary>} />
            <Route path="manual-execution" element={<RouteErrorBoundary route="/v3/manual-execution"><Navigate to="/trading?tab=Entry+Desk" replace /></RouteErrorBoundary>} />
            <Route path="strategy" element={<RouteErrorBoundary route="/v3/strategy"><StrategyHub onDrill={setDrill} /></RouteErrorBoundary>} />
            <Route path="agents" element={<RouteErrorBoundary route="/v3/agents"><AgentRuntimeHub onDrill={setDrill} /></RouteErrorBoundary>} />
            <Route path="intelligence" element={<RouteErrorBoundary route="/v3/intelligence"><IntelligenceHub onDrill={setDrill} /></RouteErrorBoundary>} />
            <Route path="closed-loop" element={<RouteErrorBoundary route="/v3/closed-loop"><Navigate to="/intelligence?tab=closed-loop" replace /></RouteErrorBoundary>} />
            <Route path="research-intelligence" element={<RouteErrorBoundary route="/v3/research-intelligence"><ResearchIntelligenceHub onDrill={setDrill} /></RouteErrorBoundary>} />
            <Route path="research" element={<RouteErrorBoundary route="/v3/research"><Navigate to="/research-intelligence" replace /></RouteErrorBoundary>} />
            <Route path="hermes" element={<RouteErrorBoundary route="/v3/hermes"><HermesHub onDrill={setDrill} /></RouteErrorBoundary>} />
            <Route path="retirement" element={<RouteErrorBoundary route="/v3/retirement"><RetirementHub onDrill={setDrill} /></RouteErrorBoundary>} />
            <Route path="journal" element={<RouteErrorBoundary route="/v3/journal"><JournalHub onDrill={setDrill} /></RouteErrorBoundary>} />
            <Route path="trade-in-view" element={<RouteErrorBoundary route="/v3/trade-in-view"><Navigate to="/journal" replace /></RouteErrorBoundary>} />
            <Route path="watch" element={<RouteErrorBoundary route="/v3/watch"><WatchHub onDrill={setDrill} /></RouteErrorBoundary>} />
            <Route path="watch/intelligence/:symbol" element={<RouteErrorBoundary route="/v3/watch/intelligence/:symbol"><SymbolIntelligencePage /></RouteErrorBoundary>} />
            <Route path="watch/discovery" element={<RouteErrorBoundary route="/v3/watch/discovery"><WatchDiscovery onDrill={setDrill} /></RouteErrorBoundary>} />
            <Route path="watch-legacy" element={<RouteErrorBoundary route="/v3/watch-legacy"><WatchLegacy onDrill={setDrill} /></RouteErrorBoundary>} />
            <Route path="defense" element={<RouteErrorBoundary route="/v3/defense"><DefenseHub /></RouteErrorBoundary>} />
            {/* Legacy watchlist/screener nav → primary Intelligence (not the old card wall) */}
            <Route path="watchlist" element={<RouteErrorBoundary route="/v3/watchlist"><Navigate to="/watch?tab=intelligence&view=top_ideas" replace /></RouteErrorBoundary>} />
            <Route path="watchpool" element={<RouteErrorBoundary route="/v3/watchpool"><Navigate to="/watch?tab=watchpool" replace /></RouteErrorBoundary>} />
            <Route path="sectors" element={<RouteErrorBoundary route="/v3/sectors"><Navigate to="/watch?tab=sectors" replace /></RouteErrorBoundary>} />
            <Route path="pullback-macd" element={<RouteErrorBoundary route="/v3/pullback-macd"><Navigate to="/watch?tab=pullback-macd" replace /></RouteErrorBoundary>} />
            <Route path="reports" element={<RouteErrorBoundary route="/v3/reports"><ReportsHub onDrill={setDrill} /></RouteErrorBoundary>} />
            <Route path="rotation" element={<RouteErrorBoundary route="/v3/rotation"><RotationIntelligence /></RouteErrorBoundary>} />
            <Route path="redeploy" element={<RouteErrorBoundary route="/v3/redeploy"><RedeployDeskIntegrated /></RouteErrorBoundary>} />
            <Route path="advisor-changes" element={<RouteErrorBoundary route="/v3/advisor-changes"><Navigate to="/rotation?tab=advisor-guide" replace /></RouteErrorBoundary>} />
            <Route path="rec-intel" element={<RouteErrorBoundary route="/v3/rec-intel"><RecommendationIntelligence /></RouteErrorBoundary>} />
            <Route path="advisory" element={<RouteErrorBoundary route="/v3/advisory"><AdvisoryDeskHub onDrill={setDrill} /></RouteErrorBoundary>} />
            <Route path="cio" element={<RouteErrorBoundary route="/v3/cio"><CioHub onDrill={setDrill} /></RouteErrorBoundary>} />
            <Route path="health" element={<RouteErrorBoundary route="/v3/health"><HealthHub onDrill={setDrill} /></RouteErrorBoundary>} />
            <Route path="communications" element={<RouteErrorBoundary route="/v3/communications"><CommunicationsHub /></RouteErrorBoundary>} />
            <Route path="consumption" element={<RouteErrorBoundary route="/v3/consumption"><ConsumptionHub /></RouteErrorBoundary>} />
            <Route path="system" element={<RouteErrorBoundary route="/v3/system"><SystemHub onDrill={setDrill} /></RouteErrorBoundary>} />
            <Route path="system/schwab-reauth" element={<RouteErrorBoundary route="/v3/system/schwab-reauth"><SchwabReauthHub /></RouteErrorBoundary>} />
            {/* Shadow control-plane namespace. Does not replace live routes. */}
            <Route path="control-plane" element={<RouteErrorBoundary route="/v3/control-plane"><><SurfaceModeBanner route="/v3/control-plane" /><ControlPlaneHub /></></RouteErrorBoundary>} />
            <Route path="control-plane/system" element={<RouteErrorBoundary route="/v3/control-plane/system"><><SurfaceModeBanner route="/v3/control-plane/system" /><ControlPlaneSystemPage /></></RouteErrorBoundary>} />
            <Route path="control-plane/agents" element={<RouteErrorBoundary route="/v3/control-plane/agents"><><SurfaceModeBanner route="/v3/control-plane/agents" /><AgentOfficePage /></></RouteErrorBoundary>} />
            <Route path="control-plane/workflows" element={<RouteErrorBoundary route="/v3/control-plane/workflows"><><SurfaceModeBanner route="/v3/control-plane/workflows" /><WorkflowTracePage /></></RouteErrorBoundary>} />
            <Route path="control-plane/research" element={<RouteErrorBoundary route="/v3/control-plane/research"><><SurfaceModeBanner route="/v3/control-plane/research" /><ResearchAttentionPage /></></RouteErrorBoundary>} />
            <Route path="control-plane/data" element={<RouteErrorBoundary route="/v3/control-plane/data"><><SurfaceModeBanner route="/v3/control-plane/data" /><DataIntegrityPage /></></RouteErrorBoundary>} />
            <Route path="control-plane/identity" element={<RouteErrorBoundary route="/v3/control-plane/identity"><><SurfaceModeBanner route="/v3/control-plane/identity" /><IdentityPage /></></RouteErrorBoundary>} />
            <Route path="control-plane/notifications" element={<RouteErrorBoundary route="/v3/control-plane/notifications"><><SurfaceModeBanner route="/v3/control-plane/notifications" /><NotificationsPage /></></RouteErrorBoundary>} />
            <Route path="control-plane/learning" element={<RouteErrorBoundary route="/v3/control-plane/learning"><><SurfaceModeBanner route="/v3/control-plane/learning" /><LearningPage /></></RouteErrorBoundary>} />
            <Route path="control-plane/maturity" element={<RouteErrorBoundary route="/v3/control-plane/maturity"><><SurfaceModeBanner route="/v3/control-plane/maturity" /><MaturityPage /></></RouteErrorBoundary>} />
            <Route path="control-plane/audit" element={<RouteErrorBoundary route="/v3/control-plane/audit"><><SurfaceModeBanner route="/v3/control-plane/audit" /><AuditPage /></></RouteErrorBoundary>} />
          </Routes>
          <div style={{ marginTop: 18, paddingTop: 8, borderTop: '1px solid rgba(148,163,184,.16)', fontSize: 11, color: 'var(--text3)' }}>
            <BuildMarker />
          </div>
        </main>
      </div>
      <DetailDrawer ctx={drill} onClose={() => setDrill(null)} />
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
