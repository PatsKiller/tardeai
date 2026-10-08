/** Home, decision-first (operator 2026-10-08): executive strip → REQUIRES ATTENTION (red, full width) → BEST
 *  OPPORTUNITIES (green) and TOP RISKS (red) as separate cards — never mixed in one visual area.
 *  Data: /api/v2/overview (strip), /api/v2/communications/* (attention + risks), /api/v3/opportunities (CIO memory). */
import { useApi } from '../../hooks/useApi'
import { RADIUS, numStyle } from '../../lib/designTokens'
import { useOpenSymbol } from '../opportunity/OpportunityContext'
import { ActionCard, ExecutiveStrip, Stat, familyStyle } from './DecisionParts'

const unwrap = (d: any) => (d?.data && typeof d.data === 'object' && !Array.isArray(d.data) ? d.data : d)

function money(v: any, compact = true) {
  const n = Number(v)
  if (v == null || !Number.isFinite(n)) return '—'
  const sign = n < 0 ? '−' : ''
  const a = Math.abs(n)
  if (compact && a >= 1e6) return `${sign}$${(a / 1e6).toFixed(2)}M`
  if (compact && a >= 1e4) return `${sign}$${(a / 1e3).toFixed(1)}K`
  return `${sign}$${a.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
}

export function HomeExecutiveStrip({ overview, winRate }: { overview: any; winRate?: number | null }) {
  const today = overview?.today_change
  const pct = overview?.today_pct
  const up = Number(today) >= 0
  return (
    <ExecutiveStrip items={[
      { label: 'Portfolio', value: money(overview?.portfolio_value) },
      { label: 'Today', value: `${up ? '+' : ''}${money(today, false)}`, sub: pct != null ? `${up ? '+' : ''}${Number(pct).toFixed(2)}%` : undefined,
        tone: today == null ? undefined : up ? 'var(--success-color)' : 'var(--danger-color)' },
      { label: 'Realized', value: money(overview?.journal?.realized_pnl) },
      { label: 'Win rate', value: winRate != null ? `${winRate}%` : '—' },
    ]} />
  )
}

export function RequiresAttention() {
  const { data: b } = useApi<any>('/api/v2/communications/board?limit=5', 60_000)
  const { data: crit } = useApi<any>('/api/v2/communications/events?hub=1&category=threat&priority=critical&limit=1', 60_000)
  const { data: appr } = useApi<any>('/api/v2/communications/events?hub=1&category=security_alert&actionable=1&limit=1', 60_000)
  const board = unwrap(b) || {}
  const critical = unwrap(crit)?.total
  const approvals = unwrap(appr)?.total
  return (
    <ActionCard testId="home-attention" family="critical" icon="🚨" title="Requires attention"
      cta={{ label: 'Review now', href: '/v3/communications?preset=attention' }} style={{ marginBottom: 12 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '2fr repeat(3, 1fr)', gap: 16, alignItems: 'end' }}>
        <div>
          <div style={{ ...numStyle, fontSize: 52, fontWeight: 900, color: 'var(--text0)', lineHeight: 1 }}>{board.actionable ?? '—'}</div>
          <div style={{ fontSize: 12, color: 'var(--text2)', textTransform: 'uppercase', letterSpacing: '.05em' }}>active issues</div>
        </div>
        <Stat value={critical ?? '—'} label="critical threats" tone="var(--danger-color)" />
        <Stat value={board?.panels?.expiring?.count ?? '—'} label="expiring soon" tone="var(--warning-color)" />
        <Stat value={approvals ?? '—'} label="approvals pending" tone="var(--ai-color)" />
      </div>
    </ActionCard>
  )
}

function Row({ left, mid, right, onClick, family }: { left: string; mid: string; right: string; onClick: () => void; family: 'opportunity' | 'critical' }) {
  const s = familyStyle(family)
  return (
    <div onClick={onClick} style={{ display: 'grid', gridTemplateColumns: '80px 1fr auto', gap: 10, alignItems: 'baseline', padding: '6px 0',
      borderTop: `1px solid ${s.border}`, cursor: 'pointer' }}>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 900, color: 'var(--text0)' }}>{left}</span>
      <span style={{ fontSize: 12, color: 'var(--text2)' }}>{mid}</span>
      <span style={{ ...numStyle, fontSize: 18, fontWeight: 900, color: s.color }}>{right}</span>
    </div>
  )
}

const TYPE: Record<string, string> = { new_position: 'New position', existing: 'Existing', re_entry: 'Re-entry', add_on: 'Add-on', exit_candidate: 'Exit candidate', watchlist: 'Watchlist' }

export function BestOpportunities() {
  const open = useOpenSymbol()
  const { data: top } = useApi<any>('/api/v3/opportunities?preset=top5', 300_000)
  const { data: any_ } = useApi<any>('/api/v3/opportunities?sort=conviction&limit=5', 300_000)
  const t = unwrap(top)
  const items: any[] = (t?.items?.length ? t.items : unwrap(any_)?.items) || []
  return (
    <ActionCard testId="home-opportunities" family="opportunity" icon="🟢" title="Best opportunities"
      cta={{ label: 'View all', href: '/v3/watch?tab=opportunities&preset=top5' }}>
      {items.length === 0 && <div style={{ fontSize: 12, color: 'var(--text2)' }}>{t?.as_of ? 'Nothing clears the bar right now.' : 'Waiting for the first CIO curation run.'}</div>}
      {items.slice(0, 5).map((a: any) => (
        <Row key={a.symbol} family="opportunity" left={a.symbol} onClick={() => open(a.symbol)}
          mid={`${TYPE[a.type] || a.type} · R:R ${(a.risk_reward || {}).rr != null ? Number(a.risk_reward.rr).toFixed(1) + 'x' : '—'}`}
          right={a.conviction != null ? `${Math.round(a.conviction)}` : '—'} />
      ))}
    </ActionCard>
  )
}

export function TopRisks() {
  const open = useOpenSymbol()
  const { data } = useApi<any>('/api/v2/communications/events?hub=1&category=threat&limit=200&sort=priority_score', 60_000)
  const rows: any[] = unwrap(data)?.events || []
  const by: Record<string, { n: number; critical: number; kind: string }> = {}
  for (const e of rows) {
    for (const s of (e.symbols || []).slice(0, 1)) {
      const b = (by[s] ||= { n: 0, critical: 0, kind: String(e.headline || '').replace(/^[^A-Za-z]+/, '').split(/\s[—–-]\s/)[0] || 'Threat' })
      b.n += 1
      if (e.priority === 'critical') b.critical += 1
    }
  }
  const top = Object.entries(by).sort((a, b) => b[1].critical - a[1].critical || b[1].n - a[1].n).slice(0, 5)
  return (
    <ActionCard testId="home-risks" family="critical" icon="🔴" title="Top risks"
      cta={{ label: 'Review stops', href: '/v3/portfolio?tab=Stop%20Management' }}>
      {top.length === 0 && <div style={{ fontSize: 12, color: 'var(--text2)' }}>No live threats.</div>}
      {top.map(([s, b]) => (
        <Row key={s} family="critical" left={s} onClick={() => open(s)}
          mid={`${b.kind.toLowerCase()}${b.critical ? ` · ${b.critical} critical` : ''}`}
          right={`${b.n}`} />
      ))}
    </ActionCard>
  )
}

/** The whole decision block for the top of Home. */
export default function HomeDecision({ overview, winRate }: { overview: any; winRate?: number | null }) {
  return (
    <div data-testid="home-decision" style={{ marginBottom: 16 }}>
      <HomeExecutiveStrip overview={overview} winRate={winRate} />
      <RequiresAttention />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 12 }}>
        <BestOpportunities />
        <TopRisks />
      </div>
      <div style={{ height: 1, background: 'var(--border)', margin: '16px 0 0', borderRadius: RADIUS.sm }} />
    </div>
  )
}
