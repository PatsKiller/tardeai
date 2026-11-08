/** Design home/v005: the actionable parts of the Home market-risk card — the verdict with dollars, the top review item,
 *  and the sections (sectors with your dollars, since you were stopped out, positions in stressed groups, review now,
 *  budget breaches). Shared by the YELLOW summary card and the ORANGE/RED banner. Tokens only. Every "Review →" opens an
 *  existing page; there is no order, size or stop control anywhere (MBI_BEHAVIOR = 0). */
import type { CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { RADIUS, TOKENS, TYPE, chipStyle, numStyle, toneVars } from '../../lib/designTokens'
import { SUMMARY_PHONE_MAX_PX, fmtUsd, type ActionableModel } from '../../lib/marketRisk'
import { EXPLAIN_CSS, Explain, GlossaryProvider, Segments } from './MarketRiskActions'
import HomeV007Context from './HomeV007Context'

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
}
/* v007: native collapsible sections; the one-line summary is hidden while open (mockup behaviour). */
[data-mr-actionable] details.mr-sec{background:${TOKENS.bg[1]};border:1px solid ${TOKENS.border};border-radius:${RADIUS.md};padding:0;min-width:0}
[data-mr-actionable] details.mr-sec>summary{list-style:none;cursor:pointer;min-height:44px;padding:10px 12px;display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px;font-weight:700;font-size:${TYPE.base}px;color:${TOKENS.text[2]};text-transform:uppercase;letter-spacing:.05em}
[data-mr-actionable] details.mr-sec>summary::-webkit-details-marker{display:none}
[data-mr-actionable] details.mr-sec>summary::after{content:"▾";margin-left:auto;color:${TOKENS.text[3]};transition:transform .15s}
[data-mr-actionable] details.mr-sec[open]>summary{border-bottom:1px solid ${TOKENS.borderSubtle}}
[data-mr-actionable] details.mr-sec[open]>summary::after{transform:rotate(180deg)}
[data-mr-actionable] .mr-sec-one{font-size:${TYPE.sm}px;font-weight:400;text-transform:none;letter-spacing:0;color:${TOKENS.text[3]}}
[data-mr-actionable] details.mr-sec[open] .mr-sec-one{display:none}
[data-mr-actionable] .mr-sec-body{padding:10px 12px;min-width:0}
@media(max-width:600px){
 /* v007 phone proof: tables become stacked rows with their column label, no horizontal page scroll. */
 [data-mr-actionable] .mr-stack{display:block;width:100%}
 [data-mr-actionable] .mr-stack thead{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}
 [data-mr-actionable] .mr-stack tbody,[data-mr-actionable] .mr-stack tr,[data-mr-actionable] .mr-stack td{display:block;width:100%}
 [data-mr-actionable] .mr-stack tr{padding:8px 0;border-bottom:1px solid ${TOKENS.borderSubtle}}
 [data-mr-actionable] .mr-stack td{border:0;padding:2px 0;text-align:left;white-space:normal;display:flex;justify-content:space-between;gap:10px}
 [data-mr-actionable] .mr-stack td::before{content:attr(data-l);color:${TOKENS.text[3]};font-size:${TYPE.sm}px}
 [data-mr-actionable] .mr-stack td:first-child::before{content:none}
 [data-mr-actionable] .mr-stack td[data-l=""]::before{content:none}
 [data-mr-actionable] .mr-stack td.mr-hide-phone{display:none}
}
@media(prefers-reduced-motion:reduce){[data-mr-actionable] details.mr-sec>summary::after{transition:none}}`

const sub: CSSProperties = { fontSize: TYPE.sm, color: TOKENS.text[3], marginTop: 4, lineHeight: 1.5 }
const item: CSSProperties = { display: 'flex', flexDirection: 'column', gap: 3, padding: '9px 12px', borderRadius: RADIUS.md, background: TOKENS.bg[0], border: `1px solid ${TOKENS.border}`, fontSize: TYPE.base + 1, lineHeight: 1.45 }
const tap: CSSProperties = { minHeight: 44, display: 'inline-flex', alignItems: 'center', color: TOKENS.info, fontWeight: 700, textDecoration: 'none', whiteSpace: 'nowrap' }
const signed = (n: number | null): CSSProperties => ({ ...numStyle, color: n == null ? TOKENS.text[3] : n < 0 ? toneVars('danger').color : toneVars('success').color })

/** v007: one native collapsible per section. Nothing is removed; every section keeps its own text and clock,
 *  and the summary shows a one-line digest that disappears once the section is open (mockup behaviour). */
function Section({ title, one, testId, children, defaultOpen = true }: { title: string; one?: string | null; testId: string; children: React.ReactNode; defaultOpen?: boolean }) {
  return (
    <details className="mr-sec" data-testid={testId} open={defaultOpen}>
      <summary><span role="heading" aria-level={3}>{title}</span>{one ? <span className="mr-sec-one">{one}</span> : null}</summary>
      <div className="mr-sec-body">{children}</div>
    </details>
  )
}

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
    // LIVEFIX-R (operator 2026-11-06): the sector table is reference, not the headline — collapsed by default; its
    // one-line digest stays visible and every row is one tap away.
    <Section title="Sectors vs SPY · your money in each" one={m.sectorsFoot} testId="mr-sectors-section" defaultOpen={false}>
    <div data-testid="mr-sectors">
      <div style={{ ...sub, marginTop: 0, marginBottom: 6 }}>look-through <Explain term="look_through" /></div>
      <table className="mr-stack">
        <thead><tr><th>Group</th><th><span className="mr-hide-phone">1d vs SPY</span><span className="mr-phone-inline">1d</span></th><th><span className="mr-hide-phone">5d vs SPY</span><span className="mr-phone-inline">5d</span></th><th>You</th><th className="mr-hide-phone">% book <Explain term="pct_book" /></th></tr></thead>
        <tbody>
          {m.sectors.map(r => {
            const t = toneVars(r.tone)
            const bg = r.chip === 'STRESS' || r.chip === 'WEAK' ? t.bg : r.unknown && r.held ? toneVars('warning').bg : undefined
            return (
              <tr key={r.key} data-testid="mr-sector-row" data-key={r.key} data-chip={r.chip} style={{ background: bg }}>
                <td data-l="Group"><span data-testid="mr-sector-chip" style={{ ...chipStyle(r.tone, 'soft'), marginRight: 2 }}>{r.chip}</span><Explain term={CHIP_TERM[r.chip]} /> {r.label}{r.theme && <span style={{ color: TOKENS.text[3] }}> (theme)</span>}</td>
                {r.unknown
                  // operator 2026-11-06: the reason is on the row (a title= tooltip never shows on a phone) + a tappable (i)
                  ? <td colSpan={2} data-testid="mr-sector-why" style={{ textAlign: 'left', color: toneVars('warning').color, fontWeight: 600, whiteSpace: 'normal', overflowWrap: 'anywhere' }}>No SPY comparison: {r.why}<Explain term="sector_unmeasured" detail={r.reason ? `Engine reason: ${r.reason}` : null} />{r.held && <span className="mr-hide-phone"> — you hold {r.usd}</span>}</td>
                  : <><td data-l="1d vs SPY" style={signed(r.rs1n)}>{r.rs1}</td><td data-l="5d vs SPY" style={signed(r.rs5n)}>{r.rs5}</td></>}
                <td data-l="You" style={numStyle}>{r.usd}</td>
                <td data-l="% book" className="mr-hide-phone" style={numStyle}>{r.pctBook}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {m.foldLine && <div data-testid="mr-sectors-folded" style={{ fontSize: TYPE.base, color: TOKENS.text[2], padding: '6px 6px 0' }}>{m.foldLine}{m.foldHasUnknown && <> <Explain term="sector_unmeasured" /></>}</div>}
      <div style={sub}>{m.sectorsFoot}</div>
    </div>
    </Section>
  )
}

function Reentry({ m }: { m: ActionableModel }) {
  if (!m.reentry.length && !m.reentryMore) return null
  return (
    <Section title="Since you were stopped out" one={m.reentryMore || `${m.reentry.length} watched exit${m.reentry.length === 1 ? '' : 's'}`} testId="mr-reentry-section">
    <div data-testid="mr-reentry">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {m.reentry.map(r => {
          const vt = toneVars(r.verdictTone)
          return (
            <div key={r.symbol} data-testid="mr-reentry-row" data-verdict={r.verdict} data-verdict-shown={r.verdictShown} style={item}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '2px 10px', alignItems: 'baseline' }}><b>{r.symbol}</b><span style={{ color: TOKENS.text[2] }}>{r.head}</span></div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '2px 10px', alignItems: 'center' }}>
                <span>now <b style={numStyle}>{r.now}</b> ({r.vsExitKnown
                  ? <><span style={signed(r.vsExitNeg ? -1 : 1)}>{r.vsExit}</span> vs exit</>
                  : <span data-testid="mr-reentry-vsexit-unknown" style={{ color: TOKENS.text[3] }}>vs exit needs a current price <Explain term="vs_exit_no_price" detail={r.priceWhy ? `This row: ${r.priceWhy}.` : null} /></span>}){r.vsMa && <> · <span style={numStyle}>{r.vsMa}</span></>} {r.trend}</span>
                <span><span data-testid="mr-reentry-verdict" style={{ ...chipStyle(r.verdictTone, 'soft'), color: vt.color }}>{r.verdictShown.toUpperCase()}</span>{r.stagesPending && <Explain term="reentry_check_timing" />}</span>
              </div>
              {r.verdictNote && <div data-testid="mr-reentry-verdict-note" style={{ ...sub, marginTop: 0, color: TOKENS.text[2] }}>{r.verdictNote}</div>}
              <div><b>Stage 1 <Explain term="stage1" /> (early setup): {r.stage1}</b><span style={{ color: TOKENS.text[2] }}> — waiting: {r.waiting}</span></div>
              <div>Invalidates below <Explain term="invalidates_below" /> <b style={numStyle}>{r.invalidates}</b><span style={{ color: TOKENS.text[2] }}> (selloff low) · Stage 2 <Explain term="stage2" /> (confirmed): {r.stage2}</span></div>
              {r.wash && <div data-testid="mr-reentry-wash" data-tone={r.wash.tone} style={{ color: r.wash.tone === 'warning' ? toneVars('warning').color : TOKENS.text[2], fontWeight: r.wash.tone === 'warning' ? 600 : 400 }}>{r.wash.tone === 'warning' ? '⚠ ' : 'ⓘ '}{r.wash.text}</div>}
              {r.earnings && <div style={{ color: toneVars('warning').color, fontWeight: 600 }}>⚠ {r.earnings}</div>}
              <div style={{ ...sub, marginTop: 0, overflowWrap: 'anywhere' }}>{r.lookThrough}{r.lookThroughMissing && <> <Explain term="look_through_missing" /></>}</div>
            </div>
          )
        })}
      </div>
      <div style={sub}>Signal and status only — never a size or an order.{m.reentryMore && <> <Link to="/risk?tab=market-risk" data-testid="mr-reentry-more" style={tap}>{m.reentryMore} — Risk →</Link></>}</div>
    </div>
    </Section>
  )
}

function Positions({ m }: { m: ActionableModel }) {
  if (!m.positions.length) return null
  return (
    <Section title="Your positions in stressed groups · by $ exposed" one={m.positionsMore || `${m.positions.length} position${m.positions.length === 1 ? '' : 's'}`} testId="mr-positions-section">
    <div data-testid="mr-positions">
      <div style={{ overflowX: 'auto' }}><table className="mr-stack">
        <thead><tr><th>Symbol</th><th className="mr-hide-phone" style={{ textAlign: 'left' }}>Account</th><th>Value</th><th className="mr-hide-phone">% acct</th><th style={{ whiteSpace: 'normal' }}>Stressed <Explain term="stressed_pct" /></th><th style={{ whiteSpace: 'normal' }}>$ exposed <Explain term="usd_exposed" /></th><th>Stop</th><th className="mr-hide-phone">Stance</th></tr></thead>
        <tbody>
          {m.positions.map(p => (
            <tr key={`${p.symbol}-${p.account_label}`} data-testid="mr-position-row">
              <td data-l="Symbol"><b>{p.symbol}</b><span className="mr-phone-only" style={{ fontSize: TYPE.sm, color: TOKENS.text[3] }}>{p.account_label}</span></td>
              <td data-l="Account" className="mr-hide-phone" style={{ textAlign: 'left', color: TOKENS.text[2], whiteSpace: 'normal' }}>{p.account_label}</td>
              <td data-l="Value" style={numStyle}>{fmtUsd(p.value_usd)}</td>
              <td data-l="% acct" className="mr-hide-phone" style={numStyle}>{p.pct_account != null ? `${p.pct_account.toFixed(1)}%` : '—'}</td>
              <td data-l="Stressed" style={numStyle}>{Math.round(p.stressed_share * 100)}%</td>
              <td data-l="$ exposed" style={{ ...numStyle, fontWeight: 700 }}>{fmtUsd(p.usd_exposed)}</td>
              <td data-l="Stop" data-testid="mr-position-stop" style={{ color: !m.stopsKnown ? TOKENS.text[3] : p.stop_distance_pct == null ? toneVars('warning').color : TOKENS.text[1], fontWeight: m.stopsKnown && p.stop_distance_pct == null ? 600 : 400 }}>{!m.stopsKnown ? 'stops unavailable' : p.stop_distance_pct == null ? 'no stop' : `${p.stop_distance_pct.toFixed(1)}% below`}</td>
              <td data-l="Stance" className="mr-hide-phone" style={{ color: TOKENS.text[2], whiteSpace: 'normal' }}>{p.material ? (p.stance ?? 'hold') : 'residual'}</td>
            </tr>
          ))}
        </tbody>
      </table></div>
      {m.positionsMore && <div style={sub}>{m.positionsMore}</div>}
    </div>
    </Section>
  )
}

function Review({ m }: { m: ActionableModel }) {
  if (!m.review.length) return null
  return (
    <Section title="Review now · ranked by $ at risk" one={`${m.review.length} item${m.review.length === 1 ? '' : 's'}`} testId="mr-review-section">
    <div data-testid="mr-review">
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
    </Section>
  )
}

/** LQ-20261107-1239: "since the close" — the news on held names and the futures/overseas levels the join read.
 *  Additive: absent when the API sent neither block. Stacked rows (no table): nothing scrolls sideways at 412 px. */
function SinceClose({ m }: { m: ActionableModel }) {
  const s = m.sinceClose
  if (!s) return null
  if (!s.news.length && !s.markets.length && !s.marketsNote && !s.newsMore) return null
  const count = s.news.length + s.markets.length
  return (
    <Section title="Since the close" one={s.window || `${count} item${count === 1 ? '' : 's'}`} testId="mr-since-close-section">
    <div data-testid="mr-since-close">
      <div style={{ ...sub, marginTop: 0, marginBottom: 6 }}>{s.window}</div>
      {s.news.length > 0 && (
        <div data-testid="mr-since-close-news" style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 8 }}>
          {s.news.map(n => (
            <Link key={n.symbol} to={n.to} data-testid="mr-since-close-news-row" data-tone={n.tone}
              style={{ ...item, flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: '2px 8px', minHeight: 44, color: TOKENS.text[0], textDecoration: 'none' }}>
              <b style={{ flex: '0 0 auto' }}>{n.symbol}</b>
              <span style={{ flex: '1 1 160px', minWidth: 0, color: toneVars(n.tone).color, fontWeight: n.tone === 'danger' ? 700 : 600 }}>{n.text}</span>
              <span style={{ color: TOKENS.info, fontWeight: 700 }}>Open →</span>
            </Link>
          ))}
        </div>
      )}
      {s.newsMore && <div data-testid="mr-since-close-news-gap" style={{ ...sub, marginTop: 0, color: toneVars('warning').color }}>{s.newsMore}</div>}
      {s.markets.length > 0 && (
        <table className="mr-stack" data-testid="mr-since-close-markets">
          <thead><tr><th>Market</th><th>Last</th><th>Change</th></tr></thead>
          <tbody>
            {s.markets.map(x => (
              <tr key={x.symbol} data-testid="mr-since-close-market-row" data-level-only={x.level_only ? '1' : '0'}>
                <td data-l="Market"><b>{x.label}</b><span className="mr-phone-only" style={{ fontSize: TYPE.sm, color: TOKENS.text[3] }}>{x.note}</span></td>
                <td data-l="Last" style={numStyle}>{x.value}</td>
                <td data-l="Change" style={{ ...numStyle, color: toneVars(x.tone).color }}>{x.change}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {s.markets.length > 0 && s.markets.some(x => x.note) && (
        <div data-testid="mr-since-close-market-note" className="mr-hide-phone" style={sub}>{s.markets.map(x => `${x.label}: ${x.note}`).join(' · ')}</div>
      )}
      {s.marketsNote && <div data-testid="mr-since-close-markets-gap" style={{ ...sub, marginTop: 0, color: toneVars('warning').color }}>{s.marketsNote}</div>}
      <div style={sub}>{s.foot}</div>
    </div>
    </Section>
  )
}

function Budgets({ m }: { m: ActionableModel }) {  if (!m.budgets.length && m.budgetsNote) {
    return (
      <Section title="Budget breaches" one={m.budgetsNote} testId="mr-budgets-section">
      <div data-testid="mr-budgets">
        <div style={{ ...sub, marginTop: 0, marginBottom: 6 }}><Explain term="budget_breach" /></div>
        <div data-testid="mr-budgets-unavailable" style={{ ...item, color: toneVars('warning').color }}>{m.budgetsNote}</div>
      </div>
      </Section>
    )
  }
  if (!m.budgets.length) return null
  return (
    <Section title="Budget breaches" one={`${m.budgets.length} breach${m.budgets.length === 1 ? '' : 'es'}`} testId="mr-budgets-section">
    <div data-testid="mr-budgets">
      <div style={{ ...sub, marginTop: 0, marginBottom: 6 }}><Explain term="budget_breach" /></div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {m.budgets.map((b, i) => (
          <div key={i} data-testid="mr-budget-row" style={item}>
            <div><b>{b.account}</b> <span>{b.text}</span></div>
            {b.drivers && <div style={{ color: TOKENS.text[2] }}>drivers: {b.drivers}</div>}
          </div>
        ))}
      </div>
    </div>
    </Section>
  )
}

const BODY_LAYOUT_CSS = `
.mr-body{display:flex;flex-direction:column;gap:16px}
.mr-body>.mr-col{display:contents}
.mr-body .mr-names{order:1;min-width:0}
.mr-body .mr-stressed{order:2;min-width:0}
.mr-body>.mr-col>*{min-width:0}
@container (min-width: 940px){
 .mr-body{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px 20px;align-items:start}
 .mr-body>.mr-col{display:flex;flex-direction:column;gap:16px;min-width:0}
 .mr-body .mr-names,.mr-body .mr-stressed{order:0}
}`

/** Sections 1–6; ``why`` is section 7 (the v004 contributor block), passed in by the card that owns it. design home/v006:
 *  "Review now" moved into Protect (MarketRiskActions); it renders here only when the API sent no Protect block. */
export function ActionableBody({ m, why }: { m: ActionableModel; why: React.ReactNode }) {
  return (
    <GlossaryProvider terms={m.glossary}>
      {/* LQ-1240a: a container query, not a viewport one, so the two-column layout follows the width the body really has.
          Narrow: the column wrappers vanish (display:contents) and CSS order keeps the phone order of before: holdings,
          why, reentry, stopped-out names, stressed groups. Wide: two flex columns; the stopped-out block moves under
          Multi-segment issuer on the left so both columns end together instead of leaving a dead panel.
          Fold-3f union (LQ-20261107-1239): the served line's container-query layout and the part-scoped
          HomeV007Context wrappers win; the incoming commit's SinceClose block joins the context column, beside
          Reentry — it is "what happened", not "what you hold". Its bare <HomeV007Context /> is not taken: the served
          line renders both parts explicitly. */}
      <div className="mr-body-wrap" style={{ containerType: 'inline-size' }}>
        <div data-mr-actionable="" data-testid="mr-actionable-body" className="mr-body" style={{ paddingTop: 8 }}>
          <style>{ACTIONABLE_CSS}</style>
          <style>{BODY_LAYOUT_CSS}</style>
          <div data-testid="mr-col-holdings" className="mr-col">
            <Positions m={m} />{!m.protect && <Review m={m} />}<Budgets m={m} /><Sectors m={m} />
            {/* This wrapper holds MarketRiskActions' Segments — the multi-segment ISSUER block. Protect, Hedge and
                Rotate are NOT in here: ActionsTop renders them above the body (MarketRiskSummary / MarketRiskBanner).
                The Section title is the only "Multi-segment issuer" heading (Segments renders none of its own). */}
            {m.segments.length > 0 && (
              <Section title="Multi-segment issuer" one={`${m.segments.length} segment${m.segments.length === 1 ? '' : 's'}`} testId="mr-advisory-section"><Segments m={m} /></Section>
            )}
            <div data-testid="mr-row-names" className="mr-names"><HomeV007Context part="stopped" /></div>
          </div>
          <div data-testid="mr-col-context" className="mr-col">
            {why ? <Section title="Why this tier" one={m.verdict} testId="mr-why-section">{why}</Section> : null}
            <SinceClose m={m} />
            <Reentry m={m} />
            <div data-testid="mr-row-stressed" className="mr-stressed"><HomeV007Context part="rest" /></div>
          </div>
        </div>
      </div>
    </GlossaryProvider>
  )
}
