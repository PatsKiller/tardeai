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

export function InfluenceBadge() {
  const { data } = useApi<any>('/api/v3/maturity/influence', 30_000)
  const mode = data?.gates?.lesson_mode || 'OFF'
  return <div data-testid="learning-influence-badge" style={{ ...panel, marginBottom: 12 }}>
    <div style={{ fontWeight: 800 }}>{data?.badge || 'BASELINE'}</div>
    <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 4 }}>
      lesson_mode={mode} · fs_mode={data?.gates?.financial_senses_mode || 'OFF'} · MEMORY_BEHAVIOR_INFLUENCE untouched
    </div>
  </div>
}

export function MemoryPanel() {
  const { data, loading, error } = useApi<any>('/api/v3/maturity/memory', 30_000)
  const [msg, setMsg] = useState('')
  const counts = data?.counts || {}
  const recs = data?.records || []
  const contradictions = data?.contradictions || []
  const retrievals = data?.retrieval_receipts || []
  const shadow = data?.shadow || {}
  async function act(action: string, memoryId: string) {
    setMsg('')
    try {
      const r = await fetch(`/api/v3/maturity-control/memory/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ memory_id: memoryId, reason: 'operator' }),
      })
      const j = await r.json()
      setMsg(j.ok ? `${action} ${memoryId}` : `${action} blocked: ${j.error || j.message || r.status}`)
    } catch (e: any) {
      setMsg(`failed: ${e?.message || e}`)
    }
  }
  return <div data-testid="maturity-memory" style={panel}>
    <div style={{ fontWeight: 800 }}>Memory</div>
    <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 4 }}>
      Durable, NON_AUTHORITATIVE_CONTEXT. Not financial truth. Not execution authority.
    </div>
    <div style={{ marginTop: 8, fontSize: 12 }}>
      provider={data?.backend?.provider || '—'} · backend={data?.backend?.backend || '—'} ·
      durable={String(!!data?.backend?.durable)} · local={String(!!data?.backend?.local_controlled)} ·
      influence={data?.influence_mode || 'OFF'} ·
      MEMORY_BEHAVIOR_INFLUENCE={data?.memory_behavior_influence || '0'}
    </div>
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', margin: '10px 0' }}>
      {Object.entries(counts).map(([k, v]) => <Badge key={k}>{`${k} ${String(v)}`}</Badge>)}
      <Badge>{`shadow_runs ${String(shadow.comparator_runs ?? 0)}`}</Badge>
      <Badge>{`retrievals ${String(shadow.real_retrievals ?? retrievals.length)}`}</Badge>
    </div>
    {loading && <div>Loading…</div>}
    {error && <div style={{ color: 'var(--amber)' }}>{String(error)}</div>}
    {msg && <div style={{ fontSize: 12, color: 'var(--amber)', marginBottom: 8 }}>{msg}</div>}
    <Table
      cols={['id', 'status', 'type', 'subject', 'expires', 'actions']}
      rows={recs.slice(0, 40).map((r: any) => [
        r.memory_id, r.status, r.memory_type, r.subject, r.expires_at,
        `${r.memory_id}`,
      ])}
    />
    <div style={{ marginTop: 8 }}>
      {recs.slice(0, 20).map((r: any) => (
        <span key={r.memory_id} style={{ marginRight: 8 }}>
          <button type="button" onClick={() => act('dispute', r.memory_id)}>dispute {String(r.memory_id).slice(0, 10)}</button>
          <button type="button" onClick={() => act('retract', r.memory_id)}>retract</button>
          <button type="button" onClick={() => act('expire', r.memory_id)}>expire</button>
        </span>
      ))}
    </div>
    {contradictions.length > 0 && <div style={{ marginTop: 12 }}>
      <div style={label}>Contradictions / disputed</div>
      <pre style={{ fontSize: 11, whiteSpace: 'pre-wrap' }}>{JSON.stringify(contradictions.slice(0, 20), null, 2)}</pre>
    </div>}
    {retrievals.length > 0 && <div style={{ marginTop: 12 }}>
      <div style={label}>Recent retrievals</div>
      <pre style={{ fontSize: 11, whiteSpace: 'pre-wrap' }}>{JSON.stringify(retrievals.slice(-5), null, 2)}</pre>
    </div>}
  </div>
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
    <InfluenceBadge />
    <div style={{ ...panel, marginBottom: 12 }}>
      <div style={{ fontWeight: 800 }}>Learning</div>
      <div style={{ marginTop: 4, fontSize: 12, color: 'var(--text3)' }}>RATIFIED_CONTEXT is advisory context, not production policy.</div>
      <div style={{ marginTop: 8 }}><Badge tone="red">AUTO-PROMOTION TO TRADING: DISABLED</Badge></div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10 }}>
        {Object.entries(data?.counts || {}).map(([k, v]) => <Badge key={k}>{`${k} ${String(v)}`}</Badge>)}
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

export function DailyIntelligencePanel() {
  const { data, loading, error } = useApi<any>('/api/v3/maturity/heartbeat', 30_000)
  const today = data?.today || {}
  const comps = data?.components || today.components || []
  const hist = data?.history || []
  const auto = today.autonomy || {}
  const senses = today.senses || {}
  const learn = today.learning || {}
  const mem = today.memory || {}
  const cio = today.cio || {}
  const fin = today.finops || {}
  const adv = today.advisory || {}
  const auth = today.authority || {}
  return <div data-testid="daily-intelligence" style={panel}>
    <div style={{ fontWeight: 800 }}>TRADE AI INTELLIGENCE · TODAY</div>
    <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 4 }}>
      Daily proof that the intelligence office ran. Silence from CIO financial Telegram is not failure.
    </div>
    <div style={{ marginTop: 8, fontSize: 12 }}>
      overall={today.overall || data?.watchdog_state?.overall || '—'} ·
      last watchdog {data?.watchdog_state?.at || '—'}
    </div>
    <details style={{ marginTop: 4, fontSize: 11, color: 'var(--text3)' }}>
      <summary style={{ cursor: 'pointer' }}>Provenance</summary>
      SHA {String(today.release_sha || '').slice(0, 12) || '—'} ·
      status {today.provenance_status || '—'}
    </details>
    <div style={{ marginTop: 6, fontSize: 12 }}>
      last system Telegram {data?.last_system_telegram?.at || 'NEVER'} ·
      last daily heartbeat {data?.last_daily_system_telegram?.at || 'NEVER'} ·
      last financial Telegram {cio.last_financial_telegram || 'NEVER'}
    </div>
    {loading && <div>Loading…</div>}
    {error && <div style={{ color: 'var(--amber)' }}>{String(error)}</div>}
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 8, marginTop: 12 }}>
      {[
        ['Agents', auto.state, auto.wakes, auto.reason],
        ['Financial Senses', senses.state, senses.receipts, senses.reason],
        ['Learning', learn.state, learn.reflections, learn.reason],
        ['Memory', mem.state, mem.retrievals, mem.reason],
        ['CIO Notifications', cio.state, cio.material_scans, cio.reason],
        ['FinOps', fin.state, fin.events, fin.reason],
        ['Advisory Desk', adv.state, adv.facts_freshness, adv.reason],
        ['Authority', auth.memory_behavior_influence === '0' || auth.memory_behavior_influence === 0 ? 'HEALTHY' : 'FAILED', auth.memory_behavior_influence, 'MEMORY_BEHAVIOR_INFLUENCE'],
      ].map(([title, state, count, reason]) => (
        <div key={String(title)} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 10 }}>
          <div style={label}>{String(title)}</div>
          <div style={{ fontWeight: 800, marginTop: 4 }}>{String(state || '—')}</div>
          <div style={{ fontSize: 12 }}>today {String(count ?? '—')}</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>{String(reason || '')}</div>
        </div>
      ))}
    </div>
    {cio.silence_explained && <div style={{ marginTop: 12, fontSize: 12, color: 'var(--text2)' }}>
      {cio.silence_copy || 'No material immediate financial notification required. The scanner is operating normally.'}
    </div>}
    <div style={{ marginTop: 16, fontWeight: 800 }}>History (30 days)</div>
    <Table
      cols={['date', 'overall', 'agents', 'senses', 'reflection', 'memory', 'CIO scans', 'financial TG', 'health']}
      rows={hist.slice(-30).map((h: any) => [
        h.date, h.overall,
        (h.autonomy || {}).wakes, (h.senses || {}).receipts,
        (h.learning || {}).reflections, (h.memory || {}).retrievals,
        (h.cio || {}).material_scans, (h.cio || {}).Telegram_financial_sends,
        (h.health || {}).overall,
      ])}
    />
    <pre style={{ display: 'none' }}>{JSON.stringify(comps)}</pre>
  </div>
}

export function NotificationGatePanel() {
  const { data, loading, error } = useApi<any>('/api/v3/maturity/notification-gate', 30_000)
  const { data: hb } = useApi<any>('/api/v3/maturity/heartbeat', 30_000)
  const rows = data?.lineages || []
  const cio = (hb?.today || {}).cio || {}
  return <div data-testid="cio-notification-gate" style={panel}>
    <div style={{ fontWeight: 800 }}>Notification Gate</div>
    <div style={{ marginTop: 4, fontSize: 12, color: 'var(--text3)' }}>IMMEDIATE · DIGEST · COMMAND_CENTER_ONLY · SUPPRESSED</div>
    <div style={{ marginTop: 8, fontSize: 12 }}>
      Scanner: {cio.state || '—'} · scans today {cio.material_scans ?? '—'} ·
      immediate {cio.immediate ?? '—'} · digest {cio.digest ?? '—'} ·
      CC-only {cio.command_center_only ?? '—'} · suppressed {cio.suppressed ?? '—'} ·
      last Telegram {cio.last_financial_telegram || 'NEVER'}
    </div>
    {(cio.immediate === 0 || cio.immediate === '0') && (Number(cio.suppressed) > 0 || Number(cio.material_scans) > 0) && (
      <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text2)' }}>
        No material immediate financial notification required. The scanner is operating normally.
      </div>
    )}
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
  const receipts: any[] = Array.isArray(data?.receipts) ? data.receipts : []
  const lastAttempt = data?.last_delivery_attempt
  const lastSuccess = data?.last_success
  const lastFailure = data?.last_failure
  const mode = String(data?.delivery_mode || '—')
  const lastBot = data?.last_delivery_bot || (lastSuccess as any)?.bot_channel
  return <div data-testid="cio-telegram-receipts" style={panel}>
    <div style={{ fontWeight: 800 }}>Telegram receipts</div>
    <div style={{ marginTop: 4, fontSize: 12, color: 'var(--text3)' }}>
      Delivery-mode is CIO-path policy only. PREPARE_ONLY ≠ nothing was ever sent —
      check which bot actually delivered. Empty list means no recorded send on scanned paths.
    </div>
    {loading && <div>Loading…</div>}
    {error && <div style={{ color: 'var(--amber)' }}>{String(error)}</div>}
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '10px 0' }}>
      <Badge tone={mode === 'CIO_ONLY_LIVE' ? 'green' : 'amber'}>{`mode ${mode}`}</Badge>
      <Badge tone={data?.credentials_ready ? 'green' : 'amber'}>{`credentials ready ${!!data?.credentials_ready}`}</Badge>
      <Badge tone={data?.live_authorized ? 'green' : 'slate'}>{`live authorized ${!!data?.live_authorized}`}</Badge>
      <Badge tone={data?.interdicted ? 'amber' : 'green'}>{`interdicted ${!!data?.interdicted}`}</Badge>
      <Badge tone={data?.dedicated_cio_delivered ? 'green' : 'slate'}>{`CIO bot delivered ${!!data?.dedicated_cio_delivered}`}</Badge>
      <Badge tone={data?.generic_ops_delivered ? 'green' : 'slate'}>{`generic bot delivered ${!!data?.generic_ops_delivered}`}</Badge>
      {lastBot && <Badge>{`last delivery bot ${lastBot}`}</Badge>}
    </div>
    {data?.delivery_mode_note && (
      <div style={{ fontSize: 12, color: 'var(--text2)', marginBottom: 8 }}>{String(data.delivery_mode_note)}</div>
    )}
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 8, marginBottom: 12 }}>
      {[
        ['Last attempt', lastAttempt],
        ['Last success', lastSuccess],
        ['Last failure', lastFailure],
      ].map(([title, val]) => (
        <div key={String(title)} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 10 }}>
          <div style={label}>{String(title)}</div>
          <div style={{ fontSize: 12, marginTop: 4, color: 'var(--text1)', wordBreak: 'break-word' }}>
            {val == null || val === ''
              ? '—'
              : typeof val === 'object'
                ? Object.entries(val as Record<string, unknown>).slice(0, 6).map(([k, v]) => (
                  <div key={k}><span style={{ color: 'var(--text3)' }}>{k.replace(/_/g, ' ')}</span>: {String(v ?? '—')}</div>
                ))
                : String(val)}
          </div>
        </div>
      ))}
    </div>
    {receipts.length === 0 ? (
      <div style={{ fontSize: 12, color: 'var(--text3)' }} data-testid="telegram-receipts-empty">
        No receipts recorded on the scanned delivery paths.
      </div>
    ) : (
      <Table
        cols={['at', 'bot', 'ok', 'message_id', 'kind', 'subject']}
        rows={receipts.slice(-40).reverse().map((r: any) => [
          String(r.at || r.ts || r.timestamp || '—').slice(0, 19),
          r.bot_channel || r.bot || r.bot_name || r.sender || '—',
          r.ok === true ? 'ok' : r.ok === false ? 'fail' : (r.status || 'prep'),
          r.message_id ?? '—',
          r.event_type || r.channel || r.kind || '—',
          String(r.subject || r.dedupe_key || r.symbol || r.detail || '').slice(0, 80) || '—',
        ])}
      />
    )}
  </div>
}

export function SensesEvidencePanel() {
  const { data, loading, error } = useApi<any>('/api/v3/maturity/senses', 60_000)
  const receipts: any[] = Array.isArray(data?.financial_senses_receipts)
    ? data.financial_senses_receipts
    : Array.isArray(data?.receipts) ? data.receipts : []
  const providers: any[] = Array.isArray(data?.fs_providers)
    ? data.fs_providers
    : Array.isArray(data?.fs_provider_status?.providers) ? data.fs_provider_status.providers : []
  const unconfiguredProviders = Array.isArray(data?.fs_providers_unconfigured_or_denied)
    ? data.fs_providers_unconfigured_or_denied
    : providers.filter((p: any) => {
      const lab = String(p.label || p.status || '').toLowerCase()
      return lab.includes('denied') || lab.includes('unconfigured')
    })
  const unconfiguredReceipts = receipts.filter((r: any) => {
    const st = String(r.status || r.result || r.quality || '').toUpperCase()
    return st.includes('DENIED') || st.includes('NOT_CONFIGURED') || st.includes('UNCONFIGURED')
  }).length
  return <div data-testid="cio-senses-evidence" style={panel}>
    <div style={{ fontWeight: 800 }}>Senses evidence</div>
    <div style={{ marginTop: 6, fontSize: 12, color: 'var(--text3)' }}>
      Financial Senses receipts from AgentRunTrace / tool traces. Shadow-only; no execution influence.
      {unconfiguredProviders.length > 0
        ? ` · ${unconfiguredProviders.length} provider(s) labeled shadow/unconfigured or DENIED.`
        : ''}
      {unconfiguredReceipts > 0 ? ` · ${unconfiguredReceipts} receipt(s) denied or unconfigured.` : ''}
      {data?.fs_provider_status?.shadow_enabled === false ? ' · AIF shadow OFF → DENIED' : ''}
    </div>
    {loading && <div>Loading…</div>}
    {error && <div style={{ color: 'var(--amber)' }}>{String(error)}</div>}
    {providers.length > 0 && (
      <div style={{ marginTop: 10 }} data-testid="senses-provider-status">
        <div style={label}>FS providers</div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', margin: '6px 0' }}>
          {providers.map((p: any) => (
            <Badge
              key={String(p.provider)}
              tone={String(p.label || '').includes('DENIED') || String(p.label || '').includes('unconfigured') ? 'amber' : 'slate'}
            >{`${p.provider} ${p.label || p.status}`}</Badge>
          ))}
        </div>
        <Table
          cols={['provider', 'label', 'status', 'reason']}
          rows={providers.map((p: any) => [p.provider, p.label, p.status, p.reason])}
        />
      </div>
    )}
    {receipts.length === 0 ? (
      <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 10 }} data-testid="senses-evidence-empty">
        No Financial Senses receipts in store yet.
      </div>
    ) : (
      <div style={{ marginTop: 10 }}>
        <Table
          cols={['as of', 'provider', 'capability', 'status', 'facts', 'note']}
          rows={receipts.slice(0, 40).map((r: any) => [
            r.as_of || r.ts || r.at || '—',
            r.fs_provider || r.provider || '—',
            r.fs_capability || r.capability || '—',
            r.status || r.result || r.quality || '—',
            r.fact_count ?? r.facts_count ?? (Array.isArray(r.facts) ? r.facts.length : '—'),
            String(r.reason || r.note || r.error || '').slice(0, 72) || '—',
          ])}
        />
      </div>
    )}
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
