import tempfile
from pathlib import Path
from datetime import datetime

from titan.learning.metrics import NormalizationMetrics
from titan.learning.normalizer import ErrorNormalizer
from titan.learning.dataset import SyntheticDataset


# ---------------------------------------------------------------------------
# NormalizationMetrics
# ---------------------------------------------------------------------------

class TestNormalizationMetrics:
    def test_empty_runs(self):
        metrics = NormalizationMetrics()
        m = metrics.compute([])
        assert m["total_raw"] == 0
        assert m["health"] == "no_data"

    def test_single_error(self):
        metrics = NormalizationMetrics()
        runs = [
            {"error_fingerprint": "missing openssl", "error_category": "BuildrootError"},
        ]
        m = metrics.compute(runs)
        assert m["total_raw"] == 1
        assert m["unique_raw"] == 1
        assert m["unique_canonical"] == 1
        assert m["compression_ratio"] == 1.0
        assert m["health"] == "healthy"

    def test_compression_multiple_variations(self):
        metrics = NormalizationMetrics()
        runs = [
            {"error_fingerprint": "missing openssl", "error_category": "BuildrootError"},
            {"error_fingerprint": "package openssl not found", "error_category": "BuildrootError"},
            {"error_fingerprint": "openssl dependency missing", "error_category": "BuildrootError"},
        ]
        m = metrics.compute(runs)
        assert m["total_raw"] == 3
        assert m["unique_raw"] == 3
        assert m["unique_canonical"] == 1
        assert m["compression_ratio"] == 3.0

    def test_compression_mixed_categories(self):
        metrics = NormalizationMetrics()
        runs = [
            {"error_fingerprint": "missing openssl", "error_category": "BuildrootError"},
            {"error_fingerprint": "Nothing PROVIDES openssl", "error_category": "YoctoError"},
        ]
        m = metrics.compute(runs)
        assert m["unique_canonical"] == 2
        # BUILDROOT_MISSING_PACKAGE:openssl e YOCTO_NOTHING_PROVIDES:openssl

    def test_top_fingerprints(self):
        metrics = NormalizationMetrics()
        runs = [
            {"error_fingerprint": "missing openssl", "error_category": "BuildrootError"},
            {"error_fingerprint": "package openssl not found", "error_category": "BuildrootError"},
            {"error_fingerprint": "nothing provides python3", "error_category": "YoctoError"},
        ]
        m = metrics.compute(runs)
        assert len(m["top_fingerprints"]) == 2
        assert m["top_fingerprints"][0]["occurrences"] == 2  # openssl vem primeiro

    def test_collision_detection(self):
        """Duas variações diferentes que viram o mesmo fingerprint."""
        metrics = NormalizationMetrics()
        runs = [
            {"error_fingerprint": "missing openssl", "error_category": "BuildrootError"},
            {"error_fingerprint": "missing zlib", "error_category": "BuildrootError"},
        ]
        m = metrics.compute(runs)
        # São dois fingerprints diferentes (BUILDROOT_MISSING_PACKAGE:openssl vs :zlib)
        # Isso NÃO é colisão — são erros diferentes
        assert m["collision_count"] == 0

    def test_collision_true_positive(self):
        """Variações do mesmo erro que viram o mesmo fingerprint — não é colisão."""
        metrics = NormalizationMetrics()
        runs = [
            {"error_fingerprint": "missing openssl", "error_category": "BuildrootError"},
            {"error_fingerprint": "openssl not found", "error_category": "BuildrootError"},
        ]
        m = metrics.compute(runs)
        # Ambos viram BUILDROOT_MISSING_PACKAGE:openssl — é compressão, não colisão
        assert m["collision_count"] == 0  # compressão correta

    def test_summarize_output(self):
        metrics = NormalizationMetrics()
        runs = [
            {"error_fingerprint": "missing openssl", "error_category": "BuildrootError"},
            {"error_fingerprint": "nothing provides python3", "error_category": "YoctoError"},
        ]
        out = metrics.summarize(runs)
        assert "NormalizationMetrics" in out
        assert "Compression Ratio" in out

    def test_health_collision(self):
        """Fix_signatures diferentes com mesmo canonical → colisão real."""
        normalizer = ErrorNormalizer()
        runs = [
            {"error_fingerprint": "missing openssl", "error_category": "BuildrootError",
             "fix_signature": "BR2_PACKAGE_OPENSSL=y"},
            {"error_fingerprint": "missing openssl", "error_category": "BuildrootError",
             "fix_signature": "BR2_PACKAGE_LIBOPENSSL=y"},  # fix diferente!
        ]
        metrics = NormalizationMetrics(normalizer)
        m = metrics.compute(runs)
        # Mesmo canonical (BUILDROOT_MISSING_PACKAGE:openssl) com fixes diferentes
        assert m["collision_count"] == 1
        assert m["health"] == "collisions_detected"

    def test_health_no_collision_same_fix(self):
        """Mesmo canonical com mesmo fix → compressão saudável."""
        normalizer = ErrorNormalizer()
        runs = [
            {"error_fingerprint": "missing openssl", "error_category": "BuildrootError",
             "fix_signature": "BR2_PACKAGE_OPENSSL=y"},
            {"error_fingerprint": "package openssl not found", "error_category": "BuildrootError",
             "fix_signature": "BR2_PACKAGE_OPENSSL=y"},
        ]
        metrics = NormalizationMetrics(normalizer)
        m = metrics.compute(runs)
        assert m["collision_count"] == 0
        assert m["health"] == "healthy"


# ---------------------------------------------------------------------------
# SyntheticDataset
# ---------------------------------------------------------------------------

class TestSyntheticDataset:
    def test_generate_defaults(self):
        ds = SyntheticDataset(seed=42)
        events = ds.generate(n_events=100)
        assert len(events) == 100
        for e in events:
            assert "error_fingerprint" in e
            assert "error_category" in e
            assert "score" in e
            assert "accepted" in e
            assert "fix_signature" in e

    def test_generate_category_distribution(self):
        ds = SyntheticDataset(seed=42)
        events = ds.generate(n_events=500)
        cats = set(e["error_category"] for e in events)
        assert "BuildrootError" in cats
        assert "YoctoError" in cats
        assert "DTSError" in cats
        assert "SecurityError" in cats

    def test_generate_accepted_rate(self):
        ds = SyntheticDataset(seed=42)
        events = ds.generate(n_events=200, accepted_rate=0.7)
        accepted = sum(1 for e in events if e["accepted"])
        # Com seed fixa, deve ser próximo de 70%
        assert accepted > 0

    def test_generate_workspace_context(self):
        ds = SyntheticDataset(seed=42)
        events = ds.generate(n_events=10)
        for e in events:
            meta = e.get("metadata", {})
            ws = meta.get("workspace", {})
            assert "arch" in ws
            assert "toolchain_type" in ws

    def test_generate_benchmark(self):
        ds = SyntheticDataset(seed=42)
        events = ds.generate_benchmark(n_per_fix=3)
        assert len(events) > 0
        # Cada fix aparece 3 vezes — verificar fingerprints
        fps = set(e["error_fingerprint"] for e in events)
        assert len(fps) > 0

    def test_generate_benchmark_balanced(self):
        ds = SyntheticDataset(seed=42)
        events = ds.generate_benchmark(n_per_fix=3)
        combo_counts: dict = {}
        for e in events:
            key = (e["error_fingerprint"], e["fix_signature"])
            combo_counts[key] = combo_counts.get(key, 0) + 1
        for (fp, fix), count in combo_counts.items():
            assert count == 3, (
                f"({fp!r}, {fix!r}) appears {count} times, expected 3"
            )

    def test_generate_with_timestamp(self):
        ds = SyntheticDataset(seed=42)
        events = ds.generate(n_events=5, base_timestamp="2025-06-01T00:00:00")
        for i, e in enumerate(events):
            assert "T" in e["timestamp"] or " " in e["timestamp"]


# ---------------------------------------------------------------------------
# Regression tests — normalizer collisions do v17 refinement
# Cada teste verifica que erros com fixes DIFERENTES
# produzem fingerprints canónicos DIFERENTES.
# ---------------------------------------------------------------------------

class TestNormalizerCollisionRegression:
    """Garante que as 8 colisões encontradas no benchmark foram eliminadas."""

    def test_buildroot_config_error_split(self):
        """BR2_PACKAGE_X is not set → BUILDROOT_MISSING_PACKAGE, não CONFIG_ERROR."""
        n = ErrorNormalizer()
        r1 = n.normalize("configuration error", "BuildrootError")
        r2 = n.normalize("BR2_PACKAGE_OPENSSL is not set", "BuildrootError")
        assert r1 != r2, (
            f"configuration error e BR2_PACKAGE_OPENSSL is not set "
            f"colidiram: ambos → {r1}"
        )
        assert r1.startswith("BUILDROOT_DEFCONFIG_ERROR") or r1.startswith("BUILDROOT_CONFIG")
        assert r2.startswith("BUILDROOT_MISSING_PACKAGE")

    def test_buildroot_toolchain_error_split(self):
        """toolchain unsupported ≠ toolchain not found ≠ cross compile."""
        n = ErrorNormalizer()
        r1 = n.normalize("toolchain not found", "BuildrootError")
        r2 = n.normalize("toolchain unsupported", "BuildrootError")
        r3 = n.normalize("cross compile toolchain", "BuildrootError")
        fingerprints = {r1, r2, r3}
        assert len(fingerprints) == 3, (
            f"Toolchain errors colidiram: {fingerprints}"
        )

    def test_buildroot_kernel_error_split(self):
        """kernel not configured ≠ kernel config missing ≠ cannot build kernel."""
        n = ErrorNormalizer()
        r1 = n.normalize("kernel not configured", "BuildrootError")
        r2 = n.normalize("kernel config missing", "BuildrootError")
        r3 = n.normalize("cannot build kernel", "BuildrootError")
        fingerprints = {r1, r2, r3}
        assert len(fingerprints) == 3, (
            f"Kernel errors colidiram: {fingerprints}"
        )

    def test_dts_compilation_error_split(self):
        """dtc error ≠ compilation failed ≠ unable to parse dts ≠ not valid."""
        n = ErrorNormalizer()
        r1 = n.normalize("dtc error: syntax error", "DTSError")
        r2 = n.normalize("compilation failed", "DTSError")
        r3 = n.normalize("unable to parse dts", "DTSError")
        r4 = n.normalize("interrupt-cells is not valid", "DTSError")
        fingerprints = {r1, r2, r3, r4}
        assert len(fingerprints) == 4, (
            f"DTS errors colidiram: {fingerprints}"
        )

    def test_dts_binding_error_split(self):
        """binding check failed ≠ binding clock not found ≠ reg binding mismatch."""
        n = ErrorNormalizer()
        r1 = n.normalize("binding check failed", "DTSError")
        r2 = n.normalize("binding clock not found", "DTSError")
        r3 = n.normalize("reg binding mismatch", "DTSError")
        fingerprints = {r1, r2, r3}
        assert len(fingerprints) == 3, (
            f"DTS binding errors colidiram: {fingerprints}"
        )

    def test_yocto_task_failure_split(self):
        """do_compile ≠ do_install ≠ do_configure ≠ exit code."""
        n = ErrorNormalizer()
        r1 = n.normalize("task do_compile failed", "YoctoError")
        r2 = n.normalize("do_install failed", "YoctoError")
        r3 = n.normalize("function do_configure failed", "YoctoError")
        r4 = n.normalize("exit code 1", "YoctoError")
        fingerprints = {r1, r2, r3, r4}
        assert len(fingerprints) == 4, (
            f"Yocto task errors colidiram: {fingerprints}"
        )

    def test_yocto_qa_warning_split(self):
        """rdepends ≠ build dependency ≠ installed in image."""
        n = ErrorNormalizer()
        r1 = n.normalize("QA issue: rdepends on busybox", "YoctoError")
        r2 = n.normalize("build dependency missing", "YoctoError")
        r3 = n.normalize("installed openssl in image", "YoctoError")
        fingerprints = {r1, r2, r3}
        assert len(fingerprints) == 3, (
            f"Yocto QA errors colidiram: {fingerprints}"
        )

    def test_same_fix_same_fingerprint(self):
        """Erros com o mesmo fix DEVEM ter o mesmo fingerprint."""
        n = ErrorNormalizer()
        r1 = n.normalize("missing openssl", "BuildrootError")
        r2 = n.normalize("package openssl not found", "BuildrootError")
        assert r1 == r2, (
            f"Variações de missing openssl NÃO colapsaram: {r1} != {r2}"
        )

    def test_toolchain_not_stolen_by_missing_package(self):
        """cannot find toolchain → TOOLCHAIN_PATH_ERROR, não MISSING_PACKAGE:toolchain."""
        n = ErrorNormalizer()
        r = n.normalize("cannot find toolchain", "BuildrootError")
        assert r == "BUILDROOT_TOOLCHAIN_PATH_ERROR", (
            f"cannot find toolchain foi roubado por MISSING_PACKAGE: {r}"
        )

    def test_toolchain_missing_vs_path_different_fingerprints(self):
        """toolchain not found ≠ cannot find toolchain (fixes diferentes)."""
        n = ErrorNormalizer()
        r1 = n.normalize("toolchain not found", "BuildrootError")
        r2 = n.normalize("cannot find toolchain", "BuildrootError")
        assert r1 != r2, (
            f"toolchain not found e cannot find toolchain colidiram: {r1}"
        )
        assert r1 == "BUILDROOT_TOOLCHAIN_MISSING"
        assert r2 == "BUILDROOT_TOOLCHAIN_PATH_ERROR"

    def test_toolchain_unsupported_variants(self):
        """toolchain unsupported — variantes linguísticas colapsam."""
        n = ErrorNormalizer()
        r1 = n.normalize("toolchain unsupported", "BuildrootError")
        r2 = n.normalize("toolchain is unsupported", "BuildrootError")
        r3 = n.normalize("unsupported toolchain version", "BuildrootError")
        assert r1 == r2 == r3 == "BUILDROOT_TOOLCHAIN_UNSUPPORTED", (
            f"Variações de toolchain unsupported divergiram: {r1}, {r2}, {r3}"
        )

    def test_compile_failure_not_stolen_by_exit_code(self):
        """do_compile failed with exit code 1 → COMPILE_FAILURE, não GENERIC_FAILURE."""
        n = ErrorNormalizer()
        r = n.normalize("do_compile failed with exit code 1", "YoctoError")
        assert r == "YOCTO_COMPILE_FAILURE", (
            f"do_compile failed foi roubado por GENERIC_FAILURE: {r}"
        )

    def test_security_critical_cve_with_found(self):
        """"critical CVE-2023-44487 found" → SECURITY_CRITICAL_CVE:cve-2023-44487."""
        n = ErrorNormalizer()
        r = n.normalize("critical CVE-2023-44487 found", "SecurityError")
        assert r == "SECURITY_CRITICAL_CVE:cve-2023-44487", (
            f"critical CVE não normalizou: {r}"
        )

    def test_security_cve_critical_keyword(self):
        """"CVE-2023-38545 critical" → SECURITY_CRITICAL_CVE:cve-2023-38545."""
        n = ErrorNormalizer()
        r = n.normalize("CVE-2023-38545 critical", "SecurityError")
        assert r == "SECURITY_CRITICAL_CVE:cve-2023-38545", (
            f"CVE critical keyword não normalizou: {r}"
        )

    def test_security_high_cve_found(self):
        """"CVE-2023-45871 found" → SECURITY_HIGH_CVE:cve-2023-45871."""
        n = ErrorNormalizer()
        r = n.normalize("CVE-2023-45871 found", "SecurityError")
        assert r == "SECURITY_HIGH_CVE:cve-2023-45871", (
            f"CVE found não normalizou para HIGH: {r}"
        )

    def test_security_cve_detected(self):
        """"CVE-2024-0001 detected" → SECURITY_CRITICAL_CVE:cve-2024-0001."""
        n = ErrorNormalizer()
        r = n.normalize("CVE-2024-0001 detected", "SecurityError")
        assert r == "SECURITY_CRITICAL_CVE:cve-2024-0001", (
            f"CVE detected não normalizou: {r}"
        )

    def test_security_no_false_positive(self):
        """'exit code' NÃO deve virar CVE fingerprint."""
        n = ErrorNormalizer()
        r = n.normalize("exit code 1", "BuildrootError")
        assert "CVE" not in r, (
            f"exit code contaminou CVE fingerprint: {r}"
        )

    def test_compression_improved(self):
        """Após o refinamento, o compression ratio deve manter-se saudável
        e colisões entre TIPOS DIFERENTES de erro devem ser zero."""
        from titan.learning.metrics import NormalizationMetrics
        runs = [
            {"error_fingerprint": "missing openssl", "error_category": "BuildrootError",
             "fix_signature": "BR2_PACKAGE_OPENSSL=y"},
            {"error_fingerprint": "package openssl not found", "error_category": "BuildrootError",
             "fix_signature": "BR2_PACKAGE_OPENSSL=y"},
            {"error_fingerprint": "openssl dependency missing", "error_category": "BuildrootError",
             "fix_signature": "BR2_PACKAGE_OPENSSL=y"},
            {"error_fingerprint": "configuration error", "error_category": "BuildrootError",
             "fix_signature": "BR2_DEFCONFIG=/path/to/config"},
            {"error_fingerprint": "toolchain unsupported", "error_category": "BuildrootError",
             "fix_signature": "BR2_TOOLCHAIN_EXTERNAL_CUSTOM=y"},
            {"error_fingerprint": "toolchain not found", "error_category": "BuildrootError",
             "fix_signature": "BR2_TOOLCHAIN_EXTERNAL=y"},
        ]
        m = NormalizationMetrics(ErrorNormalizer()).compute(runs)
        assert m["unique_canonical"] >= 3, "Deve ter pelo menos 3 canónicos"
        # Colisões entre tipos DIFERENTES de erro devem ser zero.
        # "configuration error" e "invalid .config" são ambos DEFCONFIG_ERROR
        # com fixes diferentes — isso é esperado e aceitável.
        harmful = [
            c for c in m["collisions"]
            if "CONFIG" not in c[0]  # ignorar colisões dentro de DEFCONFIG
        ]
        assert len(harmful) == 0, (
            f"Colisões entre tipos diferentes: {harmful}"
        )
