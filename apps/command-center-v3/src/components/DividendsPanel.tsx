/** Portfolio → Dividends desk: progress-to-target, tax treatment, charts, payers table.
 *  Account filter comes from parent (URL-synced `?acct=`). Backend payers may include `account`
 *  (per-holding MV split from /api/v2/dividends); falls back to client MV share if not.
 */
import { useMemo, type CSSProperties } from 'react'
import {
  PieChart, Pie, Cell, ResponsiveContainer, Tooltip,
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
} from 'recharts'
import { fmt$ } from '../lib/format'
import { BB, T, TYPE } from '../lib/watchTokens'

const TARGET = 55_000
const MINIMUM = 37_500
const STRETCH = 67_500
const BAR_MAX = STRETCH * 1.1

const DONUT_COLORS = [
  T.link, BB.green, BB.red, BB.amber, T.extIntel.hermes,
  T.extIntel.grok, BB.orange, T.extIntel.gpt, BB.text2, BB.text3,
]

export type DivPayer = {
  symbol: string
  shares?: number
  price?: number
  market_value?: number
  yield_pct?: number
  frequency?: string
  annual_income?: number
  monthly_amort?: number
  qualified?: boolean
  safety?: string
  account?: string | null
  account_key?: string | null
}

export type DivData = {
  has_data?: boolean
  payers?: DivPayer[]
  total_annual?: number
  qualified_annual?: number
  ordinary_annual?: number
  monthly_average?: number
  monthly_summary?: any
  ex_div_alerts?: { symbol: string; ex_date?: string; amount?: string }[]
  by_account?: Record<string, { annual: number; monthly: number; payers: number }>
  account_attribution?: string
}

type HoldingLite = { symbol?: string; account?: string; market_value?: number }

type Props = {
  divs: DivData | null | undefined
  holdings: HoldingLite[]
  accounts: [string, { n: number; value: number }][]
  acctFilter: string | null
  selectAcct: (a: string | null) => void
  acctColor: (a: string) => string
  panelStyle?: CSSProperties
  terminalUi?: boolean
}

function monthEntries(ms: any): [string, number][] {
  if (!ms) return []
  if (Array.isArray(ms)) {
    return ms.map((item: any) => [item.month_name || `M${item.month}`, Number(item.total) || 0])
  }
  return Object.entries(ms)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, v]) => [k, Number(v) || 0] as [string, number])
}

function buildRows(
  allPayers: DivPayer[],
  holdings: HoldingLite[],
  acctFilter: string | null,
): { symbol: string; yield_pct: number; annual: number; monthly: number; frequency: string; qualified: boolean; safety: string; account: string }[] {
  const hasPayerAcct = allPayers.some(p => p.account || p.account_key)
  const mvBySymAcct: Record<string, Record<string, number>> = {}
  const mvBySym: Record<string, number> = {}
  for (const h of holdings) {
    const sym = String(h.symbol || '')
    if (!sym) continue
    const acct = String(h.account ?? 'unknown')
    const mv = Number(h.market_value) || 0
    mvBySym[sym] = (mvBySym[sym] || 0) + mv
    mvBySymAcct[sym] ??= {}
    mvBySymAcct[sym][acct] = (mvBySymAcct[sym][acct] || 0) + mv
  }

  const out: ReturnType<typeof buildRows> = []
  for (const p of allPayers) {
    const sym = p.symbol
    const baseAnnual = Number(p.annual_income) || 0
    const baseMonthly = Number(p.monthly_amort) || baseAnnual / 12
    const yld = Number(p.yield_pct) || 0
    const freq = p.frequency || '—'
    const qual = !!p.qualified
    const safety = p.safety || '—'

    if (hasPayerAcct) {
      const pa = String(p.account ?? p.account_key ?? '')
      if (acctFilter && pa !== acctFilter) continue
      out.push({
        symbol: sym, yield_pct: yld, annual: baseAnnual, monthly: baseMonthly,
        frequency: freq, qualified: qual, safety, account: pa,
      })
      continue
    }

    // Client fallback when API still portfolio-level
    const accts = Object.keys(mvBySymAcct[sym] || {})
    const totalMv = mvBySym[sym] || 0
    if (!acctFilter) {
      if (accts.length <= 1) {
        out.push({
          symbol: sym, yield_pct: yld, annual: baseAnnual, monthly: baseMonthly,
          frequency: freq, qualified: qual, safety, account: accts[0] || '',
        })
      } else {
        for (const acct of accts) {
          const share = totalMv > 0 ? (mvBySymAcct[sym][acct] || 0) / totalMv : 0
          out.push({
            symbol: sym, yield_pct: yld, annual: baseAnnual * share, monthly: baseMonthly * share,
            frequency: freq, qualified: qual, safety, account: acct,
          })
        }
      }
      continue
    }
    const acctMv = mvBySymAcct[sym]?.[acctFilter] || 0
    if (acctMv <= 0) continue
    const share = totalMv > 0 ? acctMv / totalMv : 0
    out.push({
      symbol: sym, yield_pct: yld, annual: baseAnnual * share, monthly: baseMonthly * share,
      frequency: freq, qualified: qual, safety, account: acctFilter,
    })
  }
  return out.sort((a, b) => b.annual - a.annual)
}

export default function DividendsPanel({
  divs, holdings, accounts, acctFilter, selectAcct, acctColor, panelStyle, terminalUi,
}: Props) {
  const rows = useMemo(
    () => buildRows((divs?.payers ?? []) as DivPayer[], holdings, acctFilter),
    [divs, holdings, acctFilter],
  )
  const viewAnnual = rows.reduce((s, r) => s + r.annual, 0)
  const viewMonthly = rows.reduce((s, r) => s + r.monthly, 0) || viewAnnual / 12
  const viewQual = rows.filter(r => r.qualified).reduce((s, r) => s + r.annual, 0)
  const viewOrd = viewAnnual - viewQual

  const earned = viewAnnual || Number(divs?.total_annual) || 0
  const pct = (v: number) => Math.min((v / BAR_MAX) * 100, 100)

  const top8 = rows.slice(0, 8)
  const otherIncome = rows.slice(8).reduce((s, r) => s + r.annual, 0)
  const donut = top8.map(r => ({ name: r.symbol, value: r.annual }))
  if (otherIncome > 0) donut.push({ name: 'Other', value: otherIncome })

  const months = monthEntries(divs?.monthly_summary).map(([name, total]) => ({ name: name.slice(0, 3), total }))

  const taxable = rows.filter(r => /taxable/i.test(r.account)).reduce((s, r) => s + r.annual, 0)
  const roth = rows.filter(r => /roth/i.test(r.account)).reduce((s, r) => s + r.annual, 0)
  const deferred = Math.max(0, viewAnnual - taxable - roth)

  const attribution = divs?.account_attribution
    || (rows.some(r => r.account) ? 'holdings_mv_share' : 'portfolio_level')

  if (!divs) {
    return (
      <div className={terminalUi ? 'cc-panel' : undefined} style={panelStyle}>
        <div style={{ color: 'var(--text3)', fontSize: TYPE.sm }}>Loading dividend data…</div>
      </div>
    )
  }

  return (
    <div className={terminalUi ? 'cc-panel' : undefined} style={panelStyle}>
      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>
        Dividend Income
        {acctFilter && (
          <span style={{ fontSize: TYPE.sm, color: 'var(--text3)', fontWeight: 500 }}>
            {' '}· {acctFilter.replace(/_/g, ' ')}
          </span>
        )}
      </div>

      {accounts.length > 1 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12, alignItems: 'center' }}>
          <button type="button" onClick={() => selectAcct(null)} style={{
            padding: '3px 10px', fontSize: TYPE.xs, borderRadius: 12, cursor: 'pointer',
            border: `1px solid ${acctFilter === null ? T.link : 'var(--border)'}`,
            background: acctFilter === null ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
            color: acctFilter === null ? T.link : 'var(--text3)', fontWeight: acctFilter === null ? 700 : 400,
          }}>All</button>
          {accounts.map(([a]) => (
            <button type="button" key={a} onClick={() => selectAcct(a === acctFilter ? null : a)} style={{
              padding: '3px 10px', fontSize: TYPE.xs, borderRadius: 12, cursor: 'pointer',
              border: `1px solid ${acctFilter === a ? acctColor(a) : 'var(--border)'}`,
              background: acctFilter === a ? `${acctColor(a)}22` : 'var(--bg2)',
              color: acctFilter === a ? acctColor(a) : 'var(--text3)', fontWeight: acctFilter === a ? 700 : 400,
            }}>
              <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: acctColor(a), marginRight: 5 }} />
              {a.replace(/_/g, ' ')}
            </button>
          ))}
        </div>
      )}

      {/* Progress to target */}
      <div style={{ background: 'var(--bg2)', borderRadius: 10, padding: 14, marginBottom: 12, border: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
          <div>
            <span style={{ fontSize: 24, fontWeight: 800, color: BB.green }}>{fmt$(earned, 0)}</span>
            <span style={{ color: 'var(--text3)', fontSize: TYPE.xs, marginLeft: 8 }}>/ yr projected{acctFilter ? ' (view)' : ''}</span>
          </div>
          <div style={{ textAlign: 'right', lineHeight: 1.55, fontSize: TYPE.xs, color: 'var(--text2)' }}>
            <div>Minimum <strong style={{ color: BB.amber }}>{fmt$(MINIMUM, 0)}</strong></div>
            <div>Target <strong style={{ color: BB.green }}>{fmt$(TARGET, 0)}</strong></div>
            <div>Stretch <strong style={{ color: T.extIntel.hermes }}>{fmt$(STRETCH, 0)}</strong></div>
          </div>
        </div>
        <div style={{ position: 'relative', height: 22, background: 'var(--bg3, var(--bg1))', borderRadius: 6, overflow: 'visible' }}>
          <div style={{
            position: 'absolute', left: 0, top: 0, bottom: 0, width: `${pct(earned)}%`,
            background: `linear-gradient(90deg, ${BB.green} 0%, ${T.link} 100%)`,
            borderRadius: 6, transition: 'width 0.5s ease',
          }} />
          {([[MINIMUM, BB.amber, 'Min'], [TARGET, BB.green, 'Target'], [STRETCH, T.extIntel.hermes, 'Stretch']] as const).map(([v, c, lab]) => (
            <div key={lab} style={{ position: 'absolute', left: `${pct(v)}%`, top: -2, bottom: -2, width: 2, background: c, zIndex: 2 }}>
              <div style={{ position: 'absolute', top: -14, left: '50%', transform: 'translateX(-50%)', fontSize: TYPE.xs, color: c, whiteSpace: 'nowrap' }}>{lab}</div>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 10, fontSize: TYPE.xs, color: 'var(--text3)', textAlign: 'right' }}>
          {((earned / TARGET) * 100).toFixed(1)}% of target
          {earned < MINIMUM && <span style={{ color: BB.red, marginLeft: 10 }}>{fmt$(MINIMUM - earned, 0)} to minimum</span>}
          {earned >= MINIMUM && earned < TARGET && <span style={{ color: BB.amber, marginLeft: 10 }}>{fmt$(TARGET - earned, 0)} to target</span>}
          {earned >= TARGET && earned < STRETCH && <span style={{ color: T.extIntel.hermes, marginLeft: 10 }}>{fmt$(STRETCH - earned, 0)} to stretch</span>}
          {earned >= STRETCH && <span style={{ color: BB.green, marginLeft: 10 }}>Stretch goal achieved</span>}
        </div>
      </div>

      {/* KPI tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 12 }}>
        {[
          { lab: 'Annual', val: fmt$(viewAnnual, 0), c: BB.green },
          { lab: 'Monthly Avg', val: fmt$(viewMonthly, 0), c: 'var(--text0)' },
          { lab: 'Qualified', val: fmt$(viewQual || divs.qualified_annual || 0, 0), c: 'var(--text0)' },
          { lab: 'Payers', val: String(rows.length), c: 'var(--text0)' },
        ].map(t => (
          <div key={t.lab} style={{ background: 'var(--bg2)', borderRadius: 8, padding: 10, textAlign: 'center' }}>
            <div style={{ fontSize: 18, fontWeight: 700, color: t.c }}>{t.val}</div>
            <div style={{ fontSize: TYPE.xs, color: 'var(--text3)' }}>{t.lab}{acctFilter && t.lab === 'Annual' ? ' (filtered)' : ''}</div>
          </div>
        ))}
      </div>

      {/* Tax treatment by account sleeve */}
      {(taxable > 0 || roth > 0 || deferred > 0) && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 12 }}>
          <div style={{ padding: '8px 12px', background: 'rgba(194,65,12,0.06)', border: '1px solid rgba(194,65,12,0.15)', borderRadius: 8 }}>
            <div style={{ fontSize: TYPE.xs, color: BB.orange, fontWeight: 700, textTransform: 'uppercase' }}>Taxable</div>
            <div style={{ fontSize: 16, fontWeight: 800, color: 'var(--text0)' }}>{fmt$(taxable, 0)}<span style={{ fontSize: TYPE.xs, color: 'var(--text3)' }}>/yr</span></div>
          </div>
          <div style={{ padding: '8px 12px', background: 'rgba(30,64,175,0.06)', border: '1px solid rgba(30,64,175,0.15)', borderRadius: 8 }}>
            <div style={{ fontSize: TYPE.xs, color: T.link, fontWeight: 700, textTransform: 'uppercase' }}>Tax-deferred</div>
            <div style={{ fontSize: 16, fontWeight: 800, color: 'var(--text0)' }}>{fmt$(deferred, 0)}<span style={{ fontSize: TYPE.xs, color: 'var(--text3)' }}>/yr</span></div>
          </div>
          <div style={{ padding: '8px 12px', background: 'rgba(21,128,61,0.06)', border: '1px solid rgba(21,128,61,0.15)', borderRadius: 8 }}>
            <div style={{ fontSize: TYPE.xs, color: BB.green, fontWeight: 700, textTransform: 'uppercase' }}>Roth (tax-free)</div>
            <div style={{ fontSize: 16, fontWeight: 800, color: 'var(--text0)' }}>{fmt$(roth, 0)}<span style={{ fontSize: TYPE.xs, color: 'var(--text3)' }}>/yr</span></div>
          </div>
        </div>
      )}

      {/* Charts */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr 1fr', gap: 12, marginBottom: 14 }}>
        <div style={{ background: 'var(--bg2)', borderRadius: 10, padding: 12, border: '1px solid var(--border)', minHeight: 220 }}>
          <div style={{ fontSize: TYPE.xs, fontWeight: 700, color: 'var(--text2)', marginBottom: 8 }}>Annual by position</div>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={rows.slice(0, 10).map(r => ({ name: r.symbol, annual: Math.round(r.annual) }))} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: 'var(--text3)' }} />
              <YAxis tick={{ fontSize: 10, fill: 'var(--text3)' }} tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`} />
              <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 11 }} formatter={(v: number) => [fmt$(v, 0), 'Annual']} />
              <Bar dataKey="annual" fill={BB.amber} radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div style={{ background: 'var(--bg2)', borderRadius: 10, padding: 12, border: '1px solid var(--border)', minHeight: 220 }}>
          <div style={{ fontSize: TYPE.xs, fontWeight: 700, color: 'var(--text2)', marginBottom: 8 }}>Monthly pattern</div>
          {months.length === 0 ? (
            <div style={{ color: 'var(--text3)', fontSize: TYPE.xs, padding: 20 }}>No monthly summary</div>
          ) : (
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={months} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="name" tick={{ fontSize: 10, fill: 'var(--text3)' }} />
                <YAxis tick={{ fontSize: 10, fill: 'var(--text3)' }} tickFormatter={(v: number) => `$${v}`} />
                <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 11 }} formatter={(v: number) => [fmt$(v, 0), 'Est.']} />
                <Bar dataKey="total" fill={T.link} radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
        <div style={{ background: 'var(--bg2)', borderRadius: 10, padding: 12, border: '1px solid var(--border)', minHeight: 220 }}>
          <div style={{ fontSize: TYPE.xs, fontWeight: 700, color: 'var(--text2)', marginBottom: 8 }}>Top payers</div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <div style={{ width: 120, height: 120 }}>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={donut} dataKey="value" nameKey="name" innerRadius={32} outerRadius={54} paddingAngle={1}>
                    {donut.map((_, i) => <Cell key={i} fill={DONUT_COLORS[i % DONUT_COLORS.length]} />)}
                  </Pie>
                  <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 11 }} formatter={(v: number) => fmt$(v, 0)} />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div style={{ flex: 1, maxHeight: 160, overflow: 'auto' }}>
              {donut.map((d, i) => (
                <div key={d.name} style={{ display: 'flex', gap: 6, alignItems: 'center', padding: '2px 0', fontSize: TYPE.xs }}>
                  <span style={{ width: 8, height: 8, borderRadius: 2, background: DONUT_COLORS[i % DONUT_COLORS.length], flexShrink: 0 }} />
                  <span style={{ fontWeight: 700, color: 'var(--text1)', minWidth: 36 }}>{d.name}</span>
                  <span style={{ marginLeft: 'auto', color: 'var(--text3)' }}>{fmt$(d.value, 0)}</span>
                </div>
              ))}
            </div>
          </div>
          {(viewQual > 0 || viewOrd > 0) && (
            <div style={{ marginTop: 8, fontSize: TYPE.xs, color: 'var(--text3)' }}>
              Qual {fmt$(viewQual, 0)} · Ord {fmt$(viewOrd, 0)}
            </div>
          )}
        </div>
      </div>

      {/* Payers table */}
      {rows.length === 0 ? (
        <div style={{ color: 'var(--text3)', fontSize: TYPE.base, padding: 12 }}>No dividend payers match this account filter.</div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: TYPE.sm }}>
            <thead>
              <tr style={{ color: 'var(--text3)' }}>
                <th style={{ textAlign: 'left', padding: '4px 8px' }}>Symbol</th>
                <th style={{ textAlign: 'right', padding: '4px 8px' }}>Yield</th>
                <th style={{ textAlign: 'right', padding: '4px 8px' }}>Annual</th>
                <th style={{ textAlign: 'right', padding: '4px 8px' }}>Monthly</th>
                <th style={{ textAlign: 'left', padding: '4px 8px' }}>Freq</th>
                <th style={{ textAlign: 'left', padding: '4px 8px' }}>Tax</th>
                <th style={{ textAlign: 'left', padding: '4px 8px' }}>Safety</th>
                {!acctFilter && <th style={{ textAlign: 'left', padding: '4px 8px' }}>Account</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((p, i) => (
                <tr key={`${p.symbol}-${p.account}-${i}`} style={{ borderTop: '1px solid rgba(148,163,184,.12)', color: 'var(--text1)' }}>
                  <td style={{ textAlign: 'left', padding: '4px 8px', fontWeight: 700, fontFamily: 'monospace' }}>{p.symbol}</td>
                  <td style={{ textAlign: 'right', padding: '4px 8px', color: BB.green }}>{p.yield_pct.toFixed(2)}%</td>
                  <td style={{ textAlign: 'right', padding: '4px 8px', fontFamily: 'monospace', fontWeight: 700, color: BB.amber }}>{fmt$(p.annual, 0)}</td>
                  <td style={{ textAlign: 'right', padding: '4px 8px', fontFamily: 'monospace' }}>{fmt$(p.monthly, 0)}</td>
                  <td style={{ textAlign: 'left', padding: '4px 8px', color: 'var(--text2)', fontSize: TYPE.xs }}>{p.frequency}</td>
                  <td style={{ textAlign: 'left', padding: '4px 8px', fontSize: TYPE.xs, color: p.qualified ? BB.green : BB.amber }}>{p.qualified ? 'Qual' : 'Ord'}</td>
                  <td style={{ textAlign: 'left', padding: '4px 8px', fontSize: TYPE.xs, color: p.safety === 'strong' ? BB.green : BB.amber }}>{p.safety}</td>
                  {!acctFilter && <td style={{ textAlign: 'left', padding: '4px 8px', color: 'var(--text3)', fontSize: TYPE.xs }}>{(p.account || '—').replace(/_/g, ' ')}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(divs.ex_div_alerts?.length ?? 0) > 0 && (
        <div style={{ marginTop: 14 }}>
          <div style={{ fontSize: TYPE.base, fontWeight: 700, color: 'var(--text0)', marginBottom: 6 }}>Upcoming ex-div</div>
          {(divs.ex_div_alerts as any[]).slice(0, 8).map((a: any, i: number) => (
            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid var(--border)', fontSize: TYPE.sm }}>
              <span style={{ fontFamily: 'monospace', fontWeight: 700 }}>{a.symbol}</span>
              <span style={{ color: 'var(--text2)' }}>{a.ex_date}</span>
              <span style={{ color: BB.green }}>{a.amount}</span>
            </div>
          ))}
        </div>
      )}

      <div style={{ fontSize: TYPE.xs, color: 'var(--text3)', marginTop: 10 }}>
        Source: /api/v2/dividends · attribution: {attribution}
        {acctFilter ? ' · filtered by account' : ''}. Targets: min {fmt$(MINIMUM, 0)} / target {fmt$(TARGET, 0)} / stretch {fmt$(STRETCH, 0)}.
      </div>
    </div>
  )
}
