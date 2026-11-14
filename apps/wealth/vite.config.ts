import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'
import path from 'path'
import { execSync } from 'child_process'

// Separate build identity from /v3: app = "wealth", own version, own build-meta.json, own base.
// Identity is read from git at build time; if git is unavailable the sha is null and labelled
// as such. It is never copied from another app's build-meta.
const APP = 'wealth'
const APP_VERSION = '0.1.0'
const BASE = '/wealth/'
const BUILT_AT = new Date().toISOString()
// Approved design reference v02 (lead GO 2026-11-14T2313Z; replaces v01 9bafaac1…, history only).
const DESIGN_REF = 'docs/wealth/design-reference/TradeAI_Wealth_Management_Mockups_v02.html'
const DESIGN_REF_SHA256 = '23f96d84199c5a7cabb3837a7bd94fab87d68eed15d3d5bbfb5d07e6f8dde7aa'

function gitIdentity(): { sha: string | null; dirty: boolean | null; branch: string | null } {
  try {
    const sha = execSync('git rev-parse HEAD', { cwd: __dirname }).toString().trim()
    // Vite writes vite.config.ts.timestamp-*.mjs next to this file while it loads the config, so it is
    // always present when this runs: excluding it is what lets a clean tree read source_dirty:false.
    const dirty = execSync("git status --porcelain -- . ':(exclude)vite.config.ts.timestamp-*'", { cwd: __dirname }).toString().trim().length > 0
    const branch = execSync('git rev-parse --abbrev-ref HEAD', { cwd: __dirname }).toString().trim()
    return { sha, dirty, branch }
  } catch {
    return { sha: null, dirty: null, branch: null }
  }
}
const GIT = gitIdentity()

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'wealth-build-meta',
      closeBundle() {
        const meta = {
          app: APP,
          app_version: APP_VERSION,
          base: BASE,
          source_sha: GIT.sha,
          source_sha_note: GIT.sha ? 'git HEAD of the tree this bundle was built from' : 'git unavailable at build time',
          source_dirty: GIT.dirty,
          branch: GIT.branch,
          built_at: BUILT_AT,
          design_reference_sha256: DESIGN_REF_SHA256,
          design_reference_present_in_tree: fs.existsSync(path.resolve(__dirname, '../..', DESIGN_REF)),
        }
        fs.writeFileSync(path.resolve(__dirname, 'dist/build-meta.json'), JSON.stringify(meta, null, 2))
      },
    },
  ],
  define: {
    __WEALTH_APP_VERSION__: JSON.stringify(APP_VERSION),
    __WEALTH_SOURCE_SHA__: JSON.stringify(GIT.sha),
    __WEALTH_BUILT_AT__: JSON.stringify(BUILT_AT),
  },
  base: BASE,
  build: { outDir: 'dist', emptyOutDir: true },
  server: {
    port: 7790,
    host: '127.0.0.1',
    proxy: { '/api': 'http://127.0.0.1:7777' },
  },
})
