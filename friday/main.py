"""Run with: python -m friday.main."""
from friday.config.settings import settings
from friday.core.assistant import FridayAssistant
from friday.providers.base import ProviderError
from friday.providers.ollama import OllamaProvider


def main() -> None:
    provider = OllamaProvider(
        settings.ollama_base_url, settings.ollama_model,
        timeout=settings.ollama_timeout, think=settings.ollama_think,
    )
    friday = FridayAssistant(provider, settings.system_prompt)
    print(f"{settings.assistant_name} LOCAL AI")
    print(f"Model: {settings.ollama_model}")
    print("Type exit, quit, or /bye to close. Ctrl+C also exits.\n")
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
    print(f"{settings.assistant_name}: Goodbye.")


if __name__ == "__main__":
    main()
