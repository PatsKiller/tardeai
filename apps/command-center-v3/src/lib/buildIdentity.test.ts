import { compareServedBuild, LOADED_BUILD, type LoadedBuild } from './buildIdentity.ts'
const assert = {
  equal(a: unknown, b: unknown) { if (a !== b) throw new Error(`${String(a)} !== ${String(b)}`) },
  ok(value: unknown) { if (!value) throw new Error('expected truthy value') },
}

const sha = 'a'.repeat(40)
const loaded: LoadedBuild = Object.freeze({ uiVersion: '3.14+loaded', sourceSha: sha, builtAt: '2026-10-18' })
const metadata = { ui_version: loaded.uiVersion, git_sha: sha, source_commit: sha }
assert.equal(compareServedBuild(loaded, metadata), 'SAME')
assert.equal(compareServedBuild(loaded, { ...metadata, ui_version: '3.14+next' }), 'DIFFERENT')
assert.equal(compareServedBuild(loaded, { ...metadata, git_sha: 'b'.repeat(40), source_commit: 'b'.repeat(40) }), 'DIFFERENT')
assert.equal(loaded.sourceSha, sha)
assert.equal(loaded.uiVersion, '3.14+loaded')
assert.equal(compareServedBuild(loaded, { ...metadata, source_commit: 'b'.repeat(40) }), 'UNAVAILABLE')
assert.equal(compareServedBuild(loaded, { ...metadata, git_sha: 'short' }), 'UNAVAILABLE')
assert.equal(compareServedBuild(loaded, null), 'UNAVAILABLE')
assert.equal(compareServedBuild({ ...loaded, sourceSha: null }, metadata), 'UNAVAILABLE')
assert.ok(Object.isFrozen(LOADED_BUILD))
// Outside a Vite build, unknown compiled identity remains unknown.
assert.equal(LOADED_BUILD.sourceSha, null)
console.log('buildIdentity: loaded/served identities remain distinct; malformed/missing metadata is unavailable')
