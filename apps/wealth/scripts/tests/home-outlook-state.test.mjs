import test from 'node:test'
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import Module from 'node:module'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const app=fileURLToPath(new URL('../../',import.meta.url))
const compiled=await build({stdin:{contents:`import React from 'react';import{renderToStaticMarkup}from'react-dom/server';import{MemoryRouter}from'react-router-dom';import{DrawerProvider}from'./src/components/Drawer';import{HomeOutlookPage}from'./src/pages/home/HomeOutlookPage';import{HomeSecondary}from'./src/pages/home/HomeV2Parts';export function inspect(sections){const tree=HomeOutlookPage({sections}),panels=[];function visit(node){if(!node||typeof node!=='object')return;if(node.props?.id)panels.push(node);React.Children.forEach(node.props?.children,visit)}visit(tree);const secondary=[];function inventory(node){if(!node||typeof node!=='object')return;if(node.type===HomeSecondary)secondary.push(node);React.Children.forEach(node.props?.children,inventory)}inventory(tree);const conflict=panels.find(x=>x.props.id==='disagreements');const render=node=>renderToStaticMarkup(<MemoryRouter><DrawerProvider>{node}</DrawerProvider></MemoryRouter>);return{ids:panels.map(x=>x.props.id),html:conflict?render(conflict):null,closed:render(tree),inventories:secondary.map(x=>x.props.title)}}`,resolveDir:app,loader:'tsx'},bundle:true,write:false,platform:'node',format:'cjs',target:'node22',loader:{'.css':'empty'},logLevel:'silent',define:{'process.env.NODE_ENV':'"production"'}})
const module=new Module(path.join(app,'scripts/tests/home-outlook-state-virtual.cjs'))
module.filename=path.join(app,'scripts/tests/home-outlook-state-virtual.cjs')
module.paths=Module._nodeModulePaths(app)
module._compile(compiled.outputFiles[0].text,module.filename)
const {inspect}=module.exports
const base={available:true,rows:[],state:'grey',clock:'2040-01-02T03:04:05Z',source:'Synthetic source'}

for(const [name,section,expected] of [
 ['complete current zero',{...base,complete:true,totalCount:0},false],
 ['incomplete empty',{...base,complete:false},true],
 ['stale historical zero',{...base,complete:true,totalCount:0,emptyState:'stale',verdict:'stale'},true],
 ['failed refresh zero',{...base,complete:true,totalCount:0,readFailed:true},true],
 ['unavailable source',{...base,available:false},true],
 ['populated findings',{...base,rows:[{label:'Synthetic finding'}]},true],
])test(`Outlook conflict inventory: ${name}`,()=>{
 const result=inspect({disagreements:section})
 assert.equal(result.ids.includes('disagreements'),expected)
 if(expected){assert.match(result.html,/Registered conflicts/);assert.match(result.html,/Source evidence/)}
 if(section.readFailed){assert.match(result.html,/Retained observation: zero/);assert.match(result.html,/current population is unknown/);assert.match(result.html,/dateTime="2040-01-02T03:04:05Z"/)}
})

test('absent source stays visible as not served rather than known zero',()=>{
 const result=inspect({})
 assert.match(result.html,/stored projection not served/)
 assert.doesNotMatch(result.html,/complete observed population/)
})
test('a populated contradictory zero declaration does not discard records',()=>{
 const result=inspect({disagreements:{...base,complete:true,totalCount:0,emptyState:'known-zero',rows:[{label:'Synthetic finding retained'}]}})
 assert.match(result.html,/Synthetic finding retained/)
})
test('registry disclosure remains collapsed by default with its accessible control',()=>{
 const result=inspect({disagreements:{...base,rows:[{label:'Synthetic registered conflict'}]}})
 assert.match(result.closed,/Open registered findings/)
 assert.match(result.closed,/aria-expanded="false"/)
 assert.doesNotMatch(result.closed,/Synthetic registered conflict/)
 assert.equal(result.inventories[0],'registered findings · conflicts, policy gates and data quality')
})
test('zero conflicts do not remove gates, quality findings or other registered records',()=>{
 const s={...base,rows:[{label:'Synthetic sibling finding'}]}
 const result=inspect({disagreements:{...base,complete:true,totalCount:0},gates:s,dataQuality:s,otherFindings:s})
 assert.equal(result.ids.includes('disagreements'),false)
 for(const id of ['gates','dataQuality','otherFindings'])assert.equal(result.ids.includes(id),true)
})
