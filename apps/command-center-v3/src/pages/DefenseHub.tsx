import { useApi } from '../hooks/useApi'
import { BB, DASH, numStyle } from '../lib/watchTokens'
import { hubTitle, hubSubtitle } from '../lib/terminalHubChrome'
import { useTerminalUi } from '../lib/terminalUi'
import RecommendationsRail from '../components/defense/RecommendationsRail'
import RotationBoards from '../components/defense/RotationBoards'
import DefenseDetails from '../components/defense/DefenseDetails'

// Defense Desk v3 (WS-D3): a dashboard, not a data dump. Row 1 verdict + four big
// numbers · Row 2 recommendations (the reason the desk exists) · Row 3 rotation
// picture · Row 4 collapsed detail folds. House scale = DASH tokens; the design
// guard (scripts/check_design_tokens.sh) blocks raw hex and sub-10px regressions.

function Big({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div style={{ minWidth: 130 }}>
      <div style={{ fontSize: DASH.chip, fontWeight: 800, color: BB.text3, textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 2 }}>{label}</div>
      <div style={{ ...numStyle, fontSize: DASH.verdict, fontWeight: 800, color: tone || BB.text1 }}>{value}</div>
    </div>
  )
}

export default function DefenseHub() {
  const [terminalUi] = useTerminalUi()
  const { data: posture } = useApi<any>('/api/v2/defense/posture', 300_000)
  const { data: industries } = useApi<any>('/api/v2/defense/industries', 300_000)
  const { data: recsData } = useApi<any>('/api/v2/defense/recommendations', 300_000)
  const { data: regime } = useApi<any>('/api/v2/risk-regime/latest', 300_000)
  const { data: tradeAi } = useApi<any>('/api/v2/trade-ai/summary', 300_000)

  const rows: any[] = posture?.momentum?.rows || []
  const market = posture?.momentum?.market
  const transitions: any[] = posture?.momentum?.transitions_today || []
  const net = posture?.net_exposure
  const recs = recsData?.recommendations
  const radar = recsData?.hedging_radar
  const ind: any[] = industries?.industries || []
  const weakLag = rows.filter(r => r.state === 'WEAKENING' || r.state === 'LAGGING')
  const shortAdvised = (recs?.groups?.short_side || []).length
  const spyLong = (market?.indices || []).find((i: any) => i.symbol === 'SPY')?.long ?? null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 1480, margin: '0 auto' }}>
      <div>
        <div style={hubTitle()}>Defense Desk</div>
        <div style={hubSubtitle(terminalUi)}>
          recommendations · rotation · hedging — advisory only, nothing here places orders
        </div>
      </div>

      {/* Row 1 — verdict */}
      <div style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderLeft: `3px solid ${weakLag.length >= 3 ? BB.red : weakLag.length ? BB.amber : BB.green}`, borderRadius: 2, padding: '14px 16px' }}>
        <div style={{ fontSize: DASH.verdict, fontWeight: 800, color: BB.text1, lineHeight: 1.35, marginBottom: 12 }}>
          {market?.state_line || 'market engine warming up'}
        </div>
        <div style={{ display: 'flex', gap: 28, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <Big label="Net equity exposure" value={net ? `${net.equity_pct}%` : '—'} tone={BB.amber} />
          <Big label="Hedges · active / advised" value={`0 / ${shortAdvised}`} tone={shortAdvised ? BB.red : BB.text1} />
          <Big label="Transitions today" value={String(transitions.length)} tone={transitions.length ? BB.amber : BB.text1} />
          <Big label="VIX · regime" value={`${tradeAi?.vix ?? '—'}`} />
          <div style={{ fontSize: DASH.data, color: BB.text3, paddingBottom: 4 }}>
            {regime?.regime_label?.replace(/_/g, ' ') ?? ''}
            {net && <span> · {net.cash_pct}% cash ≈ ${Math.round(net.cash_dollars / 1000)}K is already a hedge</span>}
          </div>
        </div>
        {transitions.length > 0 && (
          <div style={{ marginTop: 10 }}>
            {transitions.map((t: any, i: number) => (
              <div key={i} style={{ fontSize: DASH.section, fontWeight: 700, color: t.severity === 'urgent' ? BB.red : BB.amber, padding: '2px 0' }}>{t.line}</div>
            ))}
          </div>
        )}
      </div>

      {/* Row 2 — the recommendations rail */}
      <RecommendationsRail recs={recs} />

      {/* Row 3 — the rotation picture */}
      <RotationBoards sectors={rows} industries={ind} spyLong={spyLong} />

      {/* Row 4 — detail folds, collapsed by default */}
      <DefenseDetails posture={posture} industries={industries} radar={radar} />
    </div>
  )
}
