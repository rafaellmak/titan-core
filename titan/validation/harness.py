from __future__ import annotations
from typing import Any, Dict, List, Optional

from titan.core.planner import Skill, SkillPlanner
from titan.core.memory import MultiLayerMemory
from titan.core.digital_twin import DigitalTwin
from titan.core.knowledge_engine import KnowledgeEngine
from .contracts import ErrorSignature, SkillResult, ValidationResult
from .history import ValidationHistory
from .score import Scorer
from .report import generate_report
from .validators import REGISTRY, BaseValidator


class ValidationHarness:
    """Wraps skill execution with deterministic validation + history recording.

    Usage:
        harness = ValidationHarness()
        result, validation = await harness.execute(skill, data, memory, twin, ke)
        if validation.accepted:
            # apply result
        else:
            # reject or retry
    """

    def __init__(self, validators: Optional[List[BaseValidator]] = None,
                 history: Optional[ValidationHistory] = None):
        self.validators = validators or REGISTRY
        self.scorer = Scorer()
        self.history_log: List[dict] = []
        self.validation_history = history or ValidationHistory()

    async def execute(
        self,
        skill: Skill,
        data: Dict[str, Any],
        memory: MultiLayerMemory,
        digital_twin: DigitalTwin,
        knowledge_engine: KnowledgeEngine,
        workspace: Any = None,
        workspace_hash: str = "",
        twin_snapshot_id: str = "",
        metadata: dict | None = None,
    ) -> tuple[SkillResult, ValidationResult]:
        self.validation_history.start_run(skill.__class__.__name__)
        raw = await skill.execute(data, memory, digital_twin, knowledge_engine)
        if raw is None:
            raw = {}

        result = SkillResult.from_skill(skill.__class__.__name__, raw)

        validator = self._find_validator(result)
        if validator:
            validation = validator.validate(result, workspace=workspace)
        else:
            validation = ValidationResult(
                score=100.0,
                accepted=True,
                checks=[],
                reasons=["no validator found — accepted by default"],
            )

        # Extract fix_signature from result if available
        fix_sig = raw.get("action", "") or raw.get("fix", "") or ""

        # Extract error signature
        error_sig = ErrorSignature.from_raw(raw, result.skill_name)

        # Persist run
        run_id = self.validation_history.finish_run(
            result=result,
            validation=validation,
            error_sig=error_sig,
            fix_signature=fix_sig,
            workspace_hash=workspace_hash,
            twin_snapshot_id=twin_snapshot_id,
            metadata=metadata,
        )

        self.history_log.append({
            "run_id": run_id,
            "skill": result.skill_name,
            "success": result.success,
            "score": validation.score,
            "accepted": validation.accepted,
        })
        return result, validation

    def _find_validator(self, result: SkillResult) -> Optional[BaseValidator]:
        for v in self.validators:
            if v.can_validate(result.skill_name, result):
                return v
        return None

    def get_report(self, result: SkillResult, validation: ValidationResult) -> str:
        return generate_report(result, validation)

    def get_summary(self) -> Dict[str, Any]:
        if not self.history_log:
            return {"executions": 0}
        total = len(self.history_log)
        accepted = sum(1 for h in self.history_log if h["accepted"])
        avg_score = sum(h["score"] for h in self.history_log) / total
        return {
            "executions": total,
            "accepted": accepted,
            "rejected": total - accepted,
            "avg_score": round(avg_score, 1),
        }


async def validate_dispatch(
    planner: SkillPlanner,
    event_type: str,
    data: Dict[str, Any],
    harness: ValidationHarness,
    workspace: Any = None,
) -> list[tuple[SkillResult, ValidationResult]]:
    """Dispatcher que executa skills com validação.

    Em vez de planner.dispatch(), usa este helper para obter
    SkillResult + ValidationResult para cada skill executada.
    """
    results: list[tuple[SkillResult, ValidationResult]] = []

    for skill in planner.skills:
        if skill.can_handle(event_type, data):
            try:
                result, validation = await harness.execute(
                    skill, data, planner.memory,
                    planner.digital_twin, planner.knowledge_engine,
                    workspace=workspace,
                )
                results.append((result, validation))

                if result.success:
                    planner.memory.log_event("SKILL_SUCCESS", {
                        "skill": result.skill_name,
                        "score": validation.score,
                        "accepted": validation.accepted,
                    })
                else:
                    planner.memory.log_event("SKILL_ERROR", {
                        "skill": result.skill_name,
                        "error": result.summary,
                    }, status="ERROR")
            except Exception as e:
                planner.memory.log_event("SKILL_ERROR", {
                    "skill": skill.__class__.__name__,
                    "error": str(e),
                }, status="ERROR")

    if not results:
        planner.memory.log_event("UNHANDLED_EVENT", {
            "event_type": event_type,
        }, status="WARNING")

    return results
