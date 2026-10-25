import { SYSTEM_TABS, systemTab, systemTabParams } from './systemTabModel.ts'
function equal(actual: unknown, expected: unknown) { if (actual !== expected) throw new Error(`${String(actual)} != ${String(expected)}`) }
for (const tab of SYSTEM_TABS) {
  equal(systemTab(new URLSearchParams({ tab: tab.toLowerCase() })), tab)
  equal(systemTab(new URLSearchParams({ tab: ` ${tab.toUpperCase()} ` })), tab)
}
equal(systemTab(new URLSearchParams()), 'Pipeline')
equal(systemTab(new URLSearchParams({ tab: 'missing-tab' })), 'Pipeline')
const incoming = new URLSearchParams('tab=llm&query=fixture+job&focus=youtube-cookies&source=report')
const next = systemTabParams(incoming, 'Data Sources')
equal(systemTab(next), 'Data Sources')
equal(next.get('query'), 'fixture job'); equal(next.get('focus'), 'youtube-cookies'); equal(next.get('source'), 'report')
equal(incoming.get('tab'), 'llm')
equal(systemTabParams(next, 'LLM').get('tab'), 'LLM')
console.log('systemTabModel: all tab names, URL context preservation and fallback passed')
