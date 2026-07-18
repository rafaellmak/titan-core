from __future__ import annotations
from typing import Any, Dict, List, Optional

from .patterns import PatternDB, LearnedPattern
from .engine import LearningEngine
from .context import WorkspaceContext
from .ranking import RankingEngine
from .feedback import FeedbackLoop
from titan.context.models import (
    WorkspaceFingerprint, Recommendation, RiskAssessment,
    compute_confidence, compute_adjusted_confidence, confidence_level,
)
from titan.context.similarity import compare as context_compare


# Maximum number of entities to analyze via DigitalTwin per recommendation
# to avoid excessive graph traversal
_MAX_RISK_ENTITIES = 5


class Recommender:
    """Sugere correções com base em padrões aprendidos + contexto + feedback.

    Fluxo:
      error_text → normalizer → fingerprint
      fingerprint → patterns
      patterns + context → ranking
      ranking → top N recomendações
    """

    def __init__(self, engine: LearningEngine,
                 ranking: Optional[RankingEngine] = None):
        self.engine = engine
        self.db = engine.db
        self.ranking = ranking or RankingEngine(
            pattern_db=self.db,
            context_db=engine.context_db if hasattr(engine, 'context_db') else None,
            feedback=FeedbackLoop(),
        )
        self._context_db = self.ranking.context_db

    def recommend(self, error_text: str, limit: int = 3,
                  context: Optional[WorkspaceContext] = None,
                  fingerprint: Optional[WorkspaceFingerprint] = None,
                  digital_twin: Any = None) -> List[Dict[str, Any]]:
        patterns = self.engine.suggest(error_text, limit=limit * 2)
        if not patterns:
            return []

        ranked = self.ranking.rank(patterns, context=context,
                                   fingerprint=fingerprint, limit=limit)
        results = []
        for r in ranked:
            ctx_match = 0
            if fingerprint:
                similar = self._context_db.search_by_context(
                    r["fingerprint"],
                    WorkspaceContext(arch=fingerprint.architecture,
                                     toolchain=fingerprint.toolchain,
                                     board=fingerprint.board,
                                     kernel=fingerprint.kernel_version),
                    limit=1,
                )
                if similar:
                    best = similar[0]
                    other_fp = WorkspaceFingerprint(
                        architecture=best.get("arch", ""),
                        toolchain=best.get("toolchain", ""),
                        board=best.get("board", ""),
                        kernel_version=best.get("kernel", ""),
                    )
                    match = context_compare(fingerprint, other_fp)
                    ctx_match = match.score
            raw_conf = compute_confidence(
                success_rate=r["success_rate"],
                context_match=ctx_match / 100.0,
                occurrences=r["occurrences"],
                feedback_score=self.ranking.feedback.fix_effectiveness(
                    r["fingerprint"]
                ).get("acceptance_rate", 0.5),
            )
            r["raw_confidence"] = round(raw_conf * 100, 1)

            # Risk assessment via DigitalTwin
            risk = self._assess_risk(r.get("best_fix", ""), digital_twin)

            # Adjust confidence
            adj_conf = compute_adjusted_confidence(raw_conf, risk.risk_score)
            r["confidence"] = round(adj_conf * 100, 1)
            r["adjusted_confidence"] = r["confidence"]
            r["confidence_level"] = confidence_level(adj_conf * 100)
            r["context_match"] = ctx_match
            r["risk_level"] = risk.risk_level
            r["risk_score"] = risk.risk_score
            r["risk_explanation"] = risk.explanation
            results.append(r)
        return results

    @staticmethod
    def _assess_risk(fix: str,
                     digital_twin: Any) -> RiskAssessment:
        if not digital_twin or not fix:
            return RiskAssessment()

        # Extract entity from fix (e.g. "BR2_PACKAGE_OPENSSL=y" → "openssl")
        entity, _ = Recommender._extract_entity(fix)
        if not entity:
            return RiskAssessment()

        # Try to find the entity in the graph with common prefixes
        for prefix in ("buildroot_package:", "package:", "recipe:",
                       "layer:"):
            node_id = f"{prefix}{entity}"
            if digital_twin.graph.has_node(node_id):
                report = digital_twin.analyze_impact(node_id)
                return RiskAssessment(
                    risk_level=report.risk_level,
                    risk_score=report.risk_score,
                    affected_count=report.affected_count,
                    critical_path=report.critical_path,
                    explanation=report.explanation,
                )

        return RiskAssessment()

    @staticmethod
    def _extract_entity(fix: str) -> tuple[str, str]:
        """Extrai entidade e tipo de uma fix string.

        Exemplos:
          "BR2_PACKAGE_OPENSSL=y"   → ("openssl", "buildroot_package")
          "BR2_PACKAGE_LIBRESSL=y"  → ("libressl", "buildroot_package")
          "RDEPENDS:zlib"           → ("zlib", "package")
          "layer:meta-oe"           → ("meta-oe", "layer")
        """
        fix_lower = fix.lower().strip()
        if fix_lower.startswith("br2_package_"):
            pkg = fix_lower.replace("br2_package_", "").replace("=y", "").strip()
            return pkg.replace("_", "-"), "buildroot_package"
        if "rdepends" in fix_lower or "depends" in fix_lower:
            parts = fix_lower.replace("rdepends", "").replace("depends", "").split(":")
            if len(parts) > 1 and parts[-1].strip():
                return parts[-1].strip(), "package"
        if fix_lower.startswith("layer:"):
            return fix_lower.replace("layer:", "").strip(), "layer"
        return "", ""

    def recommend_with_confidence(
        self, error_text: str, limit: int = 3,
        context: Optional[WorkspaceContext] = None,
        fingerprint: Optional[WorkspaceFingerprint] = None,
        digital_twin: Any = None,
    ) -> List[Recommendation]:
        ranked = self.recommend(error_text, limit=limit,
                                context=context, fingerprint=fingerprint,
                                digital_twin=digital_twin)
        return [
            Recommendation(
                fix_signature=r["best_fix"],
                confidence=r["confidence"],
                confidence_level=r["confidence_level"],
                context_match=r["context_match"],
                evidence_count=r["occurrences"],
                success_rate=r["success_rate"],
                fingerprint=r["fingerprint"],
                category=r["category"],
                rank_score=r["rank_score"],
                raw_confidence=r.get("raw_confidence", r["confidence"]),
                adjusted_confidence=r.get("adjusted_confidence", r["confidence"]),
                risk_level=r.get("risk_level", "LOW"),
                risk_score=r.get("risk_score", 0.0),
                explanation=r.get("risk_explanation", ""),
            )
            for r in ranked
        ]

    def recommend_by_fingerprint(self, fingerprint: str, limit: int = 3,
                                  context: Optional[WorkspaceContext] = None,
                                  fp: Optional[WorkspaceFingerprint] = None,
                                  digital_twin: Any = None) -> List[Dict[str, Any]]:
        pattern = self.db.get_pattern(fingerprint)
        if not pattern:
            return []
        ranked = self.ranking.rank([pattern], context=context, fingerprint=fp, limit=limit)
        for r in ranked:
            raw_conf = compute_confidence(
                success_rate=r["success_rate"],
                context_match=0,
                occurrences=r["occurrences"],
                feedback_score=0.5,
            )
            risk = self._assess_risk(r.get("best_fix", ""), digital_twin)
            adj_conf = compute_adjusted_confidence(raw_conf, risk.risk_score)
            r["raw_confidence"] = round(raw_conf * 100, 1)
            r["confidence"] = round(adj_conf * 100, 1)
            r["adjusted_confidence"] = r["confidence"]
            r["confidence_level"] = confidence_level(adj_conf * 100)
            r["risk_level"] = risk.risk_level
            r["risk_score"] = risk.risk_score
            r["risk_explanation"] = risk.explanation
        return ranked

    def explain(self, recommendation: Dict[str, Any]) -> str:
        header = (
            f"{recommendation['category']}: {recommendation['fingerprint']}\n"
            f"  Ocorrências: {recommendation['occurrences']}\n"
            f"  Taxa de sucesso: {recommendation['success_rate']:.1%}\n"
            f"  Score médio: {recommendation['average_score']}/100\n"
            f"  Melhor fix: {recommendation['best_fix'] or '—'}\n"
        )
        if "rank_score" in recommendation:
            header += f"  Rank contextual: {recommendation['rank_score']:.1f}/100\n"
        if "confidence" in recommendation:
            header += f"  Confiança: {recommendation['confidence']:.0%}\n"
        return header

    def top_recommendations(self, category: str | None = None,
                            limit: int = 5) -> List[Dict[str, Any]]:
        patterns = self.db.top_patterns(category=category, limit=limit)
        results = []
        for p in patterns:
            results.append({
                "fingerprint": p.fingerprint,
                "category": p.category,
                "occurrences": p.occurrences,
                "success_rate": p.success_rate,
                "average_score": p.average_score,
                "best_fix": p.best_fix,
            })
        return results

    def _confidence_score_raw(self, occurrences: int, success_rate: float,
                              average_score: float) -> float:
        occ_score = min(occurrences / 50.0, 1.0)
        score_norm = min(average_score / 100.0, 1.0)
        rate_norm = success_rate
        return (occ_score * 0.3) + (score_norm * 0.35) + (rate_norm * 0.35)
