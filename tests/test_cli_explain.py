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


def _indexed():
    _run(["recipe", "index"])


class TestExplain:
    def test_indexed_recipe_explains(self):
        _indexed()
        r = _run(["explain", "openssl"])
        assert r.returncode == 0
        assert "openssl" in r.stdout
        assert "Caminho" in r.stdout
        assert "Por que" in r.stdout

    def test_unknown_recipe_returns_1(self):
        _indexed()
        r = _run(["explain", "zzz-nonexistent"])
        assert r.returncode == 1
        assert "não indexado" in r.stdout

    def test_no_target_returns_error(self):
        r = _run(["explain"])
        assert r.returncode in (1, 2)

    def test_outside_workspace_returns_1(self, tmp_path):
        r = _run(["explain", "openssl"], cwd=tmp_path)
        assert r.returncode == 1
        assert "Nenhum workspace" in r.stdout

    def test_with_global_workspace_flag(self, tmp_path):
        _indexed()
        r = _run(["--workspace", str(WORKSPACE), "explain", "openssl"], cwd=tmp_path)
        assert r.returncode == 0
        assert "openssl" in r.stdout
