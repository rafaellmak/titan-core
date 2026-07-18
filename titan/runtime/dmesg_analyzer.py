import re
from typing import List, Dict, Tuple, Pattern

class DmesgAnalyzer:
    """Analisador de logs dmesg para o Titan Enterprise.

    Cobre as principais classes de eventos críticos em kernels Linux
    modernos (>= 4.x): panics, oops, OOM, soft/hard lockups, RCU stalls,
    faults de hardware (MCE), erros de I/O, segfaults e corrupção de
    sistema de arquivos.
    """

    patterns: List[Tuple[Pattern, str, str]] = [
        (re.compile(r"Kernel panic - not syncing: (?P<reason>.*)"), "Critical", "Kernel Panic"),
        (re.compile(r"BUG:\s+unable to handle (?P<kind>.*)"), "Critical", "Kernel Bug"),
        (re.compile(r"kernel BUG at (?P<file>[^:]+):(?P<line>\d+)!"), "Critical", "Kernel Bug"),
        (re.compile(r"Oops:\s*(?P<bits>[\d#x]+)(?:\s*\[#(?P<n>\d+)\])?\s*(?P<mode>[A-Z]+)?"), "Critical", "Kernel Oops"),
        (re.compile(r"general protection fault,?\s*(?P<detail>.*)"), "Critical", "General Protection Fault"),
        (re.compile(r"Out of memory: Kill(?:ed)?\s+process\s+(?P<pid>\d+)\s+\((?P<name>[^)]+)\)"), "Error", "OOM Killer"),
        (re.compile(r"oom[-_]kill:(?P<rest>.*)"), "Error", "OOM Killer (cgroup)"),
        (re.compile(r"(?i)\bmce\s*:\s*(?P<kind>.*)"), "Critical", "Machine Check Exception"),
        (re.compile(r"Hardware name: (?P<system>.*)"), "Info", "Hardware Identity"),
        (re.compile(r"watchdog:\s*BUG:\s*soft lockup\s*-\s*CPU#(?P<cpu>\d+)\s+stuck\s+for\s+(?P<secs>\d+)s"), "Error", "Soft Lockup"),
        (re.compile(r"NMI watchdog: Watchdog detected hard LOCKUP on cpu\s+(?P<cpu>\d+)"), "Critical", "Hard Lockup"),
        (re.compile(r"rcu[_:]\s*INFO:?\s*rcu_(?P<kind>sched|bh|tasks)\s+detected\s+stalls?\s+on\s+CPUs?(?::?/?tasks)?[:\s]+(?P<detail>.*)"), "Error", "RCU Stall"),
        (re.compile(r"segfault at\s+(?P<addr>[0-9a-f]+)\s+ip\s+(?P<ip>[0-9a-f]+)\s+sp\s+(?P<sp>[0-9a-f]+)\s+error\s+(?P<err>\d+)"), "Error", "Segmentation Fault"),
        (re.compile(r"EXT4-fs error \(device\s+(?P<dev>[^)]+)\):\s*(?P<detail>.*)"), "Error", "EXT4 Filesystem Error"),
        (re.compile(r"XFS \(dm-\d+\):\s*(?P<detail>.*error.*)"), "Error", "XFS Filesystem Error"),
        (re.compile(r"I/O error,?\s*dev\s+(?P<dev>\S+),?\s*sector\s+(?P<sector>\d+)"), "Error", "Block I/O Error"),
        (re.compile(r"Buffer I/O error on device\s+(?P<dev>\S+),?\s*logical block\s+(?P<blk>\d+)"), "Error", "Buffer I/O Error"),
        (re.compile(r"usb\s+\S+:\s*(?P<detail>.*error.*)"), "Warning", "USB Error"),
        (re.compile(r"thermal\s+(?P<kind>emergency|shutdown):\s*(?P<detail>.*)"), "Critical", "Thermal Event"),
        (re.compile(r"WARNING: CPU:\s*(?P<cpu>\d+)\s+PID:\s*(?P<pid>\d+)\s+at\s+(?P<loc>.*)"), "Warning", "Kernel Warning"),
        (re.compile(r"call_trace:\s+begin"), "Info", "Call Trace"),
        (re.compile(r"Modules linked in:\s*(?P<modules>.*)"), "Info", "Modules Loaded"),
    ]

    def __init__(self):
        pass

    def analyze_log(self, content: str) -> List[Dict]:
        findings = []
        lines = content.splitlines()
        for i, line in enumerate(lines, 1):
            for pattern, severity, category in self.patterns:
                match = pattern.search(line)
                if match:
                    findings.append({
                        "line": i,
                        "severity": severity,
                        "category": category,
                        "description": line.strip(),
                        "details": {k: v.strip() if isinstance(v, str) else v
                                    for k, v in match.groupdict().items() if v is not None}
                    })
        return findings

    def report_findings(self, findings: List[Dict]):
        if not findings:
            print("✅ Nenhum erro crítico detectado no log dmesg.")
            return

        print(f"🚦 Análise de Runtime ({len(findings)} eventos detectados):")
        for f in findings:
            print(f"[{f['severity']}] {f['category']} (Linha {f['line']}): {f['description']}")
