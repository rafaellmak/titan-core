from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ErrorSignature:
    category: str
    fingerprint: str
    raw: str = ""

    @staticmethod
    def from_raw(raw: dict, skill_name: str = "") -> ErrorSignature:
        error_text = raw.get("error", "") or raw.get("summary", "") or ""
        if "buildroot" in skill_name.lower() or raw.get("type") == "buildroot":
            category = "BuildrootError"
        elif "yocto" in skill_name.lower() or "autofix" in skill_name.lower():
            category = "YoctoError"
        elif "dts" in skill_name.lower():
            category = "DTSError"
        elif "security" in skill_name.lower():
            category = "SecurityError"
        else:
            category = "GenericError"
        fingerprint = error_text.strip()[:200] if error_text else "unknown"
        return ErrorSignature(category=category, fingerprint=fingerprint, raw=error_text)

    def to_dict(self) -> dict:
        return {"category": self.category, "fingerprint": self.fingerprint}

    def __hash__(self) -> int:
        return hash((self.category, self.fingerprint))


@dataclass
class SkillResult:
    success: bool
    skill_name: str
    summary: str
    artifacts: List[str] = field(default_factory=list)
    messages: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_skill(skill_name: str, raw: Dict[str, Any]) -> SkillResult:
        success = raw.get("status") in ("indexed", "ok", "applied") or "error" not in raw
        summary = raw.get("status", str(raw.get("error", "completed")))
        return SkillResult(
            success=success,
            skill_name=skill_name,
            summary=summary,
            raw=raw,
            messages=[raw.get("error", "")] if "error" in raw else [],
        )


@dataclass
class ValidationCheck:
    name: str
    passed: bool
    detail: str = ""
    weight: float = 1.0


@dataclass
class ValidationResult:
    score: float
    accepted: bool
    checks: List[ValidationCheck] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    artifact_paths: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "accepted": self.accepted,
            "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in self.checks],
            "reasons": self.reasons,
            "artifact_paths": self.artifact_paths,
        }
