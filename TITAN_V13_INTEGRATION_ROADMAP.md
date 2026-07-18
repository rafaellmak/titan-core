# Titan v13 — The Integration Release
## Roadmap de Integração por Arquivo

> **Premissa**: Os módulos já existem. O problema não é criar código novo — é conectar o que já existe em um pipeline coerente.

---

## Diagnóstico Atual

### O que existe mas NÃO é usado pelo CLI

| Módulo | Arquivo | Status |
|--------|---------|--------|
| `DigitalTwin` | `titan/core/digital_twin.py` | ✅ Existe, ❌ Nenhum import no CLI |
| `EventBus` | `titan/core/event_bus.py` | ✅ Existe, ❌ Nenhum import no CLI |
| `KnowledgeEngine` | `titan/core/knowledge_engine.py` | ✅ Existe, ❌ Nenhum import no CLI |
| `MultiLayerMemory` | `titan/core/memory.py` | ✅ Existe, ❌ Nenhum import no CLI |
| `SkillPlanner` | `titan/core/planner.py` | ✅ Existe, ❌ Nenhum import no CLI |
| `AutoFixSkill` | `titan/skills/autofix_skill.py` | ✅ Existe, ❌ Nunca instanciado |
| `YoctoSkill` | `titan/skills/yocto_skill.py` | ✅ Existe, ❌ Nunca instanciado |
| `SecuritySkill` | `titan/skills/security_skill.py` | ✅ Existe, ❌ Nunca instanciado |
| `BuildrootSkill` | `titan/skills/buildroot_skill.py` | ✅ Existe, ❌ Nunca instanciado |
| `DTSSkill` | `titan/skills/dts_skill.py` | ✅ Existe, ❌ Nunca instanciado |

### O que o CLI realmente usa

```
cli.py
 ├── WorkspaceDetector.detect()
 ├── DiagnosticEngine.analyze_log()
 ├── AutoFixEngine.run_fix()
 ├── RecipeDB / RecipeIndexer
 ├── RecipeModifier / WorkspaceModifier
 ├── CVEMonitor
 ├── DeviceTreeAnalyzer
 ├── DmesgAnalyzer
 ├── ExplainEngine
 └── LLMAssistEngine.route_query()
```

**Todos são chamados diretamente. Nenhum passa pelo Event Bus, Digital Twin ou Planner.**

---

## Arquitetura Alvo

```
┌─────────────────────────────────────────────────────────┐
│                     CLI (cli.py)                       │
│  diagnose │ fix │ recipe │ security │ explain │ ...    │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│              TitanContext (NOVO)                        │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  EventBus   │  │ DigitalTwin  │  │  Knowledge   │  │
│  │  (existe)   │  │   (existe)   │  │   Engine     │  │
│  └─────────────┘  └──────────────┘  │   (existe)   │  │
│  ┌─────────────┐  ┌──────────────┐  └──────────────┘  │
│  │  Memory     │  │  Planner     │  ┌──────────────┐  │
│  │  (existe)   │  │  (existe)    │  │   Metrics    │  │
│  └─────────────┘  └──────────────┘  │   (NOVO)     │  │
│                                      └──────────────┘  │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│                   Skills Layer                          │
│  YoctoSkill │ AutoFixSkill │ SecuritySkill │ DTSSkill   │
│  BuildrootSkill │ (futuros plugins...)                  │
└─────────────────────────────────────────────────────────┘
```

---

## Sprint 1 — Core Integration (Semana 1-2)

### Etapa 1: Criar `TitanContext` (estado global compartilhado)

**Arquivo**: `titan/core/context.py` (NOVO)

```python
class TitanContext:
    """Fonte única de verdade para todo o Titan.

    Substitui chamadas isoladas por estado compartilhado.
    Todos os módulos consultam e atualizam este contexto.
    """
    def __init__(self, workspace_path: str = "."):
        self.event_bus = LocalEventBus()
        self.digital_twin = DigitalTwin(self.event_bus)
        self.knowledge_engine = KnowledgeEngine()
        self.memory = MultiLayerMemory(self.event_bus)
        self.planner = SkillPlanner(self.memory, self.digital_twin, self.knowledge_engine)
        self.workspace = None
        self.metrics = RunMetrics()

        # Registrar skills padrão
        self.planner.register_skill(YoctoSkill())
        self.planner.register_skill(AutoFixSkill())
        self.planner.register_skill(SecuritySkill())
        self.planner.register_skill(DTSSkill())
        self.planner.register_skill(BuildrootSkill())
```

**Por que este arquivo**: Sem um ponto central, cada módulo continua isolado. Este é o "cola" que falta.

---

### Etapa 2: Conectar Event Bus ao fluxo real

**Arquivo**: `titan/core/event_bus.py` (MODIFICAR)

Adicionar eventos de domínio:

```python
# Eventos de domínio que serão emitidos pelo pipeline
EVENT_WORKSPACE_LOADED = "workspace_loaded"
EVENT_WORKSPACE_SCANNED = "workspace_scanned"
EVENT_DIAGNOSE_STARTED = "diagnose_started"
EVENT_DIAGNOSE_COMPLETED = "diagnose_completed"
EVENT_FIX_STARTED = "fix_started"
EVENT_FIX_APPLIED = "fix_applied"
EVENT_FIX_FAILED = "fix_failed"
EVENT_VALIDATION_PASSED = "validation_passed"
EVENT_VALIDATION_FAILED = "validation_failed"
EVENT_KNOWLEDGE_UPDATED = "knowledge_updated"
```

**Arquivo**: `titan/workspace/detector.py` (MODIFICAR)

Fazer o detector emitir eventos:

```python
# Após detectar workspace:
await context.event_bus.emit(EVENT_WORKSPACE_LOADED, workspace.to_dict())
await context.digital_twin.emit_event("workspace_scanned", {...})
```

---

### Etapa 3: Pipeline Diagnose → Fix → Validate

**Arquivo**: `titan/diagnostics/engine.py` (MODIFICAR)

```python
class DiagnosticEngine:
    def __init__(self, workspace: Workspace, context: TitanContext = None):
        self.workspace = workspace
        self.context = context  # NOVO

    def analyze_log(self, log_path: Path) -> List[Dict]:
        # NOVO: emitir evento de início
        if self.context:
            self.context.event_bus.emit("diagnose_started", {"log": str(log_path)})
            self.context.metrics.diagnoses += 1

        findings = []  # ... lógica existente ...

        # NOVO: emitir evento de conclusão + atualizar knowledge
        if self.context:
            self.context.event_bus.emit("diagnose_completed", {
                "log": str(log_path),
                "findings_count": len(findings),
                "critical_count": sum(1 for f in findings if f["severity"] == "Critical"),
            })
            # Alimentar knowledge engine com padrões encontrados
            for f in findings:
                record = KnowledgeRecord(
                    problem_signature=f["rule_id"],
                    root_cause=f["description"],
                    action_taken="diagnosed",
                    outcome="found",
                    confidence=0.9,
                    success_rate=1.0,
                )
                self.context.knowledge_engine.add_knowledge(record)

        return findings
```

**Arquivo**: `titan/autofix/engine.py` (MODIFICAR)

```python
class AutoFixEngine:
    def __init__(self, workspace, context: TitanContext = None):
        self.workspace = workspace
        self.context = context  # NOVO
        self.diag = DiagnosticEngine(workspace, context)  # Passar context

    def run_fix(self, log_path: Path):
        # NOVO: evento de início
        if self.context:
            self.context.event_bus.emit("fix_started", {"log": str(log_path)})
            self.context.metrics.fixes += 1

        findings = self.diag.analyze_log(log_path)
        # ... lógica existente de fix ...

        # NOVO: evento de resultado + knowledge update
        if self.context:
            success = workspace_ok and mutation_ok
            self.context.event_bus.emit(
                "fix_applied" if success else "fix_failed",
                {"log": str(log_path), "success": success}
            )
            if success:
                self.context.metrics.successes += 1
            # Atualizar knowledge com resultado
            self.context.knowledge_engine.update_knowledge_usage(
                f"build_failure:{log_path}", success
            )
```

---

### Etapa 4: CLI integrada ao Context

**Arquivo**: `titan/cli.py` (MODIFICAR)

```python
# No topo do main():
from titan.core.context import TitanContext

def main():
    parser = argparse.ArgumentParser(...)
    # ... argumentos existentes ...

    args = parser.parse_args()

    # NOVO: criar contexto compartilhado
    ctx = TitanContext(workspace_path=args.workspace)
    ctx.workspace = WorkspaceDetector.detect(args.workspace)

    # Passar contexto para todos os comandos
    if hasattr(args, 'func'):
        result = args.func(args, ctx)  # <-- ctx como segundo argumento
        sys.exit(result if isinstance(result, int) else 0)

# Cada comando recebe ctx:
def cmd_diagnose(args, ctx: TitanContext):
    engine = DiagnosticEngine(ctx.workspace, ctx)
    findings = engine.analyze_log(Path(args.log))
    # ... resto existente ...

def cmd_fix(args, ctx: TitanContext):
    engine = AutoFixEngine(ctx.workspace, ctx)
    engine.run_fix(Path(args.log))

def cmd_security(args, ctx: TitanContext):
    # Disparar via skill/planner em vez de chamada direta
    ctx.event_bus.emit("security_scan", {"online": args.online})
    # ... ou manter chamada direta mas com ctx injetado ...
```

---

### Etapa 5: Métricas e Telemetria

**Arquivo**: `titan/core/metrics.py` (NOVO)

```python
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

class RunMetrics:
    def __init__(self):
        self.diagnoses = 0
        self.fixes = 0
        self.successes = 0
        self.failures = 0
        self.start_time = datetime.now()
        self.steps: List[Dict[str, Any]] = []

    @property
    def success_rate(self) -> float:
        if self.fixes == 0:
            return 0.0
        return (self.successes / self.fixes) * 100

    def record_step(self, step: str, details: Dict[str, Any] = None):
        self.steps.append({
            "step": step,
            "timestamp": datetime.now().isoformat(),
            "details": details or {},
        })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "diagnoses": self.diagnoses,
            "fixes": self.fixes,
            "successes": self.successes,
            "failures": self.failures,
            "success_rate": round(self.success_rate, 1),
            "elapsed_seconds": (datetime.now() - self.start_time).total_seconds(),
            "steps": self.steps,
        }

    def save_trace(self, trace_dir: str = ".titan/traces"):
        trace_path = Path(trace_dir)
        trace_path.mkdir(parents=True, exist_ok=True)
        trace_file = trace_path / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(trace_file, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        return trace_file
```

**Arquivo**: `titan/cli.py` (ADICIONAR comando)

```python
def cmd_telemetry(args, ctx: TitanContext):
    """Mostra métricas da sessão atual."""
    m = ctx.metrics.to_dict()
    print(f"📊 Titan Telemetry")
    print(f"   Diagnoses:    {m['diagnoses']}")
    print(f"   Fixes:        {m['fixes']}")
    print(f"   Successes:    {m['successes']}")
    print(f"   Success Rate: {m['success_rate']}%")
    print(f"   Elapsed:      {m['elapsed_seconds']:.1f}s")
    if args.save:
        trace_file = ctx.metrics.save_trace()
        print(f"   Trace saved:  {trace_file}")
    return 0

# Em main():
p_telemetry = subparsers.add_parser("telemetry")
p_telemetry.add_argument("--save", action="store_true")
p_telemetry.set_defaults(func=cmd_telemetry)
```

---

## Sprint 2 — Agent Framework (Semana 3-4)

### Etapa 6: Planner como orquestador real

**Arquivo**: `titan/core/planner.py` (MODIFICAR)

```python
class SkillPlanner:
    # ... existente ...

    async def run_pipeline(self, trigger_event: str, data: Dict[str, Any]):
        """Executa o pipeline completo para um evento de trigger.

        Fluxo:
        1. Dispatch para skill apropriada
        2. Coleta resultado
        3. Atualiza knowledge
        4. Emite evento de conclusão
        """
        self.memory.log_event("PIPELINE_START", {"trigger": trigger_event})

        # Fase 1: Diagnóstico (se aplicável)
        if trigger_event in ("build_failed", "fix_requested"):
            await self.dispatch("diagnose_started", data)

        # Fase 2: Fix (se diagnóstico encontrou problemas)
        if data.get("findings"):
            await self.dispatch("fix_started", data)

        # Fase 3: Validação
        if data.get("fix_applied"):
            await self.dispatch("validation_started", data)

        self.memory.log_event("PIPELINE_COMPLETE", {"trigger": trigger_event})
```

---

### Etapa 7: Knowledge Engine como base de decisões

**Arquivo**: `titan/core/knowledge_engine.py` (MODIFICAR)

Adicionar busca antes de diagnosticar:

```python
class KnowledgeEngine:
    # ... existente ...

    def search_similar_failures(self, error_signature: str) -> List[KnowledgeRecord]:
        """Busca falhas similares antes de iniciar diagnóstico.
        Usado pelo DiagnoseAgent para acelerar resolução."""
        return self.find_similar_knowledge(error_signature)

    def get_best_known_fix(self, problem_signature: str) -> Optional[KnowledgeRecord]:
        """Retorna a correção com maior success_rate para um problema conhecido."""
        records = self.find_similar_knowledge(problem_signature)
        if not records:
            return None
        return max(records, key=lambda r: (r.success_rate, r.confidence))
```

---

## Resumo de Arquivos a Modificar

| # | Ação | Arquivo | Complexidade |
|---|------|---------|-------------|
| 1 | **CRIAR** | `titan/core/context.py` | Média |
| 2 | **CRIAR** | `titan/core/metrics.py` | Baixa |
| 3 | **MODIFICAR** | `titan/core/event_bus.py` | Baixa |
| 4 | **MODIFICAR** | `titan/core/planner.py` | Média |
| 5 | **MODIFICAR** | `titan/core/knowledge_engine.py` | Baixa |
| 6 | **MODIFICAR** | `titan/diagnostics/engine.py` | Média |
| 7 | **MODIFICAR** | `titan/autofix/engine.py` | Média |
| 8 | **MODIFICAR** | `titan/cli.py` | Alta |
| 9 | **MODIFICAR** | `titan/workspace/detector.py` | Baixa |
| 10 | **VERIFICAR** | `titan/skills/*.py` | Baixa |

**Total**: 2 arquivos novos, 8 modificados, 1 verificação.

---

## Verificação

```bash
# 1. Pipeline completo
titan diagnose build.log        # deve emitir eventos
titan fix build.log             # deve usar knowledge + emitir eventos
titan telemetry                 # deve mostrar métricas

# 2. Knowledge persistence
# Após um fix, verificar .titan_knowledge/knowledge.db

# 3. Traces
# Após execução, verificar .titan/traces/*.json

# 4. Testes
pytest tests/ -v
```

---

## O que NÃO fazer nesta sprint

- ❌ Modificar `security/`, `hardware/`, `runtime/` além de hooks mínimos
- ❌ Expandir `buildroot/` ou `explain/`
- ❌ Adicionar novos comandos CLI
- ❌ Refatorar módulos que já funcionam
- ❌ Criar novos parsers ou indexadores

**Foco**: Integração. Não expansão.
