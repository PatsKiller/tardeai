import JournalVocabPicker from './JournalVocabPicker'
import { TRADE_PLAN_CONFIG } from '../../lib/journalTagVocab'

export default function TradePlanPicker({
  value,
  onChange,
  compact,
}: {
  value: string
  onChange: (v: string) => void
  compact?: boolean
}) {
  return <JournalVocabPicker config={TRADE_PLAN_CONFIG} value={value} onChange={onChange} compact={compact} />
}