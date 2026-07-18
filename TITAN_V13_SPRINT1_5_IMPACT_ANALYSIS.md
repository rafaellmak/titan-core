# Titan v13 — Análise de Impacto da Migração EventBus (Opção C)

> **Objetivo**: Mapear TODOS os impactos antes de implementar.
> **Princípio**: Se não sabemos o que vai quebrar, não devemos tocar.

---

## 1. Arquivos a Modificar (9 arquivos)

| # | Arquivo | Tipo | Mudança |
|---|---------|------|---------|
| 1 | `titan/core/event_bus.py` | MODIFICAR | Remover async de `EventBus` + `LocalEventBus` |
| 2 | `titan/core/async_event_bus.py` | CRIAR | `AsyncEventBus` + `QueuedEventBus` (para daemon) |
| 3 | `titan/core/sync_event_bus.py` | DELETAR | Substituído pelo novo `event_bus.py` |
| 4 | `titan/core/core.py` | MODIFICAR | Importar `LocalEventBus` do novo módulo |
| 5 | `titan/core/digital_twin.py` | MODIFICAR | `emit_event()` não emite no bus (ou usa helper) |
| 6 | `titan/core/memory.py` | MODIFICAR | Remover `asyncio.create_task()` |
| 7 | `titan/daemon.py` | MODIFICAR | Importar de `async_event_bus` |
| 8 | `titan/core/session.py` | MODIFICAR | Conectar MetricsAgent |
| 9 | `titan/core/metrics_agent.py` | MODIFICAR | Remover `hasattr("on")` check |

---

## 2. Classes Alteradas

### 2.1 — `titan/core/event_bus.py` (MODIFICAR)

**ANTES**:
```python
class EventBusInterface(ABC):
    @abstractmethod
    async def emit(self, event_type: str, data: Dict[str, Any]): ...

    @abstractmethod
    async def listen(self) -> AsyncGenerator[Dict[str, Any], None]: ...

class LocalEventBus(EventBusInterface):
    def __init__(self):
        self.queue = asyncio.Queue()

    async def emit(self, event_type: str, data: Dict[str, Any]):
        await self.queue.put(event)

    async def listen(self) -> AsyncGenerator[Dict[str, Any], None]:
        while True:
            event = await self.queue.get()
            yield event
```

**DEPOIS**:
```python
class EventBus(ABC):
    @abstractmethod
    def emit(self, event_type: str, data: Dict[str, Any]) -> None: ...

    @abstractmethod
    def on(self, event_type: str, handler: Callable) -> None: ...

class LocalEventBus(EventBus):
    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = defaultdict(list)

    def on(self, event_type: str, handler: Callable) -> None:
        self._handlers[event_type].append(handler)

    def emit(self, event_type: str, data: Dict[str, Any]) -> None:
        for handler in self._handlers.get(event_type, []):
            handler(data)
```

**Assinaturas que mudam**:
| Método | Antes | Depois |
|--------|-------|--------|
| `EventBus.emit()` | `async def emit(...) → None` | `def emit(...) → None` |
| `EventBus.listen()` | `async def listen() → AsyncGenerator` | **REMOVIDO** |
| `EventBus.on()` | **NÃO EXISTIA** | `def on(event_type, handler) → None` |
| `LocalEventBus.__init__()` | `self.queue = asyncio.Queue()` | `self._handlers = defaultdict(list)` |

### 2.2 — `titan/core/async_event_bus.py` (CRIAR)

```python
class AsyncEventBus(ABC):
    @abstractmethod
    async def emit(self, event_type: str, data: Dict[str, Any]) -> None: ...

    @abstractmethod
    async def listen(self) -> AsyncGenerator[Dict[str, Any], None]: ...

class QueuedEventBus(AsyncEventBus):
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

### 2.3 — `titan/core/core.py` (MODIFICAR)

**ANTES**:
```python
from titan.core.event_bus import LocalEventBus, EventBusInterface

class TitanCore:
    def __init__(self, event_bus: EventBusInterface | None = None):
        self.event_bus: EventBusInterface = event_bus or LocalEventBus()
```

**DEPOIS**:
```python
from titan.core.event_bus import LocalEventBus, EventBus

class TitanCore:
    def __init__(self, event_bus: EventBus | None = None):
        self.event_bus: EventBus = event_bus or LocalEventBus()
```

### 2.4 — `titan/core/digital_twin.py` (MODIFICAR)

**ANTES**:
```python
class DigitalTwin:
    def __init__(self, event_bus: EventBusInterface, base_path=...):
        self.event_bus = event_bus
        ...

    async def emit_event(self, event_type: str, data: Dict[str, Any]):
        ...
        await self.event_bus.emit(event_type, data)
```

**DEPOIS**:
```python
class DigitalTwin:
    def __init__(self, event_bus: EventBus, base_path=...):
        self.event_bus = event_bus
        ...

    def emit_event(self, event_type: str, data: Dict[str, Any]):
        """Atualiza grafo internamente. NÃO emite no bus."""
        event = {
            "event": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat()
        }
        with open(self.event_log_path, 'a') as f:
            f.write(json.dumps(event) + '\n')
        self._apply_event(event)
        # NÃO emite no bus — quem chama decide se emite
```

**Justificativa**: `DigitalTwin` é um modelo de dados, não um produtor de eventos. Quem chama `emit_event()` deve emitir no bus separadamente se necessário.

### 2.5 — `titan/core/memory.py` (MODIFICAR)

**ANTES**:
```python
def add_knowledge(self, category, topic, content, tags=[]):
    asyncio.create_task(self.event_bus.emit("knowledge_added", {...}))
    ...
```

**DEPOIS**:
```python
def add_knowledge(self, category, topic, content, tags=[]):
    self.event_bus.emit("knowledge_added", {"category": category, "topic": topic, "content": content})
    ...
```

### 2.6 — `titan/daemon.py` (MODIFICAR)

**ANTES**:
```python
from titan.core.event_bus import LocalEventBus

event_bus = LocalEventBus()
```

**DEPOIS**:
```python
from titan.core.async_event_bus import QueuedEventBus

event_bus = QueuedEventBus()
```

### 2.7 — `titan/core/session.py` (MODIFICAR)

**ANTES**:
```python
class TitanSession:
    def __init__(self, core: TitanCore, workspace_path: str = "."):
        self.core = core
        self.workspace = WorkspaceDetector.detect(workspace_path)
        self.metrics = RunMetrics()
```

**DEPOIS**:
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

### 2.8 — `titan/core/metrics_agent.py` (MODIFICAR)

**ANTES**:
```python
def register(self, event_bus):
    if hasattr(event_bus, "on"):
        event_bus.on("diagnose_completed", self.on_diagnose_completed)
        ...
```

**DEPOIS**:
```python
def register(self, event_bus: EventBus) -> None:
    event_bus.on("diagnose_completed", self.on_diagnose_completed)
    event_bus.on("fix_applied", self.on_fix_applied)
    event_bus.on("fix_failed", self.on_fix_failed)
```

---

## 3. Testes a Adaptar

### 3.1 — `tests/test_sprint1_integration.py`

| Teste | Linha | Problema | Correção |
|-------|-------|----------|----------|
| `test_05_diagnostic_engine_with_core_emits_events` | 128 | Usa `SyncEventBus` (será deletado) | Usar `LocalEventBus` novo |
| `test_11_sync_event_bus_delivers_events` | 214 | Usa `SyncEventBus` (será deletado) | Usar `LocalEventBus` novo |
| `test_12_metrics_agent_listens_to_events` | 228 | Usa `SyncEventBus` + `asyncio.run()` | Usar `LocalEventBus` novo (sync) |
| `test_13_full_pipeline_with_sync_bus` | 248 | Usa `SyncEventBus` | Usar `LocalEventBus` novo |
| `test_14_knowledge_engine_no_duplicate_entries` | 270 | Usa `SyncEventBus` | Usar `LocalEventBus` novo |
| `test_15_digital_twin_receives_events_via_emit_event` | 299 | Usa `SyncEventBus` + `asyncio.run()` | Usar `LocalEventBus` novo |
| `test_17_autofix_engine_with_core_emits_events` | 322 | Usa `SyncEventBus` | Usar `LocalEventBus` novo |
| `core_with_sync_bus` fixture | 72 | Usa `SyncEventBus` | Usar `LocalEventBus` novo |
| `test_memory_without_knowledge_engine_creates_default` | 410 | Usa `LocalEventBus` | OK (mantém) |
| `test_memory_with_injected_knowledge_engine` | 420 | Usa `LocalEventBus` | OK (mantém) |

**Total**: 8 testes + 1 fixture precisam de adaptação.

### 3.2 — Outros testes

| Arquivo | Impacto |
|---------|---------|
| `tests/test_titan.py` | Nenhum — não usa EventBus diretamente |
| `tests/test_cli_diagnose.py` | Nenhum — testa CLI via subprocess |
| `tests/test_autofix.py` | Nenhum — não usa EventBus |
| `tests/test_daemon.py` | **Pode precisar** — testa daemon async |

---

## 4. Riscos por Componente

### 4.1 — CLI

| Risco | Severidade | Probabilidade | Mitigação |
|-------|------------|---------------|-----------|
| `cmd_diagnose` para de funcionar | 🔴 Alta | Baixa | Testes cobrem todos os caminhos |
| `cmd_fix` para de funcionar | 🔴 Alta | Baixa | Testes cobrem todos os caminhos |
| `cmd_telemetry` para de funcionar | 🟡 Média | Baixa | Teste dedicado |
| Regressão em outros comandos | 🟡 Média | Baixa | 168 testes originais |

### 4.2 — Daemon

| Risco | Severidade | Probabilidade | Mitigação |
|-------|------------|---------------|-----------|
| `event_loop_worker` para de receber eventos | 🔴 Alta | Média | `QueuedEventBus` é cópia exata do `LocalEventBus` async |
| Skills param de ser disparados | 🔴 Alta | Média | Depende do bus funcionar |
| FastAPI startup falha | 🟡 Média | Baixa | Import simples |

### 4.3 — DigitalTwin

| Risco | Severidade | Probabilidade | Mitigação |
|-------|------------|---------------|-----------|
| `emit_event()` para de atualizar grafo | 🔴 Alta | **Alta** | **MUDANÇA DE COMPORTAMENTO** — não emite mais no bus |
| Grafo para de receber eventos externos | 🟡 Média | **Certa** | **INTENCIONAL** — twin não deve emitir no bus |
| Snapshots param de funcionar | 🟡 Média | Baixa | Snapshots não dependem do bus |

### 4.4 — Memory

| Risco | Severidade | Probabilidade | Mitigação |
|-------|------------|---------------|-----------|
| `add_knowledge()` para de emitir evento | 🟡 Média | Baixa | `emit()` sync funciona |
| `log_event()` para de funcionar | 🟡 Média | Baixa | Não usa bus diretamente |

### 4.5 — Diagnostics

| Risco | Severidade | Probabilidade | Mitigação |
|-------|------------|---------------|-----------|
| `analyze_log()` para de emitir eventos | 🟡 Média | Baixa | `core.event_bus.emit()` sync funciona |
| Knowledge para de ser atualizado | 🟡 Média | Baixa | Usa `core.knowledge_engine` diretamente |

### 4.6 — AutoFix

| Risco | Severidade | Probabilidade | Mitigação |
|-------|------------|---------------|-----------|
| `run_fix()` para de emitir eventos | 🟡 Média | Baixa | `core.event_bus.emit()` sync funciona |
| Fix para de funcionar | 🔴 Alta | Baixa | Lógica de fix não muda |

---

## 5. Diff Arquitetural

### ANTES

```
┌─────────────────────────────────────────────────────────────────┐
│                    EventBusInterface (ABC)                      │
│                                                                 │
│  @abstractmethod                                                │
│  async def emit(...)          ← força async em tudo            │
│                                                                 │
│  @abstractmethod                                                │
│  async def listen()           ← só daemon usa                  │
└─────────────────────────────────────────────────────────────────┘
           │                                    │
           ▼                                    ▼
┌─────────────────────┐          ┌─────────────────────────┐
│   LocalEventBus     │          │     SyncEventBus        │
│   (async queue)     │          │     (sync handlers)     │
│                     │          │     async emit()        │
│ Usado por:          │          │                         │
│ - TitanCore (CLI)   │          │ Usado por:              │
│ - Daemon (FastAPI)  │          │ - Ninguém               │
│                     │          │                         │
│ Problema:           │          │ Problema:               │
│ CLI chama emit()    │          │ async def emit() sem    │
│ sem await → evento  │          │ necessidade             │
│ descartado          │          │                         │
└─────────────────────┘          └─────────────────────────┘
```

### DEPOIS

```
┌─────────────────────────────────────────────────────────────────┐
│                    EventBus (ABC) — SYNC                         │
│                                                                 │
│  @abstractmethod                                                │
│  def emit(...)                ← síncrono por padrão            │
│                                                                 │
│  @abstractmethod                                                │
│  def on(event_type, handler)  ← registro de handlers           │
└─────────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      LocalEventBus                              │
│                                                                 │
│  def emit(event_type, data):                                    │
│      for handler in self._handlers[event_type]:                 │
│          handler(data)        ← entrega imediata               │
│                                                                 │
│  Usado por:                                                     │
│ - TitanCore (CLI)  ← funciona ✅                               │
│ - DiagnosticEngine ← funciona ✅                               │
│ - AutoFixEngine    ← funciona ✅                               │
│ - MultiLayerMemory ← funciona ✅                               │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                   AsyncEventBus (ABC) — ASYNC                   │
│                                                                 │
│  @abstractmethod                                                │
│  async def emit(...)          ← async para daemon              │
│                                                                 │
│  @abstractmethod                                                │
│  async def listen()           ← consumidor async               │
└─────────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────┐
│                     QueuedEventBus                              │
│                                                                 │
│  async def emit(event_type, data):                              │
│      await self.queue.put(...)                                  │
│                                                                 │
│  async def listen():                                            │
│      while True:                                                │
│          event = await self.queue.get()                         │
│          yield event                                            │
│                                                                 │
│  Usado por:                                                     │
│ - Daemon (FastAPI) ← funciona ✅                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. Compatibilidade Retroativa

### 6.1 — O que quebra

| API | Quebra? | Motivo |
|-----|---------|--------|
| `EventBusInterface.emit()` | **SIM** | Era `async def`, agora é `def` |
| `EventBusInterface.listen()` | **SIM** | Removida da interface sync |
| `LocalEventBus.emit()` | **SIM** | Era `async def`, agora é `def` |
| `LocalEventBus.listen()` | **SIM** | Removida |
| `LocalEventBus.queue` | **SIM** | Não existe mais |
| `SyncEventBus` | **SIM** | Classe deletada |

### 6.2 — O que NÃO quebra

| API | Status | Motivo |
|-----|--------|--------|
| `TitanCore.__init__()` | ✅ Mantida | Apenas muda o import |
| `DiagnosticEngine.__init__()` | ✅ Mantida | Não muda assinatura |
| `AutoFixEngine.__init__()` | ✅ Mantida | Não muda assinatura |
| `MultiLayerMemory.__init__()` | ✅ Mantida | Não muda assinatura |
| `DigitalTwin.__init__()` | ✅ Mantida | Não muda assinatura (apenas tipo do bus) |
| `SkillPlanner.__init__()` | ✅ Mantida | Não muda |
| `RunMetrics` | ✅ Mantida | Não muda |
| `MetricsAgent` | ✅ Mantida | Apenas remove `hasattr` |
| CLI commands | ✅ Mantida | Não mudam assinaturas |
| Todos os testes CLI | ✅ Mantidos | Testam via subprocess |

### 6.3 — Estratégia de compatibilidade

**Não há compatibilidade retroativa perfeita** porque a interface muda de async para sync. Porém:

1. **O daemon é o único consumidor de `AsyncEventBus`** — e ele será migrado para `QueuedEventBus`
2. **O CLI nunca usou `listen()`** — então remover não afeta
3. **Nenhum código externo usa `EventBusInterface` diretamente** — é uma interface interna
4. **Os testes são adaptados** — 8 testes mudam, 160+ permanecem

---

## 7. Plano de Rollback

### Se a migração falhar em qualquer ponto:

```bash
# 1. Reverter todos os arquivos
git checkout HEAD -- titan/core/event_bus.py
git checkout HEAD -- titan/core/core.py
git checkout HEAD -- titan/core/digital_twin.py
git checkout HEAD -- titan/core/memory.py
git checkout HEAD -- titan/daemon.py
git checkout HEAD -- titan/core/session.py
git checkout HEAD -- titan/core/metrics_agent.py

# 2. Deletar arquivos novos
rm -f titan/core/async_event_bus.py
rm -f titan/core/sync_event_bus.py

# 3. Deletar testes novos (se necessário)
rm -f tests/test_sprint1_integration.py

# 4. Verificar baseline
python3 -m pytest tests/ -v --tb=short
# Esperado: 168 passed (baseline original)
```

### Rollback parcial (se apenas alguns arquivos falharem):

| Arquivo | Rollback individual | Impacto |
|---------|---------------------|---------|
| `event_bus.py` | `git checkout HEAD -- titan/core/event_bus.py` | Tudo para |
| `async_event_bus.py` | `rm titan/core/async_event_bus.py` | Daemon para |
| `core.py` | `git checkout HEAD -- titan/core/core.py` | CLI para |
| `daemon.py` | `git checkout HEAD -- titan/daemon.py` | Daemon para |
| `digital_twin.py` | `git checkout HEAD -- titan/core/digital_twin.py` | Twin para |
| `memory.py` | `git checkout HEAD -- titan/core/memory.py` | Memory para |

---

## 8. Validação Pré-Implementação

Antes de implementar, confirmar:

- [ ] **168 testes passando** (baseline atual)
- [ ] **Nenhum uso de `EventBusInterface` fora do core** (verificado: apenas `memory.py` e `digital_twin.py`)
- [ ] **Nenhum uso de `LocalEventBus.listen()` no CLI** (verificado: nenhum)
- [ ] **Daemon é o único consumidor de `listen()`** (verificado: `daemon.py:28`)
- [ ] **Skills usam `EventBusInterface` apenas no daemon** (verificado: skills recebem bus via `SkillPlanner`)
- [ ] **Testes de daemon não serão afetados** (verificar: `test_daemon.py` não importa `LocalEventBus` diretamente)

---

## 9. Estimativa de Esforço

| Tarefa | Complexidade | Tempo |
|--------|--------------|-------|
| Criar `async_event_bus.py` | Baixa | 15 min |
| Modificar `event_bus.py` (remover async) | Baixa | 10 min |
| Deletar `sync_event_bus.py` | Baixa | 1 min |
| Modificar `core.py` (imports) | Baixa | 5 min |
| Modificar `digital_twin.py` (remover emit no bus) | Baixa | 10 min |
| Modificar `memory.py` (remover asyncio) | Baixa | 5 min |
| Modificar `daemon.py` (import async) | Baixa | 5 min |
| Modificar `session.py` (conectar MetricsAgent) | Baixa | 10 min |
| Modificar `metrics_agent.py` (remover hasattr) | Baixa | 5 min |
| Adaptar 8 testes | Média | 30 min |
| Rodar todos os testes | Baixa | 5 min |
| **Total** | | **~100 min** |

---

## 10. Decisão

### A migração é segura?

**SIM**, com as seguintes ressalvas:

1. **`DigitalTwin.emit_event()` muda de comportamento** — não emite mais no bus. Isso é **intencional** e **correto** (twin é modelo, não produtor de eventos).
2. **8 testes precisam de adaptação** — todos os usos de `SyncEventBus` → `LocalEventBus`.
3. **Zero impacto no CLI** — comandos continuam funcionando via subprocess.
4. **Daemon continua funcionando** — `QueuedEventBus` é cópia exata do `LocalEventBus` async.
5. **Rollback é simples** — `git checkout` em 7 arquivos.

### Recomendação

**Implementar.** A migração é segura, o rollback é simples, e o benefício é eliminar a causa raiz do bug de eventos.
