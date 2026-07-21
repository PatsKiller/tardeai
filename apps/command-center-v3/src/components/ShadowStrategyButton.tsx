import { useState, useRef, useEffect, type CSSProperties } from 'react'
import { BB } from '../lib/watchlistTerminalTokens'

/*
 * ShadowStrategyButton — the "Build Full Strategy" control (Stage D).
 *
 * SHADOW ONLY. Pressing it POSTs /api/v2/shadow/strategy/build (which returns a
 * run_id in ~0.04s and runs the analysis in a detached worker), then polls
 * /api/v2/shadow/strategy/status until the run reaches a terminal state, and
 * renders the multidimensional decision packet.
 *
 * It does NOT replace the primary card or its legacy IGNORE label — that is the
 * card rebuild (§15), deliberately out of scope here. This is an additive panel
 * shown only when the operator asks for it, so the shadow architecture can be
 * inspected on a real symbol before anything about the production card changes.
 *
 * Nothing here queues, approves, submits, or confirms an order.
 *
 * Design: no raw hex (BB tokens only), no sub-10px fonts (the card's design
 * guard rejects both).
 */

type Family = { family: string; structure: string; state: string; rejection_reasons?: any[] }
type StageRow = { name: string; state: string }

const STATE_COLOR: Record<string, string> = {
  ELIGIBLE: BB.green,
  CONDITIONAL: BB.amber,
  REJECTED: BB.red,
  NOT_APPLICABLE: BB.text3,
  DATA_UNAVAILABLE: BB.text3,
}

const FAMILY_LABEL: Record<string, string> = {
  LONG_TERM: 'Long-term ownership',
  SWING: 'Tactical / swing',
  BEARISH: 'Bearish / short',
  OPTIONS: 'Options',
  NO_TRADE: 'No-trade case',
}
const FAMILY_ORDER = ['LONG_TERM', 'SWING', 'BEARISH', 'OPTIONS', 'NO_TRADE']

export default function ShadowStrategyButton({ symbol }: { symbol: string }) {
  const [open, setOpen] = useState(false)
  const [phase, setPhase] = useState<'idle' | 'running' | 'done' | 'failed'>('idle')
  const [stages, setStages] = useState<StageRow[]>([])
  const [currentStage, setCurrentStage] = useState<string | null>(null)
  const [packet, setPacket] = useState<any>(null)
  const [families, setFamilies] = useState<Family[]>([])
  const [err, setErr] = useState<string | null>(null)
  const timer = useRef<number | null>(null)

  useEffect(() => () => { if (timer.current) window.clearInterval(timer.current) }, [])

  // The api_v2 dispatcher wraps GET handler results as { ok, data: {...} } but
  // returns POST results unwrapped. `unwrap` handles both so this component does
  // not care which shape a given route uses — without it, the poll read s.stages
  // off the wrapper (undefined), never saw COMPLETE, and the panel spun forever
  // with the button visible but no result (the exact symptom observed).
  const unwrap = (j: any) => (j && typeof j === 'object' && 'data' in j && j.data ? j.data : j)

  const readback = async () => {
    try {
      const r = await fetch(`/api/v2/shadow/strategy/packet?symbol=${encodeURIComponent(symbol)}`)
      const j = unwrap(await r.json())
      if (j.ok) { setPacket(j.packet); setFamilies(j.blueprints || []) }
    } catch { /* packet endpoint optional; stages already tell the story */ }
  }

  const poll = (runId: number) => {
    if (timer.current) window.clearInterval(timer.current)
    timer.current = window.setInterval(async () => {
      try {
        const r = await fetch(`/api/v2/shadow/strategy/status?run_id=${runId}`)
        const s = unwrap(await r.json())
        if (!s.ok) return
        setStages(s.stages || [])
        setCurrentStage(s.current_stage || null)
        if (s.state === 'COMPLETE') {
          if (timer.current) window.clearInterval(timer.current)
          setPhase('done'); await readback()
        } else if (s.state === 'FAILED') {
          if (timer.current) window.clearInterval(timer.current)
          setPhase('failed'); setErr(s.failure_reason || 'run failed')
        }
      } catch { /* transient; keep polling */ }
    }, 1500)
  }

  const build = async (e: any) => {
    e.stopPropagation()
    setOpen(true); setPhase('running'); setErr(null); setPacket(null); setFamilies([])
    try {
      const r = await fetch('/api/v2/shadow/strategy/build', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, requested_by: 'operator' }),
      })
      const j = unwrap(await r.json())
      if (!j.ok) { setPhase('failed'); setErr(j.error || 'could not start'); return }
      poll(j.run_id)
    } catch (e: any) { setPhase('failed'); setErr(String(e?.message || e)) }
  }

  const btnStyle: CSSProperties = {
    fontSize: 10, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '.04em',
    cursor: 'pointer', color: phase === 'running' ? BB.text3 : BB.amber,
    background: 'transparent', border: `1px solid ${BB.amber}`, borderRadius: 2,
    padding: '2px 8px',
  }

  const mr = packet?.model_review
  const ev = packet?.event_state?.earnings
  const dq = packet?.data_quality

  return (
    <div style={{ width: '100%' }} onClick={e => e.stopPropagation()}>
      <button onClick={build} disabled={phase === 'running'} style={btnStyle}
        title="Shadow-only multidimensional analysis — long-term, swing, bearish and options families, blind model pass. Does not place, queue, approve, or submit anything.">
        {phase === 'running' ? '⏳ building full strategy…'
          : phase === 'done' ? '↻ rebuild full strategy'
          : '⚡ build full strategy (shadow)'}
      </button>

      {open && (
        <div style={{
          marginTop: 6, border: `1px solid ${BB.border}`, borderRadius: 2,
          background: BB.bgPanel, padding: 8, fontSize: 10.5, color: BB.text2,
        }}>
          {/* stage progress */}
          {phase === 'running' && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 4 }}>
              {stages.map(s => (
                <span key={s.name} style={{
                  fontSize: 10, fontWeight: 700, padding: '1px 5px', borderRadius: 2,
                  color: s.state === 'complete' ? BB.green : s.state === 'running' ? BB.amber
                    : s.state === 'failed' ? BB.red : BB.text3,
                  border: `1px solid ${s.state === 'running' ? BB.amber : BB.border}`,
                }}>{s.name}{s.name === currentStage ? '…' : ''}</span>
              ))}
              {stages.length === 0 && <span style={{ color: BB.text3 }}>queued…</span>}
            </div>
          )}

          {phase === 'failed' && (
            <div style={{ color: BB.red, fontWeight: 700 }}>
              FAILED — {err}
            </div>
          )}

          {phase === 'done' && packet && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              <div style={{ fontSize: 11, fontWeight: 800, color: BB.text0 }}>
                {packet.headline}
              </div>

              {/* the dimensions the one-word verdict collapsed */}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, color: BB.text3, fontSize: 10 }}>
                {ev && <span>EVENT <b style={{ color: ev.state === 'SCHEDULED' ? BB.amber : BB.text2 }}>
                  {ev.state}{ev.date ? ` ${ev.date}` : ''}</b></span>}
                {dq && <span>DATA <b style={{ color: dq.state === 'FRESH' ? BB.green : BB.amber }}>{dq.state}</b></span>}
                {mr && <span>MODELS <b style={{ color: mr.mode === 'BLIND' ? BB.green : BB.amber }}>
                  {mr.mode} {(mr.lanes_completed || []).length}/{(mr.lanes_requested || []).length}</b></span>}
              </div>

              {/* per-dimension model agreement — never one badge */}
              {mr?.agreement_by_dimension && (
                <div style={{ color: BB.text3, fontSize: 10 }}>
                  AGREE {Object.entries(mr.agreement_by_dimension).map(([d, v]: any) =>
                    `${d.replace('long_term_thesis', 'thesis').replace('tactical_timing', 'timing')} ${v}`).join(' · ')}
                </div>
              )}

              {/* every family, always present, colour-coded by state */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                {FAMILY_ORDER.map(fam => {
                  const rows = families.filter(f => f.family === fam)
                  const state = rows[0]?.state || 'DATA_UNAVAILABLE'
                  const reason = rows.map(r => (r.rejection_reasons || [])[0]).filter(Boolean)[0]
                  return (
                    <div key={fam} style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
                      <span style={{ minWidth: 118, color: BB.text2, fontWeight: 700 }}>{FAMILY_LABEL[fam]}</span>
                      <span style={{ minWidth: 96, fontWeight: 800, color: STATE_COLOR[state] || BB.text3 }}>{state}</span>
                      {reason && <span style={{ color: BB.text3, fontSize: 10 }}>{String(reason).slice(0, 88)}</span>}
                    </div>
                  )
                })}
              </div>

              {/* legacy label, explicitly demoted */}
              {packet.legacy_summary?.recommendation && (
                <div style={{ color: BB.text3, fontSize: 10, borderTop: `1px solid ${BB.border}`, paddingTop: 4 }}>
                  Legacy CIO: <b style={{ color: BB.text2 }}>{packet.legacy_summary.recommendation}</b> — {packet.legacy_summary.note}
                </div>
              )}
              <div style={{ color: BB.text3, fontSize: 10, fontStyle: 'italic' }}>
                Shadow analysis · advisory only · nothing queued or submitted
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
