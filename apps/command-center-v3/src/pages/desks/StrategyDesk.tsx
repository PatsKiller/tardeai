import DeskBoard from '../../components/DeskBoard'
import BacktestPanel from '../../components/BacktestPanel'
import ExecutionHypothesesPanel from '../../components/ExecutionHypothesesPanel'
import type { DrillContext } from '../../components/DetailDrawer'

/** Approved board 2. `?tab=planner` (Risk's "Strategy planner →") opens the Planner tab. */
export const STRATEGY_TABS = [
  { id: 'leaderboard', label: 'Leaderboard' },
  { id: 'plan-vs-performance', label: 'Plan vs performance' },
  { id: 'planner', label: 'Planner' },
  { id: 'desk', label: 'Desk' },
  { id: 'incubator', label: 'Incubator' },
  { id: 'backtests', label: 'Backtests' },
] as const

export default function StrategyDesk({ onDrill }: { onDrill: (ctx: DrillContext) => void }) {
  return <DeskBoard desk="strategy" testId="strategy-desk" title="Strategy"
    purpose="Which strategies are earning their keep, and which to promote, pause or retire."
    tabs={STRATEGY_TABS} tabAliases={{ 'plan-vs-perf': 'plan-vs-performance', analytics: 'leaderboard', backtesting: 'backtests' }}
    classicHref="/strategy/classic"
    // Board 13: backtests moved here from TradeInView classic (read-only panels, unchanged).
    extras={{ backtests: <section aria-label="Backtest detail" data-testid="strategy-backtest-detail" style={{ display: 'flex', flexDirection: 'column', gap: 12, minWidth: 0, overflowX: 'auto' }}>
      <ExecutionHypothesesPanel /><BacktestPanel onDrill={onDrill} />
    </section> }} />
}
