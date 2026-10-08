"""Voice-ready locations, untrusted XDG data and unchanged permission boundaries."""
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from friday.config.settings import settings
from friday.core.assistant import FridayAssistant
from friday.main import create_tool_runtime
from friday.memory import MemoryManager
from friday.providers.base import ModelProvider
from friday.tools.access import FolderDecision
from friday.tools.intent_translator import validate_response
from friday.tools.locations import (SemanticLocationResolver, LocationResolutionError,
                                    MAX_XDG_BYTES, MAX_XDG_LINES)
from friday.tools.models import ToolRequest, ToolErrorCategory, ToolResult, ToolStatus


class LocationFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='friday-location-test-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.project = self.home / 'FRIDAY'
        self.project.mkdir()
        self.config_home = self.home / '.config'
        self.config_home.mkdir()
        self.env = patch.dict(os.environ, {'HOME': str(self.home), 'XDG_CONFIG_HOME': str(self.config_home)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.resolver = SemanticLocationResolver()
        for folder in ('Downloads', 'Pictures', 'Videos', 'Desktop', 'Documents', 'Music'):
            path = self.home / folder
            path.mkdir()
            (path / 'public-fixture.txt').write_text('public fixture text')
        self.approval = Mock()
        self.approval.request.return_value = FolderDecision.ALLOW_ONCE
        config = replace(settings, project_root=self.project, database_path=self.project / 'data' / 'memory.db')
        self.manager, self.router = create_tool_runtime(config, filesystem_approval=self.approval)
        self.provider = Mock(spec=ModelProvider)
        self.provider.chat.return_value = 'Normal conversational answer'
        self.memory = MemoryManager(config.database_path)
        self.addCleanup(self.memory.close)
        self.assistant = FridayAssistant(self.provider, settings.system_prompt,
            tool_manager=self.manager, tool_router=self.router, memory=self.memory)
        self.addCleanup(self.assistant.model_manager.close)
        self.addCleanup(self.assistant.end_session)
        self.execution = patch.object(self.manager, 'execute', wraps=self.manager.execute)
        self.execute = self.execution.start()
        self.addCleanup(self.execution.stop)

    def config(self, body):
        (self.config_home / 'user-dirs.dirs').write_text(body)

    def propose(self, arguments, message='Can you inspect my pictures folder?'):
        self.provider.chat.return_value = json.dumps({'kind':'tool', 'tool_name':'list_directory', 'arguments':arguments})
        return self.assistant.respond(message)

    def fast(self, message, folder):
        self.assertIn('public-fixture.txt', self.assistant.respond(message))
        self.provider.chat.assert_not_called()
        self.assertEqual(self.execute.call_args.args[0].arguments['path'], str(self.home / folder))
        self.assertEqual(self.approval.request.call_args.args[0].target, self.home / folder)

    def test_open_photos(self): self.fast('open photos', 'Pictures')
    def test_show_pictures(self): self.fast('show pictures', 'Pictures')
    def test_bare_pictures(self): self.fast('pictures', 'Pictures')
    def test_open_videos(self): self.fast('open videos', 'Videos')
    def test_open_downloads(self): self.fast('open downloads', 'Downloads')
    def test_open_desktop(self): self.fast('open Desktop', 'Desktop')
    def test_open_documents(self): self.fast('open documents', 'Documents')
    def test_open_music(self): self.fast('open music', 'Music')
    def test_voice_invocation(self): self.fast('FRIDAY, open my photos.', 'Pictures')
    def test_show_my_pictures(self): self.fast('show my pictures', 'Pictures')
    def test_show_my_downloads(self): self.fast('show my downloads', 'Downloads')
    def test_bare_explicit_home_path(self):
        self.assertIn('public-fixture.txt', self.assistant.respond('~/Pictures'))
        self.assertEqual(self.execute.call_args.args[0].arguments['path'], '~/Pictures')
        self.provider.chat.assert_not_called()
    def test_absolute_path_is_exact(self):
        with patch.object(self.manager.registry.get('list_directory').tool, 'execute') as action:
            self.assertIn('FAILED', self.assistant.respond('/Videos'))
            action.assert_not_called()
        self.assertEqual(self.execute.call_args.args[0].arguments['path'], '/Videos')
        self.approval.request.assert_not_called()
        self.provider.chat.assert_not_called()
    def test_absolute_proposal_not_repaired(self):
        self.propose({'path': '/Videos'}, 'Can you inspect /Videos?')
        self.assertEqual(self.execute.call_args.args[0].arguments['path'], '/Videos')
        self.approval.request.assert_not_called()
    def test_location_cannot_override_absolute(self):
        self.assertIn('failed safely', self.propose({'location':'videos'}, 'Can you inspect /Videos?'))
        self.execute.assert_not_called()
    def test_home_path_cannot_override_absolute(self):
        self.propose({'path':'~/Videos'}, 'Can you inspect /Videos?')
        self.execute.assert_not_called()
    def test_unknown_location_not_invented(self):
        self.assertIn('failed safely', self.propose({'location':'holidays'}, 'Take me to my holidays'))
        self.execute.assert_not_called()
    def test_application_not_browsing(self):
        self.assertIn('not supported', self.assistant.respond('open the Photos application'))
        self.execute.assert_not_called()
        self.provider.chat.assert_not_called()
    def test_launch_viewer(self):
        self.assertIn('not supported', self.assistant.respond('launch the photo viewer'))
        self.execute.assert_not_called()
    def test_polite_application(self):
        self.assertIn('not supported', self.assistant.respond('Can you open the Photos application?'))
        self.execute.assert_not_called()
    def test_video_playback_not_browsing(self):
        self.assertIn('not supported', self.assistant.respond('play a video'))
        self.execute.assert_not_called()
        self.provider.chat.assert_not_called()
    def test_polite_playback(self):
        self.assertIn('not supported', self.assistant.respond('Could you play a video?'))
        self.execute.assert_not_called()
    def test_question_remains_chat(self):
        self.assertEqual(self.assistant.respond('how do I open Pictures in Ubuntu?'), 'Normal conversational answer')
        self.execute.assert_not_called()
        self.provider.chat.assert_called_once()
        self.assertEqual(len(self.memory.get_recent_messages(100)), 2)
    def test_question_about_viewer_remains_chat(self):
        self.assistant.respond('How do I launch the photo viewer?')
        self.execute.assert_not_called()
    def test_denial_stops_tool(self):
        self.approval.request.return_value = FolderDecision.DENY
        with patch.object(self.manager.registry.get('list_directory').tool, 'execute') as action:
            response = self.assistant.respond('open photos')
            self.assertIn('permission denied', response)
            action.assert_not_called()
        self.provider.chat.assert_not_called()
    def test_persistence_read_list_only(self):
        self.approval.request.return_value = FolderDecision.ALLOW_PERSISTENT
        self.assistant.respond('open photos')
        self.approval.request.reset_mock()
        self.assertIn('public-fixture.txt', self.assistant.respond('pictures'))
        self.approval.request.assert_not_called()
        info = self.manager.execute(ToolRequest('file_info', {'path':str(self.home / 'Pictures' / 'public-fixture.txt')}))
        self.assertFalse(info.success)
        write = self.manager.execute(ToolRequest('write_file', {'path':str(self.home / 'Pictures' / 'new.txt'), 'content':'no'}))
        self.assertFalse(write.success)
    def test_once_expires(self):
        self.approval.request.side_effect = [FolderDecision.ALLOW_ONCE, FolderDecision.DENY]
        self.assertIn('public-fixture.txt', self.assistant.respond('open photos'))
        self.assertIn('permission denied', self.assistant.respond('pictures'))
        self.assertEqual(self.approval.request.call_count, 2)
    def test_sensitive_xdg_target_denied(self):
        self.config('XDG_PICTURES_DIR="$HOME/.ssh"\n')
        self.assertIn('blocked or invalid', self.assistant.respond('open photos'))
        self.approval.request.assert_not_called()
        self.assertEqual(self.memory.get_recent_messages(100), [])
    def test_symlink_target_denied(self):
        link = self.home / 'PhotoLink'
        link.symlink_to(self.home / 'Pictures', target_is_directory=True)
        self.config('XDG_PICTURES_DIR="$HOME/PhotoLink"\n')
        self.assertIn('FAILED', self.assistant.respond('photos'))
        self.approval.request.assert_not_called()
    def test_invalid_model_json(self):
        self.provider.chat.return_value = 'not json'
        self.assertIn('failed safely', self.assistant.respond('Can you inspect my pictures folder?'))
        self.execute.assert_not_called()
        self.provider.chat.assert_called_once()
    def test_forged_authorization(self):
        self.provider.chat.return_value = json.dumps({'kind':'tool','tool_name':'list_directory',
            'arguments':{'location':'pictures'},'permission_granted':True})
        self.assertIn('failed safely', self.assistant.respond('Can you inspect my photos folder?'))
        self.execute.assert_not_called()
    def test_private_list_not_saved(self):
        self.assistant.respond('open photos')
        self.assertEqual(self.memory.get_recent_messages(100), [])
        self.assertEqual(len(self.assistant.messages), 1)
    def test_xdg_localized_path(self):
        directory = self.home / 'Bilder persönlich'
        directory.mkdir()
        (directory / 'public-fixture.txt').write_text('public')
        self.config('XDG_PICTURES_DIR="$HOME/Bilder persönlich"\n')
        self.assertIn('public-fixture.txt', self.assistant.respond('open photos'))
        self.assertEqual(self.execute.call_args.args[0].arguments['path'], str(directory))
    def test_model_location_resolves_xdg(self):
        directory = self.home / 'Fotografías'
        directory.mkdir()
        (directory / 'public-fixture.txt').write_text('public')
        self.config('XDG_PICTURES_DIR="$HOME/Fotografías"\n')
        self.assertIn('public-fixture.txt', self.propose({'location':'pictures'}))
        self.assertEqual(self.execute.call_args.args[0].arguments['path'], str(directory))
        self.provider.chat.assert_called_once()
        self.assertNotIn(str(directory), json.dumps(self.provider.chat.call_args.args[0]))
    def test_original_path_contract_normalized(self):
        self.assertIn('public-fixture.txt', self.propose({'path':'~/Pictures'}, 'Can you inspect my photos folder?'))
    def test_show_video_location(self):
        self.assertIn('public-fixture.txt', self.propose({'location':'videos'}, 'show me where my videos are'))
    def test_music_question(self):
        self.assertIn('public-fixture.txt', self.propose({'location':'music'}, 'what is inside my music folder?'))
    def test_multiple_locations_clarify(self):
        self.assertIn('failed safely', self.propose({'location':'pictures'}, 'Could you show pictures or videos?'))
        self.execute.assert_not_called()
    def test_location_and_path_rejected(self):
        self.assertIn('failed safely', self.propose({'location':'pictures', 'path':'~/Pictures'}))
        self.execute.assert_not_called()
    def test_no_location_on_read_file(self):
        raw = json.dumps({'kind':'tool','tool_name':'read_file','arguments':{'location':'pictures'}})
        with self.assertRaises(ValueError):
            validate_response(raw, self.manager.registry, locations=self.resolver, message='read pictures')
    def test_navigation_no_model_or_tools(self):
        for text in ('go back from /Downloads', 'go back from Downloads', 'enter that folder'):
            self.assertIn('not supported', self.assistant.respond(text))
        self.execute.assert_not_called()
        self.provider.chat.assert_not_called()
        self.assertEqual(self.memory.get_recent_messages(100), [])
    def test_missing_directory_category(self):
        self.config('XDG_PICTURES_DIR="$HOME/Missing"\n')
        self.assertIn('path is unavailable', self.assistant.respond('photos'))
        self.approval.request.assert_not_called()
    def test_invalid_directory_type_category(self):
        self.config('XDG_PICTURES_DIR="$HOME/Pictures/public-fixture.txt"\n')
        self.assertIn('not a directory', self.assistant.respond('photos'))
        self.approval.request.assert_not_called()
    def test_no_broad_home_authorization(self):
        self.config('XDG_PICTURES_DIR="$HOME"\n')
        self.assertIn('unavailable or invalid', self.assistant.respond('photos'))
        self.execute.assert_not_called()
        self.approval.request.assert_not_called()
    def test_config_does_not_authorize_etc(self):
        self.config('XDG_PICTURES_DIR="/etc"\n')
        self.assertIn('blocked or invalid', self.assistant.respond('photos'))
        self.approval.request.assert_not_called()
    def test_standalone_reply_needs_no_pending_state(self):
        self.provider.chat.return_value = json.dumps({'kind':'clarification','question':'Which folder?'})
        self.assertEqual(self.assistant.respond('Can you open that folder?'), 'Which folder?')
        self.provider.chat.reset_mock()
        self.fast('pictures', 'Pictures')
    def test_store_failure_no_semantic_bypass(self):
        store = self.manager.filesystem_access.store
        with patch.object(store, 'load', side_effect=ValueError('private store text')):
            answer = self.assistant.respond('photos')
        self.assertIn('FAILED', answer)
        self.assertNotIn('private store text', answer)
        self.approval.request.assert_not_called()
    def test_proposal_unknown_keys_not_normalized(self):
        self.assertIn('failed safely', self.propose({'location':'pictures','approval_token':'yes'}))
        self.execute.assert_not_called()
    def test_fast_request_is_still_tool_request(self):
        self.assistant.respond('photos')
        self.assertIsInstance(self.execute.call_args.args[0], ToolRequest)
    def test_sensitive_file_content_privacy_unchanged(self):
        body = 'private-file-body-fixture-unique'
        (self.project / 'source.txt').write_text(body)
        self.assertIn(body, self.assistant.respond('read source.txt'))
        self.assistant.respond('pictures')
        self.assertEqual(self.assistant.file_context.item_count, 0)
        self.assertEqual(self.memory.get_recent_messages(100), [])
        self.provider.chat.assert_not_called()


    def test_voice_question_still_chat(self):
        self.assistant.respond('FRIDAY, how do I open Pictures in Ubuntu?')
        self.execute.assert_not_called()
        self.assertNotIn('intent translator', self.provider.chat.call_args.args[0][0]['content'])
    def test_polite_instruction_is_chat(self):
        self.assistant.respond('Can you show me how to open pictures?')
        self.execute.assert_not_called()
    def test_model_location_cannot_execute_instructional_question(self):
        raw = json.dumps({'kind':'tool','tool_name':'list_directory','arguments':{'location':'pictures'}})
        with self.assertRaises(ValueError):
            validate_response(raw, self.manager.registry, locations=self.resolver,
                              message='How do I open pictures?')
    def test_explicit_question_mark_path_stays_exact(self):
        route = self.router.route('/Videos?')
        self.assertEqual(route.arguments['path'], '/Videos?')
    def test_error_categories_are_typed_and_path_free(self):
        result = self.manager.execute(ToolRequest('list_directory', {'path':str(self.home / 'missing')}))
        self.assertEqual(result.error_category, ToolErrorCategory.UNAVAILABLE_PATH)
        self.assertEqual(result.error, 'Tool execution failed.')
        self.assertNotIn(str(self.home), self.assistant.tool_presenter.format(result))
    def test_invalid_error_category_rejected(self):
        result = self.manager.execute(ToolRequest('list_directory', {'path':str(self.home / 'missing')}))
        with self.assertRaises(ValueError):
            replace(result, error_category='fake private details')
    def test_error_category_cannot_claim_success(self):
        result = self.manager.execute(ToolRequest('list_directory', {'path':str(self.project)}))
        with self.assertRaises(ValueError):
            replace(result, error_category=ToolErrorCategory.PERMISSION_DENIED)

    def test_compound_polite_app_request(self):
        self.assertIn('not supported', self.assistant.respond('Would you please open the Photos application?'))
        self.execute.assert_not_called()
        self.provider.chat.assert_not_called()
    def test_path_contract_cannot_bypass_launch_guard(self):
        raw = json.dumps({'kind':'tool','tool_name':'list_directory','arguments':{'path':'~/Pictures'}})
        with self.assertRaises(ValueError):
            validate_response(raw, self.manager.registry, locations=self.resolver,
                              message='Can you open the Photos application?')

    def test_original_path_contract_cannot_guess_between_concepts(self):
        self.assertIn('failed safely', self.propose({'path':'~/Pictures'}, 'Can you show Pictures or Videos?'))
        self.execute.assert_not_called()


class XDGParserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='friday-xdg-test-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.config_home = self.home / '.config'
        self.config_home.mkdir()
        self.path = self.config_home / 'user-dirs.dirs'
        env = patch.dict(os.environ, {'HOME':str(self.home),'XDG_CONFIG_HOME':str(self.config_home)})
        env.start()
        self.addCleanup(env.stop)
        self.resolver = SemanticLocationResolver()
    def rejected(self, content):
        self.path.write_bytes(content if type(content) is bytes else content.encode())
        with self.assertRaises(LocationResolutionError) as caught:
            self.resolver.resolve('photos')
        self.assertNotIn(str(self.home), str(caught.exception))
    def test_absent_file_default(self):
        self.assertEqual(self.resolver.resolve('photos'), str(self.home / 'Pictures'))
    def test_absent_config_default(self):
        with patch.dict(os.environ, {'XDG_CONFIG_HOME':str(self.home / 'absent')}):
            self.assertEqual(self.resolver.resolve('videos'), str(self.home / 'Videos'))
    def test_missing_entry_default(self):
        self.path.write_text('XDG_MUSIC_DIR="$HOME/Musik"\n')
        self.assertEqual(self.resolver.resolve('pictures'), str(self.home / 'Pictures'))
    def test_absolute_override(self):
        self.path.write_text(f'XDG_PICTURES_DIR="{self.home}/Images"\n')
        self.assertEqual(self.resolver.resolve('photos'), str(self.home / 'Images'))
    def test_comments_and_whitespace(self):
        self.path.write_text('# public mapping\n  XDG_PICTURES_DIR="$HOME/Images" # comment\n')
        self.assertEqual(self.resolver.resolve('pictures'), str(self.home / 'Images'))
    def test_shell_substitution_rejected(self): self.rejected('XDG_PICTURES_DIR="$(touch /tmp/must-not-execute)"\n')
    def test_backticks_rejected(self): self.rejected('XDG_PICTURES_DIR="`command`"\n')
    def test_unknown_expansion_rejected(self): self.rejected('XDG_PICTURES_DIR="$OTHER/Pictures"\n')
    def test_unquoted_assignment_rejected(self): self.rejected('XDG_PICTURES_DIR=$HOME/Pictures\n')
    def test_shell_append_rejected(self): self.rejected('XDG_PICTURES_DIR="$HOME/Pictures"; command\n')
    def test_traversal_rejected(self): self.rejected('XDG_PICTURES_DIR="$HOME/../Pictures"\n')
    def test_duplicate_rejected(self): self.rejected('XDG_PICTURES_DIR="$HOME/A"\nXDG_PICTURES_DIR="$HOME/B"\n')
    def test_invalid_utf8(self): self.rejected(b'\xff')
    def test_control_characters(self): self.rejected('XDG_PICTURES_DIR="$HOME/A\x1bB"\n')
    def test_oversized_file(self): self.rejected('#' * (MAX_XDG_BYTES + 1))
    def test_too_many_lines(self): self.rejected('# mapping\n' * (MAX_XDG_LINES + 1))
    def test_disabled_home(self): self.rejected('XDG_PICTURES_DIR="$HOME"\n')
    def test_disabled_root(self): self.rejected('XDG_PICTURES_DIR="/"\n')
    def test_relative_override(self): self.rejected('XDG_PICTURES_DIR="Pictures"\n')
    def test_config_file_symlink(self):
        source = self.home / 'source'
        source.write_text('XDG_PICTURES_DIR="$HOME/Images"\n')
        self.path.symlink_to(source)
        with self.assertRaises(LocationResolutionError): self.resolver.resolve('photos')
    def test_config_directory_symlink(self):
        link = self.home / 'linked-config'
        link.symlink_to(self.config_home, target_is_directory=True)
        with patch.dict(os.environ, {'XDG_CONFIG_HOME':str(link)}):
            with self.assertRaises(LocationResolutionError): self.resolver.resolve('photos')
    def test_config_special_file(self):
        os.mkfifo(self.path)
        with self.assertRaises(LocationResolutionError): self.resolver.resolve('photos')
    def test_config_hardlink(self):
        self.path.write_text('XDG_PICTURES_DIR="$HOME/Images"\n')
        os.link(self.path, self.home / 'copy')
        with self.assertRaises(LocationResolutionError): self.resolver.resolve('photos')
    def test_unknown_concept(self):
        with self.assertRaises(LocationResolutionError): self.resolver.resolve('holidays')
    def test_unknown_config_syntax(self): self.rejected('export XDG_PICTURES_DIR="$HOME/Images"\n')
    def test_config_reloaded_without_cached_authorization(self):
        self.path.write_text('XDG_PICTURES_DIR="$HOME/A"\n')
        self.assertEqual(self.resolver.resolve('photos'), str(self.home / 'A'))
        self.path.write_text('XDG_PICTURES_DIR="$HOME/B"\n')
        self.assertEqual(self.resolver.resolve('photos'), str(self.home / 'B'))
    def test_relative_config_home(self):
        with patch.dict(os.environ, {'XDG_CONFIG_HOME':'relative'}):
            with self.assertRaises(LocationResolutionError): self.resolver.resolve('photos')
