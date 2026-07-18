import { useState } from 'react'
import { BB, T, DASH, numStyle } from '../../lib/watchTokens'
import LadderTrack from './LadderTrack'

// Defense v3 R5 — the recommendations rail. Per-account tabs, four groups, every card
// complete-or-absent (the engine's field guard enforces; this component renders what
// survives). SHADOW chips until promote. Advisory only — cards route, never execute.

const GROUPS: Array<{ key: string; label: string; color: string; tip: string }> = [
  { key: 'get_into', label: 'Get Into', color: BB.green, tip: 'rotate-in candidates: LEADING/IMPROVING sectors where your effective book weight is under the 4% floor — ETF always valid, constituents pass liquidity/extension/earnings rails' },
  { key: 'protect', label: 'Protect', color: BB.amber, tip: 'move-out/trim advisories on held positions (≥3 fired factors, values shown) + the residual-scraps cleanup card + locked put hedges' },
  { key: 'short_side', label: 'Short-Side', color: BB.red, tip: 'inverse-ETF hedges (all accounts) + taxable-only short advisories from confirmed-LAGGING industries — anti-squeeze filtered, mandatory buy-stops, ≤2% cap' },
  { key: 'income', label: 'Income', color: T.link, tip: 'covered-call candidates on ≥100-share holdings in WEAKENING/LAGGING sectors — concrete strike/premium from last night\'s chain snapshot' },
]

const chip: React.CSSProperties = {
  fontSize: DASH.chip, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '.05em',
  borderRadius: 2, padding: '1px 6px', border: `1px solid ${BB.border}`, color: BB.text2,
}

function PairCard({ c }: { c: any }) {
  const [open, setOpen] = useState(false)
  return (
    <div style={{ border: `1px solid ${T.link}`, borderLeft: `4px solid ${T.link}`, borderRadius: 2, padding: '10px 12px', background: BB.bg }}>
      <div onClick={() => setOpen(o => !o)} style={{ cursor: 'pointer' }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap', marginBottom: 4 }}>
          <span style={{ fontSize: DASH.section, fontWeight: 800, color: BB.text1 }}>{c.title}</span>
          <span style={{ ...chip, color: BB.amber, borderColor: BB.amber }}>{c.mode}</span>
          {c.is_core && <span style={{ ...chip, color: BB.amber }}>★CORE</span>}
          <span style={{ ...chip }}>{c.tax_note.split('—')[0].trim()}</span>
        </div>
        <div title="the sell leg: whole-share ESTIMATE at the labeled as-of price — confirming it runs the ladder/round-trip flow; never an order" style={{ fontSize: DASH.data, color: BB.text1, fontWeight: 600, marginBottom: 2, cursor: 'help' }}>{c.sell_ticket.line}</div>
        {c.buy_legs.map((l: any) => (
          <div key={l.symbol} title="buy leg funded by the sell proceeds (same account) — staged as a PENDING idea in the approval queue; you approve, nothing self-executes" style={{ fontSize: DASH.data, color: BB.text2, marginBottom: 2, cursor: 'help' }}>→ {l.line}</div>
        ))}
        <div style={{ fontSize: DASH.data, color: BB.text3 }}>
          {c.style_rationale}
          {c.exposure_after?.sector && <span> · {c.exposure_after.sector} {c.exposure_after.before_pct}% → {c.exposure_after.after_pct}%</span>}
          {c.exposure_after?.income_sleeve_pp && <span> · income sleeve {c.exposure_after.income_sleeve_pp}</span>}
          <span> · {open ? '▾ less' : '▸ detail'}</span>
        </div>
      </div>
      {open && (
        <div style={{ marginTop: 6, paddingTop: 6, borderTop: `1px solid ${BB.borderHair}`, fontSize: DASH.data, color: BB.text2, display: 'flex', flexDirection: 'column', gap: 3 }}>
          {c.factors.map((f: any, i: number) => (
            <div key={i}><span style={{ color: BB.text3 }}>{f.name}:</span> <b>{String(f.value)}</b></div>
          ))}
          <div><span style={{ color: BB.text3 }}>entry:</span> {c.entry_logic}</div>
          <div><span style={{ color: BB.text3 }}>invalidation:</span> {c.invalidation}</div>
          <div style={{ color: BB.amber }}>{c.tax_note}</div>
          {c.cross_account_note && <div style={{ color: BB.text3 }}>{c.cross_account_note}</div>}
          <div style={{ color: BB.text3 }}>routes: sell — {c.routes.sell} · buys — {c.routes.buys}</div>
        </div>
      )}
    </div>
  )
}

function StageOrderButton({ label, payload, accounts, autoTwin }: { label: string; payload: any; accounts?: string[]; autoTwin?: boolean }) {
  const [state, setState] = useState<'idle' | 'busy' | 'ok' | 'refused'>('idle')
  const [msg, setMsg] = useState('')
  // v8 A1 — the CARD's account is the default (real, first-listed); multi-account asks;
  // NEVER silently paper-first. The paper twin is a SEPARATE, labeled SHADOW intent.
  const real = (accounts || []).filter(a => a !== 'alpaca_paper')
  const [acct, setAcct] = useState<string>(real[0] || payload.account)
  const disp = (a: string) => a === 'alpaca_paper' ? 'Alpaca Paper (shadow)' : a.replace('schwab_', '').replace(/_/g, ' ')
  const stage = async (e: any) => {
    e.stopPropagation()
    setState('busy')
    try {
      const r = await fetch('/api/v2/defense/intent/stage', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...payload, account: acct }),
      })
      const j = await r.json()
      if (j.ok) {
        setState('ok')
        let m = `staged → APPROVALS (${disp(acct)})`
        if (autoTwin && acct !== 'alpaca_paper') {
          const t = await fetch('/api/v2/defense/intent/stage', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...payload, account: 'alpaca_paper', source_card: payload.source_card + '-twin' }),
          })
          if ((await t.json()).ok) m += ' + SHADOW twin (Alpaca Paper)'
        }
        setMsg(m)
      }
      else { setState('refused'); setMsg(j.refused || j.error || 'refused') }
    } catch { setState('idle') }
  }
  return (
    <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', marginBottom: 3 }}>
      {real.length > 1 && (
        <select value={acct} onClick={e => e.stopPropagation()} onChange={e => setAcct(e.target.value)}
          title="the card lists multiple valid accounts — pick the target (never silently chosen)"
          style={{ fontSize: DASH.chip, background: 'transparent', color: BB.text1, border: `1px solid ${BB.border}`, borderRadius: 2, padding: '1px 4px' }}>
          {real.map(a => <option key={a} value={a}>{disp(a)}</option>)}
        </select>
      )}
      <button onClick={stage} disabled={state === 'busy' || state === 'ok'}
        title="stages this order intent: caps + whitelist checked now → APPROVALS queue → 2FA pill → paper auto-executes / live renders an armed ticket. Nothing executes from this click."
        style={{ fontSize: DASH.chip, fontWeight: 800, textTransform: 'uppercase', cursor: 'pointer', color: state === 'ok' ? BB.green : BB.text1, background: 'transparent', border: `1px solid ${state === 'ok' ? BB.green : state === 'refused' ? BB.red : BB.amber}`, borderRadius: 2, padding: '2px 9px' }}>
        {state === 'busy' ? '…' : state === 'ok' ? '✓ staged' : label}
      </button>
      {msg && <span style={{ fontSize: DASH.chip, color: state === 'refused' ? BB.red : BB.text3 }}>{msg}</span>}
    </span>
  )
}

function ValidateButton({ cs, onValid }: { cs: any; onValid: (ts: string) => void }) {
  const [res, setRes] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const run = async (e: any) => {
    e.stopPropagation()
    setBusy(true)
    try {
      const r = await fetch('/api/v2/defense/chain/validate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: cs.symbol, strike: cs.strike, exp: cs.exp, delta: cs.delta }),
      })
      const j = await r.json()
      setRes(j)
      if (j.ok && j.all_pass) onValid(j.validated_at)
    } finally { setBusy(false) }
  }
  return (
    <span style={{ display: 'block', marginBottom: 3 }}>
      <button onClick={run} disabled={busy}
        title="fresh single-contract chain pull (throttled): re-checks OI, volume, spread, delta against the rails and shows the live book — the trade button stays locked until a validation ≤15 min old passes"
        style={{ fontSize: DASH.chip, fontWeight: 800, textTransform: 'uppercase', cursor: 'pointer', color: BB.text1, background: 'transparent', border: `1px solid ${T.link}`, borderRadius: 2, padding: '2px 9px', marginRight: 6 }}>
        {busy ? 'validating…' : '⟳ validate chain'}
      </button>
      {res && res.ok && (
        <span style={{ fontSize: DASH.chip, color: res.all_pass ? BB.green : BB.red }}>
          {res.rows.map((r: any) => `${r.pass ? '✓' : '✗'} ${r.rail} ${r.value}`).join(' · ')} · book ${res.book.bid}×${res.book.ask} · {String(res.validated_at).slice(11, 19)}Z
        </span>
      )}
      {res && res.ok && res.drift && (
        <span style={{ display: 'block', fontSize: DASH.chip, color: BB.amber }}>
          drift: {res.drift.line} — re-stage required (never silently substituted)
        </span>
      )}
      {res && !res.ok && <span style={{ fontSize: DASH.chip, color: BB.red }}>{res.error}</span>}
    </span>
  )
}

function QueueTradeButton({ cs, validatedAt }: { cs: any; validatedAt: string | null }) {
  const [state, setState] = useState<'idle' | 'busy' | 'queued'>('idle')
  const fresh = validatedAt != null && (Date.now() - new Date(validatedAt).getTime()) < 15 * 60_000
  const queue = async (e: any) => {
    e.stopPropagation()
    setState('busy')
    try {
      const r = await fetch('/api/v2/defense/cc/queue-trade', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cc_struct: cs }),
      })
      setState((await r.json()).ok ? 'queued' : 'idle')
    } catch { setState('idle') }
  }
  return (
    <button onClick={queue} disabled={state !== 'idle' || !fresh}
      title={fresh ? 'queues this exact structure into the options approval queue — YOU approve there, and per-order 2FA gates the actual order; nothing executes from this page'
        : 'LOCKED — run ⟳ validate chain first (validation must be ≤15 min old); the click is gated on fresh rails'}
      style={{ fontSize: DASH.chip, fontWeight: 800, textTransform: 'uppercase', cursor: fresh ? 'pointer' : 'not-allowed', opacity: fresh ? 1 : 0.45, color: state === 'queued' ? BB.green : BB.text1, background: 'transparent', border: `1px solid ${state === 'queued' ? BB.green : BB.amber}`, borderRadius: 2, padding: '2px 9px', marginBottom: 3 }}>
      {state === 'busy' ? '…' : state === 'queued' ? '✓ queued — approve in Options (2FA)' : fresh ? '⚡ queue trade (2FA approval)' : '🔒 re-validate first'}
    </button>
  )
}

function Card({ c, tab, ladder }: { c: any; tab: string; ladder?: any }) {
  const [open, setOpen] = useState(false)
  const [validatedAt, setValidatedAt] = useState<string | null>(null)
  const g = GROUPS.find(x => x.key === c.group)
  // v6: singles superseded by a pair fold to one line — reachable, never deleted
  const [unfolded, setUnfolded] = useState(false)
  if (c.superseded_by_pair && !unfolded) {
    return (
      <div onClick={() => setUnfolded(true)} style={{ border: `1px dashed ${BB.borderHair}`, borderRadius: 2, padding: '5px 10px', cursor: 'pointer', fontSize: DASH.data, color: BB.text3 }}>
        {c.title.split('(')[0].trim()} — superseded by a ROTATE pair above · click to expand the single
      </div>
    )
  }
  const lv = c.levels || {}
  // dollars for the SELECTED account tab; 'all' shows the largest valid account's band
  const band = c.dollars_by_account && (
    tab !== 'all' && c.dollars_by_account[tab]
      ? { label: '', v: c.dollars_by_account[tab] }
      : Object.entries(c.dollars_by_account).sort((a: any, b: any) => b[1][1] - a[1][1])[0]
        ? { label: Object.entries(c.dollars_by_account).sort((a: any, b: any) => b[1][1] - a[1][1])[0][0], v: (Object.entries(c.dollars_by_account).sort((a: any, b: any) => b[1][1] - a[1][1])[0][1] as number[]) }
        : null)
  const fmt$ = (n: number) => n >= 1000 ? `$${(n / 1000).toFixed(1)}K` : `$${n}`
  const topFactors = (c.factors || []).slice(0, 2)
  return (
    <div style={{ border: `1px solid ${BB.border}`, borderLeft: `3px solid ${g?.color || BB.text3}`, borderRadius: 2, padding: '8px 10px', background: BB.bg }}>
      <div onClick={() => setOpen(o => !o)} style={{ cursor: 'pointer' }}>
        <div style={{ fontSize: DASH.data + 1, fontWeight: 700, color: BB.text1, marginBottom: 4 }}>{c.title}</div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 4 }}>
          <span title="SHADOW = advisory renders on-page only; Telegram alerts start only after the Jul 30–31 promote review" style={{ ...chip, color: BB.amber, borderColor: BB.amber, cursor: 'help' }}>{c.mode}</span>
          <span title="what this card asks you to do — advisory only, nothing places orders" style={{ ...chip, cursor: 'help' }}>{c.direction}</span>
          {band?.v
            ? <span style={chip}>{fmt$(band.v[0])}–{fmt$(band.v[1])}{band.label ? ` (${band.label.replace('schwab_', '')})` : ''}</span>
            : <span style={chip}>{c.size_band.split('(')[0].trim()}</span>}
        </div>
        <div style={{ fontSize: DASH.data, color: BB.text2, marginBottom: 3 }}>
          {c.instruments.map((i: any) => (
            <span key={i.symbol + i.kind} style={{ marginRight: 10 }}>
              <b style={{ ...numStyle, color: BB.text1 }}>{i.symbol}</b>
              {i.price != null && <span style={{ ...numStyle, color: BB.text2 }}> ${i.price}</span>}
              <span style={{ color: BB.text3 }}> {i.kind}</span>
            </span>
          ))}
        </div>
        {(lv.entry_zone || lv.stop || lv.position_value) && (
          <div style={{ fontSize: DASH.data, color: BB.text2, marginBottom: 3 }}>
            {lv.position_value ? <span>position <b style={numStyle}>{fmt$(lv.position_value)}</b> · </span> : null}
            {lv.entry_zone ? <span>entry: {lv.entry_zone} · </span> : null}
            {lv.stop ? <span style={{ color: BB.amber }}>{lv.stop}</span> : null}
          </div>
        )}
        {/* v5 DT2 — the sell ticket ON the face (estimates, as-of labeled, IRA-first) */}
        {c.ticket?.options?.map((o: any, i: number) => (
          <div key={i} style={{ fontSize: DASH.data, color: o.kind === 'taxable_harvest' ? BB.amber : BB.text1, marginBottom: 2, fontWeight: 600 }}>
            {o.line}
          </div>
        ))}
        {c.ticket && <div style={{ fontSize: DASH.chip, color: BB.text3, marginBottom: 3 }}>{c.instruments[0]?.price != null ? '' : ''}{(c.ticket.options?.[0]?.price_as_of) || ''} · estimates, not order instructions</div>}
        {ladder && <LadderTrack ladder={ladder} price={c.levels?.price} />}
        {c.playbook && !open && (
          <div title="full 4-step playbook in the expand — entry alerts are armed on the 20-min evaluator" style={{ fontSize: DASH.data, color: BB.amber, marginBottom: 3, cursor: 'help' }}>
            ▶ {c.playbook[0].slice(0, 118)}…
          </div>
        )}
        {c.cc_struct && <ValidateButton cs={c.cc_struct} onValid={setValidatedAt} />}
        {c.cc_struct && <QueueTradeButton cs={c.cc_struct} validatedAt={validatedAt} />}
        {c.id?.startsWith('moveout-') && c.ticket?.options?.[0] && (
          <StageOrderButton label={`stage sell (${c.ticket.options[0].account_label})`} payload={{
            source_card: c.id, intent_type: 'trim_sell', symbol: c.instruments[0].symbol,
            side: 'sell', qty: c.ticket.options[0].shares,
            limit_low: c.levels?.price ? +(c.levels.price * 0.995).toFixed(2) : null,
            limit_high: c.levels?.price ? +(c.levels.price * 1.005).toFixed(2) : null,
            account: c.ticket.options[0].account, est_dollars: c.ticket.options[0].proceeds_est,
          }} />
        )}
        {c.id?.startsWith('inverse-') && (
          <StageOrderButton label="stage hedge entry" accounts={c.accounts} autoTwin={true} payload={{
            source_card: c.id, intent_type: 'inverse_etf', symbol: c.instruments[0].symbol,
            side: 'buy', qty: Math.max(1, Math.floor(2000 / (c.levels?.price || 1))),
            limit_low: c.levels?.price ? +(c.levels.price * 0.995).toFixed(2) : null,
            limit_high: c.levels?.price ? +(c.levels.price * 1.01).toFixed(2) : null,
            account: (c.accounts || []).filter((a: string) => a !== 'alpaca_paper')[0] || c.accounts?.[0], est_dollars: 2000,
          }} />
        )}
        {c.id?.startsWith('short-') && (
          <StageOrderButton label="stage short (Taxable, 2FA)" payload={{
            source_card: c.id, intent_type: 'taxable_short', symbol: c.instruments[0].symbol,
            side: 'sell_short', qty: Math.max(1, Math.floor(700 / (c.levels?.price || 1))),
            limit_low: c.levels?.price ? +(c.levels.price * 0.99).toFixed(2) : null,
            limit_high: c.levels?.price ? +(c.levels.price * 1.005).toFixed(2) : null,
            account: 'schwab_taxable', est_dollars: 700,
          }} />
        )}
        <div style={{ fontSize: DASH.data, color: BB.text3 }}>
          {topFactors.map((f: any, i: number) => (
            <span key={i} style={{ marginRight: 10 }}>{f.name}: <b style={{ color: BB.text2 }}>{String(f.value)}</b></span>
          ))}
          <span>{open ? '▾ less' : `▸ ${Math.max(0, (c.factors || []).length - 2)} more`}</span>
        </div>
      </div>
      {open && (
        <div style={{ marginTop: 6, paddingTop: 6, borderTop: `1px solid ${BB.borderHair}`, fontSize: DASH.data, color: BB.text2, display: 'flex', flexDirection: 'column', gap: 3 }}>
          {c.playbook && (
            <div style={{ border: `1px solid ${BB.amber}`, borderRadius: 2, padding: '6px 9px', marginBottom: 3 }}>
              <div style={{ fontSize: DASH.chip, fontWeight: 800, color: BB.amber, textTransform: 'uppercase', marginBottom: 3 }}>Playbook — in after highs, out with profits</div>
              {c.playbook.map((line: string, i: number) => (
                <div key={i} style={{ marginBottom: 3, color: BB.text1 }}>{line}</div>
              ))}
            </div>
          )}
          {c.factors.slice(2).map((f: any, i: number) => (
            <div key={i}><span style={{ color: BB.text3 }}>{f.name}:</span> <b>{String(f.value)}</b></div>
          ))}
          <div><span style={{ color: BB.text3 }}>entry:</span> {c.entry_logic}</div>
          <div><span style={{ color: BB.text3 }}>invalidation:</span> {c.invalidation}</div>
          {c.instruments.filter((i: any) => i.note).map((i: any) => (
            <div key={i.symbol}><span style={{ color: BB.text3 }}>{i.symbol}:</span> {i.note}</div>
          ))}
          {Object.entries(c.routes || {}).map(([k, v]) => (
            <div key={k}><span style={{ color: BB.text3 }}>route/{k}:</span> {String(v)}</div>
          ))}
          <div style={{ color: BB.text3 }}>as of {c.as_of} · valid: {c.accounts.join(', ')}</div>
        </div>
      )}
    </div>
  )
}

export default function RecommendationsRail({ recs }: { recs: any }) {
  const [tab, setTab] = useState<string>('all')
  const accounts: Record<string, string> = recs?.accounts || {}
  const groups: Record<string, any[]> = recs?.groups || {}
  const pairs: any[] = recs?.pairs || []
  const ladders: any[] = recs?.ladders || []
  const ladderFor = (cardId: string) => ladders.find(l => l.advisory_id === cardId)
  const all = Object.values(groups).flat()
  const forTab = (cards: any[]) => tab === 'all' ? cards : cards.filter(c => c.accounts.includes(tab))
  const countFor = (key: string) => key === 'all' ? all.length : all.filter(c => c.accounts.includes(key)).length

  return (
    <div style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: '10px 12px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: DASH.panel, fontWeight: 800, color: BB.text1 }}>Recommendations</span>
        <span style={{ fontSize: DASH.data, color: BB.text3 }}>{recs?.shadow_note || ''}</span>
      </div>
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 10 }}>
        {[['all', 'All'], ...Object.entries(accounts).filter(([k]) => k !== 'alpaca_paper')].map(([key, label]) => (
          <button key={key} onClick={() => setTab(key)} style={{
            fontSize: DASH.data, fontWeight: 700, padding: '3px 10px', cursor: 'pointer', borderRadius: 2,
            color: tab === key ? BB.text1 : BB.text3, background: tab === key ? BB.border : 'transparent',
            border: `1px solid ${BB.border}`,
          }}>
            {label} <span style={{ ...numStyle, color: tab === key ? BB.text2 : BB.text3 }}>{countFor(key)}</span>
          </button>
        ))}
      </div>
      {/* v6 — funded rotation pairs: full-width, superseding their singles below */}
      {forTab(pairs).length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 10 }}>
          <div style={{ fontSize: DASH.section, fontWeight: 800, color: T.link }}>
            Funded rotations <span style={{ ...numStyle, color: BB.text3, fontSize: DASH.data }}>{forTab(pairs).length}</span>
            <span style={{ fontSize: DASH.chip, color: BB.text3, fontWeight: 600, marginLeft: 8 }}>out of X, into Y — same account, both legs ticketed</span>
          </div>
          {forTab(pairs).map(p => <PairCard key={p.id} c={p} />)}
        </div>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 10 }}>
        {GROUPS.map(g => {
          const cards = forTab(groups[g.key] || [])
          return (
            <div key={g.key}>
              <div title={g.tip} style={{ fontSize: DASH.section, fontWeight: 800, color: g.color, marginBottom: 6, cursor: 'help' }}>
                {g.label} <span style={{ ...numStyle, color: BB.text3, fontSize: DASH.data }}>{cards.length}</span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {cards.length === 0 && (
                  <div style={{ fontSize: DASH.data, color: BB.text3, border: `1px dashed ${BB.borderHair}`, borderRadius: 2, padding: '8px 10px' }}>
                    {tab !== 'all'
                      ? `nothing valid for ${accounts[tab] || tab} in this group today`
                      : (recs?.empty_reasons?.[g.key] || 'none today')}
                  </div>
                )}
                {cards.map(c => <Card key={c.id} c={c} tab={tab} ladder={ladderFor(c.id)} />)}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
