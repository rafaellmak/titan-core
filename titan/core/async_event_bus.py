"""AsyncEventBus — event bus assíncrono para daemon/FastAPI.

Usa asyncio.Queue para entrega assíncrona de eventos.
O daemon consome eventos via listen() em loop async.
"""
from __future__ import annotations
import asyncio
from abc import ABC, abstractmethod
from typing import Any, Dict, AsyncGenerator


class AsyncEventBus(ABC):
    """Interface para event bus assíncrono."""

    @abstractmethod
    async def emit(self, event_type: str, data: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    async def listen(self) -> AsyncGenerator[Dict[str, Any], None]:
        pass


class QueuedEventBus(AsyncEventBus):
    """Event bus com queue asyncio — para daemon."""

    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()

    async def emit(self, event_type: str, data: Dict[str, Any]) -> None:
        await self.queue.put({"type": event_type, "data": data})

    async def listen(self) -> AsyncGenerator[Dict[str, Any], None]:
        while True:
            event = await self.queue.get()
            yield event
            self.queue.task_done()
