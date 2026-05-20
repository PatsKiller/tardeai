import { useState, useEffect } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'

interface Stage {
  id: string
  label: string
  status_color: 'green' | 'amber' | 'red' | 'gray' | 'blue'
  last_run_at: string | null
  last_status: 'success' | 'failed' | 'running' | null
  rows_processed: number
  duration_sec: number
  error_message: string | null
  cadence_h: number
  minutes_ago: number
}

interface Group {
  id: string
  label: string
  description: string
  stages: Stage[]
}

interface Summary {
  healthy: number
  warnings: number
  critical: number
  total_stages: number
  last_full_cycle: string
}

interface PipelineData {
  ok: boolean
  summary: Summary
  groups: Group[]
}

const STATUS_COLORS: Record<string, { border: string; bg: string }> = {
  green:  { border: '#10B981', bg: 'rgba(16,185,129,0.15)' },
  amber:  { border: '#F59E0B', bg: 'rgba(245,158,11,0.15)' },
  red:    { border: '#EF4444', bg: 'rgba(239,68,68,0.15)' },
  gray:   { border: '#6B7280', bg: 'rgba(107,114,128,0.15)' },
  blue:   { border: '#3B82F6', bg: 'rgba(59,130,246,0.15)' },
}

function formatAgo(minutes: number | null | undefined): string {
  if (minutes == null) return 'never'
  if (minutes < 60) return `${Math.round(minutes)}m ago`
  if (minutes < 1440) return `${Math.round(minutes / 60)}h ago`
  return `${Math.round(minutes / 1440)}d ago`
}

function formatTimestamp(iso: string | null): string {
  if (!iso) return 'never'
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

function formatDuration(sec: number | null | undefined): string {
  if (sec == null) return '-'
  if (sec < 60) return `${sec.toFixed(1)}s`
  return `${(sec / 60).toFixed(1)}m`
}

export default function PipelineHealthMaster() {
  const [data, setData] = useState<PipelineData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

  const fetchData = async () => {
    try {
      const res = await fetch('/api/v2/pipeline-health-master')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setData(json)
      setError(null)
      setLastRefresh(new Date())
    } catch (e: any) {
      setError(e.message || 'Failed to fetch pipeline health')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 60_000)
    return () => clearInterval(interval)
  }, [])

  if (loading && !data) {
    return (
      <>
        <PageHeader title="Pipeline Health Master" subtitle="31-stage pipeline overview" />
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--text3)', fontSize: 11 }}>
          Loading pipeline health...
        </div>
      </>
    )
  }

  if (error && !data) {
    return (
      <>
        <PageHeader title="Pipeline Health Master" subtitle="31-stage pipeline overview" />
        <div style={{ padding: '12px 16px', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8, color: '#EF4444', fontSize: 11 }}>
          Error loading pipeline health: {error}
        </div>
      </>
    )
  }

  const summary = data?.summary
  const groups = data?.groups || []

  return (
    <>
      <PageHeader
        title="Pipeline Health Master"
        subtitle="31-stage pipeline overview"
        actions={
          <button onClick={fetchData} style={btnStyle}>Refresh</button>
        }
      />

      {/* Status Legend */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 10, padding: '6px 10px', background: 'rgba(16,20,28,0.6)', borderRadius: 8, fontSize: 9, fontFamily: 'monospace' }}>
        {[
          { icon: '\u2705', label: 'Healthy', color: '#10B981', desc: 'Ran successfully' },
          { icon: '\ud83d\udd52', label: 'Waiting', color: '#3B82F6', desc: 'Before scheduled window' },
          { icon: '\u26a0\ufe0f', label: 'Needs Attention', color: '#F59E0B', desc: 'Window passed, no run/data' },
          { icon: '\ud83d\udfe0', label: 'Blocked', color: '#F97316', desc: 'Dependency or gate blocked' },
          { icon: '\u26d4', label: 'Failed', color: '#EF4444', desc: 'Ran and failed' },
          { icon: '\u25fb', label: 'Manual/On-Demand', color: '#6B7280', desc: 'Weekly or manual only' },
          { icon: '\ud83e\uddea', label: 'Dry-Run', color: '#A855F7', desc: 'Test only, not production' },
        ].map(s => (
          <span key={s.label} style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
            <span>{s.icon}</span>
            <span style={{ color: s.color, fontWeight: 600 }}>{s.label}</span>
            <span style={{ color: 'var(--text3)' }}>— {s.desc}</span>
          </span>
        ))}
      </div>

      {/* KPI Tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 8, marginBottom: 12 }}>
        {[
          { label: 'Completed', value: summary?.healthy ?? 0, color: '#10B981', hint: 'Stages with successful telemetry' },
          { label: 'Warnings', value: summary?.warnings ?? 0, color: '#F59E0B', hint: 'Window passed or no telemetry' },
          { label: 'Critical', value: summary?.critical ?? 0, color: '#EF4444', hint: 'Failed stages' },
          { label: 'Never Run', value: (summary as any)?.never_run ?? 0, color: '#6B7280', hint: 'No production telemetry exists' },
          { label: 'Waiting', value: Math.max(0, (summary?.total_stages ?? 31) - (summary?.healthy ?? 0) - (summary?.warnings ?? 0) - (summary?.critical ?? 0) - ((summary as any)?.never_run ?? 0)), color: '#3B82F6', hint: 'Before scheduled window' },
          { label: 'Last Cycle', value: summary?.last_full_cycle ?? '-', color: 'var(--text2)', hint: 'Most recent pipeline run' },
        ].map(kpi => (
          <div key={kpi.label} style={{ background: 'rgba(16,20,28,0.9)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 8, padding: '8px 10px', textAlign: 'center' }} title={kpi.hint}>
            <div style={{ fontSize: typeof kpi.value === 'number' ? 18 : 11, fontWeight: 700, color: kpi.color }}>{kpi.value}</div>
            <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>{kpi.label}</div>
          </div>
        ))}
      </div>

      {/* Explanation */}
      <div style={{ fontSize: 9, color: 'var(--text3)', padding: '4px 10px', marginBottom: 10, fontStyle: 'italic', lineHeight: 1.5 }}>
        Pipeline Health separates stage registry from run telemetry. A stage can be registered but never run. Yellow means the expected window passed without telemetry. Gray means manual/on-demand. No stage is marked healthy unless telemetry proves it ran.
      </div>

      {/* Summary bar */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '8px 14px',
        marginBottom: 14,
        background: 'rgba(16,20,28,0.92)',
        border: '1px solid rgba(255,255,255,0.07)',
        borderRadius: 10,
        fontSize: 11,
        fontFamily: 'monospace',
      }}>
        <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
          <span style={{ color: 'var(--text1)', fontWeight: 700 }}>
            Pipeline Health: {(() => {
              const h = summary?.healthy ?? 0
              const w = summary?.warnings ?? 0
              const c = summary?.critical ?? 0
              const total = summary?.total_stages ?? 31
              const nr = (summary as any)?.never_run ?? 0
              if (h === 0 && w === 0 && c === 0 && nr === 0) return <span style={{ color: '#F59E0B' }}>0/{total} stages completed — waiting for schedule</span>
              if (h === 0 && w > 0) return <span style={{ color: '#F59E0B' }}>{h}/{total} completed · {w} warnings · {nr > 0 ? `${nr} never run` : ''}</span>
              return <span style={{ color: c > 0 ? '#EF4444' : w > 0 ? '#F59E0B' : '#10B981' }}>{h}/{total} stages healthy</span>
            })()}
          </span>
          <span style={{ color: '#F59E0B' }}>
            {summary?.warnings ?? 0} warnings
          </span>
          <span style={{ color: '#EF4444' }}>
            {summary?.critical ?? 0} critical
          </span>
          <span style={{ color: 'var(--text3)' }}>
            Last full cycle: {summary?.last_full_cycle ?? '-'}
          </span>
        </div>
        <div style={{ fontSize: 9, color: 'var(--text3)' }}>
          {lastRefresh ? `Refreshed ${lastRefresh.toLocaleTimeString()}` : ''}
          {error && <span style={{ color: '#EF4444', marginLeft: 8 }}>fetch error</span>}
        </div>
      </div>

      {/* Groups */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {groups.map((group) => (
          <Card key={group.id} title={group.label} subtitle={group.description}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 0, overflowX: 'auto', paddingBottom: 4 }}>
              {group.stages.map((stage, i) => {
                const colors = STATUS_COLORS[stage.status_color] || STATUS_COLORS.gray
                const isExpanded = expanded === stage.id

                return (
                  <div key={stage.id} style={{ display: 'flex', alignItems: 'flex-start' }}>
                    {/* Arrow connector */}
                    {i > 0 && (
                      <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        paddingTop: 12,
                        color: 'var(--text3)',
                        fontSize: 9,
                        fontFamily: 'monospace',
                        userSelect: 'none',
                        flexShrink: 0,
                      }}>
                        -&gt;
                      </div>
                    )}

                    {/* Stage node */}
                    <div style={{ flexShrink: 0 }}>
                      <div
                        onClick={() => setExpanded(isExpanded ? null : stage.id)}
                        style={{
                          borderLeft: `2px solid ${colors.border}`,
                          background: colors.bg,
                          padding: '6px 8px',
                          borderRadius: 4,
                          cursor: 'pointer',
                          minWidth: 80,
                          maxWidth: 110,
                          transition: 'background 120ms ease',
                        }}
                      >
                        <div style={{
                          fontSize: 10,
                          fontWeight: 700,
                          color: 'var(--text1)',
                          lineHeight: 1.2,
                          marginBottom: 2,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}>
                          {stage.label}
                        </div>
                        <div style={{ fontSize: 9, color: 'var(--text3)', fontFamily: 'monospace' }}>
                          {(() => {
                            const c = stage.status_color
                            if (c === 'green') return '\u2705 Healthy'
                            if (c === 'blue') return '\ud83d\udd52 Running'
                            if (c === 'amber') return '\u26a0\ufe0f Attention'
                            if (c === 'red') return '\u26d4 Failed'
                            return '\u25fb No telemetry'
                          })()}
                        </div>
                        <div style={{ fontSize: 8, color: 'var(--text3)', fontFamily: 'monospace' }}>
                          {formatAgo(stage.minutes_ago)} {stage.rows_processed != null && stage.rows_processed > 0 ? `· ${stage.rows_processed.toLocaleString()} rows` : ''}
                        </div>
                      </div>

                      {/* Expanded detail */}
                      {isExpanded && (
                        <div style={{
                          marginTop: 4,
                          padding: '6px 8px',
                          background: 'var(--bg2, rgba(20,26,38,0.95))',
                          border: '1px solid rgba(255,255,255,0.07)',
                          borderRadius: 4,
                          fontSize: 9,
                          fontFamily: 'monospace',
                          color: 'var(--text2)',
                          minWidth: 160,
                          lineHeight: 1.6,
                        }}>
                          <div><span style={{ color: 'var(--text3)' }}>script:</span> {(stage as any).owner_script || stage.id}</div>
                          <div><span style={{ color: 'var(--text3)' }}>status:</span>{' '}
                            <span style={{ color: colors.border }}>{stage.last_status ?? 'unknown'}</span>
                          </div>
                          <div><span style={{ color: 'var(--text3)' }}>last run:</span> {formatTimestamp(stage.last_run_at)}</div>
                          <div><span style={{ color: 'var(--text3)' }}>duration:</span> {formatDuration(stage.duration_sec)}</div>
                          <div><span style={{ color: 'var(--text3)' }}>cadence:</span> {(stage as any).cron_pattern || `every ${stage.cadence_h}h`}</div>
                          {(stage as any).output_tables?.length > 0 && (
                            <div><span style={{ color: 'var(--text3)' }}>output:</span> {(stage as any).output_tables.join(', ')}</div>
                          )}
                          {(stage as any).never_run_subtype && (
                            <div><span style={{ color: '#F59E0B' }}>why:</span> {(stage as any).never_run_subtype.replace(/_/g, ' ')}</div>
                          )}
                          {(stage as any).recommended_action && (
                            <div style={{ marginTop: 3, padding: '2px 4px', background: 'rgba(59,130,246,0.1)', borderRadius: 3, color: '#60A5FA' }}>
                              {(stage as any).recommended_action}
                            </div>
                          )}
                          {(stage as any).failure_hint && (
                            <div><span style={{ color: 'var(--text3)' }}>hint:</span> {(stage as any).failure_hint}</div>
                          )}
                          <div><span style={{ color: 'var(--text3)' }}>next expected:</span>{' '}
                            {stage.last_run_at && stage.cadence_h
                              ? new Date(new Date(stage.last_run_at).getTime() + stage.cadence_h * 3600_000).toLocaleTimeString()
                              : '-'}
                          </div>
                          {stage.error_message && (
                            <div style={{ marginTop: 4, padding: '3px 6px', background: 'rgba(239,68,68,0.1)', borderRadius: 3, color: '#EF4444', wordBreak: 'break-word' }}>
                              {stage.error_message}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </Card>
        ))}
      </div>
    </>
  )
}

const btnStyle: React.CSSProperties = {
  padding: '4px 12px',
  fontSize: 10,
  border: '1px solid rgba(255,255,255,0.08)',
  borderRadius: 8,
  background: 'rgba(255,255,255,0.04)',
  color: 'var(--text1)',
  cursor: 'pointer',
  fontFamily: 'var(--sans)',
}
