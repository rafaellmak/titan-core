# Titan v13 — Revisão Arquitetural do Roadmap de Integração

> **Escopo**: Análise crítica do `TITAN_V13_INTEGRATION_ROADMAP.md` como arquiteto de software sênior.
> **Princípio**: Cada modificação proposta é avaliada por risco, acoplamento, dependência, testabilidade, performance e extensibilidade.

---

## 1. Visão Geral do Roadmap Proposto

O roadmap propõe transformar 10 módulos isolados em um sistema integrado através de:

1. Um objeto central `TitanContext` que agrega todos os módulos core
2. Um Event Bus como mecanismo de comunicação
3. Um pipeline `Diagnose → Fix → Validate` com telemetria
4. Skills registradas no Planner

---

## 2. Análise por Modificação Proposta

### 2.1 — Criar `TitanContext` (context.py)

#### Riscos Arquiteturais

**RISCO ALTO — God Object**

O `TitanContext` proposto instancia e expõe diretamente:
- `EventBus`
- `DigitalTwin`
- `KnowledgeEngine`
- `MultiLayerMemory`
- `SkillPlanner`
- `RunMetrics`
- `Workspace`

Isso é um God Object clássico. Qualquer mudança em qualquer módulo core exige modificar o Context. O Context conhece tudo sobre todos.

**RISCO MÉDIO — Acoplamento de inicialização**

O Context instancia skills com imports diretos:
```python
self.planner.register_skill(YoctoSkill())
self.planner.register_skill(AutoFixSkill())
```
Isso cria acoplamento estático. Adicionar um novo plugin exige modificar o Context.

**RISCO MÉDIO — Estado mutável compartilhado**

Todos os comandos CLI recebem o mesmo `ctx`. Se dois comandos rodam em paralelo (ou testes), há compartilhamento de estado sem controle.

#### Acoplamentos Desnecessários

- `TitanContext` → `YoctoSkill`, `AutoFixSkill`, `SecuritySkill`, `DTSSkill`, `BuildrootSkill`
  - O Context não deveria conhecer skills concretas. Deveria receber uma lista de plugins.
- `TitanContext` → `RunMetrics`
  - Métricas é uma preocupação transversal, não responsabilidade do Context.

#### Dependências Criadas

```
TitanContext
  ├── titan.core.event_bus (LocalEventBus)
  ├── titan.core.digital_twin (DigitalTwin)
  ├── titan.core.knowledge_engine (KnowledgeEngine)
  ├── titan.core.memory (MultiLayerMemory)
  ├── titan.core.planner (SkillPlanner)
  ├── titan.core.metrics (RunMetrics) [NOVO]
  ├── titan.skills.yocto_skill (YoctoSkill)
  ├── titan.skills.autofix_skill (AutoFixSkill)
  ├── titan.skills.security_skill (SecuritySkill)
  ├── titan.skills.dts_skill (DTSSkill)
  └── titan.skills.buildroot_skill (BuildrootSkill)
```

**11 dependências diretas.** Um God Object por definição.

#### Como Evitar o God Object

**Solução**: Separar em dois objetos com responsabilidades distintas:

```python
class TitanCore:
    """Apenas os serviços core. Sem skills, sem métricas."""
    def __init__(self):
        self.event_bus = LocalEventBus()
        self.digital_twin = DigitalTwin(self.event_bus)
        self.knowledge_engine = KnowledgeEngine()
        self.memory = MultiLayerMemory(self.event_bus)
        self.planner = SkillPlanner(self.memory, self.digital_twin, self.knowledge_engine)

class TitanSession:
    """Uma sessão de execução. Core + workspace + métricas + plugins."""
    def __init__(self, core: TitanCore, workspace_path: str = "."):
        self.core = core
        self.workspace = WorkspaceDetector.detect(workspace_path)
        self.metrics = RunMetrics()
        self._plugins_loaded = False

    def register_plugin(self, plugin: 'TitanPlugin'):
        """Registra skills de um plugin sem conhecer classes concretas."""
        for skill in plugin.get_skills():
            self.core.planner.register_skill(skill)
        self._plugins_loaded = True
```

**Benefícios**:
- `TitanCore` tem 4 dependências (não 11)
- `TitanSession` não conhece skills concretas
- Plugins são registrados externamente
- Testes podem criar `TitanCore` sem workspace ou métricas

---

### 2.2 — Conectar Event Bus ao Fluxo Real

#### Riscos Arquiteturais

**RISCO ALTO — Event Bus como chamada indireta**

O roadmap propõe:
```python
# Em cmd_security:
ctx.event_bus.emit("security_scan", {"online": args.online})
```

Isso é apenas uma chamada de função disfarçada de evento. O `emit` é fire-and-forget — ninguém consome o evento. O `SecuritySkill.can_handle` escuta `"security_scan"`, mas o skill nunca é disparado porque o Planner não está no loop.

**Resultado**: eventos órfãos. O Event Bus vira um mecanismo de chamadas indiretas sem nenhum benefício real sobre chamadas diretas.

**RISCO MÉDIO — Mistura de sync/async**

O `LocalEventBus` usa `asyncio.Queue`. Mas `DiagnosticEngine.analyze_log()` é síncrono. `AutoFixEngine.run_fix()` é síncrono. O CLI é síncrono.

Para emitir eventos de código síncrono, precisaríamos de:
```python
asyncio.run(self.context.event_bus.emit(...))  # Cria novo loop a cada chamada
# ou
loop = asyncio.get_event_loop()
loop.run_until_complete(...)  # Pode falhar se loop já estiver rodando
```

Isso é frágil e propenso a erros em produção.

**RISCO BAIXO — Eventos sem schema**

Os eventos são strings + dicts sem validação. Não há contrato de evento. Qualquer módulo pode emitir qualquer coisa.

#### Como Evitar que o Event Bus Vire Chamada Indireta

**Solução**: Usar o Event Bus apenas para eventos que têm **múltiplos consumidores** ou que precisam de **desacoplamento temporal**.

```
USAR Event Bus para:
  ✓ WorkspaceLoaded (múltiplos módulos reagem)
  ✓ DiagnoseCompleted (metrics, knowledge, twin atualizam)
  ✓ FixApplied (metrics, knowledge, memory atualizam)

NÃO usar Event Bus para:
  ✗ SecurityScan (um único consumidor, chamada direta é mais claro)
  ✗ DiagnoseStarted (apenas métricas — incremento simples)
```

**Solução para sync/async**: Usar um Event Bus síncrono para o CLI e manter o async apenas para o daemon/servidor.

```python
class SyncEventBus:
    """Event bus síncrono para uso no CLI."""
    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = defaultdict(list)

    def on(self, event_type: str, handler: Callable):
        self._handlers[event_type].append(handler)

    def emit(self, event_type: str, data: Dict[str, Any]):
        for handler in self._handlers.get(event_type, []):
            handler(data)
```

---

### 2.3 — Pipeline Diagnose → Fix → Validate

#### Riscos Arquiteturais

**RISCO ALTO — Context opcional quebra o contrato**

O roadmap propõe:
```python
def __init__(self, workspace: Workspace, context: TitanContext = None):
    self.context = context  # Pode ser None

def analyze_log(self, findings):
    if self.context:  # Guard clause em toda chamada
        self.context.event_bus.emit(...)
```

O `context=None` cria dois caminhos de execução. Em testes, o context quase sempre será None, então os eventos nunca serão testados. Em produção, se alguém esquecer de passar o context, o sistema silenciosamente para de emitir eventos.

**RISCO MÉDIO — AutoFixEngine cria DiagnosticEngine internamente**

```python
class AutoFixEngine:
    def __init__(self, workspace, context=None):
        self.diag = DiagnosticEngine(workspace, context)
```

Isso significa que `AutoFixEngine` depende de `DiagnosticEngine`. Se o pipeline crescer (Diagnose → Knowledge Lookup → Fix → Validate), cada engine vai depender da anterior, criando uma cadeia rígida.

**RISCO MÉDIO — Validação não é um agente**

O roadmap menciona "Validation" mas não cria um `ValidationAgent`. A validação é feita dentro do `AutoFixEngine.validate_workspace()` e `validate_mutation()`. Isso significa que a validação não é extensível nem reutilizável.

#### Dependências Criadas

```
DiagnosticEngine → TitanContext (opcional)
DiagnosticEngine → KnowledgeEngine (via context)
AutoFixEngine → DiagnosticEngine (composição direta)
AutoFixEngine → TitanContext (opcional)
AutoFixEngine → FixTransaction (existente)
```

#### Acoplamentos Desnecessários

- `DiagnosticEngine` → `KnowledgeEngine`: O diagnóstico não deveria alimentar o knowledge engine diretamente. Deveria emitir um evento e deixar o knowledge engine reagir.
- `AutoFixEngine` → `DiagnosticEngine`: Dependência direta. O fix deveria receber os findings, não criar o diagnóstico.

#### Solução — Pipeline com Findings como contrato

```python
# O pipeline troca Findings, não engines
@dataclass
class DiagnosisResult:
    findings: List[Finding]
    root_causes: List[RootCause]
    confidence: float

@dataclass
class FixResult:
    patch_applied: bool
    files_mutated: List[Path]
    validation_passed: bool
    rollback_needed: bool

# Cada etapa recebe dados, não cria dependências
class DiagnoseAgent:
    def run(self, log_path: Path, rules: List[DiagnosticRule]) -> DiagnosisResult:
        ...

class FixAgent:
    def run(self, diagnosis: DiagnosisResult, workspace: Workspace) -> FixResult:
        ...

class ValidationAgent:
    def run(self, fix: FixResult, workspace: Workspace) -> bool:
        ...
```

---

### 2.4 — CLI Integrada ao Context

#### Riscos Arquiteturais

**RISCO ALTO — Assinatura de função muda para todos os comandos**

O roadmap propõe:
```python
def cmd_diagnose(args, ctx: TitanContext):
def cmd_fix(args, ctx: TitanContext):
def cmd_security(args, ctx: TitanContext):
```

Isso muda a assinatura de **todos** os comandos existentes. Se algum comando não for atualizado, quebra em runtime.

**RISCO MÉDIO — CLI conhece TitanContext**

O CLI deveria ser uma camada fina que recebe argumentos e delega. Se o CLI conhece `TitanContext`, ele conhece `EventBus`, `DigitalTwin`, `KnowledgeEngine`, etc. Isso viola separação de camadas.

**RISCO BAIXO — Criação do Context no main()**

```python
ctx = TitanContext(workspace_path=args.workspace)
```

Se a criação do Context falhar (ex: workspace inválido), o CLI inteiro falha antes de qualquer comando rodar.

#### Solução — CLI delega para um CommandBus

```python
# CLI não conhece TitanContext
def cmd_diagnose(args):
    workspace = WorkspaceDetector.detect(args.workspace)
    engine = DiagnosticEngine(workspace)
    findings = engine.analyze_log(Path(args.log))
    # ... output ...

# O Context é criado por um CommandBus que orquestra
class CommandBus:
    def __init__(self, session: TitanSession):
        self.session = session

    def diagnose(self, log_path: Path) -> DiagnosisResult:
        agent = DiagnoseAgent(self.session.core.knowledge_engine)
        result = agent.run(log_path)
        self.session.core.event_bus.emit("diagnose_completed", result.to_dict())
        self.session.metrics.record_step("diagnose", result.to_dict())
        return result
```

---

### 2.5 — Métricas e Telemetria

#### Riscos Arquiteturais

**RISCO BAIXO — RunMetrics é estado mutável**

`RunMetrics` é um contador simples. Não há risco arquitetural significativo.

**RISCO MÉDIO — Métricas espalhadas no código**

O roadmap propõe incrementar métricas em `DiagnosticEngine`, `AutoFixEngine`, etc. Isso acopla cada engine ao sistema de métricas.

#### Solução — Métricas via Event Bus

```python
# MetricsAgent escuta eventos e atualiza contadores
class MetricsAgent:
    def __init__(self):
        self.diagnoses = 0
        self.fixes = 0
        self.successes = 0

    def on_diagnose_completed(self, data):
        self.diagnoses += 1

    def on_fix_applied(self, data):
        self.fixes += 1
        if data.get("success"):
            self.successes += 1

# Registro no bus
bus.on("diagnose_completed", metrics.on_diagnose_completed)
bus.on("fix_applied", metrics.on_fix_applied)
```

**Benefício**: Nenhum engine conhece métricas. Métricas reagem a eventos.

---

### 2.6 — Planner como Orquestador Real

#### Riscos Arquiteturais

**RISCO ALTO — Planner não tem conhecimento de pipeline**

O `SkillPlanner` atual faz dispatch 1:1 (event → skill). Ele não sabe que `diagnose_completed` deve ser seguido de `fix_started`. O `run_pipeline` proposto é hardcoded:

```python
if trigger_event in ("build_failed", "fix_requested"):
    await self.dispatch("diagnose_started", data)
if data.get("findings"):
    await self.dispatch("fix_started", data)
```

Isso é um pipeline hardcoded no Planner, que deveria ser genérico.

**RISCO MÉDIO — Skills não têm ordem de execução**

O `SkillPlanner.dispatch()` itera sobre skills em ordem de registro. Não há prioridade, não há dependência entre skills.

#### Solução — Pipeline como objeto de primeira classe

```python
@dataclass
class PipelineStep:
    event_type: str
    skill_filter: Optional[Callable] = None
    condition: Optional[Callable] = None

class Pipeline:
    def __init__(self, name: str, steps: List[PipelineStep]):
        self.name = name
        self.steps = steps

    async def execute(self, planner: SkillPlanner, initial_data: Dict) -> Dict:
        data = initial_data.copy()
        for step in self.steps:
            if step.condition and not step.condition(data):
                continue
            result = await planner.dispatch(step.event_type, data)
            data.update(result or {})
        return data

# Pipelines definidos declarativamente
FIX_PIPELINE = Pipeline("fix", [
    PipelineStep("diagnose_started"),
    PipelineStep("fix_started", condition=lambda d: d.get("findings")),
    PipelineStep("validation_started", condition=lambda d: d.get("fix_applied")),
])
```

---

### 2.7 — Knowledge Engine como Base de Decisões

#### Riscos Arquiteturais

**RISCO BAIXO — Métodos novos são adições, não modificações**

`search_similar_failures()` e `get_best_known_fix()` são métodos novos que não quebram a API existente.

**RISCO MÉDIO — Knowledge Engine é criado em múltiplos lugares**

No código atual:
- `KnowledgeEngine()` é criado em `MultiLayerMemory.__init__`
- `KnowledgeEngine()` é criado em `TitanContext.__init__`

São duas instâncias independentes. O que uma aprende, a outra não sabe.

#### Solução — Single source of truth

```python
# KnowledgeEngine deve ser criado uma única vez e passado adiante
class TitanCore:
    def __init__(self):
        self.knowledge_engine = KnowledgeEngine()  # Única instância

class MultiLayerMemory:
    def __init__(self, event_bus, knowledge_engine: KnowledgeEngine):
        self.knowledge_engine = knowledge_engine  # Recebido, não criado
```

---

## 3. Diagramas Antes/Depois

### 3.1 — Antes (Estado Atual)

```
┌──────────────────────────────────────────────────────────────┐
│                        cli.py                                │
│                                                              │
│  cmd_diagnose ──→ DiagnosticEngine ──→ rules.py             │
│  cmd_fix       ──→ AutoFixEngine    ──→ DiagnosticEngine     │
│                                        ──→ FixTransaction    │
│  cmd_security  ──→ CVEMonitor                               │
│  cmd_hardware  ──→ DeviceTreeAnalyzer                       │
│  cmd_runtime   ──→ DmesgAnalyzer                            │
│  cmd_explain   ──→ ExplainEngine                            │
│  cmd_recipe    ──→ RecipeDB / RecipeIndexer                 │
│  cmd_llm       ──→ LLMAssistEngine                          │
│                                                              │
│  (cada comando é independente, sem compartilhamento)         │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                    Código Morto                               │
│                                                              │
│  DigitalTwin        ← nunca importado                       │
│  EventBus           ← nunca importado                       │
│  KnowledgeEngine    ← nunca importado (exceto em memory.py) │
│  MultiLayerMemory   ← nunca importado                       │
│  SkillPlanner       ← nunca importado                       │
│  Skills (5)         ← nunca instanciados                    │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 — Depois (Roadmap Original — PROBLEMÁTICO)

```
┌──────────────────────────────────────────────────────────────┐
│                        cli.py                                │
│                         │                                    │
│                         ▼                                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              TitanContext (God Object)                │   │
│  │                                                      │   │
│  │  event_bus  digital_twin  knowledge_engine  memory   │   │
│  │  planner   metrics       workspace                   │   │
│  │                                                      │   │
│  │  Skills registrados diretamente:                     │   │
│  │    YoctoSkill, AutoFixSkill, SecuritySkill, ...     │   │
│  └──────────┬───────────────────────────────┬───────────┘   │
│             │                               │               │
│             ▼                               ▼               │
│  DiagnosticEngine(context)       AutoFixEngine(context)     │
│  (context opcional!)             (context opcional!)         │
│                                                              │
│  Problemas:                                                  │
│  ✗ 11 dependências no Context                               │
│  ✗ context=None cria dois caminhos de execução              │
│  ✗ Eventos órfãos (emit mas ninguém consome)                │
│  ✗ Sync/async misturado                                     │
│  ✗ Métricas acopladas aos engines                           │
└──────────────────────────────────────────────────────────────┘
```

### 3.3 — Depois (Arquitetura Revisada — RECOMENDADA)

```
┌──────────────────────────────────────────────────────────────┐
│                        cli.py                                │
│                         │                                    │
│                    create_session()                          │
│                         │                                    │
│                         ▼                                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                  TitanSession                         │   │
│  │                                                      │   │
│  │  core: TitanCore     ← compartilhado entre sessões   │   │
│  │  workspace           ← específico desta sessão       │   │
│  │  metrics             ← específico desta sessão       │   │
│  │  plugins: registrados via register_plugin()          │   │
│  └──────────┬───────────────────────────────────────────┘   │
│             │                                                │
│             ▼                                                │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                  TitanCore                            │   │
│  │                                                      │   │
│  │  event_bus    ← SyncEventBus (CLI) / Async (daemon)  │   │
│  │  digital_twin ← alimentado por eventos               │   │
│  │  knowledge    ← criado uma única vez                 │   │
│  │  memory       ← recebe knowledge por injeção         │   │
│  │  planner      ← recebe skills por registro           │   │
│  └──────────┬───────────────────────────────────────────┘   │
│             │                                                │
│             ▼                                                │
│  ┌──────────────────────────────────────────────────────┐   │
│  │               Agent Layer                             │   │
│  │                                                      │   │
│  │  DiagnoseAgent  → recebe rules, retorna Diagnosis    │   │
│  │  FixAgent       → recebe Diagnosis, retorna Fix      │   │
│  │  ValidationAgent → recebe Fix, retorna bool          │   │
│  │  MetricsAgent   → escuta eventos, atualiza contadores│   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  Vantagens:                                                  │
│  ✓ TitanCore tem 4 dependências (não 11)                    │
│  ✓ Skills registrados via plugins, não hardcoded            │
│  ✓ Métricas via eventos, não acopladas                      │
│  ✓ SyncEventBus para CLI, sem problemas de async            │
│  ✓ KnowledgeEngine criado uma única vez                     │
│  ✓ Agents recebem dependências por injeção                  │
└──────────────────────────────────────────────────────────────┘
```

---

## 4. Impacto em Testes Unitários

### Roadmap Original

| Aspecto | Impacto | Nota |
|---------|---------|------|
| `context=None` em tudo | Testes nunca exercitam eventos | 🔴 Ruim |
| God Object `TitanContext` | Setup de teste precisa mockar 11 dependências | 🔴 Ruim |
| Eventos fire-and-forget | Impossível testar se evento foi consumido | 🔴 Ruim |
| Métricas nos engines | Testes precisam verificar métricas além do resultado | 🟡 Médio |
| Skills hardcoded no Context | Impossível testar Context sem skills reais | 🔴 Ruim |

### Arquitetura Revisada

| Aspecto | Impacto | Nota |
|---------|---------|------|
| `TitanCore` com 4 deps | Setup de teste simples | 🟢 Bom |
| Agents com injeção de deps | Mock fácil por parâmetro | 🟢 Bom |
| SyncEventBus | Testes síncronos, sem asyncio | 🟢 Bom |
| Métricas via eventos | Testar emitindo eventos e verificando contadores | 🟢 Bom |
| Plugins registrados externamente | Testar core sem plugins | 🟢 Bom |

### Exemplo de Teste Revisado

```python
# Teste do pipeline sem God Object
def test_diagnose_to_fix_pipeline():
    # Arrange
    core = TitanCore()
    metrics = RunMetrics()
    bus = SyncEventBus()

    diag_agent = DiagnoseAgent(rules=YOCTO_RULES)
    fix_agent = FixAgent(workspace=mock_workspace)
    metrics_agent = MetricsAgent()

    # Registrar metrics para escutar eventos
    bus.on("diagnose_completed", metrics_agent.on_diagnose_completed)
    bus.on("fix_applied", metrics_agent.on_fix_applied)

    # Act
    diagnosis = diag_agent.run(Path("test.log"))
    bus.emit("diagnose_completed", diagnosis.to_dict())

    if diagnosis.findings:
        fix = fix_agent.run(diagnosis)
        bus.emit("fix_applied", fix.to_dict())

    # Assert
    assert metrics_agent.diagnoses >= 0
    # Sem mock complexo, sem context=None, sem asyncio
```

---

## 5. Impacto em Performance

### Roadmap Original

| Operação | Overhead | Nota |
|----------|----------|------|
| Criação do `TitanContext` | ~50ms (6 instâncias + 5 skills) | 🟡 Aceitável |
| `context=None` check por chamada | ~0.01ms (if simples) | 🟢 Negligível |
| `asyncio.Queue` em código sync | ~5-10ms por `asyncio.run()` | 🔴 Problemático |
| Evento fire-and-forget | ~0.1ms por emit | 🟢 Negligível |
| KnowledgeEngine SQLite | ~1-5ms por query | 🟢 Aceitável |

### Arquitetura Revisada

| Operação | Overhead | Nota |
|----------|----------|------|
| Criação do `TitanCore` | ~30ms (4 instâncias) | 🟢 Melhor |
| Criação do `TitanSession` | ~20ms (workspace + metrics) | 🟢 Melhor |
| `SyncEventBus.emit()` | ~0.01ms (chamada direta) | 🟢 Melhor |
| Agents com injeção | ~0 (sem overhead) | 🟢 Igual |

**Veredicto**: A revisão melhora performance principalmente eliminando o overhead de `asyncio.run()` em código síncolo.

---

## 6. Impacto em Extensibilidade Futura

### Roadmap Original

| Cenário | Esforço | Nota |
|---------|---------|------|
| Adicionar plugin Android | Modificar `TitanContext` + importar skill | 🔴 Invasivo |
| Adicionar novo evento | Modificar `event_bus.py` + modificar engines | 🟡 Médio |
| Adicionar novo agente | Criar skill + modificar `TitanContext` | 🔴 Invasivo |
| Suportar daemon async | Reescrever Event Bus | 🔴 Invasivo |
| Suportar REST API | Criar wrapper around `TitanContext` | 🟡 Médio |

### Arquitetura Revisada

| Cenário | Esforço | Nota |
|---------|---------|------|
| Adicionar plugin Android | Criar `AndroidPlugin` + `register_plugin()` | 🟢 Não invasivo |
| Adicionar novo evento | Adicionar handler no bus | 🟢 Não invasivo |
| Adicionar novo agente | Criar agente + registrar no pipeline | 🟢 Não invasivo |
| Suportar daemon async | Trocar `SyncEventBus` por `AsyncEventBus` | 🟢 Swap |
| Suportar REST API | Criar rota que chama `CommandBus` | 🟢 Não invasivo |

---

## 7. Roadmap Revisado com Prioridades

### P0 — Fundação (Semana 1)

> Sem isso, nada mais funciona de forma limpa.

| # | Ação | Arquivo | Critério de Aceite |
|---|------|---------|-------------------|
| 0.1 | **CRIAR** `TitanCore` (sem God Object) | `titan/core/core.py` | `TitanCore()` instancia 4 serviços. Teste cria core sem workspace. |
| 0.2 | **CRIAR** `TitanSession` | `titan/core/session.py` | `TitanSession(core, path)` detecta workspace. Teste cria sessão mock. |
| 0.3 | **CRIAR** `SyncEventBus` | `titan/core/event_bus.py` | `bus.emit("test", {})` chama handlers registrados. Teste verifica handler chamado. |
| 0.4 | **MODIFICAR** `MultiLayerMemory` para receber `KnowledgeEngine` por injeção | `titan/core/memory.py` | `MultiLayerMemory(bus, knowledge_engine)` não cria nova instância. |
| 0.5 | **CRIAR** `RunMetrics` | `titan/core/metrics.py` | `metrics.to_dict()` retorna contadores. Teste incrementa e verifica. |

**Rollback**: Se P0 falhar, manter código atual. P0 não modifica nenhum arquivo existente (exceto `memory.py` que recebe parâmetro opcional).

### P1 — Integração (Semana 2)

> Conecta o que já existe sem quebrar.

| # | Ação | Arquivo | Critério de Aceite |
|---|------|---------|-------------------|
| 1.1 | **MODIFICAR** `DiagnosticEngine` para aceitar `TitanCore` opcional | `titan/diagnostics/engine.py` | `DiagnosticEngine(workspace, core=None)` funciona com e sem core. Teste com core=None mantém comportamento atual. |
| 1.2 | **MODIFICAR** `AutoFixEngine` para aceitar `TitanCore` opcional | `titan/autofix/engine.py` | `AutoFixEngine(workspace, core=None)` funciona com e sem core. |
| 1.3 | **MODIFICAR** `cli.py` para criar `TitanSession` | `titan/cli.py` | `main()` cria sessão. Comandos recebem `session` em vez de `ctx`. Todos os comandos existentes continuam funcionando. |
| 1.4 | **CRIAR** `MetricsAgent` | `titan/core/metrics_agent.py` | `MetricsAgent` escuta eventos e atualiza contadores. Teste emite evento e verifica contador. |
| 1.5 | **ADICIONAR** comando `telemetry` | `titan/cli.py` | `titan telemetry` mostra métricas da sessão. |

**Rollback**: Se P1 falhar, reverter `cli.py`, `diagnostics/engine.py`, `autofix/engine.py` para versões anteriores. `TitanCore` e `TitanSession` podem existir como código morto.

### P2 — Agent Framework (Semana 3-4)

> Orquestração real, sem hardcoded.

| # | Ação | Arquivo | Critério de Aceite |
|---|------|---------|-------------------|
| 2.1 | **CRIAR** `DiagnoseAgent` | `titan/agents/diagnose.py` | `DiagnoseAgent.run(log_path)` retorna `DiagnosisResult`. Teste com log mock. |
| 2.2 | **CRIAR** `FixAgent` | `titan/agents/fix.py` | `FixAgent.run(diagnosis)` retorna `FixResult`. Teste com diagnosis mock. |
| 2.3 | **CRIAR** `ValidationAgent` | `titan/agents/validation.py` | `ValidationAgent.run(fix)` retorna `bool`. Teste com fix mock. |
| 2.4 | **CRIAR** `Pipeline` declarativo | `titan/core/pipeline.py` | `Pipeline.execute()` roda steps em ordem. Teste com pipeline de 3 steps. |
| 2.5 | **MODIFICAR** `CommandBus` para usar Pipeline | `titan/core/command_bus.py` | `CommandBus.fix(log_path)` roda pipeline completo. Teste end-to-end. |
| 2.6 | **ATUALIZAR** `KnowledgeEngine` com `get_best_known_fix` | `titan/core/knowledge_engine.py` | `get_best_known_fix(signature)` retorna record com maior success_rate. |

**Rollback**: Se P2 falhar, P1 continua funcionando. Agents são novos arquivos, não modificam existentes.

---

## 8. Estratégia de Rollback Global

### Princípio: Cada etapa é reversível individualmente

```
P0 (Fundação)
  ├── Se falhar: manter código atual, P0 não modifica nada crítico
  └── Se OK: avançar para P1

P1 (Integração)
  ├── Se falhar: reverter P1, manter P0 como código morto
  └── Se OK: avançar para P2

P2 (Agents)
  ├── Se falhar: reverter P2, manter P1
  └── Se OK: Titan v13 completo
```

### Arquivos de rollback

| Etapa | Arquivos modificados | Estratégia |
|-------|---------------------|------------|
| P0 | `memory.py` (parâmetro opcional) | Manter assinatura antiga como default |
| P1 | `diagnostics/engine.py`, `autofix/engine.py`, `cli.py` | Git revert |
| P2 | Novos arquivos apenas | Deletar novos arquivos |

### Critério de aborto

Se qualquer critério de aceite de P0 falhar, **não avançar para P1**. P0 é a fundação — se a fundação está errada, tudo em cima será errado.

---

## 9. Resumo Executivo

### O que o roadmap original acerta

- ✅ Identifica corretamente o problema (módulos isolados)
- ✅ Propõe integração em vez de expansão
- ✅ Reconhece que os módulos já existem
- ✅ Métricas e telemetria são necessárias

### O que o roadmap original erra

- ❌ Cria um God Object (`TitanContext` com 11 dependências)
- ❌ Usa Event Bus como chamada indireta (eventos órfãos)
- ❌ Mistura sync/async sem necessidade
- ❌ Context opcional (`context=None`) cria dois caminhos de execução
- ❌ Skills hardcoded no Context
- ❌ Métricas acopladas aos engines
- ❌ Validação não é um agente
- ❌ Planner não tem noção de pipeline

### O que a revisão propõe

- `TitanCore` (4 dependências) em vez de `TitanContext` (11 dependências)
- `TitanSession` separado do core
- `SyncEventBus` para CLI, `AsyncEventBus` para daemon
- Agents com injeção de dependências
- Métricas via eventos (MetricsAgent)
- Pipeline declarativo
- KnowledgeEngine criado uma única vez
- Plugins registrados externamente
- Rollback individual por etapa

### Estimativa revisada

| Sprint | Original | Revisado |
|--------|----------|----------|
| Sprint 1 | 2 novos + 8 modificados | 4 novos + 1 modificado |
| Sprint 2 | 2 modificados | 3 novos + 1 modificado |
| **Total** | **2 novos + 10 modificados** | **7 novos + 2 modificados** |

**Trade-off**: Mais arquivos novos, menos modificações em código existente. Menor risco de regressão.
