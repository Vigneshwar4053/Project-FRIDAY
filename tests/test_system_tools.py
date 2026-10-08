from io import BytesIO
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from friday.tools import (PermissionDecision, RiskLevel, RiskPermissionPolicy,
                          ToolManager, ToolRegistry, ToolRequest, ToolStatus)
from friday.tools.filesystem import FileSystemPolicy
from friday.tools.system import register_system_tools

MODULE = 'friday.tools.system'
MEMORY = 'MemTotal: 1000 kB\nMemAvailable: 400 kB\nSwapTotal: 200 kB\nSwapFree: 50 kB\nSecret: hidden\n'


class SystemToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'allowed'
        self.root.mkdir()
        self.outside = self.base / 'outside'
        self.outside.mkdir()
        self.policy = FileSystemPolicy([self.root])
        self.registry = ToolRegistry()
        register_system_tools(self.registry, self.policy)
        self.manager = ToolManager(self.registry)

    def invoke(self, tool_name, **arguments):
        return self.manager.execute(ToolRequest(tool_name, arguments))

    def failed(self, result):
        self.assertIs(result.status, ToolStatus.FAILED)
        self.assertIsNone(result.data)
        self.assertEqual(result.error, 'Tool execution failed.')

    def test_registration_and_risks(self):
        self.assertEqual(len(self.registry), 5)
        for spec in self.registry.list_tools():
            self.assertIs(spec.risk, RiskLevel.READ_ONLY)

    def test_system_information(self):
        info = SimpleNamespace(sysname='Linux', release='test-kernel', machine='test-arch', nodename='host')
        with patch(MODULE + '.os.uname', return_value=info):
            result = self.invoke('system_info')
        self.assertTrue(result.success)
        self.assertEqual(result.data['operating_system'], 'Linux')
        self.assertEqual(result.data['architecture'], 'test-arch')
        self.assertEqual(set(result.data), {'operating_system', 'kernel', 'architecture',
                                          'hostname', 'python_version', 'python_implementation'})

    def test_system_failure_is_generic(self):
        with patch(MODULE + '.os.uname', side_effect=OSError('sensitive')):
            self.failed(self.invoke('system_info'))

    def test_memory_parsing_and_privacy(self):
        with patch(MODULE + '.open', return_value=BytesIO(MEMORY.encode())) as source:
            result = self.invoke('memory_info')
        source.assert_called_once_with('/proc/meminfo', 'rb')
        self.assertTrue(result.success)
        self.assertEqual(dict(result.data), {'total': 1024000, 'available': 409600,
                         'used': 614400, 'swap_total': 204800, 'swap_free': 51200,
                         'swap_used': 153600, 'unit': 'bytes'})
        self.assertNotIn('hidden', str(result.data))

    def test_memory_optional_missing(self):
        with patch(MODULE + '.open', return_value=BytesIO(b'MemTotal: 100 kB\n')):
            result = self.invoke('memory_info')
        self.assertTrue(result.success)
        for field in ('available', 'used', 'swap_total', 'swap_free', 'swap_used'):
            self.assertIsNone(result.data[field])

    def test_memory_incomplete_swap(self):
        with patch(MODULE + '.open', return_value=BytesIO(b'MemTotal: 100 kB\nSwapTotal: 10 kB\n')):
            result = self.invoke('memory_info')
        self.assertTrue(result.success)
        self.assertIsNone(result.data['swap_total'])

    def test_memory_malformed(self):
        for content in ('', 'MemTotal: -1 kB', 'MemTotal: nope kB', 'MemTotal: 5 MB',
                        'MemTotal: 0 kB', 'MemTotal: 5 kB\nMemTotal: 5 kB',
                        'MemTotal: 5 kB\nMemAvailable: 6 kB',
                        'MemTotal: 5 kB\nSwapTotal: 1 kB\nSwapFree: 2 kB'):
            with self.subTest(content=content), patch(MODULE + '.open', return_value=BytesIO(content.encode())):
                self.failed(self.invoke('memory_info'))

    def test_memory_missing_inaccessible(self):
        for error in (FileNotFoundError(), PermissionError()):
            with patch(MODULE + '.open', side_effect=error):
                self.failed(self.invoke('memory_info'))

    def test_memory_input_bounded(self):
        with patch(MODULE + '.open', return_value=BytesIO(b'x' * 65537)):
            self.failed(self.invoke('memory_info'))

    def test_memory_bad_encoding(self):
        with patch(MODULE + '.open', return_value=BytesIO(b'\xff')):
            self.failed(self.invoke('memory_info'))

    def test_cpu_information(self):
        content = b'processor : 0\nmodel name : Demo CPU\nsecret : hidden\n'
        with patch(MODULE + '.open', return_value=BytesIO(content)), \
             patch(MODULE + '.os.cpu_count', return_value=8), \
             patch(MODULE + '.os.getloadavg', return_value=(1.0, 2.0, 3.0)):
            result = self.invoke('cpu_info')
        self.assertTrue(result.success)
        self.assertEqual(result.data['model_name'], 'Demo CPU')
        self.assertEqual(result.data['logical_count'], 8)
        self.assertEqual(result.data['load_average'], (1.0, 2.0, 3.0))
        self.assertEqual(set(result.data), {'model_name', 'logical_count', 'architecture', 'load_average'})

    def test_cpu_model_bounded(self):
        source = BytesIO(b'model name : ' + b'x' * 1000 + b'\n' + b'x' * 100000)
        with patch(MODULE + '.open', return_value=source):
            result = self.invoke('cpu_info')
        self.assertEqual(len(result.data['model_name']), 256)

    def test_cpu_fallback_and_missing(self):
        with patch(MODULE + '.open', return_value=BytesIO(b'Hardware : ARM Test\n')):
            self.assertEqual(self.invoke('cpu_info').data['model_name'], 'ARM Test')
        for data in (b'bad data', b'model name : bad\x00name\n'):
            with patch(MODULE + '.open', return_value=BytesIO(data)):
                self.assertIsNone(self.invoke('cpu_info').data['model_name'])

    def test_cpu_optional_sources_unavailable(self):
        with patch(MODULE + '.open', side_effect=FileNotFoundError()), \
             patch(MODULE + '.os.getloadavg', side_effect=OSError()), \
             patch(MODULE + '.os.cpu_count', return_value=None):
            result = self.invoke('cpu_info')
        self.assertTrue(result.success)
        for field in ('model_name', 'load_average', 'logical_count'):
            self.assertIsNone(result.data[field])

    def test_cpu_invalid_load(self):
        for load in ((float('nan'), 0, 0), (-1, 0, 0), (0,)):
            with patch(MODULE + '.os.getloadavg', return_value=load):
                self.assertIsNone(self.invoke('cpu_info').data['load_average'])

    def test_disk_allowed_and_structured(self):
        usage = SimpleNamespace(f_blocks=100, f_bfree=40, f_bavail=30, f_frsize=1024)
        with patch(MODULE + '.os.fstatvfs', return_value=usage) as query:
            result = self.invoke('disk_usage', path='.')
        self.assertTrue(result.success)
        self.assertIsInstance(query.call_args.args[0], int)
        self.assertEqual(result.data['total'], 102400)
        self.assertEqual(result.data['used'], 61440)
        self.assertEqual(result.data['free'], 30720)

    def test_disk_allowed_file(self):
        file = self.root / 'file'
        file.touch()
        self.assertTrue(self.invoke('disk_usage', path=str(file)).success)

    def test_disk_outside_and_traversal_before_query(self):
        for path in (str(self.outside), '/etc', '../outside', 'x/../.'):
            with patch(MODULE + '.os.fstatvfs') as query:
                self.failed(self.invoke('disk_usage', path=path))
                query.assert_not_called()

    def test_disk_symlink_and_nested(self):
        (self.root / 'escape').symlink_to(self.outside, target_is_directory=True)
        (self.root / 'inside').symlink_to(self.root, target_is_directory=True)
        (self.outside / 'file').touch()
        for path in ('escape', 'escape/file', 'inside'):
            with patch(MODULE + '.os.fstatvfs') as query:
                self.failed(self.invoke('disk_usage', path=path))
                query.assert_not_called()

    def test_disk_missing_and_fifo(self):
        os.mkfifo(self.root / 'fifo')
        for path in ('missing', 'fifo'):
            self.failed(self.invoke('disk_usage', path=path))

    def test_disk_requires_explicit_policy(self):
        from friday.tools.system import DiskUsageTool
        with self.assertRaises(ValueError):
            DiskUsageTool(None)

    def process_fixture(self):
        proc = self.base / 'proc'
        proc.mkdir()
        for pid, name in (('1', 'ollama'), ('2', 'python'), ('3', 'ollama-helper'), ('4', 'ollama')):
            directory = proc / pid
            directory.mkdir()
            (directory / 'comm').write_text(name + '\n')
            (directory / 'cmdline').write_text('SECRET TOKEN')
            (directory / 'environ').write_text('SECRET ENV')
        (proc / 'not-a-pid').mkdir()
        return proc

    def proc_open(self, proc):
        original = os.open
        def wrapped(path, flags, *args, **kwargs):
            if path == '/proc':
                path = str(proc)
            return original(path, flags, *args, **kwargs)
        return wrapped

    def test_process_running_and_privacy(self):
        proc = self.process_fixture()
        with patch(MODULE + '.os.open', side_effect=self.proc_open(proc)) as opened:
            result = self.invoke('process_status', name='ollama')
        self.assertNotIn('cmdline', [call.args[0] for call in opened.call_args_list])
        self.assertNotIn('environ', [call.args[0] for call in opened.call_args_list])
        self.assertEqual(dict(result.data), {'name': 'ollama', 'running': True, 'count': 2,
                                           'incomplete': False, 'scope': 'visible_processes'})
        self.assertNotIn('SECRET', str(result.data))

    def test_process_not_running(self):
        proc = self.process_fixture()
        with patch(MODULE + '.os.open', side_effect=self.proc_open(proc)):
            result = self.invoke('process_status', name='code')
        self.assertTrue(result.success)
        self.assertFalse(result.data['running'])
        self.assertEqual(result.data['count'], 0)

    def test_process_invalid_name_before_io(self):
        for name in ('', '../comm', 'a b', 'python;id', 'a'*16, '*', '-option', 'é', 'x\n', 'x\x00'):
            with patch(MODULE + '._process_counts') as scan:
                self.failed(self.invoke('process_status', name=name))
                scan.assert_not_called()

    def test_process_disappearing_and_inaccessible(self):
        proc = self.process_fixture()
        (proc / '5').mkdir()  # vanished comm
        wrapper = self.proc_open(proc)
        def inaccessible(path, flags, *args, **kwargs):
            if path == '2':
                raise PermissionError('secret detail')
            return wrapper(path, flags, *args, **kwargs)
        with patch(MODULE + '.os.open', side_effect=inaccessible):
            result = self.invoke('process_status', name='ollama')
        self.assertTrue(result.success)
        self.assertTrue(result.data['incomplete'])
        self.assertEqual(result.data['count'], 2)

    def test_process_proc_unavailable(self):
        with patch(MODULE + '.os.open', side_effect=FileNotFoundError('secret')):
            self.failed(self.invoke('process_status', name='ollama'))

    def test_process_no_symlink_following(self):
        proc = self.process_fixture()
        (proc / '1' / 'comm').unlink()
        (proc / '1' / 'comm').symlink_to(proc / '4' / 'comm')
        with patch(MODULE + '.os.open', side_effect=self.proc_open(proc)):
            result = self.invoke('process_status', name='ollama')
        self.assertEqual(result.data['count'], 1)
        self.assertTrue(result.data['incomplete'])

    def test_permission_denied_and_approval_never_execute(self):
        for decision, status in ((PermissionDecision.DENY, ToolStatus.DENIED),
                                 (PermissionDecision.REQUIRE_USER_APPROVAL, ToolStatus.APPROVAL_REQUIRED)):
            manager = ToolManager(self.registry, RiskPermissionPolicy({RiskLevel.READ_ONLY: decision}))
            for spec in self.registry.list_tools():
                args = {'path': '.'} if spec.name == 'disk_usage' else {'name': 'ollama'} if spec.name == 'process_status' else {}
                tool = self.registry.get(spec.name).tool
                with patch.object(tool, 'execute') as call:
                    result = manager.execute(ToolRequest(spec.name, args))
                    self.assertIs(result.status, status)
                    call.assert_not_called()

    def test_unknown_and_invalid_requests(self):
        self.assertIs(self.invoke('unknown').status, ToolStatus.UNKNOWN_TOOL)
        for name, arguments in [('system_info', {'extra': True}), ('disk_usage', {}),
                                ('disk_usage', {'path': 2}), ('process_status', {'name': 1})]:
            with patch.object(self.registry.get(name).tool, 'execute') as call:
                self.assertIs(self.invoke(name, **arguments).status, ToolStatus.INVALID_ARGUMENTS)
                call.assert_not_called()

    def test_interrupt_preserved(self):
        with patch(MODULE + '.os.uname', side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                self.invoke('system_info')


if __name__ == '__main__':
    unittest.main()
