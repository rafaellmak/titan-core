import asyncio
from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
import networkx as nx

from titan.core.async_event_bus import QueuedEventBus
from titan.core.digital_twin import TwinManager
from titan.core.memory import MultiLayerMemory
from titan.core.planner import SkillPlanner
from titan.skills.yocto_skill import YoctoSkill
from titan.skills.dts_skill import DTSSkill
from titan.skills.security_skill import SecuritySkill
from titan.skills.autofix_skill import AutoFixSkill
from titan.skills.buildroot_skill import BuildrootSkill
from titan.validation.harness import ValidationHarness

event_bus = QueuedEventBus()
twin_mgr = TwinManager()
twin = twin_mgr.get("default", event_bus)
memory = MultiLayerMemory(event_bus, digital_twin=twin)
harness = ValidationHarness()
planner = SkillPlanner(memory, twin, memory.knowledge_engine, harness=harness)

planner.register_skill(YoctoSkill())
planner.register_skill(DTSSkill())
planner.register_skill(SecuritySkill())
planner.register_skill(AutoFixSkill())
planner.register_skill(BuildrootSkill())

app = FastAPI(title="Titan Embedded Intelligence Runtime", version="12.0")

async def event_loop_worker():
    """Autonomous loop: consumes events and dispatches to skills"""
    print("[Daemon] Event Loop iniciado. Escutando ambiente...")
    async for event in event_bus.listen():
        event_type = event.get("type")
        data = event.get("data", {})
        await planner.dispatch(event_type, data)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(event_loop_worker())


class AnalysisRequest(BaseModel):
    query: str
    context: Optional[dict] = None

class HardwareAnalyzeRequest(BaseModel):
    path: str = Field(..., description="Path to the Device Tree file (.dts/.dtsi)")

class BuildFailureRequest(BaseModel):
    log_path: str = Field(..., description="Path to the build log file")
    recipe: Optional[str] = Field(None, description="Optional recipe PN that failed")
    task: Optional[str] = Field(None, description="Optional task name (e.g. do_compile)")

class SnapshotRequest(BaseModel):
    snapshot_id: str = Field(..., description="Identifier for this snapshot")
    note: Optional[str] = Field(None, description="Optional human note")

class LearnRequest(BaseModel):
    problem_signature: str = Field(..., description="Signature of the problem that was acted on")
    success: bool = Field(..., description="Whether the action succeeded")
    notes: Optional[str] = Field(None, description="Optional notes from the operator")


@app.post("/api/v1/analyze")
async def trigger_analysis(request: AnalysisRequest):
    """Trigger a manual analysis via API"""
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="query is required and cannot be empty")
    await event_bus.emit("user_query", {"query": request.query, "context": request.context or {}})
    return {"status": "Analysis queued", "event_type": "user_query"}


@app.post("/api/v1/workspace/scan")
async def scan_workspace():
    """Scan the Yocto workspace"""
    await event_bus.emit("workspace_scan", {})
    return {"status": "Workspace scan queued"}


@app.post("/api/v1/buildroot/scan")
async def scan_buildroot():
    """Scan the Buildroot workspace"""
    await event_bus.emit("buildroot_scan", {})
    return {"status": "Buildroot scan queued"}


@app.post("/api/v1/hardware/analyze")
async def analyze_hardware(request: HardwareAnalyzeRequest):
    """Analyze a Device Tree file (body: {path: '...'})"""
    await event_bus.emit("analyze_hardware", {"path": request.path})
    return {"status": "Hardware analysis queued"}


@app.post("/api/v1/security/scan")
async def security_scan():
    """Trigger a security scan for CVEs"""
    await event_bus.emit("security_scan", {})
    return {"status": "Security scan queued"}


@app.post("/api/v1/build/failure")
async def report_build_failure(request: BuildFailureRequest):
    """Report a build failure and trigger AutoFix (body: {log_path, recipe?, task?})"""
    await event_bus.emit("build_failed", {
        "log_path": request.log_path,
        "recipe": request.recipe,
        "task": request.task,
    })
    return {"status": "Build failure logged, AutoFix triggered"}


@app.get("/api/v1/state")
async def get_state(key: str = Query(..., min_length=1, description="State key to fetch")):
    """Get current state from memory"""
    if not key:
        raise HTTPException(status_code=400, detail="key is required")
    value = memory.get_state(key)
    if value is None:
        return {"key": key, "value": None, "found": False}
    return {"key": key, "value": value, "found": True}


@app.get("/api/v1/digital_twin/graph")
async def get_digital_twin_graph():
    """Get the current state of the Digital Twin graph"""
    graph_data = nx.node_link_data(memory.digital_twin.get_graph())
    return {"graph": graph_data}


@app.get("/api/v1/digital_twin/impact")
async def query_digital_twin_impact(
    node_id: str = Query(..., min_length=1, description="Node ID to query")
):
    """Query impact analysis for a given node in the Digital Twin"""
    impact = memory.digital_twin.query_impact(node_id)
    return {"node_id": node_id, "impact": impact}


@app.get("/api/v1/digital_twin/timeline")
async def get_digital_twin_timeline(hours: int = Query(24, ge=1, le=8760)):
    """Get recent events from the Digital Twin timeline (hours: 1..8760)"""
    timeline = memory.digital_twin.get_timeline(hours)
    return {"timeline": timeline, "hours": hours}


@app.post("/api/v1/digital_twin/snapshot")
async def create_digital_twin_snapshot(request: SnapshotRequest):
    """Create a snapshot of the Digital Twin (body: {snapshot_id, note?})"""
    if not request.snapshot_id.strip():
        raise HTTPException(status_code=400, detail="snapshot_id is required and cannot be empty")
    memory.digital_twin.create_snapshot(request.snapshot_id, note=request.note)
    return {"status": f"Snapshot {request.snapshot_id} created"}


@app.get("/api/v1/knowledge/similar")
async def find_similar_knowledge(
    problem_description: str = Query(..., min_length=1, description="Problem to find similar records for")
):
    """Find similar knowledge records based on a problem description"""
    similar_records = memory.knowledge_engine.find_similar_knowledge(problem_description)
    return {"similar_records": [record.to_dict() for record in similar_records]}


@app.get("/api/v1/knowledge/ranked")
async def get_ranked_knowledge():
    """Get ranked knowledge records"""
    ranked_records = memory.knowledge_engine.get_ranked_knowledge()
    return {"ranked_records": [record.to_dict() for record in ranked_records]}


@app.get("/api/v1/knowledge/explain")
async def explain_knowledge(
    problem_signature: str = Query(..., min_length=1, description="Knowledge record signature")
):
    """Get an explanation for a knowledge record"""
    record = memory.knowledge_engine.get_knowledge(problem_signature)
    if not record:
        raise HTTPException(status_code=404, detail=f"Knowledge record not found: {problem_signature}")
    return {"explanation": memory.knowledge_engine.explain_knowledge(record)}


@app.post("/api/v1/knowledge/learn")
async def learn_from_outcome(request: LearnRequest):
    """Update knowledge based on the outcome of an action (body: {problem_signature, success, notes?})"""
    memory.knowledge_engine.update_knowledge_usage(
        request.problem_signature, request.success, notes=request.notes
    )
    return {"status": "Knowledge updated", "problem_signature": request.problem_signature, "success": request.success}


@app.get("/api/v1/knowledge/failure_patterns")
async def get_failure_patterns(
    min_occurrences: int = Query(15, ge=1, le=10000, description="Minimum occurrences to flag a pattern")
):
    """Recognize recurring failure patterns (min_occurrences: 1..10000)"""
    patterns = memory.knowledge_engine.recognize_failure_patterns(min_occurrences)
    return {"failure_patterns": patterns, "min_occurrences": min_occurrences}


@app.get("/api/v1/diagnostics")
async def get_diagnostics():
    """Get audit log and diagnostics"""
    return {"status": "Diagnostics endpoint ready", "version": app.version}


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "version": "12.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
