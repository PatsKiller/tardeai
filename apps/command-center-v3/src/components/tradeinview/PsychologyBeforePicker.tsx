import JournalVocabPicker from './JournalVocabPicker'
import { PSYCHOLOGY_BEFORE_CONFIG } from '../../lib/psychologyBefore'

export default function PsychologyBeforePicker({
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
      config={PSYCHOLOGY_BEFORE_CONFIG}
      value={value}
      onChange={onChange}
      compact={compact}
    />
  )
}