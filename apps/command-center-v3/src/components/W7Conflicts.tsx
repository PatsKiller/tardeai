import ConflictLine from './conflicts/ConflictLine'
import ConflictSheet, { useConflictSheet } from './conflicts/ConflictSheet'

/** The accepted shared UI owns selection, its detail GET and all finding display. */
export default function W7Conflicts({ section, title = 'CIO findings' }: { section: any, title?: string }) {
  const sheet = useConflictSheet()
  return <>
    <ConflictLine section={section} onOpen={sheet.open} />
    {sheet.key && <ConflictSheet title={title} section={section} mobile={sheet.mobile} onBack={sheet.close} />}
  </>
}
