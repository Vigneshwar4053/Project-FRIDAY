"""Current owner policy: attempt every approved native open, deduplicate only Q."""
from test_desktop import DesktopFixture
from friday.desktop.routing import DesktopIntentResolver
from friday.tools.router import ToolRouter
from friday.tools.access import FolderDecision
from friday.memory import MemoryManager


class NativeOpeningPolicyTests(DesktopFixture):
    def setUp(self):
        super().setUp()
        self.router=ToolRouter(self.project,desktop_resolver=DesktopIntentResolver(self.apps,self.adapter.recent,self.adapter.browser))
    def command(self,text):
        request=self.router.route(text)
        return self.invoke(request.tool_name,dict(request.arguments))
    def test_native_defaults_never_launch_browser_or_consult_suppression(self):
        from unittest.mock import patch
        with patch.object(self.adapter.file_navigation,'blocked',side_effect=AssertionError('old suppression')) as guard:
            for text in ('open files','open downloads','open documents','open home'):
                self.assertEqual(self.command(text).data['status'],'launch_accepted')
        guard.assert_not_called()
        self.assertEqual(self.process.call_count,4);self.assertEqual(self.approval.request.call_count,4)
        self.assertTrue(all(call.args[0].operation=='navigate_folder' for call in self.approval.request.call_args_list))
        self.assertIsNone(self.adapter.browser.transport.child)
        self.child.terminate.assert_not_called();self.child.kill.assert_not_called()
    def test_application_wording_normalizes_to_one_activity(self):
        for text in ('open vs code','open visual studio code','open code'):
            self.assertEqual(self.command(text).data['status'],'launch_accepted')
        rows=self.memory.recent_work();self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['application_id'],'vscode');self.assertEqual(self.process.call_count,3)
        self.assertTrue(all(call.args[0].operation=='launch_application' for call in self.approval.request.call_args_list))
    def test_three_firefox_launches_make_one_persistent_record(self):
        self.command('open firefox');identity=self.memory.recent_work()[0]['entry_id']
        self.command('open firefox');self.command('open firefox')
        rows=self.memory.recent_work();self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['entry_id'],identity);self.assertEqual(self.process.call_count,3)
        with MemoryManager(self.root/'memory.db') as restarted:self.assertEqual(restarted.recent_work(),rows)
    def test_folder_repeat_order_and_fresh_resume_denial(self):
        self.command('open downloads');identity=self.memory.recent_work()[0]['entry_id']
        self.command('open documents');self.command('open downloads')
        rows=self.memory.recent_work();self.assertEqual([r['title'] for r in rows],['Downloads folder','Documents folder'])
        self.assertEqual(rows[0]['entry_id'],identity)
        self.command('show Q');self.approval.request.return_value=FolderDecision.DENY
        self.assertFalse(self.command('1').success)
        self.assertEqual(self.memory.recent_work(),rows);self.assertEqual(self.process.call_count,3)
        self.assertEqual(self.approval.request.call_count,4)
    def test_home_aliases_share_one_approved_location(self):
        self.command('open files');identity=self.memory.recent_work()[0]['entry_id']
        self.command('open home');self.command('open ubuntu files')
        rows=self.memory.recent_work();self.assertEqual(len(rows),1);self.assertEqual(rows[0]['entry_id'],identity)
        self.assertEqual(rows[0]['activity_type'],'nautilus_location')
