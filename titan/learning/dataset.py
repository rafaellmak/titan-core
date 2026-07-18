from __future__ import annotations
import random
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


class SyntheticDataset:
    """Gera eventos sintéticos de erro para Buildroot, Yocto, DTS e Security.

    Cada evento segue o formato esperado pelo ValidationHistory:
      error_fingerprint, error_category, score, accepted, fix_signature, metadata
    """

    BUILDROOT_ERRORS: Dict[str, List[Dict[str, str]]] = {
        "BUILDROOT_MISSING_PACKAGE": [
            {"error": "missing openssl", "fix": "BR2_PACKAGE_OPENSSL=y"},
            {"error": "package zlib not found", "fix": "BR2_PACKAGE_ZLIB=y"},
            {"error": "libcurl dependency missing", "fix": "BR2_PACKAGE_LIBCURL=y"},
            {"error": "ncurses unavailable", "fix": "BR2_PACKAGE_NCURSES=y"},
            {"error": "cannot find readline", "fix": "BR2_PACKAGE_READLINE=y"},
            {"error": "libpcap is not selected", "fix": "BR2_PACKAGE_LIBPCAP=y"},
            {"error": "libuuid is in the dependency of", "fix": "BR2_PACKACE_UTIL_LINUX=y"},
            {"error": "libxml2 not present", "fix": "BR2_PACKAGE_LIBXML2=y"},
            {"error": "missing python3", "fix": "BR2_PACKAGE_PYTHON3=y"},
            {"error": "libffi dependency missing", "fix": "BR2_PACKAGE_LIBFFI=y"},
        ],
        "BUILDROOT_TOOLCHAIN_ERROR": [
            {"error": "toolchain not found", "fix": "BR2_TOOLCHAIN_EXTERNAL=y"},
            {"error": "no toolchain", "fix": "BR2_TOOLCHAIN_EXTERNAL=y"},
            {"error": "toolchain unsupported", "fix": "BR2_TOOLCHAIN_EXTERNAL_CUSTOM=y"},
            {"error": "cannot find toolchain", "fix": "BR2_TOOLCHAIN_PATH=/opt/toolchain"},
            {"error": "cross compile toolchain", "fix": "BR2_TOOLCHAIN_EXTERNAL_PATH=/opt/cross"},
        ],
        "BUILDROOT_KERNEL_ERROR": [
            {"error": "kernel not configured", "fix": "BR2_LINUX_KERNEL=y"},
            {"error": "linux kernel not found", "fix": "BR2_LINUX_KERNEL_CUSTOM_VERSION=y"},
            {"error": "kernel config missing", "fix": "BR2_LINUX_KERNEL_USE_CUSTOM_CONFIG=y"},
            {"error": "cannot build kernel", "fix": "BR2_LINUX_KERNEL_CUSTOM_DTS_PATH=y"},
        ],
        "BUILDROOT_CONFIG_ERROR": [
            {"error": "configuration error", "fix": "BR2_DEFCONFIG=/path/to/config"},
            {"error": "invalid .config", "fix": "make defconfig"},
            {"error": "BR2_PACKAGE_OPENSSL is not set", "fix": "BR2_PACKAGE_OPENSSL=y"},
        ],
    }

    YOCTO_ERRORS: Dict[str, List[Dict[str, str]]] = {
        "YOCTO_NOTHING_PROVIDES": [
            {"error": "Nothing PROVIDES openssl", "fix": 'IMAGE_INSTALL += "openssl"'},
            {"error": "python3 not provided", "fix": 'IMAGE_INSTALL += "python3"'},
            {"error": "unable to satisfy libcurl", "fix": 'IMAGE_INSTALL += "curl"'},
            {"error": "no recipe provides libpcap", "fix": 'IMAGE_INSTALL += "libpcap"'},
        ],
        "YOCTO_PARSE_ERROR": [
            {"error": "parsing error in openssl_1.1.bb", "fix": "bitbake -c clean openssl"},
            {"error": "syntax error in layer.conf", "fix": "BBLAYERS += /path/to/layer"},
            {"error": "bbclass autotools not found", "fix": "INHERIT += autotools"},
        ],
        "YOCTO_TASK_FAILURE": [
            {"error": "task do_compile failed", "fix": "CLEANBROKEN = '1'"},
            {"error": "do_install failed", "fix": "INHIBIT_PACKAGE_STRIP = '1'"},
            {"error": "exit code 1", "fix": "check log.do_compile"},
            {"error": "function do_configure failed", "fix": "EXTRA_OECONF += '--disable-static'"},
        ],
        "YOCTO_QA_WARNING": [
            {"error": "QA issue: rdepends on busybox", "fix": "RDEPENDS += 'busybox'"},
            {"error": "build dependency missing", "fix": "DEPENDS += 'virtual/kernel'"},
            {"error": "installed openssl in image", "fix": "LICENSE_FLAGS = 'commercial'"},
        ],
    }

    DTS_ERRORS: Dict[str, List[Dict[str, str]]] = {
        "DTS_COMPILATION_ERROR": [
            {"error": "dtc error: syntax error", "fix": "fix dts node syntax"},
            {"error": "compilation failed", "fix": "check dts includes"},
            {"error": "unable to parse dts", "fix": "fix dts format"},
            {"error": "interrupt-cells is not valid", "fix": "#interrupt-cells = <1>"},
        ],
        "DTS_BINDING_ERROR": [
            {"error": "binding check failed", "fix": "update binding yaml"},
            {"error": "device not compatible", "fix": "add compatible string"},
            {"error": "binding clock not found", "fix": "clocks = <&clk 0>"},
            {"error": "reg binding mismatch", "fix": "reg = <0x0 0x1000>"},
        ],
    }

    SECURITY_ERRORS: Dict[str, List[Dict[str, str]]] = {
        "SECURITY_CRITICAL_CVE": [
            {"error": "critical CVE-2023-44487 found", "fix": "Bumping package version >2.3.0"},
            {"error": "CVE-2023-38545 critical", "fix": "curl >= 8.4.0"},
            {"error": "unpatched openssl CVE critical", "fix": "openssl >= 3.1.4"},
        ],
        "SECURITY_HIGH_CVE": [
            {"error": "high CVE-2023-45871 found", "fix": "update bluez to 5.66"},
            {"error": "CVE-2023-4911 high", "fix": "glibc >= 2.38"},
            {"error": "vulnerability nginx unpatched", "fix": "nginx >= 1.24.0"},
        ],
    }

    CATEGORY_MAP: Dict[str, str] = {
        "BUILDROOT_MISSING_PACKAGE": "BuildrootError",
        "BUILDROOT_TOOLCHAIN_ERROR": "BuildrootError",
        "BUILDROOT_KERNEL_ERROR": "BuildrootError",
        "BUILDROOT_CONFIG_ERROR": "BuildrootError",
        "YOCTO_NOTHING_PROVIDES": "YoctoError",
        "YOCTO_PARSE_ERROR": "YoctoError",
        "YOCTO_TASK_FAILURE": "YoctoError",
        "YOCTO_QA_WARNING": "YoctoError",
        "DTS_COMPILATION_ERROR": "DTSError",
        "DTS_BINDING_ERROR": "DTSError",
        "SECURITY_CRITICAL_CVE": "SecurityError",
        "SECURITY_HIGH_CVE": "SecurityError",
    }

    ERROR_CATEGORIES: Dict[str, Dict[str, List[Dict[str, str]]]] = {
        "BuildrootError": BUILDROOT_ERRORS,
        "YoctoError": YOCTO_ERRORS,
        "DTSError": DTS_ERRORS,
        "SecurityError": SECURITY_ERRORS,
    }

    WORKSPACE_VARIANTS: List[Dict[str, str]] = [
        {"arch": "aarch64", "toolchain_type": "external", "c_library": "glibc", "board": "raspberrypi4", "distro": "unknown", "kernel_version": "5.15"},
        {"arch": "armv7", "toolchain_type": "external", "c_library": "glibc", "board": "beaglebone", "distro": "unknown", "kernel_version": "5.10"},
        {"arch": "x86_64", "toolchain_type": "internal", "c_library": "glibc", "board": "pc_x86_64", "distro": "ubuntu", "kernel_version": "6.1"},
        {"arch": "aarch64", "toolchain_type": "internal", "c_library": "musl", "board": "qemu_aarch64", "distro": "alpine", "kernel_version": "6.1"},
        {"arch": "armv5", "toolchain_type": "external", "c_library": "glibc", "board": "at91sam9g20", "distro": "buildroot", "kernel_version": "4.19"},
        {"arch": "riscv64", "toolchain_type": "external", "c_library": "glibc", "board": "sifive_u", "distro": "fedora", "kernel_version": "6.2"},
    ]

    def __init__(self, seed: int = 42):
        self.random = random.Random(seed)

    def generate(self, n_events: int = 500,
                 accepted_rate: float = 0.7,
                 base_timestamp: Optional[str] = None) -> List[Dict[str, Any]]:
        if base_timestamp is None:
            base = datetime.now()
        else:
            base = datetime.fromisoformat(base_timestamp)

        events: List[Dict[str, Any]] = []
        for i in range(n_events):
            category = self.random.choice(list(self.ERROR_CATEGORIES.keys()))
            error_type = self.random.choice(list(self.ERROR_CATEGORIES[category].keys()))
            samples = self.ERROR_CATEGORIES[category][error_type]
            sample = self.random.choice(samples)
            ws = self.random.choice(self.WORKSPACE_VARIANTS)

            score = self.random.randint(60, 100) if self.random.random() < accepted_rate else self.random.randint(20, 59)
            accepted = score >= 60
            ts = base + timedelta(hours=i, minutes=self.random.randint(0, 59))

            event = {
                "skill_name": f"{category}Skill",
                "score": float(score),
                "accepted": accepted,
                "error_category": category,
                "error_fingerprint": sample["error"],
                "fix_signature": sample["fix"],
                "timestamp": ts.isoformat(),
                "summary": f"{error_type}: {sample['error']}",
                "raw_data": {"raw": sample["error"]},
                "metadata": {"workspace": ws},
            }
            events.append(event)
        return events

    def generate_benchmark(self, n_per_fix: int = 3,
                           base_timestamp: Optional[str] = None) -> List[Dict[str, Any]]:
        """Gera dataset equilibrado: cada fix aparece n_per_fix vezes."""
        if base_timestamp is None:
            base = datetime.now()
        else:
            base = datetime.fromisoformat(base_timestamp)

        events: List[Dict[str, Any]] = []
        idx = 0
        for category, error_types in self.ERROR_CATEGORIES.items():
            for error_type, samples in error_types.items():
                for sample in samples:
                    for _ in range(n_per_fix):
                        ws = self.random.choice(self.WORKSPACE_VARIANTS)
                        score = self.random.randint(75, 100) if self.random.random() < 0.8 else self.random.randint(40, 74)
                        accepted = score >= 60
                        ts = base + timedelta(hours=idx)

                        events.append({
                            "skill_name": f"{category}Skill",
                            "score": float(score),
                            "accepted": accepted,
                            "error_category": category,
                            "error_fingerprint": sample["error"],
                            "fix_signature": sample["fix"],
                            "timestamp": ts.isoformat(),
                            "summary": f"{error_type}: {sample['error']}",
                            "raw_data": {"raw": sample["error"]},
                            "metadata": {"workspace": ws},
                        })
                        idx += 1
        return events
