from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional

from titan.validation.history import ValidationHistory
from titan.core.knowledge_engine import KnowledgeEngine, KnowledgeRecord
from .patterns import LearnedPattern, PatternDB
from .normalizer import ErrorNormalizer
from .context import WorkspaceContext, PatternContextDB
from .feedback import FeedbackLoop, FeedbackDB


# Thresholds de aprendizado — só promove a padrão se superar todos
MIN_OCCURRENCES = 3
MIN_SCORE = 60.0
MIN_SUCCESS_RATE = 0.60


class LearningEngine:
    """Lê o histórico de validações, extrai padrões e persiste no PatternDB.

    Usa ErrorNormalizer para unificar fingerprints, e regista contexto
    do workspace no PatternContextDB + feedback no FeedbackDB.

    Quando knowledge_engine é fornecido, padrões promovidos são também
    registados no KnowledgeEngine para consulta unificada.
    """

    def __init__(self, history: ValidationHistory,
                 db: PatternDB | None = None,
                 normalizer: ErrorNormalizer | None = None,
                 context_db: PatternContextDB | None = None,
                 feedback: FeedbackLoop | None = None,
                 knowledge_engine: KnowledgeEngine | None = None):
        self.history = history
        self.db = db or PatternDB()
        self.normalizer = normalizer or ErrorNormalizer()
        self.context_db = context_db or PatternContextDB()
        self.feedback = feedback or FeedbackLoop()
        self.knowledge_engine = knowledge_engine

    def learn_all(self) -> List[LearnedPattern]:
        """Processa todo o histórico e extrai/actualiza padrões."""
        all_runs = self.history.recent(limit=100000)
        groups = self._group_by_fingerprint(all_runs)

        learned: List[LearnedPattern] = []
        for fingerprint, runs in groups.items():
            pattern = self._build_pattern(fingerprint, runs)
            if self._should_promote(pattern):
                self.db.upsert_pattern(pattern)
                self._record_contexts(fingerprint, runs)
                self._promote_to_knowledge(pattern)
                learned.append(pattern)

        return learned

    def learn_from_run(self, run: dict) -> Optional[LearnedPattern]:
        """Aprende a partir de uma única execução (incremental)."""
        raw_fp = run.get("error_fingerprint", "")
        if not raw_fp:
            return None

        # Normaliza
        category = run.get("error_category", "")
        fingerprint = self.normalizer.normalize(raw_fp, category)

        # Busca padrão existente ou constrói novo
        existing = self.db.get_pattern(fingerprint)
        if existing:
            updated = self._update_from_existing(existing, run)
            self._record_context(fingerprint, run)
            return updated

        # Ainda não é padrão — precisa de MIN_OCCURRENCES runs
        similar = self.history.recent(limit=10000)
        groups = self._group_by_fingerprint(similar)
        runs = groups.get(fingerprint, [])
        all_runs = runs + [run]
        if len(runs) + 1 < MIN_OCCURRENCES:
            return None

        pattern = self._build_pattern(fingerprint, all_runs)
        if self._should_promote(pattern):
            self.db.upsert_pattern(pattern)
            self._record_contexts(fingerprint, all_runs)
            self._promote_to_knowledge(pattern)
            return pattern
        return None

    def suggest(self, error_text: str, limit: int = 3) -> List[LearnedPattern]:
        """Retorna os padrões mais relevantes para um texto de erro.

        Faz fallback à pesquisa pelo fingerprint normalizado caso a
        pesquisa textual directa não encontre resultados.
        """
        patterns = self.db.search_patterns(error_text, limit=limit * 3)
        if not patterns:
            norm = self.normalizer.normalize(error_text)
            patterns = self.db.search_patterns(norm, limit=limit * 3)
        if not patterns and ":" in error_text:
            pass  # já é um fingerprint normalizado
        return sorted(patterns, key=lambda p: (p.occurrences, p.success_rate), reverse=True)[:limit]

    def top_knowledge(self, category: str | None = None, limit: int = 10) -> List[LearnedPattern]:
        return self.db.top_patterns(category=category, limit=limit)

    def stats(self) -> Dict[str, Any]:
        total = self.db.count_patterns()
        if total == 0:
            return {"patterns": 0, "status": "no_knowledge"}
        categories = {}
        for cat in ["BuildrootError", "YoctoError", "DTSError", "SecurityError", "GenericError"]:
            c = self.db.count_patterns(cat)
            if c > 0:
                categories[cat] = c
        return {
            "patterns": total,
            "categories": categories,
            "status": "learning",
        }

    def _promote_to_knowledge(self, pattern: LearnedPattern) -> None:
        if not self.knowledge_engine:
            return
        record = KnowledgeRecord(
            problem_signature=pattern.fingerprint,
            root_cause=pattern.category,
            action_taken=pattern.best_fix or "",
            outcome="fixed" if pattern.success_rate >= 0.5 else "partial",
            confidence=pattern.success_rate,
            success_rate=pattern.success_rate,
            usage_count=pattern.occurrences,
        )
        self.knowledge_engine.add_knowledge(record)

    def _should_promote(self, pattern: LearnedPattern) -> bool:
        return (
            pattern.occurrences >= MIN_OCCURRENCES
            and pattern.average_score >= MIN_SCORE
            and pattern.success_rate >= MIN_SUCCESS_RATE
        )

    def _build_pattern(self, fingerprint: str, runs: List[dict]) -> LearnedPattern:
        n = len(runs)
        scores = [r.get("score", 0) or 0 for r in runs]
        accepted = [r for r in runs if r.get("accepted")]

        avg_score = sum(scores) / n if n > 0 else 0.0
        success_rate = len(accepted) / n if n > 0 else 0.0

        fix_counts: Dict[str, int] = {}
        for r in runs:
            fix = r.get("fix_signature", "") or ""
            if fix.strip():
                fix_counts[fix] = fix_counts.get(fix, 0) + 1
        best_fix = max(fix_counts, key=fix_counts.get) if fix_counts else ""

        timestamps = [r.get("timestamp", "") for r in runs if r.get("timestamp")]
        first_seen = min(timestamps) if timestamps else datetime.now().isoformat()
        last_seen = max(timestamps) if timestamps else datetime.now().isoformat()

        return LearnedPattern(
            fingerprint=fingerprint,
            category=runs[0].get("error_category", "GenericError") if runs else "GenericError",
            occurrences=n,
            success_rate=round(success_rate, 3),
            average_score=round(avg_score, 1),
            best_fix=best_fix,
            first_seen=first_seen,
            last_seen=last_seen,
            top_fixes=fix_counts,
        )

    def _group_by_fingerprint(self, runs: List[dict]) -> Dict[str, List[dict]]:
        groups: Dict[str, List[dict]] = {}
        for r in runs:
            raw = r.get("error_fingerprint", "unknown")
            cat = r.get("error_category", "")
            norm = self.normalizer.normalize(raw, cat)
            if norm not in groups:
                groups[norm] = []
            groups[norm].append(r)
        return groups

    def _update_from_existing(self, existing: LearnedPattern, run: dict) -> Optional[LearnedPattern]:
        n = existing.occurrences + 1
        score = run.get("score", 0) or 0
        accepted = run.get("accepted", False)
        fix = run.get("fix_signature", "") or ""
        ts = run.get("timestamp", datetime.now().isoformat())

        existing.average_score = round(
            ((existing.average_score * (n - 1)) + score) / n, 1
        )
        existing.success_rate = round(
            ((existing.success_rate * (n - 1)) + (1 if accepted else 0)) / n, 3
        )
        existing.occurrences = n
        existing.last_seen = max(existing.last_seen, ts)

        if fix.strip():
            existing.top_fixes[fix] = existing.top_fixes.get(fix, 0) + 1
            sorted_fixes = sorted(existing.top_fixes.items(), key=lambda x: -x[1])
            existing.best_fix = sorted_fixes[0][0] if sorted_fixes else existing.best_fix

        if self._should_promote(existing):
            self.db.upsert_pattern(existing)
            self._promote_to_knowledge(existing)
            return existing
        return None

    def _record_context(self, fingerprint: str, run: dict) -> None:
        ctx = WorkspaceContext.from_run(run)
        if any(getattr(ctx, a) for a in ["arch", "toolchain", "board"]):
            self.context_db.upsert_context(
                fingerprint, ctx,
                score=run.get("score", 0) or 0,
                accepted=run.get("accepted", False),
                fix=run.get("fix_signature", "") or "",
            )

    def _record_contexts(self, fingerprint: str, runs: List[dict]) -> None:
        for r in runs:
            self._record_context(fingerprint, r)
