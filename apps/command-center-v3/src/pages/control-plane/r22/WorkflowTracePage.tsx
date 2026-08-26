/** R22 Workflow Trace — list from CONTROL_PLANE_API_V1_BASELINE GET /api/v3/control-plane/workflows.
 *
 * Lineage graph uses GET /api/v3/control-plane/workflows/{id} (R21.1). No runtime mock.
 * Cross-ID lookup uses the same endpoint (event/decision/generation/artifact/notification/checkpoint/outcome).
 * Contract order (not inferred): event → entity → materiality → graph → research → specialist → council → cio → notification → checkpoint → outcome → learning
 *
 * Node labels (including CIO / notification) are opaque payload strings.
 * This page does not compute CIO decisions, notification class, or maturity.
 * Does not infer missing lineage nodes from other fields.
 * Does not replace live /system. Routes are integrator-owned.
 */

import { useState } from 'react'
import type { WorkflowNode, WorkflowNodeKind, WorkflowTrace } from '../../../control-plane/contractV1'
import { WORKFLOW_LINEAGE_ARROW, WORKFLOW_LINEAGE_ORDER } from './contractView'
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
  CONTROL_PLANE_WORKFLOWS_URL,
  asCollection,
  displayedDataQuality,
  useControlPlaneSummary,
  workflowDetailUrl,
} from './fetchControlPlane'
import { FIXTURE_MOCK_LABEL, WORKFLOWS_ENVELOPE } from './mocks/loadFixtures'

const KIND_TONE: Record<WorkflowNodeKind, 'green' | 'blue' | 'amber' | 'purple' | 'slate' | 'red'> = {
  event: 'amber',
  entity: 'blue',
  materiality: 'amber',
  graph: 'slate',
  research: 'blue',
  specialist: 'green',
  council: 'purple',
  cio: 'amber',
  notification: 'slate',
  checkpoint: 'blue',
  outcome: 'green',
  learning: 'purple',
}

/** List keys if present, else absent. Do not invent lineage nodes from these fields. */
export const WORKFLOW_LIST_FIELDS = [
  { header: 'trace_id / workflow_id', keys: ['trace_id', 'workflow_id', 'id', 'event_id'] },
  { header: 'status', keys: ['status'] },
  { header: 'evidence_class', keys: ['evidence_class'] },
  { header: 'source_sha', keys: ['source_sha'] },
  { header: 'started_at', keys: ['started_at'] },
  { header: 'updated_at', keys: ['updated_at'] },
  { header: 'failure_reason', keys: ['failure_reason'] },
] as const

function nodesInLineageOrder(nodes: WorkflowNode[]): WorkflowNode[] {
  const used = new Set<string>()
  const ordered: WorkflowNode[] = []
  for (const kind of WORKFLOW_LINEAGE_ORDER) {
    for (const node of nodes) {
      if (node.kind === kind && !used.has(node.node_id)) {
        used.add(node.node_id)
        ordered.push(node)
      }
    }
  }
  for (const node of nodes) {
    if (!used.has(node.node_id)) ordered.push(node)
  }
  return ordered
}

function firstOfKind(nodes: WorkflowNode[], kind: WorkflowNodeKind): WorkflowNode | undefined {
  return nodes.find(n => n.kind === kind)
}

function itemRowKey(item: Record<string, unknown>, index: number): string {
  for (const key of ['trace_id', 'workflow_id', 'id', 'event_id'] as const) {
    if (Object.prototype.hasOwnProperty.call(item, key) && item[key] != null && item[key] !== '') {
      return `${key}:${String(item[key])}`
    }
  }
  return `index:${index}`
}

function presentWorkflowId(item: Record<string, unknown> | null): string {
  if (!item) return ''
  for (const key of ['workflow_id', 'trace_id', 'id', 'event_id', 'decision_id', 'generation_id'] as const) {
    if (Object.prototype.hasOwnProperty.call(item, key) && item[key] != null && item[key] !== '') {
      return String(item[key])
    }
  }
  return ''
}

function ApiTraceBody({ lookupId }: { lookupId: string }) {
  const url = lookupId ? workflowDetailUrl(lookupId) : ''
  const { phase, envelope } = useControlPlaneSummary(url)
  const [selectedId, setSelectedId] = useState('')
  if (!lookupId) {
    return <div style={{ ...cpPanel, ...cpMono, color: 'var(--text3)' }}>No workflow id on the selected list item.</div>
  }
  if (phase === 'LOADING' || envelope == null) {
    return <div style={cpPanel} data-testid="workflow-detail-loading">LOADING {url}</div>
  }
  const data = envelope.data && typeof envelope.data === 'object' ? envelope.data as Record<string, unknown> : {}
  const nodes = Array.isArray(data.nodes) ? data.nodes.filter(n => n && typeof n === 'object') as Record<string, unknown>[] : []
  const edges = Array.isArray(data.edges) ? data.edges.filter(e => e && typeof e === 'object') as Record<string, unknown>[] : []
  const identifiers = data.identifiers && typeof data.identifiers === 'object' ? data.identifiers as Record<string, unknown> : {}
  const selected = nodes.find(n => String(n.node_id) === selectedId) ?? nodes[0] ?? null
  return (
    <div style={{ display: 'grid', gap: 12 }} data-source="api" data-testid="workflow-detail-api" data-detail-url={url}>
      <section style={cpPanel} data-testid="workflow-lineage">
        <div style={cpLabel}>GET {url} · workflow_id={String(data.workflow_id ?? ABSENT)} · resolved_from={String(data.resolved_from ?? ABSENT)}</div>
        <div style={{ ...cpMono, marginTop: 8 }}>{WORKFLOW_LINEAGE_ARROW}</div>
        <div style={{ ...cpMono, marginTop: 8 }}>
          data_quality={envelope.data_quality} evidence_class={String(data.evidence_class ?? envelope.evidence_class)} source_sha={String(data.source_sha ?? envelope.source_sha)}
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }} data-testid="workflow-identifiers">
          {Object.entries(identifiers).map(([k, v]) => (
            <Chip key={k}>{k}={String(v)}</Chip>
          ))}
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
          {nodes.map(node => (
            <Chip key={String(node.node_id)} active={selected?.node_id === node.node_id} onClick={() => setSelectedId(String(node.node_id))}>
              {String(node.node_type ?? node.node_id)} · {String(node.status ?? ABSENT)}
            </Chip>
          ))}
        </div>
      </section>
      <section style={cpPanel}>
        <div style={cpLabel}>Selected node · fields as projected · no invented nodes</div>
        {selected ? (
          <div style={{ display: 'grid', gap: 8, marginTop: 8, gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
            {Object.keys(selected).map(k => <Field key={k} k={k} v={formatPresentField(selected, [k])} />)}
          </div>
        ) : (
          <div style={{ ...cpMono, marginTop: 8, color: 'var(--text3)' }}>No nodes in detail payload.</div>
        )}
      </section>
      <section style={cpPanel} data-testid="workflow-edges">
        <div style={cpLabel}>Edges · certainty as projected (UNRESOLVED_LINK / LEGACY_REFERENCE / MISSING_PARENT / UNAVAILABLE_STORE / QUARANTINED_RECORD)</div>
        {edges.length === 0 ? (
          <div style={{ ...cpMono, marginTop: 8, color: 'var(--text3)' }}>No edges.</div>
        ) : edges.map((edge, i) => (
          <div key={i} style={{ ...cpMono, marginTop: 6 }} data-certainty={String(edge.certainty)}>
            {String(edge.from)} → {String(edge.to)} · {String(edge.relationship)} · {String(edge.certainty)}
          </div>
        ))}
      </section>
    </div>
  )
}

function TraceBody({ trace }: { trace: WorkflowTrace }) {
  const ordered = nodesInLineageOrder(trace.nodes)
  const [selectedId, setSelectedId] = useState<string>(ordered[0]?.node_id ?? '')
  const selected = ordered.find(n => n.node_id === selectedId) ?? ordered[0] ?? null

  return (
    <div style={{ display: 'grid', gap: 12 }} data-source="FIXTURE/MOCK">
      <section style={cpPanel} data-testid="workflow-lineage">
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          <Chip tone="amber">FIXTURE</Chip>
          <Chip tone="amber">MOCK</Chip>
          <span style={cpLabel}>{FIXTURE_MOCK_LABEL}</span>
        </div>
        <div style={{ ...cpLabel, marginTop: 8 }}>Lineage · contract order (not inferred)</div>
        <div style={{ ...cpMono, marginTop: 8, color: 'var(--text0)' }}>{WORKFLOW_LINEAGE_ARROW}</div>
        <div style={{ ...cpMono, marginTop: 6, color: 'var(--text2)', lineHeight: 1.45 }}>
          EVENT → ENTITY → MATERIALITY → GRAPH → RESEARCH → SPECIALIST → COUNCIL → CIO PRODUCT → NOTIFICATION → CHECKPOINT → OUTCOME → LEARNING
          · R21.1 workflow detail is pending. Do not infer missing lineage nodes from other fields. Label is opaque. CIO / notification / maturity are not computed here.
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6, marginTop: 10 }}>
          {WORKFLOW_LINEAGE_ORDER.map((kind, i) => {
            const node = firstOfKind(trace.nodes, kind)
            return (
              <span key={kind} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                {i > 0 && <span style={{ color: 'var(--text3)', fontSize: 12 }}>→</span>}
                <Chip
                  tone={node ? KIND_TONE[kind] : 'slate'}
                  active={selected?.kind === kind}
                  onClick={node ? () => setSelectedId(node.node_id) : undefined}
                >
                  <span data-lineage-kind={kind}>{kind}</span>
                  <span style={{ color: 'var(--text3)' }}>{node ? node.status : 'ABSENT'}</span>
                </Chip>
              </span>
            )
          })}
        </div>
      </section>

      <div style={{ ...cpPanel, display: 'grid', gap: 8 }}>
        <div style={cpLabel}>Trace · {FIXTURE_MOCK_LABEL}</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
          <span style={{ ...cpMono, color: 'var(--text0)' }}>{trace.trace_id}</span>
          <Chip tone="green">{trace.status}</Chip>
          <Chip tone="slate">{trace.evidence_class}</Chip>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10 }}>
          <Field k="source_sha" v={trace.source_sha} />
          <Field k="started_at" v={trace.started_at} />
          <Field k="updated_at" v={trace.updated_at} />
          <Field k="failure_reason" v={displayText(trace.failure_reason)} />
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12, alignItems: 'start' }}>
        <section style={cpPanel}>
          <div style={cpLabel}>Nodes · event → … → learning · FIXTURE/MOCK</div>
          <ol data-testid="workflow-nodes" style={{ listStyle: 'none', marginTop: 10, display: 'grid', gap: 0, borderLeft: '2px solid var(--border)', paddingLeft: 0 }}>
            {ordered.map((node, idx) => {
              const on = selected?.node_id === node.node_id
              return (
                <li
                  key={node.node_id}
                  data-node-kind={node.kind}
                  data-node-id={node.node_id}
                  onClick={() => setSelectedId(node.node_id)}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '18px minmax(0, 1fr)',
                    gap: 8,
                    padding: '8px 8px 8px 0',
                    background: on ? 'var(--bg2)' : 'transparent',
                    cursor: 'pointer',
                    borderBottom: '1px solid var(--border-subtle)',
                  }}
                >
                  <div style={{ ...cpMono, color: 'var(--text3)', textAlign: 'right' }}>{idx + 1}</div>
                  <div>
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                      <Chip tone={KIND_TONE[node.kind]}>{node.kind}</Chip>
                      <span style={{ ...cpMono, color: 'var(--text3)' }}>{node.status}</span>
                      <span style={{ ...cpMono, color: 'var(--text3)' }}>{node.evidence_class}</span>
                    </div>
                    <div style={{ marginTop: 4, fontSize: 12, color: 'var(--text1)', lineHeight: 1.4 }}>{node.label}</div>
                  </div>
                </li>
              )
            })}
          </ol>
        </section>

        <section style={cpPanel}>
          <div style={cpLabel}>Selected node · payload fields only · {FIXTURE_MOCK_LABEL}</div>
          {selected ? (
            <div style={{ display: 'grid', gap: 10, marginTop: 10 }} data-testid="workflow-node-detail">
              <Field k="node_id" v={selected.node_id} />
              <Field k="kind" v={<Chip tone={KIND_TONE[selected.kind]}>{selected.kind}</Chip>} />
              <Field k="label" v={selected.label} />
              <Field k="status" v={selected.status} />
              <Field k="entity_refs" v={displayList(selected.entity_refs)} />
              <Field k="artifact_refs" v={displayList(selected.artifact_refs)} />
              <Field k="started_at" v={displayText(selected.started_at)} />
              <Field k="ended_at" v={displayText(selected.ended_at)} />
              <Field k="evidence_class" v={selected.evidence_class} />
              <div style={{ ...cpMono, color: 'var(--text3)', lineHeight: 1.45 }}>
                label is opaque. CIO / notification / maturity are not computed here.
              </div>
            </div>
          ) : (
            <div style={{ ...cpMono, marginTop: 10, color: 'var(--text3)' }}>No nodes in payload.</div>
          )}
        </section>
      </div>

      <section style={cpPanel}>
        <div style={cpLabel}>Edges · causal_reason as provided · {FIXTURE_MOCK_LABEL}</div>
        <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 8, fontSize: 11 }}>
          <thead>
            <tr style={{ ...cpLabel, textAlign: 'left' }}>
              {['edge_id', 'from_node', 'to_node', 'event_id', 'causal_reason'].map(h => (
                <th key={h} style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)', fontWeight: 800 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {trace.edges.map(edge => (
              <tr key={edge.edge_id}>
                <td style={{ ...cpMono, padding: '7px 8px', borderBottom: '1px solid var(--border-subtle)' }}>{edge.edge_id}</td>
                <td style={{ ...cpMono, padding: '7px 8px', borderBottom: '1px solid var(--border-subtle)' }}>{edge.from_node}</td>
                <td style={{ ...cpMono, padding: '7px 8px', borderBottom: '1px solid var(--border-subtle)' }}>{edge.to_node}</td>
                <td style={{ ...cpMono, padding: '7px 8px', borderBottom: '1px solid var(--border-subtle)' }}>{displayText(edge.event_id)}</td>
                <td style={{ padding: '7px 8px', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text2)' }}>{edge.causal_reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}

function LoadingShell() {
  return (
    <div data-page="workflow-trace" data-phase="LOADING" style={{ display: 'grid', gap: 14, maxWidth: 1280 }}>
      <div style={{ fontSize: 16, fontWeight: 800, letterSpacing: '.04em', color: 'var(--text0)' }}>WORKFLOW TRACE</div>
      <div style={{ ...cpPanel, ...cpMono }}>LOADING</div>
    </div>
  )
}

export default function WorkflowTracePage() {
  const { phase, envelope } = useControlPlaneSummary(CONTROL_PLANE_WORKFLOWS_URL)
  const fixture = WORKFLOWS_ENVELOPE
  const [selectedKey, setSelectedKey] = useState<string>('')
  const [crossId, setCrossId] = useState<string>('')
  const [lookupId, setLookupId] = useState<string>('')

  if (phase === 'LOADING' || envelope == null) {
    return <LoadingShell />
  }

  const collection = asCollection(envelope.data)
  const displayQuality = displayedDataQuality(envelope, collection)
  const items = collection?.items ?? []
  const selected = items.find((item, i) => itemRowKey(item, i) === selectedKey) ?? items[0] ?? null

  return (
    <div data-page="workflow-trace" data-phase="READY" data-live-claim="false" style={{ display: 'grid', gap: 14, maxWidth: 1280 }}>
      <ApiEnvelopeBanner
        title="WORKFLOW TRACE"
        routeHint="/control-plane/workflows"
        summaryUrl={CONTROL_PLANE_WORKFLOWS_URL}
        envelope={envelope}
        collection={collection}
        displayQuality={displayQuality}
      />

      <div style={{ ...cpPanel, borderLeft: '3px solid var(--amber)' }}>
        <div style={cpLabel}>List source</div>
        <div style={{ ...cpMono, marginTop: 6, color: 'var(--text2)', lineHeight: 1.5 }}>
          GET {CONTROL_PLANE_WORKFLOWS_URL} · authority READ_ONLY_ADVISORY · MEMORY_BEHAVIOR_INFLUENCE=0 ·
          API existence is not a LIVE claim. Lineage is GET /api/v3/control-plane/workflows/id — no frontend reconstruction.
        </div>
      </div>

      <section style={{ ...cpPanel, overflow: 'auto' }} data-testid="workflow-api-list" data-source="api">
        <div style={cpLabel}>Workflows · GET {CONTROL_PLANE_WORKFLOWS_URL} items (not FIXTURE)</div>
        <CollectionNotice displayQuality={displayQuality} envelopeQuality={envelope.data_quality} />
        <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 8, fontSize: 11 }}>
          <thead>
            <tr style={{ ...cpLabel, textAlign: 'left' }}>
              {WORKFLOW_LIST_FIELDS.map(field => (
                <th key={field.header} style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)', fontWeight: 800 }}>
                  {field.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((item, index) => {
              const key = itemRowKey(item, index)
              const on = selected === item
              return (
                <tr
                  key={key}
                  data-workflow-row={key}
                  onClick={() => setSelectedKey(key)}
                  style={{ cursor: 'pointer', background: on ? 'var(--bg2)' : 'transparent' }}
                >
                  {WORKFLOW_LIST_FIELDS.map(field => (
                    <td
                      key={field.header}
                      style={{ ...cpMono, padding: '7px 8px', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text1)' }}
                    >
                      {formatPresentField(item, field.keys)}
                    </td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
        {items.length === 0 && (
          <div style={{ ...cpMono, marginTop: 10, color: 'var(--text3)' }}>
            No workflow items. Missing keys would show {ABSENT}. Lineage nodes are not inferred from list fields.
          </div>
        )}
      </section>

      <section style={cpPanel} data-source="api">
        <div style={cpLabel}>Selected list item · keys if present, else absent · not GET /workflows/id</div>
        {selected ? (
          <div style={{ display: 'grid', gap: 10, marginTop: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }} data-testid="workflow-api-selected">
            {WORKFLOW_LIST_FIELDS.map(field => (
              <Field key={field.header} k={field.header} v={formatPresentField(selected, field.keys)} />
            ))}
          </div>
        ) : (
          <div style={{ ...cpMono, marginTop: 10, color: 'var(--text3)' }}>
            No API item selected. {displayQuality}
          </div>
        )}
      </section>

      <section style={cpPanel} data-testid="workflow-cross-id">
        <div style={cpLabel}>Cross-ID lookup · same GET detail endpoint · no reconstruction</div>
        <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
          <input
            value={crossId}
            onChange={e => setCrossId(e.target.value)}
            placeholder="event_id / decision_id / generation_id / artifact_id / notification_id / checkpoint_id / outcome_id"
            style={{ ...cpMono, flex: 1, minWidth: 240, padding: 8, background: 'var(--bg1)', color: 'var(--text0)', border: '1px solid var(--border)' }}
          />
          <Chip tone="amber" onClick={() => setLookupId(crossId.trim())}>open</Chip>
        </div>
      </section>

      <ApiTraceBody lookupId={lookupId || presentWorkflowId(selected)} />

      <details style={cpPanel} data-testid="fixture-preview" data-source="TEST_FIXTURE" data-role="TEST_FIXTURE">
        <summary style={{ ...cpLabel, cursor: 'pointer' }}>
          TEST_FIXTURE only · ControlPlane@v1.0.0 · not a runtime substitute
        </summary>
        <div style={{ marginTop: 10 }}>
          <ControlPlaneEnvelopeBanner
            title="WORKFLOW TRACE FIXTURE PREVIEW"
            routeHint="/control-plane/workflows"
            envelope={fixture}
          />
        </div>
      </details>
    </div>
  )
}
