"""Validated per-request budgets; never tool authority or model selection."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class InferenceProfile:
    num_predict: int = 512
    num_ctx: int = 8192
    temperature: float = 0.4
    timeout_seconds: float = 300
    max_context_bytes: int = 24576
    max_history_messages: int = 12
    think: bool = False

    def __post_init__(self):
        if type(self.think) is not bool:
            raise ValueError("Thinking control must be boolean.")
        integers = ((self.num_predict, 32, 2048), (self.num_ctx, 1024, 16384),
                    (self.max_context_bytes, 2048, 131072), (self.max_history_messages, 0, 40))
        if any(type(value) is not int or not low <= value <= high for value, low, high in integers):
            raise ValueError('Inference profile budgets are invalid or unbounded.')
        if self.num_ctx <= self.num_predict + 512:
            raise ValueError("Context budget must reserve room for output and template overhead.")
        if self.max_history_messages % 2:
            raise ValueError('History budget must retain complete conversation pairs.')
        for value, low, high in ((self.temperature, 0, 1), (self.timeout_seconds, 1, 600)):
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError('Inference profile settings are invalid or unbounded.')

    @property
    def input_byte_limit(self):
        # Conservative proxy: one UTF-8 byte per possible token, plus a
        # fixed template margin. Not an installed-model tokenizer claim.
        return min(self.max_context_bytes, self.num_ctx - self.num_predict - 512)

    @property
    def options(self):
        return {'num_predict': self.num_predict, 'num_ctx': self.num_ctx, 'temperature': self.temperature}


def deep_profile():
    return InferenceProfile(think=True, num_predict=2048, timeout_seconds=450,
                            max_context_bytes=32768, max_history_messages=16)


def standard_profile():
    """Modest completion headroom; smaller recent-history window on CPU."""
    return InferenceProfile(num_predict=768, temperature=0.3, max_history_messages=6)


STANDARD_RESPONSE_INSTRUCTIONS = (
    'For standard conversation, give the final answer directly and concisely. '
    'Aim for at most 150 words unless the user explicitly requests more. '
    'For explanations use one small example only, then stop. '
    'Do not narrate your planning or internal reasoning. '
    'Keep existing security and untrusted-data instructions authoritative.'
)


DEEP_RESPONSE_INSTRUCTIONS = (
    'Provide a careful technical analysis as a final answer. '
    'Identify assumptions, threats, trade-offs, limitations and practical recommendations. '
    'Prioritize the most important issues; avoid repetition and unnecessary examples. '
    'Aim for at most 350 words unless the user explicitly requests more. '
    'Keep internal deliberation brief and finish with the final answer. '
    'Do not narrate planning or internal reasoning. '
    'Keep existing security and untrusted-data instructions authoritative.'
)
