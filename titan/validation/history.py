from __future__ import annotations
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from .contracts import ErrorSignature, SkillResult, ValidationResult
from .persistence import ValidationDB


class ValidationHistory:
    """Histórico persistente de execuções de validação.

    Cada execução do harness é registada com:
      - Skill + Score + Accepted
      - ErrorSignature (categoria + fingerprint)
      - Fix signature
      - Workspace hash e twin snapshot
      - Tempo de execução
    """

    def __init__(self, db: ValidationDB | None = None):
        self.db = db or ValidationDB()
        self._current_run: Optional[dict] = None

    def start_run(self, skill_name: str) -> None:
        self._current_run = {
            "skill_name": skill_name,
            "start_time": time.time(),
            "timestamp": datetime.now().isoformat(),
        }

    def finish_run(
        self,
        result: SkillResult,
        validation: ValidationResult,
        error_sig: ErrorSignature | None = None,
        fix_signature: str = "",
        workspace_hash: str = "",
        twin_snapshot_id: str = "",
        metadata: dict | None = None,
    ) -> int:
        elapsed = time.time() - self._current_run.get("start_time", time.time()) if self._current_run else 0.0
        if error_sig is None:
            error_sig = ErrorSignature.from_raw(result.raw, result.skill_name)

        run = {
            "skill_name": result.skill_name,
            "validation_level": "BASIC",
            "score": validation.score,
            "accepted": validation.accepted,
            "error_category": error_sig.category,
            "error_fingerprint": error_sig.fingerprint,
            "fix_signature": fix_signature,
            "execution_time": round(elapsed, 3),
            "workspace_hash": workspace_hash,
            "twin_snapshot_id": twin_snapshot_id,
            "summary": result.summary,
            "raw_data": {
                "raw": result.raw,
                "checks": [c.to_dict() if hasattr(c, 'to_dict') else {"name": c.name, "passed": c.passed}
                          for c in validation.checks],
            },
            "metadata": metadata or {},
        }
        run_id = self.db.insert_run(run)
        self._current_run = None
        return run_id

    def recent(self, skill_name: str | None = None, limit: int = 20) -> List[dict]:
        return self.db.list_runs(skill_name=skill_name, limit=limit)

    def best(self, skill_name: str) -> Optional[float]:
        return self.db.best_score(skill_name)

    def worst(self, skill_name: str) -> Optional[float]:
        return self.db.worst_score(skill_name)

    def average_score(self, skill_name: str | None = None) -> float:
        total = self.db.count_runs(skill_name)
        if total == 0:
            return 0.0
        runs = self.db.list_runs(skill_name=skill_name, limit=total)
        scores = [r["score"] for r in runs if r["score"] is not None]
        if not scores:
            return 0.0
        return round(sum(scores) / len(scores), 1)

    def acceptance_rate(self, skill_name: str | None = None) -> float:
        total = self.db.count_runs(skill_name)
        if total == 0:
            return 0.0
        runs = self.db.list_runs(skill_name=skill_name, limit=total)
        accepted = sum(1 for r in runs if r.get("accepted"))
        return round((accepted / total) * 100, 1)

    def top_errors(self, skill_name: str | None = None, limit: int = 10) -> List[dict]:
        runs = self.db.list_runs(skill_name=skill_name, limit=10000)
        counts: Dict[str, dict] = {}
        for r in runs:
            key = r.get("error_fingerprint", "unknown")
            if key not in counts:
                counts[key] = {
                    "fingerprint": key,
                    "category": r.get("error_category", "unknown"),
                    "count": 0,
                    "avg_score": 0.0,
                    "last_seen": r.get("timestamp", ""),
                }
            c = counts[key]
            c["count"] += 1
            c["avg_score"] = ((c["avg_score"] * (c["count"] - 1)) + (r.get("score") or 0)) / c["count"]
            if r.get("timestamp", "") > c["last_seen"]:
                c["last_seen"] = r["timestamp"]

        sorted_errors = sorted(counts.values(), key=lambda x: x["count"], reverse=True)
        return sorted_errors[:limit]

    def trend(self, skill_name: str, window: int = 10) -> List[dict]:
        """Retorna scores recentes para análise de tendência."""
        runs = self.db.list_runs(skill_name=skill_name, limit=window)
        return [
            {"id": r["id"], "score": r["score"], "accepted": r["accepted"], "timestamp": r["timestamp"]}
            for r in reversed(runs)
        ]
