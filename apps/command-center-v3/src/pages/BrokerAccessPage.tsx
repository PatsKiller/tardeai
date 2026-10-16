// Broker Access & Sync (operator 2026-10-16): one OPS page for broker access and sync. Read-only view of
// GET /api/v2/system/broker-access (scripts/lib/data_broker/broker_access.py): Schwab access mode + trading lock,
// Schwab token state per account (no token values), auto-reauth schedule, how to re-login, per-broker sync
// freshness (OK / STALE / DEGRADED / PAUSED / NEEDS_REAUTH, each with its reason), stop health, the operator's
// read-only sync command. There is NO run-sync control: it requires a broker-read grant + a ratified amendment.
import { useState, type CSSProperties, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { Chip, ChipRow } from '../components/primitives'
import { TOKENS, TYPE } from '../lib/watchTokens'
import { FONT, RADIUS, type Tone } from '../lib/designTokens'

type State = 'OK' | 'STALE' | 'DEGRADED' | 'PAUSED' | 'NEEDS_REAUTH'
type Step = { name?: string; rc?: number | null; signals?: string[] }
type BrokerRow = {
  id: string; label: string; broker?: string; state: State; reason: string; flags?: string[]
  last_success_at?: string | null; operator_log_step?: Step | null; note?: string | null
}
type TokenRow = {
  account_key: string; state: State; reason: string; token_condition?: State; has_token?: boolean
  last_login?: string | null; true_expiry?: string | null; days_left?: number | null; proactive_due_at?: string | null
  last_error?: string | null; last_failed_event?: { event?: string; status?: string; at?: string; detail?: string } | null
}
type Relogin = { label: string; href?: string; note?: string; steps: Array<{ text: string; command?: string }> }
export type BrokerAccessPayload = {
  schema?: string; as_of?: string; overall?: State
  access?: { mode?: string; paused?: boolean; since?: string | null; reason?: string | null; error?: string | null }
  trading_lock?: { locked?: boolean; reason?: string | null; refusals_today?: number; last_refusal?: { at?: string; broker?: string; action?: string; caller?: string } | null }
  schwab_tokens?: { db?: string; accounts?: TokenRow[]; auto_reauth?: Record<string, unknown> }
  brokers?: BrokerRow[]
  stop_health?: { state?: State; reason?: string; headline?: string | null; finished_at?: string | null; open_alert_count?: number; alerts_db?: string
    open_alerts?: Array<{ id?: number; at?: string; symbol?: string; severity?: string; message?: string }> }
  operator_sync_log?: { present?: boolean; path?: string | null; ran_at?: string | null; mode?: string | null; release?: string | null; steps?: Step[]; failed_steps?: string[]; note?: string }
  relogin?: { warning?: string | null; telegram?: Relogin; command_center?: Relogin }
  sync_command?: { run_by?: string; dry_run?: string; apply?: string; future_path?: string; future_note?: string; scope?: string; run_action?: { enabled?: boolean; reason?: string } }
  links?: Array<{ label: string; href: string }>
}

const STATE_TONE: Record<State, Tone> = { OK: 'success', STALE: 'warning', DEGRADED: 'danger', PAUSED: 'info', NEEDS_REAUTH: 'danger' }
const STATE_LABEL: Record<State, string> = { OK: 'OK', STALE: 'Stale', DEGRADED: 'Degraded', PAUSED: 'Paused', NEEDS_REAUTH: 'Needs re-auth' }
const panel: CSSProperties = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: 14, minWidth: 0 }
const cell: CSSProperties = { padding: '6px 6px', fontSize: TYPE.sm, color: TOKENS.text[1], verticalAlign: 'top', textAlign: 'left' }
const h2: CSSProperties = { margin: '0 0 8px', fontSize: TYPE.base, color: TOKENS.text[0] }
const muted: CSSProperties = { fontSize: TYPE.sm, color: TOKENS.text[2], margin: '4px 0' }
const code: CSSProperties = { fontFamily: FONT.mono, fontSize: TYPE.sm, color: TOKENS.text[0], background: TOKENS.bg[2], border: `1px solid ${TOKENS.borderSubtle}`, borderRadius: RADIUS.sm, padding: '4px 8px', overflowX: 'auto', whiteSpace: 'pre', flex: 1, minWidth: 0 }
const btn: CSSProperties = { fontSize: TYPE.sm, color: TOKENS.text[1], background: TOKENS.bg[2], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, padding: '3px 10px', cursor: 'pointer' }
const s = (v: unknown) => (v === null || v === undefined || v === '' ? '—' : String(v))
const et = (v: unknown) => {
  const t = Date.parse(String(v ?? ''))
  if (!Number.isFinite(t)) return s(v)
  return new Date(t).toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }) + ' ET'
}

function StateChip({ state }: { state?: State }) {
  if (!state) return <Chip tone="warning">Unknown</Chip>
  return <Chip tone={STATE_TONE[state] || 'warning'}>{STATE_LABEL[state] || state}</Chip>
}

function CopyLine({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false)
  const copy = () => {
    const ok = () => { setDone(true); setTimeout(() => setDone(false), 1500) }
    if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).then(ok).catch(() => setDone(false))
  }
  return <div style={{ display: 'flex', gap: 6, alignItems: 'center', minWidth: 0 }}>
    <code style={code}>{text}</code>
    <button type="button" aria-label={`Copy ${label}`} onClick={copy} style={btn}>{done ? 'Copied' : 'Copy'}</button>
  </div>
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return <div style={panel}><h2 style={h2}>{title}</h2>{children}</div>
}

function Table({ label, heads, rows }: { label: string; heads: string[]; rows: Array<Array<ReactNode>> }) {
  return <div style={{ overflowX: 'auto' }}>
    <table aria-label={label} style={{ width: '100%', borderCollapse: 'collapse' }}>
      <thead><tr>{heads.map(h => <th key={h} style={{ ...cell, color: TOKENS.text[3], whiteSpace: 'nowrap' }}>{h}</th>)}</tr></thead>
      <tbody>
        {rows.map((r, i) => <tr key={i} style={{ borderTop: `1px solid ${TOKENS.borderSubtle}` }}>{r.map((c, j) => <td key={j} style={cell}>{c ?? '—'}</td>)}</tr>)}
        {!rows.length ? <tr><td colSpan={heads.length} style={{ ...cell, color: TOKENS.text[2] }}>No rows</td></tr> : null}
      </tbody>
    </table>
  </div>
}

function StepSummary({ step }: { step?: Step | null }) {
  if (!step) return <span style={{ color: TOKENS.text[3] }}>not in log</span>
  return <span>rc={s(step.rc)}{step.signals?.length ? ` · ${step.signals.join(', ')}` : ''}</span>
}

function ReloginBlock({ r }: { r?: Relogin }) {
  if (!r) return null
  return <div style={{ display: 'grid', gap: 6, minWidth: 0 }}>
    <h3 style={{ ...h2, fontSize: TYPE.sm }}>{r.label}</h3>
    <ol style={{ margin: 0, paddingLeft: 18, display: 'grid', gap: 6 }}>
      {r.steps.map((st, i) => <li key={i} style={{ fontSize: TYPE.sm, color: TOKENS.text[1] }}>
        {st.text}{st.command ? <div style={{ marginTop: 4 }}><CopyLine text={st.command} label={`step ${i + 1} command`} /></div> : null}
      </li>)}
    </ol>
    {r.href ? <p style={muted}><a href={r.href} style={{ color: TOKENS.primary }}>Open the Schwab Reauth page</a></p> : null}
    {r.note ? <p style={muted}>{r.note}</p> : null}
  </div>
}

export default function BrokerAccessPage() {
  const api = useApi<BrokerAccessPayload>('/api/v2/system/broker-access', 60_000)
  const d = api.data
  const lock = d?.trading_lock
  const auto = d?.schwab_tokens?.auto_reauth || {}
  const log = d?.operator_sync_log
  const cmd = d?.sync_command
  return <section data-testid="broker-access" style={{ display: 'grid', gap: 12, minWidth: 0, maxWidth: '100%' }}>
    <div style={panel}>
      <h1 style={{ margin: 0, fontSize: TYPE.lg, color: TOKENS.text[0] }}>Broker Access & Sync</h1>
      <p style={muted}>Read-only. Access mode, trading lock, Schwab login state, sync freshness per broker and stop health, from receipts, logs and token metadata. No broker is called from this page.</p>
      <ChipRow>
        {api.error ? <Chip tone="warning">UNAVAILABLE</Chip> : api.loading && !d ? <Chip tone="neutral">Loading</Chip> : <StateChip state={d?.overall} />}
        <Chip tone={d?.access?.paused ? 'info' : 'neutral'}>Schwab mode {s(d?.access?.mode)}</Chip>
        <Chip tone={lock?.locked === false ? 'warning' : 'neutral'}>{lock?.locked === false ? 'Trading UNLOCKED' : 'Trading locked'}</Chip>
        <Chip tone="neutral">Observed {et(d?.as_of)}</Chip>
      </ChipRow>
      {api.error ? <p role="alert" style={muted}>Broker access read model unavailable. Nothing here is reported as healthy.</p> : null}
    </div>

    <Panel title="Access">
      <Table label="Access mode and trading lock" heads={['Control', 'State', 'Detail']} rows={[
        ['Schwab access mode', s(d?.access?.mode), `${s(d?.access?.reason)} · since ${et(d?.access?.since)}${d?.access?.error ? ` · ${d.access.error}` : ''}`],
        ['Trading lock', lock?.locked === false ? 'UNLOCKED' : 'LOCKED', s(lock?.reason)],
        ['Lock refusals today', s(lock?.refusals_today ?? 0), lock?.last_refusal ? `last ${et(lock.last_refusal.at)} · ${s(lock.last_refusal.broker)} ${s(lock.last_refusal.action)} · ${s(lock.last_refusal.caller)}` : '—'],
      ]} />
    </Panel>

    <Panel title="Schwab login (token state)">
      {d?.schwab_tokens?.db === 'unavailable' ? <p role="alert" style={muted}>Token store unreadable. Token state is unknown, not assumed healthy.</p> : null}
      <Table label="Schwab token state per account" heads={['Account', 'State', 'Days left', 'True expiry', 'Last login', 'Last error', 'Reason']}
        rows={(d?.schwab_tokens?.accounts || []).map(t => [t.account_key, <StateChip state={t.state} />, t.days_left ?? '—', et(t.true_expiry), et(t.last_login),
          t.last_error || (t.last_failed_event ? `${s(t.last_failed_event.event)} ${s(t.last_failed_event.status)} ${et(t.last_failed_event.at)}` : '—'), t.reason])} />
      <p style={muted}>Auto-reauth: {s(auto.mode)}; proactive on day {s(auto.reauth_at_days)} ({s(auto.proactive_due_at ? et(auto.proactive_due_at) : null)}), hours {Array.isArray(auto.allowed_hours_local) ? (auto.allowed_hours_local as number[]).join('–') : '—'} local, due now {auto.due_now ? 'yes' : 'no'}. Last attempt {et(auto.last_attempt_at)}: {s(auto.last_result)} {auto.last_error ? `(${String(auto.last_error)})` : ''}</p>
    </Panel>

    <Panel title="How to re-login">
      {d?.relogin?.warning ? <p role="alert" style={{ ...muted, color: TOKENS.warning }}>{d.relogin.warning}</p> : null}
      <div style={{ display: 'grid', gap: 14, gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))' }}>
        <ReloginBlock r={d?.relogin?.telegram} />
        <ReloginBlock r={d?.relogin?.command_center} />
      </div>
    </Panel>

    <Panel title="Sync freshness by broker">
      <Table label="Broker sync freshness" heads={['Source', 'State', 'Last success', 'Operator log step', 'Reason']}
        rows={(d?.brokers || []).map(b => [b.label, <span><StateChip state={b.state} />{(b.flags || []).filter(f => f !== b.state).map(f => <Chip key={f} tone={STATE_TONE[f as State] || 'warning'} style={{ marginLeft: 4 }}>{STATE_LABEL[f as State] || f}</Chip>)}</span>,
          et(b.last_success_at), <StepSummary step={b.operator_log_step} />, <span>{b.reason}{b.note ? <span style={{ display: 'block', color: TOKENS.text[2] }}>{b.note}</span> : null}</span>])} />
    </Panel>

    <Panel title="Stop health">
      <ChipRow><StateChip state={d?.stop_health?.state} /><Chip tone="neutral">check {et(d?.stop_health?.finished_at)}</Chip>
        <Chip tone={(d?.stop_health?.open_alert_count || 0) > 0 ? 'warning' : 'neutral'}>open stop alerts {d?.stop_health?.alerts_db === 'unavailable' ? 'unknown' : d?.stop_health?.open_alert_count ?? 0}</Chip></ChipRow>
      <p style={muted}>{s(d?.stop_health?.reason)}</p>
      <Table label="Open stop alerts" heads={['At', 'Symbol', 'Severity', 'Message']}
        rows={(d?.stop_health?.open_alerts || []).map(a => [et(a.at), s(a.symbol), s(a.severity), s(a.message)])} />
    </Panel>

    <Panel title="Operator sync (read-only)">
      <p style={muted}>Operator-run. {s(cmd?.scope)}. Moving to {s(cmd?.future_path)} ({s(cmd?.future_note)}).</p>
      <div style={{ display: 'grid', gap: 6 }}>
        {cmd?.dry_run ? <CopyLine text={cmd.dry_run} label="dry-run sync command" /> : null}
        {cmd?.apply ? <CopyLine text={cmd.apply} label="apply sync command" /> : null}
      </div>
      <p style={muted}>
        <button type="button" disabled aria-disabled="true" title={cmd?.run_action?.reason} style={{ ...btn, cursor: 'not-allowed', opacity: 0.6 }}>Run sync</button>
        {' '}Disabled: {s(cmd?.run_action?.reason)}.
      </p>
      <h3 style={{ ...h2, fontSize: TYPE.sm, marginTop: 10 }}>Latest operator run {log?.present ? `· ${s(log.mode)} · ${et(log.ran_at)} · release ${s(log.release)}` : ''}</h3>
      {log?.present ? <Table label="Operator sync log steps" heads={['Step', 'Exit', 'Signals']}
        rows={(log.steps || []).map(st => [s(st.name), <Chip tone={st.rc === 0 ? 'neutral' : 'danger'}>rc={s(st.rc)}</Chip>, (st.signals || []).join(', ') || '—'])} />
        : <p style={muted}>{s(log?.note)}</p>}
    </Panel>

    <Panel title="Related">
      <ChipRow>
        {(d?.links || []).map(l => <Link key={l.href} to={l.href.replace(/^\/v3/, '')} style={{ fontSize: TYPE.sm, color: TOKENS.primary, marginRight: 12 }}>{l.label}</Link>)}
      </ChipRow>
    </Panel>
  </section>
}
