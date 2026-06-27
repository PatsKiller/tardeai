import JournalVocabPicker from './JournalVocabPicker'
import { INDUSTRY_CONFIG } from '../../lib/journalTagVocab'

export default function IndustryPicker({
  value,
  onChange,
  compact,
}: {
  value: string
  onChange: (v: string) => void
  compact?: boolean
}) {
  return <JournalVocabPicker config={INDUSTRY_CONFIG} value={value} onChange={onChange} compact={compact} />
}