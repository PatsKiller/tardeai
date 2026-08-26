/** R22 Agent Office — list from CONTROL_PLANE_API_V1_BASELINE GET /api/v3/control-plane/agents.
 *
 * Renders every RuntimeStatus from the payload/item fields:
 * LIVE_EVENT_DRIVEN, LIVE_SCHEDULED, CALLABLE_ONLY, EXPECTED_IDLE, SHADOW, DISABLED, BROKEN
 *
 * Does not compute CIO decisions, notification class, or maturity.
 * Does not infer RuntimeStatus from process existence, queue depth, or last_wake.
 * If the item has no runtime_state or state field, it is absent — not LIVE.
 * Does not replace live /agents. Routes are integrator-owned.
 * Detail uses GET /api/v3/control-plane/agents/{agent_id}. No runtime mock.
 */

import { useState } from 'react'
import type { AgentRuntimeStatus, RuntimeStatus } from '../../../control-plane/contractV1'
import { RUNTIME_STATUS_ORDER } from './contractView'
import {
  ABSENT,
  ApiEnvelopeBanner,
  Chip,
  CollectionNotice,
  ControlPlaneEnvelopeBanner,
  Field,
  cpLabel,
  cpMono,
  cpPanel,
  displayList,
  displayText,
  formatPresentField,
} from './controlPlaneChrome'
import {
  CONTROL_PLANE_AGENTS_URL,
  agentDetailUrl,
  asCollection,
  displayedDataQuality,
  useControlPlaneSummary,
} from './fetchControlPlane'
import { AGENTS_ENVELOPE, FIXTURE_MOCK_LABEL } from './mocks/loadFixtures'

const STATE_TONE: Record<RuntimeStatus, 'green' | 'blue' | 'slate' | 'purple' | 'red' | 'amber'> = {
  LIVE_EVENT_DRIVEN: 'green',
  LIVE_SCHEDULED: 'blue',
  CALLABLE_ONLY: 'slate',
  EXPECTED_IDLE: 'amber',
  SHADOW: 'purple',
  DISABLED: 'slate',
  BROKEN: 'red',
}

/** Keys the list MUST display if present on the item, else "absent" (do not invent). */
export const AGENT_LIST_FIELDS = [
  { header: 'agent / agent_id', keys: ['agent', 'agent_id'] },
  { header: 'role', keys: ['role'] },
  { header: 'runtime_state / state', keys: ['runtime_state', 'state'] },
  { header: 'last_wake', keys: ['last_wake'] },
  { header: 'wake_reason', keys: ['wake_reason'] },
  { header: 'current_task', keys: ['current_task'] },
  { header: 'entity / entity_refs', keys: ['entity', 'entity_refs'] },
  { header: 'queue_depth / queue', keys: ['queue_depth', 'queue'] },
  { header: 'last_success', keys: ['last_success'] },
  { header: 'last_failure', keys: ['last_failure'] },
  { header: 'last_artifact / last_artifact_id', keys: ['last_artifact', 'last_artifact_id'] },
  { header: 'research_route', keys: ['research_route'] },
  { header: 'model_route / route / model', keys: ['model_route', 'route', 'model'] },
  { header: 'latency', keys: ['latency'] },
  { header: 'cost', keys: ['cost'] },
  { header: 'next_eligible_wake', keys: ['next_eligible_wake'] },
  { header: 'evidence_class', keys: ['evidence_class'] },
] as const

function countPayloadStates(agents: AgentRuntimeStatus[]): Record<RuntimeStatus, number> {
  const counts: Record<RuntimeStatus, number> = {
    LIVE_EVENT_DRIVEN: 0,
    LIVE_SCHEDULED: 0,
    CALLABLE_ONLY: 0,
    EXPECTED_IDLE: 0,
    SHADOW: 0,
    DISABLED: 0,
    BROKEN: 0,
  }
  for (const agent of agents) {
    if (Object.prototype.hasOwnProperty.call(counts, agent.state)) {
      counts[agent.state] += 1
    }
  }
  return counts
}

function countItemStates(items: Record<string, unknown>[]): Record<RuntimeStatus, number> {
  const counts: Record<RuntimeStatus, number> = {
    LIVE_EVENT_DRIVEN: 0,
    LIVE_SCHEDULED: 0,
    CALLABLE_ONLY: 0,
    EXPECTED_IDLE: 0,
    SHADOW: 0,
    DISABLED: 0,
    BROKEN: 0,
  }
  for (const item of items) {
    const seen = new Set<RuntimeStatus>()
    for (const key of ['runtime_state', 'state'] as const) {
      if (!Object.prototype.hasOwnProperty.call(item, key)) continue
      const value = item[key]
      if (typeof value === 'string' && Object.prototype.hasOwnProperty.call(counts, value)) {
        seen.add(value as RuntimeStatus)
      }
    }
    for (const state of seen) counts[state] += 1
  }
  return counts
}

function itemHasStatus(item: Record<string, unknown>, status: RuntimeStatus): boolean {
  for (const key of ['runtime_state', 'state'] as const) {
    if (Object.prototype.hasOwnProperty.call(item, key) && item[key] === status) return true
  }
  return false
}

function presentId(item: Record<string, unknown> | null): string {
  if (!item) return ''
  for (const key of ['agent_id', 'agent', 'id'] as const) {
    if (Object.prototype.hasOwnProperty.call(item, key) && item[key] != null && item[key] !== '') {
      return String(item[key])
    }
  }
  return ''
}

function presentId(item: Record<string, unknown> | null): string {
  if (!item) return ''
  for (const key of ['agent_id', 'agent', 'id'] as const) {
    if (Object.prototype.hasOwnProperty.call(item, key) && item[key] != null && item[key] !== '') {
      return String(item[key])
    }
  }
  return ''
}

function itemRowKey(item: Record<string, unknown>, index: number): string {
  for (const key of ['agent_id', 'agent', 'id'] as const) {
    if (Object.prototype.hasOwnProperty.call(item, key) && item[key] != null && item[key] !== '') {
      return `${key}:${String(item[key])}`
    }
  }
  return `index:${index}`
}

function AgentDetailPanel({ agentId }: { agentId: string }) {
  const url = agentId ? agentDetailUrl(agentId) : ''
  const { phase, envelope } = useControlPlaneSummary(url)
  if (!agentId) {
    return <div style={{ ...cpMono, marginTop: 10, color: 'var(--text3)' }}>No agent_id on the selected list item.</div>
  }
  if (phase === 'LOADING' || envelope == null) {
    return <div style={{ ...cpMono, marginTop: 10 }} data-testid="agent-detail-loading">LOADING {url}</div>
  }
  const data = envelope.data && typeof envelope.data === 'object' ? envelope.data as Record<string, unknown> : {}
  const keys = [
    'agent_id', 'role', 'runtime_state', 'trigger_classes', 'last_wake', 'wake_reason',
    'current_task', 'entity_refs', 'queue_depth', 'last_success', 'last_failure',
    'last_artifact', 'research_route', 'model_route', 'latency', 'cost',
    'next_eligible_wake', 'evidence_class', 'status', 'data_quality', 'source_sha',
  ]
  return (
    <div data-testid="agent-detail" data-source="api" data-detail-url={url}>
      <div style={cpLabel}>GET {url} · data_quality={envelope.data_quality} · evidence_class={envelope.evidence_class}</div>
      <div style={{ display: 'grid', gap: 10, marginTop: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
        {keys.map(key => (
          <Field key={key} k={key} v={formatPresentField(data, [key])} />
        ))}
      </div>
    </div>
  )
}

function RuntimeStateCell({ item }: { item: Record<string, unknown> }) {
  const chips = []
  for (const key of ['runtime_state', 'state'] as const) {
    if (!Object.prototype.hasOwnProperty.call(item, key)) continue
    const value = item[key]
    const tone = typeof value === 'string' && Object.prototype.hasOwnProperty.call(STATE_TONE, value)
      ? STATE_TONE[value as RuntimeStatus]
      : 'slate'
    chips.push(
      <Chip key={key} tone={tone}>
        {key}={value == null ? 'null' : String(value)}
      </Chip>,
    )
  }
  if (chips.length === 0) return <span style={cpMono}>{ABSENT}</span>
  return <span style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>{chips}</span>
}

function LoadingShell({ title }: { title: string }) {
  return (
    <div data-page="agent-office" data-phase="LOADING" style={{ display: 'grid', gap: 14, maxWidth: 1280 }}>
      <div style={{ fontSize: 16, fontWeight: 800, letterSpacing: '.04em', color: 'var(--text0)' }}>{title}</div>
      <div style={{ ...cpPanel, ...cpMono }}>LOADING</div>
    </div>
  )
}

export default function AgentOfficePage() {
  const { phase, envelope } = useControlPlaneSummary(CONTROL_PLANE_AGENTS_URL)
  const fixture = AGENTS_ENVELOPE
  const fixtureAgents = fixture.payload.agents
  const fixtureCounts = countPayloadStates(fixtureAgents)
  const [filter, setFilter] = useState<RuntimeStatus | 'ALL'>('ALL')
  const [selectedKey, setSelectedKey] = useState<string>('')

  if (phase === 'LOADING' || envelope == null) {
    return <LoadingShell title="AGENT OFFICE" />
  }

  const collection = asCollection(envelope.data)
  const displayQuality = displayedDataQuality(envelope, collection)
  const items = collection?.items ?? []
  const counts = countItemStates(items)
  const visible = filter === 'ALL' ? items : items.filter(item => itemHasStatus(item, filter))
  const selected = visible.find((item, i) => itemRowKey(item, i) === selectedKey) ?? visible[0] ?? null
  const selectedId = presentId(selected)

  return (
    <div data-page="agent-office" data-phase="READY" data-live-claim="false" style={{ display: 'grid', gap: 14, maxWidth: 1280 }}>
      <ApiEnvelopeBanner
        title="AGENT OFFICE"
        routeHint="/control-plane/agents"
        summaryUrl={CONTROL_PLANE_AGENTS_URL}
        envelope={envelope}
        collection={collection}
        displayQuality={displayQuality}
      />

      <div style={{ ...cpPanel, borderLeft: '3px solid var(--amber)' }}>
        <div style={cpLabel}>List source</div>
        <div style={{ ...cpMono, marginTop: 6, color: 'var(--text2)', lineHeight: 1.5 }}>
          GET {CONTROL_PLANE_AGENTS_URL} · authority READ_ONLY_ADVISORY · MEMORY_BEHAVIOR_INFLUENCE=0 ·
          this page does not infer LIVE from a process, pid, or queue.
          runtime_state OR state is rendered if present; they are not mapped as if computed.
        </div>
      </div>

      <section style={cpPanel}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <div style={cpLabel}>RuntimeStatus · every contract value is shown, including zero-count</div>
          <Chip tone={filter === 'ALL' ? 'amber' : 'slate'} active={filter === 'ALL'} onClick={() => setFilter('ALL')}>
            ALL {items.length}
          </Chip>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }} data-testid="runtime-status-legend">
          {RUNTIME_STATUS_ORDER.map(state => (
            <Chip
              key={state}
              tone={STATE_TONE[state]}
              active={filter === state}
              onClick={() => setFilter(state)}
            >
              <span data-runtime-status={state}>{state}</span>
              <span style={{ color: 'var(--text3)' }}>{counts[state]}</span>
            </Chip>
          ))}
        </div>
      </section>

      <section style={{ ...cpPanel, overflow: 'auto' }} data-testid="agent-api-list" data-source="api">
        <div style={cpLabel}>Agents · GET {CONTROL_PLANE_AGENTS_URL} items (not FIXTURE)</div>
        <CollectionNotice displayQuality={displayQuality} envelopeQuality={envelope.data_quality} />
        <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 8, fontSize: 11 }}>
          <thead>
            <tr style={{ ...cpLabel, textAlign: 'left' }}>
              {AGENT_LIST_FIELDS.map(field => (
                <th key={field.header} style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)', fontWeight: 800 }}>
                  {field.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((item, index) => {
              const key = itemRowKey(item, index)
              const on = selected === item
              return (
                <tr
                  key={key}
                  data-agent-row={key}
                  onClick={() => setSelectedKey(key)}
                  style={{ cursor: 'pointer', background: on ? 'var(--bg2)' : 'transparent' }}
                >
                  {AGENT_LIST_FIELDS.map(field => (
                    <td
                      key={field.header}
                      style={{ ...cpMono, padding: '7px 8px', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text1)' }}
                    >
                      {field.keys[0] === 'runtime_state' ? <RuntimeStateCell item={item} /> : formatPresentField(item, field.keys)}
                    </td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
        {visible.length === 0 && (
          <div style={{ ...cpMono, marginTop: 10, color: 'var(--text3)' }}>
            No items to display for this filter. Missing keys would show {ABSENT} — they are not invented as LIVE.
          </div>
        )}
      </section>

      <section style={cpPanel} data-source="api">
        <div style={cpLabel}>Selected list item · keys if present, else absent · not GET /agents/id</div>
        {selected ? (
          <div style={{ display: 'grid', gap: 10, marginTop: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }} data-testid="agent-api-selected">
            {AGENT_LIST_FIELDS.map(field => (
              <Field key={field.header} k={field.header} v={formatPresentField(selected, field.keys)} />
            ))}
          </div>
        ) : (
          <div style={{ ...cpMono, marginTop: 10, color: 'var(--text3)' }}>
            No API item selected. {displayQuality}
          </div>
        )}
      </section>

      <section style={cpPanel} data-source="api" data-testid="agent-detail-api">
        <div style={cpLabel}>Agent detail · GET /api/v3/control-plane/agents/{'{agent_id}'} · not a runtime mock</div>
        <AgentDetailPanel agentId={selectedId} />
      </section>

      <details style={cpPanel} data-testid="fixture-preview" data-source="TEST_FIXTURE" data-role="TEST_FIXTURE">
        <summary style={{ ...cpLabel, cursor: 'pointer' }}>
          TEST_FIXTURE only · ControlPlane@v1.0.0 · not a runtime substitute
        </summary>
        <div style={{ marginTop: 10 }}>
          <ControlPlaneEnvelopeBanner
            title="AGENT OFFICE FIXTURE PREVIEW"
            routeHint="/control-plane/agents"
            envelope={fixture}
          />
          <div style={{ ...cpMono, marginTop: 8, color: 'var(--text2)', lineHeight: 1.5 }}>
            on_current_runtime={String(fixture.payload.on_current_runtime)} · payload.state is fixture payload.state ·
            this preview does not infer LIVE from a process, pid, or queue.
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
            {RUNTIME_STATUS_ORDER.map(state => (
              <Chip key={state} tone={STATE_TONE[state]}>
                <span data-fixture-runtime-status={state}>{state}</span>
                <span style={{ color: 'var(--text3)' }}>{fixtureCounts[state]}</span>
              </Chip>
            ))}
          </div>
        </div>
      </details>
    </div>
  )
}
