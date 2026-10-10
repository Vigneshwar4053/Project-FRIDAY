"""Bounded session-local launch receipts, never window state or authorization."""
from collections import OrderedDict
import math
import time


class RecentLaunchGuard:
    def __init__(self, seconds=20, *, clock=time.monotonic):
        if type(seconds) not in {int,float} or not math.isfinite(seconds) or not 1 <= seconds <= 120:
            raise ValueError('Desktop duplicate window must be between 1 and 120 seconds.')
        self.seconds=seconds; self.clock=clock; self.receipts=OrderedDict()

    @staticmethod
    def key(lease):
        return (lease['record_operation'],lease['application_id'],
                str(lease['path']) if lease['path'] is not None else None,
                lease['identity'],lease['url'])

    def _expire(self):
        now=self.clock()
        for key,stamp in tuple(self.receipts.items()):
            if now-stamp >= self.seconds or now < stamp: del self.receipts[key]
        return now

    def recent(self, lease):
        self._expire()
        return self.key(lease) in self.receipts

    def record(self, lease):
        stamp=self._expire(); key=self.key(lease)
        self.receipts.pop(key,None);self.receipts[key]=stamp
        while len(self.receipts)>32: self.receipts.popitem(last=False)

    def clear(self): self.receipts.clear()
