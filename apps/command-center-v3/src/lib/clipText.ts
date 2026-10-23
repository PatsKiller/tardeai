/** Clip prose for a one-line preview without cutting a word or a number in half.
 *  Risk → Recovery Watch sliced analyst_summary at 150 chars and showed "above original stop $3"
 *  for a $33.xx stop (site validation 2026-10-22). Full text belongs in the element's title. */
export function clipAtWord(text: unknown, max = 150): string {
  const s = String(text ?? '').replace(/\s+/g, ' ').trim()
  if (s.length <= max) return s
  const cut = s.slice(0, max)
  const sp = cut.lastIndexOf(' ')
  return (sp > max * 0.6 ? cut.slice(0, sp) : cut).replace(/[\s,;:·—-]+$/, '') + '…'
}
