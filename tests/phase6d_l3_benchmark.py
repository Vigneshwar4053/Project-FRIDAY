"""Explicitly opt-in public L3 comparison; never print prompts or model text."""
import argparse
from contextlib import closing
from dataclasses import replace
import json
from time import perf_counter_ns

from friday.config.settings import settings
from friday.models import ModelManager
from friday.models.profile import deep_profile, DEEP_RESPONSE_INSTRUCTIONS
from friday.providers.base import ProviderError
from friday.providers.ollama import OllamaProvider
from friday.sync import create_synchronization


def run(samples=1, *, alternatives=False, current_only=False):
    if type(samples) is not int or not 1 <= samples <= 2:
        raise ValueError('Use one or two samples.')
    modes = [] if current_only else [('previous_l3', replace(deep_profile(),think=True,num_predict=1024), '')]
    modes.append(('current_l3', settings.deep_inference_profile, DEEP_RESPONSE_INSTRUCTIONS))
    if alternatives and not current_only:
        modes.append(('direct_deep', replace(deep_profile(),think=False,num_predict=1024), DEEP_RESPONSE_INSTRUCTIONS))
    provider=OllamaProvider(settings.ollama_base_url,settings.ollama_model)
    rows=[]
    with closing(create_synchronization(settings.sync_library_path)) as gate:
        with ModelManager(provider,settings.ollama_model,synchronization=gate) as manager:
            for mode,profile,instruction in modes:
                for sample in range(samples):
                    messages=[{'role':'system','content':'You are a technical assistant. Analyze a hypothetical local Ubuntu assistant with registered tools, default-deny filesystem permissions, a model intent validator and a native mutex. Do not claim to inspect a real project. '+instruction},
                              {'role':'user','content':'Think deeply about the security architecture.'}]
                    before=manager.invocation_count
                    started=perf_counter_ns()
                    status='success'
                    try:
                        manager.generate(messages,profile=profile)
                    except ProviderError:
                        status='failed'
                    rows.append({'mode':mode,'sample':sample+1,'status':status,
                                 'wall_seconds':(perf_counter_ns()-started)/1e9,
                                 'model_calls':manager.invocation_count-before,
                                 'think_requested':profile.think,'num_predict':profile.num_predict,
                                 'metrics':provider.last_generation_metrics})
                    if manager.last_job is not None:
                        manager.last_job.messages=[]
                        manager.last_job.result=None
                        manager.last_job.error=None
    return {'rows':rows,'limitations':'Single public fresh-context scenario; order/loading/stochastic effects. Total output tokens include thinking; API does not provide a reasoning/final token split. No Ollama CPU/RSS measurement. No raw text is recorded.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--alternatives',action='store_true',help='Also measure the direct-answer alternative')
    parser.add_argument('--current-only',action='store_true',help='Measure only the configured current L3 profile')
    parser.add_argument('--samples',type=int,default=1)
    args=parser.parse_args()
    if not args.live: parser.error('Live inference requires --live.')
    if not 1<=args.samples<=2: parser.error('Use one or two samples.')
    print(json.dumps(run(args.samples,alternatives=args.alternatives,current_only=args.current_only),indent=2))
