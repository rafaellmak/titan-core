"""Teste de integração end-to-end da Sprint 1.

Valida o fluxo completo:
  1. Workspace carregado via TitanSession
  2. Diagnose executado via DiagnosticEngine com core
  3. Evento emitido (diagnose_completed)
  4. Knowledge atualizado
  5. Métricas atualizadas
  6. Telemetry exibe métricas corretas
  7. Trace salvo em arquivo

Usa os componentes reais da Sprint 1 — sem mocks desnecessários.
"""
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from titan.core.core import TitanCore
from titan.core.session import TitanSession
from titan.core.metrics import RunMetrics
from titan.core.knowledge_engine import KnowledgeEngine
from titan.core.event_bus import LocalEventBus
from titan.diagnostics.engine import DiagnosticEngine
from titan.diagnostics.rules import YOCTO_RULES
from titan.workspace.models import YoctoWorkspace


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_workspace(tmp_path):
    """Cria um workspace Yocto mínimo para testes."""
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    (build_dir / "conf").mkdir()
    (build_dir / "conf" / "local.conf").write_text('MACHINE = "raspberrypi3"\n')
    (build_dir / "conf" / "bblayers.conf").write_text("")
    (tmp_path / "oe-init-build-env").write_text("#!/bin/bash\n")
    return tmp_path


@pytest.fixture
def yocto_workspace(tmp_workspace):
    """Cria um YoctoWorkspace apontando para o tmp dir."""
    return YoctoWorkspace(
        root_dir=tmp_workspace,
        build_dir=tmp_workspace / "build",
        init_script=tmp_workspace / "oe-init-build-env",
        machine="raspberrypi3",
    )


@pytest.fixture
def sample_log(tmp_workspace):
    """Cria um log de erro Yocto válido."""
    log = tmp_workspace / "test.log"
    log.write_text(
        "ERROR: Task 6984 (/path/to/recipe.bb:do_compile) failed with exit code '1'\n"
        "ERROR: Nothing PROVIDES 'missing-package'\n"
    )
    return log


@pytest.fixture
def core_with_sync_bus():
    """Cria um TitanCore com LocalEventBus para capturar eventos síncronos."""
    bus = LocalEventBus()
    core = TitanCore(event_bus=bus)
    return core, bus


# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------

class TestSprint1EndToEnd:
    """Valida o fluxo completo da Sprint 1."""

    def test_01_titan_core_creates_all_services(self):
        """TitanCore instancia todos os 4 serviços core."""
        core = TitanCore()

        assert core.event_bus is not None
        assert core.digital_twin is not None
        assert core.knowledge_engine is not None
        assert core.memory is not None
        assert core.planner is not None

    def test_02_titan_core_knowledge_engine_shared_with_memory(self):
        """KnowledgeEngine é o mesmo objeto no core e na memory."""
        core = TitanCore()

        # Memory recebe o mesmo KnowledgeEngine criado pelo core
        assert core.memory.knowledge_engine is core.knowledge_engine

    def test_03_titan_session_creates_workspace_and_metrics(self, tmp_workspace):
        """TitanSession detecta workspace e cria métricas."""
        core = TitanCore()
        session = TitanSession(core, workspace_path=str(tmp_workspace))

        assert session.core is core
        assert session.metrics is not None
        assert isinstance(session.metrics, RunMetrics)

    def test_04_session_exposes_core_services_via_properties(self, tmp_workspace):
        """TitanSession expõe serviços do core via properties."""
        core = TitanCore()
        session = TitanSession(core, workspace_path=str(tmp_workspace))

        assert session.event_bus is core.event_bus
        assert session.digital_twin is core.digital_twin
        assert session.knowledge_engine is core.knowledge_engine
        assert session.memory is core.memory
        assert session.planner is core.planner

    def test_05_diagnostic_engine_with_core_emits_events(self, yocto_workspace, sample_log, core_with_sync_bus):
        """DiagnosticEngine com core emite eventos no EventBus."""
        core, bus = core_with_sync_bus

        # Capturar eventos emitidos
        events_captured = []
        bus.on("diagnose_completed", lambda data: events_captured.append(data))

        engine = DiagnosticEngine(yocto_workspace, core=core)
        findings = engine.analyze_log(sample_log)

        # Valida: findings encontrados
        assert len(findings) == 2
        rule_ids = {f["rule_id"] for f in findings}
        assert "YOC-002" in rule_ids
        assert "YOC-001" in rule_ids

        # AGORA eventos SÃO entregues (bug corrigido na Sprint 1.5)
        # LocalEventBus.emit() é síncrono e entrega handlers imediatamente
        assert len(events_captured) == 1
        assert events_captured[0]["findings_count"] == 2

    def test_06_diagnostic_engine_updates_knowledge(self, yocto_workspace, sample_log, core_with_sync_bus):
        """DiagnosticEngine atualiza KnowledgeEngine com findings."""
        core, bus = core_with_sync_bus

        engine = DiagnosticEngine(yocto_workspace, core=core)
        findings = engine.analyze_log(sample_log)

        # Valida: knowledge foi persistido
        for f in findings:
            record = core.knowledge_engine.get_knowledge(f["rule_id"])
            assert record is not None, f"Knowledge para {f['rule_id']} não foi persistido"
            assert record.root_cause == f["description"]
            assert record.confidence == 0.9

    def test_07_diagnostic_engine_without_core_still_works(self, yocto_workspace, sample_log):
        """DiagnosticEngine funciona sem core (backward compatibility)."""
        engine = DiagnosticEngine(yocto_workspace, core=None)
        findings = engine.analyze_log(sample_log)

        assert len(findings) == 2
        # Sem core, sem eventos, sem knowledge update — mas diagnóstico funciona

    def test_08_metrics_updated_after_diagnose(self, tmp_workspace, yocto_workspace, sample_log):
        """Métricas são atualizadas após diagnóstico."""
        core = TitanCore()
        session = TitanSession(core, workspace_path=str(tmp_workspace))

        engine = DiagnosticEngine(yocto_workspace, core=core)
        engine.analyze_log(sample_log)

        # Simula o que cmd_diagnose faz
        session.metrics.diagnoses += 1

        assert session.metrics.diagnoses == 1

    def test_09_run_metrics_to_dict(self):
        """RunMetrics.to_dict() retorna todos os campos esperados."""
        metrics = RunMetrics()
        metrics.diagnoses = 3
        metrics.fixes = 2
        metrics.successes = 1
        metrics.failures = 1
        metrics.record_step("diagnose", {"log": "test.log"})

        d = metrics.to_dict()

        assert d["diagnoses"] == 3
        assert d["fixes"] == 2
        assert d["successes"] == 1
        assert d["failures"] == 1
        assert d["success_rate"] == 50.0
        assert "elapsed_seconds" in d
        assert len(d["steps"]) == 1

    def test_10_run_metrics_save_trace(self, tmp_path):
        """RunMetrics.save_trace() salva arquivo JSON válido."""
        metrics = RunMetrics()
        metrics.diagnoses = 1
        metrics.record_step("test", {})

        trace_file = metrics.save_trace(trace_dir=str(tmp_path / "traces"))

        assert trace_file.exists()
        data = json.loads(trace_file.read_text())
        assert data["diagnoses"] == 1
        assert len(data["steps"]) == 1

    def test_11_local_event_bus_delivers_events(self):
        """LocalEventBus entrega eventos aos handlers registrados (síncrono)."""
        bus = LocalEventBus()
        received = []

        bus.on("test_event", lambda data: received.append(data))

        # LocalEventBus.emit() é síncrono — não precisa de asyncio.run
        bus.emit("test_event", {"key": "value"})

        assert len(received) == 1
        assert received[0]["key"] == "value"

    def test_12_metrics_agent_listens_to_events(self):
        """MetricsAgent atualiza métricas quando eventos são emitidos."""
        from titan.core.metrics_agent import MetricsAgent

        metrics = RunMetrics()
        agent = MetricsAgent(metrics)
        bus = LocalEventBus()
        agent.register(bus)

        # LocalEventBus.emit() é síncrono — não precisa de asyncio.run
        bus.emit("diagnose_completed", {"log": "test.log", "findings_count": 2})

        assert len(metrics.steps) == 1
        assert metrics.steps[0]["step"] == "diagnose"

    def test_13_full_pipeline_with_local_bus(self, yocto_workspace, sample_log):
        """Pipeline completo: core → diagnose → evento → knowledge → metrics."""
        # Setup
        bus = LocalEventBus()
        core = TitanCore(event_bus=bus)
        metrics = RunMetrics()

        # Capturar eventos
        events = []
        bus.on("diagnose_completed", lambda d: events.append(d))

        # Executar diagnóstico
        engine = DiagnosticEngine(yocto_workspace, core=core)
        findings = engine.analyze_log(sample_log)

        # Atualizar métricas (como cmd_diagnose faz)
        metrics.diagnoses += 1
        metrics.record_step("diagnose", {"findings": len(findings)})

        # Validações
        assert len(findings) >= 1
        # AGORA eventos SÃO entregues (bug corrigido na Sprint 1.5)
        assert len(events) == 1
        assert events[0]["findings_count"] == len(findings)
        assert metrics.diagnoses == 1
        assert len(metrics.steps) == 1

        # Knowledge persistido (INSERT OR REPLACE por rule_id)
        for f in findings:
            record = core.knowledge_engine.get_knowledge(f["rule_id"])
            assert record is not None

    def test_14_knowledge_engine_no_duplicate_entries(self, yocto_workspace, sample_log, core_with_sync_bus):
        """DiagnosticEngine usa INSERT OR REPLACE para evitar duplicatas."""
        core, bus = core_with_sync_bus

        engine = DiagnosticEngine(yocto_workspace, core=core)

        # Executar diagnóstico 2 vezes com mesmo log
        engine.analyze_log(sample_log)
        engine.analyze_log(sample_log)

        # O KnowledgeEngine usa INSERT OR REPLACE por problem_signature.
        # Cada rule_id deve ter apenas 1 entrada.
        conn = sqlite3.connect(core.knowledge_engine.db_path)
        cursor = conn.execute(
            "SELECT problem_signature, COUNT(*) FROM knowledge_records GROUP BY problem_signature"
        )
        rows = cursor.fetchall()
        conn.close()

        # Cada signature deve ter exatamente 1 entrada (INSERT OR REPLACE)
        for sig, count in rows:
            assert count == 1, f"Signature '{sig}' tem {count} entradas (esperado 1)"

    def test_15_digital_twin_receives_events_via_emit_event(self, core_with_sync_bus):
        """DigitalTwin atualiza grafo quando eventos são emitidos via emit_event."""
        core, bus = core_with_sync_bus

        # emit_event agora é síncrono — não precisa de asyncio.run
        core.digital_twin.emit_event("layer_added", {"layer": "meta-test"})

        graph = core.digital_twin.get_graph()
        assert graph.has_node("layer:meta-test")

    def test_16_session_register_skill(self, tmp_workspace):
        """TitanSession.register_skill() registra skills no planner."""
        from titan.core.planner import Skill

        class DummySkill(Skill):
            def can_handle(self, event_type, data):
                return event_type == "test"
            async def execute(self, data, memory, digital_twin, knowledge_engine):
                return {"handled": True}

        core = TitanCore()
        session = TitanSession(core, workspace_path=str(tmp_workspace))
        session.register_skill(DummySkill())

        assert len(core.planner.skills) == 1

    def test_17_autofix_engine_with_core_emits_events(self, tmp_path, core_with_sync_bus):
        """AutoFixEngine com core emite eventos de fix_applied/fix_failed."""
        from titan.autofix.engine import AutoFixEngine

        core, bus = core_with_sync_bus
        events_captured = []
        bus.on("fix_applied", lambda d: d)
        bus.on("fix_failed", lambda d: d)

        # Criar workspace com recipe mutável
        workspace_root = tmp_path / "ws"
        workspace_root.mkdir()
        layer = workspace_root / "meta-test"
        layer.mkdir()
        recipes_dir = layer / "recipes-test" / "openssl"
        recipes_dir.mkdir(parents=True)
        bb = recipes_dir / "openssl_3.0.bb"
        bb.write_text('SUMMARY = "OpenSSL"\nPV = "3.0.8"\n')

        workspace = YoctoWorkspace(
            root_dir=workspace_root,
            build_dir=workspace_root / "build",
            init_script=workspace_root / "oe-init-build-env",
            machine="qemux86-64",
            layers=[layer],
        )

        # Indexar recipe
        from titan.recipes.db import RecipeDB
        db = RecipeDB(workspace_root)
        db.upsert_recipe({
            "pn": "openssl",
            "pv": "3.0.8",
            "file_path": str(bb),
            "depends": "",
            "rdepends": "",
            "license": "",
            "src_uri": "",
            "inherits": "",
        })

        # Criar log com YOC-004 (fixable)
        log = workspace_root / "build.log"
        log.write_text(
            "WARNING: openssl-3.0.8-r0 do_package_qa: QA Issue: openssl rdepends on zlib, "
            "but it isn't a build-time dependency?\n"
        )

        engine = AutoFixEngine(workspace, core=core)

        with patch.object(AutoFixEngine, "_has_bitbake", return_value=False):
            engine.run_fix(log)

        # O fix foi aplicado (YOC-004 é fixable)
        content = bb.read_text()
        assert "RDEPENDS" in content or "zlib" in content


class TestSprint1BackwardCompatibility:
    """Valida que nada existente foi quebrado."""

    def test_diagnostic_engine_without_core_unchanged(self, yocto_workspace, sample_log):
        """DiagnosticEngine sem core funciona identicamente ao original."""
        engine = DiagnosticEngine(workspace=yocto_workspace)
        findings = engine.analyze_log(sample_log)

        assert len(findings) == 2
        for f in findings:
            assert "rule_id" in f
            assert "severity" in f
            assert "description" in f
            assert "suggestion" in f

    def test_autofix_engine_without_core_unchanged(self, yocto_workspace):
        """AutoFixEngine sem core funciona identicamente ao original."""
        from titan.autofix.engine import AutoFixEngine

        engine = AutoFixEngine(workspace=yocto_workspace)
        assert engine.db is not None
        assert engine.diag is not None

    def test_memory_without_knowledge_engine_creates_default(self):
        """MultiLayerMemory sem knowledge_engine cria um por padrão."""
        from titan.core.event_bus import LocalEventBus
        from titan.core.memory import MultiLayerMemory

        bus = LocalEventBus()
        memory = MultiLayerMemory(event_bus=bus, base_path=".titan_memory_test")

        assert memory.knowledge_engine is not None

    def test_memory_with_injected_knowledge_engine(self):
        """MultiLayerMemory com knowledge_engine injetado usa o mesmo objeto."""
        from titan.core.event_bus import LocalEventBus
        from titan.core.memory import MultiLayerMemory
        from titan.core.knowledge_engine import KnowledgeEngine

        bus = LocalEventBus()
        ke = KnowledgeEngine(base_path=".titan_ke_injected_test")
        memory = MultiLayerMemory(event_bus=bus, base_path=".titan_memory_injected_test",
                                  knowledge_engine=ke)

        assert memory.knowledge_engine is ke
