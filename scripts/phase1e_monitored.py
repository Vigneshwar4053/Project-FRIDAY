"""Owner-authorized monitored soft limits, not kernel-enforced ceilings."""
import os
from pathlib import Path
import shutil
from threading import Event, Lock, Thread
from time import monotonic

from scripts.phase1e_admission import AdmissionDenied, available_ram, private_storage_size, GIB, MIB


def admit_monitored(*, ram, disk, storage, chunks, cancelled=False):
    if cancelled:raise AdmissionDenied('Owned indexing session cancelled.')
    if any(type(v) is not int or v<0 for v in (ram,disk,storage,chunks)):
        raise AdmissionDenied('Monitored resource measurements are unavailable.')
    if ram<3*GIB:raise AdmissionDenied('Observed MemAvailable below 3 GiB.')
    if disk<10*GIB:raise AdmissionDenied('Observed free disk below 10 GiB.')
    if storage>100*MIB:raise AdmissionDenied('Observed experiment storage above 100 MiB.')
    if chunks>312:raise AdmissionDenied('Approved 312-chunk maximum exceeded.')


def processes():
    """Process metadata only; never read process environments or source text."""
    values={}
    for path in Path('/proc').iterdir():
        if not path.name.isdecimal():continue
        try:
            fields=(path/'stat').read_text().rsplit(')',1)[1].split()
            status=(path/'status').read_text().splitlines()
            memory=next(int(l.split()[1])*1024 for l in status if l.startswith('VmRSS:'))
            values[int(path.name)]={'parent':int(fields[1]),'start':int(fields[19]),
                'cpu':(int(fields[11])+int(fields[12]))/os.sysconf('SC_CLK_TCK'),
                'rss':memory,'name':(path/'comm').read_text().strip()}
        except (OSError,ValueError,IndexError,StopIteration):continue
    return values


def descendants(values,roots):
    selected=set(roots)&set(values)
    while True:
        extra={pid for pid,v in values.items() if v['parent'] in selected}
        if extra<=selected:return selected
        selected.update(extra)


class Monitor:
    def __init__(self,root,cancelled,*,seconds=300):
        self.root=root;self.cancelled=cancelled;self.stopped=Event();self.lock=Lock()
        self.started=monotonic();self.deadline=self.started+seconds
        self.reason=None;self.latest=None;self.peak_total_rss=0;self.peak_additional_rss=0
        self.minimum_available=None;self.minimum_disk=None;self.maximum_storage=0;self.samples=0
        self.baseline=processes();self.cpu_initial={};self.cpu_last={}
        if os.getpid() not in self.baseline:raise AdmissionDenied('Runner RSS cannot be measured.')
        self.baseline_ollama=sum(v['rss'] for pid,v in self.baseline.items() if pid in
            descendants(self.baseline,{p for p,v in self.baseline.items() if v['name']=='ollama'}))
        self.thread=Thread(target=self._run,daemon=True)

    def fail(self,reason):
        with self.lock:
            if self.reason is None:self.reason=reason
        self.cancelled.set()

    def sample(self,chunks=0,*,storage_check=True):
        if monotonic()>=self.deadline:self.fail('Monitored five-minute session deadline reached.')
        values=processes()
        if os.getpid() not in values:raise AdmissionDenied('Runner RSS cannot be measured.')
        own=descendants(values,{os.getpid()})
        ollama=descendants(values,{p for p,v in values.items() if v['name']=='ollama'})
        total=sum(values[p]['rss'] for p in own|ollama)
        additional=max(0,sum(values[p]['rss'] for p in own)-self.baseline[os.getpid()]['rss'])+max(
            0,sum(values[p]['rss'] for p in ollama-own)-self.baseline_ollama)
        ram=available_ram();disk=shutil.disk_usage(self.root).free
        storage=private_storage_size(self.root) if storage_check else self.maximum_storage
        with self.lock:
            self.samples+=1;self.peak_total_rss=max(self.peak_total_rss,total)
            self.peak_additional_rss=max(self.peak_additional_rss,additional)
            self.minimum_available=ram if self.minimum_available is None else min(ram,self.minimum_available)
            self.minimum_disk=disk if self.minimum_disk is None else min(disk,self.minimum_disk)
            self.maximum_storage=max(self.maximum_storage,storage)
            for p in own|ollama:
                key=(p,values[p]['start']);baseline=self.baseline.get(p)
                initial=baseline['cpu'] if baseline and baseline['start']==values[p]['start'] else 0
                self.cpu_initial.setdefault(key,initial);self.cpu_last[key]=values[p]['cpu']
            self.latest={'ram':ram,'disk':disk,'storage':storage,'chunks':chunks,
                         'rss':total,'additional_rss':additional,'elapsed':monotonic()-self.started}
        admit_monitored(ram=ram,disk=disk,storage=storage,chunks=chunks,cancelled=self.cancelled.is_set())
        return dict(self.latest)

    def _run(self):
        while not self.stopped.is_set():
            try:self.sample(storage_check=False)
            except AdmissionDenied as error:self.fail(str(error));return
            except Exception:self.fail('Background resource sampler failed safely.');return
            self.stopped.wait(.05)

    def check(self,chunks=0):
        if self.reason:raise AdmissionDenied(self.reason)
        try:return self.sample(chunks)
        except AdmissionDenied as error:self.fail(str(error));raise

    def summary(self):
        return {'policy':'monitored soft admission; not hard ceilings','sample_interval_seconds':.05,
            'rss_samples':self.samples,'peak_observed_relevant_rss_bytes':self.peak_total_rss,
            'peak_observed_additional_rss_bytes':self.peak_additional_rss,
            'minimum_available_ram_bytes':self.minimum_available,'minimum_free_disk_bytes':self.minimum_disk,
            'maximum_observed_storage_bytes':self.maximum_storage,
            'sampled_cpu_seconds':sum(max(0,v-self.cpu_initial[k]) for k,v in self.cpu_last.items()),
            'sampled_wall_seconds':monotonic()-self.started,'incident':self.reason,
            'limits':'50 ms sampling can miss brief peaks and exited-process CPU tails; RSS counts shared mappings. '
                     'Storage is measured before/after batches; concurrent external clients are not locked by this process-local gate.'}

    def __enter__(self):self.check();self.thread.start();return self
    def __exit__(self,*_):self.stopped.set();self.thread.join(2)
