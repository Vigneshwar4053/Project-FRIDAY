"""Deterministic character offsets with explicit UTF-8 byte limits."""
from friday.intelligence.models import KnowledgeChunk, KnowledgeError, digest, fingerprint, MAX_ACTIVE_CHUNKS


class TextChunker:
    def __init__(self,max_bytes=1536,overlap_bytes=192):
        if (type(max_bytes) is not int or type(overlap_bytes) is not int or
                not 16<=max_bytes<=1536 or not 0<=overlap_bytes<max_bytes//2):
            raise KnowledgeError('Invalid chunk budgets.')
        self.max_bytes=max_bytes;self.overlap_bytes=overlap_bytes
        self.version=f'utf8-paragraph-v1:{max_bytes}:{overlap_bytes}'

    def chunks(self,source_id,revision_id,text):
        result=[];start=0
        while start<len(text):
            if len(result)>=MAX_ACTIVE_CHUNKS:raise KnowledgeError('Document exceeds its chunk limit.')
            end=start;size=0
            while end<len(text) and size+len(text[end].encode('utf-8'))<=self.max_bytes:
                size+=len(text[end].encode('utf-8'));end+=1
            if end<len(text):
                boundary=text.rfind('\n\n',start,end)
                if boundary>=start+(end-start)//2:end=boundary+2
            value=text[start:end]
            ordinal=len(result)
            chunk_id='chk_'+fingerprint([revision_id,self.version,ordinal,start,end,digest(value)])
            result.append(KnowledgeChunk(chunk_id,source_id,revision_id,ordinal,start,end,digest(value),value))
            if end==len(text):break
            next_start=end;overlap=0
            while next_start>start+1:
                width=len(text[next_start-1].encode('utf-8'))
                if overlap+width>self.overlap_bytes:break
                overlap+=width;next_start-=1
            start=next_start
        return tuple(result)
