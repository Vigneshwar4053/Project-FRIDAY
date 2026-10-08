"""Opt-in live L2 comparison using public prompts; aggregate-only stdout.
No SQLite, filesystem tools, shell commands, prompt/answer logging, or retries.
"""
from contextlib import closing
import argparse
import json
from time import perf_counter_ns

from friday.config.settings import settings
from friday.models import ModelManager
from friday.models.profile import InferenceProfile, STANDARD_RESPONSE_INSTRUCTIONS
from friday.providers.base import ProviderError
from friday.providers.ollama import OllamaProvider
from friday.sync import create_synchronization

PUBLIC_SCENARIOS = (('identity', 'Do you know who I am?'),
                    ('decorators', 'Explain Python decorators.'))


def run(samples=1, *, baseline=False):
    if type(samples) is not int or not 1 <= samples <= 2:
        raise ValueError('Use one or two samples.')
    rows = []
    modes = [('current_l2', settings.standard_inference_profile, STANDARD_RESPONSE_INSTRUCTIONS)]
    if baseline:
        modes.insert(0, ('previous_l2', InferenceProfile(), ''))
    provider = OllamaProvider(settings.ollama_base_url, settings.ollama_model)
    with closing(create_synchronization(settings.sync_library_path)) as sync:
        with ModelManager(provider, settings.ollama_model, synchronization=sync) as manager:
            for mode, profile, instruction in modes:
                for scenario, question in PUBLIC_SCENARIOS:
                    for sample in range(samples):
                        # Fixed public identity, no personal settings/history or file bodies.
                        messages = [{'role':'system', 'content':'You are a helpful local assistant. No user identity is supplied. ' + instruction},
                                    {'role':'user', 'content':question}]
                        started = perf_counter_ns()
                        previous = manager.invocation_count
                        status = 'success'
                        try:
                            manager.generate(messages, profile=profile)
                        except ProviderError:
                            status = 'failed'
                        rows.append({'mode':mode, 'scenario':scenario, 'sample':sample + 1,
                                     'wall_seconds':(perf_counter_ns() - started) / 1e9,
                                     'model_calls':manager.invocation_count - previous,
                                     'status':status, 'think_requested':profile.think,
                                     'num_predict':profile.num_predict,
                                     'metrics':provider.last_generation_metrics})
                        # Benchmark never retains a generated answer or raw request in jobs.
                        if manager.last_job is not None:
                            manager.last_job.messages = []
                            manager.last_job.result = None
                            manager.last_job.error = None
    return {'rows':rows, 'limitations':'No process-wide Ollama CPU/RSS measurement. Cold/warm order effects; synthetic fresh-context prompts, not personal CLI history. Thinking-present=false is evidence, not proof of no internal computation.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Explicitly permit local model inference')
    parser.add_argument('--baseline', action='store_true', help='Also run the previous 512-token profile')
    parser.add_argument('--samples', type=int, default=1)
    args = parser.parse_args()
    if not args.live:
        parser.error('Live inference requires --live.')
    if not 1 <= args.samples <= 2:
        parser.error('Use --samples 1 or 2.')
    print(json.dumps(run(args.samples, baseline=args.baseline), indent=2))
