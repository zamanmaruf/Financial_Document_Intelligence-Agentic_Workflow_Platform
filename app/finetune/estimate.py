"""Training-token and cost estimate for a fine-tuning job, and the spending guard around it.

Token counts use the model's tiktoken encoding with the usual chat overhead (a few tokens per
message plus the reply primer), so they are close to, not identical with, what the provider
bills. Prices come from the ``fine_tuning`` section of ``config/pricing.yaml``; they are
illustrative and must be checked against the provider's price list before submitting.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

TOKENS_PER_MESSAGE = 3
REPLY_PRIMER_TOKENS = 3
DEFAULT_COST_CAP_USD = 30.0


class Encoding(Protocol):
    def encode(self, text: str) -> list[int]: ...


def record_tokens(record: dict[str, Any], encoding: Encoding) -> int:
    total = REPLY_PRIMER_TOKENS
    for message in record["messages"]:
        total += TOKENS_PER_MESSAGE
        total += len(encoding.encode(message["role"]))
        total += len(encoding.encode(message["content"]))
    return total


@dataclass(frozen=True)
class TrainingEstimate:
    base_model: str
    examples: int
    epochs: int
    tokens_per_epoch: int
    max_example_tokens: int
    billed_tokens: int
    price_per_1m_tokens: float
    cost_usd: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate_training(
    records: list[dict[str, Any]],
    base_model: str,
    epochs: int,
    price_per_1m_tokens: float,
    encoding: Encoding,
) -> TrainingEstimate:
    if epochs < 1:
        raise ValueError("epochs must be at least 1")
    counts = [record_tokens(r, encoding) for r in records]
    per_epoch = sum(counts)
    billed = per_epoch * epochs
    return TrainingEstimate(
        base_model=base_model,
        examples=len(records),
        epochs=epochs,
        tokens_per_epoch=per_epoch,
        max_example_tokens=max(counts, default=0),
        billed_tokens=billed,
        price_per_1m_tokens=price_per_1m_tokens,
        cost_usd=round(billed / 1_000_000 * price_per_1m_tokens, 4),
    )


def training_prices(config_dir: Path) -> dict[str, float]:
    """Base model -> USD per 1M training tokens, from ``config/pricing.yaml``."""
    data = yaml.safe_load((config_dir / "pricing.yaml").read_text(encoding="utf-8")) or {}
    section = data.get("fine_tuning") or {}
    return {model: float(entry["training_per_1m"]) for model, entry in section.items()}


def check_budget(estimate_usd: float, confirmed_usd: float | None, cap_usd: float) -> None:
    """Refuse to submit unless the estimate is under the cap and the user confirmed at least it.

    ``confirmed_usd`` is the amount the user typed after reading the estimate; it is compared
    with the estimate rounded up to the cent.
    """
    if estimate_usd > cap_usd:
        raise ValueError(f"estimated cost ${estimate_usd:.2f} exceeds the ${cap_usd:.2f} cap")
    if confirmed_usd is None:
        raise ValueError(
            f"estimated cost ${estimate_usd:.2f}: rerun with --confirm-cost-usd to submit"
        )
    if confirmed_usd < math.ceil(estimate_usd * 100) / 100:
        raise ValueError(
            f"confirmed ${confirmed_usd:.2f} is below the estimated ${estimate_usd:.2f}"
        )
    if confirmed_usd > cap_usd:
        raise ValueError(f"confirmed ${confirmed_usd:.2f} exceeds the ${cap_usd:.2f} cap")
