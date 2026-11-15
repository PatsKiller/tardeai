import { useEffect, useState } from 'react'
import { getJson } from '../../../api/client'
import { questionPath, questionsState, questionDetailState } from './questionsAdapter'
import { Note } from '../../../components/primitives'
import { QuestionsPage, QuestionDetailView } from './QuestionsPage'
import type { Read } from '../../home/homeAdapter'
function useQuestionRead(ref?: string) {
 const [read,setRead] = useState<Read>(null), path=questionPath(ref)
 useEffect(() => {const ctl=new AbortController();setRead(null);if(path!==null)void getJson<unknown>(path,ctl.signal).then(r=>{if(!ctl.signal.aborted)setRead(r)});return()=>ctl.abort()},[path])
 return {read,invalidRef:path===null}
}
function StoredAnswer({threadRef}:{threadRef:string}) {
 const {read,invalidRef}=useQuestionRead(threadRef)
 if(invalidRef)return <Note>Stored thread reference unavailable. No request was sent.</Note>
 return <QuestionDetailView read={questionDetailState(read,Date.now())} now={Date.now()} />
}
export function QuestionsLive() {
 const {read}=useQuestionRead()
 return <QuestionsPage read={questionsState(read,Date.now())} detail={ref=><StoredAnswer threadRef={ref}/>} />
}
