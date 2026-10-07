"""Model names and selection metadata; never loads or unloads a model."""


class ModelRegistry:
    def __init__(self):
        self._models: dict[str, None] = {}
        self.default_model: str | None = None
        self.current_model: str | None = None
        self.active_model: str | None = None

    @property
    def registered_models(self) -> tuple[str, ...]:
        return tuple(self._models)

    def register(self, model: str) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError('A model needs a nonblank name.')
        self._models[model] = None
        if self.default_model is None:
            self.default_model = model
            self.current_model = model

    def _require_registered(self, model: str) -> None:
        if model not in self._models:
            raise ValueError(f'Model {model!r} is not registered.')

    def set_default(self, model: str) -> None:
        self._require_registered(model)
        self.default_model = model

    def select(self, model: str) -> None:
        self._require_registered(model)
        self.current_model = model

    def mark_active(self, model: str) -> None:
        """Track the last model used for a provider call, not Ollama load state."""
        self._require_registered(model)
        self.active_model = model
