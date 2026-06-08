import { useState } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import MetricStrip from './components/MetricStrip'
import NavRail from './components/NavRail'
import DetailDrawer, { type DrillContext } from './components/DetailDrawer'
import HubPlaceholder from './components/HubPlaceholder'
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
import SystemHub from './pages/SystemHub'

function Shell() {
  const [drill, setDrill] = useState<DrillContext | null>(null)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--bg0)', color: 'var(--text0)' }}>
      <MetricStrip onDrill={setDrill} />
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <NavRail />
        <main style={{ flex: 1, overflowY: 'auto', padding: '16px 24px' }}>
          <Routes>
            <Route index element={<HomeHub onDrill={setDrill} />} />
            <Route path="portfolio" element={<PortfolioHub onDrill={setDrill} />} />
            <Route path="risk" element={<RiskHub onDrill={setDrill} />} />
            <Route path="trading" element={<TradingHub onDrill={setDrill} />} />
            <Route path="strategy" element={<StrategyHub onDrill={setDrill} />} />
            <Route path="agents" element={<AgentsHub onDrill={setDrill} />} />
            <Route path="intelligence" element={<IntelligenceHub onDrill={setDrill} />} />
            <Route path="hermes" element={<HermesHub onDrill={setDrill} />} />
            <Route path="retirement" element={<RetirementHub onDrill={setDrill} />} />
            <Route path="journal" element={<JournalHub onDrill={setDrill} />} />
            <Route path="watchlist" element={<WatchlistHub onDrill={setDrill} />} />
            <Route path="watchpool" element={<WatchpoolHub onDrill={setDrill} />} />
            <Route path="system" element={<SystemHub onDrill={setDrill} />} />
          </Routes>
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
