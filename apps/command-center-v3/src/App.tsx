import { useState } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import MetricStrip from './components/MetricStrip'
import NavRail from './components/NavRail'
import DetailDrawer, { type DrillContext } from './components/DetailDrawer'
import HubPlaceholder from './components/HubPlaceholder'
import StrategyHub from './pages/StrategyHub'
import RiskHub from './pages/RiskHub'

function Shell() {
  const [drill, setDrill] = useState<DrillContext | null>(null)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--bg0)', color: 'var(--text0)' }}>
      <MetricStrip onDrill={setDrill} />
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <NavRail />
        <main style={{ flex: 1, overflowY: 'auto', padding: '16px 24px' }}>
          <Routes>
            <Route index element={<HubPlaceholder name="Home" />} />
            <Route path="portfolio" element={<HubPlaceholder name="Portfolio" />} />
            <Route path="risk" element={<RiskHub onDrill={setDrill} />} />
            <Route path="trading" element={<HubPlaceholder name="Trading" />} />
            <Route path="strategy" element={<StrategyHub onDrill={setDrill} />} />
            <Route path="agents" element={<HubPlaceholder name="Agents" />} />
            <Route path="intelligence" element={<HubPlaceholder name="Intelligence" />} />
            <Route path="hermes" element={<HubPlaceholder name="Hermes" />} />
            <Route path="retirement" element={<HubPlaceholder name="Retirement" />} />
            <Route path="journal" element={<HubPlaceholder name="Journal" />} />
            <Route path="system" element={<HubPlaceholder name="System" />} />
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
