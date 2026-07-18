from __future__ import annotations
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class RecommendationOutcome:
    fingerprint: str
    recommended_fix: str
    applied_fix: str
    accepted: bool
    score: float
    context: str = ""
    timestamp: str = ""


SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback_loop (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    recommended_fix TEXT NOT NULL,
    applied_fix TEXT NOT NULL,
    accepted INTEGER NOT NULL,
    score REAL DEFAULT 0.0,
    context TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_fb_fingerprint ON feedback_loop(fingerprint);
CREATE INDEX IF NOT EXISTS idx_fb_accepted ON feedback_loop(accepted);
"""


class FeedbackDB:
    """Persiste outcomes de recomendações para aprendizado por reforço."""

    def __init__(self, db_path: str | Path = ".titan/feedback.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.executescript(SCHEMA)

    def _conn(self):
        return sqlite3.connect(str(self.db_path))

    def record_outcome(self, outcome: RecommendationOutcome) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO feedback_loop
                (timestamp, fingerprint, recommended_fix, applied_fix,
                 accepted, score, context)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    outcome.timestamp or datetime.now().isoformat(),
                    outcome.fingerprint,
                    outcome.recommended_fix,
                    outcome.applied_fix,
                    1 if outcome.accepted else 0,
                    outcome.score,
                    outcome.context,
                ),
            )
            return cur.lastrowid or 0

    def acceptance_rate(self, fingerprint: str) -> float:
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT AVG(accepted) FROM feedback_loop WHERE fingerprint = ?",
                (fingerprint,),
            )
            row = cur.fetchone()
            return row[0] if row and row[0] is not None else 0.0

    def best_fix(self, fingerprint: str) -> Optional[str]:
        """Fix com maior taxa de sucesso para este fingerprint."""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                """SELECT applied_fix, AVG(accepted) as rate, COUNT(*) as n
                FROM feedback_loop WHERE fingerprint = ?
                GROUP BY applied_fix
                ORDER BY rate DESC, n DESC LIMIT 1""",
                (fingerprint,),
            )
            row = cur.fetchone()
            return row["applied_fix"] if row else None

    def recent_feedback(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT * FROM feedback_loop ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in cur.fetchall()]


class FeedbackLoop:
    """Regista resultados reais de recomendações.

    Cada vez que uma recomendação é aplicada, registamos:
      - O que foi recomendado
      - O que foi realmente aplicado
      - Se funcionou (accepted) e score

    Isto permite aprendizado por reforço ao longo do tempo.
    """

    def __init__(self, db: FeedbackDB | None = None):
        self.db = db or FeedbackDB()

    def record(self, fingerprint: str, recommended_fix: str,
               applied_fix: str = "", accepted: bool = False,
               score: float = 0.0, context: str = "") -> int:
        outcome = RecommendationOutcome(
            fingerprint=fingerprint,
            recommended_fix=recommended_fix,
            applied_fix=applied_fix or recommended_fix,
            accepted=accepted,
            score=score,
            context=context,
            timestamp=datetime.now().isoformat(),
        )
        return self.db.record_outcome(outcome)

    def fix_effectiveness(self, fingerprint: str) -> Dict[str, Any]:
        rate = self.db.acceptance_rate(fingerprint)
        best = self.db.best_fix(fingerprint)
        return {
            "fingerprint": fingerprint,
            "acceptance_rate": round(rate, 3),
            "best_fix": best or "",
        }
