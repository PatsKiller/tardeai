import { useApi } from '../../hooks/useApi'
import { LOADED_BUILD, compareServedBuild } from '../../lib/buildIdentity'
import { TOKENS, TYPE, RADIUS, chipStyle } from '../../lib/designTokens'

/** Keep the loaded identity distinct from a later served artifact; never auto-reload. */
export default function WatchReloadNotice() {
  const { data } = useApi<unknown>('/v3/build-meta.json', 60_000)
  const comparison = compareServedBuild(LOADED_BUILD, data)
  if (comparison !== 'DIFFERENT') return null
  return <div role="status" data-testid="watch-reload-notice" style={{ padding: 12, background: TOKENS.bg[2],
    border: `1px solid ${TOKENS.warning}`, borderRadius: RADIUS.md, color: TOKENS.text[0], fontSize: TYPE.base,
    display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12 }}>
    <span>Command Center was updated. Reload to use the current page.</span>
    <button type="button" onClick={() => window.location.reload()} style={{ ...chipStyle('warning', 'outline', 'md'),
      minHeight: 44, minWidth: 44, cursor: 'pointer', whiteSpace: 'normal' }}>Reload Command Center</button>
  </div>
}
