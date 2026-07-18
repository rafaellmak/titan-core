from .contracts import SkillResult, ValidationResult
from .score import Scorer


def generate_report(skill_result: SkillResult, validation: ValidationResult) -> str:
    scorer = Scorer()
    grade = scorer.classify(validation.score)

    lines = [
        "=" * 55,
        f"  Validation Report — {skill_result.skill_name}",
        "=" * 55,
        f"  Result:   {'✓' if skill_result.success else '✗'} {skill_result.summary}",
        f"  Score:    {validation.score}/100 ({grade})",
        f"  Accepted: {'yes' if validation.accepted else 'no'}",
        "",
        "  Checks:",
    ]
    for c in validation.checks:
        mark = "✓" if c.passed else "✗"
        lines.append(f"    [{mark}] {c.name}")
        if c.detail:
            lines.append(f"          {c.detail}")

    if validation.reasons:
        lines.extend(["", "  Reasons:"])
        for r in validation.reasons:
            lines.append(f"    • {r}")

    if validation.artifact_paths:
        lines.extend(["", "  Artifacts:"])
        for a in validation.artifact_paths:
            lines.append(f"    • {a}")

    lines.append("=" * 55)
    return "\n".join(lines)
