/** Ticker Prospectus — institutional blocks (approved mockup prospectus/v001, operator 2026-10-26 "approved push live").
 *  Every block is computed by the backend from house data; each renders from its own JSON block and, when the block
 *  is absent or empty, a compact "not available yet" row — never a crash and never an invented number.
 *  Colours: tokens (CSS vars) for chrome; CHART_HEX for recharts props, which cannot read CSS vars. */
import { useState, type ReactNode } from 'react'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { CHART_HEX, RADIUS, TOKENS, TYPE } from '../../lib/designTokens'
import { useTheme } from '../../hooks/useTheme'
import {
  COVERAGE_GROUPS, RET_COLUMNS, RET_COLUMNS_PHONE, benchName, coverageGroups, coverageTone, fmtNum, isBlankValue,
  monthLabel, monthTicks, peerCell, peerColumns, pct, presentationOf, relRows, relWindows, signTone, toNumber,
  verdictTiles, whenEt,
  type ProspectusBlocks, type ProspectusDoc, type ScenarioCase,
} from '../../lib/prospectusModel'
import { CiteText, FootnoteRef, useFootnotes } from './Citations'

/** The one compact line a block shows when the house holds no data for it (data absent, not "not applicable"). */
export function NotAvailable({ what, gaps, testId }: { what: string; gaps?: string[] | null; testId?: string }) {
  return (
    <div className="psp-na" data-testid={testId ?? 'prospectus-na'}>
      <span className="psp-na-dot" aria-hidden="true" />
      <span>{what}: not in our data{gaps && gaps.length ? <span className="psp-muted"> — {gaps[0]}</span> : null}</span>
    </div>
  )
}

/** One line naming every field a block could not fill ("Not in our data: X, Y") — never a dash per field. */
export function NotInData({ fields, testId = 'prospectus-not-in-data' }: { fields: string[]; testId?: string }) {
  if (!fields.length) return null
  return <p className="psp-notin" data-testid={testId}>Not in our data: {fields.join(', ')}</p>
}

export function Card({ title, tone, children, testId, label, className }: { title: ReactNode; tone?: string; children: ReactNode; testId?: string; label?: string; className?: string }) {
  return (
    <section className={`psp-card${className ? ` ${className}` : ''}`} data-testid={testId} aria-label={label}>
      <h2 className={`psp-card-title${tone ? ` psp-tone-${tone}` : ''}`}>{title}</h2>
      {children}
    </section>
  )
}

/** Key/value rows. Rows whose value is blank ('—', 'n/a', '— / —') are dropped and named once below. */
function Kv({ rows, compact = true }: { rows: Array<[string, ReactNode, string?]>; compact?: boolean }) {
  const shown = compact ? rows.filter(([, v]) => !isBlankValue(v)) : rows
  const absent = compact ? rows.filter(([, v]) => isBlankValue(v)).map(([k]) => k) : []
  return (
    <>
      {shown.length > 0 && (
        <div className="psp-kv">
          {shown.map(([k, v, tone], i) => (
            <div key={i} className="psp-kv-row"><span className="psp-kv-k">{k}</span><span className={`psp-kv-v${tone ? ` psp-tone-${tone}` : ''}`}>{v}</span></div>
          ))}
        </div>
      )}
      <NotInData fields={absent} />
    </>
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
            ? <div className={`psp-tile-v${t.id === 'verdict' ? ` psp-tone-${t.tone}` : ''}`}>{t.id === 'stop' && t.value.includes(' · ')
                ? <>{t.value.split(' · ')[0]}<span className="psp-tile-state"> · {t.value.split(' · ').slice(1).join(' · ')}</span></> : t.value}</div>
            : <div className="psp-tile-v psp-tile-na">not in our data</div>}
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
  const relTicks = monthTicks(rows.map(r => String(r.x)), phone ? 4 : 6)
  const bench = rel.benchmarks ?? []
  // ticker = amber (thick); the rest take the series palette; Nasdaq dashed (as approved).
  const colorFor = (n: string, i: number) => n === symbol ? hex.warning : n === 'QQQ' ? hex.text : n === 'SPY' ? hex.series[0]
    : /industry/i.test(n) ? hex.series[5] : bench.includes(n) || /^XL/.test(n) ? hex.series[3] : hex.series[(i + 1) % hex.series.length]
  const rets = rel.returns ?? []
  // Columns no row fills are dropped (a fund with only a 1Y history shows one column, not five dashes).
  const cols = (phone ? RET_COLUMNS_PHONE : RET_COLUMNS).filter(c => rets.some(r => toNumber(r[c]) != null) || toNumber(rel.excess_vs_spy?.[c]) != null)
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
                  <XAxis dataKey="x" tick={{ fill: hex.text, fontSize: TYPE.xs }} stroke={hex.grid} interval={0}
                    ticks={relTicks.length ? relTicks : undefined} tickFormatter={monthLabel} minTickGap={relTicks.length ? 0 : 24} />
                  <YAxis domain={['auto', 'auto']} tick={{ fill: hex.text, fontSize: TYPE.xs }} stroke={hex.grid} />
                  <ReferenceLine y={100} stroke={hex.grid} strokeDasharray="3 4" />
                  <Tooltip labelFormatter={v => whenEt(v)} contentStyle={{ background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, fontSize: TYPE.sm }} />
                  {names.map((n, i) => <Line key={n} type="monotone" dataKey={n} name={benchName(n, symbol, bench)} stroke={colorFor(n, i)}
                    strokeWidth={n === symbol ? 3 : 2} strokeDasharray={n === 'QQQ' ? '6 4' : undefined} dot={false} isAnimationActive={false} connectNulls />)}
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="psp-legend" data-testid="prospectus-rel-legend">
              {names.map((n, i) => <span key={n} className="psp-legend-item" style={{ fontWeight: n === symbol ? 700 : 500 }}><span className="psp-legend-swatch" aria-hidden="true" style={{ background: n === 'QQQ' ? 'transparent' : colorFor(n, i), borderTop: n === 'QQQ' ? `2px dashed ${colorFor(n, i)}` : undefined }} />{benchName(n, symbol, bench)}</span>)}
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
          {(() => {
            const minis = [
              { k: phone ? 'Industry rank' : 'Rank in industry', v: rank ? `${rank.rank} of ${rank.of}` : null, sub: rank?.percentile != null ? `1Y return · ${rank.percentile}th pct` : null, tone: 'success', name: 'Rank in industry' },
              { k: phone ? 'Rel. strength' : 'Relative strength', v: toNumber(rel.rs_rating_12m) != null ? `${rel.rs_rating_12m}/99` : null, sub: 'vs the market, 12 months', tone: 'warning', name: 'Relative strength' },
              { k: phone ? 'Sector' : 'Sector trend', v: trendLabel, sub: 'house momentum', tone: 'success', name: 'Sector trend' },
            ]
            const shown = minis.filter(m => m.v)
            return (
              <>
                {shown.length > 0 && (
                  <div className="psp-mini-tiles">
                    {shown.map(m => <div key={m.name} className="psp-mini"><div className="psp-tile-k">{m.k}</div><div className={`psp-mini-v psp-tone-${m.tone}`}>{m.v}</div>{!phone && m.sub && <div className="psp-tile-sub">{m.sub}</div>}</div>)}
                  </div>
                )}
                <NotInData fields={minis.filter(m => !m.v).map(m => m.name)} />
              </>
            )
          })()}
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
          {(surprises.length > 0 || up != null || down != null || e.next_report) && (
            <div className="psp-body-sm">
              {[surprises.length ? <span key="b">EPS beat {beats} of last {surprises.length}</span> : null,
                up != null || down != null ? <span key="r">estimate revisions 90d: <b className="psp-tone-success">{up ?? '—'} up</b> / <b className="psp-tone-danger">{down ?? '—'} down</b></span> : null,
                e.next_report ? <span key="n">next report {whenEt(e.next_report)}</span> : null]
                .filter(Boolean).flatMap((x, i) => (i ? [<span key={`s${i}`}> · </span>, x] : [x]))}
            </div>
          )}
          <NotInData fields={[...(surprises.length ? [] : ['EPS surprise history']), ...(up == null && down == null ? ['Estimate revisions (90d)'] : []), ...(e.next_report ? [] : ['Next report date'])]} />
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

// ── Stop plan (holdings) ──────────────────────────────────────────────────────────────────────────────────────────
const STOP_STATE: Record<string, [string, string]> = {
  active: ['Active', 'success'], resting: ['Resting · pending activation', 'warning'], filled: ['Filled', 'warning'],
  none: ['None on record', 'danger'], unknown: ['State not reported', 'neutral'],
}
export function StopPlanBlock({ blocks }: { blocks?: ProspectusBlocks }) {
  const sp = blocks?.stop_plan
  if (!sp || sp.not_applicable) return null
  const rec = sp.recommended ?? {}
  const br = sp.broker ?? {}
  const money = (v: unknown) => { const n = toNumber(v); return n == null ? '—' : `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` }
  const band = rec.band
  const [stateLabel, stateTone] = STOP_STATE[br.state ?? 'unknown'] ?? STOP_STATE.unknown
  const bandText = band && toNumber(band.stop_min_pct) != null
    ? `${band.label ?? 'Policy'} ${fmtNum(band.stop_min_pct, 0)}–${fmtNum(band.stop_max_pct, 0)}% below${band.levels?.length === 2 ? ` (${money(band.levels[0])}–${money(band.levels[1])})` : ''}`
    : '—'
  return (
    <Card title="Stop plan · house policy vs broker" testId="prospectus-stop-plan" label="Stop plan">
      <Kv rows={[
        ['House recommended stop', <span data-testid="prospectus-stop-house">{money(rec.level)}</span>],
        ['Method', dash(rec.method)],
        ['Distance below last close', toNumber(rec.distance_pct) == null ? '—' : `${fmtNum(rec.distance_pct, 1)}%`],
        ['$ at risk at the house stop', money(rec.usd_at_risk)],
        ['Broker stop', <span data-testid="prospectus-stop-broker">{money(br.level)} · {stateLabel}</span>, stateTone],
        ['Policy band', bandText],
        ...(br.other_accounts ? [['Other accounts', String(br.other_accounts)] as [string, ReactNode]] : []),
      ]} />
      {sp.comparison && <p className="psp-muted" data-testid="prospectus-stop-comparison">{sp.comparison}</p>}
      {(sp.gaps ?? []).length > 0 && <p className="psp-muted"><CiteText text={(sp.gaps ?? []).join('; ')} /></p>}
      <div className="psp-muted" data-testid="prospectus-stop-advisory">{sp.advisory ?? 'advisory — no AI places, sizes or stops orders'}</div>
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
                {c.narrative && <div className="psp-body-sm"><CiteText text={c.narrative} /></div>}
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
                  <td className={s.effect ? `psp-tone-${/head/i.test(s.effect) ? 'warning' : /tail/i.test(s.effect) ? 'success' : 'neutral'}` : 'psp-muted'}>{s.effect ? <CiteText text={s.effect} /> : '—'}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {(toNumber(m?.rate_beta_10y) != null || events.length > 0) && (
        <div className="psp-muted">{[toNumber(m?.rate_beta_10y) != null ? `Rate beta to 10-year: ${fmtNum(m?.rate_beta_10y, 4)}` : null, events.length ? `next macro events: ${events.join(', ')}` : null].filter(Boolean).join(' · ')}</div>
      )}
      {series.length > 0 && <NotInData fields={[...(toNumber(m?.rate_beta_10y) == null ? ['Rate beta to 10-year'] : []), ...(events.length ? [] : ['Next macro events'])]} />}
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
      {bullets.map((b, i) => <li key={`b${i}`}><CiteText text={b} /></li>)}
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
export function OptionsBlock({ blocks, withOwnership, fund }: { blocks?: ProspectusBlocks; withOwnership?: boolean; fund?: boolean }) {
  const o = blocks?.options_sentiment_dividends as Record<string, unknown> | undefined
  const own = blocks?.ownership_flows as Record<string, unknown> | undefined
  // Funds: the distribution lives in "Fund structure & holdings"; ownership rows never apply.
  const opt = o ? optRows(o).filter(([k]) => !(fund && /^Dividend/.test(k))) : []
  const rows: Array<[string, ReactNode, string?]> = [
    ...(withOwnership && own && !fund ? OWN_ROWS.slice(0, 3).map(([k, f]) => [k, f(own)] as [string, ReactNode]) : []),
    ...opt,
  ]
  const title = withOwnership && !fund ? 'Ownership, options and sentiment' : fund ? 'Options and sentiment' : 'Options, sentiment and dividends'
  return (
    <Card title={title} tone={withOwnership ? 'info' : undefined} testId="prospectus-options" label="Options, sentiment and dividends">
      {!rows.length ? <NotAvailable what={title} /> : <Kv rows={rows} />}
    </Card>
  )
}

// ── Fund structure & holdings (funds only; replaces ownership, estimates and the earnings call) ──────────────────────
// Operator 2026-10-26: "ETF shouldn't have this. They should have something else that's relative to ETF."
export function FundStructureBlock({ doc, wide }: { doc: ProspectusDoc; wide?: boolean }) {
  const fs = presentationOf(doc)?.fund_structure
  const byId = useFootnotes()
  if (!fs) return <Card title="Fund structure & holdings" testId="prospectus-fund-structure" label="Fund structure and holdings"><NotAvailable what="Fund structure" /></Card>
  const top = fs.top_holdings ?? []
  const maxW = Math.max(1, ...top.map(h => h.weight_pct ?? 0))
  const sectors = fs.sectors ?? []
  const maxS = Math.max(1, ...sectors.map(x => x.weight_pct))
  const overlap = fs.rows.find(r => r.group === 'overlap')
  return (
    <Card title="Fund structure & holdings" tone="info" testId="prospectus-fund-structure" label="Fund structure and holdings" className={wide ? 'psp-span2' : undefined}>
      {overlap && <p className="psp-fs-overlap" data-testid="prospectus-fund-overlap"><b>{overlap.label}:</b> {overlap.value}</p>}
      <div className={`psp-fs${wide ? ' psp-fs-wide' : ''}`}>
        <div className="psp-kv" data-testid="prospectus-fund-rows">
          {fs.rows.filter(r => r.group !== 'overlap').map(r => {
            const notes = (r.cites ?? []).map(i => byId.get(i)).filter((x): x is NonNullable<typeof x> => !!x)
            return (
              <div key={r.label} className="psp-kv-row"><span className="psp-kv-k">{r.label}</span>
                <span className="psp-kv-v">{r.value}{notes.length > 0 && <FootnoteRef notes={notes} ids={notes.map(n => n.id)} />}</span></div>
            )
          })}
        </div>
        {(top.length > 0 || sectors.length > 0) && (
          <div className="psp-fs-lists">
            {top.length > 0 && (
              <div>
                <div className="psp-tile-k">Top {top.length} holdings{fs.as_of ? <span className="psp-muted"> · as of {whenEt(fs.as_of)}</span> : null}</div>
                <ul className="psp-wbars" data-testid="prospectus-fund-holdings">
                  {top.map(h => (
                    <li key={h.name}><span className="psp-wbar-k" title={h.name}>{h.symbol || h.name}</span>
                      <span className="psp-wbar-track"><span className="psp-wbar-fill psp-bg-info" style={{ width: `${((h.weight_pct ?? 0) / maxW) * 100}%` }} /></span>
                      <span className="psp-wbar-v">{h.weight_pct == null ? '' : `${h.weight_pct.toFixed(1)}%`}</span></li>
                  ))}
                </ul>
              </div>
            )}
            {sectors.length > 0 && (
              <div>
                <div className="psp-tile-k">Sector weights</div>
                <ul className="psp-wbars" data-testid="prospectus-fund-sectors">
                  {sectors.map(x => (
                    <li key={x.name}><span className="psp-wbar-k" title={x.name}>{x.name}</span>
                      <span className="psp-wbar-track"><span className="psp-wbar-fill psp-bg-ai" style={{ width: `${(x.weight_pct / maxS) * 100}%` }} /></span>
                      <span className="psp-wbar-v">{x.weight_pct.toFixed(1)}%</span></li>
                  ))}
                </ul>
              </div>
            )}
            {(fs.countries ?? []).length > 0 && (
              <div className="psp-body-sm">Countries: {(fs.countries ?? []).map(c => `${c.name} ${c.weight_pct.toFixed(1)}%`).join(' · ')}</div>
            )}
          </div>
        )}
      </div>
      <NotInData fields={fs.missing ?? []} testId="prospectus-fund-missing" />
    </Card>
  )
}

// ── Source coverage ───────────────────────────────────────────────────────────────────────────────────────────────
// Only the sources relevant to a security report, grouped and collapsed; internal plumbing stays in the JSON.
export function CoverageBlock({ doc }: { doc: ProspectusDoc }) {
  const { groups, counts, hidden } = coverageGroups(doc)
  const total = counts.used + counts.stale + counts.failed + counts.missing
  const summary = COVERAGE_GROUPS.filter(([g]) => counts[g]).map(([g, lab]) => (
    <span key={g} className={`psp-cov-count psp-tone-${coverageTone(g === 'missing' ? 'empty' : g)}`} data-testid={`prospectus-coverage-count-${g}`}>{counts[g]} {lab.toLowerCase()}</span>
  ))
  return (
    <section className="psp-card" data-testid="prospectus-coverage" aria-label="Source coverage">
      {!total ? (<><h2 className="psp-card-title">Source coverage</h2><NotAvailable what="Source coverage" /></>) : (
        <details className="psp-cov-d">
          <summary className="psp-srcs-sum psp-cov-sum" data-testid="prospectus-coverage-toggle">
            <h2 className="psp-card-title">Source coverage</h2><span className="psp-cov-counts">{summary}</span>
          </summary>
          {COVERAGE_GROUPS.filter(([g]) => groups[g]?.length).map(([g, lab]) => (
            <div key={g} className="psp-cov-group" data-group={g}>
              <div className="psp-tile-k">{lab} · {counts[g]}</div>
              <div className="psp-cov">
                {groups[g].map(d => (
                  <span key={d.domain} className={`psp-chip psp-cov-chip psp-tone-${coverageTone(d.status === 'empty' ? 'empty' : d.status)}`} data-testid="prospectus-coverage-chip" data-status={d.status}
                    title={[d.status, d.reason, d.as_of ? `as of ${whenEt(d.as_of)}` : null].filter(Boolean).join(' · ')}>
                    {d.label}{d.status === 'stale' && d.as_of ? ` · ${whenEt(d.as_of)}` : ''}
                  </span>
                ))}
              </div>
            </div>
          ))}
          <div className="psp-muted">{hidden ? `${hidden} internal or not-applicable sources are kept in the record and not listed. ` : ''}A missing key source marks the report "partial".</div>
        </details>
      )}
    </section>
  )
}
