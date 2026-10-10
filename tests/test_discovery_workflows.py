"""Synthetic conversational references and plans; all GUI/process launch mocked."""
from dataclasses import replace
from pathlib import Path
import time
from unittest.mock import patch
import unittest
from test_desktop import DesktopFixture
from friday.desktop.routing import DesktopIntentResolver
from friday.tools.discovery import TargetDiscovery
from friday.tools.access import FilesystemAccess
from friday.tools.filesystem import FileSystemPolicy
from friday.tools.grants import PermissionStore
from friday.tools.router import ToolRouter
from friday.desktop.workflows import WorkflowAction, WorkflowPlan, WorkflowStep, parse_workflow, website
from friday.tools.access import FolderDecision
from friday.tools.discovery import NO_REFERENCE
from friday.tools.models import ToolRequest


class DiscoveryWorkflowFixture(DesktopFixture):
    def setUp(self):
        super().setUp()
        self.store=PermissionStore(self.root/'permissions/grants.json',self.adapter.sensitive)
        self.boundary=FileSystemPolicy([self.project],grant_store=self.store)
        self.access=FilesystemAccess(self.boundary,self.store,self.approval)
        self.discovery=TargetDiscovery(self.access,self.adapter.projects,self.adapter.locations)
        self.adapter.discovery=self.discovery
        self.router=ToolRouter(self.project,desktop_resolver=DesktopIntentResolver(self.apps,self.adapter.recent,None,self.discovery))
        self.portfolio=self.project/'portfolio';self.portfolio.mkdir()

    def command(self,text):
        route=self.router.route(text)
        self.assertTrue(route.matched)
        return self.invoke(route.tool_name,dict(route.arguments))

    def file(self):
        directory=self.home/'Downloads/portfolio';directory.mkdir()
        item=directory/'data.js';item.write_text('NEVER_READ_PRIVATE_CONTENT')
        return item



class ReferenceTests(DiscoveryWorkflowFixture):
    def test_find_file_open_that_fresh_exact_permission_no_read(self):
        item=self.file()
        self.command('find data.js in downloads')
        self.assertEqual(self.approval.request.call_count,1)
        self.assertEqual(self.discovery.reference.path,str(item))
        assistant,provider=self.assistant()
        with patch.object(self.manager,'execute',wraps=self.manager.execute) as execute:
            response=assistant.respond('open that')
            self.assertEqual(execute.call_args.args[0].tool_name,'discovery_selection')
        self.assertIn('Launch',response)
        self.assertNotIn('NEVER_READ_PRIVATE_CONTENT',response)
        self.assertEqual(self.approval.request.call_count,2)
        self.assertIn(str(item),self.approval.request.call_args.args[0].target)
        self.assertEqual(self.store.load(),())
        self.assertEqual(self.memory.recent_work(),())
        provider.chat.assert_not_called()

    def test_directory_open_it_uses_existing_destination_selection(self):
        self.command('find portfolio')
        result=self.command('open it')
        self.assertEqual(result.data['status'],'needs_selection')
        self.process.assert_not_called()
        self.assertEqual(self.command('2').data['status'],'launch_accepted')
        self.assertIn(str(self.portfolio),self.approval.request.call_args.args[0].target)

    def test_open_its_folder_exact_parent_not_file(self):
        item=self.file();self.command('find data.js in downloads')
        result=self.command('open its folder')
        self.assertEqual(result.data['status'],'launch_accepted')
        self.assertIn(str(item.parent),self.approval.request.call_args.args[0].target)
        self.assertNotIn('data.js',self.approval.request.call_args.args[0].target)
        self.assertEqual(self.approval.request.call_count,2)

    def test_parent_is_original_scope_root(self):
        item=self.home/'Downloads/data.js';item.write_text('synthetic')
        self.command('find data.js in downloads')
        self.assertEqual(self.command('open its folder').data['status'],'launch_accepted')

    def test_show_file_in_files_does_not_substitute_parent(self):
        self.file();self.command('find data.js in downloads')
        result=self.command('show that in files')
        self.assertEqual(result.data['status'],'unsupported_target')
        self.assertIn('open its folder',result.data['message'])
        self.process.assert_not_called()

    def test_show_directory_in_files(self):
        self.command('find portfolio')
        self.assertEqual(self.command('show that in files').data['status'],'launch_accepted')

    def test_multiple_results_clarify_before_action(self):
        (self.project/'nested/portfolio').mkdir(parents=True)
        self.command('find portfolio')
        self.assertIsNone(self.discovery.reference)
        result=self.command('open that')
        self.assertEqual(result.data['status'],'needs_selection')
        self.process.assert_not_called()
        self.assertEqual(self.command('1').data['status'],'needs_selection')
        self.assertTrue(self.discovery.reference.unique)
        self.assertEqual(self.command('2').data['status'],'launch_accepted')

    def test_no_reference_cannot_search_pronoun_or_use_model(self):
        assistant,provider=self.assistant()
        for phrase in ('open that','open it','open this file','open the found file','open its folder','show that in files'):
            with patch.object(self.manager,'execute') as execute:
                self.assertEqual(assistant.respond(phrase),NO_REFERENCE)
                execute.assert_not_called()
        provider.chat.assert_not_called();self.process.assert_not_called()

    def test_missing_and_replaced_targets_invalidate_reference(self):
        for change in ('missing','replaced'):
            self.command('find portfolio')
            self.portfolio.rename(self.project/'old')
            if change=='replaced': self.portfolio.mkdir()
            result=self.command('open it')
            self.assertEqual(result.data['status'],'unavailable')
            self.assertIsNone(self.discovery.reference)
            self.process.assert_not_called()
            if change=='replaced': self.portfolio.rmdir()
            (self.project/'old').rename(self.portfolio)

    def test_modified_file_same_inode_rejected(self):
        item=self.file();self.command('find data.js in downloads')
        item.write_text('changed metadata and content')
        self.assertEqual(self.command('open that').data['status'],'unavailable')
        self.assertIsNone(self.discovery.reference);self.process.assert_not_called()

    def test_symlink_replacement_rejected(self):
        item=self.file();self.command('find data.js in downloads')
        item.rename(item.parent/'old');item.symlink_to(item.parent/'old')
        self.assertEqual(self.command('open that').data['status'],'unavailable')
        self.process.assert_not_called()

    def test_parent_replacement_same_file_inode_rejected(self):
        item=self.file();self.command('find data.js in downloads')
        item.parent.rename(item.parent.with_name('old'))
        item.parent.mkdir();(item.parent.with_name('old')/'data.js').rename(item)
        self.assertEqual(self.command('open that').data['status'],'unavailable')
        self.process.assert_not_called()

    def test_fresh_permission_denial_stops_without_action(self):
        self.file();self.command('find data.js in downloads')
        self.approval.request.return_value=FolderDecision.DENY
        self.assertFalse(self.command('open that').success)
        self.process.assert_not_called();self.assertIsNone(self.discovery.reference)

    def test_target_changed_during_approval_rejected(self):
        item=self.file();self.command('find data.js in downloads')
        def approve(_):
            item.write_text('changed during permission prompt')
            return FolderDecision.ALLOW_ONCE
        self.approval.request.side_effect=approve
        self.assertFalse(self.command('open that').success)
        self.process.assert_not_called();self.assertIsNone(self.discovery.reference)

    def test_snap_file_handoff_still_blocked(self):
        self.file();self.command('find data.js in downloads')
        self.paths['vscode'].unlink();self.apps.production=True
        result=self.command('open that')
        self.assertEqual(result.data['status'],'unsupported_target')
        self.assertIn('app-only',result.data['message']);self.assertIn('open its folder',result.data['message'])
        self.process.assert_not_called()

    def test_new_explicit_target_invalidates_and_replaces_old(self):
        self.command('find portfolio')
        self.command('find missing')
        self.assertEqual(self.router.route('open it').message,NO_REFERENCE)
        self.command('find portfolio')
        other=self.project/'second';other.mkdir()
        self.command('find second')
        self.assertEqual(self.discovery.reference.path,str(other))
        self.router.route('open downloads')
        self.assertIsNone(self.discovery.reference)

    def test_stop_and_session_exit_clear_references(self):
        assistant,provider=self.assistant()
        assistant.respond('find portfolio')
        self.assertIsNotNone(self.discovery.reference)
        assistant.respond('stop')
        self.assertIsNone(self.discovery.reference)
        assistant.respond('find portfolio');assistant.end_session()
        self.assertIsNone(self.discovery.reference)
        provider.chat.assert_not_called()

    def test_reference_expires_and_token_cannot_be_replayed(self):
        self.command('find portfolio')
        self.discovery.reference=replace(self.discovery.reference,created=time.monotonic()-121)
        self.assertEqual(self.router.route('open that').message,NO_REFERENCE)
        self.command('find portfolio')
        route=self.router.route('show that in files')
        self.invoke(route.tool_name,dict(route.arguments))
        self.assertEqual(self.invoke(route.tool_name,dict(route.arguments)).data['status'],'invalid_selection')

    def test_reference_is_per_conversation_and_not_in_sqlite(self):
        self.command('find portfolio')
        self.assertEqual(self.memory.recent_work(),())
        self.assertEqual(self.store.load(),())
        assistant,provider=self.assistant();assistant.end_session()
        self.assertEqual(self.router.route('open that').message,NO_REFERENCE)

    def test_malformed_followups_never_dispatch_paths_or_shell(self):
        self.command('find portfolio')
        assistant,provider=self.assistant()
        for text in ('open that /etc/passwd','open it --flag','open that; whoami','show that in files /tmp'):
            with patch.object(self.manager,'execute') as execute:
                self.assertIn('Unsupported',assistant.respond(text))
                execute.assert_not_called()
        provider.chat.assert_not_called();self.process.assert_not_called()

    def test_model_text_cannot_establish_reference(self):
        assistant,provider=self.assistant()
        provider.chat.return_value='Found /invented/data.js'
        assistant.respond('tell me a story')
        self.assertEqual(assistant.respond('open that'),NO_REFERENCE)
        self.assertIsNone(self.discovery.reference)
        self.process.assert_not_called()

    def test_reference_survives_unrelated_turn_and_stale_token_expires(self):
        self.command('find portfolio')
        self.router.route('hello')
        self.assertIsNotNone(self.discovery.reference)
        route=self.router.route('show that in files')
        self.discovery.receipts[route.arguments['token']]['expires']=time.monotonic()-1
        result=self.invoke(route.tool_name,dict(route.arguments))
        self.assertEqual(result.data['status'],'invalid_selection')
        self.assertIsNone(self.discovery.reference);self.process.assert_not_called()

    def test_truncated_result_not_silently_unique(self):
        (self.project/'another-entry').write_text('synthetic')
        self.discovery.MAX_ENTRIES=1
        self.command('find portfolio')
        self.assertIsNone(self.discovery.reference)
        self.process.assert_not_called()


class WorkflowTests(DiscoveryWorkflowFixture):
    def test_firefox_search_plan_preserves_query_case(self):
        plan=parse_workflow('Open Firefox and search for Physics Wallah')
        self.assertEqual(len(plan.steps),6)
        self.assertEqual(plan.steps[3].value,'Physics Wallah')
        self.assertEqual(plan.steps[3].action,WorkflowAction.SEARCH)
        self.assertEqual(plan.steps[0].capability,'supported_via_gateway')
        self.assertEqual(plan.steps[1].capability,'planned_not_executable')

    def test_recognized_exact_and_unknown_websites(self):
        self.assertEqual(parse_workflow('Open Firefox and go to YouTube').steps[3].value,'https://www.youtube.com/')
        self.assertEqual(parse_workflow('Open Firefox and go to https://example.com/help').steps[3].value,'https://example.com/help')
        for site in ('Gatewallah','unknownsite','You Tube'):
            plan=parse_workflow('Open Firefox and go to '+site)
            self.assertIsNotNone(plan.clarification)
            self.assertNotIn(site.casefold()+'.com',plan.response())
            self.assertIn('exact HTTPS URL',plan.response())

    def test_file_and_folder_compound_structures(self):
        plan=parse_workflow('Find data.js in Downloads and open it')
        self.assertEqual(plan.steps[0].value,'data.js');self.assertEqual(plan.steps[0].scope,'downloads')
        plan=parse_workflow('Open Downloads and find data.js')
        self.assertEqual(plan.steps[0].action,WorkflowAction.OPEN_FOLDER)
        self.assertEqual(plan.steps[1].scope,'downloads')
        plan=parse_workflow('Open VS Code and open my portfolio project')
        self.assertEqual(plan.steps[2].capability,'conditional_native_snap_handoff_blocked')

    def test_no_partial_execution_or_model_calls(self):
        assistant,provider=self.assistant()
        self.approval.request.return_value=FolderDecision.DENY
        for command in ('Open Firefox and search for Python tutorials',
                        'Open Firefox and go to YouTube','Open Firefox and go to Gatewallah',
                        'Find data.js in Downloads and open it','Open Downloads and find data.js',
                        'Open VS Code and open my portfolio project'):
            with patch.object(self.manager,'execute') as execute:
                response=assistant.respond(command)
                execute.assert_not_called()
                self.assertEqual(assistant.last_performance.level,'L1')
                self.assertIn('no ',response.casefold())
        self.approval.request.assert_not_called();self.process.assert_not_called();provider.chat.assert_not_called()

    def test_single_action_still_supported(self):
        self.assertEqual(self.router.route('open firefox').tool_name,'launch_application')
        self.assertEqual(self.router.route('open downloads').tool_name,'open_folder')
        self.assertEqual(self.router.route('find portfolio').tool_name,'discover_target')

    def test_injection_unknown_extra_steps_and_urls_rejected(self):
        for command in ('Open Firefox and search for Python; touch /tmp/owned',
                        'Open Firefox and search for $(whoami)',
                        'Open Firefox and search for Python and delete files',
                        'Open Downloads and find ../secret',
                        'Open Firefox and go to javascript:alert(1)',
                        'Open Firefox and go to https://user:pass@example.com/',
                        'Open Firefox and go to https://127.0.0.1/',
                        'Open Firefox and go to https://example.com:99999/'):
            route=self.router.route(command)
            self.assertTrue(route.matched)
            self.assertIsNone(route.tool_name)
            self.assertIsNotNone(route.message)
            self.process.assert_not_called()

    def test_typed_plan_bounds_and_no_dispatch_api(self):
        with self.assertRaises(ValueError): WorkflowStep('launch_application','firefox')
        with self.assertRaises(ValueError): WorkflowStep(WorkflowAction.LAUNCH,'terminal')
        with self.assertRaises(ValueError): WorkflowPlan((WorkflowStep(WorkflowAction.LAUNCH,'firefox'),)*9)
        plan=parse_workflow('Open Firefox and search for Python')
        self.assertFalse(hasattr(plan,'execute'))

    def test_compound_plan_and_stop_invalidate_old_reference(self):
        self.command('find portfolio')
        self.router.route('Open Firefox and search for Python')
        self.assertIsNone(self.discovery.reference)
        self.router.route('stop')
        self.assertEqual(self.router.route('open that').message,NO_REFERENCE)

if __name__=='__main__': unittest.main()
