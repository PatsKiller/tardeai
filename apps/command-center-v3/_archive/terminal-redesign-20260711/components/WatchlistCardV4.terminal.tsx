import { useState, type CSSProperties } from 'react'
import type { DrillContext } from './DetailDrawer'
import ProAnalystPill from './ProAnalystPill'
import { exitLadder, planWarnings, MONITOR_RULES, type Ladder } from '../lib/exitLadder'
import {
  deriveRecommendedAction,
  ladderStepTooltip,
  watchlistNeedsRefresh,
  cioRecColor,
  targetVsStreetLabel,
  dataQualityFlags,
  actionReasoning,
  deriveSecondaryActions,
  rrTooltip,
  type CardActionType,
} from '../lib/watchlistCardAction'
import CountryFlag from './CountryFlag'
import { LadderLine } from './primitives/cardPrimitives'
import { type RiskPct } from '../lib/watchlistProposeSizing'
import { EvidenceBlock } from './EvidenceBlock'
import FibConfluencePanel from './FibConfluencePanel'
import HoldingReportLinks from './HoldingReportLinks'
import SizingTable from './SizingTable'
import { EnsembleValidationInline } from './EnsembleValidationCard'
import CloudLlmRunButtons from './CloudLlmRunButtons'
import type { WatchlistCardProps } from './WatchlistCard'
import { marketAwareStale, composeWhy, sameHeadline, catalystAgeDays } from '../lib/watchlistCardV4'
import {
  resolvePlanVolContext,
  stopVolatilityLine,
  volatilityBadgeText,
  volatilityBadgeTooltip,
} from '../lib/watchlistVolatility'
import {
  BB,
  numStyle,
  terminalVerdictBg,
  terminalVerdictColor,
  terminalRail,
  terminalSigned,
  terminalRrColor,
  terminalButton,
  verdictWord,
} from '../lib/watchlistTerminalTokens'

// Security Card v4 — Bloomberg Terminal dense panel (2026-07).
// Single-surface, hairline dividers, amber primary actions, numbers-first scannability.
// All data + expanders preserved; secondary detail lives in compact drawers.

function ago(v: any) {
  if (!v) return ''
  const t = new Date(v).getTime()
  if (!Number.isFinite(t)) return ''
  const h = Math.round((Date.now() - t) / 36e5)
  if (h < 1) return 'now'
  if (h < 48) return `${h}h`
  return `${Math.round(h / 24)}d`
}

function money(v: any) {
  const n = Number(v)
  return Number.isFinite(n) ? `$${n.toFixed(2)}` : '—'
}

function pct(from: number | null, to: number | null): string | null {
  if (from == null || to == null || !from) return null
  const p = ((to - from) / from) * 100
  return `${p >= 0 ? '+' : ''}${p.toFixed(1)}%`
}

function fmtPc(v: any): string {
  if (v == null) return '—'
  const n = Number(v)
  return `${n > 0 ? '+' : ''}${n.toFixed(1)}%`
}

function truncate(text: string, max: number): string {
  const t = text.trim()
  if (t.length <= max) return t
  return `${t.slice(0, max - 1).trimEnd()}…`
}

function cleanNewsSource(raw?: string): string {
  if (!raw) return 'news'
  return String(raw)
    .replace(/^(google_news|yahoo_rss|finviz_news|hermes):\s*/i, '')
    .replace(/^hermes\s*·\s*/i, '')
    .trim() || 'news'
}

function ladderFocusIndex(ladder: Ladder | null): number {
  if (!ladder?.steps.length) return -1
  return ladder.steps.length > 1 ? 1 : 0
}

const micro: CSSProperties = { fontSize: 8, fontWeight: 700, letterSpacing: '.07em', textTransform: 'uppercase', color: BB.text3 }
const hair = `1px solid ${BB.border}`

export default function WatchlistCardV4({
  it, adv, sc, pa, outcome, llms, fv, reportEntry, paMap, accounts, heldPositions, maxDeployPctOfCash,
  ensOpen, refreshState, onDrill, onToggleStar, onRefresh, onToggleEns, isStarred,
  onPropose, onAdjust, onBuildPlan, onOpenDesk, onCioDone,
}: WatchlistCardProps) {
  const enriched = !!it.last_enriched_at
  const stale = enriched && marketAwareStale(it.last_enriched_at)
  const needsRefresh = watchlistNeedsRefresh(it, stale)
  const street = pa?.target != null && Number(pa.target) > 0 ? Number(pa.target) : null
  const entry = it.entry_limit != null ? Number(it.entry_limit) : null
  const stop = it.entry_stop != null ? Number(it.entry_stop) : null
  const planTarget = it.entry_target != null ? Number(it.entry_target) : null
  const rr = it.entry_rr != null ? Number(it.entry_rr)
    : (entry && stop && planTarget && entry > stop && planTarget > entry ? (planTarget - entry) / (entry - stop) : null)
  const hasPlan = entry != null && stop != null
  const volCtx = resolvePlanVolContext(it, fv, entry, stop)
  const ladder = entry != null || stop != null ? exitLadder(entry, stop, planTarget, street) : null
  const warns = entry != null || stop != null
    ? planWarnings({
      entry, stop, planTarget, rr, pctCash: null, streetTarget: street,
      analystUpside: pa?.upside != null ? Number(pa.upside) : null,
      stopAtrMult14: volCtx.stopAtrMult14, stopAtrMult20: volCtx.stopAtrMult20,
      atrPct14: volCtx.atrPct14, atrPct20: volCtx.atrPct20,
    })
    : []
  const stopVolLine = stopVolatilityLine(volCtx)
  const dataDoubt = (it.synthesis_data_i_doubt && it.synthesis_data_i_doubt !== 'none')
    ? String(it.synthesis_data_i_doubt).trim() : ''
  const action = deriveRecommendedAction({
    it, hasPlan, rr, warns, stale, enriched, entry, adv, pa, dataDoubt, needsRefresh,
  })
  const rail = terminalRail(action.verdict, action.urgency)
  const verdictColor = terminalVerdictColor(action.verdict, action.urgency)
  const verdictBg = terminalVerdictBg(action.verdict, action.urgency)
  const focusIdx = ladderFocusIndex(ladder)
  const cioRec = it.latest_recommendation ? String(it.latest_recommendation).replace(/_/g, ' ') : null
  const cioLabel = cioRec ?? (pa?.rec ? String(pa.rec).replace(/_/g, ' ') : 'watch')
  const cioAccent = cioRecColor(it.latest_recommendation || cioLabel)
  const confNum = it.research_confidence != null
    ? Number(it.research_confidence)
    : (it.hermes_score_components?._confidence != null ? Number(it.hermes_score_components._confidence) : null)

  const [drawerOpen, setDrawerOpen] = useState(false)
  const [ladderOpen, setLadderOpen] = useState(false)
  const [evidenceOpen, setEvidenceOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)

  const drillCtx: DrillContext = {
    title: `${it.symbol}${it.hermes_rank != null ? ` — Hermes #${it.hermes_rank}` : ''}`,
    subtitle: `${it.origin_system ?? it.source ?? ''} · ${it.status}`,
    endpoint: `/api/v2/hermes/intel/${it.symbol}`,
    rows: [adv ? { ...it, setup_advisory_note: adv.note, setup_advisory_flag: adv.advisory_flag, current_rsi: adv.rsi, rsi_band: adv.band } : it],
  }

  const sectorShort = sc?.sector || it.profile_sector || null
  const isHeld = it.in_portfolio || outcome?.held
  const analystDivergent = pa?.divergence === 'divergent'
  const allNews: any[] = sc?.news ?? []
  const newsPool = allNews.filter((n, i) => i > 0 || !sameHeadline(n?.title, it.catalyst_headline))
  const topNews = newsPool[0] ?? null
  const moreNews = newsPool.slice(1, 4)
  const exitVsStreet = targetVsStreetLabel(planTarget, street)
  const secondaryActions = deriveSecondaryActions(action, hasPlan)
  const reasoning = actionReasoning({ it, pa, adv, action, hasPlan, rr, stale, enriched })
  const cioSnip = it.synthesis_narrative_snip ? String(it.synthesis_narrative_snip) : ''
  const reasonForHero = reasoning && cioSnip && reasoning.trim().slice(0, 60) === cioSnip.trim().slice(0, 60) ? null : reasoning
  const whyLine = composeWhy([action.heroText, reasonForHero].map(s => s ? truncate(String(s), 120) : s))
  const catAgeD = catalystAgeDays(it.catalyst_at)
  const catalystStale = catAgeD != null && catAgeD > 7 && !!it.catalyst_headline
  const dqFlags = [
    ...dataQualityFlags({ it, stale, enriched, needsRefresh, dataDoubt, adv }),
    ...(catalystStale ? [{ label: `cat ${catAgeD}d`, severity: 'amber' as const }] : []),
  ]
  const visibleDqFlags = action.warning?.text?.startsWith('Data doubt')
    ? dqFlags.filter(f => !f.label.startsWith('Data doubt'))
    : dqFlags
  const worstDq = visibleDqFlags.find(f => f.severity === 'red') ?? visibleDqFlags[0]
  const dqColor = worstDq ? (worstDq.severity === 'red' ? BB.red : BB.amber) : BB.green
  const hasEvidence = !!(it.synthesis_evidence?.length || action.detail || adv?.note)
  const cioNote = it.synthesis_narrative_snip ? truncate(String(it.synthesis_narrative_snip), 140) : null

  const executeAction = (e: React.MouseEvent, type: CardActionType) => {
    e.stopPropagation()
    setMenuOpen(false)
    switch (type) {
      case 'REFRESH_DATA': onRefresh(e); break
      case 'VIEW_INTEL':
      case 'REVIEW_SETUP': onDrill(drillCtx); break
      case 'PROPOSE_ENTRY': onPropose?.(it); break
      case 'ADJUST_PLAN':
      case 'REVIEW_EXIT': onAdjust?.(it); break
      case 'BUILD_PLAN': onBuildPlan?.(it.symbol); break
      case 'WATCH_ON_DESK':
      case 'QUEUE_PROPOSAL': onOpenDesk?.(it.symbol); break
      case 'REC_INTEL': window.location.href = `/v3/rec-intel?symbol=${encodeURIComponent(it.symbol)}`; break
      case 'ENSEMBLE': onToggleEns(); break
      default: break
    }
  }

  const handlePrimary = (e: React.MouseEvent) => {
    if (!action.allowPrimary) return
    executeAction(e, action.type)
  }

  const inlineSecondary = secondaryActions[0] ?? null
  const menuItems: { type: CardActionType; label: string }[] = []
  const addMenuItem = (type: CardActionType, label: string) => {
    if (type === action.type) return
    if (inlineSecondary && type === inlineSecondary.type) return
    if (!menuItems.some(m => m.type === type)) menuItems.push({ type, label })
  }
  for (const sec of secondaryActions.slice(1)) addMenuItem(sec.type, sec.label)
  addMenuItem('VIEW_INTEL', 'Intel drawer')
  addMenuItem('REC_INTEL', 'Rec-Intel')
  addMenuItem('ENSEMBLE', ensOpen ? 'Hide ensemble' : 'Ensemble')
  if (hasPlan) addMenuItem('WATCH_ON_DESK', 'Monitor on desk')
  if (ladder) addMenuItem('REVIEW_EXIT', 'Exit ladder')

  const showHeaderRefresh = action.type !== 'REFRESH_DATA'
  const canPropose = action.type === 'PROPOSE_ENTRY'
  const volTag = volatilityBadgeText(volCtx)
  const planWarn = warns[0]?.text ?? (exitVsStreet ? exitVsStreet : null)
  const link = (href: string, label: string) => (
    <a href={href} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} className="wlc4-link" style={{ color: BB.text2 }}>{label}</a>
  )

  const contextBullets: { key: string; node: React.ReactNode }[] = []
  if (cioNote) {
    contextBullets.push({
      key: 'cio',
      node: <><span style={{ color: BB.amber, fontWeight: 800 }}>CIO</span> {cioNote}</>,
    })
  }
  if (it.catalyst_headline) {
    contextBullets.push({
      key: 'cat',
      node: (
        <>
          <span style={{ color: BB.text3, fontWeight: 800 }}>CAT</span>{' '}
          {it.catalyst_url ? link(it.catalyst_url, truncate(String(it.catalyst_headline), 72)) : truncate(String(it.catalyst_headline), 72)}
          {it.catalyst_at && <span style={{ color: catalystStale ? BB.amber : BB.text3 }}> · {ago(it.catalyst_at)}</span>}
        </>
      ),
    })
  }
  if (topNews) {
    contextBullets.push({
      key: 'news',
      node: (
        <>
          <span style={{ color: BB.text3, fontWeight: 800 }}>NEWS</span>{' '}
          {topNews.url ? link(topNews.url, truncate(String(topNews.title), 72)) : truncate(String(topNews.title), 72)}
        </>
      ),
    })
  }
  if (fv) {
    contextBullets.push({
      key: 'tech',
      node: (
        <>
          <span style={{ color: BB.text3, fontWeight: 800 }}>TECH</span>{' '}
          <span style={numStyle}>RSI {fv.rsi == null ? '—' : Math.round(Number(fv.rsi))}</span>
          {' · '}<span style={{ color: terminalSigned(Number(fv.perf_week) || 0) }}>1W {fmtPc(fv.perf_week)}</span>
          {' · '}<span style={{ color: terminalSigned(Number(fv.perf_month) || 0) }}>1M {fmtPc(fv.perf_month)}</span>
          {volTag && <span style={{ color: BB.amber }}> · {volTag}</span>}
        </>
      ),
    })
  }

  return (
    <div
      onClick={() => onDrill(drillCtx)}
      style={{
        background: BB.bg,
        border: hair,
        borderLeft: `3px solid ${rail}`,
        borderRadius: 2,
        cursor: 'pointer',
        minWidth: 0,
        width: '100%',
        boxSizing: 'border-box',
        overflow: 'hidden',
        color: BB.text1,
        fontSize: 10,
        lineHeight: 1.35,
      }}
    >
      {/* ① Ultra-compact header */}
      <div
        style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 10px', borderBottom: hair, flexWrap: 'nowrap' }}
        onClick={e => e.stopPropagation()}
      >
        <button
          onClick={e => { e.stopPropagation(); onToggleStar(e) }}
          title={isStarred ? 'Unstar' : 'Star'}
          style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, padding: 0, color: isStarred ? BB.amber : BB.text3, flexShrink: 0 }}
        >{isStarred ? '★' : '☆'}</button>
        <span style={{ ...numStyle, fontWeight: 800, fontSize: 18, color: BB.text0, flexShrink: 0 }}>{it.symbol}</span>
        <CountryFlag symbol={it.symbol} country={it.country} countryName={it.country_name} size={16} />
        {sectorShort && (
          <span style={{ fontSize: 9, color: BB.text3, textTransform: 'uppercase', letterSpacing: '.05em', flexShrink: 0 }}>{sectorShort}</span>
        )}
        {isHeld && (
          <span className="wlc-term-tag" style={{ color: BB.amber, border: `1px solid ${BB.amber}55`, background: BB.amberDim }}>HELD</span>
        )}
        <span onClick={e => e.stopPropagation()} style={{ flexShrink: 0 }}><ProAnalystPill symbol={it.symbol} map={paMap} compact neutral={false} /></span>
        {analystDivergent && <span className="wlc-term-tag" style={{ color: BB.amber, border: `1px solid ${BB.amber}44` }}>CIO≠ST</span>}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'baseline', gap: 8, flexShrink: 0 }}>
          <span style={{ ...numStyle, fontSize: 16, fontWeight: 800, color: BB.text0 }}>{it.price != null ? money(it.price) : '—'}</span>
          {it.change_pct != null && (
            <span style={{ ...numStyle, fontSize: 12, fontWeight: 800, color: terminalSigned(Number(it.change_pct)) }}>
              {Number(it.change_pct) >= 0 ? '+' : ''}{Number(it.change_pct).toFixed(2)}%
            </span>
          )}
          {volTag && (
            <span
              className="wlc-term-tag"
              title={volatilityBadgeTooltip(volCtx)}
              style={{ color: volCtx.band === 'extreme' ? BB.red : BB.amber, border: `1px solid ${volCtx.band === 'extreme' ? BB.red : BB.amber}44`, cursor: 'help' }}
            >{volTag}</span>
          )}
          {showHeaderRefresh && (
            <button
              onClick={e => { e.stopPropagation(); onRefresh(e) }}
              disabled={!!refreshState}
              title="Refresh Finviz + re-queue synthesis"
              className="wlc-term-icon"
              style={{ width: 22, height: 20, fontSize: 10 }}
            >{refreshState ? '…' : '↻'}</button>
          )}
        </div>
      </div>

      {/* ② Recommendation + status strip */}
      <div
        onClick={e => e.stopPropagation()}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '5px 10px',
          borderBottom: hair,
          background: verdictBg,
          flexWrap: 'wrap',
        }}
      >
        <span
          style={{
            ...numStyle,
            fontSize: 11,
            fontWeight: 900,
            letterSpacing: '.12em',
            color: verdictColor,
            flexShrink: 0,
          }}
        >{verdictWord(action.verdict)}</span>
        <span style={{ flex: 1, minWidth: 120, fontSize: 10.5, fontWeight: 600, color: BB.text0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={whyLine || action.heroText}>
          {whyLine || action.heroText}
        </span>
        <span style={{ ...numStyle, fontSize: 9, fontWeight: 800, color: cioAccent, textTransform: 'uppercase', flexShrink: 0 }} title={`CIO view: ${cioLabel}`}>
          {cioLabel}
        </span>
        {it.models_agree === true && <span style={{ fontSize: 8, color: BB.green, fontWeight: 800, flexShrink: 0 }}>AGREE</span>}
        {it.models_agree === false && <span style={{ fontSize: 8, color: BB.amber, fontWeight: 800, flexShrink: 0 }}>SPLIT</span>}
        {confNum != null && (
          <span style={{ ...numStyle, fontSize: 8, color: BB.text3, flexShrink: 0 }} title="Research confidence">{confNum.toFixed(2)}</span>
        )}
        {stale && (
          <span className="wlc-term-tag" style={{ color: BB.amber, border: `1px solid ${BB.amber}55`, background: BB.amberDim }} title="Data older than 1h during market hours">STALE</span>
        )}
        <span
          title={visibleDqFlags.map(f => f.label).join(' · ') || 'Data healthy'}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 4, flexShrink: 0, fontSize: 8, color: BB.text3 }}
        >
          <span style={{ width: 5, height: 5, borderRadius: 1, background: dqColor, display: 'inline-block' }} />
          {worstDq ? worstDq.label : `ok ${ago(it.last_enriched_at)}`}
        </span>
        {rr != null && hasPlan && (
          <span title={rrTooltip(entry, stop, planTarget, rr)} style={{ ...numStyle, fontSize: 11, fontWeight: 800, color: terminalRrColor(rr), flexShrink: 0 }}>
            {rr.toFixed(1)}R
          </span>
        )}
        {action.warning && (
          <span style={{ fontSize: 8, color: action.warning.severity === 'red' ? BB.red : BB.amber, fontWeight: 700, flexShrink: 0 }} title={action.warning.text}>
            ⚠ {truncate(action.warning.text, 48)}
          </span>
        )}
      </div>

      {/* ③ Trade plan ⟷ Sizing */}
      <div className="wlc-term-grid" onClick={e => e.stopPropagation()}>
        <div className="wlc-term-cell">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
            <span style={micro}>Plan</span>
            {ladder && (
              <button onClick={e => { e.stopPropagation(); setLadderOpen(v => !v) }} style={{ ...terminalButton('ghost'), fontSize: 8, padding: 0 }}>
                ladder {ladderOpen ? '▴' : '▾'}
              </button>
            )}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 4 }}>
            {([
              ['LMT', money(it.entry_limit), hasPlan && it.entry_zone_low != null ? `z ${money(it.entry_zone_low)}` : null],
              ['STP', money(it.entry_stop), stopVolLine ? truncate(stopVolLine, 22) : null],
              ['TGT', money(it.entry_target), entry != null && planTarget != null ? pct(entry, planTarget) : null],
              ['R:R', rr != null ? rr.toFixed(1) : '—', ladder ? `$${ladder.R.toFixed(2)}/sh` : null],
            ] as const).map(([lbl, val, sub]) => (
              <div key={lbl}>
                <div style={micro}>{lbl}</div>
                <div style={{
                  ...numStyle,
                  fontSize: 13,
                  fontWeight: 800,
                  color: lbl === 'STP' && hasPlan && stop == null ? BB.red
                    : lbl === 'R:R' && rr != null ? terminalRrColor(rr)
                      : BB.text0,
                }}>{val}</div>
                {sub && <div style={{ fontSize: 8, color: lbl === 'STP' && volCtx.tightVsAtr ? BB.amber : BB.text3, marginTop: 1 }}>{sub}</div>}
              </div>
            ))}
          </div>
          {planWarn && (
            <div style={{ fontSize: 8, color: BB.amber, marginTop: 4, fontWeight: 600 }} title={planWarn}>⚠ {truncate(planWarn, 90)}</div>
          )}
          {ladder && !ladderOpen && (
            <div style={{ marginTop: 4 }}>
              <LadderLine steps={ladder.steps} focusIdx={focusIdx} stepTooltip={ladderStepTooltip} />
            </div>
          )}
        </div>
        <div className="wlc-term-cell">
          <SizingTable
            variant="terminal"
            accounts={accounts}
            heldPositions={heldPositions}
            entry={entry}
            stop={stop}
            target={planTarget}
            canPropose={canPropose}
            maxDeployPctOfCash={maxDeployPctOfCash}
            onSize={(accountKey, riskPct) => onPropose?.(it, { account_key: accountKey, risk_pct: riskPct as RiskPct })}
          />
        </div>
      </div>

      {ladderOpen && ladder && (
        <div onClick={e => e.stopPropagation()} style={{ padding: '6px 10px', borderTop: hair, background: BB.bgShift }}>
          {ladder.steps.map((s, i) => (
            <div key={i} style={{ display: 'flex', gap: 8, fontSize: 9, color: BB.text2 }}>
              <b style={{ ...numStyle, color: BB.text3, width: 96, flexShrink: 0 }}>{s.label}</b>
              <span>{s.px.toFixed(2)} — {s.action}</span>
            </div>
          ))}
          <div style={{ display: 'flex', gap: 8, fontSize: 9, color: BB.text2, marginTop: 2 }}>
            <b style={{ ...numStyle, color: BB.text3, width: 96, flexShrink: 0 }}>Rules</b>
            <span>{MONITOR_RULES}</span>
          </div>
        </div>
      )}

      {/* ④ Minimal context strip */}
      {contextBullets.length > 0 && (
        <div onClick={e => e.stopPropagation()} style={{ padding: '5px 10px', borderTop: hair, display: 'flex', flexDirection: 'column', gap: 2 }}>
          {contextBullets.slice(0, 4).map(b => (
            <div key={b.key} style={{ fontSize: 9.5, color: BB.text2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={typeof b.node === 'string' ? b.node : undefined}>
              {b.node}
            </div>
          ))}
        </div>
      )}

      {/* ⑤ Action row */}
      <div
        onClick={e => e.stopPropagation()}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '5px 10px',
          borderTop: hair,
          background: BB.bgPanel,
          flexWrap: 'wrap',
        }}
      >
        {action.allowPrimary && (
          <button onClick={handlePrimary} style={terminalButton(action.buttonVariant === 'outline-red' ? 'danger' : 'primary')}>
            {action.primaryLabel}
          </button>
        )}
        {inlineSecondary && (
          <button onClick={e => executeAction(e, inlineSecondary.type)} style={terminalButton('secondary')}>{inlineSecondary.label}</button>
        )}
        <button onClick={e => { e.stopPropagation(); setDrawerOpen(v => !v) }} style={terminalButton('ghost')}>More {drawerOpen ? '▴' : '▾'}</button>
        <div style={{ position: 'relative', marginLeft: 2 }}>
          <button onClick={e => { e.stopPropagation(); setMenuOpen(v => !v) }} style={terminalButton('ghost')} aria-label="More actions">⋯</button>
          {menuOpen && (
            <div style={{
              position: 'absolute', bottom: '110%', left: 0, zIndex: 30, minWidth: 150,
              background: BB.bgPanel, border: hair, borderRadius: 2, padding: 2,
              boxShadow: '0 8px 20px rgba(0,0,0,.55)',
            }}>
              {menuItems.map(m => (
                <button
                  key={m.type}
                  onClick={e => executeAction(e, m.type)}
                  style={{ display: 'block', width: '100%', textAlign: 'left', fontSize: 9, fontWeight: 700, color: BB.text2, background: 'none', border: 'none', cursor: 'pointer', padding: '5px 8px' }}
                >{m.label}</button>
              ))}
            </div>
          )}
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 4 }} onClick={e => e.stopPropagation()}>
          <CloudLlmRunButtons processId="watchlist_cio_synthesis" lanePolicy="ensemble" symbol={it.symbol} compact onDone={() => onCioDone?.()} />
          <HoldingReportLinks symbol={it.symbol} entry={reportEntry} reportType={reportEntry?.report_type || 'symbol_watchlist'} compact />
          {hasEvidence && (
            <button onClick={e => { e.stopPropagation(); setEvidenceOpen(v => !v) }} className="wlc-term-icon" title="CIO evidence">E</button>
          )}
          <button onClick={e => { e.stopPropagation(); onToggleEns() }} className="wlc-term-icon" title={ensOpen ? 'Hide ensemble' : 'Ensemble check'}>⊕</button>
        </div>
      </div>

      {/* Expandable drawer — secondary intelligence + diligence */}
      {drawerOpen && (
        <div onClick={e => e.stopPropagation()} style={{ padding: '6px 10px', borderTop: hair, background: BB.bgShift, display: 'flex', flexDirection: 'column', gap: 4, fontSize: 9.5, color: BB.text2 }}>
          {visibleDqFlags.length > 1 && (
            <div><span style={{ color: BB.text3, fontWeight: 800 }}>DATA </span>{visibleDqFlags.map(f => f.label).join(' · ')}</div>
          )}
          {action.detail && <div><span style={{ color: BB.text3, fontWeight: 800 }}>ADV </span>{action.detail}</div>}
          {adv?.note && adv.note !== action.detail && <div><span style={{ color: BB.text3, fontWeight: 800 }}>SETUP </span>{adv.note}</div>}
          {moreNews.map((n, i) => (
            <div key={i}>
              <span style={{ color: BB.text3, fontWeight: 800 }}>NEWS </span>
              {n.url ? link(n.url, String(n.title)) : n.title}
            </div>
          ))}
          {(sc?.description || it.profile_description) && (
            <div><span style={{ color: BB.text3, fontWeight: 800 }}>CO </span>{truncate(String(sc?.description || it.profile_description), 200)}</div>
          )}
          {llms.length > 0 && (
            <div><span style={{ color: BB.text3, fontWeight: 800 }}>INTEL </span>{llms.map((e: any) => e.lane).join(' · ')}</div>
          )}
          <div>
            <span style={{ color: BB.text3, fontWeight: 800 }}>DD </span>
            {reportEntry?.generated_at
              ? `prospectus ${ago(reportEntry.generated_at)}${reportEntry.oversight_verdict ? ` · ${reportEntry.oversight_verdict}` : ''}`
              : 'no prospectus — generate via icons'}
          </div>
          <FibConfluencePanel symbol={it.symbol} />
        </div>
      )}

      {evidenceOpen && hasEvidence && (
        <div onClick={e => e.stopPropagation()} style={{ padding: '6px 10px', borderTop: hair }}>
          {it.synthesis_evidence?.length > 0 && (
            <EvidenceBlock title="CIO evidence" evidence={it.synthesis_evidence} compact maxItems={3} />
          )}
          {action.detail && <div style={{ fontSize: 9, color: BB.text3, marginTop: 4 }}>{action.detail}</div>}
          {adv?.note && adv.note !== action.detail && <div style={{ fontSize: 9, color: BB.text3, marginTop: 4 }}>{adv.note}</div>}
        </div>
      )}

      {ensOpen && (
        <div onClick={e => e.stopPropagation()} style={{ padding: '6px 10px', borderTop: hair }}>
          <EnsembleValidationInline
            targetType="signal"
            targetId={it.id}
            subject={it.symbol}
            content={`${it.symbol} watchlist — ${it.latest_recommendation || it.trend || ''} · ${it.profile_sector || ''}`}
          />
        </div>
      )}
    </div>
  )
}