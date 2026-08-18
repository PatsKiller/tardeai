import { useState, type CSSProperties } from 'react'
import { useApi } from '../hooks/useApi'

const panel: CSSProperties = {
  background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14,
}
const label: CSSProperties = {
  fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: .5, fontWeight: 750,
}

function Badge({ children, tone = 'slate' }: { children: string; tone?: string }) {
  const color = tone === 'green' ? 'var(--green)' : tone === 'amber' ? 'var(--amber)' : tone === 'red' ? 'var(--red)' : 'var(--text2)'
  return <span style={{ fontSize: 10, fontWeight: 800, color, border: '1px solid var(--border)', borderRadius: 999, padding: '2px 7px' }}>{children}</span>
}

function Table({ cols, rows }: { cols: string[]; rows: Array<Array<string | number | null | undefined>> }) {
  return <div style={{ overflowX: 'auto' }}><table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
    <thead><tr>{cols.map(c => <th key={c} style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--text3)', fontSize: 10 }}>{c}</th>)}</tr></thead>
    <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} style={{ padding: '6px 8px', borderTop: '1px solid var(--border-subtle)', verticalAlign: 'top' }}>{c ?? '—'}</td>)}</tr>)}</tbody>
  </table></div>
}

export function LearningPanel() {
  const { data, loading, error } = useApi<any>('/api/v3/maturity/learning', 60_000)
  const [open, setOpen] = useState<string | null>(null)
  const { data: ev } = useApi<any>(
    open ? `/api/v3/maturity/lessons/${encodeURIComponent(open)}` : '/api/v3/maturity/authority',
    undefined,
    { enabled: !!open },
  )
  const lessons = data?.lessons || []
  return <div data-testid="maturity-learning">
    <div style={{ ...panel, marginBottom: 12 }}>
      <div style={{ fontWeight: 800 }}>Learning</div>
      <div style={{ marginTop: 4, fontSize: 12, color: 'var(--text3)' }}>RATIFIED_CONTEXT is advisory context, not production policy.</div>
      <div style={{ marginTop: 8 }}><Badge tone="red">AUTO-PROMOTION TO TRADING: DISABLED</Badge></div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10 }}>
        {Object.entries(data?.counts || {}).map(([k, v]) => <Badge key={k}>{k} {String(v)}</Badge>)}
      </div>
    </div>
    {loading && <div style={{ color: 'var(--text3)' }}>Loading lessons…</div>}
    {error && <div style={{ color: 'var(--amber)' }}>{String(error)}</div>}
    <Table
      cols={['lifecycle', 'id', 'source', 'symbols', 'apps', 'hits', 'hit_rate', 'citations', 'created', 'ratified_by']}
      rows={lessons.map((l: any) => [
        l.lifecycle, l.lesson_id, l.source, (l.symbols || []).join(','),
        l.applications, l.hits, l.hit_rate ?? '—', l.citations,
        l.created_at || '—', l.ratified_by || '—',
      ])}
    />
    <div style={{ marginTop: 10, fontSize: 12 }}>
      {lessons.slice(0, 40).map((l: any) => (
        <button key={l.lesson_id} type="button" onClick={() => setOpen(l.lesson_id)}
          style={{ margin: 3, fontSize: 11, cursor: 'pointer' }}>drill {l.lesson_id}</button>
      ))}
    </div>
    {ev?.lesson && <div style={{ ...panel, marginTop: 12 }} data-testid="maturity-evidence">
      <div style={label}>Evidence lineage (no hidden chain-of-thought)</div>
      <pre style={{ whiteSpace: 'pre-wrap', fontSize: 11, color: 'var(--text2)' }}>{JSON.stringify({
        lesson: ev.lesson, cases: ev.originating_cases, reflection: ev.reflection,
        runs: ev.agent_runs, senses: ev.financial_senses_receipts,
      }, null, 2)}</pre>
    </div>}
  </div>
}

export function PromotionPanel() {
  const { data, loading, error } = useApi<any>('/api/v3/maturity/promotions', 30_000)
  const rows = data?.promotions || []
  return <div data-testid="maturity-promotion" style={panel}>
    <div style={{ fontWeight: 800 }}>Promotion (Phase 11)</div>
    <div style={{ marginTop: 4, fontSize: 12, color: 'var(--text3)' }}>Governed advisory-only. Sign/activate via CLI <code>scripts/maturity_promotion.py</code>. Dashboard is GET-only.</div>
    <div style={{ marginTop: 8 }}><Badge tone="red">AUTO-PROMOTION TO TRADING: DISABLED</Badge></div>
    {loading && <div>Loading…</div>}
    {error && <div style={{ color: 'var(--amber)' }}>{String(error)}</div>}
    <Table
      cols={['id', 'capability', 'status', 'from', 'requested', 'sha', 'evidence', 'expires']}
      rows={rows.map((p: any) => [
        p.promotion_id, p.capability_type, p.status, p.from_state, p.requested_state,
        String(p.exact_source_sha || '').slice(0, 12), String(p.evidence_bundle_hash || '').slice(0, 12),
        p.expires_at,
      ])}
    />
    {rows.length === 0 && <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text3)' }}>No promotion records yet. Use the Phase 11 CLI to draft/sign/canary.</div>}
  </div>
}

export function CasesPanel() {
  const { data, loading, error } = useApi<any>('/api/v3/maturity/cases', 60_000)
  const cases = data?.cases || []
  return <div data-testid="maturity-cases" style={panel}>
    <div style={{ fontWeight: 800 }}>Cases</div>
    <div style={{ marginTop: 4, fontSize: 12, color: 'var(--text3)' }}>{data?.cases_seen ?? 0} materialized · {JSON.stringify(data?.by_status || {})}</div>
    {loading && <div>Loading…</div>}
    {error && <div style={{ color: 'var(--amber)' }}>{String(error)}</div>}
    <Table
      cols={['case', 'decision', 'status', 'disposition', 'outcome']}
      rows={cases.slice(0, 80).map((c: any) => [
        c.case_id, c.decision_id, c.status,
        (c.operator_disposition || {}).disposition || '—',
        (c.outcome || {}).outcome_status || '—',
      ])}
    />
  </div>
}

export function NotificationGatePanel() {
  const { data, loading, error } = useApi<any>('/api/v3/maturity/notification-gate', 30_000)
  const rows = data?.lineages || []
  return <div data-testid="cio-notification-gate" style={panel}>
    <div style={{ fontWeight: 800 }}>Notification Gate</div>
    <div style={{ marginTop: 4, fontSize: 12, color: 'var(--text3)' }}>IMMEDIATE · DIGEST · COMMAND_CENTER_ONLY · SUPPRESSED</div>
    {loading && <div>Loading…</div>}
    {error && <div style={{ color: 'var(--amber)' }}>{String(error)}</div>}
    <Table
      cols={['lineage', 'class', 'suppressed', 'material', 'evidence', 'telegram', 'evaluated']}
      rows={rows.map((r: any) => [
        r.decision_lineage_id, r.notification_class, r.suppression_reason,
        r.material_generation_id, r.evidence_generation_id, r.telegram_message_id, r.last_evaluated,
      ])}
    />
  </div>
}

export function TelegramReceiptsPanel() {
  const { data, loading, error } = useApi<any>('/api/v3/maturity/telegram-receipts', 30_000)
  return <div data-testid="cio-telegram-receipts" style={panel}>
    <div style={{ fontWeight: 800 }}>Telegram receipts</div>
    {loading && <div>Loading…</div>}
    {error && <div style={{ color: 'var(--amber)' }}>{String(error)}</div>}
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '10px 0' }}>
      <Badge>{`mode ${data?.delivery_mode || '—'}`}</Badge>
      <Badge tone={data?.credentials_ready ? 'green' : 'amber'}>{`credentials_ready ${!!data?.credentials_ready}`}</Badge>
      <Badge tone={data?.live_authorized ? 'green' : 'slate'}>{`live_authorized ${!!data?.live_authorized}`}</Badge>
      <Badge tone={data?.interdicted ? 'amber' : 'green'}>{`interdicted ${!!data?.interdicted}`}</Badge>
    </div>
    <pre style={{ fontSize: 11, color: 'var(--text2)', whiteSpace: 'pre-wrap' }}>{JSON.stringify({
      last_attempt: data?.last_delivery_attempt,
      last_success: data?.last_success,
      last_failure: data?.last_failure,
      receipts: data?.receipts,
    }, null, 2)}</pre>
  </div>
}

export function SensesEvidencePanel() {
  const { data } = useApi<any>('/api/v3/maturity/senses', 60_000)
  return <div data-testid="cio-senses-evidence" style={panel}>
    <div style={{ fontWeight: 800 }}>Senses evidence</div>
    <div style={{ marginTop: 6, fontSize: 12, color: 'var(--text3)' }}>Financial Senses receipts from AgentRunTrace / tool traces. Shadow-only; no execution influence.</div>
    <pre style={{ fontSize: 11, whiteSpace: 'pre-wrap', color: 'var(--text2)' }}>{JSON.stringify(data?.financial_senses_receipts || [], null, 2)}</pre>
  </div>
}

export function AutonomyLoopPanel() {
  const { data, loading, error } = useApi<any>('/api/v3/maturity/autonomy-health', 30_000)
  return <div data-testid="health-intelligence-loop" style={panel}>
    <div style={{ fontWeight: 800 }}>Intelligence loop</div>
    <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 4 }}>CURRENT {String(data?.current_sha || '').slice(0, 12)} · unexpected failures {data?.unexpected_failures ?? '—'}</div>
    {loading && <div>Loading…</div>}
    {error && <div style={{ color: 'var(--amber)' }}>{String(error)}</div>}
    <Table
      cols={['component', 'class', 'result', 'exit', 'last']}
      rows={(data?.components || []).map((c: any) => [c.id, c.classification, c.last_result, c.last_exit, c.last_success || c.last_failure])}
    />
    <div style={{ marginTop: 12 }}><div style={label}>Artifacts</div>
      <Table cols={['id', 'freshness', 'age_s']} rows={(data?.artifacts || []).map((a: any) => [a.id, a.freshness, a.age_seconds])} />
    </div>
  </div>
}
