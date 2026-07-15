from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class PathSegment:
    points: list[tuple[float, float]]  # (t, x) pairs, ascending in t
    style: Literal["solid", "dashed"] = "solid"

    def to_dict(self) -> dict:
        return {"points": self.points, "style": self.style}

    @classmethod
    def from_dict(cls, d: dict) -> "PathSegment":
        return cls(points=[tuple(p) for p in d["points"]], style=d.get("style", "solid"))
