import pytest
import asyncio
import os
import shutil
from titan.core.event_bus import LocalEventBus
from titan.core.digital_twin import DigitalTwin
from titan.core.knowledge_engine import KnowledgeEngine, KnowledgeRecord
from titan.core.memory import MultiLayerMemory

@pytest.fixture
def event_bus():
    return LocalEventBus()

@pytest.fixture
def temp_dir():
    path = ".test_titan"
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path)
    yield path
    shutil.rmtree(path)

@pytest.mark.asyncio
async def test_digital_twin_event_sourcing(event_bus, temp_dir):
    dt = DigitalTwin(event_bus, base_path=os.path.join(temp_dir, "dt"))
    
    dt.emit_event("layer_added", {"layer": "meta-titan"})
    dt.emit_event("recipe_added", {"layer": "meta-titan", "recipe": "titan-core"})
    
    # Verify graph state
    graph = dt.get_graph()
    assert f"layer:meta-titan" in graph.nodes
    assert f"recipe:titan-core" in graph.nodes
    assert graph.has_edge("layer:meta-titan", "recipe:titan-core")
    
    # Verify timeline
    timeline = dt.get_timeline()
    assert len(timeline) == 2
    assert timeline[0]["event"] == "layer_added"
    assert timeline[1]["event"] == "recipe_added"

@pytest.mark.asyncio
async def test_digital_twin_impact_analysis(event_bus, temp_dir):
    dt = DigitalTwin(event_bus, base_path=os.path.join(temp_dir, "dt"))
    
    dt.emit_event("layer_added", {"layer": "meta-networking"})
    dt.emit_event("recipe_added", {"layer": "meta-networking", "recipe": "openssl"})
    dt.emit_event("dependency_added", {"source_recipe": "openssl", "target_package": "zlib"})
    
    impact = dt.query_impact("layer:meta-networking")
    assert impact["affected_recipes"] == 1
    assert impact["affected_packages"] == 1

def test_knowledge_engine_similarity_and_learning(temp_dir):
    ke = KnowledgeEngine(base_path=os.path.join(temp_dir, "ke"))
    
    record = KnowledgeRecord(
        problem_signature="Nothing PROVIDES qtbase",
        root_cause="Missing meta-qt6 layer",
        action_taken="bitbake-layers add-layer meta-qt6",
        outcome="fixed",
        confidence=0.8,
        success_rate=0.8
    )
    ke.add_knowledge(record)
    
    # Similarity search
    similar = ke.find_similar_knowledge("Nothing PROVIDES qtbase")
    assert len(similar) > 0
    assert similar[0].problem_signature == "Nothing PROVIDES qtbase"
    
    # Learning loop
    ke.update_knowledge_usage("Nothing PROVIDES qtbase", success=True)
    updated_record = ke.get_knowledge("Nothing PROVIDES qtbase")
    assert updated_record.usage_count == 1
    assert updated_record.success_rate > 0.8
    assert updated_record.confidence > 0.8

@pytest.mark.asyncio
async def test_memory_integration(event_bus, temp_dir):
    memory = MultiLayerMemory(event_bus, base_path=os.path.join(temp_dir, "memory"))
    
    # Add knowledge through memory
    memory.add_knowledge("build", "Nothing PROVIDES bash", {"solution": "Add meta-poky"})
    
    # Verify it reached the KnowledgeEngine
    record = memory.knowledge_engine.get_knowledge("Nothing PROVIDES bash")
    assert record is not None
    assert record.problem_signature == "Nothing PROVIDES bash"
    
    # Verify event was logged to Digital Twin
    timeline = memory.digital_twin.get_timeline()
    # Depending on how log_event is called, it might have events
    memory.log_event("TEST_EVENT", {"data": "test"})
    # log_event agora é síncrono — não precisa de asyncio.sleep
    timeline = memory.digital_twin.get_timeline()
    assert any(e["event"] == "TEST_EVENT" for e in timeline)
