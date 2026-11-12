// LQ-20261107-2228 (REVIEW-2225 Medium): which banner the Finviz credential-health payload gets.
// A health check that ERRORED (status 'check_failed' or cookie_status 'unknown') is UNKNOWN: the cookie may be fine,
// we could not tell. It must not borrow the red, non-dismissible look of a confirmed expiry, even though the
// server payload carries ok:false for it. A real expiry (or a missing cookie) stays red.
export type FinvizHealth = {
  ok?: boolean
  status?: string
  severity?: string
  cookie_status?: string
  show_banner?: boolean
}

export type FinvizBannerView = {
  show: boolean
  // UNKNOWN: the check errored; not a confirmed expiry
  unknown: boolean
  // red and non-dismissible: a confirmed expiry, a missing cookie or an explicit red severity
  severe: boolean
}

export function isUnknownCheck(h: FinvizHealth | null | undefined): boolean {
  if (!h) return false
  const st = (h.status || '').toLowerCase()
  const cs = (h.cookie_status || '').toLowerCase()
  return st === 'check_failed' || cs === 'unknown'
}

export function shouldShowFinviz(h: FinvizHealth | null | undefined): boolean {
  if (!h) return false
  if (h.show_banner) return true
  if (h.ok === false) return true
  const st = (h.status || '').toLowerCase()
  if (st === 'token_ok') return true // cookie dead even though the token works (LQ-1289)
  return st === 'expired' || st === 'missing' || st === 'error' || st === 'check_failed' || st === 'invalid'
}

export function finvizBannerView(h: FinvizHealth | null | undefined, dismissed: boolean): FinvizBannerView {
  const unknown = isUnknownCheck(h)
  // an errored check never counts as severe, whatever ok / severity say; everything else keeps the old rule
  const severe = !!h && !unknown && (h.severity === 'red' || h.ok === false || h.cookie_status === 'missing')
  const show = shouldShowFinviz(h) && (severe || !dismissed)
  return { show, unknown, severe }
}
