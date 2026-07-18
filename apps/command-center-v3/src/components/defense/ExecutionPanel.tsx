import { useState } from 'react'
import { BB, T, DASH, numStyle } from '../../lib/watchTokens'

// Defense v7 — In Play + the execution rail's visible state: every intent from
// staged → approvals → 2FA (code entry here) → armed ticket / paper submit →
// FILLED (auto-detected, 10-min poller). The audit chain's last 20 hops fold below.
// The desk STAGES and ARMS; approvals + 2FA own the go; live placement is the
// operator's hands on an armed ticket until the pilot fence is widened.

const ST: Record<string, { c: string; label: string; tip: string }> = {
  staged: { c: BB.text3, label: 'STAGED', tip: 'in the APPROVALS queue — approve there to get the 2FA pill' },
  awaiting_2fa: { c: BB.amber, label: 'AWAITING 2FA', tip: 'a 6-digit code was sent via Telegram (15-min expiry) — enter it here to ARM' },
  armed_ticket: { c: T.link, label: 'ARMED TICKET', tip: 'approved + 2FA-armed — place the exact order below in ToS/web; the 10-min poller reconciles the fill automatically' },
  submitted_paper: { c: T.link, label: 'PAPER SUBMITTED', tip: 'auto-submitted to the Alpaca paper lane post-2FA; fill reconciles automatically' },
  filled: { c: BB.green, label: 'FILLED', tip: 'fill detected and recorded — ladder/pair/round-trip states advanced automatically' },
  refused: { c: BB.red, label: 'REFUSED', tip: 'staging refused by caps/whitelist/kill-file — reason shown' },
}

function TwoFaInput({ intentKey, onDone }: { intentKey: string; onDone: () => void }) {
  const [code, setCode] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const submit = async () => {
    setBusy(true)
    setErr(null)
    try {
      const r = await fetch('/api/v2/defense/intent/2fa', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ intent_key: intentKey, code }),
      })
      const j = await r.json()
      if (j.ok) onDone()
      else setErr(j.error || 'failed')
    } finally { setBusy(false) }
  }
  return (
    <span style={{ display: 'inline-flex', gap: 5, alignItems: 'center' }}>
      <input value={code} onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
        placeholder="Telegram code" style={{ width: 92, fontSize: DASH.data, background: 'transparent', color: BB.text1, border: `1px solid ${BB.amber}`, borderRadius: 2, padding: '2px 6px' }} />
      <button onClick={submit} disabled={busy || code.length !== 6}
        style={{ fontSize: DASH.chip, fontWeight: 800, cursor: 'pointer', color: BB.text1, background: 'transparent', border: `1px solid ${BB.amber}`, borderRadius: 2, padding: '2px 8px' }}>
        {busy ? '…' : 'ARM'}
      </button>
      {err && <span style={{ fontSize: DASH.chip, color: BB.red }}>{err}</span>}
    </span>
  )
}

export default function ExecutionPanel({ intents, execLog, capsCfg, onChange }: {
  intents: any[]; execLog: any[]; capsCfg: any; onChange: () => void
}) {
  const [logOpen, setLogOpen] = useState(false)
  const active = (intents || []).filter(i => i.status !== 'refused')
  const refused = (intents || []).filter(i => i.status === 'refused')
  if (!active.length && !refused.length) return null
  const disabled = capsCfg?.disabled
  return (
    <div style={{ background: BB.bg, border: `1px solid ${disabled ? BB.red : BB.border}`, borderRadius: 2, padding: '10px 12px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: DASH.panel, fontWeight: 800, color: BB.text1 }}>
          In Play — execution rail
          <span title="the desk stages and arms; approvals + per-order 2FA own the go; autonomous submit stays OFF" style={{ fontSize: DASH.data, color: BB.text3, fontWeight: 600, cursor: 'help' }}> · staged → approved → 2FA → placed → filled (auto)</span>
        </span>
        <span style={{ fontSize: DASH.data, color: BB.text3 }} title={`caps: $${(capsCfg?.max_order_dollars || 0).toLocaleString()}/order · ${capsCfg?.max_orders_per_day}/day · fills polled every ${capsCfg?.fill_poll_minutes}m RTH`}>
          {disabled ? <b style={{ color: BB.red }}>EXECUTION DISABLED (kill file)</b>
            : `caps $${((capsCfg?.max_order_dollars || 0) / 1000)}K/order · ${capsCfg?.max_orders_per_day}/day`}
        </span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {active.map(i => {
          const st = ST[i.status] || { c: BB.text3, label: i.status, tip: '' }
          return (
            <div key={i.intent_key} style={{ border: `1px solid ${BB.border}`, borderLeft: `3px solid ${st.c}`, borderRadius: 2, padding: '6px 10px', display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              <span title={st.tip} style={{ fontSize: DASH.chip, fontWeight: 800, color: st.c, cursor: 'help', minWidth: 104 }}>{st.label}</span>
              <span style={{ fontSize: DASH.data, fontWeight: 700, color: BB.text1 }}>
                {String(i.side).toUpperCase()} <span style={numStyle}>{Number(i.qty)}</span> {i.symbol}
              </span>
              <span style={{ fontSize: DASH.data, color: BB.text3 }}>{String(i.account).replace('schwab_', '')} · {i.lane}</span>
              {i.limit_low != null && <span style={{ ...numStyle, fontSize: DASH.data, color: BB.text2 }}>limit {i.limit_low}–{i.limit_high}</span>}
              {i.status === 'awaiting_2fa' && <TwoFaInput intentKey={i.intent_key} onDone={onChange} />}
              {i.status === 'armed_ticket' && (
                <span title="place exactly this in ToS/web — the poller reconciles the fill" style={{ fontSize: DASH.data, color: T.link, fontWeight: 700, cursor: 'help' }}>
                  → PLACE: {String(i.side).toUpperCase()} {Number(i.qty)} {i.symbol} LIMIT {i.limit_low}–{i.limit_high} ({String(i.account).replace('schwab_', '')})
                </span>
              )}
              {i.status === 'filled' && (
                <span style={{ ...numStyle, fontSize: DASH.data, color: BB.green }}>
                  {Number(i.fill_qty)} @ ${Number(i.fill_price)} · states advanced
                </span>
              )}
              <span style={{ fontSize: DASH.chip, color: BB.text3, marginLeft: 'auto' }}>{String(i.created_at).slice(5, 16)}</span>
            </div>
          )
        })}
        {refused.slice(0, 3).map(i => (
          <div key={i.intent_key} style={{ fontSize: DASH.data, color: BB.text3, border: `1px dashed ${BB.borderHair}`, borderRadius: 2, padding: '4px 10px' }}>
            <b style={{ color: BB.red }}>REFUSED</b> {i.symbol} {i.side} — {i.refusal}
          </div>
        ))}
      </div>
      <button onClick={() => setLogOpen(o => !o)} style={{ fontSize: DASH.chip, fontWeight: 700, color: BB.text3, background: 'transparent', border: `1px solid ${BB.border}`, borderRadius: 2, padding: '2px 9px', cursor: 'pointer', marginTop: 8 }}>
        {logOpen ? '▾' : '▸'} Execution log ({(execLog || []).length} recent hops — full audit chain never deleted)
      </button>
      {logOpen && (
        <div style={{ marginTop: 5 }}>
          {(execLog || []).map((e: any, i: number) => (
            <div key={i} style={{ display: 'flex', gap: 8, fontSize: DASH.data, padding: '1px 0', borderBottom: `1px solid ${BB.borderHair}`, color: BB.text2 }}>
              <span style={{ ...numStyle, color: BB.text3, minWidth: 128 }}>{e.at}</span>
              <span style={{ fontWeight: 700, minWidth: 150, color: e.hop.includes('refus') || e.hop.includes('reject') ? BB.red : e.hop.includes('fill') ? BB.green : BB.text1 }}>{e.hop}</span>
              <span style={{ color: BB.text3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.intent_key} · {e.detail}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
