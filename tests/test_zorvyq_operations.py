"""Synthetic operation data only. No real diagnostics or scans execute."""
from dataclasses import replace
from pathlib import Path
import json
import os
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import Mock, patch
from zorvyq.operations.contracts import Stage, StageResult, Permission
from zorvyq.operations.registry import Registry, OPERATIONS
from zorvyq.operations.engine import Engine
from zorvyq.operations.runner import Runner
from zorvyq.operations.collector import parse
from zorvyq.operations.reporting import report, sanitize, analysis_input, export_json

class EngineTests(unittest.TestCase):
 def setUp(self):
  self.runner=Mock()
  self.runner.preview.return_value=('/mock/reviewed',)
  self.runner.run.side_effect=lambda stage,cancel,emit:StageResult(stage.stage_id,'COMPLETED',0,metrics={'count':1})
  self.engine=Engine(runner=self.runner)
 def test_registry_contracts_and_future_modules_are_unavailable(self):
  self.assertGreater(len(self.engine.registry.operations),50)
  for op in OPERATIONS:
   self.assertTrue(op.implemented);self.assertFalse(op.privileges)
   self.assertEqual(bool(op.side_effects),op.permission==Permission.NETWORK);self.assertIn('mocked',op.verification)
  future=next(k for k in self.engine.registry.operations if k.startswith('future.'))
  with self.assertRaises(ValueError):self.engine.registry.plan(future)
 def test_dry_run_executes_nothing_and_denial_is_closed(self):
  plan=self.engine.registry.plan('network.overview')
  self.assertIn('arguments',self.engine.preview(plan)['stages'][0])
  self.runner.run.assert_not_called()
  with self.assertRaises(PermissionError):self.engine.approve(plan)
  with self.assertRaises(PermissionError):self.engine.run(plan,None)
  self.runner.run.assert_not_called()
 def test_one_use_scope_and_sequential_partial_failure(self):
  plan=self.engine.registry.plan('network.overview')
  ticket=self.engine.approve(plan,confirmed=True)
  self.runner.run.side_effect=[StageResult('interfaces','COMPLETED',0,metrics={'count':1}),StageResult('routes','FAILED',1),StageResult('wifi','NOT CHECKED'),StageResult('dns','COMPLETED',0),StageResult('network-listeners','COMPLETED',0)]
  result=self.engine.run(plan,ticket)
  self.assertEqual(result['checks_completed'],['interfaces','dns','network-listeners'])
  self.assertEqual(result['check_failures'],['routes'])
  self.assertEqual(result['checks_skipped'],['wifi'])
  with self.assertRaises(PermissionError):self.engine.run(plan,ticket)
 def test_forged_command_and_privileged_permission_denied(self):
  plan=self.engine.registry.plan('network.overview')
  forged=replace(plan,stages=(Stage('bad','bad','python',('-c','bad')),))
  with self.assertRaises(ValueError):self.engine.approve(forged,confirmed=True)
  for permission in (Permission.PRIVILEGED,Permission.CHANGE,Permission.DESTRUCTIVE):
   with self.assertRaises(PermissionError):self.engine.permissions.approve(replace(plan,permission=permission),confirmed=True)
 def test_network_target_requires_exact_private_scope_and_attestation(self):
  plan=self.engine.registry.plan('network.discovery',{'target':'192.168.2.0/24','purpose':'Owner lab inventory'})
  self.assertIn('-sn',plan.stages[0].arguments)
  with self.assertRaises(PermissionError):self.engine.approve(plan,confirmed=True)
  ticket=self.engine.approve(plan,confirmed=True,authorized_target=True)
  self.engine.run(plan,ticket)
  for target in ('8.8.8.8','example.test','192.168.0.0/16','-oN','$(id)','127.0.0.1'):
   with self.subTest(target=target),self.assertRaises(ValueError):self.engine.registry.plan('network.discovery',{'target':target,'purpose':'lab'})
 def test_full_diagnosis_never_adds_network_or_privileged_work(self):
  plan=self.engine.registry.plan('system.diagnosis')
  self.assertEqual(plan.permission,Permission.LOCAL)
  self.assertNotIn('nmap',[s.tool for s in plan.stages])
  self.assertNotIn('sudo',[s.tool for s in plan.stages])
  with patch.dict('zorvyq.operations.engine.COLLECTORS',{key:lambda cancel,target:{'cpu_percent':90,'not_checked':['SMART']} for key in ('system','storage','processes','security','project')}):
   result=self.engine.run(plan,self.engine.approve(plan,confirmed=True))
  self.assertTrue(result['findings']);self.assertIsNone(result['ai_analysis'])
  self.assertIn('No historical trend',str(result['limitations']))
 def test_cancel_preserves_partial_report_and_shutdown(self):
  plan=self.engine.registry.plan('network.overview')
  def step(stage,cancel,emit):
   cancel.set();return StageResult(stage.stage_id,'CANCELLED')
  self.runner.run.side_effect=step
  result=self.engine.run(plan,self.engine.approve(plan,confirmed=True))
  self.assertEqual(result['execution_status'],'Cancelled')
  self.assertEqual(len(result['checks_skipped']),4)
  self.engine.close()
  self.assertTrue(self.engine.closed)
 def test_selected_path_scope_rejects_traversal_and_symlink_escape(self):
  with TemporaryDirectory() as temp:
   root=Path(temp)/'Projects';root.mkdir();(root/'alpha').mkdir()
   (root/'escape').symlink_to(Path(temp))
   registry=Registry(root)
   plan=registry.plan('storage.overview',{'project':str(root/'alpha')})
   self.assertEqual(plan.target,str(root/'alpha'))
   for path in (root/'escape',root/'../Projects/alpha'):
    with self.assertRaises(ValueError):registry.plan('storage.overview',{'project':str(path)})
   (root/'alpha').rmdir();(root/'alpha').symlink_to(Path(temp))
   with self.assertRaises(ValueError):registry.validate(plan)
 def test_runner_failure_still_returns_report(self):
  plan=self.engine.registry.plan('network.overview')
  self.runner.run.side_effect=RuntimeError('PRIVATE error')
  result=self.engine.run(plan,self.engine.approve(plan,confirmed=True))
  self.assertEqual(len(result['check_failures']),5)
  self.assertNotIn('PRIVATE',str(result))

class RunnerTests(unittest.TestCase):
 def setUp(self):
  self.stage=next(op for op in OPERATIONS if op.operation_id=='developer.environment').stages[0]
  fixture=patch('zorvyq.operations.runner.resolve_tool',side_effect=lambda tool:'/mock/'+tool)
  fixture.start();self.addCleanup(fixture.stop)
 def child(self,data=b'version 1\n',error=b'',returncode=0):
  child=Mock(returncode=returncode,pid=999999)
  for name,value in (('stdout',data),('stderr',error)):
   reader,writer=os.pipe();os.write(writer,value);os.close(writer)
   stream=os.fdopen(reader,'rb');setattr(child,name,stream);self.addCleanup(stream.close)
  child.poll.return_value=returncode
  return child
 def test_fixed_arguments_no_shell_and_bounded_output(self):
  child=self.child()
  with patch('zorvyq.operations.runner.subprocess.Popen',return_value=child) as start:
   result=Runner().run(self.stage,Event())
  self.assertEqual(result.status,'COMPLETED')
  self.assertFalse(start.call_args.kwargs['shell'])
  args=start.call_args.args[0]
  self.assertIn('--cpu=10',args);self.assertEqual(args[-2:],['/mock/git','--version'])
  self.assertNotIn('HOME',start.call_args.kwargs['env'])
 def test_disallowed_command_cannot_reach_subprocess(self):
  with patch('zorvyq.operations.runner.subprocess.Popen') as start:
   for stage in (Stage('x','x','python',('-c','bad')),replace(self.stage,arguments=('--help',';bad'))):
    with self.assertRaises(ValueError):Runner().run(stage,Event())
   start.assert_not_called()
 def test_nonzero_timeout_and_output_limit(self):
  with patch('zorvyq.operations.runner.subprocess.Popen',return_value=self.child(returncode=1)):
   self.assertEqual(Runner().run(self.stage,Event()).status,'FAILED')
  with patch('zorvyq.operations.runner.subprocess.Popen',return_value=self.child(b'x'*100)),patch.object(Runner,'stop') as stop:
   result=Runner().run(replace(self.stage,output_limit=32),Event())
   self.assertEqual(result.status,'OUTPUT LIMIT');self.assertEqual(len(result.stdout),32);stop.assert_called_once()
  with patch('zorvyq.operations.runner.subprocess.Popen',return_value=self.child()),patch('zorvyq.operations.runner.monotonic',side_effect=[0,9,9]),patch.object(Runner,'stop') as stop:
   self.assertEqual(Runner().run(self.stage,Event()).status,'TIMEOUT');stop.assert_called_once()
 def test_cancel_only_stops_current_owned_child(self):
  event=Mock();event.is_set.side_effect=[False,True]
  child=self.child()
  with patch('zorvyq.operations.runner.subprocess.Popen',return_value=child),patch.object(Runner,'stop') as stop:
   self.assertEqual(Runner().run(self.stage,event).status,'CANCELLED')
   stop.assert_called_once_with(child)
 def test_missing_tool_is_not_healthy(self):
  with patch('zorvyq.operations.runner.resolve_tool',return_value=None),patch('zorvyq.operations.runner.subprocess.Popen') as start:
   self.assertEqual(Runner().run(self.stage,Event()).status,'NOT CHECKED');start.assert_not_called()

class ReportTests(unittest.TestCase):
 def test_redaction_and_numeric_ai_input(self):
  plan=Registry().plan('system.health')
  result=report(plan,[StageResult('resources','COMPLETED',stdout='token=secret123 /home/alice/doc\x1b[31m',metrics={'ram_used_percent':91,'process':'PRIVATE PROCESS'})])
  self.assertNotIn('secret123',str(result));self.assertNotIn('/home/alice',str(result));self.assertNotIn('\x1b',str(result))
  normalized=analysis_input(result)
  self.assertNotIn('PRIVATE',str(normalized));self.assertNotIn('stdout',normalized)
  self.assertEqual(normalized['observations'][0]['value'],91)
 def test_structured_parsers_and_no_private_log_messages(self):
  result=parse('journal','{"PRIORITY":"3","MESSAGE":"private should never be requested"}\n')
  self.assertEqual(result['metadata_entries'],1);self.assertNotIn('private',str(result))
  with self.assertRaises(ValueError):parse('json','not JSON')
 def test_export_is_explicit_new_owner_only_file(self):
  with TemporaryDirectory() as temp:
   path=Path(temp)/'report.json'
   export_json({'token':'token=abc'},path)
   self.assertEqual(path.stat().st_mode&0o777,0o600)
   with self.assertRaises(FileExistsError):export_json({},path)
   link=Path(temp)/'link';link.symlink_to(path)
   with self.assertRaises(ValueError):export_json({},link)

class CollectorTests(unittest.TestCase):
 def test_project_collector_refuses_symlink_swap_at_open(self):
  from zorvyq.operations.collector import project
  with TemporaryDirectory() as temp:
   root=Path(temp);(root/'outside').mkdir();(root/'selected').symlink_to(root/'outside')
   with self.assertRaises(OSError):project(Event(),str(root/'selected'))
 def test_system_metrics_use_synthetic_counters_and_missing_sensors_are_not_checked(self):
  from zorvyq.operations.collector import system
  stat=iter(('cpu 100 0 0 100 0 0 0 0\n','cpu 150 0 0 150 0 0 0 0\n'))
  def read(path,limit=16384):
   if path=='/proc/stat':return next(stat)
   if path=='/proc/meminfo':return 'MemTotal: 1000 kB\nMemAvailable: 250 kB\nSwapTotal: 500 kB\nSwapFree: 300 kB\n'
   if path=='/proc/cpuinfo':return 'model name : Synthetic CPU\n'
   raise OSError()
  with patch('zorvyq.operations.collector.read',side_effect=read),patch('zorvyq.operations.collector.processes',return_value={}),patch('zorvyq.operations.collector.disk',return_value={'root_used_percent':70}),patch('zorvyq.operations.collector.Path.glob',return_value=iter(())):
   cancel=Mock();cancel.is_set.return_value=False
   result=system(cancel,'Local system metadata')
  self.assertEqual(result['cpu_percent'],50)
  self.assertEqual(result['ram_used_percent'],75)
  self.assertEqual(result['swap_used_bytes'],200*1024)
  self.assertIn('Temperature sensors',result['not_checked'])
  self.assertIn('Battery status',result['not_checked'])
 def test_selected_directory_collects_metadata_only_and_skips_hidden_files(self):
  from zorvyq.operations.collector import project
  with TemporaryDirectory() as temp:
   root=Path(temp);(root/'visible').mkdir();(root/'file.txt').write_text('PRIVATE CONTENT')
   (root/'.env').write_text('SECRET');(root/'escape').symlink_to('/tmp')
   value=project(Event(),temp)
  names={entry['name'] for entry in value['visible_entries']}
  self.assertEqual(names,{'visible','file.txt'})
  self.assertNotIn('SECRET',str(value));self.assertNotIn('PRIVATE CONTENT',str(value))
 def test_correlation_is_hypothesis_with_measured_references(self):
  value=report(Registry().plan('investigate.slow'),[StageResult('resources','COMPLETED',metrics={'ram_used_percent':95,'swap_used_bytes':1000})])
  self.assertEqual(value['hypotheses'][0]['kind'],'hypothesis')
  self.assertIn('swap_used_bytes',str(value['hypotheses'][0]['evidence_refs']))
  self.assertIn('No memory leak',value['hypotheses'][0]['limitation'])
 def test_cancel_between_approval_and_worker_start_is_preserved(self):
  engine=Engine(runner=Mock())
  plan=engine.registry.plan('network.overview');ticket=engine.approve(plan,confirmed=True)
  engine.cancel();value=engine.run(plan,ticket)
  engine.runner.run.assert_not_called()
  self.assertEqual(value['execution_status'],'Cancelled')
