import re
from pathlib import Path
from ..workspace.models import YoctoWorkspace
from .db import RecipeDB
from .parser import parse_bb_file

class RecipeIndexer:
    def __init__(self, workspace: YoctoWorkspace, digital_twin=None):
        self.workspace = workspace
        self.db = RecipeDB(workspace.root_dir)
        self.digital_twin = digital_twin
        self.bbmask_regex = None
        
        # Compila BBMASK se configurado no local.conf
        if self.workspace.bbmask and self.workspace.bbmask != "unknown":
            try:
                self.bbmask_regex = re.compile(self.workspace.bbmask)
            except re.error as e:
                print(f"⚠️ Falha ao compilar regex do BBMASK '{self.workspace.bbmask}': {e}")

    def index_all(self):
        print(f"🔄 Iniciando indexação de {len(self.workspace.layers)} layers...")
        indexed_recipes = []
        for layer in self.workspace.layers:
            if not layer.exists(): continue
            
            layer_name = layer.name
            if self.digital_twin:
                self.digital_twin.emit_event("layer_added", {"layer": layer_name})
            
            for bb_file in layer.rglob("*.bb"):
                # Aplica filtro BBMASK se ativo no workspace
                if self.bbmask_regex and self.bbmask_regex.search(str(bb_file)):
                    continue
                    
                try:
                    data = parse_bb_file(bb_file)
                    self.db.upsert_recipe(data)
                    indexed_recipes.append({"recipe_data": data, "layer_name": layer_name})
                    
                    if self.digital_twin:
                        self.digital_twin.emit_event("recipe_added", {
                            "recipe": data["pn"], "layer": layer_name
                        })
                        if data.get("depends"):
                            for dep in data["depends"].split():
                                self.digital_twin.emit_event("dependency_added", {
                                    "source_recipe": data["pn"], "target_package": dep
                                })
                        if data.get("rdepends"):
                            for dep in data["rdepends"].split():
                                self.digital_twin.emit_event("dependency_added", {
                                    "source_recipe": data["pn"], "target_package": dep
                                })
                except Exception as e:
                    print(f"⚠️ Erro ao indexar {bb_file.name}: {e}")
                    
        print(f"✅ Indexação concluída! {len(indexed_recipes)} recipes armazenados no banco de dados (BBMASKs aplicados).")
        return indexed_recipes
