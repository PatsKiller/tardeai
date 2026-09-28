/** The shared primitives (PR2, 2026-09-27). Pages and cards import from here; the legacy
 *  cardPrimitives (VerdictBanner, LadderLine, TrustLine, AgeChip) are re-exported and will be
 *  re-skinned on tokens as their cards convert. */
export { Tooltip, MetricGuide, MetricGuideBody } from './Tooltip'
export { Chip, ChipRow } from './Chip'
export { Metric, MetricRow } from './Metric'
export { Sparkline, TrendIndicator, Legend } from './Charts'
export type { Trend } from './Charts'
export { Collapsible, Accordion, ShowMore, Drawer } from './Collapsible'
export { InsightLine, TakeawayBanner } from './Insight'
export type { Insight } from './Insight'
export { TickerHeader } from './TickerHeader'
export type { TickerIdentity, StatusChip, Sentiment } from './TickerHeader'
export { SortHeader } from './SortHeader'
export { VerdictBanner, LadderLine, TrustLine, AgeChip } from './cardPrimitives'
export { useSort, sortRows, compareValues, nextSort } from '../../lib/tableSort'
export type { SortState, SortDir } from '../../lib/tableSort'
export { registerGuide, getGuide, useMetricGuide, fillGuide, loadGuideOnce } from '../../lib/metricGuide'
export type { MetricGuideEntry, MetricGuideKey } from '../../lib/metricGuide'
