"""Run with: python -m friday.main."""
from contextlib import closing
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


def create_tool_runtime(configuration, *, filesystem_approval=None):
    """Production composition, with explicit project roots and isolated registries."""
    permission_path = Path(configuration.filesystem_permission_store_path or
                           configuration.project_root / 'data' / 'permissions' / 'grants.json').expanduser()
    sensitive = SensitivePaths([permission_path.parent, configuration.database_path,
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
    return ToolManager(registry, filesystem_access=access), ToolRouter(configuration.project_root)


def main() -> None:
    provider = OllamaProvider(
        settings.ollama_base_url, settings.ollama_model,
        timeout=settings.ollama_timeout, think=settings.ollama_think,
    )
    print(f"{settings.assistant_name} LOCAL AI")
    print(f"Model: {settings.ollama_model}")
    print("Type exit, quit, or /bye to close. Ctrl+C also exits.\n")
    try:
        with closing(create_synchronization(settings.sync_library_path)) as synchronization:
            print(f"Synchronization: {synchronization.backend_name}")
            if synchronization.fallback_reason:
                print(synchronization.fallback_reason)
            with ModelManager(provider, settings.ollama_model, synchronization=synchronization) as model_manager, \
                 MemoryManager(settings.database_path) as memory:
                try:
                    tool_manager, tool_router = create_tool_runtime(settings, filesystem_approval=CLIFileApproval())
                except (OSError, ValueError, RuntimeError):
                    print('Filesystem authorization configuration is unavailable; exiting safely.')
                    return
                friday = FridayAssistant(
                    model_manager, settings.system_prompt, memory=memory,
                    recent_memory_limit=settings.recent_memory_limit,
                    tool_manager=tool_manager, tool_router=tool_router,
                )
                try:
                    while True:
                        try:
                            user_input = input("You: ").strip()
                            if not user_input:
                                continue
                            if user_input.lower() in {"exit", "quit", "/bye"}:
                                break
                            print(f"{settings.assistant_name}: Working...", flush=True)
                            response = friday.respond(user_input)
                            print(f"\n{settings.assistant_name}: {response}\n")
                        except (KeyboardInterrupt, EOFError):
                            print()
                            break
                        except ProviderError as exc:
                            print(f"\nError: {exc}\n")
                finally:
                    friday.end_session()
    except MemoryStorageError as exc:
        print(f"\nMemory error: {exc}\n")
    except SynchronizationError as exc:
        print(f"\nSynchronization error: {exc}\n")
    except KeyboardInterrupt:
        print()
    print(f"{settings.assistant_name}: Goodbye.")


if __name__ == "__main__":
    main()
