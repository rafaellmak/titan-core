"""EventBus — event bus síncrono para CLI e uso geral.

Handlers são chamados diretamente no emit().
Sem asyncio, sem await, sem RuntimeWarning.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any, Callable, Dict, List


class EventBus(ABC):
    """Interface para event bus síncrono."""

    @abstractmethod
    def emit(self, event_type: str, data: Dict[str, Any]) -> None:
        """Emite evento e entrega a todos os handlers registrados."""
        pass

    @abstractmethod
    def on(self, event_type: str, handler: Callable) -> None:
        """Registra handler para um tipo de evento."""
        pass


class LocalEventBus(EventBus):
    """Event bus síncrono — para CLI e uso geral."""

    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = defaultdict(list)

    def on(self, event_type: str, handler: Callable) -> None:
        self._handlers[event_type].append(handler)

    def emit(self, event_type: str, data: Dict[str, Any]) -> None:
        for handler in self._handlers.get(event_type, []):
            handler(data)
