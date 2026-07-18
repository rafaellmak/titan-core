"""MetricsAgent — escuta eventos e atualiza métricas.

Desacopla a coleta de métricas dos engines.
Em vez de DiagnosticEngine e AutoFixEngine conhecerem métricas,
este agente reage a eventos do EventBus.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

from titan.core.event_bus import EventBus

if TYPE_CHECKING:
    from titan.core.metrics import RunMetrics


class MetricsAgent:
    """Atualiza métricas com base em eventos do EventBus."""

    def __init__(self, metrics: RunMetrics):
        self.metrics = metrics

    def on_diagnose_completed(self, data: dict):
        self.metrics.record_step("diagnose", data)

    def on_fix_applied(self, data: dict):
        self.metrics.record_step("fix_applied", data)

    def on_fix_failed(self, data: dict):
        self.metrics.record_step("fix_failed", data)

    def register(self, event_bus: EventBus) -> None:
        """Registra handlers no event bus."""
        event_bus.on("diagnose_completed", self.on_diagnose_completed)
        event_bus.on("fix_applied", self.on_fix_applied)
        event_bus.on("fix_failed", self.on_fix_failed)
