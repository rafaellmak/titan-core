import asyncio
import os
import shutil
from titan.core.event_bus import LocalEventBus
from titan.core.memory import MultiLayerMemory
from titan.core.digital_twin import DigitalTwin
from titan.core.knowledge_engine import KnowledgeEngine
from titan.core.planner import SkillPlanner
from titan.skills.yocto_skill import YoctoSkill
from titan.skills.dts_skill import DTSSkill


async def test_agentic_flow():
    print("--- Testando Titan 12.0 Agentic Evolution ---")

    base = ".titan_test_agentic"
    if os.path.exists(base):
        shutil.rmtree(base)
    os.makedirs(base)

    bus = LocalEventBus()
    memory = MultiLayerMemory(bus, base_path=os.path.join(base, "memory"))
    twin = DigitalTwin(bus, base_path=os.path.join(base, "twin"))
    knowledge = KnowledgeEngine(base_path=os.path.join(base, "knowledge"))
    planner = SkillPlanner(memory, twin, knowledge)

    planner.register_skill(YoctoSkill())
    planner.register_skill(DTSSkill())

    print("[Teste] Emitindo: workspace_scan")
    await planner.dispatch("workspace_scan", {})

    print("[Teste] Emitindo: file_changed (DTS)")
    dts_path = os.path.join(base, "test_board.dts")
    with open(dts_path, "w") as f:
        f.write('/ { model = "Test Board"; };')

    await planner.dispatch("file_changed", {"path": dts_path})

    ws_state = memory.get_state("workspace")
    print(f"[Verificação] Estado do Workspace: {ws_state['type'] if ws_state else 'None'}")

    assert ws_state is not None, "workspace state not set"

    shutil.rmtree(base, ignore_errors=True)
    print("--- Teste Concluído ---")


if __name__ == "__main__":
    asyncio.run(test_agentic_flow())
