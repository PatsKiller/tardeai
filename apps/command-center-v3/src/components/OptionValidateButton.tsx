// Validate one options proposal against the live Schwab chain (operator 2026-09-26).
// Read-only market data: re-quotes the exact contract, recomputes the economics,
// flags material changes. Approval requires a fresh VALIDATED result.
import { useState } from 'react'
import { BB } from '../lib/watchlistTerminalTokens'

type Result = {
  status: string
  validated_at?: string
  reason?: string
  note?: string | null
  live?: { bid?: number; ask?: number; mid?: number; last?: number | null; oi?: number | null; volume?: number | null; spot?: number; bid_ask_spread_pct?: number | null }
  recomputed?: { premium_total?: number; breakeven?: number; max_profit?: number | null; max_loss?: number | null; cash_flow?: string }
  material_changes?: string[]
  liquidity_issues?: string[]
}

export default function OptionValidateButton({ proposalId }: { proposalId: string }) {
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<Result | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const run = async () => {
    setBusy(true); setErr(null)
    try {
      const r = await fetch('/api/v2/options/validate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposal_id: proposalId }),
      })
      const j = await r.json()
      if (!r.ok || j?.ok === false) setErr(j?.error || `validate failed (${r.status})`)
      else setRes(j.data)
    } catch (e: any) {
      setErr(String(e?.message || e))
    } finally {
      setBusy(false)
    }
  }
  const color = res?.status === 'VALIDATED' ? BB.green : res ? BB.red : BB.text2
  const money = (v?: number | null) => (v == null ? '—' : `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`)
  return (
    <div data-testid="option-validate" style={{ marginTop: 8 }}>
      <button onClick={run} disabled={busy} style={{ fontSize: 11, fontWeight: 800, padding: '4px 10px', borderRadius: 6, border: `1px solid ${BB.border}`, background: 'transparent', color: BB.text1, cursor: 'pointer' }}>
        {busy ? 'Validating against Schwab…' : 'Validate against live Schwab'}
      </button>
      {err && <div style={{ marginTop: 4, color: BB.red, fontSize: 11 }}>{err}</div>}
      {res && (
        <div style={{ marginTop: 4, fontSize: 11, color: BB.text2 }}>
          <b style={{ color }}>{res.status.replace(/_/g, ' ')}</b>
          {res.validated_at ? ` · ${new Date(res.validated_at).toLocaleTimeString()}` : ''}
          {res.reason ? ` · ${res.reason}` : ''}
          {res.live && (
            <div>Live: bid {money(res.live.bid)} · ask {money(res.live.ask)} · mid {money(res.live.mid)} · OI {res.live.oi ?? '—'} · vol {res.live.volume ?? '—'} · spread {res.live.bid_ask_spread_pct ?? '—'}% · spot {money(res.live.spot)}</div>
          )}
          {res.recomputed && (
            <div>Recomputed: {res.recomputed.cash_flow === 'debit' ? 'you pay' : 'you collect'} {money(res.recomputed.premium_total)} · breakeven {money(res.recomputed.breakeven)}{res.recomputed.max_loss != null ? ` · max loss ${money(res.recomputed.max_loss)}` : ''}</div>
          )}
          {(res.material_changes || []).length > 0 && <div style={{ color: BB.amber }}>Changed: {(res.material_changes || []).join('; ')}. Regenerate before approving.</div>}
          {(res.liquidity_issues || []).length > 0 && <div style={{ color: BB.red }}>Liquidity: {(res.liquidity_issues || []).join('; ')}</div>}
          {res.note && <div style={{ color: BB.amber }}>{res.note}</div>}
        </div>
      )}
    </div>
  )
}
