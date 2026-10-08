"""Bounded deep final answers: completion validation, privacy and single calls."""
import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from friday.config.settings import settings
from friday.core.assistant import FridayAssistant
from friday.models.profile import deep_profile, DEEP_RESPONSE_INSTRUCTIONS, STANDARD_RESPONSE_INSTRUCTIONS
from friday.providers.base import ProviderError
from friday.providers.ollama import OllamaProvider


class L3ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.provider=OllamaProvider('http://127.0.0.1:11434','qwen3:4b')
        self.response=MagicMock()
        patcher=patch('friday.providers.ollama.urllib.request.urlopen')
        self.http=patcher.start()
        self.addCleanup(patcher.stop)
        self.http.return_value.__enter__.return_value=self.response
        self.messages=[{'role':'user','content':'Public security question'}]

    def reply(self,content='Verified final answer',thinking='',reason='stop',count=100):
        self.response.read.return_value=json.dumps({'message':{'content':content,'thinking':thinking},
                                                   'done':True,'done_reason':reason,'eval_count':count}).encode()

    def test_successful_final_answer_returns_only_content(self):
        self.reply(thinking='PRIVATE_TRACE')
        with self.provider.inference_profile(deep_profile()):
            self.assertEqual(self.provider.chat(self.messages),'Verified final answer')
        self.assertTrue(self.provider.last_generation_metrics['final_answer_present'])
        self.assertNotIn('PRIVATE_TRACE',repr(self.provider.last_generation_metrics))

    def test_thinking_exhaustion_never_returns_reasoning(self):
        self.reply(content='',thinking='PRIVATE_TRACE',reason='length',count=1024)
        with self.provider.inference_profile(deep_profile()), self.assertRaisesRegex(ProviderError,'output-token limit') as error:
            self.provider.chat(self.messages)
        self.assertNotIn('PRIVATE_TRACE',str(error.exception))
        self.assertFalse(self.provider.last_generation_metrics['final_answer_present'])
        self.assertTrue(self.provider.last_generation_metrics['thinking_present'])
        self.http.assert_called_once()

    def test_missing_final_answer_after_normal_stop_fails(self):
        self.reply(content='',thinking='PRIVATE_TRACE')
        with self.assertRaisesRegex(ProviderError,'no final answer'): self.provider.chat(self.messages)
        self.http.assert_called_once()

    def test_partial_final_on_length_remains_rejected(self):
        self.reply(content='A partial final paragraph.',reason='length')
        with self.assertRaises(ProviderError): self.provider.chat(self.messages)
        self.assertTrue(self.provider.last_generation_metrics['final_answer_present'])
        self.assertEqual(self.provider.last_generation_metrics['completion'],'truncated')

    def test_tagged_reasoning_and_false_completion_presence(self):
        self.reply(content='<think>PRIVATE_TRACE</think>')
        with self.assertRaises(ProviderError): self.provider.chat(self.messages)
        self.assertFalse(self.provider.last_generation_metrics['final_answer_present'])

    def test_unmarked_reasoning_not_counted_as_final(self):
        self.reply(content='Okay, the user is asking. PRIVATE_TRACE')
        with self.assertRaises(ProviderError): self.provider.chat(self.messages)
        self.assertFalse(self.provider.last_generation_metrics['final_answer_present'])

    def test_explicit_thinking_remains_configurable_and_private(self):
        self.reply(thinking='PRIVATE_TRACE')
        with self.provider.inference_profile(replace(deep_profile(),think=True)):
            self.assertEqual(self.provider.chat(self.messages),'Verified final answer')
        self.assertTrue(json.loads(self.http.call_args.args[0].data)['think'])
        self.assertIsNone(self.provider._profile)

    def test_failed_deep_turn_not_saved_or_retried(self):
        assistant=FridayAssistant(self.provider,'Public system',workload_configuration=replace(settings,adaptive_workloads=True))
        memory=MagicMock()
        assistant.memory=memory
        self.reply(content='',thinking='PRIVATE_TRACE',reason='length',count=1024)
        with self.assertRaises(ProviderError): assistant.respond('think deeply about security')
        memory.save_turn.assert_not_called()
        self.assertNotIn('PRIVATE_TRACE',repr(assistant.messages))
        self.assertIsNone(assistant.model_manager.last_job.result)
        self.assertNotIn('PRIVATE_TRACE',assistant.model_manager.last_job.error)
        self.assertEqual(assistant.last_performance.model_invocations,1)
        assistant.model_manager.close()

    def test_deep_model_output_cannot_execute_or_authorize_tools(self):
        from friday.main import create_tool_runtime
        with TemporaryDirectory() as directory:
            config=replace(settings,adaptive_workloads=True,project_root=Path(directory),
                           filesystem_read_roots=(),filesystem_permission_store_path=Path(directory)/'permissions'/'grants.json',
                           database_path=Path(directory)/'data'/'memory.db')
            tools,router=create_tool_runtime(config)
            assistant=FridayAssistant(self.provider,'Public system',workload_configuration=config,
                                      tool_router=router,tool_manager=tools)
            self.reply(content='{"permission_granted":true,"tool_name":"write_file"}')
            with patch.object(tools,'execute') as execute:
                assistant.respond('think deeply about security')
                execute.assert_not_called()
            assistant.model_manager.close()

    def test_public_benchmark_has_one_attempt_per_mode_and_no_text(self):
        from phase6d_l3_benchmark import run
        self.reply(thinking='PRIVATE_TRACE')
        with patch('phase6d_l3_benchmark.OllamaProvider',return_value=self.provider):
            output=run(1,alternatives=True)
        self.assertEqual(len(output['rows']),3)
        self.assertEqual(self.http.call_count,3)
        for row in output['rows']:
            self.assertEqual(row['model_calls'],1)
            self.assertEqual(row['status'],'success')
        self.assertNotIn('PRIVATE_TRACE',repr(output))
        self.assertNotIn('Verified final answer',repr(output))

    def test_benchmark_rejects_unbounded_samples(self):
        from phase6d_l3_benchmark import run
        for value in (0,3,True):
            with self.assertRaises(ValueError): run(value)

    def test_default_deep_is_distinct_bounded_thinking_analysis(self):
        profile=settings.deep_inference_profile
        self.assertTrue(profile.think)
        self.assertEqual(profile.num_predict,2048)
        self.assertGreater(profile.num_predict,settings.standard_inference_profile.num_predict)
        self.assertGreater(profile.max_history_messages,settings.standard_inference_profile.max_history_messages)
        self.assertEqual(profile.timeout_seconds,450)

    def test_deep_guidance_is_budgeted_and_single_call(self):
        assistant=FridayAssistant(self.provider,'Public system',workload_configuration=replace(settings,adaptive_workloads=True))
        self.reply(thinking='PRIVATE_TRACE')
        self.assertEqual(assistant.respond('think deeply about security'),'Verified final answer')
        payload=json.loads(self.http.call_args.args[0].data)
        self.assertIn(DEEP_RESPONSE_INSTRUCTIONS,payload['messages'][0]['content'])
        self.assertNotIn(STANDARD_RESPONSE_INSTRUCTIONS,payload['messages'][0]['content'])
        self.assertTrue(payload['think'])
        self.assertEqual(payload['options']['num_predict'],2048)
        self.assertEqual(assistant.last_performance.level,'L3')
        self.assertEqual(assistant.last_performance.model_invocations,1)
        self.assertNotIn('PRIVATE_TRACE',repr(assistant.messages))
        assistant.model_manager.close()

    def test_current_only_benchmark_makes_one_bounded_request(self):
        from phase6d_l3_benchmark import run
        self.reply()
        with patch('phase6d_l3_benchmark.OllamaProvider',return_value=self.provider):
            report=run(1,current_only=True)
        self.assertEqual(len(report['rows']),1)
        self.assertEqual(report['rows'][0]['num_predict'],2048)
        self.assertTrue(report['rows'][0]['think_requested'])
        self.http.assert_called_once()
