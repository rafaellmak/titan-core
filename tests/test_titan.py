import pytest
import tempfile
import sqlite3
import shutil
import os
from pathlib import Path
from titan.workspace.detector import WorkspaceDetector
from titan.workspace.models import YoctoWorkspace
from titan.recipes.db import RecipeDB
from titan.recipes.graph import KnowledgeGraph
from titan.diagnostics.engine import DiagnosticEngine
from titan.actions.recipe import RecipeModifier
from titan.autofix.sandbox import FixTransaction
from titan.autofix.engine import AutoFixEngine
from titan.security.cve_monitor import CVEMonitor
from titan.explain.engine import ExplainEngine

@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)

def test_workspace_detector_none(temp_workspace):
    workspace = WorkspaceDetector.detect(temp_workspace)
    assert workspace is None

def test_recipe_db_operations(temp_workspace):
    db = RecipeDB(temp_workspace)
    recipe_data = {
        "pn": "openssl",
        "pv": "3.0.8",
        "license": "Apache-2.0",
        "depends": "zlib",
        "rdepends": "",
        "src_uri": "https://openssl.org",
        "inherits": "",
        "file_path": str(temp_workspace / "openssl_3.0.8.bb")
    }
    db.upsert_recipe(recipe_data)
    fetched = db.get_recipe("openssl")
    assert fetched is not None
    assert fetched["pv"] == "3.0.8"

def test_knowledge_graph(temp_workspace):
    db_file = temp_workspace / "recipes.db"
    graph = KnowledgeGraph(db_file)
    graph.add_edge("libfoo", "libbar", "depends_on")
    deps = graph.get_dependencies("libfoo", depth=1)
    assert "libbar" in deps

def test_autofix_sandbox_rollback(temp_workspace):
    # Cria workspace fictício
    root = temp_workspace
    build_dir = root / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    
    recipe_dir = root / "recipes-test"
    recipe_dir.mkdir(parents=True, exist_ok=True)
    recipe_file = recipe_dir / "test-recipe.bb"
    recipe_file.write_text("RDEPENDS:${PN} = \"\"", encoding="utf-8")
    
    # Simula inicialização do workspace
    ws = YoctoWorkspace(
        root_dir=root,
        build_dir=build_dir,
        init_script=root / "oe-init-build-env"
    )
    
    # Inicia transação e simula mutação com falha subsequente para testar Rollback
    with FixTransaction(ws) as tx:
        tx.register_mutation(recipe_file)
        # Altera arquivo na sandbox
        recipe_file.write_text("MUTATION", encoding="utf-8")
        assert recipe_file.read_text() == "MUTATION"
        # Força falha e executa rollback
        tx.rollback()
        
    # Garante que o arquivo voltou ao estado íntegro original
    assert recipe_file.read_text() == "RDEPENDS:${PN} = \"\""

def test_cve_monitor_cache(temp_workspace):
    db = RecipeDB(temp_workspace)
    monitor = CVEMonitor(db)
    # Garante que a inicialização cria a tabela de cache sem falhas
    assert monitor.scan_workspace(online=False) is not None

def test_explain_engine(temp_workspace):
    db = RecipeDB(temp_workspace)
    recipe_data = {
        "pn": "zlib",
        "pv": "1.2.11",
        "license": "Zlib",
        "depends": "",
        "rdepends": "",
        "src_uri": "",
        "inherits": "",
        "file_path": "/recipes-core/zlib/zlib_1.2.11.bb"
    }
    db.upsert_recipe(recipe_data)
    engine = ExplainEngine(db)
    explanation = engine.explain_recipe("zlib")
    assert "zlib" in explanation

# Módulos enterprise não implementados ainda (planejado para v13)
# from titan.enterprise.auth import AuthManager
# from titan.enterprise.models import EnterpriseDB
# from titan.enterprise.hardening import SecurityHardening
