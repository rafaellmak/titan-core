from __future__ import annotations
from typing import Dict

from .models import WorkspaceFingerprint


DELIMITER = "/"

FINGERPRINT_FIELDS = [
    "workspace_type", "architecture", "toolchain", "libc",
    "board", "kernel_version", "buildroot_version", "yocto_release",
]


def compute(fingerprint: WorkspaceFingerprint) -> str:
    parts = [
        _val(getattr(fingerprint, f, ""))
        for f in FINGERPRINT_FIELDS
    ]
    return DELIMITER.join(parts)


def parse(fp_str: str) -> WorkspaceFingerprint:
    parts = fp_str.split(DELIMITER)
    kwargs: Dict[str, str] = {}
    for i, f in enumerate(FINGERPRINT_FIELDS):
        val = parts[i] if i < len(parts) else ""
        kwargs[f] = "" if val in ("any", "unknown") else val
    return WorkspaceFingerprint(**kwargs)


def _val(s: str) -> str:
    s = s.strip().lower().replace(" ", "_")
    return s if s else "any"
