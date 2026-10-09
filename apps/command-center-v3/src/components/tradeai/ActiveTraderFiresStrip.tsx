/** Active Trader fires on the Trade AI tab (operator 2026-10-09: "active trader firing but nothing on tradeai").
 *  The two engines used to be invisible to each other: AT's sent alerts lived only on the Active Trader page.
 *  This strip lists today's SENT Active Trader alerts with Trade-AI's own verdict for the same symbol, so
 *  agreement and disagreement are visible in one place. Read-only; data: GET /api/v3/active-trader/alerts. */
import { useApi } from '../../hooks/useApi'
import { RADIUS, TOKENS } from '../../lib/designTokens'
import { SymbolLink } from '../opportunity/OpportunityContext'

const KIND_COLOR: Record<string, string> = {
  TRIGGERED: TOKENS.success, PULLBACK_ZONE: TOKENS.success, APPROACHING: TOKENS.info, ARMED: TOKENS.warning,
  EXTENDED: TOKENS.warning, TRIGGER_CANCELLED: TOKENS.neutral, STAND_DOWN: TOKENS.neutral,
}
const VERDICT_COLOR: Record<string, string> = { GO: TOKENS.success, WAIT: TOKENS.warning, MANUAL_REVIEW: TOKENS.info }

export default function ActiveTraderFiresStrip({ tradeAiTickers }: { tradeAiTickers: any[] }) {
  const { data } = useApi<any>('/api/v3/active-trader/alerts?limit=500', 30_000)
  const d = data?.data && data.data.decisions ? data.data : data
  const sent: any[] = (d?.decisions || []).filter((x: any) => x.sent)
  const verdict: Record<string, string> = {}
  for (const t of tradeAiTickers || []) if (t?.symbol) verdict[String(t.symbol).toUpperCase()] = String(t.decision || '')
  return (
    <div data-testid="at-fires-strip" style={{ border: '1px solid var(--border)', borderRadius: RADIUS.md, padding: '8px 10px', marginBottom: 10, background: 'var(--bg0)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}>
        <span style={{ fontSize: 11, fontWeight: 800, color: 'var(--text0)' }}>Active Trader fired today · {sent.length}</span>
        <span style={{ fontSize: 10, color: 'var(--text3)' }}>scalp alerts sent · Trade-AI verdict beside each</span>
      </div>
      {!sent.length && <div style={{ fontSize: 11, color: 'var(--text3)' }}>No Active Trader alerts sent today.</div>}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {sent.slice(0, 24).map((x: any) => {
          const v = verdict[String(x.symbol || '').toUpperCase()]
          return (
            <span key={x.id} title={`${x.kind} ${x.at ? new Date(x.at).toLocaleTimeString() : ''} · entry ${x.entry ?? '—'} · stop ${x.stop ?? '—'}`}
              style={{ fontSize: 11, padding: '3px 8px', borderRadius: RADIUS.pill, border: `1px solid ${KIND_COLOR[x.kind] || TOKENS.neutral}`, display: 'inline-flex', gap: 6, alignItems: 'baseline' }}>
              <b style={{ color: 'var(--text0)' }}><SymbolLink symbol={String(x.symbol)} /></b>
              <span style={{ color: KIND_COLOR[x.kind] || TOKENS.neutral, fontWeight: 800 }}>{String(x.kind || '').replace('_', ' ')}</span>
              <span style={{ color: 'var(--text3)' }}>{x.at ? new Date(x.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}</span>
              <span style={{ color: v ? (VERDICT_COLOR[v] || TOKENS.danger) : 'var(--text3)', fontWeight: 700 }}>{v ? `Trade-AI ${v.replace('_', ' ')}` : 'not in Trade-AI'}</span>
            </span>
          )
        })}
      </div>
    </div>
  )
}
