from __future__ import annotations
from typing import Any, Dict, List, Optional

from titan.validation.history import ValidationHistory
from .context import WorkspaceContext
from .engine import LearningEngine
from .recommender import Recommender


class ReplayRunner:
    """Replay do histórico de validações através do pipeline de aprendizado.

    Simula: histórico → aprendizado → recomendação → comparação com fix real
    Permite medir se o Titan recomendaria o mesmo fix que foi realmente usado.
    """

    def __init__(self, history: ValidationHistory,
                 engine: Optional[LearningEngine] = None,
                 recommender: Optional[Recommender] = None):
        self.history = history
        self.engine = engine or LearningEngine(history)
        self.recommender = recommender or Recommender(self.engine)
        self.results: List[Dict[str, Any]] = []
        self.summary: Dict[str, Any] = {}

    def replay(self, skill_name: Optional[str] = None) -> Dict[str, Any]:
        """Executa replay completo do histórico."""
        self.engine.learn_all()
        all_runs = self.history.recent(skill_name=skill_name, limit=100000)

        self.results = []
        matches = 0
        total = 0
        top1_matches = 0
        top3_matches = 0
        empty_recommendations = 0

        for run in all_runs:
            raw_fp = run.get("error_fingerprint", "")
            category = run.get("error_category", "")
            actual_fix = run.get("fix_signature", "") or ""

            if not raw_fp:
                continue

            normalizer = self.engine.normalizer
            norm_fp = normalizer.normalize(raw_fp, category)

            ctx = WorkspaceContext.from_run(run) if _has_context(run) else None
            recommendations = self.recommender.recommend(
                raw_fp, limit=3, context=ctx
            )

            total += 1
            recommended_fixes = [r.get("best_fix", "") for r in recommendations]
            top1 = recommended_fixes[0] if recommended_fixes else ""

            if not recommendations:
                empty_recommendations += 1

            is_match = actual_fix and top1 == actual_fix
            top3_match = actual_fix and actual_fix in recommended_fixes

            if is_match:
                matches += 1
                top1_matches += 1
            if top3_match:
                top3_matches += 1

            self.results.append({
                "run_index": len(self.results),
                "fingerprint": raw_fp,
                "normalized": norm_fp,
                "category": category,
                "actual_fix": actual_fix,
                "top1_fix": top1,
                "top3_fixes": recommended_fixes,
                "is_match": is_match,
                "top3_match": top3_match,
                "score": run.get("score", 0),
                "accepted": run.get("accepted", False),
            })

        self.summary = {
            "total_runs": total,
            "with_recommendation": total - empty_recommendations,
            "empty_recommendations": empty_recommendations,
            "top1_matches": top1_matches,
            "top3_matches": top3_matches,
            "top1_accuracy": round(top1_matches / max(total, 1), 4),
            "top3_accuracy": round(top3_matches / max(total, 1), 4),
            "recommendation_recall": round(
                (total - empty_recommendations) / max(total, 1), 4
            ),
        }
        return self.summary

    def replay_by_category(self) -> Dict[str, Dict[str, Any]]:
        """Replay agrupado por categoria de erro."""
        if not self.results:
            self.replay()

        cats: Dict[str, Dict[str, Any]] = {}
        for r in self.results:
            cat = r.get("category", "unknown")
            if cat not in cats:
                cats[cat] = {"total": 0, "top1": 0, "top3": 0}
            cats[cat]["total"] += 1
            if r.get("is_match"):
                cats[cat]["top1"] += 1
            if r.get("top3_match"):
                cats[cat]["top3"] += 1

        for cat, data in cats.items():
            t = max(data["total"], 1)
            data["top1_accuracy"] = round(data["top1"] / t, 4)
            data["top3_accuracy"] = round(data["top3"] / t, 4)

        return cats

    def report(self) -> str:
        s = self.summary
        lines = [
            "=" * 50,
            "ReplayRunner Report",
            "=" * 50,
            f"  Total runs:            {s.get('total_runs', 0)}",
            f"  With recommendation:   {s.get('with_recommendation', 0)}",
            f"  Empty recommendations: {s.get('empty_recommendations', 0)}",
            "",
            f"  Top-1 Matches:         {s.get('top1_matches', 0)}",
            f"  Top-3 Matches:         {s.get('top3_matches', 0)}",
            f"  Top-1 Accuracy:        {s.get('top1_accuracy', 0):.2%}",
            f"  Top-3 Accuracy:        {s.get('top3_accuracy', 0):.2%}",
            f"  Recommendation Recall: {s.get('recommendation_recall', 0):.2%}",
            "",
        ]

        cats = self.replay_by_category()
        if cats:
            lines.append("By Category:")
            for cat, data in sorted(cats.items()):
                lines.append(
                    f"  {cat:<20s}  total={data['total']:>4d}"
                    f"  top1={data['top1_accuracy']:.0%}"
                    f"  top3={data['top3_accuracy']:.0%}"
                )
            lines.append("")

        return "\n".join(lines)


def _has_context(run: dict) -> bool:
    metadata = run.get("metadata", {})
    if isinstance(metadata, str):
        return False
    ws = metadata.get("workspace", {}) if isinstance(metadata, dict) else {}
    return bool(ws.get("arch") or ws.get("toolchain_type") or ws.get("board"))
