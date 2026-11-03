"""Token estimation.

Deliberately avoids tiktoken: it downloads encoding files on first use,
which violates the offline requirement.
"""

from __future__ import annotations

import math
import re
from typing import Protocol, runtime_checkable

# CJK punctuation, kana, ideographs, compatibility ideographs, fullwidth forms, hangul.
_CJK_RE = re.compile(
    "[　-〿぀-ヿ㐀-䶿一-鿿豈-﫿＀-￯가-힯]"
)


@runtime_checkable
class TokenEstimator(Protocol):
    name: str

    def estimate(self, text: str) -> int: ...


class CharTokenEstimator:
    """Non-CJK characters / ``chars_per_token`` plus ``cjk_weight`` per CJK character."""

    name = "chars"

    def __init__(self, chars_per_token: float = 4.0, cjk_weight: float = 1.0):
        if chars_per_token <= 0:
            raise ValueError("chars_per_token must be positive")
        self.chars_per_token = chars_per_token
        self.cjk_weight = cjk_weight

    def estimate(self, text: str) -> int:
        if not text:
            return 0
        cjk = len(_CJK_RE.findall(text))
        other = len(text) - cjk
        return math.ceil(other / self.chars_per_token + cjk * self.cjk_weight)

    def estimate_from_size(self, size_bytes: int) -> int:
        """Rough estimate for files that are not read (e.g. too large)."""
        return math.ceil(size_bytes / self.chars_per_token)


DEFAULT_ESTIMATOR = CharTokenEstimator()
