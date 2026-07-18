from __future__ import annotations
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class LearnedPattern:
    fingerprint: str
    category: str
    occurrences: int = 0
    success_rate: float = 0.0
    average_score: float = 0.0
    best_fix: str = ""
    first_seen: str = ""
    last_seen: str = ""
    top_fixes: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "category": self.category,
            "occurrences": self.occurrences,
            "success_rate": round(self.success_rate, 3),
            "average_score": round(self.average_score, 1),
            "best_fix": self.best_fix,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "top_fixes": dict(sorted(self.top_fixes.items(), key=lambda x: -x[1])[:5]),
        }


SCHEMA = """
CREATE TABLE IF NOT EXISTS learned_patterns (
    fingerprint TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    occurrences INTEGER DEFAULT 0,
    success_rate REAL DEFAULT 0.0,
    average_score REAL DEFAULT 0.0,
    best_fix TEXT DEFAULT '',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    top_fixes TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_patterns_category ON learned_patterns(category);
CREATE INDEX IF NOT EXISTS idx_patterns_score ON learned_patterns(average_score DESC);
CREATE INDEX IF NOT EXISTS idx_patterns_occurrences ON learned_patterns(occurrences DESC);
"""


class PatternDB:
    def __init__(self, db_path: str | Path = ".titan/patterns.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.executescript(SCHEMA)

    def _conn(self):
        return sqlite3.connect(str(self.db_path))

    def upsert_pattern(self, pattern: LearnedPattern) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO learned_patterns
                (fingerprint, category, occurrences, success_rate, average_score,
                 best_fix, first_seen, last_seen, top_fixes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    occurrences = excluded.occurrences,
                    success_rate = excluded.success_rate,
                    average_score = excluded.average_score,
                    best_fix = excluded.best_fix,
                    last_seen = excluded.last_seen,
                    top_fixes = excluded.top_fixes""",
                (
                    pattern.fingerprint,
                    pattern.category,
                    pattern.occurrences,
                    pattern.success_rate,
                    pattern.average_score,
                    pattern.best_fix,
                    pattern.first_seen,
                    pattern.last_seen,
                    json.dumps(pattern.top_fixes),
                ),
            )

    def get_pattern(self, fingerprint: str) -> Optional[LearnedPattern]:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT * FROM learned_patterns WHERE fingerprint = ?", (fingerprint,)
            )
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_pattern(row)

    def search_patterns(self, query: str, limit: int = 10) -> List[LearnedPattern]:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                """SELECT * FROM learned_patterns
                WHERE fingerprint LIKE ? OR category LIKE ?
                ORDER BY occurrences DESC, success_rate DESC
                LIMIT ?""",
                (f"%{query}%", f"%{query}%", limit),
            )
            return [self._row_to_pattern(row) for row in cur.fetchall()]

    def top_patterns(self, category: str | None = None, limit: int = 10) -> List[LearnedPattern]:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            if category:
                cur = conn.execute(
                    """SELECT * FROM learned_patterns WHERE category = ?
                    ORDER BY occurrences DESC, success_rate DESC LIMIT ?""",
                    (category, limit),
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM learned_patterns ORDER BY occurrences DESC, success_rate DESC LIMIT ?",
                    (limit,),
                )
            return [self._row_to_pattern(row) for row in cur.fetchall()]

    def count_patterns(self, category: str | None = None) -> int:
        with self._conn() as conn:
            if category:
                cur = conn.execute("SELECT COUNT(*) FROM learned_patterns WHERE category = ?", (category,))
            else:
                cur = conn.execute("SELECT COUNT(*) FROM learned_patterns")
            return cur.fetchone()[0] or 0

    def delete_all(self) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM learned_patterns")

    @staticmethod
    def _row_to_pattern(row: sqlite3.Row) -> LearnedPattern:
        top_fixes_raw = row["top_fixes"]
        if isinstance(top_fixes_raw, str):
            top_fixes = json.loads(top_fixes_raw) if top_fixes_raw else {}
        elif isinstance(top_fixes_raw, dict):
            top_fixes = top_fixes_raw
        else:
            top_fixes = {}
        return LearnedPattern(
            fingerprint=row["fingerprint"],
            category=row["category"],
            occurrences=row["occurrences"],
            success_rate=row["success_rate"],
            average_score=row["average_score"],
            best_fix=row["best_fix"],
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
            top_fixes=top_fixes,
        )
