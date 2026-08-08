/**
 * Ops Command Board — monitor Layer-1 Autonomous Ops Agent + Layer-4 Health Agent
 * at a glance: WHAT · WHY (root cause) · WHO · WHEN · HOW · STATUS
 *
 * Data sources (graceful fallback):
 *  1) GET /api/v2/health/ops-autonomy  (v2 memory / cadence / decisions)
 *  2) GET /api/v2/health + /activity     (live L4 findings — works without redeploy)
 */
import { useCallback, useMemo, useState, type CSSProperties, type ReactNode } from 'react'
import { useApi } from '../hooks/useApi'
import { StatusBadge } from '../components/StatusBadge'
import { hubPanel } from '../lib/terminalHubChrome'
import { useTerminalUi } from '../lib/terminalUi'

// ── Types ───────────────────────────────────────────────────────────────────

type Discovery = {
  signature?: string
  name?: string
  times_seen?: number
  successful_fixes?: number
  failed_fixes?: number
  confidence?: number
  autonomy_level?: string
  severity?: string
  last_message?: string
  linked_cmd?: string
  last_seen?: string
  operator_decision?: string | null
}

type OpsPayload = {
  overview?: {
    healthy_pct?: number
    status?: string
    warnings?: number
    critical?: number
    auto_fixed_today?: number
    learning_candidates?: number
    modules_ok?: number
    modules_total?: number
    avg_confidence?: number
  }
  cadence?: {
    last_band?: string
    last_score?: number
    next_sleep_s?: number
    mode?: string
    last_cycle?: string
  }
  discoveries?: Discovery[]
  actions?: any[]
  human_required?: Discovery[]
  learning?: {
    by_level?: Record<string, number>
    approved?: number
    blocked?: number
    candidates?: number
    queue?: Discovery[]
    recent_events?: any[]
  }
  decisions_allowed?: string[]
}

type IncidentRow = {
  id: string
  severity: string
  what: string
  why: string
  who: string
  when: string
  how: string
  status: string
  category?: string
  source: 'ops' | 'health'
  raw?: any
}

type Decision = 'approve' | 'deny' | 'dismiss' | 'sandbox' | 'reset'

// ── Style tokens ────────────────────────────────────────────────────────────

const SEV: Record<string, string> = {
  critical: 'var(--red)', P0: 'var(--red)',
  warning: 'var(--amber)', P1: 'var(--amber)', high: 'var(--amber)',
  info: 'var(--text3)', P2: 'var(--text3)', P3: 'var(--text3)', low: 'var(--text3)',
  medium: 'var(--accent)',
}

const STATUS_COL: Record<string, string> = {
  fixed: 'var(--green)', success: 'var(--green)', approved: 'var(--green)', verified: 'var(--green)',
  failed: 'var(--red)', blocked: 'var(--red)', error: 'var(--red)',
  attempted: 'var(--amber)', investigating: 'var(--accent)', queued: 'var(--amber)',
  detected: 'var(--text3)', observe: 'var(--text3)', sandbox: 'var(--accent)',
  candidate: 'var(--amber)', correlate: 'var(--text2)', no_changes: 'var(--text3)',
  human_required: 'var(--red)',
}

const LEVEL_COLOR: Record<string, string> = {
  observe: 'var(--text3)', correlate: 'var(--text2)', candidate: 'var(--amber)',
  sandbox: 'var(--accent)', approved: 'var(--green)', blocked: 'var(--red)',
}

const btnBase: CSSProperties = {
  fontSize: 10, fontWeight: 700, padding: '4px 8px', borderRadius: 5,
  border: '1px solid var(--border)', cursor: 'pointer',
  background: 'var(--bg2)', color: 'var(--text1)',
}

const thStyle: CSSProperties = {
  textAlign: 'left', fontSize: 10, fontWeight: 800, color: 'var(--text3)',
  textTransform: 'uppercase', letterSpacing: 0.5, padding: '6px 8px',
  borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap',
}

const tdStyle: CSSProperties = {
  fontSize: 11, padding: '8px', verticalAlign: 'top',
  borderBottom: '1px solid var(--border-subtle, var(--border))',
  color: 'var(--text1)',
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function fmtWhen(s?: string | null) {
  if (!s) return '—'
  try { return new Date(s).toLocaleString() } catch { return String(s) }
}

function fmtAgo(s?: string | null) {
  if (!s) return '—'
  try {
    const ms = Date.now() - new Date(s).getTime()
    if (!Number.isFinite(ms) || ms < 0) return fmtWhen(s)
    const m = Math.floor(ms / 60000)
    if (m < 1) return 'just now'
    if (m < 60) return `${m}m ago`
    const h = Math.floor(m / 60)
    if (h < 48) return `${h}h ago`
    return `${Math.floor(h / 24)}d ago`
  } catch { return fmtWhen(s) }
}

function chip(label: string, value: string | number, color?: string, sub?: string) {
  return (
    <div style={{
      minWidth: 100, padding: '10px 12px', borderRadius: 8,
      background: 'var(--bg2)', border: '1px solid var(--border)',
    }}>
      <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: 0.4 }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 800, color: color || 'var(--text0)', marginTop: 2 }}>{value}</div>
      {sub && <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: 10, fontWeight: 800, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: 0.4 }}>{label}</div>
      <div style={{ fontSize: 11, color: 'var(--text1)', marginTop: 2, lineHeight: 1.35 }}>{children}</div>
    </div>
  )
}

function pill(text: string, color: string) {
  return (
    <span style={{
      fontSize: 10, fontWeight: 800, textTransform: 'uppercase', letterSpacing: 0.3,
      color, background: 'var(--bg2)', border: `1px solid ${color}`,
      padding: '2px 7px', borderRadius: 9, whiteSpace: 'nowrap',
    }}>{text}</span>
  )
}

async function postDecision(body: {
  signature?: string; name?: string; decision: Decision; note?: string; linked_cmd?: string
}): Promise<{ ok: boolean; error?: string; autonomy_level?: string }> {
  const r = await fetch('/api/v2/health/ops-autonomy/decision', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...body, operator: 'command-center' }),
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok || j?.ok === false) return { ok: false, error: j?.error || `HTTP ${r.status}` }
  return { ok: true, autonomy_level: j?.autonomy_level }
}

function DecisionButtons({
  item, busy, onDecide,
}: {
  item: Discovery; busy: boolean; onDecide: (d: Decision, item: Discovery) => void
}) {
  const mk = (d: Decision, label: string, color: string) => (
    <button key={d} type="button" disabled={busy || (!item.signature && !item.name)}
      onClick={() => onDecide(d, item)}
      style={{ ...btnBase, color, borderColor: color, opacity: busy ? 0.5 : 1 }}
      title={`${label} ${item.name || item.signature || ''}`}>
      {label}
    </button>
  )
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
      {mk('approve', 'Approve', 'var(--green)')}
      {mk('sandbox', 'Sandbox', 'var(--accent)')}
      {mk('deny', 'Deny', 'var(--red)')}
      {mk('dismiss', 'Dismiss', 'var(--text3)')}
      {mk('reset', 'Reset', 'var(--text2)')}
    </div>
  )
}

function unwrapHealth(raw: any): any {
  if (!raw || typeof raw !== 'object') return raw
  // useApi may pass {ok,data} or unwrapped data
  if (raw.overall_score != null || raw.findings) return raw
  if (raw.data && (raw.data.overall_score != null || raw.data.findings)) return raw.data
  return raw
}

function healthToIncidents(health: any): IncidentRow[] {
  const findings: any[] = health?.findings || []
  const rows: IncidentRow[] = findings.map((f: any, i: number) => {
    const rem = f.remediation || {}
    const who = rem.by
      ? `${f.detected_by || 'health_agent'} → ${rem.by}`
      : (f.detected_by || 'health_agent')
    const when = rem.at || f.detected_at || ''
    const how = f.recommended_action || rem.detail || f.action_type || '—'
    const why = f.why || (f.age_hours != null
      ? `Stale ${f.age_hours}h (max ${f.max_hours ?? '—'}h)`
      : 'Health signal needs review')
    return {
      id: `h-${f.category}-${f.type}-${i}`,
      severity: String(f.severity || 'info'),
      what: f.message || f.type || 'finding',
      why,
      who,
      when,
      how,
      status: rem.status || 'detected',
      category: f.category,
      source: 'health' as const,
      raw: f,
    }
  })
  const rank = (s: string) => (s === 'critical' ? 0 : s === 'warning' ? 1 : 2)
  rows.sort((a, b) => rank(a.severity) - rank(b.severity))
  return rows
}

function opsToIncidents(ops: OpsPayload | null): IncidentRow[] {
  if (!ops) return []
  const human = ops.human_required || []
  const disc = ops.discoveries || []
  const pool = human.length ? human : disc.filter(d =>
    ['blocked', 'sandbox', 'candidate'].includes(d.autonomy_level || '') ||
    String(d.severity || '').toUpperCase().includes('P0') ||
    (d.failed_fixes || 0) >= 2,
  )
  return pool.map((d, i) => ({
    id: `o-${d.signature || d.name || i}`,
    severity: d.severity || (d.autonomy_level === 'blocked' ? 'critical' : 'warning'),
    what: d.name || d.signature || 'issue',
    why: d.last_message || `Seen ${d.times_seen ?? 0}× · conf ${d.confidence ?? '—'} · ${d.autonomy_level || 'observe'}`,
    who: d.operator_decision
      ? `operator:${d.operator_decision}`
      : 'ops-agent (Layer-1)',
    when: d.last_seen || '',
    how: d.linked_cmd || (d.autonomy_level === 'approved' ? 'auto-remediate' : 'hold / human decision'),
    status: d.autonomy_level || 'observe',
    source: 'ops' as const,
    raw: d,
  }))
}

// ── Main ────────────────────────────────────────────────────────────────────

export default function OpsAutonomyDashboard() {
  const [terminalUi] = useTerminalUi()
  const { data: opsRaw, loading: opsLoading, error: opsError, refetch: refetchOps } =
    useApi<OpsPayload>('/api/v2/health/ops-autonomy', 60_000)
  const { data: healthRaw, loading: healthLoading, refetch: refetchHealth } =
    useApi<any>('/api/v2/health', 120_000)
  const { data: activityRaw, refetch: refetchAct } =
    useApi<any>('/api/v2/health/activity', 60_000)

  const health = unwrapHealth(healthRaw)
  const activity: any[] = activityRaw?.activity || activityRaw?.data?.activity || []

  const opsAvailable = !opsError && !!opsRaw && !!(opsRaw.overview || opsRaw.discoveries || opsRaw.cadence)
  const loading = (opsLoading || healthLoading) && !opsRaw && !health

  const [busyKey, setBusyKey] = useState<string | null>(null)
  const [flash, setFlash] = useState<{ ok: boolean; msg: string } | null>(null)
  const [filter, setFilter] = useState<'all' | 'critical' | 'human' | 'auto'>('all')
  const [source, setSource] = useState<'both' | 'ops' | 'health'>('both')

  const onDecide = useCallback(async (decision: Decision, item: Discovery) => {
    const key = item.signature || item.name || ''
    setBusyKey(key)
    setFlash(null)
    try {
      const res = await postDecision({
        signature: item.signature, name: item.name, decision, linked_cmd: item.linked_cmd,
      })
      if (res.ok) {
        setFlash({ ok: true, msg: `${decision.toUpperCase()} → ${item.name || key} (${res.autonomy_level || 'ok'})` })
        refetchOps()
      } else {
        setFlash({ ok: false, msg: res.error || 'Decision failed (L1 API may need deploy)' })
      }
    } catch (e: any) {
      setFlash({ ok: false, msg: e?.message || 'Network error' })
    } finally {
      setBusyKey(null)
    }
  }, [refetchOps])

  const opsIncidents = useMemo(() => opsToIncidents(opsAvailable ? opsRaw : null), [opsRaw, opsAvailable])
  const healthIncidents = useMemo(() => healthToIncidents(health), [health])

  const incidents = useMemo(() => {
    let rows: IncidentRow[] = []
    if (source === 'ops' || source === 'both') rows = rows.concat(opsIncidents)
    if (source === 'health' || source === 'both') rows = rows.concat(healthIncidents)
    if (filter === 'critical') rows = rows.filter(r => r.severity === 'critical' || r.severity === 'P0')
    if (filter === 'human') {
      rows = rows.filter(r =>
        ['failed', 'blocked', 'human_required', 'detected', 'attempted'].includes(r.status) ||
        r.severity === 'critical',
      )
    }
    if (filter === 'auto') {
      rows = rows.filter(r => ['fixed', 'success', 'verified', 'approved'].includes(r.status))
    }
    return rows
  }, [opsIncidents, healthIncidents, source, filter])

  const ov = opsRaw?.overview || {}
  const cadence = opsRaw?.cadence || {}
  const learning = opsRaw?.learning || {}
  const discoveries = opsRaw?.discoveries || []
  const actions = opsRaw?.actions || []

  const recentActions = useMemo(() => {
    if (actions.length) {
      return actions.slice(0, 25).map((a: any) => ({
        when: a.timestamp || a.at,
        who: a.agent || a.actor || 'ops',
        what: a.finding || a.component || a.action || '—',
        status: a.action || (a.verified ? 'fixed' : 'attempted'),
        how: a.new_state || a.old_state || a.detail || '',
      }))
    }
    return activity.slice(0, 25).map((a: any) => ({
      when: a.at,
      who: a.actor || 'health',
      what: a.component || '—',
      status: a.action || '—',
      how: a.detail || a.resolution || a.lane || '',
    }))
  }, [actions, activity])

  const score = ov.healthy_pct != null
    ? ov.healthy_pct
    : (health?.overall_score != null ? health.overall_score : null)
  const scoreColor = score == null ? 'var(--text3)'
    : score >= 85 ? 'var(--green)' : score >= 65 ? 'var(--amber)' : 'var(--red)'
  const statusLabel = ov.status || health?.status || 'unknown'
  const crit = ov.critical ?? health?.counts?.critical ?? 0
  const warn = ov.warnings ?? health?.counts?.warning ?? 0

  if (loading) {
    return <div style={{ padding: 16, color: 'var(--text3)', fontSize: 12 }}>Loading Ops Command Board…</div>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* Command strip */}
      <div style={{ ...hubPanel(terminalUi), borderLeft: `4px solid ${scoreColor}` }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', alignItems: 'flex-start' }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)', letterSpacing: 0.3 }}>
              Ops Command Board
            </div>
            <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 4, maxWidth: 680, lineHeight: 1.45 }}>
              At a glance: <b>WHAT</b> broke · <b>WHY</b> (root cause) · <b>WHO</b> owns it ·
              {' '}<b>WHEN</b> · <b>HOW</b> to fix · <b>STATUS</b>.
              {' '}Layer-1 Ops Agent + Layer-4 Health Agent.
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <button type="button" onClick={() => { refetchOps(); refetchHealth(); refetchAct() }}
              style={{ ...btnBase, borderColor: 'var(--accent)', color: 'var(--accent)' }}>
              Refresh
            </button>
            {pill(
              opsAvailable ? 'L1 API live' : 'L1 offline · L4 fallback',
              opsAvailable ? 'var(--green)' : 'var(--amber)',
            )}
          </div>
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 12 }}>
          {chip('Health', score != null ? `${score}${ov.healthy_pct != null ? '%' : '/100'}` : '—', scoreColor, statusLabel)}
          {chip('Critical', crit, crit > 0 ? 'var(--red)' : 'var(--text0)')}
          {chip('Warnings', warn, warn > 0 ? 'var(--amber)' : 'var(--text0)')}
          {chip('Auto fixed', ov.auto_fixed_today ?? health?.remediated ?? '—', 'var(--green)', 'today / last cycle')}
          {chip('Learning', ov.learning_candidates ?? learning.candidates ?? 0, 'var(--amber)', 'ladder candidates')}
          {chip('Approved', learning.approved ?? 0, 'var(--green)', 'auto patterns')}
          {chip(
            'Cadence',
            cadence.next_sleep_s != null
              ? `${Math.round(Number(cadence.next_sleep_s) / 60)}m`
              : (health?.scheduler || '—'),
            'var(--text0)',
            cadence.last_band || health?.mode || 'mode',
          )}
        </div>

        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))',
          gap: 12, marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--border)',
        }}>
          <Field label="Who (agents)">
            <span style={{ color: 'var(--text0)', fontWeight: 700 }}>ops-agent</span> (L1) ·{' '}
            <span style={{ fontWeight: 700 }}>health_agent</span> (L4)
          </Field>
          <Field label="When (last cycle)">
            {fmtWhen(cadence.last_cycle || health?.captured_at)} · {fmtAgo(cadence.last_cycle || health?.captured_at)}
          </Field>
          <Field label="How (loop)">
            Discover → Classify → Remediate → Verify → Learn · band{' '}
            <b>{cadence.last_band || health?.mode || '—'}</b>
          </Field>
          <Field label="Mode">
            {cadence.mode || health?.mode || 'daemon/cron'} · next{' '}
            {cadence.next_sleep_s != null ? `${Math.round(Number(cadence.next_sleep_s) / 60)}m` : '—'}
          </Field>
          <Field label="Report status">
            <StatusBadge status={(statusLabel || 'unknown').toLowerCase()} />
            {health?.summary ? (
              <span style={{ marginLeft: 6, color: 'var(--text3)' }}>{health.summary}</span>
            ) : null}
          </Field>
        </div>

        {flash && (
          <div style={{
            marginTop: 10, fontSize: 11, padding: '6px 8px', borderRadius: 6,
            background: flash.ok ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)',
            color: flash.ok ? 'var(--green)' : 'var(--red)',
            border: `1px solid ${flash.ok ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)'}`,
          }}>{flash.msg}</div>
        )}
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 700 }}>SHOW</span>
        {([
          ['all', 'All'],
          ['critical', 'Critical'],
          ['human', 'Needs human'],
          ['auto', 'Fixed / auto'],
        ] as const).map(([k, lab]) => (
          <button key={k} type="button" onClick={() => setFilter(k)}
            style={{
              ...btnBase,
              background: filter === k ? 'var(--accent-dim, var(--bg2))' : 'var(--bg2)',
              borderColor: filter === k ? 'var(--accent)' : 'var(--border)',
              color: filter === k ? 'var(--accent)' : 'var(--text2)',
            }}>{lab}</button>
        ))}
        <span style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 700, marginLeft: 8 }}>SOURCE</span>
        {([
          ['both', 'Both agents'],
          ['health', 'Health L4'],
          ['ops', 'Ops L1'],
        ] as const).map(([k, lab]) => (
          <button key={k} type="button" onClick={() => setSource(k)}
            style={{
              ...btnBase,
              background: source === k ? 'var(--bg1)' : 'var(--bg2)',
              borderColor: source === k ? 'var(--text2)' : 'var(--border)',
              color: source === k ? 'var(--text0)' : 'var(--text3)',
            }}>{lab}</button>
        ))}
        <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--text3)' }}>
          {incidents.length} row{incidents.length === 1 ? '' : 's'}
        </span>
      </div>

      {/* Incident board */}
      <div style={{ ...hubPanel(terminalUi), padding: 0, overflow: 'hidden' }}>
        <div style={{
          padding: '10px 12px', borderBottom: '1px solid var(--border)',
          fontSize: 11, fontWeight: 800, color: 'var(--text1)', textTransform: 'uppercase', letterSpacing: 0.4,
        }}>
          Incident board · what · why · who · when · how · status
        </div>
        <div style={{ overflowX: 'auto', maxHeight: 480, overflowY: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 900 }}>
            <thead>
              <tr style={{ position: 'sticky', top: 0, background: 'var(--bg1)', zIndex: 1 }}>
                <th style={{ ...thStyle, width: 72 }}>Sev</th>
                <th style={{ ...thStyle, minWidth: 200 }}>What</th>
                <th style={{ ...thStyle, minWidth: 180 }}>Why / root cause</th>
                <th style={{ ...thStyle, width: 140 }}>Who</th>
                <th style={{ ...thStyle, width: 110 }}>When</th>
                <th style={{ ...thStyle, minWidth: 160 }}>How (action)</th>
                <th style={{ ...thStyle, width: 100 }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {incidents.length === 0 && (
                <tr>
                  <td colSpan={7} style={{ ...tdStyle, color: 'var(--green)', padding: 16 }}>
                    No incidents in this filter — systems quiet or data not loaded.
                  </td>
                </tr>
              )}
              {incidents.map((r) => (
                <tr key={r.id} style={{ background: r.severity === 'critical' ? 'rgba(239,68,68,0.04)' : undefined }}>
                  <td style={tdStyle}>{pill(r.severity, SEV[r.severity] || 'var(--text3)')}</td>
                  <td style={{ ...tdStyle, color: 'var(--text0)', fontWeight: 600 }}>
                    {r.what}
                    {r.category && (
                      <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>{r.category} · {r.source}</div>
                    )}
                  </td>
                  <td style={tdStyle}>{r.why}</td>
                  <td style={{ ...tdStyle, fontFamily: 'ui-monospace, monospace', fontSize: 10 }}>{r.who}</td>
                  <td style={tdStyle}>
                    <div>{fmtAgo(r.when)}</div>
                    <div style={{ fontSize: 10, color: 'var(--text3)' }}>{fmtWhen(r.when)}</div>
                  </td>
                  <td style={{ ...tdStyle, fontSize: 10, color: 'var(--accent)' }}>{r.how}</td>
                  <td style={tdStyle}>{pill(r.status, STATUS_COL[r.status] || 'var(--text3)')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Bottom panels */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 12 }}>
        <div style={hubPanel(terminalUi)}>
          <div style={{ fontSize: 11, fontWeight: 800, color: 'var(--text2)', marginBottom: 8, textTransform: 'uppercase' }}>
            What the agent did
          </div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 8 }}>WHO · WHAT · WHEN · STATUS</div>
          {recentActions.length === 0 ? (
            <div style={{ fontSize: 11, color: 'var(--text3)' }}>No recent remediations.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 280, overflow: 'auto' }}>
              {recentActions.map((a, i) => (
                <div key={i} style={{
                  padding: '6px 8px', borderRadius: 6, background: 'var(--bg2)',
                  border: '1px solid var(--border-subtle, var(--border))', fontSize: 10,
                }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    {pill(String(a.status), STATUS_COL[String(a.status)] || 'var(--text3)')}
                    <span style={{ flex: 1, fontWeight: 600, color: 'var(--text0)' }}>{a.what}</span>
                  </div>
                  <div style={{ color: 'var(--text3)', marginTop: 3 }}>
                    <b style={{ color: 'var(--accent)' }}>{a.who}</b>
                    {' · '}{fmtAgo(a.when)}
                    {a.how ? ` · ${a.how}` : ''}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div style={hubPanel(terminalUi)}>
          <div style={{ fontSize: 11, fontWeight: 800, color: 'var(--amber)', marginBottom: 8, textTransform: 'uppercase' }}>
            Learning ladder
          </div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 8 }}>
            observe → correlate → candidate → sandbox → approved
          </div>
          {opsAvailable && learning.by_level ? (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
              {Object.entries(learning.by_level).map(([lvl, n]) => (
                <div key={lvl} style={{
                  padding: '6px 10px', borderRadius: 6, background: 'var(--bg2)',
                  border: `1px solid ${LEVEL_COLOR[lvl] || 'var(--border)'}`,
                }}>
                  <div style={{ fontSize: 10, color: LEVEL_COLOR[lvl] || 'var(--text3)', fontWeight: 800 }}>{lvl.toUpperCase()}</div>
                  <div style={{ fontSize: 16, fontWeight: 800, color: 'var(--text0)' }}>{n as number}</div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ fontSize: 11, color: 'var(--amber)', marginBottom: 10 }}>
              L1 memory API offline — redeploy portfolio-server for ladder counts. L4 findings still shown above.
            </div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5, maxHeight: 200, overflow: 'auto' }}>
            {(learning.queue || discoveries).slice(0, 10).map((q: Discovery) => {
              const key = q.signature || q.name || ''
              return (
                <div key={key} style={{
                  padding: 6, background: 'var(--bg2)', borderRadius: 5,
                  border: '1px solid var(--border-subtle, var(--border))', fontSize: 10,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6 }}>
                    <b style={{ color: 'var(--text0)' }}>{q.name}</b>
                    <span style={{ color: LEVEL_COLOR[q.autonomy_level || ''] || 'var(--text3)' }}>
                      {(q.autonomy_level || '').toUpperCase()} · seen {q.times_seen}
                    </span>
                  </div>
                  {q.last_message && <div style={{ color: 'var(--text3)', marginTop: 2 }}>{q.last_message}</div>}
                  <div style={{ marginTop: 4 }}>
                    <DecisionButtons item={q} busy={busyKey === key} onDecide={onDecide} />
                  </div>
                </div>
              )
            })}
            {!opsAvailable && (
              <div style={{ fontSize: 10, color: 'var(--text3)' }}>No L1 discoveries until ops-autonomy API is live.</div>
            )}
          </div>
        </div>

        <div style={hubPanel(terminalUi)}>
          <div style={{ fontSize: 11, fontWeight: 800, color: 'var(--red)', marginBottom: 8, textTransform: 'uppercase' }}>
            Human required
          </div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 8 }}>
            Approve promotes · Deny blocks · Dismiss hides · needs L1 API
          </div>
          {(opsRaw?.human_required || []).length === 0 ? (
            <div style={{ fontSize: 11, color: opsAvailable ? 'var(--green)' : 'var(--text3)' }}>
              {opsAvailable ? 'No blocked/critical L1 items.' : 'Connect L1 API for operator queue. Critical L4 rows are on the incident board.'}
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 280, overflow: 'auto' }}>
              {(opsRaw?.human_required || []).map((h, i) => {
                const key = h.signature || h.name || String(i)
                return (
                  <div key={key} style={{
                    fontSize: 10, padding: 8, borderRadius: 6,
                    background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.25)',
                  }}>
                    <b style={{ color: 'var(--text0)' }}>{h.name}</b>
                    <div style={{ color: 'var(--text3)', marginTop: 2 }}>
                      fails={h.failed_fixes} seen={h.times_seen} · {h.autonomy_level}
                    </div>
                    {h.last_message && <div style={{ marginTop: 3 }}>{h.last_message}</div>}
                    <div style={{ marginTop: 6 }}>
                      <DecisionButtons item={h} busy={busyKey === key} onDecide={onDecide} />
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
