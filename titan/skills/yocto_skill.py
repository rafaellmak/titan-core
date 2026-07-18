from titan.core.planner import Skill
from titan.core.memory import MultiLayerMemory
from titan.core.digital_twin import DigitalTwin
from titan.core.knowledge_engine import KnowledgeEngine
from titan.recipes.indexer import RecipeIndexer
from titan.workspace.detector import WorkspaceDetector
from titan.workspace.models import YoctoWorkspace
from typing import Any, Dict

class YoctoSkill(Skill):
    def can_handle(self, event_type: str, data: Dict[str, Any]) -> bool:
        return event_type == "workspace_scan" or event_type == "file_changed"

    async def execute(self, data: Dict[str, Any], memory: MultiLayerMemory, digital_twin: DigitalTwin, knowledge_engine: KnowledgeEngine) -> Any:
        detector = WorkspaceDetector()
        workspace = detector.detect()
        
        if isinstance(workspace, YoctoWorkspace):
            memory.update_state("workspace", workspace.to_dict())
            indexer = RecipeIndexer(workspace)
            recipes = indexer.index_all()
            memory.update_state("recipes_count", len(recipes))

            # Update Digital Twin with workspace info
            digital_twin.emit_event("workspace_scanned", {"workspace_type": workspace.type, "path": str(workspace.root_dir)})
            for layer in workspace.layers:
                digital_twin.emit_event("layer_added", {"layer": str(layer.name)})
            for recipe_data in recipes:
                digital_twin.emit_event("recipe_added", {"recipe": recipe_data["recipe_data"]["pn"], "layer": recipe_data["layer_name"]})

            return {"status": "indexed", "count": len(recipes)}
        
        return {"status": "no_yocto_workspace"}
