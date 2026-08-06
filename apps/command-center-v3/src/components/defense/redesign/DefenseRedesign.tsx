/** Defense Desk redesign v1 — sections 1-5 and 7-9 of the visual contract.
 *
 * Section 6 (rotation quadrant + ranked lists) is PRESERVED, not rebuilt
 * (contract §5) and arrives as `quadrant`. Live components absent from the
 * mockup are preserved unmodified below section 9 (contract §2b amendment,
 * operator 2026-07-29) and arrive as `preserved`.
 *
 * Structure and style are frozen; every number, count, chip and verdict is live.
 * Nulls render through <Unk>, never as an em-dash, zero, or blank.
 *
 * Read-only. Nothing here places, stages, or approves an order.
 */
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { S, panel, ph, mono, chip, th, thL, td, tdL, tdProse, btn } from '../../../lib/defenseRedesign'
import { Val, Unk, isNum, pct, signColor, compact, money } from './Val'
import { transitionRead, isStyleRow } from './transitionRead'
import SectorLeadersCard from '../SectorLeadersCard'
import CashAlternatives from './CashAlternatives'

const HORIZONS = [{ k: 'W', l: '1 week' }, { k: 'M', l: '1 month' }, { k: 'Q', l: '1 quarter' }]
const STALE_DAYS = 5

const ageDays = (iso?: string | null) => {
  if (!iso) return null
  const d = Math.floor((Date.now() - new Date(iso).getTime()) / 86400e3)
  return Number.isFinite(d) ? d : null
}
const ageShort = (iso?: string | null) => {
  if (!iso) return 'never'
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (m < 60) return `${m}m`
  if (m < 48 * 60) return `${Math.round(m / 60)}h`
  return `${Math.round(m / 1440)}d`
}

/* ─────────────────────────── 1. COMMAND STRIP ─────────────────────────── */
function CommandStrip({ sources, staleSectors, grokHealth, engineGaps, llmTimeline, onRefresh, refreshing }: {
  sources: Record<string, string | null>
  staleSectors: string[]
  grokHealth?: { available: boolean; status: number } | null
  engineGaps?: { gaps: { sector: string; etf: string; days_stale: number }[]; last_check: string | null } | null
  llmTimeline?: { seats: Record<string, { last_run: string | null; status: string; age_m: number | null }>; schedule: { label: string; et: string; next_et: string; in_min: number; seats: string[] }[] } | null
  onRefresh: () => void
  refreshing: boolean
}) {
  const tl = llmTimeline
  const seatLabel: Record<string, string> = { deepseek: 'DS Flash', chatgpt: 'GPT', grok: 'Grok', paid_ds: 'DS Pro', paid: 'Claude', paid_gpt: 'GPT Pro', paid_xai: 'Grok Pro' }
  const seatChip = (name: string, s: { last_run: string | null; status: string; age_m: number | null }) => {
    const label = seatLabel[name] || name
    const ageStr = s.age_m != null ? (s.age_m >= 1440 ? `${Math.round(s.age_m / 1440)}d` : `${Math.round(s.age_m)}m`) : '—'
    const ok = s.status === 'ok'
    const tone = ok ? 'g' : s.status === 'cached' ? 'n' : s.status === 'unavailable' ? 'r' : 'a'
    return (
      <span key={name} style={chip(tone)} title={`${label}: ${s.status} · last run ${s.last_run || 'never'} (${ageStr} ago)`}>
        {label} {ageStr}
      </span>
    )
  }
  const nextBuild = tl?.schedule?.find(s => s.seats.includes('deepseek'))
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16, flexWrap: 'wrap', marginBottom: 6 }}>
      <div>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 600, color: S.t0 }}>Defense Desk</h1>
        <div style={{ color: S.t2, fontSize: 12, marginTop: 2 }}>
          institutional rotation · portfolio defense · nothing here places orders
        </div>
      </div>
      <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        {Object.entries(sources || {}).map(([k, ts]) => (
          <span key={k} style={chip('n')} title={`${k.replace(/_/g, ' ')} snapshot written ${ts || 'never'}`}>
            {k.replace(/_/g, ' ')} {ageShort(ts)}
          </span>
        ))}
        {staleSectors.length > 0 && (
          <span style={chip('a')} title={`no refresh in over ${STALE_DAYS} days: ${staleSectors.join(', ')}`}>
            {staleSectors.length} sector{staleSectors.length === 1 ? '' : 's'} stale &gt;{STALE_DAYS}d
          </span>
        )}
        {grokHealth && (
          <span style={chip(grokHealth.available ? 'g' : 'r')} title={grokHealth.available ? 'Grok OAuth proxy reachable' : 'Grok OAuth proxy unreachable — oversight seat unavailable'}>
            GROK {grokHealth.available ? 'LIVE' : 'DOWN'}
          </span>
        )}
        {(engineGaps?.gaps?.length ?? 0) > 0 && (
          <span style={chip('a')} title={`engine gap filed for: ${engineGaps!.gaps.map(g => g.etf).join(', ')}`}>
            {engineGaps!.gaps.length} GAP{engineGaps!.gaps.length === 1 ? '' : 'S'} FILED
          </span>
        )}
        {tl?.seats && Object.entries(tl.seats).filter(([n]) => !n.startsWith('paid')).map(([n, s]) => seatChip(n, s))}
        {tl?.seats && Object.entries(tl.seats).filter(([n]) => n.startsWith('paid')).length > 0 && (
          <span style={{...chip('n'), borderStyle: 'dashed'}} title="Paid seats (weekly, metered)">
            ⚖ {Object.entries(tl.seats).filter(([n]) => n.startsWith('paid')).map(([n, s]) => `${seatLabel[n] || n} ${s.age_m != null ? Math.round(s.age_m / 1440)+'d' : '—'}`).join(' · ')}
          </span>
        )}
        {nextBuild && (
          <span style={chip('n')} title={`Next oversight build: ${nextBuild.et} ET (in ${Math.round(nextBuild.in_min / 60)}h ${Math.round(nextBuild.in_min % 60)}m)`}>
            next {nextBuild.et} ({Math.round(nextBuild.in_min / 60)}h)
          </span>
        )}
        <button style={btn()} onClick={onRefresh} disabled={refreshing}>
          {refreshing ? 'refreshing…' : 'refresh all'}
        </button>
      </div>
    </div>
  )
}

/* ─────────────────────────── 2. WHERE TO ACT ──────────────────────────── */
interface Tile { rank: number | null; name: string; etf: string; weight: number | null;
                 tone: 'g' | 'r' | 'a' | 'n'; headline: string; hcolor: string; sub: string }

function whereToAct(sectors: any[], leaders: Record<string, any>): Tile[] {
  const secs = sectors.filter(s => !isStyleRow(s.etf))
  if (!secs.length) return []
  const weights = secs.map(s => s.book_weight_pct).filter(isNum) as number[]
  const median = weights.length ? [...weights].sort((a, b) => a - b)[Math.floor(weights.length / 2)] : 0
  const tiles: Tile[] = []
  const used = new Set<string>()
  const push = (t: Tile) => { if (t.etf && !used.has(t.etf)) { used.add(t.etf); tiles.push(t) } }

  const best = secs.find(s => isNum(s.book_weight_pct) && (s.book_weight_pct as number) <= median)
  if (best) {
    const ld = leaders[best.key]
    const n = ld?.industries?.[0]
    push({
      rank: best.rank, name: best.name, etf: best.etf, weight: best.book_weight_pct, tone: 'g',
      headline: 'Top-ranked sector, near-smallest position', hcolor: S.green,
      sub: n ? `${n.passing_count} names pass filters in ${n.name}` : 'select the sector to descend to names',
    })
  }
  const worst = [...secs].reverse().find(s => isNum(s.book_weight_pct) && (s.book_weight_pct as number) > median)
  if (worst) {
    const cmp = best && isNum(best.book_weight_pct) && (best.book_weight_pct as number) > 0
      ? `${((worst.book_weight_pct as number) / (best.book_weight_pct as number)).toFixed(1)}× ${best.name}'s weight`
      : 'above the median weight'
    push({
      rank: worst.rank, name: worst.name, etf: worst.etf, weight: worst.book_weight_pct, tone: 'r',
      headline: `Worst-ranked sector, ${cmp}`, hcolor: S.red,
      sub: `rank ${worst.rank} of ${worst.rank_total} · RS20 ${isNum(worst.rs20) ? pct(worst.rs20) : 'unknown'}`,
    })
  }
  const largest = [...secs].sort((a, b) => (b.book_weight_pct ?? -1) - (a.book_weight_pct ?? -1))[0]
  if (largest) {
    push({
      rank: largest.rank, name: largest.name, etf: largest.etf, weight: largest.book_weight_pct, tone: 'g',
      headline: 'Leading, but your largest single exposure', hcolor: S.amber,
      sub: `rank ${largest.rank} of ${largest.rank_total} · ${(largest.state || '').toLowerCase()}`,
    })
  }
  // The STALEST, not merely the first stale one — 16 days beats 6.
  const stale = secs
    .filter(s => { const d = ageDays(s.as_of); return d !== null && d > STALE_DAYS })
    .sort((a, b) => (ageDays(b.as_of) ?? 0) - (ageDays(a.as_of) ?? 0))[0]
  if (stale) {
    push({
      rank: stale.rank, name: stale.name, etf: stale.etf, weight: stale.book_weight_pct, tone: 'n',
      headline: `Reading is ${ageDays(stale.as_of)} days old — not current`, hcolor: S.amber,
      sub: `last refresh ${stale.as_of} · engine gap filed`,
    })
  }
  return tiles.slice(0, 4)
}

function WhereToAct({ tiles, maxWeight }: { tiles: Tile[]; maxWeight: number }) {
  return (
    <section style={{ ...panel, borderColor: 'rgba(255,176,0,.28)', marginTop: 14 }}>
      <div style={{ ...ph, background: 'rgba(255,176,0,.06)' }}>
        <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: S.t0 }}>Where to act</h2>
        <span style={{ color: S.t2, fontSize: 12 }}>rank against your weight · the four largest mismatches</span>
        <span style={{ ...chip('a'), marginLeft: 'auto' }}>shadow · nothing routes</span>
      </div>
      {tiles.length === 0 ? (
        <div style={{ padding: '13px 16px', color: S.t3, fontSize: 12 }}>
          No sector rows available — the momentum engine has not written a snapshot.
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: `repeat(${tiles.length},1fr)`, gap: 1, background: S.line }}>
          {tiles.map(t => (
            <div key={t.etf} style={{ background: S.bg1, padding: '13px 16px' }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 7 }}>
                <span style={chip(t.tone)}>#{t.rank ?? '?'}</span>
                <strong style={{ fontSize: 15, color: S.t0 }}>{t.name}</strong>
                <span style={{ ...mono, color: S.t2, fontSize: 12 }}>{t.etf}</span>
              </div>
              <div style={{ ...mono, fontSize: 26, color: t.tone === 'n' ? S.t3 : S.t0, margin: '7px 0 2px' }}>
                <Val value={t.weight} suffix="%" reason="effective sector weight unavailable" />
              </div>
              <div style={{ height: 5, borderRadius: 3, background: S.sunk, overflow: 'hidden', marginBottom: 7 }}>
                <span style={{
                  display: 'block', height: '100%',
                  width: `${isNum(t.weight) && maxWeight > 0 ? Math.min(100, (t.weight / maxWeight) * 100) : 0}%`,
                  background: t.tone === 'r' ? S.red : t.tone === 'n' ? S.t3 : t.hcolor === S.amber ? S.amber : S.green,
                }} />
              </div>
              <div style={{ fontSize: 12, color: t.hcolor }}>{t.headline}</div>
              <div style={{ color: S.t2, fontSize: 12, marginTop: 5 }}>{t.sub}</div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

/* ─────────────────────────── 3. MARKET STATE ──────────────────────────── */
function Cell({ label, value, tone, sub }: { label: string; value: ReactNode; tone?: string; sub?: ReactNode }) {
  return (
    <div style={{ background: S.bg1, padding: '11px 16px' }}>
      <div style={{ color: S.t2, fontSize: 11 }}>{label}</div>
      <div style={{ ...mono, fontSize: 19, color: tone || S.t0 }}>{value}</div>
      {sub ? <div style={{ color: S.t3, fontSize: 11 }}>{sub}</div> : null}
    </div>
  )
}

function MarketState({ net, cashPct, tech, hedges, transitions, vix, regime, tape, cashUsd }: any) {
  return (
    <section style={{ ...panel, marginTop: 14 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6,1fr)', gap: 1, background: S.line }}>
        <Cell label="Net equity" value={<Val value={net} suffix="%" reason="net exposure not published" />} />
        <Cell label="Cash" value={<Val value={cashPct} suffix="%" reason="cash percentage not published" />}
              sub={isNum(cashUsd) ? `≈ ${money(cashUsd)} · already a hedge` : undefined} />
        <Cell label="Effective tech" value={<Val value={tech?.book_pct} suffix="%" reason="no Technology row" />}
              tone={S.red} sub={isNum(tech?.book_direct_pct) ? `${tech.book_direct_pct}% direct + look-through` : undefined} />
        <Cell label="Hedges live / advised" value={`${hedges?.live ?? 0} / ${hedges?.advised ?? 0}`} />
        <Cell label="Transitions today" value={String(transitions)} tone={transitions > 0 ? S.amber : S.t0} />
        <Cell label="VIX · regime" value={<Val value={vix} fmt={v => v.toFixed(2)} reason="no VIX in the summary payload" />}
              sub={regime || undefined} />
      </div>
      <div style={{ padding: '10px 16px', borderTop: `1px solid ${S.line}`, fontSize: 12, color: S.t2 }}>
        {tape || <Unk reason="market_state_line has not been generated" />}
      </div>
    </section>
  )
}

/* ─────────────────────────── 4. TRANSITIONS ───────────────────────────── */
function Transitions({ transitions, rows }: { transitions: any[]; rows: any[] }) {
  return (
    <section style={{ ...panel, marginTop: 14 }}>
      <div style={ph}>
        <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: S.t0 }}>Transitions</h2>
        <span style={{ color: S.t2, fontSize: 12 }}>day-2 confirmed state changes</span>
      </div>
      {transitions.length === 0 ? (
        <div style={{ padding: '12px 16px', color: S.t3, fontSize: 12 }}>
          No confirmed state changes today. The engine debounces two consecutive closes before a
          transition is published, so an empty table means no sector cleared that bar.
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              <th style={thL}>Sector</th><th style={th}>Change</th><th style={th}>RS 5d</th>
              <th style={th}>Breadth</th><th style={th}>Your exposure</th>
              <th style={{ ...thL, paddingLeft: 18 }}>Read</th>
            </tr></thead>
            <tbody style={mono}>
              {transitions.map((t, i) => {
                const r = rows.find(x => x.etf === t.etf) || {}
                const read = transitionRead(t, rows)
                return (
                  <tr key={i}>
                    <td style={{ ...tdL, color: S.t0 }}>{t.sector}</td>
                    <td style={{ ...td, color: S.t2 }}>
                      {String(t.from || '').toLowerCase()} → {String(t.to || '').toLowerCase()}
                    </td>
                    <td style={{ ...td, color: signColor(r.rs5) }}>
                      <Val value={r.rs5} fmt={v => pct(v)} reason="no 5-day RS on this row" />
                    </td>
                    <td style={{ ...td, color: isNum(r.breadth_pct) && r.breadth_pct < 40 ? S.amber : S.t1 }}>
                      {isStyleRow(t.etf) && !isNum(r.breadth_pct)
                        ? <Unk reason="style spreads have no constituent breadth" />
                        : <Val value={r.breadth_pct} suffix="%" reason="breadth not computed for this sector" />}
                    </td>
                    <td style={td}>
                      {isNum(r.book_pct)
                        ? <>{r.book_pct}% · {money(r.book_dollars)}</>
                        : <Unk reason="style spreads carry no book exposure" />}
                    </td>
                    <td style={{ ...tdProse, color: S.t2 }}>{read}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

/* ─────────────────────────── 7. YOUR BOOK ─────────────────────────────── */
function YourBook({ stances, ladders, bookRanks, notDecomposed }: any) {
  const rows: any[] = stances || []
  // Ladders arrive as their OWN array keyed by symbol+account, not on the stance.
  const ladderFor = (p: any) => (ladders || []).find(
    (l: any) => l.symbol === p.symbol && l.account === p.account)
  const ladderChips = (p: any): string[] => {
    const l = ladderFor(p)
    if (!l) return []
    const out: string[] = []
    if (l.t1_fraction != null) out.push(`T1 ${l.t1_fraction}% ${l.t1_status || 'advised'}`)
    const fired = (l.tranches || []).filter((t: any) => t.status === 'fired').length
    if (fired) out.push(`${fired} fired`)
    return out
  }
  const counts = rows.reduce((a: any, s: any) => {
    const k = String(s.stance || '').toUpperCase()
    a[k] = (a[k] || 0) + 1; return a
  }, {})
  const shown = rows.slice(0, 7)
  return (
    <section style={{ ...panel, marginTop: 14 }}>
      <div style={ph}>
        <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: S.t0 }}>Your book</h2>
        <span style={{ color: S.t2, fontSize: 12 }}>every position ≥$10K has a stance · ★ = core registry</span>
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          {counts['TRIM-WATCH'] ? <span style={chip('a')}>{counts['TRIM-WATCH']} trim-watch</span> : null}
          {counts['TRIM'] ? <span style={chip('r')}>{counts['TRIM']} trim</span> : null}
          {counts['HOLD'] ? <span style={chip('n')}>{counts['HOLD']} hold</span> : null}
        </span>
      </div>
      {shown.length === 0 ? (
        <div style={{ padding: '12px 16px', color: S.t3, fontSize: 12 }}>
          No stances published — the recommendations engine has not run since the last book refresh.
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              <th style={thL}>Position</th><th style={th}>Value</th><th style={th}>Sector rank</th>
              <th style={th}>Stance</th><th style={th}>Account</th>
              <th style={{ ...thL, paddingLeft: 18 }}>Ladder</th>
            </tr></thead>
            <tbody style={mono}>
              {shown.map((p: any, i: number) => {
                const br = bookRanks?.[p.symbol]
                const stance = String(p.stance || '').toUpperCase()
                const tone = stance === 'TRIM' ? S.red : stance === 'TRIM-WATCH' ? S.amber : S.t1
                return (
                  <tr key={i}>
                    <td style={tdL}>
                      {p.is_core ? <span style={{ ...chip('a'), marginRight: 6 }}>★</span> : null}
                      <span style={{ color: S.t0 }}>{p.symbol}</span>
                    </td>
                    <td style={td}>{money(p.value) || <Unk reason="no market value on this position" />}</td>
                    <td style={{ ...td, color: br?.rank ? S.green : S.t3 }}>
                      {br?.rank ? `#${br.rank} ${br.sector}` : <Unk reason={br?.reason || 'no sector mapping for this symbol'} />}
                    </td>
                    <td style={{ ...td, color: tone }}>{stance || <Unk reason="no stance published" />}</td>
                    <td style={{ ...td, color: S.t2 }}>{p.account_label || p.account || <Unk reason="no account on this row" />}</td>
                    <td style={{ ...tdProse }}>
                      {ladderChips(p).length
                        ? ladderChips(p).map((c: string, j: number) => (
                            <span key={j} style={{ ...chip('r'), marginRight: 5 }}>{c}</span>))
                        : <span style={{ color: S.t3 }}>—</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <div style={{ color: S.t3, padding: '9px 16px', fontSize: 11, borderTop: `1px solid ${S.line}` }}>
        {rows.length > shown.length ? `${rows.length - shown.length} further positions ≥$10K · ` : ''}
        {isNum(notDecomposed) ? `${money(notDecomposed)} not decomposed` : 'decomposition total unavailable'}
      </div>
    </section>
  )
}

/* ────────────────────── 8. SHORT SIDE + HEDGES ────────────────────────── */
function ShortSide({ cards }: { cards: any[] }) {
  return (
    <section style={panel}>
      <div style={ph}>
        <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: S.t0 }}>Short side</h2>
        <span style={{ color: S.t2, fontSize: 12 }}>lagging industry → name · taxable only</span>
        <span style={{ ...chip('a'), marginLeft: 'auto' }}>shadow</span>
      </div>
      {cards.length === 0 ? (
        <div style={{ padding: '12px 16px', color: S.t3, fontSize: 12 }}>
          No short advisories today — no lagging industry produced a name clearing the anti-squeeze,
          liquidity and stop-distance rails.
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              <th style={thL}>Name</th><th style={th}>Entry</th><th style={th}>Buy-stop</th>
              <th style={th}>vs 200DMA</th><th style={{ ...thL, paddingLeft: 18 }}>Industry</th>
            </tr></thead>
            <tbody style={mono}>
              {cards.map((c: any, i: number) => {
                const sym = c.instruments?.[0]?.symbol || c.title?.split('·')?.[1]?.trim()?.split(' ')?.[0]
                const f = (n: string) => (c.factors || []).find((x: any) => (x.name || '').includes(n))?.value
                const dma = f('200DMA')
                const num = typeof dma === 'string' ? parseFloat(dma) : dma
                return (
                  <tr key={i}>
                    <td style={{ ...tdL, color: S.t0 }}>{sym || <Unk reason="no instrument on this card" />}</td>
                    <td style={td}><Val value={c.levels?.price} fmt={v => v.toFixed(2)} reason="no entry level" /></td>
                    <td style={td}>{String(c.levels?.stop || '').match(/[\d.]+/)?.[0] || <Unk reason="no buy-stop level" />}</td>
                    <td style={{ ...td, color: S.red }}>{isNum(num) ? `${num}%` : <Unk reason="no 200DMA distance" />}</td>
                    <td style={{ ...tdProse, color: S.t2 }}>
                      {f('industry state')?.replace(/ LAGGING.*/, '') || <Unk reason="no industry on this card" />}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function Hedges({ candidates }: { candidates: any[] }) {
  // Shape: candidates[] of { inverse, bench, lights: { THESIS|ENTRY|MANAGE|EXIT:
  // { state, label, reason } } }. Armed pairs sort first — a GREEN thesis is the
  // only one the operator can act on.
  const tone = (st?: string) => st === 'GREEN' ? 'g' : st === 'AMBER' ? 'a' : 'r'
  const rows = [...candidates].sort((a, b) =>
    (b.lights?.THESIS?.state === 'GREEN' ? 1 : 0) - (a.lights?.THESIS?.state === 'GREEN' ? 1 : 0))
  return (
    <section style={panel}>
      <div style={ph}>
        <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: S.t0 }}>Inverse-ETF hedges</h2>
        <span style={{ color: S.t2, fontSize: 12 }}>−1× lane · daily-reset, governed max hold</span>
      </div>
      {rows.length === 0 ? (
        <div style={{ padding: '12px 16px', color: S.t3, fontSize: 12 }}>
          No inverse lane published — the stoplight engine has not written a snapshot.
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              <th style={thL}>Pair</th><th style={th}>Thesis</th><th style={th}>Entry</th>
              <th style={{ ...thL, paddingLeft: 18 }}>State</th>
            </tr></thead>
            <tbody style={mono}>
              {rows.map((l: any, i: number) => {
                const armed = l.lights?.THESIS?.state === 'GREEN'
                const entry = l.lights?.ENTRY
                return (
                  <tr key={i}>
                    <td style={{ ...tdL, color: armed ? S.t0 : S.t2 }}>{l.inverse} / {l.bench}</td>
                    <td style={td}>
                      <span style={chip(tone(l.lights?.THESIS?.state))}>
                        {String(l.lights?.THESIS?.state || '?').toLowerCase()}
                      </span>
                    </td>
                    <td style={td}>
                      <span style={chip(tone(entry?.state))}>
                        {String(entry?.state || '?').toLowerCase()}
                      </span>
                    </td>
                    <td style={{ ...tdProse, color: armed ? S.t2 : S.t3 }}>
                      {entry?.label
                        ? <>{entry.label}{entry.reason ? ` — ${entry.reason}` : ''}</>
                        : <Unk reason="no entry evaluation on this pair" />}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

/* ─────────────────────────── 9. OVERSIGHT ─────────────────────────────── */
function Oversight({ oversight }: { oversight: any }) {
  // `seats` is an OBJECT keyed by seat name — chatgpt / grok / paid / paid_gpt /
  // paid_xai — each { status, verdicts, memo:{ strongest_objection, top_concerns,
  // blind_spots, incoherences }, at }. Seats with status !== 'ok' (grok is
  // currently 'unavailable') carry no memo and must not be selected.
  //
  // Selection is deterministic: freshest usable seat supplies the objection, the
  // freshest OTHER usable seat supplies the counterpoint. The mockup's specific
  // pair is sample data (a VALUE per contract §1), the two-slot structure is not.
  const usable = Object.entries(oversight?.seats || {})
    .map(([seat, s]: [string, any]) => ({ seat, ...(s || {}) }))
    .filter(s => s.status === 'ok' && (s.memo?.strongest_objection || s.memo?.top_concerns?.length))
    .sort((a, b) => String(b.at || '').localeCompare(String(a.at || '')))

  const top = usable[0]
  const alt = usable[1]
  const objection = top?.memo?.strongest_objection || top?.memo?.top_concerns?.[0] || null
  const counter = alt?.memo?.strongest_objection || alt?.memo?.top_concerns?.[0] || null
  // Coverage: how many cards each seat reviewed (stored in memo.coverage e.g. "42/53 cards")
  const topCov = top?.memo?.coverage || null
  const altCov = alt?.memo?.coverage || null
  return (
    <section style={{ ...panel, marginTop: 14 }}>
      <div style={ph}>
        <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: S.t0 }}>Oversight</h2>
        <span style={{ color: S.t2, fontSize: 12 }}>five seats · informs, never blocks</span>
        {oversight?.build_hash ? <span style={{ ...chip('n'), marginLeft: 'auto' }}>build {String(oversight.build_hash).slice(0, 8)}</span> : null}
      </div>
      {!objection && !counter ? (
        <div style={{ padding: '13px 16px', color: S.t3, fontSize: 12 }}>
          No oversight memo on the current build. Seats run when the recommendations engine rebuilds;
          none has returned a parseable objection for this build hash.
        </div>
      ) : (
        <>
          <div style={{ padding: '13px 16px', borderBottom: `1px solid ${S.line}` }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', marginBottom: 5 }}>
              <span style={chip('r')}>strongest objection</span>
              <span style={{ ...mono, color: S.t2, fontSize: 11 }}>
                {top?.seat || 'seat unknown'}{top?.at ? ` · ${top.at}` : ''}
              </span>
              {topCov && <span style={{ ...chip('n'), marginLeft: 'auto' }}>coverage {topCov}</span>}
            </div>
            <div style={{ color: S.t1 }}>{objection || <Unk reason="no objection returned by any seat" />}</div>
          </div>
          <div style={{ padding: '13px 16px' }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', marginBottom: 5 }}>
              <span style={chip('a')}>counterpoint</span>
              <span style={{ ...mono, color: S.t2, fontSize: 11 }}>
                {alt?.seat ? `${alt.seat}${alt.at ? ` · ${alt.at}` : ''}` : ''}
              </span>
            </div>
            <div style={{ color: S.t2 }}>{counter || <Unk reason="only one seat returned a usable memo — no counterpoint available" />}</div>
          </div>
        </>
      )}
    </section>
  )
}

/* ═══════════════════════════ COMPOSITION ══════════════════════════════ */
export default function DefenseRedesign({ posture, recsData, tradeAi, regime, industriesCapturedAt, onRefresh, refreshing, quadrant, preserved }: {
  posture: any; recsData: any; tradeAi: any; regime: any; industriesCapturedAt?: string | null
  onRefresh: () => void; refreshing: boolean
  quadrant: ReactNode; preserved: ReactNode
}) {
  const [sl, setSl] = useState<any>(null)
  const [stoplights, setStoplights] = useState<any[]>([])
  const [horizon, setHorizon] = useState('M')
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => {
    const qs = new URLSearchParams({ horizon })
    if (selected) qs.set('sector', selected)
    let dead = false
    fetch(`/api/v2/defense/sector-leaders?${qs}`).then(r => r.json()).then(j => {
      if (dead) return
      const d = j?.data ?? j
      setSl(d)
      if (!selected && d?.sectors?.length) setSelected(d.sectors[0].key)
    }).catch(() => { /* section renders its own empty state */ })
    return () => { dead = true }
  }, [horizon, selected])

  useEffect(() => {
    let dead = false
    fetch('/api/v2/defense/inverse-stoplights').then(r => r.json()).then(j => {
      if (!dead) setStoplights(((j?.data ?? j)?.candidates) || [])
    }).catch(() => { /* section renders its own empty state */ })
    return () => { dead = true }
  }, [])

  const [cashAlt, setCashAlt] = useState<any>(null)
  useEffect(() => {
    let dead = false
    fetch('/api/v2/defense/cash-alternatives').then(r => r.json()).then(j => {
      if (!dead) setCashAlt(j?.data ?? j)
    }).catch(() => { /* section renders its own empty state */ })
    return () => { dead = true }
  }, [])

  const rows: any[] = posture?.momentum?.rows || []
  const transitions: any[] = posture?.momentum?.transitions_today || []
  const sectors: any[] = sl?.sectors || []
  const staleSectors = useMemo(
    () => sectors.filter(s => { const d = ageDays(s.as_of); return d !== null && d > STALE_DAYS }).map(s => s.etf),
    [sectors])
  const tiles = useMemo(() => whereToAct(sectors, sl?.sector ? { [sl.sector.key]: sl.sector } : {}), [sectors, sl])
  const maxWeight = Math.max(1, ...sectors.map(s => s.book_weight_pct).filter(isNum))

  const recs = recsData?.recommendations
  const sources: Record<string, string | null> = {
    sectors: posture?.momentum?.generated_at ?? null,
    industries: industriesCapturedAt ?? null,
    recs: recs?.generated_at ?? null,
  }

  return (
    <div>
      <CommandStrip sources={sources} staleSectors={staleSectors} grokHealth={posture?.grok_proxy_health} engineGaps={posture?.engine_gaps} llmTimeline={posture?.llm_timeline} onRefresh={onRefresh} refreshing={refreshing} />
      <WhereToAct tiles={tiles} maxWeight={maxWeight} />
      <CashAlternatives data={cashAlt} />
      <MarketState
        net={posture?.net_exposure?.equity_pct}
        cashPct={posture?.net_exposure?.cash_pct}
        cashUsd={posture?.net_exposure?.cash_dollars}
        tech={rows.find(r => r.sector === 'Technology')}
        hedges={{ live: posture?.hedge_state?.live ?? 0, advised: (recs?.groups?.short_side || []).length }}
        transitions={transitions.length}
        vix={tradeAi?.vix}
        regime={String(regime?.regime_label || '').replace(/_/g, ' ') || null}
        tape={posture?.momentum?.market?.state_line}
      />
      <Transitions transitions={transitions} rows={rows} />

      {/* 5. Sector leaders — timeframe toggle + 11-sector picker + expanded card */}
      <section style={{ marginTop: 14 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
          <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: S.t0 }}>Sector leaders</h2>
          <span style={{ color: S.t2, fontSize: 12 }}>sector → confirming industry → names</span>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}>
            {HORIZONS.map(h => (
              <button key={h.k} style={btn(horizon === h.k)} onClick={() => setHorizon(h.k)}>{h.l}</button>
            ))}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginBottom: 10 }}>
          {sectors.map(s => (
            <button key={s.key} style={btn(selected === s.key)} onClick={() => setSelected(s.key)}
                    title={`${s.name} · ${s.state || 'unknown'} · as of ${s.as_of || 'unknown'}`}>
              <span style={{ color: S.t3 }}>#{s.rank ?? '?'}</span>{' '}{s.etf}{' '}
              <span style={mono}>
                {isNum(s.book_weight_pct) ? `${s.book_weight_pct}%` : <Unk reason="no effective weight" />}
              </span>
            </button>
          ))}
        </div>
        {sl?.sector
          ? <SectorLeadersCard sector={sl.sector} variant="redesign" />
          : (
            <div style={{ ...panel, padding: '13px 16px', color: S.t3, fontSize: 12 }}>
              No sector selected, or the sector-leaders endpoint returned nothing for this horizon.
            </div>
          )}
      </section>

      {/* 6. PRESERVED — quadrant + ranked lists, contract §5 */}
      <div style={{ marginTop: 14 }}>{quadrant}</div>

      <YourBook
        stances={recs?.stances}
        ladders={recs?.ladders}
        bookRanks={sl?.book_sector_ranks}
        notDecomposed={recs?.not_decomposed?.dollars ?? posture?.momentum?.not_decomposed?.dollars}
      />

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginTop: 14 }}>
        <ShortSide cards={(recs?.groups?.short_side || []).filter((c: any) => c.direction === 'short')} />
        <Hedges candidates={stoplights} />
      </div>

      <Oversight oversight={recsData?.oversight} />

      {/* Contract §2b — live components absent from the mockup are PRESERVED
          unmodified, below section 9, in their existing order. */}
      <div style={{ marginTop: 22, paddingTop: 14, borderTop: `1px solid ${S.line2}` }}>
        <div style={{ color: S.t3, fontSize: 11, marginBottom: 10 }}>
          Preserved desk components — unchanged by the redesign
        </div>
        {preserved}
      </div>
    </div>
  )
}
