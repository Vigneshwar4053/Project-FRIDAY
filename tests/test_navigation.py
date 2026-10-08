"""Offline navigation regressions with real tools, permissions and SQLite."""
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from friday.config.settings import settings
from friday.core.assistant import FridayAssistant
from friday.core.navigation import MAX_HISTORY
from friday.main import create_tool_runtime
from friday.memory import MemoryManager
from friday.providers.base import ModelProvider
from friday.tools.access import FolderDecision
from friday.tools.models import DirectoryGuard, ToolRequest


class NavigationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.project = self.home / "FRIDAY"
        self.downloads = self.home / "Downloads"
        self.pictures = self.home / "Pictures"
        self.child = self.downloads / "portfolio"
        for path in (self.project, self.child, self.pictures):
            path.mkdir(parents=True)
        (self.child / "public.txt").write_text("public navigation fixture")
        (self.downloads / "notes.txt").write_text("private body never read")
        (self.downloads / ".ssh").mkdir()
        (self.downloads / "link").symlink_to(self.child, target_is_directory=True)
        env = patch.dict(os.environ, {"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config")})
        env.start()
        self.addCleanup(env.stop)
        self.approval = Mock()
        self.approval.request.return_value = FolderDecision.ALLOW_ONCE
        config = replace(settings, project_root=self.project, database_path=self.project / "data/memory.db")
        self.manager, self.router = create_tool_runtime(config, filesystem_approval=self.approval)
        self.provider = Mock(spec=ModelProvider)
        self.provider.chat.return_value = "ordinary answer"
        self.memory = MemoryManager(config.database_path)
        self.addCleanup(self.memory.close)
        self.assistant = FridayAssistant(self.provider, settings.system_prompt, memory=self.memory,
            tool_router=self.router, tool_manager=self.manager)
        self.addCleanup(self.assistant.model_manager.close)
        self.addCleanup(self.assistant.end_session)
        self.nav = self.assistant.navigation

    def start(self):
        self.assertIn("portfolio", self.assistant.respond("open downloads"))

    def test_open_child(self):
        self.start()
        self.assertIn("public.txt", self.assistant.respond("open portfolio"))
        self.assertEqual(self.nav.current.path, str(self.child))
        self.provider.chat.assert_not_called()
        self.assertEqual(self.approval.request.call_count, 2)
        self.assertEqual(self.approval.request.call_args.args[0].target, self.child)

    def test_enter_child_voice(self):
        self.start()
        self.assertIn("public.txt", self.assistant.respond("FRIDAY, please enter portfolio."))
        self.provider.chat.assert_not_called()

    def test_go_into_child(self):
        self.start()
        self.assertIn("public.txt", self.assistant.respond("can you go into the portfolio folder?"))

    def test_go_back(self):
        self.start()
        self.assistant.respond("open portfolio")
        self.assertIn("portfolio", self.assistant.respond("go back"))
        self.assertEqual(self.nav.current.path, str(self.downloads))
        self.assertEqual(self.approval.request.call_count, 3)
        self.assertEqual(self.nav.history, [])

    def test_go_home(self):
        self.start()
        self.assistant.respond("open portfolio")
        self.assertIn("[Tool: list_directory]", self.assistant.respond("go home"))
        self.assertEqual(self.nav.current.path, str(self.project))
        self.assertEqual(self.nav.history, [])
        self.assertEqual(self.approval.request.call_count, 2)

    def test_home_before_listing(self):
        self.assistant.respond("go home")
        self.assertEqual(self.nav.current.path, str(self.project))

    def test_back_without_history(self):
        self.assertIn("No previous", self.assistant.respond("go back"))
        self.provider.chat.assert_not_called()
        self.approval.request.assert_not_called()

    def test_unknown_child(self):
        self.start()
        self.assertIn("Please name", self.assistant.respond("open unknown"))
        self.assertEqual(self.approval.request.call_count, 1)
        self.provider.chat.assert_not_called()
        self.assertEqual(self.nav.current.path, str(self.downloads))

    def test_file_not_directory(self):
        self.start()
        self.assertIn("is a file, not a directory", self.assistant.respond("enter notes.txt"))
        self.assertEqual(self.approval.request.call_count, 1)

    def test_symlink_child(self):
        self.start()
        self.assertIn("symlinks", self.assistant.respond("enter link"))
        self.assertEqual(self.approval.request.call_count, 1)

    def test_sensitive_child(self):
        self.start()
        self.assertNotIn(".ssh", self.nav.children)
        self.assertIn("Please name", self.assistant.respond("enter .ssh"))
        self.assertEqual(self.approval.request.call_count, 1)

    def test_denial_keeps_location(self):
        self.start()
        self.approval.request.return_value = FolderDecision.DENY
        self.assertIn("FAILED", self.assistant.respond("open portfolio"))
        self.assertEqual(self.nav.current.path, str(self.downloads))
        self.assertEqual(self.nav.history, [])
        self.provider.chat.assert_not_called()

    def test_allow_once_not_inherited(self):
        self.start()
        self.approval.request.return_value = FolderDecision.DENY
        tool = self.manager.registry.get("list_directory").tool
        with patch.object(tool, "execute", wraps=tool.execute) as action:
            self.assistant.respond("enter portfolio")
            action.assert_not_called()
        self.assertEqual(self.approval.request.call_count, 2)

    def test_back_denial_keeps_history(self):
        self.start()
        self.assistant.respond("open portfolio")
        self.approval.request.return_value = FolderDecision.DENY
        self.assistant.respond("go back")
        self.assertEqual(self.nav.current.path, str(self.child))
        self.assertEqual(len(self.nav.history), 1)

    def test_disappearing_child(self):
        self.start()
        self.child.rename(self.downloads / "moved")
        self.assertIn("FAILED", self.assistant.respond("open portfolio"))
        self.assertEqual(self.nav.current.path, str(self.downloads))
        self.assertEqual(self.approval.request.call_count, 1)

    def test_replaced_child_before_prompt(self):
        self.start()
        self.child.rename(self.downloads / "old")
        self.child.mkdir()
        self.assertIn("FAILED", self.assistant.respond("open portfolio"))
        self.assertEqual(self.approval.request.call_count, 1)
        self.assertEqual(self.nav.current.path, str(self.downloads))

    def test_symlink_replacement(self):
        self.start()
        self.child.rename(self.downloads / "old")
        self.child.symlink_to(self.pictures, target_is_directory=True)
        self.assertIn("FAILED", self.assistant.respond("open portfolio"))
        self.assertEqual(self.approval.request.call_count, 1)

    def test_replaced_parent(self):
        self.start()
        old = self.home / "old-downloads"
        self.downloads.rename(old)
        self.downloads.mkdir()
        (old / "portfolio").rename(self.child)
        self.assertIn("FAILED", self.assistant.respond("open portfolio"))
        self.assertEqual(self.approval.request.call_count, 1)

    def test_replacement_after_approval(self):
        self.start()
        def approve(_):
            self.child.rename(self.downloads / "old")
            self.child.mkdir()
            return FolderDecision.ALLOW_ONCE
        self.approval.request.side_effect = approve
        self.assertIn("FAILED", self.assistant.respond("open portfolio"))
        self.assertEqual(self.nav.current.path, str(self.downloads))

    def test_no_sqlite_persistence(self):
        self.start()
        self.assistant.respond("open portfolio")
        self.assistant.respond("go back")
        self.assistant.respond("go home")
        self.assertEqual(self.memory.get_recent_messages(100), [])
        self.assertEqual(len(self.assistant.messages), 1)
        self.provider.chat.assert_not_called()

    def test_shutdown_clears(self):
        self.start()
        self.assistant.respond("open portfolio")
        self.assistant.end_session()
        self.assertIsNone(self.nav.current)
        self.assertEqual(self.nav.children, {})
        self.assertEqual(self.nav.history, [])

    def test_semantic_precedence(self):
        (self.downloads / "Pictures").mkdir()
        self.start()
        self.assistant.respond("open pictures")
        self.assertEqual(self.nav.current.path, str(self.pictures))

    def test_enter_semantic_precedence(self):
        self.start()
        self.assistant.respond("enter pictures")
        self.assertEqual(self.nav.current.path, str(self.pictures))

    def test_absolute_not_rewritten(self):
        self.start()
        self.assistant.respond("/Videos")
        self.assertEqual(self.nav.current.path, str(self.downloads))
        self.assertEqual(self.approval.request.call_count, 1)

    def test_explicit_home_path(self):
        self.start()
        self.assistant.respond("~/Pictures")
        self.assertEqual(self.nav.current.path, str(self.pictures))

    def test_ambiguous_case(self):
        (self.downloads / "PORTFOLIO").mkdir()
        self.start()
        self.assertIn("Please name", self.assistant.respond("open portfolio"))
        self.assertEqual(self.approval.request.call_count, 1)

    def test_quoted_case(self):
        (self.downloads / "PORTFOLIO").mkdir()
        self.start()
        self.assertIn("public.txt", self.assistant.respond('open "portfolio"'))

    def test_space_in_name(self):
        folder = self.downloads / "my work"
        folder.mkdir()
        (folder / "visible.txt").write_text("fixture")
        self.start()
        self.assertIn("visible.txt", self.assistant.respond("open my work"))

    def test_control_name_not_trusted(self):
        (self.downloads / "bad\nname").mkdir()
        self.start()
        self.assertNotIn("bad\nname", self.nav.children)

    def test_traversal_not_navigation(self):
        self.start()
        self.assistant.respond("enter ../portfolio")
        self.assertEqual(self.nav.current.path, str(self.downloads))

    def test_persistent_grant(self):
        self.approval.request.return_value = FolderDecision.ALLOW_PERSISTENT
        self.start()
        self.assertIn("public.txt", self.assistant.respond("open portfolio"))
        self.assertEqual(self.approval.request.call_count, 1)
        result = self.manager.execute(ToolRequest("write_file", {"path": str(self.child / "new.txt"), "content": "forbidden"}))
        self.assertFalse(result.success)
        self.assertFalse((self.child / "new.txt").exists())

    def test_hybrid_listing_populates_context(self):
        self.provider.chat.return_value = json.dumps({"kind":"tool", "tool_name":"list_directory", "arguments":{"path":"~/Downloads"}})
        self.assertIn("portfolio", self.assistant.respond("Can you inspect my downloads folder?"))
        self.assertIn("public.txt", self.assistant.respond("open portfolio"))
        self.provider.chat.assert_called_once()

    def test_chat_does_not_create_children(self):
        self.start()
        self.provider.chat.return_value = "invented (directory)"
        self.assistant.respond("Hello FRIDAY")
        self.assertIn("Please name", self.assistant.respond("open invented"))
        self.provider.chat.assert_called_once()

    def test_failed_home_does_not_reset(self):
        self.start()
        self.assistant.respond("open portfolio")
        moved = self.home / "moved-project"
        self.project.rename(moved)
        try:
            self.assistant.respond("go home")
            self.assertEqual(self.nav.current.path, str(self.child))
            self.assertEqual(len(self.nav.history), 1)
        finally:
            moved.rename(self.project)

    def test_history_bound(self):
        for index in range(MAX_HISTORY + 5):
            folder = self.project / str(index)
            folder.mkdir()
            self.assistant.respond(str(folder))
        self.assertEqual(len(self.nav.history), MAX_HISTORY)

    def test_children_bound(self):
        for index in range(150):
            (self.downloads / f"dir{index}").mkdir()
        self.assertIn("Additional entries omitted", self.assistant.respond("open downloads"))
        self.assertLessEqual(len(self.nav.children), 100)

    def test_unlisted_new_child_not_inferred(self):
        self.start()
        (self.downloads / "new-child").mkdir()
        self.assertIn("Please name", self.assistant.respond("open new-child"))
        self.assertEqual(self.approval.request.call_count, 1)

    def test_listed_parent_not_authorization_after_revoke(self):
        self.approval.request.return_value = FolderDecision.ALLOW_PERSISTENT
        self.start()
        self.assistant.respond("revoke access to Downloads")
        self.approval.request.return_value = FolderDecision.DENY
        self.assertIn("FAILED", self.assistant.respond("open portfolio"))
        self.assertEqual(self.nav.current.path, str(self.downloads))

    def test_application_not_navigation(self):
        self.start()
        self.assertIn("not supported", self.assistant.respond("open the Photos application"))
        self.assertEqual(self.approval.request.call_count, 1)
        self.provider.chat.assert_not_called()

    def test_empty_failed_listing_not_recorded(self):
        self.start()
        before = self.nav.current
        self.assistant.respond(str(self.downloads / "missing"))
        self.assertEqual(self.nav.current, before)

    def test_model_cannot_forge_guard(self):
        self.provider.chat.return_value = json.dumps({"kind":"tool", "tool_name":"list_directory",
            "arguments":{"path":"~/Downloads"}, "directory_guard":{"permission_granted": True}})
        self.assertIn("failed safely", self.assistant.respond("Can you inspect my downloads folder?"))
        self.assertIsNone(self.nav.current)
        self.approval.request.assert_not_called()

    def test_hybrid_relative_child_uses_trusted_snapshot(self):
        self.start()
        self.provider.chat.return_value = json.dumps({"kind":"tool", "tool_name":"list_directory", "arguments":{"path":"portfolio"}})
        self.assertIn("public.txt", self.assistant.respond("Can you inspect my portfolio folder?"))
        self.assertEqual(self.nav.current.path, str(self.child))
        self.provider.chat.assert_called_once()

    def test_hybrid_unknown_basename_not_invented(self):
        self.start()
        (self.project / "invented").mkdir()
        self.provider.chat.return_value = json.dumps({"kind":"tool", "tool_name":"list_directory", "arguments":{"path":"invented"}})
        self.assertIn("Please name", self.assistant.respond("Can you inspect my invented folder?"))
        self.assertEqual(self.nav.current.path, str(self.downloads))
        self.assertEqual(self.approval.request.call_count, 1)

    def test_unlisted_basename_before_context_requires_location(self):
        (self.project / "portfolio").mkdir()
        self.provider.chat.return_value = json.dumps({"kind":"tool", "tool_name":"list_directory", "arguments":{"path":"portfolio"}})
        self.assertIn("list a folder first", self.assistant.respond("Can you inspect my portfolio folder?"))
        self.assertIsNone(self.nav.current)
        self.approval.request.assert_not_called()
