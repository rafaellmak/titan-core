from __future__ import annotations
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class WorkspaceFingerprint:
    workspace_type: str = ""
    architecture: str = ""
    toolchain: str = ""
    libc: str = ""
    board: str = ""
    kernel_version: str = ""
    buildroot_version: str = ""
    yocto_release: str = ""

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, str]) -> WorkspaceFingerprint:
        return WorkspaceFingerprint(**data)


@dataclass
class RiskAssessment:
    """Avaliação de risco de uma correção, derivada do ImpactReport."""
    risk_level: str = "LOW"
    risk_score: float = 0.0
    affected_count: int = 0
    critical_path: List[str] = field(default_factory=list)
    explanation: str = ""


@dataclass
class Recommendation:
    fix_signature: str
    confidence: float
    confidence_level: str
    context_match: int
    evidence_count: int
    success_rate: float
    fingerprint: str
    category: str
    rank_score: float
    raw_confidence: float = 0.0
    adjusted_confidence: float = 0.0
    risk_level: str = "LOW"
    risk_score: float = 0.0
    explanation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


CONFIDENCE_THRESHOLDS = [
    (75, "VERY_HIGH"),
    (50, "HIGH"),
    (25, "MEDIUM"),
    (0, "LOW"),
]


def confidence_level(value: float) -> str:
    for threshold, label in CONFIDENCE_THRESHOLDS:
        if value >= threshold:
            return label
    return "LOW"


def compute_confidence(success_rate: float, context_match: float,
                       occurrences: int, feedback_score: float) -> float:
    occurrence_strength = min(occurrences / 50.0, 1.0)
    return (
        success_rate * 0.35 +
        context_match * 0.35 +
        occurrence_strength * 0.20 +
        feedback_score * 0.10
    )


def compute_adjusted_confidence(raw: float, risk_score: float) -> float:
    """Ajusta a confiança bruta pelo risco do impacto.

    raw:         0.0 – 1.0 (confiança sem risco)
    risk_score:  0.0 – 1.0 (quanto maior, mais arriscado)

    Fórmula:
      raw * 0.75 + (1 - risk_score) * 0.25

    Isso significa que mesmo com risco CRITICAL (0.95),
    a confiança ajustada mantém 75% do peso da confiança bruta.
    """
    return raw * 0.75 + (1.0 - risk_score) * 0.25
