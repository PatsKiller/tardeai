// System → Releases & schedules (operator-approved 2026-10-22; mockup gate3 Pipeline.dc.html). What is queued and for
// when, what actually shipped, what failed — deploys and n8n / host cron in one place. Read-only view of
// GET /api/v2/ops/releases-schedules (scripts/lib/releases_schedules_view.py; contract docs/ops/RELEASES_SCHEDULES_PAGE.md).
// Every section shows its own freshness (state · age · source); UNAVAILABLE renders with its reason, never 0 or green.
// There is no control here: the deploy STOP is on Home → Deploys and Ops → Controls (components/DeployStopControl).
// The retired release train's windows and queue sections and its tab were removed 2026-10-27 (operator directive).
import { useEffect, useState, type CSSProperties, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import JobsHealth from '../components/JobsHealth'
import DeployInFlightBoard from '../components/DeployInFlightBoard'
import './OpsEvidencePages.css'
import { Chip, ChipRow } from '../components/primitives'
import { FONT, RADIUS, TOKENS, TYPE, toneVars, type Tone } from '../lib/designTokens'
import {
  ciLabel, ciTone, countOrUnavailable, etDateTime, etTime, freshnessTone, kpiDisplay, prList, RELEASES_SCHEDULES_PATH,
  sectionView, stageTone, verifyLabel, verifyVerdict,
  type LedgerToday, type NextRelease, type ReleaseError, type ReleaseRow, type ReleasesSchedulesWire,
  type SectionKey, type SectionView, type Serving, type Timeline, type TimelineRow,
} from '../lib/releasesSchedules'
import OpsDeskFrame from '../components/OpsDeskFrame'
import { IN_FLIGHT_PATH, normalizeCoordination, normalizeRows, type DeployInFlightWire, type InFlightPr } from '../lib/deployInFlight'
import { agentStateSentence, coordinationNote, engineerPanelProps, flightFreshnessNote, goingLive, jobsLine, liveNow, mergedWaiting, needsYou, needsYouAction, needsYouFacts, plainText, stuck } from '../lib/releasesOperatorView'

const panel: CSSProperties = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: 14, minWidth: 0, display: 'grid', gap: 8 }
const h2: CSSProperties = { margin: 0, fontSize: TYPE.md, fontWeight: 800, color: TOKENS.text[0] }
const muted: CSSProperties = { fontSize: TYPE.sm, color: TOKENS.text[2], margin: 0 }
const cell: CSSProperties = { padding: '6px 6px', fontSize: TYPE.sm, color: TOKENS.text[1], verticalAlign: 'top', textAlign: 'left' }
const mono: CSSProperties = { fontFamily: FONT.mono, fontSize: TYPE.sm }
const TABS = [['deploys', 'Deploys'], ['n8n', 'n8n & schedules'], ['jobs', 'Jobs']] as const
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

function DeploysTab({ s }: { s: Record<SectionKey, SectionView<any>> }) {
  const hist = (s.history.value as { releases: ReleaseRow[]; receipts_total: number } | null)
  const errs = s.release_errors.value as { rows: ReleaseError[]; window_hours: number; not_covered: string } | null
  const nx = s.next_release.value as NextRelease | null
  return <div style={{ display: 'grid', gap: 12 }}>
    <DeployInFlightBoard />
    <Section title="Releasing next · main HEAD" testId="rs-next" v={s.next_release}>
      {nx ? <Table label="Next release" heads={['main HEAD', 'Subject', 'Ahead of serving', 'PRs since serving', 'Exact-SHA CI']} empty="—" rows={[[
        <span style={mono}>{nx.short_sha}</span>, nx.subject ?? '—', nx.is_serving ? 'serving now' : countOrUnavailable(nx.commits_ahead),
        prList(nx.prs_since_serving, nx.prs_reason),
        <span title={nx.ci.source ?? ''}><Pill tone={ciTone(nx.ci.state)}>{ciLabel(nx.ci)}</Pill>
          {(nx.ci.workflows ?? []).length ? <span style={{ ...muted, display: 'block' }}>{(nx.ci.workflows ?? []).map(w => `${w.name ?? '?'} ${w.state ?? '?'}`).join(' · ')}</span> : null}
          {nx.ci.reason ? <span style={{ ...muted, display: 'block' }}>{nx.ci.reason}</span> : null}</span>,
      ]]} /> : null}
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
    <p style={muted} data-testid="rs-where-to-act">
      Deploy STOP / resume:{' '}
      <Link to="/system/ops-controls?tab=jobs" style={{ color: TOKENS.primary }} data-testid="rs-ops-controls-link">Ops → Controls → Deploys</Link>
      {' '}· Observe:{' '}
      <Link to="/coordination?tab=release" style={{ color: TOKENS.primary }} data-testid="rs-lifecycle-link">Coordination → Deploy</Link>
      . Mergify owns the merge queue; emergency promote is host CLI under release-write naming the SHA. This tab is serving pin, main HEAD, release history and errors.
    </p>
  </div>
}

function TimelineTable({ rows, label, empty }: { rows: TimelineRow[]; label: string; empty: string }) {
  return <Table label={label} heads={['Time (ET)', 'Lane', 'Runner', 'Stage']} empty={empty}
    rows={rows.map(r => [<span style={mono}>{r.cadence_label ? `${r.cadence_label} · from ${etTime(r.at)}` : etTime(r.at)}</span>,
      <span title={r.schedule}>{r.lane}</span>, r.runner,
      <span title={r.n8n_stage ? `registry scheduler.stage ${r.n8n_stage}` : ''}><Pill tone={stageTone(r.stage)}>{r.stage}</Pill></span>])} />
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


/** The operator view: what is live, what needs him, what is stuck and who fixes it (operator 2026-11-03). Every number
 *  carries its own clock or says in words that it has none; no code, SHA, branch or PR number appears here. */
function OperatorView({ s, rows, agents, generatedAt, flightAsOf, coordAsOf, flightError, loading, now,
  flightLoading, flightStale, coordStatus }: {
  s: Record<SectionKey, SectionView<any>>; rows: InFlightPr[]
  agents: Array<{ agent?: string | null; session?: string; task?: string | null; state?: string
    execution_state?: string | null; as_of?: string | null; claim_as_of?: string | null }>
  generatedAt: string | null; flightAsOf: string | null; coordAsOf: string | null
  flightError: string | null; loading: boolean; now: number
  // codex R4 (#2541): an empty list means nothing ONLY when the source actually answered. These three carry the
  // source's own state into the render, so an unanswered or stale request can never print "nothing" / "no agent".
  flightLoading: boolean; flightStale: boolean; coordStatus: 'OK' | 'PARTIAL' | 'UNAVAILABLE' }) {
  // An unparseable stamp is unknown, never an em-dash standing in for a time (codex R6).
  const when = (v: string | null | undefined) => { if (!v) return 'unknown'; const t = etDateTime(v); return t === '—' ? 'unknown' : t }
  // Every block that shows a number says when it was counted (lead, 2026-11-03).
  const flightClock = flightAsOf ? `checked ${when(flightAsOf)}` : 'as of unknown — the open-change source did not record when it checked'
  const coordClock = coordAsOf ? `last agent report ${when(coordAsOf)}` : 'as of unknown — the agent list did not record when it last checked'
  const status = liveNow(s as any, generatedAt, when)
  const ask = needsYou(rows)
  const groups = goingLive(rows)
  const blocked = stuck(rows)
  const td = s.n8n_today
  const jobs = jobsLine(td as any, when)
  const hist = s.history.value as { releases: ReleaseRow[]; receipts_total: number } | null
  const notChecked = flightError ? `The open-change list could not be read (${plainText(flightError, 'no reason given')}); anything below is from the sources that answered, and this is not an all-clear.` : null
  // One sentence per SOURCE STATE, reused by every list. Nothing here claims a measured zero unless the source
  // answered and the answer was empty (codex R4).
  const flightUnknown = flightLoading && !rows.length ? 'Still asking the open-change source — this is not an answer yet.'
    : flightStale && !rows.length ? `The open-change list is stale${flightAsOf ? ` (checked ${when(flightAsOf)})` : ''}, so an empty list here is not proof that nothing is open.`
      : null
  const agentsUnknown = coordStatus !== 'OK' && !agents.length ? coordinationNote(coordStatus) : null
  const agentsNote = coordStatus !== 'OK' && agents.length ? coordinationNote(coordStatus) : null
  // Rows that ARE shown under a stale or still-loading read say so above themselves, not only when they are absent.
  const flightNote = flightFreshnessNote({ loading: flightLoading, stale: flightStale, asOf: flightAsOf }, when)
  // codex R5: merged-but-not-live comes from the RELEASE payload, never from the open-PR list.
  const waiting = mergedWaiting(s.next_release.value as any, s.serving.value as any, when)
  return <div data-testid="rs-operator-view" style={{ display: 'grid', gap: 12, minWidth: 0 }}>
    <section data-testid="rs-what-is-live" style={{ ...panel, gap: 6 }}>
      <ChipRow><Chip tone={status.tone} variant="solid">{status.tone === 'success' ? 'All good' : status.tone === 'danger' ? 'Needs attention' : 'Watch'}</Chip></ChipRow>
      <h2 style={{ ...h2, fontSize: TYPE.lg }}>{loading ? 'Checking what is live…' : status.headline}</h2>
      <p style={{ ...muted, color: TOKENS.text[1] }}>{loading ? 'This is not an all-clear yet — the sources have not answered.' : status.detail}</p>
      <p style={muted}>{loading ? 'no clock yet' : status.clock}</p>
      {ask.length ? <a href="#rs-needs-you" style={{ minHeight: 44, display: 'inline-flex', alignItems: 'center', color: TOKENS.primary, fontWeight: 700 }}>{ask.length} thing{ask.length === 1 ? '' : 's'} need you ↓</a> : null}
    </section>

    <section id="rs-needs-you" data-testid="rs-needs-you" style={panel}>
      <h2 style={h2}>Needs you</h2>
      <p style={muted}>{flightClock}</p>
      {notChecked ? <p role="status" style={{ ...muted, color: toneVars('warning').color }}>{notChecked}</p> : null}
      {flightNote && !notChecked ? <p role="status" style={{ ...muted, color: toneVars('warning').color }}>{flightNote}</p> : null}
      {ask.length === 0 ? <p style={muted}>{flightUnknown ? flightUnknown : notChecked ? 'Nothing needs you from the sources that answered.' : 'Nothing needs you.'}</p> : ask.map(p => (
        <div key={p.number} style={{ borderTop: `1px solid ${TOKENS.borderSubtle}`, paddingTop: 8 }}>
          <div style={{ fontSize: TYPE.base, color: TOKENS.text[0], fontWeight: 700 }}>{plainText(p.title)}</div>
          <div style={muted}>{plainText(p.work?.owner ?? p.work?.board_owner, 'The agent that wrote it')}: {plainText(p.work?.current_task, 'the work is described only under Details for engineers')}.</div>
          <div style={{ ...muted, color: TOKENS.text[1] }}>{needsYouFacts(p, needsYouAction(p)).headline}</div>
          {needsYouFacts(p, needsYouAction(p)).warning
            ? <div style={{ ...muted, color: toneVars('warning').color }}>{needsYouFacts(p, needsYouAction(p)).warning}</div> : null}
          <div style={muted}>{needsYouAction(p).effect}</div>
          <a href={needsYouAction(p).kind === 'approve' ? p.url : '/system/releases?engineer=1'}
            style={{ minHeight: 44, display: 'inline-flex', alignItems: 'center', color: TOKENS.primary }}>{needsYouAction(p).label}</a>
        </div>))}
    </section>

    <section data-testid="rs-going-live" style={panel}>
      <h2 style={h2}>Going live today</h2>
      <p style={muted}>{flightClock}</p>
      {flightNote ? <p role="status" style={{ ...muted, color: toneVars('warning').color }}>{flightNote}</p> : null}
      {/* codex R5: this section is fed by RELEASE data as well as open changes, so a merge that is not live yet is
          representable even when the open-change list is empty or unreadable. */}
      {waiting.waiting || waiting.tone !== 'success'
        ? <div data-testid="rs-merged-not-live" style={{ borderTop: `1px solid ${TOKENS.borderSubtle}`, paddingTop: 8 }}>
            <div style={{ fontSize: TYPE.base, color: TOKENS.text[0], fontWeight: 700 }}>{waiting.headline}</div>
            <div style={{ ...muted, color: waiting.tone === 'warning' ? toneVars('warning').color : TOKENS.text[1] }}>{waiting.detail}</div>
          </div> : null}
      {!rows.length ? <p style={muted}>{waiting.waiting ? 'No open change is waiting to merge; the merged work above is what is waiting to go live.'
        : (flightUnknown ?? notChecked ?? 'Nothing is going live today.')}</p> : groups.map(g => (
        <div key={g.stage}>
          <h3 style={{ ...h2, fontSize: TYPE.base, marginTop: 8 }}>{g.label} · {g.rows.length}</h3>
          {g.rows.map(p => <div key={p.number} style={{ ...muted, padding: '4px 0' }}>
            {plainText(p.title)} — {plainText(p.work?.owner ?? p.work?.board_owner, 'nobody assigned yet')}
            {p.work?.as_of ? `, last touched ${when(p.work.as_of)}` : ', no time recorded for this step'}
          </div>)}
        </div>))}
    </section>

    <section data-testid="rs-stuck" style={panel}>
      <h2 style={h2}>Stuck — and who fixes it</h2>
      <p style={muted}>{flightClock}</p>
      {!blocked.length ? <p style={muted}>{rows.length ? 'Nothing is stuck right now.' : (flightUnknown ?? notChecked ?? 'Nothing is stuck right now.')}</p>
        : blocked.map(({ pr, because, whose }) => <div key={pr.number} style={{ ...muted, padding: '4px 0' }}>
          <b style={{ color: TOKENS.text[0] }}>{plainText(pr.title)}</b> — {because}. {whose} has the next step.
        </div>)}
    </section>

    <section data-testid="rs-agents-now" style={panel}>
      <h2 style={h2}>Agents now</h2>
      <p style={muted}>{coordClock}</p>
      {agentsNote ? <p role="status" style={{ ...muted, color: toneVars('warning').color }}>{agentsNote}</p> : null}
      {!agents.length ? <p style={muted}>{agentsUnknown ?? 'No agent is working right now.'}</p>
        : agents.map((a, i) => {
          // cc3 review F2: BOARD agents carry no `agent` name and no `as_of`; the served facts are session,
          // execution_state and claim_as_of. Say the activity in words and the time we can actually prove.
          const name = plainText(a.agent ?? a.session, 'An agent session')
          // codex R4: an unrecorded or unrecognised state is NOT idle. Only a state the page can actually read is
          // coloured; "we do not know" renders as unknown, in the neutral tone.
          const activity = agentStateSentence(a.execution_state ?? a.state)
          const clock = a.claim_as_of ?? a.as_of
          return <div key={i} style={{ ...muted, padding: '2px 0', color: activity.idle === true ? toneVars('warning').color
            : activity.idle === null ? toneVars('neutral').color : TOKENS.text[1] }}>
            {name}: {plainText(a.task, 'no task named')} — {activity.text}
            {clock ? `, last reported ${when(clock)}` : ', no time recorded for this agent'}
          </div>
        })}
    </section>

    <section data-testid="rs-old-work" style={panel}>
      <h2 style={h2}>Old work</h2>
      <p style={muted}>The daily pull-request audit is not counted on this page, so no number is shown here rather than a guess.</p>
      <a href="/coordination?rag=red" style={{ minHeight: 44, display: 'inline-flex', alignItems: 'center', color: TOKENS.primary }}>See the blocked and red work →</a>
    </section>

    <section data-testid="rs-recent-releases" style={panel}>
      <h2 style={h2}>Recent releases</h2>
      <p style={muted}>{s.history.asOf ? `history as of ${when(s.history.asOf)}` : 'as of unknown — the release history did not record when it was read'}</p>
      {!hist?.releases?.length ? <p style={muted}>Release history cannot be read right now.</p> : hist.releases.slice(0, 5).map(r => {
        // codex R1 (#2541): read the STRUCTURED verdict. The previous code tested the label with /VERIFIED$/, and
        // "NOT VERIFIED" ends with "VERIFIED" — so a failed check rendered as "Checked working: yes."
        const verdict = {
          verified: 'Checked working: yes.',
          not_verified: 'Checked working: no — the release did not pass its own check.',
          rollback: 'This release was rolled back.',
          not_recorded: 'Checked working: not recorded — the receipt was replaced by a later release.',
        }[verifyVerdict(r)]
        return <div key={r.receipt} style={{ ...muted, padding: '4px 0' }}>
          <b style={{ color: TOKENS.text[0] }}>{etDateTime(r.at)}</b> — {verdict}
          {' '}The recorded changes are not named in words on this page.
        </div>
      })}
    </section>

    <section data-testid="rs-jobs-health" style={panel}>
      <h2 style={h2}>Scheduled jobs health</h2>
      <p style={{ ...muted, color: jobs.tone === 'warning' ? toneVars('warning').color : TOKENS.text[1] }}>{jobs.text}</p>
      <p style={muted}>{jobs.clock}</p>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <Link to="/system/ops-controls?tab=jobs" style={{ minHeight: 44, display: 'inline-flex', alignItems: 'center', color: TOKENS.primary }}>Open the job controls →</Link>
        <Link to="/ops/jobs" style={{ minHeight: 44, display: 'inline-flex', alignItems: 'center', color: TOKENS.primary }}>See every job →</Link>
      </div>
    </section>
  </div>
}

export default function ReleasesSchedules() {
  const now = useNow(15_000)
  const [params, setParams] = useSearchParams()
  const tab: TabKey = params.get('tab') === 'jobs' ? 'jobs' : params.get('tab') === 'n8n' ? 'n8n' : 'deploys'
  const api = useApi<ReleasesSchedulesWire>(RELEASES_SCHEDULES_PATH, 60_000, { enabled: tab !== 'jobs' })
  // Operator view first (operator 2026-11-03). The developer content stays, behind a toggle, closed by default.
  // codex R3 (#2541): the section carried `hidden` AND an inline `display:grid`, and an inline display beats the
  // hidden attribute — so the engineer panel was laid out while its toggle said CLOSED. The toggle also forced the
  // panel open on non-deploy tabs with no way to close it. An explicit choice now wins over the tab default.
  const [engChoice, setEngChoice] = useState<boolean | null>(null)
  const eng = engChoice ?? (params.get('engineer') === '1' || tab !== 'deploys')
  const setEng = (open: boolean) => {
    setEngChoice(open)
    const n = new URLSearchParams(params); if (open) n.set('engineer', '1'); else n.delete('engineer')
    setParams(n, { replace: true })
  }
  const flight = useApi<DeployInFlightWire>(IN_FLIGHT_PATH, 60_000)
  const flightWire = ((flight.data as { data?: DeployInFlightWire } | DeployInFlightWire | null) as any)?.data ?? flight.data
  const flightRows: InFlightPr[] = flightWire && Array.isArray(flightWire.prs) ? normalizeRows(flightWire.prs).rows : []
  const flightAgents = normalizeCoordination(flightWire?.coordination).agents
  const flightError = flight.error ? String(flight.error) : (flightWire?.reason ?? null)
  const opts = { nowMs: now, error: !!api.error, stale: api.stale }
  const keys: SectionKey[] = ['serving', 'next_release', 'history', 'release_errors', 'n8n_today', 'timeline']
  const s = Object.fromEntries(keys.map(k => [k, sectionView(api.data, k, opts)])) as Record<SectionKey, SectionView<any>>
  const current = !api.error && !api.stale && keys.some(k => s[k].state === 'OK')
  const kpis = api.data?.schema === 'ReleasesSchedules@v1' ? api.data.kpis ?? [] : []
  const kpiKeys = ['serving', 'next_release', 'n8n_runs', 'n8n_errors']
  const labels: Record<string, string> = { serving: 'Serving', next_release: 'main HEAD', n8n_runs: 'n8n runs today', n8n_errors: 'n8n errors · skips' }
  const serving = s.serving.value as Serving | null
  const select = (t: TabKey) => { const n = new URLSearchParams(params); if (t === 'deploys') n.delete('tab'); else n.set('tab', t); setParams(n, { replace: true }) }
  return <OpsDeskFrame page="releases">
<div className="ops-evidence-page" data-testid="releases-schedules" style={{ display: 'grid', gap: 12, minWidth: 0, maxWidth: '100%' }}>
    <OperatorView s={s} rows={flightRows} agents={flightAgents} generatedAt={api.data?.generated_at ?? null}
      flightAsOf={flightWire?.generated_at ?? null} coordAsOf={normalizeCoordination(flightWire?.coordination).as_of}
      flightError={flightError} loading={api.loading && !api.data} now={now}
      flightLoading={!!flight.loading && !flightWire} flightStale={!!flight.stale}
      coordStatus={normalizeCoordination(flightWire?.coordination).status} />

    <button type="button" id="rs-engineer-toggle" data-testid="rs-engineer-toggle" aria-expanded={eng} aria-controls="rs-engineer-details"
      onClick={() => setEng(!eng)}
      style={{ minHeight: 44, width: '100%', textAlign: 'left', cursor: 'pointer', background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`,
        borderRadius: RADIUS.md, padding: '10px 14px', color: TOKENS.text[0], fontSize: TYPE.sm, fontWeight: 700 }}>
      {eng ? 'Hide details for engineers' : 'Details for engineers'}
      <span style={{ display: 'block', fontWeight: 400, color: TOKENS.text[2], marginTop: 2 }}>
        Everything the page showed before is here: raw tables, commit identifiers, check names and run ids.
      </span>
    </button>

    <div data-testid="rs-engineer-tabs">
    <nav role="tablist" aria-label="Releases and schedules sections" style={{ display: 'flex', gap: 6, flexWrap: 'wrap', borderBottom: `1px solid ${TOKENS.border}`, paddingBottom: 10 }}>
      {TABS.map(([k, label]) => <button key={k} type="button" role="tab" aria-selected={tab === k} data-testid={`rs-tab-${k}`} onClick={() => select(k)}
        style={{ borderRadius: RADIUS.md, padding: '8px 14px', fontSize: TYPE.sm, fontWeight: 700, cursor: 'pointer', minHeight: 44,
          background: tab === k ? TOKENS.bg[2] : 'transparent', border: `1px solid ${tab === k ? TOKENS.primary : TOKENS.border}`, color: tab === k ? TOKENS.text[0] : TOKENS.text[2] }}>{label}</button>)}
    </nav>
    </div>

    <section id="rs-engineer-details" aria-labelledby="rs-engineer-toggle" {...engineerPanelProps(eng)}
      style={{ ...engineerPanelProps(eng).style, gap: 12, minWidth: 0 }}>
    <div style={{ ...panel, gap: 4 }}>
      <p style={muted}>Serving pin · last promote · deploy STOP · Mergify queue (external) · n8n schedules. Read-only; nothing here merges, promotes or schedules.</p>
      <ChipRow>
        {api.error && !api.data ? <Chip tone="warning">UNAVAILABLE · {api.error}</Chip> : api.loading && !api.data ? <Chip tone="neutral">Loading</Chip>
          : <Chip tone={api.data?.status === 'OK' && current ? 'neutral' : 'warning'}>{current ? (api.data?.status ?? 'UNKNOWN') : 'STALE'}</Chip>}
        {api.data?.generated_at
          ? <Chip tone="neutral">captured {etDateTime(api.data.generated_at)}</Chip>
          : <Chip tone="warning">capture time not stated</Chip>}
        {serving ? <Chip tone={serving.pins_agree ? 'neutral' : 'warning'} title={serving.release_name ?? ''}>pins {serving.pins_agree ? 'agree with CURRENT' : 'DISAGREE with CURRENT'}</Chip> : null}
        {api.data?.stop?.effective_stop ? <Chip tone="danger">deploy STOP {api.data.stop.state}</Chip> : null}
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


    {tab === 'deploys' ? <DeploysTab s={s} /> : tab === 'jobs' ? <JobsHealth /> : <><p style={muted}>Schedules below declare intended fires. The Jobs tab shows whether each job actually ran and succeeded.</p><N8nTab s={s} /></>}
    </section>
  </div>
  </OpsDeskFrame>
}
