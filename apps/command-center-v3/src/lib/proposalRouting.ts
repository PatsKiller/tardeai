/** Two execution methods — same proposal queue, different paths at approve/promote time. */

export type ExecutionPath = 'unassigned' | 'paper_auto' | 'live_schwab' | 'live_fidelity'

export function routingKey(p: any): string {
  return String(p?.intended_broker || p?.target_account || p?.proposed_account || '').toLowerCase().trim()
}

export function executionPath(p: any): ExecutionPath {
  const k = routingKey(p)
  if (!k) return 'unassigned'
  if (k.startsWith('schwab')) return 'live_schwab'
  if (k.startsWith('fidelity')) return 'live_fidelity'
  return 'paper_auto'
}

export function isBrokerRouted(p: any): boolean {
  const ep = executionPath(p)
  return ep === 'live_schwab' || ep === 'live_fidelity'
}

export function isPaperAutoPath(p: any): boolean {
  return executionPath(p) === 'paper_auto'
}

export function isUnassigned(p: any): boolean {
  return executionPath(p) === 'unassigned'
}

const PATH_LABELS: Record<ExecutionPath, string> = {
  unassigned: 'Choose path',
  paper_auto: 'Paper auto',
  live_schwab: 'Live · Schwab',
  live_fidelity: 'Live · FA',
}

const PATH_COLORS: Record<ExecutionPath, string> = {
  unassigned: '#94A3B8',
  paper_auto: '#A855F7',
  live_schwab: '#60A5FA',
  live_fidelity: '#22C55E',
}

export function routingLabel(p: any): string {
  return PATH_LABELS[executionPath(p)]
}

export function routingColor(p: any): string {
  return PATH_COLORS[executionPath(p)]
}

export const EXECUTION_PATHS_DOC = '/docs/PROPOSAL_EXECUTION_PATHS.md'