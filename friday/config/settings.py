"""Central configuration for FRIDAY v0.2."""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    assistant_name: str = "FRIDAY"
    user_name: str = "Vigneshwar"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:4b"
    ollama_timeout: float = 300
    ollama_think: bool = False
    database_path: Path = Path(__file__).resolve().parents[2] / "data" / "friday.db"
    recent_memory_limit: int = 20

    @property
    def system_prompt(self) -> str:
        return f"""You are {self.assistant_name}, {self.user_name}'s personal local AI assistant.
Assist with programming, software engineering, Linux, AI development,
authorized defensive and educational cybersecurity, research, planning,
and automation. Be concise, practical, technically accurate, and clear
about uncertainty. Give final answers without private reasoning.
Clearly distinguish suggesting an action from actually executing it.
This version has no tools and cannot execute computer actions. Never claim
that a computer action was performed unless a future FRIDAY tool actually
performed it. Describe commands as suggestions for the user to run.
""".strip()


settings = Settings()
