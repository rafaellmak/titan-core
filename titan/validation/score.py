from typing import List
from .contracts import ValidationCheck


class Scorer:
    def __init__(self, weights: dict | None = None):
        self.weights = weights or {}

    def compute(self, checks: List[ValidationCheck]) -> float:
        if not checks:
            return 100.0
        total_weight = 0.0
        scored = 0.0
        for c in checks:
            w = self.weights.get(c.name, c.weight)
            total_weight += w
            if c.passed:
                scored += w
        if total_weight == 0:
            return 0.0
        return round((scored / total_weight) * 100, 1)

    def classify(self, score: float) -> str:
        if score >= 90:
            return "excellent"
        if score >= 70:
            return "good"
        if score >= 50:
            return "needs_review"
        return "rejected"
