/** Option Proposal Card v5 (PR4, 2026-09-28) — the first redesigned surface, behind ui_v5.
 *
 *  Contract (docs/design/UI_AUDIT_2026-09.md → PR4): header → takeaway → ≤4 hero metrics →
 *  actions → everything else in Collapsibles. Every Metric carries a guideKey; every tone
 *  comes from a server enum; every sentence is server text (AGENTS §13). Same props as
 *  OptionProposalCardV4, which stays in-tree as the ui_v5-off fallback (rollback layer 1).
 *  Paper-lab rows (educational_paper_model) keep the v4 card this phase: the Alpaca lane
 *  state machine is not re-implemented here. */
import { useState, type CSSProperties, type ReactNode } from 'react'
import OptionProposalCardV4, { type AlpacaActionResult, type AlpacaLaneAction } from './OptionProposalCardV4'
import OptionValidateButton from './OptionValidateButton'
import { BeginnerSummaryRow, ExplainTradePanel, WhatIfBox } from './OptionsNovicePanel'
import { Chip, ChipRow, Collapsible, Metric, MetricGuide, MetricRow, ShowMore, TakeawayBanner, TickerHeader } from './primitives'
import { RADIUS, SHADOW, TOKENS, TYPE, numStyle, toneVars } from '../lib/designTokens'
import { fmt$ } from '../lib/format'
import { sanitizeActionButtons, allowsManualLog, liquidityWarnings } from '../lib/optionsCardSemantics'
import { floorCallouts } from '../lib/optionsDeskTruth'
import {
  fmtIso, proposalContractLine, proposalDetailMetrics, proposalHeroMetrics, proposalInsight, proposalStatusChips,
  visibleProposalActions, type ActionSpec, type MetricSpec,
} from '../lib/optionsCardV5'
import type { OptionProposal } from './OptionProposalCard'

type Props = {
  proposal: OptionProposal
  armed?: boolean
  novice?: boolean
  onAction: (action: string, id: string) => void
  onAlpacaAction?: (action: AlpacaLaneAction, proposalId: string, payload?: { exitPremium?: number }) => Promise<AlpacaActionResult>
  onDrill?: () => void
  onManualLog?: () => void
  reviewBar?: ReactNode
  /** First card of a symbol shows the shared scenario table. Later cards point at it. */
  packageLead?: boolean
}

const label: CSSProperties = { color: TOKENS.text[1], fontWeight: 800 }
const dim: CSSProperties = { color: TOKENS.text[2] }
const line: CSSProperties = { marginTop: 3, fontSize: TYPE.sm, lineHeight: 1.45, color: TOKENS.text[1] }

function Row({ k, v }: { k: string; v: ReactNode }) {
  if (v == null || v === '' || (Array.isArray(v) && v.length === 0)) return null
  return <div style={line}><span style={label}>{k}</span> <span style={dim}>{Array.isArray(v) ? v.join(' · ') : v}</span></div>
}

function MetricFrom({ m, size, values }: { m: MetricSpec; size: 'sm' | 'md' | 'hero'; values?: Record<string, unknown> }) {
  return <Metric guideKey={m.guideKey} label={m.label} value={m.value} tone={m.tone} size={size} provenance={m.meta || undefined} values={{ ...values, ...m.values }} />
}

function ActionButton({ a, onClick }: { a: ActionSpec; onClick: () => void }) {
  const t = toneVars(a.primary ? 'success' : 'neutral')
  const btn = (
    <button type="button" disabled={a.locked} onClick={onClick}
      style={{ fontFamily: 'inherit', fontSize: TYPE.sm, fontWeight: a.primary ? 800 : 700, padding: '5px 11px', borderRadius: RADIUS.sm, whiteSpace: 'nowrap',
        cursor: a.locked ? 'not-allowed' : 'pointer', opacity: a.locked ? 0.55 : 1,
        background: a.primary ? t.bg : 'transparent', color: a.primary ? t.color : TOKENS.text[1], border: `1px solid ${a.primary ? t.border : TOKENS.border}` }}>
      {a.label}{a.action !== 'hold' ? ' →' : ''}
    </button>
  )
  return a.guideKey ? <MetricGuide guideKey={a.guideKey} phase="short">{btn}</MetricGuide> : btn
}

export default function OptionProposalCardV5(props: Props) {
  const { proposal: p, armed, novice, onAction, onDrill, onManualLog, reviewBar, packageLead = true } = props
  const x = p as OptionProposal & Record<string, any>
  const [showAllDetail, setShowAllDetail] = useState(false)
  if (x.educational_paper_model) return <OptionProposalCardV4 {...props} />

  const insight = proposalInsight(x)
  const rail = toneVars(insight.tone)
  const hero = proposalHeroMetrics(x)
  const detail = proposalDetailMetrics(x)
  const actions = visibleProposalActions(x, !!armed, sanitizeActionButtons(p))
  const chips = proposalStatusChips(x)
  const pe = x.plain_english
  const memo = x.committee_memo
  const econ = x.economics
  const cv = x.cio_view
  const dec = x.cio_decision
  const life = x.lifecycle
  const fund = x.fundamentals
  const legs: any[] = Array.isArray(x.legs_liquidity) ? x.legs_liquidity : []
  const combined = x.combined_exposure
  const research = x.research_context
  const key = `options.proposal.${String(p.strategy || 'x')}`
  // values for the guide's {placeholders}: only fields already on the row (§13)
  const guideValues = { symbol: p.symbol, strike: p.strike, dte: p.dte, validation_message: x.validation_progress?.message || x.validation_progress?.label || '' }
  const liq = liquidityWarnings(p)
  const ot = x.options_thesis
  const preferred = x.recommendation_comparison?.comparison?.preferred_structure
  const $ = (v: unknown) => (v == null ? '—' : fmt$(Number(v)))

  const econParts: string[] = []
  if (econ) {
    if (econ.net_cost_if_assigned_per_share != null) econParts.push(`Net cost if assigned $${Number(econ.net_cost_if_assigned_per_share).toFixed(2)}/sh${econ.discount_to_spot_pct != null ? ` (${econ.discount_to_spot_pct}% below spot)` : ''} · cash committed ${$(econ.cash_committed)}`)
    if (econ.called_away_price_per_share != null) econParts.push(`If called away: $${Number(econ.called_away_price_per_share).toFixed(2)}/sh incl. premium · ${econ.shares_committed ?? '—'} shares committed`)
    if (econ.collateral != null) econParts.push(`Collateral ${$(econ.collateral)} · max loss ${$(econ.max_loss_total)} · breakeven $${econ.breakeven}${econ.credit_basis ? ` · credit basis: ${econ.credit_basis}` : ''}`)
    if (econ.credit_total_at_mid != null) econParts.push(`At leg midpoints (not a fill): credit ${$(econ.credit_total_at_mid)} · max loss ${$(econ.max_loss_total_at_mid)} · breakeven $${econ.breakeven_at_mid}${econ.credit_haircut_total != null ? ` · haircut ${$(econ.credit_haircut_total)}` : ''}`)
    if (econ.floor_value_after_premium != null) econParts.push(`Insures ${econ.insured_shares} sh${econ.uninsured_shares ? ` (${econ.uninsured_shares} uninsured)` : ''} · floor ${$(econ.floor_value_after_premium)} · hedged max loss from mark ${$(econ.hedged_max_loss_from_mark)}${econ.put_breakeven != null ? ` · put breakeven $${econ.put_breakeven}` : ''}`)
    if (econ.uninsured_downside_note) econParts.push(String(econ.uninsured_downside_note))
    if (x.fill_assumption) econParts.push(`Fill assumption: ${x.fill_assumption}${x.quotes_as_of ? ` · quotes as of ${fmtIso(x.quotes_as_of)}` : ''}`)
    if (econ.ev_method) econParts.push(`Expected P/L method: ${econ.ev_method}`)
    if (econ.ev_caveat) econParts.push(`Expected P/L: ${econ.ev_caveat}`)
    if (econ.expected_pl_status) econParts.push(`Expected P/L ${econ.expected_pl_status}`)
    if (econ.prices_basis) econParts.push(`Prices: ${econ.prices_basis}`)
  }

  return (
    <article
      data-testid="option-proposal-card-v5"
      onClick={onDrill}
      style={{ background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderLeft: `3px solid ${rail.color}`, borderRadius: RADIUS.md,
        boxShadow: SHADOW[1], padding: '10px 14px 8px', cursor: onDrill ? 'pointer' : 'default', color: TOKENS.text[0], minWidth: 0 }}
    >
      <TickerHeader
        identity={{ symbol: p.symbol, sector: p.sector, industry: p.industry }}
        status={chips.map(c => ({ label: c.label, tone: c.tone, guideKey: c.guideKey }))}
        asOf={x.freshness_as_of || x.generated_at}
        right={(
          <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <button type="button" data-testid="open-chain" onClick={() => onAction('review_chain', p.id)}
              style={{ fontFamily: 'inherit', fontSize: TYPE.sm, fontWeight: 800, padding: '5px 11px', borderRadius: RADIUS.sm, cursor: 'pointer', background: toneVars('info').bg, color: TOKENS.info, border: `1px solid ${toneVars('info').border}` }}>
              Open Schwab chain
            </button>
            {x.id ? <OptionValidateButton proposalId={String(x.id)} /> : null}
          </span>
        )}
      >
        <div style={{ ...numStyle, marginTop: 4, fontSize: TYPE.base, fontWeight: 700, color: TOKENS.text[1] }}>{proposalContractLine(x)}</div>
        {liq.length > 0 && (
          <ChipRow style={{ marginTop: 6 }}>
            {liq.map(w => <Chip key={w.code} tone={w.severity === 'danger' ? 'danger' : 'warning'} variant="outline" title={w.message}>{w.message.split(' — ')[0]}</Chip>)}
          </ChipRow>
        )}
        {x.company_description && (
          <ShowMore lines={1} style={{ marginTop: 4, fontSize: TYPE.sm, color: TOKENS.text[2] }}>{x.company_description}</ShowMore>
        )}
      </TickerHeader>

      <div style={{ marginTop: 8 }} onClick={e => e.stopPropagation()}>
        <TakeawayBanner insight={insight} />
      </div>

      <MetricRow style={{ marginTop: 10 }}>
        {hero.map(m => <MetricFrom key={m.guideKey} m={m} size="md" values={guideValues} />)}
      </MetricRow>
      {floorCallouts(x).map(t => <div key={t} style={{ marginTop: 6, color: TOKENS.warning, fontSize: TYPE.sm, fontWeight: 700 }}>{t}</div>)}
      {detail.length > 0 && (
        <MetricRow style={{ marginTop: 8, gap: '6px 14px' }}>
          {(showAllDetail ? detail : detail.slice(0, 4)).map(m => <MetricFrom key={m.guideKey} m={m} size="sm" values={guideValues} />)}
          {detail.length > 4 && (
            <button type="button" onClick={e => { e.stopPropagation(); setShowAllDetail(s => !s) }}
              style={{ background: 'transparent', border: 'none', color: TOKENS.info, cursor: 'pointer', fontSize: TYPE.xs, fontWeight: 700, fontFamily: 'inherit', padding: 0 }}>
              {showAllDetail ? 'fewer' : `+${detail.length - 4} more`}
            </button>
          )}
        </MetricRow>
      )}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', marginTop: 10 }} onClick={e => e.stopPropagation()}>
        {actions.map((a, i) => <ActionButton key={`${a.action}-${i}`} a={a} onClick={() => onAction(a.action, p.id)} />)}
        {onManualLog && allowsManualLog(x) && (
          <MetricGuide guideKey="options.ui.actions.manual_log" phase="short">
            <button type="button" onClick={onManualLog}
              style={{ fontFamily: 'inherit', fontSize: TYPE.sm, fontWeight: 700, padding: '5px 11px', borderRadius: RADIUS.sm, background: 'transparent', color: TOKENS.text[2], border: `1px solid ${TOKENS.border}`, cursor: 'pointer' }}>
              Log manual fill
            </button>
          </MetricGuide>
        )}
        {/* 2026-09-28 (reviewer): "ARMED" beside BLOCKED read as readiness. On a blocked idea the route note
            says what the route is and that this idea is not eligible; the ARMED wording is kept for eligible ideas only. */}
        {x.execution_note && (x.approvable === false || x.enterprise_blocked
          ? <span style={{ fontSize: TYPE.xs, color: TOKENS.text[3], fontStyle: 'italic', minWidth: 0 }}>Broker route: {x.execution_label || 'open'} · this idea is not eligible until its blocks clear.</span>
          : <span style={{ fontSize: TYPE.xs, color: TOKENS.text[3], fontStyle: 'italic', minWidth: 0 }}>{x.execution_note}</span>)}
      </div>

      <div style={{ marginTop: 10 }} onClick={e => e.stopPropagation()}>
        {novice && <div style={{ marginBottom: 6 }}><BeginnerSummaryRow card={p} /></div>}

        {pe && (
          <Collapsible title="What this trade does" summary={pe.objective} persistKey={`${key}.plain`}>
            <div data-testid="options-plain-english">
              <Row k="Objective." v={pe.objective} />
              <Row k="Your premium." v={pe.premium_line} />
              <Row k="Why an option." v={pe.why_option} />
              <Row k="Breakeven." v={pe.breakeven_line} />
              <Row k="Best:" v={pe.cases?.best} />
              <Row k="Expected:" v={pe.cases?.expected} />
              <Row k="Worst:" v={pe.cases?.worst} />
              {Array.isArray(pe.scenarios) && pe.scenarios.length > 0 && (
                <table style={{ marginTop: 6, fontSize: TYPE.sm, borderCollapse: 'collapse', ...numStyle }}>
                  <thead><tr style={{ color: TOKENS.text[3] }}><th style={{ textAlign: 'left', paddingRight: 12 }}>At expiry</th><th style={{ textAlign: 'right', paddingRight: 12 }}>Option result</th>{pe.scenarios[0]?.shares_plus_option_pl != null && <th style={{ textAlign: 'right' }}>Shares + option</th>}</tr></thead>
                  <tbody>{pe.scenarios.map((r: any, i: number) => (
                    <tr key={i} style={{ color: TOKENS.text[1] }}><td style={{ paddingRight: 12 }}>${r.price}{r.move_pct != null ? ` (${r.move_pct > 0 ? '+' : ''}${r.move_pct}%)` : ''}</td><td style={{ textAlign: 'right', paddingRight: 12 }}>{$(r.option_pl)}</td>{r.shares_plus_option_pl != null && <td style={{ textAlign: 'right' }}>{$(r.shares_plus_option_pl)}</td>}</tr>
                  ))}</tbody>
                </table>
              )}
              {novice && <div style={{ marginTop: 6 }}><ExplainTradePanel card={p} /></div>}
            </div>
          </Collapsible>
        )}

        {(econParts.length > 0 || legs.length > 0 || combined) && (
          <Collapsible title="Economics & fill" count={legs.length ? `${legs.length} legs` : undefined}
            summary={x.credit_basis ? `credit basis ${x.credit_basis}${x.quotes_as_of ? ` · quotes ${fmtIso(x.quotes_as_of)}` : ''}` : econ?.ev_caveat}
            persistKey={`${key}.economics`}>
            {econParts.length > 0 && <div data-testid="options-economics">{econParts.map((t, i) => <div key={i} style={line}>{t}</div>)}</div>}
            {legs.length > 0 && (
              <div data-testid="options-legs-liquidity" style={{ marginTop: 6 }}>
                <div style={{ ...line, ...label }}>Each leg</div>
                {legs.map((l, i) => (
                  <div key={i} style={{ ...line, ...numStyle }}>
                    {l.role} ${l.strike}: bid {l.bid ?? '—'} / ask {l.ask ?? '—'}{l.mid != null ? ` / mid ${l.mid}` : ''}{l.spread_pct != null ? ` (${l.spread_pct}% wide)` : ''} · OI {l.open_interest ?? '—'} · volume {l.volume ?? '—'}{l.quote_time ? ` · quoted ${fmtIso(l.quote_time)}` : ''}{l.two_sided === false ? ' · no two-sided quote' : ''}
                  </div>
                ))}
              </div>
            )}
            {combined && !packageLead && (
              <div data-testid="options-combined-exposure-pointer" style={{ ...line, marginTop: 6 }}>
                Same-symbol package is on the first {p.symbol} card. The expiries differ, so there is no single at-expiry payoff.
              </div>
            )}
            {combined && packageLead && (
              <div data-testid="options-combined-exposure" style={{ marginTop: 6 }}>
                <div style={line}><span style={{ ...label, color: combined.correlated ? TOKENS.warning : TOKENS.text[1] }}>Same-symbol ideas ({(combined.ideas || []).length}).</span> <span style={dim}>{combined.note}</span></div>
                <div style={line}>Committed together {$(combined.capital_committed_total)}{combined.account_cash != null ? ` · account cash ${$(combined.account_cash)}${combined.committed_pct_of_cash != null ? ` (${combined.committed_pct_of_cash}% of it)` : ''}` : ''}{combined.shares_held ? ` · ${combined.shares_held} ${combined.symbol} shares already held` : ''}</div>
                {(combined.excluded_ideas || []).length > 0 && <div style={{ ...line, color: TOKENS.text[3] }}>Not counted (archived): {(combined.excluded_ideas || []).map((e: any) => `${String(e.strategy || '').replace(/_/g, ' ')} $${e.strike}`).join(', ')}</div>}
                {combined.shares_by_account && Object.keys(combined.shares_by_account).length > 0 && (
                  <div style={line}>Shares by account: {Object.entries(combined.shares_by_account).map(([a, n]) => `${String(a).replace(/_/g, ' ')} ${n}`).join(' · ')}</div>
                )}
                {(combined.scenarios_by_expiry || []).map((g: any, gi: number) => (
                  <div key={gi} style={{ ...line, ...numStyle }}>
                    <span style={label}>At expiry {g.expiration || '—'}.</span> {(g.rows || []).map((r: any) => `${r.move_pct > 0 ? '+' : ''}${r.move_pct}% ($${r.price}) options ${r.options_only_pl == null ? '—' : $(r.options_only_pl)} · shares ${r.shares_pl == null ? 'unknown' : $(r.shares_pl)} · whole ${r.whole_position_pl == null ? 'withheld' : $(r.whole_position_pl)}`).join(' · ')}
                  </div>
                ))}
                {combined.scenario_basis && <div style={{ ...line, color: TOKENS.text[3] }}>{combined.scenario_basis}</div>}
              </div>
            )}
          </Collapsible>
        )}

        {memo && (
          <Collapsible title="Committee memo" summary={memo.classification_label ? `${memo.classification_label} · ${memo.research_status || ''}`.replace(/ · $/, '') : undefined} persistKey={`${key}.memo`}>
            <div data-testid="options-committee-memo">
              <Row k="Classification." v={memo.classification_label} />
              <Row k="Purpose." v={memo.purpose} />
              <Row k="Investment thesis." v={memo.investment_thesis} />
              <Row k="Market thesis." v={memo.market_thesis} />
              <Row k="Contrarian view." v={memo.contrarian_view} />
              <Row k="Why now." v={memo.why_now} />
              <Row k="Research." v={memo.research_status ? `${memo.research_status}${memo.research_runs != null ? ` · ${memo.research_runs} runs` : ''} · confidence ${memo.confidence || '—'}` : undefined} />
              <Row k="CIO." v={memo.cio_status_label} />
              <Row k="Missing for approval." v={memo.missing_for_approval} />
              <Row k="Thesis invalid when." v={memo.exit_plan?.thesis_invalid_when} />
              <Row k="Exit plan." v={memo.exit_plan?.exit_when} />
              <Row k="Living thesis." v={memo.living_thesis?.thesis_pin ? `${memo.living_thesis.thesis_pin} · last reviewed ${fmtIso(memo.living_thesis.last_reviewed) || 'never'}` : undefined} />
              {Array.isArray(memo.evidence_ladder) && memo.evidence_ladder.length > 0 && (
                <ChipRow style={{ marginTop: 6 }}>
                  <span data-testid="options-evidence-ladder" style={{ display: 'contents' }}>
                    {memo.evidence_ladder.map((e: any, i: number) => <Chip key={i} tone={e.done ? 'success' : 'neutral'} variant={e.done ? 'soft' : 'outline'} title={e.detail}>{e.done ? '✓ ' : ''}{e.label}</Chip>)}
                  </span>
                </ChipRow>
              )}
            </div>
          </Collapsible>
        )}

        {(cv || dec || life || fund || research) && (
          <Collapsible title="CIO, thesis & research"
            summary={dec?.outcome ? `${String(dec.outcome).replace(/_/g, ' ')} · ${String(dec.confidence || '').toLowerCase()}` : life?.stage ? `stage ${String(life.stage).replace(/_/g, ' ').toLowerCase()}` : 'no CIO decision yet'}
            persistKey={`${key}.cio`}>
            {(ot || preferred) && (
              <div data-testid="options-thesis-line">
                <Row k="Options thesis." v={ot ? `${ot.pin || 'not stored'} · state ${String(ot.thesis_gate_state || 'unknown').toLowerCase().replace(/_/g, ' ')}${(ot.missing_required || []).length ? ` · missing: ${(ot.missing_required || []).map((f: string) => f.replace(/_/g, ' ')).join(', ')}` : ' · complete'}${(ot.pending_operator || []).length ? ` · yours: ${(ot.pending_operator || []).map((f: string) => f.replace(/_/g, ' ')).join(', ')}` : ''}` : undefined} />
                <Row k="Preferred structure." v={preferred ? String(preferred).replace(/_/g, ' ') : undefined} />
              </div>
            )}
            {dec?.outcome ? (
              <div data-testid="options-cio-decision">
                <Row k="CIO decision." v={`${String(dec.outcome).replace(/_/g, ' ')} · ${String(dec.confidence || '').toLowerCase()} confidence · ${fmtIso(dec.at)}`} />
                <Row k="Reasoning." v={dec.review?.reasoning} />
                <Row k="Concerns." v={dec.review?.concerns} />
                <Row k="Challenged." v={dec.review?.assumptions_challenged} />
                <Row k="For." v={dec.review?.evidence_for} />
                <Row k="Against." v={dec.review?.evidence_against} />
                {dec.outcome === 'APPROVE' && <div style={line}>Your confirmation is still required; sizing and 2FA are yours.</div>}
                {dec.outcome === 'MONITOR_ONLY' && <div style={{ ...line, color: TOKENS.warning }}>Monitoring: the CIO re-checks this idea automatically about 24h after the decision.</div>}
                {dec.review?.follow_up && <div data-testid="options-cio-followup"><Row k="Follow-up." v={dec.review.follow_up} /></div>}
                {life?.followup?.due_at && <div data-testid="options-cio-followup"><Row k="Follow-up due." v={`${fmtIso(life.followup.due_at)}${life.followup.deliverables ? ` · ${[].concat(life.followup.deliverables).join(', ')}` : ''}`} /></div>}
              </div>
            ) : (
              <div style={{ ...line, color: TOKENS.warning }}>No CIO decision on this idea yet{life?.stage ? ` (stage: ${String(life.stage).replace(/_/g, ' ').toLowerCase()})` : ''}.</div>
            )}
            {Array.isArray(x.thesis_blocks) && x.thesis_blocks.length > 0 && (
              <div data-testid="options-thesis-line" style={{ ...line, color: TOKENS.warning }}>Blocks: {x.thesis_blocks.map((b: any) => b?.reason || b?.code || String(b)).join(' · ')}</div>
            )}
            {cv && (
              <div data-testid="options-cio-view" style={{ marginTop: 6 }}>
                {cv.has_view ? (
                  <>
                    <Row k="Thesis." v={cv.thesis ? `${cv.thesis.pin} · ${String(cv.thesis.stance || cv.thesis.state || '').toLowerCase()}${cv.thesis.state ? ` (${String(cv.thesis.state).toLowerCase()})` : ''} · last reviewed ${fmtIso(cv.thesis.last_reviewed) || 'never'}` : undefined} />
                    <Row k="Summary." v={cv.thesis?.summary} />
                    <Row k="Latest decision." v={cv.latest_decision ? `${cv.latest_decision.recommendation} · ${cv.latest_decision.source || ''} · ${fmtIso(cv.latest_decision.at)}` : undefined} />
                    <Row k="Changed." v={cv.change_since_previous ? `${cv.change_since_previous.previous} → ${cv.change_since_previous.current}` : undefined} />
                    <Row k="Research on file." v={`${cv.research?.count ?? 0} runs · last completed ${fmtIso(cv.research?.last_completed) || 'never'}`} />
                  </>
                ) : cv.genuinely_new ? <div style={{ ...line, color: TOKENS.warning, fontWeight: 800 }}>New to the house: no thesis, decision or research on file for {p.symbol}. Research starts automatically.</div> : null}
              </div>
            )}
            {research && <Row k="Research lane." v={[research.research_status, research.summary ? `signal ${research.summary}` : null, research.catalyst, research.research_as_of ? `as of ${fmtIso(research.research_as_of)}` : null].filter(Boolean) as string[]} />}
            {life?.stage && (
              <div data-testid="options-lifecycle"><Row k="This idea." v={Array.isArray(life.timeline) && life.timeline.length
                ? life.timeline.map((t: any) => `${String(t.stage || '').replace(/_/g, ' ').toLowerCase()} (${fmtIso(t.at)})`).join(' → ')
                : String(life.stage).replace(/_/g, ' ').toLowerCase()} /></div>
            )}
            {fund && (
              <div data-testid="options-fundamentals" style={{ marginTop: 6 }}>
                <Row k="Fundamentals." v={[fund.state, fund.latest_quarter_end ? `quarter ended ${fund.latest_quarter_end}` : null, fund.gross_margin_pct != null ? `gross margin ${fund.gross_margin_pct}%` : null, fund.operating_margin_pct != null ? `operating margin ${fund.operating_margin_pct}%` : null].filter(Boolean) as string[]} />
                {(fund.lines || []).map((l: string, i: number) => <div key={i} style={line}>{l}</div>)}
                {fund.filing_url && <a href={fund.filing_url} target="_blank" rel="noreferrer" style={{ ...line, color: TOKENS.info, display: 'inline-block' }}>filing ↗</a>}
              </div>
            )}
          </Collapsible>
        )}

        {novice && <div style={{ marginTop: 6 }}><WhatIfBox strategy={p.strategy} symbol={p.symbol} card={p} /></div>}
      </div>

      {reviewBar && <div style={{ marginTop: 8 }} onClick={e => e.stopPropagation()}>{reviewBar}</div>}

      <div style={{ marginTop: 6, display: 'flex', gap: 8, flexWrap: 'wrap', fontSize: TYPE.xs, color: TOKENS.text[3], ...numStyle }}>
        {x.generated_at && <span>generated {fmtIso(x.generated_at)}</span>}
        {x.quote_age_seconds != null && <span>· quote age {Math.round(Number(x.quote_age_seconds))}s</span>}
        {x.option_strategy_guid && <span title="Stable options identity (UUIDv5); attribution only">· {String(x.option_strategy_guid).slice(0, 8)}</span>}
      </div>
    </article>
  )
}
