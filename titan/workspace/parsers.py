import re
from pathlib import Path
from typing import List, Dict

def parse_yocto_local_conf(conf_path: Path) -> Dict[str, str]:
    """Extrai variáveis chave do local.conf"""
    keys = ["MACHINE", "DISTRO", "BBMASK", "IMAGE_INSTALL", "IMAGE_FEATURES", "SDKMACHINE", "TCLIBC", "INIT_MANAGER"]
    data = {k: "unknown" for k in keys}
    
    if not conf_path.exists():
        return data
        
    content = conf_path.read_text(errors="ignore")
    
    for key in keys:
        # Captura KEY = "val", KEY ?= "val", KEY += "val"
        match = re.search(rf'^{key}\s*[?+:]*=\s*"([^"]+)"', content, re.MULTILINE)
        if match:
            data[key] = match.group(1)
            
    return data

def parse_bblayers(conf_path: Path) -> List[Path]:
    """Extrai as layers do bblayers.conf. Resolve paths relativos quando o absoluto não existe."""
    layers = []
    if not conf_path.exists():
        return layers

    content = conf_path.read_text(errors="ignore")
    content = re.sub(r'#.*', '', content)
    content = re.sub(r'\\\n', ' ', content)

    match = re.search(r'BBLAYERS\s*[?+:]*=\s*"([^"]+)"', content, re.DOTALL)
    if match:
        paths = match.group(1).split()
        workspace_root = conf_path.parent.parent.parent
        for p in paths:
            raw = Path(p.strip())
            if raw.exists():
                layers.append(raw)
            else:
                rel = (workspace_root / raw.name)
                if rel.exists():
                    layers.append(rel)
                else:
                    layers.append(raw)
    return layers