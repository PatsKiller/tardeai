/** Sector Leaders card (SL-S1) — sector → confirming industry → named
 * constituents → account routing.
 *
 * Renders ALONGSIDE the existing RESEARCH WATCH tile behind a default-off flag.
 * The old tile is untouched; retirement is a separate change.
 *
 * DESIGN CONTRACT
 *   1. Renders nothing that places, stages, or approves an order. There are no
 *      action buttons on this card at all — the reference's "Create watch" and
 *      "Evidence" buttons were dropped because this stage adds no write path.
 *   2. Every displayed number goes through <Val>. A missing value renders as an
 *      explicit italic "unknown" with a hover reason, never as an em-dash inside
 *      an otherwise-confident sentence. This is the fix for the live
 *      `breadth 55% (56/— covered)` defect.
 *   3. Ranking and sizing policy are computed server-side. This component
 *      displays a judgment and its inputs; it does not decide what is good.
 *   4. Relative strength per name is against its OWN INDUSTRY, not SPY. Inside a
 *      leading sector every name looks strong against SPY — that is sector beta
 *      arriving, not name selection.
 *
 * Colors come only from watchTokens; raw hexes are build-blocked
 * (check_design_tokens.sh, defense baseline = 0).
 */
import { useMemo, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { BB, DASH, numStyle } from '../../lib/watchTokens'
import { S } from '../../lib/defenseRedesign'
import { Chip } from '../TerminalChip'
import type { SLConstituent, SLIndustry, SLSector } from '../../lib/sectorLeaders'

/** DD-S1: the card is shared by two surfaces and must look right on both.
 *
 *   'v1'       — SectorLeadersPanel, live behind SECTOR_LEADERS_V1 (default ON)
 *   'redesign' — DefenseRedesign, the Defense Desk page itself (no flag)
 *
 * A blind restyle would have changed the LIVE surface while the redesign is
 * meant to stay dark until accepted, so the divergent values are parameterised
 * rather than replaced. Everything the two share (columns, chips, dimming, the
 * <Val> null contract) stays single-sourced.
 */
export type CardVariant = 'v1' | 'redesign'

interface CardTheme {
  cell: string; sunk: string; dim: string; muted: string
  thSize: number; thWeight: number; thTransform: 'none' | 'uppercase'; thSpacing: string
  h3: number
}
const THEMES: Record<CardVariant, CardTheme> = {
  v1: {
    cell: BB.bgPanel, sunk: BB.bgPanel, dim: BB.text3, muted: BB.text3,
    thSize: DASH.data, thWeight: 500, thTransform: 'none', thSpacing: 'normal',
    h3: DASH.panel,
  },
  redesign: {
    // Mockup: cells sit on the panel surface, sunken cells and footers on --sunk,
    // table headers are 10px uppercase on --t3.
    cell: S.bg1, sunk: S.sunk, dim: S.t3, muted: S.t2,
    thSize: 10, thWeight: 800, thTransform: 'uppercase', thSpacing: '.05em',
    h3: 14,
  },
}

const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const pct = (v: number, d = 1) => `${v > 0 ? '+' : ''}${v.toFixed(d)}%`
const signColor = (v: unknown) => (!isNum(v) ? BB.text3 : v > 0 ? BB.green : v < 0 ? BB.red : BB.text3)
const compact = (v: unknown): string | null =>
  !isNum(v) ? null
    : v >= 1e9 ? `${(v / 1e9).toFixed(1)}B`
      : v >= 1e6 ? `${Math.round(v / 1e6)}M`
        : v >= 1e3 ? `${Math.round(v / 1e3)}K`
          : String(v)

/** The null-honesty primitive. EVERY numeric render passes through this. */
export function Val(props: {
  value: number | null | undefined
  fmt?: (v: number) => string
  suffix?: string
  reason?: string
}) {
  const { value, fmt = (v: number) => v.toFixed(1), suffix = '', reason } = props
  if (!isNum(value)) {
    return (
      <span
        title={reason || 'no source for this value'}
        style={{ color: BB.text3, fontStyle: 'italic', fontSize: DASH.data }}
      >
        unknown
      </span>
    )
  }
  return <>{fmt(value)}{suffix}</>
}

/** Rank beside weight, policy-free.
 *
 * Operator decision 2026-07-29: no rank-implied sizing band exists anywhere in
 * the tree, so the signed pp figure cannot be computed honestly. Rather than
 * render the whole strip as unknown, show rank and weight adjacently and let the
 * juxtaposition carry it — #1 at 3.9% against #9 at 7.4% is legible without a
 * policy. The third cell turns on by itself when a policy lands. */
function GapStrip({ sector, t }: { sector: SLSector; t: CardTheme }) {
  const gap = sector.exposure_gap
  const warn = !!gap && gap.state !== 'in band'

  const cell = (label: string, node: ReactNode, sub?: ReactNode, flex = 1, tone?: CSSProperties) => (
    <div style={{ flex, background: t.cell, padding: '10px 16px', ...tone }}>
      <div style={{ fontSize: DASH.data, color: t.muted }}>{label}</div>
      <div style={{ fontSize: DASH.verdict, ...numStyle, marginTop: 4, color: BB.text0 }}>{node}</div>
      {sub ? <div style={{ fontSize: DASH.data, color: t.dim, marginTop: 2 }}>{sub}</div> : null}
    </div>
  )

  return (
    <div style={{ display: 'flex', gap: 1, background: BB.border, borderBottom: `1px solid ${BB.border}` }}>
      {cell(
        'Rank',
        <>
          {isNum(sector.rank) ? `${sector.rank}` : <Val value={null} reason="sector not ranked" />}
          <span style={{ fontSize: DASH.section, color: BB.text3 }}>
            {isNum(sector.rank_total) ? ` of ${sector.rank_total}` : ''}
          </span>
        </>,
        isNum(sector.rank_change) && sector.rank_change !== 0
          ? `${sector.rank_change > 0 ? 'up' : 'down'} ${Math.abs(sector.rank_change)} since prior close`
          : 'flat since prior close',
      )}
      {cell(
        'Your weight',
        <Val value={sector.book_weight_pct} suffix="%" reason="effective sector weight unavailable" />,
        sector.book_weight_basis,
      )}
      {cell(
        'Exposure gap',
        gap
          ? `${gap.pp > 0 ? '+' : ''}${gap.pp.toFixed(1)}pp`
          : <Val value={null} reason="no rank-implied sizing policy is configured — the signed gap cannot be computed without one" />,
        gap ? `${gap.state} the #${sector.rank} sector` : 'no sizing policy configured',
        1.4,
        warn ? { background: BB.amberDim } : undefined,
      )}
    </div>
  )
}

function ConstituentTable({ industry, defaultBlocked, t }: { industry: SLIndustry; defaultBlocked: string[]; t: CardTheme }) {
  const rows = industry.constituents || []
  const sameAsDefault = (b: string[]) =>
    b.length === defaultBlocked.length && b.every(x => defaultBlocked.includes(x))
  if (!rows.length) {
    return (
      <div style={{ padding: '14px 0', color: BB.text3, fontSize: DASH.row }}>
        No constituents passed the liquidity and price filters for this industry.
        {industry.filter_summary ? ` (${industry.filter_summary})` : ''}
      </div>
    )
  }

  const th: CSSProperties = {
    color: t.dim, fontSize: t.thSize, fontWeight: t.thWeight, padding: '6px 0',
    textAlign: 'right', textTransform: t.thTransform, letterSpacing: t.thSpacing,
  }
  const td: CSSProperties = { padding: '9px 0', textAlign: 'right', ...numStyle, fontSize: DASH.row }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed', minWidth: 640 }}>
        <thead>
          <tr>
            <th style={{ ...th, textAlign: 'left', width: '15%' }}>Name</th>
            <th style={{ ...th, width: '13%' }}>Price</th>
            <th
              style={{ ...th, width: '14%' }}
              title="Relative strength against its OWN industry composite, not against SPY. Both sides are the same Finviz window, so the subtraction is like-for-like."
            >
              RS vs ind
            </th>
            <th style={{ ...th, width: '12%' }}>52w high</th>
            <th style={{ ...th, width: '11%' }}>ADV20</th>
            <th style={{ ...th, textAlign: 'left', paddingLeft: 14 }}>Position and flags</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c: SLConstituent) => {
            const lagsGroup = c.lags_own_group
            const heldAccounts = (c.held?.positions || [])
              .map(p => p.account).filter(Boolean).join(', ')
            return (
              <tr
                key={c.symbol}
                style={{ borderTop: `1px solid ${BB.border}`, opacity: lagsGroup ? 0.55 : 1 }}
              >
                <td style={{ ...td, textAlign: 'left', fontWeight: 700, color: BB.text0 }}>{c.symbol}</td>
                <td style={td}><Val value={c.price} fmt={v => v.toFixed(2)} reason="no close in ticker_prices" /></td>
                <td style={{ ...td, color: signColor(c.rs_vs_industry) }}>
                  <Val
                    value={c.rs_vs_industry}
                    fmt={v => pct(v)}
                    reason="industry-relative RS not computed — the name or its industry composite has no return for this window"
                  />
                </td>
                <td style={td}><Val value={c.pct_from_52w_high} fmt={v => pct(v)} reason="no 52-week high in the enrichment cache" /></td>
                <td style={td}>{compact(c.adv_20d) || <Val value={null} reason="no average-volume source for this name" />}</td>
                <td style={{ padding: '9px 0 9px 14px', fontSize: DASH.data }}>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {c.held && (
                      <Chip kind="state" tone="green" title={`Held in ${heldAccounts || 'an account'}`}>
                        HELD
                      </Chip>
                    )}
                    {c.is_core && (
                      <Chip kind="state" tone="amber" title="Core registry: trim-ladder only, never a full exit">
                        CORE
                      </Chip>
                    )}
                    {lagsGroup && (
                      <Chip kind="state" tone="red" title="Negative relative strength against its own industry — a passenger inside a leading group">
                        lags its own group
                      </Chip>
                    )}
                    {isNum(c.days_to_earnings) && c.days_to_earnings >= 0 && c.days_to_earnings <= 10 && (
                      <Chip kind="state" tone="amber">earnings {c.days_to_earnings}d</Chip>
                    )}
                    {/* Only chip routing when this name differs from the
                        card-level default — otherwise the identical blocked list
                        repeats on every row and buries the real per-name flags. */}
                    {c.blocked_accounts?.length > 0 && !sameAsDefault(c.blocked_accounts) && (
                      <Chip kind="state" tone="red" title={c.blocked_reason || undefined}>
                        blocked: {c.blocked_accounts.join(', ')}
                      </Chip>
                    )}
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default function SectorLeadersCard({ sector, variant = 'v1' }: { sector: SLSector; variant?: CardVariant }) {
  const t = THEMES[variant]
  const [openIndustry, setOpenIndustry] = useState<string | null>(sector.industries?.[0]?.key ?? null)

  const decided = useMemo(
    () => (sector.industries || []).filter(i => i.dispersion_verdict).length,
    [sector.industries],
  )

  const stale = isNum(sector.data_age_hours)
    && sector.data_age_hours > (sector.refresh_interval_hours ?? 24)
  const isDefensive = !!sector.defensive_lean?.defensive_sectors?.includes(sector.name)

  return (
    <section
      aria-labelledby={`sector-leaders-${sector.key}`}
      style={{
        background: BB.bgShift, border: `1px solid ${BB.border}`,
        borderRadius: 10, overflow: 'hidden', color: BB.text1,
      }}
    >
      <header style={{ padding: '14px 18px', borderBottom: `1px solid ${BB.border}` }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          <h3 id={`sector-leaders-${sector.key}`} style={{ margin: 0, fontSize: t.h3, color: BB.text0 }}>
            {sector.name}
          </h3>
          <span style={{ ...numStyle, fontSize: DASH.section, color: BB.text3 }}>{sector.etf}</span>
          <Chip kind="state" tone={isNum(sector.rank) && sector.rank <= 3 ? 'green' : 'slate'}>
            rank {isNum(sector.rank) ? sector.rank : '?'} of {isNum(sector.rank_total) ? sector.rank_total : '?'}
          </Chip>
          <Chip kind="state" tone="slate">
            {(sector.state || 'unknown').toLowerCase()} · RS20 <Val value={sector.rs20} fmt={v => pct(v)} />
          </Chip>
          <Chip kind="state" tone="slate" title={`Both the name and industry returns use the Finviz ${sector.horizon_label} window`}>
            {sector.horizon_label || sector.horizon}
          </Chip>
          {stale && (
            <Chip
              kind="state"
              tone="amber"
              title={`Last refreshed ${sector.as_of || 'unknown'} — ${sector.data_age_hours}h against a ${sector.refresh_interval_hours}h refresh interval`}
            >
              stale · as of {sector.as_of || 'unknown'}
            </Chip>
          )}
        </div>
      </header>

      <GapStrip sector={sector} t={t} />

      {sector.defensive_lean?.enabled && (
        <div
          style={{
            padding: '9px 18px', borderBottom: `1px solid ${BB.border}`, fontSize: DASH.data,
            background: BB.amberDim, color: BB.amber,
          }}
          title={sector.defensive_lean.set_by || undefined}
        >
          Defensive-lean directive is active ({sector.defensive_lean.defensive_sectors.join(', ')}).
          {isDefensive
            ? ` ${sector.name} is inside that set.`
            : ` ${sector.name} is outside it — adding here points away from the standing directive.`}
        </div>
      )}

      {/* ETF-versus-names is decided PER INDUSTRY (each industry's own spread
          against the sector ETF), so the verdict lives on the industry rows
          below. The sector-level figure is a diagnostic and is deliberately not
          rendered as a verdict — pooling every confirming industry measures
          inter-industry separation, which is wide almost always. */}
      <div
        style={{
          padding: '9px 18px', borderBottom: `1px solid ${BB.border}`, fontSize: DASH.data,
          background: BB.bgPanel, color: BB.text3,
        }}
        title={sector.dispersion_scope || undefined}
      >
        ETF-versus-names is decided per industry — {decided} of {(sector.industries || []).length}{' '}
        confirming {(sector.industries || []).length === 1 ? 'industry has' : 'industries have'}{' '}
        enough priced names to call it.
        {sector.empty_reason ? ` ${sector.empty_reason}` : ''}
      </div>

      {sector.empty_reason && (sector.industries || []).length === 0 && (
        <div style={{ padding: '12px 18px', borderBottom: `1px solid ${BB.border}`,
                      fontSize: DASH.row, background: BB.redDim, color: BB.red }}>
          No industries to show. {sector.empty_reason}
        </div>
      )}

      {(sector.industries || []).map((ind) => {
        const open = openIndustry === ind.key
        return (
          <div key={ind.key} style={{ borderBottom: `1px solid ${BB.border}` }}>
            <button
              type="button"
              onClick={() => setOpenIndustry(open ? null : ind.key)}
              aria-expanded={open}
              style={{
                width: '100%', display: 'flex', alignItems: 'center', gap: 10,
                padding: '11px 18px', background: 'transparent', border: 0,
                color: 'inherit', textAlign: 'left', cursor: 'pointer', font: 'inherit',
              }}
            >
              <span style={{ fontSize: DASH.section, color: BB.text1 }}>{ind.name}</span>
              <span style={{ fontSize: DASH.data, color: BB.text3, ...numStyle }}>
                {/* GLOBAL rank among all industries, labelled with its basis so it
                    cannot be misread as a within-sector position — it agrees with
                    the Industries list at the foot of the page. */}
                {isNum(ind.rank)
                  ? <>rank {ind.rank}{isNum(ind.rank_total) ? ` of ${ind.rank_total}` : ''}{' · '}</>
                  : null}
                {(ind.state || '').toLowerCase()}
                {' · comp '}
                <Val value={ind.composite_return_pct} fmt={v => pct(v)} reason="no industry composite for this window" />
                {' · '}
                {isNum(ind.passing_count) ? `${ind.passing_count} pass filters` : 'count unknown'}
                {isNum(ind.constituent_count) ? ` of ${ind.constituent_count}` : ''}
              </span>
              {/* THE verdict: this industry's own spread, excess vs the sector ETF. */}
              {ind.dispersion_verdict ? (
                <Chip
                  kind="state"
                  tone={ind.dispersion_verdict === 'buy names' ? 'green'
                    : ind.dispersion_verdict === 'buy the ETF' ? 'amber' : 'slate'}
                  title={`spread ${ind.dispersion?.spread_pp}pp within this industry · top quartile ${ind.dispersion?.top_quartile_excess_pp}pp vs ${sector.etf} · n=${ind.dispersion?.n}`}
                >
                  {ind.dispersion_verdict}
                </Chip>
              ) : (
                <span
                  style={{ fontSize: DASH.data, color: BB.text3, fontStyle: 'italic' }}
                  title={`needs >=8 priced names in this industry; had ${ind.dispersion?.n ?? 0}`}
                >
                  no verdict
                </span>
              )}
              <span style={{ marginLeft: 'auto', color: BB.text3, fontSize: DASH.data }}>
                {open ? 'hide' : 'show names'}
              </span>
            </button>
            {open && (
              <div style={{ padding: '0 18px 14px' }}>
                <ConstituentTable industry={ind} defaultBlocked={sector.accounts?.blocked_long || []} t={t} />
                {ind.source_note && (
                  <div style={{ marginTop: 10, fontSize: DASH.data, color: BB.text3 }}>{ind.source_note}</div>
                )}
              </div>
            )}
          </div>
        )
      })}

      {sector.data_gaps?.length > 0 && (
        <div style={{ padding: '12px 18px', background: BB.bgPanel, borderTop: `1px solid ${BB.border}` }}>
          <div style={{ fontSize: DASH.data, color: BB.text3, marginBottom: 4 }}>
            What this card could not source ({sector.data_gaps.length})
          </div>
          <ul style={{ margin: 0, paddingLeft: 16, color: BB.text3, fontSize: DASH.data }}>
            {sector.data_gaps.map((g, i) => <li key={i} style={{ marginTop: 2 }}>{g}</li>)}
          </ul>
        </div>
      )}

      {sector.accounts && (
        <div style={{ padding: '11px 18px', background: BB.bgPanel, borderTop: `1px solid ${BB.border}`,
                      display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ fontSize: DASH.data, color: BB.text3 }}>Routable (long):</span>
          {sector.accounts.routable_long.length === 0 && (
            <span style={{ fontSize: DASH.data, color: BB.red }}>none</span>
          )}
          {sector.accounts.routable_long.map(a => (
            <Chip key={a} kind="state" tone="green">{a}</Chip>
          ))}
          <span style={{ fontSize: DASH.data, color: BB.text3, marginLeft: 8 }}>blocked:</span>
          {sector.accounts.blocked_long.map(a => (
            <Chip key={a} kind="state" tone="red" title={sector.accounts?.blocked_long_reason || undefined}>{a}</Chip>
          ))}
          <span style={{ fontSize: DASH.data, color: BB.text3, marginLeft: 8 }}
                title={sector.accounts.note || undefined}>
            shorting allowed in: {sector.accounts.routable_short.length
              ? sector.accounts.routable_short.join(', ')
              : 'no account'}
          </span>
        </div>
      )}

      <footer style={{ padding: '10px 18px', background: BB.bgPanel, borderTop: `1px solid ${BB.border}`, fontSize: DASH.data, color: BB.text3 }}>
        Advisory only — read-only view. This card places, stages and approves nothing.
      </footer>
    </section>
  )
}
