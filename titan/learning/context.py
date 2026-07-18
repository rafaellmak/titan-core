from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


class WorkspaceContext:
    """Contexto extraído de um workspace onde um erro ocorreu.

    Usado para ranquear correções por compatibilidade contextual.
    """

    def __init__(self, arch: str = "", toolchain: str = "", category: str = "",
                 distro: str = "", kernel: str = "", board: str = "",
                 raw: Optional[Dict[str, Any]] = None):
        self.arch = arch
        self.toolchain = toolchain
        self.category = category
        self.distro = distro
        self.kernel = kernel
        self.board = board
        self.raw = raw or {}

    def to_dict(self) -> Dict[str, str]:
        return {
            "arch": self.arch,
            "toolchain": self.toolchain,
            "category": self.category,
            "distro": self.distro,
            "kernel": self.kernel,
            "board": self.board,
        }

    @staticmethod
    def from_run(run: dict) -> WorkspaceContext:
        metadata = run.get("metadata", {})
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (json.JSONDecodeError, TypeError):
                metadata = {}
        raw = metadata.get("workspace", {}) if isinstance(metadata, dict) else {}
        return WorkspaceContext(
            arch=raw.get("arch", "") or "",
            toolchain=raw.get("toolchain", "") or raw.get("toolchain_type", "") or "",
            category=raw.get("category", "") or "",
            distro=raw.get("distro", "") or "",
            kernel=raw.get("kernel_version", "") or raw.get("kernel", "") or "",
            board=raw.get("board", "") or raw.get("machine", "") or "",
            raw=raw if isinstance(raw, dict) else {},
        )

    def similarity(self, other: WorkspaceContext) -> float:
        """Similaridade contextual: 0.0 (diferente) a 1.0 (idêntico)."""
        score = 0.0
        total = 0
        for attr in ["arch", "toolchain", "category", "distro", "kernel", "board"]:
            a = getattr(self, attr, "") or ""
            b = getattr(other, attr, "") or ""
            total += 1
            if a and b and a.lower() == b.lower():
                score += 1.0
            elif a and b:
                score += 0.3  # ambos definidos mas diferentes
        return score / total if total > 0 else 0.0


SCHEMA = """
CREATE TABLE IF NOT EXISTS pattern_context (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL,
    arch TEXT DEFAULT '',
    toolchain TEXT DEFAULT '',
    category TEXT DEFAULT '',
    distro TEXT DEFAULT '',
    kernel TEXT DEFAULT '',
    board TEXT DEFAULT '',
    occurrences INTEGER DEFAULT 0,
    success_rate REAL DEFAULT 0.0,
    average_score REAL DEFAULT 0.0,
    best_fix TEXT DEFAULT '',
    last_seen TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_ctx_fingerprint ON pattern_context(fingerprint);
CREATE INDEX IF NOT EXISTS idx_ctx_arch ON pattern_context(arch);
CREATE INDEX IF NOT EXISTS idx_ctx_toolchain ON pattern_context(toolchain);
"""


class PatternContextDB:
    """Armazena desempenho de padrões por contexto de workspace.

    Permite responder: "este fix funciona para aarch64 + glibc?"
    """

    def __init__(self, db_path: str | Path = ".titan/pattern_context.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.executescript(SCHEMA)

    def _conn(self):
        return sqlite3.connect(str(self.db_path))

    def upsert_context(self, fingerprint: str, ctx: WorkspaceContext,
                       score: float = 0.0, accepted: bool = True,
                       fix: str = "") -> None:
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT occurrences, success_rate, average_score FROM pattern_context "
                "WHERE fingerprint = ? AND arch = ? AND toolchain = ? AND category = ? "
                "AND distro = ? AND kernel = ? AND board = ?",
                (fingerprint, ctx.arch, ctx.toolchain, ctx.category,
                 ctx.distro, ctx.kernel, ctx.board),
            ).fetchone()

            if existing:
                occ, old_rate, old_avg = existing
                n = occ + 1
                new_rate = ((old_rate * occ) + (1 if accepted else 0)) / n
                new_avg = ((old_avg * occ) + score) / n
                conn.execute(
                    """UPDATE pattern_context SET occurrences = ?, success_rate = ?,
                    average_score = ?, best_fix = ?, last_seen = datetime('now')
                    WHERE fingerprint = ? AND arch = ? AND toolchain = ? AND category = ?
                    AND distro = ? AND kernel = ? AND board = ?""",
                    (n, round(new_rate, 3), round(new_avg, 1), fix,
                     fingerprint, ctx.arch, ctx.toolchain, ctx.category,
                     ctx.distro, ctx.kernel, ctx.board),
                )
            else:
                conn.execute(
                    """INSERT INTO pattern_context
                    (fingerprint, arch, toolchain, category, distro, kernel, board,
                     occurrences, success_rate, average_score, best_fix, last_seen)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, datetime('now'))""",
                    (fingerprint, ctx.arch, ctx.toolchain, ctx.category,
                     ctx.distro, ctx.kernel, ctx.board,
                     1.0 if accepted else 0.0, round(score, 1), fix),
                )

    def search_by_context(self, fingerprint: str, ctx: WorkspaceContext,
                          limit: int = 5) -> List[Dict[str, Any]]:
        """Retorna contextos similares ordenados por match."""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                """SELECT * FROM pattern_context
                WHERE fingerprint = ?
                ORDER BY
                    CASE WHEN arch = ? THEN 2 ELSE 0 END +
                    CASE WHEN toolchain = ? THEN 2 ELSE 0 END +
                    CASE WHEN category = ? THEN 1 ELSE 0 END +
                    CASE WHEN distro = ? THEN 1 ELSE 0 END +
                    CASE WHEN kernel = ? THEN 1 ELSE 0 END +
                    CASE WHEN board = ? THEN 2 ELSE 0 END DESC,
                    success_rate DESC,
                    occurrences DESC
                LIMIT ?""",
                (fingerprint, ctx.arch, ctx.toolchain, ctx.category,
                 ctx.distro, ctx.kernel, ctx.board, limit),
            )
            return [dict(row) for row in cur.fetchall()]

    def delete_all(self):
        with self._conn() as conn:
            conn.execute("DELETE FROM pattern_context")
