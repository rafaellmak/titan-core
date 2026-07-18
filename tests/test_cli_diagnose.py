import subprocess
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


@pytest.fixture
def tmp_log(tmp_path):
    def _make(content: str) -> Path:
        p = tmp_path / "test.log"
        p.write_text(content)
        return p
    return _make


class TestDiagnoseYOC002:
    def test_task_with_id(self, tmp_log):
        log = tmp_log(
            "ERROR: Task 6984 (/path/to/recipe.bb:do_compile) failed with exit code '1'\n"
        )
        r = _run(["diagnose", str(log)])
        assert r.returncode == 1
        assert "YOC-002" in r.stdout
        assert "do_compile" in r.stdout
        assert "exit code 1" in r.stdout
        assert "id 6984" in r.stdout

    def test_task_without_id(self, tmp_log):
        log = tmp_log(
            "ERROR: Task (/path/to/recipe.bb:do_fetch) failed with exit code '127'\n"
        )
        r = _run(["diagnose", str(log)])
        assert r.returncode == 1
        assert "YOC-002-alt" in r.stdout

    def test_yoc001_nothing_provides(self, tmp_log):
        log = tmp_log("ERROR: Nothing PROVIDES 'foo-bar'\n")
        r = _run(["diagnose", str(log)])
        assert r.returncode == 1
        assert "YOC-001" in r.stdout
        assert "foo-bar" in r.stdout

    def test_yoc003_fetch_failed(self, tmp_log):
        log = tmp_log("ERROR: Fetcher failure: Fetch command failed for url 'https://x.example.com/x.tar.gz'\n")
        r = _run(["diagnose", str(log)])
        assert r.returncode == 1
        assert "YOC-003" in r.stdout
        assert "x.tar.gz" in r.stdout


class TestDiagnoseCleanLog:
    def test_no_findings_returns_zero(self, tmp_log):
        log = tmp_log("WARNING: nothing to do, exiting\n")
        r = _run(["diagnose", str(log)])
        assert r.returncode == 0
        assert "Nenhum problema" in r.stdout

    def test_qa_warning_returns_zero(self, tmp_log):
        log = tmp_log("WARNING: some-context: QA Issue: zlib rdepends on openssl, but it isn't a build-time dependency?\n")
        r = _run(["diagnose", str(log)])
        assert r.returncode == 0
        assert "YOC-004" in r.stdout


class TestDiagnoseErrors:
    def test_missing_log_file(self):
        r = _run(["diagnose", "/tmp/this-does-not-exist-12345.log"])
        assert r.returncode == 1
        assert "não encontrado" in r.stdout

    def test_outside_workspace(self, tmp_path):
        log = tmp_path / "x.log"
        log.write_text("ERROR: Task 1 (foo.bb:do_x) failed with exit code '1'\n")
        r = _run(["diagnose", str(log)], cwd=tmp_path)
        assert r.returncode == 1
        assert "Nenhum workspace" in r.stdout
