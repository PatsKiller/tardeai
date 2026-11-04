// Registers the TSX render loader for the page-render tests (see tsxRenderLoader.mjs).
import { register } from 'node:module'
register('./tsxRenderLoader.mjs', import.meta.url)
