"""Model catalog types."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ModelInfo:
    """A model known to a provider, with capabilities and list pricing.

    Prices are per million tokens and reflect public list prices at the time
    of writing; they are approximations used for routing/cost estimates and
    can be overridden in the user's config.
    """

    provider: str
    id: str
    context_window: int = 128_000
    max_output: int = 4_096
    supports_tools: bool = True
    supports_vision: bool = False
    input_price_per_mtok: float | None = None
    output_price_per_mtok: float | None = None
    tags: list[str] = field(default_factory=list)
    local: bool = False

    @property
    def qualified(self) -> str:
        return f"{self.provider}/{self.id}"

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float | None:
        pin, pout = self.input_price_per_mtok, self.output_price_per_mtok
        if pin is None or pout is None:
            return None
        return (input_tokens * pin + output_tokens * pout) / 1_000_000.0
