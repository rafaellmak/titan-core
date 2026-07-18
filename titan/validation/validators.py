from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

from .contracts import SkillResult, ValidationCheck, ValidationResult


class BaseValidator(ABC):
    @abstractmethod
    def can_validate(self, skill_name: str, result: SkillResult) -> bool:
        pass

    @abstractmethod
    def validate(self, result: SkillResult, workspace: Any = None) -> ValidationResult:
        pass


class BuildrootValidator(BaseValidator):
    def can_validate(self, skill_name: str, result: SkillResult) -> bool:
        return skill_name == "BuildrootSkill" or "buildroot" in result.summary.lower()

    def validate(self, result: SkillResult, workspace: Any = None) -> ValidationResult:
        checks: List[ValidationCheck] = []
        ws = workspace

        # .config presente
        config = self._resolve_path(ws, ".config") if ws else Path()
        checks.append(ValidationCheck(
            name="buildroot_config_exists",
            passed=config.exists() if ws else ("arch" in result.raw),
            detail=".config found" if (config.exists() if ws else True) else ".config missing",
        ))

        # output/images existe
        images = self._resolve_path(ws, "output/images") if ws else Path()
        checks.append(ValidationCheck(
            name="buildroot_images_dir",
            passed=images.is_dir() if ws else True,
            detail="output/images/ exists" if (images.is_dir() if ws else True) else "output/images/ missing",
        ))

        # rootfs gerado
        rootfs = self._resolve_path(ws, "output/images/rootfs.tar") if ws else Path()
        checks.append(ValidationCheck(
            name="buildroot_rootfs",
            passed=rootfs.exists() if ws else ("packages" in result.raw and result.raw.get("packages", 0) > 0),
            detail="rootfs.tar found" if (rootfs.exists() if ws else True) else "rootfs.tar missing",
        ))

        # kernel gerado (se esperado)
        kernel_needed = result.raw.get("arch") not in ("", None) if ws else True
        if kernel_needed:
            kernel_img = self._resolve_path(ws, "output/images/zImage") if ws else Path()
            checks.append(ValidationCheck(
                name="buildroot_kernel",
                passed=kernel_img.exists() if ws else True,
                detail="zImage found" if (kernel_img.exists() if ws else True) else "zImage missing",
            ))

        # Arquitectura detectada
        checks.append(ValidationCheck(
            name="buildroot_arch_detected",
            passed=bool(result.raw.get("arch")),
            detail=f"arch={result.raw.get('arch', 'not set')}",
        ))

        # Toolchain
        checks.append(ValidationCheck(
            name="buildroot_toolchain",
            passed=result.raw.get("toolchain_type") != "",
            detail=f"toolchain={result.raw.get('toolchain_type', 'not set')}",
        ))

        passed = sum(1 for c in checks if c.passed)
        score = (passed / len(checks)) * 100 if checks else 0
        return ValidationResult(
            score=round(score, 1),
            accepted=score >= 60,
            checks=checks,
            reasons=self._build_reasons(checks),
        )

    def _resolve_path(self, workspace, suffix: str) -> Path:
        root = workspace if isinstance(workspace, Path) else getattr(workspace, "root_dir", None)
        if not root:
            return Path(suffix)
        return Path(root) / suffix

    def _build_reasons(self, checks: List[ValidationCheck]) -> List[str]:
        reasons = []
        for c in checks:
            if c.passed:
                reasons.append(f"{c.name}: passed")
            else:
                reasons.append(f"{c.name}: failed — {c.detail}")
        return reasons


class YoctoValidator(BaseValidator):
    def can_validate(self, skill_name: str, result: SkillResult) -> bool:
        return skill_name in ("YoctoSkill", "AutoFixSkill") or "yocto" in result.summary.lower()

    def validate(self, result: SkillResult, workspace: Any = None) -> ValidationResult:
        checks: List[ValidationCheck] = []

        # Workspace detectado
        checks.append(ValidationCheck(
            name="yocto_workspace_detected",
            passed=result.raw.get("count", 0) > 0 or result.raw.get("status") in ("indexed", "applied"),
            detail=f"recipes indexed: {result.raw.get('count', 0)}",
        ))

        # Recipes indexados
        count = result.raw.get("count", 0)
        checks.append(ValidationCheck(
            name="yocto_recipes_indexed",
            passed=count > 0,
            detail=f"{count} recipes found",
        ))

        # Fix applied (autofix)
        if result.skill_name == "AutoFixSkill":
            fixed = result.raw.get("fixed", False) or result.raw.get("status") == "applied"
            checks.append(ValidationCheck(
                name="yocto_fix_applied",
                passed=fixed,
                detail="fix applied" if fixed else "fix not applied",
                weight=2.0,
            ))

            # Mutated files válidos
            mutated = result.raw.get("mutated_files", [])
            checks.append(ValidationCheck(
                name="yocto_mutation_valid",
                passed=len(mutated) > 0,
                detail=f"{len(mutated)} files mutated",
                weight=1.5,
            ))

        # Build dir existe (se workspace disponível)
        if workspace:
            build_dir = getattr(workspace, "build_dir", None)
            checks.append(ValidationCheck(
                name="yocto_build_dir",
                passed=build_dir and Path(build_dir).is_dir(),
                detail=f"build_dir: {build_dir}",
            ))

        score = self._compute_score(checks)
        return ValidationResult(
            score=score,
            accepted=score >= 60,
            checks=checks,
            reasons=self._build_reasons(checks),
        )

    def _compute_score(self, checks: List[ValidationCheck]) -> float:
        if not checks:
            return 100.0
        total = sum(c.weight for c in checks)
        scored = sum(c.weight for c in checks if c.passed)
        if total == 0:
            return 0.0
        return round((scored / total) * 100, 1)

    def _build_reasons(self, checks: List[ValidationCheck]) -> List[str]:
        return [f"{c.name}: {'passed' if c.passed else 'failed'}" for c in checks]


class DTSValidator(BaseValidator):
    def can_validate(self, skill_name: str, result: SkillResult) -> bool:
        return skill_name == "DTSSkill" or "dts" in result.summary.lower()

    def validate(self, result: SkillResult, workspace: Any = None) -> ValidationResult:
        checks: List[ValidationCheck] = []
        report = result.raw if isinstance(result.raw, dict) else {}

        # DTS compilou
        dtc_ok = report.get("dtc_compilation", None)
        if dtc_ok is not None:
            checks.append(ValidationCheck(
                name="dts_dtc_compilation",
                passed=dtc_ok,
                detail="dtc compiled successfully" if dtc_ok else "dtc compilation failed",
                weight=3.0,
            ))

        # Warnings
        warnings = report.get("warnings", [])
        if isinstance(warnings, list):
            checks.append(ValidationCheck(
                name="dts_no_critical_warnings",
                passed=len(warnings) == 0,
                detail=f"{len(warnings)} warnings found" if warnings else "no warnings",
                weight=2.0,
            ))

        # Binding check
        binding = report.get("binding_check", None)
        if binding is not None:
            checks.append(ValidationCheck(
                name="dts_binding_check",
                passed=binding,
                detail="binding ok" if binding else "binding failed",
            ))

        # Model/compatible detectado
        model = report.get("model", "") or report.get("compatible", "")
        checks.append(ValidationCheck(
            name="dts_model_detected",
            passed=bool(model),
            detail=f"model={model}" if model else "model not detected",
        ))

        score = self._compute_score(checks)
        return ValidationResult(
            score=score,
            accepted=score >= 60,
            checks=checks,
            reasons=self._build_reasons(checks),
        )

    def _compute_score(self, checks: List[ValidationCheck]) -> float:
        if not checks:
            return 100.0
        total = sum(c.weight for c in checks)
        scored = sum(c.weight for c in checks if c.passed)
        if total == 0:
            return 0.0
        return round((scored / total) * 100, 1)

    def _build_reasons(self, checks: List[ValidationCheck]) -> List[str]:
        return [f"{c.name}: {'passed' if c.passed else 'failed'}" for c in checks]


class SecurityValidator(BaseValidator):
    def can_validate(self, skill_name: str, result: SkillResult) -> bool:
        return skill_name == "SecuritySkill" or "cve" in result.summary.lower()

    def validate(self, result: SkillResult, workspace: Any = None) -> ValidationResult:
        findings = result.raw if isinstance(result.raw, list) else []
        checks: List[ValidationCheck] = []

        checks.append(ValidationCheck(
            name="security_scan_completed",
            passed=len(result.messages) == 0 or "error" not in str(result.messages),
            detail="scan completed" if result.success else "scan failed",
        ))

        critical = sum(1 for f in findings if isinstance(f, dict) and f.get("severity") in ("Critical", "High"))
        checks.append(ValidationCheck(
            name="security_no_critical",
            passed=critical == 0,
            detail=f"{critical} critical/high vulnerabilities found" if critical else "no critical vulnerabilities",
            weight=3.0,
        ))

        checks.append(ValidationCheck(
            name="security_cves_checked",
            passed=len(findings) > 0 or not result.success,
            detail=f"{len(findings)} CVEs checked",
        ))

        score = self._compute_score(checks)
        return ValidationResult(
            score=score,
            accepted=score >= 50,
            checks=checks,
            reasons=self._build_reasons(checks),
        )

    def _compute_score(self, checks: List[ValidationCheck]) -> float:
        if not checks:
            return 100.0
        total = sum(c.weight for c in checks)
        scored = sum(c.weight for c in checks if c.passed)
        if total == 0:
            return 0.0
        return round((scored / total) * 100, 1)

    def _build_reasons(self, checks: List[ValidationCheck]) -> List[str]:
        return [f"{c.name}: {'passed' if c.passed else 'failed'}" for c in checks]


# Registry of all available validators
REGISTRY: List[BaseValidator] = [
    BuildrootValidator(),
    YoctoValidator(),
    DTSValidator(),
    SecurityValidator(),
]
