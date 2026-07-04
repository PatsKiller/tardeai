import type { ActionUrgency, ButtonVariant, CardVerdict } from './watchlistCardAction'

/** Proposal-card decision matrix (Phase B of the Proposals/Holdings redesign spec, 2026-07-04).
 *  Mirrors lib/watchlistCardAction.ts: one priority-ordered derivation returning the verdict,
 *  hero line and primary CTA together so the banner can never contradict the button.
 *
 *  Semantic verdicts include BLOCKED/CAUTION which the shared VerdictBanner's word map
 *  (watchlistCardTokens.verdictWord) does not know — `bannerVerdict` carries the nearest
 *  renderable CardVerdict so the primitive stays untouched. */

export const PROPOSAL_DRIFT_PCT = 15

export type ProposalVerdict = 'READY' | 'WAIT' | 'STALE' | 'FIX' | 'BLOCKED' | 'CAUTION'

/** What the primary button DOES — the card owns the handler wiring. */
export type ProposalPrimaryKind = 'dismiss' | 'view_gates' | 'modify' | 'approve' | null

export type ProposalCardAction = {
  verdict: ProposalVerdict
  /** Verdict passed to the shared VerdictBanner primitive (renderable word + treatment). */
  bannerVerdict: CardVerdict
  urgency: ActionUrgency
  heroText: string
  whyLine?: string
  primaryKind: ProposalPrimaryKind
  primaryLabel: string
  buttonVariant: ButtonVariant
}

function act(
  verdict: ProposalVerdict,
  bannerVerdict: CardVerdict,
  urgency: ActionUrgency,
  heroText: string,
  opts: { whyLine?: string; primaryKind?: ProposalPrimaryKind; primaryLabel?: string; buttonVariant?: ButtonVariant },
): ProposalCardAction {
  return {
    verdict,
    bannerVerdict,
    urgency,
    heroText,
    whyLine: opts.whyLine,
    primaryKind: opts.primaryKind ?? null,
    primaryLabel: opts.primaryLabel ?? '',
    buttonVariant: opts.buttonVariant ?? 'neutral',
  }
}

/**
 * Priority-ordered, first match wins:
 *  1. expired / broker-rejected      → STALE   · Dismiss
 *  2. hard gate / plan / oversight   → BLOCKED · View Gates
 *  3. live price >15% from entry     → FIX     · reprice/modify
 *  4. oversized vs cap               → FIX     · modify
 *  5. earnings within 7 days         → CAUTION · Approve (earnings Nd)
 *  6. required reviews pending       → WAIT    · no primary
 *  7. else all gates green           → READY   · Approve
 */
export function deriveProposalAction(args: {
  expired: boolean
  brokerRejected: boolean
  gateBlocked: boolean
  blockReason?: string | null
  blockerCount?: number
  driftPct: number | null
  oversized: boolean
  capShares?: number | null
  queuedShares?: number | null
  earningsDays: number | null
  earningsLabel?: string | null
  reviewsPendingBits: string[]
  fid: boolean
  approveLabel?: string
}): ProposalCardAction {
  const {
    expired, brokerRejected, gateBlocked, blockReason, blockerCount,
    driftPct, oversized, capShares, queuedShares,
    earningsDays, earningsLabel, reviewsPendingBits, fid, approveLabel,
  } = args
  const approveText = approveLabel || (fid ? 'Record proposal' : 'Approve · 2FA')

  if (expired || brokerRejected) {
    return act('STALE', 'STALE', 'none', brokerRejected ? 'Broker rejected' : 'Expired — not routable', {
      whyLine: brokerRejected ? 'Rejected in review — dismiss or rework' : 'Proposal window closed — dismiss to archive',
      primaryKind: 'dismiss',
      primaryLabel: 'Dismiss',
      buttonVariant: 'neutral',
    })
  }

  if (gateBlocked) {
    return act('BLOCKED', 'FIX', 'red', blockerCount ? `Blocked · ${blockerCount} gate${blockerCount > 1 ? 's' : ''}` : 'Blocked — resolve gates', {
      whyLine: blockReason || 'Hard gate / oversight BLOCK — resolve before routing',
      primaryKind: 'view_gates',
      primaryLabel: 'View Gates',
      buttonVariant: 'outline-red',
    })
  }

  if (driftPct != null && Math.abs(driftPct) > PROPOSAL_DRIFT_PCT) {
    return act('FIX', 'FIX', 'amber', `Price ${driftPct > 0 ? '+' : '−'}${Math.abs(driftPct).toFixed(0)}% from entry`, {
      whyLine: 'Live price left the proposed entry zone — reprice before approving',
      primaryKind: 'modify',
      primaryLabel: 'Reprice / Modify',
      buttonVariant: 'outline-amber',
    })
  }

  if (oversized) {
    return act('FIX', 'FIX', 'amber', capShares != null ? `Oversized · cap ${Number(capShares).toLocaleString()} sh` : 'Oversized vs policy cap', {
      whyLine: queuedShares != null && capShares != null
        ? `Queued ${Number(queuedShares).toLocaleString()} sh exceeds the ${Number(capShares).toLocaleString()} sh policy cap`
        : 'Queued size exceeds the account policy cap',
      primaryKind: 'modify',
      primaryLabel: 'Modify size',
      buttonVariant: 'outline-amber',
    })
  }

  if (earningsDays != null && earningsDays >= 0 && earningsDays <= 7) {
    return act('CAUTION', 'WAIT', 'amber', `Earnings in ${earningsDays}d`, {
      whyLine: `Event risk — earnings ${earningsLabel || `in ${earningsDays}d`}; size for a gap or wait`,
      primaryKind: 'approve',
      primaryLabel: `Approve (earnings ${earningsDays}d)`,
      buttonVariant: 'outline-amber',
    })
  }

  if (reviewsPendingBits.length) {
    return act('WAIT', 'WAIT', 'none', 'Reviews pending', {
      whyLine: reviewsPendingBits.join(' · '),
      primaryKind: null,
      primaryLabel: '',
      buttonVariant: 'neutral',
    })
  }

  return act('READY', 'READY', 'green', 'Ready — gates green', {
    whyLine: fid ? 'Record-only destination — execute manually, then log the fill' : 'All gates green · routes via Schwab 2FA review',
    primaryKind: 'approve',
    primaryLabel: approveText,
    buttonVariant: 'solid-green',
  })
}

/** Banner chip: R:R per spec — teal ≥2, neutral ≥1.5, amber below. */
export function proposalRrChip(rr: number | null | undefined): { text: string; color: string } | null {
  if (rr == null || !Number.isFinite(Number(rr))) return null
  const v = Number(rr)
  return { text: `${v.toFixed(1)}R`, color: v >= 2 ? '#2dd4bf' : v >= 1.5 ? '#aeb9ca' : '#f5a623' }
}
