from __future__ import annotations
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS validation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    validation_level TEXT DEFAULT 'BASIC',
    score REAL NOT NULL,
    accepted INTEGER NOT NULL,
    error_category TEXT,
    error_fingerprint TEXT,
    fix_signature TEXT,
    execution_time REAL,
    workspace_hash TEXT,
    twin_snapshot_id TEXT,
    summary TEXT,
    raw_data TEXT,
    metadata TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_skill ON validation_runs(skill_name);
CREATE INDEX IF NOT EXISTS idx_runs_score ON validation_runs(score);
CREATE INDEX IF NOT EXISTS idx_runs_error ON validation_runs(error_fingerprint);
CREATE INDEX IF NOT EXISTS idx_runs_timestamp ON validation_runs(timestamp);
"""


class ValidationDB:
    """Persistência SQLite para execuções de validação."""

    def __init__(self, db_path: str | Path = ".titan/validation.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.executescript(SCHEMA_SQL)

    def _conn(self):
        return sqlite3.connect(str(self.db_path))

    def insert_run(self, run: dict) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO validation_runs
                (timestamp, skill_name, validation_level, score, accepted,
                 error_category, error_fingerprint, fix_signature,
                 execution_time, workspace_hash, twin_snapshot_id,
                 summary, raw_data, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run.get("timestamp", datetime.now().isoformat()),
                    run.get("skill_name", "unknown"),
                    run.get("validation_level", "BASIC"),
                    run.get("score", 0.0),
                    1 if run.get("accepted", False) else 0,
                    run.get("error_category"),
                    run.get("error_fingerprint"),
                    run.get("fix_signature"),
                    run.get("execution_time"),
                    run.get("workspace_hash"),
                    run.get("twin_snapshot_id"),
                    run.get("summary", ""),
                    json.dumps(run.get("raw_data", {})),
                    json.dumps(run.get("metadata", {})),
                ),
            )
            return cur.lastrowid or 0

    def get_run(self, run_id: int) -> Optional[dict]:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT * FROM validation_runs WHERE id = ?", (run_id,))
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_dict(row)

    def list_runs(self, skill_name: str | None = None,
                  limit: int = 50, offset: int = 0) -> List[dict]:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            if skill_name:
                cur = conn.execute(
                    "SELECT * FROM validation_runs WHERE skill_name = ? ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                    (skill_name, limit, offset),
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM validation_runs ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )
            return [self._row_to_dict(row) for row in cur.fetchall()]

    def count_runs(self, skill_name: str | None = None) -> int:
        with self._conn() as conn:
            if skill_name:
                cur = conn.execute("SELECT COUNT(*) FROM validation_runs WHERE skill_name = ?", (skill_name,))
            else:
                cur = conn.execute("SELECT COUNT(*) FROM validation_runs")
            row = cur.fetchone()
            return row[0] if row else 0

    def best_score(self, skill_name: str) -> Optional[float]:
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT MAX(score) FROM validation_runs WHERE skill_name = ? AND accepted = 1",
                (skill_name,),
            )
            row = cur.fetchone()
            return row[0] if row and row[0] is not None else None

    def worst_score(self, skill_name: str) -> Optional[float]:
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT MIN(score) FROM validation_runs WHERE skill_name = ?",
                (skill_name,),
            )
            row = cur.fetchone()
            return row[0] if row and row[0] is not None else None

    def delete_all(self):
        with self._conn() as conn:
            conn.execute("DELETE FROM validation_runs")

    def close(self):
        pass

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["accepted"] = bool(d["accepted"])
        return d
