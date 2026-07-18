from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .models import WorkspaceFingerprint

FIELD_WEIGHTS: Dict[str, int] = {
    "workspace_type": 3,
    "architecture": 3,
    "toolchain": 2,
    "libc": 2,
    "board": 2,
    "kernel_version": 1,
    "buildroot_version": 1,
    "yocto_release": 1,
}

MAX_WEIGHT = sum(FIELD_WEIGHTS.values())


@dataclass
class ContextMatch:
    score: int
    matched_fields: List[Tuple[str, str, str]] = field(default_factory=list)
    mismatched_fields: List[Tuple[str, str, str]] = field(default_factory=list)

    def explain(self) -> str:
        lines = [f"Context Similarity: {self.score}/100"]
        if self.matched_fields:
            lines.append("  Matched:")
            for name, va, vb in self.matched_fields:
                lines.append(f"    {name}: {va} == {vb}")
        if self.mismatched_fields:
            lines.append("  Mismatched:")
            for name, va, vb in self.mismatched_fields:
                w = FIELD_WEIGHTS.get(name, 1)
                penalty = f"(-{w * 100 // MAX_WEIGHT} pts)"
                lines.append(f"    {name}: {va} != {vb} {penalty}")
        return "\n".join(lines)

    def is_compatible(self, threshold: int = 50) -> bool:
        return self.score >= threshold


def compare(a: WorkspaceFingerprint, b: WorkspaceFingerprint) -> ContextMatch:
    matched: List[Tuple[str, str, str]] = []
    mismatched: List[Tuple[str, str, str]] = []
    weighted_score = 0

    for field, weight in FIELD_WEIGHTS.items():
        va = _val(getattr(a, field, ""))
        vb = _val(getattr(b, field, ""))
        if va and vb and va == vb:
            weighted_score += weight
            matched.append((field, va, vb))
        elif va and vb:
            mismatched.append((field, va, vb))

    total = (weighted_score * 100) // MAX_WEIGHT
    return ContextMatch(score=total, matched_fields=matched, mismatched_fields=mismatched)


def _val(s: str) -> str:
    return s.strip().lower().replace(" ", "_") if s else ""
