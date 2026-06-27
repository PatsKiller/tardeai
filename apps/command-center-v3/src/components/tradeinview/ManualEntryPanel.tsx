import { useState } from 'react'

export default function ManualEntryPanel({ onSaved }: { onSaved?: () => void }) {
  const [form, setForm] = useState({ symbol: '', account: 'schwab_taxable', buy_price: '', sell_price: '', shares: '', pnl: '', notes: '' })
  const [msg, setMsg] = useState('')

  const save = async () => {
    const body: any = { symbol: form.symbol.toUpperCase(), account: form.account, notes: form.notes }
    if (form.buy_price) body.buy_price = Number(form.buy_price)
    if (form.sell_price) body.sell_price = Number(form.sell_price)
    if (form.shares) body.shares = Number(form.shares)
    if (form.pnl) body.pnl = Number(form.pnl)
    const r = await fetch('/api/v2/journal/manual-entry', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(x => x.json())
    if (r.ok) { setMsg('✓ saved'); onSaved?.() } else setMsg('⛔ ' + (r.error || 'failed'))
  }

  const inp = (k: keyof typeof form, ph: string) => (
    <input value={form[k]} onChange={e => setForm(f => ({ ...f, [k]: e.target.value }))} placeholder={ph}
      style={{ fontSize: 10, padding: '5px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)', flex: 1 }} />
  )

  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>Manual trade entry</div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        {inp('symbol', 'Symbol')}
        {inp('shares', 'Shares')}
        {inp('buy_price', 'Entry $')}
        {inp('sell_price', 'Exit $')}
        {inp('pnl', 'P&L $')}
      </div>
      <textarea value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} placeholder="Notes / setup template…"
        style={{ width: '100%', minHeight: 50, fontSize: 10, background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, color: 'var(--text1)', padding: 6 }} />
      <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
        <button onClick={save} style={{ fontSize: 10, padding: '5px 12px', borderRadius: 4, border: 'none', background: '#a855f7', color: '#fff', fontWeight: 700, cursor: 'pointer' }}>Save entry</button>
        {msg && <span style={{ fontSize: 9, color: msg.startsWith('✓') ? '#22c55e' : '#ef4444' }}>{msg}</span>}
      </div>
    </div>
  )
}