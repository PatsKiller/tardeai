import { useState } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { useConnectionHealth } from './hooks/useApi'
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
import WatchlistHub from './pages/WatchlistHub'
import WatchpoolHub from './pages/WatchpoolHub'
import PullbackMacdHub from './pages/PullbackMacdHub'
import SectorsHub from './pages/SectorsHub'
import ReportsHub from './pages/ReportsHub'
import SystemHub from './pages/SystemHub'
import ManualExecutionHub from './pages/ManualExecutionHub'
import RotationIntelligence from './pages/RotationIntelligence'
import RecommendationIntelligence from './pages/RecommendationIntelligence'
import AdvisorChangesHub from './pages/AdvisorChangesHub'
import HealthHub from './pages/HealthHub'

const BUILD_MARKER = 'cc-v3 stop-mgmt-v3 2026-06-30'

function ReconnectingBar() {
  const { degraded, failing } = useConnectionHealth()
  if (!degraded) return null
  return (
    <div style={{ background: '#f59e0b', color: '#1a1207', fontSize: 11, fontWeight: 800, textAlign: 'center', padding: '3px 8px', letterSpacing: .3 }}>
      ⟳ Reconnecting to backend… showing last-known data{failing > 1 ? ` · ${failing} feeds` : ''}
    </div>
  )
}

function Shell() {
  const [drill, setDrill] = useState<DrillContext | null>(null)

  return (
    <div className="app-shell" style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--bg0)', color: 'var(--text0)' }}>
      <ReconnectingBar />
      <MetricStrip onDrill={setDrill} />
      <div className="app-body" style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <NavRail />
        <main className="app-main" style={{ flex: 1, overflowY: 'auto', padding: '16px 24px' }}>
          <Routes>
            <Route index element={<HomeHub onDrill={setDrill} />} />
            <Route path="portfolio" element={<PortfolioHub onDrill={setDrill} />} />
            <Route path="risk" element={<RiskHub onDrill={setDrill} />} />
            <Route path="trading" element={<TradingHub onDrill={setDrill} />} />
            <Route path="manual-execution" element={<ManualExecutionHub />} />
            <Route path="strategy" element={<StrategyHub onDrill={setDrill} />} />
            <Route path="agents" element={<AgentsHub onDrill={setDrill} />} />
            <Route path="intelligence" element={<IntelligenceHub onDrill={setDrill} />} />
            <Route path="hermes" element={<HermesHub onDrill={setDrill} />} />
            <Route path="retirement" element={<RetirementHub onDrill={setDrill} />} />
            <Route path="journal" element={<JournalHub onDrill={setDrill} />} />
            <Route path="trade-in-view" element={<JournalHub onDrill={setDrill} />} />
            <Route path="watchlist" element={<WatchlistHub onDrill={setDrill} />} />
            <Route path="watchpool" element={<WatchpoolHub onDrill={setDrill} />} />
            <Route path="pullback-macd" element={<PullbackMacdHub onDrill={setDrill} />} />
            <Route path="sectors" element={<SectorsHub onDrill={setDrill} />} />
            <Route path="reports" element={<ReportsHub onDrill={setDrill} />} />
            <Route path="rotation" element={<RotationIntelligence />} />
            <Route path="rec-intel" element={<RecommendationIntelligence />} />
            <Route path="advisor-changes" element={<AdvisorChangesHub />} />
            <Route path="health" element={<HealthHub onDrill={setDrill} />} />
            <Route path="system" element={<SystemHub onDrill={setDrill} />} />
          </Routes>
          <div style={{ marginTop: 18, paddingTop: 8, borderTop: '1px solid rgba(148,163,184,.16)', fontSize: 11, color: 'var(--text3)' }}>
            Build: {BUILD_MARKER}
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
