import { useEffect, useState } from 'react'
import { BB, DASH, numStyle } from '../../lib/watchTokens'

// Defense v9 — the adjudication layer: promote console (pre-registered criteria vs
// live evidence), governance (directives with living revoke criteria), seat league
// (honestly empty until outcomes close). Decisions write dated directives only.

export default function ReviewConsole() {
  const [d, setD] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const load = async () => {
    try { const r = await (await fetch('/api/v2/defense/review')).json(); setD(r.data ?? r) } catch { /* fold hides */ }
  }
  useEffect(() => { load() }, [])
  const act = async (body: any) => {
    setBusy(true)
    try { await fetch('/api/v2/defense/review/action', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); load() } finally { setBusy(false) }
  }
  if (!d?.console) return null
  const c = d.console
  return (
    <details style={{ background: BB.bg, border: `1px solid ${c.criteria_locked ? BB.border : BB.amber}`, borderRadius: 2, padding: '8px 12px' }}>
      <summary style={{ fontSize: DASH.section, fontWeight: 800, color: BB.text2, cursor: 'pointer' }}>
        Review — promote console · {c.review_window} {c.criteria_locked ? '· criteria LOCKED' : '· ⚠ criteria UNLOCKED'}
      </summary>
      {c.unconfirmed_banner && (
        <div style={{ fontSize: DASH.data, color: BB.amber, margin: '6px 0' }}>
          {c.unconfirmed_banner}
          <button disabled={busy} onClick={() => window.confirm('Lock the promote criteria as registered? Post-lock edits require dated amendments.') && act({ action: 'lock' })}
            style={{ fontSize: DASH.chip, fontWeight: 800, marginLeft: 10, cursor: 'pointer', color: BB.text0, background: BB.amber, border: 'none', borderRadius: 2, padding: '2px 10px' }}>
            LOCK CRITERIA
          </button>
        </div>
      )}
      {c.cards.map((card: any) => (
        <div key={card.id} style={{ border: `1px solid ${BB.borderHair}`, borderLeft: `3px solid ${card.verdict_preview.includes('MET') && !card.verdict_preview.includes('NOT') ? BB.green : card.verdict_preview.includes('insufficient') ? BB.amber : BB.red}`, borderRadius: 2, padding: '6px 10px', margin: '6px 0' }}>
        <div style={{ fontSize: DASH.data, fontWeight: 800, color: BB.text1 }}>{card.question}
          <span style={{ fontSize: DASH.chip, color: BB.text3, marginLeft: 8 }}>registered {card.registered_at} · {card.verdict_preview}</span>
          {card.decision && <span style={{ fontSize: DASH.chip, color: BB.green, marginLeft: 8 }}>DECIDED: {card.decision.choice} ({card.decision.at})</span>}
        </div>
        {card.metrics.map((m: any) => (
          <div key={m.id} style={{ fontSize: DASH.data, color: m.status === 'pass' ? BB.green : m.status === 'insufficient' ? BB.text3 : BB.red }}>
            {m.status === 'pass' ? '✓' : m.status === 'insufficient' ? '…' : '✗'} {m.def}: <span style={numStyle}>{m.detail}</span>
          </div>
        ))}
        {!card.decision && c.criteria_locked && (
          <div style={{ marginTop: 4 }}>
            {card.options.map((o: string) => (
              <button key={o} disabled={busy} onClick={() => act({ action: 'decide', entry: card.id, choice: o, note: 'console decision' })}
                style={{ fontSize: DASH.chip, fontWeight: 800, marginRight: 6, cursor: 'pointer', color: BB.text1, background: 'transparent', border: `1px solid ${BB.border}`, borderRadius: 2, padding: '2px 9px' }}>{o}</button>
            ))}
          </div>
        )}
        </div>
      ))}
      <div style={{ fontSize: DASH.section, fontWeight: 800, color: BB.text2, marginTop: 8 }}>Governance — active directives</div>
      {(d.governance || []).map((g: any, i: number) => (
        <div key={i} style={{ fontSize: DASH.data, color: BB.text2, padding: '3px 0', borderBottom: `1px solid ${BB.borderHair}` }}>
          <b style={{ color: g.criterion_met ? BB.amber : BB.text1 }}>{g.directive}</b> · {g.status}
          <div style={{ fontSize: DASH.chip, color: BB.text3 }}>{String(g.rationale).slice(0, 140)} · revoke: {String(g.revoke_criterion).slice(0, 80)}</div>
        </div>
      ))}
      <div style={{ fontSize: DASH.section, fontWeight: 800, color: BB.text2, marginTop: 8 }}>Seat league <span style={{ fontSize: DASH.chip, color: BB.text3, fontWeight: 600 }}>· the auditors get audited — unranked until n≥10 closed outcomes</span></div>
      {(d.league || []).map((l: any) => (
        <div key={l.seat} style={{ fontSize: DASH.data, color: BB.text2, padding: '2px 0' }}>
          {l.seat}: <span style={numStyle}>{l.reviews}</span> reviews · object-precision {l.object_precision} · ${l.cost_usd} · {l.note || 'RANKED'}
        </div>
      ))}
    </details>
  )
}
