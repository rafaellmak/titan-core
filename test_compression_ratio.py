#!/usr/bin/env python3
"""Validates Compression Ratio hypothesis with realistic linguistic variants."""
import json
from collections import defaultdict
from titan.learning.normalizer import ErrorNormalizer

TEST_CASES = [
    # (category, expected_fp, variants)
    # Buildroot: MISSING_PACKAGE
    ("BuildrootError", "BUILDROOT_MISSING_PACKAGE:openssl", [
        "missing openssl",
        "package openssl not found",
        "openssl dependency missing",
        "openssl unavailable",
        "cannot find openssl",
        "openssl is not selected",
        "BR2_PACKAGE_OPENSSL is not set",
        "openssl is in the dependency of",
        "openssl not present",
    ]),
    ("BuildrootError", "BUILDROOT_MISSING_PACKAGE:zlib", [
        "missing zlib",
        "package zlib not found",
        "zlib dependency missing",
        "cannot find zlib",
        "zlib is not selected",
        "BR2_PACKAGE_ZLIB is not set",
        "zlib not present",
    ]),
    # Buildroot: toolchain (must not be stolen by MISSING_PACKAGE)
    ("BuildrootError", "BUILDROOT_TOOLCHAIN_MISSING", [
        "toolchain not found",
        "no toolchain",
    ]),
    ("BuildrootError", "BUILDROOT_TOOLCHAIN_PATH_ERROR", [
        "cannot find toolchain",
    ]),
    ("BuildrootError", "BUILDROOT_TOOLCHAIN_UNSUPPORTED", [
        "toolchain unsupported",
        "toolchain is unsupported",
        "unsupported toolchain version",
    ]),
    ("BuildrootError", "BUILDROOT_DEFCONFIG_ERROR", [
        "configuration error",
        "invalid .config",
        "config BR2_PACKAGE not set",
        "unset configuration",
        ".config: configuration error",
    ]),
    ("BuildrootError", "BUILDROOT_KERNEL_NOT_ENABLED", [
        "kernel not configured",
        "BR2_LINUX_KERNEL is not set",
        "kernel configuration not enabled",
    ]),
    # Yocto: nothing provides
    ("YoctoError", "YOCTO_NOTHING_PROVIDES:python3", [
        "nothing provides python3",
        "python3 not provided",
        "unable to satisfy python3",
        "no recipe provides python3",
        "python3 is not available",
    ]),
    ("YoctoError", "YOCTO_NOTHING_PROVIDES:boost", [
        "nothing provides boost",
        "boost not provided",
        "unable to satisfy boost",
        "no recipe provides boost",
    ]),
    # Yocto: parse error
    ("YoctoError", "YOCTO_PARSE_ERROR", [
        "parsing error in openssl_1.1.bb",
        "parse error: openssl",
    ]),
    # Yocto: compile failure (must not be stolen by "exit code")
    ("YoctoError", "YOCTO_COMPILE_FAILURE", [
        "task do_compile failed",
        "ERROR: task do_compile failed",
        "do_compile failed with exit code 1",
    ]),
    # Yocto: rdepends
    ("YoctoError", "YOCTO_RDEPENDS_ERROR:libssl", [
        "rdepends on libssl",
        "rdepends on libssl is missing",
        "rdepends on libssl not found",
    ]),
    # DTS
    ("DTSError", "DTS_SYNTAX_ERROR", [
        "dtc error: syntax",
        "syntax error in file.dts",
        "DTC: syntax error at line 42",
    ]),
    ("DTSError", "DTS_BINDING_ERROR:gpio", [
        "binding check failed for gpio",
        "gpio not compatible with binding",
        "gpio binding mismatch",
    ]),
    ("DTSError", "DTS_INVALID_PROPERTY:clock-frequency", [
        "clock-frequency is not valid",
        "property clock-frequency is not valid",
        "clock-frequency not valid in node",
    ]),
    # Security CVE
    ("SecurityError", "SECURITY_CRITICAL_CVE:cve-2023-44487", [
        "critical CVE-2023-44487 found",
    ]),
    ("SecurityError", "SECURITY_CRITICAL_CVE:cve-2023-38545", [
        "CVE-2023-38545 critical",
    ]),
    ("SecurityError", "SECURITY_CRITICAL_CVE:openssl", [
        "unpatched openssl CVE critical",
    ]),
    ("SecurityError", "SECURITY_CRITICAL_CVE:cve-2024-0001", [
        "CVE-2024-0001 detected",
    ]),
    ("SecurityError", "SECURITY_HIGH_CVE:cve-2023-45871", [
        "high CVE-2023-45871 found",
        "CVE-2023-45871 high severity",
    ]),
    ("SecurityError", "SECURITY_HIGH_CVE:nginx", [
        "vulnerability nginx unpatched",
    ]),
    ("SecurityError", "SECURITY_HIGH_CVE:cve-2024-0002", [
        "CVE-2024-0002 found",
    ]),
]


def main():
    normalizer = ErrorNormalizer()
    total_raw = 0
    canonical_counts = defaultdict(int)
    misses = []

    print("=" * 72)
    print("  COMPRESSION RATIO VALIDATION — Linguistic Variants")
    print("=" * 72)

    for category, expected_fp, variants in TEST_CASES:
        results = set()
        for variant in variants:
            total_raw += 1
            result = normalizer.normalize(variant, category)
            results.add(result)
            canonical_counts[result] += 1

        n_raw = len(variants)
        n_unique = len(results)
        ratio = n_raw / n_unique if n_unique > 0 else 0

        indicator = "OK" if n_unique == 1 and expected_fp in results else "MISMATCH"
        if indicator == "MISMATCH":
            misses.append((expected_fp, results, variants))

        print(f"    {expected_fp:50s}  {n_raw:2d} raw → {n_unique:2d} canonical  {ratio:5.2f}x  [{indicator}]")

    print("\n" + "=" * 72)
    print("  SUMMARY")
    print("=" * 72)
    unique = len(canonical_counts)
    print(f"\n  Total raw variants:      {total_raw}")
    print(f"  Unique canonical fps:    {unique}")
    print(f"  Overall Compression:     {total_raw/unique:.2f}x" if unique else "")

    if misses:
        print(f"\n  MISMATCHES ({len(misses)}):")
        for expected, results, variants in misses:
            print(f"    Expected: {expected}")
            print(f"    Got:      {results}")
    else:
        print(f"\n  0 mismatches — all variants collapsed correctly.")

    print(f"\n  Canonical distribution (top 10):")
    for fp, count in sorted(canonical_counts.items(), key=lambda x: -x[1])[:10]:
        print(f"    {fp:55s}  {count} raw variants")


if __name__ == "__main__":
    main()
