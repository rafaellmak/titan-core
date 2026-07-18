from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from titan.core.memory import MultiLayerMemory
from titan.core.digital_twin import DigitalTwin
from titan.core.knowledge_engine import KnowledgeEngine

if TYPE_CHECKING:
    from titan.validation.harness import ValidationHarness

class Skill(ABC):
    @abstractmethod
    def can_handle(self, event_type: str, data: Dict[str, Any]) -> bool:
        pass

    @abstractmethod
    async def execute(self, data: Dict[str, Any], memory: MultiLayerMemory, digital_twin: DigitalTwin, knowledge_engine: KnowledgeEngine) -> Any:
        pass

class SkillPlanner:
    def __init__(self, memory: MultiLayerMemory, digital_twin: DigitalTwin,
                 knowledge_engine: KnowledgeEngine,
                 harness: Optional[ValidationHarness] = None):
        self.memory = memory
        self.digital_twin = digital_twin
        self.knowledge_engine = knowledge_engine
        self.harness = harness
        self.skills: List[Skill] = []

    def register_skill(self, skill: Skill):
        self.skills.append(skill)

    async def dispatch(self, event_type: str, data: Dict[str, Any]):
        self.memory.log_event("DISPATCH_START", {"event_type": event_type, "data": data})

        handled = False
        for skill in self.skills:
            if skill.can_handle(event_type, data):
                try:
                    if self.harness:
                        _result, validation = await self.harness.execute(
                            skill, data, self.memory,
                            self.digital_twin, self.knowledge_engine,
                        )
                        self.memory.log_event("SKILL_SUCCESS", {
                            "skill": skill.__class__.__name__,
                            "score": validation.score,
                            "accepted": validation.accepted,
                        })
                    else:
                        _result = await skill.execute(
                            data, self.memory, self.digital_twin, self.knowledge_engine
                        )
                        self.memory.log_event("SKILL_SUCCESS", {
                            "skill": skill.__class__.__name__,
                            "result": _result,
                        })
                    handled = True
                except Exception as e:
                    self.memory.log_event("SKILL_ERROR", {
                        "skill": skill.__class__.__name__,
                        "error": str(e),
                    }, status="ERROR")

        if not handled:
            self.memory.log_event("UNHANDLED_EVENT", {
                "event_type": event_type,
            }, status="WARNING")
