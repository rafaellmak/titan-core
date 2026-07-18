import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from titan.recipes.db import RecipeDB
from titan.security.cve_monitor import CVEMonitor, _OFFLINE_STUB_DB
from titan.workspace.models import YoctoWorkspace


def _setup(tmp_path: Path, recipes=("openssl", "zlib", "busybox")):
    layer = tmp_path / "meta-test"
    layer.mkdir()
    workspace = YoctoWorkspace(
        root_dir=tmp_path,
        build_dir=tmp_path / "build",
        init_script=tmp_path / "oe-init-build-env",
        machine="qemux86-64",
        distro="poky",
        layers=[layer],
    )
    db = RecipeDB(workspace.root_dir)
    for pn in recipes:
        recipes_dir = layer / f"recipes-{pn}"
        recipes_dir.mkdir()
        (recipes_dir / f"{pn}_1.0.bb").write_text(f'SUMMARY = "{pn}"\n')
        db.upsert_recipe({
            "pn": pn, "pv": "1.0", "file_path": str(recipes_dir / f"{pn}_1.0.bb"),
            "depends": "", "rdepends": "", "license": "", "src_uri": "", "inherits": "",
        })
    return workspace, db


def test_offline_default_is_honest_no_fake_data(tmp_path, capsys):
    """Default mode (no --online, no --stub) must NOT show fake data."""
    workspace, db = _setup(tmp_path, recipes=("openssl",))
    monitor = CVEMonitor(db, workspace=workspace)
    findings = monitor.scan_workspace()
    assert findings == [], f"expected no findings in default mode, got {findings}"
    out = capsys.readouterr().out
    assert "OFFLINE STUB" not in out
    assert "Modo offline sem stub" in out or "Sem fontes CVE" in out


def test_stub_returns_real_cve_ids(tmp_path):
    workspace, db = _setup(tmp_path, recipes=("openssl", "zlib", "busybox"))
    monitor = CVEMonitor(db, workspace=workspace)
    findings = monitor.scan_workspace(include_stub=True)
    cve_ids = {f["cve_id"] for f in findings}
    assert "CVE-2022-3602" in cve_ids
    assert "CVE-2022-37434" in cve_ids
    assert "CVE-2023-4911" not in cve_ids
    for f in findings:
        assert f["source"] == "offline-stub"


def test_stub_no_data_for_unknown_packages(tmp_path):
    workspace, db = _setup(tmp_path, recipes=("example",))
    monitor = CVEMonitor(db, workspace=workspace)
    findings = monitor.scan_workspace(include_stub=True)
    assert findings == []


def test_severity_filter(tmp_path):
    workspace, db = _setup(tmp_path, recipes=("openssl", "zlib"))
    monitor = CVEMonitor(db, workspace=workspace)
    all_findings = monitor.scan_workspace(include_stub=True)
    high_only = [f for f in all_findings if f["severity"] == "High"]
    assert len(high_only) >= 2
    critical = [f for f in all_findings if f["severity"] == "Critical"]
    assert len(critical) >= 1


def test_stub_db_has_real_cves_not_fake():
    """The stub DB should contain real CVE IDs, not placeholders."""
    for pn, cves in _OFFLINE_STUB_DB.items():
        for cve in cves:
            cve_id = cve.get('cve_id', cve.get('id', ''))
            assert cve_id.startswith("CVE-20"), f"bad CVE id: {cve_id}"
            assert cve["severity"] in ("Low", "Medium", "High", "Critical")
            assert len(cve["description"]) > 20, "description too short"


def test_report_shows_source_label(tmp_path, capsys):
    workspace, db = _setup(tmp_path, recipes=("openssl",))
    monitor = CVEMonitor(db, workspace=workspace)
    findings = monitor.scan_workspace(include_stub=True)
    monitor.generate_report(findings)
    out = capsys.readouterr().out
    assert "OFFLINE STUB" in out


def test_report_clean_when_no_findings(tmp_path, capsys):
    workspace, db = _setup(tmp_path, recipes=("example",))
    monitor = CVEMonitor(db, workspace=workspace)
    findings = monitor.scan_workspace(include_stub=True)
    monitor.generate_report(findings)
    out = capsys.readouterr().out
    assert "Nenhuma vulnerabilidade" in out


def test_cve_check_source_when_summary_file_exists(tmp_path, capsys):
    """If build/tmp/log/cve/cve-summary.json exists, use it as primary source."""
    workspace, db = _setup(tmp_path, recipes=("openssl",))
    cve_dir = workspace.build_dir / "tmp" / "log" / "cve"
    cve_dir.mkdir(parents=True)
    cve_summary = {
        "package": [
            {
                "name": "openssl", "version": "3.0.8",
                "issue": [
                    {"id": "CVE-2024-REAL-001", "status": "Unpatched", "severity": "High"},
                ],
            },
        ],
    }
    (cve_dir / "cve-summary.json").write_text(json.dumps(cve_summary))

    monitor = CVEMonitor(db, workspace=workspace)
    findings = monitor.scan_workspace()
    assert any(f["cve_id"] == "CVE-2024-REAL-001" and f["source"] == "cve-check" for f in findings)
    out = capsys.readouterr().out
    assert "manifesto de segurança" in out


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "/home/ubunote/projects/titan-core-v12")
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        test_offline_default_is_honest_no_fake_data(p, type("X", (), {"readouterr": lambda self: type("Y", (), {"out": ""})()})())
    print("OK: tests would need pytest; see file for full suite")
