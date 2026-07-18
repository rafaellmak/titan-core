from __future__ import annotations
from typing import Any, Dict, List, Optional

from .patterns import LearnedPattern, PatternDB
from .context import WorkspaceContext, PatternContextDB
from .feedback import FeedbackLoop
from titan.context.models import WorkspaceFingerprint
from titan.context.similarity import compare as context_compare


class RankingEngine:
    """Ranqueia fixes por relevância contextual + feedback histórico.

    Combina:
      - Similaridade contextual (arch, toolchain, board...)
      - Taxa de sucesso histórica do padrão
      - Feedback de recomendações anteriores
      - Score médio de validação
    """

    def __init__(self, pattern_db: PatternDB,
                 context_db: Optional[PatternContextDB] = None,
                 feedback: Optional[FeedbackLoop] = None):
        self.pattern_db = pattern_db
        self.context_db = context_db or PatternContextDB()
        self.feedback = feedback or FeedbackLoop()

    def rank(self, patterns: List[LearnedPattern],
             context: Optional[WorkspaceContext] = None,
             fingerprint: Optional[WorkspaceFingerprint] = None,
             limit: int = 3) -> List[Dict[str, Any]]:
        scored = []
        for p in patterns:
            score = self._compute_rank(p, context, fingerprint)
            scored.append({
                "fingerprint": p.fingerprint,
                "category": p.category,
                "rank_score": round(score, 2),
                "occurrences": p.occurrences,
                "success_rate": p.success_rate,
                "average_score": p.average_score,
                "best_fix": p.best_fix,
                "top_fixes": dict(sorted(p.top_fixes.items(), key=lambda x: -x[1])[:3]),
            })
        return sorted(scored, key=lambda x: -x["rank_score"])[:limit]

    def _compute_rank(self, pattern: LearnedPattern,
                      context: Optional[WorkspaceContext] = None,
                      fingerprint: Optional[WorkspaceFingerprint] = None) -> float:
        # Componente 1: Score bruto do padrão (0-40)
        raw_score = (pattern.success_rate * 20) + min(pattern.average_score / 5, 20)

        # Componente 2: Contexto (0-30)
        ctx_score = 0.0
        ctx_source = context or self._fp_to_context(fingerprint)
        if ctx_source:
            similar = self.context_db.search_by_context(pattern.fingerprint, ctx_source, limit=3)
            if similar:
                best = similar[0]
                if fingerprint:
                    other_fp = WorkspaceFingerprint(
                        architecture=best.get("arch", ""),
                        toolchain=best.get("toolchain", ""),
                        board=best.get("board", ""),
                        kernel_version=best.get("kernel", ""),
                    )
                    sim_score = context_compare(fingerprint, other_fp).score / 100
                else:
                    ctx_match = WorkspaceContext(
                        arch=best.get("arch", ""),
                        toolchain=best.get("toolchain", ""),
                        board=best.get("board", ""),
                    )
                    sim_score = context.similarity(ctx_match)
                ctx_score = sim_score * 20 + min(best.get("success_rate", 0) * 10, 10)
        else:
            ctx_score = 15  # neutro se sem contexto

        # Componente 3: Feedback (0-30)
        fb_info = self.feedback.fix_effectiveness(pattern.fingerprint)
        fb_score = fb_info.get("acceptance_rate", 0.5) * 30

        return raw_score + ctx_score + fb_score

    def _fp_to_context(self, fp: Optional[WorkspaceFingerprint]) -> Optional[WorkspaceContext]:
        if not fp:
            return None
        return WorkspaceContext(
            arch=fp.architecture,
            toolchain=fp.toolchain,
            board=fp.board,
            kernel=fp.kernel_version,
        )

    def explain_ranking(self, result: Dict[str, Any]) -> str:
        return (
            f"  Rank score: {result['rank_score']:.1f}/100\n"
            f"    • {result['occurrences']} ocorrências ({result['success_rate']:.0%} sucesso)\n"
            f"    • Score médio: {result['average_score']}/100\n"
            f"    • Melhor fix: {result['best_fix'] or '—'}\n"
        )
