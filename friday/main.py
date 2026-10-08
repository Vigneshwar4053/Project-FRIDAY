"""Run with: python -m friday.main."""
from contextlib import closing
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


def create_tool_runtime(configuration):
    """Production composition, with explicit project roots and isolated registries."""
    boundary = FileSystemPolicy(
        [configuration.project_root, *configuration.filesystem_read_roots],
        write_roots=[configuration.project_root],
        max_directory_entries=configuration.filesystem_max_directory_entries)
    registry = ToolRegistry()
    register_file_tools(registry, boundary)
    register_system_tools(registry, boundary)
    register_computation_tools(registry)
    return ToolManager(registry), ToolRouter(configuration.project_root)


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
                tool_manager, tool_router = create_tool_runtime(settings)
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
