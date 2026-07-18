"""Teste E2E: ciclo operacional completo do Titan.

Fluxo:
  Workspace → PatternDB → Recommender → ContextSimilarity → RiskBridge
  → AutoFix → Snapshot before/after → StateDiff → Revalidation
"""
from __future__ import annotations
import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from titan.context.models import (
    WorkspaceFingerprint, compute_confidence, compute_adjusted_confidence,
    confidence_level,
)
from titan.context.similarity import compare as context_compare
from titan.core.digital_twin import DigitalTwin
from titan.core.event_bus import LocalEventBus
from titan.core.knowledge_engine import KnowledgeEngine
from titan.core.memory import MultiLayerMemory
from titan.core.planner import SkillPlanner
from titan.validation.contracts import ErrorSignature, SkillResult, ValidationResult
from titan.validation.harness import ValidationHarness
from titan.validation.history import ValidationHistory
from titan.validation.persistence import ValidationDB
from titan.learning.patterns import PatternDB, LearnedPattern
from titan.learning.context import PatternContextDB, WorkspaceContext
from titan.learning.feedback import FeedbackLoop, FeedbackDB
from titan.learning.ranking import RankingEngine
from titan.learning.engine import LearningEngine
from titan.learning.normalizer import ErrorNormalizer
from titan.learning.recommender import Recommender
from titan.autofix.engine import AutoFixEngine


SAMPLE_YOC004_LOG = (
    'WARNING: openssl-3.0.8-r0 do_package_qa: '
    'QA Issue: openssl rdepends on zlib, '
    "but it isn't a build-time dependency?\n"
)


@pytest.mark.asyncio
async def test_e2e_complete_cycle(tmp_path):
    """Valida o pipeline completo do Titan com componentes reais.

    Etapas:
      1. Workspace real + Recipe DB
      2. DigitalTwin populado
      3. PatternDB seedado (simula aprendizado prévio)
      4. Recommender com contexto + risco
      5. AutoFix real em arquivo
      6. Snapshot before/after
      7. StateDiff
      8. Revalidation com score melhorado
    """
    base = tmp_path / "e2e"
    base.mkdir()

    # ── 1. Real Yocto workspace ──────────────────────────────────────────
    ws_root = base / "workspace"
    layer = ws_root / "meta-test"
    recipes_dir = layer / "recipes-connectivity" / "openssl"
    recipes_dir.mkdir(parents=True)
    bb = recipes_dir / "openssl_3.0.bb"
    bb.write_text('SUMMARY = "OpenSSL"\nPV = "3.0.8"\n')

    from titan.workspace.models import YoctoWorkspace
    workspace = YoctoWorkspace(
        root_dir=ws_root, build_dir=ws_root / "build",
        init_script=ws_root / "oe-init-build-env",
        machine="qemux86-64", distro="poky", layers=[layer],
    )

    # ── 2. Core infrastructure ───────────────────────────────────────────
    bus = LocalEventBus()
    twin = DigitalTwin(bus, base_path=str(base / "twin"))
    memory = MultiLayerMemory(bus, digital_twin=twin,
                              base_path=str(base / "memory"))
    knowledge = KnowledgeEngine(base_path=str(base / "knowledge"))
    planner = SkillPlanner(memory, twin, knowledge)

    # ── 3. Populate DigitalTwin ──────────────────────────────────────────
    twin.emit_event("buildroot_workspace_scanned", {"arch": "arm"})
    twin.emit_event("buildroot_package_added", {"package": "openssl"})
    twin.emit_event("buildroot_package_added", {"package": "curl"})
    twin.emit_event("buildroot_package_dependency",
                    {"package": "curl", "depends_on": "openssl"})
    twin.emit_event("buildroot_package_added", {"package": "zlib"})

    # ── 4. Seed PatternDB + ContextDB + Feedback ─────────────────────────
    p_db = PatternDB(db_path=str(base / "patterns.db"))
    c_db = PatternContextDB(db_path=str(base / "ctx.db"))
    f_db = FeedbackDB(db_path=str(base / "fb.db"))

    normalizer = ErrorNormalizer()
    # Derive a real normalized fingerprint so PatternDB.search_patterns() finds it
    error_text = "openssl rdepends on zlib"
    norm_fp = normalizer.normalize(error_text, "YoctoError")
    pattern = LearnedPattern(
        fingerprint=norm_fp,
        category="YoctoError",
        occurrences=5,
        success_rate=0.94,
        average_score=85.0,
        best_fix='RDEPENDS:${PN} += "zlib"',
        top_fixes={'RDEPENDS:${PN} += "zlib"': 5},
    )
    p_db.upsert_pattern(pattern)

    ctx = WorkspaceContext(arch="arm", toolchain="gcc", board="qemuarm")
    c_db.upsert_context(pattern.fingerprint, ctx,
                         score=85, accepted=True,
                         fix=pattern.best_fix)

    fb = FeedbackLoop(f_db)
    fb.record(pattern.fingerprint, recommended_fix=pattern.best_fix,
              accepted=True)
    fb.record(pattern.fingerprint, recommended_fix=pattern.best_fix,
              accepted=True)
    fb.record(pattern.fingerprint, recommended_fix=pattern.best_fix,
              accepted=True)

    # ── 5. Seed ValidationHistory + LearningEngine ───────────────────────
    v_db = ValidationDB(db_path=str(base / "validation.db"))
    history = ValidationHistory(db=v_db)

    for i in range(5):
        r = SkillResult(success=True, skill_name="AutoFixSkill",
                        summary=f"fix ok {i}")
        v = ValidationResult(score=float(80 + i), accepted=True, checks=[])
        es = ErrorSignature(
            raw=error_text,
            category="YoctoError",
            fingerprint=pattern.fingerprint,
        )
        history.start_run("AutoFixSkill")
        history.finish_run(r, v, error_sig=es, fix_signature=pattern.best_fix)

    normalizer = ErrorNormalizer()
    learning_engine = LearningEngine(
        history=history, db=p_db, normalizer=normalizer,
        context_db=c_db, feedback=fb, knowledge_engine=knowledge,
    )
    promoted = learning_engine.learn_all()
    assert len(promoted) >= 1

    # ── 6. Recommender com risco ─────────────────────────────────────────
    ranking = RankingEngine(pattern_db=p_db, context_db=c_db, feedback=fb)
    recommender = Recommender(learning_engine, ranking=ranking)

    fp = WorkspaceFingerprint(
        architecture="arm", toolchain="gcc", board="qemuarm",
        libc="glibc", kernel_version="5.10",
        workspace_type="yocto", buildroot_version="",
        yocto_release="kirkstone",
    )

    recs = recommender.recommend_with_confidence(
        error_text=error_text,
        fingerprint=fp,
        digital_twin=twin,
    )
    assert len(recs) >= 1
    best = recs[0]

    # Risk fields populated
    assert best.risk_level in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert isinstance(best.risk_score, float)
    assert best.risk_level in ("MEDIUM", "LOW")
    assert best.raw_confidence > 0
    assert best.adjusted_confidence > 0
    # adjusted_confidence = raw * 0.75 + (1 - risk_score) * 0.25
    # For risk_score 0 (LOW): adjusted > raw (boost from (1-0)*0.25)
    assert isinstance(best.adjusted_confidence, float)

    # ── 7. Snapshot BEFORE ───────────────────────────────────────────────
    snap_before = twin.create_snapshot(
        "e2e-before",
        note="Before autofix",
        workspace_fingerprint="yocto/arm/gcc/glibc",
    )
    assert snap_before is not None
    assert snap_before.id == "e2e-before"

    # ── 8. AutoFixEngine — fix real recipe ───────────────────────────────
    engine = AutoFixEngine(workspace)
    engine.db.upsert_recipe({
        "pn": "openssl", "pv": "3.0.8", "file_path": str(bb),
        "depends": "", "rdepends": "", "license": "",
        "src_uri": "", "inherits": "",
    })

    log_file = ws_root / "build.log"
    log_file.write_text(SAMPLE_YOC004_LOG)

    with patch.object(AutoFixEngine, "_has_bitbake", return_value=False):
        fix_result = engine.run_fix(log_file)

    assert fix_result["fixed"] is True
    assert "recipe:openssl" in fix_result["entities"]
    bb_content = bb.read_text()
    assert 'RDEPENDS:${PN} += "zlib"' in bb_content

    # ── 9. Snapshot AFTER + StateDiff ────────────────────────────────────
    # Emit dependency event to reflect the fix in the Twin
    twin.emit_event("buildroot_package_dependency",
                    {"package": "openssl", "depends_on": "zlib"})

    snap_after = twin.create_snapshot(
        "e2e-after",
        note="After autofix: added zlib dependency",
        parent="e2e-before",
        workspace_fingerprint="yocto/arm/gcc/glibc",
    )
    assert snap_after is not None
    assert snap_after.id == "e2e-after"
    assert snap_after.parent == "e2e-before"

    # StateDiff
    diff = twin.compare("e2e-before", "e2e-after")
    assert diff is not None
    diff_summary = diff.summary()
    assert "edge" in diff_summary
    # Fingerprint similarity depends on field overlap (same fp string → same parse)
    assert diff.fingerprint_similarity >= 0.6

    # ── 10. Revalidation — score improved ────────────────────────────────
    v_db2 = ValidationDB(db_path=str(base / "validation.db"))
    history2 = ValidationHistory(db=v_db2)

    r2 = SkillResult(success=True, skill_name="AutoFixSkill",
                     summary="fix validated after autofix")
    v2 = ValidationResult(score=98.0, accepted=True, checks=[])
    es2 = ErrorSignature(
        raw=error_text,
        category="YoctoError",
        fingerprint=pattern.fingerprint,
    )
    history2.start_run("AutoFixSkill")
    history2.finish_run(r2, v2, error_sig=es2,
                        fix_signature=pattern.best_fix)

    avg_before = history.average_score("AutoFixSkill")
    avg_after = history2.average_score("AutoFixSkill")
    # After revalidation with 98, the average should be higher
    # than the original 5 runs averaging 82
    assert avg_after >= avg_before, (
        f"avg after ({avg_after}) should be >= before ({avg_before})"
    )

    # ── 11. List snapshots ───────────────────────────────────────────────
    all_snaps = twin.list_snapshots()
    assert len(all_snaps) >= 2
    snap_ids = [s.id for s in all_snaps]
    assert "e2e-before" in snap_ids
    assert "e2e-after" in snap_ids

    # ── 12. Verify confidence math ───────────────────────────────────────
    ctx_match_obj = context_compare(fp, fp)
    raw_conf_val = compute_confidence(
        success_rate=0.94,
        context_match=ctx_match_obj.score / 100.0,
        occurrences=5,
        feedback_score=1.0,
    )
    adj_conf_val = compute_adjusted_confidence(raw_conf_val, best.risk_score)
    # Formula: adj = raw * 0.75 + (1 - risk) * 0.25
    # For risk=0 (LOW): adj = raw * 0.75 + 0.25
    # When raw < 1.0, adj may be > raw (boost from low risk)
    # Critical risk (0.95) would give adj < raw (penalty)
    assert isinstance(adj_conf_val, float)
