import React, { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Shell from './components/Shell'

const Overview = lazy(() => import('./pages/Overview'))
const TradeAI = lazy(() => import('./pages/TradeAI'))
const Portfolio = lazy(() => import('./pages/Portfolio'))
const Journal = lazy(() => import('./pages/Journal'))
const Returns = lazy(() => import('./pages/Returns'))
const Technical = lazy(() => import('./pages/Technical'))
const Risk = lazy(() => import('./pages/Risk'))
const TaxLots = lazy(() => import('./pages/TaxLots'))
const Correlation = lazy(() => import('./pages/Correlation'))
const Rebalance = lazy(() => import('./pages/Rebalance'))
const Dividends = lazy(() => import('./pages/Dividends'))
const Retirement = lazy(() => import('./pages/Retirement'))
const Attribution = lazy(() => import('./pages/Attribution'))
const Forecast = lazy(() => import('./pages/Forecast'))
const Research = lazy(() => import('./pages/Research'))
const Notifications = lazy(() => import('./pages/Notifications'))
const AlertsActions = lazy(() => import('./pages/AlertsActions'))
const Watchlist = lazy(() => import('./pages/Watchlist'))
const CIODashboard = lazy(() => import('./pages/CIODashboard'))
const SystemHealth = lazy(() => import('./pages/SystemHealth'))
const SystemHub = lazy(() => import('./pages/SystemHub'))
const Approvals = lazy(() => import('./pages/Approvals'))
const Reports = lazy(() => import('./pages/Reports'))
const Ops = lazy(() => import('./pages/Ops'))
const StoppedOutWatch = lazy(() => import('./pages/StoppedOutWatch'))
const JournalAnalytics = lazy(() => import('./pages/JournalAnalytics'))
const Orchestration = lazy(() => import('./pages/Orchestration'))
const ActionCenter = lazy(() => import('./pages/ActionCenter'))
const MorningBrief = lazy(() => import('./pages/MorningBrief'))
const AIAnalyst = lazy(() => import('./pages/AIAnalyst'))
const IntelligenceSources = lazy(() => import('./pages/IntelligenceSources'))
const PortfolioIntelligence = lazy(() => import('./pages/PortfolioIntelligence'))
const ContentHealth = lazy(() => import('./pages/ContentHealth'))

function Loading() {
  return <div style={{ color: 'var(--text3)', padding: 20 }}>Loading...</div>
}

function SafePage({ children }: { children: React.ReactNode }) {
  return <ErrorBoundary><Suspense fallback={<Loading />}>{children}</Suspense></ErrorBoundary>
}

class ErrorBoundary extends React.Component<{ children: React.ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }
  static getDerivedStateFromError(error: Error) { return { error } }
  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 20 }}>
          <div style={{ padding: '12px 16px', background: 'rgba(246,70,93,.08)', border: '1px solid #f6465d', borderRadius: 6, maxWidth: 600 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#f6465d', marginBottom: 6 }}>Page render error</div>
            <div style={{ fontSize: 11, color: '#c4cdd8', lineHeight: 1.5, marginBottom: 8 }}>{this.state.error.message}</div>
            <button onClick={() => this.setState({ error: null })} style={{ fontSize: 10, padding: '4px 12px', border: '1px solid #4a90f4', borderRadius: 4, background: 'rgba(74,144,244,.1)', color: '#4a90f4', cursor: 'pointer' }}>Try Again</button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

export default function App() {
  return (
    <BrowserRouter basename="/v2">
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<SafePage><Overview /></SafePage>} />
          <Route path="trade-ai" element={<SafePage><TradeAI /></SafePage>} />
          <Route path="portfolio" element={<SafePage><Portfolio /></SafePage>} />
          <Route path="portfolio-intelligence" element={<SafePage><PortfolioIntelligence /></SafePage>} />
          <Route path="journal" element={<SafePage><Journal /></SafePage>} />
          <Route path="returns" element={<SafePage><Returns /></SafePage>} />
          <Route path="technical" element={<SafePage><Technical /></SafePage>} />
          <Route path="risk" element={<SafePage><Risk /></SafePage>} />
          <Route path="tax" element={<SafePage><TaxLots /></SafePage>} />
          <Route path="correlation" element={<SafePage><Correlation /></SafePage>} />
          <Route path="rebalance" element={<SafePage><Rebalance /></SafePage>} />
          <Route path="dividends" element={<SafePage><Dividends /></SafePage>} />
          <Route path="retirement" element={<SafePage><Retirement /></SafePage>} />
          <Route path="attribution" element={<SafePage><Attribution /></SafePage>} />
          <Route path="forecast" element={<SafePage><Forecast /></SafePage>} />
          <Route path="research" element={<SafePage><Research /></SafePage>} />
          <Route path="alerts" element={<SafePage><AlertsActions /></SafePage>} />
          <Route path="notifications" element={<SafePage><Notifications /></SafePage>} />
          <Route path="watchlist" element={<SafePage><Watchlist /></SafePage>} />
          <Route path="cio" element={<SafePage><CIODashboard /></SafePage>} />
          <Route path="system-health" element={<SafePage><SystemHealth /></SafePage>} />
          <Route path="hub" element={<SafePage><SystemHub /></SafePage>} />
          <Route path="approvals" element={<SafePage><Approvals /></SafePage>} />
          <Route path="reports" element={<SafePage><Reports /></SafePage>} />
          <Route path="ops" element={<SafePage><Ops /></SafePage>} />
          <Route path="recovery" element={<SafePage><StoppedOutWatch /></SafePage>} />
          <Route path="journal-analytics" element={<SafePage><JournalAnalytics /></SafePage>} />
          <Route path="orchestration" element={<SafePage><Orchestration /></SafePage>} />
          <Route path="actions" element={<SafePage><ActionCenter /></SafePage>} />
          <Route path="morning-brief" element={<SafePage><MorningBrief /></SafePage>} />
          <Route path="ai-analyst" element={<SafePage><AIAnalyst /></SafePage>} />
          <Route path="intelligence-sources" element={<SafePage><IntelligenceSources /></SafePage>} />
          <Route path="content-health" element={<SafePage><ContentHealth /></SafePage>} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
