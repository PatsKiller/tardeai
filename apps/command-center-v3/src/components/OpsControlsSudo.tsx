// Ops → Controls additions (feat/ops-controls-sudo-window-20261022), kept out of OpsControls.tsx so the page diff stays
// small while the Jobs & schedules tab is reworked on another branch.
//   SudoBanner      the open sudo window: remaining time, idle limit, the opening passkey, "End window now".
//                   The window is INERT until AGENTS.md >= 20.0.0 is ACTIVE and ops_controls.sudo_window_enabled is true;
//                   then one passkey assertion opens it and a risky act inside it needs only the typed phrase (except
//                   the always-fresh kinds). Server: scripts/lib/ops_controls_sudo.py.
//   KillSwitchCell  the global trading kill switch's real state, read-only, from the existing route
//                   GET /api/v2/execution/kill-switches (the one the Execution panel reads). Never writes.
import { useEffect, useState, type CSSProperties } from 'react'
import { useApi } from '../hooks/useApi'
import { Chip, ChipRow } from './primitives'
import { TOKENS, TYPE } from '../lib/watchTokens'
import { FONT, RADIUS, toneVars } from '../lib/designTokens'
import { fmtRemaining, killSwitchSummary, opsApi, sudoToken, type KillSwitchWire, type SudoWindowState } from '../lib/opsControls'

const et = (v: unknown) => {
  const t = Date.parse(String(v ?? ''))
  if (!Number.isFinite(t)) return '—'
  return new Date(t).toLocaleString('en-US', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hour12: false }) + ' ET'
}

/** Seconds left, counted down locally between the 15 s state refreshes (never below the server's own end times). */
function useCountdown(remaining: number | undefined, key: string | undefined): number {
  const [left, setLeft] = useState(remaining ?? 0)
  useEffect(() => {
    setLeft(remaining ?? 0)
    if (!remaining) return
    const t0 = Date.now()
    const id = setInterval(() => setLeft(Math.max(0, (remaining ?? 0) - Math.floor((Date.now() - t0) / 1000))), 1000)
    return () => clearInterval(id)
  }, [remaining, key])
  return left
}

export function SudoBanner({ sw, onChanged }: { sw: SudoWindowState | undefined; onChanged: () => void }) {
  const w = sw?.window || null
  const left = useCountdown(w?.remaining_s, w ? `${w.window_id8}:${w.uses}:${w.remaining_s}` : undefined)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const hasToken = !!sudoToken.get()
  useEffect(() => { if (!w && hasToken) sudoToken.clear() }, [w, hasToken])
  if (!sw) return null
  if (sw.state !== 'ACTIVE' || !w) {
    return <p style={{ fontSize: TYPE.sm, color: TOKENS.text[2], margin: 0 }} data-testid="ops-sudo-status">
      Sudo window {sw.state === 'ACTIVE' ? `available: tick “open a sudo window” on your next passkey step-up (${sw.minutes ?? 60} min, ends after ${sw.idle_minutes ?? 15} idle min)` : `inert — ${sw.reason || 'no reason reported'}`}.
    </p>
  }
  const end = async () => {
    setBusy(true); setErr(null)
    try { await opsApi.sudoEnd(); sudoToken.clear(); onChanged() } catch (e) { setErr(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  const t = toneVars('warning')
  const box: CSSProperties = { background: t.bg, border: `1px solid ${t.border}`, borderRadius: RADIUS.md, padding: '10px 12px', minWidth: 0, display: 'grid', gap: 6 }
  return <div role="status" aria-live="polite" style={box} data-testid="ops-sudo-banner">
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', justifyContent: 'space-between' }}>
      <span style={{ fontSize: TYPE.base, fontWeight: 700, color: t.color }}>Sudo window open — {fmtRemaining(left)} left</span>
      <button type="button" disabled={busy} onClick={end} style={{ fontSize: TYPE.base, fontWeight: 600, borderRadius: RADIUS.sm, padding: '6px 10px', minHeight: 32, cursor: busy ? 'not-allowed' : 'pointer', color: t.color, background: TOKENS.bg[2], border: `1px solid ${t.border}` }}>
        {busy ? 'Ending…' : 'End window now'}
      </button>
    </div>
    <ChipRow>
      <Chip tone="neutral">ends {et(w.expires_at)} at the latest</Chip>
      <Chip tone="neutral">idle limit {et(w.idle_expires_at)}</Chip>
      <Chip tone="neutral">opened {et(w.opened_at)} by passkey {w.credential_name || w.credential_id8}</Chip>
      <Chip tone="neutral">{w.uses} act{w.uses === 1 ? '' : 's'} in this window</Chip>
    </ChipRow>
    <span style={{ fontSize: TYPE.sm, color: TOKENS.text[1] }}>
      Risky changes need only the typed phrase while it is open{hasToken ? '' : ' — but this browser session does not hold the window (it was opened elsewhere), so here a passkey is still asked for'}.
      Grants, kill-switch clear, passkeys, the release train and the sudo-window settings always ask for a fresh passkey.
      Every act is audited with the opening assertion <span style={{ fontFamily: FONT.mono }}>{w.opening_assertion_id}</span>.
    </span>
    {err ? <span role="alert" style={{ fontSize: TYPE.sm, color: TOKENS.danger }}>{err}</span> : null}
  </div>
}

export function KillSwitchCell() {
  const api = useApi<KillSwitchWire>('/api/v2/execution/kill-switches', 30_000)
  const k = killSwitchSummary(api.data, api.error)
  const tone = k.state === 'ENGAGED' ? 'danger' : k.state === 'CLEAR' ? 'success' : 'warning'
  return <span style={{ display: 'grid', gap: 2 }} data-testid="ops-kill-switch-state">
    <ChipRow><Chip tone={tone}>{k.state}</Chip>{k.others ? <Chip tone="warning">{k.others} narrower switch{k.others === 1 ? '' : 'es'} engaged</Chip> : null}</ChipRow>
    <span style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>{k.text} · read-only, from /api/v2/execution/kill-switches</span>
  </span>
}
