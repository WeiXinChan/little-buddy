"""Opt-in, content-free failure observations; never a voice control input."""
import json
import inspect
import asyncio
import sys
import time
import weakref
import math
from backend.v2.diagnostics import CONTRACT_FAILURES,CONTRACT_DETAILS

STAGES=frozenset({'bind','input_policy','plan','facts','fact_commit','safety','synthesis'})

def metadata(stage,error):
    # Explicit class mapping: never serialize an arbitrary class name/message.
    from backend.v2.voice import VoiceFault,WireError
    from backend.v2.companion import ModelError
    from backend.v2.safety import SafetyFault
    from backend.v2.review import QualityFault
    from backend.dashscope import SpeechTaskError
    kinds={VoiceFault:'VoiceFault',WireError:'WireError',ModelError:'ModelError',
           SafetyFault:'SafetyFault',QualityFault:'QualityFault',SpeechTaskError:'SpeechTaskError',
           TimeoutError:'TimeoutError',OSError:'OSError',RuntimeError:'RuntimeError',
           ValueError:'ValueError',TypeError:'TypeError',BufferError:'BufferError'}
    def enum(value,allowed):return value if type(value) is str and value in allowed else 'unknown'
    try:
        contract=enum(getattr(error,'contract_diagnostic',None),CONTRACT_FAILURES)
        detail=enum(getattr(error,'contract_detail',None),CONTRACT_DETAILS)
    except BaseException:contract=detail='unknown'
    row=dict(stage=enum(stage,STAGES),kind=kinds.get(type(error),'unknown'),contract=contract)
    if detail!='unknown':row['detail']=detail
    return row

def journal_sink(row):
    # Only enable in the V2-only namespace; its existing retention applies.
    print(json.dumps(dict(service='little-buddy-v2',event='bounded_failure',**row),separators=(',',':')),
          file=sys.stderr,flush=True)

class FailureWindow:
    """One process-lifetime admission window, not renewed by new connections.

    At most 4 peers, 4 failures per admitted peer, 16 total, for 900 seconds.
    No peer history, text, IDs, audio, exception objects or object graphs in rows.
    """
    def __init__(self,sink,*,clock=time.monotonic):
        if not callable(sink) or inspect.iscoroutinefunction(sink):raise ValueError('observer_sync_required')
        self.clock=clock;self.started=clock();self.sink=sink
        self.peers=0;self.records=0;self.disabled=False
    def attach(self,peer):
        try:
            if self.disabled or self.clock()-self.started>=900 or self.peers>=4 or self.records>=16:return
            if getattr(peer,'failure_observer',None) is not None:return
            self.peers+=1;peer.failure_observer=PeerFailures(self,peer,self.peers)
        except BaseException:self.disabled=True;self.sink=None

class PeerFailures:
    def __init__(self,window,peer,ordinal):
        self.window=window;self.peer=weakref.ref(peer);self.session=weakref.ref(peer.session)
        self.connection=peer.session.connection;self.ordinal=ordinal;self.records=0
    def record(self,peer,operation,row):
        window=self.window
        try:
            now=window.clock()
            if window.disabled or now-window.started>=900 or window.records>=16 or self.records>=4:return
            s=peer.session
            # Read-only identity checks: do not call _live/valid or renew budgets.
            if (self.peer() is not peer or self.session() is not s or self.connection!=s.connection or
                operation.peer is not peer or operation.session is not s or operation.session_id!=s.session or
                operation.connection!=s.connection or operation.turn!=s.turn or operation.epoch!=peer.epoch or
                operation.revision is not None and operation.revision!=peer.revision or
                operation.output is not None and operation.output!=s.output or
                operation.private_mode!=s.private_mode or operation.cancelled or
                peer.closed or peer.quarantined or not s.active or s.management_paused or
                s.clock()>=min(s.expires,s.heartbeat_deadline)):return
            # Re-whitelist caller-supplied metadata too; no arbitrary fields survive.
            def enum(key,allowed):
                value=row.get(key);return value if type(value) is str and value in allowed else 'unknown'
            def number(value):return value if type(value) is int and 0<=value<=2**31-1 else None
            clean=dict(stage=enum('stage',STAGES),kind=enum('kind',KINDS),
                       contract=enum('contract',CONTRACT_FAILURES),detail=enum('detail',CONTRACT_DETAILS),
                       peer=self.ordinal,record=self.records+1,turn=number(s.turn),epoch=number(peer.epoch),revision=number(peer.revision),elapsed_ms=min(900000,max(0,round((now-window.started)*1000))))
            self.records+=1;window.records+=1
            result=window.sink(clean)
            if inspect.isawaitable(result):
                if inspect.iscoroutine(result):result.close()
                elif isinstance(result,asyncio.Future):
                    def observed(done):
                        if not done.cancelled():done.exception()
                    result.add_done_callback(observed)
                raise ValueError('observer_sync_required')
        except BaseException:
            window.disabled=True;window.sink=None

    def timeout(self,peer,source):
        """Terminal observation may follow expiry; never grants operation authority."""
        window=self.window
        try:
            now=window.clock();s=peer.session
            if (window.disabled or now-window.started>=900 or window.records>=16 or self.records>=4 or
                self.peer() is not peer or self.session() is not s or self.connection!=s.connection or peer.closed):return
            allowed={'input_monitor','session_monitor','input_analysis','output_generation'}
            if source not in allowed:return
            sampled=s.clock()
            def remaining(deadline):
                if deadline is None:return None
                value=(deadline-sampled)*1000
                return max(-2147483647,min(2147483647,round(value))) if math.isfinite(value) else None
            reason=s.expiry_reason if s.expiry_reason in {'heartbeat_timeout','response_timeout','management_expired','session_expired'} else 'none'
            row=dict(stage='timeout',kind='TimeoutError',source=source,expiry=reason,
                     peer=self.ordinal,record=self.records+1,
                     elapsed_ms=min(900000,max(0,round((now-window.started)*1000))),
                     input_remaining_ms=remaining(peer.input_budget.deadline),
                     output_remaining_ms=remaining(s.deadline or None),progress_remaining_ms=remaining(s.progress_deadline or None),
                     heartbeat_remaining_ms=remaining(s.heartbeat_deadline),ttl_remaining_ms=remaining(s.expires),
                     awaiting_input=peer.awaiting_input,thinking=peer.input_budget.thinking_at is not None,
                     response_confirmed=s.response_confirmed,response_expired=s.response_expired,
                     active=s.active)
            self.records+=1;window.records+=1
            result=window.sink(row)
            if inspect.isawaitable(result):
                if inspect.iscoroutine(result):result.close()
                elif isinstance(result,asyncio.Future):
                    result.add_done_callback(lambda done: None if done.cancelled() else done.exception())
                raise ValueError('observer_sync_required')
        except BaseException:
            window.disabled=True;window.sink=None


def timeout(peer,source):
    observer=getattr(peer,'failure_observer',None)
    if observer is None:return
    try:observer.timeout(peer,source)
    except BaseException:pass

KINDS=frozenset({'VoiceFault','WireError','ModelError','SafetyFault','QualityFault','SpeechTaskError',
                 'TimeoutError','OSError','RuntimeError','ValueError','TypeError','BufferError'})

def record(peer,operation,stage,error,*,revision=None):
    """Off means no row allocation; any observation error is isolated."""
    observer=getattr(peer,'failure_observer',None)
    if observer is None:return
    try:
        captured=operation.revision if revision is None else revision
        if type(captured) is not int or captured!=peer.revision:return
        observer.record(peer,operation,metadata(stage,error))
    except BaseException:pass
