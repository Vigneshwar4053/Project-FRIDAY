"""Actual worker event loop and socket protocol with headless GTK stand-ins."""
import json
import socket
import sys
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch

from friday.desktop.browser import BrowserTransport, BrowserHealthUnavailable
from friday.desktop import browser_worker
from friday.desktop.recent import RecentWorkQueue
import test_managed_browser as browser_tests
from test_desktop import DesktopFixture
from friday.desktop.browser import ManagedBrowser
from friday.desktop.routing import DesktopIntentResolver
from friday.tools.router import ToolRouter


class Widget:
    def __init__(self, **fields): self.text=fields.get('label','');self.mapped=False;self.closed=None
    def __getattr__(self,name): return lambda *args,**kwargs: None
    def set_text(self,text): self.text=text
    def get_text(self): return self.text
    def present(self): self.mapped=True
    def get_mapped(self): return self.mapped
    def connect(self,event,callback): self.closed=callback


class HeadlessWorker(unittest.TestCase):
    def setUp(self):
        self.callbacks=[];self.stop=threading.Event();self.windows=[];self.errors=[]
        owner=self
        class Loop:
            def quit(self): owner.stop.set()
            def run(self):
                while not owner.stop.is_set():
                    for callback in tuple(owner.callbacks):
                        if not callback(): owner.callbacks.remove(callback)
                    owner.stop.wait(.002)
        def window(**fields):
            widget=Widget(**fields);self.windows.append(widget);return widget
        glib=types.SimpleNamespace(MainLoop=Loop,timeout_add=lambda interval,callback:self.callbacks.append(callback))
        gtk=types.SimpleNamespace(init_check=lambda:True,Window=window,Box=Widget,Label=Widget,
                                  ScrolledWindow=Widget,Orientation=types.SimpleNamespace(VERTICAL=1))
        gi=types.ModuleType('gi');gi.require_version=lambda *args:None
        repository=types.ModuleType('gi.repository');repository.Gtk=gtk;repository.GLib=glib
        self.modules=patch.dict(sys.modules,{'gi':gi,'gi.repository':repository});self.modules.start()
        parent,child=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET);parent.settimeout(.5)
        self.fd=child.detach();self.argv=patch.object(sys,'argv',['worker',str(self.fd)]);self.argv.start()
        def run():
            try: browser_worker.main()
            except Exception as exc:self.errors.append(type(exc).__name__)
        self.thread=threading.Thread(target=run);self.thread.start()
        self.transport=BrowserTransport();self.transport.channel=parent
        self.process=Mock();self.process.stderr=None
        self.process.poll.side_effect=lambda:None if self.thread.is_alive() else 0
        self.process.wait.side_effect=lambda timeout:self.thread.join(timeout)
        self.transport.child=self.process
        self.addCleanup(self.cleanup_worker)
    def cleanup_worker(self):
        self.stop.set();self.thread.join(1)
        self.transport.close();self.argv.stop();self.modules.stop()
        self.assertFalse(self.thread.is_alive());self.assertEqual(self.errors,[])
    def test_multiple_locations_one_live_loop_one_window_and_hidden_ping(self):
        for location in ('/home/approved','/home/approved/Downloads','/home/approved/Documents','/home/approved'):
            self.transport.request('navigate',location=location)
            self.assertTrue(self.thread.is_alive());self.assertTrue(self.transport.alive())
        self.assertEqual(len(self.windows),1)
        self.windows[0].mapped=False
        self.assertTrue(self.transport.alive())
        self.process.terminate.assert_not_called()
    def test_window_close_detected_before_replacement(self):
        self.transport.request('navigate',location='/approved')
        self.windows[0].closed();self.thread.join(1)
        self.assertFalse(self.transport.alive());self.assertIsNone(self.transport.child)
        self.process.terminate.assert_not_called()
    def test_replayed_request_ends_worker_without_another_window(self):
        self.transport.request('navigate',location='/approved')
        self.transport.channel.send(json.dumps({'id':1,'op':'ping'}).encode())
        self.thread.join(1);self.assertFalse(self.thread.is_alive());self.assertEqual(len(self.windows),1)
    def test_malformed_message_rejected(self):
        self.transport.channel.send(b'{invalid');self.thread.join(1)
        self.assertFalse(self.thread.is_alive());self.assertEqual(len(self.windows),1)


class BrowserRepairTests(DesktopFixture):
    def setUp(self):
        super().setUp()
        self.renderer=browser_tests.Renderer();self.adapter.browser=ManagedBrowser(self.renderer)
        self.router=ToolRouter(self.project,desktop_resolver=DesktopIntentResolver(self.apps,self.adapter.recent,self.adapter.browser))
    def command(self,text):
        route=self.router.route(text)
        return self.invoke(route.tool_name,dict(route.arguments))
    def test_inconclusive_health_does_not_reapprove_or_launch(self):
        self.command('open friday browser');before=self.approval.request.call_count
        with patch.object(self.renderer,'alive',side_effect=BrowserHealthUnavailable('unconfirmed')):
            result=self.command('open downloads in friday browser')
        self.assertEqual(result.data['status'],'browser_health_unverified')
        self.assertEqual(self.approval.request.call_count,before)
        self.assertEqual(self.renderer.starts,1);self.assertEqual(self.adapter.executor.launch_count,1)
    def test_navigation_failure_does_not_destroy_live_renderer(self):
        self.command('open friday browser');self.renderer.fail=True
        self.command('open downloads in friday browser');self.command('open downloads in friday browser')
        self.assertEqual(self.renderer.starts,1)
        self.assertEqual(sum(c.args[0].operation=='launch_browser' for c in self.approval.request.call_args_list),1)
    def test_native_q_is_explicit_and_conversion_preserves_saved_data(self):
        path=self.home/'Downloads';info=path.stat()
        activity=RecentWorkQueue.activity('open_folder',{'folder_id':'downloads'},'files',path,(info.st_dev,info.st_ino),version=2)
        self.memory.record_recent_work({**activity,'launch_status':'launch_accepted'})
        old=self.memory.recent_work()[0]
        shown=self.command('show Q')
        self.assertIn('Downloads — Ubuntu Files',shown.data['message'])
        self.assertEqual(self.memory.recent_work()[0],old)
        converted=self.command('resume Q 1 in friday browser')
        self.assertEqual(converted.data['status'],'navigation_confirmed')
        rows=self.memory.recent_work();self.assertEqual(rows[1],old)
        self.assertEqual(rows[0]['activity_type'],'friday_browser_location')
        self.assertEqual([c.args[0].operation for c in self.approval.request.call_args_list],['launch_browser','navigate_browser'])
        self.command('show Q');self.command('1')
        self.assertEqual(len(self.memory.recent_work()),2);self.assertEqual(self.renderer.starts,1)
    def test_conversion_denied_preserves_native_history(self):
        from friday.tools.access import FolderDecision
        self.invoke('open_folder',{'folder_id':'downloads'});before=self.memory.recent_work()
        self.command('show Q');self.approval.request.return_value=FolderDecision.DENY
        self.assertFalse(self.command('resume Q 1 in friday browser').success)
        self.assertEqual(self.memory.recent_work(),before);self.assertEqual(self.renderer.starts,0)
    def test_new_types_keep_legacy_stable_id_when_owner_repeats_launch(self):
        path=self.home/'Downloads';info=path.stat()
        activity=RecentWorkQueue.activity('open_folder',{'folder_id':'downloads'},'files',path,(info.st_dev,info.st_ino),version=2)
        self.memory.record_recent_work({**activity,'launch_status':'launch_accepted'});old=self.memory.recent_work()[0]
        self.invoke('open_folder',{'folder_id':'downloads'})
        new=self.memory.recent_work()[0]
        self.assertEqual(new['entry_id'],old['entry_id']);self.assertEqual(len(self.memory.recent_work()),1)
        self.assertEqual(new['activity_type'],'nautilus_location')
    def test_native_windows_never_claimed_owned_or_closed(self):
        self.command('open files');self.command('open downloads')
        self.assertIsNone(self.adapter.file_navigation.last_activity.managed_window_identity)
        self.assertFalse(self.adapter.file_navigation.supports_window_replacement)
        self.child.terminate.assert_not_called();self.child.kill.assert_not_called()
        self.assertEqual(self.process.call_count,2)


class TransportRecoveryTests(unittest.TestCase):
    def transport(self):
        transport=BrowserTransport();transport.child=Mock();transport.child.poll.return_value=None
        transport.child.stderr=None;transport.channel=Mock()
        return transport
    def test_timeout_keeps_process_and_recovers_late_ack_before_new_ping(self):
        transport=self.transport();child=transport.child
        transport.channel.recv.side_effect=TimeoutError
        with self.assertRaises(BrowserHealthUnavailable):transport.request('navigate',location='/approved')
        self.assertIsNotNone(transport.pending_command)
        transport.channel.recv.side_effect=[
            json.dumps({'id':1,'op':'navigate','window':'managed','location':'/approved','mapped':True}).encode(),
            json.dumps({'id':2,'op':'ping','window':'managed','location':'/approved','mapped':False}).encode()]
        self.assertTrue(transport.alive());self.assertIsNone(transport.pending_command)
        self.assertEqual(transport.channel.send.call_count,2);child.terminate.assert_not_called()
    def test_malformed_ack_latches_unusable_without_killing_or_relaunching(self):
        transport=self.transport();child=transport.child;transport.channel.recv.return_value=b'{invalid'
        with self.assertRaises(ValueError):transport.request('navigate',location='/approved')
        with self.assertRaises(BrowserHealthUnavailable):transport.alive()
        self.assertTrue(transport.broken);self.assertIs(transport.child,child)
        self.assertEqual(transport.channel.send.call_count,1);child.terminate.assert_not_called()
    def test_bounded_diagnostics_do_not_expose_paths_or_exception_strings(self):
        transport=self.transport()
        for _ in range(40):transport._event('ipc_timeout')
        diagnostics=transport.diagnostics()
        self.assertEqual(len(diagnostics['events']),16)
        self.assertEqual(set(diagnostics),{'process_state','exit_code','events'})
        self.assertNotIn('/approved',json.dumps(diagnostics))
