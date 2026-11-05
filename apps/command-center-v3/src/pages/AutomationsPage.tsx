// Automations (n8n) page — design automations/v001, APPROVED 2026-11-04 (D36). Read-only: renders
// GET /api/v2/n8n/automations (scripts/lib/data_broker/n8n_automations.py). No number is computed here.
import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useApi } from '../hooks/useApi'
import { projectionReadPath } from '../lib/projectionReadProtocol'
import { Chip, ChipRow } from '../components/primitives'
import { RADIUS, TOKENS, TYPE, FONT, type Tone } from '../lib/designTokens'
import {
  displayCount, fmtEt, matchesFilter, projectAutomations, rowFailure, searchRows,
  type AutomationsFilter, type AutomationsPayload, type WorkflowRow,
} from '../lib/automationsProjection'

const panel: CSSProperties = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: 14, minWidth: 0 }
const cell: CSSProperties = { padding: '6px 6px', fontSize: TYPE.sm, color: TOKENS.text[1], textAlign: 'left', verticalAlign: 'top' }
const mono: CSSProperties = { ...cell, fontFamily: FONT.mono }
const h2: CSSProperties = { margin: '0 0 8px', fontSize: TYPE.base, color: TOKENS.text[0] }
const muted: CSSProperties = { fontSize: TYPE.sm, color: TOKENS.text[2] }
const tile: CSSProperties = { ...panel, display: 'flex', flexDirection: 'column', gap: 4, minWidth: 132, flex: '1 1 132px' }
const tileLabel: CSSProperties = { fontSize: TYPE.xs, color: TOKENS.text[3], textTransform: 'uppercase', letterSpacing: '0.04em' }
const tileValue: CSSProperties = { fontSize: TYPE.lg, fontWeight: 600, color: TOKENS.text[0], fontVariantNumeric: 'tabular-nums' }

const FILTERS: AutomationsFilter[] = ['all', 'failing', 'live', 'off']
const FILTER_LABEL: Record<AutomationsFilter, string> = { all: 'All', failing: 'Failing', live: 'Live', off: 'Off' }
const TABS = ['Workflows', 'Cutovers', 'Cron left', 'Library & backup'] as const

const deltaText = (d: Record<string, number | null> | null, key: string): string => {
  if (!d) return ''
  const v = d[key]
  if (typeof v !== 'number' || !Number.isFinite(v)) return ''
  if (v === 0) return ' · no change'
  return ` · ${v > 0 ? '+' : ''}${v} vs prior 7d`
}

function StatePill({ state }: { state?: string | null }) {
  const s = String(state ?? '').toLowerCase()
  const label = s === 'live' ? 'Live' : s === 'shadow' ? 'Shadow' : s === 'off' ? 'Off' : 'Unknown'
  const tone = s === 'live' ? 'success' : s === 'shadow' ? 'warning' : 'neutral'
  return <Chip tone={tone as Tone}>{label}</Chip>
}

export default function AutomationsPage({ active = true }: { active?: boolean } = {}) {
  const api = useApi<AutomationsPayload>(projectionReadPath('automations'), 60_000, { enabled: active })
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<AutomationsFilter>('all')
  const [openSnapshot, setOpenSnapshot] = useState<WorkflowRow | null>(null)
  // cx-openai-3's F6 at 25b3348e: a 304 keeps the same payload object, so a view projected once never aged. The clock
  // ticks on its own, and the projection is re-derived from it — an unchanged payload still becomes STALE when the
  // observation it carries gets old. Nothing here moves the producer's as_of.
  const [nowMs, setNowMs] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNowMs(Date.now()), 30_000)
    return () => window.clearInterval(id)
  }, [])
  const view = useMemo(
    () => projectAutomations(api.data ?? null, { error: !!api.error, nowMs }),
    [api.data, api.error, nowMs],
  )
  const rows = useMemo(() => searchRows(view.rows.filter(r => matchesFilter(r, filter)), query), [view.rows, filter, query])
  // cx-openai-3's F5 at 25b3348e: the sheet follows the CURRENT row by its stable id, so a refresh that changes or
  // removes the workflow is reflected instead of leaving yesterday's object on screen. A removed row keeps its sheet
  // only as an explicitly historical view.
  const rowKey = (r: WorkflowRow) => String(r.workflow_id ?? r.name ?? '')
  const liveOpen = openSnapshot === null ? null : (view.rows.find(r => rowKey(r) === rowKey(openSnapshot)) ?? null)
  const open = liveOpen ?? openSnapshot
  const removed = openSnapshot !== null && liveOpen === null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <style>{`
        .automations-sheet { position: fixed; inset: 0; background: ${TOKENS.bg[1]}; z-index: 40; overflow: auto; padding: 16px; }
        .automations-row { cursor: pointer; }
        .automations-row:focus-visible { outline: 2px solid ${TOKENS.primary}; outline-offset: -2px; }
        @media (max-width: 640px) { .automations-sheet { padding: 12px; } }
      `}</style>

      <div>
        <h2 style={h2}>Automations</h2>
        <div style={muted}>
          n8n schedules; the host does the work. Read-only, {view.asOf ? `checked ${fmtEt(view.asOf)}` : 'no successful check yet'}.
          {view.status !== 'OK' ? ` Status: ${view.status}.` : ''}
        </div>
      </div>

      {view.banner.show && view.banner.cause ? (
        <div role="alert" style={{ ...panel, borderLeft: `4px solid ${TOKENS.danger}`, display: 'flex', flexDirection: 'column', gap: 4 }}>
          <strong style={{ color: TOKENS.text[0] }}>{view.banner.rate}% of scheduled runs failed in the last 7 days.</strong>
          <span style={muted}>Top cause: {view.banner.cause.name} — {view.banner.cause.reason}</span>
        </div>
      ) : null}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
        <div style={tile}>
          {/* cx-openai-3's F3 at a1aa3bd3a: n8n keeps failed runs only, so this is a count of RECORDED executions,
              not of scheduled ones. Saying "scheduled" was the same untruth the rate carried. */}
          <span style={tileLabel}>Recorded runs</span>
          <span style={tileValue}>{displayCount(view.kpi.runs)}<span style={muted}>{deltaText(view.kpi.deltas, 'runs')}</span></span>
        </div>
        <div style={tile}>
          <span style={tileLabel}>Failed runs</span>
          <span style={tileValue}>{displayCount(view.kpi.failed)}<span style={muted}>{deltaText(view.kpi.deltas, 'failed')}</span></span>
        </div>
        {/* A lock skip is n8n recording "the previous run was still going" as an error. It is counted, and it is not a
            failure — the broker classifies every execution (cx-openai-3's / cx-openai-5's F1 at 25b3348e). */}
        <div style={tile}>
          <span style={tileLabel}>Lock skips</span>
          <span style={tileValue} title="Runs n8n refused because the previous run was still going. Never counted as failures.">
            {displayCount(view.kpi.skipped)}
          </span>
        </div>
        <div style={tile}>
          <span style={tileLabel}>Failure rate</span>
          <span style={tileValue} title={view.kpi.failRate === null ? (view.kpi.failRateUnavailable || 'rate unavailable') : undefined}>
            {view.kpi.failRate === null ? '—' : `${view.kpi.failRate}%`}
          </span>
        </div>
        <div style={tile}>
          {/* cx-openai-3's F3 remainder / cx-openai-5's F4: this is the mean of the SAVED executions, no more. */}
          <span style={tileLabel}>Avg recorded run time</span>
          <span style={tileValue} title="Mean duration of the runs that were saved, not of every scheduled run.">{view.kpi.avgRunS === null ? '—' : `${view.kpi.avgRunS}s`}</span>
        </div>
        <div style={tile}>
          <span style={tileLabel}>Cron jobs left</span>
          <span style={tileValue}>{displayCount(view.kpi.cronLeft)}<span style={muted}>{view.kpi.cronLeftHasDraft === null ? '' : ` · ${view.kpi.cronLeftHasDraft} have a draft`}</span></span>
        </div>
        <div style={tile}>
          <span style={tileLabel}>Workflows</span>
          <span style={tileValue}>{displayCount(view.counts.workflows)}<span style={muted}>{view.counts.failing ? ` · ${view.counts.failing} failing` : ''}</span></span>
        </div>
      </div>
      {view.kpi.deltasUnavailable ? <div style={muted}>Change vs the prior 7 days: {view.kpi.deltasUnavailable}.</div> : null}
      {/* cx-openai-3's F3 remainder: the sampling limitation was only a tooltip. It is on the page itself, at phone
          width, and it names the cohort every number above belongs to. */}
      {view.status !== 'UNAVAILABLE' ? (
        <div style={muted}>
          n8n keeps failed runs only; a successful run is not saved. Every count and average here is over the runs that
          were <strong>recorded</strong>, not over every run the schedules fired.
        </div>
      ) : null}

      <div style={panel}>
        <ChipRow>
          {TABS.map(t => <Chip key={t} tone={t === 'Workflows' ? 'success' : 'neutral'}>{t}</Chip>)}
        </ChipRow>
        <div style={{ ...muted, marginTop: 6 }}>
          This page currently renders the Workflows tab. Cutovers, Cron left and Library &amp; backup need their own
          broker sources (cutover ledger, crontab/timers, the ~/Claude/N8N manifest) and are not in this projection yet.
        </div>
      </div>

      <div style={panel}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 8 }}>
          <input
            id="automations-search"
            aria-label="Search workflows"
            placeholder="Search name, area or error"
            value={query}
            onChange={e => setQuery(e.target.value)}
            style={{ flex: '1 1 220px', minHeight: 36, padding: '6px 10px', fontSize: TYPE.sm, color: TOKENS.text[0],
                     background: TOKENS.bg[0], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm }}
          />
          <ChipRow>
            {FILTERS.map(f => (
              <Chip key={f} tone={filter === f ? 'success' : 'neutral'} onClick={() => setFilter(f)} title={`Show ${FILTER_LABEL[f].toLowerCase()}`}>
                {FILTER_LABEL[f]}
              </Chip>
            ))}
          </ChipRow>
        </div>

        {view.status !== 'OK' ? (
          <div style={muted}>{view.status === 'UNAVAILABLE' ? 'The automation data could not be read; no row is shown rather than an empty, healthy-looking table.' : 'The last successful check is old; rows below may be out of date.'}</div>
        ) : rows.length === 0 ? (
          <div style={muted}>{view.rows.length === 0 ? 'No non-archived workflow was reported.' : 'No workflow matches this search and filter.'}</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table aria-label="Automations workflows" style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>{['Workflow', 'Last saved run', 'Area', 'Steps', 'OK of recorded', 'Fail %', 'State'].map(h =>
                  <th key={h} style={{ ...cell, color: TOKENS.text[3], whiteSpace: 'nowrap' }}>{h}</th>)}</tr>
              </thead>
              <tbody>
                {rows.map(r => {
                  const { failing, reason } = rowFailure(r)
                  const name = String(r.name ?? 'unnamed workflow')
                  return (
                    <tr key={String(r.workflow_id ?? name)} className="automations-row" tabIndex={0}
                        onClick={() => setOpenSnapshot(r)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpenSnapshot(r) } }}
                        style={{ borderTop: `1px solid ${TOKENS.borderSubtle}`, borderLeft: failing ? `3px solid ${TOKENS.danger}` : '3px solid transparent' }}>
                      <td style={cell}>
                        <div style={{ color: TOKENS.text[0] }}>{name}</div>
                        {failing ? <div style={{ ...muted, color: TOKENS.danger ?? TOKENS.text[1] }}>{reason}</div> : null}
                      </td>
                      <td style={mono}>{fmtEt(r.last_run_at) ?? '—'}</td>
                      <td style={mono}>{r.folder ?? '—'}</td>
                      <td style={mono}>{r.steps ?? '—'}</td>
                      <td style={mono}>{r.ok ?? '—'} / {r.runs ?? '—'}</td>
                      <td style={{ ...mono, color: failing ? (TOKENS.danger) : TOKENS.text[1] }}>{r.fail_pct ?? '—'}</td>
                      <td style={cell}><StatePill state={r.state} /></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {open ? (
        <div className="automations-sheet" role="dialog" aria-modal="true" aria-label={`${open.name ?? 'Workflow'} details`}>
          <button type="button" onClick={() => setOpenSnapshot(null)}
                  style={{ minHeight: 44, padding: '8px 12px', marginBottom: 12, fontSize: TYPE.sm, color: TOKENS.text[0],
                           background: TOKENS.bg[0], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, cursor: 'pointer' }}>
            ← Back
          </button>
          <h2 style={h2}>{String(open.name ?? 'unnamed workflow')}</h2>
          {/* cx-openai-3's F5 at 25b3348e: the sheet follows the current list. When the workflow is gone from it, the
              numbers below are labelled as the snapshot they are instead of reading as today's. */}
          {removed ? (
            <div role="note" style={{ ...panel, borderLeft: `4px solid ${TOKENS.warning}`, marginBottom: 12 }}>
              <strong>This workflow is not in the current list.</strong>{' '}
              <span style={muted}>
                {view.status === 'OK'
                  ? 'It was removed or archived since this sheet was opened; the figures below are the last values read for it, not today’s.'
                  : 'The current list could not be read, so these are the last values read for it, not today’s.'}
              </span>
            </div>
          ) : null}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 12 }}>
            <div style={tile}><span style={tileLabel}>State</span><span style={tileValue}><StatePill state={open.state} /></span></div>
            <div style={tile}><span style={tileLabel}>Saved runs (7d)</span><span style={tileValue}>{displayCount(open.runs ?? null)}</span></div>
            <div style={tile}><span style={tileLabel}>Failures</span><span style={tileValue}>{displayCount(open.fail ?? null)}</span></div>
            <div style={tile} title="Runs n8n refused because the previous run was still going. Never counted as failures.">
              <span style={tileLabel}>Lock skips</span><span style={tileValue}>{displayCount(open.skipped ?? null)}</span></div>
            <div style={tile}><span style={tileLabel}>Last saved run</span><span style={tileValue}>{fmtEt(open.last_run_at) ?? '—'}</span></div>
          </div>
          {(() => {
            const { failing, reason } = rowFailure(open)
            return failing ? (
              <div style={{ ...panel, borderLeft: `4px solid ${TOKENS.danger}`, marginBottom: 12 }}>
                <strong>Why it fails:</strong> {reason}
                {open.last_error_at ? <div style={muted}>Last error at {fmtEt(open.last_error_at)}</div> : null}
              </div>
            ) : (
              <div style={{ ...panel, marginBottom: 12 }}><span style={muted}>No failure recorded in the last 7 days.</span></div>
            )
          })()}
          <div style={panel}>
            <div style={muted}>
              Runs per 6 h, what this replaces, the repo and backup files with drift, and the lifecycle stage with 72 h
              progress are part of the approved design but are not in this projection yet; the sheet shows only what the
              broker has measured rather than inventing it.
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
