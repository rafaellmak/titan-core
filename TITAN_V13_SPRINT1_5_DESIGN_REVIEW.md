# Titan v13 — Revisão Crítica do Design da Sprint 1.5

> **Objetivo**: Validar se a migração para SyncEventBus corrige a causa raiz ou apenas contorna o problema.
> **Princípio**: A melhor solução é a mais simples que resolve o problema real.

---

## 1. Análise da Causa Raiz

### O problema real

```
EventBusInterface exige async def emit()
         ↓
CLI é síncrono
         ↓
Chamadores síncronos não podem await
         ↓
Eventos são descartados
```

**A causa raiz NÃO é** que `LocalEventBus` é async.
**A causa raiz É** que `EventBusInterface` força `async def emit()` em um mundo síncrono.

### Quem usa o EventBus e como

| Consumidor | Arquivo | Contexto | Precisa de async? |
|------------|---------|----------|-------------------|
| `DiagnosticEngine` | diagnostics/engine.py | CLI sync | ❌ Não |
| `AutoFixEngine` | autofix/engine.py | CLI sync | ❌ Não |
| `MultiLayerMemory` | memory.py | CLI sync | ❌ Não |
| `DigitalTwin` | digital_twin.py | Interno | ✅ Sim (já é async) |
| `daemon.py` | daemon.py | FastAPI async | ✅ Sim |
| `SkillPlanner` | planner.py | Daemon async | ✅ Sim |

**Conclusão**: Existem DOIS mundos:
- **Mundo CLI**: síncrono, precisa de `emit()` síncrono
- **Mundo Daemon**: assíncrono, precisa de `emit()` assíncrono

O `EventBusInterface` atual força o mundo CLI a usar async. **Essa é a abstração errada.**

---

## 2. Design Atual (Sprint 1)

```
┌─────────────────────────────────────────────────────────────┐
│                  EventBusInterface (ABC)                    │
│                                                             │
│  @abstractmethod                                            │
│  async def emit(...)          ← força async em tudo        │
│                                                             │
│  @abstractmethod                                            │
│  async def listen()           ← só usado no daemon         │
└─────────────────────────────────────────────────────────────┘
           │                                    │
           ▼                                    ▼
┌─────────────────────┐          ┌─────────────────────────┐
│   LocalEventBus     │          │     SyncEventBus        │
│   (async queue)     │          │     (sync handlers)     │
│                     │          │                         │
│ Usado por:          │          │ Usado por:              │
│ - TitanCore (CLI)  │          │ - Ninguém (código      │
│ - Daemon (FastAPI)  │          │   morto)                │
│                     │          │                         │
│ Problema:           │          │ Problema:               │
│ CLI chama emit()    │          │ Implementa interface    │
│ sem await → evento  │          │ async desnecessariamente│
│ descartado          │          │                         │
└─────────────────────┘          └─────────────────────────┘
```

**Problemas do design atual**:
1. `EventBusInterface` força async em quem não precisa
2. `SyncEventBus` implementa `async def emit()` → ainda precisa de `asyncio.run()` ou `await`
3. `SyncEventBus.listen()` lança `NotImplementedException` → interface quebrada
4. Dois buses diferentes para o mesmo conceito → duplicação

---

## 3. Design Proposto (Sprint 1.5 original)

```
┌─────────────────────────────────────────────────────────────┐
│                  EventBusInterface (ABC)                    │
│                                                             │
│  @abstractmethod                                            │
│  async def emit(...)          ← ainda força async          │
│                                                             │
│  @abstractmethod                                            │
│  async def listen()           ← só daemon usa              │
└─────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────┐
│              SyncEventBus                                │
│                                                         │
│  def emit_sync(...)         ← novo método síncrono      │
│  async def emit(...)        ← chama emit_sync()         │
│  async def listen()         ← NotImplementedError       │
│                                                         │
│  + TitanCore.emit() helper com hasattr("emit_sync")     │
└─────────────────────────────────────────────────────────┘
```

**Problemas do design proposto**:

### 3.1 — `SyncEventBus.emit()` ainda é async

O `SyncEventBus.emit()` continua `async def` para implementar `EventBusInterface`. Isso significa:
- `DigitalTwin.emit_event()` pode usar `await` → OK
- Mas `DiagnosticEngine` NÃO pode usar `await` → precisa do helper `emit_sync()`
- O helper `TitanCore.emit()` usa `hasattr()` para detectar → **code smell**

### 3.2 — `hasattr()` esconde o problema

```python
# TitanCore.emit() proposto
def emit(self, event_type, data):
    bus = self.event_bus
    if hasattr(bus, "emit_sync"):
        bus.emit_sync(event_type, data)
    else:
        bus.emit(event_type, data)  # ← ainda async!
```

Isso é um **type check disfarçado**. Estamos detectando o tipo do bus em runtime em vez de ter uma interface clara.

### 3.3 — `SyncEventBus.listen()` lança exceção

```python
async def listen(self):
    raise NotImplementedError("SyncEventBus usa .on() em vez de .listen()")
```

Isso viola o **Liskov Substitution Principle**. Um `SyncEventBus` NÃO é um `EventBusInterface` completo.

### 3.4 — Dois métodos para a mesma operação

`SyncEventBus` tem `emit()` (async) e `emit_sync()` (sync). Isso confunde: qual usar? Quando?

---

## 4. Trade-offs das Opções

### Opção A: Manter EventBusInterface async + adicionar emit_sync()

**Vantagens**:
- Mínimas mudanças
- Daemon continua funcionando

**Desvantagens**:
- Interface quebrada (Liskov)
- `hasattr()` esconde tipo
- Dois métodos para mesma operação
- Complexidade futura: novos devs não sabem qual usar

**Complexidade**: ⭐⭐⭐ (média — workaround, não solução)

### Opção B: Separar interfaces (SyncEventBusInterface + AsyncEventBusInterface)

```python
class EventBusInterface(ABC):
    """Interface base — apenas métodos comuns."""
    pass

class AsyncEventBusInterface(EventBusInterface):
    @abstractmethod
    async def emit(self, event_type: str, data: Dict[str, Any]): ...

    @abstractmethod
    async def listen(self) -> AsyncGenerator[Dict[str, Any], None]: ...

class SyncEventBusInterface(EventBusInterface):
    @abstractmethod
    def emit(self, event_type: str, data: Dict[str, Any]): ...
```

**Vantagens**:
- Interfaces claras e corretas
- Liskov respeitado
- Type checking funciona

**Desvantagens**:
- Mais classes
- `TitanCore` precisa saber qual tipo está usando
- `DigitalTwin` precisa de async → acoplamento

**Complexidade**: ⭐⭐⭐⭐ (alta — muitas interfaces)

### Opção C: Eliminar asyncio do CLI completamente (RECOMENDADA)

**Premissa**: O CLI é síncrono. O daemon é assíncrono. São dois contextos diferentes. Não devem compartilhar a mesma interface.

```python
# ============================================
# titan/core/event_bus.py — APENAS sync
# ============================================
from abc import ABC, abstractmethod
from typing import Any, Dict

class EventBus(ABC):
    """Event bus interface — síncrona por padrão."""

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
        from collections import defaultdict
        from typing import Callable, List
        self._handlers: Dict[str, List[Callable]] = defaultdict(list)

    def on(self, event_type: str, handler: Callable) -> None:
        self._handlers[event_type].append(handler)

    def emit(self, event_type: str, data: Dict[str, Any]) -> None:
        for handler in self._handlers.get(event_type, []):
            handler(data)


# ============================================
# titan/core/async_event_bus.py — APENAS async
# ============================================
class AsyncEventBus(ABC):
    """Event bus assíncrono — para daemon/FastAPI."""

    @abstractmethod
    async def emit(self, event_type: str, data: Dict[str, Any]) -> None: ...

    @abstractmethod
    async def listen(self) -> AsyncGenerator[Dict[str, Any], None]: ...


class QueuedEventBus(AsyncEventBus):
    """Event bus com queue asyncio — para daemon."""

    def __init__(self):
        self.queue = asyncio.Queue()

    async def emit(self, event_type: str, data: Dict[str, Any]) -> None:
        await self.queue.put({"type": event_type, "data": data})

    async def listen(self) -> AsyncGenerator[Dict[str, Any], None]:
        while True:
            event = await self.queue.get()
            yield event
            self.queue.task_done()
```

**Vantagens**:
- Zero async no CLI → zero RuntimeWarning
- Interfaces claras e separadas
- Liskov respeitado
- Type checking funciona
- Código mais simples de entender
- `DigitalTwin.emit_event()` continua async (usa `await` internamente)

**Desvantagens**:
- Precisa renomear `LocalEventBus` → `QueuedEventBus` (ou manter nome)
- `daemon.py` precisa importar de `async_event_bus`
- `DigitalTwin` precisa de adaptação (ver abaixo)

**Complexidade**: ⭐⭐ (baixa — separação clara)

---

## 5. Impacto no DigitalTwin

O `DigitalTwin.emit_event()` é async e chama `await self.event_bus.emit()`. Com a Opção C:

### Solução: DigitalTwin usa AsyncEventBus internamente

```python
class DigitalTwin:
    def __init__(self, event_bus, base_path=".titan_digital_twin"):
        self.event_bus = event_bus  # Pode ser sync ou async
        self._async_bus = None      # Criado só se necessário
        ...

    async def emit_event(self, event_type: str, data: Dict[str, Any]):
        """Async — sempre funciona."""
        # Persiste no log
        self._persist_event(event_type, data)
        # Atualiza grafo
        self._apply_event({"event": event_type, "data": data})
        # Emite no bus (sync ou async)
        if hasattr(self.event_bus, "emit_sync"):
            self.event_bus.emit(event_type, data)
        else:
            await self.event_bus.emit(event_type, data)
```

**Alternativa mais simples**: `DigitalTwin` NÃO emite no event bus. Quem chama `emit_event()` é responsável por emitir no bus depois.

```python
# Em vez de twin.emit_event() emitir no bus:
await twin.emit_event("layer_added", {"layer": "meta-test"})
# O twin atualiza o grafo internamente

# Quem chama emite no bus:
event_bus.emit("layer_added", {"layer": "meta-test"})
```

**Recomendação**: Alternativa mais simples. `DigitalTwin` é um modelo de dados, não um produtor de eventos.

---

## 6. Solução Recomendada

### Opção C: Eliminar asyncio do CLI

**Mudanças necessárias**:

| Arquivo | Mudança | Complexidade |
|---------|---------|--------------|
| `titan/core/event_bus.py` | Remover `async` de `EventBus` e `LocalEventBus` | Baixa |
| `titan/core/async_event_bus.py` | NOVO — `AsyncEventBus` + `QueuedEventBus` | Baixa |
| `titan/core/core.py` | Importar `LocalEventBus` (sync) | Baixa |
| `titan/core/digital_twin.py` | `emit_event()` não emite no bus (ou usa helper) | Baixa |
| `titan/core/memory.py` | Remover `asyncio.create_task()` | Baixa |
| `titan/diagnostics/engine.py` | `core.event_bus.emit()` → funciona diretamente | Baixa |
| `titan/autofix/engine.py` | Mesmo | Baixa |
| `titan/core/session.py` | Conectar MetricsAgent | Baixa |
| `titan/daemon.py` | Importar de `async_event_bus` | Baixa |

**Total**: 9 arquivos, todas alterações baixas.

### Diagrama final

```
┌─────────────────────────────────────────────────────────────────┐
│                        MUNDO CLI                                │
│                                                                 │
│  CLI → TitanSession → TitanCore → LocalEventBus (sync)          │
│                                      ↓                          │
│                              MetricsAgent.on()                  │
│                                      ↓                          │
│                              RunMetrics                         │
│                                                                 │
│  Zero async. Zero await. Zero RuntimeWarning.                   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                       MUNDO DAEMON                              │
│                                                                 │
│  FastAPI → AsyncEventBus → QueuedEventBus (async queue)         │
│                                      ↓                          │
│                              event_loop_worker()                │
│                                      ↓                          │
│                              SkillPlanner.dispatch()            │
│                                      ↓                          │
│                              Skills → Knowledge → Metrics       │
│                                                                 │
│  Totalmente async. FastAPI gerencia o loop.                     │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    DigitalTwin (compartilhado)                  │
│                                                                 │
│  Async por fora (emit_event), mas NÃO emite no bus.             │
│  Quem chama decide se emite no bus (sync ou async).             │
└─────────────────────────────────────────────────────────────────┘
```

### Por que esta é a melhor solução

1. **Elimina a causa raiz**: CLI não tem async forçado
2. **Interfaces corretas**: `EventBus` é sync, `AsyncEventBus` é async
3. **Liskov respeitado**: Nenhuma interface lança `NotImplementedError`
4. **Type-safe**: `hasattr()` não é mais necessário
5. **Simples**: Cada mundo usa o que precisa
6. **Extensível**: Novos buses implementam a interface correta
7. **Testável**: Testes sync não precisam de `asyncio.run()`

---

## 7. Resposta às Perguntas

### 1. O SyncEventBus deve realmente implementar métodos async?

**NÃO.** Se é sync, deve ter interface sync. Implementar `async def` para satisfazer uma interface errada é um workaround.

### 2. Existe alguma forma de eliminar completamente asyncio do fluxo CLI?

**SIM.** Separar `EventBus` (sync) de `AsyncEventBus` (async). O CLI usa `EventBus`. O daemon usa `AsyncEventBus`. Zero async no CLI.

### 3. O EventBusInterface atual está forçando uma aberragem errada?

**SIM.** Forçar `async def emit()` em código síncrono é a causa raiz do bug. A interface deve refletir o uso real, não um ideal abstrato.

### 4. Devemos ter SyncEventBusInterface + AsyncEventBusInterface ou apenas uma interface?

**Duas interfaces.** Uma sync (`EventBus`), uma async (`AsyncEventBus`). Compartilham um base class vazio se necessário para type hints, mas não forçam métodos que não fazem sentido.

### 5. O helper TitanCore.emit() está escondendo um problema arquitetural?

**SIM.** O `hasattr("emit_sync")` é um type check disfarçado. Com interfaces separadas, cada bus tem a assinatura correta e o type checker resolve.

### 6. Existe uma forma mais simples e explícita de resolver isso?

**SIM.** Eliminar async do CLI completamente. O CLI é síncrono por natureza (argparse, input, print). Forçar async adiciona complexidade sem benefício. A separação clara entre `EventBus` (sync) e `AsyncEventBus` (async) é a solução mais simples e explícita.
