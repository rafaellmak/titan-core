from titan.core.planner import Skill
from titan.core.memory import MultiLayerMemory
from titan.core.digital_twin import DigitalTwin
from titan.core.knowledge_engine import KnowledgeEngine
from titan.hardware.dt_analyzer import DeviceTreeAnalyzer
from typing import Any, Dict

class DTSSkill(Skill):
    def can_handle(self, event_type: str, data: Dict[str, Any]) -> bool:
        return event_type == "analyze_hardware" or \
               (event_type == "file_changed" and data.get("path", "").endswith(".dts"))

    async def execute(self, data: Dict[str, Any], memory: MultiLayerMemory, digital_twin: DigitalTwin, knowledge_engine: KnowledgeEngine) -> Any:
        path = data.get("path")
        if not path:
            return {"error": "No DTS path provided"}
            
        analyzer = DeviceTreeAnalyzer()
        report = analyzer.analyze_dts(path)
        
        memory.log_event("DTS_ANALYSIS", {"path": path, "report": report})
        # Potentially emit events to digital_twin about hardware components or issues
        # await digital_twin.emit_event("hardware_analyzed", {"path": path, "report": report})
        return report
