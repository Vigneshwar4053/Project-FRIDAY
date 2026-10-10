"""Offline adaptive profiles, context, metrics and unchanged security boundaries."""
from contextlib import contextmanager
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from friday.config.settings import Settings, settings
from friday.core.assistant import FridayAssistant
from friday.core.context import select_context
from friday.core.workload import classify, WorkloadLevel
from friday.main import create_tool_runtime, main
from friday.memory import MemoryManager
from friday.models.profile import InferenceProfile, deep_profile, standard_profile
from friday.providers.base import ModelProvider, ProviderError
from friday.providers.ollama import OllamaProvider
from friday.tools.access import FolderDecision
import phase6d_benchmark as benchmark


class RecordingProvider(benchmark.FixtureProvider):
    def __init__(self):
        super().__init__()
        self.calls = 0
        self.messages = []
        self.answer = None
        self.failure = None
    def chat(self, messages):
        self.calls += 1
        self.messages = [dict(m) for m in messages]
        if self.failure is not None:
            raise self.failure
        return self.answer if self.answer is not None else super().chat(messages)


class ClassificationTests(unittest.TestCase):
    def test_greetings(self):
        for message in ('hello', 'hi', 'good morning', 'thank you', 'thanks', 'goodbye', 'hello friday'):
            with self.subTest(message=message):
                decision = classify(message)
                self.assertEqual(decision.level, WorkloadLevel.MINIMAL)
                self.assertFalse(decision.inference_needed)
    def test_mixed_not_greeting(self):
        for message in ('hello, list downloads', 'thanks, show my files', 'hi read data.js', 'good morning open portfolio'):
            self.assertNotEqual(classify(message).level, WorkloadLevel.MINIMAL)
    def test_tool_priority(self):
        decision = classify('think deeply about this architecture', deterministic=True)
        self.assertEqual(decision.level, WorkloadLevel.LIGHT)
        self.assertFalse(decision.inference_needed)
    def test_explicit_deep(self):
        for message in ('think deeply about this architecture', 'perform a detailed technical analysis',
                        'compare these two system designs thoroughly'):
            self.assertEqual(classify(message).level, WorkloadLevel.DEEP)
    def test_ordinary_conversation(self):
        for message in ('explain Python decorators', 'what is a neural network?', 'help me understand REST APIs'):
            self.assertEqual(classify(message).level, WorkloadLevel.STANDARD)
    def test_deep_mention_is_not_request(self):
        self.assertEqual(classify('What does think deeply mean?').level, WorkloadLevel.STANDARD)
    def test_explanation_is_model_work(self):
        self.assertEqual(classify('explain data.js', deterministic=True, explanation=True).profile, 'standard')
    def test_no_paths_or_permission_fields(self):
        decision = classify('open ~/Downloads', deterministic=True)
        self.assertFalse(hasattr(decision, 'path'))
        self.assertFalse(hasattr(decision, 'permission_granted'))
    def test_invalid_structured_profile(self):
        from friday.core.workload import WorkloadDecision
        with self.assertRaises(ValueError):
            WorkloadDecision(WorkloadLevel.STANDARD, 'test', '/private/path', True)
    def test_invalid_input(self):
        with self.assertRaises(ValueError): classify(None)


class ProfileTests(unittest.TestCase):
    def test_conservative_defaults(self):
        self.assertEqual(InferenceProfile().num_predict, 512)
        self.assertEqual(deep_profile().num_predict, 2048)
        self.assertEqual(deep_profile().num_ctx, InferenceProfile().num_ctx)
    def test_unbounded_tokens_rejected(self):
        for value in (-2, -1, 0, 31, 2049, True, 999999, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError): InferenceProfile(num_predict=value)
    def test_output_and_template_reserve(self):
        with self.assertRaises(ValueError): InferenceProfile(num_ctx=1024,num_predict=512)
        self.assertEqual(InferenceProfile().input_byte_limit,7168)
    def test_context_budget_rejected(self):
        for value in (-1, 0, True, 999999):
            with self.subTest(value=value), self.assertRaises(ValueError): InferenceProfile(num_ctx=value)
    def test_nonfinite_settings(self):
        for value in (float('inf'), float('nan'), -1, True):
            with self.subTest(value=value), self.assertRaises(ValueError): InferenceProfile(temperature=value)
    def test_timeout_bounds(self):
        for value in (0, -1, 601, True, float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError): InferenceProfile(timeout_seconds=value)
    def test_history_whole_pairs(self):
        with self.assertRaises(ValueError): InferenceProfile(max_history_messages=3)
    def test_invalid_config_switch(self):
        with self.assertRaises(ValueError): Settings(adaptive_workloads='yes')
    def test_invalid_config_profile(self):
        with self.assertRaises(ValueError): Settings(standard_inference_profile={'shell':True})
    def test_options_exact(self):
        self.assertEqual(set(InferenceProfile().options), {'num_predict','num_ctx','temperature'})

    def http(self):
        response = Mock()
        response.read.return_value = json.dumps({'message':{'content':'public answer'}}).encode()
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        return response, context

    def test_options_and_timeout_forwarded(self):
        provider = OllamaProvider(settings.ollama_base_url, settings.ollama_model, timeout=12)
        profile = InferenceProfile(num_predict=64, num_ctx=2048, timeout_seconds=34, temperature=0.2)
        _, response = self.http()
        with patch('friday.providers.ollama.urllib.request.urlopen', return_value=response) as request:
            with provider.inference_profile(profile): provider.chat([{'role':'user','content':'public'}])
        payload = json.loads(request.call_args.args[0].data)
        self.assertEqual(payload['options'], profile.options)
        self.assertEqual(request.call_args.kwargs['timeout'], 34)
        self.assertEqual(payload['model'], 'qwen3:4b')
        self.assertIsNone(provider._profile)
    def test_selected_profile_output_budgets_forwarded(self):
        provider = OllamaProvider(settings.ollama_base_url, settings.ollama_model)
        for profile, budget in ((standard_profile(), 768), (deep_profile(), 2048)):
            with self.subTest(budget=budget):
                _, response = self.http()
                with patch('friday.providers.ollama.urllib.request.urlopen', return_value=response) as request:
                    with provider.inference_profile(profile):
                        provider.chat([{'role':'user','content':'public'}])
                payload = json.loads(request.call_args.args[0].data)
                self.assertEqual(payload['options']['num_predict'], budget)
                self.assertEqual(payload['options'], profile.options)

    def test_intent_uses_selected_profile_budget_and_preserves_contract(self):
        provider = OllamaProvider(settings.ollama_base_url, settings.ollama_model)
        for profile, budget in ((standard_profile(), 768), (deep_profile(), 2048),
                                (InferenceProfile(num_predict=64), 64)):
            with self.subTest(budget=budget):
                _, response = self.http()
                with patch('friday.providers.ollama.urllib.request.urlopen', return_value=response) as request:
                    with provider.intent_mode(), provider.inference_profile(profile):
                        provider.chat([{'role':'user','content':'public'}])
                payload = json.loads(request.call_args.args[0].data)
                self.assertEqual(payload['options'], {**profile.options, 'temperature': 0})
                self.assertEqual(payload['options']['num_predict'], budget)
                self.assertFalse(payload['think'])
                self.assertEqual(payload['format'], 'json')

    def test_intent_default_budget_without_profile(self):
        provider = OllamaProvider(settings.ollama_base_url, settings.ollama_model)
        _, response = self.http()
        with patch('friday.providers.ollama.urllib.request.urlopen', return_value=response) as request:
            with provider.intent_mode():
                provider.chat([{'role':'user','content':'public'}])
        payload = json.loads(request.call_args.args[0].data)
        self.assertEqual(payload['options'], {'num_predict':512})
        self.assertFalse(payload['think'])
        self.assertEqual(payload['format'],'json')
    def test_provider_profile_restores_on_failure(self):
        provider = OllamaProvider(settings.ollama_base_url, settings.ollama_model)
        with patch('friday.providers.ollama.urllib.request.urlopen', side_effect=TimeoutError()):
            with self.assertRaises(ProviderError), provider.inference_profile(deep_profile()):
                provider.chat([{'role':'user','content':'public'}])
        self.assertIsNone(provider._profile)
    def test_transport_limit(self):
        provider = OllamaProvider(settings.ollama_base_url, settings.ollama_model)
        response, context = self.http()
        response.read.return_value = b'x'*262145
        with patch('friday.providers.ollama.urllib.request.urlopen',return_value=context):
            with self.assertRaises(ProviderError), provider.inference_profile(InferenceProfile()):
                provider.chat([{'role':'user','content':'public'}])
        response.read.assert_called_once_with(262145)
    def test_unknown_provider_option_rejected(self):
        with self.assertRaises(TypeError): InferenceProfile(shell=True)


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.history = [{'role':role,'content':f'{role}-{index}'} for index in range(5) for role in ('user','assistant')]
        self.system = lambda recent: {'role':'system','content':'public system'}
    def test_recent_complete_pairs(self):
        selected = select_context(self.history,'current',InferenceProfile(max_history_messages=4),self.system)
        self.assertEqual(selected[1:5],self.history[-4:])
        self.assertEqual(selected[-1]['content'],'current')
    def test_byte_budget_drops_whole_turns(self):
        history = [{'role':role,'content':'x'*1500} for role in ('user','assistant')]
        selected = select_context(history,'current',InferenceProfile(max_context_bytes=2048),self.system)
        self.assertEqual(len(selected),2)
    def test_file_snapshot_is_not_silently_truncated(self):
        snapshot = 'public verified data'*200
        selected = select_context(self.history,'explain',InferenceProfile(),self.system,temporary=snapshot)
        self.assertEqual(selected[-2]['content'].split('\n',1)[1],snapshot)
    def test_mandatory_overflow_fails(self):
        with self.assertRaises(ProviderError):
            select_context([], 'x'*4000,InferenceProfile(max_context_bytes=2048),self.system)
    def test_file_overflow_fails_without_shortening(self):
        with self.assertRaises(ProviderError):
            select_context([], 'explain',InferenceProfile(max_context_bytes=2048),self.system,temporary='x'*4000)
    def test_orphan_reply_not_retained(self):
        selected = select_context([{'role':'assistant','content':'orphan'}], 'current',InferenceProfile(),self.system)
        self.assertEqual(len(selected),2)
    def test_invalid_text_encoding_denied(self):
        with self.assertRaises(ProviderError):
            select_context([], 'bad\ud800',InferenceProfile(),self.system)
    def test_input_not_mutated(self):
        before = json.dumps(self.history)
        select_context(self.history,'current',InferenceProfile(max_history_messages=2),self.system)
        self.assertEqual(json.dumps(self.history),before)
    def test_system_annotation_recomputed(self):
        builder = lambda recent: {'role':'system','content':str(len(recent))}
        selected = select_context(self.history,'current',InferenceProfile(max_history_messages=2),builder)
        self.assertEqual(selected[0]['content'],'2')


class AdaptiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.project, self.downloads = self.home/'FRIDAY', self.home/'Downloads'
        self.project.mkdir()
        (self.downloads/'portfolio').mkdir(parents=True)
        (self.downloads/'portfolio'/'data.js').write_text('PUBLIC_PRIVATE_CONTEXT_MARKER_6D')
        (self.downloads/'portfolio'/'portfolio.zip').write_bytes(b'PK\x00fixture')
        env = patch.dict(os.environ,{'HOME':str(self.home),'XDG_CONFIG_HOME':str(self.home/'.config')})
        env.start()
        self.addCleanup(env.stop)
        self.config = replace(settings,project_root=self.project,database_path=self.project/'memory.db',adaptive_workloads=True)
        self.approval = Mock()
        self.approval.request.return_value = FolderDecision.ALLOW_ONCE
        self.manager,self.router = create_tool_runtime(self.config,filesystem_approval=self.approval)
        self.provider = RecordingProvider()
        self.memory = MemoryManager(self.config.database_path)
        self.addCleanup(self.memory.close)
        self.assistant = FridayAssistant(self.provider,self.config.system_prompt,memory=self.memory,
            tool_router=self.router,tool_manager=self.manager,workload_configuration=self.config)
        self.addCleanup(self.assistant.model_manager.close)
        self.addCleanup(self.assistant.end_session)
    def browse(self):
        self.assistant.respond('list downloads')
        self.assistant.respond('open portfolio')
    def test_l0_no_model_tool_permission_or_memory(self):
        with patch.object(self.manager,'execute') as tool, patch.object(self.memory,'save_turn') as save:
            self.assertIn('Hello',self.assistant.respond('hello friday'))
            tool.assert_not_called()
            save.assert_not_called()
        self.approval.request.assert_not_called()
        self.assertEqual(self.provider.calls,0)
        self.assertEqual(self.assistant.last_performance.level,'L0')
        self.assertEqual(self.assistant.last_performance.routing_ns,0)
    def test_thanks_offline(self):
        self.provider.failure=ProviderError('offline')
        self.assertIn('welcome',self.assistant.respond('thank you'))
        self.assertEqual(self.provider.calls,0)
    def test_mixed_greeting_not_swallowed(self):
        self.assistant.respond('hello, list downloads')
        self.assertNotEqual(self.assistant.last_performance.level,'L0')
        self.assertEqual(self.provider.calls,1)
    def test_l1_uses_toolmanager_and_approval(self):
        with patch.object(self.manager,'execute',wraps=self.manager.execute) as tool:
            self.assistant.respond('list downloads')
            tool.assert_called_once()
        self.approval.request.assert_called_once()
        self.assertEqual(self.provider.calls,0)
        self.assertEqual(self.assistant.last_performance.level,'L1')
    def test_known_file_light(self):
        self.browse()
        self.assertIn('PUBLIC_PRIVATE_CONTEXT_MARKER_6D',self.assistant.respond('open data.js'))
        self.assertEqual(self.assistant.last_performance.level,'L1')
        self.assertEqual(self.provider.calls,0)
        self.assertEqual(self.approval.request.call_count,3)
    def test_list_current_folder_fresh_permission(self):
        self.browse()
        self.assistant.respond('list this folder')
        self.assertEqual(self.approval.request.call_count,3)
        self.assertEqual(self.assistant.last_performance.level,'L1')
        self.assertEqual(self.provider.calls,0)
    def test_l2_standard_profile(self):
        self.assistant.respond('explain Python decorators')
        self.assertEqual(self.assistant.last_performance.level,'L2')
        self.assertEqual(self.provider.profiles[-1],self.config.standard_inference_profile)
        self.assertEqual(self.provider.calls,1)
    def test_l3_deep_profile_one_call(self):
        self.assistant.respond('think deeply about this architecture')
        self.assertEqual(self.assistant.last_performance.level,'L3')
        self.assertEqual(self.provider.profiles[-1],self.config.deep_inference_profile)
        self.assertEqual(self.provider.calls,1)
    def test_hybrid_uses_standard_profile(self):
        self.assistant.respond('Can you inspect my downloads folder?')
        self.assertEqual(self.provider.profiles[-1],self.config.standard_inference_profile)
        self.assertEqual(self.provider.calls,1)
    def test_denial_no_fallback(self):
        self.approval.request.return_value=FolderDecision.DENY
        self.assertIn('permission denied',self.assistant.respond('list downloads'))
        self.assertEqual(self.provider.calls,0)
        self.assertIsNone(self.assistant.navigation.current)
    def test_parent_once_does_not_authorize_read(self):
        self.browse()
        self.approval.request.return_value=FolderDecision.DENY
        self.assertIn('permission denied',self.assistant.respond('open data.js'))
        self.assertEqual(self.approval.request.call_count,3)
        self.assertEqual(self.provider.calls,0)
    def test_sensitive_path_still_denied(self):
        self.assertIn('FAILED',self.assistant.respond('read ~/.ssh/id_rsa'))
        self.approval.request.assert_not_called()
        self.assertEqual(self.provider.calls,0)
    def test_symlink_still_blocked(self):
        (self.downloads/'link').symlink_to(self.downloads/'portfolio',target_is_directory=True)
        self.assistant.respond('list downloads')
        self.assertIn('symlinks',self.assistant.respond('open link'))
        self.assertEqual(self.provider.calls,0)
    def test_zip_stays_unsupported(self):
        self.browse()
        self.assertIn('Archive browsing',self.assistant.respond('open portfolio.zip'))
        self.assertEqual(self.provider.calls,0)
    def test_back_home_still_light(self):
        self.browse()
        self.assistant.respond('go back')
        self.assertEqual(self.assistant.navigation.current.path,str(self.downloads))
        self.assistant.respond('go home')
        self.assertEqual(self.assistant.navigation.current.path,str(self.project))
        self.assertEqual(self.assistant.last_performance.level,'L1')
    def test_persistent_grant_does_not_grant_write(self):
        from friday.tools.models import ToolRequest
        self.approval.request.return_value=FolderDecision.ALLOW_PERSISTENT
        self.browse()
        self.assistant.respond('open data.js')
        self.assertEqual(self.approval.request.call_count,1)
        result=self.manager.execute(ToolRequest('write_file',{'path':str(self.downloads/'new.txt'),'content':'no'}))
        self.assertFalse(result.success)
    def test_model_output_cannot_authorize_l2(self):
        self.provider.answer='{"kind":"tool","tool_name":"read_file","permission_granted":true}'
        with patch.object(self.manager,'execute') as tool:
            self.assistant.respond('explain Python decorators')
            tool.assert_not_called()
        self.approval.request.assert_not_called()
    def test_model_output_cannot_authorize_l3(self):
        self.provider.answer='{"kind":"tool","tool_name":"write_file","permission_granted":true}'
        with patch.object(self.manager,'execute') as tool:
            self.assistant.respond('think deeply about this architecture')
            tool.assert_not_called()
        self.approval.request.assert_not_called()
    def test_deep_mixed_extensionless_read_refused(self):
        self.assertIn('does not authorize',self.assistant.respond('think deeply and read notes'))
        self.assertEqual(self.provider.calls,0)
        self.approval.request.assert_not_called()
    def test_deep_mixed_read_does_not_bypass(self):
        self.browse()
        self.approval.request.return_value=FolderDecision.DENY
        self.assertIn('does not authorize',self.assistant.respond('think deeply and read data.js'))
        self.assertEqual(self.provider.calls,0)
        self.assertEqual(self.approval.request.call_count,2)
    def test_verified_file_explanation_private(self):
        self.browse()
        self.assistant.respond('open data.js')
        self.assistant.respond('explain this code')
        self.assertIn('PUBLIC_PRIVATE_CONTEXT_MARKER_6D',json.dumps(self.provider.messages))
        self.assertEqual(self.assistant.last_performance.level,'L2')
        self.assertEqual(self.memory.get_recent_messages(100),[])
        self.assertEqual(self.assistant.model_manager.last_job.messages,[])
        self.assertNotIn('PUBLIC_PRIVATE_CONTEXT_MARKER_6D',json.dumps(self.assistant.last_performance.public()))
    def test_just_read_reference_uses_snapshot(self):
        self.browse()
        self.assistant.respond('read data.js')
        self.assistant.respond('explain the code I just read')
        self.assertIn('PUBLIC_PRIVATE_CONTEXT_MARKER_6D',json.dumps(self.provider.messages))
        self.assertEqual(self.provider.calls,1)
    def test_deep_snapshot_not_reread(self):
        self.browse()
        self.assistant.respond('read data.js')
        with patch.object(self.manager,'execute') as tool:
            self.assistant.respond('think deeply about this code')
            tool.assert_not_called()
        self.assertIn('PUBLIC_PRIVATE_CONTEXT_MARKER_6D',json.dumps(self.provider.messages))
        self.assertEqual(self.assistant.last_performance.level,'L3')
        self.assertEqual(self.memory.get_recent_messages(100),[])
    def test_metrics_exact_counts_redacted(self):
        self.assistant.respond('explain Python decorators')
        metrics=self.assistant.last_performance.public()
        self.assertEqual(metrics['model_invocations'],1)
        self.assertGreaterEqual(metrics['total_response_ns'],metrics['model_request_ns'])
        self.assertGreaterEqual(metrics['python_cpu_ns'],0)
        self.assertNotIn(str(self.home),json.dumps(metrics))
        self.assertNotIn('decorators',json.dumps(metrics))
        self.assertNotIn('permission',json.dumps(metrics))
    def test_explicit_explanation_has_one_outer_metric(self):
        self.browse()
        self.assistant.respond('explain data.js')
        self.assertEqual(self.assistant.last_performance.level, 'L2')
        self.assertEqual(self.assistant.last_performance.model_invocations, 1)
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(self.memory.get_recent_messages(100), [])
    def test_unavailable_rss_does_not_break_response(self):
        with patch('friday.core.assistant.resource.getrusage',side_effect=OSError('private diagnostic')):
            self.assertIn('Hello',self.assistant.respond('hello friday'))
        self.assertIsNone(self.assistant.last_performance.python_peak_rss_kib)
        self.assertEqual(self.provider.calls,0)
    def test_invalid_request_encoding_no_model(self):
        with self.assertRaises(ProviderError): self.assistant.respond('explain \ud800')
        self.assertEqual(self.provider.calls,0)
        self.assertEqual(self.memory.get_recent_messages(100),[])
    def test_metrics_count_failure(self):
        self.provider.failure=ProviderError('timeout')
        with self.assertRaises(ProviderError): self.assistant.respond('explain Python decorators')
        self.assertEqual(self.assistant.last_performance.model_invocations,1)
        self.assertEqual(self.provider.calls,1)
        self.assertEqual(self.memory.get_recent_messages(100),[])
    def test_failure_navigation_unchanged(self):
        self.browse()
        before=self.assistant.navigation.current
        self.provider.failure=ProviderError('offline')
        with self.assertRaises(ProviderError): self.assistant.respond('think deeply about architecture')
        self.assertEqual(self.assistant.navigation.current,before)
    def test_profile_mode_enters_inside_synchronization(self):
        state={'inside':False}
        class Gate:
            def __enter__(self): state['inside']=True
            def __exit__(self,*args): state['inside']=False
        @contextmanager
        def profile_mode(profile):
            self.assertTrue(state['inside'])
            yield
            self.assertTrue(state['inside'])
        self.provider.inference_profile=profile_mode
        with patch.object(self.assistant.model_manager,'synchronization',Gate()):
            self.assistant.respond('explain Python decorators')
        self.assertFalse(state['inside'])
    def test_unsupported_provider_fails_closed(self):
        self.provider.supports_inference_profiles=False
        with self.assertRaisesRegex(ProviderError,'does not support'):
            self.assistant.respond('explain Python decorators')
        self.assertEqual(self.provider.calls,0)
    def test_intent_budget_checked_before_provider(self):
        self.assistant.workload_configuration=replace(self.config,
            standard_inference_profile=InferenceProfile(max_context_bytes=2048))
        request='Can you inspect my downloads folder? ' + 'x'*2500
        self.assertIn('failed safely',self.assistant.respond(request))
        self.assertEqual(self.provider.calls,0)
        self.approval.request.assert_not_called()
    def test_classifier_failure_not_fallback(self):
        with patch('friday.core.assistant.classify',side_effect=ValueError('private path')):
            with self.assertRaisesRegex(ProviderError,'selection failed safely'):
                self.assistant.respond('list downloads')
        self.assertEqual(self.provider.calls,0)
        self.approval.request.assert_not_called()
        self.assertIsNone(self.assistant._measurement)
    def test_context_overflow_no_model(self):
        self.assertIn('too long',self.assistant.respond('explain '+ 'x'*40000))
        self.assertEqual(self.provider.calls,0)
        self.assertEqual(self.memory.get_recent_messages(100),[])
    def test_file_snapshot_overflow_not_silently_trimmed(self):
        self.browse()
        self.assistant.respond('read data.js')
        self.assistant.file_context.remember('public','x'*6000)
        self.assistant.workload_configuration=replace(self.config,standard_inference_profile=InferenceProfile(max_context_bytes=2048))
        with self.assertRaisesRegex(ProviderError,'input budget'): self.assistant.respond('explain this code')
        self.assertEqual(self.provider.calls,0)
        self.assertEqual(self.assistant.file_context.item_count,0)
    def test_context_history_limited_without_deleting_memory(self):
        for index in range(10): self.assistant.respond('conversation '+str(index))
        self.assistant.respond('conversation current')
        self.assertLessEqual(len(self.provider.messages),14)
        self.assertEqual(len(self.memory.get_recent_messages(100)),22)
    def test_oversized_model_answer_fails(self):
        self.provider.answer='x'*65537
        with self.assertRaisesRegex(ProviderError,'response budget'): self.assistant.respond('explain Python decorators')
        self.assertEqual(self.memory.get_recent_messages(100),[])
    def test_legacy_compatibility_preserved(self):
        self.assistant.adaptive_workloads=False
        self.assistant.respond('hello')
        self.assertEqual(self.provider.calls,1)
        self.assertEqual(self.provider.profiles,[])
        self.assertIsNone(self.assistant.last_performance)
    def test_shutdown_clears_context(self):
        self.browse()
        self.assistant.respond('read data.js')
        self.assistant.end_session()
        self.assertEqual(self.assistant.file_context.item_count,0)
        self.assertIsNone(self.assistant.navigation.current)


class BenchmarkTests(unittest.TestCase):
    def test_reproducible_scenarios_and_call_counts(self):
        result=benchmark.run_benchmark(samples=1)
        self.assertEqual(len(result['rows']),10)
        adaptive=[r for r in result['rows'] if r['mode']=='adaptive']
        self.assertEqual([r['level'] for r in adaptive],['L0','L1','L1','L2','L3'])
        self.assertEqual([r['model_invocations'] for r in adaptive],[0,0,0,1,1])
        self.assertEqual([r['errors'] for r in adaptive],[0]*5)
        self.assertNotIn('PUBLIC_BENCHMARK_BODY_6D',json.dumps(result))
        self.assertIn('exclude Ollama',result['limits'])
    def test_benchmark_ignores_personal_roots_and_store(self):
        configuration=replace(settings,filesystem_read_roots=('/DO_NOT_ACCESS/private',),
            filesystem_permission_store_path=Path('/DO_NOT_ACCESS/private/grants.json'), user_name='Private identity')
        with patch.object(benchmark,'settings',configuration), \
             patch.object(benchmark,'create_tool_runtime',wraps=benchmark.create_tool_runtime) as runtime:
            benchmark.run_benchmark(samples=1)
        for call in runtime.call_args_list:
            config=call.args[0]
            self.assertEqual(config.filesystem_read_roots,())
            self.assertTrue(config.filesystem_permission_store_path.is_relative_to(config.project_root))
            self.assertEqual(config.user_name,'Benchmark user')
    def test_live_samples_bounded(self):
        with self.assertRaises(ValueError): benchmark.run_benchmark(samples=3,live=True)
    def test_samples_not_unbounded(self):
        with self.assertRaises(ValueError): benchmark.run_benchmark(samples=0)


class AdaptiveCLITests(unittest.TestCase):
    def run_cli(self, inputs, *, adaptive=True, diagnostics=False):
        with tempfile.TemporaryDirectory() as temporary:
            config=replace(settings,database_path=Path(temporary)/'memory.db')
            with patch('friday.main.settings',config), patch('friday.main.OllamaProvider') as provider, \
                 patch('builtins.input',side_effect=inputs), patch('sys.stdout',new_callable=io.StringIO) as output:
                provider.return_value.chat.return_value='Public conversational answer'
                provider.return_value.supports_inference_profiles=True
                @contextmanager
                def mode(profile): yield
                provider.return_value.inference_profile=mode
                main(adaptive=adaptive,diagnostics=diagnostics,speech_backend=Mock())
                return output.getvalue(),provider.return_value.chat.call_count
    def test_adaptive_cli_greeting_zero_calls(self):
        output,calls=self.run_cli(['hello friday','quit'])
        self.assertIn('Hello, Vigneshwar!',output)
        self.assertEqual(calls,0)
        self.assertNotIn('[Workload]',output)
    def test_diagnostics_opt_in(self):
        output,calls=self.run_cli(['hello friday','quit'],diagnostics=True)
        metric=json.loads(next(line for line in output.splitlines() if line.startswith('[Workload]')).split(' ',1)[1])
        self.assertEqual(metric['level'],'L0')
        self.assertEqual(metric['model_invocations'],0)
        self.assertNotIn('hello',json.dumps(metric))
    def test_cli_standard_profile(self):
        output,calls=self.run_cli(['explain Python decorators','quit'],diagnostics=True)
        self.assertEqual(calls,1)
        self.assertIn('"level": "L2"',output)
    def test_invalid_cli_configuration_fails_safely(self):
        output,calls=self.run_cli(['quit'],adaptive='not a boolean')
        self.assertIn('configuration is invalid',output)
        self.assertEqual(calls,0)
    def test_diagnostics_require_adaptive(self):
        output,calls=self.run_cli(['quit'],adaptive=False,diagnostics=True)
        self.assertIn('require adaptive mode',output)
        self.assertEqual(calls,0)
