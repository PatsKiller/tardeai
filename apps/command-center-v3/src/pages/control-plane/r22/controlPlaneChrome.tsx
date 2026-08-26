/** Shared read-only chrome for R22 control-plane pages.
 * Displays envelope fields as provided. Does not compute CIO / notification / maturity. */

import type { CSSProperties, ReactNode } from 'react'
import {
  CONTROL_PLANE_CONTRACT_VERSION,
  type ControlPlaneEnvelope,
} from '../../../control-plane/contractV1'
import {
  CONTROL_PLANE_HTTP_FREEZE,
  DATA_QUALITY_VALUES,
  EMPTY_VALID_RULE,
  type CollectionData,
  type ControlPlaneHttpEnvelope,
} from './fetchControlPlane'
import { FIXTURE_MOCK_LABEL, FIXTURE_SOURCE } from './mocks/loadFixtures'

export const cpPanel: CSSProperties = {
  background: 'var(--bg1)',
  border: '1px solid var(--border)',
  borderRadius: 2,
  padding: '10px 12px',
}

export const cpLabel: CSSProperties = {
  fontSize: 10,
  fontWeight: 800,
  letterSpacing: '.06em',
  textTransform: 'uppercase',
  color: 'var(--text3)',
  fontFamily: 'var(--mono)',
}

export const cpMono: CSSProperties = {
  fontFamily: 'var(--mono)',
  fontSize: 11,
  color: 'var(--text1)',
  fontVariantNumeric: 'tabular-nums',
}

export const ABSENT = 'absent'

export function displayText(value: string | number | boolean | null | undefined): string {
  if (value == null || value === '') return '—'
  return String(value)
}

export function displayList(value: string[] | null | undefined): string {
  if (!value || value.length === 0) return '—'
  return value.join(', ')
}

export function formatUnknown(value: unknown): string {
  if (value === null) return 'null'
  if (value === undefined) return ABSENT
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  if (Array.isArray(value)) {
    return value.map(v => (v == null ? 'null' : typeof v === 'object' ? JSON.stringify(v) : String(v))).join(', ')
  }
  try {
    return JSON.stringify(value)
  } catch {
    return ABSENT
  }
}

/** Render listed keys if present on the item; else "absent". Do not map alternate keys. */
export function formatPresentField(item: Record<string, unknown>, keys: readonly string[]): string {
  const present = keys.filter(k => Object.prototype.hasOwnProperty.call(item, k))
  if (present.length === 0) return ABSENT
  return present.map(k => `${k}=${formatUnknown(item[k])}`).join(' · ')
}

const FLAG_OK = 'var(--green)'
const FLAG_BAD = 'var(--red)'

function flagColor(name: string, value: unknown): string {
  if (name === 'authority') return value === 'READ_ONLY_ADVISORY' ? FLAG_OK : FLAG_BAD
  if (name === 'memory_behavior_influence') return value === 0 ? FLAG_OK : FLAG_BAD
  if (name === 'financial_action') return value === false ? FLAG_OK : FLAG_BAD
  if (name.startsWith('computes_')) return value === false ? FLAG_OK : FLAG_BAD
  return 'var(--text2)'
}

export function Chip({
  children,
  tone = 'neutral',
  active = false,
  onClick,
}: {
  children: ReactNode
  tone?: 'neutral' | 'green' | 'red' | 'amber' | 'blue' | 'purple' | 'slate'
  active?: boolean
  onClick?: () => void
}) {
  const color =
    tone === 'green' ? 'var(--green)'
      : tone === 'red' ? 'var(--red)'
        : tone === 'amber' ? 'var(--amber)'
          : tone === 'blue' ? 'var(--blue)'
            : tone === 'purple' ? 'var(--purple)'
              : tone === 'slate' ? 'var(--text3)'
                : 'var(--text2)'
  const style: CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    padding: '3px 8px',
    borderRadius: 2,
    border: `1px solid ${active ? color : 'var(--border)'}`,
    background: active ? 'var(--bg2)' : 'var(--bg0)',
    color,
    fontSize: 10,
    fontWeight: 800,
    letterSpacing: '.04em',
    textTransform: 'uppercase',
    fontFamily: 'var(--mono)',
    cursor: onClick ? 'pointer' : 'default',
    margin: 0,
  }
  if (onClick) {
    return <button type="button" onClick={onClick} style={style}>{children}</button>
  }
  return <span style={style}>{children}</span>
}

export function Field({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div>
      <div style={cpLabel}>{k}</div>
      <div style={{ ...cpMono, marginTop: 3, color: 'var(--text1)', lineHeight: 1.45, wordBreak: 'break-word' }}>{v}</div>
    </div>
  )
}

export function ControlPlaneEnvelopeBanner({
  title,
  routeHint,
  envelope,
}: {
  title: string
  routeHint: string
  envelope: ControlPlaneEnvelope<unknown>
}) {
  const flags: Array<[string, unknown]> = [
    ['authority', envelope.authority],
    ['memory_behavior_influence', envelope.memory_behavior_influence],
    ['computes_cio_decisions', envelope.computes_cio_decisions],
    ['computes_agent_state', envelope.computes_agent_state],
    ['computes_maturity', envelope.computes_maturity],
    ['computes_notification_eligibility', envelope.computes_notification_eligibility],
    ['financial_action', envelope.financial_action],
  ]
  return (
    <div style={{ display: 'grid', gap: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 800, letterSpacing: '.04em', color: 'var(--text0)' }}>{title}</div>
          <div style={{ ...cpLabel, marginTop: 4, textTransform: 'none', letterSpacing: '.02em', fontWeight: 600 }}>
            {CONTROL_PLANE_CONTRACT_VERSION} · {routeHint} · {FIXTURE_MOCK_LABEL}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <Chip tone="amber">FIXTURE</Chip>
          <Chip tone="amber">MOCK</Chip>
          <Chip tone="slate">{envelope.evidence_class}</Chip>
          <Chip tone="slate">{envelope.data_quality}</Chip>
        </div>
      </div>
      <div style={{ ...cpPanel, display: 'grid', gap: 8 }}>
        <div style={cpLabel}>Envelope · {FIXTURE_SOURCE}</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, ...cpMono }}>
          <span>schema={envelope.schema}</span>
          <span>page={envelope.page}</span>
          <span>as_of={envelope.as_of}</span>
          <span>source_sha={envelope.source_sha}</span>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {flags.map(([name, value]) => (
            <span key={name} style={{ ...cpMono, color: flagColor(name, value) }}>
              {name}={String(value)}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}

function qualityTone(quality: string): 'green' | 'red' | 'amber' | 'slate' {
  if (quality === 'AVAILABLE') return 'green'
  if (quality === 'UNAVAILABLE' || quality === 'INVALID_SCHEMA' || quality === 'BROKEN') return 'red'
  if (quality === 'STALE' || quality === 'DEGRADED' || quality === 'EMPTY_VALID') return 'amber'
  return 'slate'
}

export function DataQualityLegend({ current }: { current: string }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }} data-testid="data-quality-legend">
      {DATA_QUALITY_VALUES.map(quality => (
        <Chip key={quality} tone={qualityTone(quality)} active={current === quality}>
          <span data-data-quality={quality}>{quality}</span>
        </Chip>
      ))}
    </div>
  )
}

export function CollectionNotice({
  displayQuality,
  envelopeQuality,
}: {
  displayQuality: string
  envelopeQuality: string
}) {
  if (displayQuality === 'UNAVAILABLE' || envelopeQuality === 'UNAVAILABLE') {
    return (
      <div style={{ ...cpMono, color: 'var(--red)', lineHeight: 1.5 }}>
        UNAVAILABLE — not EMPTY_VALID. Canonical store missing or fetch failed. ok=true with UNAVAILABLE is real; ok is not a LIVE claim.
      </div>
    )
  }
  if (displayQuality === 'INVALID_SCHEMA' || envelopeQuality === 'INVALID_SCHEMA') {
    return (
      <div style={{ ...cpMono, color: 'var(--red)', lineHeight: 1.5 }}>
        INVALID_SCHEMA — response is not a valid {CONTROL_PLANE_HTTP_FREEZE} envelope. Not a populated fixture.
      </div>
    )
  }
  if (displayQuality === 'EMPTY_VALID') {
    return (
      <div style={{ ...cpMono, color: 'var(--amber)', lineHeight: 1.5 }}>
        EMPTY_VALID — {EMPTY_VALID_RULE}. Valid empty collection, not UNAVAILABLE.
      </div>
    )
  }
  if (displayQuality === 'STALE' || envelopeQuality === 'STALE') {
    return (
      <div style={{ ...cpMono, color: 'var(--amber)', lineHeight: 1.5 }}>
        STALE — envelope data_quality as provided. Not inferred.
      </div>
    )
  }
  if (displayQuality === 'DEGRADED' || envelopeQuality === 'DEGRADED') {
    return (
      <div style={{ ...cpMono, color: 'var(--amber)', lineHeight: 1.5 }}>
        DEGRADED — envelope data_quality as provided. Not inferred.
      </div>
    )
  }
  return null
}

export function ApiEnvelopeBanner({
  title,
  routeHint,
  summaryUrl,
  envelope,
  collection,
  displayQuality,
}: {
  title: string
  routeHint: string
  summaryUrl: string
  envelope: ControlPlaneHttpEnvelope
  collection: CollectionData | null
  displayQuality: string
}) {
  const pag = collection?.pagination
  return (
    <div style={{ display: 'grid', gap: 10 }} data-testid="api-envelope">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 800, letterSpacing: '.04em', color: 'var(--text0)' }}>{title}</div>
          <div style={{ ...cpLabel, marginTop: 4, textTransform: 'none', letterSpacing: '.02em', fontWeight: 600 }}>
            {CONTROL_PLANE_HTTP_FREEZE} · GET {summaryUrl} · {routeHint} · API existence is not a LIVE claim
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <Chip tone="slate">ok={String(envelope.ok)}</Chip>
          <Chip tone={qualityTone(envelope.data_quality)}>{envelope.data_quality}</Chip>
          {displayQuality !== envelope.data_quality && (
            <Chip tone={qualityTone(displayQuality)}>{displayQuality}</Chip>
          )}
          <Chip tone="slate">{envelope.evidence_class}</Chip>
        </div>
      </div>
      <div style={{ ...cpPanel, display: 'grid', gap: 8 }}>
        <div style={cpLabel}>HTTP envelope · ok is not a LIVE claim · {EMPTY_VALID_RULE}</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, ...cpMono }}>
          <span>ok={String(envelope.ok)}</span>
          <span>as_of={formatUnknown(envelope.as_of)}</span>
          <span>source_sha={formatUnknown(envelope.source_sha)}</span>
          <span>freshness={formatUnknown(envelope.freshness)}</span>
          <span>data_quality={envelope.data_quality}</span>
          <span>display_quality={displayQuality}</span>
          <span>evidence_class={envelope.evidence_class}</span>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, ...cpMono }}>
          {pag ? (
            <>
              <span>items={collection?.items.length ?? 0}</span>
              <span>pagination.limit={pag.limit}</span>
              <span>pagination.offset={pag.offset}</span>
              <span>pagination.total={pag.total}</span>
            </>
          ) : (
            <span>data is not a collection with items + pagination</span>
          )}
        </div>
        <CollectionNotice displayQuality={displayQuality} envelopeQuality={envelope.data_quality} />
        <div style={cpLabel}>data_quality values (explicit, including zero-count)</div>
        <DataQualityLegend current={displayQuality} />
      </div>
    </div>
  )
}
