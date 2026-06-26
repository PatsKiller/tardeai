/** Agnostic proposal status labels — simulation or live destination, never "paper-only". */

export const PROPOSAL_STATUS_LABELS: Record<string, { label: string; title: string; color: string }> = {
  APPROVED_FOR_PAPER_TEST: {
    label: 'Approved · route-eligible',
    color: '#22c55e',
    title: 'Passed review. Eligible for automated simulation OR live broker routing (2FA). Destination is operator-selected.',
  },
  PENDING: {
    label: 'Pending review',
    color: '#f59e0b',
    title: 'Awaiting agent + oversight review before routing',
  },
  APPROVED: {
    label: 'Approved · route-eligible',
    color: '#22c55e',
    title: 'Approved and eligible for broker routing (2FA when live)',
  },
  EXPIRED: { label: 'Expired', color: '#94a3b8', title: 'No longer routable' },
  REJECTED: { label: 'Rejected', color: '#ef4444', title: 'Rejected in review' },
}

export const ROUTING_PATH_LABELS: Record<string, string> = {
  queue_route_2fa: 'Live queue · 2FA',
  canary_pilot: 'Canary pilot',
  paper_auto: 'Auto simulation',
  record_only: 'Record only (manual)',
}

export function routingPathLabel(path?: string | null): string {
  if (!path) return 'Not submitted'
  return ROUTING_PATH_LABELS[path] || path.replace(/_/g, ' ')
}

export function unifiedEdgeFromProposal(p: any): number | null {
  const basis = p?.sizing_basis
  const raw = typeof basis === 'object' ? basis?.unified_edge : null
  if (raw != null && !Number.isNaN(Number(raw))) return Number(raw)
  return null
}