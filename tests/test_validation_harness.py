import pytest
import asyncio
import os
import shutil
import tempfile
from pathlib import Path

from titan.validation.contracts import ErrorSignature, SkillResult, ValidationResult, ValidationCheck
from titan.validation.score import Scorer
from titan.validation.report import generate_report
from titan.validation.validators import (
    BuildrootValidator, YoctoValidator, DTSValidator, SecurityValidator,
)
from titan.validation.harness import ValidationHarness
from titan.validation.history import ValidationHistory


# ---------------------------------------------------------------------------
# SkillResult
# ---------------------------------------------------------------------------

class TestSkillResult:
    def test_from_skill_success(self):
        result = SkillResult.from_skill("BuildrootSkill", {"status": "indexed", "arch": "aarch64"})
        assert result.success is True
        assert result.skill_name == "BuildrootSkill"
        assert result.summary == "indexed"

    def test_from_skill_error(self):
        result = SkillResult.from_skill("AutoFixSkill", {"error": "No recipe found"})
        assert result.success is False
        assert "No recipe found" in result.messages[0]

    def test_from_skill_none(self):
        result = SkillResult.from_skill("TestSkill", {})
        assert result.success is True
        assert result.summary == "completed"


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------

class TestValidationResult:
    def test_to_dict(self):
        vr = ValidationResult(
            score=85.0,
            accepted=True,
            checks=[ValidationCheck(name="test", passed=True)],
            reasons=["all good"],
        )
        d = vr.to_dict()
        assert d["score"] == 85.0
        assert d["accepted"] is True
        assert d["reasons"] == ["all good"]

    def test_empty(self):
        vr = ValidationResult(score=100.0, accepted=True)
        assert vr.to_dict()["score"] == 100.0


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------

class TestScorer:
    def test_all_pass(self):
        checks = [
            ValidationCheck(name="a", passed=True, weight=1.0),
            ValidationCheck(name="b", passed=True, weight=1.0),
        ]
        score = Scorer().compute(checks)
        assert score == 100.0

    def test_half_pass(self):
        checks = [
            ValidationCheck(name="a", passed=True, weight=1.0),
            ValidationCheck(name="b", passed=False, weight=1.0),
        ]
        score = Scorer().compute(checks)
        assert score == 50.0

    def test_custom_weights(self):
        checks = [
            ValidationCheck(name="critical", passed=True, weight=3.0),
            ValidationCheck(name="minor", passed=False, weight=1.0),
        ]
        score = Scorer({"critical": 3.0, "minor": 1.0}).compute(checks)
        assert score == 75.0

    def test_classify(self):
        s = Scorer()
        assert s.classify(95) == "excellent"
        assert s.classify(80) == "good"
        assert s.classify(60) == "needs_review"
        assert s.classify(30) == "rejected"


# ---------------------------------------------------------------------------
# BuildrootValidator
# ---------------------------------------------------------------------------

class TestBuildrootValidator:
    def make_result(self, arch="aarch64", toolchain_type="external", packages=10):
        return SkillResult(
            success=True,
            skill_name="BuildrootSkill",
            summary="indexed",
            raw={"arch": arch, "toolchain_type": toolchain_type, "packages": packages},
        )

    def test_can_validate(self):
        v = BuildrootValidator()
        assert v.can_validate("BuildrootSkill", self.make_result())
        assert not v.can_validate("YoctoSkill", SkillResult(success=True, skill_name="YoctoSkill", summary="indexed"))

    def test_validates_without_workspace(self):
        v = BuildrootValidator()
        result = self.make_result(arch="arm", toolchain_type="external")
        vr = v.validate(result)
        assert vr.accepted is True
        assert vr.score >= 60
        assert any("arch" in c.name for c in vr.checks)

    def test_rejects_missing_arch(self):
        v = BuildrootValidator()
        result = self.make_result(arch="", toolchain_type="")
        vr = v.validate(result)
        assert vr.score < 100


# ---------------------------------------------------------------------------
# YoctoValidator
# ---------------------------------------------------------------------------

class TestYoctoValidator:
    def test_can_validate(self):
        v = YoctoValidator()
        r = SkillResult(success=True, skill_name="YoctoSkill", summary="indexed", raw={"count": 42})
        assert v.can_validate("YoctoSkill", r)

    def test_validates_indexed(self):
        v = YoctoValidator()
        r = SkillResult(success=True, skill_name="YoctoSkill", summary="indexed", raw={"count": 10})
        vr = v.validate(r)
        assert vr.accepted is True
        assert any("recipes_indexed" in c.name for c in vr.checks)

    def test_accepts_autofix_with_mutations(self):
        v = YoctoValidator()
        r = SkillResult(
            success=True, skill_name="AutoFixSkill", summary="applied",
            raw={"fixed": True, "mutated_files": ["openssl_3.0.bb"]},
        )
        vr = v.validate(r)
        assert vr.accepted is True
        reasons = [c.name for c in vr.checks]
        assert "yocto_fix_applied" in reasons
        assert "yocto_mutation_valid" in reasons


# ---------------------------------------------------------------------------
# DTSValidator
# ---------------------------------------------------------------------------

class TestDTSValidator:
    def test_can_validate(self):
        v = DTSValidator()
        r = SkillResult(success=True, skill_name="DTSSkill", summary="dts_analyzed", raw={})
        assert v.can_validate("DTSSkill", r)

    def test_validates_clean_dts(self):
        v = DTSValidator()
        r = SkillResult(
            success=True, skill_name="DTSSkill", summary="ok",
            raw={"dtc_compilation": True, "warnings": [], "binding_check": True, "model": "Test Board"},
        )
        vr = v.validate(r)
        assert vr.accepted is True
        assert vr.score >= 80

    def test_validates_with_warnings(self):
        v = DTSValidator()
        r = SkillResult(
            success=True, skill_name="DTSSkill", summary="ok",
            raw={"dtc_compilation": True, "warnings": ["unit_address_vs_reg"], "binding_check": True},
        )
        vr = v.validate(r)
        # Should still accept but score lower
        assert vr.score < 100

    def test_rejects_dtc_failure(self):
        v = DTSValidator()
        r = SkillResult(
            success=False, skill_name="DTSSkill", summary="error",
            raw={"dtc_compilation": False},
        )
        vr = v.validate(r)
        assert vr.score < 60


# ---------------------------------------------------------------------------
# SecurityValidator
# ---------------------------------------------------------------------------

class TestSecurityValidator:
    def test_can_validate(self):
        v = SecurityValidator()
        r = SkillResult(success=True, skill_name="SecuritySkill", summary="ok")
        assert v.can_validate("SecuritySkill", r)

    def test_validates_clean(self):
        v = SecurityValidator()
        r = SkillResult(success=True, skill_name="SecuritySkill", summary="ok", raw=[])
        vr = v.validate(r)
        assert vr.accepted is True

    def test_critical_findings_reduces_score(self):
        v = SecurityValidator()
        findings = [
            {"cve_id": "CVE-2024-0001", "severity": "Critical"},
            {"cve_id": "CVE-2024-0002", "severity": "High"},
        ]
        r = SkillResult(success=True, skill_name="SecuritySkill", summary="ok", raw=findings)
        vr = v.validate(r)
        assert not any(c.passed for c in vr.checks if "no_critical" in c.name)
        assert vr.score < 100


# ---------------------------------------------------------------------------
# ValidationHarness
# ---------------------------------------------------------------------------

class TestValidationHarness:
    @pytest.mark.asyncio
    async def test_execute_wraps_skill_result(self):
        from titan.core.planner import Skill
        from titan.core.memory import MultiLayerMemory
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        from titan.core.knowledge_engine import KnowledgeEngine
        import tempfile

        class DummySkill(Skill):
            def can_handle(self, event_type, data):
                return True
            async def execute(self, data, memory, twin, ke):
                return {"status": "indexed", "arch": "arm", "count": 5}

        bus = LocalEventBus()
        with tempfile.TemporaryDirectory() as tmp:
            memory = MultiLayerMemory(bus, base_path=os.path.join(tmp, "mem"))
            twin = DigitalTwin(bus, base_path=os.path.join(tmp, "twin"))
            ke = KnowledgeEngine(base_path=os.path.join(tmp, "ke"))

            harness = ValidationHarness()
            result, validation = await harness.execute(
                DummySkill(), {}, memory, twin, ke,
            )

        assert result.success is True
        assert result.skill_name == "DummySkill"
        assert validation.score > 0

    @pytest.mark.asyncio
    async def test_execute_with_error(self):
        from titan.core.planner import Skill
        from titan.core.memory import MultiLayerMemory
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        from titan.core.knowledge_engine import KnowledgeEngine
        import tempfile

        class FailingSkill(Skill):
            def can_handle(self, event_type, data):
                return True
            async def execute(self, data, memory, twin, ke):
                return {"error": "something broke"}

        bus = LocalEventBus()
        with tempfile.TemporaryDirectory() as tmp:
            memory = MultiLayerMemory(bus, base_path=os.path.join(tmp, "mem"))
            twin = DigitalTwin(bus, base_path=os.path.join(tmp, "twin"))
            ke = KnowledgeEngine(base_path=os.path.join(tmp, "ke"))

            harness = ValidationHarness()
            result, validation = await harness.execute(
                FailingSkill(), {}, memory, twin, ke,
            )

        assert result.success is False

    def test_history_is_recorded(self):
        harness = ValidationHarness()
        assert harness.get_summary()["executions"] == 0
        harness.history_log.append({"skill": "X", "success": True, "score": 90, "accepted": True})
        harness.history_log.append({"skill": "Y", "success": False, "score": 30, "accepted": False})
        s = harness.get_summary()
        assert s["executions"] == 2
        assert s["accepted"] == 1
        assert s["rejected"] == 1
        assert s["avg_score"] == 60.0


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

class TestReport:
    def test_generate_report(self):
        result = SkillResult(success=True, skill_name="TestSkill", summary="ok")
        validation = ValidationResult(
            score=85.0,
            accepted=True,
            checks=[ValidationCheck(name="check1", passed=True, detail="all good")],
            reasons=["everything passed"],
            artifact_paths=["/tmp/output.bin"],
        )
        report = generate_report(result, validation)
        assert "TestSkill" in report
        assert "85.0" in report
        assert "check1" in report
        assert "/tmp/output.bin" in report


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_validation_harness_integration():
    """End-to-end: harness + real validator with mock skill output."""
    harness = ValidationHarness()

    from titan.core.planner import Skill
    from titan.core.memory import MultiLayerMemory
    from titan.core.digital_twin import DigitalTwin
    from titan.core.event_bus import LocalEventBus
    from titan.core.knowledge_engine import KnowledgeEngine
    import tempfile

    class MockBuildrootSkill(Skill):
        def can_handle(self, event_type, data):
            return True
        async def execute(self, data, memory, twin, ke):
            return {"status": "indexed", "arch": "aarch64", "toolchain_type": "external", "packages": 15}

    bus = LocalEventBus()
    with tempfile.TemporaryDirectory() as tmp:
        memory = MultiLayerMemory(bus, base_path=os.path.join(tmp, "mem"))
        twin = DigitalTwin(bus, base_path=os.path.join(tmp, "twin"))
        ke = KnowledgeEngine(base_path=os.path.join(tmp, "ke"))

        result, validation = await harness.execute(
            MockBuildrootSkill(), {}, memory, twin, ke,
        )

    assert result.success is True
    assert result.skill_name == "MockBuildrootSkill"
    assert validation.accepted is True
    assert validation.score >= 60

    report = harness.get_report(result, validation)
    assert "MockBuildrootSkill" in report
    assert str(validation.score) in report


# ---------------------------------------------------------------------------
# ErrorSignature
# ---------------------------------------------------------------------------

class TestErrorSignature:
    def test_from_raw_buildroot(self):
        sig = ErrorSignature.from_raw({"type": "buildroot", "error": "missing openssl"}, "BuildrootSkill")
        assert sig.category == "BuildrootError"
        assert "missing openssl" in sig.fingerprint

    def test_from_raw_yocto(self):
        sig = ErrorSignature.from_raw({"error": "Nothing PROVIDES python3"}, "YoctoSkill")
        assert sig.category == "YoctoError"

    def test_from_raw_empty(self):
        sig = ErrorSignature.from_raw({}, "UnknownSkill")
        assert sig.category == "GenericError"
        assert sig.fingerprint == "unknown"

    def test_hash(self):
        a = ErrorSignature(category="BuildrootError", fingerprint="missing openssl")
        b = ErrorSignature(category="BuildrootError", fingerprint="missing openssl")
        assert hash(a) == hash(b)


# ---------------------------------------------------------------------------
# ValidationDB (persistence)
# ---------------------------------------------------------------------------

class TestValidationDB:
    def test_insert_and_retrieve(self):
        from titan.validation.persistence import ValidationDB
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = ValidationDB(db_path=f"{tmp}/test.db")
            run_id = db.insert_run({
                "skill_name": "BuildrootSkill",
                "score": 85.0,
                "accepted": True,
            })
            assert run_id > 0

            run = db.get_run(run_id)
            assert run is not None
            assert run["skill_name"] == "BuildrootSkill"
            assert run["score"] == 85.0
            assert run["accepted"] is True

    def test_list_runs(self):
        from titan.validation.persistence import ValidationDB
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = ValidationDB(db_path=f"{tmp}/test.db")
            db.insert_run({"skill_name": "A", "score": 90, "accepted": True})
            db.insert_run({"skill_name": "B", "score": 50, "accepted": False})
            db.insert_run({"skill_name": "A", "score": 70, "accepted": True})

            all_runs = db.list_runs(limit=10)
            assert len(all_runs) == 3

            a_runs = db.list_runs(skill_name="A", limit=10)
            assert len(a_runs) == 2

    def test_best_and_worst(self):
        from titan.validation.persistence import ValidationDB
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = ValidationDB(db_path=f"{tmp}/test.db")
            db.insert_run({"skill_name": "S", "score": 50, "accepted": False})
            db.insert_run({"skill_name": "S", "score": 90, "accepted": True})
            db.insert_run({"skill_name": "S", "score": 70, "accepted": True})

            assert db.best_score("S") == 90.0
            assert db.worst_score("S") == 50.0

    def test_count_runs(self):
        from titan.validation.persistence import ValidationDB
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = ValidationDB(db_path=f"{tmp}/test.db")
            assert db.count_runs() == 0
            db.insert_run({"skill_name": "X", "score": 80, "accepted": True})
            assert db.count_runs() == 1
            assert db.count_runs("X") == 1
            assert db.count_runs("Y") == 0

    def test_delete_all(self):
        from titan.validation.persistence import ValidationDB
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = ValidationDB(db_path=f"{tmp}/test.db")
            db.insert_run({"skill_name": "X", "score": 80, "accepted": True})
            db.delete_all()
            assert db.count_runs() == 0


# ---------------------------------------------------------------------------
# ValidationHistory
# ---------------------------------------------------------------------------

class TestValidationHistory:
    def test_start_and_finish_run(self):
        from titan.validation.persistence import ValidationDB
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = ValidationDB(db_path=f"{tmp}/history.db")
            history = ValidationHistory(db=db)

            result = SkillResult(success=True, skill_name="BuildrootSkill", summary="indexed",
                                 raw={"arch": "arm", "status": "indexed"})
            validation = ValidationResult(score=92.0, accepted=True, checks=[])

            history.start_run("BuildrootSkill")
            run_id = history.finish_run(result, validation)

            run = db.get_run(run_id)
            assert run is not None
            assert run["skill_name"] == "BuildrootSkill"
            assert run["score"] == 92.0
            assert run["accepted"] is True

    def test_recent(self):
        from titan.validation.persistence import ValidationDB
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = ValidationDB(db_path=f"{tmp}/history.db")
            history = ValidationHistory(db=db)

            for i in range(5):
                r = SkillResult(success=True, skill_name="TestSkill", summary=f"run-{i}")
                v = ValidationResult(score=float(80 + i), accepted=True)
                history.start_run("TestSkill")
                history.finish_run(r, v)

            recent = history.recent(limit=3)
            assert len(recent) == 3

    def test_average_score(self):
        from titan.validation.persistence import ValidationDB
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = ValidationDB(db_path=f"{tmp}/history.db")
            history = ValidationHistory(db=db)

            # scores: 80, 90, 100 -> avg = 90
            for s in [80, 90, 100]:
                r = SkillResult(success=True, skill_name="AvgSkill", summary="ok")
                v = ValidationResult(score=float(s), accepted=True)
                history.start_run("AvgSkill")
                history.finish_run(r, v)

            assert history.average_score("AvgSkill") == 90.0

    def test_acceptance_rate(self):
        from titan.validation.persistence import ValidationDB
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = ValidationDB(db_path=f"{tmp}/history.db")
            history = ValidationHistory(db=db)

            for s, acc in [(80, True), (90, True), (30, False)]:
                r = SkillResult(success=True, skill_name="RateSkill", summary="ok")
                v = ValidationResult(score=float(s), accepted=acc)
                history.start_run("RateSkill")
                history.finish_run(r, v)

            rate = history.acceptance_rate("RateSkill")
            assert rate == 66.7  # 2/3 = 66.7

    def test_top_errors(self):
        from titan.validation.persistence import ValidationDB
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = ValidationDB(db_path=f"{tmp}/history.db")
            history = ValidationHistory(db=db)

            for _ in range(3):
                r = SkillResult(success=False, skill_name="ErrSkill", summary="error",
                                raw={"error": "missing openssl"})
                v = ValidationResult(score=30.0, accepted=False)
                history.start_run("ErrSkill")
                history.finish_run(r, v)

            for _ in range(1):
                r = SkillResult(success=False, skill_name="ErrSkill", summary="error",
                                raw={"error": "missing zlib"})
                v = ValidationResult(score=40.0, accepted=False)
                history.start_run("ErrSkill")
                history.finish_run(r, v)

            top = history.top_errors(limit=5)
            assert len(top) >= 2
            assert top[0]["fingerprint"] == "missing openssl"
            assert top[0]["count"] == 3


# ── End of tests ──────────────────────────────────────────────────────
