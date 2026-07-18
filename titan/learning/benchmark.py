from __future__ import annotations
from typing import Any, Dict, List, Optional

from titan.validation.history import ValidationHistory
from titan.validation.persistence import ValidationDB
from .patterns import PatternDB
from .engine import LearningEngine
from .recommender import Recommender
from .normalizer import ErrorNormalizer
from .replay import ReplayRunner


class LearningBenchmark:
    """Benchmark do pipeline de aprendizado.

    Métricas:
      - Top-1 / Top-3 Accuracy
      - Recommendation Recall
      - Learning Score (média ponderada das métricas anteriores)
      - Confusion matrix por fingerprint
    """

    def __init__(self, history: ValidationHistory,
                 engine: Optional[LearningEngine] = None,
                 recommender: Optional[Recommender] = None):
        self.history = history
        self.engine = engine or LearningEngine(history)
        self.recommender = recommender or Recommender(self.engine)
        self.results: Dict[str, Any] = {}

    def run(self, skill_name: Optional[str] = None) -> Dict[str, Any]:
        runner = ReplayRunner(self.history, self.engine, self.recommender)
        summary = runner.replay(skill_name=skill_name)

        top1 = summary.get("top1_accuracy", 0)
        top3 = summary.get("top3_accuracy", 0)
        recall = summary.get("recommendation_recall", 0)
        learning_score = round((top1 * 0.5 + top3 * 0.3 + recall * 0.2) * 100, 2)

        category_breakdown = runner.replay_by_category()
        confusion = self._build_confusion(runner.results)

        self.results = {
            "top1_accuracy": top1,
            "top3_accuracy": top3,
            "recommendation_recall": recall,
            "learning_score": learning_score,
            "total_runs": summary.get("total_runs", 0),
            "top1_matches": summary.get("top1_matches", 0),
            "top3_matches": summary.get("top3_matches", 0),
            "empty_recommendations": summary.get("empty_recommendations", 0),
            "categories": category_breakdown,
            "confusion": confusion,
            "grade": self._grade(learning_score),
        }
        return self.results

    def report(self) -> str:
        r = self.results
        if not r:
            return "No benchmark results. Call run() first."

        lines = [
            "=" * 50,
            "LearningBenchmark Report",
            "=" * 50,
            f"  Learning Score:  {r.get('learning_score', 0):.1f}/100  ({r.get('grade', '—')})",
            "",
            f"  Top-1 Accuracy:  {r.get('top1_accuracy', 0):.2%}  ({r.get('top1_matches', 0)}/{r.get('total_runs', 0)})",
            f"  Top-3 Accuracy:  {r.get('top3_accuracy', 0):.2%}  ({r.get('top3_matches', 0)}/{r.get('total_runs', 0)})",
            f"  Recommendation Recall: {r.get('recommendation_recall', 0):.2%}",
            f"  Empty recommendations: {r.get('empty_recommendations', 0)}",
            "",
            "By Category:",
        ]

        cats = r.get("categories", {})
        for cat in sorted(cats.keys()):
            d = cats[cat]
            lines.append(
                f"  {cat:<20s}  total={d['total']:>4d}"
                f"  top1={d['top1_accuracy']:.0%}  top3={d['top3_accuracy']:.0%}"
            )

        confusion = r.get("confusion", {})
        if confusion:
            lines.append("")
            lines.append("Top Confusion Entries (actual_fix != top1_fix):")
            for entry in confusion[:5]:
                lines.append(
                    f"  fp={entry['fingerprint']:<40s}"
                    f"  actual={entry['actual_fix']:<30s}"
                    f"  top1={entry['top1_fix']:<30s}"
                )

        lines.append("")
        return "\n".join(lines)

    def _build_confusion(self, results: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        mismatches = [
            r for r in results
            if r.get("actual_fix") and r.get("top1_fix") and not r.get("is_match")
        ]
        seen = set()
        unique: List[Dict[str, str]] = []
        for r in mismatches:
            key = (r["fingerprint"], r["actual_fix"], r["top1_fix"])
            if key not in seen:
                seen.add(key)
                unique.append({
                    "fingerprint": r["fingerprint"],
                    "category": r.get("category", ""),
                    "actual_fix": r["actual_fix"],
                    "top1_fix": r["top1_fix"],
                })
        return unique[:10]

    @staticmethod
    def _grade(score: float) -> str:
        if score >= 90:
            return "A"
        elif score >= 75:
            return "B"
        elif score >= 60:
            return "C"
        elif score >= 40:
            return "D"
        return "F"
