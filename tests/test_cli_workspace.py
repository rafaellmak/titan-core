import subprocess
import shutil
import os
from pathlib import Path
import pytest

WORKSPACE = Path("/home/ubunote/projects/titan-core-v12")


def _run(args, cwd=None, **kwargs):
    return subprocess.run(
        ["titan"] + args,
        cwd=cwd or WORKSPACE, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(WORKSPACE)},
        **kwargs,
    )


@pytest.fixture(autouse=True)
def clean_titan():
    for pattern in (".titan_digital_twin", ".titan_cache", ".titan_recipe_db", ".titan"):
        p = WORKSPACE / pattern
        if p.exists():
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink()
    cache = Path.home() / ".cache" / "titan"
    if cache.exists():
        shutil.rmtree(cache, ignore_errors=True)
    yield
    for pattern in (".titan_digital_twin", ".titan_cache", ".titan_recipe_db", ".titan"):
        p = WORKSPACE / pattern
        if p.exists():
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink()


class TestGlobalWorkspaceFlag:
    def test_long_flag_detects_workspace(self):
        r = _run(["--workspace", str(WORKSPACE), "info"])
        assert r.returncode == 0
        assert "YOCTO" in r.stdout

    def test_short_flag_works(self):
        r = _run(["-w", str(WORKSPACE), "info"])
        assert r.returncode == 0
        assert "YOCTO" in r.stdout

    def test_default_uses_cwd(self):
        r = _run(["info"])
        assert r.returncode == 0
        assert "YOCTO" in r.stdout

    def test_invalid_workspace_errors(self, tmp_path):
        r = _run(["--workspace", "/tmp", "info"])
        assert r.returncode == 1
        assert "Nenhum workspace" in r.stdout
        assert "/tmp" in r.stdout

    def test_workspace_with_recipe_subcommand(self):
        r = _run(["-w", str(WORKSPACE), "recipe", "index"])
        assert r.returncode == 0
        assert "Indexação concluída" in r.stdout

        r = _run(["-w", str(WORKSPACE), "recipe", "show", "openssl"])
        assert r.returncode == 0
        assert "openssl" in r.stdout

    def test_workspace_with_action_subcommand(self):
        backup = (WORKSPACE / "build" / "conf" / "local.conf").read_text()
        try:
            r = _run(["-w", str(WORKSPACE), "action", "append-conf", 'TEST_W_FLAG = "y"'])
            assert r.returncode == 0
            assert "sucesso" in r.stdout
            local = (WORKSPACE / "build" / "conf" / "local.conf").read_text()
            assert 'TEST_W_FLAG = "y"' in local
        finally:
            (WORKSPACE / "build" / "conf" / "local.conf").write_text(backup)
