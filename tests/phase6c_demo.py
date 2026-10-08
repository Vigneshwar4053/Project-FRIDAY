"""Offline production-component demo; no personal files, all state temporary.
Run: PYTHONPATH=. .venv/bin/python -B tests/phase6c_demo.py
"""
from contextlib import closing
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from friday.config.settings import settings
from friday.core.assistant import FridayAssistant
from friday.main import create_tool_runtime
from friday.memory import MemoryManager
from friday.models import ModelManager
from friday.providers.base import ModelProvider
from friday.sync.native import NativeSemaphore
from friday.tools.access import CLIFileApproval


class FixtureProvider(ModelProvider):
    def __init__(self):
        self.calls = 0
        self.response = ''
    def chat(self, messages):
        self.calls += 1
        return self.response


def main():
    with tempfile.TemporaryDirectory(prefix='friday-6c-demo-') as temporary:
        home = Path(temporary)
        project = home / 'FRIDAY'
        downloads = home / 'Downloads'
        project.mkdir()
        downloads.mkdir()
        (downloads / 'public-fixture.txt').write_text('public demo content')
        (downloads / 'portfolio').mkdir()
        (downloads / 'portfolio' / 'public-child.txt').write_text('public child demo')
        (downloads / 'portfolio' / 'data.js').write_text('const demoValue = 42;')
        (downloads / 'portfolio' / 'index.html').write_text('<html>public HTML demo</html>')
        (downloads / 'portfolio' / 'portfolio.zip').write_bytes(b'PK\x00archive fixture')
        for name in ('Imágenes', 'Videos'):
            folder = home / name
            folder.mkdir()
            (folder / 'public-fixture.txt').write_text('public demo content')
        config_home = home / '.config'
        config_home.mkdir()
        (config_home / 'user-dirs.dirs').write_text('XDG_PICTURES_DIR="$HOME/Imágenes"\n')
        config = replace(settings, project_root=project, database_path=project / 'data' / 'memory.db')
        provider = FixtureProvider()
        with patch.dict(os.environ, {'HOME': str(home), 'XDG_CONFIG_HOME': str(home / '.config')}), closing(NativeSemaphore()) as sync, \
             ModelManager(provider, settings.ollama_model, synchronization=sync) as models, \
             MemoryManager(config.database_path) as memory:
            manager, router = create_tool_runtime(config, filesystem_approval=CLIFileApproval())
            assistant = FridayAssistant(models, settings.system_prompt, tool_manager=manager,
                                         tool_router=router, memory=memory)
            def approval(message, choice):
                output = io.StringIO()
                with patch('sys.stdin.isatty', return_value=True), patch('sys.stdout', output), \
                     patch.object(output, 'isatty', return_value=True), patch('builtins.input', return_value=choice) as input_mock:
                    answer = assistant.respond(message)
                input_mock.assert_called_once()
                assert 'Permission required:' in output.getvalue()
                return answer
            def proposal(name, **args):
                provider.response = json.dumps({'kind':'tool','tool_name':name,'arguments':args})
            with patch.object(manager, 'execute', wraps=manager.execute) as execute:
                assert 'public-fixture.txt' in approval('List files in Downloads', '1')
                assert provider.calls == 0
                print('A: deterministic list -> success; zero model calls')
                assert 'public-child.txt' in approval('open portfolio', '1')
                assert assistant.navigation.current.path == str(downloads / 'portfolio')
                assert 'const demoValue = 42;' in approval("what's in data.js?", '1')
                assert 'public HTML demo' in approval('read the index file', '1')
                assert 'Archive browsing is not supported' in assistant.respond('open .zip file')
                assert provider.calls == 0
                print('Known files: verified JS/HTML -> fresh read approvals -> actual text; ZIP refused without read/model')
                assert 'portfolio' in approval('go back', '1')
                assert '[Tool: list_directory]' in assistant.respond('go home')
                assert assistant.navigation.current.path == str(project)
                assert provider.calls == 0
                print('Navigation: Downloads -> portfolio -> back -> project home; fresh CLI approvals; zero model calls')

                proposal('list_directory', path='~/Downloads')
                assert 'public-fixture.txt' in approval('Open Downloads', '1')
                assert provider.calls == 0
                print('B: Open Downloads -> trusted semantic fast path -> CLI approval -> ToolManager success (zero model calls)')
                proposal('list_directory', location='downloads')
                assert 'public-fixture.txt' in approval("What's inside Downloads?", '1')
                assert provider.calls == 1
                print('C: flexible folder request -> success')
                proposal('memory_info')
                assert '[Tool: memory_info]' in assistant.respond('How much RAM do I have?')
                assert provider.calls == 2
                print('D: RAM request -> memory_info success')
                prior = execute.call_count
                provider.response = 'Open Ubuntu Files and select Downloads.'
                assistant.respond('How do I open Downloads?')
                assert execute.call_count == prior and provider.calls == 3
                print('E: instructional question -> one normal chat call; no tool execution')
                provider.response = json.dumps({'kind':'clarification','question':'Which file do you mean?'})
                assert 'Which file' in assistant.respond('Open that file')
                assert execute.call_count == prior and provider.calls == 4
                print('F: missing reference -> clarification; no tool execution')
                assert 'not supported' in assistant.respond('Run rm -rf /')
                assert execute.call_count == prior and provider.calls == 4
                print('G: malicious shell request -> refusal; no model/tool call')
                assert 'FAILED' in assistant.respond('Read ~/.ssh/id_rsa')
                assert provider.calls == 4
                print('H: sensitive path -> blocked; no approval/model call')
                proposal('list_directory', path='~/Downloads')
                tool = manager.registry.get('list_directory').tool
                with patch.object(tool, 'execute', side_effect=AssertionError('Denied tool executed')) as action:
                    assert 'FAILED' in approval('Open Downloads', '3')
                    action.assert_not_called()
                assert provider.calls == 4
                print('I: direct CLI Deny -> no filesystem tool execution; no model retry')
                provider.response = 'Hello!'
                assert assistant.respond('Hello FRIDAY') == 'Hello!'
                assert provider.calls == 5
                print('J: ordinary chat -> normal response; one model call')
                assert 'public-fixture.txt' in approval('FRIDAY, open my photos.', '1')
                assert provider.calls == 5
                assert execute.call_args.args[0].arguments['path'] == str(home / 'Imágenes')
                print('K: voice-ready photos -> localized XDG Pictures mapping; zero model calls')
                proposal('list_directory', location='pictures')
                assert 'public-fixture.txt' in approval('Can you inspect my pictures folder?', '1')
                assert provider.calls == 6
                print('L: unfamiliar wording -> location proposal -> trusted XDG normalization -> approved listing')
                prior = execute.call_count
                assert 'not supported' in assistant.respond('go back from /Downloads')
                assert execute.call_count == prior and provider.calls == 6
                print('M: unsupported navigation -> no model/tool execution')
                assert 'FAILED' in assistant.respond('/Videos')
                assert execute.call_args.args[0].arguments['path'] == '/Videos'
                print('N: explicit /Videos remains exact and is blocked; no home-directory replacement')
                assert 'public-fixture.txt' in approval('~/Videos', '1')
                assert execute.call_args.args[0].arguments['path'] == '~/Videos'
                assert provider.calls == 6
                print('O: explicit ~/Videos -> approved listing; original path spelling retained')
                assert 'public-fixture.txt' in approval('open downloads', '1')
                assert 'data.js' in approval('open portfolio', '1')
                provider.response = 'The verified demo code declares a constant.'
                assert 'declares a constant' in approval('explain data.js', '1')
                assert provider.calls == 7
                assert models.last_job.messages == [] and models.last_job.result is None
                assert assistant.navigation.current.path == str(downloads / 'portfolio')
                print('P: authorized explanation -> one model call; private prompt/job scrubbed; navigation unchanged')
            saved = memory.get_recent_messages(100)
            assert len(saved) == 4  # Only instructional question and ordinary chat.
            assert 'public-fixture.txt' not in json.dumps([m.content for m in saved])
            assistant.end_session()
            assert assistant.file_context.item_count == 0
            print('PASS: actual native mutex and production permission/tool pipeline; fake provider only.')
            print('No live Qwen behavior verified; no personal files accessed; all writable state temporary.')


if __name__ == '__main__':
    main()
