import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from titan.autofix.engine import (
    AutoFixEngine,
    _is_balanced_braces,
    _is_valid_bb,
)
from titan.workspace.models import YoctoWorkspace


SAMPLE_YOC004_LOG = """
WARNING: openssl-3.0.8-r0 do_package_qa: QA Issue: openssl rdepends on zlib, but it isn't a build-time dependency?
"""


def test_is_balanced_braces_valid():
    assert _is_balanced_braces('VAR = "foo"') is True
    assert _is_balanced_braces('do_compile() { echo hi; }') is True
    assert _is_balanced_braces('') is True
    assert _is_balanced_braces('RDEPENDS:${PN} += "zlib"') is True
    assert _is_balanced_braces('SUMMARY = "Test {with braces}"') is True


def test_is_balanced_braces_invalid():
    assert _is_balanced_braces('do_compile() { echo hi;') is False
    assert _is_balanced_braces('VAR = "foo') is False
    assert _is_balanced_braces('}extra') is False
    assert _is_balanced_braces('do_compile() {} }') is False


def test_yoc004_regex_uses_pn_not_task_name():
    """The autofix should target the recipe by its PN ('openssl'), not by
    the warning context line ('openssl-3.0.8-r0 do_package_qa')."""
    from titan.diagnostics.rules import YOCTO_RULES
    rule = next(r for r in YOCTO_RULES if r.id == "YOC-004")
    m = rule.pattern.search(SAMPLE_YOC004_LOG)
    assert m is not None
    assert m.group("pn") == "openssl"
    assert m.group("dep") == "zlib"
    # The 'context' group is the noisy task-line; it must NOT be used as
    # the recipe name. This is what caused the original bug.
    assert "openssl" not in m.group("context") or "do_package_qa" in m.group("context")


def test_autofix_modifies_correct_recipe(tmp_path, capsys):
    """End-to-end: run autofix on a YOC-004 log and verify the right
    .bb file gets the RDEPENDS line, with the right PN."""
    workspace_root = tmp_path
    layer = workspace_root / "meta-test"
    recipes_dir = layer / "recipes-connectivity" / "openssl"
    recipes_dir.mkdir(parents=True)
    bb = recipes_dir / "openssl_3.0.bb"
    bb.write_text('SUMMARY = "OpenSSL"\nPV = "3.0.8"\n')

    workspace = YoctoWorkspace(
        root_dir=workspace_root,
        build_dir=workspace_root / "build",
        init_script=workspace_root / "oe-init-build-env",
        machine="qemux86-64",
        distro="poky",
        layers=[layer],
    )
    workspace._fix_type = property(lambda self: "yocto")

    from titan.workspace.models import Workspace
    Workspace.type = property(lambda self: getattr(self, "_fix_type", "yocto"))

    engine = AutoFixEngine(workspace)
    assert engine.db is not None, "RecipeDB should be created for yocto workspace"

    # Indexa para que openssl entre no DB
    engine.db.upsert_recipe({
        "pn": "openssl",
        "pv": "3.0.8",
        "file_path": str(bb),
        "depends": "",
        "rdepends": "",
        "license": "",
        "src_uri": "",
        "inherits": "",
    })

    log = workspace_root / "build.log"
    log.write_text(SAMPLE_YOC004_LOG)

    with patch.object(AutoFixEngine, "_has_bitbake", return_value=False):
        engine.run_fix(log)

    out = capsys.readouterr().out
    content = bb.read_text()

    assert "openssl" in out, "should mention the right recipe name"
    assert "openssl-3.0.8-r0 do_package_qa" not in out, "must NOT use the task-line as recipe"
    assert 'RDEPENDS:${PN} += "zlib"' in content
    assert content.startswith('SUMMARY = "OpenSSL"'), "must preserve original content"


def test_autofix_skips_unknown_recipe(tmp_path, capsys):
    """If the recipe is not in the DB, autofix should skip with a clear
    message and not modify anything."""
    workspace_root = tmp_path
    layer = workspace_root / "meta-test"
    layer.mkdir()
    workspace = YoctoWorkspace(
        root_dir=workspace_root,
        build_dir=workspace_root / "build",
        init_script=workspace_root / "oe-init-build-env",
        machine="qemux86-64",
        distro="poky",
        layers=[layer],
    )
    from titan.workspace.models import Workspace
    Workspace.type = property(lambda self: "yocto")

    engine = AutoFixEngine(workspace)
    log = workspace_root / "build.log"
    log.write_text(
        "WARNING: nothere-1.0 do_package_qa: QA Issue: nothere rdepends on foo, "
        "but it isn't a build-time dependency?\n"
    )

    with patch.object(AutoFixEngine, "_has_bitbake", return_value=False):
        engine.run_fix(log)

    out = capsys.readouterr().out
    assert "pulando" in out or "não indexado" in out


def test_validate_mutation_detects_corrupted_file(tmp_path):
    """If a mutation produces an invalid file, validate_mutation should
    return False and the caller should rollback."""
    workspace_root = tmp_path
    layer = workspace_root / "meta-test"
    layer.mkdir()
    workspace = YoctoWorkspace(
        root_dir=workspace_root,
        build_dir=workspace_root / "build",
        init_script=workspace_root / "oe-init-build-env",
        machine="qemux86-64",
        distro="poky",
        layers=[layer],
    )
    from titan.workspace.models import Workspace
    Workspace.type = property(lambda self: "yocto")

    engine = AutoFixEngine(workspace)

    good = workspace_root / "good.bb"
    good.write_text('SUMMARY = "ok"\n')
    bad = workspace_root / "bad.bb"
    bad.write_text('do_compile() { broken')  # unbalanced

    assert engine.validate_mutation([good]) is True
    assert engine.validate_mutation([bad]) is False
    assert engine.validate_mutation([good, bad]) is False
    assert engine.validate_mutation([]) is True


# ── v20: Operational Intelligence tests ───────────────────────────────────


def test_autofix_engine_returns_structured_result(tmp_path, capsys):
    """AutoFixEngine.run_fix() must return a structured dict with entities."""
    from titan.workspace.models import YoctoWorkspace, Workspace
    from unittest.mock import patch

    workspace_root = tmp_path
    layer = workspace_root / "meta-test"
    recipes_dir = layer / "recipes-connectivity" / "openssl"
    recipes_dir.mkdir(parents=True)
    bb = recipes_dir / "openssl_3.0.bb"
    bb.write_text('SUMMARY = "OpenSSL"\n')

    workspace = YoctoWorkspace(
        root_dir=workspace_root, build_dir=workspace_root / "build",
        init_script=workspace_root / "oe-init-build-env",
        machine="qemux86-64", distro="poky", layers=[layer],
    )
    Workspace.type = property(lambda self: "yocto")

    engine = AutoFixEngine(workspace)
    engine.db.upsert_recipe({
        "pn": "openssl", "pv": "3.0.8", "file_path": str(bb),
        "depends": "", "rdepends": "", "license": "",
        "src_uri": "", "inherits": "",
    })

    log = workspace_root / "build.log"
    log.write_text(SAMPLE_YOC004_LOG)

    with patch.object(AutoFixEngine, "_has_bitbake", return_value=False):
        result = engine.run_fix(log)

    assert isinstance(result, dict)
    assert "fixed" in result
    assert "entities" in result
    assert "root_cause" in result
    assert result["fixed"] is True
    assert "recipe:openssl" in result["entities"]
    assert "package:zlib" in result["entities"]


def test_autofix_engine_returns_result_no_fixable(tmp_path, capsys):
    """Even when nothing is fixable, run_fix returns a dict."""
    from titan.workspace.models import YoctoWorkspace, Workspace
    from unittest.mock import patch

    workspace_root = tmp_path
    workspace = YoctoWorkspace(
        root_dir=workspace_root, build_dir=workspace_root / "build",
        init_script=workspace_root / "oe-init-build-env",
        machine="qemux86-64", distro="poky", layers=[],
    )
    Workspace.type = property(lambda self: "yocto")

    engine = AutoFixEngine(workspace)
    log = workspace_root / "build.log"
    log.write_text("DEBUG: Nothing to see here\n")

    result = engine.run_fix(log)
    assert isinstance(result, dict)
    assert result["fixed"] is False


def test_autofix_skill_extract_entity():
    """AutoFixSkill._extract_entity picks the first recipe: or
    buildroot_package: entity from the list."""
    from titan.skills.autofix_skill import AutoFixSkill
    skill = AutoFixSkill()
    entities = ["package:zlib", "recipe:openssl"]
    assert skill._extract_entity(entities) == "recipe:openssl"

    entities = ["buildroot_package:busybox"]
    assert skill._extract_entity(entities) == "buildroot_package:busybox"

    entities = []
    assert skill._extract_entity(entities) is None


def test_autofix_skill_integration_twin(tmp_path):
    """AutoFixSkill.execute() with a populated Twin should enrich
    the result with impact and snapshot data."""
    import asyncio
    import os
    from pathlib import Path
    from unittest.mock import patch, MagicMock
    from titan.core.digital_twin import DigitalTwin
    from titan.core.event_bus import LocalEventBus
    from titan.skills.autofix_skill import AutoFixSkill
    from titan.workspace.models import YoctoWorkspace, Workspace

    twin_base = tmp_path / "twin"
    twin = DigitalTwin(LocalEventBus(), base_path=str(twin_base))
    twin.emit_event("buildroot_workspace_scanned", {"arch": "arm"})
    twin.emit_event("buildroot_package_added", {"package": "openssl"})
    twin.emit_event("buildroot_package_added", {"package": "curl"})
    twin.emit_event("buildroot_package_dependency",
                    {"package": "curl", "depends_on": "openssl"})

    memory = MagicMock()
    memory.get_state.return_value = {"type": "yocto", "root_dir": str(tmp_path)}

    skill = AutoFixSkill()

    with patch("titan.skills.autofix_skill.AutoFixEngine") as MockEngine:
        instance = MockEngine.return_value
        instance.run_fix.return_value = {
            "fixed": True,
            "action": 'RDEPENDS:${PN} += "zlib"',
            "entities": ["buildroot_package:openssl", "buildroot_package:zlib"],
            "rule_ids": ["YOC-004"],
            "root_cause": "Missing runtime dependency",
            "mutated_files": [str(tmp_path / "openssl_3.0.bb")],
        }

        knowledge_engine = MagicMock()
        coro = skill.execute(
            {"log_path": "build.log"},
            memory, twin, knowledge_engine,
        )
        result = asyncio.run(coro)

    assert result["fixed"] is True
    enrichment = result.get("enrichment", {})
    assert enrichment["impact"] is not None
    assert enrichment["impact"]["entity"] == "buildroot_package:openssl"
    assert enrichment["impact"]["risk_level"] == "MEDIUM"
    assert enrichment["snapshot_before"] is not None
    assert enrichment["snapshot_after"] is not None
    assert enrichment["diff"] is not None
    assert "summary" in enrichment["diff"]
    assert enrichment["risk_assessment"]["risk_level"] == "MEDIUM"


if __name__ == "__main__":
    test_is_balanced_braces_valid()
    test_is_balanced_braces_invalid()
    test_yoc004_regex_uses_pn_not_task_name()
    test_autofix_modifies_correct_recipe(None)
    test_autofix_skips_unknown_recipe(None)
    test_validate_mutation_detects_corrupted_file(None)
    test_autofix_engine_returns_structured_result(None)
    test_autofix_engine_returns_result_no_fixable(None)
    test_autofix_skill_extract_entity()
    print("OK: 9 testes do autofix")
