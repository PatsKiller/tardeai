import { useEffect, useState } from 'react'
import { getJson } from '../../../api/client'
import { questionPath, questionsState, questionDetailState } from './questionsAdapter'
import { QuestionsPage, QuestionDetailView } from './QuestionsPage'
import type { Read } from '../../home/homeAdapter'
function useQuestionRead(ref?: string) {
 const [read,setRead] = useState<Read>(null)
 useEffect(() => {const ctl=new AbortController();setRead(null);void getJson<unknown>(questionPath(ref),ctl.signal).then(r=>{if(!ctl.signal.aborted)setRead(r)});return()=>ctl.abort()},[ref])
 return read
}
function StoredAnswer({threadRef}:{threadRef:string}) {
 const read=useQuestionRead(threadRef)
 return <QuestionDetailView read={questionDetailState(read,Date.now())} now={Date.now()} />
}
export function QuestionsLive() {
 const read=useQuestionRead()
 return <QuestionsPage read={questionsState(read,Date.now())} detail={ref=><StoredAnswer threadRef={ref}/>} />
}
