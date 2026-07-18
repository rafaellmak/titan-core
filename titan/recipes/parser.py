import re
from pathlib import Path
from typing import Dict

def parse_bb_file(filepath: Path) -> Dict[str, str]:
    """Extrai metadados de um arquivo .bb ou .bbappend"""
    
    # Extrai PN e PV do nome do arquivo (ex: bash_5.1.bb -> pn=bash, pv=5.1)
    stem = filepath.stem
    parts = stem.split("_", 1)
    pn = parts[0]
    pv = parts[1] if len(parts) > 1 else "1.0"

    content = filepath.read_text(errors="ignore")
    
    # Resolve line continuations ( \ no final da linha)
    content = re.sub(r"\\\n\s*", " ", content)

    def extract_var(var_name: str) -> str:
        # Busca VAR = "val", VAR += "val", etc.
        match = re.search(rf"^{var_name}\s*[?+:]*=\s*\"([^\"]*)\"", content, re.MULTILINE)
        if match:
            # Limpa múltiplos espaços
            return " ".join(match.group(1).split())
        return ""

    def extract_inherit() -> str:
        matches = re.findall(r"^inherit\s+(.+)$", content, re.MULTILINE)
        return " ".join(" ".join(matches).split())

    return {
        "pn": pn,
        "pv": pv,
        "license": extract_var("LICENSE"),
        "depends": extract_var("DEPENDS"),
        "rdepends": extract_var("RDEPENDS"),
        "src_uri": extract_var("SRC_URI"),
        "inherits": extract_inherit(),
        "file_path": str(filepath.absolute())
    }
