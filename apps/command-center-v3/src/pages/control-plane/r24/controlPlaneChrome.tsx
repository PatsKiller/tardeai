/** Shared read-only chrome for R24 control-plane pages.
 *  CSS variables only (design-token guard). No score math. No live claims.
 *  Live contract is CONTROL_PLANE_API_V1_BASELINE (`data`, not `payload`). */

import type { CSSProperties, ReactNode } from 'react'
import { CONTROL_PLANE_API_V1_BASELINE } from './httpEnvelope'
import type { ControlPlaneView } from './useControlPlaneEnvelope'

const pageWrap: CSSProperties = {
  display: 'grid',
  gap: 12,
  maxWidth: 1280,
}

const banner: CSSProperties = {
  background: 'var(--amber-dim)',
  border: '1px solid var(--amber)',
  borderRadius: 6,
  padding: '10px 12px',
  color: 'var(--amber)',
  fontSize: 12,
  lineHeight: 1.45,
}

const panel: CSSProperties = {
  background: 'var(--bg1)',
  border: '1px solid var(--border)',
  borderRadius: 6,
  padding: 12,
}

const eyebrow: CSSProperties = {
  fontFamily: 'var(--mono)',
  fontSize: 10,
  fontWeight: 700,
  letterSpacing: '0.08em',
  textTransform: 'uppercase',
  color: 'var(--text3)',
}

const titleStyle: CSSProperties = {
  fontSize: 16,
  fontWeight: 800,
  color: 'var(--text0)',
  letterSpacing: '0.02em',
}

const metaGrid: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
  gap: 8,
  marginTop: 10,
}

const metaCell: CSSProperties = {
  background: 'var(--bg2)',
  border: '1px solid var(--border-subtle)',
  borderRadius: 4,
  padding: '8px 10px',
}

const tableWrap: CSSProperties = {
  overflowX: 'auto',
}

const tableStyle: CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  fontSize: 12,
}

const thStyle: CSSProperties = {
  textAlign: 'left',
  fontFamily: 'var(--mono)',
  fontSize: 10,
  fontWeight: 700,
  letterSpacing: '0.06em',
  textTransform: 'uppercase',
  color: 'var(--text3)',
  borderBottom: '1px solid var(--border)',
  padding: '8px 8px 8px 0',
  whiteSpace: 'nowrap',
}

const tdStyle: CSSProperties = {
  padding: '8px 8px 8px 0',
  borderBottom: '1px solid var(--border-subtle)',
  color: 'var(--text1)',
  verticalAlign: 'top',
  fontFamily: 'var(--mono)',
  fontSize: 12,
  lineHeight: 1.4,
}

const chipStyle: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  padding: '2px 8px',
  borderRadius: 999,
  border: '1px solid var(--border)',
  background: 'var(--bg2)',
  color: 'var(--text1)',
  fontFamily: 'var(--mono)',
  fontSize: 10,
  fontWeight: 700,
  letterSpacing: '0.04em',
}

export function renderField(value: unknown): string {
  if (value === null) return 'null'
  if (value === undefined) return 'undefined'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return value.map(item => renderField(item)).join(', ')
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

export function projectionEmptyLabel(viewState: string, fallback: string): string {
  if (viewState === 'PENDING') return 'GET pending'
  if (viewState === 'UNAVAILABLE') return 'UNAVAILABLE'
  if (viewState === 'INVALID_SCHEMA') return 'INVALID_SCHEMA'
  if (viewState === 'BROKEN') return 'BROKEN'
  if (viewState === 'NO_RELEVANT_EVENTS') return 'NO_RELEVANT_EVENTS'
  if (viewState === 'EMPTY_VALID') return 'EMPTY_VALID'
  if (viewState === 'STALE') return 'STALE'
  if (viewState === 'DEGRADED') return 'DEGRADED'
  return fallback
}

export function EnvelopeBanner(props: {
  title: string
  route: string
  view: ControlPlaneView
  extra?: ReactNode
}) {
  const { title, route, view, extra } = props
  const fixtureNote = view.fixtureLabel
    ? 'FIXTURE · labeled for tests only · not the live view · '
    : ''
  return (
    <section style={panel} data-testid="control-plane-envelope">
      <div style={eyebrow}>Control plane · summary GET · not live</div>
      <div style={{ ...titleStyle, marginTop: 4 }}>{title}</div>
      <div style={{ marginTop: 6, fontSize: 12, color: 'var(--text2)', lineHeight: 1.45 }}>
        Route {route} is a preview beside existing Command Center pages. Integrator owns
        shell and navigation registration. Existing production routes stay untouched.
        This page does not claim R20-R24 live. Live path is GET CONTROL_PLANE_API_V1_BASELINE
        data.items. Frozen ControlPlane@v1.0.0 JSON is labeled FIXTURE for tests only.
      </div>
      <div style={{ ...banner, marginTop: 10 }}>
        NOT LIVE · {fixtureNote}liveClaim={renderField(view.liveClaim)} ·
        view_state={view.viewState} · data_quality={renderField(view.dataQuality)} ·
        contract={view.contract} · data_source={view.dataSource} ·
        authority={view.authority} · memory_behavior_influence={renderField(view.memoryBehaviorInfluence)} ·
        financial_action={renderField(view.financialAction)}
        {view.error ? ` · ${view.error}` : ''}
      </div>
      <div style={metaGrid}>
        <Meta label="page" value={view.page} />
        <Meta label="view_state" value={view.viewState} />
        <Meta label="data_quality" value={renderField(view.dataQuality)} />
        <Meta label="ok" value={renderField(view.ok)} />
        <Meta label="as_of" value={renderField(view.asOf)} />
        <Meta label="freshness" value={renderField(view.freshness)} />
        <Meta label="evidence_class" value={renderField(view.evidenceClass)} />
        <Meta label="source_sha" value={renderField(view.sourceSha)} />
        <Meta label="pagination.limit" value={renderField(view.pagination?.limit)} />
        <Meta label="pagination.offset" value={renderField(view.pagination?.offset)} />
        <Meta label="pagination.total" value={renderField(view.pagination?.total)} />
        <Meta label="computes_cio_decisions" value={renderField(view.computesCioDecisions)} />
        <Meta label="computes_agent_state" value={renderField(view.computesAgentState)} />
        <Meta label="computes_maturity" value={renderField(view.computesMaturity)} />
        <Meta label="computes_notification_eligibility" value={renderField(view.computesNotificationEligibility)} />
        <Meta label="http_contract" value={CONTROL_PLANE_API_V1_BASELINE} />
        <Meta label="vocabulary" value="ControlPlane@v1.0.0" />
      </div>
      {extra}
    </section>
  )
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div style={metaCell}>
      <div style={eyebrow}>{label}</div>
      <div style={{ marginTop: 4, fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--text0)', wordBreak: 'break-word' }}>
        {value}
      </div>
    </div>
  )
}

export function ProjectionStatePanel({ view }: { view: ControlPlaneView }) {
  return (
    <Panel
      title={`projection ${view.viewState}`}
      kicker="page truth · CONTROL_PLANE_API_V1_BASELINE"
      testId="projection-state"
    >
      <div style={{ fontSize: 24, fontWeight: 800, color: 'var(--text0)', fontFamily: 'var(--mono)' }}>
        {view.viewState}
      </div>
      <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text2)', lineHeight: 1.45 }}>
        EMPTY_VALID is AVAILABLE with pagination.total 0, not UNAVAILABLE.
        Fetch failure and data_quality UNAVAILABLE/INVALID_SCHEMA are rendered as the page
        truth. Populated FROZEN_ENVELOPES are not kept as the live view.
        {view.error ? ` ${view.error}` : ''}
      </div>
    </Panel>
  )
}

export function Panel(props: { title: string; kicker?: string; children: ReactNode; testId?: string }) {
  return (
    <section style={panel} data-testid={props.testId}>
      {props.kicker ? <div style={eyebrow}>{props.kicker}</div> : null}
      <div style={{ ...titleStyle, fontSize: 14, marginTop: props.kicker ? 4 : 0 }}>{props.title}</div>
      <div style={{ marginTop: 10 }}>{props.children}</div>
    </section>
  )
}

export function NeutralChip({ children }: { children: ReactNode }) {
  return <span style={chipStyle}>{children}</span>
}

export function FieldTable(props: {
  columns: string[]
  rows: Array<Array<unknown>>
  empty: string
}) {
  if (props.rows.length === 0) {
    return <div style={{ fontSize: 12, color: 'var(--text3)' }}>{props.empty}</div>
  }
  return (
    <div style={tableWrap}>
      <table style={tableStyle}>
        <thead>
          <tr>
            {props.columns.map(col => (
              <th key={col} style={thStyle}>{col}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {props.rows.map((row, index) => (
            <tr key={index}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex} style={tdStyle}>{renderField(cell)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function PayloadDump({ payload }: { payload: unknown }) {
  return (
    <pre style={{
      margin: 0,
      padding: 10,
      background: 'var(--bg2)',
      border: '1px solid var(--border-subtle)',
      borderRadius: 4,
      color: 'var(--text2)',
      fontFamily: 'var(--mono)',
      fontSize: 10,
      lineHeight: 1.45,
      overflowX: 'auto',
      whiteSpace: 'pre-wrap',
    }}>
      {JSON.stringify(payload, null, 2)}
    </pre>
  )
}

export function PageFrame({ children }: { children: ReactNode }) {
  return <div style={pageWrap}>{children}</div>
}
