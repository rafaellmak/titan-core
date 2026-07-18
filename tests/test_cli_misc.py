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
def dmesg_critical(tmp_path):
    p = tmp_path / "dmesg.log"
    p.write_text(
        "[1234.56] Out of memory: Killed process 1234 (gcc) total-vm:2GB\n"
        "[1236.00] kernel: BUG: unable to handle kernel NULL pointer dereference at 00000040\n"
    )
    return p


@pytest.fixture
def dmesg_clean(tmp_path):
    p = tmp_path / "dmesg.log"
    p.write_text("[1234.56] usb 1-1: new high-speed USB device number 5 using ehci-pci\n")
    return p


@pytest.fixture
def dts_with_issue(tmp_path):
    p = tmp_path / "board.dts"
    p.write_text(
        "/dts-v1/;\n"
        "/ {\n"
        "    model = \"Test\";\n"
        "    soc { uart0: serial@1 { pinctrl-0 = <&missing_pins>; } };\n"
        "};\n"
    )
    return p


class TestHardwareExitCodes:
    def test_dts_with_error_exit_1(self, dts_with_issue):
        r = _run(["hardware", str(dts_with_issue)])
        assert r.returncode == 1
        assert "missing" in r.stdout.lower() or "LabelRef" in r.stdout or "Erro" in r.stdout or "Error" in r.stdout

    def test_missing_dts_exit_1(self):
        r = _run(["hardware", "/tmp/this-dts-does-not-exist.dts"])
        assert r.returncode == 1

    def test_outside_workspace_exit_1(self, dts_with_issue, tmp_path):
        r = _run(["hardware", str(dts_with_issue)], cwd=tmp_path)
        assert r.returncode == 1
        assert "Nenhum workspace" in r.stdout


class TestLLMAssistStdin:
    def test_prompt_via_stdin(self):
        r = subprocess.run(
            "echo 'diagnosticar problema no openssl' | titan llm-assist",
            shell=True, cwd=WORKSPACE, capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(WORKSPACE)},
        )
        assert r.returncode in (0, 1)
        assert "titan" in r.stdout.lower()

    def test_no_prompt_at_all(self):
        r = subprocess.run(
            "echo -n '' | titan llm-assist",
            shell=True, cwd=WORKSPACE, capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(WORKSPACE)},
        )
        assert r.returncode == 1
        assert "requer um prompt" in r.stdout

    def test_prompt_as_arg(self):
        r = _run(["llm-assist", "fix build error"])
        assert r.returncode in (0, 1)
        assert "titan" in r.stdout.lower()
