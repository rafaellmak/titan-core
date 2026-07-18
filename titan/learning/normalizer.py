from __future__ import annotations
import re
from typing import Dict, List, Optional

# Mapas canónicos: variações de erro → fingerprint normalizado
# Regras de ordenação (CRÍTICO — dict iteration order define matching order):
#   1. Patterns mais específicos PRIMEIROS (ex: toolchain specific
#      antes de "cannot find (.+)" genérico que pode roubar toolchain)
#   2. Patterns com capture group antes de exact match do mesmo tipo
#   3. Cada fingerprint canónico deve representar UM tipo de problema
#      com UMA família de fixes
#   4. Catch-all genéricos (ex: "exit code", "missing (.+)") sempre ÚLTIMOS

BUILDROOT_PATTERNS: Dict[str, List[str]] = {
    # Toolchain — específicos primeiro para não serem roubados por "cannot find (.+)"
    "BUILDROOT_TOOLCHAIN_MISSING": [
        "toolchain not found",
        "no toolchain",
    ],
    "BUILDROOT_TOOLCHAIN_PATH_ERROR": [
        "cannot find toolchain",
    ],
    "BUILDROOT_TOOLCHAIN_UNSUPPORTED": [
        "toolchain unsupported",
        "toolchain is unsupported",
        "unsupported toolchain version",
    ],
    "BUILDROOT_TOOLCHAIN_LOAD_ERROR": [
        "unable to load toolchain",
    ],
    "BUILDROOT_TOOLCHAIN_CONFIG": [
        "cross compile toolchain",
    ],
    "BUILDROOT_TOOLCHAIN_ERROR": [
        "toolchain error",
    ],
    # Kernel
    "BUILDROOT_KERNEL_NOT_ENABLED": [
        "kernel not configured",
        "BR2_LINUX_KERNEL is not set",
    ],
    "BUILDROOT_KERNEL_NOT_FOUND": [
        "linux(.+) not found",
        "kernel .+ not found",
    ],
    "BUILDROOT_KERNEL_CONFIG_MISSING": [
        "kernel .+ missing",
        "kernel config missing",
    ],
    "BUILDROOT_KERNEL_BUILD_FAILURE": [
        "cannot build kernel",
    ],
    # Defconfig
    "BUILDROOT_DEFCONFIG_ERROR": [
        "configuration error",
        "invalid .config",
        "config .+ not set",
        "unset configuration",
    ],
    # Generic catch-all — ÚLTIMO para evitar roubo de patterns específicos
    "BUILDROOT_MISSING_PACKAGE": [
        "missing (.+)", "package (.+) not found", "(.+) dependency missing",
        "(.+) unavailable", "cannot find (.+)", "(.+) is not selected",
        "(.+) is in the dependency of", "(.+) not present",
        "BR2_PACKAGE_(.+) is not set",
    ],
}

YOCTO_PATTERNS: Dict[str, List[str]] = {
    # Task-specific failures — PRIMEIROS para não serem roubados por "exit code"
    "YOCTO_COMPILE_FAILURE": [
        "task do_compile failed",
        "do_compile failed",
    ],
    "YOCTO_INSTALL_FAILURE": [
        "do_install failed",
    ],
    "YOCTO_CONFIGURE_FAILURE": [
        "function do_configure failed",
    ],
    # Package/dependency patterns
    "YOCTO_NOTHING_PROVIDES": [
        "nothing provides (.+)", "(.+) not provided", "unable to satisfy (.+)",
        "no recipe provides (.+)", "(.+) is not available",
    ],
    "YOCTO_RDEPENDS_ERROR": [
        "rdepends on (.+)",
    ],
    "YOCTO_BUILD_DEPENDENCY": [
        "build dependency",
    ],
    # Parse/QA
    "YOCTO_PARSE_ERROR": [
        "parsing error", "parse error", "syntax error in (.+)",
        "bbclass (.+) not found",
    ],
    "YOCTO_LICENSE_ERROR": [
        "installed (.+) in image",
    ],
    "YOCTO_QA_WARNING": [
        "qa issue",
        "qa warning",
    ],
    # Generic catch-all — ÚLTIMO para não roubar patterns específicos
    "YOCTO_GENERIC_FAILURE": [
        "exit code",
    ],
}

DTS_PATTERNS: Dict[str, List[str]] = {
    "DTS_SYNTAX_ERROR": [
        "dtc error",
        "syntax error",
    ],
    "DTS_COMPILATION_FAILED": [
        "compilation failed",
    ],
    "DTS_PARSE_ERROR": [
        "unable to parse dts",
    ],
    "DTS_INVALID_PROPERTY": [
        "(.+) is not valid",
    ],
    "DTS_BINDING_ERROR": [
        "binding check failed",
        "(.+) not compatible",
        "(.+) binding mismatch",
    ],
    "DTS_BINDING_MISSING": [
        "binding .+ not found",
    ],
    "DTS_CLOCK_REFERENCE_ERROR": [
        "binding clock not found",
        "clocks .+ not found",
    ],
    "DTS_REG_BINDING_ERROR": [
        "reg binding mismatch",
    ],
}

SECURITY_PATTERNS: Dict[str, List[str]] = {
    "SECURITY_CRITICAL_CVE": [
        "(cve-\\d+-\\d+) critical",          # CVE-2023-38545 critical
        "critical (cve-\\d+-\\d+)",           # critical CVE-2023-44487 found
        "unpatched (.+) cve",                  # unpatched openssl CVE critical
        "(cve-\\d+-\\d+) detected",            # CVE-2024-0001 detected
    ],
    "SECURITY_HIGH_CVE": [
        "(cve-\\d+-\\d+) high",               # CVE-2023-45871 high severity
        "high (cve-\\d+-\\d+)",                # high CVE-2023-45871 found
        "vulnerability (.+) unpatched",         # vulnerability nginx unpatched
        "(cve-\\d+-\\d+) found",               # CVE-2023-45871 found in package
    ],
}

# Mapa consolidado: categoria → {canonical → regex list}
CANONICAL_PATTERNS: Dict[str, Dict[str, List[str]]] = {
    "BuildrootError": BUILDROOT_PATTERNS,
    "YoctoError": YOCTO_PATTERNS,
    "DTSError": DTS_PATTERNS,
    "SecurityError": SECURITY_PATTERNS,
}


class ErrorNormalizer:
    """Normaliza variações de erro num fingerprint canónico.

    Exemplo:
      "missing openssl"  → "BUILDROOT_MISSING_PACKAGE:openssl"
      "Nothing PROVIDES python3" → "YOCTO_NOTHING_PROVIDES:python3"
      "openssl not found" → "BUILDROOT_MISSING_PACKAGE:openssl"

    Cada fingerprint canónico representa um tipo de problema.
    Dois erros com fixes diferentes NUNCA devem partilhar o mesmo fingerprint.
    """

    def __init__(self, custom_patterns: Optional[Dict[str, Dict[str, List[str]]]] = None):
        self.patterns = CANONICAL_PATTERNS.copy()
        if custom_patterns:
            self._merge_patterns(custom_patterns)
        self._compiled: Dict[str, List[tuple[str, re.Pattern]]] = {}
        self._build_cache()

    def normalize(self, error_fingerprint: str, category: str = "") -> str:
        """Retorna fingerprint normalizado ou o original se não houver correspondência."""
        text = error_fingerprint.strip().lower()
        if not text:
            return "unknown"

        # Tenta matching com patterns da categoria
        candidates = self._compiled.get(category, [])
        if not candidates:
            # fallback: tenta todas as categorias
            candidates = [(c, p) for cat in self._compiled.values() for (c, p) in cat]

        for canonical_name, pattern in candidates:
            m = pattern.search(text)
            if m:
                captured = m.group(1).strip() if m.lastindex and m.group(1) else ""
                if captured:
                    return f"{canonical_name}:{captured}"
                return canonical_name

        # Se falhou, extrai a palavra-chave principal
        # "missing openssl dependency" → "MISSING_OPENSSL"
        words = re.findall(r'[a-zA-Z_][a-zA-Z0-9_.-]*', error_fingerprint.strip())
        significant = [w.upper() for w in words if len(w) > 2][:4]
        if significant:
            return "_".join(significant)
        return error_fingerprint.strip().upper().replace(" ", "_")[:100]

    def add_rule(self, category: str, canonical: str, regex: str) -> None:
        if category not in self.patterns:
            self.patterns[category] = {}
        if canonical not in self.patterns[category]:
            self.patterns[category][canonical] = []
        self.patterns[category][canonical].append(regex)
        self._build_cache()

    def known_patterns(self) -> Dict[str, Dict[str, str]]:
        result: Dict[str, Dict[str, str]] = {}
        for cat, canonicals in CANONICAL_PATTERNS.items():
            result[cat] = {c: " | ".join(variants) for c, variants in canonicals.items()}
        return result

    def _merge_patterns(self, custom: Dict[str, Dict[str, List[str]]]) -> None:
        for cat, canonicals in custom.items():
            if cat not in self.patterns:
                self.patterns[cat] = {}
            for canonical, regexes in canonicals.items():
                if canonical not in self.patterns[cat]:
                    self.patterns[cat][canonical] = []
                self.patterns[cat][canonical].extend(regexes)

    def _build_cache(self) -> None:
        self._compiled.clear()
        for cat, canonicals in self.patterns.items():
            entries: List[tuple[str, re.Pattern]] = []
            for canonical, regexes in canonicals.items():
                for regex in regexes:
                    try:
                        compiled = re.compile(regex, re.IGNORECASE)
                        entries.append((canonical, compiled))
                    except re.error:
                        pass
            if entries:
                self._compiled[cat] = entries
