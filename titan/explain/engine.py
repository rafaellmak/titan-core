from pathlib import Path
from typing import Dict, Any, List
from ..recipes.db import RecipeDB
from ..recipes.graph import KnowledgeGraph

class ExplainEngine:
    """Motor determinístico de explicação de dependências e arquitetura de recipes."""
    
    def __init__(self, db: RecipeDB):
        self.db = db
        self.graph = KnowledgeGraph(db.db_path)

    def explain_recipe(self, pn: str) -> str:
        recipe = self.db.get_recipe(pn)
        if not recipe:
            return f"❌ Recipe '{pn}' não indexado no banco de dados local."
            
        reasons = self.graph.why(pn)
        impacts = self.graph.impact(pn)
        
        upstream_status = "Upstream (Read-Only)" if "poky" in recipe['file_path'] or "openembedded" in recipe['file_path'] else "Local (Custom)"
        
        explanation = [
            f"# Explicação Técnica: {pn} (v{recipe['pv']})",
            f"- **Status**: {upstream_status}",
            f"- **Caminho**: `{recipe['file_path']}`",
        ]

        if recipe.get("license"):
            explanation.append(f"- **Licença**: {recipe['license']}")
        if recipe.get("inherits"):
            explanation.append(f"- **Herda de**: {recipe['inherits']}")
        if recipe.get("depends"):
            explanation.append(f"- **DEPENDS**: {recipe['depends']}")
        if recipe.get("rdepends"):
            explanation.append(f"- **RDEPENDS**: {recipe['rdepends']}")
        if recipe.get("src_uri"):
            explanation.append(f"- **SRC_URI**: {recipe['src_uri']}")
        
        explanation.append("\n## Por que este pacote está no build?")
        
        if not reasons:
            explanation.append("Este pacote parece ser um nó raiz ou uma dependência base do sistema.")
        else:
            explanation.append("Dependências que requerem este pacote:")
            for r in reasons:
                explanation.append(f"- `{r['source']}` (via `{r['relation']}`)")
                
        explanation.append("\n## Qual o impacto de alterá-lo?")
        if not impacts:
            explained_impact = self._fallback_impact_from_db(pn, recipe)
            explanation.append(explained_impact)
        else:
            explanation.append(f"Alterações neste pacote podem afetar: {', '.join(impacts)}.")
            
        return "\n".join(explanation)

    def _fallback_impact_from_db(self, pn: str, recipe: dict) -> str:
        """Quando o grafo está vazio, busca dependentes via RecipeDB."""
        all_recipes = self.db.get_all_recipes()
        dependents = []
        for r in all_recipes:
            deps = (r.get("depends") or "") + " " + (r.get("rdepends") or "")
            if pn in deps.split():
                dependents.append(r["pn"])
        if dependents:
            return f"Pode afetar: {', '.join(dependents)}."
        return "Nenhum outro pacote indexado depende diretamente deste recipe."
