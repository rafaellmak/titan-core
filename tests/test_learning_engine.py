import tempfile
from datetime import datetime
from pathlib import Path

from titan.learning.patterns import LearnedPattern, PatternDB
from titan.learning.engine import LearningEngine, MIN_OCCURRENCES, MIN_SCORE, MIN_SUCCESS_RATE
from titan.learning.recommender import Recommender

from titan.validation.contracts import SkillResult, ValidationResult
from titan.validation.history import ValidationHistory
from titan.validation.persistence import ValidationDB


# ---------------------------------------------------------------------------
# LearnedPattern
# ---------------------------------------------------------------------------

class TestLearnedPattern:
    def test_to_dict(self):
        p = LearnedPattern(
            fingerprint="missing openssl",
            category="BuildrootError",
            occurrences=10,
            success_rate=0.9,
            average_score=85.0,
            best_fix="BR2_PACKAGE_OPENSSL=y",
            first_seen="2025-01-01",
            last_seen="2025-06-01",
            top_fixes={"fix_a": 5, "fix_b": 3},
        )
        d = p.to_dict()
        assert d["fingerprint"] == "missing openssl"
        assert d["occurrences"] == 10
        assert d["success_rate"] == 0.9
        assert len(d["top_fixes"]) == 2

    def test_to_dict_empty(self):
        p = LearnedPattern(fingerprint="unknown", category="GenericError")
        d = p.to_dict()
        assert d["occurrences"] == 0
        assert d["best_fix"] == ""


# ---------------------------------------------------------------------------
# PatternDB
# ---------------------------------------------------------------------------

class TestPatternDB:
    def test_insert_and_retrieve(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PatternDB(db_path=Path(tmp) / "patterns.db")
            p = LearnedPattern(
                fingerprint="missing zlib",
                category="BuildrootError",
                occurrences=5,
                success_rate=0.8,
                average_score=75.0,
                best_fix="BR2_PACKAGE_ZLIB=y",
                first_seen="2025-01-01",
                last_seen="2025-06-01",
                top_fixes={"BR2_PACKAGE_ZLIB=y": 4},
            )
            db.upsert_pattern(p)

            loaded = db.get_pattern("missing zlib")
            assert loaded is not None
            assert loaded.fingerprint == "missing zlib"
            assert loaded.occurrences == 5
            assert loaded.success_rate == 0.8
            assert loaded.best_fix == "BR2_PACKAGE_ZLIB=y"
            assert loaded.top_fixes == {"BR2_PACKAGE_ZLIB=y": 4}

    def test_upsert_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PatternDB(db_path=Path(tmp) / "patterns.db")
            p = LearnedPattern(fingerprint="err", category="X", occurrences=1,
                               first_seen="2025-01-01", last_seen="2025-01-01")
            db.upsert_pattern(p)

            p.occurrences = 10
            p.success_rate = 0.9
            db.upsert_pattern(p)

            loaded = db.get_pattern("err")
            assert loaded.occurrences == 10
            assert loaded.success_rate == 0.9

    def test_search_patterns(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PatternDB(db_path=Path(tmp) / "patterns.db")
            for name in ["missing openssl", "missing zlib", "toolchain error"]:
                db.upsert_pattern(LearnedPattern(
                    fingerprint=name, category="BuildrootError",
                    occurrences=3, first_seen="2025-01-01", last_seen="2025-06-01",
                ))

            results = db.search_patterns("missing", limit=10)
            assert len(results) == 2
            fingerprints = {r.fingerprint for r in results}
            assert "missing openssl" in fingerprints
            assert "missing zlib" in fingerprints

    def test_top_patterns(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PatternDB(db_path=Path(tmp) / "patterns.db")
            for i, name in enumerate(["common", "rare"]):
                db.upsert_pattern(LearnedPattern(
                    fingerprint=name, category="BuildrootError",
                    occurrences=10 - i, success_rate=0.9 - (i * 0.1),
                    first_seen="2025-01-01", last_seen="2025-06-01",
                ))

            top = db.top_patterns(limit=5)
            assert len(top) == 2
            assert top[0].fingerprint == "common"

    def test_count_patterns(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PatternDB(db_path=Path(tmp) / "patterns.db")
            assert db.count_patterns() == 0

            for i, cat in enumerate(["BuildrootError", "BuildrootError", "YoctoError"]):
                db.upsert_pattern(LearnedPattern(
                    fingerprint=f"err-{cat}-{i}", category=cat,
                    occurrences=3, first_seen="2025-01-01", last_seen="2025-06-01",
                ))

            assert db.count_patterns() == 3
            assert db.count_patterns("BuildrootError") == 2
            assert db.count_patterns("YoctoError") == 1

    def test_delete_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PatternDB(db_path=Path(tmp) / "patterns.db")
            db.upsert_pattern(LearnedPattern(
                fingerprint="x", category="X",
                occurrences=1, first_seen="2025-01-01", last_seen="2025-06-01",
            ))
            assert db.count_patterns() == 1
            db.delete_all()
            assert db.count_patterns() == 0


# ---------------------------------------------------------------------------
# LearningEngine
# ---------------------------------------------------------------------------

def _seed_history(db_path: str, runs: list) -> ValidationHistory:
    """Helper: cria ValidationHistory com execuções de teste."""
    vdb = ValidationDB(db_path=db_path)
    history = ValidationHistory(db=vdb)
    for i, r in enumerate(runs):
        vdb.insert_run({
            "skill_name": r.get("skill_name", "TestSkill"),
            "score": r.get("score", 50.0),
            "accepted": 1 if r.get("accepted", True) else 0,
            "error_category": r.get("error_category", "GenericError"),
            "error_fingerprint": r.get("error_fingerprint", f"err-{i}"),
            "fix_signature": r.get("fix_signature", ""),
            "timestamp": r.get("timestamp", datetime.now().isoformat()),
            "summary": r.get("summary", ""),
            "raw_data": "{}",
            "metadata": "{}",
        })
    return history


class TestLearningEngine:
    def test_learn_all_promotes_patterns_above_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = _seed_history(f"{tmp}/val.db", [
                {"error_fingerprint": "missing openssl", "score": 85, "accepted": True,
                 "error_category": "BuildrootError", "fix_signature": "BR2_PACKAGE_OPENSSL=y"},
                {"error_fingerprint": "missing openssl", "score": 90, "accepted": True,
                 "error_category": "BuildrootError", "fix_signature": "BR2_PACKAGE_OPENSSL=y"},
                {"error_fingerprint": "missing openssl", "score": 80, "accepted": True,
                 "error_category": "BuildrootError", "fix_signature": "BR2_PACKAGE_OPENSSL=y"},
            ])

            engine = LearningEngine(history, db=PatternDB(db_path=Path(tmp) / "patterns.db"))
            learned = engine.learn_all()

            assert len(learned) == 1
            assert learned[0].fingerprint == "BUILDROOT_MISSING_PACKAGE:openssl"
            assert learned[0].occurrences == 3
            assert learned[0].average_score >= 80
            assert learned[0].success_rate >= 0.99

    def test_learn_all_skips_below_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = _seed_history(f"{tmp}/val.db", [
                {"error_fingerprint": "rare error", "score": 50, "accepted": False},
            ])

            engine = LearningEngine(history, db=PatternDB(db_path=Path(tmp) / "patterns.db"))
            learned = engine.learn_all()

            assert len(learned) == 0  # abaixo de MIN_OCCURRENCES

    def test_learn_all_multiple_patterns(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = _seed_history(f"{tmp}/val.db", [
                {"error_fingerprint": "missing openssl", "score": 90, "accepted": True,
                 "error_category": "BuildrootError"},
                {"error_fingerprint": "missing openssl", "score": 85, "accepted": True,
                 "error_category": "BuildrootError"},
                {"error_fingerprint": "missing openssl", "score": 95, "accepted": True,
                 "error_category": "BuildrootError"},
                {"error_fingerprint": "Nothing PROVIDES python3", "score": 70, "accepted": True,
                 "error_category": "YoctoError"},
                {"error_fingerprint": "Nothing PROVIDES python3", "score": 75, "accepted": True,
                 "error_category": "YoctoError"},
                {"error_fingerprint": "Nothing PROVIDES python3", "score": 80, "accepted": True,
                 "error_category": "YoctoError"},
                {"error_fingerprint": "Nothing PROVIDES python3", "score": 65, "accepted": False,
                 "error_category": "YoctoError"},
            ])

            engine = LearningEngine(history, db=PatternDB(db_path=Path(tmp) / "patterns.db"))
            learned = engine.learn_all()

            assert len(learned) == 2
            names = {p.fingerprint for p in learned}
            assert "BUILDROOT_MISSING_PACKAGE:openssl" in names
            assert "YOCTO_NOTHING_PROVIDES:python3" in names

    def test_learn_from_run_incremental(self):
        with tempfile.TemporaryDirectory() as tmp:
            # First: seed 2 runs (below MIN_OCCURRENCES)
            history = _seed_history(f"{tmp}/val.db", [
                {"error_fingerprint": "toolchain error", "score": 80, "accepted": True,
                 "error_category": "BuildrootError", "fix_signature": "fix-a"},
                {"error_fingerprint": "toolchain error", "score": 85, "accepted": True,
                 "error_category": "BuildrootError", "fix_signature": "fix-b"},
            ])

            engine = LearningEngine(history, db=PatternDB(db_path=Path(tmp) / "patterns.db"))

            # Ainda abaixo do threshold
            learned = engine.learn_all()
            assert len(learned) == 0

            # Terceira execução — agora atinge MIN_OCCURRENCES
            run = {
                "error_fingerprint": "toolchain error",
                "score": 90,
                "accepted": True,
                "error_category": "BuildrootError",
                "fix_signature": "fix-a",
                "timestamp": datetime.now().isoformat(),
            }
            pattern = engine.learn_from_run(run)
            assert pattern is not None
            assert pattern.fingerprint == "BUILDROOT_TOOLCHAIN_ERROR"
            assert pattern.occurrences == 3
            assert pattern.best_fix == "fix-a"  # mais frequente (2x)

    def test_suggest_returns_relevant(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = _seed_history(f"{tmp}/val.db", [
                {"error_fingerprint": "missing openssl", "score": 90, "accepted": True,
                 "error_category": "BuildrootError"},
                {"error_fingerprint": "missing openssl", "score": 80, "accepted": True,
                 "error_category": "BuildrootError"},
                {"error_fingerprint": "missing openssl", "score": 85, "accepted": True,
                 "error_category": "BuildrootError"},
                {"error_fingerprint": "missing zlib", "score": 70, "accepted": True,
                 "error_category": "BuildrootError"},
                {"error_fingerprint": "missing zlib", "score": 75, "accepted": True,
                 "error_category": "BuildrootError"},
                {"error_fingerprint": "missing zlib", "score": 80, "accepted": True,
                 "error_category": "BuildrootError"},
            ])

            engine = LearningEngine(history, db=PatternDB(db_path=Path(tmp) / "patterns.db"))
            engine.learn_all()

            suggests = engine.suggest("openssl", limit=2)
            assert len(suggests) >= 1
            assert "openssl" in suggests[0].fingerprint

    def test_top_knowledge(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = _seed_history(f"{tmp}/val.db", [
                {"error_fingerprint": "err-a", "score": 95, "accepted": True,
                 "error_category": "BuildrootError"},
                {"error_fingerprint": "err-a", "score": 90, "accepted": True,
                 "error_category": "BuildrootError"},
                {"error_fingerprint": "err-a", "score": 85, "accepted": True,
                 "error_category": "BuildrootError"},
                {"error_fingerprint": "err-b", "score": 60, "accepted": False,
                 "error_category": "BuildrootError"},
                {"error_fingerprint": "err-b", "score": 55, "accepted": False,
                 "error_category": "BuildrootError"},
                {"error_fingerprint": "err-b", "score": 50, "accepted": False,
                 "error_category": "BuildrootError"},
            ])

            engine = LearningEngine(history, db=PatternDB(db_path=Path(tmp) / "patterns.db"))
            engine.learn_all()

            top = engine.top_knowledge(limit=5)
            # ERR-A (score 90) vem primeiro, ERR-B (score 55) fica abaixo do threshold
            assert len(top) >= 1
            assert top[0].fingerprint == "ERR-A"

    def test_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = _seed_history(f"{tmp}/val.db", [
                {"error_fingerprint": "err-a", "score": 90, "accepted": True,
                 "error_category": "BuildrootError"},
                {"error_fingerprint": "err-a", "score": 85, "accepted": True,
                 "error_category": "BuildrootError"},
                {"error_fingerprint": "err-a", "score": 80, "accepted": True,
                 "error_category": "BuildrootError"},
            ])

            engine = LearningEngine(history, db=PatternDB(db_path=Path(tmp) / "patterns.db"))
            engine.learn_all()

            s = engine.stats()
            assert s["patterns"] == 1
            assert "BuildrootError" in s["categories"]

            empty = LearningEngine(history, db=PatternDB(db_path=Path(tmp) / "empty.db"))
            assert empty.stats()["patterns"] == 0


# ---------------------------------------------------------------------------
# Recommender
# ---------------------------------------------------------------------------

class TestRecommender:
    def test_recommend(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = _seed_history(f"{tmp}/val.db", [
                {"error_fingerprint": "missing openssl", "score": 95, "accepted": True,
                 "error_category": "BuildrootError", "fix_signature": "BR2_PACKAGE_OPENSSL=y"},
                {"error_fingerprint": "missing openssl", "score": 90, "accepted": True,
                 "error_category": "BuildrootError", "fix_signature": "BR2_PACKAGE_OPENSSL=y"},
                {"error_fingerprint": "missing openssl", "score": 85, "accepted": True,
                 "error_category": "BuildrootError", "fix_signature": "BR2_PACKAGE_OPENSSL=y"},
            ])

            engine = LearningEngine(history, db=PatternDB(db_path=Path(tmp) / "patterns.db"))
            engine.learn_all()

            recommender = Recommender(engine)
            recs = recommender.recommend("openssl", limit=3)

            assert len(recs) >= 1
            assert recs[0]["fingerprint"] == "BUILDROOT_MISSING_PACKAGE:openssl"
            assert recs[0]["best_fix"] == "BR2_PACKAGE_OPENSSL=y"
            assert recs[0]["confidence"] > 0.5

    def test_recommend_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = _seed_history(f"{tmp}/val.db", [])
            engine = LearningEngine(history, db=PatternDB(db_path=Path(tmp) / "patterns.db"))

            recommender = Recommender(engine)
            recs = recommender.recommend("anything")
            assert len(recs) == 0

    def test_explain(self):
        rec = {
            "category": "BuildrootError",
            "fingerprint": "missing openssl",
            "occurrences": 10,
            "success_rate": 0.9,
            "average_score": 85.0,
            "best_fix": "BR2_PACKAGE_OPENSSL=y",
            "confidence": 0.85,
        }
        from unittest.mock import MagicMock
        mock_engine = MagicMock()
        mock_engine.db = MagicMock()
        recommender = Recommender(mock_engine)
        explanation = recommender.explain(rec)
        assert "BuildrootError" in explanation
        assert "missing openssl" in explanation
        assert "BR2_PACKAGE_OPENSSL=y" in explanation

    def test_top_recommendations(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = _seed_history(f"{tmp}/val.db", [
                {"error_fingerprint": "err-a", "score": 95, "accepted": True,
                 "error_category": "BuildrootError"},
                {"error_fingerprint": "err-a", "score": 90, "accepted": True,
                 "error_category": "BuildrootError"},
                {"error_fingerprint": "err-a", "score": 85, "accepted": True,
                 "error_category": "BuildrootError"},
                {"error_fingerprint": "err-b", "score": 80, "accepted": True,
                 "error_category": "YoctoError"},
                {"error_fingerprint": "err-b", "score": 75, "accepted": True,
                 "error_category": "YoctoError"},
                {"error_fingerprint": "err-b", "score": 70, "accepted": True,
                 "error_category": "YoctoError"},
            ])

            engine = LearningEngine(history, db=PatternDB(db_path=Path(tmp) / "patterns.db"))
            engine.learn_all()

            recommender = Recommender(engine)
            top = recommender.top_recommendations(limit=5)
            assert len(top) == 2


# ---------------------------------------------------------------------------
# Integration: history → learning → recommend
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_full_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            # 1. History com múltiplas execuções
            history = _seed_history(f"{tmp}/val.db", [
                {"error_fingerprint": "missing openssl", "score": 90, "accepted": True,
                 "error_category": "BuildrootError", "fix_signature": "BR2_PACKAGE_OPENSSL=y"},
                {"error_fingerprint": "missing openssl", "score": 85, "accepted": True,
                 "error_category": "BuildrootError", "fix_signature": "BR2_PACKAGE_OPENSSL=y"},
                {"error_fingerprint": "missing openssl", "score": 95, "accepted": True,
                 "error_category": "BuildrootError", "fix_signature": "BR2_PACKAGE_OPENSSL=y"},
                {"error_fingerprint": "missing openssl", "score": 80, "accepted": True,
                 "error_category": "BuildrootError", "fix_signature": "BR2_PACKAGE_OPENSSL=y"},
            ])

            # 2. Learning Engine
            engine = LearningEngine(history, db=PatternDB(db_path=Path(tmp) / "patterns.db"))
            learned = engine.learn_all()

            assert len(learned) == 1
            p = learned[0]
            assert p.fingerprint == "BUILDROOT_MISSING_PACKAGE:openssl"
            assert p.occurrences == 4
            assert p.average_score >= 85
            assert p.best_fix == "BR2_PACKAGE_OPENSSL=y"

            # 3. Recommender
            recommender = Recommender(engine)
            recs = recommender.recommend("openssl", limit=3)

            assert len(recs) >= 1
            assert recs[0]["fingerprint"] == "BUILDROOT_MISSING_PACKAGE:openssl"
            assert recs[0]["best_fix"] == "BR2_PACKAGE_OPENSSL=y"
            assert recs[0]["average_score"] >= 85

            # 4. Estatísticas
            stats = engine.stats()
            assert stats["patterns"] == 1
            assert stats["status"] == "learning"
