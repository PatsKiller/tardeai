import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { RADIUS } from '../../lib/designTokens'
import type { Intent } from './StandingIntentsPanel'

const field: CSSProperties = { display: 'grid', gap: 4, marginBottom: 12 }
const input: CSSProperties = { padding: 8, color: 'var(--text-0)', background: 'var(--bg-1)', border: '1px solid var(--border-color)', borderRadius: RADIUS.sm }

/** Edits advisory preferences on the existing ticker directive. Preview before save; no orders. */
export default function StandingIntentModal({ intents, onClose, onSaved }: {
  intents: Intent[]; onClose: () => void; onSaved: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [symbol, setSymbol] = useState('')
  const [target, setTarget] = useState('')
  const [csp, setCsp] = useState(false), [cc, setCc] = useState(false), [leap, setLeap] = useState(false)
  const [putMax, setPutMax] = useState(''), [callMin, setCallMin] = useState('')
  const [minDte, setMinDte] = useState('20'), [maxDte, setMaxDte] = useState('50')
  const [leapDte, setLeapDte] = useState('365'), [leapDelta, setLeapDelta] = useState('0.70')
  const [avoidEarnings, setAvoidEarnings] = useState(true), [rationale, setRationale] = useState('')
  const [preview, setPreview] = useState<any>(null), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const existing = intents.find(i => i.symbol === symbol.trim().toUpperCase())
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    dialog.current?.showModal()
    return () => { opener?.focus() }
  }, [])
  useEffect(() => {
    const p = existing?.plays || {}
    setTarget(existing?.thesis_target == null ? '' : String(existing.thesis_target))
    setCsp(!!p.cash_secured_put); setCc(!!p.covered_call); setLeap(!!p.leap_call)
    setPutMax(p.cash_secured_put?.strike_max == null ? '' : String(p.cash_secured_put.strike_max))
    setCallMin(p.covered_call?.min_strike == null ? '' : String(p.covered_call.min_strike))
    const dte = (p.cash_secured_put?.dte || p.covered_call?.dte || [20, 50]) as number[]
    setMinDte(String(dte[0])); setMaxDte(String(dte[1]))
    setLeapDte(String(p.leap_call?.min_dte || 365)); setLeapDelta(String(p.leap_call?.min_delta || .7))
    setAvoidEarnings(existing?.avoid_earnings_cross ?? true); setRationale(existing?.rationale || '')
    setPreview(null); setError('')
  }, [existing])
  const number = (v: string, name: string, min = 0) => {
    const x = Number(v)
    if (!v.trim() || !Number.isFinite(x) || x <= min) throw new Error(`${name} must be greater than ${min}.`)
    return x
  }
  function draft() {
    const sym = symbol.trim().toUpperCase()
    if (!/^[A-Z][A-Z0-9.\-]{0,9}$/.test(sym)) throw new Error('Enter a valid ticker symbol.')
    if (!csp && !cc && !leap) throw new Error('Choose at least one strategy.')
    const dte = [number(minDte, 'Minimum days'), number(maxDte, 'Maximum days')]
    if (dte[0] > dte[1] || dte.some(n => !Number.isInteger(n) || n > 3650)) throw new Error('Use whole days in ascending order, up to 3650.')
    const plays: Record<string, Record<string, unknown>> = {}
    if (csp) plays.cash_secured_put = { ...existing?.plays?.cash_secured_put, dte, strike_max: number(putMax, 'Maximum purchase strike') }
    if (cc) plays.covered_call = { ...existing?.plays?.covered_call, dte, min_strike: number(callMin, 'Minimum sale strike') }
    if (leap) {
      const minDelta = number(leapDelta, 'Minimum delta'), days = number(leapDte, 'Minimum LEAP days')
      if (minDelta > 1 || days < 180 || days > 3650 || !Number.isInteger(days)) throw new Error('LEAP days must be 180–3650; delta must be above 0 and at most 1.')
      plays.leap_call = { ...existing?.plays?.leap_call, min_dte: days, min_delta: minDelta }
    }
    return { symbol: sym, status: 'active', thesis_target: target.trim() ? number(target, 'Target') : null,
      thesis_source: 'Operator standing plan in Command Center', goals: [csp && 'accumulate', cc && 'income', leap && 'upside'].filter(Boolean),
      plays, avoid_earnings_cross: avoidEarnings, earnings_estimate: existing?.earnings_estimate,
      rationale, source: 'operator_command_center' }
  }
  async function submit(save: boolean) {
    setError(''); setBusy(true)
    try {
      const body = save ? { ...preview.intent, source: 'operator_command_center', expected_intent_updated_at: preview.previous_intent?.updated_at ?? null } : draft()
      const response = await fetch('/api/v2/options/intents', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...body, dry_run: !save }) })
      const result = await response.json()
      if (!response.ok || !result.ok) throw new Error(result.error || `Unable to ${save ? 'save' : 'preview'} (${response.status}).`)
      if (save) { onSaved(); onClose() } else setPreview(result)
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to save the plan.'); if (save) setPreview(null) }
    finally { setBusy(false) }
  }
  return <dialog ref={dialog} aria-labelledby="standing-plan-title" onCancel={e => { e.preventDefault(); if (!busy) onClose() }}
    style={{ width: 'min(620px, 92vw)', maxHeight: '85vh', overflow: 'auto', padding: 20, color: 'var(--text-0)', background: 'var(--bg-0)', border: '1px solid var(--border-color)', borderRadius: RADIUS.md }}>
    <h2 id="standing-plan-title">Create standing plan</h2>
    <p>Tell the options matcher what to look for. Saving records an advisory preference; account allocation, CIO review and order approval remain separate.</p>
    <form onSubmit={e => { e.preventDefault(); void submit(!!preview) }}>
      <fieldset disabled={busy || !!preview} style={{ border: 0, padding: 0 }} onChange={() => setPreview(null)}>
        <label style={field}>Ticker<input autoFocus style={input} value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())} maxLength={10} required /></label>
        {existing && <p>Editing the existing standing plan for {existing.symbol}. Preview shows the previous plan.</p>}
        <label style={field}>Thesis target (optional)<input style={input} type="number" min="0.01" step="any" value={target} onChange={e => setTarget(e.target.value)} /></label>
        <label style={field}><span><input type="checkbox" checked={csp} onChange={e => setCsp(e.target.checked)} /> Accumulate shares with cash-secured puts</span></label>
        {csp && <label style={field}>Maximum purchase strike<input style={input} type="number" min="0.01" step="any" value={putMax} onChange={e => setPutMax(e.target.value)} required /></label>}
        <label style={field}><span><input type="checkbox" checked={cc} onChange={e => setCc(e.target.checked)} /> Income from covered calls on held shares</span></label>
        {cc && <label style={field}>Minimum acceptable sale strike<input style={input} type="number" min="0.01" step="any" value={callMin} onChange={e => setCallMin(e.target.value)} required /></label>}
        {(csp || cc) && <div style={{ display: 'flex', gap: 16 }}>
          <label style={field}>Minimum days to expiry<input style={input} type="number" min={1} max={3650} value={minDte} onChange={e => setMinDte(e.target.value)} required /></label>
          <label style={field}>Maximum days to expiry<input style={input} type="number" min={1} max={3650} value={maxDte} onChange={e => setMaxDte(e.target.value)} required /></label>
        </div>}
        <label style={field}><span><input type="checkbox" checked={leap} onChange={e => setLeap(e.target.checked)} /> Long-dated calls for upside exposure (LEAP)</span></label>
        {leap && <div style={{ display: 'flex', gap: 16 }}>
          <label style={field}>Minimum LEAP days<input style={input} type="number" min={180} max={3650} value={leapDte} onChange={e => setLeapDte(e.target.value)} required /></label>
          <label style={field}>Minimum LEAP delta<input style={input} type="number" min={.01} max={1} step={.01} value={leapDelta} onChange={e => setLeapDelta(e.target.value)} required /></label>
        </div>}
        <label style={field}><span><input type="checkbox" checked={avoidEarnings} onChange={e => setAvoidEarnings(e.target.checked)} /> Calls/puts expire before the recorded earnings date</span><small>Applies when an earnings date is known; long-dated calls may span earnings.</small></label>
        <label style={field}>Your reasoning<textarea style={input} value={rationale} onChange={e => setRationale(e.target.value)} maxLength={2000} /></label>
      </fieldset>
      {preview && <section aria-label="Standing plan preview">
        <strong>{preview.action === 'update' ? 'Update' : 'Create'} advisory plan for {preview.symbol}</strong>
        <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12 }}>{JSON.stringify({ target: preview.intent.thesis_target, strategies: preview.intent.plays, avoid_earnings_cross: preview.intent.avoid_earnings_cross }, null, 2)}</pre>
        {preview.previous_intent && <details><summary>Previous standing plan</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(preview.previous_intent, null, 2)}</pre></details>}
        <p>Saved plans wait for the existing scheduled matcher. No immediate chain fetch, model request or trade is submitted.</p>
      </section>}
      {error && <p role="alert">{error}</p>}
      <div style={{ display: 'flex', gap: 12 }}>
        <button type="button" onClick={onClose} disabled={busy}>Cancel</button>
        {preview && <button type="button" onClick={() => setPreview(null)} disabled={busy}>Edit plan</button>}
        <button type="submit" disabled={busy}>{busy ? 'Working…' : preview ? 'Save advisory plan' : 'Preview plan'}</button>
      </div>
    </form>
  </dialog>
}
