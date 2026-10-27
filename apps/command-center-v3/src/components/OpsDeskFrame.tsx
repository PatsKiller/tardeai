import type { ReactNode } from 'react'
import DeskPage, { type DeskDecision, type DeskSource } from './DeskPage'

/** Board 0 frame for the seven ops pages (W4 ops-pages directive, operator 2026-10-24: "make sure all of those ops
 *  pages get deployed with the redesign"). Purpose line, Source clocks with writer-lane state + last successful run
 *  from config/lane_registry.json (via /api/v2/desk-sources), in-panel gaps and the Decisions band. Each page keeps
 *  its own URL-synced tabs and every panel it had (change control): the frame is added around them, nothing is
 *  removed. Lane ids are registry ids; a source whose update time the page does not supply says so. */
export type OpsPageKey = 'health' | 'llm' | 'coordination' | 'broker' | 'releases' | 'controls' | 'system' | 'jobs' | 'incidents'

type SourceSpec = Omit<DeskSource, 'asOf' | 'gap'>
type PageSpec = { title: string; purpose: string; sources: SourceSpec[] }

const PAGES: Record<OpsPageKey, PageSpec> = {
  incidents: {
    title: 'Incidents',
    purpose: 'What broke, who or what is fixing it, what was tried, and what fixed it — the coordinator’s log. Agents and watchers write it; you acknowledge or close as won’t fix.',
    sources: [
      { id: 'watchers', label: 'Incident watchers (host timer, 5 min)', laneIds: [] },
      { id: 'supervisor', label: 'Incident supervisor (host timer, 10 min)', laneIds: [] },
    ],
  },
  jobs: {
    title: 'Jobs & health',
    purpose: 'Did each scheduled job actually run and succeed? Success is a run receipt with its exit code and output, never a log write time.',
    sources: [
      { id: 'receipts', label: 'Run receipts and wrapper events', laneIds: ['n8n-pilot-dispatch', 'n8n-incident-fanin'] },
      { id: 'registry', label: 'Job registry snapshot', laneIds: ['crontab-snapshot-for-health-agent'] },
    ],
  },
  health: {
    title: 'Health',
    purpose: 'What is broken or degraded right now, what was repaired, and did every job run?',
    sources: [
      { id: 'health', label: 'Health agent findings', laneIds: ['tradeai-health-agent-service', 'health-agent-llm-review'] },
      { id: 'crontab', label: 'Crontab snapshot for the health agent', laneIds: ['crontab-snapshot-for-health-agent'] },
    ],
  },
  llm: {
    title: 'LLM Spend',
    purpose: 'What each model lane costs, which calls failed, and where off-peak routing applies.',
    sources: [
      { id: 'spend', label: 'Spend reports', laneIds: ['llm-spend-report-daily', 'llm-spend-report-weekly'] },
      { id: 'deferred', label: 'Deferred (off-peak) queue', laneIds: ['llm-deferred-drain'] },
    ],
  },
  coordination: {
    title: 'Coordination',
    purpose: 'Agent work, n8n runs today, releases and migrations — and whether each scheduled job ran.',
    sources: [
      { id: 'n8n', label: 'n8n dispatch and incidents', laneIds: ['n8n-pilot-dispatch', 'n8n-incident-fanin'] },
      { id: 'gateway', label: 'Coordination gateway', laneIds: ['tradeai-n8n-coordination-gateway-service'] },
    ],
  },
  broker: {
    title: 'Broker Access',
    purpose: 'Is each broker connection readable, when did it last sync, and what is locked? Read-only; no orders.',
    sources: [
      { id: 'positions', label: 'Broker position sync', laneIds: ['schwab-position-sync', 'portfolio-broker-reconciliation'] },
      { id: 'stops', label: 'Broker stop reconcile', laneIds: ['broker-stop-reconcile'] },
    ],
  },
  releases: {
    title: 'Releases & Schedules',
    purpose: 'What is released, what is scheduled to run, and whether scheduled jobs actually ran.',
    sources: [
      { id: 'train', label: 'Deploy on main', laneIds: ['release-train-claim'] },
      { id: 'n8n', label: 'n8n dispatch', laneIds: ['n8n-pilot-dispatch'] },
    ],
  },
  controls: {
    title: 'Ops Controls',
    purpose: 'Change how the system runs — pause, resume, flags, grants — with preview, confirmation, backup and audit.',
    sources: [
      { id: 'applier', label: 'Controls applier', laneIds: ['ops-controls-applier'] },
      { id: 'crontab', label: 'Crontab snapshot', laneIds: ['crontab-snapshot-for-health-agent'] },
    ],
  },
  system: {
    title: 'System',
    purpose: 'Platform health, queues, storage and jobs — the plumbing behind every desk.',
    sources: [
      { id: 'platform', label: 'Platform maintenance', laneIds: ['platform-maintenance-nightly', 'postgres-main-watchdog'] },
      { id: 'server', label: 'Portfolio server watchdog', laneIds: ['portfolio-server-watchdog'] },
    ],
  },
}

export const OPS_PAGES = PAGES

const DECISIONS: DeskDecision[] = [
  { id: 'approvals', title: 'Approvals waiting on you →', detail: 'Policy amendments, grants, activations and operator conflicts, in one queue.', href: '/approvals' },
]

export default function OpsDeskFrame({ page, asOf = {}, gaps = {}, children }: {
  page: OpsPageKey
  /** The page's own payload time per source id; absent means the page has none to give (shown as a gap). */
  asOf?: Record<string, string | null | undefined>
  gaps?: Record<string, string | null | undefined>
  children: ReactNode
}) {
  const spec = PAGES[page]
  const sources: DeskSource[] = spec.sources.map(source => ({
    ...source, asOf: asOf[source.id] ?? null,
    gap: gaps[source.id] ?? (asOf[source.id] ? undefined : 'This page does not record when this source last updated; the writer’s last successful run is shown instead.'),
  }))
  return <DeskPage title={spec.title} purpose={spec.purpose} sources={sources} decisions={DECISIONS}>
    <div data-testid={`ops-frame-${page}`} style={{ minWidth: 0 }}>{children}</div>
  </DeskPage>
}
