type StopRow = {
  order_type?: string
  stop_price?: number
  trail_pct?: number
  status?: string
  active?: boolean
  placed_date?: string
  updated_at?: string
}

export default function StopContextPanel({ ctx }: { ctx?: any }) {
  if (!ctx?.ok) return null
  const stops: StopRow[] = ctx.broker_stops || []
  const conf = ctx.stop_confirmations || []
  const notes: string[] = ctx.notes || []
  const suggested = ctx.suggested_exit_type as string | undefined

  const suggestLabel: Record<string, string> = {
    hard_stop: 'Hard stop',
    trailing_stop: 'Trailing stop',
    target_hit: 'Target hit',
    manual_exit: 'Manual exit',
  }

  return (
    <div style={{
      background: 'rgba(245,158,11,.06)', border: '1px solid rgba(245,158,11,.35)',
      borderRadius: 10, padding: '12px 14px', marginBottom: 14,
    }}>
      <div style={{ fontSize: 13, fontWeight: 800, color: '#fcd34d', marginBottom: 6 }}>
        Stop management context
      </div>
      <div style={{ fontSize: 12, color: 'var(--text2)', lineHeight: 1.45, marginBottom: 8 }}>
        {ctx.has_history
          ? 'Recorded stops / confirmations for this symbol & account. Verify exit type on save — Schwab round-trips do not auto-tag stop vs trail.'
          : 'No stop history on file for this symbol/account. Tag exit type manually if you were stopped out.'}
        {ctx.sell_price != null && ctx.sell_price > 0 && (
          <span> · Exit fill <strong style={{ color: 'var(--text0)' }}>${Number(ctx.sell_price).toFixed(4)}</strong></span>
        )}
      </div>
      {suggested && (
        <div style={{ fontSize: 12, fontWeight: 700, color: '#86efac', marginBottom: 8 }}>
          Suggested: {suggestLabel[suggested] || suggested}
          {ctx.suggested_exit_signals?.length ? ` (${ctx.suggested_exit_signals.join(', ')})` : ''}
        </div>
      )}
      {notes.map((n, i) => (
        <div key={i} style={{ fontSize: 11, color: 'var(--text1)', marginBottom: 4 }}>• {n}</div>
      ))}
      {stops.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text1)', marginBottom: 4 }}>Broker stops (manual_broker_stops)</div>
          {stops.slice(0, 6).map((s, i) => (
            <div key={i} style={{ fontSize: 11, color: 'var(--text2)', fontFamily: 'monospace' }}>
              {(s.order_type || 'STOP').toUpperCase()}
              {s.stop_price != null ? ` @ $${Number(s.stop_price).toFixed(2)}` : ''}
              {s.trail_pct != null ? ` · trail ${s.trail_pct}%` : ''}
              {s.active === false ? ' · inactive' : ''}
              {s.placed_date ? ` · ${s.placed_date}` : ''}
            </div>
          ))}
        </div>
      )}
      {conf.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text1)', marginBottom: 4 }}>Operator confirmations</div>
          {conf.map((c: any, i: number) => (
            <div key={i} style={{ fontSize: 11, color: 'var(--text2)' }}>
              {c.stop_status || '—'}
              {c.stop_price_confirmed != null ? ` · confirmed $${Number(c.stop_price_confirmed).toFixed(2)}` : ''}
              {c.stop_confirmed_at ? ` · ${String(c.stop_confirmed_at).slice(0, 16)}` : ''}
            </div>
          ))}
        </div>
      )}
      {(ctx.stop_grok_reviews || []).length > 0 && (
        <div style={{ marginTop: 8, fontSize: 11, color: 'var(--text3)' }}>
          {ctx.stop_grok_reviews.length} stop review(s) on file — see Portfolio → Stop Management for full history.
        </div>
      )}
    </div>
  )
}