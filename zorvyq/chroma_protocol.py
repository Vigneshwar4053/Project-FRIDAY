"""Bounded JSON over inherited anonymous pipes; no pickle or network listener."""
import json
import os
import re
import selectors
from time import monotonic

LIMIT=524288

def unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate IPC field')
        result[key]=value
    return result

class JsonPipe:
    def __init__(self,reader,writer,nonce):
        if not re.fullmatch(r'[0-9a-f]{64}',nonce):raise ValueError('Invalid IPC identity')
        self.reader,self.writer,self.nonce=reader,writer,nonce
        self.buffer=bytearray();self.closed=False
    def write(self,sequence,kind,payload,*,deadline=None):
        raw=json.dumps({'version':1,'nonce':self.nonce,'sequence':sequence,'kind':kind,'payload':payload},
                       allow_nan=False,separators=(',',':')).encode()+b'\n'
        if len(raw)>LIMIT:raise ValueError('IPC size limit')
        deadline=deadline or monotonic()+5
        os.set_blocking(self.writer,False)
        with selectors.DefaultSelector() as selector:
            selector.register(self.writer,selectors.EVENT_WRITE)
            offset=0
            while offset<len(raw):
                if monotonic()>=deadline:raise TimeoutError('IPC write deadline')
                if selector.select(min(.05,max(.001,deadline-monotonic()))):
                    try:offset+=os.write(self.writer,raw[offset:])
                    except BlockingIOError:pass
    def read(self,deadline,cancelled=None):
        os.set_blocking(self.reader,False)
        with selectors.DefaultSelector() as selector:
            selector.register(self.reader,selectors.EVENT_READ)
            while b'\n' not in self.buffer:
                if cancelled is not None and cancelled.is_set():raise InterruptedError('IPC cancelled')
                if monotonic()>=deadline:raise TimeoutError('IPC read deadline')
                if not selector.select(min(.05,max(.001,deadline-monotonic()))):continue
                try:raw=os.read(self.reader,65536)
                except BlockingIOError:continue
                if not raw:raise EOFError('IPC worker closed')
                self.buffer.extend(raw)
                if len(self.buffer)>LIMIT:raise ValueError('IPC response exceeded its bound')
        line,_,remaining=self.buffer.partition(b'\n');self.buffer=bytearray(remaining)
        value=json.loads(line,object_pairs_hook=unique,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
        if (type(value) is not dict or set(value)!={'version','nonce','sequence','kind','payload'} or
            type(value['version']) is not int or value['version']!=1 or value['nonce']!=self.nonce or
            type(value['sequence']) is not int or not 0<=value['sequence']<=1000 or type(value['kind']) is not str):
            raise ValueError('Invalid IPC envelope')
        return value
    def close(self):
        if self.closed:return
        self.closed=True
        for fd in (self.reader,self.writer):
            try:os.close(fd)
            except OSError:pass
