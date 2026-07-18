import sqlite3
from pathlib import Path
from typing import List, Dict, Set, Optional

class KnowledgeGraph:
    """Motor de Grafo de Conhecimento Determinístico para o Titan Enterprise."""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS graph_edges (
                    source TEXT,
                    target TEXT,
                    relation TEXT,
                    metadata TEXT,
                    PRIMARY KEY (source, target, relation)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_source ON graph_edges(source)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_target ON graph_edges(target)")

    def add_edge(self, source: str, target: str, relation: str, metadata: str = ""):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO graph_edges VALUES (?, ?, ?, ?)",
                (source, target, relation, metadata)
            )

    def get_dependencies(self, node: str, depth: int = 1) -> Set[str]:
        deps = set()
        to_visit = [(node, 0)]
        visited = set()

        while to_visit:
            current, current_depth = to_visit.pop(0)
            if current in visited or current_depth >= depth:
                continue
            
            visited.add(current)
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT target FROM graph_edges WHERE source = ? AND relation IN ('depends_on', 'builds')",
                    (current,)
                )
                for row in cursor:
                    deps.add(row[0])
                    to_visit.append((row[0], current_depth + 1))
        return deps

    def why(self, node: str) -> List[Dict]:
        """Explica por que um nó existe no grafo (quem depende dele)."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT source, relation, metadata FROM graph_edges WHERE target = ?",
                (node,)
            )
            return [{"source": row[0], "relation": row[1], "metadata": row[2]} for row in cursor]

    def impact(self, node: str) -> List[str]:
        """Calcula o impacto de remover ou alterar um nó (quem quebra)."""
        impacted = set()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT source FROM graph_edges WHERE target = ? AND relation = 'depends_on'",
                (node,)
            )
            for row in cursor:
                impacted.add(row[0])
        return list(impacted)

class GraphEngine:
    """Interface de alto nível para manipulação do grafo."""
    def __init__(self, db):
        self.db = db
        self.graph = KnowledgeGraph(db.db_path)

    def sync_from_recipes(self):
        """Sincroniza o grafo a partir das receitas indexadas."""
        recipes = self.db.search_recipes("")
        for r in recipes:
            pn = r['pn']
            layer_name = Path(r['file_path']).parts[-3] if len(Path(r['file_path']).parts) >= 3 else "unknown"
            self.graph.add_edge(pn, layer_name, "belongs_to")
            
            if r.get('depends'):
                for dep in r['depends'].split():
                    self.graph.add_edge(pn, dep, "depends_on")

            if r.get('rdepends'):
                for dep in r['rdepends'].split():
                    self.graph.add_edge(pn, dep, "depends_on")

    def get_deps_list(self, pn: str) -> List[str]:
        deps = list(self.graph.get_dependencies(pn, depth=2))
        if not deps:
            recipe = self.db.get_recipe(pn)
            if recipe:
                raw = (recipe.get("depends") or "") + " " + (recipe.get("rdepends") or "")
                deps = sorted(set(raw.split()))
        return deps if deps else []

    def get_impact_list(self, pn: str) -> List[str]:
        reasons = self.graph.why(pn)
        if reasons:
            return sorted(set(r["source"] for r in reasons))
        all_recipes = self.db.get_all_recipes()
        dependents = []
        for r in all_recipes:
            deps = (r.get("depends") or "") + " " + (r.get("rdepends") or "")
            if pn in deps.split():
                dependents.append(r["pn"])
        return sorted(set(dependents))

    def print_tree(self, node: str, reverse: bool = False):
        if reverse:
            print(f"🔍 Impacto de '{node}' (quem depende dele):")
            reasons = self.graph.why(node)
            if reasons:
                for r in reasons:
                    print(f"  ├─ [{r['relation']}] {r['source']}")
            else:
                self._fallback_print_impact(node)
        else:
            print(f"📦 Dependências de '{node}':")
            deps = self.graph.get_dependencies(node, depth=2)
            if deps:
                for d in sorted(deps):
                    print(f"  ├─ {d}")
            else:
                self._fallback_print_deps(node)

    def _fallback_print_deps(self, pn: str):
        """Fallback: busca dependências diretamente do RecipeDB."""
        recipe = self.db.get_recipe(pn)
        if not recipe:
            print(f"  ⚠️ Recipe '{pn}' não encontrada no banco.")
            return
        deps = []
        if recipe.get("depends"):
            deps.extend(recipe["depends"].split())
        if recipe.get("rdepends"):
            deps.extend(recipe["rdepends"].split())
        if deps:
            for d in sorted(set(deps)):
                print(f"  ├─ {d}")
        else:
            print(f"  ℹ️ Nenhuma dependência declarada para '{pn}'.")

    def _fallback_print_impact(self, pn: str):
        """Fallback: busca quem depende desta recipe no RecipeDB."""
        all_recipes = self.db.get_all_recipes()
        dependents = []
        for r in all_recipes:
            deps = (r.get("depends") or "") + " " + (r.get("rdepends") or "")
            if pn in deps.split():
                dependents.append(r["pn"])
        if dependents:
            for d in sorted(dependents):
                print(f"  ├─ {d}")
        else:
            print(f"  ℹ️ Nenhum outro recipe depende de '{pn}'.")
