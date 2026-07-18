#!/usr/bin/env python3
"""Contextual Benchmark — same error, 5 contexts, verify ranking changes."""
import tempfile, json
from pathlib import Path
from titan.learning.patterns import PatternDB, LearnedPattern
from titan.learning.ranking import RankingEngine
from titan.learning.feedback import FeedbackLoop, FeedbackDB
from titan.learning.context import PatternContextDB, WorkspaceContext
from titan.context.models import WorkspaceFingerprint
from titan.context.similarity import compare as context_compare

TMP = Path(tempfile.mkdtemp())
P_DB = PatternDB(db_path=str(TMP / "patterns.db"))
C_DB = PatternContextDB(db_path=str(TMP / "ctx.db"))
F_DB = FeedbackDB(db_path=str(TMP / "fb.db"))
FEEDBACK = FeedbackLoop(F_DB)
RANKING = RankingEngine(pattern_db=P_DB, context_db=C_DB, feedback=FEEDBACK)

ERROR = "missing openssl"
FIX_A = "BR2_PACKAGE_OPENSSL=y"
FIX_B = "BR2_PACKAGE_LIBRESSL=y"

# ── Seed 3 patterns for the same error ──────────────────────────
PATTERNS = {
    "BUILDROOT_MISSING_PACKAGE:openssl": LearnedPattern(
        fingerprint="BUILDROOT_MISSING_PACKAGE:openssl",
        category="BuildrootError", occurrences=50, success_rate=0.94,
        average_score=88.0, best_fix=FIX_A,
        top_fixes={FIX_A: 47, "BR2_PACKAGE_NETTLE=y": 3},
    ),
    "BUILDROOT_MISSING_PACKAGE:libressl": LearnedPattern(
        fingerprint="BUILDROOT_MISSING_PACKAGE:libressl",
        category="BuildrootError", occurrences=20, success_rate=0.80,
        average_score=75.0, best_fix=FIX_B,
        top_fixes={FIX_B: 16, FIX_A: 4},
    ),
    "BUILDROOT_MISSING_PACKAGE:nettle": LearnedPattern(
        fingerprint="BUILDROOT_MISSING_PACKAGE:nettle",
        category="BuildrootError", occurrences=5, success_rate=0.60,
        average_score=65.0, best_fix="BR2_PACKAGE_NETTLE=y",
        top_fixes={"BR2_PACKAGE_NETTLE=y": 3},
    ),
}
for p in PATTERNS.values():
    P_DB.upsert_pattern(p)

# ── Seed context history ────────────────────────────────────────
CONTEXTS = {
    "openssl_aarch64": WorkspaceContext(
        arch="aarch64", toolchain="gcc_external", category="BuildrootError",
        distro="buildroot", kernel="5.15", board="raspberrypi4",
    ),
    "openssl_x86": WorkspaceContext(
        arch="x86_64", toolchain="internal", category="BuildrootError",
        distro="ubuntu", kernel="6.1", board="pc_x86_64",
    ),
}

# openssl fix has strong history on aarch64
for _ in range(30):
    C_DB.upsert_context("BUILDROOT_MISSING_PACKAGE:openssl", CONTEXTS["openssl_aarch64"],
                        score=90, accepted=True, fix=FIX_A)
# libressl fix tried on x86 a few times
for _ in range(5):
    C_DB.upsert_context("BUILDROOT_MISSING_PACKAGE:libressl", CONTEXTS["openssl_x86"],
                        score=75, accepted=True, fix=FIX_B)

# ── 5 test contexts ─────────────────────────────────────────────
TEST_CONTEXTS = [
    ("aarch64 + glibc + Buildroot 2025", WorkspaceFingerprint(
        workspace_type="buildroot", architecture="aarch64",
        toolchain="gcc_external", libc="glibc", board="raspberrypi4",
        kernel_version="5.15", buildroot_version="2025.02",
    )),
    ("x86_64 + glibc + Ubuntu", WorkspaceFingerprint(
        workspace_type="buildroot", architecture="x86_64",
        toolchain="internal", libc="glibc", board="pc_x86_64",
        kernel_version="6.1",
    )),
    ("armv7 + musl + Buildroot 2023", WorkspaceFingerprint(
        workspace_type="buildroot", architecture="armv7",
        toolchain="gcc", libc="musl", board="beaglebone",
        kernel_version="5.10", buildroot_version="2023.11",
    )),
    ("riscv64 + glibc + Fedora", WorkspaceFingerprint(
        workspace_type="buildroot", architecture="riscv64",
        toolchain="gcc_external", libc="glibc", board="sifive_u",
        kernel_version="6.2",
    )),
    ("yocto + aarch64 + glibc", WorkspaceFingerprint(
        workspace_type="yocto", architecture="aarch64",
        toolchain="gcc", libc="glibc", board="raspberrypi4",
        yocto_release="kirkstone",
    )),
]

# ── Run benchmark ───────────────────────────────────────────────
print("=" * 72)
print("  CONTEXTUAL BENCHMARK — mesmo erro, 5 contextos")
print("=" * 72)

all_patterns = list(PATTERNS.values())
for label, fp in TEST_CONTEXTS:
    ranked = RANKING.rank(all_patterns, fingerprint=fp, limit=3)
    top = ranked[0] if ranked else None
    print(f'\n  Contexto: {label}')
    print(f'  Fingerprint: {fp.architecture}/{fp.toolchain}/{fp.libc}/{fp.board}')
    for r in ranked:
        ctx_match = 0
        if hasattr(fp, 'architecture'):
            other = WorkspaceFingerprint(
                architecture=r.get("fingerprint", "").split(":")[-1] if ":" in r.get("fingerprint","") else "",
            )
        icon = "◀" if r == top else " "
        print(f'    {icon} {r["fingerprint"]:40s} score={r["rank_score"]:5.1f}  '
              f'fix={r["best_fix"]}')

# ── Summary ─────────────────────────────────────────────────────
print("\n" + "=" * 72)
print("  RANKING CHANGES BY CONTEXT")
print("=" * 72)
first_top = None
for label, fp in TEST_CONTEXTS:
    ranked = RANKING.rank(all_patterns, fingerprint=fp, limit=3)
    top = ranked[0] if ranked else None
    if first_top is None:
        first_top = top
    changed = top["fingerprint"] != first_top["fingerprint"] if top and first_top else False
    print(f'  {label:35s} → {top["fingerprint"]:40s}  top1={top["rank_score"]:.1f}  '
          f'{"⚡ CHANGED" if changed else "—"}')
