import JobsHealth from '../components/JobsHealth'
import { TOKENS } from '../lib/designTokens'

export default function JobsPage() {
  return <main style={{ padding: 20, background: TOKENS.bg[0], minWidth: 0 }}><JobsHealth /></main>
}
