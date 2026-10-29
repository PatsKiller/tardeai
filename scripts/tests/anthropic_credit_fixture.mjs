// Synthetic, no-server component proof. All network is blocked.
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs/promises'
import assert from 'node:assert/strict'
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..')
const app=path.join(root,'apps/command-center-v3')
const require=createRequire(path.join(app,'package.json'))
const {build}=require('esbuild'),{chromium}=require('@playwright/test')
const packet=path.resolve(process.env.ANTHROPIC_FIXTURE_OUTPUT ?? path.join(os.homedir(),'.local/state/tradeai/validation/anthropic-first-20261025'))
const relativeOutput=path.relative(root,packet)
assert(relativeOutput.startsWith('..'+path.sep)||path.isAbsolute(relativeOutput),'Fixture screenshots require a PRIVATE output directory outside the repository')
await fs.mkdir(packet,{recursive:true,mode:0o700})
const status={status:'PAUSED_TODAY',as_of:'2026-10-25T18:00:00Z',routing_order:['grok','chatgpt','deepseek'],credit:{credit_used_usd:'21.25',reserved_usd:'0.1',estimated_credit_remaining_usd:'178.65',daily_cap_usd:'10',today_used_usd:'10',days_to_expiry:21},usage:{today:{calls:25,usd:10,error_rate:0.04},seven_days:{calls:53,usd:21.25,error_rate:0.02}},models:{'claude-haiku-5-5':{calls:53,usd:21.25}},models_by_period:{today:{'claude-haiku-5-5':{calls:25,usd:10}},seven_days:{'claude-haiku-5-5':{calls:53,usd:21.25}}},fallback_reasons:{PAUSED_TODAY:2,RATE_LIMITED:1},last_success_at:'2026-10-25T17:59:00Z',last_error:{code:'RATE_LIMITED',at:'2026-10-25T17:58:00Z'},last_fallback_reason:'PAUSED_TODAY',fallback_count:3,ledger_coverage:'COMPLETE_FILE',note:'Synthetic fixture. Remaining organization credit is estimated.'}
const bundle=await build({stdin:{contents:`import React from 'react';import{createRoot}from'react-dom/client';import Panel from './src/components/AnthropicCreditPanel';createRoot(document.getElementById('root')).render(<Panel status={${JSON.stringify(status)}}/>);`,resolveDir:app,loader:'tsx'},bundle:true,write:false,format:'iife',jsx:'automatic',define:{'process.env.NODE_ENV':'"production"'}})
const browser=await chromium.launch({headless:true})
try{
 for(const width of [412,390]){
  const page=await browser.newPage({viewport:{width,height:900},isMobile:true,hasTouch:true})
  await page.route('**/*',r=>r.abort())
  await page.setContent(`<html><head><meta name="viewport" content="width=device-width, initial-scale=1"><style>:root{--bg-0:#0c111b;--bg-1:#141c29;--text-0:#f4f6fa;--text-1:#d4dbea;--text-2:#a8b6ce;--warning-color:#f6c76a;--success-color:#85dea7;--border-color:#48566b;--radius-md:8px;--radius-sm:6px;--font-mono:monospace}*{box-sizing:border-box}body{margin:0;padding:12px;background:var(--bg-0);font-family:Arial,sans-serif}</style></head><body><div id="root"></div></body></html>`)
  await page.addScriptTag({content:bundle.outputFiles[0].text})
  const button=page.locator('button[aria-controls="anthropic-credit-details"]');await button.waitFor()
  assert((await button.boundingBox()).height>=43.9)
  await button.tap();await page.getByText('Trailing 7 days:',{exact:false}).waitFor()
  assert.equal(await button.getAttribute('aria-expanded'),'true')
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth))
  assert.equal(await page.getByText('PAUSED_TODAY: 2',{exact:true}).count(),1)
  assert.equal(await page.getByText('Today (UTC) model usage',{exact:true}).count(),1)
  assert.equal(await page.getByText('Trailing 7-day model usage',{exact:true}).count(),1)
  assert(!(await page.locator('body').innerText()).includes('$—'))
  assert((await page.locator('body').innerText()).includes('ET'))
  await page.screenshot({path:path.join(packet,`impl-anthropic-${width}.png`),fullPage:true})
  await button.tap()
  assert.equal(await page.locator('#anthropic-credit-details').count(),0);await page.close()
 }
 await fs.writeFile(path.join(packet,'phone-fixture-proof.json'),JSON.stringify({viewports:[412,390],tapFlows:['expand','collapse'],horizontalOverflow:false,source:'synthetic component; no network'},null,2)+'\n')
 console.log('412/390 synthetic tap flows and screenshots passed')
}finally{await browser.close()}
