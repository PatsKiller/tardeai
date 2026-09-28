/** Option Position Card v5 (PR4, 2026-09-28) — open option leg, behind ui_v5. Same props as
 *  OptionPositionCardV4 (the ui_v5-off fallback). Header → takeaway (the monitor's own
 *  recommendation + rationale) → P/L · mark · captured · DTE → actions → Collapsibles for
 *  risk (moneyness bar, P/L profile), greeks and the beginner explanation. */
import { type CSSProperties, type ReactNode } from 'react'
import OptionMoneynessBar from './risk/OptionMoneynessBar'
import OptionsPnLProfile from './risk/OptionsPnLProfile'
import { WhatIfBox } from './OptionsNovicePanel'
import { Collapsible, Metric, MetricGuide, MetricRow, TakeawayBanner, TickerHeader } from './primitives'
import { RADIUS, SHADOW, TOKENS, TYPE, numStyle, toneVars } from '../lib/designTokens'
import { plainEnglishPosition } from '../lib/optionsNovice'
import { fmtIso, positionContractLine, positionDetailMetrics, positionHeroMetrics, positionInsight, positionStatusChips, type MetricSpec } from '../lib/optionsCardV5'
import type { MetricGuideKey } from '../lib/metricGuide'
import type { OptionPosition } from './OptionPositionCard'

type Props = { position: OptionPosition; novice?: boolean; onAction: (action: string, id: string) => void; onDrill?: () => void }

const line: CSSProperties = { marginTop: 3, fontSize: TYPE.sm, lineHeight: 1.45, color: TOKENS.text[1] }
function Row({ k, v }: { k: string; v: ReactNode }) {
  if (v == null || v === '') return null
  return <div style={line}><span style={{ color: TOKENS.text[1], fontWeight: 800 }}>{k}</span> <span style={{ color: TOKENS.text[2] }}>{v}</span></div>
}
function MetricFrom({ m, size }: { m: MetricSpec; size: 'sm' | 'md' | 'hero' }) {
  return <Metric guideKey={m.guideKey} label={m.label} value={m.value} tone={m.tone} size={size} provenance={m.meta || undefined} />
}

export default function OptionPositionCardV5({ position: p, novice, onAction, onDrill }: Props) {
  const x = p as OptionPosition & Record<string, any>
  const insight = positionInsight(x)
  const rail = toneVars(insight.tone)
  const hero = positionHeroMetrics(x)
  const detail = positionDetailMetrics(x)
  const chips = positionStatusChips(x)
  const key = 'options.position'
  const spot = Number(p.underlying_price)
  const strike = Number(p.strike)

  return (
    <article
      data-testid="option-position-card-v5"
      onClick={onDrill}
      style={{ background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderLeft: `3px solid ${rail.color}`, borderRadius: RADIUS.md,
        boxShadow: SHADOW[1], padding: '10px 14px 8px', cursor: onDrill ? 'pointer' : 'default', color: TOKENS.text[0], minWidth: 0 }}
    >
      <TickerHeader identity={{ symbol: p.underlying, sector: p.sector, industry: p.industry }} status={chips.map(c => ({ label: c.label, tone: c.tone, guideKey: c.guideKey }))} asOf={x.monitored_at}>
        <div style={{ ...numStyle, marginTop: 4, fontSize: TYPE.base, fontWeight: 700, color: TOKENS.text[1] }}>{positionContractLine(x)}{p.occ_symbol ? <span style={{ color: TOKENS.text[3], fontWeight: 500 }}> · {p.occ_symbol}</span> : null}</div>
      </TickerHeader>

      <div style={{ marginTop: 8 }} onClick={e => e.stopPropagation()}><TakeawayBanner insight={insight} /></div>

      <MetricRow style={{ marginTop: 10 }}>{hero.map(m => <MetricFrom key={m.guideKey} m={m} size="md" />)}</MetricRow>
      {detail.length > 0 && <MetricRow style={{ marginTop: 8, gap: '6px 14px' }}>{detail.map(m => <MetricFrom key={m.guideKey} m={m} size="sm" />)}</MetricRow>}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', marginTop: 10 }} onClick={e => e.stopPropagation()}>
        {(p.action_buttons || []).map((b, i) => {
          const primary = /close|roll/.test(b.action)
          const t = toneVars(primary ? 'warning' : 'neutral')
          const gk: MetricGuideKey | undefined = b.action === 'hold' ? 'options.ui.actions.hold' : b.action === 'review_chain' ? 'options.ui.actions.review_chain' : primary ? 'options.ui.actions.close_roll' : undefined
          const btn = (
            <button type="button" onClick={() => onAction(b.action, p.id)}
              style={{ fontFamily: 'inherit', fontSize: TYPE.sm, fontWeight: primary ? 800 : 700, padding: '5px 11px', borderRadius: RADIUS.sm, whiteSpace: 'nowrap', cursor: 'pointer',
                background: primary ? t.bg : 'transparent', color: primary ? t.color : TOKENS.text[1], border: `1px solid ${primary ? t.border : TOKENS.border}` }}>
              {b.label}{b.action !== 'hold' ? ' →' : ''}
            </button>
          )
          return <span key={`${b.action}-${i}`}>{gk ? <MetricGuide guideKey={gk} phase="short">{btn}</MetricGuide> : btn}</span>
        })}
        {p.execution_note && <span style={{ fontSize: TYPE.xs, color: TOKENS.text[3], fontStyle: 'italic', minWidth: 0 }}>{p.execution_note}</span>}
      </div>

      <div style={{ marginTop: 10 }} onClick={e => e.stopPropagation()}>
        <Collapsible title="Risk at expiry" summary={p.moneyness ? `${p.moneyness}${p.pop_otm_pct != null ? ` · P(OTM) ${Math.round(Number(p.pop_otm_pct))}%` : ''}` : undefined} persistKey={`${key}.risk`}>
          {spot > 0 && strike > 0 && (
            <OptionMoneynessBar moneyness={p.moneyness} spot={spot} strike={strike} popOtm={p.pop_otm_pct} popItm={p.pop_itm_pct} optionType={p.option_type || 'call'} compact />
          )}
          {spot > 0 && strike > 0 && (
            <div style={{ marginTop: 8 }}>
              <OptionsPnLProfile underlying={p.underlying} side={p.side || p.strategy} optionType={p.option_type || 'call'} strike={strike} spot={spot}
                qty={Math.abs(Number(p.qty) || 1)} avgEntry={Number(p.avg_entry)} mark={Number(p.mark)} compact hideTitle />
            </div>
          )}
          <Row k="Entry." v={p.entry_credit_debit != null ? `${Number(p.entry_credit_debit) >= 0 ? 'credit' : 'debit'} $${Math.abs(Number(p.entry_credit_debit)).toFixed(2)}` : undefined} />
          <Row k="Acts on." v={p.action_criterion} />
          <Row k="Maturity." v={p.maturity_note} />
          <Row k="Margin." v={p.margin_note} />
          {p.pnl_unknown_reason && <Row k="P/L unknown." v={p.pnl_unknown_reason} />}
        </Collapsible>

        {(novice || p.strategy) && (
          <Collapsible title="What this position does" persistKey={`${key}.plain`}>
            <div style={line}>{plainEnglishPosition(p)}</div>
            {novice && p.strategy && (
              <div style={{ marginTop: 6 }}>
                <WhatIfBox symbol={p.underlying} strategy={p.strategy === 'short_put' ? 'cash_secured_put' : p.strategy === 'short_call' ? 'covered_call' : p.strategy.replace(/^long_/, 'long_')} card={p as any} />
              </div>
            )}
          </Collapsible>
        )}
      </div>

      <div style={{ marginTop: 6, display: 'flex', gap: 8, flexWrap: 'wrap', fontSize: TYPE.xs, color: TOKENS.text[3], ...numStyle }}>
        {x.monitored_at && <span>monitored {fmtIso(x.monitored_at)}</span>}
        {p.position_source && <span>· {p.position_source}</span>}
      </div>
    </article>
  )
}
