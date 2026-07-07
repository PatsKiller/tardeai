// PrivateProxyCard — the FULL public-proxy GRAPH for a PRIVATE company you can't buy directly.
// Use case: Anthropic IPO. The operator named ONE proxy (ZM); Hermes discovers the whole graph —
// direct/strategic/CVC investors, cloud/chip suppliers, customers, comparables, ETFs — scores and
// RANKS them, and buckets them into decision cards (best direct / best materiality / best options /
// best lower-risk equity / too-diluted-watch / rejected).
//
// Renders /api/v2/proxy/targets. SAFETY: ADVISORY / RESEARCH ONLY. Every thesis is event-driven and
// UNVALIDATED until paper outcomes exist. No live order path; no candidate is live-eligible. View Chain
// is required before any paper or manual action. Every accepted proxy carries source citations; rejected
// ones carry a reason. Unknown stake values are shown as unknown — never fabricated.
import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { WL, numStyle, sectionLabel } from '../lib/watchlistCardTokens'
import { fmt$, fmtNum } from '../lib/format'

const chip = (c: string, quiet = false): React.CSSProperties => ({
  fontSize: 9, fontWeight: 800, padding: '2px 7px', borderRadius: 4, whiteSpace: 'nowrap',
  letterSpacing: '.02em', color: c, background: quiet ? 'rgba(148,163,184,.08)' : `${c}18`,
  border: `1px solid ${quiet ? 'rgba(148,163,184,.2)' : `${c}44`}`,
})
const scoreColor = (n: number | null | undefined): string =>
  n == null ? WL.text.dim : n >= 60 ? WL.signal.teal : n >= 35 ? WL.signal.amber : WL.text.dim

function fmtCap(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`
  if (n >= 1e6) return `$${(n / 1e6).toFixed(0)}M`
  return fmt$(n, 0)
}

const TYPE_LABEL: Record<string, string> = {
  direct_equity_stake: 'Direct equity', convertible_note: 'Convertible', preferred_stock: 'Preferred',
  corporate_venture_investor: 'CVC investor', strategic_partner: 'Strategic partner',
  cloud_provider: 'Cloud provider', chip_supplier: 'Chip supplier', customer: 'Customer',
  public_comparable: 'Comparable', ETF: 'ETF',
}
const DIRECT_TYPES = new Set(['direct_equity_stake', 'convertible_note', 'preferred_stock', 'corporate_venture_investor'])
const STRAT_LABEL: Record<string, string> = {
  deep_itm_call: 'Deep ITM call / LEAPS', call_debit_spread: 'Call debit spread', cash_secured_put: 'Cash-secured put',
}
const PICK_LABELS: [string, string, string][] = [
  ['best_direct', 'Best direct exposure', WL.signal.teal],
  ['best_materiality', 'Highest materiality', WL.signal.teal],
  ['best_options', 'Best options proxy', WL.signal.teal],
  ['best_lower_risk_equity', 'Lower-risk equity', WL.text.secondary],
  ['too_diluted_but_watch', 'Too diluted — watch', WL.signal.amber],
]

function Metric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, padding: '6px 10px', background: WL.surface.inset, borderRadius: 5, minWidth: 72 }}>
      <span style={{ fontSize: 8.5, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: WL.text.dim }}>{label}</span>
      <span style={{ ...numStyle, fontSize: 12.5, fontWeight: 700, color: tone || WL.text.primary }}>{value}</span>
    </div>
  )
}

function candidateMetrics(strategy: string, m: any): { label: string; value: string; tone?: string }[] {
  const pct = (v: any) => (v == null ? '—' : `${Number(v).toFixed(1)}%`)
  if (strategy === 'deep_itm_call') return [
    { label: 'Debit', value: fmt$(m.debit, 2) }, { label: 'Delta', value: m.delta == null ? '—' : Number(m.delta).toFixed(2) },
    { label: 'Breakeven', value: fmt$(m.breakeven, 2) }, { label: 'Cap.Eff', value: m.capital_efficiency == null ? '—' : Number(m.capital_efficiency).toFixed(2), tone: WL.signal.teal },
    { label: 'Leverage', value: m.leverage == null ? '—' : `${Number(m.leverage).toFixed(1)}x` }, { label: 'DTE', value: fmtNum(m.dte) },
  ]
  if (strategy === 'call_debit_spread') return [
    { label: 'Debit', value: fmt$(m.debit, 2) }, { label: 'Max Gain', value: fmt$(m.max_gain, 2), tone: WL.price.up },
    { label: 'R:R', value: m.reward_risk == null ? '—' : `${Number(m.reward_risk).toFixed(2)}x`, tone: WL.signal.teal },
    { label: 'Breakeven', value: fmt$(m.breakeven, 2) }, { label: 'DTE', value: fmtNum(m.dte) },
  ]
  return [
    { label: 'Premium', value: fmt$(m.premium, 2), tone: WL.price.up }, { label: 'Discount', value: pct(m.strike_discount_pct), tone: WL.signal.teal },
    { label: 'Ann.Yield', value: pct(m.annualized_yield_pct) }, { label: 'WTO', value: m.willingness_to_own_score == null ? '—' : Number(m.willingness_to_own_score).toFixed(0) },
    { label: 'DTE', value: fmtNum(m.dte) },
  ]
}
const legText = (l: any) => `${l.action || ''} ${l.strike != null ? `$${l.strike}` : ''} ${String(l.side || '').toUpperCase()}${l.exp ? ` ${l.exp}` : ''}`.trim()

function OptionCandidate({ c }: { c: any }) {
  const [openChain, setOpenChain] = useState(false)
  const legs: any[] = c.legs || []
  return (
    <div style={{ borderTop: `1px solid ${WL.surface.divider}`, padding: '8px 0' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
        <span style={{ ...numStyle, fontSize: 11.5, fontWeight: 800 }}>{legs.map(l => l.strike).filter((x: any) => x != null).join(' / ') || '—'}</span>
        <span style={{ fontSize: 9.5, color: WL.text.muted }}>{legs.map(legText).join('  ·  ')}</span>
        <span style={{ ...chip(WL.signal.teal, true), marginLeft: 'auto' }}>rank {c.rank_score == null ? '—' : Number(c.rank_score).toFixed(0)}</span>
        {c.caps_upside && <span style={chip(WL.signal.amber)}>CAPS UPSIDE</span>}
        <span style={chip(WL.text.dim, true)}>REVIEW-ONLY</span>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginBottom: 6 }}>
        {candidateMetrics(c.strategy, c.metrics || {}).map(mm => <Metric key={mm.label} {...mm} />)}
      </div>
      <button onClick={() => setOpenChain(o => !o)} style={{ fontSize: 9.5, fontWeight: 700, padding: '4px 11px', borderRadius: 6, cursor: 'pointer', border: `1px solid ${WL.signal.teal}55`, background: 'transparent', color: WL.signal.teal }}
        title="Required before any paper or manual action — read-only chain detail; no live order path">
        {openChain ? '▾ Hide Chain' : '▸ View Chain (required before any action)'}
      </button>
      {openChain && (
        <div style={{ marginTop: 6, padding: '8px 12px', background: WL.surface.inset, borderRadius: 6, fontSize: 10, color: WL.text.secondary }}>
          {legs.map((l, i) => (
            <div key={i} style={{ ...numStyle, display: 'flex', gap: 14, padding: '2px 0', color: WL.text.primary }}>
              <span style={{ minWidth: 140 }}>{legText(l)}</span>
              <span>bid {l.bid ?? '—'}</span><span>ask {l.ask ?? '—'}</span><span>mid {l.mid ?? '—'}</span><span>Δ {l.delta ?? '—'}</span><span>OI {l.oi ?? '—'}</span>
            </div>
          ))}
          <div style={{ marginTop: 6, fontSize: 9, color: WL.text.dim }}>No live order path. Alpaca paper only if you explicitly mark this ready and confirm — event-driven and UNVALIDATED until paper outcomes exist.</div>
        </div>
      )}
    </div>
  )
}

function ProxyRow({ p, rank }: { p: any; rank: string }) {
  const [open, setOpen] = useState(false)
  const plan = p.ticker_plan || {}
  const cites: any[] = p.citations || []
  const byStrat: Record<string, any[]> = p.option_candidates_by_strategy || {}
  const typeC = DIRECT_TYPES.has(p.proxy_type) ? WL.signal.teal : p.proxy_type === 'strategic_partner' ? WL.text.secondary : WL.text.dim
  return (
    <div style={{ borderTop: `1px solid ${WL.surface.divider}` }}>
      <div onClick={() => setOpen(o => !o)} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 4px', cursor: 'pointer', flexWrap: 'wrap' }}>
        <span style={{ ...numStyle, fontSize: 11, fontWeight: 800, color: WL.text.dim, minWidth: 22 }}>{rank}</span>
        <span style={{ ...numStyle, fontSize: 13, fontWeight: 800, color: WL.text.primary, minWidth: 52 }}>{p.proxy_ticker}</span>
        <span style={{ ...chip(typeC, true) }}>{TYPE_LABEL[p.proxy_type] || p.proxy_type}</span>
        {p.discovered === false && <span style={chip(WL.text.dim, true)} title="Operator-seeded and confirmed by discovery">seeded</span>}
        {p.confirmed === false && <span style={chip(WL.signal.amber, true)} title="Relationship not confirmed by current sources">unconfirmed</span>}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <Metric label="Materiality" value={p.materiality_score ?? '—'} tone={scoreColor(p.materiality_score)} />
          <Metric label="Confidence" value={p.source_confidence ?? '—'} tone={scoreColor(p.source_confidence)} />
          <Metric label="Dilution" value={p.dilution_score ?? '—'} tone={(p.dilution_score ?? 0) >= 70 ? WL.signal.amber : WL.text.primary} />
          <Metric label="Mkt Cap" value={fmtCap(p.market_cap)} />
          <Metric label="Stake %" value={p.stake_to_mktcap_pct == null ? (p.stake_known ? '—' : 'unknown') : `${Number(p.stake_to_mktcap_pct).toFixed(2)}%`} />
          <Metric label="Options" value={p.has_options == null ? '?' : p.has_options ? (p.leaps_available ? 'LEAPS' : 'yes') : 'no'} tone={p.has_options ? WL.signal.teal : WL.text.dim} />
          <Metric label="Rank Score" value={p.rank_score == null ? '—' : Number(p.rank_score).toFixed(0)} tone={WL.signal.teal} />
          <span style={{ color: WL.text.dim, fontSize: 12 }}>{open ? '▾' : '▸'}</span>
        </div>
      </div>
      {open && (
        <div style={{ padding: '4px 4px 12px 30px' }}>
          {p.evidence_summary && <div style={{ fontSize: 11.5, lineHeight: 1.5, color: WL.text.secondary, marginBottom: 8 }}>{p.evidence_summary}</div>}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 10, marginBottom: 8 }}>
            <div><div style={sectionLabel}>Regular-stock plan</div><div style={{ fontSize: 11, color: WL.text.secondary }}>{plan.regular_plan || '—'}</div></div>
            <div><div style={sectionLabel}>Options plan</div><div style={{ fontSize: 11, color: WL.text.secondary }}>{plan.options_plan || '—'}</div></div>
            <div><div style={sectionLabel}>Watch triggers</div>{(plan.watch_triggers || []).map((w: string, i: number) => <div key={i} style={{ fontSize: 10.5, color: WL.text.muted }}>• {w}</div>)}</div>
            <div><div style={sectionLabel}>Invalidation triggers</div>{(plan.invalidation_triggers || []).map((w: string, i: number) => <div key={i} style={{ fontSize: 10.5, color: WL.text.muted }}>• {w}</div>)}</div>
          </div>
          {plan.why_not && <div style={{ fontSize: 11, color: WL.signal.amber, marginBottom: 8 }}><b>Why not: </b><span style={{ color: WL.text.secondary }}>{plan.why_not}</span></div>}
          {Object.keys(byStrat).length > 0 && (
            <div style={{ marginTop: 6 }}>
              <div style={sectionLabel}>Scanned option candidates</div>
              {['deep_itm_call', 'call_debit_spread', 'cash_secured_put'].filter(s => byStrat[s]?.length).map(s => (
                <div key={s} style={{ marginTop: 6 }}>
                  <div style={{ fontSize: 10.5, fontWeight: 800, color: WL.text.secondary }}>{STRAT_LABEL[s] || s} <span style={{ color: WL.text.dim, fontWeight: 600 }}>· underlying {fmt$(byStrat[s][0]?.underlying_price, 2)}</span></div>
                  {byStrat[s].map((c, i) => <OptionCandidate key={i} c={c} />)}
                </div>
              ))}
            </div>
          )}
          {cites.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div style={sectionLabel}>Sources ({cites.length})</div>
              {cites.map((c, i) => (
                <div key={i} style={{ fontSize: 10, color: WL.text.muted, padding: '2px 0' }}>
                  <span style={{ color: WL.text.secondary }}>{c.claim}</span>{c.source && <span> — {c.source}</span>}
                  {c.url && <a href={c.url} target="_blank" rel="noreferrer" style={{ color: WL.signal.teal, marginLeft: 6 }}>link</a>}
                  {c.as_of && <span style={{ color: WL.text.dim }}> ({c.as_of})</span>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function BucketPicks({ picks, proxies }: { picks: any; proxies: any[] }) {
  const byTicker: Record<string, any> = {}
  proxies.forEach(p => { byTicker[p.proxy_ticker] = p })
  return (
    <div style={{ padding: `10px ${WL.row.padX}px`, borderTop: `1px solid ${WL.surface.divider}` }}>
      <div style={sectionLabel}>Decision cards</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8 }}>
        {PICK_LABELS.map(([key, label, color]) => {
          const tkr = picks?.[key]
          const p = tkr ? byTicker[tkr] : null
          return (
            <div key={key} style={{ padding: '8px 10px', background: WL.surface.inset, borderRadius: 6, borderLeft: `2px solid ${color}` }}>
              <div style={{ fontSize: 8.5, fontWeight: 700, letterSpacing: '.05em', textTransform: 'uppercase', color: WL.text.dim }}>{label}</div>
              <div style={{ ...numStyle, fontSize: 14, fontWeight: 800, color: tkr ? WL.text.primary : WL.text.dim }}>{tkr || '—'}</div>
              {p && <div style={{ fontSize: 9.5, color: WL.text.muted }}>{TYPE_LABEL[p.proxy_type] || p.proxy_type}</div>}
            </div>
          )
        })}
      </div>
      {picks?.rejected?.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: WL.text.dim, marginBottom: 4 }}>Rejected proxies</div>
          {picks.rejected.map((r: any, i: number) => (
            <div key={i} style={{ fontSize: 10.5, color: WL.text.muted, padding: '1px 0' }}>
              <span style={{ ...numStyle, color: WL.text.secondary, fontWeight: 700 }}>{r.ticker}</span> — {r.reason || 'rejected'}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const GENERIC_EDU: { title: string; body: string }[] = [
  { title: 'This is the full graph, not one ticker', body: 'The operator named one proxy; Hermes discovers every public company tied to the private target and ranks them. The named ticker is a starting point, not the answer.' },
  { title: 'Direct economic exposure ranks highest', body: 'A confirmed equity/convertible/CVC stake beats a generic "AI beneficiary" comparable. But a smaller-cap holder with a BIG stake can outrank a mega-cap whose stake is a rounding error.' },
  { title: 'Give the thesis time', body: 'IPO catalysts are uncertain and can be distant. Options decay (theta) daily — short-dated OTM calls can expire worthless even if you are right. Prefer LEAPS / long expiries.' },
  { title: 'Unknown means unknown', body: 'Where a stake value is not disclosed, it is shown as unknown — never fabricated. Every accepted proxy carries a source; rejected ones carry a reason.' },
]

function TargetCard({ t }: { t: any }) {
  const cc = t.card_copy || {}
  const proxies: any[] = t.proxies || []
  const accepted = proxies.filter(p => p.accepted)
  return (
    <div style={{ background: WL.surface.card, border: `1px solid ${WL.surface.edge}`, borderLeft: `3px solid ${WL.text.dim}`, borderRadius: WL.card.radius, boxShadow: WL.card.shadow, overflow: 'hidden', color: WL.text.primary, marginBottom: 16 }}>
      {/* Header */}
      <div style={{ padding: `12px ${WL.row.padX}px`, display: 'flex', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <span style={{ fontSize: 16, fontWeight: 800 }}>{t.private_target_name}</span>
            <span style={{ fontSize: 12, color: WL.text.dim }}>private → {accepted.length} public proxies</span>
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <span style={chip(WL.text.muted, true)}>IPO: {String(t.ipo_status || 'unknown').replace(/_/g, ' ')}</span>
            {t.expected_ipo_window && t.expected_ipo_window !== 'unknown' && <span style={chip(WL.signal.amber, true)}>window {t.expected_ipo_window}</span>}
            {t.latest_valuation && <span style={chip(WL.text.muted, true)}>val {fmtCap(t.latest_valuation)}</span>}
            {t.model_used && <span style={chip(WL.text.dim, true)}>research: {t.model_used}</span>}
          </div>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <span style={chip(WL.signal.amber)} title="Moves on a discrete headline event; direction and timing uncertain">EVENT-DRIVEN</span>
          <span style={chip(WL.signal.red)} title="No paper outcomes yet — do not size as a validated edge">UNVALIDATED</span>
          <span style={chip(WL.text.dim, true)}>ADVISORY ONLY</span>
        </div>
      </div>

      {cc.beginner_summary && (
        <div style={{ margin: `0 ${WL.row.padX}px 12px`, padding: '10px 14px', background: 'rgba(148,163,184,.06)', border: '1px solid rgba(148,163,184,.16)', borderRadius: 8, fontSize: 12.5, lineHeight: 1.5, color: WL.text.secondary }}>{cc.beginner_summary}</div>
      )}

      {/* Decision cards */}
      <BucketPicks picks={t.bucket_picks} proxies={proxies} />

      {/* Ranked proxy graph */}
      <div style={{ padding: `10px ${WL.row.padX}px`, borderTop: `1px solid ${WL.surface.divider}` }}>
        <div style={sectionLabel}>Ranked public-proxy graph ({accepted.length} accepted{t.rejected_count ? `, ${t.rejected_count} rejected` : ''})</div>
        <div style={{ overflowX: 'auto' }}>
          <div style={{ minWidth: 640 }}>
            {accepted.length === 0 && <div style={{ fontSize: 11.5, color: WL.text.dim, fontStyle: 'italic', padding: '6px 0' }}>No accepted proxies yet — run discovery (needs a web lane). Rejected candidates appear in the decision cards above.</div>}
            {accepted.map(p => <ProxyRow key={p.proxy_ticker} p={p} rank={String(p.rank_overall ?? '—')} />)}
          </div>
        </div>
      </div>

      {/* Education */}
      <div style={{ padding: `10px ${WL.row.padX}px`, borderTop: `1px solid ${WL.surface.divider}` }}>
        <div style={sectionLabel}>How proxy investing works</div>
        {[...GENERIC_EDU, ...((cc.education as any[]) || [])].map((e, i) => (
          <div key={i} style={{ padding: '4px 0', fontSize: 11.5, lineHeight: 1.5 }}>
            <span style={{ fontWeight: 700, color: WL.text.primary }}>{e.title}. </span><span style={{ color: WL.text.secondary }}>{e.body}</span>
          </div>
        ))}
      </div>

      {(cc.what_to_monitor as any[])?.length > 0 && (
        <div style={{ padding: `10px ${WL.row.padX}px`, borderTop: `1px solid ${WL.surface.divider}` }}>
          <div style={sectionLabel}>What to monitor</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {(cc.what_to_monitor as string[]).map((w, i) => <span key={i} style={{ ...chip(WL.text.secondary, true), fontWeight: 600 }}>{w}</span>)}
          </div>
        </div>
      )}

      <div style={{ padding: `10px ${WL.row.padX}px`, borderTop: `1px solid ${WL.surface.divider}`, background: 'rgba(2,6,23,.25)', fontSize: 10, lineHeight: 1.5, color: WL.text.dim }}>
        Advisory / research only. No auto-promotion, no live submit — no candidate is live-eligible. View Chain is required before any paper or manual action. Alpaca paper only if you explicitly mark a candidate ready and confirm. Every accepted proxy carries source citations; unknown stakes are shown as unknown, never fabricated. No Schwab / Fidelity / OCO / 2FA behavior is touched.
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
        <div style={{ fontSize: 13, fontWeight: 800, color: WL.text.primary }}>Private-Company Proxy Graph</div>
        <span style={chip(WL.text.dim, true)}>full public-proxy graph — the named ticker is not the whole answer</span>
      </div>
      {loading && targets.length === 0 && <div style={{ color: WL.text.muted, fontSize: 12 }}>Loading proxy graph…</div>}
      {error && <div style={{ color: WL.signal.red, fontSize: 12 }}>Failed to load proxy graph: {error}</div>}
      {!loading && targets.length === 0 && !error && (
        <div style={{ color: WL.text.muted, fontSize: 12 }}>No proxy targets yet. Seed one in config/private_company_proxies.yaml, then run discovery + scan.</div>
      )}
      {targets.map((t, i) => <TargetCard key={t.slug || i} t={t} />)}
    </div>
  )
}
