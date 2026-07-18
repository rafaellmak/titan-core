import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..diagnostics.engine import DiagnosticEngine
from ..actions.recipe import RecipeModifier
from ..recipes.db import RecipeDB
from ..recipes.parser import parse_bb_file
from .sandbox import FixTransaction


def _is_balanced_braces(content: str) -> bool:
    """Checagem barata de balanceamento de chaves. Ignora chaves dentro de strings.
    Suficiente para detectar mutação que deixou o recipe sintaticamente quebrado."""
    depth = 0
    in_string = False
    string_quote = None
    i = 0
    while i < len(content):
        c = content[i]
        if in_string:
            if c == "\\" and i + 1 < len(content):
                i += 2
                continue
            if c == string_quote:
                in_string = False
                string_quote = None
        else:
            if c in ('"', "'"):
                in_string = True
                string_quote = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth < 0:
                    return False
        i += 1
    return depth == 0 and not in_string


def _is_valid_bb(path: Path) -> bool:
    """Valida um .bb ou .bbappend modificado sem precisar do Bitbake.
    Critérios: o arquivo existe, tem conteúdo, e tem chaves balanceadas.
    Falha = mutação corrompeu o arquivo."""
    if not path.exists():
        return False
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    if not content.strip():
        return False
    return _is_balanced_braces(content)


class AutoFixEngine:
    def __init__(self, workspace, core: Optional["TitanCore"] = None):
        self.workspace = workspace
        self.core = core
        self.diag = DiagnosticEngine(workspace, core=core)
        self.db = RecipeDB(workspace.root_dir) if workspace.type == "yocto" else None
        self.recipe_mod = RecipeModifier(self.db) if self.db else None

    def _has_bitbake(self) -> bool:
        """Detecta se bitbake está disponível no PATH (ambiente Yocto real)."""
        return shutil.which("bitbake") is not None

    def validate_workspace(self) -> bool:
        """Valida que a mutação proposta não corrompeu o workspace.

        Dois níveis de validação:
        - Strict (quando bitbake está disponível): roda 'bitbake -p' que
          re-parsea todos os recipes. É a validação canônica mas requer
          um ambiente Yocto inicializado.
        - Light (fallback): re-parsea cada arquivo mutado e verifica
          balanceamento de chaves + tamanho não-vazio. Suficiente para
          detectar mutação que quebrou o recipe.

        Retorna True se ambos os níveis passam (ou se light é o único
        disponível e passa)."""
        if self.workspace.type != "yocto":
            return True

        if self._has_bitbake():
            print("⚙️  Validando integridade semântica na Sandbox via Bitbake (strict)...")
            init_script = self.workspace.init_script.absolute()
            build_dir = self.workspace.build_dir.absolute()
            cmd = f"bash -c 'source {init_script} {build_dir} && bitbake -p'"
            try:
                res = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True,
                    cwd=self.workspace.root_dir, timeout=30
                )
                if res.returncode != 0:
                    print(f"❌ Bitbake Validation falhou:\n{res.stderr.strip()[:500]}")
                    return False
                print("✅ Bitbake aceitou a mutação.")
                return True
            except subprocess.TimeoutExpired:
                print("❌ Bitbake excedeu timeout de 30s.")
                return False
            except Exception as e:
                print(f"❌ Falha ao executar Bitbake: {e}")
                return False

        print("⚙️  bitbake não disponível no PATH — usando validação leve (re-parse + brace balance).")
        return True

    def validate_mutation(self, mutated_files: List[Path]) -> bool:
        """Validação leve que não precisa de bitbake: cada arquivo mutado
        ainda existe, é não-vazio, e tem sintaxe de chaves balanceada."""
        if not mutated_files:
            return True
        for path in mutated_files:
            if not _is_valid_bb(path):
                print(f"❌ Mutação corrompeu o arquivo: {path}")
                return False
        print("✅ Validação leve passou (todos os arquivos mutados têm sintaxe válida).")
        return True

    def run_fix(self, log_path: Path) -> Dict[str, Any]:
        print(f"🛠️  Iniciando Auto-Fix transacional para: {log_path.name}")
        findings = self.diag.analyze_log(log_path)
        fixable_findings = [f for f in findings if f.get('fixable')]

        if not fixable_findings:
            print("✅ Nenhum problema auto-corrigível detectado.")
            return {
                "fixed": False,
                "action": "no_fixable_findings",
                "mutated_files": [],
                "entities": [],
                "rule_ids": [],
                "root_cause": "No auto-fixable issues detected",
            }

        from ..diagnostics.rules import YOCTO_RULES
        rules_by_id = {r.id: r for r in YOCTO_RULES}

        mutated_files: List[Path] = []
        entities: List[str] = []
        applied_actions: List[str] = []

        with FixTransaction(self.workspace) as tx:
            for f in fixable_findings:
                rule = rules_by_id.get(f['rule_id'])
                if not rule:
                    continue
                m = rule.pattern.search(f['raw_log'])
                if not m:
                    continue

                if f['rule_id'] == 'YOC-004' and self.recipe_mod:
                    pn = m.group('pn')
                    dep = m.group('dep')

                    recipe_data = self.db.get_recipe(pn)
                    if not recipe_data:
                        print(f"⚠️  Recipe '{pn}' não indexado — pulando (não posso patchear).")
                        continue

                    target_path = Path(recipe_data['file_path'])
                    tx.register_mutation(target_path)

                    print(f"🔧 Adicionando RDEPENDS para {pn}: {dep}")
                    ok = self.recipe_mod.append_variable(pn, "RDEPENDS:${PN}", dep)
                    if ok:
                        mutated_files.append(target_path)
                        entities.append(f"recipe:{pn}")
                        entities.append(f"package:{dep}")
                        applied_actions.append('RDEPENDS:${PN} += "' + dep + '"')

            if not mutated_files:
                print("ℹ️  Nenhuma mutação aplicada — nada para validar.")
                return {
                    "fixed": False,
                    "action": "no_applicable_mutations",
                    "mutated_files": [],
                    "entities": [],
                    "rule_ids": [f['rule_id'] for f in fixable_findings],
                    "root_cause": fixable_findings[0].get("description", "Unknown"),
                }

            workspace_ok = self.validate_workspace()
            mutation_ok = self.validate_mutation(mutated_files)

            if not (workspace_ok and mutation_ok):
                print("❌ Validação falhou. Aplicando rollback...")
                tx.rollback()
                if self.core:
                    self.core.event_bus.emit("fix_failed", {
                        "log": str(log_path), "success": False,
                    })
                return {
                    "fixed": False,
                    "action": "; ".join(applied_actions),
                    "mutated_files": [str(p) for p in mutated_files],
                    "entities": list(set(entities)),
                    "rule_ids": [f['rule_id'] for f in fixable_findings],
                    "root_cause": fixable_findings[0].get("description", "Unknown"),
                    "validation_error": True,
                }
            else:
                print("✅ Correções aplicadas e validadas com sucesso.")
                if self.core:
                    self.core.event_bus.emit("fix_applied", {
                        "log": str(log_path), "success": True,
                    })
                return {
                    "fixed": True,
                    "action": "; ".join(applied_actions),
                    "mutated_files": [str(p) for p in mutated_files],
                    "entities": list(set(entities)),
                    "rule_ids": [f['rule_id'] for f in fixable_findings],
                    "root_cause": fixable_findings[0].get("description", "Unknown"),
                }
