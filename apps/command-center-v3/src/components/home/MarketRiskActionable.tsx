/** Design home/v005: the actionable parts of the Home market-risk card — the verdict with dollars, the top review item,
 *  and the sections (sectors with your dollars, since you were stopped out, positions in stressed groups, review now,
 *  budget breaches). Shared by the YELLOW summary card and the ORANGE/RED banner. Tokens only. Every "Review →" opens an
 *  existing page; there is no order, size or stop control anywhere (MBI_BEHAVIOR = 0). */
import type { CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { RADIUS, TOKENS, TYPE, chipStyle, numStyle, toneVars } from '../../lib/designTokens'
import { SUMMARY_PHONE_MAX_PX, fmtUsd, type ActionableModel } from '../../lib/marketRisk'
import { EXPLAIN_CSS, Explain, GlossaryProvider, Segments } from './MarketRiskActions'

const CHIP_TERM: Record<string, string> = { STRESS: 'stress', WEAK: 'weak', RESILIENT: 'resilient', HOLDING: 'holding', 'NOT MEAS.': 'not_measured' }

export const ACTIONABLE_CSS = `${EXPLAIN_CSS}
[data-mr-actionable] table{width:100%;border-collapse:collapse}
[data-mr-actionable] th{font-size:${TYPE.sm}px;color:var(--text-3);font-weight:600;text-align:right;padding:4px 6px;border-bottom:1px solid var(--border-color);white-space:nowrap}
[data-mr-actionable] th:first-child,[data-mr-actionable] td:first-child{text-align:left}
[data-mr-actionable] td{padding:7px 6px;border-bottom:1px solid var(--border-subtle);text-align:right;white-space:nowrap;font-size:${TYPE.base + 1}px}
[data-mr-actionable] .mr-phone-only{display:none}
[data-mr-actionable] .mr-phone-inline{display:none}
@media(max-width:${SUMMARY_PHONE_MAX_PX}px){
 [data-mr-actionable] .mr-phone-inline{display:inline}
 [data-mr-actionable] .mr-hide-phone{display:none}
 [data-mr-actionable] .mr-phone-only{display:block}
 [data-mr-actionable] td,[data-mr-actionable] th{padding:6px 3px}
 [data-mr-actionable] td:first-child{white-space:normal}
}`

const h3: CSSProperties = { display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap', margin: '0 0 6px', fontSize: TYPE.base, color: TOKENS.text[2], textTransform: 'uppercase', letterSpacing: '.05em', fontWeight: 700 }
const sub: CSSProperties = { fontSize: TYPE.sm, color: TOKENS.text[3], marginTop: 4, lineHeight: 1.5 }
const item: CSSProperties = { display: 'flex', flexDirection: 'column', gap: 3, padding: '9px 12px', borderRadius: RADIUS.md, background: TOKENS.bg[0], border: `1px solid ${TOKENS.border}`, fontSize: TYPE.base + 1, lineHeight: 1.45 }
const tap: CSSProperties = { minHeight: 44, display: 'inline-flex', alignItems: 'center', color: TOKENS.info, fontWeight: 700, textDecoration: 'none', whiteSpace: 'nowrap' }
const signed = (n: number | null): CSSProperties => ({ ...numStyle, color: n == null ? TOKENS.text[3] : n < 0 ? toneVars('danger').color : toneVars('success').color })

/** Verdict line and exposure line (inside the card's summary area, visible collapsed). */
export function ActionableHead({ m }: { m: ActionableModel }) {
  return (
    <span style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span data-testid="mr-verdict" style={{ fontSize: TYPE.md + 1, fontWeight: 700, lineHeight: 1.4, color: TOKENS.text[0] }}>{m.verdict}</span>
      {(m.exposure || m.exposureNote) && (
        <span data-testid="mr-exposure" style={{ fontSize: TYPE.md, lineHeight: 1.45, color: m.exposureNote ? toneVars('warning').color : TOKENS.text[1] }}>{m.exposure ?? m.exposureNote}</span>
      )}
    </span>
  )
}

/** The top review item: always visible, a full-width ≥44 px link. */
export function TopReview({ m }: { m: ActionableModel }) {
  const r = m.topReview
  if (!r) return null
  return (
    <Link to={r.to} data-testid="mr-top-review" style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '2px 8px', minHeight: 44, margin: '4px 0 6px', padding: '6px 12px', boxSizing: 'border-box', borderRadius: RADIUS.md, background: TOKENS.bg[0], border: `1px solid ${TOKENS.border}`, fontSize: TYPE.base + 1, color: TOKENS.text[0], textDecoration: 'none' }}>
      <span style={{ color: TOKENS.text[3] }}>Review now</span>
      <span><b>{r.symbol}</b> · {r.account_label} — {r.text} · <span style={numStyle}>{fmtUsd(r.usd)}</span></span>
      <span style={{ marginLeft: 'auto', color: TOKENS.info, fontWeight: 700 }}>Review →</span>
    </Link>
  )
}

function Sectors({ m }: { m: ActionableModel }) {
  return (
    <div data-testid="mr-sectors">
      <h3 style={h3}>Sectors vs SPY · your money in each (look-through <Explain term="look_through" />)</h3>
      <table>
        <thead><tr><th>Group</th><th><span className="mr-hide-phone">1d vs SPY</span><span className="mr-phone-inline">1d</span></th><th><span className="mr-hide-phone">5d vs SPY</span><span className="mr-phone-inline">5d</span></th><th>You</th><th className="mr-hide-phone">% book <Explain term="pct_book" /></th></tr></thead>
        <tbody>
          {m.sectors.map(r => {
            const t = toneVars(r.tone)
            const bg = r.chip === 'STRESS' || r.chip === 'WEAK' ? t.bg : r.unknown && r.held ? toneVars('warning').bg : undefined
            return (
              <tr key={r.key} data-testid="mr-sector-row" data-key={r.key} data-chip={r.chip} style={{ background: bg }}>
                <td><span data-testid="mr-sector-chip" style={{ ...chipStyle(r.tone, 'soft'), marginRight: 2 }}>{r.chip}</span><Explain term={CHIP_TERM[r.chip]} /> {r.label}{r.theme && <span style={{ color: TOKENS.text[3] }}> (theme)</span>}</td>
                {r.unknown
                  ? <td colSpan={2} title={r.reason ?? undefined} style={{ textAlign: 'left', color: toneVars('warning').color, fontWeight: 600, whiteSpace: 'normal' }}>not measured{r.held && <span className="mr-hide-phone"> — you hold {r.usd}</span>}</td>
                  : <><td style={signed(r.rs1n)}>{r.rs1}</td><td style={signed(r.rs5n)}>{r.rs5}</td></>}
                <td style={numStyle}>{r.usd}</td>
                <td className="mr-hide-phone" style={numStyle}>{r.pctBook}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {m.foldLine && <div data-testid="mr-sectors-folded" style={{ fontSize: TYPE.base, color: TOKENS.text[2], padding: '6px 6px 0' }}>{m.foldLine}</div>}
      <div style={sub}>{m.sectorsFoot}</div>
    </div>
  )
}

function Reentry({ m }: { m: ActionableModel }) {
  if (!m.reentry.length && !m.reentryMore) return null
  return (
    <div data-testid="mr-reentry">
      <h3 style={h3}>Since you were stopped out</h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {m.reentry.map(r => {
          const vt = toneVars(r.verdictTone)
          return (
            <div key={r.symbol} data-testid="mr-reentry-row" data-verdict={r.verdict} style={item}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '2px 10px', alignItems: 'baseline' }}><b>{r.symbol}</b><span style={{ color: TOKENS.text[2] }}>{r.head}</span></div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '2px 10px', alignItems: 'center' }}>
                <span>now <b style={numStyle}>{r.now}</b> (<span style={signed(r.vsExitNeg ? -1 : 1)}>{r.vsExit}</span> vs exit){r.vsMa && <> · <span style={numStyle}>{r.vsMa}</span></>} {r.trend}</span>
                <span data-testid="mr-reentry-verdict" style={{ ...chipStyle(r.verdictTone, 'soft'), color: vt.color }}>{r.verdict.toUpperCase()}</span>
              </div>
              <div><b>Stage 1 <Explain term="stage1" /> (early setup): {r.stage1}</b><span style={{ color: TOKENS.text[2] }}> — waiting: {r.waiting}</span></div>
              <div>Invalidates below <Explain term="invalidates_below" /> <b style={numStyle}>{r.invalidates}</b><span style={{ color: TOKENS.text[2] }}> (selloff low) · Stage 2 <Explain term="stage2" /> (confirmed): {r.stage2}</span></div>
              {r.wash && <div data-testid="mr-reentry-wash" data-tone={r.wash.tone} style={{ color: r.wash.tone === 'warning' ? toneVars('warning').color : TOKENS.text[2], fontWeight: r.wash.tone === 'warning' ? 600 : 400 }}>{r.wash.tone === 'warning' ? '⚠ ' : 'ⓘ '}{r.wash.text}</div>}
              {r.earnings && <div style={{ color: toneVars('warning').color, fontWeight: 600 }}>⚠ {r.earnings}</div>}
              <div style={{ ...sub, marginTop: 0 }}>{r.lookThrough}</div>
            </div>
          )
        })}
      </div>
      <div style={sub}>Signal and status only — never a size or an order.{m.reentryMore && <> <Link to="/risk?tab=market-risk" data-testid="mr-reentry-more" style={tap}>{m.reentryMore} — Risk →</Link></>}</div>
    </div>
  )
}

function Positions({ m }: { m: ActionableModel }) {
  if (!m.positions.length) return null
  return (
    <div data-testid="mr-positions">
      <h3 style={h3}>Your positions in stressed groups · by $ exposed</h3>
      <div style={{ overflowX: 'auto' }}><table>
        <thead><tr><th>Symbol</th><th className="mr-hide-phone" style={{ textAlign: 'left' }}>Account</th><th>Value</th><th className="mr-hide-phone">% acct</th><th style={{ whiteSpace: 'normal' }}>Stressed <Explain term="stressed_pct" /></th><th style={{ whiteSpace: 'normal' }}>$ exposed <Explain term="usd_exposed" /></th><th>Stop</th><th className="mr-hide-phone">Stance</th></tr></thead>
        <tbody>
          {m.positions.map(p => (
            <tr key={`${p.symbol}-${p.account_label}`} data-testid="mr-position-row">
              <td><b>{p.symbol}</b><span className="mr-phone-only" style={{ fontSize: TYPE.sm, color: TOKENS.text[3] }}>{p.account_label}</span></td>
              <td className="mr-hide-phone" style={{ textAlign: 'left', color: TOKENS.text[2], whiteSpace: 'normal' }}>{p.account_label}</td>
              <td style={numStyle}>{fmtUsd(p.value_usd)}</td>
              <td className="mr-hide-phone" style={numStyle}>{p.pct_account != null ? `${p.pct_account.toFixed(1)}%` : '—'}</td>
              <td style={numStyle}>{Math.round(p.stressed_share * 100)}%</td>
              <td style={{ ...numStyle, fontWeight: 700 }}>{fmtUsd(p.usd_exposed)}</td>
              <td data-testid="mr-position-stop" style={{ color: !m.stopsKnown ? TOKENS.text[3] : p.stop_distance_pct == null ? toneVars('warning').color : TOKENS.text[1], fontWeight: m.stopsKnown && p.stop_distance_pct == null ? 600 : 400 }}>{!m.stopsKnown ? 'stops unavailable' : p.stop_distance_pct == null ? 'no stop' : `${p.stop_distance_pct.toFixed(1)}% below`}</td>
              <td className="mr-hide-phone" style={{ color: TOKENS.text[2], whiteSpace: 'normal' }}>{p.material ? (p.stance ?? 'hold') : 'residual'}</td>
            </tr>
          ))}
        </tbody>
      </table></div>
      {m.positionsMore && <div style={sub}>{m.positionsMore}</div>}
    </div>
  )
}

function Review({ m }: { m: ActionableModel }) {
  if (!m.review.length) return null
  return (
    <div data-testid="mr-review">
      <h3 style={h3}>Review now · ranked by $ at risk</h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {m.review.map((r, i) => (
          <div key={`${r.symbol}-${r.account_label}`} data-testid="mr-review-item" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '0 8px', minHeight: 44, padding: '0 12px', borderRadius: RADIUS.md, background: TOKENS.bg[0], border: `1px solid ${TOKENS.border}`, fontSize: TYPE.base + 1 }}>
            <span style={{ ...numStyle, color: TOKENS.text[3] }}>{i + 1}</span>
            <span style={{ flex: '1 1 200px', minWidth: 0, padding: '6px 0' }}><b>{r.symbol} · {r.account_label}</b> — {r.text}</span>
            <span style={numStyle}>{fmtUsd(r.usd)}</span>
            <Link to={r.to} data-testid="mr-review-link" style={tap}>Review →</Link>
          </div>
        ))}
      </div>
      <div style={sub}>Advisory only. Each link opens the existing stop review or the symbol's page. No order, size or stop level is implied.</div>
    </div>
  )
}

function Budgets({ m }: { m: ActionableModel }) {
  if (!m.budgets.length && m.budgetsNote) {
    return (
      <div data-testid="mr-budgets">
        <h3 style={h3}>Budget breaches <Explain term="budget_breach" /></h3>
        <div data-testid="mr-budgets-unavailable" style={{ ...item, color: toneVars('warning').color }}>{m.budgetsNote}</div>
      </div>
    )
  }
  if (!m.budgets.length) return null
  return (
    <div data-testid="mr-budgets">
      <h3 style={h3}>Budget breaches <Explain term="budget_breach" /></h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {m.budgets.map((b, i) => (
          <div key={i} data-testid="mr-budget-row" style={item}>
            <div><b>{b.account}</b> <span>{b.text}</span></div>
            {b.drivers && <div style={{ color: TOKENS.text[2] }}>drivers: {b.drivers}</div>}
          </div>
        ))}
      </div>
    </div>
  )
}

/** Sections 1–6; ``why`` is section 7 (the v004 contributor block), passed in by the card that owns it. design home/v006:
 *  "Review now" moved into Protect (MarketRiskActions); it renders here only when the API sent no Protect block. */
export function ActionableBody({ m, why }: { m: ActionableModel; why: React.ReactNode }) {
  return (
    <GlossaryProvider terms={m.glossary}>
      <div data-mr-actionable="" data-testid="mr-actionable-body" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 460px), 1fr))', gap: '16px 20px', alignItems: 'start', paddingTop: 8 }}>
        <style>{ACTIONABLE_CSS}</style>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, minWidth: 0 }}><Sectors m={m} /><Reentry m={m} /></div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, minWidth: 0 }}><Positions m={m} />{!m.protect && <Review m={m} />}<Budgets m={m} /><Segments m={m} />{why}</div>
      </div>
    </GlossaryProvider>
  )
}
