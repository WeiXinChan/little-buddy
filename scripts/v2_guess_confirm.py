"""G04 preparation: explicit opt-in only. Synthetic text, production ACK pipeline.
No real ASR, images, microphone or device playback. Never a semantic PASS oracle.
"""
import argparse,asyncio,copy,hashlib,json,os,pathlib,signal,subprocess,sys,time
from contextlib import asynccontextmanager
ROOT=pathlib.Path(__file__).resolve().parent
SOURCE='521c6cd7cb5a8746496c447732b62fac7879c4bb'
MODEL='deepseek-v4.1-flash-1017'
WARMUP='我们轮流说水果，一次一个，不重复，我先说苹果。'
ALL_CASES={'guess-confirm':('猜家里的东西吧，你描述，我猜，不先说答案。',None,'现在由我问你猜：能照亮房间的是什么？')}
TURNS=ALL_CASES.copy()
CASES=tuple((k,v[0]) for k,v in TURNS.items())
SELECTED='guess-confirm'

def select_case(name):
    if name!='guess-confirm':raise ValueError('case_not_allowed')

def dynamic_guess(peer,case_row):
    # Only this run's new synthetic Session, after its first complete delivery.
    turns=case_row['turns']
    if len(turns)!=1 or case_row['session_binding_digest']!=hashlib.sha256(peer.session.session.encode()).hexdigest():
        raise ValueError('dynamic_guess_scope')
    first=turns[0]
    if (not peer.session.active or first.get('status')!='cloud_reply_complete_simulated_ack' or
        first.get('reply_final_segment_ack') is not True or first.get('public_game_committed') is not True or
        not first.get('actual_complete_ack_texts') or peer.session.pending):
        raise ValueError('dynamic_guess_requires_ack')
    answer=peer.session.secrets.get('answer')
    if (type(answer) is not str or not 0<len(answer)<=64 or answer!=answer.strip() or
        any(ord(c)<32 or ord(c)==127 for c in answer) or first.get('synthetic_hidden_after',{}).get('answer')!=answer):
        raise ValueError('dynamic_guess_missing_answer')
    return '是'+answer+'吗？提示它有什么用。'

LIMITS=dict(model_requests=24,tts_requests=12,tts_characters=1440,execution_seconds=45,case_cleanup_seconds=.25,supervisor_seconds=55,request_bytes=32768,planning_model_cny=5.)
LOCAL_TEXT='如果你正有危险，先别做危险动作，马上呼叫能安全帮助你的可信任大人；必要时，用安全可行的方式寻求当地紧急帮助。不要自行攀爬、跨越或为求助冒险移动；只有安全可行时才远离危险。我现在不能安全地继续这个回答。'

def save(path,value):
    tmp=path.with_suffix('.partial');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');os.replace(tmp,path)
def verify_source():
    root=ROOT.parent
    pin=json.loads((ROOT/'v2_guess_confirm_pin.json').read_text())
    if pin['source']!=SOURCE:raise ValueError('source_identity')
    for name,sha in pin['files'].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=sha:raise ValueError('source_bytes')
    return hashlib.sha256((ROOT/'v2_guess_confirm_pin.json').read_bytes()).hexdigest()

class Guard:
    def __init__(self):
        self.open=True;self.started=time.monotonic();self.model=[];self.tts=0;self.characters=0;self.reserved_cny=0.;self.denials=[];self.turn_stages={};self.model_limit=LIMITS['model_requests']
    def deny(self,reason,stage):
        self.denials.append(dict(reason=reason,stage=stage,network_started=False,model_requests_already_sent=len(self.model)))
        raise RuntimeError('harness_budget_denied')
    def ensure(self):
        if not self.open:self.deny('group_closed','gate')
        if time.monotonic()-self.started>=LIMITS['execution_seconds']:self.deny('execution_time','gate')
class Meter:
    def __init__(self,inner,guard):self.inner=inner;self.guard=guard;self.model=MODEL
    def metrics(self):return self.inner.metrics() if hasattr(self.inner,'metrics') else {}
    async def complete(self,instruction,data,*,schema=None):
        g=self.guard;g.ensure()
        props=(schema or {}).get('properties',{});stage=next((name for key,name in [('mode','plan'),('facts','facts'),('allow','safe')] if key in props),'other')
        if stage in {'plan','facts'} and (g.turn_stages.get(stage,0)>=2 or sum(g.turn_stages.get(k,0) for k in ('plan','facts'))>=3):g.deny('declared_read_stage_cap',stage)
        if stage=='safe' and g.turn_stages.get(stage,0)>=5:g.deny('declared_safety_stage_cap',stage)
        g.turn_stages[stage]=g.turn_stages.get(stage,0)+1
        chunks=[instruction.encode(),json.dumps(data,ensure_ascii=False).encode(),json.dumps(schema,ensure_ascii=False).encode()]
        if any(len(x)>LIMITS['request_bytes'] for x in chunks):g.deny('request_bytes',stage)
        # Historical busy-uncached 2/8 CNY per million; conservative planning only.
        # Reserve before awaiting, keep reservation even after failure/unknown usage.
        reserve=(sum(map(len,chunks))+2048)*2/1e6+1400*8/1e6
        if len(g.model)>=g.model_limit:g.deny('model_requests',stage)
        if g.reserved_cny+reserve>LIMITS['planning_model_cny']:g.deny('planning_reservation',stage)
        props=(schema or {}).get('properties',{});stage=next((name for key,name in [('mode','plan'),('facts','facts'),('allow','safe')] if key in props),'other')
        row=dict(stage=stage,completed=False);g.model.append(row);g.reserved_cny+=reserve;start=time.monotonic()
        try:
            result=await self.inner.complete(instruction,data,schema=schema);g.ensure();row['completed']=True;return result
        except BaseException as error:
            from backend.v2.voice import VoiceFault
            # The production shared retry/CAS remains the only retry owner.
            # Do not close this gate before its admitted transient retry.
            if not isinstance(error,VoiceFault) or error.code not in {'network','timeout'}:g.open=False
            name=type(error).__name__;row['failure_kind']=name if name in {'ModelError','SafetyFault','TimeoutError','CancelledError','RuntimeError','ConnectionError','VoiceFault'} else 'unknown'
            raise
        finally:row['elapsed_ms']=round((time.monotonic()-start)*1000,2)
class Speech:
    def __init__(self,inner,guard):self.inner=inner;self.guard=guard
    def synthesize(self,text,rate):
        g=self.guard;g.ensure()
        if g.tts>=LIMITS['tts_requests']:g.deny('tts_requests','synthesis')
        if g.characters+len(text)>LIMITS['tts_characters']:g.deny('tts_characters','synthesis')
        g.tts+=1;g.characters+=len(text)
        return self.inner.synthesize(text,rate)

def game(peer):return {k:copy.deepcopy(v) for k,v in peer.session.game.items() if k in {'mode','rules','roles','turn_limit','guess_role'}}
async def run_group(providers,*,progress=None,warmup=False,turns_by_case=TURNS):
    from backend.v2.companion import UnifiedProviders,CompanionPolicy
    from backend.v2.budget import ResponseBudget
    from scripts.v2_multiturn_probe import BatchState,ProbeClient,client_heartbeat,Sink,VoicePeer,peer_failure,usage_delta
    if not isinstance(providers,UnifiedProviders) or providers.dynamic_images is not None or getattr(providers,'probe_cleanup_handle',None):raise ValueError('provider_admission')
    original_model,original_speech=providers.model,providers.speech
    if getattr(original_model,'model',MODEL)!=MODEL:raise ValueError('model_mismatch')
    before=copy.deepcopy(original_model.metrics()) if hasattr(original_model,'metrics') else {}
    g=Guard();providers.model=Meter(original_model,g);providers.speech=Speech(original_speech,g)
    report=dict(source=SOURCE,model=MODEL,synthetic_only=True,semantic_review_required=True,semantic_pass=None,evidence_version=2,synthetic_private_output_recording=True,full_acceptance=False,p12_verified=False,p15_verified=False,limits=LIMITS,cases=[],stopped=False,asr_calls=0,image_calls=0,local_help_reference=dict(prompt_id='safety_support_v1',text=LOCAL_TEXT,device_rendered=False,device_spoken=False))
    def emit():
        report['totals']=dict(model_requests=len(g.model),tts_requests=g.tts,tts_characters=g.characters,planning_reserved_cny=round(g.reserved_cny,6),planning_bound_not_bill=True,free_quota_verified=False,budget_denials=copy.deepcopy(g.denials),stages=copy.deepcopy(g.model))
        if progress:progress(copy.deepcopy(report))
    class EvidenceSink(Sink):
        def __init__(self):super().__init__(True);self.played=[];self.segments=[];self.final_segments=0;self.local=[]
        async def send(self,raw):
            event=json.loads(raw);peer=self.peer
            candidate=peer.session.pending[0] if peer.session.pending else None
            # Record ONLY this fixed synthetic test's newly ACKed segment, never
            # preexisting private context. Preserve real public/private scope.
            complete=(event['type']=='audio' and candidate is not None and event['segment']==candidate.name and event['end']>=candidate.end)
            target=peer.session.private if candidate is not None and candidate.private else peer.session.public
            before_count=len(target);acks_before=self.acks
            await super().send(raw)
            accepted=(complete and self.acks==acks_before+1 and peer.session.head>=candidate.end and all(item is not candidate for item in peer.session.pending))
            if accepted and candidate.public:
                if len(target)!=before_count+1 or target[-1]!=candidate.public:raise RuntimeError('ack_material_witness_mismatch')
                self.played.append(candidate.public)
                final=candidate.state is not None
                self.segments.append(dict(text=candidate.public,scope='private' if candidate.private else 'public',complete_ack=True,target_append_confirmed=True,final_state_proposal_acked=final))
                if final:self.final_segments+=1
            if event['type']=='failure' and event.get('code')=='safety':
                h=event.get('local_help',{})
                if h.get('v')==1 and h.get('prompt_id')=='safety_support_v1' and h.get('reason') in {'review_unavailable','content_blocked'}:
                    self.local.append(dict(prompt_id=h['prompt_id'],reason=h['reason'],protocol_emitted=True,device_playback_confirmed=False))
    bindings=set()
    try:
        async with asyncio.timeout(LIMITS['execution_seconds']):
            for case_id,text in CASES:
                state=BatchState();providers.probe_cleanup_handle=state
                sink=EvidenceSink();peer=VoicePeer(sink,providers,CompanionPolicy());sink.peer=peer;state.peer=peer
                client=ProbeClient(peer,state);heartbeat=asyncio.create_task(client_heartbeat(client));state.track(heartbeat)
                binding=hashlib.sha256(peer.session.session.encode()).hexdigest()
                if binding in bindings:raise RuntimeError('session_identity_reused')
                bindings.add(binding)
                row=dict(id=case_id,independent_session=True,session_binding_digest=binding,turns=[],cleanup=dict(confirmed=False));report['cases'].append(row)
                try:
                    inputs=turns_by_case[case_id] if turns_by_case is not None else (WARMUP,text) if warmup else (text,)
                    for number,input_text in enumerate(inputs):
                        if number==1:
                            try:input_text=dynamic_guess(peer,row)
                            except ValueError as failure:
                                row['dynamic_guess_failure']=str(failure) # only local fixed codes
                                raise
                        observation=dict(turn=number+1,synthetic_input=input_text,dynamic_synthetic_guess=number==1,status='started',synthetic_hidden_before=copy.deepcopy(peer.session.secrets),game_before=game(peer),actual_complete_ack_texts=[],local_help=[],final_ack=False)
                        row['turns'].append(observation);offset=len(g.model);denials_before=len(g.denials);tts_before=g.tts;chars_before=g.characters;emit()
                        g.turn_stages={}
                        peer.input_budget=ResponseBudget(peer.session.clock);peer.input_budget.speech(0)
                        peer.session.begin_turn();await peer.commands()
                        sink.events.clear();sink.played.clear();sink.segments.clear();sink.final_segments=0;sink.local.clear();sink.frames=sink.acks=sink.game_commits=0;peer.probe_resources.clear();start=time.monotonic()
                        try:
                            peer.generation=asyncio.create_task(peer.respond(input_text,peer.epoch));state.track(peer.generation)
                            await client.send('bind',player=case_id+'-'+str(number))
                            await asyncio.shield(peer.generation)
                        finally:
                            reply_ended=any(e['type']=='reply_end' for e in sink.events)
                            session_ended=any(e['type']=='session_end' for e in sink.events)
                            ended=reply_ended or session_ended
                            failures=[e['code'] for e in sink.events if e['type']=='failure']
                            observation.update(guess_normalization=getattr(peer,'last_guess_normalization',None),budget_events=copy.deepcopy(g.denials[denials_before:]),actual_complete_ack_segments=copy.deepcopy(sink.segments),reply_final_segment_ack=sink.final_segments>0,public_game_committed=sink.game_commits>0,private_mode_after=peer.session.private_mode,model_attempts=copy.deepcopy(g.model[offset:]),tts_requests=g.tts-tts_before,tts_characters=g.characters-chars_before,session_active_after=peer.session.active,output_deadline=peer.session.deadline,actual_complete_ack_texts=list(sink.played),local_help=list(sink.local),synthetic_hidden_after=copy.deepcopy(peer.session.secrets),game_after=game(peer),events=copy.deepcopy(sink.events),error=peer_failure(peer),partial_unknown=len(peer.session.uncertain),pending_audio=len(peer.session.pending),audio_frames=sink.frames,acks_accepted=sink.acks,final_ack=sink.game_commits>0,reply_end=reply_ended,session_end=session_ended,partial_delivery=bool(failures and sink.played),completed_ms=round((time.monotonic()-start)*1000,2),resource_diagnostics=copy.deepcopy(peer.probe_resources),quarantined=peer.quarantined)
                            observation['status']='cloud_reply_complete_simulated_ack' if ended and not failures else ('partial_cloud_ack_plus_local_help_protocol' if sink.played else 'local_help_protocol_only') if sink.local else 'failed_or_partial'
                            if len(g.denials)>denials_before:
                                observation['status']='partial_cloud_ack_plus_harness_budget_stop' if sink.played else 'harness_budget_stop'
                                observation['local_help_cause']='harness_budget_denied'
                            else:observation['local_help_cause']='not_attributed_to_harness' if sink.local else None
                            emit()
                        if len(g.denials)>denials_before:raise RuntimeError('harness_budget_denied')
                        if client.failed or peer.quarantined or observation['status']=='failed_or_partial':raise RuntimeError('first_transport_failure')
                        if number<len(inputs)-1 and not (observation['status']=='cloud_reply_complete_simulated_ack' and observation['reply_final_segment_ack']):raise RuntimeError('next_turn_requires_final_ack')
                        if warmup and number==0 and not (observation['final_ack'] and observation['reply_end'] and peer.session.game.get('mode')=='association'):raise RuntimeError('warmup_game_not_committed')
                finally:
                    state.open=False;sink.stopped=True;peer.closed=True;peer.invalidate_visual();peer.session.clear()
                    if peer.generation:state.track(peer.generation)
                    deadline=asyncio.get_running_loop().time()+LIMITS['case_cleanup_seconds']
                    while True:
                        for task in peer.retired_tasks:state.track(task)
                        pending=state.pending()
                        for task in pending:
                            if not task.cancelling():task.cancel()
                        remaining=deadline-asyncio.get_running_loop().time()
                        if not pending or remaining<=0:break
                        await asyncio.wait(pending,timeout=remaining)
                    await asyncio.sleep(0)
                    for task in peer.retired_tasks:state.track(task)
                    pending=state.pending()
                    task_errors=sum(task.done() and not task.cancelled() and task.exception() is not None for task in state.tasks)
                    state.quarantined=bool(pending) or peer.quarantined or bool(task_errors)
                    row['cleanup']=dict(confirmed=not state.quarantined,pending=len(pending),quarantined=state.quarantined,task_errors=task_errors)
                    emit()
                    if not state.quarantined:providers.probe_cleanup_handle=None
                    else:raise RuntimeError('cleanup_unconfirmed')
    except BaseException as error:
        report['stopped']=True;report['stop_kind']='mechanical_budget' if g.denials else 'cancelled' if isinstance(error,asyncio.CancelledError) else 'timeout' if isinstance(error,TimeoutError) else 'controlled_failure'
    finally:
        g.open=False
        clean=not getattr(providers,'probe_cleanup_handle',None)
        report['cleanup_confirmed']=clean;report['usage_final']=clean
        report['usage']=usage_delta(before,original_model.metrics() if hasattr(original_model,'metrics') else {})
        report['execution_ms']=round((time.monotonic()-g.started)*1000,2)
        if clean:providers.model=original_model;providers.speech=original_speech
        emit()
    return report

def validate_result(result,*,warmup=False,turns_by_case=TURNS):
    def need(value):
        if not value:raise ValueError('terminal_evidence_invalid')
    need(type(result) is dict and result.get('source')==SOURCE and result.get('model')==MODEL)
    need(result.get('evidence_version')==2 and result.get('synthetic_private_output_recording') is True)
    need(result.get('semantic_pass') is None and result.get('semantic_review_required') is True and result.get('synthetic_only') is True)
    need(result.get('limits')==LIMITS and result.get('cleanup_confirmed') is True and result.get('usage_final') is True and result.get('stopped') is False)
    need(result.get('asr_calls')==0 and result.get('image_calls')==0)
    rows=result.get('cases');need(type(rows) is list and len(rows)==len(CASES))
    for row,(case_id,text) in zip(rows,CASES):
        need(row.get('id')==case_id and row.get('independent_session') is True)
        clean=row.get('cleanup',{});need(clean.get('confirmed') is True and clean.get('quarantined') is False and type(clean.get('pending')) is int and clean['pending']==0 and clean.get('task_errors')==0)
        inputs=turns_by_case[case_id] if turns_by_case is not None else (WARMUP,text) if warmup else (text,)
        turns=row.get('turns');need(type(turns) is list and len(turns)==len(inputs))
        for turn,wanted in zip(turns,inputs):
            if wanted is None:
                answer=turns[0]['synthetic_hidden_after'].get('answer')
                need(type(answer) is str and turn.get('dynamic_synthetic_guess') is True)
                wanted='是'+answer+'吗？提示它有什么用。'
            need(turn.get('synthetic_input')==wanted and type(turn.get('actual_complete_ack_texts')) is list)
            need(all(type(t) is str and 0<len(t)<=240 for t in turn['actual_complete_ack_texts']))
            need(type(turn.get('final_ack')) is bool and turn['final_ack']==turn.get('public_game_committed'))
            for field in ('synthetic_hidden_before','synthetic_hidden_after'):
                need(type(turn.get(field)) is dict and all(type(k) is str and type(v) is str for k,v in turn[field].items()))
            status=turn.get('status');need(status in {'cloud_reply_complete_simulated_ack','local_help_protocol_only','partial_cloud_ack_plus_local_help_protocol'})
            if status=='cloud_reply_complete_simulated_ack':
                need(turn.get('reply_final_segment_ack') is True and turn.get('pending_audio')==0 and (turn.get('reply_end') is True or turn.get('session_end') is True))
                segments=turn.get('actual_complete_ack_segments');need(type(segments) is list and bool(segments))
                need([item.get('text') for item in segments]==turn['actual_complete_ack_texts'])
                need(all(item.get('complete_ack') is True and item.get('target_append_confirmed') is True and item.get('scope') in {'public','private'} for item in segments))
                need(segments[-1].get('final_state_proposal_acked') is True)
                need(turn['public_game_committed'] is (segments[-1]['scope']=='public'))
            else:need(bool(turn.get('local_help')) and turn.get('reply_end') is False and turn.get('session_end') is False)
        need(all(turn['status']=='cloud_reply_complete_simulated_ack' and turn['reply_final_segment_ack'] is True for turn in turns[:-1]))
        if warmup:need(turns[0]['status']=='cloud_reply_complete_simulated_ack' and turns[0]['game_before']=={} and turns[0]['game_after'].get('mode')=='association')
    totals=result.get('totals',{})
    for key,cap in [('model_requests',LIMITS['model_requests']),('tts_requests',LIMITS['tts_requests']),('tts_characters',LIMITS['tts_characters'])]:
        need(type(totals.get(key)) is int and 0<=totals[key]<=cap)
    need(totals.get('budget_denials')==[])
    need(type(totals.get('stages')) is list and len(totals['stages'])==totals['model_requests'])
    need(type(totals.get('planning_reserved_cny')) in (int,float) and 0<=totals['planning_reserved_cny']<=LIMITS['planning_model_cny'])

async def live(out):
    import httpx
    from backend.v2.runtime import settings,providers,FIELDS
    config=settings(environment={},service_env='/etc/little-buddy-v2/service.env')
    if config['llm']!=MODEL:raise ValueError('model_mismatch')
    async with httpx.AsyncClient(trust_env=False,follow_redirects=False,timeout=10.) as http:
        p=providers(http,environment={FIELDS[k]:v for k,v in config.items()},credential_directory='/etc/little-buddy-v2')
        # Production model/strict schemas/review only; no provider speech method runs.
        class SyntheticSpeech:
            @asynccontextmanager
            async def synthesize(self,text,rate):
                async def frames():yield b'\x01\x00'*2400
                yield frames()
        p.speech=SyntheticSpeech()
        result=await run_group(p,progress=lambda r:save(out/'result.json',r))
        save(out/'result.json',result)

def admission():
    return dict(source=SOURCE,model=MODEL,no_fallback=True,no_automatic_retry=True,production_shared_retry_preserved=True,
        case=SELECTED,model_request_limit=24,quota_not_live_verified_acknowledged=True,account_quota_verified=False,
        authorization='existing_user_authorization_for_bounded_text_recheck',
        historical_user_evidence=dict(model=MODEL,free_tokens_shown=999070,
            free_tier_exhaustion_stop_enabled=True,live_verified=False),
        preference='free_quota_first',planning_budget_not_bill=True,
        allowed_network='deepseek_1017_text_only',real_asr_tts_images_allowed=False)

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',choices=tuple(ALL_CASES),required=True)
    parser.add_argument('--execute',action='store_true');parser.add_argument('--acknowledge-quota-not-live-verified',action='store_true')
    parser.add_argument('--output',type=pathlib.Path);parser.add_argument('--_worker',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args(argv)
    select_case(args.case)
    if not args.execute:
        print(json.dumps(dict(status='DISABLED_PLAN_ONLY',source=SOURCE,case=SELECTED,cases=TURNS,limits=LIMITS,semantic_pass=None,cloud_calls=0),ensure_ascii=False));return 0
    if not args.acknowledge_quota_not_live_verified or args.output is None:return 2
    verify_source()
    if args._worker:
        # Internal worker is explicit opt-in; parent PID check is not a security boundary.
        if os.environ.get('V2_RECHECK_PARENT')!=str(os.getppid()):return 2
        asyncio.run(live(args.output));return 0
    out=args.output.resolve();out.mkdir(exist_ok=False,mode=0o700)
    save(out/'admission.json',admission())
    command=[sys.executable,'-I','-B',str(pathlib.Path(__file__).resolve()),'--case',args.case,'--execute','--acknowledge-quota-not-live-verified','--_worker','--output',str(out)]
    child=subprocess.Popen(command,env={**os.environ,'V2_RECHECK_PARENT':str(os.getpid())},start_new_session=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    forced=False;code=None
    try:code=child.wait(timeout=LIMITS['supervisor_seconds'])
    except BaseException:
        forced=True;os.killpg(child.pid,signal.SIGKILL);code=child.wait(timeout=2)
    valid=False
    try:
        result=json.loads((out/'result.json').read_text());validate_result(result);valid=True
    except (OSError,ValueError,TypeError,KeyError):pass
    save(out/'supervisor.json',dict(exit_code=code,forced_exit=forced,artifact_valid=valid,cleanup_confirmed=valid and code==0 and not forced,semantic_pass=None,automatic_retry=False))
    return 0 if valid and code==0 and not forced else 2

if __name__=='__main__':
    # -I omits cwd: admit only the pinned repository, never external modules.
    sys.path.insert(0,str(ROOT.parent))
    try:raise SystemExit(main())
    except Exception:print('{"status":"controlled_failure"}');raise SystemExit(2)
