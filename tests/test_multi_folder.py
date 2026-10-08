"""Phase 6A uses only temporary fixtures and the production composition."""
from dataclasses import replace
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from friday.config.settings import settings
from friday.core.assistant import FridayAssistant
from friday.main import create_tool_runtime
from friday.providers.base import ModelProvider
from friday.tools import (PermissionDecision, RiskLevel, RiskPermissionPolicy,
                          ToolManager, ToolRequest, ToolStatus)
from friday.tools.filesystem import FileSystemPolicy
from friday.tools.presenter import MAX_PRESENTED_CHARACTERS, ToolPresenter


class MultiFolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.root = self.home / 'FRIDAY'
        self.downloads = self.home / 'Downloads'
        self.documents = self.home / 'Documents'
        self.outside = self.home / 'Private'
        for folder in (self.root, self.downloads, self.documents, self.outside):
            folder.mkdir()
            (folder / 'notes.txt').write_text('fixture only', encoding='utf-8')
        self.configuration = replace(settings, project_root=self.root,
            filesystem_read_roots=(self.downloads, self.documents),
            filesystem_max_directory_entries=3)
        self.manager, self.router = create_tool_runtime(self.configuration)
        self.provider = Mock(spec=ModelProvider)
        self.provider.chat.return_value = 'chat fixture'
        self.assistant = FridayAssistant(self.provider, settings.system_prompt,
            tool_manager=self.manager, tool_router=self.router)
        self.addCleanup(self.assistant.model_manager.close)

    def invoke(self, tool, path, manager=None, **extra):
        return (manager or self.manager).execute(ToolRequest(tool, {'path': str(path), **extra}))

    def test_project_access(self):
        self.assertTrue(self.invoke('read_file', 'notes.txt').success)

    def test_project_basename_does_not_shadow_source_package(self):
        package = self.root / 'friday' / 'tools'
        package.mkdir(parents=True)
        (package / 'router.py').write_text('fixture source')
        self.assertEqual(self.invoke('read_file', 'friday/tools/router.py').data['content'], 'fixture source')

    def test_multiple_absolute_read_roots(self):
        for root in (self.downloads, self.documents):
            self.assertTrue(self.invoke('read_file', root / 'notes.txt').success)

    def test_home_expansion(self):
        with patch.dict(os.environ, {'HOME': str(self.home)}):
            self.assertTrue(self.invoke('read_file', '~/Downloads/notes.txt').success)
            self.assertFalse(self.invoke('read_file', '~/Private/notes.txt').success)

    def test_configured_home_expansion(self):
        with patch.dict(os.environ, {'HOME': str(self.home)}):
            manager, _ = create_tool_runtime(replace(self.configuration,
                filesystem_read_roots=('~/Downloads',)))
        self.assertTrue(self.invoke('read_file', self.downloads / 'notes.txt', manager).success)

    def test_alias_case_and_children(self):
        self.assertTrue(self.invoke('read_file', 'downloads/notes.txt').success)
        self.assertTrue(self.invoke('list_directory', 'Documents').success)

    def test_unauthorized_alias(self):
        self.assertFalse(self.invoke('list_directory', 'Private').success)

    def test_duplicate_alias_denied(self):
        other = self.home / 'other' / 'Downloads'
        other.mkdir(parents=True)
        manager, _ = create_tool_runtime(replace(self.configuration,
            filesystem_read_roots=(self.downloads, other)))
        self.assertFalse(self.invoke('list_directory', 'Downloads', manager).success)
        self.assertTrue(self.invoke('list_directory', other, manager).success)

    def test_alias_project_collision_denied(self):
        (self.root / 'Downloads').mkdir()
        self.assertFalse(self.invoke('list_directory', 'Downloads').success)
        self.assertTrue(self.invoke('list_directory', self.downloads).success)

    def test_unauthorized_absolute_paths(self):
        for tool in ('read_file', 'list_directory', 'file_info'):
            self.assertFalse(self.invoke(tool, self.outside / 'notes.txt').success)

    def test_traversal(self):
        for path in ('../Private/notes.txt', 'Downloads/../Documents/notes.txt',
                     str(self.downloads / '..' / 'Documents' / 'notes.txt')):
            self.assertFalse(self.invoke('read_file', path).success)

    def test_symlinks(self):
        for target in (self.outside, self.documents):
            link = self.downloads / ('escape' if target == self.outside else 'inside')
            link.symlink_to(target, target_is_directory=True)
            self.assertFalse(self.invoke('read_file', link / 'notes.txt').success)
            self.assertFalse(self.invoke('list_directory', link).success)

    def test_replaced_root(self):
        policy = FileSystemPolicy([self.root, self.downloads])
        original = policy.resolve
        def replaced(path):
            result = original(path)
            self.downloads.rename(self.home / 'old-downloads')
            self.downloads.symlink_to(self.outside, target_is_directory=True)
            return result
        with patch.object(policy, 'resolve', side_effect=replaced):
            with self.assertRaises(OSError):
                with policy.open(str(self.downloads / 'notes.txt'), os.O_RDONLY):
                    self.fail('Replaced root opened')

    def test_read_roots_never_grant_writes(self):
        writer = ToolManager(self.manager.registry, RiskPermissionPolicy({
            RiskLevel.WRITE: PermissionDecision.ALLOW}))
        for path in (self.downloads / 'new.txt', 'Downloads/notes.txt'):
            self.assertFalse(self.invoke('write_file', path, writer,
                content='changed', overwrite=True).success)
        self.assertFalse((self.downloads / 'new.txt').exists())
        self.assertEqual((self.downloads / 'notes.txt').read_text(), 'fixture only')
        self.assertTrue(self.invoke('write_file', 'new.txt', writer, content='project fixture').success)

    def test_default_write_permission_prevents_io(self):
        result = self.invoke('write_file', self.downloads / 'new.txt', content='x')
        self.assertIs(result.status, ToolStatus.APPROVAL_REQUIRED)
        self.assertFalse((self.downloads / 'new.txt').exists())

    def test_permission_deny_before_filesystem(self):
        manager = ToolManager(self.manager.registry, RiskPermissionPolicy({
            RiskLevel.READ_ONLY: PermissionDecision.DENY}))
        with patch('friday.tools.files.os.scandir', side_effect=AssertionError('no IO')):
            self.assertIs(self.invoke('list_directory', self.downloads, manager).status, ToolStatus.DENIED)

    def test_huge_directory_bounded(self):
        for index in range(1000):
            (self.downloads / f'entry-{index}').touch()
        result = self.invoke('list_directory', self.downloads)
        self.assertEqual(len(result.data['entries']), 3)
        self.assertTrue(result.data['truncated'])
        self.assertIn('omitted', ToolPresenter().format(result))

    def test_enumeration_stops_after_limit_plus_one(self):
        entry = Mock()
        entry.name = 'fixture'
        entry.stat.return_value.st_mode = 0o100600
        count = 0
        def entries():
            nonlocal count
            for _ in range(1000):
                count += 1
                yield entry
        scan = Mock()
        scan.__enter__ = Mock(return_value=entries())
        scan.__exit__ = Mock(return_value=False)
        with patch('friday.tools.files.os.scandir', return_value=scan):
            result = self.invoke('list_directory', self.downloads)
        self.assertTrue(result.success)
        self.assertEqual(count, 4)
        self.assertEqual(entry.stat.call_count, 3)

    def test_exact_limit_not_truncated(self):
        for name in ('a', 'b'):
            (self.downloads / name).touch()
        self.assertFalse(self.invoke('list_directory', self.downloads).data['truncated'])

    def test_terminal_and_invalid_byte_names(self):
        name = 'bad\n\t\x1b[31m\u202e'
        (self.downloads / name).touch()
        os.close(os.open(os.fsencode(self.downloads) + b'/bad-\xff', os.O_CREAT | os.O_WRONLY, 0o600))
        result = self.invoke('list_directory', self.downloads)
        names = '\n'.join(entry['name'] for entry in result.data['entries'])
        self.assertNotIn('\x1b', names)
        self.assertNotIn('\u202e', names)
        self.assertIn('\\n', names)
        self.assertIn('\\udcff', names)
        self.assertLess(len(ToolPresenter().format(result)), MAX_PRESENTED_CHARACTERS + 100)

    def test_oversize_invalid_utf8_special_and_missing(self):
        (self.downloads / 'big').write_bytes(b'x' * (1024 * 1024 + 1))
        (self.downloads / 'invalid').write_bytes(b'\xff')
        os.mkfifo(self.downloads / 'fifo')
        for name in ('big', 'invalid', 'fifo', 'missing'):
            self.assertFalse(self.invoke('read_file', self.downloads / name).success)

    def test_disappearing_listing_entry(self):
        entry = Mock()
        entry.name = 'gone'
        entry.stat.side_effect = FileNotFoundError()
        scan = Mock()
        scan.__enter__ = Mock(return_value=iter([entry]))
        scan.__exit__ = Mock(return_value=False)
        with patch('friday.tools.files.os.scandir', return_value=scan):
            self.assertFalse(self.invoke('list_directory', self.downloads).success)

    def test_malformed_paths(self):
        for path in ('', ' ', 'Downloads/\x00notes', '~no-such-friday-user/file'):
            self.assertFalse(self.invoke('read_file', path).success)

    def test_invalid_configuration(self):
        for limit in (0, -1, True, '100'):
            with self.assertRaises(ValueError):
                FileSystemPolicy([self.root], max_directory_entries=limit)
        with self.assertRaises(ValueError):
            FileSystemPolicy([self.root], write_roots=[self.downloads])

    def test_required_routes_and_no_model(self):
        with patch.dict(os.environ, {'HOME': str(self.home)}):
            for message in ('list files in Downloads', 'what files are in ~/Downloads',
                f'list {self.downloads}', 'show files in Documents',
                f'read {self.documents}/notes.txt', 'read ~/Downloads/notes.txt',
                'what files are in this project', 'read notes.txt'):
                with self.subTest(message=message):
                    response = self.assistant.respond(message)
                    self.assertIn('[Tool:', response)
                    self.assertNotIn('FAILED', response)
        self.provider.chat.assert_not_called()

    def test_unauthorized_routes_never_fallback(self):
        for message in ('list files in Pictures', 'what files are in Videos',
                        'read /etc/passwd', 'list files in /etc',
                        'read ../Private/notes.txt', 'list files in Private',
                        'read /etc/path with spaces', 'read Downloads/\x00bad',
                        'read /etc/passwd\nmalformed', 'list files in /etc\nmalformed'):
            self.assertIn('FAILED', self.assistant.respond(message))
        self.provider.chat.assert_not_called()

    def test_unmatched_chat_uses_model(self):
        self.assertEqual(self.assistant.respond('explain recursion'), 'chat fixture')
        self.provider.chat.assert_called_once()

    def test_other_folders_work_only_after_opt_in(self):
        roots = tuple(self.home / name for name in ('Desktop', 'Pictures', 'Videos'))
        for root in roots:
            root.mkdir()
        manager, router = create_tool_runtime(replace(self.configuration,
            filesystem_read_roots=roots))
        for message in ('list files in Pictures', 'what files are in Videos', 'show files in Desktop'):
            decision = router.route(message)
            self.assertTrue(manager.execute(ToolRequest(decision.tool_name, decision.arguments)).success)


if __name__ == '__main__':
    unittest.main()
