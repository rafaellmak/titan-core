from __future__ import annotations
from pathlib import Path
from typing import Any, Dict

from titan.core.planner import Skill
from titan.core.memory import MultiLayerMemory
from titan.core.digital_twin import DigitalTwin
from titan.core.knowledge_engine import KnowledgeEngine, KnowledgeRecord
from titan.autofix.engine import AutoFixEngine


class AutoFixSkill(Skill):
    def can_handle(self, event_type: str, data: Dict[str, Any]) -> bool:
        return event_type == "build_failed"

    def _extract_entity(self, entities: list[str]) -> str | None:
        """Pega a primeira entidade tipo 'recipe:' ou 'buildroot_package:'."""
        for e in entities:
            if e.startswith("recipe:") or e.startswith("buildroot_package:"):
                return e
        return None

    async def execute(self, data: Dict[str, Any], memory: MultiLayerMemory,
                      digital_twin: DigitalTwin,
                      knowledge_engine: KnowledgeEngine) -> Any:
        log_path = data.get("log_path")
        ws_info = memory.get_state("workspace")
        if not log_path or not ws_info:
            return {"error": "Missing log_path or workspace info"}

        log_path_obj = Path(log_path) if isinstance(log_path, str) else log_path
        log_name = log_path_obj.name if hasattr(log_path_obj, 'name') else str(log_path)

        engine = AutoFixEngine(ws_info)
        result = engine.run_fix(log_path_obj)

        memory.log_event("AUTOFIX_ATTEMPT", {"log": str(log_path), "result": result})

        # ── Operational Intelligence: Twin reads ────────────────────
        enrichment = {
            "impact": None,
            "risk_assessment": None,
            "snapshot_before": None,
            "snapshot_after": None,
            "diff": None,
        }

        entity_id = self._extract_entity(result.get("entities", []))
        if entity_id and digital_twin.graph.has_node(entity_id):
            # 1. Impact analysis
            report = digital_twin.analyze_impact(entity_id)
            enrichment["impact"] = {
                "entity": entity_id,
                "affected_count": report.affected_count,
                "risk_level": report.risk_level,
                "risk_score": report.risk_score,
                "critical_path": report.critical_path,
                "direct_dependents": report.direct_dependents,
                "transitive_dependents": report.transitive_dependents,
                "explanation": report.explanation,
            }
            enrichment["risk_assessment"] = {
                "risk_level": report.risk_level,
                "risk_score": report.risk_score,
                "explanation": report.explanation,
            }

            # 2. Snapshot before
            before_id = f"autofix-before-{log_name}"
            try:
                snap_before = digital_twin.create_snapshot(
                    before_id, note=f"Before autofix: {log_name}",
                )
                enrichment["snapshot_before"] = snap_before.to_dict()
            except Exception:
                pass

        # 3. Apply fix (already done inside engine.run_fix)
        fixed = result.get("fixed", False)
        action_taken = result.get("action", "No action")

        # 4. Snapshot after + diff
        if entity_id and digital_twin.graph.has_node(entity_id) and fixed:
            after_id = f"autofix-after-{log_name}"
            try:
                snap_after = digital_twin.create_snapshot(
                    after_id, note=f"After autofix: {log_name}",
                    parent=before_id if enrichment["snapshot_before"] else None,
                )
                enrichment["snapshot_after"] = snap_after.to_dict()

                if enrichment["snapshot_before"]:
                    diff = digital_twin.compare(before_id, after_id)
                    if diff:
                        enrichment["diff"] = {
                            "nodes_added": diff.nodes_added,
                            "nodes_removed": diff.nodes_removed,
                            "edges_added": diff.edges_added,
                            "edges_removed": diff.edges_removed,
                            "summary": diff.summary(),
                        }
            except Exception:
                pass

        # ── Knowledge recording ─────────────────────────────────────
        problem_signature = f"build_failure:{log_name}"
        outcome = "fixed" if fixed else "failed"
        risk_info = enrichment["risk_assessment"] or {}
        record = KnowledgeRecord(
            problem_signature=problem_signature,
            root_cause=result.get("root_cause", "Unknown"),
            action_taken=action_taken,
            outcome=outcome,
            confidence=0.8 if fixed else 0.2,
            success_rate=1.0 if fixed else 0.0,
        )
        knowledge_engine.add_knowledge(record)
        knowledge_engine.update_knowledge_usage(problem_signature, fixed)

        result["enrichment"] = enrichment
        return result
