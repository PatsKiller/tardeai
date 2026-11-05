/**
 * Choosing a name on Watch changes the reading view, not the list.
 *
 * `setParam` is the filter setter: it resets `page` to 1 for every key but `page`, because a changed filter invalidates
 * the page you were on. Selection is not a filter. Writing `detail` through that setter (cx-openai-3 R2 at c3ea49812)
 * sent the operator from `page=2` to `page=1&detail=BBB`: the page asked for page 1, the selected name was not in that
 * page's cards, and the reading view fell back to the first card — so Beta was the row clicked and Alpha was what
 * rendered.
 *
 * `withDetail` edits one key and leaves every other part of the query (`page`, `view`, `tab`, filters) untouched.
 */
export function withDetail(sp: URLSearchParams, symbol: string): URLSearchParams {
  const next = new URLSearchParams(sp)
  if (symbol) next.set('detail', symbol)
  else next.delete('detail')
  return next
}
