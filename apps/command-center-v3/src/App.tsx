import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useConnectionHealth, signalApiRecover, retryApiConnection } from './hooks/useApi'
import MetricStrip from './components/MetricStrip'
import NavRail from './components/NavRail'
import DetailDrawer, { type DrillContext } from './components/DetailDrawer'
import StrategyHub from './pages/StrategyHub'
import RiskHub from './pages/RiskHub'
import HomeHub from './pages/HomeHub'
import PortfolioHub from './pages/PortfolioHub'
import TradingHub from './pages/TradingHub'
import AgentsHub from './pages/AgentsHub'
import IntelligenceHub from './pages/IntelligenceHub'
import HermesHub from './pages/HermesHub'
import RetirementHub from './pages/RetirementHub'
import JournalHub from './pages/JournalHub'
import WatchHub from './pages/WatchHub'
import ReportsHub from './pages/ReportsHub'
import SystemHub from './pages/SystemHub'
import RotationIntelligence from './pages/RotationIntelligence'
import RecommendationIntelligence from './pages/RecommendationIntelligence'
import ResearchIntelligenceHub from './pages/ResearchIntelligenceHub'
import RedeployDesk from './pages/RedeployDesk'
import HealthHub from './pages/HealthHub'
import ConsumptionHub from './pages/ConsumptionHub'


declare const __ANALYST_UI_VERSION__: string
declare const __BUILD_DATE__: string
// Real build stamp (vite define) — the old hardcoded label misled deploy verification.
const BUILD_MARKER_FALLBACK = `cc-v3 ${__ANALYST_UI_VERSION__} · built ${__BUILD_DATE__}`

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
  // v3.1 (WS-A): quiet chip, not a red alarm — the data on screen is good, only
  // the refresh is degraded. Stale-with-honest-timestamp is professional;
  // a flashing failure banner over valid data is not.
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

function Shell() {
  const [drill, setDrill] = useState<DrillContext | null>(null)
  return (
    <div className="app-shell cc-terminal-ui" style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--bg0)', color: 'var(--text0)' }}>
      <ReconnectingBar />
      <MetricStrip onDrill={setDrill} />
      <div className="app-body" style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'hidden' }}>
        <NavRail />
        <main className="app-main" style={{ flex: 1, minWidth: 0, minHeight: 0, overflowY: 'auto', padding: '16px 24px' }}>
          <Routes>
            <Route index element={<HomeHub onDrill={setDrill} />} />
            <Route path="portfolio" element={<PortfolioHub onDrill={setDrill} />} />
            <Route path="risk" element={<RiskHub onDrill={setDrill} />} />
            <Route path="trading" element={<TradingHub onDrill={setDrill} />} />
            <Route path="manual-execution" element={<Navigate to="/trading?tab=Entry+Desk" replace />} />
            <Route path="strategy" element={<StrategyHub onDrill={setDrill} />} />
            <Route path="agents" element={<AgentsHub onDrill={setDrill} />} />
            <Route path="intelligence" element={<IntelligenceHub onDrill={setDrill} />} />
            <Route path="research-intelligence" element={<ResearchIntelligenceHub onDrill={setDrill} />} />
            <Route path="research" element={<Navigate to="/research-intelligence" replace />} />
            <Route path="hermes" element={<HermesHub onDrill={setDrill} />} />
            <Route path="retirement" element={<RetirementHub onDrill={setDrill} />} />
            <Route path="journal" element={<JournalHub onDrill={setDrill} />} />
            <Route path="trade-in-view" element={<Navigate to="/journal" replace />} />
            <Route path="watch" element={<WatchHub onDrill={setDrill} />} />
            <Route path="watchlist" element={<Navigate to="/watch?tab=watchlist" replace />} />
            <Route path="watchpool" element={<Navigate to="/watch?tab=watchpool" replace />} />
            <Route path="sectors" element={<Navigate to="/watch?tab=sectors" replace />} />
            <Route path="pullback-macd" element={<Navigate to="/watch?tab=pullback-macd" replace />} />
            <Route path="reports" element={<ReportsHub onDrill={setDrill} />} />
            <Route path="rotation" element={<RotationIntelligence />} />
            <Route path="redeploy" element={<RedeployDesk />} />
            <Route path="advisor-changes" element={<Navigate to="/rotation?tab=advisor-guide" replace />} />
            <Route path="rec-intel" element={<RecommendationIntelligence />} />
            <Route path="health" element={<HealthHub onDrill={setDrill} />} />
            <Route path="consumption" element={<ConsumptionHub />} />
            <Route path="system" element={<SystemHub onDrill={setDrill} />} />
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