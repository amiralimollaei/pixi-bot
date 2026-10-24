from __future__ import annotations

import array
from dataclasses import dataclass


@dataclass
class Embedding:
    text: str
    dim: int
    vec: array.array[float]
