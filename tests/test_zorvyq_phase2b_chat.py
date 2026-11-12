import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from zorvyq.model_modes import profile
from zorvyq.preferences import Preferences
from zorvyq.security import SPECIALIST
from zorvyq.services import Residency, DesktopProvider
from friday.config.settings import Settings

class ModeTests(unittest.TestCase):
 def test_modes_are_bounded_complete_and_model_compatible(self):
  for model in ('qwen3:4b',SPECIALIST):
   profiles=[profile(model,m) for m in ('Short','Medium','Deep Analysis')]
   self.assertEqual([p.num_predict for p in profiles],[768,1024,2048])
   self.assertTrue(all(p.require_complete and not p.think for p in profiles))
   self.assertEqual(profile(model,'Short','Explain everything in detail').num_predict,2048)
 def test_persistence(self):
  with TemporaryDirectory() as temp:
   p=Path(temp)/'prefs.json';prefs=Preferences(p)
   prefs.save(selected_model=SPECIALIST,response_mode='Deep Analysis')
   self.assertEqual(Preferences(p).values['selected_model'],SPECIALIST)
   self.assertEqual(Preferences(p).values['response_mode'],'Deep Analysis')
 def test_specialist_payload_omits_unsupported_thinking_control(self):
  service=Mock(); service.request.return_value={'models':[]}
  provider=DesktopProvider(service,Settings(),SPECIALIST)
  provider.desktop_profile=profile(SPECIALIST,'Medium')
  response=Mock();response.read.return_value=json.dumps({'message':{'content':'Final answer'},'done':True,'done_reason':'stop'}).encode()
  response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=None)
  with patch('friday.providers.ollama.urllib.request.urlopen',return_value=response) as send:
   self.assertEqual(provider.chat([{'role':'user','content':'Synthetic'}]),'Final answer')
  data=json.loads(send.call_args.args[0].data)
  self.assertNotIn('think',data);self.assertEqual(data['model'],SPECIALIST)
  self.assertEqual(data['options']['num_predict'],1024)

class ResidencyTests(unittest.TestCase):
 def test_preexisting_same_model_is_not_silently_reused_and_unloaded(self):
  from friday.providers.base import ProviderError
  service=Mock();service.request.return_value={'models':[{'name':'qwen3:4b','digest':'foreign','expires_at':'future'}]}
  provider=DesktopProvider(service,Settings())
  provider.residency=Residency(service)
  with patch('friday.providers.ollama.urllib.request.urlopen') as http,self.assertRaises(ProviderError):
   provider.chat([{'role':'user','content':'Synthetic'}])
  http.assert_not_called()
 def test_exit_unloads_only_unchanged_app_lease(self):
  service=Mock(); row={'name':'qwen3:4b','digest':'abc','expires_at':'expiry','size':100}
  service.request.return_value={'models':[row]}
  tracker=Residency(service);tracker.observe('qwen3:4b')
  service.request.side_effect=[{'models':[row,{'name':'foreign'}]}, {}, {'models':[{'name':'foreign'}]}]
  tracker.release()
  self.assertIn(unittest.mock.call('/api/generate',{'model':'qwen3:4b','keep_alive':0,'stream':False}),service.request.call_args_list)
  self.assertNotIn('foreign',str(service.request.call_args_list[-2]))
 def test_changed_or_unknown_residency_never_unloaded(self):
  service=Mock();tracker=Residency(service)
  tracker.leases={'qwen3:4b':('old','expiry',100,None)}
  service.request.return_value={'models':[{'name':'qwen3:4b','digest':'new','expires_at':'expiry','size':100}]}
  tracker.release()
  self.assertTrue(all(call.args[0]=='/api/ps' for call in service.request.call_args_list))

class AnalysisTests(unittest.TestCase):
 def setUp(self):
  from zorvyq.services import Controller
  self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  root=Path(self.temp.name)
  self.controller=Controller(Mock(),Mock(),Settings(project_root=root,database_path=root/'memory.sqlite',filesystem_permission_store_path=root/'permissions/grants.json'))
  self.controller._initialize();self.addCleanup(self.controller.close)
  self.report={'operation_id':'system.health','observed_metrics':{'resources':{'ram_used_percent':91,'private':'SECRET'}},
   'checks_completed':['resources'],'checks_skipped':[],'check_failures':[],'stages':[{'stdout':'SECRET'}],'ai_analysis':None}
 def test_optional_analysis_uses_selected_model_numeric_data_and_verifiable_refs(self):
  output=json.dumps({'interpretation':'Memory use is elevated; repeat the measurement.','evidence_refs':['resources.ram_used_percent']})
  with patch.object(self.controller.service,'models',return_value={'installed':[{'name':SPECIALIST}]}),patch('zorvyq.services.DesktopProvider.chat',return_value=output) as chat:
   result=self.controller.analyze_operation(self.report,SPECIALIST,'Medium')
  self.assertEqual(result['model'],SPECIALIST)
  self.assertEqual(result['kind'],'AI hypotheses — unverified')
  self.assertNotIn('SECRET',str(chat.call_args.args[0]))
  self.assertIsNone(self.report['ai_analysis'])
 def test_bad_analysis_never_alters_deterministic_report(self):
  from friday.providers.base import ProviderError
  before=json.dumps(self.report,sort_keys=True)
  for output in ('bad',json.dumps({'interpretation':'Invented','evidence_refs':['not.real']})):
   with patch('zorvyq.services.DesktopProvider.chat',return_value=output),self.assertRaises(ProviderError):
    self.controller.analyze_operation(self.report)
  self.assertEqual(json.dumps(self.report,sort_keys=True),before)
 def test_shutdown_releases_app_owned_models_and_is_idempotent(self):
  self.controller.residency.release=Mock()
  self.controller.close();self.controller.close()
  self.controller.residency.release.assert_called_once()
  self.assertTrue(self.controller.closed)
