import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'

// ════════════════════════════════════════════════════════════════════════════════════════════════
// Broker Orders — thinkorswim-DESKTOP-style Active Trader surface (Stage 2a, DORMANT).
// The layout/familiarity is ToS; the execution model is NOT: every control builds or edits a DRAFT
// canonical intent that routes through /preview (validate+translate) and is BLOCKED by the guard.
// There is NO "auto send", NO submit endpoint, NO one-click live order anywhere on this surface.
// ════════════════════════════════════════════════════════════════════════════════════════════════
const mono = { fontFamily: 'JetBrains Mono, monospace' as const }
const T = {
  bg: '#0d0d0d', card: '#161616', border: '#2c2c2c', dim: '#8a8a8a', text: '#e0e0e0',
  buy: '#2e7d32', buyHi: '#43a047', sell: '#c62828', sellHi: '#e53935', amber: '#ffa726',
}
const lbl = { fontSize: 8.5, color: T.dim, textTransform: 'uppercase' as const, letterSpacing: 0.6 }
const inp = { fontSize: 11.5, padding: '4px 7px', borderRadius: 3, border: `1px solid ${T.border}`,
  background: '#101010', color: T.text, width: 86, ...mono } as const
const btn = (bg: string, fg = '#fff') => ({ fontSize: 9.5, fontWeight: 700, padding: '4px 10px',
  borderRadius: 3, border: `1px solid ${T.border}`, background: bg, color: fg, cursor: 'pointer' as const })

const STATE_C: Record<string, string> = {
  TRANSLATED: '#66bb6a', BLOCKED: '#ef5350', DRAFT: '#64b5f6', VALIDATED: '#ffee58',
}

// ── static tooltips: what each order structure does + how it translates to Schwab ───────────────
const STRATEGY_TIP: Record<string, string> = {
  SINGLE: 'One standalone order, no attached exits. Translates to a Schwab SINGLE orderStrategyType.',
  BRACKET: 'OTOCO bracket: the entry, once filled, TRIGGERs an OCO pair (one profit target + one stop). Translates to orderStrategyType TRIGGER with a childOrderStrategies OCO of [LIMIT target, STOP].',
  MULTI_TARGET: 'OTOCO with TWO profit targets splitting the position (e.g. 50%/50%) plus one stop, all OCO: any fill/stop cancels the rest. Translates to TRIGGER → OCO of [LIMIT t1, LIMIT t2, STOP]. Runtime acceptance of the qty split is UNVERIFIED until the canary session.',
  TRAILING: 'Entry + trailing stop exit: the stop follows price by the offset (e.g. 3% off LAST). Translates to TRIGGER → child TRAILING_STOP with stopPriceLinkBasis/Type/Offset.',
  OCO: 'OCO exits ONLY (for an existing position): target + stop, either filling cancels the other. Translates to orderStrategyType OCO with two SINGLE children.',
  LADDER: 'Scale-in ladder: 2+ LIMIT entries at stepped prices splitting the quantity. WE coordinate the legs (cancel-all-on-stop is our logic, not the broker\'s). Each leg translates to its own order.',
}
const FIELD_TIP: Record<string, string> = {
  qty: 'Shares per order. Canary presets only (2/5/10) — the hardcoded gate caps qty at 10 and notional at $40.',
  limit: 'Limit price: the worst price you accept. Becomes Schwab "price". The canary gate requires a limit (≤$4) — MARKET drafts preview fine but can never pass the envelope.',
  stopPrice: 'Entry stop trigger: order activates when price touches this. Becomes Schwab "stopPrice".',
  stopLoss: 'Protective stop exit below entry (long). Becomes a child STOP order via TRIGGER.',
  target: 'Profit target exit above entry (long). Becomes a child LIMIT order via TRIGGER.',
  trail: 'Trailing offset: distance the stop follows price. PERCENT = % off basis, VALUE = $, TICK = ticks. Becomes stopPriceLinkBasis/Type/Offset on a TRAILING_STOP child.',
  tif: 'Time in force: DAY dies at close; GTC works until cancelled (Schwab GOOD_TILL_CANCEL); FOK/IOC are all-or-now variants.',
  session: 'NORMAL = regular hours; AM/PM = extended sessions; SEAMLESS = all. Translates to Schwab "session".',
}

function humanSummary(it: any): { line: string; pills: string[]; purpose: string } {
  if (!it) return { line: '—', pills: [], purpose: '' }
  const q = it.quantity?.qty ?? it.quantity?.notional ?? it.quantity?.contracts
  const e = it.entry ?? {}
  const x = it.exit_policy ?? {}
  const entryTxt = e.method === 'MARKET' ? 'at market'
    : e.method === 'LIMIT' ? `limit $${e.limit_price ?? e.entry_range?.high ?? '?'}`
    : e.method === 'STOP' ? `buy-stop $${e.stop_price}`
    : e.method === 'STOP_LIMIT' ? `stop $${e.stop_price} / limit $${e.limit_price}`
    : (e.method ?? '').replace(/_/g, ' ').toLowerCase()
  const line = `${it.direction === 'SHORT' ? 'SELL SHORT' : 'BUY'} ${q} sh ${it.instrument?.symbol} ${entryTxt}`
  const pills: string[] = []
  if (x.stop?.price) pills.push(`stop $${x.stop.price}`)
  if (x.stop?.trail) pills.push(`trailing ${x.stop.trail.offset}${x.stop.trail.type === 'PERCENT' ? '%' : x.stop.trail.type === 'TICK' ? ' ticks' : '$'} off ${x.stop.trail.basis}`)
  if (!x.stop) pills.push('⚠ no stop')
  for (const t of (x.targets ?? [])) pills.push(`target $${t.price}${t.qty_pct < 100 ? ` (${t.qty_pct}%)` : ''}`)
  if (it.ladder) pills.push(`ladder ×${it.ladder.legs?.length}`)
  if (it.tif !== 'DAY') pills.push(it.tif)
  if (it.session !== 'NORMAL') pills.push(`session ${it.session}`)
  const purpose = it.meta?.thesis || 'operator draft from the Active Trader panel'
  return { line, pills, purpose }
}

function groupEvents(events: any[]): { text: string; n: number; block: boolean; at: string }[] {
  const out: { text: string; n: number; block: boolean; at: string }[] = []
  for (const e of events) {
    const txt = String(e.event).startsWith('guard:')
      ? (String(e.event).includes('BLOCK')
        ? `Guard BLOCKED a ${String(e.event).split(':')[1]} attempt — ${String(e.detail).slice(0, 70)}`
        : `Guard allowed ${String(e.event).split(':')[1]} (${String(e.event).split(':')[3] ?? ''})`)
      : String(e.event).startsWith('state:')
        ? `Intent saved as ${String(e.event).slice(6)}`
        : `${e.event} ${e.detail ?? ''}`
    const last = out[out.length - 1]
    if (last && last.text === txt) { last.n += 1 } else {
      out.push({ text: txt, n: 1, block: String(e.event).includes('BLOCK'), at: String(e.created_at).slice(5, 16) })
    }
  }
  return out.slice(0, 25)
}

// ── TYPE-THE-TICKER web confirm (Part E: a click alone NEVER confirms) ───────────────────────────
function TickerConfirmModal({ intentId, symbol, onClose, onDone }:
  { intentId: string; symbol: string; onClose: () => void; onDone: (msg: string) => void }) {
  const [typed, setTyped] = useState('')
  const ok = typed.trim().toUpperCase() === String(symbol).toUpperCase()
  const confirm = async () => {
    const r = await fetch('/api/v2/broker-orders/approve', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ intent_id: intentId, channel: 'web', code: typed.trim() }) })
    const j = await r.json()
    onDone(JSON.stringify(j?.data ?? j).slice(0, 140))
    onClose()
  }
  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.75)', zIndex: 80, display: 'flex',
      alignItems: 'center', justifyContent: 'center' }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{ background: T.card, border: `1px solid ${T.amber}`,
        borderRadius: 8, padding: 18, width: 'min(380px, 92vw)' }}>
        <div style={{ fontSize: 12, fontWeight: 800, color: T.amber }}>⚠ WEB CONFIRMATION — either channel approves</div>
        <div style={{ fontSize: 10, color: '#bdbdbd', marginTop: 6, lineHeight: 1.5 }}>
          Anti-fat-finger check: type the ticker <b style={{ color: T.text, ...mono }}>{symbol}</b> to enable
          Confirm. This <b style={{ color: T.text }}>or</b> the Telegram code is enough — you don't need both.
          Single-use, expires with the approval TTL, one order at a time.
          <b style={{ color: '#90caf9' }}> Draft approval only. Draft cards never submit; use the top Stage 2b Pilot Console preflight box to submit.</b>
        </div>
        <input autoFocus value={typed} onChange={e => setTyped(e.target.value)}
          placeholder={`type ${symbol} here`}
          style={{ ...inp, width: '100%', marginTop: 10, fontSize: 14, padding: '8px 10px',
            borderColor: ok ? '#66bb6a' : T.border }} />
        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <button disabled={!ok} onClick={confirm}
            style={{ ...btn(ok ? T.buy : '#222', ok ? '#fff' : '#555'), flex: 1, padding: '8px 0', fontSize: 11 }}>
            {ok ? `CONFIRM ${symbol} (web channel)` : 'type the ticker to enable'}</button>
          <button onClick={onClose} style={{ ...btn('#333'), padding: '8px 14px' }}>cancel</button>
        </div>
      </div>
    </div>
  )
}

function ApprovalPanel({ intentId, symbol }: { intentId: string; symbol: string }) {
  const { data: st, refetch } = useApi<any>(`/api/v2/broker-orders/approval-status?intent_id=${intentId}`, 15_000)
  const [code, setCode] = useState('')
  const [msg, setMsg] = useState('')
  const [popup, setPopup] = useState(false)
  const s = (st as any)?.data ?? st
  const chans: any[] = s?.channels ?? []
  const web = chans.find((c: any) => c.channel === 'web')
  const tg = chans.find((c: any) => c.channel === 'telegram')
  const post = async (path: string, body: any) => {
    const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    const j = await r.json(); setMsg(JSON.stringify(j?.data ?? j).slice(0, 150)); refetch()
  }
  const badge = (c: any, label: string) => (
    <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 3,
      background: (c?.status === 'confirmed' ? '#66bb6a' : c?.status === 'pending' ? '#ffee58' : T.dim) + '22',
      color: c?.status === 'confirmed' ? '#66bb6a' : c?.status === 'pending' ? '#ffee58' : T.dim }}>
      {label}: {c?.status ?? '—'}
    </span>
  )
  return (
    <div style={{ marginTop: 8, padding: 8, background: '#101010', border: `1px solid ${T.border}`, borderRadius: 4 }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{ fontSize: 10, fontWeight: 700, color: T.text }}>🔐 Approval — either channel</span>
        <span style={{ fontSize: 9, color: T.dim }}>— ① Telegram code (proposals chat, deep-links back here) OR ② web popup where you TYPE the ticker. Either one approves.</span>
        {badge(web, 'web')} {badge(tg, 'telegram')}
        {s?.fully_approved && <span style={{ fontSize: 9, fontWeight: 800, color: '#66bb6a' }}>FULLY APPROVED — draft only; submit from top Pilot Console</span>}
      </div>
      <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
        <button onClick={() => post('/api/v2/broker-orders/request-approval', { intent_id: intentId })}
          style={btn('#1565c0')}>Request approval (Telegram + deep-link)</button>
        <button onClick={() => setPopup(true)} style={btn(T.buy)}>Confirm — web (type ticker…)</button>
        <input value={code} onChange={e => setCode(e.target.value)} placeholder="telegram code"
          style={{ ...inp, width: 90, fontSize: 10 }} />
        <button onClick={() => post('/api/v2/broker-orders/approve', { intent_id: intentId, channel: 'telegram', code })}
          style={btn('#6a1b9a')}>Confirm — telegram code</button>
      </div>
      {msg && <div style={{ fontSize: 9, color: T.dim, marginTop: 5, ...mono }}>{msg}</div>}
      {popup && <TickerConfirmModal intentId={intentId} symbol={symbol} onClose={() => setPopup(false)}
        onDone={m => { setMsg(m); refetch() }} />}
    </div>
  )
}

// ── Canary 5-ticket battery (Monday 2026-06-15) — ALL single-leg, ALL via the API pilot. A logical
// round-trip that proves every order TYPE + lifecycle inside the ≤$4/$40/10-share envelope:
//   1 buy_cancel  BUY  LIMIT  below-market → place + CANCEL (cannot fill)  · pilot order 1
//   2 real_fill   BUY  LIMIT  @ live ask   → let it FILL (~$33)            · pilot order 2 (now long 10)
//   3 protective  SELL STOP   below-market → place + CANCEL (won't trigger)· pilot order 3
//   4 trailing    SELL TRAIL  3% off LAST  → place + CANCEL (won't trigger)· pilot order 4
//   5 close       SELL LIMIT  @ live bid   → CLOSE the long (back to flat) · pilot order 5
// pkey = which body field carries the operator value; live = pull bid/ask at load time.
// Pared down to the ONE proven $0 test (operator 2026-06-15: only the place→cancel worked cleanly; the
// rigid 2-5 sequence caused confusion). This preset just auto-fills the form below — the manual form
// (symbol/qty/limit → type ticker → SUBMIT) handles any other allowlisted order ad-hoc, decoupled.
const CANARY_BATTERY: any[] = [
  { n: 'TEST', shape: 'buy_cancel', symbol: 'GRAB', qty: 10, pkey: 'price', plabel: 'limit $', pdef: '1.70',
    title: '$0 PLACE → CANCEL test', spec: 'BUY 10 GRAB LIMIT 1.70 DAY',
    note: 'BUY ~50% below market — CANNOT fill. Tap → type the ticker → SUBMIT → confirm it RESTS in ToS → Cancel. Proves the full place + cancel path at zero fill risk. (Proven working 2026-06-15.)' },
]

// ── STAGE 2b PILOT CONSOLE — the ONLY surface that can reach the fenced write path. Flow:
// preflight (envelope/gate/quote) → 2FA (existing ApprovalPanel: web typed-ticker + Telegram) →
// execute (transport re-enforces the whole stack server-side) → cancel. Everything fail-closed.
function PilotConsole() {
  const { data: stR, refetch } = useApi<any>('/api/v2/broker-orders/pilot/status', 15_000)
  const s = (stR as any)?.data ?? stR
  const [symbol, setSymbol] = useState('')
  const [qty, setQty] = useState('1')
  const [limit, setLimit] = useState('')
  const [step, setStep] = useState<any>(null)   // selected canary battery preset
  const [param, setParam] = useState('')        // shape value: limit $ / stop $ / trail %
  const [armModal, setArmModal] = useState<null | 'arm' | 'disarm'>(null)
  const [armPhrase, setArmPhrase] = useState('')
  const [armMsg, setArmMsg] = useState('')
  const [pf, setPf] = useState<any>(null)
  const [execMsg, setExecMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirmTicker, setConfirmTicker] = useState('')  // type-the-ticker = fat-finger confirm + submit
  // Schwab OAuth token health — surface re-auth UP FRONT (the freshness timestamp can read healthy while
  // Schwab has revoked the token server-side; preflight catches it too, but this warns before any attempt).
  const [tokenHealth, setTokenHealth] = useState<any>(null)
  const needsReauth = tokenHealth?.needs_reauth === true
  useEffect(() => {
    fetch('/api/v2/brokers/schwab/token-health').then(x => x.json()).then(j => setTokenHealth((j as any)?.data ?? j)).catch(() => {})
  }, [])
  const post = async (path: string, body: any) => {
    setBusy(true)
    try { const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); const j = await r.json(); return (j as any)?.data ?? j }
    finally { setBusy(false) }
  }
  if (!s) return null
  const lock = (label: string, ok: boolean, tip?: string) => (
    <span title={tip} style={{ fontSize: 9, fontWeight: 800, padding: '2px 7px', borderRadius: 3,
      background: (ok ? '#66bb6a' : '#ef5350') + '22', color: ok ? '#66bb6a' : '#ef5350' }}>{ok ? '🔓' : '🔒'} {label}</span>
  )
  const armed = !!s.armed
  const used = s.pilot_orders_used ?? 0
  const cap = s.pilot_orders_cap ?? 5
  return (
    <div style={{ border: `1px solid ${armed ? '#66bb6a55' : T.border}`, borderRadius: 6, padding: 12, marginBottom: 12, background: T.card }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{ fontSize: 12, fontWeight: 800, color: T.text }}>STAGE 2b PILOT CONSOLE</span>
        <span style={{ fontSize: 9, fontWeight: 800, padding: '2px 8px', borderRadius: 3,
          background: (armed ? '#66bb6a' : '#ef5350') + '22', color: armed ? '#66bb6a' : '#ef5350' }}>
          {armed ? 'ARMED' : 'DISARMED'}</span>
        <span style={{ fontSize: 10, fontWeight: 800, color: used >= cap ? '#ef5350' : T.text }}>orders {used}/{cap}</span>
        <span style={{ flex: 1 }} />
        {armed
          ? <button onClick={() => { setArmModal('disarm'); setArmPhrase(''); setArmMsg('') }} style={btn('#b71c1c')}>● DISARM</button>
          : <button onClick={() => { setArmModal('arm'); setArmPhrase(''); setArmMsg('') }} style={btn('#1b5e20')}>○ ARM…</button>}
        <button onClick={() => refetch()} style={btn('#333')}>refresh</button>
      </div>

      {/* SCHWAB TOKEN HEALTH — re-auth needed banner (shown up front; every live submit would be rejected) */}
      {needsReauth && <div style={{ marginTop: 10, padding: 10, background: '#ef535022', border: '1px solid #ef5350', borderRadius: 6 }}>
        <div style={{ fontSize: 11, fontWeight: 800, color: '#ef5350' }}>⚠ Schwab re-auth needed — orders will be rejected</div>
        <div style={{ fontSize: 9.5, color: T.text, marginTop: 4, lineHeight: 1.45 }}>{tokenHealth?.message || 'Schwab login expired/revoked.'} The refresh token must be renewed by a manual browser login before any live order can submit. Run:</div>
        <div style={{ marginTop: 5, padding: '5px 8px', borderRadius: 4, background: '#0d0d0d', color: '#e0e0e0', fontSize: 10.5, ...({ fontFamily: 'monospace' } as any) }}>{tokenHealth?.reauth_command || 'python3 scripts/schwab_token_manager.py reauth-url schwab_taxable'}</div>
      </div>}
      {s.pilot_armed_until && s.pilot_session_active && (
        <div style={{ fontSize: 9, color: '#66bb6a', marginTop: 4 }}>session armed until {new Date(s.pilot_armed_until).toLocaleTimeString()} · auto-expires · any restart disarms</div>
      )}
      {armModal && (
        <div onClick={() => setArmModal(null)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.7)', zIndex: 70, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div onClick={e => e.stopPropagation()} style={{ background: T.card, border: `1px solid ${armModal === 'arm' ? '#1b5e20' : '#b71c1c'}`, borderRadius: 8, padding: 18, width: 'min(460px,94vw)' }}>
            <div style={{ fontSize: 13, fontWeight: 800, color: armModal === 'arm' ? '#81c784' : '#ef5350' }}>
              {armModal === 'arm' ? 'ARM the Stage 2b pilot' : 'DISARM the pilot'}</div>
            <div style={{ fontSize: 10, color: T.dim, margin: '6px 0 10px', lineHeight: 1.5 }}>
              {armModal === 'arm'
                ? 'Opens an auto-expiring armed session (no shell/restart). Per-order Telegram 2FA still gates every submit — this alone places nothing. Type the exact phrase to confirm:'
                : 'Expires the session and clears all locks. Type the exact phrase to confirm:'}</div>
            <div style={{ fontSize: 11, ...mono, color: T.text, padding: '5px 8px', background: '#0d1117', borderRadius: 4, marginBottom: 8 }}>
              {armModal === 'arm' ? (s.arm_phrase ?? '—') : (s.disarm_phrase ?? 'DISARM SCHWAB PILOT')}</div>
            <input autoFocus value={armPhrase} onChange={e => setArmPhrase(e.target.value)} placeholder="type the phrase exactly"
              style={{ ...inp, width: '100%', fontSize: 12, padding: '7px 9px' }} />
            {armMsg && <div style={{ fontSize: 10, color: armMsg.startsWith('✓') ? '#66bb6a' : '#ef5350', marginTop: 7 }}>{armMsg}</div>}
            <div style={{ display: 'flex', gap: 8, marginTop: 12, justifyContent: 'flex-end' }}>
              <button onClick={() => setArmModal(null)} style={btn('#333')}>cancel</button>
              <button disabled={busy} onClick={async () => {
                const want = armModal === 'arm' ? s.arm_phrase : (s.disarm_phrase ?? 'DISARM SCHWAB PILOT')
                if (armPhrase !== want) { setArmMsg('phrase does not match exactly'); return }
                const r = await post(`/api/v2/broker-orders/pilot/${armModal}`, { confirm: armPhrase })
                if (r?.ok) { setArmMsg(`✓ ${armModal}ed`); refetch(); setTimeout(() => setArmModal(null), 800) }
                else setArmMsg(r?.error ?? `${armModal} failed`)
              }} style={btn(armModal === 'arm' ? '#1b5e20' : '#b71c1c')}>
                {armModal === 'arm' ? 'ARM' : 'DISARM'}</button>
            </div>
          </div>
        </div>
      )}
      <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 7 }}>
        {lock('armed key', !!s.env_BROKER_LIVE_ENABLED || !!s.pilot_session_active, 'auto-expiring armed session (ARM button) OR shell env flag — the physical key')}
        {lock('db control', !!s.db_control_broker_live_enabled, "system_controls['broker_live_enabled']")}
        {lock('standing approval', (s.standing_approvals_active ?? 0) > 0, 'broker_live_approvals row (schwab_pilot_arm.py --arm)')}
        {lock('write flag (taxable)', !!s.api_write_enabled?.schwab_taxable, 'broker_accounts.api_write_enabled')}
        {lock(`canary day ${s.canary_session_date}`, !!s.canary_session_is_today, 'committed CANARY_SESSION_DATE must be today (auto-expires)')}
        <span style={{ fontSize: 9, color: T.dim }}>allowlist: {(s.canary_allowlist ?? []).join(', ') || '—'} ·
          ≤${s.canary_envelope?.max_price} · ≤{s.canary_envelope?.max_qty} sh · ≤${s.canary_envelope?.max_notional}</span>
      </div>
      <div style={{ fontSize: 9, color: T.dim, marginTop: 5 }}>{s.note}</div>

      {/* canary 5-ticket battery presets — all single-leg, all via this console */}
      <div style={{ marginTop: 10, paddingTop: 8, borderTop: `1px solid ${T.border}` }}>
        <div style={{ fontSize: 10, fontWeight: 800, color: T.text, marginBottom: 5 }}>Quick test <span style={{ fontWeight: 400, color: T.dim }}>· one-tap $0 place→cancel preset · or use the form below for any allowlisted order</span></div>
        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
          {CANARY_BATTERY.map((b) => (
            <button key={b.n} onClick={async () => {
              // Select the step AND auto-run preflight, so the ✓-passed box (with the approval field
              // + EXECUTE button) appears in ONE click. Previously you had to manually click the
              // greyed-out "Run preflight" — if the form wasn't populated it silently no-op'd and the
              // EXECUTE button never rendered. (operator UX 2026-06-15)
              setStep(b); setSymbol(b.symbol); setQty(String(b.qty)); setPf(null); setExecMsg('')
              const preflight = async (p: string) => {
                const body: any = { symbol: b.symbol, qty: b.qty, account_key: 'schwab_taxable' }
                if (b.shape) { body.shape = b.shape; body[b.pkey] = p } else { body.limit_price = p }
                if (p) setPf(await post('/api/v2/broker-orders/pilot/preflight', body))
              }
              if (b.live) {
                setParam('')
                try {
                  const j = await fetch(`/api/v2/schwab/quotes?symbols=${b.symbol}`).then(r => r.json())
                  const q = ((j?.data ?? j)?.quotes ?? {})[b.symbol]
                  const px = b.live === 'ask' ? q?.ask : q?.bid
                  if (px != null) { setParam(String(px)); await preflight(String(px)) }
                } catch { /* leave param empty; operator can fill + click Run preflight */ }
              } else { setParam(b.pdef ?? ''); await preflight(b.pdef ?? '') }
            }} style={{
              ...btn(step?.n === b.n ? '#1565c0' : '#222', step?.n === b.n ? '#fff' : '#90caf9'),
              fontSize: 9.5, padding: '5px 9px' }}>▸ {b.n} · {b.title}</button>
          ))}
        </div>
        {step && (
          <div style={{ marginTop: 7, padding: 9, borderRadius: 5, background: 'rgba(21,101,192,.10)', border: '1px solid #1565c044' }}>
            <div style={{ fontSize: 10, fontWeight: 800, color: '#90caf9' }}>{step.n} — {step.title} · loaded below ▾{step.live ? ` (${step.plabel} pulled live)` : ''}</div>
            <div style={{ fontSize: 10, ...mono, color: T.text, margin: '4px 0' }}>{step.spec}</div>
            <div style={{ fontSize: 9, color: '#cfcfcf', lineHeight: 1.45 }}>{step.note}</div>
          </div>
        )}
      </div>

      {/* preflight form — the param field adapts to the selected shape (limit $ / stop $ / trail %) */}
      <div style={{ display: 'flex', gap: 6, marginTop: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <input value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())} placeholder="symbol (allowlist)" style={{ ...inp, width: 110 }} />
        <input value={qty} onChange={e => setQty(e.target.value.replace(/\D/g, ''))} placeholder="qty" style={{ ...inp, width: 55 }} />
        <label style={{ fontSize: 9, color: T.dim, display: 'flex', flexDirection: 'column', gap: 2 }}>{step?.plabel ?? 'limit $'}
          <input value={param} onChange={e => setParam(e.target.value)} placeholder={step?.plabel ?? 'limit $'} style={{ ...inp, width: 80 }} /></label>
        <button disabled={busy || !symbol || !qty || !param}
          onClick={async () => {
            const body: any = { symbol, qty: Number(qty), account_key: 'schwab_taxable' }
            if (step?.shape) { body.shape = step.shape; body[step.pkey] = param }
            else { body.limit_price = param }
            setPf(await post('/api/v2/broker-orders/pilot/preflight', body)); setExecMsg('')
          }}
          style={btn('#1565c0')}>Run preflight</button>
        <span style={{ fontSize: 9, color: T.dim }}>preflight = envelope + canary gate + token health + live quote; saves the draft for 2FA</span>
      </div>
      {pf && !pf.ok && <div style={{ fontSize: 10, color: '#ef5350', marginTop: 7, fontWeight: 700 }}>⛔ {pf.reason ?? pf.error}</div>}
      {pf && pf.ok && (
        <div style={{ marginTop: 8, padding: 8, background: '#101010', border: `1px solid ${T.border}`, borderRadius: 4 }}>
          <div style={{ fontSize: 10, fontWeight: 800, color: '#66bb6a' }}>✓ preflight passed — {pf.operator_phrase}</div>
          <div style={{ fontSize: 9, color: T.dim, marginTop: 3, ...mono }}>
            quote: bid {pf.checks?.live_quote?.bid} / ask {pf.checks?.live_quote?.ask} · spread {pf.checks?.live_quote?.spread_pct}%</div>
          <pre style={{ fontSize: 9, color: T.dim, margin: '6px 0 0', maxHeight: 120, overflow: 'auto' }}>{JSON.stringify(pf.order_spec)}</pre>
          {/* operator directive 2026-06-15: type the ticker (= the fat-finger confirm) + SUBMIT and the
              order goes. One click chains request-approval → web-approve(ticker) → execute. The server
              STILL enforces the full canary envelope + allowlist + armed session + 5-order cap regardless. */}
          <div style={{ marginTop: 10, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <input autoFocus value={confirmTicker} onChange={e => setConfirmTicker(e.target.value.toUpperCase())}
              placeholder={`type ${symbol} to submit`}
              style={{ ...inp, width: 150, fontSize: 13, padding: '8px 10px',
                borderColor: confirmTicker === symbol ? '#66bb6a' : T.border }} />
            <button disabled={busy || !armed || confirmTicker !== symbol || needsReauth}
              title={needsReauth ? 'Schwab re-auth required before placing a live order' : undefined}
              onClick={async () => {
                setBusy(true); setExecMsg('submitting…')
                try {
                  let ra = await post('/api/v2/broker-orders/request-approval', { intent_id: pf.intent_id })
                  // Auto-clear a STALE slot-holder: an abandoned earlier intent holding the "one order at a
                  // time" approval slot blocks every fresh submit. Reject the stale holder(s) — which only
                  // frees the slot (never approves/executes) — and retry once. (operator 2026-06-15)
                  if (ra && ra.ok === false && Array.isArray(ra.holder_intent_ids) && ra.holder_intent_ids.length) {
                    setExecMsg('clearing a stale approval slot…')
                    for (const hid of ra.holder_intent_ids) {
                      if (hid && hid !== pf.intent_id) await post('/api/v2/broker-orders/reject', { intent_id: hid })
                    }
                    ra = await post('/api/v2/broker-orders/request-approval', { intent_id: pf.intent_id })
                  }
                  if (ra && ra.ok === false) { setExecMsg(`⛔ approval: ${ra.reason ?? ra.error ?? 'request failed'}`); return }
                  const ap = await post('/api/v2/broker-orders/approve', { intent_id: pf.intent_id, channel: 'web', code: confirmTicker })
                  if (!ap?.ok && !ap?.fully_approved) { setExecMsg(`approve: ${ap?.reason ?? ap?.error ?? 'failed'}`); return }
                  const r = await post('/api/v2/broker-orders/pilot/execute', { intent_id: pf.intent_id })
                  setExecMsg(r?.ok ? `✅ SUBMITTED — ${JSON.stringify(r).slice(0, 200)}` : `⛔ ${r?.reason ?? r?.error ?? JSON.stringify(r).slice(0,180)}`)
                  setConfirmTicker(''); refetch()
                } finally { setBusy(false) }
              }}
              style={{ ...btn((armed && confirmTicker === symbol && !needsReauth) ? T.buy : '#222', (armed && confirmTicker === symbol && !needsReauth) ? '#fff' : '#555'), padding: '8px 18px', fontWeight: 800 }}>
              {busy ? 'SUBMITTING…' : needsReauth ? 'RE-AUTH NEEDED' : 'SUBMIT ORDER'}</button>
            <span style={{ fontSize: 9, color: T.dim }}>type the ticker → SUBMIT = sends to Schwab (server still enforces the canary envelope + caps)</span>
          </div>
          {execMsg && <div style={{ fontSize: 10, color: execMsg.startsWith('✅') ? '#66bb6a' : execMsg.startsWith('⛔') ? '#ef5350' : T.text, marginTop: 7, ...mono }}>{execMsg}</div>}
        </div>
      )}

      {/* pilot orders + cancel */}
      {(s.pilot_orders ?? []).length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: T.text, marginBottom: 4 }}>Pilot orders</div>
          {(s.pilot_orders ?? []).map((o: any) => (
            <div key={o.id} style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 9.5, padding: '4px 0', borderTop: `1px solid ${T.border}` }}>
              <span style={{ ...mono, fontWeight: 800, color: T.text }}>#{o.id} {o.side} {o.qty} {o.symbol} @{o.limit_price}</span>
              <span style={{ color: o.status?.startsWith('cancel') ? T.amber : o.status === 'filled' ? '#66bb6a' : ['submitted', 'working', 'accepted', 'queued'].includes(String(o.status || '').toLowerCase()) ? '#60a5fa' : T.dim }}
                title={o.live_status ? 'broker-confirmed live status' : 'submit-time status (not yet reconciled)'}>{o.status}{o.live_status ? ' ✓' : ''}</span>
              {o.broker_order_id && <span style={{ color: T.dim, ...mono }}>id {o.broker_order_id}</span>}
              <span style={{ color: T.dim }}>{String(o.created_at ?? '').slice(0, 16)}</span>
              <span style={{ flex: 1 }} />
              {/* Cancel from the Command Center: show for any CANCELLABLE (non-terminal) status, and
                  CONFIRM first (operator 2026-06-15). Hits Schwab's live cancel via pilot/cancel. */}
              {o.broker_order_id && !['canceled', 'cancelled', 'filled', 'rejected', 'expired', 'replaced'].includes(String(o.status || '').toLowerCase()) && (
                <button disabled={busy} onClick={async () => {
                  if (!confirm(`Cancel this LIVE Schwab order?\n\n${o.side} ${o.qty} ${o.symbol} @ ${o.limit_price}\nbroker id ${o.broker_order_id}\n\nThis sends a cancel to Schwab.`)) return
                  setExecMsg('cancelling…')
                  const r = await post('/api/v2/broker-orders/pilot/cancel', { broker_order_id: o.broker_order_id })
                  setExecMsg(r?.ok ? `✅ cancel sent — ${JSON.stringify(r).slice(0, 160)}` : `⛔ ${r?.reason ?? r?.error ?? JSON.stringify(r).slice(0, 160)}`)
                  refetch()
                }}
                  style={btn('#b71c1c')}>cancel order</button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── ACTIVE TRADER panel (ToS desktop layout; builds DRAFTS only) ────────────────────────────────
const SCHWAB_ACCOUNTS = ['schwab_taxable', 'schwab_rollover_ira', 'schwab_roth_ira']

function ActiveTraderPanel({ seed, onPreviewed }: { seed: any | null; onPreviewed: () => void }) {
  const [symbol, setSymbol] = useState('')
  const [account, setAccount] = useState('schwab_taxable')   // operator 2026-06-12: account selection
  const [qty, setQty] = useState(2)
  const [strategy, setStrategy] = useState<keyof typeof STRATEGY_TIP>('BRACKET')
  const [method, setMethod] = useState('LIMIT')
  const [limit, setLimit] = useState('')
  const [entryStop, setEntryStop] = useState('')
  const [stopLoss, setStopLoss] = useState('')
  const [target, setTarget] = useState('')
  const [target2, setTarget2] = useState('')
  const [t1pct, setT1pct] = useState('50')
  const [trailOff, setTrailOff] = useState('3')
  const [trailType, setTrailType] = useState('PERCENT')
  const [trailBasis, setTrailBasis] = useState('LAST')
  const [lad1, setLad1] = useState(''); const [lad2, setLad2] = useState('')
  const [tif, setTif] = useState('DAY')
  const [session, setSession] = useState('NORMAL')
  const [quote, setQuote] = useState<any>(null)
  const [result, setResult] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [sug, setSug] = useState<any>(null)
  const [sugBusy, setSugBusy] = useState(false)
  const [ai, setAi] = useState<{ q: string; a: string; provider: string } | null>(null)
  const [aiQ, setAiQ] = useState('')
  const [aiBusy, setAiBusy] = useState(false)

  // C2 monitor hands a live order here as a DRAFT seed
  useEffect(() => {
    if (!seed) return
    setSymbol(seed.instrument?.symbol ?? '')
    setQty(seed.quantity?.qty ?? 2)
    setMethod(seed.entry?.method ?? 'LIMIT')
    setLimit(seed.entry?.limit_price ? String(seed.entry.limit_price) : '')
    setEntryStop(seed.entry?.stop_price ? String(seed.entry.stop_price) : '')
    setStrategy('SINGLE')
    setTif(seed.tif ?? 'DAY')
    setSession(seed.session ?? 'NORMAL')
  }, [seed])

  const fetchQuote = async (sym: string) => {
    if (!sym) return
    try {
      const r = await fetch(`/api/v2/schwab/quotes?symbols=${encodeURIComponent(sym)}`)
      const j = await r.json()
      const d = j?.data ?? j
      // response shape: { data: { quotes: { SYM: {bid,ask,last,...} } } } — read the nested map
      const q = (d?.quotes ?? d)?.[sym.toUpperCase()] ?? null
      setQuote(q ? { ...q, fetched_at: Date.now() } : null)
    } catch { setQuote(null) }
  }
  useEffect(() => {
    const t = setTimeout(() => fetchQuote(symbol.trim().toUpperCase()), 600)
    // live numbers (operator 2026-06-12): while a symbol is set, refresh the quote every 10s
    const iv = symbol.trim() ? setInterval(() => fetchQuote(symbol.trim().toUpperCase()), 10_000) : undefined
    return () => { clearTimeout(t); if (iv) clearInterval(iv) }
  }, [symbol])

  // Read-only technical level suggester (advisory): fills entry/stop/target from ATR + structure.
  const suggestLevels = async () => {
    const sym = symbol.trim().toUpperCase()
    if (!sym) return
    setSugBusy(true); setSug(null)
    try {
      const r = await fetch(`/api/v2/broker-orders/suggest-levels?symbol=${encodeURIComponent(sym)}`)
      const j = await r.json(); const d = j?.data ?? j
      setSug(d)
      if (d && !d.error) {
        if (d.limit != null) setLimit(String(d.limit))
        if (d.stop != null) setStopLoss(String(d.stop))
        if (d.target != null) setTarget(String(d.target))
      }
    } catch (e: any) { setSug({ error: e.message }) }
    setSugBusy(false)
  }

  const buildIntent = (direction: 'LONG' | 'SHORT') => {
    const exits: any = { stop: null, targets: [] as any[], oco: true, on_stop_place_failure: 'CLOSE_POSITION' }
    if (strategy === 'BRACKET') {
      exits.stop = stopLoss ? { price: Number(stopLoss), trail: null } : null
      exits.targets = target ? [{ price: Number(target), qty_pct: 100 }] : []
    } else if (strategy === 'MULTI_TARGET') {
      exits.stop = stopLoss ? { price: Number(stopLoss), trail: null } : null
      const p1 = Number(t1pct) || 50
      exits.targets = [
        ...(target ? [{ price: Number(target), qty_pct: p1 }] : []),
        ...(target2 ? [{ price: Number(target2), qty_pct: 100 - p1 }] : []),
      ]
    } else if (strategy === 'TRAILING') {
      exits.stop = { price: null, trail: { basis: trailBasis, type: trailType, offset: Number(trailOff) || 0 } }
      exits.targets = target ? [{ price: Number(target), qty_pct: 100 }] : []
    } else if (strategy === 'OCO') {
      exits.stop = stopLoss ? { price: Number(stopLoss), trail: null } : null
      exits.targets = target ? [{ price: Number(target), qty_pct: 100 }] : []
    }
    const ladder = strategy === 'LADDER' && lad1 && lad2
      ? { legs: [{ entry_price: Number(lad1), qty_pct: 50 }, { entry_price: Number(lad2), qty_pct: 50 }], cancel_policy: 'ALL_ON_STOP' }
      : null
    return {
      instrument: { symbol: symbol.trim().toUpperCase(), asset_type: 'EQUITY', option_legs: [] },
      direction,
      entry: { method, limit_price: limit ? Number(limit) : null, stop_price: entryStop ? Number(entryStop) : null,
               entry_range: null, price_link: null },
      quantity: { qty: Number(qty) || null, notional: null, contracts: null },
      broker: 'schwab', account_key: account, tif, session, exit_policy: exits, ladder,
      risk: { sizing_basis: 'shares' },
      meta: { thesis: `Active Trader panel draft (${strategy})`, created_by: 'operator' },
      state: 'DRAFT',
    }
  }

  // EVERY action = build draft + preview/translate. The guard records a BLOCK for execution. Nothing sends.
  const act = async (direction: 'LONG' | 'SHORT', priceSource?: 'bid' | 'ask' | 'mid') => {
    if (!symbol.trim()) { setResult({ error: 'symbol required' }); return }
    if (priceSource && quote) {
      const px = priceSource === 'bid' ? quote.bid : priceSource === 'ask' ? quote.ask
        : (quote.bid && quote.ask) ? Number(((quote.bid + quote.ask) / 2).toFixed(2)) : quote.last
      if (px) setLimit(String(px))
    }
    setBusy(true)
    const body = buildIntent(direction)
    if (priceSource && quote) {
      const px = priceSource === 'bid' ? quote.bid : priceSource === 'ask' ? quote.ask
        : (quote.bid && quote.ask) ? Number(((quote.bid + quote.ask) / 2).toFixed(2)) : quote.last
      if (px) body.entry.limit_price = Number(px)
    }
    const r = await fetch('/api/v2/broker-orders/preview', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    const j = await r.json()
    setResult(j?.data ?? j)
    setBusy(false)
    onPreviewed()
  }

  const explain = async (escalate: boolean) => {
    setAiBusy(true)
    try {
      const r = await fetch('/api/v2/broker-orders/explain', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: `${strategy} order structure / ${method} entry`, question: aiQ,
          intent: buildIntent('LONG'), escalate }) })
      const j = await r.json(); const d = j?.data ?? j
      setAi({ q: aiQ || strategy, a: d.answer, provider: d.provider })
    } catch (e: any) { setAi({ q: aiQ, a: `error: ${e.message}`, provider: 'none' }) }
    setAiBusy(false)
  }

  const F = ({ label, tip, children }: any) => (
    <label title={tip} style={{ display: 'flex', flexDirection: 'column', gap: 2, cursor: 'help' }}>
      <span style={{ ...lbl, borderBottom: `1px dotted ${T.dim}55`, width: 'fit-content' }}>{label}</span>
      {children}
    </label>)

  const exitFields = (
    <>
      {(strategy === 'BRACKET' || strategy === 'MULTI_TARGET' || strategy === 'OCO') && (
        <F label="stop-loss $" tip={FIELD_TIP.stopLoss}>
          <input value={stopLoss} onChange={e => setStopLoss(e.target.value)} style={inp} /></F>)}
      {strategy !== 'SINGLE' && strategy !== 'LADDER' && (
        <F label={strategy === 'MULTI_TARGET' ? 'target 1 $' : 'target $'} tip={FIELD_TIP.target}>
          <input value={target} onChange={e => setTarget(e.target.value)} style={inp} /></F>)}
      {strategy === 'MULTI_TARGET' && (<>
        <F label="t1 qty %" tip="Share of the position the first target sells (rest goes to target 2). Must sum to 100.">
          <input value={t1pct} onChange={e => setT1pct(e.target.value)} style={{ ...inp, width: 52 }} /></F>
        <F label="target 2 $" tip={FIELD_TIP.target}>
          <input value={target2} onChange={e => setTarget2(e.target.value)} style={inp} /></F>
      </>)}
      {strategy === 'TRAILING' && (<>
        <F label="trail offset" tip={FIELD_TIP.trail}>
          <input value={trailOff} onChange={e => setTrailOff(e.target.value)} style={{ ...inp, width: 56 }} /></F>
        <F label="trail type" tip={FIELD_TIP.trail}>
          <select value={trailType} onChange={e => setTrailType(e.target.value)} style={{ ...inp, width: 92 }}>
            <option>PERCENT</option><option>VALUE</option><option>TICK</option></select></F>
        <F label="trail basis" tip="Which price the trail follows: LAST trade, BID, ASK, or MARK.">
          <select value={trailBasis} onChange={e => setTrailBasis(e.target.value)} style={{ ...inp, width: 78 }}>
            <option>LAST</option><option>BID</option><option>ASK</option><option>MARK</option></select></F>
      </>)}
      {strategy === 'LADDER' && (<>
        <F label="leg 1 $ (50%)" tip={STRATEGY_TIP.LADDER}>
          <input value={lad1} onChange={e => setLad1(e.target.value)} style={inp} /></F>
        <F label="leg 2 $ (50%)" tip={STRATEGY_TIP.LADDER}>
          <input value={lad2} onChange={e => setLad2(e.target.value)} style={inp} /></F>
      </>)}
    </>
  )

  return (
    <div style={{ background: T.bg, border: `1px solid ${T.border}`, borderRadius: 6, padding: 0, marginBottom: 14, overflow: 'hidden' }}>
      <div style={{ padding: '6px 12px', background: T.card, borderBottom: `1px solid ${T.border}`, display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ fontSize: 11.5, fontWeight: 800, color: T.text, letterSpacing: 0.5 }}>ACTIVE TRADER · DRAFT BUILDER</span>
        <span style={{ fontSize: 9, color: T.amber, fontWeight: 700 }}>DORMANT — every button builds a DRAFT + preview; the guard BLOCKS execution (correct). No auto-send exists.</span>
      </div>

      <div style={{ padding: 12 }}>
        {/* symbol + quote strip */}
        <div style={{ display: 'flex', gap: 14, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <F label="symbol" tip="US equity only this program. The canary gate allowlist is committed in code at session time.">
            <input value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())}
              style={{ ...inp, width: 92, fontSize: 14, fontWeight: 700 }} placeholder="—" /></F>
          <F label="account" tip="Which Schwab account this draft (and your manual ToS placement) is for.">
            <select value={account} onChange={e => setAccount(e.target.value)} style={{ ...inp, width: 130 }}>
              {SCHWAB_ACCOUNTS.map(a => <option key={a} value={a}>{a.replace('schwab_', '').replace(/_/g, ' ').toUpperCase()}</option>)}
            </select></F>
          <div style={{ display: 'flex', gap: 12, padding: '0 10px 4px', alignItems: 'flex-end' }}>
            {(['bid', 'last', 'ask'] as const).map(k => (
              <div key={k} style={{ textAlign: 'center' }}>
                <div style={lbl}>{k}</div>
                <div style={{ fontSize: 15, fontWeight: 800, color: k === 'bid' ? '#ef5350' : k === 'ask' ? '#66bb6a' : T.text, ...mono }}>
                  {quote?.[k] != null ? Number(quote[k]).toFixed(2) : '—'}
                </div>
              </div>
            ))}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              <button onClick={() => fetchQuote(symbol.trim().toUpperCase())} title="quotes auto-refresh every 10s while a symbol is typed; this forces it now"
                style={{ ...btn('#1b1b1b', '#90caf9'), padding: '4px 9px' }}>↻ quote</button>
              {quote?.fetched_at && <span style={{ fontSize: 8, color: T.dim }}>@ {new Date(quote.fetched_at).toLocaleTimeString()}</span>}
            </div>
            <button onClick={suggestLevels} disabled={!symbol.trim() || sugBusy}
              title="Read-only technical suggestion: ATR-buffered stop below structure, limit near support/last, target vs recent range + analyst mean. Advisory — fills the fields, never sends."
              style={{ ...btn('#3b245e', '#c4b5fd'), padding: '4px 10px' }}>{sugBusy ? '…' : '💡 suggest levels'}</button>
          </div>
          {sug && <div style={{ fontSize: 9, color: sug.error ? '#ef5350' : T.dim, padding: '0 10px 4px' }}>
            {sug.error ? `suggest failed: ${sug.error}` : `💡 ${sug.rationale} · entry ${sug.limit} · stop ${sug.stop} (${sug.stop_pct}%) · target ${sug.target} · R:R ${sug.rr}`}</div>}
          {/* qty stepper — canary-scaled presets ONLY */}
          <F label="qty (shares)" tip={FIELD_TIP.qty}>
            <span style={{ display: 'flex', gap: 3, alignItems: 'center' }}>
              <button onClick={() => setQty(q => Math.max(1, q - 1))} style={btn('#222')}>−</button>
              <input value={qty} onChange={e => setQty(Math.max(0, Number(e.target.value) || 0))} style={{ ...inp, width: 48, textAlign: 'center' }} />
              <button onClick={() => setQty(q => q + 1)} style={btn('#222')}>+</button>
              {[2, 5, 10].map(p => (
                <button key={p} onClick={() => setQty(p)}
                  style={{ ...btn(qty === p ? '#1565c0' : '#1b1b1b'), padding: '4px 9px' }}>{p}</button>
              ))}
            </span></F>
        </div>

        {/* order structure row */}
        <div style={{ display: 'flex', gap: 10, marginTop: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <F label="structure" tip={STRATEGY_TIP[strategy]}>
            <select value={strategy} onChange={e => setStrategy(e.target.value as any)} style={{ ...inp, width: 128 }}>
              <option value="SINGLE">SINGLE</option>
              <option value="BRACKET">BRACKET (OTOCO)</option>
              <option value="MULTI_TARGET">MULTI-TARGET OCO</option>
              <option value="TRAILING">TRAILING STOP</option>
              <option value="OCO">OCO EXITS</option>
              <option value="LADDER">LADDER</option>
            </select></F>
          <F label="entry type" tip={FIELD_TIP.limit}>
            <select value={method} onChange={e => setMethod(e.target.value)} style={{ ...inp, width: 100 }}>
              <option>LIMIT</option><option>MARKET</option><option>STOP</option><option>STOP_LIMIT</option></select></F>
          {(method === 'LIMIT' || method === 'STOP_LIMIT') && strategy !== 'LADDER' && (
            <F label="limit $" tip={FIELD_TIP.limit}>
              <input value={limit} onChange={e => setLimit(e.target.value)} style={inp} /></F>)}
          {(method === 'STOP' || method === 'STOP_LIMIT') && (
            <F label="entry stop $" tip={FIELD_TIP.stopPrice}>
              <input value={entryStop} onChange={e => setEntryStop(e.target.value)} style={inp} /></F>)}
          {exitFields}
          <F label="TIF" tip={FIELD_TIP.tif}>
            <select value={tif} onChange={e => setTif(e.target.value)} style={{ ...inp, width: 64 }}>
              <option>DAY</option><option>GTC</option><option>FOK</option><option>IOC</option></select></F>
          <F label="session" tip={FIELD_TIP.session}>
            <select value={session} onChange={e => setSession(e.target.value)} style={{ ...inp, width: 92 }}>
              <option>NORMAL</option><option>AM</option><option>PM</option><option>SEAMLESS</option></select></F>
        </div>

        {/* inline explainer for the selected structure */}
        <div style={{ fontSize: 9, color: '#9e9e9e', marginTop: 8, lineHeight: 1.5, maxWidth: 860 }}>
          ⓘ <b style={{ color: '#bdbdbd' }}>{strategy.replace('_', '-')}:</b> {STRATEGY_TIP[strategy]}
        </div>

        {/* BUY / SELL action rows — ToS layout; every click = draft + preview + guard BLOCK */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 12, maxWidth: 760 }}>
          <div style={{ border: `1px solid ${T.buy}55`, borderRadius: 4, padding: 8, background: T.buy + '0d' }}>
            <div style={{ ...lbl, color: '#81c784', marginBottom: 5 }}>buy {qty} {symbol || '—'} → builds draft, never sends</div>
            <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
              <button disabled={busy} onClick={() => act('LONG', 'bid')} style={{ ...btn(T.buy), padding: '7px 12px' }}>BUY @ BID</button>
              <button disabled={busy} onClick={() => act('LONG', 'mid')} style={{ ...btn(T.buy), padding: '7px 12px' }}>BUY @ MID</button>
              <button disabled={busy} onClick={() => act('LONG', 'ask')} style={{ ...btn(T.buyHi), padding: '7px 12px' }}>BUY @ ASK</button>
              <button disabled={busy} onClick={() => act('LONG')} style={{ ...btn('#1b1b1b', '#81c784'), padding: '7px 12px' }}>BUY (fields)</button>
            </div>
          </div>
          <div style={{ border: `1px solid ${T.sell}55`, borderRadius: 4, padding: 8, background: T.sell + '0d' }}>
            <div style={{ ...lbl, color: '#e57373', marginBottom: 5 }}>sell short {qty} {symbol || '—'} → draft only (gate is long-only)</div>
            <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
              <button disabled={busy} onClick={() => act('SHORT', 'ask')} style={{ ...btn(T.sell), padding: '7px 12px' }}>SELL @ ASK</button>
              <button disabled={busy} onClick={() => act('SHORT', 'mid')} style={{ ...btn(T.sell), padding: '7px 12px' }}>SELL @ MID</button>
              <button disabled={busy} onClick={() => act('SHORT', 'bid')} style={{ ...btn(T.sellHi), padding: '7px 12px' }}>SELL @ BID</button>
              <button disabled={busy} onClick={() => act('SHORT')} style={{ ...btn('#1b1b1b', '#e57373'), padding: '7px 12px' }}>SELL (fields)</button>
            </div>
          </div>
        </div>

        {/* preview result — the proof the click went draft→preview→guard BLOCK */}
        {result && (
          <div style={{ marginTop: 10, padding: 8, background: '#101010', border: `1px solid ${T.border}`, borderRadius: 4 }}>
            {result.error && <div style={{ fontSize: 10, color: '#ef5350' }}>❌ {result.error}</div>}
            {result.validation?.errors?.length > 0 ? (
              <div style={{ fontSize: 10, color: '#ef5350' }}>❌ Not valid: {result.validation.errors.join(' · ')}</div>
            ) : result.translation_preview ? (
              <div style={{ fontSize: 10, color: '#66bb6a' }}>
                ✅ Draft saved + translates cleanly — Schwab WOULD receive {(result.translation_preview?.orders ?? []).length} order(s)
                {result.translation_preview?.orders?.[0]?.orderStrategyType === 'TRIGGER' ? ' (entry triggers exits)' : ''}.
              </div>
            ) : null}
            {result.execution && (
              <div style={{ fontSize: 10, color: '#ef5350', marginTop: 3, fontWeight: 700 }}>
                ⛔ Guard: {result.execution.mode} — {String(result.execution.reason).slice(0, 110)} (BLOCKED = correct this phase)
              </div>
            )}
            {result.validation?.warnings?.length > 0 &&
              <div style={{ fontSize: 9, color: T.amber, marginTop: 3 }}>⚠ {result.validation.warnings.join(' · ')}</div>}
            {result.translation_preview?.unverified?.length > 0 &&
              <div style={{ fontSize: 9, color: T.amber, marginTop: 3 }}>UNVERIFIED vs Schwab runtime: {result.translation_preview.unverified.join('; ')}</div>}
          </div>
        )}

        {/* AI help — advisory only; local first, Claude on explicit request */}
        <div style={{ marginTop: 10, padding: 8, background: '#101010', border: `1px dashed ${T.border}`, borderRadius: 4 }}>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 9.5, fontWeight: 700, color: '#9e9e9e' }}>🧠 AI help (advisory only — explains mechanics, never picks trades, cannot submit/approve)</span>
            <input value={aiQ} onChange={e => setAiQ(e.target.value)} placeholder={`ask about ${strategy}…`}
              style={{ ...inp, width: 260 }} />
            <button disabled={aiBusy} onClick={() => explain(false)} style={btn('#1b1b1b', '#90caf9')}>
              {aiBusy ? '…' : 'Explain (local model)'}</button>
            <button disabled={aiBusy} onClick={() => explain(true)} style={btn('#1b1b1b', '#ce93d8')}>
              Ask Claude (explicit escalation)</button>
          </div>
          {ai && (
            <div style={{ fontSize: 10, color: '#bdbdbd', marginTop: 6, lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
              <span style={{ color: T.dim, fontSize: 8.5 }}>[{ai.provider}]</span> {ai.a}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Edit-before-approval modal (kept from prior phase, ToS-toned) ────────────────────────────────
function EditModal({ draft, onClose, onSaved }: { draft: any; onClose: () => void; onSaved: () => void }) {
  const it = draft.intent_json ?? {}
  const [account, setAccount] = useState(it.account_key ?? 'schwab_taxable')   // operator 2026-06-12: was hidden here
  const [qty, setQty] = useState(String(it.quantity?.qty ?? 2))
  const [method, setMethod] = useState(it.entry?.method ?? 'LIMIT')
  const [limit, setLimit] = useState(String(it.entry?.limit_price ?? ''))
  const [entryStop, setEntryStop] = useState(String(it.entry?.stop_price ?? ''))
  const [stop, setStop] = useState(String(it.exit_policy?.stop?.price ?? ''))
  const [target, setTarget] = useState(String(it.exit_policy?.targets?.[0]?.price ?? ''))
  const [trailOn, setTrailOn] = useState(!!it.exit_policy?.stop?.trail)
  const [trailOff, setTrailOff] = useState(String(it.exit_policy?.stop?.trail?.offset ?? '3'))
  const [trailType, setTrailType] = useState(it.exit_policy?.stop?.trail?.type ?? 'PERCENT')
  const [tif, setTif] = useState(it.tif ?? 'DAY')
  const [session, setSession] = useState(it.session ?? 'NORMAL')
  const [dir, setDir] = useState(it.direction ?? 'LONG')
  const [result, setResult] = useState<any>(null)
  const [busy, setBusy] = useState(false)

  const buildIntent = () => ({
    ...it,
    direction: dir, tif, session, account_key: account,
    quantity: { qty: Number(qty) || null, notional: null, contracts: null },
    entry: { ...it.entry, method, limit_price: limit ? Number(limit) : null,
             stop_price: entryStop ? Number(entryStop) : null },
    exit_policy: {
      ...it.exit_policy, oco: true,
      stop: (stop || trailOn) ? { price: stop ? Number(stop) : null,
        trail: trailOn ? { basis: it.exit_policy?.stop?.trail?.basis ?? 'LAST', type: trailType, offset: Number(trailOff) || 0 } : null } : null,
      targets: target ? [{ price: Number(target), qty_pct: 100 }] : [],
    },
    meta: { ...it.meta, thesis: (it.meta?.thesis ?? '') + ' [edited by operator]' },
    state: 'DRAFT',
  })

  const repreview = async () => {
    setBusy(true)
    const r = await fetch('/api/v2/broker-orders/preview', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(buildIntent()) })
    const j = await r.json(); setResult(j?.data ?? j); setBusy(false); onSaved()
  }

  const F = ({ label, children }: any) => (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 2, ...lbl }}>
      {label}{children}
    </label>)

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.7)', zIndex: 60, display: 'flex',
      justifyContent: 'center', alignItems: 'flex-start', padding: '5vh 2vw', overflow: 'auto' }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{ background: T.card, border: `1px solid ${T.border}`,
        borderRadius: 8, padding: 16, width: 'min(680px, 96vw)' }}>
        <div style={{ fontSize: 13, fontWeight: 800, color: T.text, marginBottom: 2 }}>
          Edit order — {it.instrument?.symbol}</div>
        <div style={{ fontSize: 9, color: T.dim, marginBottom: 10 }}>
          Step 1: adjust · Step 2: re-preview the Schwab translation · Step 3: two-channel approval
          (Telegram ✅ + web type-the-ticker). Nothing executes this phase regardless.</div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <F label="ACCOUNT (must match ToS!)"><select value={account} onChange={e => setAccount(e.target.value)}
            style={{ ...inp, width: 130, borderColor: '#ffa726' }}>
            {SCHWAB_ACCOUNTS.map(a => <option key={a} value={a}>{a.replace('schwab_', '').replace(/_/g, ' ').toUpperCase()}</option>)}
          </select></F>
          <F label="direction"><select value={dir} onChange={e => setDir(e.target.value)} style={inp}>
            <option>LONG</option><option>SHORT</option></select></F>
          <F label="shares"><input value={qty} onChange={e => setQty(e.target.value)} style={inp} /></F>
          <F label="entry"><select value={method} onChange={e => setMethod(e.target.value)} style={inp}>
            {['MARKET','LIMIT','STOP','STOP_LIMIT'].map(m => <option key={m}>{m}</option>)}</select></F>
          <F label="limit $"><input value={limit} onChange={e => setLimit(e.target.value)} style={inp} /></F>
          <F label="entry stop $"><input value={entryStop} onChange={e => setEntryStop(e.target.value)} style={inp} /></F>
          <F label="stop-loss $"><input value={stop} onChange={e => setStop(e.target.value)} style={inp} /></F>
          <F label="target $"><input value={target} onChange={e => setTarget(e.target.value)} style={inp} /></F>
          <F label="trailing stop"><span style={{ display: 'flex', gap: 4 }}>
            <input type="checkbox" checked={trailOn} onChange={e => setTrailOn(e.target.checked)} />
            <input value={trailOff} onChange={e => setTrailOff(e.target.value)} style={{ ...inp, width: 46 }} disabled={!trailOn} />
            <select value={trailType} onChange={e => setTrailType(e.target.value)} style={{ ...inp, width: 78 }} disabled={!trailOn}>
              <option>PERCENT</option><option>VALUE</option><option>TICK</option></select></span></F>
          <F label="time in force"><select value={tif} onChange={e => setTif(e.target.value)} style={inp}>
            {['DAY','GTC','FOK','IOC'].map(m => <option key={m}>{m}</option>)}</select></F>
          <F label="session"><select value={session} onChange={e => setSession(e.target.value)} style={inp}>
            {['NORMAL','AM','PM','SEAMLESS'].map(m => <option key={m}>{m}</option>)}</select></F>
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 12, alignItems: 'center' }}>
          <button onClick={repreview} disabled={busy} style={{ ...btn('#1565c0'), fontSize: 11, padding: '6px 14px' }}>
            {busy ? 'translating…' : '② Re-preview Schwab translation'}</button>
          <button onClick={async () => { await fetch('/api/v2/broker-orders/reject', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ intent_id: it.intent_id }) }); onSaved(); onClose() }}
            style={{ ...btn('#b45309'), fontSize: 11, padding: '6px 14px' }}>✖ Reject (keep record)</button>
          <button onClick={async () => { if (confirm('Delete this draft entirely? (audit events are kept)')) { await fetch('/api/v2/broker-orders/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ intent_id: it.intent_id }) }); onSaved(); onClose() } }}
            style={{ ...btn('#7f1d1d'), fontSize: 11, padding: '6px 14px' }}>🗑 Delete draft</button>
          <button onClick={onClose} style={{ ...btn('#333'), fontSize: 11, padding: '6px 14px' }}>close</button>
        </div>
        {result && (
          <div style={{ marginTop: 10 }}>
            {result.validation?.errors?.length > 0 ? (
              <div style={{ fontSize: 10, color: '#ef5350' }}>
                ❌ Not valid: {result.validation.errors.join(' · ')}</div>
            ) : (
              <div style={{ fontSize: 10, color: '#66bb6a' }}>
                ✅ Translates cleanly — Schwab would receive {(result.translation_preview?.orders ?? []).length} order(s)
                {result.translation_preview?.orders?.[0]?.orderStrategyType === 'TRIGGER' ? ' (bracket: entry triggers exits)' : ''}.
                Execution: <b>{result.execution?.mode}</b> (blocked — correct this phase).</div>
            )}
            {result.validation?.warnings?.length > 0 &&
              <div style={{ fontSize: 9, color: T.amber, marginTop: 3 }}>⚠ {result.validation.warnings.join(' · ')}</div>}
            {result.live_quote && (() => {
              const q = result.live_quote
              const ts = q.fetched_at ? new Date(q.fetched_at) : null
              const age = ts ? Math.round((Date.now() - ts.getTime()) / 1000) : null
              const ok = q.status === 'ok'
              return (
                <div style={{ marginTop: 8, padding: '7px 9px', background: '#0d1117',
                  border: `1px solid ${ok ? '#1f6f43' : '#7f1d1d'}`, borderRadius: 5 }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
                    <span style={{ fontSize: 9.5, fontWeight: 800, color: ok ? '#66bb6a' : '#ef5350' }}>
                      📡 LIVE SCHWAB QUOTE{ok ? '' : ` — ${q.status}`}</span>
                    {ok && <span style={{ ...mono, fontSize: 11, color: T.text }}>
                      bid {q.bid ?? '—'} · ask {q.ask ?? '—'} · last {q.last ?? '—'}
                      {q.spread_pct != null ? ` · spread ${q.spread_pct}%` : ''}</span>}
                    {!ok && <span style={{ fontSize: 9, color: T.dim }}>{q.detail}</span>}
                  </div>
                  {ok && q.limit_vs_last_pct != null && (
                    <div style={{ fontSize: 9, marginTop: 2,
                      color: Math.abs(q.limit_vs_last_pct) <= 2 ? '#66bb6a' : T.amber }}>
                      your limit ${limit} is {q.limit_vs_last_pct >= 0 ? '+' : ''}{q.limit_vs_last_pct}% vs last
                      {q.limit_vs_last_pct > 0 ? ' (above market — marketable buy)' : q.limit_vs_last_pct < 0 ? ' (below market — rests)' : ''}
                    </div>)}
                  <div style={{ fontSize: 8.5, color: T.dim, marginTop: 2 }}>
                    fetched {ts ? ts.toLocaleTimeString() : '—'}{age != null ? ` (${age}s ago)` : ''} · re-preview to refresh
                  </div>
                </div>
              )
            })()}
            <div style={{ marginTop: 8, padding: '7px 9px', borderRadius: 5, background: 'rgba(96,165,250,.08)', border: '1px solid rgba(96,165,250,.25)', fontSize: 9.5, color: T.dim }}>
              📋 This is a DRAFT editor — it never sends, and approving here would only block the real
              submit. To place a canary order, use the <b style={{ color: '#60a5fa' }}>top Pilot Console</b>:
              tap a <b>▸ step</b> → type the ticker → <b>SUBMIT</b> (it handles the 2FA approval itself).
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── main surface ─────────────────────────────────────────────────────────────────────────────────
export default function BrokerOrders({ draftSeed }: { draftSeed?: any | null }) {
  const { data: capsR } = useApi<any>('/api/v2/broker-orders/capabilities?broker=schwab', 120_000)
  const { data: draftsR, refetch } = useApi<any>('/api/v2/broker-orders/drafts?broker=schwab', 30_000)
  const { data: eventsR, refetch: refetchEvents } = useApi<any>('/api/v2/broker-orders/events', 30_000)
  const { data: activityR } = useApi<any>('/api/v2/broker-orders/activity', 60_000)
  const { data: reconR } = useApi<any>('/api/v2/broker-orders/shadow-recon', 60_000)
  const [open, setOpen] = useState<string | null>(null)
  const [editing, setEditing] = useState<any>(null)
  const [searchParams] = useSearchParams()
  const deepLinkRef = useRef<HTMLDivElement | null>(null)
  const caps = (capsR as any)?.data ?? capsR
  const drafts: any[] = ((draftsR as any)?.data ?? draftsR)?.drafts ?? []
  // Canary battery drafts carry a "CANARY n/5" tag in meta.thesis — surface their run order so the
  // list reads as the ordered 1→5 sequence (was unsorted, mixing the battery with ad-hoc scratch drafts).
  const canaryStep = (d: any): number => {
    const m = /CANARY\s*(\d)\s*\/\s*5/.exec(d?.intent_json?.meta?.thesis ?? '')
    return m ? Number(m[1]) : 99
  }
  const events: any[] = ((eventsR as any)?.data ?? eventsR)?.events ?? []
  const activity: any[] = ((activityR as any)?.data ?? activityR)?.activity ?? []
  const recon = (reconR as any)?.data ?? reconR

  // Telegram deep-link (?intent=<id>) → auto-open that exact order item
  const intentParam = searchParams.get('intent')
  useEffect(() => {
    if (intentParam && drafts.some(d => d.intent_id === intentParam)) {
      setOpen(intentParam)
      setTimeout(() => deepLinkRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 200)
    }
  }, [intentParam, drafts.length])

  const lastRun = recon?.runs?.[0]

  return (
    <div>
      {/* execution-disabled banner — text from backend capability truth */}
      <div style={{ padding: '10px 14px', background: 'rgba(239,83,80,.07)', border: '1px solid rgba(239,83,80,.35)', borderRadius: 6, marginBottom: 12 }}>
        <span style={{ fontSize: 11, fontWeight: 800, color: '#ef5350' }}>EXECUTION GATED — mode {caps?.execution_mode} · this panel builds DRAFTS only (never sends)</span>
        <div style={{ fontSize: 10, color: '#bdbdbd', marginTop: 3 }}>{caps?.execution_disabled_notice}</div>
        <div style={{ fontSize: 9, color: T.dim, marginTop: 3 }}>
          Environment: {caps?.environment} · Hardcoded canary gate armed (≤$4 / ≤10 sh / ≤$40, allowlist committed at session time) ·
          Protocol: docs/brokers/stage2a-canary-protocol.md
        </div>
      </div>

      <PilotConsole />

      <ActiveTraderPanel seed={draftSeed ?? null} onPreviewed={() => { refetch(); refetchEvents() }} />

      <div style={{ fontSize: 12, fontWeight: 700, color: T.text, marginBottom: 2 }}>
        Draft order intents <button onClick={() => refetch()} style={btn('#333')}>refresh</button>
      </div>
      <div style={{ fontSize: 9, color: T.dim, marginBottom: 8 }}>
        A draft = a fully-specified order the system COULD send, with its exact Schwab translation — nothing
        here ever executes this phase. Identical fixtures are grouped.
      </div>
      {(() => {
        const seen: Record<string, { d: any; n: number }> = {}
        for (const d of drafts) {
          const h = humanSummary(d.intent_json)
          const k = `${d.symbol}|${h.line}|${h.pills.join(',')}`
          if (seen[k]) seen[k].n += 1; else seen[k] = { d, n: 1 }
        }
        // deep-linked intent always shows, even if its twin grouped first
        const vals = Object.values(seen)
        if (intentParam && !vals.some(v => v.d.intent_id === intentParam)) {
          const hit = drafts.find(d => d.intent_id === intentParam)
          if (hit) vals.unshift({ d: hit, n: 1 })
        }
        // Canary battery first in run order (1→5), then ad-hoc scratch drafts.
        vals.sort((a, b) => canaryStep(a.d) - canaryStep(b.d))
        return vals.slice(0, 25)
      })().map(({ d, n }: any) => (
        <div key={d.intent_id} ref={d.intent_id === intentParam ? deepLinkRef : undefined}
          style={{ border: `1px solid ${d.intent_id === intentParam ? T.amber : T.border}`, borderRadius: 6, padding: 10, marginBottom: 8, background: T.card }}>
          {(() => { const h = humanSummary(d.intent_json); return (
          <div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              {canaryStep(d) < 99 && (
                <span style={{ fontSize: 10, fontWeight: 900, padding: '2px 8px', borderRadius: 4,
                  background: T.buyHi + '22', color: T.buyHi, border: `1px solid ${T.buyHi}66` }}
                  title="Canary battery run order — execute steps 1→5 in sequence (only step 4 fills; 1/2/3 place→cancel, 5 closes flat)">
                  RUN {canaryStep(d)}/5</span>
              )}
              <span style={{ fontSize: 12.5, fontWeight: 800, color: T.text }}>{h.line}</span>
              {/* account badge on every draft card (operator 2026-06-12: per-order account tick) */}
              <span style={{ fontSize: 9, fontWeight: 800, padding: '1px 7px', borderRadius: 3,
                background: 'rgba(255,167,38,.15)', color: T.amber }}
                title="this draft's account — must match your thinkorswim account selector before placing">
                {(d.intent_json?.account_key ?? 'no account').replace('schwab_', '').replace(/_/g, ' ').toUpperCase()}</span>
              {n > 1 && <span style={{ fontSize: 9, color: T.dim }}>×{n} identical</span>}
              {d.intent_id === intentParam && <span style={{ fontSize: 9, fontWeight: 800, color: T.amber }}>← from Telegram deep-link</span>}
              <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 3,
                background: (STATE_C[d.state] ?? T.dim) + '22', color: STATE_C[d.state] ?? T.dim }}
                title="translates cleanly = converts to Schwab format with no errors">
                {d.state === 'TRANSLATED' ? 'translates cleanly' : d.state.toLowerCase()}</span>
              <span style={{ flex: 1 }} />
              <button onClick={() => setEditing(d)} style={btn('#1565c0')}>✏ edit & approve</button>
              <button onClick={() => setOpen(open === d.intent_id ? null : d.intent_id)} style={btn('#333')}>
                {open === d.intent_id ? 'close' : 'details'}
              </button>
            </div>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 4 }}>
              {h.pills.map((p2: string, i: number) => (
                <span key={i} style={{ fontSize: 9, padding: '1px 6px', borderRadius: 3,
                  background: p2.startsWith('⚠') ? 'rgba(255,167,38,.13)' : '#101010',
                  color: p2.startsWith('⚠') ? T.amber : '#bdbdbd' }}>{p2}</span>
              ))}
            </div>
            <div style={{ fontSize: 9, color: T.dim, marginTop: 3, fontStyle: 'italic' }}>
              Purpose: {h.purpose}
            </div>
            {d.blocked_reason && <div style={{ fontSize: 9, color: '#ef5350', marginTop: 2 }}>⛔ {String(d.blocked_reason).slice(0, 100)}</div>}
          </div>
          )})()}
          {open === d.intent_id && (
            <div>
              <div style={{ fontSize: 9.5, color: '#bdbdbd', marginTop: 8, lineHeight: 1.5 }}>
                <b style={{ color: T.text }}>If this were live:</b>{' '}
                Schwab would receive {(d.translation_json?.orders ?? []).length} order(s).{' '}
                {(d.translation_json?.orders?.[0]?.orderStrategyType === 'TRIGGER')
                  ? 'The entry triggers the exit order(s) automatically once filled (bracket).'
                  : 'A single standalone order.'}{' '}
                {(d.translation_json?.unverified?.length > 0) &&
                  <span style={{ color: T.amber }}>Unverified vs Schwab runtime: {d.translation_json.unverified.join('; ')}. </span>}
                <span style={{ color: '#ef5350' }}>This phase: nothing is sent — preview only.</span>
              </div>
              <details style={{ marginTop: 6 }}>
                <summary style={{ fontSize: 9, color: T.dim, cursor: 'pointer' }}>show raw JSON (engineering view)</summary>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 6 }}>
                  <pre style={{ fontSize: 8, color: '#bdbdbd', background: '#101010', padding: 8, borderRadius: 4, maxHeight: 220, overflow: 'auto', ...mono }}>
                    {JSON.stringify(d.intent_json, null, 1)}</pre>
                  <pre style={{ fontSize: 8, color: '#86efac', background: '#101010', padding: 8, borderRadius: 4, maxHeight: 220, overflow: 'auto', ...mono }}>
                    {JSON.stringify(d.translation_json, null, 1)}</pre>
                </div>
              </details>
              {/* Draft cards are DRAFT-ONLY and never execute. Approving here used to create a 2FA
                  slot-holder that blocked the real Pilot Console submit ("one order at a time"). Removed
                  the approval flow from drafts — approval + submit happen ONLY in the top Pilot Console,
                  which handles 2FA itself. (workflow fix 2026-06-15) */}
              <div style={{ marginTop: 8, padding: '7px 9px', borderRadius: 5, background: 'rgba(96,165,250,.08)', border: '1px solid rgba(96,165,250,.25)', fontSize: 9.5, color: T.dim }}>
                📋 Draft only — does not execute. To place this canary order, use the <b style={{ color: '#60a5fa' }}>top Pilot Console</b>: tap its <b>▸ step</b> → type the ticker → <b>SUBMIT</b> (it does the approval for you).
              </div>
            </div>
          )}
        </div>
      ))}

      {/* shadow recon strip (Part A1) */}
      <div style={{ fontSize: 12, fontWeight: 700, color: T.text, margin: '14px 0 4px' }}>Shadow reconciliation (session harness)</div>
      <div style={{ padding: 8, border: `1px solid ${T.border}`, borderRadius: 6, background: T.card, fontSize: 9.5, color: '#bdbdbd' }}>
        {lastRun ? (
          <span>
            last run #{lastRun.id} · {String(lastRun.started_at).slice(0, 16)} · orders seen {lastRun.orders_seen} ·{' '}
            <b style={{ color: '#66bb6a' }}>{lastRun.matched} matched</b> ·{' '}
            <b style={{ color: lastRun.mismatched ? '#ef5350' : T.dim }}>{lastRun.mismatched} mismatched</b> ·{' '}
            {lastRun.unmatched} unmatched · status {lastRun.status}{lastRun.detail ? ` (${String(lastRun.detail).slice(0, 80)})` : ''}
            {lastRun.mismatched > 0 && <b style={{ color: '#ef5350' }}> — ABORT CONDITION</b>}
          </span>
        ) : 'no runs yet — starts with the canary session (scripts/schwab_shadow_recon.py --watch)'}
      </div>

      {/* safety log + activity capture */}
      <div style={{ fontSize: 12, fontWeight: 700, color: T.text, margin: '14px 0 6px' }}>Safety log — what tried to happen, and what the guard did</div>
      <div style={{ fontSize: 9, color: T.dim, marginBottom: 4 }}>
        Every action attempt is decided by the guard and logged. Draft cards never execute; only the top Stage 2b Pilot Console submit path can reach the fenced Schwab transport.
        ACCT-activity capture rows (fills/status from the read poller) appear below the guard events.
      </div>
      <div style={{ maxHeight: 260, overflow: 'auto', border: `1px solid ${T.border}`, borderRadius: 6, padding: 8, background: T.card }}>
        {groupEvents(events).map((g, i: number) => (
          <div key={i} style={{ fontSize: 9.5, color: g.block ? '#ef5350' : '#66bb6a', marginBottom: 2, ...mono }}>
            {g.at} · {g.text}{g.n > 1 ? `  (×${g.n})` : ''}
          </div>
        ))}
        {activity.length > 0 && <div style={{ ...lbl, margin: '6px 0 2px' }}>activity capture (read-only poll)</div>}
        {activity.slice(0, 20).map((a: any, i: number) => (
          <div key={`a${i}`} style={{ fontSize: 9.5, color: '#90caf9', marginBottom: 2, ...mono }}>
            {String(a.captured_at).slice(5, 16)} · {a.account_key?.replace('schwab_', '')} · {a.kind} · {a.symbol} · {a.status}
          </div>
        ))}
      </div>
      {editing && <EditModal draft={editing} onClose={() => setEditing(null)} onSaved={() => refetch()} />}
      <div style={{ fontSize: 8.5, color: T.dim, marginTop: 8 }}>
        Source: /api/v2/broker-orders/* · every guard decision (grant or block) is audited · no execution path exists from this surface · no auto-send exists
      </div>
    </div>
  )
}
