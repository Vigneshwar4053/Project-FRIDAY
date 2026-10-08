"""Central configuration and identity for FRIDAY."""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    project_root: Path = Path(__file__).resolve().parents[2]
    # Trusted opt-in configuration only; no personal directories enabled by default.
    filesystem_read_roots: tuple[Path | str, ...] = ()
    filesystem_max_directory_entries: int = 100
    assistant_name: str = "FRIDAY"
    user_name: str = "Vigneshwar"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:4b"
    ollama_timeout: float = 300
    ollama_think: bool = False
    database_path: Path = Path(__file__).resolve().parents[2] / "data" / "friday.db"
    recent_memory_limit: int = 20
    sync_library_path: Path = Path(__file__).resolve().parents[2] / "native" / "sync" / "libfriday_sync.so"

    @property
    def system_prompt(self) -> str:
        return f"""You are {self.assistant_name}, {self.user_name}'s personal local AI assistant.
Assist with programming, software engineering, Linux, AI development,
authorized defensive and educational cybersecurity, research, planning,
and automation. Be concise, practical, technically accurate, and clear
about uncertainty. Give final answers without private reasoning.
Clearly distinguish suggesting an action from actually executing it.
You have no tools or direct execution access. The CLI separately routes narrow
read-only intents to verified tools. Never claim that you performed an action.
Tool-labeled history contains previous snapshots, not necessarily current state.
Do not guess live system facts that are absent from the supplied context.
Describe commands as suggestions for the user to run.
""".strip()


settings = Settings()
