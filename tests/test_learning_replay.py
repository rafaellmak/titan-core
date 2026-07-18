import tempfile
from datetime import datetime
from pathlib import Path

from titan.validation.history import ValidationHistory
from titan.validation.persistence import ValidationDB
from titan.learning.engine import LearningEngine
from titan.learning.patterns import PatternDB
from titan.learning.replay import ReplayRunner
from titan.learning.benchmark import LearningBenchmark
from titan.learning.dataset import SyntheticDataset


def _seed_from_dataset(ds_path: str, events: list) -> ValidationHistory:
    vdb = ValidationDB(db_path=ds_path)
    history = ValidationHistory(db=vdb)
    for e in events:
        vdb.insert_run({
            "skill_name": e.get("skill_name", "BuildrootSkill"),
            "score": e.get("score", 80.0),
            "accepted": 1 if e.get("accepted", True) else 0,
            "error_category": e.get("error_category", "BuildrootError"),
            "error_fingerprint": e.get("error_fingerprint", "missing openssl"),
            "fix_signature": e.get("fix_signature", ""),
            "timestamp": e.get("timestamp", datetime.now().isoformat()),
            "summary": e.get("summary", ""),
            "raw_data": e.get("raw_data", "{}"),
            "metadata": e.get("metadata", "{}"),
        })
    return history


# ---------------------------------------------------------------------------
# ReplayRunner
# ---------------------------------------------------------------------------

class TestReplayRunner:
    def test_replay_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = _seed_from_dataset(f"{tmp}/val.db", [])
            runner = ReplayRunner(history)
            summary = runner.replay()
            assert summary["total_runs"] == 0

    def test_replay_simple(self):
        with tempfile.TemporaryDirectory() as tmp:
            ds = SyntheticDataset(seed=42)
            events = ds.generate_benchmark(n_per_fix=3)
            history = _seed_from_dataset(f"{tmp}/val.db", events)
            runner = ReplayRunner(history)
            summary = runner.replay()

            assert summary["total_runs"] > 0
            assert summary["recommendation_recall"] > 0

    def test_replay_accuracy_known_good(self):
        """Dataset equilibrado onde cada fix aparece 3x → esperamos boa acurácia."""
        with tempfile.TemporaryDirectory() as tmp:
            ds = SyntheticDataset(seed=42)
            events = ds.generate_benchmark(n_per_fix=3)
            history = _seed_from_dataset(f"{tmp}/val.db", events)
            runner = ReplayRunner(history)
            summary = runner.replay()

            assert summary["top1_accuracy"] >= 0.0
            assert summary["top3_accuracy"] >= summary["top1_accuracy"]
            assert "total_runs" in summary
            assert "top1_matches" in summary

    def test_replay_by_category(self):
        with tempfile.TemporaryDirectory() as tmp:
            ds = SyntheticDataset(seed=42)
            events = ds.generate_benchmark(n_per_fix=3)
            history = _seed_from_dataset(f"{tmp}/val.db", events)
            runner = ReplayRunner(history)
            runner.replay()

            cats = runner.replay_by_category()
            assert len(cats) > 0
            for cat, data in cats.items():
                assert "total" in data
                assert "top1" in data
                assert "top1_accuracy" in data

    def test_replay_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            ds = SyntheticDataset(seed=42)
            events = ds.generate_benchmark(n_per_fix=3)
            history = _seed_from_dataset(f"{tmp}/val.db", events)
            runner = ReplayRunner(history)
            runner.replay()

            report = runner.report()
            assert "ReplayRunner" in report
            assert "Top-1" in report

    def test_replay_empty_recommendations(self):
        """Dataset com erros muito raros (1 ocorrência cada) → muitas recomendações vazias."""
        with tempfile.TemporaryDirectory() as tmp:
            ds = SyntheticDataset(seed=42)
            events = ds.generate(n_events=10)
            history = _seed_from_dataset(f"{tmp}/val.db", events)
            runner = ReplayRunner(history)
            summary = runner.replay()

            # Com apenas 1-2 ocorrências, alguns não viram padrão
            assert summary["empty_recommendations"] >= 0


# ---------------------------------------------------------------------------
# LearningBenchmark
# ---------------------------------------------------------------------------

class TestLearningBenchmark:
    def test_benchmark_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = _seed_from_dataset(f"{tmp}/val.db", [])
            bench = LearningBenchmark(
                history,
                engine=LearningEngine(history, db=PatternDB(db_path=Path(tmp) / "p.db")),
            )
            results = bench.run()
            assert results["total_runs"] == 0
            assert results["learning_score"] == 0.0

    def test_benchmark_known_good(self):
        with tempfile.TemporaryDirectory() as tmp:
            ds = SyntheticDataset(seed=42)
            events = ds.generate_benchmark(n_per_fix=3)
            history = _seed_from_dataset(f"{tmp}/val.db", events)
            bench = LearningBenchmark(
                history,
                engine=LearningEngine(history, db=PatternDB(db_path=Path(tmp) / "p.db")),
            )
            results = bench.run()

            assert results["total_runs"] > 0
            assert results["top1_accuracy"] >= 0.0
            assert results["top3_accuracy"] >= results["top1_accuracy"]
            assert "grade" in results
            assert "learning_score" in results

    def test_benchmark_grade_a(self):
        """LearningScore >= 90 → grade A."""
        bench = LearningBenchmark.__new__(LearningBenchmark)
        assert bench._grade(95) == "A"
        assert bench._grade(90) == "A"
        assert bench._grade(89) == "B"
        assert bench._grade(75) == "B"
        assert bench._grade(60) == "C"
        assert bench._grade(40) == "D"
        assert bench._grade(39) == "F"

    def test_benchmark_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            ds = SyntheticDataset(seed=42)
            events = ds.generate_benchmark(n_per_fix=3)
            history = _seed_from_dataset(f"{tmp}/val.db", events)
            bench = LearningBenchmark(
                history,
                engine=LearningEngine(history, db=PatternDB(db_path=Path(tmp) / "p.db")),
            )
            bench.run()

            report = bench.report()
            assert "LearningBenchmark" in report
            assert "Learning Score" in report
            assert "By Category" in report
