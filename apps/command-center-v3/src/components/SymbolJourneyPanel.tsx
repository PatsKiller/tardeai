import { useEffect, useMemo, useState, type ReactNode } from 'react'

const TEXT0 = '#f8fafc'
const TEXT1 = '#dbeafe'
const TEXT2 = '#cbd5e1'
const MUTED = '#94a3b8'
const DIM = '#64748b'
const GREEN = '#22c55e'
const RED = '#ef4444'
const AMBER = '#f59e0b'
const BLUE = '#60a5fa'
const PURPLE = '#a855f7'
const TEAL = '#2dd4bf'

const panel = { background: 'rgba(15,23,42,.72)', border: '1px solid rgba(148,163,184,.20)', borderRadius: 12, padding: 14 } as const
const metric = { background: 'rgba(2,6,23,.40)', border: '1px solid rgba(148,163,184,.18)', borderRadius: 10, padding: '10px 12px' } as const

const GATE_COLOR: Record<string, string> = {
  promote_eligible: GREEN,
  demote_pressure: RED,
  pause_eligible: RED,
  promote_blocked_bad_tag: AMBER,
  neutral: MUTED,
}

const WATCH_STAGE_COLOR: Record<string, string> = {
  new: BLUE,
  monitoring: MUTED,
  watch: AMBER,
  promoted: GREEN,
  demoted: AMBER,
  archived: DIM,
  blacklisted: RED,
}

const HOLDING_STAGE_COLOR: Record<string, string> = {
  healthy: GREEN,
  watch: AMBER,
  trim_candidate: RED,
  exited: DIM,
}

const KIND_META: Record<string, { label: string; color: string }> = {
  governor_tier: { label: 'Tier change', color: BLUE },
  watchlist_gate_blocked: { label: 'Promotion blocked', color: AMBER },
  watchlist_override: { label: 'Lifecycle override', color: PURPLE },
  outcome_graded: { label: 'Outcome graded', color: TEAL },
  paper_trade: { label: 'Paper trade', color: GREEN },
}

const HEALTH_COMPONENT_LABELS: Record<string, string> = {
  outcome_performance: 'Outcome perf',
  promotion_success_rate: 'Promo success',
  tag_lift_consistency: 'Tag lift',
  stop_quality: 'Stop quality',
  regime_alignment: 'Regime',
  research_actionability: 'Research',
}

type JourneyData = {
  ok?: boolean
  symbol?: string
  generated_at?: string
  summary?: Record<string, any>
  timeline?: { at?: string; kind?: string; source?: string; summary?: string; detail?: string }[]
  watchlist_lifecycle?: Record<string, any>
  holdings_lifecycle?: Record<string, any>
  governor_feedback?: Record<string, any>
  outcome_bus?: Record<string, any>
  trace_links?: Record<string, string>
  reason?: string
}

function fmtTs(v?: string | null): string {
  if (!v) return '—'
  const d = new Date(v)
  if (isNaN(d.getTime())) return String(v).slice(0, 16)
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function healthColor(score?: number | null): string {
  const n = Number(score)
  if (!Number.isFinite(n)) return MUTED
  if (n >= 70) return GREEN
  if (n < 50) return RED
  return AMBER
}

function Metric({ label, value, color = TEXT0 }: { label: string; value: ReactNode; color?: string }) {
  return (
    <div style={metric}>
      <div style={{ fontSize: 9, color: MUTED, textTransform: 'uppercase', letterSpacing: '.06em', fontWeight: 850 }}>{label}</div>
      <div style={{ fontSize: 14, fontWeight: 950, color, marginTop: 4, lineHeight: 1.15 }}>{value ?? '—'}</div>
    </div>
  )
}

function Section({ title, subtitle, children, accent = BLUE }: { title: string; subtitle?: string; children: React.ReactNode; accent?: string }) {
  return (
    <div style={{ ...panel, borderLeft: `4px solid ${accent}` }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 9, flexWrap: 'wrap', gap: 6 }}>
        <div style={{ fontSize: 12, fontWeight: 950, color: TEXT0, textTransform: 'uppercase', letterSpacing: '.04em' }}>{title}</div>
        {subtitle && <div style={{ fontSize: 10, color: MUTED }}>{subtitle}</div>}
      </div>
      {children}
    </div>
  )
}

function HealthComponents({ components }: { components?: Record<string, number> }) {
  const entries = Object.entries(components ?? {}).filter(([, v]) => v != null && Number.isFinite(Number(v)))
  if (entries.length === 0) return null
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 8, marginTop: 8 }}>
      {entries.map(([k, v]) => {
        const n = Number(v)
        const c = healthColor(n)
        return (
          <div key={k} style={{ ...metric, padding: '8px 10px' }}>
            <div style={{ fontSize: 8, color: MUTED, textTransform: 'uppercase' }}>{HEALTH_COMPONENT_LABELS[k] ?? k.replace(/_/g, ' ')}</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
              <div style={{ flex: 1, height: 4, background: 'rgba(148,163,184,.15)', borderRadius: 2, overflow: 'hidden' }}>
                <div style={{ width: `${Math.min(100, Math.max(0, n))}%`, height: '100%', background: c, borderRadius: 2 }} />
              </div>
              <span style={{ fontSize: 11, fontWeight: 850, color: c, minWidth: 28, textAlign: 'right' }}>{Math.round(n)}</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function Timeline({ events }: { events: JourneyData['timeline'] }) {
  const rows = events ?? []
  if (rows.length === 0) {
    return <div style={{ fontSize: 11, color: MUTED, padding: '8px 0' }}>No timeline events yet — governor tick or outcome grading will populate this trail.</div>
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
      {rows.map((ev, i) => {
        const meta = KIND_META[ev.kind ?? ''] ?? { label: ev.kind ?? 'Event', color: MUTED }
        const isLast = i === rows.length - 1
        return (
          <div key={`${ev.at}-${ev.kind}-${i}`} style={{ display: 'flex', gap: 14, minHeight: 56 }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 14, flexShrink: 0 }}>
              <div style={{ width: 10, height: 10, borderRadius: '50%', background: meta.color, border: `2px solid ${meta.color}55`, flexShrink: 0, marginTop: 4 }} />
              {!isLast && <div style={{ flex: 1, width: 2, background: 'rgba(148,163,184,.18)', marginTop: 4 }} />}
            </div>
            <div style={{ flex: 1, paddingBottom: isLast ? 0 : 14, borderBottom: isLast ? 'none' : '1px solid rgba(148,163,184,.10)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap' }}>
                <div>
                  <span style={{ fontSize: 10, fontWeight: 850, color: meta.color, textTransform: 'uppercase', letterSpacing: '.04em' }}>{meta.label}</span>
                  <div style={{ fontSize: 12, fontWeight: 750, color: TEXT0, marginTop: 3, lineHeight: 1.35 }}>{ev.summary ?? '—'}</div>
                </div>
                <span style={{ fontSize: 9, color: DIM, fontFamily: 'monospace', whiteSpace: 'nowrap' }}>{fmtTs(ev.at)}</span>
              </div>
              {ev.detail && (
                <div style={{ fontSize: 10, color: TEXT2, marginTop: 4, lineHeight: 1.45, wordBreak: 'break-word' }}>{ev.detail}</div>
              )}
              {ev.source && (
                <div style={{ fontSize: 8, color: DIM, marginTop: 3, fontFamily: 'monospace' }}>{ev.source}</div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default function SymbolJourneyPanel({ endpoint }: { endpoint: string }) {
  const [data, setData] = useState<JourneyData | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setErr(null)
    setData(null)
    fetch(endpoint)
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(j => {
        if (cancelled) return
        if (!j?.ok) {
          setErr(j?.reason ?? 'Journey unavailable')
          setData(j)
        } else {
          setData(j)
        }
      })
      .catch(e => { if (!cancelled) setErr(String(e?.message ?? e)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [endpoint])

  const summary = data?.summary ?? {}
  const wl = data?.watchlist_lifecycle ?? {}
  const hl = data?.holdings_lifecycle ?? {}
  const fb = data?.governor_feedback

  const traceLinks = useMemo(() => {
    const links = data?.trace_links ?? {}
    return Object.entries(links).map(([k, href]) => ({
      key: k,
      href,
      label: k.replace(/_/g, ' '),
    }))
  }, [data])

  if (loading) {
    return <Section title="Closed-loop journey" subtitle="Loading trace…" accent={BLUE}>
      <div style={{ fontSize: 11, color: MUTED }}>Merging governor audit, lifecycle, outcomes, and trades…</div>
    </Section>
  }

  if (err && !data?.ok) {
    return <Section title="Closed-loop journey" accent={RED}>
      <div style={{ fontSize: 11, color: RED }}>{err}</div>
    </Section>
  }

  return (
    <>
      <Section title="Current state" subtitle={data?.generated_at ? `as of ${fmtTs(data.generated_at)}` : undefined} accent={GREEN}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 10 }}>
          <Metric label="Scope tier" value={summary.scope_tier ?? wl.scope_tier ?? '—'} />
          <Metric
            label="Watchlist stage"
            value={summary.watchlist_stage ?? wl.lifecycle_stage ?? '—'}
            color={WATCH_STAGE_COLOR[String(summary.watchlist_stage ?? wl.lifecycle_stage ?? '')] ?? TEXT1}
          />
          <Metric
            label="Holdings stage"
            value={summary.holdings_stage ?? hl.lifecycle_stage ?? '—'}
            color={HOLDING_STAGE_COLOR[String(summary.holdings_stage ?? hl.lifecycle_stage ?? '')] ?? TEXT1}
          />
          <Metric
            label="Watchlist health"
            value={summary.watchlist_health != null ? Math.round(Number(summary.watchlist_health)) : '—'}
            color={healthColor(summary.watchlist_health ?? wl.health_score)}
          />
          <Metric
            label="Holdings health"
            value={summary.holdings_health != null ? Math.round(Number(summary.holdings_health)) : '—'}
            color={healthColor(summary.holdings_health ?? hl.health_score)}
          />
          <Metric
            label="Outcome gate"
            value={summary.outcome_gate ?? data?.outcome_bus?.gate ?? '—'}
            color={GATE_COLOR[String(summary.outcome_gate ?? data?.outcome_bus?.gate ?? '')] ?? TEXT1}
          />
          <Metric label="Bus lift" value={summary.bus_lift ?? data?.outcome_bus?.lift ?? '—'} color={(summary.bus_lift ?? 0) < 0 ? RED : TEXT0} />
          <Metric label="Graded n" value={summary.bus_n ?? data?.outcome_bus?.n ?? '—'} />
          <Metric label="Research 30d" value={summary.research_rows_30d ?? '—'} />
        </div>
        {(wl.health_components || hl.health_components) && (
          <div style={{ marginTop: 12 }}>
            {wl.health_components && (
              <>
                <div style={{ fontSize: 9, color: MUTED, textTransform: 'uppercase', fontWeight: 850, marginBottom: 4 }}>Watchlist health components</div>
                <HealthComponents components={wl.health_components} />
              </>
            )}
            {hl.health_components && (
              <>
                <div style={{ fontSize: 9, color: MUTED, textTransform: 'uppercase', fontWeight: 850, marginTop: wl.health_components ? 12 : 0, marginBottom: 4 }}>Holdings health components</div>
                <HealthComponents components={hl.health_components} />
              </>
            )}
          </div>
        )}
      </Section>

      {fb && (
        <Section title="Governor feedback" subtitle="Outcome bus reaction for this symbol" accent={AMBER}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 10 }}>
            <Metric label="Action" value={fb.action ?? '—'} color={fb.action ? AMBER : TEXT0} />
            <Metric label="Gate" value={fb.gate ?? '—'} color={GATE_COLOR[String(fb.gate ?? '')] ?? TEXT1} />
            {fb.lift != null && <Metric label="Lift" value={fb.lift} color={Number(fb.lift) < 0 ? RED : TEXT0} />}
            {fb.n != null && <Metric label="Sample n" value={fb.n} />}
          </div>
          {fb.reason && <div style={{ fontSize: 10, color: TEXT2, marginTop: 8, lineHeight: 1.45 }}>{String(fb.reason).slice(0, 280)}</div>}
        </Section>
      )}

      <Section
        title="Journey timeline"
        subtitle={`${summary.timeline_events ?? data?.timeline?.length ?? 0} events · watchlist → governor → outcome → trade`}
        accent={BLUE}
      >
        <Timeline events={data?.timeline} />
      </Section>

      {traceLinks.length > 0 && (
        <Section title="Trace links" accent={TEAL}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {traceLinks.map(l => (
              <a
                key={l.key}
                href={l.href}
                target="_blank"
                rel="noreferrer"
                style={{
                  fontSize: 11, fontWeight: 850, color: '#bfdbfe', textDecoration: 'none',
                  padding: '5px 10px', borderRadius: 6, background: 'rgba(96,165,250,.13)', border: '1px solid rgba(96,165,250,.32)',
                }}
              >
                {l.label} →
              </a>
            ))}
          </div>
        </Section>
      )}
    </>
  )
}