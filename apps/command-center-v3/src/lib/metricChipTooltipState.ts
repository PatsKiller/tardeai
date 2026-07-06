/** Pure tap/hover phase logic for MetricChipTooltip — testable without React. */

export type MetricChipPhase = 'closed' | 'short' | 'more'

export function metricChipHoverEnter(phase: MetricChipPhase): MetricChipPhase {
  return phase === 'more' ? 'more' : 'short'
}

export function metricChipHoverLeave(phase: MetricChipPhase): MetricChipPhase {
  return phase === 'more' ? 'more' : 'closed'
}

/** Mobile/coarse pointer: closed → short → more → closed. Desktop click from short → more. */
export function metricChipTap(phase: MetricChipPhase, coarsePointer: boolean): MetricChipPhase {
  if (phase === 'closed') return 'short'
  if (phase === 'short') return 'more'
  return 'closed'
}

export function metricChipMoreClick(): MetricChipPhase {
  return 'more'
}