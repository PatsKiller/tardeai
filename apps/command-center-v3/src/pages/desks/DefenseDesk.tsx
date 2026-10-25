import DeskBoard from '../../components/DeskBoard'

/** Approved board 3. Sector momentum is owned by Watch › Sectors (board 13): linked, not repeated. */
export const DEFENSE_TABS = [
  { id: 'where-to-act', label: 'Where to act' },
  { id: 'your-book', label: 'Your book' },
  { id: 'hedges', label: 'Hedges & short side' },
  { id: 'review-log', label: 'Review log' },
] as const

export default function DefenseDesk() {
  return <DeskBoard desk="defense" testId="defense-desk" title="Defense"
    purpose="How exposed is the book if the market turns — and what hedges are ready?"
    tabs={DEFENSE_TABS} tabAliases={{ act: 'where-to-act', book: 'your-book', 'short-side': 'hedges', review: 'review-log' }}
    classicHref="/defense/classic" />
}
