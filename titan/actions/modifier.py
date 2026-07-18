from pathlib import Path
from ..workspace.models import YoctoWorkspace
import subprocess

class WorkspaceModifier:
    def __init__(self, workspace: YoctoWorkspace):
        self.workspace = workspace

    def append_local_conf(self, content: str) -> bool:
        """Adiciona conteúdo ao local.conf de forma segura"""
        local_conf = self.workspace.build_dir / "conf" / "local.conf"
        if not local_conf.exists():
            print(f"❌ local.conf não encontrado em {local_conf}")
            return False
        
        with open(local_conf, "a") as f:
            f.write(f"\n# --- Adicionado pelo Titan ---\n{content}\n")
        print(f"✅ Conteúdo adicionado ao local.conf com sucesso.")
        return True

    def add_layer(self, layer_path: str) -> bool:
        """Adiciona uma layer. Tenta bitbake-layers (com source do init script) primeiro;
        se não estiver disponível, edita bblayers.conf diretamente como fallback."""
        import shutil
        from ..workspace.parsers import parse_bblayers

        layer_abs = Path(layer_path).expanduser().resolve()
        if not layer_abs.exists():
            print(f"❌ Layer não encontrada em: {layer_abs}")
            return False
        if not (layer_abs / "conf" / "layer.conf").exists():
            print(f"❌ '{layer_abs}' não possui conf/layer.conf — não é uma layer Yocto válida.")
            return False

        bblayers_conf = self.workspace.build_dir / "conf" / "bblayers.conf"
        if not bblayers_conf.exists():
            print(f"❌ bblayers.conf não encontrado em {bblayers_conf}")
            return False

        existing = parse_bblayers(bblayers_conf)
        if layer_abs in existing:
            print(f"ℹ️  Layer já está no bblayers.conf: {layer_abs}")
            return True

        bitbake_layers = shutil.which("bitbake-layers")
        if bitbake_layers:
            init_script = self.workspace.init_script.absolute()
            build_dir = self.workspace.build_dir.absolute()
            cmd = f"bash -c 'source {init_script} {build_dir} && bitbake-layers add-layer {layer_abs}'"
            print(f"⚙️  Usando bitbake-layers: add-layer {layer_abs}")
            try:
                res = subprocess.run(cmd, shell=True, text=True, capture_output=True,
                                    cwd=self.workspace.root_dir, timeout=30)
                if res.returncode == 0:
                    print("✅ Layer adicionada com sucesso (via bitbake-layers).")
                    return True
                print(f"⚠️  bitbake-layers falhou ({res.returncode}). Caindo no fallback de edição direta.")
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                print(f"⚠️  bitbake-layers indisponível ({e}). Caindo no fallback de edição direta.")

        content = bblayers_conf.read_text(encoding="utf-8")
        close_idx = content.rfind('"')
        if close_idx == -1:
            with open(bblayers_conf, "a", encoding="utf-8") as f:
                f.write(f"\nBBLAYERS += \"{layer_abs}\"\n")
        else:
            new_content = content[:close_idx] + f"  {layer_abs}\n" + content[close_idx:]
            bblayers_conf.write_text(new_content, encoding="utf-8")
        print(f"✅ Layer adicionada via edição direta de bblayers.conf: {layer_abs}")
        return True
