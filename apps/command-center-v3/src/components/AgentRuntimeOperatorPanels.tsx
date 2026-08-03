import { useState, type CSSProperties, type ReactNode } from 'react'
import { BB, T, TYPE, numStyle } from '../lib/watchTokens'
import { fmtDeskAge, fmtDeskTimestamp } from '../lib/fmtTimestamp'
import type { FleetRunPulse } from '../lib/agentRuntimeRunRollup'
import type { AgentRunRollupEntry } from '../lib/agentRuntimeRunRollup'
import type { ResolvedReadinessView } from '../lib/agentRuntimeReadiness'
import type { AgentOperationsEntry } from '../lib/agentRuntimeOperations'
import { manualRunCommand } from '../lib/agentRuntimeReadiness'
import { dispatchAgentRun } from '../lib/agentRuntimeDispatch'
import {
  fleetNameCollisionNote,
  normalizeSubsystem,
  openClawCollisionNote,
  SUBSYSTEM_LABELS,
  subsystemChipTone,
  subsystemExplainer,
} from '../lib/agentSubsystem'

type BadgeTone = 'blue' | 'green' | 'amber' | 'red' | 'slate'

const badgeTone: Record<BadgeTone, { color: string; background: string; border: string }> = {
  blue: { color: T.link, background: 'rgba(96,165,250,.12)', border: 'rgba(96,165,250,.34)' },
  green: { color: BB.green, background: BB.greenDim, border: 'rgba(34,197,94,.34)' },
  amber: { color: BB.amber, background: BB.amberDim, border: 'rgba(255,176,0,.34)' },
  red: { color: BB.red, background: BB.redDim, border: 'rgba(239,68,68,.34)' },
  slate: { color: BB.text3, background: 'rgba(148,163,184,.10)', border: 'rgba(148,163,184,.28)' },
}

const panel: CSSProperties = {
  background: 'var(--bg1)',
  border: '1px solid var(--border)',
  borderRadius: 10,
  padding: 14,
}

function StatusBadge({ children, tone = 'blue' }: { children: ReactNode; tone?: BadgeTone }) {
  const colors = badgeTone[tone]
  return <span style={{
    display: 'inline-flex', alignItems: 'center', padding: '2px 7px', borderRadius: 999,
    border: `1px solid ${colors.border}`, background: colors.background, color: colors.color,
    fontSize: TYPE.xs, fontWeight: 800,
  }}>{children}</span>
}

export function SubsystemChip({ subsystem, agentId }: { subsystem?: string | null; agentId?: string }) {
  const norm = normalizeSubsystem(subsystem)
  const tip = agentId ? subsystemExplainer(norm, agentId) : SUBSYSTEM_LABELS[norm]
  return <span title={tip}><StatusBadge tone={subsystemChipTone(norm)}>{SUBSYSTEM_LABELS[norm]}</StatusBadge></span>
}

export function OpenClawPersonaChip({ registered, model }: { registered?: boolean; model?: string | null }) {
  if (!registered) return <span style={{ fontSize: TYPE.xs, color: 'var(--text3)' }}>—</span>
  return <span title={`OpenClaw gateway persona · model ${model ?? 'default'}`}>
    <StatusBadge tone="amber">OC persona</StatusBadge>
    {model && <span style={{ marginLeft: 4, fontSize: TYPE.xs, color: 'var(--text3)', fontFamily: 'var(--mono)' }}>{model}</span>}
  </span>
}

export function ColumnHeaderTip({ label, tip }: { label: string; tip: string }) {
  return <span title={tip} style={{ cursor: 'help', borderBottom: '1px dotted var(--text3)' }}>{label} ?</span>
}

export function FleetOperationsBar({
  pulse,
  readiness,
  healthMonitor,
  runtimeLive,
  asOf,
  lastRefresh,
  criticLanesEnabled,
}: {
  pulse: FleetRunPulse | null
  readiness: ResolvedReadinessView
  healthMonitor?: {
    state: string
    last_checked_at: string | null
    detail: string
  } | null
  runtimeLive: boolean
  asOf: string
  lastRefresh: string
  criticLanesEnabled?: boolean | null
}) {
  const dispatch = readiness.payload?.wiring?.dispatch
  const dispatchTone: BadgeTone = dispatch?.state === 'WIRED' ? 'green' : 'amber'
  return <div style={{ ...panel, padding: '12px 14px' }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
      <div style={{ fontSize: TYPE.md, fontWeight: 800 }}>Fleet operations</div>
      <span style={{ fontSize: TYPE.xs, color: 'var(--text3)', fontFamily: 'var(--mono)' }}>
        refreshed {fmtDeskTimestamp(lastRefresh) ?? lastRefresh} · as_of {fmtDeskTimestamp(asOf) ?? asOf}
      </span>
    </div>
    <div style={{ marginTop: 10, display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(200px,1fr))', gap: 10 }}>
      <div style={{ padding: 10, borderRadius: 8, background: 'var(--bg2)' }}>
        <div style={{ fontSize: TYPE.xs, color: 'var(--text3)', marginBottom: 6 }} title="Counts from the latest runs listing (read API).">Run pulse</div>
        {runtimeLive && pulse ? <>
          <div style={{ ...numStyle, fontSize: TYPE.sm, fontWeight: 800 }}>
            {pulse.completed} completed · {pulse.failed} failed · {pulse.running} running
          </div>
          <div style={{ marginTop: 4, fontSize: TYPE.xs, color: 'var(--text2)' }}>
            {pulse.newestStartedAt
              ? `Latest fleet run ${fmtDeskAge(pulse.newestStartedAt) ?? ''} (${fmtDeskTimestamp(pulse.newestStartedAt) ?? ''})`
              : 'No runs in listing'}
          </div>
        </> : <div style={{ fontSize: TYPE.xs, color: 'var(--text3)' }}>Connect read API for live run pulse.</div>}
      </div>
      <div style={{ padding: 10, borderRadius: 8, background: 'var(--bg2)' }}>
        <div style={{ fontSize: TYPE.xs, color: 'var(--text3)', marginBottom: 6 }} title="Dispatch env + kill switch; does not execute from this panel unless Run now is used.">Dispatch posture</div>
        <StatusBadge tone={dispatchTone}>{dispatch?.state?.replace(/_/g, ' ') ?? 'UNKNOWN'}</StatusBadge>
        <div style={{ marginTop: 6, fontSize: TYPE.xs, color: 'var(--text2)' }}>
          kill switch {dispatch?.kill_switch_present ? 'ON' : 'OFF'} · provider {dispatch?.provider_module_configured ? 'set' : 'missing'}
        </div>
      </div>
      <div style={{ padding: 10, borderRadius: 8, background: 'var(--bg2)' }}>
        <div style={{ fontSize: TYPE.xs, color: 'var(--text3)', marginBottom: 6 }}>Runtime health monitor</div>
        <StatusBadge tone={healthMonitor?.state === 'HEALTHY' ? 'green' : healthMonitor?.state === 'DEGRADED' ? 'amber' : 'slate'}>
          {healthMonitor?.state?.replace(/_/g, ' ') ?? 'UNKNOWN'}
        </StatusBadge>
        <div style={{ marginTop: 6, fontSize: TYPE.xs, color: 'var(--text2)', lineHeight: 1.45 }}>
          {healthMonitor?.last_checked_at
            ? `checked ${fmtDeskAge(healthMonitor.last_checked_at) ?? fmtDeskTimestamp(healthMonitor.last_checked_at)}`
            : 'No monitor observation yet.'}
        </div>
      </div>
      <div style={{ padding: 10, borderRadius: 8, background: 'var(--bg2)' }}>
        <div style={{ fontSize: TYPE.xs, color: 'var(--text3)', marginBottom: 6 }} title="AGENT_RUNTIME_CRITIC_LANES — cloud/local LLM escalation for iris, hermes, alex, reflection, aegis.">Critic LLM lanes</div>
        <StatusBadge tone={criticLanesEnabled ? 'green' : 'amber'}>
          {criticLanesEnabled ? 'ENABLED' : 'OFF'}
        </StatusBadge>
        <div style={{ marginTop: 6, fontSize: TYPE.xs, color: 'var(--text2)', lineHeight: 1.45 }}>
          {criticLanesEnabled
            ? 'Severity-gated cloud/local escalation active for TEXT_ONLY and LOCAL_ONLY critics.'
            : 'Deterministic-only critics; set AGENT_RUNTIME_CRITIC_LANES=1 to enable model lanes.'}
        </div>
      </div>
      <div style={{ padding: 10, borderRadius: 8, background: 'var(--bg2)' }}>
        <div style={{ fontSize: TYPE.xs, color: 'var(--text3)', marginBottom: 6 }}>Dashboard refresh</div>
        <div style={{ fontSize: TYPE.xs, color: 'var(--text2)', lineHeight: 1.45 }}>
          Page polls every 60s. This is display refresh, not an agent schedule.
        </div>
      </div>
    </div>
  </div>
}

export function ReadinessFallbackBanner({ detail }: { detail: string }) {
  return <div style={{ ...panel, borderColor: 'rgba(255,176,0,.34)', background: BB.amberDim, padding: '10px 14px' }}>
    <div style={{ fontSize: TYPE.sm, fontWeight: 800, color: BB.amber }}>Operator wiring unavailable</div>
    <div style={{ marginTop: 4, fontSize: TYPE.xs, color: 'var(--text1)', lineHeight: 1.45 }}>
      {detail}. Deploy <code style={{ fontFamily: 'var(--mono)' }}>GET /api/v3/agent-runtime/readiness</code> on the server to see dispatch gates and copy-run commands.
    </div>
  </div>
}

export function RunAgeCell({ rollup }: { rollup?: AgentRunRollupEntry }) {
  if (!rollup?.lastStartedAt) {
    return <span style={{ fontSize: TYPE.xs, color: 'var(--text3)' }} title="No run recorded for this agent in the runs listing.">never</span>
  }
  const abs = fmtDeskTimestamp(rollup.lastStartedAt)
  const rel = fmtDeskAge(rollup.lastStartedAt)
  return <div style={{ fontSize: TYPE.xs, color: 'var(--text2)', fontFamily: 'var(--mono)', lineHeight: 1.35 }}>
    <div>{rel ?? abs ?? '—'}</div>
    {abs && <div style={{ color: 'var(--text3)', whiteSpace: 'nowrap' }}>{abs}</div>}
  </div>
}

export function RunOutcomeCell({ rollup }: { rollup?: AgentRunRollupEntry }) {
  if (!rollup?.lastStatus) return <span style={{ fontSize: TYPE.xs, color: 'var(--text3)' }}>—</span>
  const tone: BadgeTone = rollup.lastStatus === 'COMPLETED' ? 'green' : rollup.lastStatus === 'FAILED' ? 'red' : 'slate'
  return <StatusBadge tone={tone}>{rollup.lastStatus}</StatusBadge>
}

export function ScheduleCell({ ops }: { ops?: AgentOperationsEntry }) {
  if (!ops) return <span style={{ fontSize: TYPE.xs, color: 'var(--text3)' }}>—</span>
  const timerTone: BadgeTone = ops.timer_state === 'ACTIVE' ? 'green' : ['NOT_INSTALLED', 'NOT_APPLICABLE'].includes(ops.timer_state) ? 'slate' : 'amber'
  const sourceTone: BadgeTone = ops.source_state === 'READY' ? 'green' : ops.source_state === 'BLOCKED_SOURCE' ? 'red' : 'amber'
  const stateLabel = ops.timer_state === 'NOT_INSTALLED'
    ? (ops.schedule_mode === 'EVENT_DRIVEN' ? 'TRIGGER DESIGNED' : 'NOT SCHEDULED')
    : ops.timer_state === 'NOT_APPLICABLE' ? 'NOT RUNNABLE' : ops.timer_state.replace(/_/g, ' ')
  const queueLabel = ops.queue_depth != null && ops.queue_depth > 0
    ? `queue ${ops.queue_depth}${ops.oldest_queued_source_at ? ` · oldest ${fmtDeskTimestamp(ops.oldest_queued_source_at) ?? ops.oldest_queued_source_at}` : ''}`
    : ops.autonomy?.event_queue_state === 'READY'
      ? 'queue empty'
      : 'queue unverified'
  return <div>
    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
      <StatusBadge tone={timerTone}>{stateLabel}</StatusBadge>
      {ops.source_state && <StatusBadge tone={sourceTone}>{ops.source_state.replace(/_/g, ' ')}</StatusBadge>}
    </div>
    <div style={{ marginTop: 3, fontSize: TYPE.xs, color: 'var(--text3)', lineHeight: 1.35 }} title={ops.designed_schedule}>
      {ops.next_timer_at
        ? `next ${fmtDeskTimestamp(ops.next_timer_at) ?? ops.next_timer_at}`
        : ops.configured_calendar
          ? `calendar ${ops.configured_calendar}`
          : 'next: not scheduled'}
    </div>
    <div style={{ fontSize: TYPE.xs, color: 'var(--text3)' }}>{queueLabel}</div>
    {ops.last_trigger_at && <div style={{ fontSize: TYPE.xs, color: 'var(--text3)' }}>
      last trigger {ops.last_trigger_kind?.replace(/_/g, ' ') ?? 'event'} · {fmtDeskTimestamp(ops.last_trigger_at) ?? ops.last_trigger_at}
    </div>}
    {ops.last_timer_run_at && <div style={{ fontSize: TYPE.xs, color: 'var(--text3)' }}>
      timer last {fmtDeskTimestamp(ops.last_timer_run_at) ?? ops.last_timer_run_at}
    </div>}
  </div>
}

export function OperatorActionCell({
  agentId,
  dispatchOperable,
  runTemplate,
  dispatchWired,
  operations,
  onDispatched,
}: {
  agentId: string
  dispatchOperable: boolean
  runTemplate?: string
  dispatchWired: boolean
  operations?: AgentOperationsEntry
  onDispatched?: () => void
}) {
  const [copied, setCopied] = useState(false)
  const [modal, setModal] = useState(false)
  const [about, setAbout] = useState(false)
  const cmd = manualRunCommand(agentId, runTemplate)
  const canRun = dispatchOperable && dispatchWired
  const observabilityOnly = operations?.schedule_mode === 'NOT_RUNNABLE'
  const runTitle = canRun
    ? 'Queue one bounded SHADOW batch'
    : !dispatchWired
      ? 'Dispatch not WIRED — run deploy_operator_wiring.sh --execute'
      : 'Agent not dispatch-operable in fleet registry (enable SHADOW in definitions.py)'

  return <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }} onClick={e => e.stopPropagation()}>
    <button type="button" title="What this agent does, interacts with, and when it runs"
      onClick={() => setAbout(true)}
      style={{ fontSize: TYPE.xs, fontWeight: 750, padding: '3px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg1)', cursor: 'pointer', color: 'var(--text2)' }}>
      About
    </button>
    {observabilityOnly ? <StatusBadge tone="slate">OBSERVABILITY ONLY</StatusBadge> : <>
    <button type="button" title={cmd}
      onClick={() => void navigator.clipboard.writeText(cmd).then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000) })}
      style={{ fontSize: TYPE.xs, fontWeight: 750, padding: '3px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg1)', cursor: 'pointer', color: T.link }}>
      {copied ? 'Copied' : 'Copy LAB cmd'}
    </button>
    <button type="button" disabled={!canRun} title={runTitle}
      onClick={() => setModal(true)}
      style={{ fontSize: TYPE.xs, fontWeight: 750, padding: '3px 8px', borderRadius: 6, border: '1px solid var(--border)', background: canRun ? 'rgba(96,165,250,.12)' : 'var(--bg2)', cursor: canRun ? 'pointer' : 'not-allowed', color: canRun ? T.link : 'var(--text3)' }}>
      Run now
    </button>
    </>}
    {modal && <RunNowModal agentId={agentId} onClose={() => setModal(false)} onDone={() => { setModal(false); onDispatched?.() }} />}
    {about && <AgentDescriptionModal agentId={agentId} operations={operations} onClose={() => setAbout(false)} />}
  </div>
}

function AgentDescriptionModal({
  agentId,
  operations,
  onClose,
}: {
  agentId: string
  operations?: AgentOperationsEntry
  onClose: () => void
}) {
  const field = (name: string, value: ReactNode) => <div style={{ padding: '8px 0', borderBottom: '1px solid var(--border-subtle)' }}>
    <div style={{ fontSize: TYPE.xs, color: 'var(--text3)', fontWeight: 800, textTransform: 'uppercase' }}>{name}</div>
    <div style={{ marginTop: 3, fontSize: TYPE.sm, color: 'var(--text1)', lineHeight: 1.5 }}>{value}</div>
  </div>
  const autonomy = operations?.autonomy
  const collision = fleetNameCollisionNote(agentId)
  return <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.62)', zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }} onClick={onClose}>
    <div style={{ ...panel, width: 'min(720px, 96vw)', maxHeight: '88vh', overflowY: 'auto' }} onClick={e => e.stopPropagation()}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
        <div>
          <div style={{ fontSize: TYPE.lg, fontWeight: 850 }}>{operations?.display_name ?? agentId} <span style={{ fontSize: TYPE.xs, color: 'var(--text3)' }}>(Fleet)</span></div>
          <div style={{ marginTop: 4, display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            <SubsystemChip subsystem={operations?.subsystem} />
            <span style={{ fontSize: TYPE.xs, color: 'var(--text3)', fontFamily: 'var(--mono)' }}>{agentId}</span>
          </div>
        </div>
        <button type="button" onClick={onClose} style={{ border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)', borderRadius: 6, cursor: 'pointer', height: 28 }}>Close</button>
      </div>
      {collision && <div style={{ marginTop: 10, padding: '8px 10px', borderRadius: 6, border: `1px solid ${BB.amber}`, background: BB.amberDim, fontSize: TYPE.xs, color: 'var(--text1)', lineHeight: 1.5 }}>
        <b>Name collision:</b> {collision}
      </div>}
      <div style={{ marginTop: 10, fontSize: TYPE.xs, fontWeight: 800, color: 'var(--text3)', textTransform: 'uppercase' }}>Identity card (governed contract)</div>
      {field('Owner', operations?.owner ?? 'architecture-owner')}
      {field('Subsystem', operations?.subsystem ? SUBSYSTEM_LABELS[normalizeSubsystem(operations.subsystem)] : '—')}
      {field('Allowed tools', operations?.allowed_tools?.length ? operations.allowed_tools.join(' · ') : '—')}
      {field('Denied tools', operations?.denied_tools?.length ? operations.denied_tools.join(' · ') : '—')}
      {field('Retrieval required', operations?.retrieval_required === true ? 'Yes' : operations?.retrieval_required === false ? 'No' : '—')}
      {field('What it does', operations?.summary ?? 'No governed runtime description is installed.')}
      {field('Role', operations?.role ?? 'Observability-only catalog row')}
      {field('Autonomy', autonomy
        ? <><b>Current mode: {autonomy.execution.replace(/_/g, ' ')}</b>. Capability: {autonomy.capability.replace(/_/g, ' ')}. Event queue: {autonomy.event_queue_state.replace(/_/g, ' ')}. Per-run operator approval: <b>{autonomy.per_run_operator_approval_required === false ? 'No' : autonomy.per_run_operator_approval_required === true ? 'Yes' : 'N/A'}</b>. It cannot schedule itself and has <b>no financial authority</b>.</>
        : 'No autonomous runtime is installed.')}
      {field('Runs when', operations?.triggers?.length
        ? <ul style={{ margin: '0 0 0 18px', padding: 0 }}>{operations.triggers.map(trigger => <li key={`${trigger.kind}:${trigger.description}`}><b>{trigger.kind.replace(/_/g, ' ')}</b> — {trigger.description}</li>)}</ul>
        : 'It does not run; no governed trigger contract exists.')}
      {field('Trigger source', operations?.source_state
        ? <><b>{operations.source_state.replace(/_/g, ' ')}</b>{operations.queue_depth != null ? <> · queue depth <b>{operations.queue_depth}</b></> : null}{operations.last_trigger_at ? <> · last trigger <b>{operations.last_trigger_kind?.replace(/_/g, ' ') ?? 'event'}</b> at {fmtDeskTimestamp(operations.last_trigger_at) ?? operations.last_trigger_at}</> : null}.</>
        : 'Source readiness not measured.')}
      {field('Schedule and next run', operations
        ? <>{operations.designed_schedule} <b>Installed timer:</b> {operations.timer_state.replace(/_/g, ' ')}. <b>Next:</b> {operations.next_timer_at ? fmtDeskTimestamp(operations.next_timer_at) ?? operations.next_timer_at : operations.configured_calendar ? operations.configured_calendar : 'not scheduled'}.</>
        : 'Not scheduled.')}
      {field('Interacts with', operations?.interacts_with?.length ? operations.interacts_with.join(' · ') : 'No runtime tool interactions declared.')}
      {field('Produces', operations?.allowed_outputs?.length ? operations.allowed_outputs.join(' · ') : 'No runtime output contract declared.')}
      {field('Independent review', operations?.reviewer_agent_id
        ? <>Reviewer: <b>{operations.reviewer_agent_id}</b> · scorer: <b>{operations.scorer_agent_id}</b>. “Human review required” on the board is a maturity/promotion gate, not approval before each run.</>
        : 'No reviewer/scorer runtime pair is installed.')}
    </div>
  </div>
}

function RunNowModal({ agentId, onClose, onDone }: { agentId: string; onClose: () => void; onDone: () => void }) {
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const confirm = async () => {
    setBusy(true)
    setErr(null)
    setMsg(null)
    const result = await dispatchAgentRun(agentId, 1)
    setBusy(false)
    if (!result.ok) {
      setErr(result.detail)
      return
    }
    const o = result.payload.outcomes
    setMsg(`Dispatch ${result.payload.dispatch_id.slice(0, 18)}… · ${JSON.stringify(o)}`)
    setTimeout(onDone, 1200)
  }

  return <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.55)', zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}
    onClick={onClose}>
    <div style={{ ...panel, maxWidth: 420, width: '100%' }} onClick={e => e.stopPropagation()}>
      <div style={{ fontSize: TYPE.md, fontWeight: 800 }}>Run {agentId} in LAB (SHADOW)</div>
      <div style={{ marginTop: 8, fontSize: TYPE.xs, color: 'var(--text2)', lineHeight: 1.5 }}>
        Queues one bounded batch via the same path as <code>run_once --once</code>. No broker, order, 2FA, or production authority.
      </div>
      {err && <div style={{ marginTop: 10, fontSize: TYPE.xs, color: BB.red }}>{err}</div>}
      {msg && <div style={{ marginTop: 10, fontSize: TYPE.xs, color: BB.green, fontFamily: 'var(--mono)' }}>{msg}</div>}
      <div style={{ marginTop: 14, display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button type="button" onClick={onClose} style={{ fontSize: TYPE.xs, padding: '6px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg1)', cursor: 'pointer' }}>Cancel</button>
        <button type="button" disabled={busy} onClick={() => void confirm()}
          style={{ fontSize: TYPE.xs, fontWeight: 800, padding: '6px 12px', borderRadius: 6, border: '1px solid rgba(96,165,250,.4)', background: 'rgba(96,165,250,.14)', cursor: busy ? 'wait' : 'pointer', color: T.link }}>
          {busy ? 'Running…' : 'Confirm Run now'}
        </button>
      </div>
    </div>
  </div>
}

export function OperatorGlossary() {
  return <details style={{ padding: '10px 14px', borderTop: '1px solid var(--border)', fontSize: TYPE.xs, color: 'var(--text3)', lineHeight: 1.55 }}>
    <summary style={{ cursor: 'pointer', fontWeight: 800, color: 'var(--text2)' }}>Operator glossary</summary>
    <ul style={{ margin: '8px 0 0 18px' }}>
      <li><b>Last run</b> — newest <code>started_at</code> for this agent in the SHADOW runs table (read API).</li>
      <li><b>NOT RUN (review)</b> — no independent peer review recorded yet; distinct from &quot;never dispatched&quot;.</li>
      <li><b>Timer ACTIVE</b> — user systemd timer installed; <b>NOT INSTALLED</b> — designed cadence only.</li>
      <li><b>Run now</b> — server dispatch (bounded); <b>Copy LAB cmd</b> — manual CLI on the host.</li>
    </ul>
  </details>
}
