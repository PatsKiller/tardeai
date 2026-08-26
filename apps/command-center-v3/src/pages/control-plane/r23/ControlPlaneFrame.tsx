/**
 * Shared read-only chrome for R23 side-by-side control-plane pages.
 * Renders CONTROL_PLANE_API_V1_BASELINE envelope metadata as provided.
 * Does not infer quality, runtime, CIO, maturity, or LIVE.
 * live_claim=false — API existence is not a LIVE claim.
 */

import type { CSSProperties, ReactNode } from 'react'
import { displayItemField, displayPresent } from './display'
import type { ControlPlaneApiV1Envelope } from './fetchControlPlaneSummary'
import { isControlPlaneApiV1Collection } from './fetchControlPlaneSummary'
import { R23_CONTRACT, R23_LIVE_CLAIM, R23_VOCABULARY_CONTRACT } from './r23Routes'

const pageStyle: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 12,
  color: 'var(--text0)',
}

const titleStyle: CSSProperties = {
  fontSize: 16,
  fontWeight: 800,
  letterSpacing: '.02em',
  color: 'var(--text0)',
}

const subtitleStyle: CSSProperties = {
  fontSize: 10,
  color: 'var(--text3)',
  marginTop: 2,
  letterSpacing: '.04em',
}

const bannerStyle: CSSProperties = {
  background: 'var(--bg2)',
  border: '1px solid var(--border)',
  borderRadius: 2,
  padding: '8px 10px',
  fontSize: 10,
  color: 'var(--text2)',
  lineHeight: 1.5,
}

const metaGrid: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
  gap: 8,
}

const metaCell: CSSProperties = {
  background: 'var(--bg1)',
  border: '1px solid var(--border)',
  borderRadius: 2,
  padding: '6px 8px',
}

const metaLabel: CSSProperties = {
  fontSize: 10,
  color: 'var(--text3)',
  textTransform: 'uppercase',
  letterSpacing: '.06em',
  fontWeight: 700,
}

const metaValue: CSSProperties = {
  marginTop: 3,
  fontSize: 12,
  fontFamily: 'var(--mono)',
  color: 'var(--text0)',
  wordBreak: 'break-word',
}

const flagRow: CSSProperties = {
  display: 'flex',
  flexWrap: 'wrap',
  gap: 6,
}

const flag: CSSProperties = {
  fontSize: 10,
  fontWeight: 700,
  letterSpacing: '.04em',
  textTransform: 'uppercase',
  padding: '3px 8px',
  borderRadius: 2,
  border: '1px solid var(--border)',
  background: 'var(--bg2)',
  color: 'var(--text2)',
}

export const tableWrap: CSSProperties = {
  overflowX: 'auto',
  border: '1px solid var(--border)',
  borderRadius: 2,
}

export const tableStyle: CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  fontSize: 11,
}

export const thStyle: CSSProperties = {
  textAlign: 'left',
  fontSize: 10,
  fontWeight: 800,
  letterSpacing: '.04em',
  textTransform: 'uppercase',
  color: 'var(--text3)',
  background: 'var(--bg2)',
  borderBottom: '1px solid var(--border)',
  padding: '6px 8px',
  whiteSpace: 'nowrap',
}

export const tdStyle: CSSProperties = {
  padding: '6px 8px',
  borderBottom: '1px solid var(--border-subtle)',
  color: 'var(--text1)',
  verticalAlign: 'top',
}

export const tdMono: CSSProperties = {
  ...tdStyle,
  fontFamily: 'var(--mono)',
  fontSize: 11,
  color: 'var(--text0)',
}

export const sectionLabel: CSSProperties = {
  fontSize: 12,
  fontWeight: 800,
  color: 'var(--text0)',
  letterSpacing: '.03em',
  textTransform: 'uppercase',
}

export const panelStyle: CSSProperties = {
  background: 'var(--bg1)',
  border: '1px solid var(--border)',
  borderRadius: 2,
  padding: '8px 10px',
  fontSize: 12,
  color: 'var(--text1)',
  lineHeight: 1.45,
}

const VIEW_STATE_COPY: Record<string, string> = {
  UNAVAILABLE:
    'UNAVAILABLE — canonical store missing or GET unreachable. Empty items are NOT EMPTY_VALID. Do not treat this as a valid empty book. HTTP 200 is not a LIVE claim.',
  INVALID_SCHEMA:
    'INVALID_SCHEMA — canonical file present but not a CONTROL_PLANE_API_V1_BASELINE envelope / row list. Items are not trustworthy.',
  STALE:
    'STALE — projection reports stale data. Rendered as provided. Freshness is not recomputed in this UI. Not a LIVE claim.',
  DEGRADED:
    'DEGRADED — projection reports degraded data. Rendered as provided. Duplicates/orphans/freshness are not recomputed in this UI.',
  EMPTY_VALID:
    'EMPTY_VALID — AVAILABLE and pagination.total===0. Canonical store present and valid; collection is empty. Distinct from UNAVAILABLE.',
  AVAILABLE:
    'AVAILABLE — projection succeeded. API existence is not a LIVE claim. evidence_class and freshness rendered as provided.',
  LOADING:
    'LOADING — GET in flight. Not EMPTY_VALID. Not UNAVAILABLE. Not a LIVE claim.',
}

function bannerBorder(viewState: string): string {
  if (viewState === 'UNAVAILABLE' || viewState === 'INVALID_SCHEMA' || viewState === 'BROKEN') {
    return '1px solid var(--red)'
  }
  if (viewState === 'STALE' || viewState === 'DEGRADED') {
    return '1px solid var(--amber)'
  }
  if (viewState === 'EMPTY_VALID' || viewState === 'LOADING') {
    return '1px solid var(--text3)'
  }
  return '1px solid var(--border)'
}

interface Props {
  title: string
  intendedRoute: string
  getUrl: string
  canonicalFile: string
  envelope: ControlPlaneApiV1Envelope | null
  viewState: string
  error?: string | null
  children: ReactNode
}

export function ControlPlaneFrame({
  title,
  intendedRoute,
  getUrl,
  canonicalFile,
  envelope,
  viewState,
  error,
  children,
}: Props) {
  const flags = [
    'authority=READ_ONLY_ADVISORY',
    'memory_behavior_influence=0',
    'MBI=0',
    'computes_cio_decisions=false',
    'computes_agent_state=false',
    'computes_maturity=false',
    'computes_notification_eligibility=false',
    'financial_action=false',
    `live_claim=${String(R23_LIVE_CLAIM)}`,
  ]

  const data = envelope?.data
  const pagination = isControlPlaneApiV1Collection(data) ? data.pagination : null
  const bannerText = VIEW_STATE_COPY[viewState] ?? `${viewState} — rendered as provided. Not a LIVE claim.`

  return (
    <div
      style={pageStyle}
      data-contract={R23_CONTRACT}
      data-vocabulary={R23_VOCABULARY_CONTRACT}
      data-mode="side-by-side-unregistered"
      data-live-claim="false"
    >
      <div>
        <div style={titleStyle}>{title}</div>
        <div style={subtitleStyle}>
          Intended route {intendedRoute} · Not registered · GET {getUrl} · {R23_CONTRACT}
        </div>
      </div>

      <div style={bannerStyle} data-testid="side-by-side-preview-banner">
        SIDE-BY-SIDE UNREGISTERED — not a live Command Center route replacement. Integrator owns
        App.tsx / NavRail registration. Authority is READ_ONLY_ADVISORY. Pages GET R21 summary
        APIs and do not compute CIO decisions, runtime state, maturity, or notification
        eligibility. API existence is not a LIVE claim. live_claim=false.
      </div>

      <div
        style={{ ...bannerStyle, border: bannerBorder(viewState), fontWeight: 700 }}
        data-testid="data-quality-banner"
        data-view-state={viewState}
      >
        {bannerText}
        {error ? ` (${error})` : ''}
        <div style={{ marginTop: 4, fontWeight: 500, fontFamily: 'var(--mono)' }}>
          canonical_file={canonicalFile}
        </div>
      </div>

      <div style={metaGrid}>
        <Meta label="ok" value={envelope ? displayPresent(envelope.ok) : 'absent'} />
        <Meta label="as_of" value={envelope ? displayPresent(envelope.as_of) : 'absent'} />
        <Meta label="source_sha" value={envelope ? displayPresent(envelope.source_sha) : 'absent'} />
        <Meta label="freshness" value={envelope ? displayPresent(envelope.freshness) : 'absent'} />
        <Meta label="data_quality" value={envelope ? displayPresent(envelope.data_quality) : 'absent'} />
        <Meta label="evidence_class" value={envelope ? displayPresent(envelope.evidence_class) : 'absent'} />
        <Meta label="GET" value={getUrl} />
        <Meta
          label="pagination"
          value={
            pagination
              ? `limit=${pagination.limit} offset=${pagination.offset} total=${pagination.total}`
              : 'absent'
          }
        />
      </div>

      <div style={flagRow}>
        {flags.map((item) => (
          <span key={item} style={flag}>{item}</span>
        ))}
      </div>

      {children}
    </div>
  )
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div style={metaCell}>
      <div style={metaLabel}>{label}</div>
      <div style={metaValue}>{value}</div>
    </div>
  )
}

export function emptyCollectionMessage(viewState: string, colSpan: number) {
  let message = 'No items to render'
  if (viewState === 'EMPTY_VALID') message = 'EMPTY_VALID: pagination.total===0 — valid empty collection'
  else if (viewState === 'UNAVAILABLE') message = 'UNAVAILABLE: empty items are not EMPTY_VALID'
  else if (viewState === 'INVALID_SCHEMA') message = 'INVALID_SCHEMA: items not rendered as a valid collection'
  else if (viewState === 'LOADING') message = 'LOADING: GET in flight — not EMPTY_VALID'
  else if (viewState === 'STALE') message = 'STALE: no items in this page'
  else if (viewState === 'DEGRADED') message = 'DEGRADED: no items in this page'
  return (
    <tr>
      <td style={tdStyle} colSpan={colSpan}>{message}</td>
    </tr>
  )
}

export function extraKeysCell(item: Record<string, unknown>, known: readonly string[]) {
  const extra = Object.keys(item).filter((key) => !known.includes(key))
  if (extra.length === 0) return 'absent'
  return extra.map((key) => `${key}=${displayItemField(item, key)}`).join(' ')
}
