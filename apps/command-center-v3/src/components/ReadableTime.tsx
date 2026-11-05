import type { CSSProperties } from 'react'
import { readableTime } from '../lib/readableTime'

/**
 * The shared <time> renderer: ET display text (house `fmtAsOf`), raw stamp kept in dateTime + title
 * so the exact value is one hover / long-press away. Never prints a raw ISO string.
 */
export default function ReadableTime({ value, timeOnly, fallback = 'time unavailable', style, className, testId }: {
  value: string | null | undefined
  timeOnly?: boolean
  fallback?: string
  style?: CSSProperties
  className?: string
  testId?: string
}) {
  const raw = value == null ? '' : String(value).trim()
  const text = readableTime(raw, { timeOnly }) ?? fallback
  return <time dateTime={raw || undefined} title={raw || undefined} className={className} style={style} data-testid={testId}>{text}</time>
}
