# Titan v13 — Sprint 1.5: Migração para SyncEventBus

> **Objetivo**: Eliminar o gargalo de eventos async em código síncrono.
> **Critério de aceite**: Zero RuntimeWarning, 100% eventos entregues, 189 testes passando.

---

## Diagnóstico do Problema

### O que existe hoje

```
┌─────────────────────────────────────────────────────────────────┐
│                    LocalEventBus (async)                        │
│                                                                 │
│  async def emit(event_type, data):                              │
│      await self.queue.put(event)  ← requer loop async rodando  │
│                                                                 │
│  async def listen():              ← nunca chamado               │
│      while True:                                                │
│          event = await self.queue.get()                         │
│          yield event                                            │
└─────────────────────────────────────────────────────────────────┘

Chamadores (todos síncronos):
  DiagnosticEngine.analyze_log()  → core.event_bus.emit(...)  ← coroutine órfã
  AutoFixEngine.run_fix()         → core.event_bus.emit(...)  ← coroutine órfã
  MultiLayerMemory.add_knowledge()→ asyncio.create_task(emit) ← nunca chamado
  DigitalTwin.emit_event()        → await self.event_bus.emit() ← funciona (é async)
```

### O que cada chamador faz

| Chamador | Arquivo | Tipo | Como chama | Resultado |
|----------|---------|------|------------|-----------|
| `DiagnosticEngine.analyze_log()` | diagnostics/engine.py:77 | Sync | `self.core.event_bus.emit(...)` | ❌ Coroutine órfã |
| `AutoFixEngine.run_fix()` | autofix/engine.py:175,181 | Sync | `self.core.event_bus.emit(...)` | ❌ Coroutine órfã |
| `MultiLayerMemory.add_knowledge()` | memory.py:83 | Sync | `asyncio.create_task(self.event_bus.emit(...))` | ❌ Task nunca aguardada |
| `DigitalTwin.emit_event()` | digital_twin.py:30 | Async | `await self.event_bus.emit(...)` | ✅ Funciona (mas twin nunca recebe eventos externos) |

### Eventos fantasmas (emitidos mas nunca consumidos)

| Evento | Emitido por | Consumido por | Status |
|--------|-------------|---------------|--------|
| `diagnose_completed` | DiagnosticEngine | **NINGUÉM** | ❌ Órfão |
| `fix_applied` | AutoFixEngine | **NINGUÉM** | ❌ Órfão |
| `fix_failed` | AutoFixEngine | **NINGUÉM** | ❌ Órfão |
| `knowledge_added` | MultiLayerMemory | **NINGUÉM** | ❌ Órfão |

### O que existe mas não é usado

| Componente | Arquivo | Status |
|------------|---------|--------|
| `SyncEventBus` | titan/core/sync_event_bus.py | Código morto — nunca importado |
| `MetricsAgent` | titan/core/metrics_agent.py | Código morto — nunca registrado |
| `LocalEventBus.listen()` | titan/core/event_bus.py | Nunca chamado |

---

## Plano de Migração

### Opção A: SyncEventBus (RECOMENDADA)

```
CLI síncrono
  ↓
SyncEventBus (handlers chamados diretamente)
  ↓
MetricsAgent (escuta e atualiza métricas)
```

**Vantagens**:
- Zero async/await no CLI
- Eventos entregues imediatamente
- Sem RuntimeWarning
- Código mais simples de debugar

**Desvantagens**:
- `DigitalTwin.emit_event()` é async → precisa de adaptação
- `MultiLayerMemory.add_knowledge()` usa `asyncio.create_task` → precisa remover

### Opção B: CLI assíntrico com LocalEventBus

```
CLI assíncrono (asyncio.run)
  ↓
LocalEventBus (async queue)
  ↓
Listeners async
```

**Vantagens**:
- Mantém a interface async existente
- `DigitalTwin.emit_event()` funciona sem mudança

**Desvantagens**:
- Precisa reescrever todo CLI como async
- Mais complexo para um CLI simples
- Overhead de asyncio desnecessário

### Decisão: Opção A (SyncEventBus)

Justificativa: O CLI é síncrono por natureza (argparse, input, print). Forçar async adiciona complexidade sem benefício. O `SyncEventBus` já existe e foi projetado para este caso.

---

## Ordem de Implementação

### Passo 1: Corrigir SyncEventBus.emit() para ser síncrono

**Problema**: `SyncEventBus.emit()` é `async def` para implementar `EventBusInterface`, mas isso significa que código síncrono ainda precisa de `asyncio.run()` para chamá-lo.

**Solução**: Criar um método `emit_sync()` síncrono no `SyncEventBus` e fazer `emit()` chamar `emit_sync()` internamente.

```python
class SyncEventBus(EventBusInterface):
    def emit_sync(self, event_type: str, data: Dict[str, Any]):
        """Emite evento sincronicamente — para uso do CLI."""
        for handler in self._handlers.get(event_type, []):
            handler(data)

    async def emit(self, event_type: str, data: Dict[str, Any]):
        """Implementação async da interface (para compatibilidade)."""
        self.emit_sync(event_type, data)
```

**Arquivo**: `titan/core/sync_event_bus.py`
**Impacto**: Zero — adiciona método, não modifica existente.

### Passo 2: Trocar LocalEventBus por SyncEventBus no TitanCore

**Antes**:
```python
class TitanCore:
    def __init__(self, event_bus: EventBusInterface | None = None):
        self.event_bus = event_bus or LocalEventBus()
```

**Depois**:
```python
class TitanCore:
    def __init__(self, event_bus: EventBusInterface | None = None):
        self.event_bus = event_bus or SyncEventBus()
```

**Arquivo**: `titan/core/core.py`
**Import**: Trocar `from titan.core.event_bus import LocalEventBus` por `from titan.core.sync_event_bus import SyncEventBus`

### Passo 3: Adaptar DiagnosticEngine para usar emit_sync

**Antes**:
```python
if self.core:
    self.core.event_bus.emit("diagnose_completed", {...})
```

**Depois**:
```python
if self.core:
    bus = self.core.event_bus
    if hasattr(bus, "emit_sync"):
        bus.emit_sync("diagnose_completed", {...})
    else:
        bus.emit("diagnose_completed", {...})
```

**Alternativa mais limpa**: Criar um helper no TitanCore:
```python
class TitanCore:
    def emit(self, event_type: str, data: Dict[str, Any]):
        """Emite evento — funciona com sync e async bus."""
        bus = self.event_bus
        if hasattr(bus, "emit_sync"):
            bus.emit_sync(event_type, data)
        else:
            bus.emit(event_type, data)
```

**Arquivos**: `titan/core/core.py`, `titan/diagnostics/engine.py`, `titan/autofix/engine.py`

### Passo 4: Adaptar AutoFixEngine (mesmo padrão)

**Antes**:
```python
if self.core:
    self.core.event_bus.emit("fix_applied", {...})
```

**Depois**:
```python
if self.core:
    self.core.emit("fix_applied", {...})
```

### Passo 5: Adaptar MultiLayerMemory.add_knowledge()

**Antes**:
```python
asyncio.create_task(self.event_bus.emit("knowledge_added", {...}))
```

**Depois**:
```python
bus = self.event_bus
if hasattr(bus, "emit_sync"):
    bus.emit_sync("knowledge_added", {"category": category, "topic": topic, "content": content})
else:
    asyncio.create_task(bus.emit("knowledge_added", {"category": category, "topic": topic, "content": content}))
```

**Arquivo**: `titan/core/memory.py`

### Passo 6: Adaptar DigitalTwin.emit_event()

**Problema**: `DigitalTwin.emit_event()` é `async` e usa `await self.event_bus.emit()`. Com `SyncEventBus`, `emit()` é async mas chama `emit_sync()` internamente, então `await` funciona.

**Solução**: Nenhuma mudança necessária — `SyncEventBus.emit()` é `async` e chama `emit_sync()` internamente, então `await` funciona normalmente.

### Passo 7: Conectar MetricsAgent

**Em TitanSession.__init__()**:
```python
class TitanSession:
    def __init__(self, core: TitanCore, workspace_path: str = "."):
        self.core = core
        self.workspace = WorkspaceDetector.detect(workspace_path)
        self.metrics = RunMetrics()
        # Conectar MetricsAgent ao event bus
        self._metrics_agent = MetricsAgent(self.metrics)
        self._metrics_agent.register(self.core.event_bus)
```

**Arquivo**: `titan/core/session.py`

### Passo 8: Atualizar cmd_telemetry para mostrar steps

**Antes**:
```python
print(f"   Diagnoses:    {m['diagnoses']}")
```

**Depois**:
```python
print(f"   Diagnoses:    {m['diagnoses']}")
print(f"   Steps:        {len(m['steps'])}")
if m['steps']:
    for step in m['steps']:
        print(f"     → {step['step']}: {step['details']}")
```

---

## Arquivos a Modificar

| # | Arquivo | Alteração | Complexidade |
|---|---------|-----------|-------------|
| 1 | `titan/core/sync_event_bus.py` | Adicionar `emit_sync()` | Baixa |
| 2 | `titan/core/core.py` | Trocar LocalEventBus → SyncEventBus + adicionar helper `emit()` | Baixa |
| 3 | `titan/diagnostics/engine.py` | Usar `core.emit()` em vez de `core.event_bus.emit()` | Baixa |
| 4 | `titan/autofix/engine.py` | Usar `core.emit()` em vez de `core.event_bus.emit()` | Baixa |
| 5 | `titan/core/memory.py` | Usar `emit_sync()` em `add_knowledge()` | Baixa |
| 6 | `titan/core/session.py` | Conectar MetricsAgent no `__init__` | Baixa |
| 7 | `titan/cli.py` | Atualizar `cmd_telemetry` para mostrar steps | Baixa |

**Total**: 7 arquivos, todas alterações baixas.

---

## Arquivos de Teste a Modificar

| # | Arquivo | Alteração |
|---|---------|-----------|
| 1 | `tests/test_sprint1_integration.py` | Testes 05, 13: eventos agora são entregues (assert len == 1) |
| 2 | `tests/test_sprint1_integration.py` | Teste 17: AutoFixEngine emite eventos (assert events_captured) |

---

## Validação

```bash
# 1. Zero RuntimeWarning
python3 -m pytest tests/ -W error::RuntimeWarning -v 2>&1 | tail -5

# 2. Todos os testes passando
python3 -m pytest tests/ -v 2>&1 | tail -5

# 3. Eventos realmente entregues (teste manual)
python3 -c "
from titan.core.core import TitanCore
from titan.core.sync_event_bus import SyncEventBus

bus = SyncEventBus()
core = TitanCore(event_bus=bus)

received = []
bus.on('test_event', lambda d: received.append(d))

core.emit('test_event', {'key': 'value'})
print(f'Eventos recebidos: {len(received)}')
print(f'Dados: {received[0]}')
assert len(received) == 1
print('✅ Eventos entregues corretamente')
"

# 4. Métricas via MetricsAgent
python3 -c "
from titan.core.core import TitanCore
from titan.core.session import TitanSession

core = TitanCore()
session = TitanSession(core, workspace_path='.')

# Simular diagnose
session.core.emit('diagnose_completed', {'log': 'test.log', 'findings_count': 2})
session.metrics.diagnoses += 1

# Simular fix
session.core.emit('fix_applied', {'log': 'test.log', 'success': True})
session.metrics.fixes += 1
session.metrics.successes += 1

m = session.metrics.to_dict()
print(f'Diagnoses: {m[\"diagnoses\"]}')
print(f'Fixes: {m[\"fixes\"]}')
print(f'Successes: {m[\"successes\"]}')
print(f'Steps: {len(m[\"steps\"])}')
for step in m['steps']:
    print(f'  → {step[\"step\"]}: {step[\"details\"]}')
assert len(m['steps']) == 2, f'Esperado 2 steps, got {len(m[\"steps\"])}'
print('✅ MetricsAgent funcionando')
"
```

---

## Critérios de Aceite

- [ ] Zero RuntimeWarning em todos os testes
- [ ] 189 testes passando
- [ ] `diagnose_completed` entregue ao MetricsAgent
- [ ] `fix_applied` entregue ao MetricsAgent
- [ ] `fix_failed` entregue ao MetricsAgent
- [ ] `titan telemetry` mostra steps populados
- [ ] Nenhum `asyncio.create_task()` sem await
- [ ] Nenhum `coroutine never awaited`

---

## Rollback

Se a migração falhar:
1. Reverter `core.py`: `SyncEventBus()` → `LocalEventBus()`
2. Reverter `session.py`: remover MetricsAgent
3. 168 testes originais continuam passando (não foram modificados)
