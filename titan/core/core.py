"""TitanCore — núcleo compartilhado de serviços.

Agrupa apenas os 4 serviços fundamentais:
  - EventBus (comunicação)
  - DigitalTwin (modelo do workspace)
  - KnowledgeEngine (base de conhecimento)
  - MultiLayerMemory (memória persistente + SkillPlanner)

Não conhece workspace, skills, métricas ou CLI.
"""
from titan.core.event_bus import LocalEventBus, EventBus
from titan.core.digital_twin import DigitalTwin
from titan.core.knowledge_engine import KnowledgeEngine
from titan.core.memory import MultiLayerMemory
from titan.core.planner import SkillPlanner


class TitanCore:
    """Serviços core compartilhados entre sessões.

    O KnowledgeEngine é criado aqui e injetado no MultiLayerMemory,
    garantindo uma única base de conhecimento por processo.
    """

    def __init__(self, event_bus: EventBus | None = None):
        self.event_bus: EventBus = event_bus or LocalEventBus()
        self.digital_twin = DigitalTwin(self.event_bus)
        self.knowledge_engine = KnowledgeEngine()
        self.memory = MultiLayerMemory(
            event_bus=self.event_bus,
            knowledge_engine=self.knowledge_engine,
            digital_twin=self.digital_twin,
        )
        self.planner = SkillPlanner(
            memory=self.memory,
            digital_twin=self.digital_twin,
            knowledge_engine=self.knowledge_engine,
        )
