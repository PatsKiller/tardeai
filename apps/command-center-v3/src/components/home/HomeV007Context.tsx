// Home v007 — the additive "today's context" section.
//
// Self-fetching so the existing card props (and marketRisk.ts) are untouched: it reads the same
// GET /api/v2/market-risk/latest and renders only the optional `home_v007` block. Every fact shows its own state,
// time and source; unknown/missing/future says why; stale keeps the value with its age; not_applicable is labelled.
// Display only — no size, order or stop level, and no button where the contract says the decision is unavailable.
import { useApi } from '../../hooks/useApi'
import { RADIUS, TOKENS, TYPE, toneVars } from '../../lib/designTokens'
import { parseHomeV007, type Fact, type SymbolContext } from '../../lib/homeV007'
import { fmtAsOf } from '../../lib/asOfDisplay'

const PATH = '/api/v2/market-risk/latest'
const card: React.CSSProperties = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: 12, display: 'grid', gap: 8 }
const h4: React.CSSProperties = { margin: 0, fontSize: TYPE.sm, fontWeight: 800, color: TOKENS.text[0] }
const dim: React.CSSProperties = { fontSize: TYPE.xs, color: TOKENS.text[3] }
const small: React.CSSProperties = { fontSize: TYPE.sm, color: TOKENS.text[1] }

const money = (v: number | null) => (v == null ? null : `$${v.toLocaleString('en-US', { maximumFractionDigits: 2 })}`)
const pct = (v: number | null) => (v == null ? null : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`)

function stateText(f: Fact): string | null {
  if (f.state === 'measured') return null
  if (f.state === 'not_applicable') return 'not applicable'
  const label = 'unknown'
  const bits = [f.reason, f.remediation].filter(Boolean).join(' · ')
  return `${label}${bits ? ` — ${bits}` : ''}`
}

function SymbolBlock({ s }: { s: SymbolContext }) {
  const q = s.quote
  const qState = stateText(q)
  return <div data-testid={`v7-symbol-${s.symbol}`} style={{ display: 'grid', gap: 3, padding: '6px 0', borderTop: `1px solid ${TOKENS.borderSubtle}` }}>
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'baseline' }}>
      <b style={{ color: TOKENS.text[0] }}>{s.symbol}</b>
      {qState
        ? <span data-testid={`v7-quote-${s.symbol}`} style={{ color: toneVars('warning').color, fontWeight: 600 }}>
            <>price {qState}</>
          </span>
        : <span data-testid={`v7-quote-${s.symbol}`} style={small}>
            <b style={{ color: TOKENS.text[0] }}>{money(q.price) ?? 'price unknown'}</b>
            {q.session ? ` · ${q.session}` : ''}{q.asOf ? ` · ${fmtAsOf(q.asOf) ?? q.asOf}` : ''}{q.source ? ` · ${q.source}` : ''}{q.basis ? ` · ${q.basis}` : ''}{q.ageSeconds != null && q.ageSeconds >= 900 ? ' · stale' : ''}{q.ageSeconds != null && q.ageSeconds >= 300 ? ` · ${Math.round(q.ageSeconds / 60)}m old` : ''}
          </span>}
    </div>
    {stateText(s.dayChange) ? <div style={dim}>day change {stateText(s.dayChange)}</div>
      : <div style={dim}>today {money(s.dayChange.usd) ?? ''}{s.dayChange.pct != null ? ` (${pct(s.dayChange.pct)})` : ''}{s.dayChange.referenceDate ? ` vs ${s.dayChange.referenceDate} close` : ''}</div>}
    {stateText(s.sinceExit) ? <div style={dim}>since exit {stateText(s.sinceExit)}</div>
      : <div style={dim}>since exit {money(s.sinceExit.usd) ?? ''}{s.sinceExit.pct != null ? ` (${pct(s.sinceExit.pct)})` : ''}{s.sinceExit.exitDate ? ` · exited ${s.sinceExit.exitDate}` : ''}</div>}
    {s.references.length ? <div style={dim}>to trigger: {s.references.map(r => `${r.label} ${r.distancePct != null ? pct(r.distancePct) : ''}${r.distanceUsd != null ? ` (${money(r.distanceUsd)})` : ''}`).join(' · ')}</div> : null}
    {s.headlines.length ? <div style={dim}>headlines: {s.headlines.map(h => `${h.title}${h.ageSeconds != null ? ` (${Math.round(h.ageSeconds / 3600)}h)` : ''}`).join(' · ')}</div> : null}
    {s.nextEvent.label || s.nextEvent.at ? <div style={dim}>next event {s.nextEvent.label ?? ''}{s.nextEvent.at ? ` · ${fmtAsOf(s.nextEvent.at) ?? s.nextEvent.at}` : ''}</div> : null}
    {stateText(s.cio) ? <div style={dim}>CIO stance {stateText(s.cio)}</div>
      : <div style={dim}>CIO stance <b>{s.cio.stance}</b>{s.cio.conviction != null ? ` · conviction ${s.cio.conviction}` : ''}{s.cio.storeLabel ? ` · ${s.cio.storeLabel}` : ''}{s.cio.ageSeconds != null ? ` · ${Math.round(s.cio.ageSeconds / 3600)}h old` : ''}{s.cio.stale ? ' · stale' : ''}</div>}
    {s.marketStance.value ? <div style={dim}>market-risk stance {s.marketStance.value} (separate from CIO)</div> : null}
    {stateText(s.volume) ? <div style={dim}>volume {stateText(s.volume)}</div>
      : <div style={dim}>volume {s.volume.ratio}× 20-day{s.volume.notTimeAdjusted ? ' (not time-adjusted)' : ''}</div>}
  </div>
}

export default function HomeV007Context() {
  const api = useApi<{ home_v007?: unknown }>(PATH, 60_000)
  const v7 = parseHomeV007(api.data?.home_v007)
  if (!v7.present) return null
  return <section data-testid="home-v007" style={card}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', alignItems: 'baseline' }}>
      <h4 style={h4}>Today’s context</h4>
      <span style={dim}>each line states its own time and source</span>
    </div>
    {v7.symbols.map(s => <SymbolBlock key={s.symbol} s={s} />)}
    {v7.risk.categories.length ? <div style={dim}>
      risk score {v7.risk.score ?? 'unknown'} · {v7.risk.categories.map(c => `${c.label} ${c.chip ?? c.state}`).join(' · ')}
      {v7.risk.nextEvaluation?.at ? ` · next evaluation ${fmtAsOf(v7.risk.nextEvaluation.at) ?? v7.risk.nextEvaluation.at} (${v7.risk.nextEvaluation.basis ?? 'declared'})` : ''}
    </div> : null}
    {v7.hedge.triggers.length ? <div style={dim}>hedge: {v7.hedge.triggers.map(t => `${t.label} ${t.current ?? '?'} of ${t.threshold ?? '?'}${t.met === true ? ' met' : t.met === false ? ' not met' : ''}`).join(' · ')}{v7.hedge.inverse.length ? ` · inverse today: ${v7.hedge.inverse.map(i => `${i.symbol} ${i.dayPct == null ? 'unknown' : pct(i.dayPct)}`).join(' · ')}` : ''}</div> : null}
    {v7.budgets.map(b => <div key={b.key} style={dim} data-testid={`v7-budget-${b.key}`}>
      budget {b.label}: {money(b.current) ?? 'unknown'} of {money(b.budget) ?? 'unknown'}{b.breach ? ' · breach' : ''}{b.clearsWhen ? ` · clears ${b.clearsWhen}` : ''}
      {b.decision.active
        ? ` · intentional${b.decision.intentionalUntil ? ` until ${fmtAsOf(b.decision.intentionalUntil) ?? b.decision.intentionalUntil}` : ''}${b.decision.actor ? ` · ${b.decision.actor}` : ''}${b.decision.receipt ? ` · receipt ${b.decision.receipt.slice(0, 8)}` : ''}${b.breach ? ' · breach still stands' : ''}${b.decision.history ? ` · ${b.decision.history} earlier` : ''}`
        : b.operatorDecision === 'unavailable'
          ? ` · intentional decision ${b.decisionRemediation ?? 'not available yet'}`
          : ' · intentional decision available to the operator'}
      {b.sourceAsOf || b.sourceSha || b.presentationSha
        ? ` · measured ${b.sourceAsOf ? (fmtAsOf(b.sourceAsOf) ?? b.sourceAsOf) : 'unknown'}${b.sourceSha ? ` · src ${b.sourceSha.slice(0, 8)}` : ''}${b.presentationSha ? ` · presentation ${b.presentationSha.slice(0, 8)}` : ''}`
        : ''}
    </div>)}
    {v7.decisionHistory.complete === false ? <div style={dim} data-testid="v7-decision-history-partial">decision history is incomplete{typeof v7.decisionHistory.count === 'number' ? ` · ${v7.decisionHistory.count} in the ledger` : ''} — earlier decisions may be missing</div> : null}
    {v7.gaps.map((g, i) => <div key={i} style={dim}>gap {g.member} · {g.key}{g.reason ? ` — ${g.reason}` : ''}</div>)}
    {v7.readErrors.map((e, i) => <div key={i} style={dim}>read error {e.member} · {e.code}</div>)}
    <div style={dim}>Facts only. Nothing here is a size, an order or a stop level.</div>
  </section>
}
