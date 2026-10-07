import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from friday.tools import (PermissionDecision, PermissionPolicy, ToolManager,
                          ToolRegistry, ToolRequest, ToolStatus)
from friday.tools.files import register_file_tools
from friday.tools.filesystem import FileSystemPolicy


class AllowWrites(PermissionPolicy):
    def evaluate(self, spec, request):
        return PermissionDecision.ALLOW


class FileToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'allowed'
        self.root.mkdir()
        self.outside = self.base / 'outside'
        self.outside.mkdir()
        self.file = self.root / 'hello.txt'
        self.file.write_text('hello', encoding='utf-8')
        (self.outside / 'secret.txt').write_text('outside', encoding='utf-8')
        self.policy = FileSystemPolicy([self.root], max_file_size=32)
        self.registry = ToolRegistry()
        register_file_tools(self.registry, self.policy)
        self.manager = ToolManager(self.registry)
        self.writer = ToolManager(self.registry, AllowWrites())

    def invoke(self, name, path='hello.txt', manager=None, **arguments):
        return (manager or self.manager).execute(ToolRequest(name, {'path': path, **arguments}))

    def failed(self, name, path, **arguments):
        result = self.invoke(name, path, **arguments)
        self.assertIs(result.status, ToolStatus.FAILED)
        self.assertIsNone(result.data)
        self.assertEqual(result.error, 'Tool execution failed.')

    def test_list_directory(self):
        result = self.invoke('list_directory', '.')
        self.assertTrue(result.success)
        self.assertEqual(result.data['entries'][0]['name'], 'hello.txt')
        self.assertEqual(result.data['entries'][0]['type'], 'file')

    def test_read_and_identity(self):
        request = ToolRequest('read_file', {'path': 'hello.txt'})
        result = self.manager.execute(request)
        self.assertTrue(result.success)
        self.assertEqual(result.request_id, request.request_id)
        self.assertEqual(result.data['content'], 'hello')
        self.assertEqual(result.data['size'], 5)
        self.assertGreaterEqual(result.finished_at, result.started_at)

    def test_metadata(self):
        result = self.invoke('file_info')
        self.assertTrue(result.success)
        self.assertEqual(set(result.data), {'path', 'type', 'size', 'modified_at'})
        self.assertEqual(result.data['type'], 'file')
        self.assertEqual(result.data['size'], 5)
        self.assertEqual(self.invoke('file_info', '.').data['type'], 'directory')

    def test_write_approval_no_io(self):
        with patch.object(self.policy, 'open', side_effect=AssertionError('Must not open')):
            result = self.invoke('write_file', 'new.txt', content='new')
        self.assertIs(result.status, ToolStatus.APPROVAL_REQUIRED)
        self.assertFalse((self.root / 'new.txt').exists())
        self.assertEqual(self.file.read_text(), 'hello')

    def test_allowed_write(self):
        result = self.invoke('write_file', 'new.txt', manager=self.writer, content='new')
        self.assertTrue(result.success)
        self.assertEqual(result.data['bytes_written'], 3)
        self.assertEqual((self.root / 'new.txt').read_text(), 'new')

    def test_no_implicit_overwrite(self):
        for extra in ({}, {'overwrite': False}):
            self.failed('write_file', 'hello.txt', manager=self.writer, content='changed', **extra)
        self.assertEqual(self.file.read_text(), 'hello')

    def test_explicit_overwrite(self):
        result = self.invoke('write_file', manager=self.writer, content='hi', overwrite=True)
        self.assertTrue(result.success)
        self.assertEqual(self.file.read_text(), 'hi')

    def test_traversal(self):
        for path in ('../outside/secret.txt', 'sub/../../outside/secret.txt', 'sub/../hello.txt'):
            with self.subTest(path=path):
                self.failed('read_file', path)
                self.failed('write_file', path, manager=self.writer, content='bad', overwrite=True)
        self.assertEqual((self.outside / 'secret.txt').read_text(), 'outside')

    def test_absolute_outside_and_prefix(self):
        for path in (str(self.outside / 'secret.txt'), str(self.base / 'allowed_extra' / 'x')):
            self.failed('read_file', path)
            self.failed('write_file', path, manager=self.writer, content='bad')

    def test_absolute_inside(self):
        self.assertTrue(self.invoke('read_file', str(self.file)).success)

    def test_symlink_escape(self):
        (self.root / 'link').symlink_to(self.outside / 'secret.txt')
        for tool in ('read_file', 'file_info'):
            self.failed(tool, 'link')
        self.failed('write_file', 'link', manager=self.writer, content='bad', overwrite=True)
        self.assertEqual((self.outside / 'secret.txt').read_text(), 'outside')

    def test_nested_symlink_escape(self):
        (self.root / 'sub').mkdir()
        (self.root / 'sub' / 'link').symlink_to(self.outside, target_is_directory=True)
        self.failed('read_file', 'sub/link/secret.txt')
        self.failed('list_directory', 'sub/link')
        self.failed('write_file', 'sub/link/new.txt', manager=self.writer, content='bad')
        self.assertFalse((self.outside / 'new.txt').exists())

    def test_in_root_symlinks_rejected(self):
        (self.root / 'link').symlink_to(self.file)
        self.failed('read_file', 'link')
        self.failed('write_file', 'link', manager=self.writer, content='bad', overwrite=True)
        self.assertEqual(self.file.read_text(), 'hello')

    def test_dangling_symlink_write(self):
        (self.root / 'link').symlink_to(self.outside / 'missing.txt')
        self.failed('write_file', 'link', manager=self.writer, content='bad', overwrite=True)
        self.assertFalse((self.outside / 'missing.txt').exists())

    def test_nonexistent(self):
        for tool in ('read_file', 'file_info', 'list_directory'):
            self.failed(tool, 'missing')
        self.failed('write_file', 'missing/new.txt', manager=self.writer, content='new')

    def test_directory_as_file(self):
        self.failed('read_file', '.')
        self.failed('write_file', '.', manager=self.writer, content='bad', overwrite=True)

    def test_invalid_arguments_before_execution(self):
        with patch.object(self.policy, 'open', side_effect=AssertionError('Must not open')):
            for name, args in [('read_file', {'path': 2}), ('read_file', {}),
                               ('write_file', {'path': 'x', 'content': 3}),
                               ('write_file', {'path': 'x', 'content': 'x', 'overwrite': 'yes'}),
                               ('read_file', {'path': 'x', 'extra': True})]:
                result = self.writer.execute(ToolRequest(name, args))
                self.assertIs(result.status, ToolStatus.INVALID_ARGUMENTS)

    def test_size_limits(self):
        self.file.write_bytes(b'x' * 33)
        self.failed('read_file', 'hello.txt')
        self.failed('write_file', 'new.txt', manager=self.writer, content='x' * 33)
        self.assertFalse((self.root / 'new.txt').exists())
        self.file.write_bytes(b'x' * 32)
        self.assertTrue(self.invoke('read_file').success)

    def test_nontext(self):
        for content in (b'\xff', b'abc\x00def'):
            self.file.write_bytes(content)
            self.failed('read_file', 'hello.txt')
        self.failed('write_file', 'new.txt', manager=self.writer, content='a\x00b')

    def test_empty_text(self):
        self.file.write_bytes(b'')
        self.assertEqual(self.invoke('read_file').data['content'], '')

    def test_special_file_no_block(self):
        os.mkfifo(self.root / 'fifo')
        self.failed('read_file', 'fifo')
        self.failed('write_file', 'fifo', manager=self.writer, content='bad', overwrite=True)

    def test_hardlinks_rejected(self):
        os.link(self.outside / 'secret.txt', self.root / 'hardlink')
        self.failed('read_file', 'hardlink')
        self.failed('write_file', 'hardlink', manager=self.writer, content='bad', overwrite=True)
        self.assertEqual((self.outside / 'secret.txt').read_text(), 'outside')

    def test_invalid_paths(self):
        for path in ('', ' ', 'hello\x00.txt'):
            self.failed('read_file', path)

    def test_configuration(self):
        for roots, size in (([], 32), ([self.file], 32), ([self.root], 0), ([self.root], True)):
            with self.assertRaises(ValueError):
                FileSystemPolicy(roots, size)
        with self.assertRaises(FileNotFoundError):
            FileSystemPolicy([self.base / 'missing'])

    def test_multiple_roots(self):
        registry = ToolRegistry()
        register_file_tools(registry, FileSystemPolicy([self.root, self.outside]))
        manager = ToolManager(registry)
        self.assertTrue(self.invoke('read_file', str(self.outside / 'secret.txt'), manager=manager).success)

    def test_parent_replaced_with_symlink_after_resolution(self):
        sub = self.root / 'sub'
        sub.mkdir()
        original = self.policy.resolve
        def replace(path):
            resolved = original(path)
            sub.rmdir()
            sub.symlink_to(self.outside, target_is_directory=True)
            return resolved
        with patch.object(self.policy, 'resolve', side_effect=replace):
            self.failed('write_file', 'sub/new.txt', manager=self.writer, content='bad')
        self.assertFalse((self.outside / 'new.txt').exists())

    def test_listing_does_not_follow_links(self):
        (self.root / 'link').symlink_to(self.outside / 'secret.txt')
        result = self.invoke('list_directory', '.')
        self.assertEqual(result.data['entries'][1]['type'], 'symlink')


if __name__ == '__main__':
    unittest.main()
