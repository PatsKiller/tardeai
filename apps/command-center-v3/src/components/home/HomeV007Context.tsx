// Home v007 — the additive "today's context" section.
//
// Self-fetching so the existing card props (and marketRisk.ts) are untouched: it reads the same
// GET /api/v2/market-risk/latest and renders only the optional `home_v007` block. Every fact shows its own state, and a
// fact that carries a clock and source shows both as plain text; unknown/missing/future says why; stale keeps the value
// with its age; not_applicable is labelled.
// Display only — no size, order or stop level, and no button where the contract says the decision is unavailable.
import { useApi } from '../../hooks/useApi'
import { RADIUS, TOKENS, TYPE, toneVars } from '../../lib/designTokens'
import {
  categoryLine, conflictLine, headlineLine, hedgeLine, marketStanceLine, nextEventLine, parseHomeV007, provenanceText,
  referenceLine, stateText, volumeLine, type Fact, type SymbolContext,
} from '../../lib/homeV007'
import { offersBudgetDecision } from '../../lib/budgetIntent'
import { fmtAsOf } from '../../lib/asOfDisplay'
import BudgetIntentControl from './BudgetIntentControl'

const PATH = '/api/v2/market-risk/latest'
const card: React.CSSProperties = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: 12, display: 'grid', gap: 8 }
const h4: React.CSSProperties = { margin: 0, fontSize: TYPE.sm, fontWeight: 800, color: TOKENS.text[0] }
const dim: React.CSSProperties = { fontSize: TYPE.xs, color: TOKENS.text[3] }
const small: React.CSSProperties = { fontSize: TYPE.sm, color: TOKENS.text[1] }

const money = (v: number | null) => (v == null ? null : `$${v.toLocaleString('en-US', { maximumFractionDigits: 2 })}`)
const pct = (v: number | null) => (v == null ? null : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`)

const provenance = provenanceText

function SymbolBlock({ s }: { s: SymbolContext }) {
  const q = s.quote
  const qState = stateText(q)
  return <div data-testid={`v7-symbol-${s.symbol}`} style={{ display: 'grid', gap: 3, padding: '6px 0', borderTop: `1px solid ${TOKENS.borderSubtle}` }}>
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'baseline' }}>
      <b style={{ color: TOKENS.text[0] }}>{s.symbol}</b>
      {qState
        ? <span data-testid={`v7-quote-${s.symbol}`} style={{ color: toneVars('warning').color, fontWeight: 600 }}>
            <>price {qState}{provenance(q)}</>
          </span>
        : <span data-testid={`v7-quote-${s.symbol}`} style={small}>
            <b style={{ color: TOKENS.text[0] }}>{money(q.price) ?? 'price unknown'}</b>
            {q.session ? ` · ${q.session}` : ''}{q.asOf ? ` · fetched ${fmtAsOf(q.asOf) ?? q.asOf}` : ''}{q.source ? ` · ${q.source}` : ''}{q.basis ? ` · ${q.basis}` : ''}{q.asOf ? ' · trade time unverified' : ''}{q.stale || (q.ageSeconds != null && q.ageSeconds >= 900) ? ' · stale' : ''}{q.ageSeconds != null && q.ageSeconds >= 300 ? ` · ${Math.round(q.ageSeconds / 60)}m old` : ''}
          </span>}
    </div>
    {(() => { const line = conflictLine(q); return line ? <div style={dim} data-testid={`v7-conflict-${s.symbol}`}>{line}</div> : null })()}
    {stateText(s.dayChange) ? <div style={dim}>day change {stateText(s.dayChange)}{provenance(s.dayChange)}</div>
      : <div style={dim}>today {money(s.dayChange.usd) ?? ''}{s.dayChange.pct != null ? ` (${pct(s.dayChange.pct)})` : ''}{s.dayChange.referenceDate ? ` vs ${s.dayChange.referenceDate} close` : ''}{provenance(s.dayChange)}</div>}
    {stateText(s.sinceExit) ? <div style={dim}>since exit {stateText(s.sinceExit)}{provenance(s.sinceExit)}</div>
      : <div style={dim}>since exit {money(s.sinceExit.usd) ?? ''}{s.sinceExit.pct != null ? ` (${pct(s.sinceExit.pct)})` : ''}{s.sinceExit.exitDate ? ` · exited ${s.sinceExit.exitDate}` : ''}{provenance(s.sinceExit)}</div>}
    {stateText(s.referencesFact) ? <div style={dim} data-testid={`v7-references-${s.symbol}`}>to trigger {stateText(s.referencesFact)}{provenance(s.referencesFact)}</div> : null}
    {s.references.map((r, i) => <div key={i} style={dim} data-testid={`v7-reference-${s.symbol}-${i}`}>{referenceLine(r)}</div>)}
    {s.headlines.length ? <div style={dim}>headlines: {s.headlines.map(headlineLine).join(' · ')}</div> : null}
    {(() => { const line = nextEventLine(s.nextEvent); return line ? <div style={dim} data-testid={`v7-next-event-${s.symbol}`}>{line}</div> : null })()}
    {stateText(s.cio) ? <div style={dim}>CIO stance {stateText(s.cio)}{provenance(s.cio)}</div>
      : <div style={dim}>CIO stance <b>{s.cio.stance}</b>{s.cio.conviction != null ? ` · conviction ${s.cio.conviction}` : ''}{provenance(s.cio)}</div>}
    {(() => { const line = marketStanceLine(s.marketStance); return line ? <div style={dim} data-testid={`v7-stance-${s.symbol}`}>{line}</div> : null })()}
    <div style={dim} data-testid={`v7-volume-${s.symbol}`}>{volumeLine(s.volume)}</div>
  </div>
}

export default function HomeV007Context() {
  // Background priority: Home already fetches this same endpoint for the card model, so this read yields to the
  // page's own requests instead of competing with them for the three shared slots (see useApi's fan-out note).
  const api = useApi<{ home_v007?: unknown }>(PATH, 60_000, { priority: 'background' })
  const v7 = parseHomeV007(api.data?.home_v007)
  if (!v7.present) return null
  // The producer's stated failure is not an empty success. It carries a reason, a remediation and the gaps that
  // explain it; the card says so and renders no symbol body over it.
  if (v7.unavailable) {
    return <section data-testid="home-v007-unavailable" style={card}>
      <h4 style={h4}>Today’s context is unavailable</h4>
      <div style={{ ...small, color: toneVars('warning').color }} data-testid="v7-unavailable-reason">
        {v7.blockReason ?? 'the producer marked the block unavailable without a stated reason'}
      </div>
      {v7.blockRemediation ? <div style={dim} data-testid="v7-unavailable-remediation">{v7.blockRemediation}</div> : null}
      {v7.gaps.map((g, i) => <div key={i} style={dim}>gap {g.member} · {g.key}{g.reason ? ` — ${g.reason}` : ''}</div>)}
      {v7.readErrors.map((e, i) => <div key={i} style={dim}>read error {e.member} · {e.code}</div>)}
    </section>
  }
  return <section data-testid="home-v007" style={card}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', alignItems: 'baseline' }}>
      <h4 style={h4}>Today’s context</h4>
      <span style={dim}>price, day change, since exit, next event, CIO stance, volume and risk categories show their clock and source when the payload supplies one; the quote clock is a fetch observation, not trade time</span>
    </div>
    {v7.symbols.map(s => <SymbolBlock key={s.symbol} s={s} />)}
    {v7.risk.categories.length ? <div style={dim}>
      risk score {v7.risk.score ?? 'unknown'} · {v7.risk.categories.map(c => `${categoryLine(c)}${provenance(c)}`).join(' · ')}
      {v7.risk.nextEvaluation?.at ? ` · next evaluation ${fmtAsOf(v7.risk.nextEvaluation.at) ?? v7.risk.nextEvaluation.at} (${v7.risk.nextEvaluation.basis ?? 'declared'})` : ''}
    </div> : null}
    {v7.hedge.triggers.length ? <div style={dim}>hedge: {v7.hedge.triggers.map(hedgeLine).join(' · ')}{v7.hedge.inverse.length ? ` · inverse today: ${v7.hedge.inverse.map(i => `${i.symbol} ${i.dayPct == null ? 'unknown' : pct(i.dayPct)}`).join(' · ')}` : ''}</div> : null}
    {v7.budgets.map(b => <div key={b.key} style={dim} data-testid={`v7-budget-${b.key}`}>
      budget {b.label}: {b.state === 'measured'
        ? <>{money(b.current) ?? 'unknown'} of {money(b.budget) ?? 'unknown'}{b.breach ? ' · breach' : ''}{b.clearsWhen ? ` · clears ${b.clearsWhen}` : ''}</>
        : <>{b.state === 'not_applicable' ? 'not applicable' : 'unknown'}{b.reason ? ` — ${b.reason}` : ''}{b.remediation ? ` · ${b.remediation}` : ''}</>}
      {b.decision.active
        ? ` · intentional${b.decision.intentionalUntil ? ` until ${fmtAsOf(b.decision.intentionalUntil) ?? b.decision.intentionalUntil}` : ''}${b.decision.actor ? ` · ${b.decision.actor}` : ''}${b.decision.receipt ? ` · receipt ${b.decision.receipt.slice(0, 8)}` : ''}${b.breach ? ' · breach still stands' : ''}${b.decision.history ? ` · ${b.decision.history} earlier` : ''}`
        : b.operatorDecision === 'unavailable'
          ? ` · intentional decision ${b.decisionRemediation ?? 'not available yet'}`
          : ' · intentional decision available to the operator'}
      {b.sourceAsOf || b.sourceSha || b.presentationSha
        ? ` · measured ${b.sourceAsOf ? (fmtAsOf(b.sourceAsOf) ?? b.sourceAsOf) : 'unknown'}${b.sourceSha ? ` · src ${b.sourceSha.slice(0, 8)}` : ''}${b.presentationSha ? ` · presentation ${b.presentationSha.slice(0, 8)}` : ''}`
        : ''}
      {offersBudgetDecision(b) ? <BudgetIntentControl row={b} onRecorded={() => api.refetch()} /> : null}
    </div>)}
    {v7.decisionHistory.complete === false ? <div style={dim} data-testid="v7-decision-history-partial">decision history is incomplete{typeof v7.decisionHistory.count === 'number' ? ` · ${v7.decisionHistory.count} in the ledger` : ''} — earlier decisions may be missing</div> : null}
    {v7.gaps.map((g, i) => <div key={i} style={dim}>gap {g.member} · {g.key}{g.reason ? ` — ${g.reason}` : ''}</div>)}
    {v7.readErrors.map((e, i) => <div key={i} style={dim}>read error {e.member} · {e.code}</div>)}
    <div style={dim}>Facts only. Nothing here is a size, an order or a stop level.</div>
  </section>
}
