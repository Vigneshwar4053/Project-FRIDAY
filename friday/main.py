"""Run with: python -m friday.main."""
from contextlib import closing
from dataclasses import replace
import json
import sys
from pathlib import Path
from friday.sync import create_synchronization, SynchronizationError
from friday.config.settings import settings
from friday.core.assistant import FridayAssistant
from friday.models import ModelManager
from friday.memory import MemoryManager, MemoryStorageError
from friday.providers.base import ProviderError
from friday.providers.ollama import OllamaProvider
from friday.tools import ToolRegistry, ToolManager
from friday.tools.filesystem import FileSystemPolicy
from friday.tools.files import register_file_tools
from friday.tools.system import register_system_tools
from friday.tools.computation import register_computation_tools
from friday.tools.router import ToolRouter
from friday.tools.access import CLIFileApproval, FilesystemAccess
from friday.tools.grants import PermissionStore, approved_folder
from friday.tools.sensitive import SensitivePaths
from friday.voice.tts import SpeechController
from friday.voice.backend import ProcessCleanupError


def create_tool_runtime(configuration, *, filesystem_approval=None, memory=None):
    """Production composition, with explicit project roots and isolated registries."""
    permission_path = Path(configuration.filesystem_permission_store_path or
                           configuration.project_root / 'data' / 'permissions' / 'grants.json').expanduser()
    profile_root = configuration.project_root / 'data' / 'desktop-profiles'
    sensitive = SensitivePaths([permission_path.parent, configuration.database_path, profile_root,
        *[str(configuration.database_path) + suffix for suffix in ('-wal', '-shm', '-journal')]])
    store = PermissionStore(permission_path, sensitive)
    project_root = approved_folder(str(configuration.project_root), sensitive).folder
    read_roots = [approved_folder(str(root), sensitive).folder
                  for root in configuration.filesystem_read_roots]
    boundary = FileSystemPolicy(
        [project_root, *read_roots],
        write_roots=[project_root],
        max_directory_entries=configuration.filesystem_max_directory_entries,
        sensitive_paths=sensitive, grant_store=store)
    registry = ToolRegistry()
    register_file_tools(registry, boundary)
    register_system_tools(registry, boundary)
    register_computation_tools(registry)
    access = FilesystemAccess(boundary, store, filesystem_approval)
    from friday.desktop.runtime import DesktopPermissionAdapter, register_desktop_tools
    from friday.desktop.routing import DesktopIntentResolver
    from friday.security.owner import OwnerAuthenticator
    owner_auth = OwnerAuthenticator(configuration.project_root / '.env')
    desktop = DesktopPermissionAdapter(project_root=configuration.project_root, sensitive=sensitive,
                                       approval=filesystem_approval, memory=memory,
                                       owner_auth=owner_auth,
                                       duplicate_window_seconds=configuration.desktop_duplicate_window_seconds)
    register_desktop_tools(registry, desktop)
    from friday.desktop.atspi import AtspiBackend
    from friday.desktop.computer_use import ComputerUsePermissions, register_computer_tools
    computer = ComputerUsePermissions(AtspiBackend(), filesystem_approval, owner_auth=owner_auth)
    register_computer_tools(registry, computer)
    manager=ToolManager(registry, filesystem_access=access, desktop_access=desktop, computer_access=computer)
    desktop.list_contents=lambda request: manager.execute(request, persist_metadata=False)
    from friday.tools.discovery import TargetDiscovery
    desktop.discovery=TargetDiscovery(access,desktop.projects,desktop.locations)
    return (manager, ToolRouter(configuration.project_root, desktop_resolver=DesktopIntentResolver(desktop.applications, desktop.recent,desktop.browser,desktop.discovery)))


def main(*, adaptive=None, diagnostics=None, voice_backend=None, voice_notice=None, speech_backend=None) -> None:
    try:
        configuration = replace(settings,
            adaptive_workloads=settings.adaptive_workloads if adaptive is None else adaptive,
            workload_diagnostics=settings.workload_diagnostics if diagnostics is None else diagnostics)
    except (ValueError, TypeError):
        print('Inference/workload configuration is invalid; exiting safely.')
        return
    if configuration.workload_diagnostics and not configuration.adaptive_workloads:
        print('Workload diagnostics require adaptive mode; exiting safely.')
        return
    provider = OllamaProvider(
        settings.ollama_base_url, settings.ollama_model,
        timeout=settings.ollama_timeout, think=settings.ollama_think,
    )
    print(f"{settings.assistant_name} LOCAL AI")
    print(f"Model: {settings.ollama_model}")
    if configuration.adaptive_workloads:
        print("Workloads: adaptive (L0–L3); diagnostics " + ("on" if configuration.workload_diagnostics else "off"))
    speech = SpeechController(speech_backend, write=print)
    print('Speech Output: ' + ('ON' if speech.enabled else 'OFF'))
    print('Microphone: OFF')
    print("Type /q to toggle automatic speech, /voice for confirmed voice input, /speak TEXT for explicit offline speech; exit, quit, or /bye to close. Ctrl+C also exits.\n")
    try:
        with closing(create_synchronization(settings.sync_library_path)) as synchronization:
            print(f"Synchronization: {synchronization.backend_name}")
            if synchronization.fallback_reason:
                print(synchronization.fallback_reason)
            with ModelManager(provider, settings.ollama_model, synchronization=synchronization) as model_manager, \
                 MemoryManager(settings.database_path) as memory:
                try:
                    tool_manager, tool_router = create_tool_runtime(settings, filesystem_approval=CLIFileApproval(), memory=memory)
                except (OSError, ValueError, RuntimeError):
                    print('Filesystem authorization configuration is unavailable; exiting safely.')
                    return
                friday = FridayAssistant(
                    model_manager, settings.system_prompt, memory=memory,
                    recent_memory_limit=settings.recent_memory_limit,
                    tool_manager=tool_manager, tool_router=tool_router,
                    workload_configuration=configuration,
                )
                try:
                    from friday.voice.startup import StartupGreeting
                    interactive = sys.stdin.isatty() and sys.stdout.isatty()
                    if StartupGreeting().greet(speech, interactive=interactive,
                                               diagnostics=configuration.workload_diagnostics):
                        print(tool_manager.desktop_access.recent.show())
                    while True:
                        try:
                            user_input = input("You: ").strip()
                            if not user_input:
                                continue
                            parts = user_input.split(maxsplit=1)
                            command = parts[0].casefold()
                            arguments = parts[1] if len(parts) > 1 else ''
                            if command in {'stop', '/stop'}:
                                if arguments:
                                    print('Usage: stop')
                                else:
                                    tool_manager.computer_access.stop()
                                    tool_manager.desktop_access.stop_handoffs()
                                    if tool_manager.desktop_access.discovery is not None:
                                        tool_manager.desktop_access.discovery.clear()
                                    print('Computer-use STOP set; no further actions authorized.')
                                continue
                            if command.startswith('/') or command in {'exit','quit'}:
                                tool_manager.desktop_access.recent.menu_ids = ()
                                if tool_manager.desktop_access.discovery is not None:
                                    tool_manager.desktop_access.discovery.pending=None
                                    tool_manager.desktop_access.discovery.receipts.clear()
                            # Reserved slash commands never fall through to the
                            # model, including malformed and unknown commands.
                            if command in {'/q', '/voice', '/bye'} and arguments:
                                print('Usage: ' + command)
                                continue
                            if command.startswith('/') and command not in {'/q', '/voice', '/bye', '/speak'}:
                                print('Unknown slash command. Use /q, /voice, /speak TEXT, or /bye.')
                                continue
                            if user_input.lower() in {"exit", "quit", "/bye"}:
                                break
                            if command == '/q':
                                speech.toggle()
                                continue
                            if command == '/voice':
                                from friday.voice.cli import voice_turn
                                response = voice_turn(friday, voice_backend, read=input,
                                    write=lambda message: print(message, flush=True), unavailable_reason=voice_notice)
                                if response is not None:
                                    print(f"\n{settings.assistant_name}: {response}\n", flush=True)
                                    speech.speak_safe_response(response, friday.last_response_metadata)
                                    if configuration.workload_diagnostics and friday.last_performance is not None:
                                        print("[Workload] " + json.dumps(friday.last_performance.public(), sort_keys=True))
                                continue
                            if command == '/speak':
                                if not arguments:
                                    print('Usage: /speak TEXT')
                                    continue
                                speech.speak_explicit(arguments)
                                continue
                            print(f"{settings.assistant_name}: Working...", flush=True)
                            response = friday.respond(user_input)
                            print(f"\n{settings.assistant_name}: {response}\n", flush=True)
                            speech.speak_safe_response(response, friday.last_response_metadata)
                            if configuration.workload_diagnostics and friday.last_performance is not None:
                                print("[Workload] " + json.dumps(friday.last_performance.public(), sort_keys=True))
                        except (KeyboardInterrupt, EOFError):
                            print()
                            break
                        except ProviderError as exc:
                            print(f"\nError: {exc}\n")
                            if configuration.workload_diagnostics and friday.last_performance is not None:
                                print("[Workload] " + json.dumps(friday.last_performance.public(), sort_keys=True))
                finally:
                    try:
                        friday.end_session()
                    finally:
                        if tool_manager.desktop_access is not None:
                            tool_manager.desktop_access.close()
                        if tool_manager.computer_access is not None:
                            tool_manager.computer_access.close()
    except ProcessCleanupError:
        print('Audio process cleanup could not be confirmed; ending this session safely.')
    except MemoryStorageError as exc:
        print(f"\nMemory error: {exc}\n")
    except SynchronizationError as exc:
        print(f"\nSynchronization error: {exc}\n")
    except KeyboardInterrupt:
        print()
    finally:
        speech.shutdown()
    print(f"{settings.assistant_name}: Goodbye.")


def cli_main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='FRIDAY local assistant')
    parser.add_argument('--adaptive', action='store_true', default=None, help='Enable Phase 6D workloads')
    parser.add_argument('--diagnostics', action='store_true', default=None, help='Print redacted session metrics (enables adaptive mode)')
    parser.add_argument('--voice-binary', type=Path, help='Optional local whisper-cli executable')
    parser.add_argument('--voice-model', type=Path, help='Optional local tiny.en model')
    parser.add_argument('--voice-model-sha256', help='Required pinned model SHA-256')
    parser.add_argument('--voice-config', type=Path, help='Owner JSON configuration (default: XDG_CONFIG_HOME/friday/voice.json)')
    parser.add_argument('--check-voice-config', action='store_true', help='Inspect configuration/files/checksum without recording, playback or assistant startup')
    args = parser.parse_args(argv)
    from friday.voice.configuration import configuration_path, resolve_configuration, inspect_configuration
    from friday.voice.backend import LocalVoiceBackend, VoiceError
    voice_backend = None
    notice = None
    path = args.voice_config.expanduser() if args.voice_config is not None else configuration_path()
    try:
        voice = resolve_configuration(binary=args.voice_binary, model=args.voice_model,
                                      model_sha256=args.voice_model_sha256, path=path)
        if args.check_voice_config:
            result = inspect_configuration(voice, path)
            print(json.dumps(result, indent=2, ensure_ascii=True))
            return 0 if result['status'] == 'verified_files' else 1
        if voice is not None:
            voice_backend = LocalVoiceBackend(voice)  # Lazy, no audio/model initialization.
    except VoiceError as error:
        notice = str(error)
        if args.check_voice_config:
            print(json.dumps({'status': 'invalid', 'microphone': 'OFF', 'message': notice}))
            return 1
    main(adaptive=True if args.diagnostics else args.adaptive, diagnostics=args.diagnostics,
         voice_backend=voice_backend, voice_notice=notice)
    return 0


if __name__ == "__main__":
    import signal
    def terminate(signum, frame):
        # SystemExit unwinds voice/TTS subprocess and temporary-directory cleanup
        # and closes the established assistant's session before process exit.
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate)
    raise SystemExit(cli_main())
