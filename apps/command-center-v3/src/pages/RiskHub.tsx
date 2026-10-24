import { useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { DrillContext } from '../components/DetailDrawer'
import { useApi } from '../hooks/useApi'
import { useW7Pages, W7Load } from '../components/W7PagePanels'
import { W7RiskExposure, W7RiskConcentration, W7RiskCorrelation, W7RiskRegime, W7RiskRecovery, W7RiskStyles } from '../components/W7RiskPanels'
import { TOKENS } from '../lib/designTokens'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Exposure', 'Concentration', 'Correlation', 'Regime', 'Recovery'] as const

/** Approved board15. Shared risk facts are resolved once by the CIO. */
export default function RiskHub({ onDrill }: Props) {
  const [params, setParams] = useSearchParams()
  const tab = TABS.find(t => t.toLowerCase() === params.get('tab')?.toLowerCase()) || 'Exposure'
  const { data, loading, error } = useW7Pages()
  const { data: correlation, error: correlationError } = useApi<any>('/api/v2/correlation', 120_000, { enabled: tab === 'Correlation' })
  const { data: recovery, error: recoveryError } = useApi<any>('/api/v2/recovery', 120_000, { enabled: tab === 'Recovery' })
  const symbol = params.get('symbol')
  const focused = useRef(false)
  useEffect(() => {
    if (focused.current || !symbol || !data?.positions?.rows) return
    const row = data.positions.rows.find((p: any) => p.symbol === symbol.toUpperCase())
    if (row) { focused.current = true; const next = new URLSearchParams(params); next.set('detail', `position:${row.account_id || row.account}:${row.symbol}`); setParams(next, { replace: true }) }
  }, [symbol, data, params, setParams])
  return <main data-testid="risk-hub" data-active-tab={tab} style={{ padding: 20, color: TOKENS.text[0] }}>
    <W7RiskStyles />
    <h1 style={{ fontSize: 24, margin: '0 0 8px' }}>Risk</h1>
    <p style={{ color: TOKENS.text[2] }}>What could you lose if stops fill — and what has no active protection?</p>
    <nav role="tablist" aria-label="Risk sections" style={{ display: 'flex', flexWrap: 'wrap', gap: 6, margin: '16px 0' }}>
      {TABS.map(t => <button key={t} role="tab" aria-selected={tab === t} onClick={() => { const next = new URLSearchParams(params); next.set('tab', t.toLowerCase()); setParams(next) }} style={{ padding: '9px 14px', color: tab === t ? TOKENS.text[0] : TOKENS.text[2], background: TOKENS.bg[1], border: `1px solid ${tab === t ? TOKENS.primary : TOKENS.border}`, borderRadius: 6, cursor: 'pointer' }}>{t}</button>)}
    </nav>
    {!data && <W7Load loading={loading} error={error} />}
    {data && tab === 'Exposure' && <W7RiskExposure data={data} onDrill={onDrill} />}
    {data && tab === 'Concentration' && <W7RiskConcentration data={data} />}
    {tab === 'Correlation' && <W7RiskCorrelation data={correlation} error={correlationError} />}
    {data && tab === 'Regime' && <W7RiskRegime data={data} />}
    {tab === 'Recovery' && <W7RiskRecovery data={recovery} error={recoveryError} />}
  </main>
}
