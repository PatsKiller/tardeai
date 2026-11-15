import { useEffect, useState } from 'react'
import { getJson } from '../../../api/client'
import type { Read } from '../../home/homeAdapter'
import { INCOME_PATH, incomeState } from './incomeAdapter'
import { IncomePage } from './IncomePage'
export function IncomeLive() {
 const [read,setRead] = useState<Read>(null)
 useEffect(() => {const ctl=new AbortController();void getJson<unknown>(INCOME_PATH,ctl.signal).then(r=>{if(!ctl.signal.aborted)setRead(r)});return()=>ctl.abort()},[])
 return <IncomePage read={incomeState(read,Date.now())} />
}
