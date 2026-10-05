import type { CSSProperties } from 'react'
import { useApi } from '../../hooks/useApi'
import { RADIUS } from '../../lib/designTokens'
import { TipKpi } from '../OptionsTip'

// Operator options intents (2026-10-05). The operator's standing plan for a name (e.g. SPCX: accumulate
// with cash-secured puts at or below support, covered calls only at strikes that keep the run toward
// $300) and the live Schwab contracts the matcher found for it. GET /api/v2/options/intents.
// Advisory only — no order control here.

type Row = {
  play?: string; exp?: string; strike?: number; mid?: number; iv?: number; delta?: number; oi?: number
  credit_per_contract?: number; collateral_per_contract?: number; annualized_pct?: number; breakeven?: number
  upside_kept_pct?: number; cost_per_contract?: number; stock_cost_100?: number; time_value_pct?: number
  assignment_odds_pct?: number; called_away_odds_pct?: number; crosses_earnings?: boolean | null
}
type Match = {
  as_of?: string; spot?: number; quote_time?: string; earnings?: { date?: string | null; source?: string }
  plays?: Record<string, Row[]>; empty_reasons?: Record<string, string>; covered_call_floor?: number | null
  shares_by_account?: Record<string, number>
}
type Intent = {
  symbol: string; directive_id?: number; status?: string; thesis_target?: number | null; thesis_source?: string
  goals?: string[]; plays?: Record<string, Record<string, unknown>>; rationale?: string; updated_at?: string
  avoid_earnings_cross?: boolean; matches?: Match | null
}
type Feed = { status?: string; mode?: 'shadow' | 'send'; intents?: Intent[] }

const PLAY_NAME: Record<string, string> = {
  cash_secured_put: 'Cash-secured puts — get paid to buy lower',
  covered_call: 'Covered calls — income that keeps the upside',
  leap_call: 'LEAP calls — stock substitute',
}
const PLAY_TIP: Record<string, string> = {
  cash_secured_put: 'Sell to open. You keep the premium; if price closes below the strike you buy 100 shares per contract at the strike.',
  covered_call: 'Sell to open against shares you own. Strikes below the floor from your plan are never shown.',
  leap_call: 'Deep in-the-money long-dated calls: most of the stock move for less cash; base for a poor-man’s covered call.',
}

const n = (v?: number | null, d = 2) => (v == null || !Number.isFinite(v) ? '—' : v.toFixed(d))
const usd = (v?: number | null) => (v == null || !Number.isFinite(v) ? '—' : `$${Math.round(v).toLocaleString()}`)

const panel: CSSProperties = { background: 'var(--bg-1)', border: '1px solid var(--border-color)', borderRadius: RADIUS.md, padding: '10px 14px', marginBottom: 14 }
const muted: CSSProperties = { color: 'var(--text-3)', fontSize: 12 }
const mono: CSSProperties = { fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums', fontSize: 12 }

function line(r: Row): string {
  if (r.play === 'cash_secured_put') {
    return `${r.exp} $${r.strike}P · mid $${n(r.mid)} · ${usd(r.credit_per_contract)} on ${usd(r.collateral_per_contract)} · ${n(r.annualized_pct, 0)}%/yr · breakeven $${n(r.breakeven)} · IV ${n(r.iv, 0)}% · Δ ${n(r.delta)} (~${r.assignment_odds_pct}% assigned) · OI ${r.oi ?? '—'}`
  }
  if (r.play === 'covered_call') {
    return `${r.exp} $${r.strike}C · mid $${n(r.mid)} · ${usd(r.credit_per_contract)}/contract · keeps +${n(r.upside_kept_pct, 0)}% · ${n(r.annualized_pct, 0)}%/yr · IV ${n(r.iv, 0)}% · Δ ${n(r.delta)} · OI ${r.oi ?? '—'}`
  }
  return `${r.exp} $${r.strike}C · ${usd(r.cost_per_contract)} vs ${usd(r.stock_cost_100)} stock · time value ${n(r.time_value_pct, 1)}% · Δ ${n(r.delta)} · OI ${r.oi ?? '—'}`
}

export default function StandingIntentsPanel() {
  const { data } = useApi<Feed>('/api/v2/options/intents', 300_000)
  const intents = data?.intents ?? []
  if (!intents.length) return null
  return (
    <section style={panel} data-testid="options-standing-intents" aria-label="Your standing intents">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <strong style={{ fontSize: 14, color: 'var(--text-0)' }}>Your standing intents</strong>
        <span style={muted}>
          {data?.mode === 'send' ? 'Telegram digest on a better contract' : 'Shadow: shown here, no Telegram'} · live Schwab chain · advisory only
        </span>
      </div>
      {intents.map(it => {
        const m = it.matches
        return (
          <div key={it.symbol} style={{ borderTop: '1px solid var(--border-subtle)', marginTop: 10, paddingTop: 10 }} data-testid="options-intent">
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
              <strong style={{ fontSize: 18, color: 'var(--text-0)' }}>{it.symbol}</strong>
              <TipKpi tip={it.thesis_source || 'Your thesis target'} label="Target" value={it.thesis_target ? `$${it.thesis_target}` : '—'} color="var(--text-1)" />
              <TipKpi tip={`Schwab quote ${m?.quote_time ?? ''}`} label="Now" value={m?.spot ? `$${n(m.spot)}` : '—'} color="var(--text-1)" />
              <TipKpi tip={`Earnings date source: ${m?.earnings?.source ?? 'unknown'}`} label="Earnings" value={m?.earnings?.date ?? 'unknown'}
                color={it.avoid_earnings_cross ? 'var(--warning-color)' : 'var(--text-1)'} />
              <span style={muted}>{(it.goals ?? []).join(' + ')} · directive #{it.directive_id}</span>
            </div>
            {it.rationale && <p style={{ ...muted, margin: '6px 0' }}>{it.rationale}</p>}
            {!m && <p style={muted}>No contract scan yet. The matcher fills this from Schwab's live chain.</p>}
            {m && Object.keys(it.plays ?? {}).map(play => {
              const rows = m.plays?.[play] ?? []
              return (
                <div key={play} style={{ marginTop: 8 }}>
                  <div title={PLAY_TIP[play]} style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-1)' }}>
                    {PLAY_NAME[play] ?? play}
                    {play === 'covered_call' && m.covered_call_floor ? <span style={muted}> · floor ${n(m.covered_call_floor, 0)}</span> : null}
                  </div>
                  {rows.length === 0
                    ? <div style={muted}>None fit now — {m.empty_reasons?.[play] ?? 'no match'}</div>
                    : rows.slice(0, 3).map((r, i) => <div key={i} style={{ ...mono, color: 'var(--text-2)' }}>{line(r)}</div>)}
                </div>
              )
            })}
            {m?.as_of && <div style={{ ...muted, marginTop: 6 }}>Scanned {m.as_of.slice(0, 16).replace('T', ' ')} UTC</div>}
          </div>
        )
      })}
    </section>
  )
}
