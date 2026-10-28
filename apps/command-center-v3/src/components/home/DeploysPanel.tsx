// Deploys (2026-10-27) — Mergify merges; the host deploy_on_main poller promotes (AGENTS.md §25.10).
// Replaces the retired release-train card / Run now UI (operator directive 2026-10-27). Shows the latest
// DeployOnMainReceipt@v1, the last few receipts and the deploy STOP control (set-only; resume is Ops → Controls).
import { Link } from 'react-router-dom'
import { useApi } from '../../hooks/useApi'
import { Chip, ChipRow } from '../primitives'
import { RADIUS, TOKENS, TYPE } from '../../lib/designTokens'
import { DEPLOYS_PATHS, deploysSummary, freshness, outcomeTone, shortSha, type DeploysStatusWire } from '../../lib/deploys'
import { readableTime } from '../../lib/readableTime'
import DeployStopControl from '../DeployStopControl'

const panel = {
  background: TOKENS.bg[1],
  border: `1px solid ${TOKENS.border}`,
  borderRadius: RADIUS.md,
  padding: 14,
  display: 'grid' as const,
  gap: 10,
  minWidth: 0,
}

const link = { fontSize: TYPE.sm, fontWeight: 700, color: TOKENS.primary, minHeight: 44, display: 'inline-flex', alignItems: 'center' } as const

export default function DeploysPanel() {
  const api = useApi<DeploysStatusWire>(DEPLOYS_PATHS.status, 60_000)
  const f = freshness(api.data?.generated_at, !!api.data, { nowMs: Date.now(), loading: api.loading, error: api.error })
  const s = deploysSummary(api.data, f)
  const recent = (api.data?.recent ?? []).slice(0, 5)
  return (
    <section data-testid="deploys-panel" aria-label="Deploys" style={panel}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', alignItems: 'baseline' }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: TYPE.md, fontWeight: 800, color: TOKENS.text[0] }}>Deploys</div>
          <p style={{ margin: '4px 0 0', fontSize: TYPE.sm, color: TOKENS.text[2] }}>
            Mergify merges approved PRs to main. The host poller promotes each new main commit while the deploy STOP is clear.
          </p>
        </div>
        <ChipRow>
          <Chip tone={f.state === 'OK' ? 'neutral' : 'warning'} title={f.reason || ''}>{f.state}</Chip>
          <Chip tone={s.stopTone}>{s.stopText}</Chip>
        </ChipRow>
      </div>
      <div data-testid="deploys-last" style={{ fontSize: TYPE.sm, color: TOKENS.text[1] }}>
        Last: <Chip tone={s.lastTone}>{s.lastText}</Chip>{s.lastAt ? ` · ${readableTime(s.lastAt)}` : ''}
      </div>
      {recent.length > 0 && (
        <ul data-testid="deploys-recent" style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 4 }}>
          {recent.map((r, i) => (
            <li key={`${r.as_of}-${i}`} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'baseline', fontSize: TYPE.sm, color: TOKENS.text[2] }}>
              <Chip tone={outcomeTone(r.outcome)}>{r.outcome || 'unknown'}</Chip>
              <span>main {shortSha(r.main_sha)}{r.path === 'manual_emergency' ? ' · emergency' : ''}</span>
              <span>{r.as_of ? readableTime(r.as_of) : '—'}</span>
            </li>
          ))}
        </ul>
      )}
      <DeployStopControl compact />
      <ChipRow>
        <Link to="/system/ops-controls?tab=jobs" data-testid="deploys-ops-link" style={link}>Ops → Controls · Deploys &amp; kill switch →</Link>
        <Link to="/system/releases" data-testid="deploys-releases-link" style={link}>Releases &amp; schedules →</Link>
        <a href="https://dashboard.mergify.com" target="_blank" rel="noreferrer" data-testid="deploys-mergify-link" style={link}>Mergify dashboard ↗</a>
      </ChipRow>
    </section>
  )
}
