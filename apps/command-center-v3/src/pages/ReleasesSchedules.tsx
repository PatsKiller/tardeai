// System → Releases & schedules (operator-approved 2026-10-22; mockup gate3 Pipeline.dc.html). What is queued and for
// when, what actually shipped, what failed — the release train and n8n / host cron in one place. Read-only view of
// GET /api/v2/ops/releases-schedules (scripts/lib/releases_schedules_view.py; contract docs/ops/RELEASES_SCHEDULES_PAGE.md).
// Every section shows its own freshness (state · age · source); UNAVAILABLE renders with its reason, never 0 or green.
// There is no control here: STOP RELEASES stays on Coordination → Release train (components/ReleaseStopControl).
import { useEffect, useState, type CSSProperties, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { Chip, ChipRow } from '../components/primitives'
import { FONT, RADIUS, TOKENS, TYPE, toneVars, type Tone } from '../lib/designTokens'
import {
  ciLabel, ciTone, countOrUnavailable, etDateTime, etTime, freshnessTone, queueStoreText, kpiDisplay, lastRunText, prList, RELEASES_SCHEDULES_PATH,
  sectionView, stageTone, verifyLabel, windowTone,
  type LedgerToday, type NextRelease, type Queue, type ReleaseError, type ReleaseRow, type ReleasesSchedulesWire,
  type SectionKey, type SectionView, type Serving, type Timeline, type TimelineRow, type Windows,
} from '../lib/releasesSchedules'

const panel: CSSProperties = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: 14, minWidth: 0, display: 'grid', gap: 8 }
const h2: CSSProperties = { margin: 0, fontSize: TYPE.md, fontWeight: 800, color: TOKENS.text[0] }
const muted: CSSProperties = { fontSize: TYPE.sm, color: TOKENS.text[2], margin: 0 }
const cell: CSSProperties = { padding: '6px 6px', fontSize: TYPE.sm, color: TOKENS.text[1], verticalAlign: 'top', textAlign: 'left' }
const mono: CSSProperties = { fontFamily: FONT.mono, fontSize: TYPE.sm }
const TABS = [['train', 'Release train'], ['n8n', 'n8n & schedules']] as const
type TabKey = (typeof TABS)[number][0]

function useNow(ms: number): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), ms); return () => clearInterval(id) }, [ms])
  return now
}

function Fresh({ v }: { v: SectionView<unknown> }) {
  return <Chip tone={freshnessTone(v.state)} title={`${v.source}${v.asOf ? ` · as of ${v.asOf}` : ''}${v.reason ? ` · ${v.reason}` : ''}`}>{v.label}</Chip>
}

function Section({ title, sub, v, alert, children, testId }: { title: string; sub?: string; v: SectionView<unknown>; alert?: boolean; children: ReactNode; testId: string }) {
  const tone = toneVars('danger')
  return <section data-testid={testId} style={alert ? { ...panel, background: tone.bg, borderColor: tone.border } : panel}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
      <h2 style={h2}>{title}</h2>
      <ChipRow>{sub ? <span style={muted}>{sub}</span> : null}<Fresh v={v} /></ChipRow>
    </div>
    {v.state === 'UNAVAILABLE'
      ? <p role="status" style={{ ...muted, color: toneVars('warning').color, fontWeight: 700 }}>UNAVAILABLE{v.reason ? ` · ${v.reason}` : ''} — not empty, not healthy: unknown.</p>
      : children}
  </section>
}

function Table({ label, heads, rows, empty }: { label: string; heads: string[]; rows: Array<Array<ReactNode>>; empty: string }) {
  return <div style={{ overflowX: 'auto' }}>
    <table aria-label={label} style={{ width: '100%', borderCollapse: 'collapse' }}>
      <thead><tr>{heads.map(h => <th key={h} style={{ ...cell, color: TOKENS.text[3], whiteSpace: 'nowrap', fontSize: TYPE.xs, textTransform: 'uppercase' }}>{h}</th>)}</tr></thead>
      <tbody>
        {rows.map((r, i) => <tr key={i} style={{ borderTop: `1px solid ${TOKENS.borderSubtle}` }}>{r.map((c, j) => <td key={j} style={cell}>{c ?? '—'}</td>)}</tr>)}
        {!rows.length ? <tr><td colSpan={heads.length} style={{ ...cell, color: TOKENS.text[2] }}>{empty}</td></tr> : null}
      </tbody>
    </table>
  </div>
}

function Pill({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <Chip tone={tone} variant="solid">{children}</Chip>
}

function TrainTab({ s }: { s: Record<SectionKey, SectionView<any>> }) {
  const w = s.windows.value as Windows | null
  const q = s.queue.value as Queue | null
  const hist = (s.history.value as { releases: ReleaseRow[]; receipts_total: number } | null)
  const errs = s.release_errors.value as { rows: ReleaseError[]; window_hours: number; not_covered: string } | null
  const nx = s.next_release.value as NextRelease | null
  const stop = w?.stop
  return <div style={{ display: 'grid', gap: 12 }}>
    <Section title="Next windows" testId="rs-windows" v={s.windows}
      sub={w ? `train ${w.armed ? 'ARMED' : 'UNARMED'} · delegation ${w.delegation?.state ?? 'UNAVAILABLE'} · STOP latch ${stop?.state ?? 'UNAVAILABLE'}` : undefined}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 8 }}>
        {(w?.windows ?? []).map((x, i) => (
          <div key={x.window_id} style={{ background: TOKENS.bg[2], border: `1px solid ${i === 0 ? toneVars(windowTone(x.state)).border : TOKENS.border}`, borderRadius: RADIUS.sm, padding: '10px 12px', display: 'grid', gap: 4 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
              <span style={{ ...mono, fontSize: TYPE.lg, fontWeight: 700, color: TOKENS.text[0] }}>{x.local_time}</span>
              <Pill tone={windowTone(x.state)}>{x.state}</Pill>
            </div>
            <span style={{ fontSize: TYPE.sm, color: TOKENS.text[1] }}>{x.role ?? '—'} window · {etDateTime(x.starts_at)}</span>
            <span style={{ fontSize: TYPE.xs, color: TOKENS.text[2] }}>{x.reason ?? (x.enabled ? 'enabled' : 'not enabled')}{x.note ? ` · ${x.note}` : ''}</span>
            <span style={{ fontSize: TYPE.xs, color: TOKENS.text[3] }}>last shadow tick: {x.last_shadow_request_at ? `${etDateTime(x.last_shadow_request_at)} · ${x.last_shadow_receipt_state ?? 'no receipt'}` : 'never'}</span>
          </div>
        ))}
      </div>
      {w ? <p style={muted}>{w.manual_path}</p> : null}
    </Section>

    <Section title="Releasing next · main HEAD" testId="rs-next" v={s.next_release}>
      {nx ? <Table label="Next release" heads={['main HEAD', 'Subject', 'Ahead of serving', 'PRs since serving', 'Exact-SHA CI']} empty="—" rows={[[
        <span style={mono}>{nx.short_sha}</span>, nx.subject ?? '—', nx.is_serving ? 'serving now' : countOrUnavailable(nx.commits_ahead),
        prList(nx.prs_since_serving, nx.prs_reason),
        <span title={nx.ci.source ?? ''}><Pill tone={ciTone(nx.ci.state)}>{ciLabel(nx.ci)}</Pill>
          {(nx.ci.workflows ?? []).length ? <span style={{ ...muted, display: 'block' }}>{(nx.ci.workflows ?? []).map(w => `${w.name ?? '?'} ${w.state ?? '?'}`).join(' · ')}</span> : null}
          {nx.ci.reason ? <span style={{ ...muted, display: 'block' }}>{nx.ci.reason}</span> : null}</span>,
      ]]} /> : null}
    </Section>

    <Section title="Queue · what rides next" sub="PR · state · why not riding" testId="rs-queue" v={s.queue}>
      {q ? <>
        {q.census.alert ? <p role="alert" data-testid="rs-census-alert" style={{ margin: 0, padding: '8px 10px', borderRadius: RADIUS.sm, fontSize: TYPE.sm, fontWeight: 700, color: toneVars('danger').color, background: toneVars('danger').bg, border: `1px solid ${toneVars('danger').border}` }}>{q.census.alert}</p> : null}
        <ChipRow>
          <Chip tone={q.store.freshness === 'OK' && q.census.freshness === 'OK' ? 'neutral' : 'warning'} title={q.store.reason ?? ''}>{queueStoreText(q)}</Chip>
          <Chip tone={q.census.freshness === 'OK' ? 'neutral' : 'warning'} title={q.census.reason ?? ''}>PR census {q.census.freshness ?? 'UNAVAILABLE'} · {countOrUnavailable(q.census.open_prs)} open{q.census.as_of ? ` · ${etDateTime(q.census.as_of)}` : ''}</Chip>
        </ChipRow>
        <Table label="Open PRs and why each is not riding" heads={['PR', 'Title', 'Bucket', 'Riding?', 'Why not riding']}
          empty={q.census.freshness === 'UNAVAILABLE' ? `UNAVAILABLE · ${q.census.reason ?? 'census unavailable'}` : 'No open PRs in the census'}
          rows={q.open_prs.slice(0, 60).map(p => [<span style={mono}>{'#' + String(p.pr)}</span>, p.title ?? '—', p.bucket,
            <Pill tone={p.riding ? 'success' : 'neutral'}>{p.riding ? 'QUEUED' : 'NO'}</Pill>, p.riding ? '—' : p.why_not_riding])} />
      </> : null}
    </Section>

    <Section title="Shipped · release history" sub="served SHA · PRs · verify · rollback" testId="rs-history" v={s.history}>
      {hist ? <Table label="Release history" heads={['When', 'SHA', 'Release', 'PRs', 'Verify']} empty="No release pin receipts"
        rows={hist.releases.map(r => {
          const vl = verifyLabel(r)
          return [etDateTime(r.at), <span style={mono} title={`sha from ${r.sha_basis}`}>{r.short_sha ?? r.sha ?? '—'}</span>, r.release_name ?? r.receipt,
            prList(r.prs, r.prs_reason), <span title={r.verify_reason ?? ''}><Pill tone={vl.tone}>{vl.text}</Pill></span>]
        })} /> : null}
    </Section>

    <Section title="Release errors" sub={errs ? `last ${errs.window_hours} h` : undefined} testId="rs-release-errors" v={s.release_errors} alert={!!errs?.rows.length}>
      {errs ? <>
        {errs.rows.map((e, i) => <div key={i} style={{ fontSize: TYPE.sm, color: TOKENS.text[1] }}>
          <b style={{ color: toneVars('danger').color }}>{etDateTime(e.at)} · {e.kind}</b> · {e.detail} <span style={{ color: TOKENS.text[3] }}>({e.source})</span>
          {e.url ? <> · <a href={e.url} style={{ color: TOKENS.primary }} target="_blank" rel="noreferrer">run</a></> : null}
        </div>)}
        {!errs.rows.length ? <p style={muted}>No refused windows, rollbacks, failed deploy receipts or non-success deployed-SHA checks in the sources read.</p> : null}
        <p style={muted}>Not covered: {errs.not_covered}</p>
      </> : null}
    </Section>
    <p style={muted}>STOP RELEASES and the train's own queue/trains/events views live on <Link to="/coordination?tab=release" style={{ color: TOKENS.primary }}>Coordination → Release train</Link>.</p>
  </div>
}

function TimelineTable({ rows, label, empty }: { rows: TimelineRow[]; label: string; empty: string }) {
  return <Table label={label} heads={['Time (ET)', 'Lane', 'Runner', 'Stage', 'Last run / note']} empty={empty}
    rows={rows.map(r => [<span style={mono}>{r.cadence_label ? `${r.cadence_label} · from ${etTime(r.at)}` : etTime(r.at)}</span>,
      <span title={r.schedule}>{r.lane}</span>, r.runner,
      <span title={r.n8n_stage ? `registry scheduler.stage ${r.n8n_stage}` : ''}><Pill tone={stageTone(r.stage)}>{r.stage}</Pill></span>,
      <span style={{ color: TOKENS.text[2] }}>{lastRunText(r)}</span>])} />
}

function N8nTab({ s }: { s: Record<SectionKey, SectionView<any>> }) {
  const tl = s.timeline.value as Timeline | null
  const td = s.n8n_today.value as LedgerToday | null
  const max = Math.max(1, ...(td?.busiest ?? []).map(b => b.runs))
  return <div style={{ display: 'grid', gap: 12 }}>
    <Section title={`Coming up · next ${tl?.horizon_hours ?? 3} hours`} sub="host cron and n8n lanes, one timeline · stage shown" testId="rs-timeline" v={s.timeline}>
      {tl ? <>
        <ChipRow>
          <Chip tone={tl.crontab.source === 'crontab' || tl.crontab.source === 'snapshot' ? 'neutral' : 'warning'} title={tl.crontab.error ?? ''}>crontab {tl.crontab.source} · {tl.crontab.active_lines} active · {tl.crontab.paused_lines} paused</Chip>
          <Chip tone={tl.live_lanes.status === 'ok' ? 'neutral' : 'warning'}>relay live list {tl.live_lanes.status === 'ok' ? `${tl.live_lanes.count} lanes` : 'UNAVAILABLE'}</Chip>
          {tl.truncated ? <Chip tone="warning">truncated</Chip> : null}
        </ChipRow>
        {tl.notes.map((n, i) => <p key={i} style={{ ...muted, color: toneVars('warning').color }}>{n}</p>)}
        <TimelineTable rows={tl.rows} label="Scheduled runs in the next hours" empty="Nothing scheduled in the horizon (crontab and registry read)" />
        <h3 style={{ ...h2, fontSize: TYPE.base }}>Recurring (fires more than 4 times in the horizon)</h3>
        <TimelineTable rows={tl.recurring} label="Recurring schedules" empty="No sub-hourly schedules" />
      </> : null}
    </Section>

    <Section title="Errors and skips today" sub="from the coordination ledger" testId="rs-n8n-errors" v={s.n8n_today} alert={!!td && (td.errors_total > 0 || (td.dead_letters.unreleased ?? 0) > 0)}>
      {td ? <>
        <Table label="n8n failures today" heads={['Time (ET)', 'Lane', 'State', 'Why']} empty="No failed, timed-out or refused runs today"
          rows={td.errors.map(e => [<span style={mono}>{etTime(e.at)}</span>, e.lane, <Pill tone="danger">{e.state.replace('RUN_', '')}</Pill>,
            [e.reason, e.why, e.exit_code != null ? `exit ${e.exit_code}` : null, e.mode].filter(Boolean).join(' · ')])} />
        <Table label="Lock skips today" heads={['Lane', 'Mode', 'Skips', 'Last']} empty="No lock skips today"
          rows={td.lock_skips.map(k => [k.lane, k.mode, <Pill tone="warning">{'SKIP ×' + String(k.count)}</Pill>, etTime(k.last_at)])} />
        <p style={muted}>Dead letters unreleased: <b>{td.dead_letters.available ? countOrUnavailable(td.dead_letters.unreleased) : 'UNAVAILABLE (table absent)'}</b>
          {(td.dead_letters.recent ?? []).slice(0, 5).map((d, i) => <span key={i}> · {d.lane} {etDateTime(d.dead_at)}{d.last_reason ? ` (${d.last_reason})` : ''}</span>)}</p>
      </> : null}
    </Section>

    <Section title="Busiest lanes today" testId="rs-busiest" v={s.n8n_today}>
      {td ? <div style={{ display: 'grid', gap: 6 }}>
        {td.busiest.map(b => <div key={b.lane} style={{ display: 'grid', gridTemplateColumns: 'minmax(120px, 260px) 1fr 90px', gap: 10, alignItems: 'center', fontSize: TYPE.sm }}>
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={b.lane}>{b.lane}</span>
          <span style={{ height: 8, background: TOKENS.bg[2], borderRadius: RADIUS.sm, overflow: 'hidden' }}>
            <span style={{ display: 'block', height: 8, width: `${Math.round((b.runs / max) * 100)}%`, background: b.errors ? TOKENS.warning : TOKENS.info }} />
          </span>
          <span style={{ ...mono, textAlign: 'right' }}>{b.runs} runs</span>
        </div>)}
        {!td.busiest.length ? <p style={muted}>No ledger runs today.</p> : null}
        <p style={muted}>Day {td.day} (America/New_York), by requested time. {Object.entries(td.by_mode).map(([m, n]) => `${n} ${m}`).join(' · ')}</p>
      </div> : null}
    </Section>
  </div>
}

export default function ReleasesSchedules() {
  const now = useNow(15_000)
  const api = useApi<ReleasesSchedulesWire>(RELEASES_SCHEDULES_PATH, 60_000)
  const [params, setParams] = useSearchParams()
  const tab: TabKey = params.get('tab') === 'n8n' ? 'n8n' : 'train'
  const opts = { nowMs: now, error: !!api.error, stale: api.stale }
  const keys: SectionKey[] = ['serving', 'next_release', 'windows', 'queue', 'history', 'release_errors', 'n8n_today', 'timeline']
  const s = Object.fromEntries(keys.map(k => [k, sectionView(api.data, k, opts)])) as Record<SectionKey, SectionView<any>>
  const current = !api.error && !api.stale && keys.some(k => s[k].state === 'OK')
  const kpis = api.data?.schema === 'ReleasesSchedules@v1' ? api.data.kpis ?? [] : []
  const kpiKeys = ['serving', 'next_release', 'next_window', 'n8n_runs', 'n8n_errors']
  const labels: Record<string, string> = { serving: 'Serving', next_release: 'Releasing next', next_window: 'Next train window', n8n_runs: 'n8n runs today', n8n_errors: 'n8n errors · skips' }
  const serving = s.serving.value as Serving | null
  const select = (t: TabKey) => { const n = new URLSearchParams(params); if (t === 'train') n.delete('tab'); else n.set('tab', t); setParams(n, { replace: true }) }
  return <div data-testid="releases-schedules" style={{ display: 'grid', gap: 12, minWidth: 0, maxWidth: '100%' }}>
    <div style={{ ...panel, gap: 4 }}>
      <h1 style={{ margin: 0, fontSize: TYPE.lg, color: TOKENS.text[0] }}>Releases &amp; schedules</h1>
      <p style={muted}>What is queued, for when · what actually shipped · what failed. Release train and n8n in one place. Read-only; nothing here releases, stops or schedules.</p>
      <ChipRow>
        {api.error && !api.data ? <Chip tone="warning">UNAVAILABLE · {api.error}</Chip> : api.loading && !api.data ? <Chip tone="neutral">Loading</Chip>
          : <Chip tone={api.data?.status === 'OK' && current ? 'neutral' : 'warning'}>{current ? (api.data?.status ?? 'UNKNOWN') : 'STALE'}</Chip>}
        <Chip tone="neutral">generated {etDateTime(api.data?.generated_at)}</Chip>
        {serving ? <Chip tone={serving.pins_agree ? 'neutral' : 'warning'} title={serving.release_name ?? ''}>pins {serving.pins_agree ? 'agree with CURRENT' : 'DISAGREE with CURRENT'}</Chip> : null}
        {api.data?.stop?.effective_stop ? <Chip tone="danger">release STOP {api.data.stop.state}</Chip> : null}
      </ChipRow>
    </div>

    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 8 }}>
      {kpiKeys.map(key => {
        const k = kpis.find(x => x.key === key)
        const d = kpiDisplay(k, current)
        return <div key={key} data-testid={`rs-kpi-${key}`} style={{ ...panel, gap: 2, padding: '10px 12px' }}>
          <span style={{ ...mono, fontSize: TYPE.lg, fontWeight: 700, color: toneVars(d.tone).color }}>{d.value}</span>
          <span style={{ fontSize: TYPE.sm, fontWeight: 700, color: TOKENS.text[0] }}>{k?.label ?? labels[key]}</span>
          <span style={{ fontSize: TYPE.xs, color: TOKENS.text[2] }}>{d.detail}</span>
        </div>
      })}
    </div>

    <nav role="tablist" aria-label="Releases and schedules sections" style={{ display: 'flex', gap: 6, flexWrap: 'wrap', borderBottom: `1px solid ${TOKENS.border}`, paddingBottom: 10 }}>
      {TABS.map(([k, label]) => <button key={k} type="button" role="tab" aria-selected={tab === k} data-testid={`rs-tab-${k}`} onClick={() => select(k)}
        style={{ borderRadius: RADIUS.md, padding: '8px 14px', fontSize: TYPE.sm, fontWeight: 700, cursor: 'pointer', minHeight: 36,
          background: tab === k ? TOKENS.bg[2] : 'transparent', border: `1px solid ${tab === k ? TOKENS.primary : TOKENS.border}`, color: tab === k ? TOKENS.text[0] : TOKENS.text[2] }}>{label}</button>)}
    </nav>
    {tab === 'train' ? <TrainTab s={s} /> : <N8nTab s={s} />}
  </div>
}
