import JournalVocabPicker from './JournalVocabPicker'
import { EXIT_TYPE_CONFIG } from '../../lib/journalTagVocab'

export default function ExitTypePicker({
  value,
  onChange,
  compact,
}: {
  value: string
  onChange: (v: string) => void
  compact?: boolean
}) {
  return <JournalVocabPicker config={EXIT_TYPE_CONFIG} value={value} onChange={onChange} compact={compact} />
}