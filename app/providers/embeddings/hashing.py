"""Local, deterministic feature-hashing embeddings.

This is a *lexical* embedding (hashed unigrams + bigrams with sublinear TF, L2-normalized). It
captures token overlap, not meaning: it will not match "profit" with "earnings". It exists so
retrieval can run offline and deterministically in CI; production uses Titan / Azure OpenAI
embeddings via configuration.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from itertools import pairwise

from app.core.text import content_tokens


class HashingEmbeddingProvider:
    def __init__(self, dimension: int = 512) -> None:
        if dimension < 16:
            raise ValueError("dimension must be >= 16")
        self._dimension = dimension

    @property
    def provider_name(self) -> str:
        return "local"

    @property
    def model_name(self) -> str:
        return f"hashing-lexical-{self._dimension}"

    @property
    def is_mock(self) -> bool:
        return True

    @property
    def dimension(self) -> int:
        return self._dimension

    def _features(self, text: str) -> Counter[str]:
        tokens = content_tokens(text)
        feats: Counter[str] = Counter(tokens)
        feats.update(f"{a}_{b}" for a, b in pairwise(tokens))
        return feats

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self._dimension
        for feat, count in self._features(text).items():
            digest = hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(digest[:4], "little") % self._dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[idx] += sign * (1.0 + math.log(count))
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            return vec
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)
