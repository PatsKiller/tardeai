/**
 * Full Symbol Intelligence page (shadow) — hierarchy from prototype v1.
 * Zero provider calls. COMPLETE reviews require full provenance.
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

export default function SymbolIntelligencePage() {
  const { symbol = '' } = useParams()
  const sym = symbol.toUpperCase()
  const { data, loading, error } = useApi<any>(
    sym ? `/api/v3/watchlist/intelligence/${sym}` : '',
    120_000,
  )
  const body = data?.data && data.data.ok != null ? data.data : data
  const card = body?.card || {}
  const identity = body?.identity || {}
  const street = body?.street || card.street_consensus || {}
  const tradeAi = body?.trade_ai || {}
  const cio = body?.cio_review || {}
  const maria = body?.maria_review || {}
  const reviews = body?.reviews || []
  const cats = body?.catalysts?.timeline || []
  const rel = body?.relative_performance || {}
  const fund = body?.fundamentals || {}
  const tech = body?.technicals || {}
  const thesis = body?.thesis || {}
  const fresh = body?.freshness_matrix || {}
  const lineage = body?.evidence_lineage || {}
  const mechanics = body?.mechanics

  if (!sym) return <div style={{ color: BB.red }}>Missing symbol</div>
  if (loading) return <div style={{ color: BB.text3, fontSize: TYPE.sm }}>Loading {sym}…</div>
  if (error || body?.ok === false) {
    return <div style={{ color: BB.red, fontSize: TYPE.sm }}>Unavailable: {String(error || body?.error || 'error')}</div>
  }

  const periods = rel.periods || {}

  return (
    <div data-symbol-intelligence-page data-symbol={sym} data-provider-calls={String(body?.provider_calls ?? 0)}>
      <div style={{ marginBottom: 10 }}>
        <Link to="/watch?tab=intelligence" style={{ color: BB.text3, fontSize: TYPE.xs, textDecoration: 'none' }}>
          ← Intelligence Board
        </Link>
      </div>

      <div
        style={{
          border: `1px solid ${BB.border}`,
          background: BB.bgShift,
          color: BB.amber,
          borderRadius: 8,
          padding: '8px 10px',
          fontSize: TYPE.xs,
          marginBottom: 12,
        }}
      >
        <b>SHADOW Symbol Intelligence.</b> Street rating is primary research evidence; Trade AI owns actionability.
        Provider calls on this load: {body?.provider_calls ?? 0}.
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
              {card.freshness_state} · {card.price_source} · {card.market_session}
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 12 }}>
          <Pill tone="street">STREET {card.street_rating || 'NOT RATED'}
            {street.analyst_count != null ? ` · ${street.analyst_count} analysts` : ''}
          </Pill>
          <Pill>TRADE AI {tradeAi.primary_state || card.trade_ai_state}</Pill>
          <Pill>PROPOSAL {tradeAi.proposal_allowed || card.proposal_allowed ? 'YES' : 'NO'}</Pill>
          <Pill>CIO {cio.status === 'COMPLETE' ? (cio.verdict || 'COMPLETE') : 'NOT RUN'}</Pill>
        </div>
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
          <Panel title="Catalyst versus industry" sub="Company drivers vs backdrop">
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

function Panel({ title, sub, children, style }: { title: string; sub?: string; children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <section style={{ background: BB.bgPanel, border: `1px solid ${BB.border}`, borderRadius: 12, overflow: 'hidden', ...style }}>
      <div style={{ padding: '10px 12px', borderBottom: `1px solid ${BB.border}` }}>
        <div style={{ fontSize: TYPE.base, fontWeight: 900 }}>{title}</div>
        {sub && <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 2 }}>{sub}</div>}
      </div>
      <div style={{ padding: 12 }}>{children}</div>
    </section>
  )
}
function Pill({ children, tone }: { children: React.ReactNode; tone?: string }) {
  return (
    <span
      style={{
        border: `1px solid ${BB.border}`,
        borderRadius: 999,
        padding: '5px 9px',
        fontSize: TYPE.xs,
        fontWeight: 900,
        color: tone === 'street' ? BB.green : BB.text2,
      }}
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
