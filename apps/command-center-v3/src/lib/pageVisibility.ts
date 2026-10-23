// Page-visibility helpers for pollers (2026-10-22).
//
// The HealthHub remediation log polled /api/v2/health/remediation every 60 s even from a
// background tab; each call cost the single-process portfolio-server 300–770 MB RSS until the
// server-side fix, and the cgroup watchdog killed it 69 times that day. Pollers that only feed a
// visible panel pause while the document is hidden and refresh once when it becomes visible.

export type VisibilityDoc = {
  visibilityState?: string
  addEventListener(type: 'visibilitychange', cb: () => void): void
  removeEventListener(type: 'visibilitychange', cb: () => void): void
}

/** RemediationDashboard poll interval: 5 minutes (was 60 s). */
export const REMEDIATION_POLL_MS = 300_000

/** True unless the document says it is hidden (no document — SSR/tests — counts as visible). */
export function isPageVisible(doc: { visibilityState?: string } | null | undefined): boolean {
  if (!doc) return true
  return doc.visibilityState !== 'hidden'
}

/** Call `onChange(visible)` whenever visibility flips; returns the unsubscribe function. */
export function subscribePageVisibility(doc: VisibilityDoc | null | undefined, onChange: (visible: boolean) => void): () => void {
  if (!doc) return () => {}
  let last = isPageVisible(doc)
  const handler = () => {
    const now = isPageVisible(doc)
    if (now !== last) { last = now; onChange(now) }
  }
  doc.addEventListener('visibilitychange', handler)
  return () => doc.removeEventListener('visibilitychange', handler)
}
