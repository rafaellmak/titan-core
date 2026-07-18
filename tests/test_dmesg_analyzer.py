import os
import tempfile
from titan.runtime.dmesg_analyzer import DmesgAnalyzer


SAMPLE_DMESG = """
[    0.000000] Linux version 5.15.0-test
[    0.234567] Hardware name: Generic PC, BIOS 1.0
[    3.111111] BUG: unable to handle kernel NULL pointer dereference at 0000000000000018
[    3.111444] Oops: 0000 [#1] SMP
[    3.222222] Out of memory: Killed process 1234 (oom_test) total-vm:2097152kB
[    3.333333] oom-kill:constraint=CONSTRAINT_MEMCG,task=test,pid=1234,uid=0
[    4.333333] watchdog: BUG: soft lockup - CPU#0 stuck for 23s! [kworker/u4:0:45]
[    5.444444] NMI watchdog: Watchdog detected hard LOCKUP on cpu 2
[    6.555555] rcu: INFO: rcu_sched detected stalls on CPUs/tasks: { 0-... } 0:.(0 ticks this GP) idle=xyz/1/0
[    7.666666] segfault at 7f8a12340000 ip 00007f8a12340050 sp 00007fff12345678 error 4 in myapp
[    8.777777] EXT4-fs error (device sda1): ext4_lookup:1448: inode #12345
[    9.888888] Buffer I/O error on device sdb1, logical block 12345
[   10.999999] thermal emergency: cpu thermal reached critical temperature
[   11.111111] kernel BUG at drivers/usb/core/usb.c:1234!
[   12.222222] general protection fault, probably for non-canonical address 0x1deadbeef
[   13.333333] systemd[1]: Started Journal Service.
[   14.444444] mce: [Hardware Error]: CPU 0 BANK 0 TSC 0 ADDR 0
"""


def test_dmesg_detects_all_critical_kinds():
    a = DmesgAnalyzer()
    findings = a.analyze_log(SAMPLE_DMESG)
    cats = {f["category"] for f in findings}
    required = {
        "Kernel Bug", "Kernel Oops", "OOM Killer", "Soft Lockup", "Hard Lockup",
        "RCU Stall", "Segmentation Fault", "EXT4 Filesystem Error", "Buffer I/O Error",
        "Thermal Event", "General Protection Fault", "Machine Check Exception",
        "Hardware Identity",
    }
    missing = required - cats
    assert not missing, f"dmesg analyzer missed: {missing}"


def test_dmesg_line_numbers_are_accurate():
    a = DmesgAnalyzer()
    findings = a.analyze_log(SAMPLE_DMESG)
    by_line = {f["line"]: f for f in findings}
    assert by_line[3]["category"] == "Hardware Identity"
    assert by_line[4]["category"] == "Kernel Bug"
    assert by_line[5]["category"] == "Kernel Oops"
    assert by_line[6]["category"] == "OOM Killer"
    assert by_line[7]["category"] == "OOM Killer (cgroup)"
    assert by_line[8]["category"] == "Soft Lockup"
    assert by_line[9]["category"] == "Hard Lockup"
    assert by_line[10]["category"] == "RCU Stall"
    assert by_line[11]["category"] == "Segmentation Fault"


def test_dmesg_severities_for_real_problems():
    a = DmesgAnalyzer()
    findings = a.analyze_log(SAMPLE_DMESG)
    by_cat = {f["category"]: f for f in findings}
    assert by_cat.get("Kernel Panic") is None
    assert by_cat["Kernel Bug"]["severity"] == "Critical"
    assert by_cat["OOM Killer"]["severity"] == "Error"
    assert by_cat["Soft Lockup"]["severity"] == "Error"
    assert by_cat["Hard Lockup"]["severity"] == "Critical"
    assert by_cat["Thermal Event"]["severity"] == "Critical"
    assert by_cat["Machine Check Exception"]["severity"] == "Critical"


def test_dmesg_clean_log_returns_no_critical():
    a = DmesgAnalyzer()
    findings = a.analyze_log("""
[    0.0] Linux version 5.15
[    1.0] systemd[1]: Reached target Multi-User System.
[    2.0] usbcore: registered new interface driver usbfs
""")
    criticals = [f for f in findings if f["severity"] in ("Critical", "Error")]
    assert criticals == []


def test_dmesg_old_oom_format_kill_word_also_matches():
    """Real kernel always says 'Killed process' but the old buggy pattern
    required 'Kill process'. Make sure both forms are caught."""
    a = DmesgAnalyzer()
    content = "Out of memory: Kill process 999 (legacy) total-vm:1kB\n" \
              "Out of memory: Killed process 1000 (modern) total-vm:2kB\n"
    findings = a.analyze_log(content)
    oom = [f for f in findings if f["category"] == "OOM Killer"]
    assert len(oom) == 2, f"expected 2 OOM events, got {len(oom)}"
    pids = {f["details"].get("pid") for f in oom}
    assert pids == {"999", "1000"}


def test_dmesg_details_have_named_groups():
    a = DmesgAnalyzer()
    findings = a.analyze_log(SAMPLE_DMESG)
    oom = next(f for f in findings if f["category"] == "OOM Killer" and f["details"].get("pid") == "1234")
    assert oom["details"]["name"] == "oom_test"
    segfault = next(f for f in findings if f["category"] == "Segmentation Fault")
    assert segfault["details"]["addr"] == "7f8a12340000"
    assert segfault["details"]["err"] == "4"


if __name__ == "__main__":
    test_dmesg_detects_all_critical_kinds()
    test_dmesg_line_numbers_are_accurate()
    test_dmesg_severities_for_real_problems()
    test_dmesg_clean_log_returns_no_critical()
    test_dmesg_old_oom_format_kill_word_also_matches()
    test_dmesg_details_have_named_groups()
    print(f"OK: 6 testes do dmesg analyzer")
