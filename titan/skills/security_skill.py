from __future__ import annotations
from typing import Any, Dict, List

from titan.core.planner import Skill
from titan.core.memory import MultiLayerMemory
from titan.core.digital_twin import DigitalTwin
from titan.core.knowledge_engine import KnowledgeEngine
from titan.security.cve_monitor import CVEMonitor


class SecuritySkill(Skill):
    def can_handle(self, event_type: str, data: Dict[str, Any]) -> bool:
        return event_type == "security_scan"

    def _lookup_blast_radius(self, package: str,
                             digital_twin: DigitalTwin) -> Dict[str, Any]:
        """Consulta a Twin para descobrir o impacto de um pacote vulnerável."""
        for prefix in ("buildroot_package:", "package:", "recipe:"):
            node_id = f"{prefix}{package}"
            if digital_twin.graph.has_node(node_id):
                report = digital_twin.analyze_impact(node_id)
                return {
                    "node_id": node_id,
                    "affected_count": report.affected_count,
                    "risk_level": report.risk_level,
                    "risk_score": report.risk_score,
                    "direct_dependents": report.direct_dependents,
                    "critical_path": report.critical_path,
                    "explanation": report.explanation,
                }
        return {
            "node_id": None,
            "affected_count": 0,
            "risk_level": "UNKNOWN",
            "risk_score": 0.0,
            "direct_dependents": [],
            "critical_path": [],
            "explanation": f"Package '{package}' not found in DigitalTwin graph.",
        }

    async def execute(self, data: Dict[str, Any], memory: MultiLayerMemory,
                      digital_twin: DigitalTwin,
                      knowledge_engine: KnowledgeEngine) -> Any:
        ws_info = memory.get_state("workspace")
        if not ws_info:
            return {"error": "Workspace not detected"}

        from pathlib import Path
        from titan.recipes.db import RecipeDB
        root_dir = ws_info.get("root_dir", ".")
        db = RecipeDB(Path(root_dir))
        monitor = CVEMonitor(db)
        report = monitor.scan_workspace()

        # ── Blast radius via Twin ───────────────────────────────────
        enriched = []
        for vuln in (report if isinstance(report, list) else []):
            pkg = (vuln.get("package", "")
                   or vuln.get("recipe", "")
                   or vuln.get("name", ""))
            blast = self._lookup_blast_radius(pkg, digital_twin)
            vuln["blast_radius"] = blast
            enriched.append(vuln)

        memory.update_state("security_report", enriched if enriched else report)
        memory.log_event("SECURITY_SCAN", {"vulnerabilities": len(enriched or report)})
        return enriched if enriched else report
