import { useEffect, useMemo, useState } from 'react'
import { BB, DASH, numStyle } from '../../lib/watchTokens'

// OPTIONS LIFECYCLE DESK (Phase 7) — first-class open-position management view.
// Strategies, never loose legs. Every card carries the exact recommendation,
// why-now, cost of waiting, alternatives, next trigger, refresh time, and the
// action buttons that run the hash-bound preflight (build → approve → 2FA →
// ARMED MANUAL TICKET). A click NEVER closes a position — only recorded broker
// or operator evidence does, and the UI says so wherever it matters.

const URG: Record<string, string> = { red: BB.red, amber: BB.amber, green: BB.green }
const SECTIONS = [
  { key: 'action_now', title: '1 · ACTION NOW', test: (p: any) => p.decision?.urgency === 'red' },
  { key: 'harvest', title: '2 · PROFITABLE — HARVEST REVIEW', test: (p: any) => (p.decision?.recommendation || '').startsWith('HARVEST') },
  { key: 'mature', title: '3 · LET MATURE / ON PLAN', test: (p: any) => ['LET_MATURE', 'HOLD'].includes(p.decision?.recommendation) },
  { key: 'defend', title: '4 · DEFEND / ROLL', test: (p: any) => ['DEFEND', 'ROLL'].includes(p.decision?.recommendation) },
  { key: 'expiry', title: '5 · EXPIRATION & ASSIGNMENT', test: (p: any) => (p.economics?.dte_nearest ?? 99) <= 7 || ['ACCEPT_ASSIGNMENT', 'EXERCISE_REVIEW'].includes(p.decision?.recommendation) },
  { key: 'blocked', title: '6 · DATA BLOCKED', test: (p: any) => p.decision?.recommendation === 'DATA_BLOCKED' },
]

const fmtD = (v: any) => (v == null ? '—' : `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`)
const fmtP = (v: any) => (v == null ? '—' : `${Number(v).toFixed(1)}%`)

async function post(action: string, body: any) {
  const r = await fetch(`/api/v2/options/lifecycle/${action}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  return r.json()
}

function TicketModal({ spid, onClose }: { spid: number; onClose: () => void }) {
  const [ticket, setTicket] = useState<any>(null)
  const [blocked, setBlocked] = useState<string | null>(null)
  const [stage, setStage] = useState<'draft' | 'awaiting_2fa' | 'armed'>('draft')
  const [code, setCode] = useState('')
  const [manual, setManual] = useState<any>(null)
  const [tif, setTif] = useState('DAY')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const build = async (t: string) => {
    setBusy(true); setErr(null); setBlocked(null); setManual(null); setStage('draft')
    const r = await post('ticket-build', { strategy_position_id: spid, kind: 'close', tif: t })
    setBusy(false)
    if (r?.data?.blocked) { setBlocked(r.data.blocked); setTicket(null) } else setTicket(r?.data || null)
  }
  useEffect(() => { build(tif) }, [])

  const approve = async () => {
    if (!ticket) return
    setBusy(true); setErr(null)
    const r = await post('ticket-approve', { ticket_id: ticket.ticket_id, hash: ticket.approval_hash })
    setBusy(false)
    if (r?.data?.ok) setStage('awaiting_2fa')
    else setErr(r?.data?.error || 'approve failed')
  }
  const verify = async () => {
    setBusy(true); setErr(null)
    const r = await post('ticket-2fa', { ticket_id: ticket.ticket_id, code })
    setBusy(false)
    if (r?.data?.ok) { setStage('armed'); setManual(r.data.manual_ticket) }
    else setErr(r?.data?.error || '2FA failed')
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 90, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{ background: BB.bgPanel, border: `1px solid ${BB.border}`, borderRadius: 2, padding: 16, width: 'min(640px, 92vw)', maxHeight: '85vh', overflowY: 'auto' }}>
        <div style={{ fontSize: DASH.section, fontWeight: 800, color: BB.text1, marginBottom: 8 }}>
          CLOSE TICKET — lifecycle preflight
          <span style={{ fontSize: DASH.chip, color: BB.text3, fontWeight: 600, marginLeft: 8 }}>
            quotes refetched at build · approval binds to the exact ticket · any change invalidates
          </span>
        </div>
        {busy && <div style={{ fontSize: DASH.data, color: BB.text3 }}>working…</div>}
        {blocked && <div style={{ fontSize: DASH.data, color: BB.amber }}>⛔ BLOCKED (fail closed): {blocked}</div>}
        {err && <div style={{ fontSize: DASH.data, color: BB.red, marginBottom: 6 }}>{err}</div>}
        {ticket && (
          <>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
              <span style={{ fontSize: DASH.chip, color: BB.text3 }}>TIF</span>
              {['DAY', 'GTC'].map(t => (
                <button key={t} onClick={() => { setTif(t); build(t) }}
                  title="changing TIF rebuilds the ticket — the prior approval hash is dead"
                  style={{ fontSize: DASH.chip, fontWeight: 800, cursor: 'pointer', padding: '2px 8px', borderRadius: 2, border: `1px solid ${tif === t ? BB.amber : BB.borderHair}`, background: 'transparent', color: tif === t ? BB.amber : BB.text3 }}>{t}</button>
              ))}
              <span style={{ ...numStyle, fontSize: DASH.chip, color: BB.text3, marginLeft: 'auto' }}>hash {ticket.approval_hash?.slice(0, 10)}…</span>
            </div>
            {(ticket.legs || []).map((l: any, i: number) => (
              <div key={i} style={{ display: 'flex', gap: 10, fontSize: DASH.data, color: BB.text1, borderBottom: `1px solid ${BB.borderHair}`, padding: '3px 0' }}>
                <b>{l.instruction}</b><span style={{ ...numStyle }}>{l.contracts}×</span>
                <span>{l.occ_symbol || l.occ_target}</span>
                <span style={{ ...numStyle, marginLeft: 'auto' }}>
                  ${l.bid} × ${l.ask} → limit <b>${l.proposed_limit}</b>
                </span>
              </div>
            ))}
            {ticket.leg_out_warning && <div style={{ fontSize: DASH.data, color: BB.red, marginTop: 6 }}>⚠ {ticket.leg_out_warning}</div>}
            <div style={{ display: 'flex', gap: 14, marginTop: 8, fontSize: DASH.data, color: BB.text2, flexWrap: 'wrap' }}>
              <span>{ticket.net_label}</span>
              <span>est realized {ticket.est_realized_pnl == null ? 'UNKNOWN (basis incomplete)' : fmtD(ticket.est_realized_pnl)}</span>
              <span>fees ≈ ${ticket.est_fees}</span>
              <span style={{ color: BB.text3 }}>{ticket.broker_capability?.note}</span>
            </div>
            {stage === 'draft' && (
              <button onClick={approve} disabled={busy}
                style={{ marginTop: 10, fontSize: DASH.data, fontWeight: 800, cursor: 'pointer', textTransform: 'uppercase', color: BB.text0, background: 'transparent', border: `1px solid ${BB.amber}`, borderRadius: 2, padding: '5px 14px' }}>
                approve → request 2FA
              </button>
            )}
            {stage === 'awaiting_2fa' && (
              <div style={{ marginTop: 10, display: 'flex', gap: 8 }}>
                <input value={code} onChange={e => setCode(e.target.value)} placeholder="Telegram code"
                  style={{ ...numStyle, fontSize: DASH.data, background: BB.bg, color: BB.text0, border: `1px solid ${BB.border}`, borderRadius: 2, padding: '4px 8px', width: 130 }} />
                <button onClick={verify} disabled={busy || code.length < 6}
                  style={{ fontSize: DASH.data, fontWeight: 800, cursor: 'pointer', color: BB.text0, background: 'transparent', border: `1px solid ${BB.green}`, borderRadius: 2, padding: '4px 12px' }}>
                  arm ticket
                </button>
              </div>
            )}
            {stage === 'armed' && manual && (
              <div style={{ marginTop: 10, border: `1px solid ${BB.green}`, borderRadius: 2, padding: 10 }}>
                <div style={{ fontSize: DASH.data, fontWeight: 800, color: BB.green }}>{manual.title}</div>
                <div style={{ fontSize: DASH.chip, color: BB.text3 }}>account {manual.account} · TIF {manual.tif}</div>
                {(manual.lines || []).map((ln: string, i: number) => (
                  <div key={i} style={{ ...numStyle, fontSize: DASH.data, color: BB.text1, marginTop: 3 }}>{ln}</div>
                ))}
                <div style={{ fontSize: DASH.data, color: BB.text2, marginTop: 4 }}>{manual.net}</div>
                <div style={{ fontSize: DASH.chip, color: BB.amber, marginTop: 6 }}>{manual.reminder}</div>
              </div>
            )}
          </>
        )}
        <button onClick={onClose} style={{ marginTop: 12, fontSize: DASH.chip, cursor: 'pointer', color: BB.text3, background: 'transparent', border: `1px solid ${BB.borderHair}`, borderRadius: 2, padding: '3px 10px' }}>close</button>
      </div>
    </div>
  )
}

function StrategyCard({ p, onTicket, onAck }: { p: any; onTicket: (spid: number) => void; onAck: (id: number) => void }) {
  const d = p.decision || {}
  const e = p.economics || {}
  const gbPct = e.giveback != null && e.mfe ? (e.giveback / e.mfe) * 100 : null
  return (
    <div style={{ border: `1px solid ${BB.border}`, borderLeft: `3px solid ${URG[d.urgency] || BB.text3}`, borderRadius: 2, padding: '9px 11px' }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
        <span style={{ fontSize: DASH.data + 1, fontWeight: 800, color: BB.text1 }}>{p.underlying}</span>
        <span style={{ fontSize: DASH.chip, fontWeight: 700, color: BB.text2, textTransform: 'uppercase' }}>{(p.strategy_type || '').replace(/_/g, ' ')}</span>
        <span style={{ fontSize: DASH.chip, color: BB.text3 }}>{p.account_key} · {p.broker}</span>
        <span style={{ fontSize: DASH.chip, fontWeight: 800, color: URG[d.urgency] || BB.text2, textTransform: 'uppercase', marginLeft: 'auto' }}>{d.recommendation}</span>
      </div>
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginTop: 5, fontSize: DASH.data, color: BB.text2 }}>
        <span title="unrealized P&L for the whole structure">P&L <b style={{ ...numStyle, color: (e.unrealized_pnl ?? 0) >= 0 ? BB.green : BB.red }}>{e.unrealized_pnl == null ? 'UNKNOWN' : fmtD(e.unrealized_pnl)}</b></span>
        <span title="% of the structure's maximum possible profit already captured">max captured <b style={{ ...numStyle }}>{fmtP(e.pct_max_profit_captured)}</b></span>
        <span title="peak unrealized (MFE) and how much has been given back from it">peak {fmtD(e.mfe)}{gbPct != null && <b style={{ color: gbPct > 35 ? BB.red : BB.text2 }}> · gave back {gbPct.toFixed(0)}%</b>}</span>
        <span>DTE <b style={{ ...numStyle }}>{e.dte_nearest ?? '—'}</b></span>
        <span title="net structure greeks">Δ {e.net?.delta ?? '—'} · Θ {e.net?.theta ?? '—'}</span>
        <span title="worst leg bid/ask spread — liquidity truth">spread {fmtP(e.max_spread_pct)}</span>
      </div>
      <div style={{ fontSize: DASH.data, color: BB.text1, marginTop: 6 }}>{d.rationale}</div>
      {p.oversight?.objection && (
        <div style={{ fontSize: DASH.chip, color: BB.amber, marginTop: 3 }}
          title={`free-lane exception review (${p.oversight.trigger}) — advisory only, deterministic decision stays canonical`}>
          ✦ {p.oversight.lane} {p.oversight.verdict}: {p.oversight.objection}
        </div>
      )}
      {(d.alternatives || []).length > 0 && (
        <div style={{ fontSize: DASH.chip, color: BB.text3, marginTop: 4 }}>
          alternatives: {(d.alternatives || []).map((a: any) => a.note ? `${a.action} (${a.note})` : a.action).join(' · ')}
        </div>
      )}
      <div style={{ display: 'flex', gap: 8, marginTop: 7, alignItems: 'center', flexWrap: 'wrap' }}>
        <button onClick={() => onTicket(p.strategy_position_id)}
          title="build a fresh-quoted close ticket — approval binds to the exact ticket; a click never closes the position"
          style={{ fontSize: DASH.chip, fontWeight: 800, textTransform: 'uppercase', cursor: 'pointer', color: BB.text1, background: 'transparent', border: `1px solid ${BB.amber}`, borderRadius: 2, padding: '2px 9px' }}>
          close ticket
        </button>
        {p.alert?.alert_id && (
          <button onClick={() => onAck(p.alert.alert_id)}
            style={{ fontSize: DASH.chip, fontWeight: 700, cursor: 'pointer', color: BB.text3, background: 'transparent', border: `1px solid ${BB.borderHair}`, borderRadius: 2, padding: '2px 9px' }}>
            ack alert
          </button>
        )}
        <span style={{ fontSize: DASH.chip, color: BB.text3, marginLeft: 'auto' }}>
          {(p.legs || []).filter((l: any) => l.status === 'open').map((l: any) => `${l.side === 'short' ? '-' : '+'}${l.contracts} ${l.occ_symbol?.trim()}`).join(' · ')}
        </span>
      </div>
    </div>
  )
}

export default function OptionsLifecycleView() {
  const [data, setData] = useState<any>(null)
  const [ticketSpid, setTicketSpid] = useState<number | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  const load = async () => {
    const r = await fetch('/api/v2/options/lifecycle').then(x => x.json()).catch(() => null)
    setData(r?.data || null)
  }
  useEffect(() => { load() }, [])

  const refresh = async () => {
    setRefreshing(true)
    await post('refresh', {}).catch(() => null)
    await load()
    setRefreshing(false)
  }
  const ack = async (id: number) => { await post('alert-ack', { alert_id: id }); await load() }

  const positions = data?.positions || []
  const strip = useMemo(() => {
    const num = (v: any) => (v == null || isNaN(Number(v)) ? 0 : Number(v))
    const pnl = positions.reduce((a: number, p: any) => a + num(p.economics?.unrealized_pnl), 0)
    const peak = positions.reduce((a: number, p: any) => a + num(p.economics?.mfe), 0)
    const gb = positions.reduce((a: number, p: any) => a + num(p.economics?.giveback), 0)
    return {
      open: positions.length, pnl, peak, giveback: gb,
      harvest: positions.filter((p: any) => (p.decision?.recommendation || '').startsWith('HARVEST')).length,
      defend: positions.filter((p: any) => ['DEFEND', 'ROLL'].includes(p.decision?.recommendation)).length,
      assign: positions.filter((p: any) => ['ACCEPT_ASSIGNMENT', 'EXERCISE_REVIEW'].includes(p.decision?.recommendation) || (p.economics?.dte_nearest ?? 99) <= 3).length,
      week: positions.filter((p: any) => (p.economics?.dte_nearest ?? 99) <= 5).length,
      stale: positions.filter((p: any) => p.decision?.recommendation === 'DATA_BLOCKED').length,
    }
  }, [positions])
  const failedHealth = (data?.health || []).filter((h: any) => !h.ok)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'baseline', background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: '10px 12px' }}>
        <span style={{ fontSize: DASH.panel, fontWeight: 800, color: BB.text1 }}>Options Lifecycle</span>
        {[['open strategies', strip.open], ['total P&L', fmtD(strip.pnl)], ['peak reached', fmtD(strip.peak)],
          ['profit at giveback risk', fmtD(strip.giveback)], ['harvest', strip.harvest], ['defend/roll', strip.defend],
          ['assignment risk', strip.assign], ['expiring ≤5d', strip.week], ['data blocked', strip.stale]].map(([l, v]) => (
          <span key={String(l)} style={{ fontSize: DASH.data, color: BB.text3 }}>{l} <b style={{ ...numStyle, color: BB.text1 }}>{v as any}</b></span>
        ))}
        <button onClick={refresh} disabled={refreshing}
          style={{ marginLeft: 'auto', fontSize: DASH.chip, fontWeight: 800, cursor: 'pointer', textTransform: 'uppercase', color: BB.text1, background: 'transparent', border: `1px solid ${BB.borderHair}`, borderRadius: 2, padding: '3px 10px' }}>
          {refreshing ? 'refreshing…' : '⟳ refresh'}
        </button>
        <span style={{ fontSize: DASH.chip, color: BB.text3 }}>
          {data?.generated_at ? `run ${String(data.generated_at).slice(11, 16)}Z · policy ${data.policy_version}` : 'no run yet'}
        </span>
      </div>

      {failedHealth.length > 0 && (
        <div style={{ border: `1px solid ${BB.red}`, borderRadius: 2, padding: '8px 10px' }}>
          <div style={{ fontSize: DASH.data, fontWeight: 800, color: BB.red }}>HEALTH — desk fails closed until these clear</div>
          {failedHealth.map((h: any) => (
            <div key={h.check} style={{ fontSize: DASH.data, color: BB.text2 }}>⛔ {h.check}: {h.detail}</div>
          ))}
        </div>
      )}

      {positions.length === 0 && (
        <div style={{ fontSize: DASH.data, color: BB.text3, border: `1px dashed ${BB.borderHair}`, borderRadius: 2, padding: 14 }}>
          No open option strategies. The desk is armed: broker sync, policy engine, alerts, and hash-bound
          2FA tickets are live — the first position (paper or real) appears here with a full lifecycle card.
        </div>
      )}

      {SECTIONS.map(sec => {
        const rows = positions.filter(sec.test)
        if (!rows.length) return null
        return (
          <div key={sec.key}>
            <div style={{ fontSize: DASH.section, fontWeight: 800, color: BB.text1, margin: '4px 0 6px' }}>{sec.title}
              <span style={{ fontSize: DASH.chip, color: BB.text3, fontWeight: 600, marginLeft: 8 }}>{rows.length}</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {rows.map((p: any) => (
                <StrategyCard key={p.strategy_position_id} p={p} onTicket={setTicketSpid} onAck={ack} />
              ))}
            </div>
          </div>
        )
      })}

      <div>
        <div style={{ fontSize: DASH.section, fontWeight: 800, color: BB.text1, margin: '4px 0 6px' }}>7 · CLOSED OUTCOMES</div>
        {(data?.closed_outcomes || []).length === 0 ? (
          <div style={{ fontSize: DASH.data, color: BB.text3 }}>
            No closed positions yet — outcome calibration unlocks at the configured minimum sample; nothing tunes automatically.
          </div>
        ) : (data.closed_outcomes.map((o: any, i: number) => (
          <div key={i} style={{ display: 'flex', gap: 12, fontSize: DASH.data, color: BB.text2, borderBottom: `1px solid ${BB.borderHair}`, padding: '3px 0' }}>
            <b style={{ color: BB.text1 }}>{o.underlying}</b>
            <span>{(o.strategy_type || '').replace(/_/g, ' ')}</span>
            <span>rec: {o.recommendation || '—'}</span>
            <span>action: {o.operator_action}</span>
            <b style={{ ...numStyle, marginLeft: 'auto', color: (o.realized_pnl ?? 0) >= 0 ? BB.green : BB.red }}>
              {o.realized_pnl == null ? 'UNKNOWN' : fmtD(o.realized_pnl)}
            </b>
            <span style={{ color: BB.text3 }}>{String(o.closed_at).slice(0, 10)}</span>
          </div>
        )))}
      </div>

      <div style={{ fontSize: DASH.chip, color: BB.text3 }}>
        advisory desk · tickets are hash-bound and 2FA-armed · Schwab options pilot DISARMED (manual tickets) ·
        positions close only on broker or operator-recorded evidence · policy v{data?.policy_version || '—'}
      </div>

      {ticketSpid != null && <TicketModal spid={ticketSpid} onClose={() => { setTicketSpid(null); load() }} />}
    </div>
  )
}
