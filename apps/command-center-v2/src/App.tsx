import React, { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Shell from './components/Shell'

// ── Core pages ──
const Overview = lazy(() => import('./pages/Overview'))
const MorningBrief = lazy(() => import('./pages/MorningBrief'))
const Command = lazy(() => import('./pages/Command'))

// ── Portfolio (consolidated: Holdings + Health + Intelligence) ──
const PortfolioCommand = lazy(() => import('./pages/PortfolioCommand'))
const Dividends = lazy(() => import('./pages/Dividends'))
const Returns = lazy(() => import('./pages/Returns'))
const Attribution = lazy(() => import('./pages/Attribution'))
const TaxLots = lazy(() => import('./pages/TaxLots'))
const Rebalance = lazy(() => import('./pages/Rebalance'))
const Retirement = lazy(() => import('./pages/Retirement'))

// ── Trading & Analysis ──
const TradeAI = lazy(() => import('./pages/TradeAI'))
const Prospects = lazy(() => import('./pages/Prospects'))
const StrategyDesk = lazy(() => import('./pages/StrategyDesk'))
const PaperStatus = lazy(() => import('./pages/PaperStatus'))
const PaperProposals = lazy(() => import('./pages/PaperProposals'))
const Incubator = lazy(() => import('./pages/Incubator'))
const ExecutionQuality = lazy(() => import('./pages/ExecutionQuality'))
const BrokerReconciliation = lazy(() => import('./pages/BrokerReconciliation'))
const Technical = lazy(() => import('./pages/Technical'))
const Risk = lazy(() => import('./pages/Risk'))
const RiskRegime = lazy(() => import('./pages/RiskRegime'))
const Research = lazy(() => import('./pages/Research'))
const StrategyAdmin = lazy(() => import('./pages/StrategyAdmin'))
const StrategyAnalytics = lazy(() => import('./pages/StrategyAnalytics'))

// ── Paper Review (consolidated: Outcomes + TCA) ──
const PaperReview = lazy(() => import('./pages/PaperReview'))
const PlanVsPerformance = lazy(() => import('./pages/PlanVsPerformance'))

// ── Strategy & Monitoring ──
const Watchlist = lazy(() => import('./pages/Watchlist'))
const WatchlistSymbolPage = lazy(() => import('./pages/WatchlistSymbolPage'))
const CIODashboard = lazy(() => import('./pages/CIODashboard'))
const StoppedOutWatch = lazy(() => import('./pages/StoppedOutWatch'))

// ── Journal (consolidated: Entries + Analytics + Reports + Paper) ──
const JournalHub = lazy(() => import('./pages/JournalHub'))

// ── Intelligence (consolidated: Sources + Entities + Whiteboard + Content Health) ──
const OvernightDashboard = lazy(() => import('./pages/OvernightDashboard'))
const IntelligenceHub = lazy(() => import('./pages/IntelligenceHub'))
const TopicMonitor = lazy(() => import('./pages/TopicMonitor'))
const ResearchTopics = lazy(() => import('./pages/ResearchTopics'))
const AIAnalyst = lazy(() => import('./pages/AIAnalyst'))

// ── Agents & Pipeline (consolidated) ──
const AgentPipeline = lazy(() => import('./pages/AgentPipeline'))
const AgentCalibration = lazy(() => import('./pages/AgentCalibration'))
const PipelineHub = lazy(() => import('./pages/PipelineHub'))
const WeeklyLearning = lazy(() => import('./pages/WeeklyLearning'))
const Backtesting = lazy(() => import('./pages/Backtesting'))
const SelfImprovement = lazy(() => import('./pages/SelfImprovement'))

// ── Inbox (consolidated: Alerts + Notifications + Actions) ──
const Inbox = lazy(() => import('./pages/Inbox'))

// ── Governance (consolidated: Paper + Learning + Approvals) ──
const GovernanceHub = lazy(() => import('./pages/GovernanceHub'))

// ── Ops (consolidated: Hub + Ops + Orchestration) ──
const OpsHub = lazy(() => import('./pages/OpsHub'))

// ── Alerts ──
const AlertsDashboard = lazy(() => import('./pages/AlertsDashboard'))

// ── System ──
const SystemHealth = lazy(() => import('./pages/SystemHealth'))
const Reports = lazy(() => import('./pages/Reports'))

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
          {/* ── Home ── */}
          <Route index element={<SafePage><Overview /></SafePage>} />
          <Route path="command" element={<SafePage><Command /></SafePage>} />
          <Route path="morning-brief" element={<SafePage><MorningBrief /></SafePage>} />

          {/* ── Portfolio (consolidated) ── */}
          <Route path="portfolio" element={<SafePage><PortfolioCommand /></SafePage>} />
          <Route path="dividends" element={<SafePage><Dividends /></SafePage>} />
          <Route path="returns" element={<SafePage><Returns /></SafePage>} />
          <Route path="attribution" element={<SafePage><Attribution /></SafePage>} />
          <Route path="tax" element={<SafePage><TaxLots /></SafePage>} />
          <Route path="rebalance" element={<SafePage><Rebalance /></SafePage>} />
          <Route path="retirement" element={<SafePage><Retirement /></SafePage>} />

          {/* ── Trading & Analysis ── */}
          <Route path="trade-ai" element={<SafePage><TradeAI /></SafePage>} />
          <Route path="prospects" element={<SafePage><Prospects /></SafePage>} />
          <Route path="strategy-desk" element={<SafePage><StrategyDesk /></SafePage>} />
          <Route path="paper-status" element={<SafePage><PaperStatus /></SafePage>} />
          <Route path="paper-proposals" element={<SafePage><PaperProposals /></SafePage>} />
          <Route path="incubator" element={<SafePage><Incubator /></SafePage>} />
          <Route path="execution-quality" element={<SafePage><ExecutionQuality /></SafePage>} />
          <Route path="broker-reconciliation" element={<SafePage><BrokerReconciliation /></SafePage>} />
          <Route path="paper-review" element={<SafePage><PaperReview /></SafePage>} />
          <Route path="plan-vs-performance" element={<SafePage><PlanVsPerformance /></SafePage>} />
          <Route path="strategy-admin" element={<SafePage><StrategyAdmin /></SafePage>} />
          <Route path="strategy-analytics" element={<SafePage><StrategyAnalytics /></SafePage>} />
          <Route path="technical" element={<SafePage><Technical /></SafePage>} />
          <Route path="risk" element={<SafePage><Risk /></SafePage>} />
          <Route path="risk-regime" element={<SafePage><RiskRegime /></SafePage>} />
          <Route path="research" element={<SafePage><Research /></SafePage>} />

          {/* ── Strategy & Monitoring ── */}
          <Route path="watchlist" element={<SafePage><Watchlist /></SafePage>} />
          <Route path="watchlist/:symbol" element={<SafePage><WatchlistSymbolPage /></SafePage>} />
          <Route path="cio" element={<SafePage><CIODashboard /></SafePage>} />
          <Route path="recovery" element={<SafePage><StoppedOutWatch /></SafePage>} />

          {/* ── Journal (consolidated) ── */}
          <Route path="journal" element={<SafePage><JournalHub /></SafePage>} />
          <Route path="automated-journal" element={<Navigate to="/v2/journal?tab=automated-journal" replace />} />

          {/* ── Intelligence (consolidated) ── */}
          <Route path="overnight" element={<SafePage><OvernightDashboard /></SafePage>} />
          <Route path="intelligence" element={<SafePage><IntelligenceHub /></SafePage>} />
          <Route path="topic-monitor" element={<SafePage><TopicMonitor /></SafePage>} />
          <Route path="research-topics" element={<SafePage><ResearchTopics /></SafePage>} />
          <Route path="ai-analyst" element={<SafePage><AIAnalyst /></SafePage>} />

          {/* ── Agents & Pipeline (consolidated) ── */}
          <Route path="agent-pipeline" element={<SafePage><AgentPipeline /></SafePage>} />
          <Route path="agent-calibration" element={<SafePage><AgentCalibration /></SafePage>} />
          <Route path="pipeline" element={<SafePage><PipelineHub /></SafePage>} />
          <Route path="weekly-learning" element={<SafePage><WeeklyLearning /></SafePage>} />
          <Route path="backtesting" element={<SafePage><Backtesting /></SafePage>} />
          <Route path="self-improvement" element={<SafePage><SelfImprovement /></SafePage>} />

          {/* ── Inbox (consolidated) ── */}
          <Route path="inbox" element={<SafePage><Inbox /></SafePage>} />

          {/* ── Governance (consolidated) ── */}
          <Route path="governance" element={<SafePage><GovernanceHub /></SafePage>} />

          {/* ── Alerts ── */}
          <Route path="alerts" element={<SafePage><AlertsDashboard /></SafePage>} />

          {/* ── Ops (consolidated) ── */}
          <Route path="ops" element={<SafePage><OpsHub /></SafePage>} />

          {/* ── System ── */}
          <Route path="system-health" element={<SafePage><SystemHealth /></SafePage>} />
          <Route path="reports" element={<SafePage><Reports /></SafePage>} />

          {/* ── Legacy redirects (old routes → consolidated pages) ── */}
          <Route path="portfolio-monitor" element={<SafePage><PortfolioCommand /></SafePage>} />
          <Route path="portfolio-intelligence" element={<SafePage><PortfolioCommand /></SafePage>} />
          <Route path="journal-analytics" element={<SafePage><JournalHub /></SafePage>} />
          <Route path="journal-reports" element={<SafePage><JournalHub /></SafePage>} />
          <Route path="paper-journal" element={<SafePage><JournalHub /></SafePage>} />
          <Route path="paper-outcomes" element={<SafePage><PaperReview /></SafePage>} />
          <Route path="paper-trade-intelligence" element={<SafePage><PaperReview /></SafePage>} />
          <Route path="pipeline-health-master" element={<SafePage><PipelineHub /></SafePage>} />
          <Route path="pipeline-controller" element={<SafePage><PipelineHub /></SafePage>} />
          <Route path="alerts" element={<SafePage><Inbox /></SafePage>} />
          <Route path="notifications" element={<SafePage><Inbox /></SafePage>} />
          <Route path="actions" element={<SafePage><Inbox /></SafePage>} />
          <Route path="paper-governance" element={<SafePage><GovernanceHub /></SafePage>} />
          <Route path="learning-governance" element={<SafePage><GovernanceHub /></SafePage>} />
          <Route path="approvals" element={<SafePage><GovernanceHub /></SafePage>} />
          <Route path="hub" element={<SafePage><OpsHub /></SafePage>} />
          <Route path="orchestration" element={<SafePage><OpsHub /></SafePage>} />
          <Route path="intelligence-sources" element={<SafePage><IntelligenceHub /></SafePage>} />
          <Route path="intelligence-entities" element={<SafePage><IntelligenceHub /></SafePage>} />
          <Route path="intelligence-whiteboard" element={<SafePage><IntelligenceHub /></SafePage>} />
          <Route path="content-health" element={<SafePage><IntelligenceHub /></SafePage>} />
          <Route path="live-governance" element={<SafePage><GovernanceHub /></SafePage>} />
          <Route path="correlation" element={<SafePage><Risk /></SafePage>} />
          <Route path="forecast" element={<SafePage><Returns /></SafePage>} />
          <Route path="proposals" element={<Navigate to="../paper-proposals" replace />} />
          <Route path="strategy" element={<Navigate to="../strategy-desk" replace />} />

          <Route path="*" element={
            <div style={{ padding: 40, color: 'var(--text2)' }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Page not found</div>
              <div style={{ fontSize: 12, marginBottom: 16 }}>This route doesn't exist in the Command Center.</div>
              <a href="/v2/" style={{ color: 'var(--accent)', fontSize: 12 }}>Back to Command Center</a>
            </div>
          } />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
