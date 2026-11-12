"""Bounded subprocess transport. Only Registry-validated plans may reach this runner."""
import os
import selectors
import signal
import subprocess
from time import monotonic
from .contracts import StageResult
from .registry import resolve_tool
from .reporting import sanitize

class Runner:
    @staticmethod
    def validate(stage):
        from .registry import OPERATIONS, Registry
        from dataclasses import replace
        candidates=[s for op in OPERATIONS for s in op.stages if s.tool]
        if stage.tool=='nmap' and stage.arguments:
            candidates.extend(Registry().plan('network.discovery',{'target':stage.arguments[-1],'purpose':stage.purpose}).stages)
        if not any(0 < stage.timeout <= s.timeout and 0 < stage.output_limit <= s.output_limit and
                   replace(s,timeout=stage.timeout,output_limit=stage.output_limit)==stage for s in candidates):
            raise ValueError('Command is outside the reviewed registry.')

    def preview(self,stage):
        self.validate(stage)
        tool=resolve_tool(stage.tool)
        limiter=resolve_tool('prlimit')
        if not tool or not limiter:return None
        return (limiter,'--cpu=10','--as=268435456','--fsize=1048576','--',tool,*stage.arguments)

    @staticmethod
    def stop(child):
        # The PID is the fresh session/group created below. Never target any
        # process discovered by a diagnostic or supplied by the owner/model.
        try:os.killpg(child.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:child.wait(timeout=.5)
        except subprocess.TimeoutExpired:
            try:os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            child.wait(timeout=2)

    def run(self,stage,cancel,emit=lambda text:None):
        command=self.preview(stage)
        if command is None:return StageResult(stage.stage_id,'NOT CHECKED',limitation='Required tool or resource limiter unavailable')
        if cancel.is_set():return StageResult(stage.stage_id,'CANCELLED')
        import json
        emit('Exact argv: '+sanitize(json.dumps(command),4096))
        started=monotonic(); buffers={'stdout':bytearray(),'stderr':bytearray()};status='COMPLETED'
        child=None
        displayed={'stdout':0,'stderr':0}
        try:
            child=subprocess.Popen(list(command),shell=False,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,start_new_session=True,close_fds=True,
                env={'PATH':'/usr/bin:/usr/sbin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8','SYSTEMD_PAGER':'','PAGER':'cat','GIT_TERMINAL_PROMPT':'0'})
            with selectors.DefaultSelector() as selector:
                for name in buffers:
                    stream=getattr(child,name);os.set_blocking(stream.fileno(),False)
                    selector.register(stream,selectors.EVENT_READ,name)
                while selector.get_map():
                    if cancel.is_set(): status='CANCELLED';break
                    if monotonic()-started>=stage.timeout:status='TIMEOUT';break
                    for key,_ in selector.select(.1):
                        data=os.read(key.fileobj.fileno(),4096)
                        if not data:
                            selector.unregister(key.fileobj);continue
                        room=stage.output_limit-sum(len(b) for b in buffers.values())
                        buffers[key.data].extend(data[:max(0,room)])
                        # Emit complete lines only so redaction spans read boundaries.
                        if stage.parser != 'journal':
                            end = buffers[key.data].rfind(b'\n')+1
                            if end > displayed[key.data]:
                                chunk = buffers[key.data][displayed[key.data]:end].decode(errors='replace')
                                emit(key.data+': '+sanitize(chunk,stage.output_limit))
                                displayed[key.data]=end
                        if len(data)>room:status='OUTPUT LIMIT';break
                    if status!='COMPLETED':break
                if status!='COMPLETED':self.stop(child)
                else:
                    try:child.wait(timeout=max(.01,stage.timeout-(monotonic()-started)))
                    except subprocess.TimeoutExpired:status='TIMEOUT';self.stop(child)
            if status=='COMPLETED' and child.returncode not in stage.expected_codes:status='FAILED'
            stdout=sanitize(buffers['stdout'].decode(errors='replace'),stage.output_limit)
            stderr=sanitize(buffers['stderr'].decode(errors='replace'),stage.output_limit)
            result=StageResult(stage.stage_id,status,child.returncode,round(monotonic()-started,3),stdout,stderr)
            # Parsing uses bounded original bytes; reports/display receive sanitized
            # forms only. Log message bodies are never requested by the registry.
            if status=='COMPLETED':
                from .collector import parse
                try:result.metrics=parse(stage.parser,buffers['stdout'].decode(errors='replace'))
                except (ValueError,TypeError):result.status='INVALID OUTPUT';result.limitation='Structured command response rejected'
            if stage.parser=='journal':
                result.stdout='Bounded journal metadata counts only; raw records withheld.'
                if stderr:
                    result.status='NOT CHECKED';result.limitation='Journal access incomplete; no full-visibility claim'
            emit(stage.stage_id+': '+result.status+' · exit='+str(result.exit_code)+' · elapsed='+str(result.elapsed)+'s')
            if stage.parser == 'journal':
                emit(result.stdout)
                if result.stderr:emit('stderr: '+result.stderr)
            else:
                for name in buffers:
                    tail=buffers[name][displayed[name]:].decode(errors='replace')
                    if tail:emit(name+': '+sanitize(tail,stage.output_limit))
            return result
        except OSError:
            return StageResult(stage.stage_id,'NOT CHECKED',elapsed=round(monotonic()-started,3),limitation='Executable or local access unavailable')
        finally:
            if child is not None:
                if child.poll() is None:self.stop(child)
                for stream in (child.stdout,child.stderr):
                    if stream is not None:stream.close()
