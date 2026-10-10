"""Routing/handoff regression tests, synthetic paths and mocked launches only."""
from unittest.mock import patch
from test_discovery_workflows import DiscoveryWorkflowFixture
from friday.desktop.registry import ApplicationRegistry
from friday.tools.access import FolderDecision


class FileOpenTests(DiscoveryWorkflowFixture):
    def test_open_filename_is_discovery_not_read(self):
        route=self.router.route('open data.js')
        self.assertEqual(route.tool_name,'discover_target')
        self.assertEqual(dict(route.arguments),{'action':'open','name':'data.js'})
        self.assertEqual(self.router.route('read data.js').tool_name,'read_file')

    def test_matching_reference_preserves_exact_scope_and_never_reads(self):
        item=self.file();self.command('find data.js in downloads')
        with patch.object(self.discovery,'search',side_effect=AssertionError('Unexpected new search')):
            result=self.command('open data.js')
        self.assertEqual(result.data['status'],'launch_accepted')
        self.assertIn(str(item),self.approval.request.call_args.args[0].target)
        self.assertEqual(self.approval.request.call_count,2)
        self.assertNotIn('NEVER_READ_PRIVATE_CONTENT',str(result))
        self.assertEqual(self.memory.recent_work(),())

    def test_no_reference_uses_bounded_search(self):
        result=self.command('open data.js')
        self.assertEqual(result.data['status'],'not_found')
        self.assertIn('Search bounds',result.data['message'])
        self.process.assert_not_called()

    def test_ambiguous_filename_requires_selection(self):
        (self.portfolio/'data.js').write_text('synthetic')
        (self.project/'data.js').write_text('synthetic')
        result=self.command('open data.js')
        self.assertEqual(result.data['status'],'needs_selection')
        self.process.assert_not_called()

    def test_matching_missing_and_changed_reference_rejected(self):
        item=self.file();self.command('find data.js in downloads');item.write_text('changed data')
        route=self.router.route('open data.js')
        self.assertIsNone(route.tool_name);self.assertIn('changed',route.message)
        self.process.assert_not_called()

    def test_matching_filename_fresh_permission_denial(self):
        self.file();self.command('find data.js in downloads')
        self.approval.request.return_value=FolderDecision.DENY
        self.assertFalse(self.command('open data.js').success)
        self.process.assert_not_called()

    def test_snap_file_handoff_still_blocked(self):
        self.file();self.command('find data.js in downloads')
        self.adapter.applications=ApplicationRegistry()
        with patch.object(self.adapter.applications,'executable',side_effect=FileNotFoundError()):
            result=self.command('open data.js')
        self.assertEqual(result.data['status'],'unsupported_target')
        self.assertIn('open its folder',result.data['message']);self.process.assert_not_called()
        self.assertEqual(self.approval.request.call_count,1)

    def test_qualified_reference_uses_existing_vscode_target(self):
        self.command('find portfolio')
        self.assertEqual(self.command('open it in vs code').data['status'],'launch_accepted')
        self.assertIn('vscode',self.approval.request.call_args.args[0].target)

    def test_qualified_filename_matches_recent_reference(self):
        item=self.file();self.command('find data.js in downloads')
        self.assertEqual(self.command('open data.js in vs code').data['status'],'launch_accepted')
        self.assertIn(str(item),self.approval.request.call_args.args[0].target)

    def test_incomplete_discovery_does_not_become_unique_reference(self):
        self.file()
        search=self.discovery.search
        with patch.object(self.discovery,'search',side_effect=lambda *args:(search(*args)[0],True)):
            self.command('find data.js in downloads')
        result=self.command('open data.js')
        self.assertEqual(result.data['status'],'needs_selection');self.process.assert_not_called()

    def test_completed_selection_does_not_shadow_new_recent_work_menu(self):
        self.command('open portfolio');self.command('1')
        self.command('show q')
        self.assertEqual(self.command('1').data['status'],'launch_accepted')

    def test_denied_selection_stays_consumed(self):
        self.command('open portfolio');self.approval.request.return_value=FolderDecision.DENY
        self.assertFalse(self.command('1').success)
        self.assertIsNone(self.router.route('2').tool_name)
        self.assertIn('already completed',self.router.route('2').message)
        self.process.assert_not_called()

    def test_completed_selection_second_number_never_reaches_model(self):
        self.command('open portfolio');self.command('1')
        assistant,provider=self.assistant()
        result=assistant.respond('2')
        self.assertIn('already completed',result)
        provider.chat.assert_not_called();self.assertEqual(self.process.call_count,1)

    def test_blocked_selection_second_number_never_reaches_model(self):
        self.command('open portfolio');self.adapter.applications=ApplicationRegistry()
        with patch.object(self.adapter.applications,'executable',side_effect=FileNotFoundError()):
            self.assertEqual(self.command('1').data['status'],'unsupported_target')
        assistant,provider=self.assistant()
        self.assertIn('already completed',assistant.respond('2'));provider.chat.assert_not_called()
        self.process.assert_not_called()

    def test_path_and_shell_cannot_be_opened_or_read(self):
        for value in ('open /etc/passwd','open ../data.js','open data.js; touch /tmp/pwn','open data.js --shell'):
            route=self.router.route(value)
            self.assertIsNone(route.tool_name)
        self.process.assert_not_called()

    def test_compound_browser_workflow_executes_zero_steps(self):
        assistant,provider=self.assistant()
        with patch.object(self.manager,'execute') as execute:
            for command in ('open firefox and search for python','open firefox and go to youtube'):
                self.assertIsNotNone(self.router.route(command).workflow)
                assistant.respond(command)
            execute.assert_not_called()
        self.process.assert_not_called();self.approval.request.assert_not_called();provider.chat.assert_not_called()
