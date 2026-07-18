import re
from pathlib import Path
from typing import Optional
from ..recipes.db import RecipeDB
from ..workspace.models import YoctoWorkspace

class RecipeModifier:
    def __init__(self, db: RecipeDB, workspace: YoctoWorkspace = None):
        self.db = db
        self.workspace = workspace

    def _is_upstream_recipe(self, path: Path) -> bool:
        """Determina se o recipe reside em uma layer upstream / somente leitura."""
        upstream_keywords = ["poky", "openembedded", "meta-oe", "meta-python", "meta-networking", "meta-filesystems", "meta-perl", "meta-multimedia"]
        path_str = str(path).lower()
        return any(k in path_str for k in upstream_keywords)

    def _discover_recipe_on_disk(self, pn: str) -> Optional[Path]:
        """Procura um .bb/.bbappend no filesystem para o PN dado (fallback quando o DB não tem)."""
        if not self.workspace:
            return None
        candidates = []
        for layer in self.workspace.layers:
            if not layer.exists():
                continue
            for ext in ("*.bb", "*.bbappend"):
                for p in layer.rglob(ext):
                    if p.name.startswith(f"{pn}_") or p.name.startswith(f"{pn}."):
                        candidates.append(p)
        if not candidates:
            return None
        candidates.sort(key=lambda p: (p.suffix != ".bb", len(str(p))))
        return candidates[0]

    def _find_local_custom_layer(self, target_layer: str = None) -> Path:
        """Localiza a melhor layer local para criar arquivos .bbappend."""
        if target_layer:
            layer_path = Path(target_layer).resolve()
            if layer_path.exists():
                return layer_path
            # Tenta buscar pelo nome da pasta se não for caminho absoluto
            if self.workspace and self.workspace.layers:
                for layer in self.workspace.layers:
                    if layer.name == target_layer:
                        return layer
            print(f"⚠️ Layer '{target_layer}' não encontrada. Usando detecção automática.")

        if self.workspace and self.workspace.layers:
            for layer in self.workspace.layers:
                if not self._is_upstream_recipe(layer):
                    return layer
        # Fallback de segurança se nenhuma layer customizada for encontrada
        fallback_path = self.workspace.root_dir / "meta-titan-local" if self.workspace else Path("meta-titan-local")
        fallback_path.mkdir(exist_ok=True)
        return fallback_path

    def _get_yocto_override_char(self, content: str) -> str:
        """Detecta se o recipe usa a sintaxe moderna ':' (post-Honister) ou antiga '_' para overrides."""
        modern_count = len(re.findall(r'\b[A-Z_][A-Z0-9_]*:[a-zA-Z0-9_-]+\s*=', content))
        legacy_count = len(re.findall(r'\b[A-Z_][A-Z0-9_]*_[a-zA-Z0-9_-]+\s*=', content))
        return ":" if modern_count >= legacy_count else "_"

    def _format_var_name(self, var_name: str, content: str) -> str:
        """Formata o nome da variável usando o caractere de override correto. NÃO troca chars no meio do nome."""
        if ":" in var_name or "_" in var_name.split("=")[0]:
            override_char = self._get_yocto_override_char(content)
            if ":" in var_name:
                prefix, override = var_name.split(":", 1)
                return f"{prefix}:{override}" if override_char == ":" else f"{prefix}_{override}"
        return var_name

    def _generate_bbappend(self, pn: str, original_path: Path, var_name: str, value: str, target_layer: str = None) -> bool:
        """Gera um arquivo .bbappend em uma layer customizada local de forma segura."""
        local_layer = self._find_local_custom_layer(target_layer)

        recipes_group = "recipes-custom"
        for part in original_path.parts:
            if part.startswith("recipes-"):
                recipes_group = part
                break

        append_dir = local_layer / recipes_group / pn
        append_dir.mkdir(parents=True, exist_ok=True)

        append_file = append_dir / f"{pn}_%.bbappend"

        existing_content = append_file.read_text(errors='ignore') if append_file.exists() else ""
        formatted_var = self._format_var_name(var_name, existing_content)

        with open(append_file, "a", encoding="utf-8") as f:
            f.write(f"\n# --- Auto-patched by Titan ---\n{formatted_var} += \"{value}\"\n")

        print(f"✅ .bbappend gerado de forma segura em: {append_file}")
        return True

    def append_variable(self, pn: str, var_name: str, value: str, target_layer: str = None) -> bool:
        recipe = self.db.get_recipe(pn)
        if not recipe and self.workspace:
            discovered = self._discover_recipe_on_disk(pn)
            if discovered:
                recipe = {"pn": pn, "file_path": str(discovered)}
        if not recipe:
            print(f"❌ Recipe '{pn}' não encontrada no banco nem no filesystem.")
            print(f"   Dica: rode 'titan index' para indexar a workspace, ou verifique o nome (PN).")
            return False
        
        path = Path(recipe['file_path'])
        if not path.exists():
            print(f"❌ Arquivo físico não encontrado: {path}")
            return False
            
        # Protege o BSP upstream criando um .bbappend se necessário
        if self._is_upstream_recipe(path):
            return self._generate_bbappend(pn, path, var_name, value, target_layer)
            
        content = path.read_text(errors='ignore')
        formatted_var = self._format_var_name(var_name, content)

        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n# --- Auto-patched by Titan ---\n{formatted_var} += \"{value}\"\n")

        print(f"✅ Recipe local '{pn}' modificado: {formatted_var} += \"{value}\"")
        return True
