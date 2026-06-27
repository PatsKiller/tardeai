import JournalVocabPicker from './JournalVocabPicker'
import { SETUP_FAMILY_CONFIG } from '../../lib/setupFamilies'

export default function SetupFamilyPicker({
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
      config={SETUP_FAMILY_CONFIG}
      value={value}
      onChange={onChange}
      compact={compact}
    />
  )
}