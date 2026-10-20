// These values are replaced by Vite in the bundle being executed, never by a
// fetch of metadata from a different, currently served artifact.
declare const __ANALYST_UI_VERSION__: string
declare const __BUILD_DATE__: string
declare const __CC_BUNDLE_SOURCE_SHA__: string | null

export type LoadedBuild = Readonly<{ uiVersion: string | null; sourceSha: string | null; builtAt: string | null }>
const fullSha = (value: unknown): value is string => typeof value === 'string' && /^[0-9a-f]{40}$/.test(value)
export const LOADED_BUILD: LoadedBuild = Object.freeze({
  uiVersion: typeof __ANALYST_UI_VERSION__ === 'string' ? __ANALYST_UI_VERSION__ : null,
  sourceSha: typeof __CC_BUNDLE_SOURCE_SHA__ === 'string' && fullSha(__CC_BUNDLE_SOURCE_SHA__) ? __CC_BUNDLE_SOURCE_SHA__ : null,
  builtAt: typeof __BUILD_DATE__ === 'string' ? __BUILD_DATE__ : null,
})

export function compareServedBuild(loaded: LoadedBuild, metadata: unknown): 'SAME' | 'DIFFERENT' | 'UNAVAILABLE' {
  if (!metadata || typeof metadata !== 'object' || Array.isArray(metadata) || !loaded.uiVersion || !fullSha(loaded.sourceSha)) return 'UNAVAILABLE'
  const m = metadata as Record<string, unknown>
  if (typeof m.ui_version !== 'string' || !m.ui_version || !fullSha(m.git_sha)) return 'UNAVAILABLE'
  for (const alias of ['source_commit', 'source_sha']) {
    if (m[alias] != null && m[alias] !== m.git_sha) return 'UNAVAILABLE'
  }
  return m.ui_version === loaded.uiVersion && m.git_sha === loaded.sourceSha ? 'SAME' : 'DIFFERENT'
}
