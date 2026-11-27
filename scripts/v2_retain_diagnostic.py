"""Disabled fixed-synthetic-case diagnostic. Never a semantic PASS oracle."""
import argparse,asyncio,copy,hashlib,json,os,signal,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts import v2_retain_only_probe as base

EXPECTED_SOURCE='79ba62b3b7e8b16d15b43249039891e568de8672'
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def fixed_profile():
    if base.SOURCE!=EXPECTED_SOURCE or base.TURNS!={'retain-only-change':('我们玩会飞的东西，不重复。我已经说过小鸟和飞机，这些不能再用；这次我说蝴蝶，轮到你。','只改成两个字，保留会飞和不重复，不重新开始；轮到你了。')}:
        raise ValueError('diagnostic_scope')

class TraceModel:
    def __init__(self,inner):
        self.inner=inner;self.model=base.MODEL;self.turn=0;self.review=0;self.records=[]
    def metrics(self):return self.inner.metrics() if hasattr(self.inner,'metrics') else {}
    async def complete(self,instruction,data,*,schema=None):
        props=(schema or {}).get('properties',{})
        kind='plan' if 'mode' in props else 'review' if 'allow' in props else 'other'
        row=None
        if kind=='plan':
            text=data.get('text');inputs=base.TURNS['retain-only-change']
            if text not in inputs:raise ValueError('diagnostic_input_scope')
            turn=inputs.index(text)+1
            if turn!=self.turn:self.turn=turn;self.review=0
            row=dict(kind=kind,turn=self.turn,input=text,context=copy.deepcopy(data.get('context')),constraints=copy.deepcopy(data.get('server_constraints')))
        elif kind=='review':
            if self.turn not in (1,2):raise ValueError('diagnostic_review_scope')
            row=dict(kind=kind,turn=self.turn,phase='whole' if self.review==0 else 'segment',index=self.review,
                candidate=copy.deepcopy(data.get('segment')),context=copy.deepcopy(data.get('context')))
            self.review+=1
        if row is not None:
            if len(self.records)>=16 or len(json.dumps(row,ensure_ascii=False).encode())>65536:raise ValueError('diagnostic_capacity')
            row['instruction_sha256']=digest(instruction);row['outcome']='incomplete';self.records.append(row)
        try:raw=await self.inner.complete(instruction,data,schema=schema)
        except BaseException as error:
            if row is not None:row['outcome']='upstream_failed';row['failure_kind']=type(error).__name__ if type(error).__name__ in {'ModelError','TimeoutError','CancelledError','VoiceFault'} else 'unknown'
            raise
        if row is not None:
            try:
                if not isinstance(raw,str) or len(raw.encode())>32768:raise ValueError('diagnostic_response_capacity')
                from backend.v2.image_review import unique_object
                value=json.loads(raw,object_pairs_hook=unique_object)
                if kind=='review':
                    valid=type(value) is dict and set(value)=={'allow','quality'} and all(type(value[k]) is bool for k in ('allow','quality'))
                    row['allow']=value['allow'] if valid else None
                    row['quality']=value['quality'] if valid else None
                    row['outcome']=('safety_denied' if not value['allow'] else 'quality_denied' if not value['quality'] else 'allowed') if valid else 'invalid'
                    row['raw_reason_available']=False
                    if type(value) is dict and set(value)=={'allow'}:
                        row['legacy_boolean_only']=True # do not invent an old denial category
                else:
                    row['outcome']='candidate_json'
                    row['candidate']={k:copy.deepcopy(value[k]) for k in ('action','mode','rules','roles','secrets','sentences','anchors','guess_role') if k in value} if type(value) is dict else None
            except (ValueError,TypeError):row['outcome']='invalid_json';row['raw_sha256']=hashlib.sha256(raw.encode()).hexdigest() if isinstance(raw,str) else None
        return raw

async def run(providers,*,progress=None):
    fixed_profile();original=providers.model;trace=TraceModel(original);providers.model=trace
    def annotated(report):
        report['diagnostic']=dict(source=EXPECTED_SOURCE,synthetic_case_only=True,trace=copy.deepcopy(trace.records),
            raw_safety_reason_available=False,classification='strict_safety_priority_quality_allow_invalid_upstream_not_free_text_reason',
            complete_final_ack_for_all_turns=bool(len(report['cases'])==1 and len(report['cases'][0]['turns'])==2 and all(t.get('reply_final_segment_ack') and t.get('status')=='cloud_reply_complete_simulated_ack' for t in report['cases'][0]['turns'])))
        return report
    try:
        report=await base.run_group(providers,progress=None if progress is None else lambda r:progress(annotated(r)))
        return annotated(report)
    finally:
        if not getattr(providers,'probe_cleanup_handle',None):providers.model=original

async def live(output):
    import httpx
    from contextlib import asynccontextmanager
    from backend.v2.runtime import settings,providers,FIELDS
    config=settings(environment={},service_env='/etc/little-buddy-v2/service.env')
    if config['llm']!=base.MODEL:raise ValueError('model_mismatch')
    class Speech:
        @asynccontextmanager
        async def synthesize(self,text,rate):
            async def chunks():yield b'\x01\x00'*2400
            yield chunks()
    async with httpx.AsyncClient(trust_env=False,follow_redirects=False,timeout=10.) as http:
        p=providers(http,environment={FIELDS[k]:v for k,v in config.items()},credential_directory='/etc/little-buddy-v2');p.speech=Speech()
        result=await run(p,progress=lambda r:base.save(output/'result.json',r));base.save(output/'result.json',result)

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',choices=('retain-only-change',),required=True);parser.add_argument('--execute',action='store_true')
    parser.add_argument('--acknowledge-quota-not-live-verified',action='store_true');parser.add_argument('--output',type=Path)
    parser.add_argument('--_worker',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args(argv);fixed_profile()
    if not args.execute:print(json.dumps(dict(status='disabled',source=EXPECTED_SOURCE,model_request_limit=16,cloud_calls=0)));return 0
    if not args.acknowledge_quota_not_live_verified or args.output is None:return 2
    base.verify_source()
    if args._worker:
        if os.environ.get('V2_RETAIN_DIAGNOSTIC_PARENT')!=str(os.getppid()):return 2
        asyncio.run(live(args.output));return 0
    output=args.output.resolve();output.mkdir(exist_ok=False,mode=0o700)
    base.save(output/'admission.json',dict(**base.admission(),diagnostic_synthetic_case_only=True))
    command=[sys.executable,'-I','-B',str(Path(__file__).resolve()),'--case','retain-only-change','--execute','--acknowledge-quota-not-live-verified','--_worker','--output',str(output)]
    child=subprocess.Popen(command,env={**os.environ,'V2_RETAIN_DIAGNOSTIC_PARENT':str(os.getpid())},start_new_session=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    forced=False
    try:code=child.wait(timeout=55)
    except BaseException:forced=True;os.killpg(child.pid,signal.SIGKILL);code=child.wait(timeout=2)
    valid=False;complete=False
    try:
        report=json.loads((output/'result.json').read_text());base.validate_result(report);valid=True
        complete=report['diagnostic']['complete_final_ack_for_all_turns'] is True
    except (OSError,KeyError,TypeError,ValueError):pass
    base.save(output/'supervisor.json',dict(exit_code=code,forced_exit=forced,artifact_valid=valid,all_target_replies_complete=complete,
        semantic_pass=None,cleanup_confirmed=valid and code==0 and not forced,no_retry=True))
    return 0 if valid and complete and not forced and code==0 else 2

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception:print('{"status":"controlled_failure"}');raise SystemExit(2)
