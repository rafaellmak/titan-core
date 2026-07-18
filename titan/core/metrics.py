"""RunMetrics — métricas de execução de uma sessão.

Acumula contadores de diagnóstico, fix e sucesso.
Pode salvar traces em JSON para observabilidade.
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


class RunMetrics:
    """Métricas de execução de uma sessão do Titan."""

    def __init__(self):
        self.diagnoses: int = 0
        self.fixes: int = 0
        self.successes: int = 0
        self.failures: int = 0
        self.start_time: datetime = datetime.now()
        self.steps: List[Dict[str, Any]] = []

    @property
    def success_rate(self) -> float:
        if self.fixes == 0:
            return 0.0
        return (self.successes / self.fixes) * 100

    def record_step(self, step: str, details: Dict[str, Any] | None = None):
        self.steps.append({
            "step": step,
            "timestamp": datetime.now().isoformat(),
            "details": details or {},
        })

    def to_dict(self) -> Dict[str, Any]:
        elapsed = (datetime.now() - self.start_time).total_seconds()
        return {
            "diagnoses": self.diagnoses,
            "fixes": self.fixes,
            "successes": self.successes,
            "failures": self.failures,
            "success_rate": round(self.success_rate, 1),
            "elapsed_seconds": round(elapsed, 2),
            "steps": self.steps,
        }

    def save_trace(self, trace_dir: str = ".titan/traces") -> Path:
        trace_path = Path(trace_dir)
        trace_path.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        trace_file = trace_path / f"run_{ts}.json"
        with open(trace_file, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        return trace_file
