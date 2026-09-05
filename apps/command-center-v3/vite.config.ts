import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'
import path from 'path'
import { execSync } from 'child_process'

// 3.14 = MetricStrip STALE parity + unprotected taxonomy + Operator Inbox plain language
const UI_VERSION = '3.14'
// Single stamp per build — must match build-meta.json or AnalystReportsPanel false-positives "stale".
const BUILD_STAMP = Date.now().toString(36)
const FULL_UI_VERSION = `${UI_VERSION}+${BUILD_STAMP}`

// Build identity must come from the exact served artifact (cc-header-truth-v2
// Phase 2 G): the commit this tree is built from, never a hardcoded date or a
// claim that unserved code is live. Read HEAD at build time; fall back to the
// If git is unavailable the SHAs are written as null and labelled as such (see the
// else-branch below) — the checked-in build-meta.json is NEVER read. This comment
// previously claimed it was a fallback source, which is why that file was believed
// load-bearing at build time. It is not: it is output, not input.
function resolveGitIdentity() {
  try {
    const sha = execSync('git rev-parse HEAD', { encoding: 'utf8' }).trim()
    const branch = execSync('git rev-parse --abbrev-ref HEAD', { encoding: 'utf8' }).trim()
    return { sha, branch, short: sha.slice(0, 12) }
  } catch {
    return null
  }
}
const GIT_IDENTITY = resolveGitIdentity()

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'build-meta',
      closeBundle() {
        // ui_version drives the server's forced client-reload (portfolio_server injects a check
        // vs sessionStorage). It MUST change every build or browsers never auto-pick-up a new
        // bundle — append a per-build stamp so every deploy triggers a one-time reload.
        const meta: Record<string, unknown> = {
          ui_version: FULL_UI_VERSION,
          base_version: UI_VERSION,
          built_at: new Date().toISOString(),
          release_notes: 'cc-header-truth-v2: source-explicit header provenance, setup-run population, per-field freshness, served build identity',
        }
        if (GIT_IDENTITY) {
          meta.git_sha = GIT_IDENTITY.sha
          meta.build_sha = GIT_IDENTITY.short
          meta.source_sha = GIT_IDENTITY.sha
          meta.source_commit = GIT_IDENTITY.sha
          meta.branch = GIT_IDENTITY.branch
        } else {
          // Never fabricate a commit identity. If git is unavailable the served
          // artifact cannot truthfully claim a SHA, so it says so explicitly.
          meta.git_sha = null
          meta.build_sha = null
          meta.source_sha = null
          meta.source_commit = null
          meta.branch = null
        }
        fs.writeFileSync(
          path.resolve(__dirname, 'dist/build-meta.json'),
          JSON.stringify(meta, null, 2),
        )
      },
    },
  ],
  define: {
    __ANALYST_UI_VERSION__: JSON.stringify(FULL_UI_VERSION),
    __BUILD_DATE__: JSON.stringify(new Date().toISOString().slice(0, 10)),
  },
  base: '/v3/',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    port: 7789,
    host: '0.0.0.0',
    proxy: {
      '/api': 'http://127.0.0.1:7777',
    },
  },
})
