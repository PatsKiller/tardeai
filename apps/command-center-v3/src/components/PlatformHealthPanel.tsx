/** Platform health (2026-10-21) — is the machinery up?
 *
 * Reads GET /api/v2/system/platform-health (PlatformHealth@v1) and renders one row per probe with a status pill.
 * `compact` is the Home card (overall pill, counts, the rows that are not OK, link to System → Platform); the full
 * panel on /v3/system?tab=Platform lists every row by group with its reason, source and as-of time.
 * UNKNOWN renders as UNKNOWN (never OK, never 0); a reading older than 2 min renders STALE (lib/platformHealth.ts).
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { Chip } from './primitives/Chip'
import { RADIUS, TOKENS, TYPE, numStyle } from '../lib/designTokens'
import { countsLabel, platformHealthFrom, toneFor, type PlatformRow } from '../lib/platformHealth'

const PATH = '/api/v2/system/platform-health'

function useNow(ms: number): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(id)
  }, [ms])
  return now
}

function asOfLabel(iso: string | null): string {
  if (!iso) return '—'
  const t = Date.parse(iso)
  return Number.isFinite(t) ? new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—'
}

function Row({ r, full }: { r: PlatformRow; full: boolean }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, padding: '4px 0', borderBottom: `1px solid ${TOKENS.borderSubtle}`, fontSize: TYPE.sm, flexWrap: 'wrap' }}>
      <span style={{ minWidth: 64 }}><Chip tone={toneFor(r.status)} title={r.reason ?? r.status}>{r.status}</Chip></span>
      <span style={{ color: TOKENS.text[1], fontWeight: 600, minWidth: 150 }}>{r.label}</span>
      <span style={{ ...numStyle, color: r.status === 'UNKNOWN' ? TOKENS.text[3] : TOKENS.text[0], flex: 1, minWidth: 120 }}>{r.value}</span>
      {full && <span style={{ color: TOKENS.text[3], fontSize: TYPE.xs }}>{asOfLabel(r.asOf)}</span>}
      {r.reason && (
        <div style={{ flexBasis: '100%', paddingLeft: 72, color: TOKENS.text[2], fontSize: TYPE.xs }}>{r.reason}</div>
      )}
      {full && r.source && (
        <div style={{ flexBasis: '100%', paddingLeft: 72, color: TOKENS.text[3], fontSize: TYPE.xs }}>source: {r.source}</div>
      )}
    </div>
  )
}

export default function PlatformHealthPanel({ compact = false }: { compact?: boolean }) {
  const { data, loading, error } = useApi<any>(PATH, compact ? 60_000 : 30_000)
  const now = useNow(15_000)
  const h = platformHealthFrom(data, { error, loading, nowMs: now })
  const notOk = h.rows.filter(r => r.status !== 'OK')
  const box = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: '12px 14px', marginBottom: 16 }

  const header = (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
      <span style={{ fontSize: TYPE.md, fontWeight: 700, color: TOKENS.text[0] }}>Platform</span>
      <Chip tone={toneFor(h.state)} size="md" title={h.reason ?? undefined}>{h.state}</Chip>
      {h.rows.length > 0 && <span style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>{countsLabel(h.counts)}</span>}
      <span style={{ flex: 1 }} />
      <span style={{ fontSize: TYPE.xs, color: TOKENS.text[3] }}>as of {asOfLabel(h.asOf)}</span>
      {compact && <Link to="/system?tab=Platform" style={{ fontSize: TYPE.xs, fontWeight: 700, color: TOKENS.info, textDecoration: 'none' }}>System → Platform</Link>}
    </div>
  )

  if (h.state === 'LOADING' || h.state === 'UNAVAILABLE') {
    return (
      <div style={box}>
        {header}
        <div style={{ fontSize: TYPE.sm, color: TOKENS.text[3] }}>
          {h.state === 'LOADING' ? 'Reading platform probes…' : `Platform health unavailable: ${h.reason ?? 'no answer'}. Nothing here is known to be OK.`}
        </div>
      </div>
    )
  }

  if (compact) {
    return (
      <div style={box}>
        {header}
        {notOk.length === 0
          ? <div style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>All {h.rows.length} probes OK: n8n, host services, disk/CPU/memory, backup, main Postgres.</div>
          : notOk.slice(0, 6).map(r => <Row key={r.id} r={r} full={false} />)}
        {notOk.length > 6 && <div style={{ fontSize: TYPE.xs, color: TOKENS.text[3], marginTop: 4 }}>+{notOk.length - 6} more on System → Platform</div>}
      </div>
    )
  }

  return (
    <div style={box}>
      {header}
      {h.reason && <div style={{ fontSize: TYPE.xs, color: TOKENS.warning, marginBottom: 8 }}>{h.reason}</div>}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(min(420px,100%),1fr))', gap: 14 }}>
        {h.groups.map(g => (
          <div key={g.group}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={{ fontSize: TYPE.base, fontWeight: 700, color: TOKENS.text[0] }}>{g.title}</span>
              <Chip tone={toneFor(g.worst)}>{g.worst}</Chip>
            </div>
            {g.rows.map(r => <Row key={r.id} r={r} full />)}
          </div>
        ))}
      </div>
      <div style={{ fontSize: TYPE.xs, color: TOKENS.text[3], marginTop: 10 }}>
        Source: {PATH} · read-only probes, each ≤2 s, cached 30 s · UNKNOWN = the probe could not look · STALE = reading older than 2 min
      </div>
    </div>
  )
}
