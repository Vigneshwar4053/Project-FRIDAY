"""Snap exception tests: package checks and fixed argv, no real app launches."""
from contextlib import contextmanager
from copy import deepcopy
import os
import stat
from types import SimpleNamespace
from unittest.mock import Mock,patch
import unittest

from test_desktop import DesktopFixture
from friday.desktop.registry import ApplicationRegistry
from friday.desktop.snap import ReviewedSnap,PACKAGES
from friday.tools.access import FolderDecision


class SnapValidationTests(unittest.TestCase):
    def setUp(self):
        self.snap=ReviewedSnap()
        package,snap_id,publisher_id,publisher,confinement=PACKAGES['vscode']
        self.metadata={'name':package,'id':snap_id,'status':'active','type':'app','confinement':confinement,
                       'revision':'264','mounted-from':'/var/lib/snapd/snaps/code_264.snap',
                       'publisher':{'id':publisher_id,'username':publisher,'validation':'verified'},
                       'devmode':False,'ignore-validation':False}
    def test_only_two_fixed_app_only_commands(self):
        self.assertEqual(ReviewedSnap.arguments('vscode'),['run','code'])
        self.assertEqual(ReviewedSnap.arguments('firefox'),['run','firefox'])
        for app in ('files','terminal','firefox --shell','code'):
            with self.assertRaises(ValueError): ReviewedSnap.arguments(app)
        for kwargs in ({'path':'/tmp/project'},{'url':'https://github.com/'},{'path':'--shell'}):
            with self.assertRaises(ValueError): ReviewedSnap.arguments('vscode',**kwargs)
    def test_package_registration_mismatch_rejected_before_paths(self):
        for key,value in [('name','other'),('id','wrong'),('status','disabled'),('type','snapd'),
                          ('confinement','devmode'),('devmode',True),('ignore-validation',True),
                          ('revision','../../tmp'),('mounted-from','/tmp/package.snap')]:
            metadata={**self.metadata,key:value}
            with self.subTest(key=key),patch.object(self.snap,'metadata',return_value=metadata):
                with self.assertRaises(ValueError): self.snap.review('vscode')
    def test_publisher_mismatch_rejected(self):
        for key,value in [('id','other'),('username','attacker'),('validation','unproven')]:
            metadata=deepcopy(self.metadata);metadata['publisher'][key]=value
            with self.subTest(key=key),patch.object(self.snap,'metadata',return_value=metadata):
                with self.assertRaises(ValueError): self.snap.review('vscode')
    def test_untrusted_host_path_rejected(self):
        from friday.desktop.snap import administrator_path
        with patch('friday.desktop.snap.directory_descriptor') as descriptor, \
             patch('pathlib.Path.lstat',return_value=SimpleNamespace(st_uid=0,st_mode=stat.S_IFDIR|0o777)):
            descriptor.return_value.__enter__.return_value=1
            with self.assertRaises(ValueError): administrator_path('/usr/bin/snap')
    def test_unavailable_daemon_fail_closed(self):
        with patch.object(self.snap,'metadata',side_effect=OSError('Daemon unavailable.')):
            with self.assertRaises(OSError): self.snap.review('vscode')


class SnapRuntimeTests(DesktopFixture):
    def setUp(self):
        super().setUp()
        self.adapter.applications=ApplicationRegistry()
        self.native=patch.object(self.adapter.applications,'executable',side_effect=FileNotFoundError()).start()
        @contextmanager
        def prepared(app):
            with self.apps.executable(app) as native:
                yield (*native,('registered',app))
        self.reviewed=patch.object(self.adapter.snap,'executable',side_effect=prepared).start()
        self.review=patch.object(self.adapter.snap,'review',side_effect=lambda app:('registered',app)).start()
    def test_app_only_exact_once_approval_and_no_shell(self):
        for app in ('firefox','vscode'):
            result=self.invoke('launch_application',{'application_id':app})
            self.assertEqual(result.data['status'],'launch_accepted')
            argv=self.process.call_args.args[0]
            self.assertEqual(argv[1:3],['run','firefox' if app=='firefox' else 'code'])
            self.assertNotIn('shell',self.process.call_args.kwargs)
            self.assertEqual(self.process.call_args.kwargs['env']['SNAP_REEXEC'],'0')
        self.assertEqual(self.approval.request.call_count,2)
    def test_denied_no_spawn_or_q(self):
        self.approval.request.return_value=FolderDecision.DENY
        self.assertFalse(self.invoke('launch_application',{'application_id':'firefox'}).success)
        self.process.assert_not_called();self.assertEqual(self.memory.recent_work(),())
    def test_project_and_url_not_authorized_by_app_only_exception(self):
        for name,args in [('open_project',{'project_id':'friday'}),('launch_application',{'application_id':'firefox','url':'https://github.com/'})]:
            self.assertEqual(self.invoke(name,args).data['status'],'unsupported_target')
        self.process.assert_not_called();self.approval.request.assert_not_called()
    def test_metadata_change_after_approval_refused(self):
        @contextmanager
        def changed(app):
            with self.apps.executable(app) as native: yield (*native,('changed',app))
        self.approval.request.side_effect=lambda _: (setattr(self.adapter.snap,'executable',changed) or FolderDecision.ALLOW_ONCE)
        self.assertFalse(self.invoke('launch_application',{'application_id':'firefox'}).success)
        self.process.assert_not_called();self.assertEqual(self.memory.recent_work(),())
    def test_metadata_change_at_execution_refused(self):
        self.review.return_value=('changed','firefox');self.review.side_effect=None
        self.assertFalse(self.invoke('launch_application',{'application_id':'firefox'}).success)
        self.process.assert_not_called()
    def test_launch_budget_and_duplicate_q(self):
        for _ in range(4): self.assertEqual(self.invoke('launch_application',{'application_id':'firefox'}).data['status'],'launch_accepted')
        self.assertEqual(len(self.memory.recent_work()),1)
        self.assertEqual(self.invoke('launch_application',{'application_id':'firefox'}).data['status'],'launch_limit_reached')
        self.assertEqual(self.process.call_count,4);self.assertEqual(self.approval.request.call_count,4)
    def test_resume_needs_new_approval(self):
        self.invoke('launch_application',{'application_id':'firefox'})
        identifier=self.memory.recent_work()[0]['entry_id']
        self.invoke('resume_activity',{'entry_id':identifier})
        self.assertEqual(self.approval.request.call_count,2);self.assertEqual(len(self.memory.recent_work()),1)
    def test_failed_launch_no_queue(self):
        self.child.wait.return_value=1
        self.assertEqual(self.invoke('launch_application',{'application_id':'firefox'}).data['status'],'launch_failed')
        self.assertEqual(self.memory.recent_work(),())
