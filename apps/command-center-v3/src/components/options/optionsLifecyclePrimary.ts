/** Same order as scripts/lib/options_lifecycle_primary.py. One primary bucket. */
export type Bucket = 'blocked' | 'action_now' | 'harvest' | 'defend' | 'expiry' | 'mature'

const ORDER: Bucket[] = ['blocked', 'action_now', 'harvest', 'defend', 'expiry', 'mature']

export function matchingBuckets(p: any): Bucket[] {
  const rec = String(p?.decision?.recommendation || '')
  const dteRaw = p?.economics?.dte_nearest
  const dte = dteRaw == null || Number.isNaN(Number(dteRaw)) ? 99 : Number(dteRaw)
  const found: Bucket[] = []
  if (rec === 'DATA_BLOCKED') found.push('blocked')
  if (p?.decision?.urgency === 'red') found.push('action_now')
  if (rec.startsWith('HARVEST')) found.push('harvest')
  if (rec === 'DEFEND' || rec === 'ROLL') found.push('defend')
  if (dte <= 7 || rec === 'ACCEPT_ASSIGNMENT' || rec === 'EXERCISE_REVIEW') found.push('expiry')
  if (rec === 'LET_MATURE' || rec === 'HOLD') found.push('mature')
  return found
}

export function primaryBucket(p: any): Bucket {
  const found = matchingBuckets(p)
  for (const key of ORDER) if (found.includes(key)) return key
  return 'mature'
}

export function subordinateBuckets(p: any): Bucket[] {
  const primary = primaryBucket(p)
  return matchingBuckets(p).filter(k => k !== primary)
}
