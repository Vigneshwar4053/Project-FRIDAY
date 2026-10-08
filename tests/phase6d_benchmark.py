"""Opt-in public-fixture benchmark; no shell execution, private paths or raw output.
Run offline: PYTHONPATH=. .venv/bin/python -B tests/phase6d_benchmark.py
Run live: same command with --live --samples 1 (Ollama must already be running).
"""
import argparse
from contextlib import contextmanager, closing
from dataclasses import replace
import json
import os
from pathlib import Path
import resource
import statistics
import tempfile
from time import perf_counter_ns, process_time_ns
from unittest.mock import patch

from friday.config.settings import settings
from friday.core.assistant import FridayAssistant
from friday.main import create_tool_runtime
from friday.memory import MemoryManager
from friday.models import ModelManager
from friday.providers.base import ModelProvider, ProviderError
from friday.providers.ollama import OllamaProvider
from friday.sync import create_synchronization
from friday.tools.access import FolderDecision

SCENARIOS = (('A_greeting', 'hello friday'), ('B_folder', 'open downloads'),
             ('C_known_file', 'read benchmark.txt'),
             ('D_standard', 'explain Python decorators'),
             ('E_deep', 'think deeply about software architecture'))


class FixtureProvider(ModelProvider):
    supports_inference_profiles = True
    def __init__(self):
        self.profiles = []
    @contextmanager
    def inference_profile(self, profile):
        self.profiles.append(profile)
        yield
    def chat(self, messages):
        if "FRIDAY's intent translator" in messages[0]['content']:
            return json.dumps({'kind':'chat', 'response':'Public fixture conversational answer.'})
        return 'Public fixture conversational answer.'


class FixtureApproval:
    def __init__(self):
        self.calls = 0
    def request(self, target):
        self.calls += 1
        return FolderDecision.ALLOW_ONCE  # Explicit fixture-only authorization.


def run_benchmark(*, samples=3, live=False):
    if type(samples) is not int or not 1 <= samples <= (2 if live else 5):
        raise ValueError('Use 1–5 offline samples or 1–2 explicit live samples.')
    rows = []
    backends = set()
    for adaptive in (False, True):
        for scenario, message in SCENARIOS:
            measured = []
            for _ in range(samples):
                with tempfile.TemporaryDirectory(prefix='friday-workload-benchmark-') as temporary:
                    home = Path(temporary)
                    project, downloads = home / 'FRIDAY', home / 'Downloads'
                    project.mkdir()
                    downloads.mkdir()
                    (downloads / 'benchmark.txt').write_text('PUBLIC_BENCHMARK_BODY_6D')
                    config = replace(settings, project_root=project, database_path=project / 'memory.db',
                                     adaptive_workloads=adaptive, workload_diagnostics=False, user_name='Benchmark user',
                                     filesystem_read_roots=(),
                                     filesystem_permission_store_path=project/'permissions'/'grants.json')
                    provider = (OllamaProvider(config.ollama_base_url, config.ollama_model,
                                timeout=config.ollama_timeout, think=config.ollama_think) if live else FixtureProvider())
                    approval = FixtureApproval()
                    with patch.dict(os.environ, {'HOME':str(home), 'XDG_CONFIG_HOME':str(home / '.config')}), \
                         closing(create_synchronization(config.sync_library_path)) as synchronization, \
                         ModelManager(provider, config.ollama_model, synchronization=synchronization) as models, \
                         MemoryManager(config.database_path) as memory:
                        backends.add(synchronization.backend_name)
                        manager, router = create_tool_runtime(config, filesystem_approval=approval)
                        assistant = FridayAssistant(models, config.system_prompt, memory=memory,
                            tool_router=router, tool_manager=manager, workload_configuration=config)
                        try:
                            if scenario == 'C_known_file':
                                assistant.respond('open downloads')  # Setup excluded from timing and counts.
                            before = models.invocation_count
                            model_time = models.model_request_ns
                            cpu, started = process_time_ns(), perf_counter_ns()
                            error = False
                            try:
                                answer = assistant.respond(message)
                            except ProviderError:
                                error = True
                            elapsed, cpu_time = perf_counter_ns() - started, process_time_ns() - cpu
                            if scenario == 'B_folder' and not error:
                                assert 'benchmark.txt' in answer
                            if scenario == 'C_known_file' and not error:
                                assert 'PUBLIC_BENCHMARK_BODY_6D' in answer
                            assert 'PUBLIC_BENCHMARK_BODY_6D' not in json.dumps([m.content for m in memory.get_recent_messages(100)])
                            metrics = assistant.last_performance
                            measured.append({'wall_ns':elapsed, 'python_cpu_ns':cpu_time,
                                'python_peak_rss_kib':int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
                                'model_invocations':models.invocation_count-before,
                                'model_request_ns':models.model_request_ns-model_time,
                                'level':metrics.level if metrics else 'legacy',
                                'classification_ns':metrics.classification_ns if metrics else None,
                                'routing_ns':metrics.routing_ns if metrics else None, 'error':error})
                        finally:
                            assistant.end_session()
            numeric = ('wall_ns', 'python_cpu_ns', 'python_peak_rss_kib', 'model_invocations', 'model_request_ns')
            row = {'mode':'adaptive' if adaptive else 'phase6c_compatibility', 'scenario':scenario,
                   'samples':samples, 'level':measured[-1]['level'], 'errors':sum(m['error'] for m in measured)}
            row.update({key:statistics.median(m[key] for m in measured) for key in numeric})
            for key in ('classification_ns','routing_ns'):
                row[key] = statistics.median(m[key] for m in measured) if adaptive else None
            rows.append(row)
    return {'synchronization_backends': sorted(backends), 'provider':'live_ollama' if live else 'fake_no_inference_delay',
            'baseline':'Retained Phase 6C compatibility path under shared instrumentation; not a pristine commit timing.',
            'limits':'Python CPU/peak RSS exclude Ollama. Peak RSS is cumulative for this process. No model memory/CPU savings or live speedup inferred.',
            'rows':rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Explicitly send public requests to installed qwen3:4b')
    parser.add_argument('--samples', type=int)
    args = parser.parse_args()
    print(json.dumps(run_benchmark(samples=args.samples if args.samples is not None else 1 if args.live else 3,
                                   live=args.live), indent=2, sort_keys=True))
