// PrivateProxyCard — public-market PROXY for a PRIVATE company that can't be bought directly.
// Use case: Anthropic IPO → Zoom (ZM) as proxy because Zoom Ventures holds an Anthropic stake.
//
// Renders /api/v2/proxy/targets: the research row (10 answers, scores, citations), the operator
// strategy scaffolding (regular + options, with speculative / caps-upside flags), the ranked
// option candidates from the scanner, and the human-facing card_copy (beginner summary / education /
// what-to-monitor).
//
// SAFETY (matches the backend invariants): ADVISORY / RESEARCH ONLY. Every proxy thesis is
// event-driven and UNVALIDATED until paper outcomes exist. No live order path; no candidate is
// live-eligible. View Chain is required before any paper or manual action. Alpaca paper only if the
// operator explicitly marks a candidate ready and confirms. Nothing here submits or promotes.
import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { WL, numStyle, sectionLabel } from '../lib/watchlistCardTokens'
import { fmt$, fmtNum } from '../lib/format'

const chip = (c: string, quiet = false): React.CSSProperties => ({
  fontSize: 9, fontWeight: 800, padding: '2px 7px', borderRadius: 4, whiteSpace: 'nowrap',
  letterSpacing: '.02em', color: c, background: quiet ? 'rgba(148,163,184,.08)' : `${c}18`,
  border: `1px solid ${quiet ? 'rgba(148,163,184,.2)' : `${c}44`}`,
})

// 0–100 score → signal color. High conviction = teal, mid = amber, low/unknown = dim.
const scoreColor = (n: number | null | undefined): string =>
  n == null ? WL.text.dim : n >= 60 ? WL.signal.teal : n >= 35 ? WL.signal.amber : WL.text.dim

const STRAT_LABEL: Record<string, string> = {
  deep_itm_call: 'Deep ITM call / LEAPS', call_debit_spread: 'Call debit spread', cash_secured_put: 'Cash-secured put',
}

function Score({ label, v }: { label: string; v: number | null | undefined }) {
  const c = scoreColor(v)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 88 }}>
      <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: '.07em', textTransform: 'uppercase', color: WL.text.dim }}>{label}</span>
      <span style={{ ...numStyle, fontSize: 15, fontWeight: 800, color: c }}>{v == null ? '--' : v}<span style={{ fontSize: 9, color: WL.text.dim, fontWeight: 600 }}> /100</span></span>
    </div>
  )
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, padding: '6px 10px', background: WL.surface.inset, borderRadius: 5, minWidth: 74 }}>
      <span style={{ fontSize: 8.5, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: WL.text.dim }}>{label}</span>
      <span style={{ ...numStyle, fontSize: 12.5, fontWeight: 700, color: tone || WL.text.primary }}>{value}</span>
    </div>
  )
}

// Compact, per-strategy metric set (the scanner stores different keys per structure).
function candidateMetrics(strategy: string, m: any): { label: string; value: string; tone?: string }[] {
  const pct = (v: any) => (v == null ? '--' : `${Number(v).toFixed(1)}%`)
  if (strategy === 'deep_itm_call') return [
    { label: 'Debit', value: fmt$(m.debit, 2) },
    { label: 'Delta', value: m.delta == null ? '--' : Number(m.delta).toFixed(2) },
    { label: 'Breakeven', value: fmt$(m.breakeven, 2) },
    { label: 'Cap.Eff', value: m.capital_efficiency == null ? '--' : Number(m.capital_efficiency).toFixed(2), tone: WL.signal.teal },
    { label: 'Leverage', value: m.leverage == null ? '--' : `${Number(m.leverage).toFixed(1)}x` },
    { label: 'OI', value: fmtNum(m.oi) },
    { label: 'Spread', value: pct(m.spread_pct) },
    { label: 'DTE', value: fmtNum(m.dte) },
  ]
  if (strategy === 'call_debit_spread') return [
    { label: 'Debit', value: fmt$(m.debit, 2) },
    { label: 'Max Gain', value: fmt$(m.max_gain, 2), tone: WL.price.up },
    { label: 'R:R', value: m.reward_risk == null ? '--' : `${Number(m.reward_risk).toFixed(2)}x`, tone: WL.signal.teal },
    { label: 'Breakeven', value: fmt$(m.breakeven, 2) },
    { label: 'Width', value: fmt$(m.width, 2) },
    { label: 'Min OI', value: fmtNum(m.min_leg_oi) },
    { label: 'Spread', value: pct(m.max_leg_spread_pct) },
    { label: 'DTE', value: fmtNum(m.dte) },
  ]
  // cash_secured_put
  return [
    { label: 'Premium', value: fmt$(m.premium, 2), tone: WL.price.up },
    { label: 'Discount', value: pct(m.strike_discount_pct), tone: WL.signal.teal },
    { label: 'Ann.Yield', value: pct(m.annualized_yield_pct) },
    { label: 'Assign Risk', value: m.assignment_risk == null ? '--' : Number(m.assignment_risk).toFixed(2) },
    { label: 'WTO', value: m.willingness_to_own_score == null ? '--' : Number(m.willingness_to_own_score).toFixed(0) },
    { label: 'Cash Sec.', value: fmt$(m.cash_secured, 0) },
    { label: 'OI', value: fmtNum(m.oi) },
    { label: 'DTE', value: fmtNum(m.dte) },
  ]
}

function legText(l: any): string {
  const side = String(l.side || '').toUpperCase()
  return `${l.action || ''} ${l.strike != null ? `$${l.strike}` : ''} ${side}${l.exp ? ` ${l.exp}` : ''}`.trim()
}

function OptionCandidate({ c }: { c: any }) {
  // View Chain gate — required before any paper or manual action (spec). Read-only leg/chain detail;
  // there is NO live order path from here.
  const [openChain, setOpenChain] = useState(false)
  const m = c.metrics || {}
  const legs: any[] = c.legs || []
  return (
    <div style={{ borderTop: `1px solid ${WL.surface.divider}`, padding: '10px 0' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <span style={{ ...numStyle, fontSize: 12, fontWeight: 800, color: WL.text.primary }}>
          {legs.map(l => l.strike).filter((x: any) => x != null).join(' / ') || '—'}
        </span>
        <span style={{ fontSize: 10, color: WL.text.muted }}>{legs.map(legText).join('  ·  ')}</span>
        <span style={{ ...chip(WL.signal.teal, true), marginLeft: 'auto' }} title="Composite rank score (higher = better fit for this structure)">
          rank {c.rank_score == null ? '--' : Number(c.rank_score).toFixed(0)}
        </span>
        {c.speculative && <span style={chip(WL.signal.red)} title="Speculative — small, explicitly-labeled bet only">SPECULATIVE</span>}
        {c.caps_upside && <span style={chip(WL.signal.amber)} title="Caps your upside at the short strike">CAPS UPSIDE</span>}
        <span style={chip(WL.text.dim, true)} title="Never live-eligible — review/paper only">REVIEW-ONLY</span>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
        {candidateMetrics(c.strategy, m).map(mm => <Metric key={mm.label} {...mm} />)}
      </div>
      <button
        onClick={() => setOpenChain(o => !o)}
        style={{ fontSize: 10, fontWeight: 700, padding: '5px 12px', borderRadius: 6, cursor: 'pointer',
          border: `1px solid ${WL.signal.teal}55`, background: 'transparent', color: WL.signal.teal }}
        title="Required before any paper or manual action — read-only chain detail; no live order path">
        {openChain ? '▾ Hide Chain' : '▸ View Chain (required before any action)'}
      </button>
      {openChain && (
        <div style={{ marginTop: 8, padding: '8px 12px', background: WL.surface.inset, borderRadius: 6, fontSize: 10.5, color: WL.text.secondary }}>
          <div style={{ ...sectionLabel, marginBottom: 6 }}>Chain detail (read-only)</div>
          {legs.map((l, i) => (
            <div key={i} style={{ ...numStyle, display: 'flex', gap: 14, padding: '2px 0', color: WL.text.primary }}>
              <span style={{ minWidth: 150 }}>{legText(l)}</span>
              <span>bid {l.bid ?? '--'}</span><span>ask {l.ask ?? '--'}</span>
              <span>mid {l.mid ?? '--'}</span><span>Δ {l.delta ?? '--'}</span>
              <span>IV {l.iv ?? '--'}</span><span>OI {l.oi ?? '--'}</span>
            </div>
          ))}
          <div style={{ marginTop: 8, fontSize: 9.5, color: WL.text.dim }}>
            No live order path. Alpaca paper is available only if you explicitly mark this candidate ready and confirm — this thesis is event-driven and UNVALIDATED until paper outcomes exist.
          </div>
        </div>
      )}
    </div>
  )
}

// Generic proxy-investing education — same for every target. Target-specific education comes from
// card_copy.education below it.
const GENERIC_EDU: { title: string; body: string }[] = [
  { title: 'Proxy trades are indirect', body: 'You are buying a public stock whose value is only PARTLY tied to the private company. The link is real but loose — the proxy trades mostly on its own business.' },
  { title: 'Give the thesis time', body: 'IPO catalysts are uncertain and can be distant. Options lose time value (theta) every day, so short-dated bets can expire worthless even if you are right on direction. Prefer long expiries / LEAPS.' },
  { title: 'Short-dated OTM calls are speculative', body: 'They need a big move SOON — timing you do not control. Keep them small and explicitly labeled, never the core position.' },
  { title: 'Covered calls cap the upside', body: 'Writing calls against the proxy caps exactly the IPO upside you are trying to capture. Only after a catalyst spike, and only if you accept the cap.' },
]

function TargetCard({ t }: { t: any }) {
  const sc = t.strategy_candidates || {}
  const regular: any[] = sc.regular || []
  const options: any[] = sc.options || []
  const byStrat: Record<string, any[]> = t.option_candidates_by_strategy || {}
  const cc = t.card_copy || {}
  const flags = (t.option_candidates?.[0]?.flags) || {}
  const earnings = flags.earnings_before_expiry
  const citations: any[] = t.citations || []
  const rail = WL.text.dim // neutral: this is a MONITOR/advisory surface, not an urgent action

  return (
    <div style={{ background: WL.surface.card, border: `1px solid ${WL.surface.edge}`, borderLeft: `3px solid ${rail}`,
      borderRadius: WL.card.radius, boxShadow: WL.card.shadow, overflow: 'hidden', color: WL.text.primary, marginBottom: 16 }}>

      {/* Header — private target → public proxy */}
      <div style={{ padding: `12px ${WL.row.padX}px`, display: 'flex', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <span style={{ fontSize: 16, fontWeight: 800 }}>{t.private_target_name}</span>
            <span style={{ fontSize: 12, color: WL.text.dim }}>private → proxy</span>
            <span style={{ ...numStyle, fontSize: 16, fontWeight: 800, color: WL.signal.teal }}>{t.proxy_ticker}</span>
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <span style={chip(WL.text.secondary, true)}>{String(t.proxy_type || '').replace(/_/g, ' ')}</span>
            <span style={chip(WL.text.muted, true)}>IPO: {String(t.ipo_status || 'unknown').replace(/_/g, ' ')}</span>
            {t.expected_ipo_window && t.expected_ipo_window !== 'unknown' && <span style={chip(WL.signal.amber, true)}>window {t.expected_ipo_window}</span>}
            {t.latest_valuation && <span style={chip(WL.text.muted, true)}>val {fmt$(t.latest_valuation, 0)}</span>}
          </div>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <span style={chip(WL.signal.amber)} title="Moves on a discrete headline event; direction and timing uncertain">EVENT-DRIVEN</span>
          <span style={chip(WL.signal.red)} title="No paper outcomes yet — do not size as a validated edge">UNVALIDATED</span>
          <span style={chip(WL.text.dim, true)} title="Research/advisory only — no live order path">ADVISORY ONLY</span>
        </div>
      </div>

      {/* Beginner summary — the one tinted banner */}
      {cc.beginner_summary && (
        <div style={{ margin: `0 ${WL.row.padX}px 12px`, padding: '10px 14px', background: 'rgba(148,163,184,.06)',
          border: '1px solid rgba(148,163,184,.16)', borderRadius: 8, fontSize: 12.5, lineHeight: 1.5, color: WL.text.secondary }}>
          {cc.beginner_summary}
        </div>
      )}

      {/* Scores */}
      <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', padding: `4px ${WL.row.padX}px 12px` }}>
        <Score label="Materiality" v={t.materiality_score} />
        <Score label="Catalyst" v={t.catalyst_score} />
        <Score label="Disclosure" v={t.valuation_disclosure_quality} />
        <Score label="Confidence" v={t.source_confidence} />
        {t.model_used && <div style={{ marginLeft: 'auto', alignSelf: 'flex-end', fontSize: 9.5, color: WL.text.dim }}>research: {t.model_used}</div>}
      </div>

      {/* Why + research notes */}
      {(t.why || t.research_notes) && (
        <div style={{ padding: `0 ${WL.row.padX}px 12px` }}>
          {t.why && <div style={{ fontSize: 12, lineHeight: 1.5, color: WL.text.secondary, marginBottom: t.research_notes ? 6 : 0 }}>{t.why}</div>}
          {t.research_notes && <div style={{ fontSize: 11, lineHeight: 1.5, color: WL.text.muted, fontStyle: 'italic' }}>{t.research_notes}</div>}
        </div>
      )}

      {/* Event / earnings flags */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', padding: `0 ${WL.row.padX}px 12px` }}>
        <span style={chip(WL.signal.amber)} title={flags.ipo_headline_risk?.note}>⚑ IPO headline risk — moves ZM in EITHER direction</span>
        {earnings && <span style={chip(WL.signal.amber)}>⚑ Earnings {earnings.date} (in {earnings.days}d)</span>}
      </div>

      {/* Regular-stock candidates */}
      {regular.length > 0 && (
        <div style={{ padding: `10px ${WL.row.padX}px`, borderTop: `1px solid ${WL.surface.divider}` }}>
          <div style={sectionLabel}>Regular-stock strategy candidates</div>
          {regular.map((r, i) => (
            <div key={i} style={{ padding: '5px 0', fontSize: 11.5 }}>
              <span style={{ fontWeight: 700, color: WL.text.primary }}>{r.label}</span>
              {r.note && <span style={{ color: WL.text.muted }}> — {r.note}</span>}
            </div>
          ))}
        </div>
      )}

      {/* Options candidates: operator scaffolding + scanned rows per structure */}
      {options.length > 0 && (
        <div style={{ padding: `10px ${WL.row.padX}px`, borderTop: `1px solid ${WL.surface.divider}` }}>
          <div style={sectionLabel}>Options strategy candidates</div>
          {options.map((o, i) => (
            <div key={i} style={{ padding: '5px 0', fontSize: 11.5 }}>
              <span style={{ fontWeight: 700, color: WL.text.primary }}>{o.label}</span>
              {o.speculative && <span style={{ ...chip(WL.signal.red), marginLeft: 6 }}>SPECULATIVE</span>}
              {o.caps_upside && <span style={{ ...chip(WL.signal.amber), marginLeft: 6 }}>CAPS UPSIDE</span>}
              {o.note && <div style={{ color: WL.text.muted, marginTop: 2 }}>{o.note}</div>}
            </div>
          ))}

          {/* Scanned candidates from the live chain, grouped by structure */}
          {Object.keys(byStrat).length > 0 ? (
            <div style={{ marginTop: 10 }}>
              {['deep_itm_call', 'call_debit_spread', 'cash_secured_put'].filter(s => byStrat[s]?.length).map(s => (
                <div key={s} style={{ marginTop: 8 }}>
                  <div style={{ fontSize: 10.5, fontWeight: 800, letterSpacing: '.05em', color: WL.text.secondary, marginBottom: 2 }}>
                    {STRAT_LABEL[s] || s} <span style={{ color: WL.text.dim, fontWeight: 600 }}>· {byStrat[s].length} ranked · underlying {fmt$(byStrat[s][0]?.underlying_price, 2)}</span>
                  </div>
                  {byStrat[s].map((c, i) => <OptionCandidate key={i} c={c} />)}
                </div>
              ))}
            </div>
          ) : (
            <div style={{ marginTop: 8, fontSize: 10.5, color: WL.text.dim, fontStyle: 'italic' }}>
              No scanned option candidates yet — the scanner needs a live chain (market hours + linked broker). Ranked deep-ITM / debit-spread / CSP rows appear here after the next scan.
            </div>
          )}
        </div>
      )}

      {/* Education */}
      <div style={{ padding: `10px ${WL.row.padX}px`, borderTop: `1px solid ${WL.surface.divider}` }}>
        <div style={sectionLabel}>How proxy investing works</div>
        {[...GENERIC_EDU, ...((cc.education as any[]) || [])].map((e, i) => (
          <div key={i} style={{ padding: '5px 0', fontSize: 11.5, lineHeight: 1.5 }}>
            <span style={{ fontWeight: 700, color: WL.text.primary }}>{e.title}. </span>
            <span style={{ color: WL.text.secondary }}>{e.body}</span>
          </div>
        ))}
      </div>

      {/* What to monitor */}
      {(cc.what_to_monitor as any[])?.length > 0 && (
        <div style={{ padding: `10px ${WL.row.padX}px`, borderTop: `1px solid ${WL.surface.divider}` }}>
          <div style={sectionLabel}>What to monitor</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {(cc.what_to_monitor as string[]).map((w, i) => (
              <span key={i} style={{ ...chip(WL.text.secondary, true), fontWeight: 600 }}>{w}</span>
            ))}
          </div>
        </div>
      )}

      {/* Citations */}
      {citations.length > 0 && (
        <div style={{ padding: `10px ${WL.row.padX}px`, borderTop: `1px solid ${WL.surface.divider}` }}>
          <div style={sectionLabel}>Sources ({citations.length})</div>
          {citations.map((c, i) => (
            <div key={i} style={{ padding: '3px 0', fontSize: 10.5, color: WL.text.muted }}>
              <span style={{ color: WL.text.secondary }}>{c.claim}</span>
              {c.source && <span> — {c.source}</span>}
              {c.url && <a href={c.url} target="_blank" rel="noreferrer" style={{ color: WL.signal.teal, marginLeft: 6 }}>link</a>}
              {c.as_of && <span style={{ color: WL.text.dim }}> ({c.as_of})</span>}
            </div>
          ))}
        </div>
      )}

      {/* Safety footer */}
      <div style={{ padding: `10px ${WL.row.padX}px`, borderTop: `1px solid ${WL.surface.divider}`, background: 'rgba(2,6,23,.25)',
        fontSize: 10, lineHeight: 1.5, color: WL.text.dim }}>
        Advisory / research only. No auto-promotion, no live submit — no candidate is live-eligible. View Chain is required before any paper or manual action.
        Alpaca paper only if you explicitly mark a candidate ready and confirm. This proxy thesis is event-driven and UNVALIDATED until paper outcomes exist.
        No Schwab / Fidelity / OCO / 2FA behavior is touched by this surface.
      </div>
    </div>
  )
}

export default function PrivateProxyCard() {
  const { data, loading, error } = useApi<any>('/api/v2/proxy/targets', 120_000)
  const targets: any[] = data?.targets || []
  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 13, fontWeight: 800, color: WL.text.primary }}>Private-Company Proxy Research</div>
        <span style={chip(WL.text.dim, true)}>public-market proxies for companies you can't buy directly</span>
      </div>
      {loading && targets.length === 0 && <div style={{ color: WL.text.muted, fontSize: 12 }}>Loading proxy research…</div>}
      {error && <div style={{ color: WL.signal.red, fontSize: 12 }}>Failed to load proxy research: {error}</div>}
      {!loading && targets.length === 0 && !error && (
        <div style={{ color: WL.text.muted, fontSize: 12 }}>No proxy targets yet. Seed one in config/private_company_proxies.yaml, then run the research + scan.</div>
      )}
      {targets.map((t, i) => <TargetCard key={t.slug || i} t={t} />)}
    </div>
  )
}
