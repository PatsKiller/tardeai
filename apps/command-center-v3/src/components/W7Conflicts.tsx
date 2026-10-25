import ConflictLine from './conflicts/ConflictLine'
import ConflictSheet, { useConflictSheet, type ConflictSection } from './conflicts/ConflictSheet'

/** The accepted shared UI owns selection, its detail GET and all finding display.
 *  A page document without a conflicts section is an explicit gap, never a crash or "no conflicts". */
export default function W7Conflicts({ section, title = 'CIO findings' }: { section: any, title?: string }) {
  const sheet = useConflictSheet()
  const supplied: ConflictSection = section && typeof section === 'object' && Array.isArray(section.findings)
    ? section
    : { findings: [], headline: null, gap: { reason: 'conflict section not supplied with this page' } }
  return <>
    <ConflictLine section={supplied} onOpen={sheet.open} />
    {sheet.key && <ConflictSheet title={title} section={supplied} mobile={sheet.mobile} onBack={sheet.close} />}
  </>
}
