"""Reproducible Phase 6B demo. Run: PYTHONPATH=. .venv/bin/python -B tests/phase6b_demo.py

All writable state is temporary. Real project source is read only in check J.
The provider is deterministic and offline; authorization never invokes it.
"""
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
from friday.providers.base import ModelProvider
from friday.tools.access import CLIFileApproval


class DemoProvider(ModelProvider):
    def __init__(self, fixture):
        self.fixture = fixture
        self.calls = 0

    def chat(self, messages):
        self.calls += 1
        assert self.fixture in json.dumps(messages)
        assert messages[-1]['content'] == 'explain that code'
        return 'The temporary fixture prints a public greeting.'


def main():
    body = "print('phase6b-public-demo-fixture')"
    provider = DemoProvider(body)
    with tempfile.TemporaryDirectory(prefix='friday-phase6b-demo-') as temporary:
        home = Path(temporary)
        project = home / 'FRIDAY'
        downloads = home / 'Downloads'
        project.mkdir()
        downloads.mkdir()
        (downloads / 'notes.txt').write_text('public fixture')
        (downloads / '.env').write_text('excluded public fixture')
        (project / 'source.py').write_text(body)
        configuration = replace(settings, project_root=project,
            database_path=project / 'data' / 'demo.db',
            filesystem_permission_store_path=project / 'data' / 'permissions' / 'grants.json',
            filesystem_read_roots=(settings.project_root,))

        def new_assistant(memory):
            manager, router = create_tool_runtime(configuration, filesystem_approval=CLIFileApproval())
            return FridayAssistant(provider, configuration.system_prompt, memory=memory,
                tool_manager=manager, tool_router=router)

        def approve(assistant, message, answer):
            output = io.StringIO()
            with patch('sys.stdin.isatty', return_value=True), patch('sys.stdout', output), \
                 patch.object(output, 'isatty', return_value=True), \
                 patch('builtins.input', side_effect=[answer]) as direct_input:
                result = assistant.respond(message)
            direct_input.assert_called_once()
            assert 'Permission required:' in output.getvalue()
            return result

        with patch.dict(os.environ, {'HOME': str(home)}):
            with MemoryManager(configuration.database_path) as memory:
                assistant = new_assistant(memory)
                with assistant.model_manager:
                    assert 'notes.txt' in approve(assistant, 'list files in Downloads', '1')
                    print('A: Unauthorized folder -> direct CLI allow once -> SUCCESS')
                    assert 'FAILED' in approve(assistant, 'list files in Downloads', '3')
                    print('B: Same folder -> approval requested again -> DENIED')
                    assert 'notes.txt' in approve(assistant, 'list files in Downloads', '2')
                    print('C: Direct CLI always allow -> persisted -> SUCCESS')
                    assistant.end_session()

            with MemoryManager(configuration.database_path) as memory:
                assistant = new_assistant(memory)
                with assistant.model_manager:
                    with patch('builtins.input', side_effect=AssertionError('No approval expected')):
                        assert 'notes.txt' in assistant.respond('list files in Downloads')
                    print('D: Restart -> persistent read-only grant -> SUCCESS')
                    assert 'Revoked' in assistant.respond('revoke access to Downloads')
                    assert 'FAILED' in approve(assistant, 'list files in Downloads', '3')
                    print('E: Revoke -> next access requests permission again')
                    tool = assistant.tool_manager.registry.get('list_directory').tool
                    with patch.object(tool, 'execute', side_effect=AssertionError('Denied operation executed')) as execution:
                        assert 'FAILED' in approve(assistant, 'list files in Downloads', '3')
                        execution.assert_not_called()
                    print('F: Deny -> no filesystem tool execution')
                    with patch('builtins.input', side_effect=AssertionError('Sensitive file cannot be approved')):
                        assert 'FAILED' in assistant.respond('read ~/Downloads/.env')
                    print('G: Sensitive file -> blocked without approval')
                    assert provider.calls == 0
                    print('I: All authorization/denial requests so far -> zero model calls')
                    assert body in assistant.respond('read source.py')
                    assert 'public greeting' in assistant.respond('explain that code')
                    assert provider.calls == 1
                    assert memory.get_recent_messages(100) == []
                    assert assistant.file_context.item_count == 0
                    assert assistant.model_manager.last_job.messages == []
                    print('H: Read -> explicit grounded follow-up via offline provider -> no SQLite file body or derived answer')
                    real_source = settings.project_root / 'friday' / 'tools' / 'router.py'
                    response = assistant.respond('read ' + str(real_source))
                    assert response.startswith('[Tool: read_file]\n') and '\nFAILED:' not in response
                    assert 'class ToolRouter' in response
                    print('J: Existing real project router.py read -> SUCCESS (body omitted)')
                    assistant.end_session()
                    assert assistant.file_context.item_count == 0
        assert body.encode() not in configuration.database_path.read_bytes()
        print('No personal documents read; no real project/user files modified. Only temporary fixtures and state written.')


if __name__ == '__main__':
    main()
