/** Ticker Prospectus — institutional blocks (approved mockup prospectus/v001, operator 2026-10-26 "approved push live").
 *  Every block is computed by the backend from house data; each renders from its own JSON block and, when the block
 *  is absent or empty, a compact "not available yet" row — never a crash and never an invented number.
 *  Colours: tokens (CSS vars) for chrome; CHART_HEX for recharts props, which cannot read CSS vars. */
import { useState, type ReactNode } from 'react'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { CHART_HEX, RADIUS, TOKENS, TYPE } from '../../lib/designTokens'
import { useTheme } from '../../hooks/useTheme'
import {
  RET_COLUMNS, RET_COLUMNS_PHONE, benchName, coverageTone, domainLabel, fmtNum, peerCell, peerColumns, pct, relRows,
  relWindows, signTone, toNumber, verdictTiles, whenEt,
  type CoverageDomain, type ProspectusBlocks, type ProspectusDoc, type ScenarioCase,
} from '../../lib/prospectusModel'

export function NotAvailable({ what, gaps, testId }: { what: string; gaps?: string[] | null; testId?: string }) {
  return (
    <div className="psp-na" data-testid={testId ?? 'prospectus-na'}>
      <span className="psp-na-dot" aria-hidden="true" />
      <span>{what}: not available yet{gaps && gaps.length ? <span className="psp-muted"> — {gaps[0]}</span> : null}</span>
    </div>
  )
}

export function Card({ title, tone, children, testId, label, className }: { title: ReactNode; tone?: string; children: ReactNode; testId?: string; label?: string; className?: string }) {
  return (
    <section className={`psp-card${className ? ` ${className}` : ''}`} data-testid={testId} aria-label={label}>
      <h2 className={`psp-card-title${tone ? ` psp-tone-${tone}` : ''}`}>{title}</h2>
      {children}
    </section>
  )
}

function Kv({ rows }: { rows: Array<[string, ReactNode, string?]> }) {
  return (
    <div className="psp-kv">
      {rows.map(([k, v, tone], i) => (
        <div key={i} className="psp-kv-row"><span className="psp-kv-k">{k}</span><span className={`psp-kv-v${tone ? ` psp-tone-${tone}` : ''}`}>{v}</span></div>
      ))}
    </div>
  )
}

const dash = (v: unknown) => (v == null || v === '' ? '—' : String(v))

// ── Verdict tiles ──────────────────────────────────────────────────────────────────────────────────────────────────
export function VerdictTiles({ doc }: { doc: ProspectusDoc }) {
  const tiles = verdictTiles(doc)
  return (
    <section className="psp-tiles" aria-label="Verdict" data-testid="prospectus-tiles">
      {tiles.map(t => (
        <div key={t.id} className={`psp-tile psp-tile-${t.id}${t.id === 'verdict' && t.value ? ` psp-tile-verdict-${t.tone}` : ''}`} data-testid={`prospectus-tile-${t.id}`}>
          <div className="psp-tile-k">{t.label}</div>
          {t.value
            ? <div className={`psp-tile-v${t.id === 'verdict' ? ` psp-tone-${t.tone}` : ''}`}>{t.value}</div>
            : <div className="psp-tile-v psp-tile-na">not available yet</div>}
          {t.sub && <div className={`psp-tile-sub${t.id !== 'verdict' && t.tone !== 'neutral' ? ` psp-tone-${t.tone}` : ''}`}>{t.sub}</div>}
        </div>
      ))}
    </section>
  )
}

// ── Relative performance ──────────────────────────────────────────────────────────────────────────────────────────
export function RelativePerformanceBlock({ blocks, symbol, phone }: { blocks?: ProspectusBlocks; symbol: string; phone: boolean }) {
  const rel = blocks?.relative_performance
  const [, , theme] = useTheme()
  const hex = CHART_HEX[theme]
  const wins = relWindows(rel)
  const [win, setWin] = useState<string>(wins.includes('1Y') ? '1Y' : wins[0] ?? '1Y')
  const title = phone ? 'Relative performance' : 'Relative performance · vs sector, industry and the market'
  if (!rel || (!wins.length && !(rel.returns ?? []).length)) {
    return <Card title={title} testId="prospectus-relative" label="Relative performance"><NotAvailable what="Relative performance" gaps={rel?.gaps} /></Card>
  }
  const { rows, names } = relRows(rel, win)
  const bench = rel.benchmarks ?? []
  // ticker = amber (thick); the rest take the series palette; Nasdaq dashed (as approved).
  const colorFor = (n: string, i: number) => n === symbol ? hex.warning : n === 'QQQ' ? hex.text : n === 'SPY' ? hex.series[0]
    : /industry/i.test(n) ? hex.series[5] : bench.includes(n) || /^XL/.test(n) ? hex.series[3] : hex.series[(i + 1) % hex.series.length]
  const cols = phone ? RET_COLUMNS_PHONE : RET_COLUMNS
  const rets = rel.returns ?? []
  const rank = rel.rank_in_industry
  const trend = rel.sector_trend as Record<string, unknown> | null | undefined
  const trendLabel = trend ? String(trend.trend ?? trend.label ?? trend.momentum ?? '') || null : null
  return (
    <Card title={<span className="psp-rel-head"><span>{title}</span>
      {wins.length > 0 && (
        <span className="psp-seg" role="group" aria-label="Window">
          {wins.map(w => <button key={w} type="button" aria-pressed={win === w} className={`psp-seg-btn${win === w ? ' psp-seg-on' : ''}`} data-testid={`prospectus-rel-${w}`} onClick={() => setWin(w)}>{w}</button>)}
        </span>
      )}</span>} testId="prospectus-relative" label="Relative performance">
      <div className="psp-rel-grid">
        {rows.length > 0 ? (
          <figure className="psp-chart psp-chart-flat" data-testid="prospectus-rel-chart" data-window={win}>
            <figcaption className="psp-chart-title">Rebased to 100 · {phone ? win : `ticker vs its sector ETF, industry group, S&P 500 and Nasdaq-100 · ${win}`}</figcaption>
            <div style={{ width: '100%', height: phone ? 200 : 260 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
                  <CartesianGrid stroke={hex.grid} strokeDasharray="3 3" />
                  <XAxis dataKey="x" tick={{ fill: hex.text, fontSize: TYPE.xs }} stroke={hex.grid} minTickGap={24} />
                  <YAxis domain={['auto', 'auto']} tick={{ fill: hex.text, fontSize: TYPE.xs }} stroke={hex.grid} />
                  <ReferenceLine y={100} stroke={hex.grid} strokeDasharray="3 4" />
                  <Tooltip contentStyle={{ background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, fontSize: TYPE.sm }} />
                  {names.map((n, i) => <Line key={n} type="monotone" dataKey={n} name={benchName(n, symbol, bench)} stroke={colorFor(n, i)}
                    strokeWidth={n === symbol ? 3 : 2} strokeDasharray={n === 'QQQ' ? '6 4' : undefined} dot={false} isAnimationActive={false} connectNulls />)}
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="psp-legend">
              {names.map((n, i) => <span key={n} style={{ color: colorFor(n, i), fontWeight: n === symbol ? 700 : 500 }}>{n === 'QQQ' ? '┅' : '━'} {benchName(n, symbol, bench)}</span>)}
            </div>
          </figure>
        ) : <NotAvailable what="Rebased chart" gaps={rel.gaps} />}
        <div className="psp-rel-side">
          {rets.length > 0 ? (
            <div className="psp-table-wrap">
              <table className="psp-table" data-testid="prospectus-returns">
                <thead><tr><th>Return</th>{cols.map(c => <th key={c}>{c}</th>)}</tr></thead>
                <tbody>
                  {rets.map((r, i) => (
                    <tr key={r.name}><td style={{ color: colorFor(r.name, i), fontWeight: r.name === symbol ? 700 : 500 }}>{benchName(r.name, symbol, bench)}</td>
                      {cols.map(c => <td key={c}>{pct(r[c], 1)}</td>)}</tr>
                  ))}
                  {rel.excess_vs_spy && (
                    <tr className="psp-row-excess"><td className="psp-tone-success">vs S&amp;P (excess)</td>
                      {cols.map(c => <td key={c} className={`psp-tone-${signTone(rel.excess_vs_spy?.[c])}`}>{toNumber(rel.excess_vs_spy?.[c]) == null ? '—' : `${(toNumber(rel.excess_vs_spy?.[c]) ?? 0) > 0 ? '+' : ''}${fmtNum(rel.excess_vs_spy?.[c], 1)}`}</td>)}</tr>
                  )}
                </tbody>
              </table>
            </div>
          ) : <NotAvailable what="Returns table" gaps={rel.gaps} />}
          <div className="psp-mini-tiles">
            <div className="psp-mini"><div className="psp-tile-k">{phone ? 'Industry rank' : 'Rank in industry'}</div><div className="psp-mini-v psp-tone-success">{rank ? `${rank.rank} of ${rank.of}` : '—'}</div>{!phone && <div className="psp-tile-sub">{rank?.percentile != null ? `1Y return · ${rank.percentile}th pct` : 'not available yet'}</div>}</div>
            <div className="psp-mini"><div className="psp-tile-k">{phone ? 'Rel. strength' : 'Relative strength'}</div><div className="psp-mini-v psp-tone-warning">{toNumber(rel.rs_rating_12m) != null ? `${rel.rs_rating_12m}/99` : '—'}</div>{!phone && <div className="psp-tile-sub">vs the market, 12 months</div>}</div>
            <div className="psp-mini"><div className="psp-tile-k">{phone ? 'Sector' : 'Sector trend'}</div><div className="psp-mini-v psp-tone-success">{trendLabel ?? '—'}</div>{!phone && <div className="psp-tile-sub">house momentum</div>}</div>
          </div>
        </div>
      </div>
    </Card>
  )
}

// ── Peer comparison ───────────────────────────────────────────────────────────────────────────────────────────────
export function PeerComparisonBlock({ blocks, phone }: { blocks?: ProspectusBlocks; phone: boolean }) {
  const pc = blocks?.peer_comparison
  const rows = pc?.rows ?? []
  if (!rows.length) return <Card title="Peer comparison" testId="prospectus-peers" label="Peer comparison"><NotAvailable what="Peer comparison" gaps={pc?.gaps} /></Card>
  const cols = peerColumns(pc)
  return (
    <Card title="Peer comparison" testId="prospectus-peers" label="Peer comparison">
      {phone && <div className="psp-muted">Swipe the table sideways for all {cols.length} columns</div>}
      <div className="psp-table-wrap psp-table-scroll" data-testid="prospectus-peers-scroll">
        <table className="psp-table psp-table-peers">
          <thead><tr><th>Ticker</th>{cols.map(c => <th key={c.key}>{c.label}</th>)}</tr></thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.symbol} className={r.is_subject ? 'psp-row-subject' : undefined} data-testid={r.is_subject ? 'prospectus-peer-subject' : 'prospectus-peer'}>
                <td>{r.symbol}</td>{cols.map(c => <td key={c.key}>{peerCell(c.key, r[c.key])}</td>)}
              </tr>
            ))}
            {pc?.median && (
              <tr className="psp-row-median" data-testid="prospectus-peer-median"><td>Peer median</td>{cols.map(c => <td key={c.key}>{c.key === 'consensus' ? '' : peerCell(c.key, pc.median?.[c.key])}</td>)}</tr>
            )}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

// ── Estimates / ownership / risk ──────────────────────────────────────────────────────────────────────────────────
export function EstimatesBlock({ blocks, withCall }: { blocks?: ProspectusBlocks; withCall?: boolean }) {
  const e = blocks?.estimates
  const surprises = e?.eps_surprises ?? []
  const up = toNumber(e?.revisions_90d?.up), down = toNumber(e?.revisions_90d?.down)
  const beats = surprises.filter(s => (toNumber(s.surprise_pct) ?? 0) > 0).length
  const max = Math.max(1, ...surprises.map(s => Math.abs(toNumber(s.surprise_pct) ?? 0)))
  const call = withCall ? blocks?.earnings_call : undefined
  return (
    <Card title={withCall ? 'Earnings and estimates' : 'Estimates and earnings surprises'} tone={withCall ? 'success' : undefined} testId="prospectus-estimates" label="Estimates">
      {!e ? <NotAvailable what="Estimates" /> : (
        <>
          {surprises.length > 0 && !withCall && (
            <div className="psp-bars" aria-label="EPS surprise by quarter">
              {surprises.map((s, i) => {
                const v = toNumber(s.surprise_pct) ?? 0
                return (
                  <div key={i} className="psp-bar-row">
                    <div className="psp-bar-track"><div className={`psp-bar-fill psp-bg-${v >= 0 ? 'success' : 'danger'}`} style={{ width: `${(Math.abs(v) / max) * 100}%` }} /></div>
                    <span className={`psp-tone-${v >= 0 ? 'success' : 'danger'}`}>{s.date ? whenEt(s.date) : `Q${i + 1}`} {pct(v, 1)}</span>
                  </div>
                )
              })}
            </div>
          )}
          <div className="psp-body-sm">
            {surprises.length ? `EPS beat ${beats} of last ${surprises.length}` : 'EPS surprise history not available yet'}
            {' · '}estimate revisions 90d: <b className="psp-tone-success">{up == null ? '—' : up} up</b> / <b className="psp-tone-danger">{down == null ? '—' : down} down</b>
            {' · '}next report {e.next_report ? whenEt(e.next_report) : '—'}
          </div>
          {e.gaps && e.gaps.length > 0 && <div className="psp-gaps">{e.gaps.join(' · ')}</div>}
        </>
      )}
      {withCall && <CallBullets blocks={blocks} />}
    </Card>
  )
}

const OWN_ROWS: Array<[string, (o: Record<string, unknown>) => ReactNode]> = [
  ['Institutional ownership', o => pct(o.institutional_pct, 1, false)],
  ['Insider buys / sells 90d', o => `${dash(o.insider_buys_90d)} / ${dash(o.insider_sells_90d)}`],
  ['Short interest · days to cover', o => `${pct(o.short_float_pct, 1, false)} · ${fmtNum(o.days_to_cover, 1)}`],
  ['Fund flows 30d (ETFs)', o => dash(o.etf_flows_30d)],
  ['Top holders', o => Array.isArray(o.top_holders) ? (o.top_holders as unknown[]).slice(0, 3).join(', ') : dash(o.top_holders)],
]
export function OwnershipBlock({ blocks }: { blocks?: ProspectusBlocks }) {
  const o = blocks?.ownership_flows as Record<string, unknown> | undefined
  return (
    <Card title="Ownership and flows" testId="prospectus-ownership" label="Ownership and flows">
      {!o ? <NotAvailable what="Ownership and flows" /> : <Kv rows={OWN_ROWS.map(([k, f]) => [k, f(o)])} />}
    </Card>
  )
}

const above = (v: unknown) => { const n = toNumber(v); return n == null ? '—' : n >= 0 ? `above (${pct(n, 1)})` : `below (${pct(n, 1)})` }
export function RiskBlock({ blocks, phone }: { blocks?: ProspectusBlocks; phone?: boolean }) {
  const r = blocks?.risk_technicals as Record<string, unknown> | undefined
  return (
    <Card title="Risk and technicals" tone={phone ? 'warning' : undefined} testId="prospectus-risk" label="Risk and technicals">
      {!r || Object.keys(r).filter(k => k !== 'gaps' && k !== 'basis').length === 0 ? <NotAvailable what="Risk and technicals" gaps={r?.gaps as string[] | undefined} /> : (
        <Kv rows={[
          ['Beta vs S&P (1Y)', fmtNum(r.beta_1y, 2)],
          ['Volatility (annualized)', pct(r.vol_annualized_pct, 1, false)],
          ['Max drawdown 1Y', pct(r.max_drawdown_1y_pct, 1), 'danger'],
          ['Correlation to your book', fmtNum(r.correlation_to_book, 2)],
          ['Price vs 50 / 200-day', `${above(r.px_vs_sma50_pct)} · ${above(r.px_vs_sma200_pct)}`],
          ['RSI(14) · ATR(20)', `${fmtNum(r.rsi14, 1)} · ${toNumber(r.atr20) == null ? '—' : `$${fmtNum(r.atr20, 2)}`}`],
        ]} />
      )}
    </Card>
  )
}

// ── Scenarios ─────────────────────────────────────────────────────────────────────────────────────────────────────
const CASE_TONE: Record<ScenarioCase['case'], string> = { bear: 'danger', base: 'neutral', bull: 'success' }
export function ScenariosBlock({ blocks, price }: { blocks?: ProspectusBlocks; price?: number | null }) {
  const sc = blocks?.scenarios
  const cases = sc?.cases ?? []
  return (
    <Card title="Scenarios · 12 months" testId="prospectus-scenarios" label="Scenarios">
      {!cases.length ? <NotAvailable what="Scenarios" gaps={sc?.gaps} /> : (
        <div className="psp-scen">
          {cases.map(c => {
            const p = toNumber(c.price)
            const chg = toNumber(c.change_pct) ?? (p != null && price ? ((p / price) - 1) * 100 : null)
            return (
              <div key={c.case} className={`psp-scen-card psp-scen-${c.case}`} data-testid={`prospectus-scenario-${c.case}`}>
                <div className={`psp-scen-k psp-tone-${CASE_TONE[c.case]}`}>{c.case.toUpperCase()}{toNumber(c.probability_pct) != null ? ` · ${c.probability_pct}% likely` : ''}</div>
                <div className={`psp-scen-v psp-tone-${CASE_TONE[c.case]}`}>{p == null ? '—' : `$${p.toFixed(2)}`}{chg != null ? ` (${pct(chg, 1)})` : ''}</div>
                {c.narrative && <div className="psp-body-sm">{c.narrative}</div>}
              </div>
            )
          })}
        </div>
      )}
      <div className="psp-muted" data-testid="prospectus-scenarios-footer">Built only from the supplied facts and analyst ranges; every input cited. Analysis, not an order — no AI places, sizes or stops trades.</div>
    </Card>
  )
}

// ── Macro / filings / call / options ──────────────────────────────────────────────────────────────────────────────
export function MacroBlock({ blocks }: { blocks?: ProspectusBlocks }) {
  const m = blocks?.macro_sensitivity
  const series = Object.entries(m?.series ?? {})
  const events = (m?.next_events ?? []).slice(0, 3).map(e => `${String(e.name ?? e.event ?? 'Event')} ${whenEt(e.date ?? e.at)}`)
  return (
    <Card title="Macro sensitivity · FRED" tone="info" testId="prospectus-macro" label="Macro sensitivity">
      {!series.length ? <NotAvailable what="Macro series" gaps={m?.gaps} /> : (
        <div className="psp-table-wrap">
          <table className="psp-table psp-table-left">
            <thead><tr><th>Series</th><th>Latest · trend</th><th>Effect on this name</th></tr></thead>
            <tbody>
              {series.map(([id, s]) => (
                <tr key={id}><td>{s.label}</td><td>{fmtNum(s.value, 2)}{s.trend ? ` · ${s.trend}` : ''}</td>
                  <td className={s.effect ? `psp-tone-${/head/i.test(s.effect) ? 'warning' : /tail/i.test(s.effect) ? 'success' : 'neutral'}` : 'psp-muted'}>{s.effect || '—'}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="psp-muted">Rate beta to 10-year: {toNumber(m?.rate_beta_10y) == null ? '—' : fmtNum(m?.rate_beta_10y, 4)} · next macro events: {events.length ? events.join(', ') : '—'}</div>
    </Card>
  )
}

export function FilingsBlock({ blocks }: { blocks?: ProspectusBlocks }) {
  const f = blocks?.sec_filings
  const rows = f?.filings ?? []
  return (
    <Card title="Filings · SEC EDGAR" tone="ai" testId="prospectus-filings" label="SEC filings">
      {!rows.length ? <NotAvailable what="SEC filings" gaps={f?.gaps} /> : (
        <div className="psp-table-wrap">
          <table className="psp-table psp-table-left">
            <thead><tr><th>Form</th><th>Filed</th><th>What changed</th></tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} data-testid="prospectus-filing"><td><b>{r.url ? <a href={r.url} target="_blank" rel="noopener noreferrer" className="psp-link">{r.form}</a> : r.form}</b></td>
                  <td>{r.filed_at ? whenEt(r.filed_at) : '—'}</td><td>{r.what_changed || '—'}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {f?.form4_90d && (toNumber(f.form4_90d.buys) != null || toNumber(f.form4_90d.sells) != null) && (
        <div className="psp-muted">Form 4, 90 days: {dash(f.form4_90d.buys)} buys / {dash(f.form4_90d.sells)} sells</div>
      )}
    </Card>
  )
}

function CallBullets({ blocks }: { blocks?: ProspectusBlocks }) {
  const c = blocks?.earnings_call
  const bullets = c?.bullets ?? []
  const tx = c?.transcripts ?? []
  if (!bullets.length && !tx.length) return <NotAvailable what="Earnings call" gaps={c?.gaps} testId="prospectus-call-na" />
  return (
    <ul className="psp-ul" data-testid="prospectus-call">
      {bullets.map((b, i) => <li key={`b${i}`}>{b}</li>)}
      {tx.map((t, i) => <li key={`t${i}`}>{t.url ? <a className="psp-link" href={t.url} target="_blank" rel="noopener noreferrer">{t.label}</a> : t.label}{t.as_of ? <span className="psp-muted"> · {whenEt(t.as_of)}</span> : null}</li>)}
    </ul>
  )
}

export function CallBlock({ blocks }: { blocks?: ProspectusBlocks }) {
  return <Card title="Earnings call · what management said" testId="prospectus-earnings-call" label="Earnings call"><CallBullets blocks={blocks} /></Card>
}

function optRows(o: Record<string, unknown>): Array<[string, ReactNode, string?]> {
  const ns = o.news_sentiment as Record<string, unknown> | null | undefined
  const social = o.social as Record<string, unknown> | null | undefined
  const div = (o.dividend ?? {}) as Record<string, unknown>
  const debate = o.debate as Record<string, unknown> | string | null | undefined
  const nsLabel = ns ? String(ns.label ?? '') || null : null
  return [
    ['Implied vol · IV rank', `${pct(o.iv_pct, 1, false)} · ${dash(o.iv_rank)}`],
    ['Put/call · unusual flow', `${fmtNum(o.put_call, 2)} · ${dash(o.unusual_flow)}`],
    ['News sentiment 7d', nsLabel ?? '—', nsLabel ? (/pos|bull/i.test(nsLabel) ? 'success' : /neg|bear/i.test(nsLabel) ? 'danger' : undefined) : undefined],
    ['Social chatter', social ? String(social.label ?? social.summary ?? social.volume ?? '—') : '—'],
    ['Dividend · yield', `${toNumber(div.annual_per_share) == null ? '—' : `$${fmtNum(div.annual_per_share, 2)}`} · ${pct(div.yield_pct, 2, false)}`],
    ["House agents' view (debate)", typeof debate === 'string' ? debate : debate ? String(debate.verdict ?? debate.label ?? debate.summary ?? '—') : '—'],
  ]
}
export function OptionsBlock({ blocks, withOwnership }: { blocks?: ProspectusBlocks; withOwnership?: boolean }) {
  const o = blocks?.options_sentiment_dividends as Record<string, unknown> | undefined
  const own = blocks?.ownership_flows as Record<string, unknown> | undefined
  const rows: Array<[string, ReactNode, string?]> = [
    ...(withOwnership && own ? OWN_ROWS.slice(0, 3).map(([k, f]) => [k, f(own)] as [string, ReactNode]) : []),
    ...(o ? optRows(o) : []),
  ]
  return (
    <Card title={withOwnership ? 'Ownership, options and sentiment' : 'Options, sentiment and dividends'} tone={withOwnership ? 'info' : undefined} testId="prospectus-options" label="Options, sentiment and dividends">
      {!rows.length ? <NotAvailable what="Options, sentiment and dividends" /> : <Kv rows={rows} />}
    </Card>
  )
}

// ── Source coverage ───────────────────────────────────────────────────────────────────────────────────────────────
export function CoverageBlock({ doc }: { doc: ProspectusDoc }) {
  const cov = doc.source_coverage
  const domains: CoverageDomain[] = cov?.domains ?? []
  return (
    <Card title={<>Source coverage <span className="psp-muted">· every registered source checked</span></>} testId="prospectus-coverage" label="Source coverage">
      {!domains.length ? <NotAvailable what="Source coverage" /> : (
        <div className="psp-cov">
          {domains.map(d => (
            <span key={d.domain} className={`psp-chip psp-cov-chip psp-tone-${coverageTone(d.status)}`} data-testid="prospectus-coverage-chip" data-status={d.status}
              title={[d.status, d.reason, d.as_of ? `as of ${whenEt(d.as_of)}` : null].filter(Boolean).join(' · ')}>
              {domainLabel(d)}{d.status === 'stale' && d.as_of ? ` · ${whenEt(d.as_of)}` : ''}
            </span>
          ))}
        </div>
      )}
      <div className="psp-muted">Green used · amber stale (shows as-of) · grey not applicable · red failed. A missing key source marks the report "partial".</div>
    </Card>
  )
}
