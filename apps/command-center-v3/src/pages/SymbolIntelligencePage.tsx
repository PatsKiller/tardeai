/**
 * Symbol Intelligence dossier — watch-intelligence detail + CIO journal / queue / timeline.
 * READ_ONLY_ADVISORY. Zero new provider calls beyond existing APIs.
 */
import { Link, useParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { BB, TYPE } from '../lib/watchTokens'

function money(n?: number | null) {
  if (n == null || !Number.isFinite(Number(n))) return '—'
  return `$${Number(n).toFixed(2)}`
}
function pct(n?: number | null) {
  if (n == null || !Number.isFinite(Number(n))) return '—'
  const v = Number(n)
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
}

function formatWaitHuman(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m`
  if (s < 86400) {
    const h = Math.floor(s / 3600)
    const m = Math.floor((s % 3600) / 60)
    return m > 0 ? `${h}h ${m}m` : `${h}h`
  }
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  return h > 0 ? `${d}d ${h}h` : `${d}d`
}

/** Prefer API research_queue summary; else derive from active_research[].created_at. */
function deriveResearchQueue(cioBody: any): {
  open_count: number
  oldest_wait_seconds: number | null
  oldest_wait_human: string
  source: 'summary' | 'active_research' | 'empty'
} {
  const rq = cioBody?.research_queue && typeof cioBody.research_queue === 'object'
    ? cioBody.research_queue
    : null
  if (rq != null && rq.open_count != null && Number.isFinite(Number(rq.open_count))) {
    const open = Math.max(0, Math.floor(Number(rq.open_count)))
    let oldestSec: number | null = null
    if (rq.oldest_wait_seconds != null && Number.isFinite(Number(rq.oldest_wait_seconds))) {
      oldestSec = Math.max(0, Math.floor(Number(rq.oldest_wait_seconds)))
    }
    const human = (rq.oldest_wait_human != null && String(rq.oldest_wait_human).trim())
      ? String(rq.oldest_wait_human).trim()
      : (oldestSec != null ? formatWaitHuman(oldestSec) : '')
    return {
      open_count: open,
      oldest_wait_seconds: oldestSec,
      oldest_wait_human: human,
      source: 'summary',
    }
  }

  const activeRaw =
    (Array.isArray(rq?.active_research) && rq.active_research)
    || (Array.isArray(cioBody?.active_research) && cioBody.active_research)
    || (Array.isArray(cioBody?.intelligence?.active_research) && cioBody.intelligence.active_research)
    || []
  const now = Date.now()
  let oldestSec: number | null = null
  for (const item of activeRaw) {
    if (!item || typeof item !== 'object') continue
    const ca = (item as any).created_at
    if (ca == null) continue
    const t = Date.parse(String(ca))
    if (!Number.isFinite(t)) continue
    const age = Math.max(0, Math.floor((now - t) / 1000))
    if (oldestSec == null || age > oldestSec) oldestSec = age
  }
  return {
    open_count: activeRaw.length,
    oldest_wait_seconds: oldestSec,
    oldest_wait_human: oldestSec != null ? formatWaitHuman(oldestSec) : '',
    source: activeRaw.length ? 'active_research' : 'empty',
  }
}

function formatHistoryRow(row: unknown): string {
  if (row == null) return ''
  if (typeof row === 'string') return row
  if (typeof row !== 'object') return String(row)
  const o = row as Record<string, unknown>
  const ver = o.thesis_version != null ? `v${o.thesis_version}`
    : (o.version != null ? `v${o.version}` : null)
  const when = o.published_at != null
    ? String(o.published_at).slice(0, 10)
    : (o.ts != null ? String(o.ts).slice(0, 10) : (o.as_of != null ? String(o.as_of).slice(0, 10) : null))
  const reason = o.reason_for_change || o.summary || o.stance || o.state
  return [ver, when, reason != null ? String(reason) : null].filter(Boolean).join(' · ')
}

export default function SymbolIntelligencePage() {
  const { symbol = '' } = useParams()
  const sym = symbol.toUpperCase()
  // Canonical Data Broker detail — not page-specific joins
  const { data, loading, error } = useApi<any>(
    sym ? `/api/v3/data-broker/watch-intelligence/${sym}` : '',
    120_000,
  )
  // CIO dossier extras (journal / queue / timeline) — fail-soft; never blocks watch detail
  const {
    data: cioRaw,
    loading: cioLoading,
    error: cioError,
  } = useApi<any>(
    sym ? `/api/v3/cio/intelligence/${encodeURIComponent(sym)}` : '',
    120_000,
  )

  const body = data?.data && data.data.ok != null ? data.data : data
  const detail = body?.detail || body || {}
  const card = body?.card || detail.card || {}
  const identity = detail.identity || {}
  const street = detail.street || card.street_consensus || {}
  const tradeAi = detail.trade_ai || {}
  const cio = detail.cio_review || card.cio_review || {}
  const maria = detail.maria_review || card.maria_review || {}
  const reviews = detail.reviews || []
  const cats = detail.catalysts?.timeline || []
  const rel = detail.relative_performance || {}
  const fund = detail.fundamentals || {}
  const tech = detail.technicals || {}
  const thesis = detail.thesis || {}
  const fresh = detail.freshness_matrix || {}
  const lineage = detail.evidence_lineage || {}
  const mechanics = detail.mechanics

  const cioBody = (() => {
    if (!cioRaw || typeof cioRaw !== 'object') return null
    const wrapped = (cioRaw as any).data && (cioRaw as any).data.ok != null ? (cioRaw as any).data : cioRaw
    if ((cioRaw as any).ok === false && !wrapped?.intelligence && !wrapped?.journal) return null
    return wrapped
  })()
  const intelObj = (cioBody?.intelligence && typeof cioBody.intelligence === 'object')
    ? cioBody.intelligence
    : null
  const journal: any[] = Array.isArray(cioBody?.journal) ? cioBody.journal : []
  const latestFeedback = cioBody?.latest_feedback && typeof cioBody.latest_feedback === 'object'
    ? cioBody.latest_feedback
    : null
  const queue = cioBody ? deriveResearchQueue(cioBody) : null
  const thesisBlock = (intelObj?.thesis && typeof intelObj.thesis === 'object') ? intelObj.thesis : null
  const thesisHistory: unknown[] = Array.isArray(cioBody?.thesis_history)
    ? cioBody.thesis_history
    : (Array.isArray(intelObj?.thesis_history) ? intelObj.thesis_history : [])
  const conviction =
    thesisBlock?.confidence_0_10
    ?? thesisBlock?.conviction
    ?? thesisBlock?.confidence
    ?? intelObj?.confidence_0_10
    ?? intelObj?.conviction
    ?? null

  if (!sym) return <div style={{ color: BB.red }}>Missing symbol</div>
  if (loading) return <div style={{ color: BB.text3, fontSize: TYPE.sm }}>Loading {sym}…</div>
  if (error || body?.ok === false) {
    return <div style={{ color: BB.red, fontSize: TYPE.sm }}>Unavailable: {String(error || body?.error || 'error')}</div>
  }

  const periods = rel.periods || {}

  const queueChipLabel = (() => {
    if (cioLoading && !cioBody) return 'RESEARCH QUEUE …'
    if (!queue) return 'RESEARCH QUEUE —'
    if (queue.open_count <= 0) return 'RESEARCH QUEUE idle'
    const wait = queue.oldest_wait_human || (queue.oldest_wait_seconds != null ? formatWaitHuman(queue.oldest_wait_seconds) : '')
    return wait
      ? `RESEARCH QUEUE ${queue.open_count} open · oldest ${wait}`
      : `RESEARCH QUEUE ${queue.open_count} open`
  })()
  const queueChipAttr = (() => {
    if (cioLoading && !cioBody) return 'loading'
    if (!queue) return cioError ? 'unavailable' : 'idle'
    if (queue.open_count <= 0) return 'idle'
    return String(queue.open_count)
  })()

  return (
    <div data-symbol-intelligence-page data-symbol={sym} data-provider-calls={String(body?.provider_calls ?? 0)}>
      <div style={{ marginBottom: 10, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <Link to="/watch?tab=intelligence" style={{ color: BB.text3, fontSize: TYPE.xs, textDecoration: 'none' }}>
          ← Intelligence Board
        </Link>
        <Link to="/cio" style={{ color: BB.text3, fontSize: TYPE.xs, textDecoration: 'none' }}>
          CIO hub
        </Link>
      </div>

      <div
        style={{
          border: `1px solid ${BB.border}`,
          background: BB.bgShift,
          color: BB.text2,
          borderRadius: 8,
          padding: '8px 10px',
          fontSize: TYPE.xs,
          marginBottom: 12,
        }}
        data-si-advisory-banner
      >
        Symbol Intelligence dossier · READ_ONLY_ADVISORY · Street is evidence; Trade AI owns actionability.
        {' '}Provider calls on this load: {body?.provider_calls ?? 0}.
      </div>

      <section
        style={{
          background: BB.bgPanel,
          border: `1px solid ${BB.border}`,
          borderRadius: 14,
          padding: 16,
        }}
        data-hero
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 28, fontWeight: 950, color: BB.text0 }}>{sym}</div>
            <div style={{ fontSize: TYPE.md, color: BB.text2, marginTop: 2 }}>{card.company}</div>
            <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 4 }}>
              {card.sector} · {card.industry} · {card.instrument_type || 'equity'}
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 24, fontWeight: 950 }}>{money(card.last)}</div>
            <div style={{ fontSize: TYPE.sm, fontWeight: 900, color: Number(card.day_change_pct) >= 0 ? BB.green : BB.red }}>
              {pct(card.day_change_pct)}
            </div>
            <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 4 }}>
              Quote: {card.quote_freshness || card.freshness_state || '—'} · {card.price_source} · {card.market_session}
            </div>
            <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 2 }}>
              Technicals: {card.technical_freshness || '—'} · Decision: {card.decision_freshness || '—'} · Street: {card.street_freshness || '—'} · Reviews: {card.review_freshness || '—'}
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 12 }}>
          <Pill tone="street">STREET {card.street_rating || 'NOT RATED'}
            {street.analyst_count != null ? ` · ${street.analyst_count} analysts` : ''}
          </Pill>
          <Pill>TRADE AI {tradeAi.primary_state || card.trade_ai_state}</Pill>
          <Pill>PROPOSAL {tradeAi.proposal_allowed || card.proposal_allowed ? 'YES' : 'NO'}</Pill>
          <Pill>
            CIO {cio.status === 'COMPLETE' ? (cio.verdict || 'COMPLETE') : `NOT RUN${cio.reason_code ? ` · ${cio.reason_code}` : ''}`}
          </Pill>
          <Pill>
            Maria {maria.status === 'COMPLETE' ? (maria.verdict || 'COMPLETE') : `NOT RUN${maria.reason_code ? ` · ${maria.reason_code}` : ''}`}
          </Pill>
          <Pill
            tone={queue && queue.open_count > 0 ? 'queue' : undefined}
            dataAttr={{ 'data-research-queue': queueChipAttr }}
          >
            {queueChipLabel}
          </Pill>
        </div>
        {card.decision_input_price != null && card.current_quote != null && Number(card.decision_input_price) !== Number(card.current_quote) ? (
          <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 8 }} data-decision-vs-quote>
            Decision input {money(Number(card.decision_input_price))}
            {card.decision_input_as_of ? ` @ ${card.decision_input_as_of}` : ''}
            {' · '}
            Quote {money(Number(card.current_quote))}
            {card.current_quote_as_of ? ` @ ${card.current_quote_as_of}` : ''}
          </div>
        ) : null}
      </section>

      <div style={{ display: 'grid', gridTemplateColumns: '1.15fr .85fr', gap: 12, marginTop: 12 }}>
        <div>
          <Panel title="What the company does" sub="Canonical company profile">
            <div style={{ fontSize: TYPE.sm, color: BB.text1, lineHeight: 1.45 }} data-company-description>
              {identity.what_the_company_does || identity.description || card.company_summary || 'Description unavailable — typed data gap.'}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 10 }}>
              <Fact k="Business model" v={identity.business_model || 'Not in profile (gap)'} />
              <Fact k="Industry position" v={card.industry || '—'} />
              <Fact k="Instrument" v={card.instrument_type || '—'} />
              <Fact k="Economic sensitivity" v={identity.economic_sensitivity || 'Not in profile (gap)'} />
            </div>
          </Panel>

          <Panel title="Investment decision" sub="Street rating is primary; Trade AI determines actionability" style={{ marginTop: 12 }}>
            <div style={{ fontSize: TYPE.md, fontWeight: 900, lineHeight: 1.4 }}>{card.one_line_thesis || tradeAi.operator_meaning}</div>
            <div style={{ marginTop: 10, background: BB.bgShift, border: `1px solid ${BB.border}`, borderRadius: 10, padding: 10 }}>
              <div style={{ fontSize: TYPE.xs, color: BB.text3, fontWeight: 900, textTransform: 'uppercase' }}>Do this next</div>
              <div style={{ fontSize: TYPE.sm, color: BB.text1, marginTop: 4 }}>{card.next_operator_action || tradeAi.allowed_action_now || '—'}</div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 7, marginTop: 10 }}>
              <Level n={card.support} l="Support" />
              <Level n={card.resistance} l="Resistance" />
              <Level n={mechanics ? 'Valid' : 'Hidden'} l="Mechanics" />
              <Level n={tradeAi.proposal_allowed ? 'YES' : 'NO'} l="Proposal" />
            </div>
            {mechanics && (
              <pre style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 8, whiteSpace: 'pre-wrap' }}>
                {JSON.stringify(mechanics, null, 2)}
              </pre>
            )}
            {!mechanics && (
              <div style={{ fontSize: TYPE.xs, color: BB.amber, marginTop: 8 }}>
                Current mechanics hidden — state is non-READY or proposal-ineligible (deterministic).
              </div>
            )}
          </Panel>

          <Panel title="CIO and agent reviews" sub="Visible summary first; full provenance below" style={{ marginTop: 12 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <ReviewBlock title="CIO" rev={cio} />
              <ReviewBlock title="Maria / research" rev={maria} />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 8 }}>
              <Fact k="What changes the decision" v={thesis.what_changes_the_decision || '—'} />
              <Fact k="Counter-thesis" v={thesis.counter_thesis || 'No COMPLETE counter-thesis artifact'} />
            </div>
            <details style={{ marginTop: 10, border: `1px solid ${BB.border}`, borderRadius: 8, padding: 8, background: BB.bgShift }}>
              <summary style={{ cursor: 'pointer', fontSize: TYPE.xs, fontWeight: 900 }}>All review artifacts + provenance</summary>
              <div style={{ marginTop: 8, display: 'grid', gap: 8 }}>
                {reviews.map((r: any) => (
                  <ReviewBlock key={r.agent_id} title={String(r.agent_id).toUpperCase()} rev={r} full />
                ))}
              </div>
            </details>
          </Panel>

          <Panel title="Operator journal" sub="Feedback intents from Command Center / Telegram" style={{ marginTop: 12 }} dataAttr={{ 'data-operator-journal': '1' }}>
            {cioLoading && !cioBody && (
              <div style={{ fontSize: TYPE.sm, color: BB.text3 }}>Loading journal…</div>
            )}
            {!cioLoading && !cioBody && (
              <div style={{ fontSize: TYPE.sm, color: BB.text3 }}>
                {cioError ? 'CIO intelligence unavailable — journal not loaded.' : 'No operator feedback yet.'}
              </div>
            )}
            {cioBody && journal.length === 0 && !latestFeedback && (
              <div style={{ fontSize: TYPE.sm, color: BB.text3 }}>No operator feedback yet.</div>
            )}
            {latestFeedback?.intent && (
              <div
                style={{
                  background: BB.bgShift,
                  border: `1px solid ${BB.amber}`,
                  borderRadius: 8,
                  padding: 10,
                  marginBottom: journal.length ? 10 : 0,
                }}
                data-latest-feedback
              >
                <div style={{ fontSize: TYPE.xs, color: BB.amber, fontWeight: 900, textTransform: 'uppercase' }}>
                  Latest feedback
                </div>
                <div style={{ fontSize: TYPE.sm, color: BB.text1, marginTop: 4 }}>
                  <b>{String(latestFeedback.intent)}</b>
                  {latestFeedback.stance ? ` · ${latestFeedback.stance}` : ''}
                  {latestFeedback.ts ? ` · ${String(latestFeedback.ts).slice(0, 19)}` : ''}
                </div>
                {latestFeedback.free_text ? (
                  <div style={{ fontSize: TYPE.xs, color: BB.text2, marginTop: 4 }}>{String(latestFeedback.free_text)}</div>
                ) : null}
              </div>
            )}
            {journal.length > 0 && (
              <div style={{ display: 'grid', gap: 8 }}>
                {[...journal].reverse().map((row: any, i: number) => {
                  const isLatest = latestFeedback
                    && row?.intent === latestFeedback.intent
                    && String(row?.ts || '') === String(latestFeedback.ts || '')
                  return (
                    <div
                      key={row?.id || `${row?.ts || i}-${row?.intent || i}`}
                      style={{
                        background: BB.bgShift,
                        border: `1px solid ${isLatest ? BB.amber : BB.border}`,
                        borderRadius: 8,
                        padding: 8,
                      }}
                      data-journal-entry
                    >
                      <div style={{ fontSize: TYPE.sm, color: BB.text1 }}>
                        <b>{String(row?.intent || '—')}</b>
                        {row?.stance ? ` · ${row.stance}` : ''}
                        {row?.ts ? ` · ${String(row.ts).slice(0, 19)}` : ''}
                      </div>
                      {row?.free_text ? (
                        <div style={{ fontSize: TYPE.xs, color: BB.text2, marginTop: 3 }}>{String(row.free_text)}</div>
                      ) : null}
                    </div>
                  )
                })}
              </div>
            )}
          </Panel>

          <Panel title="Fundamentals and valuation" sub="Company fields; industry medians may be missing" style={{ marginTop: 12 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  {['Metric', 'Value', 'Note'].map(h => (
                    <th key={h} style={{ textAlign: 'left', fontSize: TYPE.xs, color: BB.text3, padding: 8, borderBottom: `1px solid ${BB.border}` }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.entries(fund.fields || {}).map(([k, v]) => (
                  <tr key={k}>
                    <td style={td}>{k}</td>
                    <td style={td}>{v == null ? '—' : String(v)}</td>
                    <td style={td}>{fund.note || ''}</td>
                  </tr>
                ))}
                {fund.applicability === 'fund_fields' && (
                  <tr><td style={td} colSpan={3}>Instrument uses fund-specific fields (equity multiples not forced).</td></tr>
                )}
              </tbody>
            </table>
          </Panel>
        </div>

        <div>
          <Panel title="Thesis timeline" sub="Conviction / history from CIO intelligence when present" dataAttr={{ 'data-thesis-timeline': '1' }}>
            {cioLoading && !cioBody && (
              <div style={{ fontSize: TYPE.sm, color: BB.text3 }}>Loading thesis timeline…</div>
            )}
            {!cioLoading && !cioBody && (
              <div style={{ fontSize: TYPE.sm, color: BB.text3 }}>
                {cioError
                  ? 'CIO intelligence unavailable — thesis timeline not loaded.'
                  : 'No thesis timeline artifact yet (typed gap).'}
              </div>
            )}
            {cioBody && (
              <>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                  <Fact
                    k="Thesis state"
                    v={String(thesisBlock?.state || intelObj?.thesis_state || '—')}
                  />
                  <Fact
                    k="Conviction / confidence"
                    v={
                      conviction == null || conviction === ''
                        ? 'Not on intelligence payload (typed gap)'
                        : (typeof conviction === 'number'
                          ? (conviction <= 10 ? `${Number(conviction).toFixed(1)}/10` : String(conviction))
                          : String(conviction))
                    }
                  />
                </div>
                {(thesisBlock?.summary || intelObj?.headline) && (
                  <div style={{ fontSize: TYPE.sm, color: BB.text1, marginTop: 10, lineHeight: 1.45 }}>
                    {String(thesisBlock?.summary || intelObj?.headline)}
                  </div>
                )}
                {thesisBlock?.version != null && (
                  <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 6 }}>
                    Version {String(thesisBlock.version)}
                    {thesisBlock.role ? ` · role ${String(thesisBlock.role)}` : ''}
                  </div>
                )}
                {thesisHistory.length > 0 ? (
                  <ul style={{ margin: '10px 0 0', paddingLeft: 16, fontSize: TYPE.sm, color: BB.text1 }}>
                    {thesisHistory.slice(0, 8).map((row, i) => (
                      <li key={i} style={{ marginBottom: 4 }}>{formatHistoryRow(row) || '—'}</li>
                    ))}
                  </ul>
                ) : (
                  <div style={{ fontSize: TYPE.sm, color: BB.text3, marginTop: 10 }}>
                    No thesis history rows on intelligence payload (typed gap).
                  </div>
                )}
              </>
            )}
          </Panel>

          <Panel title="Catalyst versus industry" sub="Company drivers vs backdrop" style={{ marginTop: 12 }}>
            {(cats as any[]).length === 0 && <div style={{ fontSize: TYPE.sm, color: BB.text3 }}>No recent catalyst_events</div>}
            {(cats as any[]).map((c, i) => (
              <div key={i} style={{ display: 'grid', gridTemplateColumns: '72px 1fr', gap: 8, marginBottom: 8 }}>
                <div style={{ fontSize: TYPE.xs, color: BB.text2, fontWeight: 900 }}>{c.type || 'event'}</div>
                <div style={{ fontSize: TYPE.sm, color: BB.text1 }}>{c.headline}</div>
              </div>
            ))}
            <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 6 }}>{body?.catalysts?.versus_industry || card.catalyst_vs_industry || '—'}</div>
          </Panel>

          <Panel title="Relative performance" sub="1D–1Y company periods" style={{ marginTop: 12 }}>
            {(['1D', '1W', '1M', '3M', '6M', 'YTD', '1Y'] as const).map(p => (
              <Bar key={p} label={p} value={periods[p]} />
            ))}
            <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 8 }}>
              Versus industry / sector / SPY: not joined in shadow (typed gap). Summary: {rel.summary || '—'}
            </div>
          </Panel>

          <Panel title="Technical structure" sub="Deterministic evidence only" style={{ marginTop: 12 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <Fact k="Trend" v={tech.trend || '—'} />
              <Fact k="RSI / RVOL" v={`RSI ${tech.rsi ?? '—'} · RVOL ${tech.rvol ?? '—'}`} />
              <Fact k="Support" v={tech.support != null ? String(tech.support) : '—'} />
              <Fact k="Resistance" v={tech.resistance != null ? String(tech.resistance) : '—'} />
              <Fact k="ATR" v={tech.atr != null ? String(tech.atr) : '—'} />
              <Fact k="Setup" v={tech.setup || '—'} />
            </div>
          </Panel>

          <Panel title="Risks and counter-thesis" style={{ marginTop: 12 }}>
            {(thesis.risks || []).length === 0 && <div style={{ fontSize: TYPE.sm, color: BB.text3 }}>No COMPLETE risk list — primary risk: {card.primary_risk || '—'}</div>}
            {(thesis.risks || []).map((r: string, i: number) => (
              <div key={i} style={{ borderLeft: `2px solid ${BB.red}`, paddingLeft: 8, margin: '8px 0', fontSize: TYPE.sm, color: BB.text1 }}>{r}</div>
            ))}
          </Panel>

          <Panel title="Freshness and lineage" style={{ marginTop: 12 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <tbody>
                {Object.entries(fresh).map(([k, v]) => (
                  <tr key={k}>
                    <td style={td}>{k}</td>
                    <td style={td}>{v == null ? '—' : String(v)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <details style={{ marginTop: 8 }}>
              <summary style={{ fontSize: TYPE.xs, fontWeight: 900, cursor: 'pointer' }}>Immutable evidence lineage</summary>
              <pre style={{ fontSize: TYPE.xs, color: BB.text3, whiteSpace: 'pre-wrap' }}>{JSON.stringify(lineage, null, 2)}</pre>
            </details>
          </Panel>
        </div>
      </div>
    </div>
  )
}

const td: React.CSSProperties = {
  padding: 8,
  borderBottom: `1px solid ${BB.border}`,
  fontSize: TYPE.xs,
  color: BB.text1,
}

function Panel({
  title,
  sub,
  children,
  style,
  dataAttr,
}: {
  title: string
  sub?: string
  children: React.ReactNode
  style?: React.CSSProperties
  dataAttr?: Record<string, string>
}) {
  return (
    <section
      style={{ background: BB.bgPanel, border: `1px solid ${BB.border}`, borderRadius: 12, overflow: 'hidden', ...style }}
      {...dataAttr}
    >
      <div style={{ padding: '10px 12px', borderBottom: `1px solid ${BB.border}` }}>
        <div style={{ fontSize: TYPE.base, fontWeight: 900 }}>{title}</div>
        {sub && <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 2 }}>{sub}</div>}
      </div>
      <div style={{ padding: 12 }}>{children}</div>
    </section>
  )
}
function Pill({
  children,
  tone,
  dataAttr,
}: {
  children: React.ReactNode
  tone?: string
  dataAttr?: Record<string, string>
}) {
  return (
    <span
      style={{
        border: `1px solid ${BB.border}`,
        borderRadius: 999,
        padding: '5px 9px',
        fontSize: TYPE.xs,
        fontWeight: 900,
        color: tone === 'street' ? BB.green : tone === 'queue' ? BB.amber : BB.text2,
      }}
      {...dataAttr}
    >
      {children}
    </span>
  )
}
function Fact({ k, v }: { k: string; v: string }) {
  return (
    <div style={{ background: BB.bgShift, border: `1px solid ${BB.border}`, borderRadius: 8, padding: 8 }}>
      <div style={{ fontSize: TYPE.xs, color: BB.text3, textTransform: 'uppercase', fontWeight: 850 }}>{k}</div>
      <div style={{ fontSize: TYPE.sm, color: BB.text1, marginTop: 3, lineHeight: 1.4 }}>{v}</div>
    </div>
  )
}
function Level({ n, l }: { n: any; l: string }) {
  return (
    <div style={{ background: BB.bgShift, border: `1px solid ${BB.border}`, borderRadius: 8, padding: 8 }}>
      <div style={{ fontSize: TYPE.md, fontWeight: 900 }}>{n == null || n === '' ? '—' : String(n)}</div>
      <div style={{ fontSize: TYPE.xs, color: BB.text3, textTransform: 'uppercase', marginTop: 2 }}>{l}</div>
    </div>
  )
}
function Bar({ label, value }: { label: string; value?: number | null }) {
  const v = value == null ? null : Number(value)
  const width = v == null ? 0 : Math.min(100, Math.abs(v) * 2)
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '48px 1fr 52px', gap: 8, alignItems: 'center', margin: '6px 0', fontSize: TYPE.xs, color: BB.text3 }}>
      <span>{label}</span>
      <div style={{ height: 7, background: BB.bgShift, borderRadius: 99, overflow: 'hidden', border: `1px solid ${BB.border}` }}>
        <div style={{ height: '100%', width: `${width}%`, background: BB.text2 }} />
      </div>
      <b style={{ color: v == null ? BB.text3 : v >= 0 ? BB.green : BB.red }}>{v == null ? '—' : pct(v)}</b>
    </div>
  )
}
function ReviewBlock({ title, rev, full }: { title: string; rev: any; full?: boolean }) {
  const complete = rev?.status === 'COMPLETE'
  return (
    <div
      style={{ background: BB.bgShift, border: `1px solid ${BB.border}`, borderRadius: 10, padding: 10 }}
      data-review-block
      data-review-status={rev?.status || 'NOT_RUN'}
      data-review-model={complete ? String(rev?.model || '') : 'NONE'}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
        <div>
          <div style={{ fontSize: TYPE.sm, fontWeight: 900 }}>{title}</div>
          <div style={{ fontSize: TYPE.xs, color: BB.text3 }}>
            {complete
              ? `${rev.provider} · ${rev.model} · ${rev.executed_policy || rev.policy}`
              : 'Provider NONE · Model NONE · Policy NO_CALL'}
          </div>
        </div>
        <span style={{ fontSize: TYPE.xs, color: complete ? BB.green : BB.amber, fontWeight: 900 }}>
          {complete ? 'COMPLETE' : rev?.reason_code || 'NOT RUN'}
        </span>
      </div>
      {complete ? (
        <div style={{ fontSize: TYPE.sm, color: BB.text1, marginTop: 8, lineHeight: 1.45 }}>{rev.summary || rev.verdict || '—'}</div>
      ) : (
        <div style={{ fontSize: TYPE.sm, color: BB.amber, marginTop: 8, fontWeight: 800 }}>
          Cost $0 · {rev?.reason_code || 'NOT_SCHEDULED'}
        </div>
      )}
      {full && complete && (
        <pre style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 8, whiteSpace: 'pre-wrap' }}>
{`process_id=${rev.process_id}
artifact_id=${rev.artifact_id}
artifact_hash=${rev.artifact_hash}
input_hash=${rev.input_hash}
request_id=${rev.provider_request_id}
tokens=${rev.prompt_tokens}/${rev.completion_tokens}
cost=${rev.estimated_cost_usd}
fallback=${rev.fallback_used}
reconciliation=${rev.reconciliation_status}`}
        </pre>
      )}
      {full && !complete && rev?.legacy_summary_snip && (
        <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 6 }}>
          Legacy incomplete row snip (not COMPLETE): {rev.legacy_summary_snip}
        </div>
      )}
    </div>
  )
}
