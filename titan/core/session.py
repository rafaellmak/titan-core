"""TitanSession — sessão de execução.

Uma sessão combina:
  - Um TitanCore (serviços compartilhados)
  - Um workspace detectado
  - Métricas de execução
  - Registro de plugins/skills

Múltiplas sessões podem compartilhar o mesmo TitanCore.
"""
from __future__ import annotations
from pathlib import Path
from typing import TYPE_CHECKING

from titan.workspace.detector import WorkspaceDetector
from titan.core.metrics import RunMetrics
from titan.core.metrics_agent import MetricsAgent

if TYPE_CHECKING:
    from titan.core.core import TitanCore


class TitanSession:
    """Sessão de execução do Titan.

    Combina core compartilhado com estado específico da sessão.
    """

    def __init__(self, core: TitanCore, workspace_path: str = "."):
        self.core = core
        self.workspace = WorkspaceDetector.detect(workspace_path)
        self.metrics = RunMetrics()
        # Conectar MetricsAgent ao event bus para atualização automática
        self._metrics_agent = MetricsAgent(self.metrics)
        self._metrics_agent.register(self.core.event_bus)

    @property
    def event_bus(self):
        return self.core.event_bus

    @property
    def digital_twin(self):
        return self.core.digital_twin

    @property
    def knowledge_engine(self):
        return self.core.knowledge_engine

    @property
    def memory(self):
        return self.core.memory

    @property
    def planner(self):
        return self.core.planner

    def register_skill(self, skill):
        """Registra uma skill no planner da sessão."""
        self.core.planner.register_skill(skill)
