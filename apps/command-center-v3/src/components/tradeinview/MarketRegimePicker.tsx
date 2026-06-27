import JournalVocabPicker from './JournalVocabPicker'
import { MARKET_REGIME_CONFIG } from '../../lib/marketRegimes'

export default function MarketRegimePicker({
  value,
  onChange,
  compact,
}: {
  value: string
  onChange: (v: string) => void
  compact?: boolean
}) {
  return (
    <JournalVocabPicker
      config={MARKET_REGIME_CONFIG}
      value={value}
      onChange={onChange}
      compact={compact}
    />
  )
}