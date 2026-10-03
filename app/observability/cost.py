"""Token cost estimation from a configurable price table (``config/pricing.yaml``)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class ModelPrice(BaseModel):
    input_per_1k: float
    output_per_1k: float


class CostEstimator:
    def __init__(self, prices: dict[str, ModelPrice]) -> None:
        self._prices = prices

    @classmethod
    def load(cls, config_dir: Path) -> CostEstimator:
        path = config_dir / "pricing.yaml"
        if not path.exists():
            return cls({})
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        prices = {name: ModelPrice.model_validate(p) for name, p in data.get("models", {}).items()}
        for alias, target in (data.get("aliases") or {}).items():
            if target in prices:
                prices[alias] = prices[target]
        return cls(prices)

    def estimate(self, model_name: str, input_tokens: int, output_tokens: int) -> float | None:
        """Estimated USD cost, or ``None`` when the model has no price entry (unknown, not free)."""
        price = self._prices.get(model_name)
        if price is None:
            return None
        cost = input_tokens / 1000 * price.input_per_1k + output_tokens / 1000 * price.output_per_1k
        return round(cost, 8)

    def known(self, model_name: str) -> bool:
        return model_name in self._prices
