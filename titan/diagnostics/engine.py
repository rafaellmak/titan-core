import re
from pathlib import Path
from typing import List, Dict, Optional
from .rules import YOCTO_RULES, C_CPP_RULES
from ..workspace.models import Workspace
from ..recipes.db import RecipeDB
from ..buildroot.diagnostics import analyze_build_log

class DiagnosticEngine:
    """Motor de Diagnóstico Determinístico para o Titan Enterprise."""

    def __init__(self, workspace: Workspace, core: Optional["TitanCore"] = None):
        self.workspace = workspace
        self.core = core
        self.rules = []
        if self.workspace and self.workspace.type == "yocto":
            self.rules.extend(YOCTO_RULES)
        self.rules.extend(C_CPP_RULES)

    def analyze_log(self, log_path: Path) -> List[Dict]:
        if not log_path.exists():
            raise FileNotFoundError(f"Log não encontrado: {log_path}")

        findings = []
        db = None
        if self.workspace and self.workspace.type == "yocto":
            db = RecipeDB(self.workspace.root_dir)

        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Regras baseadas em padrões (Yocto + C/CPP)
        for line_num, line in enumerate(content.splitlines(), 1):
            for rule in self.rules:
                match = rule.pattern.search(line)
                if match:
                    try:
                        suggestion = rule.suggestion.format(**match.groupdict())
                    except KeyError:
                        suggestion = rule.suggestion
                        
                    # Se for erro de Nothing PROVIDES, tentamos buscar no banco local se o recipe existe
                    if rule.id == "YOC-001" and db:
                        target = match.groupdict().get("target", "")
                        recipes = db.search_recipes(target)
                        if recipes:
                            suggestion += f"\n   💡 [Titan Intelligence]: O target '{target}' FOI ENCONTRADO no banco local (ex: {recipes[0]['pn']}). Verifique a variável BBMASK ou se a layer correspondente foi removida do bblayers.conf.\n"
                        else:
                            suggestion += f"\n   💡 [Titan Intelligence]: O target '{target}' realmente não está indexado no banco de dados atual.\n"

                    findings.append({
                        "line": line_num,
                        "rule_id": rule.id,
                        "severity": rule.severity,
                        "description": rule.description,
                        "suggestion": suggestion,
                        "fixable": getattr(rule, 'fixable', False),
                        "raw_log": line.strip()
                    })

        # Se for Buildroot, aplicar diagnosticos especificos
        if self.workspace and self.workspace.type == "buildroot":
            br_findings = analyze_build_log(content)
            for brf in br_findings:
                findings.append({
                    "line": 0,
                    "rule_id": "BR-001",
                    "severity": "Error",
                    "description": brf['error'],
                    "suggestion": brf['solution'],
                    "fixable": False,
                    "raw_log": ""
                })

        # Integração com TitanCore: emitir evento e atualizar knowledge
        if self.core:
            self.core.event_bus.emit("diagnose_completed", {
                "log": str(log_path),
                "findings_count": len(findings),
            })
            for f in findings:
                record = self.core.knowledge_engine.get_knowledge(f["rule_id"])
                if not record:
                    from titan.core.knowledge_engine import KnowledgeRecord
                    self.core.knowledge_engine.add_knowledge(KnowledgeRecord(
                        problem_signature=f["rule_id"],
                        root_cause=f["description"],
                        action_taken="diagnosed",
                        outcome="found",
                        confidence=0.9,
                        success_rate=1.0,
                    ))

        return findings
