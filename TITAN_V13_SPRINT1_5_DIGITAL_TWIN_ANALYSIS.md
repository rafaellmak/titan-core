# Titan v13 — Análise do DigitalTwin.emit_event()

> **Objetivo**: Validar o papel real do DigitalTwin antes de modificar a emissão de eventos.

---

## 1. Quem chama `DigitalTwin.emit_event()` hoje?

### Chamadas no código do Titan

| # | Arquivo | Linha | Contexto | Tipo |
|---|---------|-------|---------|------|
| 1 | `titan/core/memory.py` | 106 | `MultiLayerMemory.log_event()` | Produção |
| 2 | `tests/test_sprint1_integration.py` | 305 | `test_15_digital_twin_receives_events_via_emit_event` | Teste |

**Total**: 1 chamada em produção, 1 em teste.

### Chamadas indiretas (via `log_event`)

| # | Arquivo | Linha | Quem chama | Contexto |
|---|---------|-------|------------|----------|
| 1 | `titan/core/planner.py` | 27 | `SkillPlanner.dispatch()` | `DISPATCH_START` |
| 2 | `titan/core/planner.py` | 35 | `SkillPlanner.dispatch()` | `SKILL_SUCCESS` |
| 3 | `titan/core/planner.py` | 41 | `SkillPlanner.dispatch()` | `SKILL_ERROR` |
| 4 | `titan/core/planner.py` | 45 | `SkillPlanner.dispatch()` | `UNHANDLED_EVENT` |

**Total**: 4 chamadas indiretas via `SkillPlanner.dispatch()`.

### Quem chama `SkillPlanner.dispatch()`?

| # | Arquivo | Linha | Contexto |
|---|---------|-------|---------|
| 1 | `titan/daemon.py` | 33 | `event_loop_worker()` — loop async do daemon |

**Total**: 1 chamada no daemon.

### Conclusão: cadeia completa

```
daemon.py:event_loop_worker()
  → planner.dispatch()
    → memory.log_event()
      → digital_twin.emit_event()
        → self._apply_event()  ← atualiza grafo
        → await self.event_bus.emit()  ← propaga evento
```

**Esta cadeia só roda no daemon (FastAPI), nunca no CLI.**

---

## 2. Quantas chamadas existem no código?

| Tipo | Quantidade | Onde |
|------|------------|------|
| `digital_twin.emit_event()` direto | 1 | `memory.py:106` |
| `memory.log_event()` → `emit_event()` | 4 | `planner.py:27,35,41,45` |
| `planner.dispatch()` → `log_event()` | 1 | `daemon.py:33` |
| **Total de caminhos** | **6** | |

---

## 3. O que cada chamada espera que aconteça?

### 3.1 — `memory.log_event()` → `digital_twin.emit_event()`

```python
# memory.py:104-110
def log_event(self, event_type, details, status="INFO"):
    # Emit audit events to the Digital Twin for timeline and snapshot
    asyncio.create_task(self.digital_twin.emit_event(event_type, details))
    with open(self.audit_db) as conn:
        conn.execute("INSERT INTO audit_log ...", ...)
```

**Expectativa**: O evento é persistido no `event_log.jsonl` do DigitalTwin E propagado no EventBus.

**Realidade**:
- `asyncio.create_task()` cria uma task que **nunca é aguardada**
- Se o loop async não estiver rodando (CLI), a task **nunca executa**
- Se o loop estiver rodando (daemon), a task executa e:
  - Persiste no `event_log.jsonl` ✅
  - Atualiza o grafo via `_apply_event()` ✅
  - Propaga via `await self.event_bus.emit()` ✅

### 3.2 — `planner.dispatch()` → `memory.log_event()` → `digital_twin.emit_event()`

```python
# planner.py:27
self.memory.log_event("DISPATCH_START", {"event_type": event_type, "data": data})
```

**Expectativa**: Registrar início de dispatch no audit log do DigitalTwin.

**Realidade**: Mesmo que `memory.log_event()` — só funciona no daemon.

### 3.3 — Teste `test_15`

```python
# test_sprint1_integration.py:299-307
asyncio.run(
    core.digital_twin.emit_event("layer_added", {"layer": "meta-test"})
)
graph = core.digital_twin.get_graph()
assert graph.has_node("layer:meta-test")
```

**Expectativa**: `emit_event()` atualiza o grafo.

**Realidade**: Funciona porque `asyncio.run()` executa a coroutine completamente.

---

## 4. Existe algum fluxo que dependa da propagação desses eventos?

### Eventos emitidos pelo DigitalTwin

| Evento | Quando é emitido | Quem escuta? |
|--------|------------------|--------------|
| `DISPATCH_START` | Início do dispatch | **NINGUÉM** |
| `SKILL_SUCCESS` | Skill executou com sucesso | **NINGUÉM** |
| `SKILL_ERROR` | Skill falhou | **NINGUÉM** |
| `UNHANDLED_EVENT` | Evento sem handler | **NINGUÉM** |
| `layer_added` | Layer adicionada ao grafo | **NINGUÉM** |
| `recipe_added` | Recipe adicionada ao grafo | **NINGUÉM** |
| `dependency_added` | Dependência adicionada | **NINGUÉM** |
| `workspace_scanned` | Workspace escaneado | **NINGUÉM** |
| `knowledge_added` | Conhecimento adicionado | **NINGUÉM** |

**Conclusão**: Nenhum código no Titan escuta os eventos emitidos pelo DigitalTwin. A propagação via `await self.event_bus.emit()` **não tem efeito observável**.

### Verificação: todos os `.on()` registrados no Titan

```bash
# Busca por registro de handlers
grep -r "\.on(" titan/ --include="*.py"
```

**Resultado**: Nenhum `.on()` registrado no código de produção do Titan. Apenas nos testes.

### Verificação: todos os `bus.on()` no daemon

```python
# daemon.py — nenhum bus.on() registrado
# O daemon usa event_bus.listen() em loop async
```

**Conclusão**: O daemon consome eventos via `listen()`, não via `.on()`. Os eventos do DigitalTwin são emitidos no mesmo bus, mas **não há rota de propagação** do DigitalTwin para o daemon.

---

## 5. Remover a emissão do EventBus muda comportamento observável?

### Análise por cenário

| Cenário | Com `await bus.emit()` | Sem `bus.emit()` | Diferença observável? |
|---------|------------------------|-------------------|----------------------|
| **Daemon: `log_event()` → `emit_event()`** | Evento emitido no bus, ninguém escuta | Evento não emitido | ❌ Nenhuma |
| **Daemon: `planner.dispatch()` → `log_event()`** | Evento emitido no bus, ninguém escita | Evento não emitido | ❌ Nenhuma |
| **CLI: `memory.log_event()` nunca é chamado** | N/A | N/A | ❌ Nenhuma |
| **Teste: `emit_event()` direto** | Grafo atualizado + evento emitido | Grafo atualizado | ❌ Nenhuma (teste não verifica evento) |

### Conclusão

**NÃO.** Remover `await self.event_bus.emit()` do `DigitalTwin.emit_event()` **não muda nenhum comportamento observável** do sistema.

Justificativa:
1. Nenhum código escuta os eventos do DigitalTwin
2. O grafo é atualizado por `_apply_event()`, que é chamado diretamente
3. O `event_log.jsonl` é escrito diretamente
4. A propagação no bus é efetivamente um no-op

---

## 6. Existe algum teste cobrindo isso?

### Testes que chamam `emit_event()`

| Teste | Arquivo | O que verifica |
|-------|---------|----------------|
| `test_15_digital_twin_receives_events_via_emit_event` | test_sprint1_integration.py:299 | Grafo atualizado (não verifica evento no bus) |

### Testes que verificam propagação de eventos do DigitalTwin

**NENHUM.** Nenhum teste verifica se os eventos do DigitalTwin são propagados no EventBus.

---

## 7. Classificação do método

### Opção A: Nome incorreto (deveria ser `update_state`)

**Parcialmente correto**. O método faz duas coisas:
1. Atualiza o grafo interno (`_apply_event()`)
2. Propaga no EventBus (`await bus.emit()`)

Se renomeado para `update_state()`, a propagação no bus seria removida. Mas o nome `emit_event()` descreve o que ele faz (emite evento), não o que deveria fazer.

### Opção B: Responsabilidade incorreta (DigitalTwin não deveria emitir eventos) ✅

**CORRETO**. Justificativa:

1. **DigitalTwin é um modelo de dados**, não um produtor de eventos
2. **Nenhum código escuta seus eventos** — a propagação é um no-op
3. **O grafo é atualizado internamente** — não precisa de eventos para isso
4. **Quem deve emitir eventos é quem chama o DigitalTwin**, não o próprio twin

Analogia: Um banco de dados não emite eventos quando você faz um INSERT. Quem emite é a aplicação que fez o INSERT.

### Opção C: Implementação incorreta (DigitalTwin deveria continuar emitindo)

**INCORRETO**. Não há razão para continuar emitindo eventos que ninguém escuta.

---

## 8. Recomendação

### Classificação: **B) Responsabilidade incorreta**

O `DigitalTwin.emit_event()` **não deveria emitir no EventBus**. Deveria apenas:
1. Persistir no `event_log.jsonl`
2. Atualizar o grafo via `_apply_event()`

### Mudança proposta

```python
# ANTES
async def emit_event(self, event_type: str, data: Dict[str, Any]):
    event = {
        "event": event_type,
        "data": data,
        "timestamp": datetime.now().isoformat()
    }
    with open(self.event_log_path, 'a') as f:
        f.write(json.dumps(event) + '\n')
    self._apply_event(event)
    await self.event_bus.emit(event_type, data)  # ← REMOVER

# DEPOIS
def emit_event(self, event_type: str, data: Dict[str, Any]):
    """Atualiza o grafo interno. NÃO emite no EventBus."""
    event = {
        "event": event_type,
        "data": data,
        "timestamp": datetime.now().isoformat()
    }
    with open(self.event_log_path, 'a') as f:
        f.write(json.dumps(event) + '\n')
    self._apply_event(event)
```

### Impacto da mudança

| Aspecto | Impacto |
|---------|---------|
| **Comportamento observável** | Nenhum — ninguém escuta esses eventos |
| **Teste `test_15`** | Continua passando — verifica grafo, não bus |
| **Daemon** | Nenhum — `log_event()` já usa `asyncio.create_task()` órfão |
| **CLI** | Nenhum — `log_event()` nunca é chamado no CLI |
| **Async/Sync** | `emit_event()` vira síncrono — mais simples |

### Benefícios

1. **Elimina async desnecessário** — `emit_event()` vira síncrono
2. **Responsabilidade clara** — twin é modelo, não produtor de eventos
3. **Simplifica a migração** — não precisa adaptar `emit_event()` para sync
4. **Remove `await` órfão** — no daemon, `log_event()` já não aguarda
