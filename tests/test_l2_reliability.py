"""Completion variants, conservative CPU profile and private-free metrics."""
import json
import unittest
from dataclasses import replace
from unittest.mock import MagicMock, patch

from friday.config.settings import settings
from friday.core.assistant import FridayAssistant
from friday.models.profile import InferenceProfile, standard_profile, deep_profile, STANDARD_RESPONSE_INSTRUCTIONS
from friday.providers.base import ProviderError
from friday.providers.ollama import OllamaProvider


class L2ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.provider = OllamaProvider('http://127.0.0.1:11434','qwen3:4b')
        self.response = MagicMock()
        patcher = patch('friday.providers.ollama.urllib.request.urlopen')
        self.http = patcher.start()
        self.addCleanup(patcher.stop)
        self.http.return_value.__enter__.return_value = self.response
        self.messages = [{'role':'user','content':'Public request'}]

    def reply(self, **metadata):
        self.response.read.return_value = json.dumps({'message':{'content':'Final answer'}, **metadata}).encode()

    def test_standard_headroom_does_not_become_deep(self):
        profile = settings.standard_inference_profile
        self.assertEqual(profile, standard_profile())
        self.assertEqual(profile.num_predict,768)
        self.assertLess(profile.num_predict,deep_profile().num_predict)
        self.assertFalse(profile.think)
        self.assertEqual(profile.num_ctx,8192)
        self.assertEqual(profile.max_history_messages,6)

    def test_normal_completion_at_token_budget_is_accepted(self):
        self.reply(done=True,done_reason='stop',eval_count=768)
        with self.provider.inference_profile(standard_profile()):
            self.assertEqual(self.provider.chat(self.messages),'Final answer')

    def test_normal_stop_below_budget_is_accepted(self):
        self.reply(done=True,done_reason='stop',eval_count=20)
        self.assertEqual(self.provider.chat(self.messages),'Final answer')

    def test_legacy_metadata_variants_are_accepted(self):
        for metadata in ({}, {'done':True}, {'done':True,'done_reason':''},
                         {'done':True,'done_reason':None}, {'done_reason':'stop'}):
            with self.subTest(metadata=metadata):
                self.reply(**metadata)
                self.assertEqual(self.provider.chat(self.messages),'Final answer')

    def test_length_is_truncation_even_if_done_true(self):
        self.reply(done=True,done_reason='length',eval_count=768)
        with self.assertRaisesRegex(ProviderError,'output-token limit'): self.provider.chat(self.messages)
        self.assertEqual(self.provider.last_generation_metrics['completion'],'truncated')
        self.http.assert_called_once()

    def test_length_not_repaired_by_punctuation_or_small_count(self):
        self.reply(done=True,done_reason='length',eval_count=4)
        with self.assertRaises(ProviderError): self.provider.chat(self.messages)

    def test_non_generation_and_invalid_metadata_rejected(self):
        for metadata in ({'done_reason':'load'}, {'done_reason':'unload'}, {'done_reason':True},
                         {'done_reason':{}}, {'done':False,'done_reason':'stop'}):
            self.reply(**metadata)
            with self.assertRaises(ProviderError): self.provider.chat(self.messages)

    def test_metrics_have_only_validated_scalar_values(self):
        self.reply(done=True,done_reason='stop',eval_count=40,eval_duration=2_000_000_000,
                   prompt_eval_count=10,load_duration=100,prompt_eval_duration=200,
                   unexpected_secret='PRIVATE')
        self.provider.chat(self.messages)
        metrics=self.provider.last_generation_metrics
        self.assertEqual(metrics['tokens_per_second'],20)
        self.assertEqual(metrics['output_tokens'],40)
        self.assertNotIn('PRIVATE',repr(metrics))
        self.assertNotIn('Final answer',repr(metrics))

    def test_invalid_and_missing_metrics_are_not_fabricated(self):
        self.reply(eval_count=True,eval_duration=0,load_duration=-1,prompt_eval_count='PRIVATE')
        self.provider.chat(self.messages)
        metrics=self.provider.last_generation_metrics
        for field in ('tokens_per_second','output_tokens','load_ns','prompt_tokens'):
            self.assertIsNone(metrics[field])

    def test_metrics_reset_when_next_request_fails(self):
        self.reply(eval_count=4)
        self.provider.chat(self.messages)
        self.http.side_effect=TimeoutError()
        with self.assertRaises(ProviderError): self.provider.chat(self.messages)
        self.assertIsNone(self.provider.last_generation_metrics)

    def test_thinking_presence_is_measured_without_content(self):
        self.response.read.return_value=json.dumps({'message':{'content':'Final answer','thinking':'PRIVATE'},'done_reason':'stop'}).encode()
        self.provider.chat(self.messages)
        self.assertTrue(self.provider.last_generation_metrics['thinking_present'])
        self.assertNotIn('PRIVATE',repr(self.provider.last_generation_metrics))

    def test_standard_concise_guidance_is_budgeted_and_deep_unchanged(self):
        assistant=FridayAssistant(self.provider,'Public system',workload_configuration=replace(settings,adaptive_workloads=True))
        self.reply(done=True,done_reason='stop')
        assistant.respond('explain Python decorators')
        payload=json.loads(self.http.call_args.args[0].data)
        self.assertIn(STANDARD_RESPONSE_INSTRUCTIONS,payload['messages'][0]['content'])
        self.assertEqual(payload['options']['num_predict'],768)
        self.assertNotIn('stop',payload['options'])
        assistant.respond('think deeply about recursion')
        payload=json.loads(self.http.call_args.args[0].data)
        self.assertNotIn(STANDARD_RESPONSE_INSTRUCTIONS,payload['messages'][0]['content'])
        self.assertTrue(payload['think'])
        self.assertEqual(payload['options']['num_predict'],2048)
        assistant.model_manager.close()

    def test_live_harness_rejects_unbounded_samples(self):
        from phase6d_l2_benchmark import run
        for samples in (0,3,True):
            with self.assertRaises(ValueError): run(samples)

    def test_live_harness_uses_gate_only_inside_manager(self):
        from phase6d_l2_benchmark import run
        self.reply(done=True,done_reason='stop',eval_count=5,eval_duration=1000)
        with patch('phase6d_l2_benchmark.OllamaProvider',return_value=self.provider):
            report=run(1,baseline=True)
        self.assertEqual(len(report['rows']),4)
        for row in report['rows']:
            self.assertEqual(row['status'],'success')
            self.assertEqual(row['model_calls'],1)
            self.assertEqual(row['metrics']['output_tokens'],5)
        self.assertEqual(self.http.call_count,4)
        self.assertNotIn('Final answer',repr(report))
