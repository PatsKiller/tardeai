// FQ-071 (/trading D) — on a phone the table headers stack at the top and each row becomes an
// unlabeled run of values, so a reader cannot tell which number is which. The page already has a
// labelled card view; a narrow viewport should start there, and the Table/Cards toggle still lets
// anyone switch back. Measured: the audit's phone capture (390/412 px) was rendered in table view.

export const CARD_VIEW_MAX_WIDTH = 820

export function defaultOpportunityView(width: number | null | undefined): 'table' | 'cards' {
  const w = Number(width)
  return Number.isFinite(w) && w > 0 && w <= CARD_VIEW_MAX_WIDTH ? 'cards' : 'table'
}

export function initialOpportunityView(): 'table' | 'cards' {
  if (typeof window === 'undefined') return 'table'   // server render: the table is the neutral default
  return defaultOpportunityView(window.innerWidth)
}
