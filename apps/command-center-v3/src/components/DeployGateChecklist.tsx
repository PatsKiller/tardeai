// Four required CI checks + mergeability chips for one in-flight PR.
import type { CSSProperties } from 'react'
import { Chip, ChipRow } from './primitives'
import { TYPE, type Tone } from '../lib/designTokens'

const REQUIRED = ['cio-hardening', 'agent-governance', 'release-readiness', 'ci-gate'] as const

const checkTone = (v: string | undefined): Tone => {
  const u = String(v || 'MISSING').toUpperCase()
  if (u === 'SUCCESS') return 'success'
  if (u.includes('PENDING') || u.includes('IN_PROGRESS') || u.includes('QUEUED')) return 'info'
  if (u === 'MISSING') return 'warning'
  return 'danger'
}

const mergeTone = (m: string): Tone => {
  if (m === 'MERGEABLE') return 'success'
  if (m === 'CONFLICTING') return 'danger'
  return 'warning'
}

const wrap: CSSProperties = { display: 'grid', gap: 4 }
const note: CSSProperties = { margin: 0, fontSize: TYPE.xs, color: 'inherit', opacity: 0.85 }

export default function DeployGateChecklist({
  checks,
  mergeable,
}: {
  checks?: Record<string, string> | null
  mergeable: string
}) {
  const mergeTitle = mergeable === 'UNKNOWN'
    ? 'GitHub has not finished computing mergeability yet — wait / refresh; this is not the same as a conflict. (mergeable: UNKNOWN)'
    : mergeable === 'CONFLICTING'
      ? 'This change conflicts with main — needs a coordinator. (mergeable: CONFLICTING)'
      : 'GitHub says this can merge cleanly. (mergeable: MERGEABLE)'

  return (
    <div style={wrap} data-testid="deploy-gate-checklist">
      <ChipRow>
        {REQUIRED.map(name => {
          const v = checks?.[name] ?? 'MISSING'
          return (
            <Chip key={name} tone={checkTone(v)}
              title={`${name}: ${v} — required tool gate (same four as Telegram / Mergify)`}>
              {name.replace(/-/g, '·')} {v === 'SUCCESS' ? 'ok' : v.toLowerCase()}
            </Chip>
          )
        })}
      </ChipRow>
      <span title={mergeTitle}>
        <Chip tone={mergeTone(mergeable)}>
          {mergeable === 'UNKNOWN' ? 'merge check pending' : mergeable === 'CONFLICTING' ? 'conflict' : 'can merge'}
        </Chip>
      </span>
      {mergeable === 'UNKNOWN' ? (
        <p style={note}>Not a conflict — GitHub is still computing.</p>
      ) : null}
    </div>
  )
}
